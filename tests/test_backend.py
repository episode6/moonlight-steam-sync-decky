"""The backend driven end to end against tests/fake_cli.py (spec 3.6.3, 3.7, 3.9)."""

from __future__ import annotations

import asyncio
import contextlib
import json
import os
import signal
import time
from pathlib import Path
from typing import Any

import pytest

from conftest import FIXTURES, run
from moonlight_sync import events as ev


def load_fixture(name: str) -> list[dict[str, Any]]:
    path = FIXTURES / name
    return [
        json.loads(line)
        for line in path.read_text().splitlines()
        if line.strip() and not line.startswith("#")
    ]


def owned(backend) -> None:
    assert run(backend.write_owned_apps(12345678, {"2379780": "Balatro", "1497440": "COCOON"}))[
        "ok"
    ]


def settings_path(backend, name: str) -> str:
    return str(Path(backend.settings_dir) / name)


def read_pending(backend) -> dict[str, Any]:
    return json.loads((Path(backend.settings_dir) / "pending.json").read_text())


async def start_and_wait(backend, start) -> dict[str, Any]:
    result = await start
    await backend.wait_for_run()
    return result


async def wait_until(predicate, timeout: float = 10.0) -> None:
    deadline = asyncio.get_running_loop().time() + timeout
    while not predicate():
        if asyncio.get_running_loop().time() > deadline:
            raise AssertionError("condition not met in time")
        await asyncio.sleep(0.02)


def sync_argv(backend, *extra: str) -> list[str]:
    return [
        "--json",
        "sync",
        "--owned-apps",
        settings_path(backend, "owned-apps.json"),
        "--ignore-file",
        settings_path(backend, "ignore.json"),
        "--client-shortcut",
        "--park-unpublished",
        "--commit",
        "await-exit",
        *extra,
    ]


# ----------------------------------------------------------------------
# startup and files


def test_a_countdown_above_the_ceiling_is_clamped_not_rejected(backend) -> None:
    """Decision 30 lowered the ceiling from 60 to 30 (the CLI's await-exit
    wait times out at 60 s, so a 60 s countdown would race it). A
    settings.json written by an older build still reads."""
    path = Path(settings_path(backend, "settings.json"))
    path.write_text(json.dumps({"version": 1, "restart_countdown_s": 60}))
    assert run(backend.get_settings())["settings"]["restart_countdown_s"] == 30
    path.write_text(json.dumps({"version": 1, "restart_countdown_s": "soon"}))
    assert run(backend.get_settings())["settings"]["restart_countdown_s"] == 5


def test_startup_creates_settings_and_ignore(backend) -> None:
    settings = json.loads(Path(settings_path(backend, "settings.json")).read_text())
    assert settings["version"] == 1
    assert settings["restart_countdown_s"] == 5
    assert settings["copy_layouts"] is True
    assert settings["retry_missing"] is False
    assert settings["layout_strategy"] == "copy"
    assert json.loads(Path(settings_path(backend, "ignore.json")).read_text()) == []


def test_startup_seeds_hosts_once(backend) -> None:
    # host.ndjson: active MY-GAMING-PC, cached MY-GAMING-PC and OFFICE-PC
    assert run(backend.get_settings())["settings"]["hosts"] == ["MY-GAMING-PC", "OFFICE-PC"]
    assert run(backend.forget_host("OFFICE-PC"))["known"] == ["MY-GAMING-PC"]
    shown = run(backend.hosts())
    assert shown["known"] == ["MY-GAMING-PC"]  # not re-seeded from cached_hosts
    assert shown["active"] == "MY-GAMING-PC"
    assert shown["source"] == "state"
    assert [c["name"] for c in shown["cached_hosts"]] == ["MY-GAMING-PC", "OFFICE-PC"]


def test_startup_probes_capabilities(make_backend) -> None:
    backend = make_backend(env={"FAKE_CLI_ART_COMMIT": "1"})
    assert run(backend.cli_capabilities()) == {"ok": True, "art_commit": True}
    argvs = backend.harness.argv()
    assert argvs[0] == ["--version"]
    assert ["art", "--help"] in argvs
    assert argvs.count(["art", "--help"]) == 1  # probed once per lifetime


def test_capabilities_without_art_commit(backend) -> None:
    assert run(backend.cli_capabilities()) == {"ok": True, "art_commit": False}
    assert run(backend.cli_version())["capabilities"] == {"art_commit": False}


def test_cli_version_shape(backend, tmp_path) -> None:
    plugin = Path(backend.plugin_dir)
    plugin.mkdir(parents=True, exist_ok=True)
    (plugin / "package.json").write_text('{"version": "0.1.0", "moonlightSteamSync": "0.3.0"}')
    info = run(backend.cli_version())
    assert info == {
        "ok": True,
        "installed": "0.3.0",
        "bundled": None,
        "minimum": "0.3.0",
        "too_old": False,
        "installed_path": str(Path(backend.home) / ".local" / "bin" / "moonlight-steam-sync"),
        "bundled_path": str(plugin / "bin" / "moonlight-steam-sync.pyz"),
        "pinned": "0.3.0",
        "plugin_version": "0.1.0",
        "log_path": str(tmp_path / "logs" / "moonlight-sync.log"),
        "install_error": None,
        "capabilities": {"art_commit": False},
    }


# ----------------------------------------------------------------------
# argv of every callable


def test_argv_env_and_cwd_of_every_callable(make_backend) -> None:
    backend = make_backend(env={"FAKE_CLI_ART_COMMIT": "1"})
    owned(backend)
    backend.harness.clear()
    own = settings_path(backend, "owned-apps.json")
    ign = settings_path(backend, "ignore.json")

    run(backend.status())
    run(backend.list_apps())
    run(backend.check_host("OFFICE-PC"))
    run(backend.list_cached("OFFICE-PC"))
    run(backend.hosts())
    run(backend.set_host("MY-GAMING-PC"))
    run(backend.set_host(""))
    run(backend.doctor())
    run(backend.test_sgdb_key())
    invocations = backend.harness.invocations()
    assert [i["argv"] for i in invocations] == [
        ["--json", "status", "--owned-apps", own],
        ["--json", "list", "--owned-apps", own, "--ignore-file", ign],
        ["--json", "list", "--host", "OFFICE-PC", "--owned-apps", own, "--ignore-file", ign],
        [
            "--json",
            "list",
            "--host",
            "OFFICE-PC",
            "--cached",
            "--owned-apps",
            own,
            "--ignore-file",
            ign,
        ],
        ["--json", "host", "show"],
        ["--json", "host", "set", "MY-GAMING-PC"],
        ["--json", "host", "clear"],
        ["doctor"],
        ["--json", "search", "Portal", "--owned-apps", own],
    ]
    for invocation in invocations:
        assert invocation["cwd"] == backend.home
        assert invocation["home"] == backend.home
        assert invocation["from_plugin"] == "1"


@pytest.mark.scenario("nothing-to-do")
def test_argv_of_the_long_runs(make_backend) -> None:
    backend = make_backend(env={"FAKE_CLI_ART_COMMIT": "1", "FAKE_CLI_WAIT_S": "0.3"})
    owned(backend)
    backend.harness.clear()
    run(start_and_wait(backend, backend.start_sync()))
    run(start_and_wait(backend, backend.start_sync({"retry_missing": True})))
    run(backend.set_settings({"retry_missing": True}))
    run(start_and_wait(backend, backend.start_sync()))
    run(start_and_wait(backend, backend.start_art_refetch()))
    run(start_and_wait(backend, backend.start_remove_all()))
    assert backend.harness.argv() == [
        sync_argv(backend),
        sync_argv(backend, "--retry-missing"),
        sync_argv(backend, "--retry-missing"),
        ["--json", "art", "--force", "--commit", "await-exit"],
        ["--json", "remove", "--all", "--client", "--commit", "await-exit"],
    ]


# ----------------------------------------------------------------------
# long runs: relay, sync_done and pending (spec 3.9)


@pytest.mark.scenario("full-sync")
def test_full_sync_relays_in_order_and_writes_pending_before_the_wait(backend, steam_gone) -> None:
    owned(backend)
    seen_pending: list[dict[str, Any]] = []

    def on_emit(name: str, payload: dict[str, Any]) -> None:
        if name == "sync_event" and payload["event"]["event"] == "awaiting-steam-exit":
            seen_pending.append(read_pending(backend))
            steam_gone()

    backend.emitted.hooks.append(on_emit)
    assert run(start_and_wait(backend, backend.start_sync())) == {"ok": True, "kind": "sync"}

    expected = load_fixture("full-sync/sync.ndjson")
    assert backend.emitted.relayed() == expected
    assert all(p["kind"] == "sync" for p in backend.emitted.of("sync_event"))
    # pending said "write" before awaiting-steam-exit reached the frontend
    assert seen_pending[0]["restart_needed"] == "write"
    assert seen_pending[0]["layout_walk"] is False
    assert seen_pending[0]["last_plan"] == expected[1]

    done = backend.emitted.of("sync_done")
    assert len(done) == 1
    assert done[0]["kind"] == "sync"
    assert done[0]["exit"] == 0
    assert done[0]["summary"] == expected[-1]
    assert done[0]["commit"] == expected[-2]
    assert done[0]["failure"] is None
    pending = done[0]["pending"]
    assert pending["restart_needed"] == "none"
    assert pending["layout_walk"] is True
    assert pending["last_summary"] == expected[-1]
    assert pending["last_plan"] == expected[1]
    assert pending["last_kind"] == "sync"
    assert read_pending(backend) == pending
    # the last event before sync_done
    assert backend.emitted.calls[-1][0] == "sync_done"
    assert ev.restart_decision(expected, 0) == "write"


@pytest.mark.scenario("art-only")
def test_art_only_sets_restart_art(backend) -> None:
    owned(backend)
    run(start_and_wait(backend, backend.start_sync()))
    events = load_fixture("art-only/sync.ndjson")
    assert backend.emitted.relayed() == events
    done = backend.emitted.of("sync_done")[0]
    assert done["exit"] == 0
    assert done["commit"]["written"] is False
    assert done["pending"]["restart_needed"] == "art"
    assert done["pending"]["layout_walk"] is False
    assert done["pending"]["last_summary"]["filled"] == 2
    assert ev.restart_decision(events, 0) == "art"


@pytest.mark.scenario("nothing-to-do")
def test_a_clean_run_of_the_pending_kind_clears_the_write(backend) -> None:
    """Decision 31: a sync that exits 0 without ever waiting for the client
    proves there is nothing left to write for a pending sync write."""
    owned(backend)
    (Path(backend.settings_dir) / "pending.json").write_text(
        json.dumps({"restart_needed": "write", "layout_walk": False, "last_kind": "sync"})
    )
    run(start_and_wait(backend, backend.start_sync()))
    done = backend.emitted.of("sync_done")[0]
    assert done["exit"] == 0 and done["commit"] is None
    assert done["pending"]["restart_needed"] == "none"
    assert done["pending"]["last_kind"] == "sync"
    assert ev.restart_decision(load_fixture("nothing-to-do/sync.ndjson"), 0) == "none"


@pytest.mark.scenario("art-only")
def test_a_clean_sync_clears_a_pending_art_write_down_to_art(backend) -> None:
    """A sync patches icons too, so it settles a write left by an art run --
    and, having saved images itself, leaves "art" behind."""
    owned(backend)
    (Path(backend.settings_dir) / "pending.json").write_text(
        json.dumps({"restart_needed": "write", "layout_walk": False, "last_kind": "art"})
    )
    run(start_and_wait(backend, backend.start_sync()))
    done = backend.emitted.of("sync_done")[0]
    assert done["exit"] == 0
    assert done["pending"]["restart_needed"] == "art"


@pytest.mark.scenario("nothing-to-do")
def test_a_sync_never_clears_a_pending_remove(backend) -> None:
    """Only another remove can settle a pending remove: a sync never planned
    those removals, so it proves nothing about them -- and it must not take
    the pending write's name either, or the restart row would re-run
    start_sync and the sync after that would settle it as "same kind"."""
    owned(backend)
    (Path(backend.settings_dir) / "pending.json").write_text(
        json.dumps({"restart_needed": "write", "layout_walk": False, "last_kind": "remove"})
    )
    run(start_and_wait(backend, backend.start_sync()))
    done = backend.emitted.of("sync_done")[0]
    assert done["exit"] == 0
    assert done["pending"]["restart_needed"] == "write"
    assert done["pending"]["last_kind"] == "remove"  # still owned by the remove
    assert done["pending"]["last_summary"]["filled"] == 0  # Last sync row still moves


@pytest.mark.scenario("unreachable")
def test_a_failing_run_clears_nothing(backend) -> None:
    owned(backend)
    (Path(backend.settings_dir) / "pending.json").write_text(
        json.dumps({"restart_needed": "write", "layout_walk": False, "last_kind": "sync"})
    )
    run(start_and_wait(backend, backend.start_sync()))
    done = backend.emitted.of("sync_done")[0]
    assert done["exit"] == 3
    assert done["pending"]["restart_needed"] == "write"


@pytest.mark.scenario("nothing-to-do")
def test_a_pending_art_is_left_alone_by_a_run_that_saved_nothing(backend) -> None:
    owned(backend)
    (Path(backend.settings_dir) / "pending.json").write_text(
        json.dumps({"restart_needed": "art", "layout_walk": False})
    )
    run(start_and_wait(backend, backend.start_sync()))
    done = backend.emitted.of("sync_done")[0]
    assert done["exit"] == 0
    assert done["commit"] is None
    assert done["pending"]["restart_needed"] == "art"  # unchanged
    assert done["pending"]["last_summary"]["filled"] == 0


@pytest.mark.scenario("unreachable")
def test_unreachable_run(backend) -> None:
    owned(backend)
    run(start_and_wait(backend, backend.start_sync()))
    done = backend.emitted.of("sync_done")[0]
    assert done["exit"] == 3
    assert done["summary"] is None
    assert done["failure"] == {
        "error": "cli-error",
        "message": "sync: moonlight: host MY-GAMING-PC unreachable",
        "exit": 3,
    }
    assert done["pending"]["restart_needed"] == "none"
    assert done["pending"]["last_summary"] is None
    assert ev.restart_decision(load_fixture("unreachable/sync.ndjson"), 3) == "none"


@pytest.mark.scenario("stopped")
def test_stopped_with_images_sets_art(backend) -> None:
    owned(backend)
    run(start_and_wait(backend, backend.start_sync()))
    done = backend.emitted.of("sync_done")[0]
    assert done["exit"] == 130
    assert done["summary"]["stop_reason"] == "interrupted"
    assert done["pending"]["restart_needed"] == "art"
    assert ev.restart_decision(load_fixture("stopped/sync.ndjson"), 130) == "art"


@pytest.mark.scenario("refused")
def test_refused_wait_keeps_write(make_backend) -> None:
    backend = make_backend(env={"FAKE_CLI_WAIT_S": "0.5"})
    owned(backend)
    run(start_and_wait(backend, backend.start_sync()))
    relayed = backend.emitted.relayed()
    assert relayed[-1] == {
        "event": "error",
        "exit": 2,
        "message": "sync: steam did not exit; shortcuts.vdf not written",
    }
    done = backend.emitted.of("sync_done")[0]
    assert done["exit"] == 2
    assert done["pending"]["restart_needed"] == "write"
    assert done["pending"]["layout_walk"] is False
    assert done["pending"]["last_kind"] == "sync"


@pytest.mark.scenario("full-sync")
@pytest.mark.parametrize("mode", ["immediate", "deferred"])
def test_stop_during_the_wait_under_both_sigint_modes(make_backend, mode) -> None:
    backend = make_backend(env={"FAKE_CLI_SIGINT_DURING_WAIT": mode, "FAKE_CLI_WAIT_S": "1"})
    owned(backend)

    async def scenario() -> None:
        await backend.start_sync()
        await wait_until(
            lambda: any(e["event"] == "awaiting-steam-exit" for e in backend.emitted.relayed())
        )
        state = await backend.sync_state()
        assert state["running"] is True
        assert state["awaiting_exit"] is True
        assert await backend.stop_sync() == {"ok": True, "running": True}
        await backend.wait_for_run()

    run(scenario())
    done = backend.emitted.of("sync_done")[0]
    assert done["exit"] == (130 if mode == "immediate" else 2)
    assert done["commit"] is None  # nothing was written
    assert done["pending"]["restart_needed"] == "write"
    state = run(backend.sync_state())
    assert state["running"] is False
    assert state["awaiting_exit"] is False
    assert state["last_exit"] == done["exit"]


@pytest.mark.scenario("full-sync")
def test_stop_outside_the_wait_ends_in_130(make_backend) -> None:
    backend = make_backend(env={"FAKE_CLI_SLEEP_MS": "300"})
    owned(backend)

    async def scenario() -> None:
        await backend.start_sync()
        await wait_until(lambda: any(e["event"] == "plan" for e in backend.emitted.relayed()))
        await backend.stop_sync()
        await backend.wait_for_run()

    run(scenario())
    done = backend.emitted.of("sync_done")[0]
    assert done["exit"] == 130
    assert done["summary"]["stop_reason"] == "interrupted"
    assert backend.emitted.relayed()[-1] == {
        "event": "error",
        "exit": 130,
        # unprefixed, and the same for art and remove (spec 3.4.6)
        "message": "interrupted; resume with the same command",
    }
    assert run(backend.stop_sync()) == {"ok": True, "running": False}


@pytest.mark.scenario("full-sync")
def test_busy_guard(make_backend, steam_gone) -> None:
    backend = make_backend(env={"FAKE_CLI_SLEEP_MS": "100"})
    owned(backend)

    async def scenario() -> list[dict[str, Any]]:
        first = await backend.start_sync()
        results = [
            first,
            await backend.start_sync(),
            await backend.start_remove_all(),
            await backend.start_art_refetch(),
        ]
        steam_gone()
        await backend.wait_for_run()
        return results

    first, second, third, fourth = run(scenario())
    assert first == {"ok": True, "kind": "sync"}
    for busy in (second, third, fourth):
        assert busy["ok"] is False
        assert busy["error"] == "busy"
        assert busy["kind"] == "sync"
    assert len(backend.emitted.of("sync_done")) == 1
    # free again afterwards
    assert run(start_and_wait(backend, backend.start_sync()))["ok"] is True


@pytest.mark.scenario("full-sync")
def test_sync_state_during_and_after_a_run(make_backend, steam_gone) -> None:
    backend = make_backend(env={"FAKE_CLI_SLEEP_MS": "50"})
    owned(backend)
    before = run(backend.sync_state())
    assert before == {
        "ok": True,
        "running": False,
        "kind": None,
        "started": None,
        "opts": {},
        "awaiting_exit": False,
        "last_exit": None,
        "last_kind": None,
        "events": [],
    }

    async def scenario() -> dict[str, Any]:
        await backend.start_sync({"immediate_restart": True})
        await wait_until(lambda: len(backend.emitted.relayed()) >= 3)
        during = await backend.sync_state()
        steam_gone()
        await backend.wait_for_run()
        return during

    during = run(scenario())
    assert during["running"] is True
    assert during["kind"] == "sync"
    assert during["opts"] == {"retry_missing": False, "immediate_restart": True}
    assert during["started"]
    assert during["events"][0]["event"] == "start"
    after = run(backend.sync_state())
    assert after["running"] is False
    assert after["kind"] is None
    assert after["last_exit"] == 0
    assert after["last_kind"] == "sync"
    assert after["events"] == load_fixture("full-sync/sync.ndjson")


@pytest.mark.scenario("full-sync")
def test_sync_state_keeps_the_plan_beyond_the_ring(make_backend, steam_gone) -> None:
    backend = make_backend()
    backend.EVENT_RING = 3
    owned(backend)
    steam_gone()
    run(start_and_wait(backend, backend.start_sync()))
    events = run(backend.sync_state())["events"]
    assert [e["event"] for e in events] == ["plan", "awaiting-steam-exit", "commit", "summary"]


def test_remove_all_clears_layouts_and_pending_on_write(backend, steam_gone) -> None:
    owned(backend)
    layouts = Path(backend.settings_dir) / "layouts.json"
    layouts.write_text('{"version": 1, "entries": {}}')
    (Path(backend.settings_dir) / "pending.json").write_text(
        json.dumps({"restart_needed": "art", "layout_walk": True})
    )
    steam_gone()
    assert run(start_and_wait(backend, backend.start_remove_all())) == {
        "ok": True,
        "kind": "remove",
    }
    assert not layouts.exists()
    done = backend.emitted.of("sync_done")[0]
    assert done["kind"] == "remove"
    assert done["exit"] == 0
    assert done["pending"]["restart_needed"] == "none"
    assert done["pending"]["layout_walk"] is False
    assert done["pending"]["last_kind"] == "remove"
    assert done["summary"]["removed"] == 6
    ignore = json.loads(Path(settings_path(backend, "ignore.json")).read_text())
    assert ignore == []  # ignores are kept (never rewritten by remove)


def test_art_refetch_refused_without_art_commit(backend) -> None:
    result = run(backend.start_art_refetch())
    assert result["ok"] is False
    assert result["error"] == "cli-too-old"
    assert "--commit" in result["message"]
    assert not any(i[:2] == ["--json", "art"] for i in backend.harness.argv())


def test_art_refetch_runs_with_art_commit(make_backend) -> None:
    backend = make_backend(env={"FAKE_CLI_ART_COMMIT": "1"})
    assert run(start_and_wait(backend, backend.start_art_refetch())) == {
        "ok": True,
        "kind": "art",
    }
    done = backend.emitted.of("sync_done")[0]
    assert done["kind"] == "art"
    assert done["pending"]["restart_needed"] == "art"  # 5 images, no write
    assert done["pending"]["last_kind"] == "art"
    assert {p["kind"] for p in backend.emitted.of("sync_event")} == {"art"}


def test_start_sync_needs_owned_apps(backend) -> None:
    result = run(backend.start_sync())
    assert result["ok"] is False
    assert result["error"] == "owned-apps-missing"
    assert run(backend.status())["error"] == "owned-apps-missing"


def test_start_sync_rejects_bad_opts(backend) -> None:
    owned(backend)
    assert run(backend.start_sync({"retry_missing": "yes"}))["error"] == "bad-request"
    assert run(backend.start_sync("fast"))["error"] == "bad-request"


@pytest.mark.scenario("full-sync")
def test_non_json_stdout_is_logged_not_relayed(make_backend, steam_gone, tmp_path) -> None:
    backend = make_backend(env={"FAKE_CLI_NOISE": "Traceback? not JSON at all"})
    owned(backend)
    steam_gone()
    run(start_and_wait(backend, backend.start_sync()))
    assert backend.emitted.relayed() == load_fixture("full-sync/sync.ndjson")
    log = (tmp_path / "logs" / "moonlight-sync.log").read_text()
    assert "non-JSON stdout line skipped: Traceback? not JSON at all" in log


@pytest.mark.scenario("full-sync")
def test_stderr_is_appended_to_the_log(make_backend, steam_gone, tmp_path) -> None:
    backend = make_backend(env={"FAKE_CLI_STDERR": "moonlight: warming up the host"})
    owned(backend)
    steam_gone()
    run(start_and_wait(backend, backend.start_sync()))
    log = (tmp_path / "logs" / "moonlight-sync.log").read_text()
    assert "moonlight: warming up the host\n" in log
    assert "sync: awaiting-steam-exit\n" in log  # the fake's human lines, verbatim
    assert "run: " in log


@pytest.mark.scenario("full-sync")
def test_unload_interrupts_a_running_child(make_backend) -> None:
    backend = make_backend(env={"FAKE_CLI_SLEEP_MS": "300"})
    owned(backend)

    async def scenario() -> None:
        await backend.start_sync()
        await wait_until(lambda: len(backend.emitted.relayed()) >= 1)
        await backend.unload()

    run(scenario())
    done = backend.emitted.of("sync_done")
    assert len(done) == 1
    assert done[0]["exit"] == 130
    assert run(backend.sync_state())["running"] is False


def test_unload_without_a_run_is_a_no_op(backend) -> None:
    run(backend.unload())
    assert backend.emitted.calls == []


# ----------------------------------------------------------------------
# collecting runs: parsing and failures


def test_status_parsing(backend) -> None:
    owned(backend)
    result = run(backend.status())
    entries = [e for e in load_fixture("common/status.ndjson") if e["event"] == "entry"]
    assert result == {"ok": True, "entries": entries, "notes": []}


def test_list_parsing(backend) -> None:
    owned(backend)
    result = run(backend.list_apps())
    apps = [e for e in load_fixture("common/list.ndjson") if e["event"] == "app"]
    assert result == {"ok": True, "apps": apps, "host": "MY-GAMING-PC", "count": 7, "notes": []}


def test_list_cached_parsing(backend) -> None:
    owned(backend)
    result = run(backend.list_cached("MY-GAMING-PC"))
    assert result["ok"] is True
    assert all(app["cached"] for app in result["apps"])


@pytest.mark.scenario("unreachable")
def test_list_apps_unreachable_is_cli_error(backend) -> None:
    owned(backend)
    result = run(backend.list_apps())
    assert result["ok"] is False
    assert result["error"] == "cli-error"
    assert result["exit"] == 3
    assert result["message"] == "list: moonlight: host MY-GAMING-PC unreachable"
    assert result["events"][0]["event"] == "start"


def test_hosts_first_run(make_backend) -> None:
    """`host show` with nothing configured exits 1 with the CLI's pinned
    wording (spec 3.4.6, the `host` bullet): "no host configured" is
    contractual, and the plugin reads it rather than treating exit 1 as a
    failure. The fixture carries the CLI's exact message."""
    message = next(
        json.loads(line)["message"]
        for line in (FIXTURES / "common" / "host-none.ndjson").read_text().splitlines()
        if line.startswith("{") and json.loads(line)["event"] == "error"
    )
    assert message == (
        "host: no host configured; pass --host, run `host set NAME`, "
        "or set `host` in ~/.config/moonlight-steam-sync/config.toml"
    )
    backend = make_backend(env={"FAKE_CLI_FIXTURE_HOST_SHOW": "host-none"})
    shown = run(backend.hosts())
    assert shown == {
        "ok": True,
        "active": None,
        "source": None,
        "cached_hosts": [],
        "known": [],
    }
    assert run(backend.get_settings())["settings"]["hosts"] == []


def test_check_host_memoises_for_ten_seconds(backend, monkeypatch) -> None:
    owned(backend)
    backend.harness.clear()
    first = run(backend.check_host("MY-GAMING-PC"))
    second = run(backend.check_host("MY-GAMING-PC"))
    assert first == second
    assert first["reachable"] is True
    assert first["count"] == 7
    assert first["ignored"] == 1
    assert first["host"] == "MY-GAMING-PC"
    assert len(backend.harness.argv()) == 1
    run(backend.check_host("MY-GAMING-PC", True))
    assert len(backend.harness.argv()) == 2
    # the memo expires after 10 s of monotonic time
    import moonlight_sync.backend as backend_module

    real = backend_module.time.monotonic
    monkeypatch.setattr(backend_module.time, "monotonic", lambda: real() + 11)
    run(backend.check_host("MY-GAMING-PC"))
    assert len(backend.harness.argv()) == 3


def test_list_apps_refreshes_the_memo(backend) -> None:
    owned(backend)
    run(backend.list_apps())
    backend.harness.clear()
    assert run(backend.check_host("MY-GAMING-PC"))["reachable"] is True
    assert backend.harness.argv() == []


@pytest.mark.scenario("unreachable")
def test_check_host_unreachable_with_last_seen(backend) -> None:
    owned(backend)
    result = run(backend.check_host("OFFICE-PC"))
    assert result["ok"] is True
    assert result["reachable"] is False
    assert result["exit"] == 3
    assert result["message"] == "list: moonlight: host MY-GAMING-PC unreachable"
    assert result["last_seen"] == "2026-09-10T20:15:00Z"
    assert result["cached_count"] == 4
    assert result["checked_at"].endswith("Z")


@pytest.mark.scenario("unreachable")
def test_check_host_never_synced(backend) -> None:
    owned(backend)
    result = run(backend.check_host("LIVING-ROOM-PC"))
    assert result["reachable"] is False
    assert result["last_seen"] is None
    assert result["cached_count"] is None


def test_any_other_exit_1_from_host_show_is_still_a_failure(make_backend, tmp_path) -> None:
    """Only the contractual "no host configured" is read as "first run"."""
    fixture = tmp_path / "fx"
    fixture.mkdir()
    (fixture / "host.ndjson").write_text(
        '{"event":"start","schema":1,"version":"0.3.0","command":"host"}\n'
        '{"event":"error","exit":1,"message":"host: cannot read the host cache"}\n'
    )
    backend = make_backend(
        env={"FAKE_CLI_FIXTURES": os.pathsep.join([str(fixture), str(FIXTURES / "common")])}
    )
    failed = run(backend.hosts())
    assert failed["ok"] is False and failed["error"] == "cli-error"
    assert failed["message"] == "host: cannot read the host cache"


def test_add_host_success_on_first_run_makes_it_active(make_backend) -> None:
    backend = make_backend(env={"FAKE_CLI_FIXTURE_HOST_SHOW": "host-none"})
    owned(backend)
    backend.harness.clear()
    result = run(backend.add_host("  OFFICE-PC "))
    assert result == {"ok": True, "count": 7, "made_active": True}
    assert run(backend.get_settings())["settings"]["hosts"] == ["OFFICE-PC"]
    argvs = backend.harness.argv()
    assert argvs[0][:4] == ["--json", "list", "--host", "OFFICE-PC"]
    assert argvs[-1] == ["--json", "host", "set", "OFFICE-PC"]


def test_add_host_with_an_active_host_does_not_switch(backend) -> None:
    owned(backend)
    run(backend.forget_host("OFFICE-PC"))
    backend.harness.clear()
    result = run(backend.add_host("OFFICE-PC"))
    assert result == {"ok": True, "count": 7, "made_active": False}
    assert run(backend.get_settings())["settings"]["hosts"] == ["MY-GAMING-PC", "OFFICE-PC"]
    assert ["--json", "host", "set", "OFFICE-PC"] not in backend.harness.argv()
    # adding it again does not duplicate it (case-insensitive)
    run(backend.add_host("office-pc"))
    assert run(backend.get_settings())["settings"]["hosts"] == ["MY-GAMING-PC", "OFFICE-PC"]


@pytest.mark.scenario("unreachable")
def test_add_host_unreachable_adds_nothing(backend) -> None:
    owned(backend)
    run(backend.forget_host("OFFICE-PC"))
    result = run(backend.add_host("OFFICE-PC"))
    assert result["ok"] is False
    assert result["error"] == "cli-error"
    assert result["exit"] == 3
    assert run(backend.get_settings())["settings"]["hosts"] == ["MY-GAMING-PC"]


def test_add_host_validates_the_name(backend) -> None:
    owned(backend)
    for bad in ("", "   ", "MY GAMING PC", "a/b", None):
        assert run(backend.add_host(bad))["error"] == "bad-request"


def test_forget_host_refuses_the_active_host(backend) -> None:
    result = run(backend.forget_host("my-gaming-pc"))
    assert result["ok"] is False
    assert result["error"] == "bad-request"
    assert result["message"] == "switch to another host first"
    assert run(backend.get_settings())["settings"]["hosts"] == ["MY-GAMING-PC", "OFFICE-PC"]


def test_set_host_requires_a_known_host(backend) -> None:
    result = run(backend.set_host("LIVING-ROOM-PC"))
    assert result["error"] == "bad-request"
    assert run(backend.set_host("office-pc"))["ok"] is True
    assert backend.harness.argv()[-1] == ["--json", "host", "set", "OFFICE-PC"]


def test_write_owned_apps(backend) -> None:
    assert run(backend.write_owned_apps(12345678, {})) == {
        "ok": False,
        "error": "owned-apps-empty",
        "message": "Steam library not loaded",
    }
    assert not Path(settings_path(backend, "owned-apps.json")).exists()
    for steamid3, apps in (
        ("12345678", {"620": "Portal 2"}),
        (True, {"620": "Portal 2"}),
        (12345678, {"portal": "Portal 2"}),
        (12345678, {"620": 620}),
        (12345678, ["620"]),
    ):
        assert run(backend.write_owned_apps(steamid3, apps))["error"] == "bad-request"
    assert run(backend.write_owned_apps(12345678, {"620": "Portal 2", 400: "Portal"})) == {
        "ok": True,
        "count": 2,
    }
    data = json.loads(Path(settings_path(backend, "owned-apps.json")).read_text())
    assert data == {
        "version": 1,
        "steamid3": 12345678,
        "apps": {"620": "Portal 2", "400": "Portal"},
    }


def test_cli_too_old_short_circuits_without_a_child(make_backend) -> None:
    backend = make_backend(env={"FAKE_CLI_VERSION": "0.2.0"})
    owned(backend)
    assert backend.harness.argv() == [["--version"]]
    result = run(backend.status())
    assert result["error"] == "cli-too-old"
    assert result["installed"] == "0.2.0"
    assert result["minimum"] == "0.3.0"
    assert run(backend.start_sync())["error"] == "cli-too-old"
    assert backend.harness.argv() == [["--version"]]
    assert run(backend.cli_version())["too_old"] is True


def test_cli_protocol_when_the_cli_rejects_a_flag(backend) -> None:
    owned(backend)
    backend.env["FAKE_CLI_VERSION"] = "0.2.0"  # reports 0.3.0 at startup, rejects now
    result = run(backend.status())
    assert result["ok"] is False
    assert result["error"] == "cli-protocol"
    assert result["exit"] == 2
    assert "unrecognized arguments: --json --owned-apps" in result["stderr"]
    assert result["message"] == "The installed CLI did not understand the request (see the log)"


def test_cli_protocol_for_a_long_run(backend) -> None:
    owned(backend)
    backend.env["FAKE_CLI_VERSION"] = "0.2.0"
    run(start_and_wait(backend, backend.start_sync()))
    done = backend.emitted.of("sync_done")[0]
    assert done["exit"] == 2
    assert done["failure"]["error"] == "cli-protocol"
    assert backend.emitted.of("sync_event") == []


def test_missing_fixture_is_an_unexpected_call(backend) -> None:
    owned(backend)
    run(start_and_wait(backend, backend.start_sync()))  # common/ has no sync.ndjson
    assert backend.emitted.of("sync_done")[0]["exit"] == 99


def test_timeout(make_backend) -> None:
    backend = make_backend(env={"FAKE_CLI_SLEEP_MS": "5000"})
    owned(backend)
    backend.TIMEOUT_SHORT = 1.0
    result = run(backend.status())
    assert result["ok"] is False
    assert result["error"] == "timeout"
    assert result["message"] == "timed out after 1 s"


def reap(pidfile: Path) -> None:
    if pidfile.exists():
        for pid in pidfile.read_text().split():
            with contextlib.suppress(ProcessLookupError):
                os.kill(int(pid), signal.SIGKILL)


def grandchild(backend, tmp_path: Path) -> Path:
    """A ``sleep`` grandchild that inherits the fake's pipes and outlives it."""
    pidfile = tmp_path / "grandchild.pid"
    backend.KILL_GRACE = 0.3
    backend.env.update(FAKE_CLI_GRANDCHILD_S="30", FAKE_CLI_GRANDCHILD_PIDFILE=str(pidfile))
    return pidfile


def test_pipes_held_by_a_grandchild_do_not_hang_a_call(backend, tmp_path) -> None:
    owned(backend)
    pidfile = grandchild(backend, tmp_path)
    try:
        started = time.monotonic()
        result = run(backend.status())
        elapsed = time.monotonic() - started
    finally:
        reap(pidfile)
    assert result["ok"] is True
    assert elapsed < 5
    assert backend._procs == set()
    log = (tmp_path / "logs" / "moonlight-sync.log").read_text()
    assert "output pipes are still open after it exited" in log


def test_timeout_with_a_grandchild_holding_the_pipes(backend, tmp_path) -> None:
    owned(backend)
    pidfile = grandchild(backend, tmp_path)
    backend.env["FAKE_CLI_SLEEP_MS"] = "5000"
    backend.TIMEOUT_SHORT = 0.5
    try:
        started = time.monotonic()
        result = run(backend.status())
        elapsed = time.monotonic() - started
    finally:
        reap(pidfile)
    assert result["error"] == "timeout"
    assert elapsed < 5
    assert backend._procs == set()


def test_a_stdout_line_over_the_limit_kills_and_reaps_the_child(backend, tmp_path) -> None:
    owned(backend)
    backend.env["FAKE_CLI_NOISE_BYTES"] = str(5 * 1024 * 1024)
    result = run(backend.status())
    assert result["ok"] is False
    assert result["error"] == "io"
    assert "unreadable CLI output" in result["message"]
    assert backend._procs == set()


@pytest.mark.scenario("full-sync")
def test_a_run_whose_output_is_unreadable_still_ends_with_sync_done(backend, tmp_path) -> None:
    owned(backend)
    backend.env["FAKE_CLI_NOISE_BYTES"] = str(5 * 1024 * 1024)
    run(start_and_wait(backend, backend.start_sync()))
    done = backend.emitted.of("sync_done")[0]
    assert done["failure"]["error"] == "io"
    assert done["exit"] != 0
    assert run(backend.sync_state())["running"] is False


def test_doctor_parses_labels(backend) -> None:
    result = run(backend.doctor())
    assert result["ok"] is True
    assert result["lines"]["active host"] == "MY-GAMING-PC (state file)"
    assert result["lines"]["sgdb api key"] == "present"
    assert result["lines"]["session"].startswith("gamescope")
    assert result["raw"].startswith("python:")


def _pending_after(previous, kind, events, exit_code, now="2026-09-20T12:00:00Z"):
    return ev.next_pending(previous, kind=kind, events=events, exit_code=exit_code, now=now)


def test_a_pending_remove_write_keeps_its_name_across_syncs() -> None:
    """Decision 31, the sequence the per-run tests cannot show: `last_kind`
    and `last_plan` name the run that owns the pending write, so no number
    of syncs can rename -- and then settle -- a remove's write."""
    nothing = load_fixture("nothing-to-do/sync.ndjson")
    remove_plan = {"event": "plan", "to_remove": 6}
    pending = {
        "restart_needed": "write",
        "layout_walk": False,
        "since": "2026-09-20T10:00:00Z",
        "last_summary": None,
        "last_plan": remove_plan,
        "last_kind": "remove",
    }

    after_one = _pending_after(pending, "sync", nothing, 0)
    assert after_one["restart_needed"] == "write"
    assert after_one["last_kind"] == "remove"
    assert after_one["last_plan"] == remove_plan
    assert after_one["last_summary"] == ev.last_of(nothing, "summary")  # Last sync moved

    after_two = _pending_after(after_one, "sync", nothing, 0)
    assert after_two["restart_needed"] == "write"
    assert after_two["last_kind"] == "remove"
    assert after_two["last_plan"] == remove_plan

    # only a remove settles it, and then it owns the state
    settled = _pending_after(
        after_two,
        "remove",
        [{"event": "start"}, {"event": "summary", "filled": 0, "removed": 0}],
        0,
    )
    assert settled["restart_needed"] == "none"
    assert settled["last_kind"] == "remove"
    assert settled["last_plan"] is None  # that remove had nothing to plan


def test_a_run_that_sets_or_settles_the_write_does_take_its_name() -> None:
    """The other half of the rule: last_kind moves whenever restart_needed
    does."""
    full = load_fixture("full-sync/sync.ndjson")
    refused = load_fixture("refused/sync.ndjson")
    empty = {"restart_needed": "none", "layout_walk": False, "last_kind": None, "last_plan": None}

    awaiting = _pending_after(empty, "sync", refused, 130)
    assert awaiting["restart_needed"] == "write"
    assert awaiting["last_kind"] == "sync"
    assert awaiting["last_plan"] == ev.last_of(refused, "plan")

    written = _pending_after(awaiting, "sync", full, 0)
    assert written["restart_needed"] == "none"
    assert written["layout_walk"] is True
    assert written["last_kind"] == "sync"

    art = _pending_after(empty, "art", load_fixture("art-only/sync.ndjson"), 0)
    assert art["restart_needed"] == "art"
    assert art["last_kind"] == "art"


# ----------------------------------------------------------------------
# settings, pending, stubs, never raising


def test_settings_round_trip_and_validation(backend) -> None:
    result = run(backend.set_settings({"restart_countdown_s": 0, "copy_layouts": False}))
    assert result["ok"] is True
    assert result["settings"]["restart_countdown_s"] == 0
    assert result["settings"]["copy_layouts"] is False
    assert run(backend.get_settings())["settings"]["restart_countdown_s"] == 0
    at_max = run(backend.set_settings({"restart_countdown_s": 30}))
    assert at_max["settings"]["restart_countdown_s"] == 30
    for bad in (
        {"restart_countdown_s": 31},
        {"restart_countdown_s": 61},
        {"restart_countdown_s": -1},
        {"restart_countdown_s": "5"},
        {"copy_layouts": 1},
        {"layout_strategy": "mirror"},
        {"hosts": ["X"]},
        {"surprise": True},
        "not an object",
    ):
        failed = run(backend.set_settings(bad))
        assert failed["ok"] is False
        assert failed["error"] == "bad-request"
    assert (
        run(backend.set_settings({"layout_strategy": "picker"}))["settings"]["layout_strategy"]
        == "picker"
    )


def test_get_ignored_is_sorted(backend) -> None:
    Path(settings_path(backend, "ignore.json")).write_text('["Steam Big Picture", "Desktop"]')
    assert run(backend.get_ignored()) == {"ok": True, "ignored": ["Desktop", "Steam Big Picture"]}


def test_pending_and_clear_pending(backend) -> None:
    assert run(backend.pending()) == {
        "ok": True,
        "restart_needed": "none",
        "layout_walk": False,
        "since": None,
        "last_summary": None,
        "last_plan": None,
        "last_kind": None,
    }
    (Path(backend.settings_dir) / "pending.json").write_text(
        json.dumps({"restart_needed": "art", "layout_walk": True, "since": "2026-09-18T14:02:00Z"})
    )
    assert run(backend.clear_pending("restart_needed"))["restart_needed"] == "none"
    assert run(backend.pending())["layout_walk"] is True
    assert run(backend.clear_pending("layout_walk"))["layout_walk"] is False
    assert run(backend.clear_pending("everything"))["error"] == "bad-request"


def test_pr6_and_pr7_stubs(backend) -> None:
    not_yet = {"ok": False, "error": "bad-request", "message": "not yet"}
    assert run(backend.search("Hades II")) == not_yet
    assert run(backend.pin("Hades II", 1145350, None, False)) == not_yet
    assert run(backend.unpin("Hades II")) == not_yet
    assert run(backend.set_ignored("Desktop", True)) == not_yet
    assert run(backend.layouts()) == not_yet
    assert run(backend.record_layout(1, 2, "copied", None)) == not_yet


def test_log_tail(backend) -> None:
    result = run(backend.log_tail(3))
    assert result["ok"] is True
    assert len(result["lines"]) == 3
    assert run(backend.log_tail(0))["error"] == "bad-request"
    assert len(run(backend.log_tail(10_000))["lines"]) <= 500


def test_callables_return_failures_instead_of_raising(backend, monkeypatch) -> None:
    def boom(*args, **kwargs):
        raise PermissionError(13, "Permission denied", "/settings/settings.json")

    monkeypatch.setattr(backend.store, "settings", boom)
    result = run(backend.get_settings())
    assert result["ok"] is False
    assert result["error"] == "io"
    assert "Permission denied" in result["message"]

    def bug(*args, **kwargs):
        raise RuntimeError("unexpected")

    monkeypatch.setattr(backend.store, "pending", bug)
    result = run(backend.pending())
    assert result == {"ok": False, "error": "bad-request", "message": "internal error: unexpected"}
    assert run(backend.check_host(None))["error"] == "bad-request"
    assert run(backend.list_cached(""))["error"] == "bad-request"
