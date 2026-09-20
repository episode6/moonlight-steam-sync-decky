"""Tests for probes/run_probes.py: argument handling, --help, the refusals,
the gap computation from a recorded pgrep log, --markdown rendering, exit 3
on a closed port, and the defensive JavaScript (run under node when it is
installed). The DevTools connection sits behind FakeDevTools."""

from __future__ import annotations

import io
import json
import re
import shutil
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

import run_probes
from run_probes import (
    EXIT_FAIL,
    EXIT_OK,
    EXIT_PORT_CLOSED,
    EXIT_REFUSED,
    PortClosed,
    Runner,
    build_expression,
    compute_gaps,
    main,
    parse_watch_log,
    render_markdown,
    watch_steam,
)

FIXTURES = Path(__file__).with_name("fixtures")
SHORTCUT = 0x80000000 + 12345
REAL_GAME = 1245620


class FakeDevTools:
    """Records every evaluate() and answers with canned results."""

    def __init__(self, results: dict[str, object] | None = None, closed_for: int = 0) -> None:
        self.results = results or {}
        self.calls: list[tuple[str, dict]] = []
        self.target_calls = 0
        self.closed_for = closed_for  # how many targets() calls raise PortClosed first

    def targets(self):
        self.target_calls += 1
        if self.target_calls <= self.closed_for:
            raise PortClosed("connection refused")
        return [{"title": "SharedJSContext", "webSocketDebuggerUrl": "ws://fake/1"}, {"title": "Steam Big Picture Mode"}]

    def shared_js_context(self):
        return self.targets()[0]

    def evaluate(self, name, params=None, *, timeout_s=90.0):
        self.calls.append((name, dict(params or {})))
        if name in self.results:
            return self.results[name]
        return {"probe": name, "fake": True}


def run(argv, tmp_path, fake=None, **kwargs):
    fake = fake or FakeDevTools()
    out, err = io.StringIO(), io.StringIO()
    code = main(
        ["--results", str(tmp_path / "probe-results.json"), *argv],
        devtools_factory=lambda host, port: fake,
        out=out,
        err=err,
        v3_log_path=tmp_path / "v3.log",
        **kwargs,
    )
    return code, out.getvalue(), err.getvalue(), fake


# ---- argument handling and --help -------------------------------------------


def test_help_documents_every_subcommand_without_websockets(tmp_path):
    env = {"PYTHONPATH": str(no_websockets_dir(tmp_path)), "PATH": "/usr/bin:/bin"}
    proc = subprocess.run(
        [sys.executable, str(Path(run_probes.__file__)), "--help"],
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
    for name in ("v1", "v2", "v3", "v4", "v5", "all", "--markdown", "--restore", "--run", "--yes", "--controller-index"):
        assert name in proc.stdout, name
    assert "0x80000000" in proc.stdout
    assert "is Decky installed and is Steam in Game Mode?" in proc.stdout


def no_websockets_dir(tmp_path: Path) -> Path:
    """A directory on PYTHONPATH whose ``websockets`` module raises on import,
    proving --help never imports it even when a venv is around."""
    d = tmp_path / "no_websockets"
    d.mkdir(exist_ok=True)
    (d / "websockets.py").write_text("raise ImportError('websockets must not be imported for --help')\n")
    return d


def test_no_subcommand_is_a_usage_error(tmp_path):
    with pytest.raises(SystemExit) as exc:
        run([], tmp_path)
    assert exc.value.code == 2


def test_v1_parses_comma_separated_appids(tmp_path):
    code, out, err, fake = run(["v1", "--appids", "1245620, 2379780,1145360"], tmp_path)
    assert code == EXIT_OK, err
    assert fake.calls == [("v1", {"appids": [1245620, 2379780, 1145360], "candidate_wait_ms": 4000})]
    printed = json.loads(out)
    assert printed["probe"] == "v1"
    assert printed["args"] == {"appids": [1245620, 2379780, 1145360], "controller_index": None}


def test_controller_index_override_is_passed_to_v1_and_v2(tmp_path):
    code, out, err, fake = run(["v1", "--appids", "1", "--controller-index", "15"], tmp_path)
    assert code == EXIT_OK, err
    assert fake.calls[0][1]["controller_index"] == 15
    code, out, err, fake = run(["v2", "--shortcut", str(SHORTCUT), "--url", "workshop://1", "--controller-index", "0"], tmp_path)
    assert code == EXIT_OK, err
    assert fake.calls[0][1]["controller_index"] == 0
    code, out, err, fake = run(["all", "--appids", "1", "--controller-index", "3"], tmp_path)
    assert code == EXIT_OK, err
    assert fake.calls[0][1]["controller_index"] == 3
    with pytest.raises(SystemExit):
        run(["v1", "--appids", "1", "--controller-index", "-1"], tmp_path)


def test_v1_rejects_non_numeric_appids(tmp_path):
    with pytest.raises(SystemExit) as exc:
        run(["v1", "--appids", "1245620,abc"], tmp_path)
    assert exc.value.code == 2


def test_v4_prints_one_json_object_and_appends_it(tmp_path):
    fake = FakeDevTools({"v4": {"probe": "v4", "total": 3, "steamid3": "12345678"}})
    code, out, err, _ = run(["v4"], tmp_path, fake, steam_root=tmp_path / "no-steam")
    assert code == EXIT_OK, err
    assert json.loads(out)["result"]["total"] == 3
    assert json.loads(out)["result"]["userdata_check"]["match"] is None  # no userdata dir: unchecked, not "no"
    code, _out2, _, _ = run(["v4"], tmp_path, fake, steam_root=tmp_path / "no-steam")
    assert code == EXIT_OK
    results = json.loads((tmp_path / "probe-results.json").read_text())
    assert [r["probe"] for r in results] == ["v4", "v4"]
    assert all("when" in r for r in results)


def test_v4_checks_the_userdata_folder_on_the_deck(tmp_path):
    root = tmp_path / "Steam"
    (root / "userdata" / "12345678").mkdir(parents=True)
    (root / "userdata" / "0").mkdir()
    (root / "userdata" / "not-an-id").mkdir()
    assert run_probes.check_userdata_folder("12345678", root) == {"match": True, "folders": 2}
    assert run_probes.check_userdata_folder("99", root) == {"match": False, "folders": 2}
    assert run_probes.check_userdata_folder("99", tmp_path / "missing")["match"] is None
    fake = FakeDevTools({"v4": {"probe": "v4", "steamid3": "12345678", "strSteamID": "76561197972610406"}})
    code, out, err, _ = run(["v4"], tmp_path, fake, steam_root=root)
    assert code == EXIT_OK, err
    assert json.loads(out)["result"]["userdata_check"] == {"match": True, "folders": 2}


# ---- the refusals ------------------------------------------------------------


def test_v2_refuses_without_url_and_touches_nothing(tmp_path):
    code, out, err, fake = run(["v2", "--shortcut", str(SHORTCUT)], tmp_path)
    assert code == EXIT_REFUSED
    assert "--url" in err
    assert fake.calls == [] and fake.target_calls == 0
    assert not (tmp_path / "probe-results.json").exists()


def test_v2_refuses_appid_below_0x80000000(tmp_path):
    code, out, err, fake = run(["v2", "--shortcut", str(REAL_GAME), "--url", "workshop://123"], tmp_path)
    assert code == EXIT_REFUSED
    assert "0x80000000" in err and "never a real game" in err
    assert fake.calls == []


def test_v2_refuses_a_non_workshop_url(tmp_path):
    code, out, err, fake = run(["v2", "--shortcut", str(SHORTCUT), "--url", "template://x.vdf"], tmp_path)
    assert code == EXIT_REFUSED
    assert "workshop://" in err
    assert fake.calls == []


def test_v2_runs_with_url_on_a_shortcut_and_passes_restore(tmp_path):
    fake = FakeDevTools({"v2": {"probe": "v2", "stuck": True, "before": {"URL": "default://x"}, "after": {"URL": "workshop://123"}}})
    code, out, err, fake = run(["v2", "--shortcut", str(SHORTCUT), "--url", "workshop://123", "--restore"], tmp_path, fake)
    assert code == EXIT_OK, err
    (name, params), = fake.calls
    assert name == "v2"
    assert params["shortcut"] == SHORTCUT and params["url"] == "workshop://123" and params["restore"] is True
    assert "shortcut_min" not in params  # the page hardcodes the bound (test_v2_js_refuses_a_real_game_...)


def test_v5_without_run_never_asks_the_page_to_run(tmp_path):
    code, out, err, fake = run(["v5", "--shortcut", str(SHORTCUT)], tmp_path)
    assert code == EXIT_OK, err
    assert fake.calls == [("v5", {"shortcut": SHORTCUT, "run": False})]


def test_v5_run_passes_the_flag(tmp_path):
    code, out, err, fake = run(["v5", "--shortcut", str(SHORTCUT), "--run"], tmp_path)
    assert code == EXIT_OK, err
    assert fake.calls == [("v5", {"shortcut": SHORTCUT, "run": True})]


def test_v3_refuses_without_yes_when_stdin_is_not_a_tty(tmp_path):
    code, out, err, fake = run(["v3"], tmp_path, stdin=io.StringIO(""))
    assert code == EXIT_REFUSED
    assert "--yes" in err
    assert fake.calls == []


def test_v3_refuses_when_the_prompt_is_declined(tmp_path):
    class Tty(io.StringIO):
        def isatty(self):
            return True

    code, out, err, fake = run(["v3"], tmp_path, stdin=Tty("n\n"))
    assert code == EXIT_REFUSED
    assert "not confirmed" in err
    assert fake.calls == []


def test_all_skips_the_state_changing_probes_without_their_flags(tmp_path):
    code, out, err, fake = run(["all", "--appids", "1,2", "--shortcut", str(SHORTCUT)], tmp_path)
    assert code == EXIT_OK, err
    assert [c[0] for c in fake.calls] == ["v1", "v4", "v5"]
    assert fake.calls[2][1]["run"] is False
    printed = json.loads(out)
    assert printed["probe"] == "all"
    assert set(printed["ran"]) == {"v1", "v4", "v5"}
    assert printed["skipped"] == {"v2": "no --url", "v3": "no --yes"}
    results = json.loads((tmp_path / "probe-results.json").read_text())
    assert [r["probe"] for r in results] == ["v1", "v4", "v5"]


def test_all_without_shortcut_skips_v5_and_v2(tmp_path):
    code, out, err, fake = run(["all"], tmp_path)
    assert code == EXIT_OK, err
    assert [c[0] for c in fake.calls] == ["v4"]
    assert json.loads(out)["skipped"] == {"v1": "no --appids", "v5": "no --shortcut", "v2": "no --shortcut", "v3": "no --yes"}


def test_all_refuses_v2_on_a_real_game_but_runs_the_rest(tmp_path):
    code, out, err, fake = run(["all", "--shortcut", str(REAL_GAME), "--url", "workshop://1"], tmp_path)
    assert code == EXIT_OK, err
    assert [c[0] for c in fake.calls] == ["v4", "v5"]
    assert "0x80000000" in json.loads(out)["skipped"]["v2"]


def test_all_refuses_a_malformed_url_before_running_any_probe(tmp_path):
    """The workshop:// shape is checked up front, with the other two
    refusals, so `all` never runs v1/v4/v5 and then dies on v2's --url."""
    code, _out, err, fake = run(["all", "--appids", "1", "--shortcut", str(SHORTCUT), "--url", "template://x.vdf"], tmp_path)
    assert code == EXIT_REFUSED
    assert "workshop://" in err
    assert fake.calls == []
    assert not (tmp_path / "probe-results.json").exists()


def test_v2_refuses_a_malformed_url_before_touching_the_port(tmp_path):
    code, _out, err, fake = run(["v2", "--shortcut", str(SHORTCUT), "--url", "workshop://abc"], tmp_path)
    assert code == EXIT_REFUSED
    assert "workshop://" in err
    assert fake.calls == [] and fake.target_calls == 0


# ---- the gap computation -----------------------------------------------------


def test_gaps_from_the_recorded_pgrep_log():
    samples = parse_watch_log((FIXTURES / "pgrep-log.txt").read_text())
    assert len(samples) == 14  # start/summary/shutdown/unrelated lines are ignored
    assert samples[0] == (0, [1234, 1240])
    gaps = compute_gaps(samples)
    assert gaps == [
        {"empty_at_ms": 3511, "back_at_ms": 7019, "gap_ms": 3508, "empty_samples": 3},
        {"empty_at_ms": 9239, "back_at_ms": 9340, "gap_ms": 101, "empty_samples": 1},
    ]


def test_gap_still_open_at_the_end_is_reported():
    gaps = compute_gaps([(0, [1]), (100, []), (200, [])])
    assert gaps == [{"empty_at_ms": 100, "back_at_ms": None, "gap_ms": None, "empty_samples": 2}]
    assert compute_gaps([(0, [1]), (100, [1])]) == []
    assert compute_gaps([]) == []


def test_pgrep_error_samples_are_not_gaps():
    """rc 2/3 (pgrep failed) or -1 (could not run) with empty stdout says
    nothing about Steam: neither opens nor closes a gap."""
    assert run_probes.sample_pids(0, "10\n") == [10]
    assert run_probes.sample_pids(1, "") == []
    assert run_probes.sample_pids(2, "") is None
    assert run_probes.sample_pids(3, "pgrep: error while loading shared libraries") is None
    assert run_probes.sample_pids(-1, "pgrep failed: FileNotFoundError") is None
    # an error sample alone, or between present samples, is no gap
    assert compute_gaps([(0, [1]), (100, None), (200, [1])]) == []
    assert compute_gaps([(0, None), (100, None)]) == []
    # an error sample inside a real gap neither closes it nor counts as empty
    assert compute_gaps([(0, [1]), (100, []), (200, None), (300, []), (400, [2])]) == [
        {"empty_at_ms": 100, "back_at_ms": 400, "gap_ms": 300, "empty_samples": 2}
    ]
    # the log parser maps rc not in (0, 1) to an error sample
    parsed = parse_watch_log("x sample t=0 rc=0 pids=10\nx sample t=100 rc=2 pids=error\nx sample t=200 rc=3 pids=-\nx sample t=300 rc=1 pids=-\n")
    assert parsed == [(0, [10]), (100, None), (200, None), (300, [])]


def test_watch_steam_logs_a_failing_pgrep_as_an_error_sample_not_a_gap():
    now = [0.0]
    calls = {"n": 0}

    def clock():
        return now[0]

    def sleep(s):
        now[0] += s

    def pgrep(*args):
        if args == ("-a", "-x", "steam"):
            return 0, "10 steam"
        calls["n"] += 1
        # one sample where pgrep itself fails (rc 2, empty stdout) in the middle of a steady run
        return (2, "") if calls["n"] == 3 else (0, "10\n")

    lines: list[str] = []
    watch = watch_steam(0.6, 100, pgrep=pgrep, clock=clock, sleep=sleep, cmdline=lambda pid: f"cmd-{pid}", log=lines.append)
    assert watch["gaps"] == []
    assert watch["pgrep_errors"] == 1
    assert [c.get("error") for c in watch["changes"]] == [None, "", None]  # present -> error -> present
    assert any("pids=error" in l and "pgrep-error=" in l for l in lines)
    assert any("pgrep_errors=1" in l for l in lines) and any("excluded from the gaps" in l for l in lines)
    assert compute_gaps(parse_watch_log("\n".join(lines))) == []
    # a run that starts with a failing pgrep never opens a gap at t=0
    watch = watch_steam(0.3, 100, pgrep=lambda *a: (-1, "pgrep failed: FileNotFoundError"), clock=clock, sleep=sleep, cmdline=lambda pid: "", log=lines.append)
    assert watch["gaps"] == [] and watch["pgrep_errors"] == 3


def test_watch_steam_with_a_fake_clock_logs_changes_and_gaps():
    now = [0.0]
    calls = {"n": 0}

    def clock():
        return now[0]

    def sleep(s):
        now[0] += s

    def pgrep(*args):
        if args == ("-a", "-x", "steam"):
            return 0, "10 ~/.local/share/Steam/ubuntu12_32/steam -gamepadui"
        calls["n"] += 1
        # present for 3 samples, empty for 4, back afterwards
        return (1, "") if 3 < calls["n"] <= 7 else (0, "10\n")

    lines: list[str] = []
    watch = watch_steam(1.0, 100, pgrep=pgrep, clock=clock, sleep=sleep, cmdline=lambda pid: f"cmd-{pid}", log=lines.append)
    assert watch["samples"] == 10
    assert watch["gaps"] == [{"empty_at_ms": 300, "back_at_ms": 700, "gap_ms": 400, "empty_samples": 4}]
    assert [c["pids"] for c in watch["changes"]] == [[10], [], [10]]
    assert watch["changes"][0]["cmdline"] == "10: cmd-10"
    change_lines = [l for l in lines if "steam-watch change" in l]
    assert len(change_lines) == 3
    assert "pgrep-a(rc=0)=[10 ~/.local/share/Steam/ubuntu12_32/steam -gamepadui]" in change_lines[0]
    # the log itself round-trips through the parser used for the fixture
    assert compute_gaps(parse_watch_log("\n".join(lines))) == watch["gaps"]
    assert any("gap #1: empty at t=300 non-empty at t=700 gap_ms=400" in l for l in lines)


def test_v3_end_to_end_with_fakes(tmp_path):
    """Shutdown is sent only after the watch has started, the samples cover the
    watch, and the runner reconnects after the port was closed for a while."""
    fake = FakeDevTools({"ping": {"pong": True}, "v3_shutdown": {"called": True, "returned": None}})
    pgrep_calls = {"n": 0}
    lock = threading.Lock()

    def pgrep(*args):
        if args == ("-a", "-x", "steam"):
            return 0, "10 steam"
        with lock:
            pgrep_calls["n"] += 1
            n = pgrep_calls["n"]
        return (1, "") if 4 < n <= 8 else (0, "10\n")

    closed_after_shutdown = {"armed": False}
    real_targets = fake.targets

    def targets():
        # closed for the first two reconnect attempts after the shutdown was sent
        if closed_after_shutdown["armed"] and fake.target_calls < closed_after_shutdown["until"]:
            fake.target_calls += 1
            raise PortClosed("refused")
        return real_targets()

    fake.targets = targets
    fake.shared_js_context = lambda: targets()[0]
    original_evaluate = fake.evaluate

    def evaluate(name, params=None, *, timeout_s=90.0):
        if name == "v3_shutdown":
            closed_after_shutdown["armed"] = True
            closed_after_shutdown["until"] = fake.target_calls + 2
        return original_evaluate(name, params, timeout_s=timeout_s)

    fake.evaluate = evaluate
    out, err = io.StringIO(), io.StringIO()
    runner = Runner(fake, out=out, err=err, results_path=tmp_path / "r.json", v3_log_path=tmp_path / "v3.log", pgrep=pgrep, cmdline=lambda pid: f"cmd-{pid}")
    entry = runner.v3(yes=True, duration_s=0.4, interval_ms=10, baseline_s=0.05, reconnect_timeout_s=5, reconnect_poll_s=0.01)
    result = entry["result"]
    assert [c[0] for c in fake.calls] == ["v3_shutdown", "ping"]
    assert result["shutdown"]["reply"] == {"called": True, "returned": None}
    assert result["steam_back"] is True and result["back_after_ms"] is not None
    assert result["samples"] >= 9
    assert len(result["gaps"]) == 1 and result["gaps"][0]["empty_samples"] == 4
    assert result["gaps"][0]["gap_ms"] > 0
    assert (tmp_path / "v3.log").exists()
    log = (tmp_path / "v3.log").read_text()
    assert "steam-watch shutdown sent" in log and "steam-watch summary" in log
    assert compute_gaps(parse_watch_log(log)) == result["gaps"]
    saved = json.loads((tmp_path / "r.json").read_text())
    assert saved[0]["probe"] == "v3"


def test_v3_records_a_lost_reply_as_expected(tmp_path):
    class Dying(FakeDevTools):
        def evaluate(self, name, params=None, *, timeout_s=90.0):
            self.calls.append((name, dict(params or {})))
            if name == "v3_shutdown":
                raise run_probes.ProbeError("websocket closed before the reply")
            return {"pong": True}

    fake = Dying()
    runner = Runner(fake, out=io.StringIO(), err=io.StringIO(), results_path=tmp_path / "r.json", v3_log_path=tmp_path / "v3.log", pgrep=lambda *a: (0, "10\n"), cmdline=lambda pid: "x")
    entry = runner.v3(yes=True, duration_s=0.05, interval_ms=10, baseline_s=0.01, reconnect_timeout_s=1, reconnect_poll_s=0.01)
    assert entry["result"]["shutdown"]["reply"] is None
    assert "expected" in entry["result"]["shutdown"]["note"]
    assert entry["result"]["gaps"] == [] and "never came back empty" in entry["result"]["note"]


def test_v3_survives_a_handshake_error_while_steam_restarts(tmp_path):
    """A websocket handshake failure (InvalidStatus / InvalidMessage: not a
    ProbeError, not OSError) on the first reconnect ping must not end the run
    with a traceback: the run keeps polling and the v3 entry is recorded."""

    class HandshakeFailed(Exception):
        pass

    class Flaky(FakeDevTools):
        pings = 0

        def evaluate(self, name, params=None, *, timeout_s=90.0):
            self.calls.append((name, dict(params or {})))
            if name == "v3_shutdown":
                return {"called": True}
            self.pings += 1
            if self.pings == 1:
                raise HandshakeFailed("server rejected WebSocket connection: HTTP 500")
            return {"pong": True}

    fake = Flaky()
    runner = Runner(fake, out=io.StringIO(), err=io.StringIO(), results_path=tmp_path / "r.json", v3_log_path=tmp_path / "v3.log", pgrep=lambda *a: (0, "10\n"), cmdline=lambda pid: "x")
    entry = runner.v3(yes=True, duration_s=0.05, interval_ms=10, baseline_s=0.01, reconnect_timeout_s=2, reconnect_poll_s=0.01)
    assert entry["result"]["steam_back"] is True
    assert [c[0] for c in fake.calls] == ["v3_shutdown", "ping", "ping"]
    saved = json.loads((tmp_path / "r.json").read_text())
    assert saved[0]["probe"] == "v3" and saved[0]["result"]["steam_back"] is True
    assert "HandshakeFailed" in (tmp_path / "v3.log").read_text()


def test_v3_records_the_gaps_even_when_the_reconnect_wait_is_interrupted(tmp_path):
    class Interrupting(FakeDevTools):
        def evaluate(self, name, params=None, *, timeout_s=90.0):
            self.calls.append((name, dict(params or {})))
            if name == "v3_shutdown":
                return {"called": True}
            raise KeyboardInterrupt()

    pgrep_calls = {"n": 0}

    def pgrep(*args):
        if args == ("-a", "-x", "steam"):
            return 0, "10 steam"
        pgrep_calls["n"] += 1
        return (1, "") if pgrep_calls["n"] > 3 else (0, "10\n")

    runner = Runner(Interrupting(), out=io.StringIO(), err=io.StringIO(), results_path=tmp_path / "r.json", v3_log_path=tmp_path / "v3.log", pgrep=pgrep, cmdline=lambda pid: "x")
    with pytest.raises(KeyboardInterrupt):
        runner.v3(yes=True, duration_s=0.08, interval_ms=10, baseline_s=0.01, reconnect_timeout_s=2, reconnect_poll_s=0.01)
    saved = json.loads((tmp_path / "r.json").read_text())
    assert saved[0]["probe"] == "v3"
    assert len(saved[0]["result"]["gaps"]) == 1 and saved[0]["result"]["gaps"][0]["back_at_ms"] is None
    assert saved[0]["result"]["steam_back"] is False
    assert saved[0]["result"]["reconnect_last_error"].startswith("interrupted: KeyboardInterrupt")


def test_v3_log_keeps_lines_whole_and_drops_writes_after_it_closes(tmp_path):
    """v3 writes this file from the main thread and the sampler thread, and
    parse_watch_log reads the gaps back out of it, so lines must stay whole.
    v3 also joins the sampler with a timeout before closing the file, so a
    sampler that outlived the join must be dropped, not raise on a closed
    file (the shutdown is irreversible; the record still has to be written).
    """
    log = run_probes.V3Log(tmp_path / "sub" / "v3.log")  # its directory is made for it

    def writer(name):
        for i in range(200):
            log(f"{name} sample t={i} rc=0 pids=10")

    threads = [threading.Thread(target=writer, args=(f"w{n}",)) for n in range(4)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    log.close()
    log("straggler sample t=999 rc=0 pids=10")  # no ValueError on a closed file
    log.close()  # idempotent

    lines = (tmp_path / "sub" / "v3.log").read_text().splitlines()
    assert len(lines) == 800
    assert all(re.fullmatch(r"\S+ w\d sample t=\d+ rc=0 pids=10", line) for line in lines)
    assert "straggler" not in "\n".join(lines)


def test_v3_records_the_samples_when_the_baseline_sleep_is_interrupted(tmp_path):
    """Ctrl-C between the watch starting and the shutdown call: the watch is
    stopped and joined, and the v3 record is still appended with whatever it
    sampled (the shutdown is irreversible, so nothing may be lost)."""
    main_thread = threading.current_thread()

    def sleep(seconds):
        if threading.current_thread() is main_thread:
            time.sleep(0.08)  # let the watch take a few samples first
            raise KeyboardInterrupt()
        time.sleep(seconds)

    fake = FakeDevTools()
    runner = Runner(
        fake,
        out=io.StringIO(),
        err=io.StringIO(),
        results_path=tmp_path / "r.json",
        v3_log_path=tmp_path / "v3.log",
        pgrep=lambda *a: (0, "10\n"),
        sleep=sleep,
        cmdline=lambda pid: "x",
    )
    with pytest.raises(KeyboardInterrupt):
        runner.v3(yes=True, duration_s=30, interval_ms=10, baseline_s=1, reconnect_timeout_s=5, reconnect_poll_s=0.01)

    assert fake.calls == []  # the shutdown was never sent
    saved = json.loads((tmp_path / "r.json").read_text())
    assert [r["probe"] for r in saved] == ["v3"]
    result = saved[0]["result"]
    assert result["samples"] >= 1
    assert result["gaps"] == [] and result["changes"]
    assert result["shutdown"] == {"sent_at_ms": None, "reply": None, "note": "not sent"}
    assert result["interrupted"].startswith("KeyboardInterrupt")
    assert result["steam_back"] is False and result["back_after_ms"] is None
    log = (tmp_path / "v3.log").read_text()
    assert "steam-watch interrupted: KeyboardInterrupt" in log and "steam-watch summary" in log


# ---- redaction ---------------------------------------------------------------


def test_redact_paths_only_substitutes_home_at_a_path_boundary():
    """A home of /home/deck must not turn /home/deckard into ~ard; HOME_RE
    still redacts it, as another user's home."""
    assert run_probes.redact_paths("ls /home/deck/Games", home="/home/deck") == "ls ~/Games"
    assert run_probes.redact_paths("cd /home/deck", home="/home/deck") == "cd ~"
    assert run_probes.redact_paths("ls /home/deckard/Games", home="/home/deck") == "ls ~/Games"
    assert run_probes.redact_paths("/opt/x /srv/deckard", home="/srv/deck") == "/opt/x /srv/deckard"


def test_redact_paths_skips_an_empty_or_root_home():
    """home="" or "/" has no prefix worth substituting, and "/" would match
    every absolute path."""
    for home in ("", "/", "~"):
        assert run_probes.redact_paths("run /opt/steam/steam.sh --silent", home=home) == "run /opt/steam/steam.sh --silent"
    assert run_probes.redact_paths("run /home/deck/steam.sh", home="/") == "run ~/steam.sh"


def _fake_websockets(monkeypatch, connect_behaviour):
    """A stand-in websockets package: exceptions.WebSocketException plus an
    asyncio.client.connect that behaves as told (async context manager)."""
    import types

    pkg = types.ModuleType("websockets")
    exceptions = types.ModuleType("websockets.exceptions")

    class WebSocketException(Exception):
        pass

    class InvalidStatus(WebSocketException):
        pass

    exceptions.WebSocketException = WebSocketException
    exceptions.InvalidStatus = InvalidStatus
    asyncio_pkg = types.ModuleType("websockets.asyncio")
    client = types.ModuleType("websockets.asyncio.client")

    class Conn:
        def __init__(self, url, **kw):
            self.url = url

        async def __aenter__(self):
            return connect_behaviour(self, InvalidStatus)

        async def __aexit__(self, *exc):
            return False

    client.connect = Conn
    pkg.exceptions = exceptions
    pkg.asyncio = asyncio_pkg
    asyncio_pkg.client = client
    for name, mod in (("websockets", pkg), ("websockets.exceptions", exceptions), ("websockets.asyncio", asyncio_pkg), ("websockets.asyncio.client", client)):
        monkeypatch.setitem(sys.modules, name, mod)


def test_evaluate_ws_turns_handshake_failures_into_probe_errors(monkeypatch):
    def rejected(conn, InvalidStatus):
        raise InvalidStatus("server rejected WebSocket connection: HTTP 500")

    _fake_websockets(monkeypatch, rejected)
    dt = run_probes.DevTools("h", 1)
    monkeypatch.setattr(dt, "shared_js_context", lambda: {"webSocketDebuggerUrl": "ws://h:1/x"})
    with pytest.raises(run_probes.ProbeError, match="InvalidStatus.*HTTP 500"):
        dt.evaluate("ping", {})


def test_evaluate_ws_returns_the_parsed_json_string(monkeypatch):
    class Ws:
        def __init__(self):
            self.sent = []

        async def send(self, text):
            self.sent.append(json.loads(text))

        async def recv(self):
            return json.dumps({"id": 1, "result": {"result": {"type": "string", "value": json.dumps({"pong": True})}}})

    ws = Ws()
    _fake_websockets(monkeypatch, lambda conn, _: ws)
    dt = run_probes.DevTools("h", 1)
    monkeypatch.setattr(dt, "shared_js_context", lambda: {"webSocketDebuggerUrl": "ws://h:1/x"})
    assert dt.evaluate("ping", {}) == {"pong": True}
    assert ws.sent[0]["method"] == "Runtime.evaluate"
    assert ws.sent[0]["params"]["awaitPromise"] is True and ws.sent[0]["params"]["returnByValue"] is True


# ---- --markdown ------------------------------------------------------------------


def test_markdown_renders_the_results_table(tmp_path):
    results = [
        {"probe": "v1", "when": "2026-09-18T21:00:00", "args": {}, "result": {
            "controllers": {"deckIndex": 15, "source": "controllerStore.GetControllerTypeString"},
            "configs": {"1245620": {"label": "ELDEN RING app_type=1", "config": {"URL": "workshop://111", "Title": "x"}}},
            "candidates": {"1245620": {"flat": [{"appID": 1245620, "URL": "workshop://111"}, {"appID": 1245620, "URL": "workshop://222"}, {"appID": 999, "URL": "workshop://333"}, {"URL": "workshop://444"}]}}}},
        {"probe": "v2", "when": "t2", "args": {}, "result": {"shortcut": SHORTCUT, "label": "ELDEN RING", "url": "workshop://111",
            "before": {"URL": "default://elden ring"}, "after": {"URL": "workshop://111"}, "stuck": True, "restored": True}},
        {"probe": "v3", "when": "t3", "args": {}, "result": {"gaps": [{"empty_at_ms": 3511, "back_at_ms": 7019, "gap_ms": 3508, "empty_samples": 3}],
            "steam_back": True, "back_after_ms": 20000, "changes": [{"cmdline": "10: ~/.local/share/Steam/ubuntu12_32/steam"}]}},
        {"probe": "v4", "when": "t4", "args": {}, "result": {"total": 312, "first20": [{"appid": 1, "display_name": "A|B", "app_type": 1}], "steamid3": "12345678", "strSteamID": "76561197972610406", "appTypeHistogram": {"1": 300}}},
        {"probe": "v5", "when": "t5", "args": {}, "result": {"shortcut": SHORTCUT, "overview": {"display_name": "So|nic", "gameid": str(SHORTCUT), "gameidType": "string", "app_type": 1073741824}, "ran": False}},
        {"probe": "v4", "when": "t6", "args": {}, "result": {"error": "collectionStore is undefined", "shape": {"globalsMatchingCollectionOrStore": ["appStore"]}}},
    ]
    (tmp_path / "probe-results.json").write_text(json.dumps(results))
    code, out, err, _ = run(["--markdown"], tmp_path)
    assert code == EXIT_OK, err
    lines = out.splitlines()
    assert lines[0] == "| probe | case | expected | observed | notes |"
    assert lines[1] == "|---|---|---|---|---|"
    body = "\n".join(lines[2:])
    assert "| V1 | Deck controller index by type |" in body and "| 15 |" in body
    assert "1245620 (ELDEN RING app_type=1)" in body and "workshop://111" in body
    assert "2 candidate(s) for this appid, 1 without appID, 1 for other appids" in body
    assert "stuck=True" in body and "restored=True" in body
    assert "3508 ms" in body and "steam_back=True" in body
    assert "total=312" in body and "first20=1 entries; keys present: yes" in body
    assert "numeric, 8 digits; matches a ~/.local/share/Steam/userdata/<id> folder: unchecked" in body
    assert "gameid=" in body and "ran=False" in body
    assert "error: collectionStore is undefined" in body
    assert "So\\|nic" in body  # pipes are escaped so the table stays a table
    assert "A|B" not in body and "76561197972610406" not in body and "12345678" not in body  # no titles, no ids
    assert all(l.replace("\\|", "").count("|") == 6 for l in lines[2:])  # 5 cells; unescaped pipes only


def test_markdown_never_prints_the_steam_id_or_a_home_path(tmp_path):
    """The table is pasted into PROBES.md and committed (spec §5: no Steam
    IDs, no absolute home paths). The raw values stay in probe-results.json."""
    results = [
        {"probe": "v4", "when": "t4", "args": {}, "result": {
            "total": 3, "first20": [{"appid": 1, "display_name": "My Secret Game", "app_type": 1}],
            "steamid3": "12345678", "strSteamID": "76561197972610406", "appTypeHistogram": {"1": 3},
            "userdata_check": {"match": True, "folders": 1}}},
        {"probe": "v3", "when": "t3", "args": {}, "result": {
            "gaps": [], "note": "n", "steam_back": True, "back_after_ms": 1,
            "changes": [
                {"cmdline": "10: /home/x/.local/share/Steam/ubuntu12_32/steam -gamepadui", "pgrep_a": "10 /home/x/.local/share/Steam/ubuntu12_32/steam"},
                {"cmdline": "11: /home/some.user/bin/steam"},
            ]}},
    ]
    out = render_markdown(results)
    for secret in ("12345678", "76561197972610406", "/home/x", "/home/some.user", "My Secret Game"):
        assert secret not in out, secret
    assert "numeric, 8 digits; matches a ~/.local/share/Steam/userdata/<id> folder: yes" in out
    assert "10: ~/.local/share/Steam/ubuntu12_32/steam -gamepadui; 11: ~/bin/steam" in out
    # the operator's own $HOME is redacted too, whatever it is called
    assert run_probes.redact_paths("/srv/users/deck/x /srv/users/deck", home="/srv/users/deck") == "~/x ~"
    assert run_probes.redact_paths("/home/deck/a /home/other/b") == "~/a ~/b"
    assert run_probes.steamid3_verdict({"steamid3": "77", "userdata_check": {"match": False, "folders": 2}}) == (
        "numeric, 2 digits; matches a ~/.local/share/Steam/userdata/<id> folder: no (2 numeric folder(s) under userdata)"
    )
    assert run_probes.steamid3_verdict({"strSteamIDType": "undefined"}) == "not derived (strSteamID is undefined)"


def test_markdown_with_unconfirmed_controller_index_shows_every_probed_index():
    results = [{"probe": "v1", "when": "t", "args": {}, "result": {
        "controllers": {"deckIndex": None, "source": "none"},
        "warning": "deck controller index not found by type",
        "configs": {"7": {"label": "G", "index": 0, "indexConfirmed": False, "indexSource": "every listed", "config": {"URL": "default://a"},
                          "byIndex": {"0": {"URL": "default://a"}, "15": {"URL": "workshop://9"}}}},
        "candidates": {"7": {"flat": []}}}}]
    out = render_markdown(results)
    assert "7 (G) at index 0 (index not confirmed by type)" in out and "default://a" in out
    assert "7 (G) at index 15 (index not confirmed by type)" in out and "workshop://9" in out


def test_markdown_with_no_results_file(tmp_path):
    code, out, err, _ = run(["--markdown"], tmp_path)
    assert code == EXIT_OK
    assert "no results yet" in out


def test_markdown_with_a_corrupt_results_file(tmp_path):
    (tmp_path / "probe-results.json").write_text("{not json")
    code, out, err, _ = run(["--markdown"], tmp_path)
    assert code == EXIT_FAIL
    assert "not valid JSON" in err


def test_render_markdown_is_pure():
    assert render_markdown([]).count("\n") == 3


# ---- the closed port ---------------------------------------------------------


def free_closed_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def test_exit_3_with_the_message_when_the_port_is_closed(tmp_path):
    port = free_closed_port()
    out, err = io.StringIO(), io.StringIO()
    code = main(["--host", "127.0.0.1", "--port", str(port), "--results", str(tmp_path / "r.json"), "v4"], out=out, err=err)
    assert code == EXIT_PORT_CLOSED
    assert err.getvalue().strip() == (
        f"run_probes.py: cannot reach Steam's CEF DevTools port at 127.0.0.1:{port}: "
        "is Decky installed and is Steam in Game Mode?"
    )
    assert out.getvalue() == ""
    assert not (tmp_path / "r.json").exists()


def test_exit_3_via_subprocess_on_the_closed_port(tmp_path):
    port = free_closed_port()
    proc = subprocess.run(
        [sys.executable, str(Path(run_probes.__file__)), "--host", "127.0.0.1", "--port", str(port), "--results", str(tmp_path / "r.json"), "v1", "--appids", "1"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 3, proc.stderr
    assert "is Decky installed and is Steam in Game Mode?" in proc.stderr


def test_no_shared_js_context_target_is_a_transport_failure(tmp_path):
    class NoTarget(FakeDevTools):
        def targets(self):
            return [{"title": "Steam Big Picture Mode"}]

        def evaluate(self, name, params=None, *, timeout_s=90.0):
            raise run_probes.ProbeError("no SharedJSContext target with a webSocketDebuggerUrl; targets: ['Steam Big Picture Mode']")

    code, out, err, _ = run(["v4"], tmp_path, NoTarget())
    assert code == EXIT_FAIL
    assert "SharedJSContext" in err


def test_real_devtools_picks_the_shared_js_context(monkeypatch):
    dt = run_probes.DevTools("h", 1)
    monkeypatch.setattr(dt, "targets", lambda: [{"title": "Steam", "webSocketDebuggerUrl": "ws://a"}, {"title": "SharedJSContext", "webSocketDebuggerUrl": "ws://b"}])
    assert dt.shared_js_context()["webSocketDebuggerUrl"] == "ws://b"
    monkeypatch.setattr(dt, "targets", lambda: [{"title": "Steam"}])
    with pytest.raises(run_probes.ProbeError, match="SharedJSContext"):
        dt.shared_js_context()


def test_missing_websockets_is_explained(monkeypatch):
    monkeypatch.setitem(sys.modules, "websockets", None)  # makes `import websockets` raise ImportError
    with pytest.raises(run_probes.ProbeError, match="msy-probes"):
        run_probes._websockets_connect()


# ---- the JavaScript ------------------------------------------------------------------


NODE = shutil.which("node")


def eval_in_node(name: str, params: dict, prelude: str = "") -> dict:
    script = prelude + "\n(" + build_expression(name, params) + ").then((s) => process.stdout.write(s));\n"
    proc = subprocess.run([NODE, "-e", script], capture_output=True, text=True, timeout=60, check=False)
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout)


@pytest.mark.skipif(NODE is None, reason="node is not installed")
@pytest.mark.parametrize("name,params", [
    ("v1", {"appids": [1], "candidate_wait_ms": 10}),
    ("v2", {"shortcut": SHORTCUT, "url": "workshop://1", "restore": False, "readback_wait_ms": 10}),
    ("v3_shutdown", {}),
    ("v4", {}),
    ("v5", {"shortcut": SHORTCUT, "run": True}),
])
def test_probe_js_reports_missing_globals_instead_of_throwing(name, params):
    result = eval_in_node(name, params)
    assert "error" in result, result
    assert "top-level" not in result["error"], result  # the guard fired, not the catch-all
    assert result.get("shape") is not None or "controllers" in result


@pytest.mark.skipif(NODE is None, reason="node is not installed")
def test_v2_js_refuses_a_real_game_even_if_the_runner_is_bypassed():
    """The bound is hardcoded in the page, not read from PARAMS: these params
    carry no shortcut_min at all and a real game is still refused."""
    result = eval_in_node("v2", {"shortcut": REAL_GAME, "url": "workshop://1", "restore": False, "readback_wait_ms": 10})
    assert result["error"] == "refused in page: appid below 0x80000000"


@pytest.mark.skipif(NODE is None, reason="node is not installed")
def test_v5_js_does_not_run_without_the_flag_and_runs_with_it():
    stub = """
    globalThis.appStore = { GetAppOverviewByAppID: (id) => ({ appid: id, display_name: "Sonic", app_type: 1073741824, gameid: String(id), BIsShortcut: () => true }) };
    globalThis.SteamClient = { Apps: { RunGame: (...args) => { globalThis.__ran = args; return undefined; } } };
    """
    quiet = eval_in_node("v5", {"shortcut": SHORTCUT, "run": False}, stub)
    assert quiet["overview"]["gameid"] == str(SHORTCUT) and "ran" not in quiet
    loud = eval_in_node("v5", {"shortcut": SHORTCUT, "run": True}, stub + "\nprocess.on('exit', () => { if (!globalThis.__ran) process.exitCode = 9; });")
    assert loud["ran"] is True and loud["runReturned"] == "<undefined>"


@pytest.mark.skipif(NODE is None, reason="node is not installed")
def test_v1_and_v2_js_against_stubbed_steam_input():
    stub = """
    const calls = [];
    globalThis.__calls = calls;
    globalThis.controllerStore = {
      GetControllers: () => [
        { nControllerIndex: 0, eControllerType: 31, strName: "Xbox" },
        { nControllerIndex: 15, eControllerType: 4, strName: "Steam Deck" },
      ],
      GetControllerTypeString: (t) => (t === 4 ? "controller_steamcontroller_neptune" : "controller_xbox360"),
    };
    let selected = { 1245620: "workshop://111" };
    globalThis.SteamClient = { Input: {
      GetConfigForAppAndController: async (appid, idx) => ({ URL: selected[appid] || ("default://app" + appid), Title: "t", idx }),
      SetSelectedConfigForApp: async (appid, idx, url) => { calls.push(["set", appid, idx, url]); selected[appid] = url; return true; },
      RegisterForControllerConfigInfoMessages: (cb) => { setTimeout(() => cb([{ appID: 1245620, nControllerType: 4, strName: "Steam Deck", URL: "workshop://111", Title: "Community", publishedFileID: "111", bOfficial: false, eExportType: 3, bSelected: true }]), 1); return { unregister: () => calls.push(["unregister"]) }; },
      QueryControllerConfigsForApp: (appid, idx, b) => { calls.push(["query", appid, idx, b]); return 0; },
    } };
    globalThis.appStore = { GetAppOverviewByAppID: (id) => ({ display_name: "Game " + id, app_type: 1 }) };
    """
    v1 = eval_in_node("v1", {"appids": [1245620, 2], "candidate_wait_ms": 20}, stub)
    assert v1["controllers"]["deckIndex"] == 15
    assert v1["controllers"]["source"] == "controllerStore.GetControllerTypeString"
    assert v1["configs"]["1245620"]["config"]["URL"] == "workshop://111"
    assert v1["configs"]["2"]["config"]["URL"] == "default://app2"
    assert v1["candidates"]["1245620"]["flat"][0]["publishedFileID"] == "111"
    assert v1["candidates"]["1245620"]["flat"][0]["appID"] == 1245620  # attribution by the message's own appID
    assert v1["candidates"]["1245620"]["flat"][0]["nControllerType"] == 4
    assert v1["candidates"]["1245620"]["unregistered"] is True
    assert v1["configs"]["1245620"]["indexConfirmed"] is True and v1["configs"]["1245620"]["index"] == 15
    assert "warning" not in v1
    v2 = eval_in_node("v2", {"shortcut": SHORTCUT, "url": "workshop://111", "restore": True, "readback_wait_ms": 5}, stub)
    assert v2["before"]["URL"] == f"default://app{SHORTCUT}"
    assert v2["after"]["URL"] == "workshop://111" and v2["stuck"] is True
    assert v2["restored"] is True and v2["afterRestore"]["URL"] == f"default://app{SHORTCUT}"


INPUT_ONLY_STUB = """
globalThis.SteamClient = { Input: {
  GetConfigForAppAndController: async (appid, idx) => ({ URL: "default://app" + appid + "@" + idx, idx }),
  SetSelectedConfigForApp: async (appid, idx, url) => { globalThis.__set = [appid, idx, url]; return true; },
  RegisterForControllerConfigInfoMessages: (cb) => ({ unregister: () => {} }),
  QueryControllerConfigsForApp: (appid, idx, b) => 0,
} };
"""


@pytest.mark.skipif(NODE is None, reason="node is not installed")
def test_v1_js_still_probes_when_the_deck_index_is_not_found_by_type():
    """No controllerStore at all: V1 falls back to the measured index 15 and
    marks the rows unconfirmed instead of aborting (a wrong guess about the
    controller lookup must not cost another build)."""
    params = {"appids": [1], "candidate_wait_ms": 5}
    v1 = eval_in_node("v1", params, INPUT_ONLY_STUB)
    assert v1["controllers"]["deckIndex"] is None
    assert "not found by type" in v1["warning"]
    assert v1["indexPlan"]["indices"] == [15] and v1["indexPlan"]["confirmed"] is False
    assert v1["configs"]["1"]["indexConfirmed"] is False and v1["configs"]["1"]["index"] == 15
    assert v1["configs"]["1"]["byIndex"] == {"15": {"URL": "default://app1@15", "idx": 15}}
    assert v1["candidates"]["1"]["indexConfirmed"] is False
    # controllers listed but none typed as the Deck: every listed index is probed
    listed = INPUT_ONLY_STUB + """
    globalThis.controllerStore = { GetControllers: () => [{ nControllerIndex: 0, eControllerType: 31 }, { nControllerIndex: 2, eControllerType: 31 }] };
    """
    v1 = eval_in_node("v1", params, listed)
    assert v1["indexPlan"]["indices"] == [0, 2] and v1["indexPlan"]["confirmed"] is False
    assert sorted(v1["configs"]["1"]["byIndex"]) == ["0", "2"]
    # the operator's override wins and is marked confirmed
    v1 = eval_in_node("v1", {**params, "controller_index": 7}, listed)
    assert v1["indexPlan"] == {"indices": [7], "confirmed": True, "source": "override (--controller-index)"}
    assert v1["configs"]["1"]["config"]["URL"] == "default://app1@7"


@pytest.mark.skipif(NODE is None, reason="node is not installed")
def test_v2_js_uses_the_fallback_index_and_the_override():
    params = {"shortcut": SHORTCUT, "url": "workshop://1", "restore": False, "readback_wait_ms": 5}
    v2 = eval_in_node("v2", params, INPUT_ONLY_STUB)
    assert v2["index"] == 15 and v2["indexConfirmed"] is False and "not found by type" in v2["warning"]
    assert v2["setReturned"] is True
    v2 = eval_in_node("v2", {**params, "controller_index": 3}, INPUT_ONLY_STUB + "\nprocess.on('exit', () => { if (globalThis.__set[1] !== 3) process.exitCode = 9; });")
    assert v2["index"] == 3 and v2["indexConfirmed"] is True


@pytest.mark.skipif(NODE is None, reason="node is not installed")
def test_controller_list_may_be_any_iterable():
    """GetControllers returning a non-Array iterable (an older MobX observable
    array) is accepted via Array.from, not dismissed by typeof."""
    stub = INPUT_ONLY_STUB + """
    globalThis.controllerStore = {
      GetControllers: () => new Set([{ nControllerIndex: 0, eControllerType: 31 }, { nControllerIndex: 15, eControllerType: 4 }]),
      GetControllerTypeString: (t) => (t === 4 ? "controller_steamcontroller_neptune" : "controller_xbox360"),
    };
    """
    v1 = eval_in_node("v1", {"appids": [1], "candidate_wait_ms": 5}, stub)
    assert v1["controllers"]["deckIndex"] == 15
    assert any("iterable of 2" in a for a in v1["controllers"]["attempts"])
    assert v1["configs"]["1"]["indexConfirmed"] is True


@pytest.mark.skipif(NODE is None, reason="node is not installed")
def test_v4_js_derives_steamid3_with_bigint():
    stub = """
    globalThis.collectionStore = { allAppsCollection: { allApps: [{ appid: 1245620, display_name: "ELDEN RING", app_type: 1 }, { appid: 2, display_name: "Demo", app_type: 8 }, { appid: 2147495962, display_name: "msy probe shortcut", app_type: 1073741824, gameid: "2147495962" }] } };
    globalThis.App = { m_CurrentUser: { strSteamID: "76561197972610406" } };
    """
    v4 = eval_in_node("v4", {}, stub)
    assert v4["total"] == 3 and v4["first20"][0]["display_name"] == "ELDEN RING"
    assert v4["appTypeHistogram"] == {"1": 1, "8": 1, "1073741824": 1}
    assert v4["steamid3"] == "12344678"
    assert v4["shortcuts"] == [{"appid": 2147495962, "display_name": "msy probe shortcut", "app_type": 1073741824, "gameid": "2147495962"}]


# ---- the plugin backend's mirror of the gap logic ---------------------------------------


def load_plugin_backend(monkeypatch):
    """Import probes/steam-input-probe/main.py with a stub `decky` module (the
    real one exists only inside plugin_loader)."""
    import importlib.util
    import logging
    import types

    decky = types.ModuleType("decky")
    decky.logger = logging.getLogger("decky-stub")
    decky.DECKY_HOME = None
    decky.DECKY_USER_HOME = None
    monkeypatch.setitem(sys.modules, "decky", decky)
    path = Path(run_probes.__file__).with_name("steam-input-probe") / "main.py"
    spec = importlib.util.spec_from_file_location("steam_input_probe_main", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_plugin_backend_mirrors_the_error_sample_rule(monkeypatch):
    main_py = load_plugin_backend(monkeypatch)
    assert main_py.PGREP_OK_RCS == run_probes.PGREP_OK_RCS
    for rc, out in ((0, "10\n"), (1, ""), (2, ""), (3, "x"), (-1, "pgrep failed")):
        assert main_py.sample_pids(rc, out) == run_probes.sample_pids(rc, out)
    samples = [(0, [1]), (100, None), (200, []), (300, None), (400, [2]), (500, None)]
    assert main_py.compute_gaps(samples) == compute_gaps(samples) == [
        {"empty_at_ms": 200, "back_at_ms": 400, "gap_ms": 200, "empty_samples": 1}
    ]
    assert main_py.compute_gaps([(0, None), (100, None)]) == []


def test_plugin_backend_log_path_prefers_the_decky_log_dir(monkeypatch, tmp_path):
    """DECKY_PLUGIN_LOG_DIR is the loader's documented (and pre-created)
    place for persistent plugin logs; the old ~/homebrew/logs path is only
    the fallback when the attribute is missing."""
    main_py = load_plugin_backend(monkeypatch)
    main_py.decky.DECKY_PLUGIN_LOG_DIR = str(tmp_path / "homebrew" / "logs" / "steam-input-probe")
    assert main_py._log_path() == str(tmp_path / "homebrew" / "logs" / "steam-input-probe" / "steam-input-probe.log")
    main_py.decky.DECKY_PLUGIN_LOG_DIR = None
    main_py.decky.DECKY_HOME = str(tmp_path / "homebrew")
    assert main_py._log_path() == str(tmp_path / "homebrew" / "logs" / "steam-input-probe.log")


def test_plugin_backend_pgrep_reaps_a_child_that_timed_out(monkeypatch):
    """wait_for cancels communicate() but leaves the child running: the
    watch must kill and reap it, or a 60 s run leaks one process (and one
    pair of pipes) per timed-out sample."""
    import asyncio

    main_py = load_plugin_backend(monkeypatch)
    spawned = []
    real_exec = asyncio.create_subprocess_exec
    real_wait_for = asyncio.wait_for

    async def slow_child(_program, *_args, **kwargs):
        proc = await real_exec(sys.executable, "-c", "import time; time.sleep(30)", **kwargs)
        spawned.append(proc)
        return proc

    async def quick_wait_for(awaitable, timeout=None):
        return await real_wait_for(awaitable, 0.2)

    monkeypatch.setattr(asyncio, "create_subprocess_exec", slow_child)
    monkeypatch.setattr(asyncio, "wait_for", quick_wait_for)
    rc, text = asyncio.run(main_py.Plugin()._pgrep("-x", "steam"))
    assert rc == -1 and "pgrep failed: TimeoutError" in text
    assert len(spawned) == 1 and spawned[0].returncode is not None  # reaped, not a zombie


def test_plugin_backend_pgrep_env_restores_the_loader_library_path(monkeypatch):
    main_py = load_plugin_backend(monkeypatch)
    monkeypatch.setenv("LD_LIBRARY_PATH", "/opt/plugin_loader/_internal")
    monkeypatch.setenv("LD_LIBRARY_PATH_ORIG", "/usr/local/lib")
    env = main_py.pgrep_env()
    assert env["LD_LIBRARY_PATH"] == "/usr/local/lib" and "LD_LIBRARY_PATH_ORIG" not in env
    monkeypatch.delenv("LD_LIBRARY_PATH_ORIG")
    env = main_py.pgrep_env()
    assert "LD_LIBRARY_PATH" not in env
    monkeypatch.delenv("LD_LIBRARY_PATH")
    assert "LD_LIBRARY_PATH" not in main_py.pgrep_env()


def test_plugin_backend_watch_excludes_failing_pgrep_from_the_gaps(monkeypatch, tmp_path):
    """A short watch with pgrep stubbed: rc 2 samples are logged as
    pids=error and never open a gap, exactly like the runner."""
    import asyncio

    main_py = load_plugin_backend(monkeypatch)
    monkeypatch.setattr(main_py, "_log_path", lambda: str(tmp_path / "probe.log"))
    calls = {"n": 0}

    async def fake_pgrep(self, *args):
        if args == ("-a", "-x", "steam"):
            return 0, "10 steam"
        calls["n"] += 1
        return (2, "pgrep: error while loading shared libraries") if calls["n"] in (1, 4) else (0, "10\n")

    monkeypatch.setattr(main_py.Plugin, "_pgrep", fake_pgrep)
    monkeypatch.setattr(main_py.Plugin, "_cmdline", staticmethod(lambda pid: "cmd"))
    plugin = main_py.Plugin()

    async def go():
        ack = await plugin.start_steam_watch(1, 20)
        assert ack["ok"] is True
        await plugin._watch_task
        return await plugin.steam_watch_state()

    state = asyncio.run(go())
    assert state["gaps"] == []
    assert state["pgrep_errors"] == 2
    assert state["running"] is False
    log = (tmp_path / "probe.log").read_text()
    assert "pids=error" in log and "pgrep-error=[pgrep: error while loading shared libraries]" in log
    assert "excluded from the gaps" in log and "gap: none" in log
    assert compute_gaps(parse_watch_log(log)) == []
