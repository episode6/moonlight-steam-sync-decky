"""The SteamGridDB key callables (spec 3.7 ``sgdb_key_state`` and friends)."""

from __future__ import annotations

import json
import stat
from pathlib import Path

from conftest import run

KEY = "0123456789abcdef0123456789abcdef"  # a made-up 32-character key


def config_dir(home: Path) -> Path:
    path = home / ".config" / "moonlight-steam-sync"
    path.mkdir(parents=True, exist_ok=True)
    return path


def write_config(home: Path, text: str) -> Path:
    path = config_dir(home) / "config.toml"
    path.write_text(text)
    return path


def key_file(home: Path) -> Path:
    return home / ".config" / "moonlight-steam-sync" / "sgdb-api-key"


def test_none_when_no_source(backend) -> None:
    state = run(backend.sgdb_key_state())
    assert state == {"ok": True, "source": "none", "hint": None, "config_parse_error": False}


def test_file_source_and_hint(backend) -> None:
    home = Path(backend.home)
    config_dir(home)
    key_file(home).write_text(f"  {KEY}  \n")
    state = run(backend.sgdb_key_state())
    assert state["source"] == "file"
    assert state["hint"] == "cdef"


def test_env_beats_file(make_backend) -> None:
    backend = make_backend(env={"SGDB_API_KEY": "envkey-000000009999"})
    config_dir(Path(backend.home))
    key_file(Path(backend.home)).write_text(KEY + "\n")
    state = run(backend.sgdb_key_state())
    assert state["source"] == "env"
    assert state["hint"] == "9999"


def test_config_beats_env_and_file(make_backend) -> None:
    backend = make_backend(env={"SGDB_API_KEY": "envkey-000000009999"})
    home = Path(backend.home)
    write_config(home, '[steamgriddb]\napi_key = "configkey-00001234"\n')
    key_file(home).write_text(KEY + "\n")
    state = run(backend.sgdb_key_state())
    assert state["source"] == "config"
    assert state["hint"] == "1234"


def test_empty_config_key_falls_through(backend) -> None:
    home = Path(backend.home)
    write_config(home, '[steamgriddb]\napi_key = ""\nhost = "MY-GAMING-PC"\n')
    key_file(home).write_text(KEY + "\n")
    assert run(backend.sgdb_key_state())["source"] == "file"


def test_config_parse_error(backend) -> None:
    home = Path(backend.home)
    write_config(home, "[steamgriddb\napi_key = \n")
    key_file(home).write_text(KEY + "\n")
    state = run(backend.sgdb_key_state())
    assert state["config_parse_error"] is True
    assert state["source"] == "file"


def test_set_writes_0600_with_trailing_newline(backend) -> None:
    result = run(backend.set_sgdb_key(f"  {KEY}\n"))
    assert result == {"ok": True, "source": "file", "hint": "cdef", "config_parse_error": False}
    path = key_file(Path(backend.home))
    assert path.read_text() == KEY + "\n"
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert not path.with_name("sgdb-api-key.tmp").exists()


def test_set_replaces_an_existing_file_keeping_0600(backend) -> None:
    home = Path(backend.home)
    config_dir(home)
    key_file(home).write_text("old-key-0000\n")
    key_file(home).chmod(0o644)
    run(backend.set_sgdb_key(KEY))
    assert key_file(home).read_text() == KEY + "\n"
    assert stat.S_IMODE(key_file(home).stat().st_mode) == 0o600


def test_set_refuses_when_config_has_a_key(backend) -> None:
    home = Path(backend.home)
    config = write_config(home, '[steamgriddb]\napi_key = "configkey-00001234"\n')
    before = config.read_text()
    result = run(backend.set_sgdb_key(KEY))
    assert result["ok"] is False
    assert result["error"] == "bad-request"
    assert result["message"] == "set in config.toml"
    assert not key_file(home).exists()
    assert config.read_text() == before  # config.toml is never written


def test_set_with_env_writes_the_file_anyway(make_backend) -> None:
    backend = make_backend(env={"SGDB_API_KEY": "envkey-000000009999"})
    result = run(backend.set_sgdb_key(KEY))
    assert result["ok"] is True
    assert result["source"] == "env"
    assert key_file(Path(backend.home)).read_text() == KEY + "\n"


def test_set_refuses_empty(backend) -> None:
    for bad in ("", "   ", None, 42):
        result = run(backend.set_sgdb_key(bad))
        assert result["ok"] is False
        assert result["error"] == "bad-request"
    assert not key_file(Path(backend.home)).exists()


def test_clear_removes_only_the_key_file(backend) -> None:
    home = Path(backend.home)
    config = write_config(home, 'host = "MY-GAMING-PC"\n')
    other = config_dir(home) / "notes.txt"
    other.write_text("keep me\n")
    run(backend.set_sgdb_key(KEY))
    result = run(backend.clear_sgdb_key())
    assert result["source"] == "none"
    assert not key_file(home).exists()
    assert config.exists()
    assert other.read_text() == "keep me\n"
    # clearing again is fine
    assert run(backend.clear_sgdb_key())["ok"] is True


def test_the_key_never_reaches_the_frontend(backend) -> None:
    """No callable result, relayed event or log line carries more than four characters."""
    home = Path(backend.home)
    results = [
        run(backend.set_sgdb_key(KEY)),
        run(backend.sgdb_key_state()),
        run(backend.test_sgdb_key()),
        run(backend.cli_version()),
        run(backend.doctor()),
        run(backend.sync_state()),
    ]
    # Plant the key in the log (as a misbehaving child's stderr could) and read it back.
    backend._log_raw(f"child said {KEY}\n")
    results.append(run(backend.log_tail(50)))
    blob = json.dumps(results) + json.dumps(backend.emitted.calls)
    assert KEY not in blob
    assert KEY[:-4] not in blob
    assert "cdef" in json.dumps(results[0])
    assert key_file(home).read_text() == KEY + "\n"


def test_a_key_echoed_by_the_cli_is_scrubbed_at_the_spawn_seam(make_backend, tmp_path) -> None:
    """A CLI that echoes the key back (in a note, an error message or on
    stderr) must not be able to leak it: Backend._spawn scrubs every parsed
    event, every stdout line and every stderr line once per spawn, so
    RunResult -- and therefore every callable's whole result, the events it
    carries and the plugin log -- is clean by construction (hard rule 4)."""
    fixture = tmp_path / "fx"
    fixture.mkdir()
    (fixture / "search.ndjson").write_text(
        '{"event":"start","schema":1,"version":"0.3.0","command":"search"}\n'
        f'{{"event":"note","message":"search: SteamGridDB rejected key {KEY}"}}\n'
        '{"event":"end"}\n'
    )
    (fixture / "list.ndjson").write_text(
        '{"event":"start","schema":1,"version":"0.3.0","command":"list"}\n'
        f'{{"event":"note","message":"list: using key {KEY}"}}\n'
        f'{{"event":"error","exit":4,"message":"list: SteamGridDB rejected key {KEY}"}}\n'
    )
    backend = make_backend(
        env={"FAKE_CLI_FIXTURES": str(fixture), "FAKE_CLI_STDERR": f"traceback with {KEY}"},
    )
    key_file(Path(backend.home)).parent.mkdir(parents=True, exist_ok=True)
    key_file(Path(backend.home)).write_text(KEY + "\n")
    assert run(backend.write_owned_apps(12345678, {"2379780": "Balatro"}))["ok"]

    tested = run(backend.test_sgdb_key())
    assert tested["ok"] is False
    assert KEY[-4:] in json.dumps(tested)  # the note did reach the result
    listed = run(backend.list_apps())
    assert listed["ok"] is False and listed["error"] == "cli-error"

    blob = json.dumps([tested, listed]) + json.dumps(run(backend.log_tail(200)))
    assert KEY not in blob
    assert KEY[:-4] not in blob  # not even the key minus its hint


def test_test_sgdb_key_ok_on_sgdb_candidates(backend) -> None:
    assert run(backend.test_sgdb_key()) == {"ok": True}
    argv = backend.harness.argv()[-1]
    assert argv[:3] == ["--json", "search", "Portal"]


def test_test_sgdb_key_maps_401(make_backend, tmp_path) -> None:
    fixture = tmp_path / "fx"
    fixture.mkdir()
    (fixture / "search.ndjson").write_text(
        '{"event":"start","schema":1,"version":"0.3.0","command":"search"}\n'
        '{"event":"error","exit":4,"message":"search: SteamGridDB returned HTTP 401"}\n'
    )
    backend = make_backend(env={"FAKE_CLI_FIXTURES": str(fixture)}, start=False)
    backend.installed_version = (0, 3, 0)
    backend.cli_ok = True
    result = run(backend.test_sgdb_key())
    assert result["ok"] is False
    assert result["error"] == "cli-error"
    assert result["message"] == "SteamGridDB rejected the key"
