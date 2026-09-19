"""The real main.py, driven through the decky stub with the fake CLI installed.

Here nothing is injected: ``main.Plugin`` builds its Backend from the
``DECKY_*`` constants exactly as on a Deck, and the "installed CLI" at
``<DECKY_USER_HOME>/.local/bin/moonlight-steam-sync`` is a copy of
``tests/fake_cli.py``, run as ``[python3, path, ...]``.
"""

from __future__ import annotations

import asyncio
import importlib
import json
import shutil
import sys
from pathlib import Path

import pytest

from conftest import FAKE_CLI, FIXTURES, ROOT, STUBS, run


@pytest.fixture
def plugin(tmp_path, monkeypatch):
    home = tmp_path / "home"
    installed = home / ".local" / "bin" / "moonlight-steam-sync"
    installed.parent.mkdir(parents=True)
    shutil.copyfile(FAKE_CLI, installed)
    plugin_dir = tmp_path / "plugins" / "Moonlight Sync"
    plugin_dir.mkdir(parents=True)
    (plugin_dir / "package.json").write_text((ROOT / "package.json").read_text())
    env = {
        "DECKY_USER_HOME": str(home),
        "DECKY_PLUGIN_SETTINGS_DIR": str(tmp_path / "settings"),
        "DECKY_PLUGIN_LOG_DIR": str(tmp_path / "logs"),
        "DECKY_PLUGIN_DIR": str(plugin_dir),
        "DECKY_PLUGIN_VERSION": "0.1.0",
        "FAKE_CLI_FIXTURES": f"{FIXTURES / 'full-sync'}:{FIXTURES / 'common'}",
        "FAKE_CLI_ARGV_LOG": str(tmp_path / "argv.jsonl"),
        "FAKE_CLI_STEAM_GONE_FILE": str(tmp_path / "steam-gone"),
    }
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    monkeypatch.delenv("SGDB_API_KEY", raising=False)
    monkeypatch.syspath_prepend(str(STUBS))
    monkeypatch.syspath_prepend(str(ROOT))
    for name in ("decky", "main"):
        sys.modules.pop(name, None)
    main = importlib.import_module("main")
    decky = sys.modules["decky"]
    decky.emitted.clear()
    yield main.Plugin(), decky, tmp_path
    for name in ("decky", "main"):
        sys.modules.pop(name, None)


def test_main_py_end_to_end(plugin) -> None:
    instance, decky, tmp_path = plugin
    (tmp_path / "steam-gone").write_text("gone\n")

    async def scenario():
        await instance._main()
        version = await instance.cli_version()
        owned = await instance.write_owned_apps(12345678, {"2379780": "Balatro"})
        status = await instance.status()
        started = await instance.start_sync()
        while (await instance.sync_state())["running"]:
            await asyncio.sleep(0.02)
        await instance._unload()
        return version, owned, status, started

    version, owned, status, started = run(scenario())
    assert version["installed"] == "0.3.0"
    assert version["pinned"] == "0.3.0"
    assert version["plugin_version"] == "0.1.0"
    assert owned == {"ok": True, "count": 1}
    assert status["ok"] is True and len(status["entries"]) == 6
    assert started == {"ok": True, "kind": "sync"}
    names = [event for event, _ in decky.emitted]
    assert names[-1] == "sync_done"
    assert names.count("sync_event") == 9
    done = decky.emitted[-1][1][0]
    assert done["exit"] == 0
    assert done["pending"]["layout_walk"] is True
    invocations = [json.loads(line) for line in (tmp_path / "argv.jsonl").read_text().splitlines()]
    home = str(tmp_path / "home")
    assert all(i["cwd"] == home and i["home"] == home for i in invocations)
    assert all(i["from_plugin"] == "1" for i in invocations)
    assert Path(tmp_path / "settings" / "settings.json").exists()
    assert Path(tmp_path / "settings" / "ignore.json").read_text().strip() == "[]"


def test_callables_wait_for_startup(plugin) -> None:
    instance, _, _ = plugin

    async def scenario():
        # no explicit _main(): the first callable runs startup itself, once
        first, second = await asyncio.gather(instance.get_settings(), instance.pending())
        return first, second, instance._startup

    first, second, startup = run(scenario())
    assert first["ok"] is True
    assert second["restart_needed"] == "none"
    assert startup.done()
