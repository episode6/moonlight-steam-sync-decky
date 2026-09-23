"""The debugger client (spec 3.20.2): ``targets()`` over a stubbed ``http``,
and ``Session``'s websocket framing against a loopback fake server in a
thread (the handshake, the three payload-length forms, client masking, a
fragmented reply, a ping, a close), ``DebuggerUnavailable`` on refusal."""

from __future__ import annotations

import base64
import hashlib
import io
import json
import socket
import struct
import threading
import urllib.error
from collections.abc import Callable
from typing import Any

import pytest

from moonlight_sync import cdp

WS_GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"


# ---------------------------------------------------------------------------
# targets()


class FakeResponse(io.BytesIO):
    def __enter__(self) -> FakeResponse:
        return self

    def __exit__(self, *args: Any) -> None:
        self.close()


def http_answering(body: bytes) -> Callable[..., Any]:
    calls: list[tuple[str, float]] = []

    def http(url: str, timeout: float) -> FakeResponse:
        calls.append((url, timeout))
        return FakeResponse(body)

    http.calls = calls  # type: ignore[attr-defined]
    return http


def test_targets_reads_json_list() -> None:
    body = json.dumps(
        [
            {
                "id": "A",
                "type": "page",
                "title": "SharedJSContext",
                "url": "https://steamloopback.host/routes/externalweb",
                "webSocketDebuggerUrl": "ws://127.0.0.1:8080/devtools/page/A",
                "devtoolsFrontendUrl": "/devtools/inspector.html?ws=...",
            },
            {"id": "B", "type": "iframe", "title": "ad", "url": "https://ads.example.invalid/"},
            "not an object",
        ]
    ).encode()
    http = http_answering(body)
    listed = cdp.targets(http)
    assert http.calls == [("http://127.0.0.1:8080/json/list", cdp.HTTP_TIMEOUT_S)]
    assert listed == [
        {
            "id": "A",
            "type": "page",
            "title": "SharedJSContext",
            "url": "https://steamloopback.host/routes/externalweb",
            "webSocketDebuggerUrl": "ws://127.0.0.1:8080/devtools/page/A",
        },
        {
            "id": "B",
            "type": "iframe",
            "title": "ad",
            "url": "https://ads.example.invalid/",
            "webSocketDebuggerUrl": "",
        },
    ]


def test_targets_unavailable_on_refusal_timeout_and_non_json() -> None:
    def refused(url: str, timeout: float) -> Any:
        raise urllib.error.URLError(ConnectionRefusedError(111, "Connection refused"))

    def timed_out(url: str, timeout: float) -> Any:
        raise TimeoutError("timed out")

    for http in (refused, timed_out, http_answering(b"<html>not json"), http_answering(b"{}")):
        with pytest.raises(cdp.DebuggerUnavailable):
            cdp.targets(http)
    assert issubclass(cdp.DebuggerUnavailable, ConnectionError)


def test_targets_default_http_against_a_closed_port(monkeypatch: pytest.MonkeyPatch) -> None:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    monkeypatch.setattr(cdp, "DEBUGGER", ("127.0.0.1", port))
    with pytest.raises(cdp.DebuggerUnavailable):
        cdp.targets()


# ---------------------------------------------------------------------------
# a loopback websocket server


def read_frame(conn: socket.socket) -> tuple[bool, int, bool, bytes]:
    """``(fin, opcode, masked, payload)`` of one client frame."""
    head = recv_exact(conn, 2)
    fin = bool(head[0] & 0x80)
    opcode = head[0] & 0x0F
    masked = bool(head[1] & 0x80)
    length = head[1] & 0x7F
    if length == 126:
        (length,) = struct.unpack("!H", recv_exact(conn, 2))
    elif length == 127:
        (length,) = struct.unpack("!Q", recv_exact(conn, 8))
    mask = recv_exact(conn, 4) if masked else b""
    payload = recv_exact(conn, length)
    if masked:
        payload = bytes(b ^ mask[i % 4] for i, b in enumerate(payload))
    return fin, opcode, masked, payload


def recv_exact(conn: socket.socket, n: int) -> bytes:
    data = b""
    while len(data) < n:
        chunk = conn.recv(n - len(data))
        if not chunk:
            raise ConnectionError("client closed")
        data += chunk
    return data


def frame(opcode: int, payload: bytes, fin: bool = True) -> bytes:
    head = bytes([(0x80 if fin else 0) | opcode])
    length = len(payload)
    if length < 126:
        head += bytes([length])
    elif length < 65536:
        head += bytes([126]) + struct.pack("!H", length)
    else:
        head += bytes([127]) + struct.pack("!Q", length)
    return head + payload


class FakeDebugger:
    """One websocket target; ``script`` answers each client text message."""

    def __init__(self, script: Callable[[FakeDebugger, socket.socket, dict[str, Any]], bool]):
        self.script = script
        self.server = socket.socket()
        self.server.bind(("127.0.0.1", 0))
        self.server.listen(1)
        self.server.settimeout(5)
        self.port = self.server.getsockname()[1]
        self.requests: list[dict[str, Any]] = []
        self.frames: list[tuple[bool, int, bool, bytes]] = []
        self.request_head = ""
        self.error: BaseException | None = None
        self.thread = threading.Thread(target=self.serve, daemon=True)
        self.thread.start()

    @property
    def url(self) -> str:
        return f"ws://127.0.0.1:{self.port}/devtools/page/T"

    def serve(self) -> None:
        try:
            conn, _ = self.server.accept()
            conn.settimeout(5)
            with conn:
                head = b""
                while b"\r\n\r\n" not in head:
                    head += conn.recv(4096)
                self.request_head = head.decode()
                key = ""
                for line in self.request_head.split("\r\n"):
                    if line.lower().startswith("sec-websocket-key:"):
                        key = line.split(":", 1)[1].strip()
                accept = base64.b64encode(hashlib.sha1((key + WS_GUID).encode()).digest()).decode()
                conn.sendall(
                    (
                        "HTTP/1.1 101 Switching Protocols\r\n"
                        "Upgrade: websocket\r\n"
                        "Connection: Upgrade\r\n"
                        f"Sec-WebSocket-Accept: {accept}\r\n\r\n"
                    ).encode()
                )
                while True:
                    fin, opcode, masked, payload = read_frame(conn)
                    self.frames.append((fin, opcode, masked, payload))
                    if opcode == 0x8:
                        conn.sendall(frame(0x8, payload[:2]))
                        return
                    if opcode == 0xA:
                        continue  # a pong
                    message = json.loads(payload)
                    self.requests.append(message)
                    if not self.script(self, conn, message):
                        return
        except BaseException as exc:  # reported by the test, not swallowed
            self.error = exc

    def close(self) -> None:
        self.server.close()
        self.thread.join(timeout=5)


def reply(conn: socket.socket, call_id: int, value: Any) -> None:
    conn.sendall(
        frame(
            0x1,
            json.dumps(
                {"id": call_id, "result": {"result": {"type": "x", "value": value}}}
            ).encode(),
        )
    )


@pytest.fixture
def debugger():
    servers: list[FakeDebugger] = []

    def start(script: Callable[..., bool]) -> FakeDebugger:
        server = FakeDebugger(script)
        servers.append(server)
        return server

    yield start
    for server in servers:
        server.close()


def test_handshake_and_a_short_masked_evaluate(debugger) -> None:
    def script(server: FakeDebugger, conn: socket.socket, message: dict[str, Any]) -> bool:
        reply(conn, message["id"], {"href": "https://example/", "ready": "complete"})
        return True

    server = debugger(script)
    session = cdp.Session(server.url)
    value = session.evaluate("({href: location.href})")
    session.close()
    server.close()
    assert server.error is None
    assert value == {"href": "https://example/", "ready": "complete"}
    assert server.request_head.startswith("GET /devtools/page/T HTTP/1.1\r\n")
    assert "Upgrade: websocket" in server.request_head
    assert "Sec-WebSocket-Version: 13" in server.request_head
    assert server.requests == [
        {
            "id": 1,
            "method": "Runtime.evaluate",
            "params": {
                "expression": "({href: location.href})",
                "returnByValue": True,
                "awaitPromise": True,
            },
        }
    ]
    fin, opcode, masked, _ = server.frames[0]
    assert (fin, opcode, masked) == (True, 0x1, True)  # the client masks
    assert server.frames[-1][1] == 0x8  # close() sent a close frame


@pytest.mark.parametrize("size", [100, 126, 65535, 65536, 200_000])
def test_payload_lengths_in_both_directions(debugger, size: int) -> None:
    big = "x" * size

    def script(server: FakeDebugger, conn: socket.socket, message: dict[str, Any]) -> bool:
        reply(conn, message["id"], message["params"]["expression"])
        return True

    server = debugger(script)
    session = cdp.Session(server.url)
    assert session.evaluate(big) == big
    session.close()
    server.close()
    assert server.error is None


def test_a_fragmented_reply_and_events_on_the_way(debugger) -> None:
    def script(server: FakeDebugger, conn: socket.socket, message: dict[str, Any]) -> bool:
        event = json.dumps({"method": "Runtime.consoleAPICalled", "params": {}}).encode()
        conn.sendall(frame(0x1, event))
        body = json.dumps({"id": message["id"], "result": {"result": {"value": "abc"}}}).encode()
        conn.sendall(frame(0x1, body[:10], fin=False))
        conn.sendall(frame(0x0, body[10:20], fin=False))
        conn.sendall(frame(0x0, body[20:], fin=True))
        return True

    server = debugger(script)
    session = cdp.Session(server.url)
    assert session.evaluate("x") == "abc"
    session.close()
    server.close()
    assert server.error is None


def test_a_ping_is_answered_with_a_pong(debugger) -> None:
    def script(server: FakeDebugger, conn: socket.socket, message: dict[str, Any]) -> bool:
        conn.sendall(frame(0x9, b"hello"))
        # the pong must arrive before the reply is sent
        fin, opcode, masked, payload = read_frame(conn)
        server.frames.append((fin, opcode, masked, payload))
        assert (opcode, masked, payload) == (0xA, True, b"hello")
        reply(conn, message["id"], 1)
        return True

    server = debugger(script)
    session = cdp.Session(server.url)
    assert session.evaluate("1") == 1
    session.close()
    server.close()
    assert server.error is None


def test_a_close_from_the_debugger_is_unavailable(debugger) -> None:
    def script(server: FakeDebugger, conn: socket.socket, message: dict[str, Any]) -> bool:
        conn.sendall(frame(0x8, struct.pack("!H", 1001)))
        read_frame(conn)  # the client's close reply
        return False

    server = debugger(script)
    session = cdp.Session(server.url)
    with pytest.raises(cdp.DebuggerUnavailable, match="closed"):
        session.evaluate("1")
    with pytest.raises(cdp.DebuggerUnavailable):
        session.evaluate("1")  # a closed session stays closed
    session.close()
    server.close()
    assert server.error is None


def test_an_exception_in_the_page_is_evaluate_error(debugger) -> None:
    def script(server: FakeDebugger, conn: socket.socket, message: dict[str, Any]) -> bool:
        body = {
            "id": message["id"],
            "result": {
                "result": {"type": "object", "subtype": "error"},
                "exceptionDetails": {
                    "text": "Uncaught",
                    "exception": {"description": "TypeError: Cannot read properties of null"},
                },
            },
        }
        conn.sendall(frame(0x1, json.dumps(body).encode()))
        return True

    server = debugger(script)
    session = cdp.Session(server.url)
    with pytest.raises(cdp.EvaluateError) as info:
        session.evaluate("null.x")
    assert info.value.description == "TypeError: Cannot read properties of null"
    session.close()
    server.close()
    assert server.error is None


def test_a_protocol_error_reply_is_unavailable(debugger) -> None:
    """A CDP-level error (the context destroyed by a navigation) is the
    session's condition, retried by the fetch, not a page change."""

    def script(server: FakeDebugger, conn: socket.socket, message: dict[str, Any]) -> bool:
        body = {
            "id": message["id"],
            "error": {"code": -32000, "message": "Execution context was destroyed."},
        }
        conn.sendall(frame(0x1, json.dumps(body).encode()))
        return True

    server = debugger(script)
    session = cdp.Session(server.url)
    with pytest.raises(cdp.DebuggerUnavailable, match="destroyed"):
        session.evaluate("1")
    session.close()
    server.close()


def test_evaluate_times_out(debugger) -> None:
    def script(server: FakeDebugger, conn: socket.socket, message: dict[str, Any]) -> bool:
        read_frame(conn)  # wait for the client's close instead of answering
        return False

    server = debugger(script)
    session = cdp.Session(server.url)
    with pytest.raises(cdp.DebuggerUnavailable, match="timed out"):
        session.evaluate("1", timeout=0.2)
    session.close()
    server.close()


def test_a_refused_websocket_is_unavailable() -> None:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    with pytest.raises(cdp.DebuggerUnavailable):
        cdp.Session(f"ws://127.0.0.1:{port}/devtools/page/T", timeout=1)
    with pytest.raises(cdp.DebuggerUnavailable):
        cdp.Session("http://127.0.0.1:1/x")


def test_a_bad_handshake_is_unavailable() -> None:
    server = socket.socket()
    server.bind(("127.0.0.1", 0))
    server.listen(1)
    server.settimeout(5)

    def serve() -> None:
        conn, _ = server.accept()
        with conn:
            conn.recv(4096)
            conn.sendall(b"HTTP/1.1 500 Internal Server Error\r\n\r\n")

    thread = threading.Thread(target=serve, daemon=True)
    thread.start()
    try:
        with pytest.raises(cdp.DebuggerUnavailable, match="handshake"):
            cdp.Session(f"ws://127.0.0.1:{server.getsockname()[1]}/x", timeout=2)
    finally:
        thread.join(timeout=5)
        server.close()


def test_the_seams_are_the_real_client() -> None:
    assert cdp.CONNECT is cdp.Session
    assert cdp.TARGETS is cdp.targets
