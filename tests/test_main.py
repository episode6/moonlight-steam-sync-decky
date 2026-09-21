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
def plugin_module(tmp_path, monkeypatch):
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
    # main.Plugin keeps its backend in *class* attributes (see main.py): the
    # module is re-imported per test, and resetting them here makes that
    # isolation explicit, so nothing a class-style test sets can reach the
    # next test.
    main.Plugin._backend = None
    main.Plugin._startup = None
    yield main, decky, tmp_path
    main.Plugin._backend = None
    main.Plugin._startup = None
    for name in ("decky", "main"):
        sys.modules.pop(name, None)


@pytest.fixture
def plugin(plugin_module):
    """The api_version > 0 shape: an instance, as decky-loader builds it."""
    main, decky, tmp_path = plugin_module
    return main.Plugin(), decky, tmp_path


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
    assert version["installed"] == "0.4.0"
    assert version["pinned"] == "0.4.0"
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


# ---- both of decky-loader's calling conventions ------------------------------
#
# The loader's sandboxed plugin host does, once the module is loaded:
#
#     if self.api_version > 0:
#         self.Plugin = module.Plugin()
#     else:
#         self.Plugin = module.Plugin
#     ...
#     if self.api_version > 0:
#         get_event_loop().create_task(self.Plugin._main())
#     else:
#         get_event_loop().create_task(self.Plugin._main(self.Plugin))
#
# and, per call, `getattr(self.Plugin, method)(*args)` for api_version >= 1
# against `getattr(self.Plugin, method)(self.Plugin, **args)` for the legacy
# path. plugin.json pins api_version 1, so the instance form is what runs on a
# Deck; main.py has no __init__ and keeps its state in class attributes so the
# legacy form works too.


def test_plugin_has_no_init_and_declares_its_state_on_the_class(plugin_module) -> None:
    main, _, _ = plugin_module
    assert "__init__" not in vars(main.Plugin)
    assert main.Plugin._backend is None and main.Plugin._startup is None


def test_the_api_version_0_convention_drives_the_class_itself(plugin_module) -> None:
    """Every call passes the class where `self` goes and nothing is
    instantiated -- the loader's api_version 0 path."""
    main, _decky, tmp_path = plugin_module
    plugin = main.Plugin  # the class, exactly as `self.Plugin = module.Plugin`
    (tmp_path / "steam-gone").write_text("gone\n")

    def call(method, *args):
        """The loader's legacy dispatch: the method looked up by name on the
        class, with the class itself passed where `self` goes."""
        return getattr(plugin, method)(plugin, *args)

    async def scenario():
        await plugin._main(plugin)
        version = await call("cli_version")
        owned = await call("write_owned_apps", 12345678, {"2379780": "Balatro"})
        status = await call("status")
        settings = await call("get_settings")
        await plugin._unload(plugin)
        return version, owned, status, settings

    version, owned, status, settings = run(scenario())
    assert version["installed"] == "0.4.0"
    assert owned == {"ok": True, "count": 1}
    assert status["ok"] is True and len(status["entries"]) == 6
    assert settings["ok"] is True
    # the state landed on the class, which is where the loader's `self` points
    assert plugin._backend is not None and plugin._startup.done()


def test_class_state_does_not_leak_into_the_next_test(plugin_module) -> None:
    """Runs after the api_version 0 test above, which set _backend on its own
    (freshly imported) class object."""
    main, _, _ = plugin_module
    assert main.Plugin._backend is None and main.Plugin._startup is None


def test_every_frontend_callable_exists_on_the_plugin(plugin) -> None:
    """src/lib/cli.ts's CALLABLES are the names @decky/api calls on main.Plugin."""
    instance, _, _ = plugin
    source = (ROOT / "src" / "lib" / "cli.ts").read_text()
    block = source.split("const CALLABLES = [", 1)[1].split("]", 1)[0]
    names = [part.strip().strip('"') for part in block.split(",") if part.strip()]
    assert {"search", "pin", "unpin", "set_ignored", "layouts", "record_layout"} <= set(names)
    missing = [name for name in names if not callable(getattr(instance, name, None))]
    assert missing == []


def test_layouts_through_main_py(plugin) -> None:
    instance, _, tmp_path = plugin

    async def scenario():
        before = await instance.layouts()
        recorded = await instance.record_layout(0x80000000 + 7, 1245620, "copied", "workshop://1")
        after = await instance.layouts()
        return before, recorded, after

    before, recorded, after = run(scenario())
    assert before == {"ok": True, "version": 1, "entries": {}}
    assert recorded["ok"] is True
    assert after["entries"] == recorded["entries"]
    assert list(after["entries"]) == [str(0x80000000 + 7)]
    assert Path(tmp_path / "settings" / "layouts.json").exists()


def test_pin_and_set_ignored_through_main_py(plugin) -> None:
    instance, _, tmp_path = plugin

    async def scenario():
        pinned = await instance.pin("Hades II", 1145350)
        ignored = await instance.set_ignored("Desktop", True)
        return pinned, ignored

    pinned, ignored = run(scenario())
    assert pinned["ok"] is True
    assert pinned["pinned"]["steam_appid"] == 1145350
    assert ignored == {"ok": True, "ignored": ["Desktop"]}
    invocations = [json.loads(line) for line in (tmp_path / "argv.jsonl").read_text().splitlines()]
    assert invocations[-1]["argv"] == [
        "--json",
        "match",
        "Hades II",
        "--steam",
        "1145350",
        "--defer-art",
    ]
