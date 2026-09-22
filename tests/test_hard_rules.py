"""Mechanical checks for the hard rules in AGENTS.md that a grep can prove."""

from __future__ import annotations

import json
import re

from conftest import ROOT

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
    else. Calls only (`.Name`): `tabs.py`'s synthetic collection *defines*
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


def test_the_cli_pin_lives_only_in_package_json() -> None:
    package = json.loads((ROOT / "package.json").read_text())
    assert package["moonlightSteamSync"] == "0.4.0"
    assert package["license"] == "MIT"
    assert "remote_binary" not in package
    for path in (ROOT / "backend" / "entrypoint.sh", ROOT / ".github" / "workflows" / "ci.yml"):
        assert "0.4.0" not in path.read_text(), path
