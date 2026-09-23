"""A Chrome DevTools Protocol client for Steam's CEF remote debugger (spec 3.20.2).

Decky Loader writes ``~/.steam/steam/.cef-enable-remote-debugging`` and Steam
then answers ``GET http://127.0.0.1:8080/json/list`` with every browser
target (the plugin's own ``SharedJSContext``, Big Picture, the popups, and
the Game Mode browser once it is open). Each target carries a
``webSocketDebuggerUrl``; a websocket to it speaks CDP, and
``Runtime.evaluate`` runs JavaScript in that page.

This is the one module that talks to the port; every other module goes
through it. Standard library only (``socket``, ``struct``, ``base64``,
``json``, ``urllib``), like the probe that measured the flow on the Deck,
so it depends on nothing of Decky's beyond the port. Blocking sockets, run
through ``asyncio.to_thread`` like ``wake.py``'s sender. Every call has a
socket timeout: nothing here blocks longer than its ``timeout``.

The seams: :data:`CONNECT` and :data:`TARGETS` are module attributes the
tests replace (a scripted fake session answering by snippet), as
``wake.SOCKET`` is; no test opens a socket to the debugger.
"""

from __future__ import annotations

import base64
import contextlib
import hashlib
import json
import os
import socket
import struct
import time
import urllib.parse
import urllib.request
from collections.abc import Callable
from typing import Any, TypedDict

#: Where Steam's debugger listens (the port Decky Loader itself injects through).
DEBUGGER = ("127.0.0.1", 8080)
#: The timeout of the one ``/json/list`` request.
HTTP_TIMEOUT_S = 5.0
#: The default timeout of a websocket connect and of one ``evaluate``.
EVALUATE_TIMEOUT_S = 10.0

_WS_GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"
_OP_CONTINUATION = 0x0
_OP_TEXT = 0x1
_OP_BINARY = 0x2
_OP_CLOSE = 0x8
_OP_PING = 0x9
_OP_PONG = 0xA
_MAX_FRAME = 64 * 1024 * 1024


class DebuggerUnavailable(ConnectionError):
    """The debugger could not be reached, or a session with it broke.

    Raised for a refused connection, a timeout, a non-JSON ``/json/list``
    body, a closed websocket and a CDP-level ``error`` reply (``Execution
    context was destroyed`` while the page navigates, ``Target closed``):
    conditions of the connection, not of the page, which a caller polling
    the browser retries.
    """


class EvaluateError(RuntimeError):
    """The JavaScript threw: ``description`` is the exception's own text."""

    def __init__(self, description: str) -> None:
        super().__init__(description)
        self.description = description


class Target(TypedDict):
    """One entry of ``/json/list``, the fields the plugin reads."""

    id: str
    type: str
    title: str
    url: str
    webSocketDebuggerUrl: str


def targets(http: Callable[..., Any] = urllib.request.urlopen) -> list[Target]:
    """One GET of ``/json/list``: every browser target, as :class:`Target`.

    ``http`` is ``urllib.request.urlopen``'s shape (a context manager whose
    ``read()`` is the body), replaced in tests. A refused connection, a
    timeout or a body that is not a JSON list is :class:`DebuggerUnavailable`.
    """
    url = f"http://{DEBUGGER[0]}:{DEBUGGER[1]}/json/list"
    try:
        with http(url, timeout=HTTP_TIMEOUT_S) as response:
            body = response.read()
    except OSError as exc:  # URLError, socket.timeout, ConnectionRefusedError
        raise DebuggerUnavailable(f"{url}: {exc}") from exc
    try:
        entries = json.loads(body)
    except (ValueError, UnicodeDecodeError) as exc:
        raise DebuggerUnavailable(f"{url}: not JSON ({exc})") from exc
    if not isinstance(entries, list):
        raise DebuggerUnavailable(f"{url}: not a list")
    result: list[Target] = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        result.append(
            Target(
                id=str(entry.get("id", "")),
                type=str(entry.get("type", "")),
                title=str(entry.get("title", "")),
                url=str(entry.get("url", "")),
                webSocketDebuggerUrl=str(entry.get("webSocketDebuggerUrl", "")),
            )
        )
    return result


class Session:
    """A websocket to one target's ``webSocketDebuggerUrl``.

    The handshake, client-side masking, the three payload-length forms,
    fragmented replies, ``ping`` (answered with ``pong``) and ``close``
    (answered, then :class:`DebuggerUnavailable`): what the probe's ``Ws``
    did. Only :meth:`evaluate` and :meth:`close` are the interface.
    """

    def __init__(self, url: str, *, timeout: float = EVALUATE_TIMEOUT_S) -> None:
        parts = urllib.parse.urlsplit(url)
        if parts.scheme != "ws" or not parts.hostname:
            raise DebuggerUnavailable(f"not a ws:// url: {url}")
        host = parts.hostname
        port = parts.port or 80
        path = parts.path or "/"
        if parts.query:
            path += "?" + parts.query
        self.url = url
        self._buffer = b""
        self._next_id = 0
        self._closed = False
        try:
            self._sock = socket.create_connection((host, port), timeout=timeout)
        except OSError as exc:
            raise DebuggerUnavailable(f"{url}: {exc}") from exc
        try:
            self._handshake(host, port, path, time.monotonic() + timeout)
        except BaseException:
            self._sock.close()
            raise

    # -- the handshake ---------------------------------------------------

    def _handshake(self, host: str, port: int, path: str, deadline: float) -> None:
        key = base64.b64encode(os.urandom(16)).decode("ascii")
        request = (
            f"GET {path} HTTP/1.1\r\n"
            f"Host: {host}:{port}\r\n"
            "Upgrade: websocket\r\n"
            "Connection: Upgrade\r\n"
            f"Sec-WebSocket-Key: {key}\r\n"
            "Sec-WebSocket-Version: 13\r\n"
            "\r\n"
        ).encode("ascii")
        self._send_all(request, deadline)
        while b"\r\n\r\n" not in self._buffer:
            self._fill(deadline)
        head, _, self._buffer = self._buffer.partition(b"\r\n\r\n")
        lines = head.decode("iso-8859-1").split("\r\n")
        status = lines[0].split(" ", 2)
        if len(status) < 2 or status[1] != "101":
            raise DebuggerUnavailable(f"{self.url}: handshake refused: {lines[0]}")
        headers = {}
        for line in lines[1:]:
            name, _, value = line.partition(":")
            headers[name.strip().lower()] = value.strip()
        expected = base64.b64encode(hashlib.sha1((key + _WS_GUID).encode("ascii")).digest())
        if headers.get("sec-websocket-accept", "").encode("ascii") != expected:
            raise DebuggerUnavailable(f"{self.url}: handshake accept mismatch")

    # -- bytes -----------------------------------------------------------

    def _remaining(self, deadline: float) -> float:
        left = deadline - time.monotonic()
        if left <= 0:
            raise DebuggerUnavailable(f"{self.url}: timed out")
        return left

    def _fill(self, deadline: float) -> None:
        self._sock.settimeout(self._remaining(deadline))
        try:
            chunk = self._sock.recv(65536)
        except TimeoutError as exc:
            raise DebuggerUnavailable(f"{self.url}: timed out") from exc
        except OSError as exc:
            raise DebuggerUnavailable(f"{self.url}: {exc}") from exc
        if not chunk:
            self._closed = True
            raise DebuggerUnavailable(f"{self.url}: connection closed")
        self._buffer += chunk

    def _read_exact(self, n: int, deadline: float) -> bytes:
        while len(self._buffer) < n:
            self._fill(deadline)
        data, self._buffer = self._buffer[:n], self._buffer[n:]
        return data

    def _send_all(self, data: bytes, deadline: float) -> None:
        self._sock.settimeout(self._remaining(deadline))
        try:
            self._sock.sendall(data)
        except TimeoutError as exc:
            raise DebuggerUnavailable(f"{self.url}: timed out") from exc
        except OSError as exc:
            raise DebuggerUnavailable(f"{self.url}: {exc}") from exc

    # -- frames ----------------------------------------------------------

    def _send_frame(self, opcode: int, payload: bytes, deadline: float) -> None:
        head = bytes([0x80 | opcode])
        length = len(payload)
        if length < 126:
            head += bytes([0x80 | length])
        elif length < 65536:
            head += bytes([0x80 | 126]) + struct.pack("!H", length)
        else:
            head += bytes([0x80 | 127]) + struct.pack("!Q", length)
        mask = os.urandom(4)
        masked = bytes(b ^ mask[i % 4] for i, b in enumerate(payload))
        self._send_all(head + mask + masked, deadline)

    def _recv_frame(self, deadline: float) -> tuple[bool, int, bytes]:
        first, second = self._read_exact(2, deadline)
        fin = bool(first & 0x80)
        opcode = first & 0x0F
        masked = bool(second & 0x80)
        length = second & 0x7F
        if length == 126:
            (length,) = struct.unpack("!H", self._read_exact(2, deadline))
        elif length == 127:
            (length,) = struct.unpack("!Q", self._read_exact(8, deadline))
        if length > _MAX_FRAME:
            raise DebuggerUnavailable(f"{self.url}: frame of {length} bytes")
        mask = self._read_exact(4, deadline) if masked else b""
        payload = self._read_exact(length, deadline)
        if masked:
            payload = bytes(b ^ mask[i % 4] for i, b in enumerate(payload))
        return fin, opcode, payload

    def _recv_message(self, deadline: float) -> bytes:
        """The next complete text message; control frames handled on the way."""
        parts: list[bytes] = []
        while True:
            fin, opcode, payload = self._recv_frame(deadline)
            if opcode == _OP_PING:
                self._send_frame(_OP_PONG, payload, deadline)
                continue
            if opcode == _OP_PONG:
                continue
            if opcode == _OP_CLOSE:
                with contextlib.suppress(DebuggerUnavailable):
                    self._send_frame(_OP_CLOSE, payload[:2], deadline)
                self._closed = True
                raise DebuggerUnavailable(f"{self.url}: closed by the debugger")
            if opcode in (_OP_TEXT, _OP_BINARY, _OP_CONTINUATION):
                parts.append(payload)
                if fin:
                    return b"".join(parts)
                continue
            raise DebuggerUnavailable(f"{self.url}: unknown opcode {opcode}")

    # -- the interface ---------------------------------------------------

    def evaluate(self, js: str, *, timeout: float = EVALUATE_TIMEOUT_S) -> Any:
        """``Runtime.evaluate`` ``js`` in the page and return its value.

        ``returnByValue`` and ``awaitPromise`` are set, so the value is
        JSON (``None`` for ``undefined`` / ``null``). A thrown exception is
        :class:`EvaluateError`; a CDP ``error`` reply, a timeout and a closed
        socket are :class:`DebuggerUnavailable`. Events the debugger sends
        meanwhile are skipped.
        """
        if self._closed:
            raise DebuggerUnavailable(f"{self.url}: session closed")
        deadline = time.monotonic() + timeout
        self._next_id += 1
        call_id = self._next_id
        request = {
            "id": call_id,
            "method": "Runtime.evaluate",
            "params": {"expression": js, "returnByValue": True, "awaitPromise": True},
        }
        self._send_frame(_OP_TEXT, json.dumps(request).encode("utf-8"), deadline)
        while True:
            raw = self._recv_message(deadline)
            try:
                message = json.loads(raw)
            except (ValueError, UnicodeDecodeError) as exc:
                raise DebuggerUnavailable(f"{self.url}: not JSON ({exc})") from exc
            if not isinstance(message, dict) or message.get("id") != call_id:
                continue
            error = message.get("error")
            if isinstance(error, dict):
                raise DebuggerUnavailable(f"{self.url}: {error.get('message', error)}")
            result = message.get("result")
            if not isinstance(result, dict):
                raise DebuggerUnavailable(f"{self.url}: reply without a result")
            details = result.get("exceptionDetails")
            if isinstance(details, dict):
                exception = details.get("exception")
                description = (
                    exception.get("description") if isinstance(exception, dict) else None
                ) or details.get("text", "exception")
                raise EvaluateError(str(description))
            value = result.get("result")
            return value.get("value") if isinstance(value, dict) else None

    def close(self) -> None:
        """Send a close frame (best effort) and close the socket."""
        if not self._closed:
            self._closed = True
            with contextlib.suppress(DebuggerUnavailable, OSError):
                self._send_frame(_OP_CLOSE, struct.pack("!H", 1000), time.monotonic() + 1.0)
        with contextlib.suppress(OSError):
            self._sock.close()


#: The seams: ``sgdbpage.fetch_key`` gets these two, and the tests replace
#: them with a fake target list and a scripted session.
CONNECT: Callable[[str], Session] = Session
TARGETS: Callable[[], list[Target]] = targets
