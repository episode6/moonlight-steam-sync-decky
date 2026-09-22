"""Wake-on-LAN (spec 3.18): the MAC sources, the packet, ``wake_host`` and ``set_wake_mac``."""

from __future__ import annotations

import json
import socket
from pathlib import Path
from typing import Any

import pytest

from conftest import run
from moonlight_sync import wake

MAC = "aa:bb:cc:dd:ee:0f"

#: A Moonlight.conf as the flatpak client writes it (QSettings INI): one host
#: with a 6-byte ``@ByteArray`` MAC and its addresses, one with an empty MAC
#: (what a Sunshine host that reports none leaves), one with a customname.
MOONLIGHT_CONF = """[General]
autoupdate=true

[gcmapping]
size=0

[hosts]
1\\customname=
1\\hostname=MY-GAMING-PC
1\\ipv6address=
1\\ipv6port=0
1\\localaddress=192.168.1.20
1\\localport=47989
1\\mac=@ByteArray(\\xaa\\xbb\\xcc\\xdd\\xee\\xf)
1\\manualaddress=
1\\manualport=0
1\\remoteaddress=203.0.113.9
1\\remoteport=47989
1\\uuid=8706E5C7-23D3-0628-3017-83EA557C64C8
2\\customname=
2\\hostname=OFFICE-PC
2\\localaddress=192.168.1.30
2\\mac=@ByteArray()
2\\uuid=11111111-2222-3333-4444-555555555555
3\\customname=Den
3\\hostname=LIVING-ROOM-PC
3\\localaddress=
3\\mac=@ByteArray(\\x1\\x2\\x3\\x4\\x5\\x6)
3\\uuid=66666666-7777-8888-9999-000000000000
size=3
"""


def write_moonlight_conf(home: Path, text: str = MOONLIGHT_CONF, *, native: bool = False) -> Path:
    relative = wake.MOONLIGHT_CONF_PATHS[1 if native else 0]
    path = home / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


# ---------------------------------------------------------------------------
# the pure half


def test_parse_mac_accepts_the_usual_spellings() -> None:
    for text in (
        "AA:BB:CC:DD:EE:0F",
        "aa-bb-cc-dd-ee-0f",
        "aabb.ccdd.ee0f",
        "AABBCCDDEE0F",
        " aa:bb:cc:dd:ee:0f\n",
    ):
        assert wake.parse_mac(text) == MAC, text
    for bad in (
        "",
        "aa:bb:cc:dd:ee",
        "aa:bb:cc:dd:ee:0f:00",
        "zz:bb:cc:dd:ee:0f",
        "00:00:00:00:00:00",
        "ff:ff:ff:ff:ff:ff",
        None,
        12,
    ):
        assert wake.parse_mac(bad) is None, bad


def test_magic_packet_is_six_ff_then_the_mac_sixteen_times() -> None:
    packet = wake.magic_packet(MAC)
    assert len(packet) == 102
    assert packet[:6] == b"\xff" * 6
    assert packet[6:] == bytes.fromhex("aabbccddee0f") * 16


def test_moonlight_hosts_reads_the_hosts_group(tmp_path: Path) -> None:
    path = write_moonlight_conf(tmp_path)
    hosts = wake.moonlight_hosts(str(path))
    assert [h["name"] for h in hosts] == ["MY-GAMING-PC", "OFFICE-PC", "LIVING-ROOM-PC"]
    assert hosts[0]["mac"] == MAC
    assert hosts[0]["addresses"] == ["192.168.1.20", "203.0.113.9"]
    # an empty @ByteArray() is no MAC
    assert hosts[1]["mac"] is None
    assert hosts[1]["addresses"] == ["192.168.1.30"]
    # single-digit escapes, and the customname is a second name
    assert hosts[2]["mac"] == "01:02:03:04:05:06"
    assert hosts[2]["names"] == ["LIVING-ROOM-PC", "Den"]
    assert hosts[2]["addresses"] == []


def test_moonlight_hosts_tolerates_a_missing_or_odd_file(tmp_path: Path) -> None:
    assert wake.moonlight_hosts(str(tmp_path / "nope")) == []
    odd = tmp_path / "odd.conf"
    odd.write_text(
        '[hosts]\nsize=1\n1\\hostname=X\n1\\mac="aa:bb:cc:dd:ee:0f"\n[other]\n1\\mac=ff\n'
    )
    hosts = wake.moonlight_hosts(str(odd))
    assert hosts == [{"name": "X", "names": ["X"], "mac": MAC, "addresses": []}]
    empty = tmp_path / "empty.conf"
    empty.write_text("")
    assert wake.moonlight_hosts(str(empty)) == []


def test_moonlight_host_prefers_the_flatpak_file_and_ignores_case(tmp_path: Path) -> None:
    write_moonlight_conf(tmp_path, native=True)
    assert wake.moonlight_host(str(tmp_path), "my-gaming-pc")["mac"] == MAC  # type: ignore[index]
    write_moonlight_conf(tmp_path, MOONLIGHT_CONF.replace("\\xaa\\xbb", "\\x11\\x22"))
    assert wake.moonlight_host(str(tmp_path), "MY-GAMING-PC")["mac"] == "11:22:cc:dd:ee:0f"  # type: ignore[index]
    # the customname finds it too
    assert wake.moonlight_host(str(tmp_path), "den")["name"] == "LIVING-ROOM-PC"  # type: ignore[index]
    assert wake.moonlight_host(str(tmp_path), "NOWHERE") is None


class FakeSocket:
    """A ``socket.socket`` stand-in recording every datagram; ``failing`` targets raise."""

    sent: list[tuple[str, int, bytes]] = []
    failing: set[str] = set()
    options: list[tuple[int, int, int]] = []

    def __init__(self, family: int, kind: int) -> None:
        self.family = family
        assert kind == socket.SOCK_DGRAM

    def __enter__(self) -> FakeSocket:
        return self

    def __exit__(self, *exc: object) -> None:
        pass

    def setsockopt(self, level: int, option: int, value: int) -> None:
        FakeSocket.options.append((level, option, value))

    def sendto(self, data: bytes, address: tuple[str, int]) -> int:
        host, port = address
        if host in FakeSocket.failing:
            raise OSError(101, "Network is unreachable")
        FakeSocket.sent.append((host, port, data))
        return len(data)


@pytest.fixture
def fake_socket(monkeypatch: pytest.MonkeyPatch) -> type[FakeSocket]:
    FakeSocket.sent = []
    FakeSocket.failing = set()
    FakeSocket.options = []
    monkeypatch.setattr(wake, "SOCKET", FakeSocket)
    return FakeSocket


def test_send_magic_packet_broadcasts_and_directs(fake_socket: type[FakeSocket]) -> None:
    sent, errors = wake.send_magic_packet(
        MAC, ["192.168.1.20", "", "192.168.1.20", "2001:db8::1"], (9, 7)
    )
    assert errors == []
    assert sent == 6
    targets = [(host, port) for host, port, _ in fake_socket.sent]
    assert targets == [
        ("255.255.255.255", 9),
        ("255.255.255.255", 7),
        ("192.168.1.20", 9),
        ("192.168.1.20", 7),
        ("2001:db8::1", 9),
        ("2001:db8::1", 7),
    ]
    assert {data for _, _, data in fake_socket.sent} == {wake.magic_packet(MAC)}
    # SO_BROADCAST on the two IPv4 sockets only
    assert fake_socket.options == [(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)] * 2


def test_send_magic_packet_counts_what_went_out(fake_socket: type[FakeSocket]) -> None:
    fake_socket.failing = {"203.0.113.9"}
    sent, errors = wake.send_magic_packet(MAC, ["203.0.113.9"], (9,))
    assert sent == 1
    assert errors == ["203.0.113.9: [Errno 101] Network is unreachable"]
    fake_socket.failing = {"255.255.255.255", "203.0.113.9"}
    assert wake.send_magic_packet(MAC, ["203.0.113.9"], (9,))[0] == 0


def test_default_ports_are_the_conventional_and_the_gamestream_ones() -> None:
    assert wake.WAKE_PORTS[:2] == (9, 7)
    assert 47009 in wake.WAKE_PORTS


# ---------------------------------------------------------------------------
# the callables


def home_of(backend: Any) -> Path:
    return Path(backend.home)


def test_hosts_carries_wake_info_per_known_host(backend, fake_socket: type[FakeSocket]) -> None:
    assert run(backend.hosts())["wake"] == {}
    write_moonlight_conf(home_of(backend))
    shown = run(backend.hosts())
    assert shown["known"] == ["MY-GAMING-PC", "OFFICE-PC"]
    assert shown["wake"] == {
        "MY-GAMING-PC": {
            "mac": MAC,
            "source": "moonlight",
            "addresses": ["192.168.1.20", "203.0.113.9"],
        }
    }


def test_wake_host_sends_to_broadcast_and_every_known_address(
    backend, fake_socket: type[FakeSocket]
) -> None:
    write_moonlight_conf(home_of(backend))
    result = run(backend.wake_host("my-gaming-pc"))
    assert result == {
        "ok": True,
        "host": "my-gaming-pc",
        "mac": MAC,
        "source": "moonlight",
        "sent": 3 * len(wake.WAKE_PORTS),
    }
    hosts = {host for host, _, _ in fake_socket.sent}
    assert hosts == {"255.255.255.255", "192.168.1.20", "203.0.113.9"}
    assert all(data == wake.magic_packet(MAC) for _, _, data in fake_socket.sent)
    log = Path(backend.log_path).read_text()
    assert f"wake_host my-gaming-pc: {3 * len(wake.WAKE_PORTS)} packets sent (moonlight MAC)" in log


def test_wake_host_without_a_mac_is_no_mac(backend, fake_socket: type[FakeSocket]) -> None:
    write_moonlight_conf(home_of(backend))
    result = run(backend.wake_host("OFFICE-PC"))
    assert result["ok"] is False
    assert result["error"] == "no-mac"
    assert "OFFICE-PC" in result["message"]
    assert "Host page" in result["message"]
    assert fake_socket.sent == []
    # no Moonlight.conf at all: the same answer
    assert run(backend.wake_host("NOWHERE"))["error"] == "no-mac"
    assert run(backend.wake_host(""))["error"] == "bad-request"
    assert run(backend.wake_host(None))["error"] == "bad-request"


def test_wake_host_is_io_only_when_nothing_went_out(backend, fake_socket: type[FakeSocket]) -> None:
    write_moonlight_conf(home_of(backend))
    fake_socket.failing = {"203.0.113.9"}
    assert run(backend.wake_host("MY-GAMING-PC"))["sent"] == 2 * len(wake.WAKE_PORTS)
    assert "wake_host MY-GAMING-PC: 203.0.113.9: [Errno 101]" in Path(backend.log_path).read_text()
    fake_socket.failing = {"255.255.255.255", "192.168.1.20", "203.0.113.9"}
    result = run(backend.wake_host("MY-GAMING-PC"))
    assert result["ok"] is False
    assert result["error"] == "io"
    assert result["message"].startswith("could not send a Wake-on-LAN packet: 255.255.255.255:")


def test_wake_host_drops_the_check_host_memo(backend, fake_socket: type[FakeSocket]) -> None:
    from test_backend import owned

    owned(backend)
    write_moonlight_conf(home_of(backend))
    run(backend.check_host("MY-GAMING-PC"))
    backend.harness.clear()
    run(backend.wake_host("MY-GAMING-PC"))
    run(backend.check_host("MY-GAMING-PC"))
    assert len(backend.harness.argv()) == 1


def test_set_wake_mac_overrides_moonlight_and_survives_forget_of_another(
    backend, fake_socket: type[FakeSocket]
) -> None:
    write_moonlight_conf(home_of(backend))
    stored = run(backend.set_wake_mac("office-pc", "11-22-33-44-55-66"))
    assert stored == {
        "ok": True,
        "host": "OFFICE-PC",
        "mac": "11:22:33:44:55:66",
        "wake": {"mac": "11:22:33:44:55:66", "source": "settings", "addresses": ["192.168.1.30"]},
    }
    settings = json.loads((Path(backend.settings_dir) / "settings.json").read_text())
    assert settings["wake_macs"] == {"OFFICE-PC": "11:22:33:44:55:66"}
    assert run(backend.get_settings())["settings"]["wake_macs"] == {
        "OFFICE-PC": "11:22:33:44:55:66"
    }
    # the setting wins over Moonlight's own
    run(backend.set_wake_mac("MY-GAMING-PC", "AABBCCDDEE01"))
    shown = run(backend.hosts())["wake"]
    assert shown["MY-GAMING-PC"] == {
        "mac": "aa:bb:cc:dd:ee:01",
        "source": "settings",
        "addresses": ["192.168.1.20", "203.0.113.9"],
    }
    woken = run(backend.wake_host("OFFICE-PC"))
    assert woken["ok"] is True
    assert woken["source"] == "settings"
    assert {host for host, _, _ in fake_socket.sent} == {"255.255.255.255", "192.168.1.30"}
    # clearing goes back to Moonlight's, or to nothing
    cleared = run(backend.set_wake_mac("MY-GAMING-PC", ""))
    assert cleared["mac"] is None
    assert cleared["wake"]["source"] == "moonlight"
    assert run(backend.set_wake_mac("OFFICE-PC", None))["wake"] is None
    assert run(backend.get_settings())["settings"]["wake_macs"] == {}


def test_set_wake_mac_validates(backend) -> None:
    for bad in ("aa:bb", "not a mac", 12):
        result = run(backend.set_wake_mac("OFFICE-PC", bad))
        assert result["ok"] is False
        assert result["error"] == "bad-request"
        assert result["message"] == "a MAC address looks like aa:bb:cc:dd:ee:ff"
    unknown = run(backend.set_wake_mac("NOWHERE", MAC))
    assert unknown["error"] == "bad-request"
    assert unknown["message"] == "NOWHERE is not a known host; add it first"
    assert run(backend.set_wake_mac("", MAC))["error"] == "bad-request"
    # and never through set_settings
    refused = run(backend.set_settings({"wake_macs": {"OFFICE-PC": MAC}}))
    assert refused["error"] == "bad-request"
    assert refused["message"] == "wake_macs is changed with set_wake_mac"


def test_forget_host_drops_its_mac(backend) -> None:
    run(backend.set_wake_mac("OFFICE-PC", MAC))
    assert run(backend.forget_host("office-pc"))["known"] == ["MY-GAMING-PC"]
    assert run(backend.get_settings())["settings"]["wake_macs"] == {}


def test_a_hand_broken_wake_macs_reads_as_empty(backend) -> None:
    path = Path(backend.settings_dir) / "settings.json"
    raw = json.loads(path.read_text())
    raw["wake_macs"] = ["not", "a", "map"]
    path.write_text(json.dumps(raw))
    assert run(backend.get_settings())["settings"]["wake_macs"] == {}
    assert run(backend.wake_host("OFFICE-PC"))["error"] == "no-mac"
    raw["wake_macs"] = {"OFFICE-PC": "garbage"}
    path.write_text(json.dumps(raw))
    assert run(backend.wake_host("OFFICE-PC"))["error"] == "no-mac"
