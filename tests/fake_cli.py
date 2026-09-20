#!/usr/bin/env python3
"""A stand-in for ``moonlight-steam-sync`` that replays NDJSON fixtures (spec 3.6.3).

Tests run it as ``[sys.executable, "tests/fake_cli.py", ...]`` through the
backend's ``cli=`` seam. Everything is driven by environment variables:

``FAKE_CLI_FIXTURES``
    One directory, or several joined with ``os.pathsep`` (searched in
    order). For subcommand ``X`` (the first argv token that is not a global
    flag) the fake prints ``<dir>/X.ndjson`` line by line (``#`` lines and
    blank lines skipped), writes one human line per event to stderr, and
    exits with the ``exit`` of the last ``error`` event, else
    ``summary.exit``, else 0. ``list --cached`` looks for
    ``list-cached.ndjson`` first and ``match --unpin`` for
    ``match-unpin.ndjson``; ``FAKE_CLI_FIXTURE_<X>_<ACTION>`` or
    ``FAKE_CLI_FIXTURE_<X>`` (upper case, ``-`` as ``_``; ``ACTION`` is the
    first positional after ``X``) names a different basename, e.g.
    ``FAKE_CLI_FIXTURE_HOST_SHOW=host-none``.
    ``doctor`` prints ``doctor.txt`` verbatim. A missing fixture prints
    ``fake_cli: no fixture for X`` to stderr and exits **99**.
``FAKE_CLI_ARGV_LOG``
    Append ``{"argv", "cwd", "from_plugin", "home"}`` as one JSON line per
    invocation.
``FAKE_CLI_VERSION`` (default ``0.3.0``)
    ``--version`` prints ``moonlight-steam-sync <v>``. Below 0.3.0 the new
    flags and subcommands are rejected the way argparse does: usage and
    ``error: unrecognized arguments`` on stderr, nothing on stdout, exit 2.
``FAKE_CLI_ART_COMMIT=1``
    ``art --help`` mentions ``--commit {restart,await-exit,refuse}``.
``FAKE_CLI_STEAM_GONE_FILE`` / ``FAKE_CLI_WAIT_S`` (default 5)
    After an ``awaiting-steam-exit`` line the fake waits (50 ms polls) for
    that file; on timeout it prints the ``steam did not exit`` error, exit 2.
``FAKE_CLI_SIGINT_DURING_WAIT`` (``immediate`` default, or ``deferred``)
    SIGINT outside the wait prints an interrupted ``summary`` and an
    ``error`` 130 and exits 130. During the wait, ``immediate`` does the
    same at once; ``deferred`` keeps waiting and then behaves as the timeout.
``FAKE_CLI_SLEEP_MS`` (default 0)
    Sleep between lines.
``FAKE_CLI_EXIT``
    Force the exit code after the fixture has been printed.
``FAKE_CLI_STDERR``
    Extra text written to stderr before anything else.
``FAKE_CLI_NOISE``
    A non-JSON line printed to stdout right after the first event (the
    backend must log it and never relay it).
``FAKE_CLI_NOISE_BYTES``
    Print one stdout line of that many ``x`` characters right after the
    first event (a line over the backend's 4 MiB limit).
``FAKE_CLI_GRANDCHILD_S`` / ``FAKE_CLI_GRANDCHILD_PIDFILE``
    Start a ``sleep`` grandchild for that many seconds that inherits stdout
    and stderr (and outlives the fake), writing its pid to the pid file.
"""

from __future__ import annotations

import json
import os
import re
import signal
import subprocess
import sys
import time

INTERRUPTED = False

#: What the CLI's `error` event says when a sync / art / remove is
#: interrupted (sync.RESUME_HINT; spec 3.4.6). Unprefixed, and the same
#: for every subcommand. The plugin never parses it: it goes by the exit
#: code and summary.stop_reason.
RESUME_HINT = "interrupted; resume with the same command"

#: Every flag 0.3.0 added. A pre-0.3.0 argparse rejects any of them with
#: "unrecognized arguments". `match`'s own flags are listed too, for
#: completeness -- in practice the subcommand is rejected first (`match` is
#: in NEW_SUBCOMMANDS), exactly as real argparse would.
NEW_FLAGS = (
    "--json",
    "--owned-apps",
    "--ignore-file",
    "--client-shortcut",
    "--commit",
    "--park-unpublished",
    "--cached",
    # match NAME <selector> [--defer-art] [--force-name]
    "--steam",
    "--sgdb",
    "--none",
    "--unpin",
    "--defer-art",
    "--force-name",
)
NEW_SUBCOMMANDS = ("host", "search", "match", "client")

ART_HELP_BASE = """usage: moonlight-steam-sync art [-h] [--force] [--retry-missing] [--limit N]

Fetch artwork for every owned shortcut.

options:
  -h, --help       show this help message and exit
  --force          re-resolve and re-download every slot
  --retry-missing  retry slots that were missing last time
"""
ART_HELP_COMMIT = (
    "  --commit {restart,await-exit,refuse}\n                   how to write shortcuts.vdf\n"
)


def _on_sigint(signum: int, frame: object) -> None:
    global INTERRUPTED
    INTERRUPTED = True


def _version_tuple(text: str) -> tuple[int, int, int]:
    match = re.match(r"^(\d+)\.(\d+)\.(\d+)", text)
    if not match:
        return (0, 0, 0)
    return (int(match.group(1)), int(match.group(2)), int(match.group(3)))


def _out(line: str) -> None:
    sys.stdout.write(line + "\n")
    sys.stdout.flush()


def _err(line: str) -> None:
    sys.stderr.write(line + "\n")
    sys.stderr.flush()


def _sleep(seconds: float) -> None:
    """Sleep in small steps so SIGINT is noticed promptly."""
    end = time.monotonic() + seconds
    while not INTERRUPTED and time.monotonic() < end:
        time.sleep(min(0.02, max(0.0, end - time.monotonic())))


def _log_argv(argv: list[str]) -> None:
    path = os.environ.get("FAKE_CLI_ARGV_LOG")
    if not path:
        return
    with open(path, "a", encoding="utf-8") as handle:
        handle.write(
            json.dumps(
                {
                    "argv": argv,
                    "cwd": os.getcwd(),
                    "from_plugin": os.environ.get("MOONLIGHT_STEAM_SYNC_FROM_PLUGIN"),
                    "home": os.environ.get("HOME"),
                }
            )
            + "\n"
        )


def _subcommand(argv: list[str]) -> str | None:
    for token in argv:
        if token == "--json":
            continue
        return token
    return None


def _reject_old(argv: list[str], subcommand: str | None) -> int | None:
    """Reproduce argparse on a pre-0.3.0 CLI; ``None`` when nothing is rejected."""
    bad = [token for token in argv if token in NEW_FLAGS]
    if subcommand == "status" and "--host" in argv:
        bad.append("--host")
    if subcommand in NEW_SUBCOMMANDS:
        _err("usage: moonlight-steam-sync [-h] [--version] {sync,list,art,status,...} ...")
        _err(f"moonlight-steam-sync: error: argument command: invalid choice: '{subcommand}'")
        return 2
    if bad:
        _err("usage: moonlight-steam-sync [-h] [--version] {sync,list,art,status,...} ...")
        _err(f"moonlight-steam-sync: error: unrecognized arguments: {' '.join(bad)}")
        return 2
    return None


def _fixture_dirs() -> list[str]:
    raw = os.environ.get("FAKE_CLI_FIXTURES", "")
    return [part for part in raw.split(os.pathsep) if part]


def _find(names: list[str]) -> str | None:
    for directory in _fixture_dirs():
        for name in names:
            path = os.path.join(directory, name)
            if os.path.exists(path):
                return path
    return None


def _fixture_names(subcommand: str, argv: list[str]) -> list[str]:
    rest = argv[argv.index(subcommand) + 1 :]
    action = rest[0] if rest and not rest[0].startswith("-") else None
    keys = [subcommand] if action is None else [f"{subcommand}_{action}", subcommand]
    override = None
    for key in keys:
        override = os.environ.get("FAKE_CLI_FIXTURE_" + key.upper().replace("-", "_"))
        if override:
            break
    if override:
        return [override if override.endswith(".ndjson") else override + ".ndjson"]
    names = [subcommand + ".ndjson"]
    if subcommand == "list" and "--cached" in argv:
        names.insert(0, "list-cached.ndjson")
    if subcommand == "match" and "--unpin" in argv:
        names.insert(0, "match-unpin.ndjson")
    return names


def _load(path: str) -> list[dict]:
    events = []
    with open(path, encoding="utf-8") as handle:
        for line in handle:
            text = line.strip()
            if not text or text.startswith("#"):
                continue
            events.append(json.loads(text))
    return events


def _interrupted(subcommand: str, events: list[dict]) -> int:
    summary = next((e for e in events if e.get("event") == "summary"), None)
    fields = (
        dict(summary)
        if summary
        else {
            "event": "summary",
            "added": 0,
            "replaced": 0,
            "removed": 0,
            "filled": 0,
            "missing": 0,
            "unmatched": [],
            "duplicates": {},
            "pending": 0,
        }
    )
    fields.update(stopped_early=True, stop_reason="interrupted", exit=130)
    if subcommand == "sync":
        # every real `sync` summary carries added_by_kind, zeros included
        fields.setdefault("added_by_kind", {"stream": 0, "shortcut": 0})
    else:
        fields.pop("added_by_kind", None)
    _out(json.dumps(fields))
    # The real CLI's resume hint (sync.RESUME_HINT, spec 3.4.6's `error`
    # bullet): unprefixed, and the same text for sync, art and remove.
    _out(json.dumps({"event": "error", "exit": 130, "message": RESUME_HINT}))
    _err(RESUME_HINT)
    return 130


def _wait_for_steam(subcommand: str, events: list[dict]) -> int | None:
    """``None`` when Steam "exited"; else the exit code the fake ends with."""
    gone = os.environ.get("FAKE_CLI_STEAM_GONE_FILE")
    limit = float(os.environ.get("FAKE_CLI_WAIT_S", "5"))
    mode = os.environ.get("FAKE_CLI_SIGINT_DURING_WAIT", "immediate")
    end = time.monotonic() + limit
    deferred = False
    while time.monotonic() < end:
        if INTERRUPTED and not deferred:
            if mode == "deferred":
                deferred = True
                _err(f"{subcommand}: interrupt deferred until the wait ends")
            else:
                return _interrupted(subcommand, events)
        if not deferred and gone and os.path.exists(gone):
            return None
        time.sleep(0.05)
    _out(
        json.dumps(
            {
                "event": "error",
                "exit": 2,
                "message": f"{subcommand}: steam did not exit; shortcuts.vdf not written",
            }
        )
    )
    _err(f"{subcommand}: steam did not exit; shortcuts.vdf not written")
    return 2


def _replay(subcommand: str, path: str) -> int:
    events = _load(path)
    sleep_s = int(os.environ.get("FAKE_CLI_SLEEP_MS", "0")) / 1000.0
    noise = os.environ.get("FAKE_CLI_NOISE")
    for index, event in enumerate(events):
        if INTERRUPTED:
            return _interrupted(subcommand, events)
        _out(json.dumps(event))
        _err(f"{subcommand}: {event.get('event')}")
        if index == 0 and noise:
            _out(noise)
        if index == 0 and os.environ.get("FAKE_CLI_NOISE_BYTES"):
            _out("x" * int(os.environ["FAKE_CLI_NOISE_BYTES"]))
        if event.get("event") == "awaiting-steam-exit":
            code = _wait_for_steam(subcommand, events)
            if code is not None:
                return code
        if sleep_s:
            _sleep(sleep_s)
    if INTERRUPTED:
        return _interrupted(subcommand, events)
    code = 0
    errors = [e for e in events if e.get("event") == "error"]
    summaries = [e for e in events if e.get("event") == "summary"]
    if errors:
        code = int(errors[-1].get("exit", 1))
    elif summaries and "exit" in summaries[-1]:
        code = int(summaries[-1]["exit"])
    return code


def _spawn_grandchild() -> None:
    seconds = os.environ.get("FAKE_CLI_GRANDCHILD_S")
    if not seconds:
        return
    child = subprocess.Popen(["sleep", seconds], stdin=subprocess.DEVNULL)
    pidfile = os.environ.get("FAKE_CLI_GRANDCHILD_PIDFILE")
    if pidfile:
        with open(pidfile, "a", encoding="utf-8") as handle:
            handle.write(f"{child.pid}\n")


def main(argv: list[str]) -> int:
    signal.signal(signal.SIGINT, _on_sigint)
    _log_argv(argv)
    _spawn_grandchild()
    extra = os.environ.get("FAKE_CLI_STDERR")
    if extra:
        _err(extra)
    version = os.environ.get("FAKE_CLI_VERSION", "0.3.0")
    if "--version" in argv:
        _out(f"moonlight-steam-sync {version}")
        return 0
    subcommand = _subcommand(argv)
    if _version_tuple(version) < (0, 3, 0):
        rejected = _reject_old(argv, subcommand)
        if rejected is not None:
            return rejected
    if subcommand is None:
        _err("usage: moonlight-steam-sync [-h] [--version] {sync,list,art,status,...} ...")
        return 2
    if subcommand == "art" and ("--help" in argv or "-h" in argv):
        text = ART_HELP_BASE
        if os.environ.get("FAKE_CLI_ART_COMMIT") == "1":
            text += ART_HELP_COMMIT
        sys.stdout.write(text)
        return 0
    if subcommand == "doctor":
        path = _find(["doctor.txt"])
        if path is None:
            _err("fake_cli: no fixture for doctor")
            return 99
        with open(path, encoding="utf-8") as handle:
            sys.stdout.write(handle.read())
        return 0
    path = _find(_fixture_names(subcommand, argv))
    if path is None:
        _err(f"fake_cli: no fixture for {subcommand}")
        return 99
    code = _replay(subcommand, path)
    forced = os.environ.get("FAKE_CLI_EXIT")
    return int(forced) if forced else code


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
