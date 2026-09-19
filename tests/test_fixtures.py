"""Every fixture line is valid JSON with exactly the keys spec 3.4.6 documents.

The key sets below are transcribed from spec 3.4.6 (including the amended
``entry.cached`` / ``cached_when``). A typo in a hand-written fixture fails
here instead of being baked into the backend and the frontend, which both
read these files.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

FIXTURES = Path(__file__).resolve().parent / "fixtures"

MATCH_KEYS = {"steam_appid", "sgdb_id", "matched_name", "how"}
SLOT_NAMES = {"portrait", "landscape", "hero", "logo", "icon"}
TITLE_SLOT_VALUES = {"steam", "sgdb", "kept", "missing", "skipped", "cached-miss"}

#: event -> its keys (``event`` included). ``end`` differs per command.
EVENT_KEYS: dict[str, set[str]] = {
    "start": {"event", "schema", "version", "command"},
    "plan": {
        "event",
        "host",
        "published",
        "ignored",
        "present",
        "to_add",
        "to_replace",
        "to_park",
        "to_unpark",
        "to_remove",
        "pending",
        "limit",
        "stream",
        "shortcut",
        "parked",
        "duplicates",
    },
    "replace": {"event", "name", "old_appid", "new_appid", "reason"},
    "title": {"event", "index", "total", "name", "kind", "appid", "match", "slots"},
    "awaiting-steam-exit": {"event", "timeout_s"},
    "commit": {"event", "written", "restarted", "backup", "relaunch_error"},
    "summary": {
        "event",
        "added",
        "replaced",
        "removed",
        "filled",
        "missing",
        "unmatched",
        "duplicates",
        "pending",
        "stopped_early",
        "stop_reason",
        "exit",
    },
    "app": {
        "event",
        "name",
        "label",
        "kind",
        "match",
        "fuzzy",
        "duplicate_of",
        "same_game_as",
        "cached",
        "cached_when",
    },
    "entry": {
        "event",
        "name",
        "app_name",
        "appid",
        "hidden",
        "parked",
        "published",
        "client",
        "match",
        "slots",
        "stale_art",
        "cached",
        "cached_when",
    },
    "host": {"event", "name", "source", "cached_hosts"},
    "candidate": {"event", "source", "id", "name", "verified", "owned", "steam_appid"},
    "pinned": {"event", "name", "steam_appid", "sgdb_id", "override_line"},
    "note": {"event", "message"},
    "error": {"event", "exit", "message"},
}
END_KEYS = {
    "list": {"event", "count", "host"},
    "status": {"event", "count"},
    "search": {"event"},
    "ignore": {"event", "count"},
    "doctor": {"event", "count"},
}


def ndjson_files() -> list[Path]:
    return sorted(FIXTURES.glob("*/*.ndjson"))


def load(path: Path) -> list[dict]:
    lines = [
        line for line in path.read_text().splitlines() if line.strip() and not line.startswith("#")
    ]
    return [json.loads(line) for line in lines]


def test_every_scenario_the_spec_names_exists() -> None:
    names = {f"{p.parent.name}/{p.name}" for p in FIXTURES.glob("*/*")}
    expected = {
        "full-sync/sync.ndjson",
        "art-only/sync.ndjson",
        "nothing-to-do/sync.ndjson",
        "unreachable/sync.ndjson",
        "unreachable/list.ndjson",
        "stopped/sync.ndjson",
        "refused/sync.ndjson",
        "common/list.ndjson",
        "common/list-cached.ndjson",
        "common/status.ndjson",
        "common/host.ndjson",
        "common/host-none.ndjson",
        "common/search.ndjson",
        "common/match.ndjson",
        "common/match-unpin.ndjson",
        "common/remove.ndjson",
        "common/art.ndjson",
        "common/doctor.txt",
    }
    assert expected <= names


@pytest.mark.parametrize("path", ndjson_files(), ids=lambda p: f"{p.parent.name}/{p.name}")
def test_fixture_key_sets_match_the_schema(path: Path) -> None:
    events = load(path)
    assert events, "empty fixture"
    first = events[0]
    assert first["event"] == "start"
    assert first["schema"] == 1
    assert first["version"] == "0.3.0"
    command = first["command"]
    for event in events:
        name = event["event"]
        expected = END_KEYS[command] if name == "end" else EVENT_KEYS.get(name)
        assert expected is not None, f"unknown event {name!r}"
        assert set(event) == expected, f"{name}: {sorted(set(event) ^ expected)}"
        for key in ("match",):
            if key in event and event[key] is not None:
                assert set(event[key]) == MATCH_KEYS
        if name == "title":
            assert set(event["slots"]) <= SLOT_NAMES
            assert set(event["slots"].values()) <= TITLE_SLOT_VALUES
        if name == "entry":
            assert set(event["slots"]) == SLOT_NAMES
        if name == "host":
            for cached in event["cached_hosts"]:
                assert set(cached) == {"name", "when", "count"}
        if name == "app":
            for other in event["same_game_as"]:
                assert set(other) == {"name", "host"}


@pytest.mark.parametrize("path", ndjson_files(), ids=lambda p: f"{p.parent.name}/{p.name}")
def test_error_is_last_and_summary_follows_plan(path: Path) -> None:
    events = load(path)
    names = [e["event"] for e in events]
    if "error" in names:
        assert names[-1] == "error"
    if "plan" in names and events[0]["command"] == "sync" and path.parent.name != "refused":
        assert "summary" in names


def test_placeholder_hosts_only() -> None:
    for path in FIXTURES.glob("*/*"):
        text = path.read_text()
        for event in load(path) if path.suffix == ".ndjson" else []:
            host = event.get("host")
            if isinstance(host, str):
                assert host in {"MY-GAMING-PC", "OFFICE-PC"}
        assert "/home/" not in text
