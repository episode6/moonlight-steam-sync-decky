"""Mechanical checks for the hard rules in AGENTS.md that a grep can prove."""

from __future__ import annotations

import asyncio
import json
import re

from conftest import ROOT, run
from moonlight_sync import sgdbpage
from moonlight_sync.keys import key_file_path

FORBIDDEN_CALLS = (
    "AddShortcut",
    "RemoveShortcut",
    "SetShortcutName",
    "SetAppLaunchOptions",
    "SetAppHiddenState",
    "SetCustomArtworkForApp",
)


def source_files():
    for pattern in ("src/**/*.ts", "src/**/*.tsx"):
        yield from ROOT.glob(pattern)


def test_plugin_json_has_no_root_flag() -> None:
    meta = json.loads((ROOT / "plugin.json").read_text())
    assert meta["name"] == "Moonlight Sync"
    assert meta["flags"] == []


def test_frontend_never_calls_the_live_shortcut_apis() -> None:
    call = re.compile(r"\.(" + "|".join(FORBIDDEN_CALLS) + r")\s*\(")
    offenders = [
        f"{path.relative_to(ROOT)}:{number}"
        for path in source_files()
        for number, line in enumerate(path.read_text().splitlines(), 1)
        if call.search(line)
    ]
    assert offenders == []


def test_the_client_library_is_only_touched_in_steam_ts() -> None:
    """Spec 3.15's one exception: hidden state and the fallback Streaming
    collection, through collectionStore, in `libraryPort()` and nowhere
    else. Calls only (`.Name`): `tabs.ts`'s synthetic collection *defines*
    an `AsDragDropCollection` of its own, which is no write."""
    call = re.compile(r"\.(SetAppsAsHidden|NewUnsavedCollection|AsDragDropCollection)\b")
    users = {
        str(path.relative_to(ROOT))
        for path in source_files()
        if not path.name.endswith(".test.ts") and call.search(path.read_text())
    }
    assert users == {"src/lib/steam.ts"}


def test_backend_never_names_config_toml_for_writing() -> None:
    """keys.py reads config.toml with tomllib; nothing opens it for writing."""
    for path in (ROOT / "py_modules").rglob("*.py"):
        text = path.read_text()
        assert not re.search(r"open\([^)]*config[^)]*['\"]w", text), path


#: The key in tests/fixtures/sgdb/api.html. Spelled here and in the fixtures
#: only (the test below proves it), so a grep for it over tests/ is the
#: proof that nothing else in the suite carries it.
PLACEHOLDER_KEY = "0123456789abcdef0123456789abcdef"


def test_the_placeholder_key_is_spelled_only_in_the_fixtures_and_here() -> None:
    carriers = {
        str(path.relative_to(ROOT))
        for path in (ROOT / "tests").rglob("*")
        if path.is_file()
        and "__pycache__" not in path.parts
        and PLACEHOLDER_KEY in path.read_text(errors="replace")
    }
    assert carriers == {"tests/fixtures/sgdb/api.html", "tests/test_hard_rules.py"}


def test_the_fetched_key_never_appears_in_an_event_or_a_log_line(
    backend, fake_browser, monkeypatch
) -> None:
    """Hard rule 4 over the browser fetch (spec 3.20.3): the key crosses the
    debugger socket into keys.py and nothing else -- not a callable result,
    an sgdb_key_event, the sgdb_key_done, a log line or sync_state --
    carries more than its last four characters."""
    monkeypatch.setattr(sgdbpage, "POLL_INTERVAL_S", 0.01)
    browser = fake_browser()

    async def scenario():
        results = [await backend.start_sgdb_key_fetch()]
        browser.open_page()
        deadline = asyncio.get_running_loop().time() + 5
        while not backend.emitted.of("sgdb_key_done"):
            assert asyncio.get_running_loop().time() < deadline
            await asyncio.sleep(0.01)
        await backend._key_fetch.task
        results.append(await backend.cancel_sgdb_key_fetch())
        results.append(await backend.sgdb_key_state())
        results.append(await backend.sync_state())
        results.append(await backend.log_tail(500))
        return results

    results = run(scenario())
    assert results[2]["source"] == "file" and results[2]["hint"] == PLACEHOLDER_KEY[-4:]
    blob = json.dumps(results) + json.dumps(backend.emitted.calls)
    assert PLACEHOLDER_KEY not in blob
    assert PLACEHOLDER_KEY[:-4] not in blob
    assert backend.emitted.of("sgdb_key_done") == [
        {"ok": True, "source": "file", "hint": PLACEHOLDER_KEY[-4:]}
    ]
    with open(key_file_path(backend.home), encoding="utf-8") as handle:
        assert handle.read() == PLACEHOLDER_KEY + "\n"


def test_the_cli_pin_lives_only_in_package_json() -> None:
    package = json.loads((ROOT / "package.json").read_text())
    assert package["moonlightSteamSync"] == "0.4.0"
    assert package["license"] == "MIT"
    assert "remote_binary" not in package
    for path in (ROOT / "backend" / "entrypoint.sh", ROOT / ".github" / "workflows" / "ci.yml"):
        assert "0.4.0" not in path.read_text(), path
