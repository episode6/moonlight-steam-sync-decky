"""Tests for probes/run_probes.py: argument handling, --help, the refusals,
the gap computation from a recorded pgrep log, --markdown rendering, exit 3
on a closed port, and the defensive JavaScript (run under node when it is
installed). The DevTools connection sits behind FakeDevTools."""

from __future__ import annotations

import io
import json
import shutil
import socket
import subprocess
import sys
import threading
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
    for name in ("v1", "v2", "v3", "v4", "v5", "all", "--markdown", "--restore", "--run", "--yes"):
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
    assert printed["args"] == {"appids": [1245620, 2379780, 1145360]}


def test_v1_rejects_non_numeric_appids(tmp_path):
    with pytest.raises(SystemExit) as exc:
        run(["v1", "--appids", "1245620,abc"], tmp_path)
    assert exc.value.code == 2


def test_v4_prints_one_json_object_and_appends_it(tmp_path):
    fake = FakeDevTools({"v4": {"probe": "v4", "total": 3, "steamid3": "12345678"}})
    code, out, err, _ = run(["v4"], tmp_path, fake)
    assert code == EXIT_OK, err
    assert json.loads(out)["result"]["total"] == 3
    code, out2, _, _ = run(["v4"], tmp_path, fake)
    assert code == EXIT_OK
    results = json.loads((tmp_path / "probe-results.json").read_text())
    assert [r["probe"] for r in results] == ["v4", "v4"]
    assert all("when" in r for r in results)


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
    assert params["shortcut_min"] == 0x80000000


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


# ---- --markdown ------------------------------------------------------------------


def test_markdown_renders_the_results_table(tmp_path):
    results = [
        {"probe": "v1", "when": "2026-09-18T21:00:00", "args": {}, "result": {
            "controllers": {"deckIndex": 15, "source": "controllerStore.GetControllerTypeString"},
            "configs": {"1245620": {"label": "ELDEN RING app_type=1", "config": {"URL": "workshop://111", "Title": "x"}}},
            "candidates": {"1245620": {"flat": [{"URL": "workshop://111"}, {"URL": "workshop://222"}]}}}},
        {"probe": "v2", "when": "t2", "args": {}, "result": {"shortcut": SHORTCUT, "label": "ELDEN RING", "url": "workshop://111",
            "before": {"URL": "default://elden ring"}, "after": {"URL": "workshop://111"}, "stuck": True, "restored": True}},
        {"probe": "v3", "when": "t3", "args": {}, "result": {"gaps": [{"empty_at_ms": 3511, "back_at_ms": 7019, "gap_ms": 3508, "empty_samples": 3}],
            "steam_back": True, "back_after_ms": 20000, "changes": [{"cmdline": "10: ~/.local/share/Steam/ubuntu12_32/steam"}]}},
        {"probe": "v4", "when": "t4", "args": {}, "result": {"total": 312, "first20": [{"appid": 1, "display_name": "A|B", "app_type": 1}], "steamid3": "12345678", "strSteamID": "76561197972610406", "appTypeHistogram": {"1": 300}}},
        {"probe": "v5", "when": "t5", "args": {}, "result": {"shortcut": SHORTCUT, "overview": {"display_name": "Sonic", "gameid": str(SHORTCUT), "gameidType": "string", "app_type": 1073741824}, "ran": False}},
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
    assert "1245620 (ELDEN RING app_type=1)" in body and "workshop://111" in body and "2 candidate(s)" in body
    assert "stuck=True" in body and "restored=True" in body
    assert "3508 ms" in body and "steam_back=True" in body
    assert "total=312" in body and "steamid3=12345678" in body
    assert "gameid=" in body and "ran=False" in body
    assert "error: collectionStore is undefined" in body
    assert "A\\|B" in body  # pipes are escaped so the table stays a table
    assert all(l.replace("\\|", "").count("|") == 6 for l in lines[2:])  # 5 cells; unescaped pipes only


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
    ("v2", {"shortcut": SHORTCUT, "url": "workshop://1", "restore": False, "shortcut_min": 0x80000000, "readback_wait_ms": 10}),
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
    result = eval_in_node("v2", {"shortcut": REAL_GAME, "url": "workshop://1", "restore": False, "shortcut_min": 0x80000000, "readback_wait_ms": 10})
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
      RegisterForControllerConfigInfoMessages: (cb) => { setTimeout(() => cb([{ URL: "workshop://111", Title: "Community", publishedFileID: "111", bOfficial: false, eExportType: 3, bSelected: true }]), 1); return { unregister: () => calls.push(["unregister"]) }; },
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
    assert v1["candidates"]["1245620"]["unregistered"] is True
    v2 = eval_in_node("v2", {"shortcut": SHORTCUT, "url": "workshop://111", "restore": True, "shortcut_min": 0x80000000, "readback_wait_ms": 5}, stub)
    assert v2["before"]["URL"] == f"default://app{SHORTCUT}"
    assert v2["after"]["URL"] == "workshop://111" and v2["stuck"] is True
    assert v2["restored"] is True and v2["afterRestore"]["URL"] == f"default://app{SHORTCUT}"


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
