"""Wake-on-LAN (spec 3.18): the MAC of a host, and the magic packet.

Moonlight's own client has *Wake PC* in a host's context menu but no
command-line action for it (``moonlight --help`` lists ``list``, ``quit``,
``stream`` and ``pair`` only), so the plugin sends the packet itself. The
MAC comes from one of two places, the setting first:

- ``settings.json``'s ``wake_macs`` (``{<host name>: "aa:bb:cc:dd:ee:ff"}``),
  entered on the Host page, for a host whose MAC Moonlight never learned
  (Sunshine on some setups reports none, and the entry is then
  ``@ByteArray()``, empty);
- Moonlight's own host list, ``Moonlight.conf``'s ``[hosts]`` group, where
  every paired host has a ``mac`` alongside its addresses. It is read, never
  written.

Nothing here runs on the gaming PC (hard rule 6) and nothing is written
anywhere: a magic packet is six ``0xff`` bytes and the MAC sixteen times,
sent over UDP to the broadcast address and to each address Moonlight knows
for the host, on the ports the Moonlight client itself uses.
"""

from __future__ import annotations

import os
import re
import socket
from collections.abc import Callable, Iterable
from typing import Any

#: The socket factory ``send_magic_packet`` uses when given no ``sender``;
#: the test seam (``tests/test_wake.py`` swaps a recorder in, so no test
#: ever puts a datagram on the network).
SOCKET: Callable[[int, int], Any] = socket.socket

#: Moonlight's settings file, the Flathub flatpak first (the Deck's), then a
#: native install. Relative to ``$HOME``.
MOONLIGHT_CONF_PATHS = (
    os.path.join(
        ".var",
        "app",
        "com.moonlight_stream.Moonlight",
        "config",
        "Moonlight Game Streaming Project",
        "Moonlight.conf",
    ),
    os.path.join(".config", "Moonlight Game Streaming Project", "Moonlight.conf"),
)

#: The UDP ports a magic packet goes to: the two conventional Wake-on-LAN
#: ports, plus the ports a GameStream / Sunshine host listens on (the
#: Moonlight client sends to these too, so a host that only accepts a magic
#: packet on an open port still wakes).
WAKE_PORTS = (9, 7, 47009, 47998, 47999, 48000, 48002, 48010)

#: The address keys of one ``[hosts]`` entry, in the order they are tried.
_ADDRESS_KEYS = ("localaddress", "remoteaddress", "manualaddress", "ipv6address")

_SIMPLE_ESCAPES = {
    "n": "\n",
    "r": "\r",
    "t": "\t",
    "0": "\0",
    "a": "\a",
    "b": "\b",
    "f": "\f",
    "v": "\v",
}


def parse_mac(text: object) -> str | None:
    """``aa:bb:cc:dd:ee:ff`` for any usual spelling, else ``None``.

    Accepts colons, dashes, dots (``aabb.ccdd.eeff``) or nothing between the
    hex pairs, any case, surrounding whitespace; never a broadcast or
    all-zero address.
    """
    if not isinstance(text, str):
        return None
    digits = re.sub(r"[\s:\-.]", "", text).lower()
    if len(digits) != 12 or not re.fullmatch(r"[0-9a-f]{12}", digits):
        return None
    if digits in ("000000000000", "ffffffffffff"):
        return None
    return ":".join(digits[i : i + 2] for i in range(0, 12, 2))


def mac_bytes(mac: str) -> bytes:
    return bytes.fromhex(mac.replace(":", ""))


def magic_packet(mac: str) -> bytes:
    return b"\xff" * 6 + mac_bytes(mac) * 16


# ---------------------------------------------------------------------------
# Moonlight.conf


def _unescape_ini(value: str) -> str:
    """Undo QSettings' INI escaping of a scalar value."""
    if len(value) >= 2 and value[0] == '"' and value[-1] == '"':
        value = value[1:-1]
    out: list[str] = []
    i = 0
    while i < len(value):
        ch = value[i]
        if ch != "\\" or i + 1 >= len(value):
            out.append(ch)
            i += 1
            continue
        nxt = value[i + 1]
        if nxt == "x":
            match = re.match(r"[0-9a-fA-F]{1,4}", value[i + 2 :])
            if match:
                out.append(chr(int(match.group(0), 16)))
                i += 2 + len(match.group(0))
                continue
        out.append(_SIMPLE_ESCAPES.get(nxt, nxt))
        i += 2
    return "".join(out)


def _byte_array(value: str) -> bytes | None:
    """The bytes of a ``@ByteArray(...)`` value; ``None`` when it is not one.

    QSettings quotes the whole value (``"@ByteArray(,\\xf0]\\xdd\\x13\\xe)"``)
    when a raw byte of the MAC is a character it must protect, such as a
    comma or a bracket, so the quotes come off before the prefix is looked
    for. Found on a device 2026-09-23: a MAC starting ``2c`` (a comma) read
    as unknown until then.
    """
    if len(value) >= 2 and value[0] == '"' and value[-1] == '"':
        value = value[1:-1]
    if not value.startswith("@ByteArray(") or not value.endswith(")"):
        return None
    inner = _unescape_ini(value[len("@ByteArray(") : -1])
    return inner.encode("latin-1", "replace")


def _mac_of(value: str) -> str | None:
    raw = _byte_array(value)
    if raw is None:
        # a plain string, in case a client ever writes it that way
        return parse_mac(_unescape_ini(value))
    if len(raw) == 6:
        return parse_mac(raw.hex())
    return parse_mac(raw.decode("latin-1"))


def moonlight_hosts(path: str) -> list[dict[str, object]]:
    """The ``[hosts]`` entries of ``Moonlight.conf``: ``name``, ``mac``, ``addresses``.

    ``name`` is the host's ``hostname`` (the name ``moonlight list HOST``
    resolves; a ``customname`` is what the client displays, so both are
    kept as ``names``). ``mac`` is normalised or ``None``; ``addresses`` are
    the non-empty ones of ``localaddress`` / ``remoteaddress`` /
    ``manualaddress`` / ``ipv6address``. A missing or unreadable file is
    ``[]``, never an error.
    """
    try:
        with open(path, encoding="utf-8", errors="replace") as handle:
            lines = handle.read().splitlines()
    except OSError:
        return []
    entries: dict[str, dict[str, str]] = {}
    in_hosts = False
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith(("#", ";")):
            continue
        if stripped.startswith("[") and stripped.endswith("]"):
            in_hosts = stripped[1:-1].strip().lower() == "hosts"
            continue
        if not in_hosts or "=" not in stripped:
            continue
        key, _, value = stripped.partition("=")
        key = key.strip()
        if "\\" not in key:
            continue  # `size=N`
        index, _, field_name = key.partition("\\")
        entries.setdefault(index, {})[field_name.strip().lower()] = value.strip()
    hosts: list[dict[str, object]] = []
    for index in sorted(entries, key=lambda i: (len(i), i)):
        fields = entries[index]
        hostname = _unescape_ini(fields.get("hostname", ""))
        custom = _unescape_ini(fields.get("customname", ""))
        names = [n for n in (hostname, custom) if n]
        if not names:
            continue
        addresses = [a for a in (_unescape_ini(fields.get(k, "")) for k in _ADDRESS_KEYS) if a]
        hosts.append(
            {
                "name": names[0],
                "names": names,
                "mac": _mac_of(fields["mac"]) if "mac" in fields else None,
                "addresses": addresses,
            }
        )
    return hosts


def moonlight_entries(home: str) -> list[dict[str, object]]:
    """Every ``Moonlight.conf`` entry under ``home``: the flatpak file's, then the native one's.

    One read of both files; ``find_host`` looks names up in the result, so
    a caller with several names to resolve parses each file once.
    """
    entries: list[dict[str, object]] = []
    for relative in MOONLIGHT_CONF_PATHS:
        entries.extend(moonlight_hosts(os.path.join(home, relative)))
    return entries


def find_host(entries: list[dict[str, object]], name: str) -> dict[str, object] | None:
    """The first entry named ``name`` (``hostname`` or ``customname``), any case."""
    wanted = name.lower()
    for entry in entries:
        names = entry["names"]
        assert isinstance(names, list)
        if any(n.lower() == wanted for n in names):
            return entry
    return None


def moonlight_host(home: str, name: str) -> dict[str, object] | None:
    """The first ``Moonlight.conf`` entry (flatpak, then native) named ``name``, any case."""
    return find_host(moonlight_entries(home), name)


# ---------------------------------------------------------------------------
# the packet


def send_magic_packet(
    mac: str,
    addresses: Iterable[str] = (),
    ports: Iterable[int] = WAKE_PORTS,
    *,
    sender: Callable[[int, int], Any] | None = None,
) -> tuple[int, list[str]]:
    """Send the packet to the broadcast address and every ``addresses`` entry.

    Returns ``(sent, errors)``: how many datagrams went out and one line per
    destination that failed. Only when nothing at all could be sent should
    the caller fail; a directed send to an address that is no longer routed
    is expected.
    """
    packet = magic_packet(mac)
    factory = sender if sender is not None else SOCKET
    ports = tuple(ports)
    sent = 0
    errors: list[str] = []
    targets: list[str] = ["255.255.255.255", *dict.fromkeys(a for a in addresses if a)]
    for target in targets:
        family = socket.AF_INET6 if ":" in target else socket.AF_INET
        try:
            with factory(family, socket.SOCK_DGRAM) as sock:
                if family == socket.AF_INET:
                    sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
                for port in ports:
                    sock.sendto(packet, (target, port))
                    sent += 1
        except OSError as exc:
            errors.append(f"{target}: {exc}")
    return sent, errors
