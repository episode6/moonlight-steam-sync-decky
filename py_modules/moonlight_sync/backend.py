"""The plugin backend: every callable of spec 3.7, over the installed CLI.

``main.py`` builds one :class:`Backend` from decky's constants and delegates
each callable to it. Nothing here imports ``decky``; tests construct a
``Backend`` over ``tests/fake_cli.py`` with ``cli=`` / ``env=`` overrides.

Conventions (spec 3.7, amended):

- Every callable returns a dict with ``"ok"``. A failure is ``{"ok": False,
  "error": <code>, "message": <text>, ...}`` with ``error`` one of
  ``cli-missing``, ``cli-too-old``, ``cli-protocol``, ``cli-error``,
  ``timeout``, ``busy``, ``owned-apps-missing``, ``owned-apps-empty``,
  ``bad-request``, ``io``. Callables never raise.
- Argv is always ``[python3, <installed cli>, "--json", <subcommand>, ...]``
  except ``doctor``, ``--version`` and ``art --help``. The child runs with
  ``cwd=<home>`` and ``env`` = the backend's plus
  ``MOONLIGHT_STEAM_SYNC_FROM_PLUGIN=1``, ``HOME=<home>`` and
  ``PYTHONUNBUFFERED=1`` (the CLI does not flush its events, and a buffered
  ``awaiting-steam-exit`` arrives after the wait it announces), minus
  plugin_loader's PyInstaller ``LD_LIBRARY_PATH`` (``_child_env``).
- Collecting runs wait for the child, time out (30 s / 90 s: SIGINT, then
  SIGKILL 3 s later) and return the events; pipes a grandchild keeps open
  are closed 3 s after the child exits. Long runs (``start_sync``,
  ``start_art_refetch``, ``start_remove_all``) share one busy guard and relay
  every event as ``sync_event`` and the end as ``sync_done``.
- The plugin never writes under the Steam directory, never writes
  ``config.toml``, and only the last four characters of the SteamGridDB key
  ever leave this process. The one CLI file it touches is the match cache,
  ``matches.json``, which ``reset_match_cache`` deletes whole (never edits)
  under the busy guard, so the CLI cannot be writing it at the time.
"""

from __future__ import annotations

import asyncio
import collections
import contextlib
import functools
import inspect
import json
import os
import shlex
import shutil
import signal
import time
import traceback
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from . import events as ev
from . import install, keys, wake
from .settings import SettingsError, Store

Result = dict[str, Any]
Emit = Callable[..., Any]

LOG_NAME = "moonlight-sync.log"
LOG_MAX_BYTES = 5 * 1024 * 1024
LOG_KEEP_BYTES = 1024 * 1024
STDOUT_LINE_LIMIT = 4 * 1024 * 1024
#: The CLI's cache directory under ``$XDG_CACHE_HOME`` (``~/.cache`` by
#: default), where ``matches.json`` and ``hosts/`` live; mirrors the CLI's
#: ``art.resolve.cache_dir()``.
CACHE_DIR_NAME = "moonlight-steam-sync"
MATCH_CACHE_NAME = "matches.json"


def iso_now() -> str:
    """UTC, seconds, ``Z`` -- the form the CLI writes (``_iso()``)."""
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def failure(code: str, message: str, **extra: Any) -> Result:
    return {"ok": False, "error": code, "message": message, **extra}


class CliOutputError(OSError):
    """The child's output could not be read; it was killed and reaped."""

    def __init__(self, message: str, exit_code: int) -> None:
        super().__init__(message)
        self.exit = exit_code


@dataclass
class RunResult:
    """What one child process produced."""

    exit: int
    events: list[dict[str, Any]]
    stdout: str
    stderr: str
    timed_out: bool = False

    def stderr_tail(self, n: int = 500) -> str:
        return self.stderr[-n:]


@dataclass
class RunState:
    """One long run (sync / art / remove) and what it has emitted so far."""

    kind: str
    opts: dict[str, Any]
    started: str
    running: bool = True
    awaiting_exit: bool = False
    #: ``stop_sync`` / ``unload`` asked for it; honoured as soon as the child
    #: exists, so the window between ``_start_run`` and the spawn is covered.
    stop_requested: bool = False
    #: A child process was actually started (``_run_started`` ran). False
    #: means the spawn itself failed, which a pending stop must not mask.
    spawned: bool = False
    plan: dict[str, Any] | None = None
    events: list[dict[str, Any]] = field(default_factory=list)
    recent: collections.deque = field(default_factory=lambda: collections.deque(maxlen=200))
    exit: int | None = None
    proc: asyncio.subprocess.Process | None = None
    task: asyncio.Task | None = None
    failure: Result | None = None


def match_cache_path(home: str, env: dict[str, str]) -> str:
    """Where the CLI keeps ``matches.json``, resolved as its ``cache_dir()``
    resolves it for the child: ``$XDG_CACHE_HOME`` from the env the child
    gets, else ``<home>/.cache``."""
    base = env.get("XDG_CACHE_HOME") or os.path.join(home, ".cache")
    return os.path.join(base, CACHE_DIR_NAME, MATCH_CACHE_NAME)


def match_cache_counts(path: str) -> tuple[int, int]:
    """``(titles, pins)`` held by a ``matches.json``; ``(0, 0)`` for a
    missing, unreadable or broken file (the CLI reads such a file as empty
    too).

    The shape is the CLI's ``MatchCache.flush()`` / ``Match.to_json()`` in
    ``art/resolve.py``: ``{"version": 1, "titles": {<name>: {"how", …}}}``
    with a pin's ``how`` being ``"pinned"`` (``HOW_PINNED``, the same value
    the ``pinned`` event carries). Checked against a Deck's file on
    2026-09-23. Only the toast depends on it: the delete does not.
    """
    try:
        with open(path, encoding="utf-8") as handle:
            payload = json.load(handle)
    except (OSError, ValueError):
        return 0, 0
    titles = payload.get("titles") if isinstance(payload, dict) else None
    if not isinstance(titles, dict):
        return 0, 0
    pins = sum(
        1 for entry in titles.values() if isinstance(entry, dict) and entry.get("how") == "pinned"
    )
    return len(titles), pins


def guarded(fn: Callable[..., Awaitable[Result]]) -> Callable[..., Awaitable[Result]]:
    """Turn any exception escaping a callable into a failure result."""

    @functools.wraps(fn)
    async def wrapper(self: Backend, *args: Any, **kwargs: Any) -> Result:
        try:
            return await fn(self, *args, **kwargs)
        except SettingsError as exc:
            return failure("bad-request", str(exc))
        except OSError as exc:
            self._log(f"{fn.__name__}: {exc}")
            return failure("io", self._redact(f"{getattr(exc, 'filename', '') or ''}: {exc}"))
        except Exception as exc:  # the contract is "never raise"
            self._log(f"{fn.__name__} failed:\n{traceback.format_exc()}")
            return failure("bad-request", self._redact(f"internal error: {exc}"))

    return wrapper


class Backend:
    """The plugin's backend. One instance per plugin load."""

    TIMEOUT_SHORT = 30.0
    TIMEOUT_LONG = 90.0
    KILL_GRACE = 3.0
    UNLOAD_WAIT = 10.0
    CHECK_HOST_TTL = 10.0
    EVENT_RING = 200

    def __init__(
        self,
        *,
        settings_dir: str,
        log_dir: str,
        plugin_dir: str,
        home: str,
        plugin_version: str = "",
        emit: Emit | None = None,
        logger: Any = None,
        cli: list[str] | None = None,
        env: dict[str, str] | None = None,
        python: str | None = None,
    ) -> None:
        self.settings_dir = settings_dir
        self.log_dir = log_dir
        self.plugin_dir = plugin_dir
        self.home = home
        self.plugin_version = plugin_version
        self.emit = emit
        self.logger = logger
        self.python = python or shutil.which("python3") or "/usr/bin/python3"
        self.installed_cli = os.path.join(home, ".local", "bin", "moonlight-steam-sync")
        self.bundled_cli = os.path.join(plugin_dir, "bin", "moonlight-steam-sync.pyz")
        #: The test seam: ``cli=[sys.executable, "tests/fake_cli.py"]``.
        self._cli_override = cli is not None
        self.cli: list[str] = list(cli) if cli is not None else [self.python, self.installed_cli]
        self.env: dict[str, str] = dict(os.environ) if env is None else dict(env)
        self.store = Store(settings_dir)
        self.log_path = os.path.join(log_dir, LOG_NAME)

        self.installed_version: install.Version | None = None
        self.bundled_version: install.Version | None = None
        self.install_error: str | None = None
        self.cli_ok = False
        self._capabilities: dict[str, bool] | None = None
        self._started = False
        self._run: RunState | None = None
        self._last_run: RunState | None = None
        #: In-flight `match` children. The busy guard is symmetric: a match
        #: writes the same matches.json a long run writes, so neither may
        #: start while the other is going.
        self._matching = 0
        self._host_memo: dict[str, tuple[float, Result]] = {}
        self._procs: set[asyncio.subprocess.Process] = set()

    # ------------------------------------------------------------------
    # logging

    def _log(self, message: str) -> None:
        line = f"{iso_now()} {message}"
        try:
            os.makedirs(self.log_dir, exist_ok=True)
            with open(self.log_path, "a", encoding="utf-8") as handle:
                handle.write(line + "\n")
        except OSError:
            pass
        if self.logger is not None:
            with contextlib.suppress(Exception):
                self.logger.info(message)

    def _log_raw(self, text: str) -> None:
        """Append the child's stderr verbatim."""
        try:
            os.makedirs(self.log_dir, exist_ok=True)
            with open(self.log_path, "a", encoding="utf-8") as handle:
                handle.write(text if text.endswith("\n") else text + "\n")
        except OSError:
            pass

    def _trim_log(self) -> None:
        try:
            if os.path.getsize(self.log_path) <= LOG_MAX_BYTES:
                return
            with open(self.log_path, "rb") as handle:
                handle.seek(-LOG_KEEP_BYTES, os.SEEK_END)
                tail = handle.read()
            with open(self.log_path, "wb") as handle:
                handle.write(tail)
        except OSError:
            pass

    def _effective_key(self) -> str:
        try:
            return keys.key_state(self.home, self.env).key
        except Exception:
            return ""

    def _redact(self, text: str, key: str | None = None) -> str:
        """Replace the SteamGridDB key with ``…<last four>`` anywhere in ``text``."""
        key = self._effective_key() if key is None else key
        if len(key) >= 8 and key in text:
            return text.replace(key, "…" + key[-4:])
        return text

    def _scrub(self, obj: dict[str, Any], key: str) -> dict[str, Any]:
        if len(key) < 8:
            return obj
        dumped = json.dumps(obj, ensure_ascii=False)
        if key not in dumped:
            return obj
        return json.loads(dumped.replace(key, "…" + key[-4:]))

    async def _emit(self, name: str, payload: dict[str, Any]) -> None:
        if self.emit is None:
            return
        try:
            result = self.emit(name, payload)
            if inspect.isawaitable(result):
                await result
        except Exception as exc:
            self._log(f"emit {name} failed: {exc}")

    # ------------------------------------------------------------------
    # startup / unload

    def _child_env(self) -> dict[str, str]:
        env = dict(self.env)
        # plugin_loader is a PyInstaller-frozen binary: it exports
        # LD_LIBRARY_PATH=/tmp/_MEIxxxxxx (its bundled, older libssl among
        # others), under which the CLI's `flatpak` call and its own
        # `import ssl` both die in the dynamic linker -- "moonlight CLI not
        # found" and "5 consecutive network failures" on the first device
        # run. PyInstaller saves the value it replaced in
        # LD_LIBRARY_PATH_ORIG, but only when there was one; under the
        # systemd service there is not, so drop its `_MEI*` entries instead.
        orig = env.pop("LD_LIBRARY_PATH_ORIG", None)
        if orig is None:
            orig = os.pathsep.join(
                entry
                for entry in env.get("LD_LIBRARY_PATH", "").split(os.pathsep)
                if entry and not os.path.basename(entry.rstrip(os.sep)).startswith("_MEI")
            )
        if orig:
            env["LD_LIBRARY_PATH"] = orig
        else:
            env.pop("LD_LIBRARY_PATH", None)
        env["MOONLIGHT_STEAM_SYNC_FROM_PLUGIN"] = "1"
        env["HOME"] = self.home
        # The CLI prints its events without flushing, and over a pipe Python
        # block-buffers stdout: `awaiting-steam-exit` would sit in the child's
        # buffer for the whole 60 s wait and only arrive with the exit, so the
        # client was never shut down in time and shortcuts.vdf never written.
        env["PYTHONUNBUFFERED"] = "1"
        return env

    def _read_installed(self) -> install.Version | None:
        if not self._cli_override and not os.path.exists(self.installed_cli):
            return None
        return install.read_version(self.cli, env=self._child_env(), cwd=self._cwd())

    def _read_bundled(self) -> install.Version | None:
        if not os.path.exists(self.bundled_cli):
            return None
        return install.read_version(
            [self.python, self.bundled_cli], env=self._child_env(), cwd=self._cwd()
        )

    def _cwd(self) -> str | None:
        return self.home if os.path.isdir(self.home) else None

    def _update_cli_ok(self) -> None:
        self.cli_ok = (
            self.installed_version is not None and self.installed_version >= install.MIN_CLI_VERSION
        )

    async def startup(self) -> None:
        """Install/upgrade check, then seed the plugin's files (spec 3.6.1 order)."""
        try:
            self._trim_log()
            self._log(f"startup: plugin {self.plugin_version or '?'}")
            if not self._cli_override:
                report = await asyncio.to_thread(
                    install.ensure_installed,
                    self.python,
                    self.bundled_cli,
                    self.installed_cli,
                    env=self._child_env(),
                    cwd=self._cwd(),
                )
                self.bundled_version = report.bundled
                self.install_error = report.error
                self._log(
                    "cli install check: "
                    f"bundled {install.format_version(report.bundled)}, "
                    f"installed {install.format_version(report.installed)}, "
                    f"action {report.action}" + (f", error: {report.error}" if report.error else "")
                )
            else:
                self.bundled_version = await asyncio.to_thread(self._read_bundled)
            self.installed_version = await asyncio.to_thread(self._read_installed)
            self._update_cli_ok()
            self._log(
                f"cli: installed {install.format_version(self.installed_version)}, "
                f"minimum {install.format_version(install.MIN_CLI_VERSION)}, ok={self.cli_ok}"
            )
            self.store.ensure_files()
            if self.cli_ok:
                caps = await self.cli_capabilities()
                self._log(f"cli capabilities: {caps}")
                if not self.store.hosts_seeded():
                    await self.hosts()
        except Exception:  # startup must never take the plugin down
            self._log(f"startup failed:\n{traceback.format_exc()}")
        finally:
            self._started = True

    async def unload(self) -> None:
        """SIGINT a running child, wait up to 10 s, then kill whatever is left.

        A run that has been registered but whose child is not spawned yet is
        flagged instead; :meth:`_run_started` interrupts it the moment it
        exists, so unloading can never leave an orphan behind.
        """
        run = self._run
        if run is not None and run.running:
            self._log("unload: interrupting the running child")
            run.stop_requested = True
            if run.proc is not None:
                self._interrupt(run.proc)
            if run.task is not None:
                done, _ = await asyncio.wait({run.task}, timeout=self.UNLOAD_WAIT)
                if not done:
                    if run.proc is not None:
                        self._kill(run.proc)
                    await asyncio.wait({run.task}, timeout=self.KILL_GRACE)
        for proc in list(self._procs):
            self._kill(proc)

    # ------------------------------------------------------------------
    # the subprocess runner

    def _interrupt(self, proc: asyncio.subprocess.Process) -> None:
        if proc.returncode is None:
            with contextlib.suppress(ProcessLookupError):
                proc.send_signal(signal.SIGINT)

    def _kill(self, proc: asyncio.subprocess.Process) -> None:
        if proc.returncode is None:
            with contextlib.suppress(ProcessLookupError):
                proc.kill()

    @staticmethod
    async def _until_exit(proc: asyncio.subprocess.Process) -> None:
        """Resolve once the child has exited, whoever holds its pipes.

        ``proc.wait()`` only resolves after every pipe has closed, which a
        grandchild that inherited them can delay forever; ``returncode`` is
        set the moment the child itself exits.
        """
        while proc.returncode is None:
            await asyncio.sleep(0.05)

    async def _settle(
        self, readers: asyncio.Future, exited: asyncio.Future, limit: float | None
    ) -> bool:
        """Wait up to ``limit`` for the output readers to reach EOF.

        Once the child has exited the readers get at most ``KILL_GRACE``
        more, so pipes held open by a grandchild cannot stall the caller.
        """
        await asyncio.wait({readers, exited}, timeout=limit, return_when=asyncio.FIRST_COMPLETED)
        if not readers.done() and exited.done():
            await asyncio.wait({readers}, timeout=self.KILL_GRACE)
        return readers.done()

    @staticmethod
    def _close_pipes(proc: asyncio.subprocess.Process) -> None:
        """Close our ends of the child's stdout/stderr pipes.

        asyncio has no public accessor for the pipe transports; closing them
        lets the subprocess transport finish (and ``proc.wait()`` resolve)
        even when a grandchild still holds the write ends.
        """
        transport = getattr(proc, "_transport", None)
        if transport is None:
            return
        for fd in (1, 2):
            pipe = transport.get_pipe_transport(fd)
            if pipe is not None:
                pipe.close()

    async def _spawn(
        self,
        argv: list[str],
        *,
        timeout: float | None,
        on_event: Callable[[dict[str, Any]], Awaitable[None]] | None = None,
        on_proc: Callable[[asyncio.subprocess.Process], None] | None = None,
        json_mode: bool = True,
    ) -> RunResult:
        """The one place a child is started.

        Raises ``OSError`` if it cannot be started, and :class:`CliOutputError`
        (an ``OSError``) if its output cannot be read (a line over the 4 MiB
        limit); the child is killed and reaped either way. A timeout sends
        SIGINT, then SIGKILL ``KILL_GRACE`` later. Output pipes still open
        ``KILL_GRACE`` after the child exited (held by a grandchild) are
        closed rather than waited for.

        **This is where the SteamGridDB key is scrubbed** (hard rule 4): the
        effective key is read once per spawn and every parsed event, every
        stdout line kept and every stderr line -- which is also what reaches
        the plugin log -- has it replaced by ``…<last four>`` before anything
        downstream sees it. So :class:`RunResult` is clean by construction and
        no caller can leak the key by forgetting to redact.
        """
        self._log("run: " + shlex.join(argv))  # the key is never on argv (keys.py)
        proc = await asyncio.create_subprocess_exec(
            *argv,
            stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=self._child_env(),
            cwd=self._cwd(),
            limit=STDOUT_LINE_LIMIT,
        )
        self._procs.add(proc)
        if on_proc is not None:
            on_proc(proc)
        events: list[dict[str, Any]] = []
        stdout_parts: list[str] = []
        stderr_parts: list[str] = []
        read_errors: list[Exception] = []
        key = self._effective_key()  # read once per spawn, not per line

        async def read_stdout() -> None:
            assert proc.stdout is not None
            while True:
                raw = await proc.stdout.readline()
                if not raw:
                    return
                text = raw.decode("utf-8", "replace")
                stdout_parts.append(self._redact(text, key))
                if not json_mode:
                    continue
                event = ev.parse_line(text)
                if event is None:
                    if text.strip():
                        shown = self._redact(text, key).rstrip()
                        self._log(f"non-JSON stdout line skipped: {shown}")
                    continue
                event = self._scrub(event, key)
                events.append(event)
                if on_event is not None:
                    try:
                        await on_event(event)
                    except Exception:
                        self._log(f"event handler failed:\n{traceback.format_exc()}")

        async def read_stderr() -> None:
            assert proc.stderr is not None
            while True:
                raw = await proc.stderr.readline()
                if not raw:
                    return
                text = self._redact(raw.decode("utf-8", "replace"), key)
                stderr_parts.append(text)
                self._log_raw(text)

        async def reading(reader: Callable[[], Awaitable[None]]) -> None:
            try:
                await reader()
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # e.g. ValueError: a line over the limit
                read_errors.append(exc)
                self._log(f"reading the CLI's output failed ({exc}); killing it")
                self._kill(proc)

        readers = asyncio.ensure_future(asyncio.gather(reading(read_stdout), reading(read_stderr)))
        exited = asyncio.ensure_future(self._until_exit(proc))
        timed_out = False
        try:
            finished = await self._settle(readers, exited, timeout)
            if not finished and proc.returncode is None:
                timed_out = True
                self._log(f"timed out after {timeout:g} s; interrupting")
                self._interrupt(proc)
                finished = await self._settle(readers, exited, self.KILL_GRACE)
                if not finished and proc.returncode is None:
                    self._kill(proc)
                    finished = await self._settle(readers, exited, self.KILL_GRACE)
            if not finished or read_errors:
                if not finished:
                    self._log("the CLI's output pipes are still open after it exited; closing them")
                readers.cancel()
                self._close_pipes(proc)
                await asyncio.wait({readers})
            if proc.returncode is None:
                self._kill(proc)
            code = await proc.wait()
        finally:
            for task in (readers, exited):
                if not task.done():
                    task.cancel()
            if proc.returncode is None:
                self._kill(proc)
            self._procs.discard(proc)
        self._log(f"exit {code}: {shlex.join(argv[len(self.cli) :]) or argv[-1]}")
        if read_errors:
            raise CliOutputError(f"unreadable CLI output: {read_errors[0]}", code)
        return RunResult(
            exit=code,
            events=events,
            stdout="".join(stdout_parts),
            stderr="".join(stderr_parts),
            timed_out=timed_out,
        )

    # ------------------------------------------------------------------
    # gates and result classification

    def _cli_gate(self) -> Result | None:
        if self.installed_version is None:
            return failure("cli-missing", "CLI not installed — see About")
        if not self.cli_ok:
            installed = install.format_version(self.installed_version)
            minimum = install.format_version(install.MIN_CLI_VERSION)
            return failure(
                "cli-too-old",
                f"CLI too old ({installed}, needs {minimum}) — see About",
                installed=installed,
                minimum=minimum,
            )
        return None

    def _owned_args(self) -> list[str]:
        return ["--owned-apps", self.store.path("owned-apps.json")]

    def _ignore_args(self) -> list[str]:
        return ["--ignore-file", self.store.path("ignore.json")]

    def _list_args(self) -> list[str]:
        """What every ``list`` call carries, live or ``--cached``."""
        return [*self._owned_args(), *self._ignore_args(), *self._host_app_args()]

    def _host_app_args(self) -> list[str]:
        """``--hide-host-apps`` (spec 3.14), on every ``sync`` / ``list`` / ``status``.

        Always passed, like ``--client-shortcut``: the panel's Desktop and
        Steam Big Picture buttons replace the two library tiles, and the
        CLI is what hides them (hard rule 1). The three must agree, or
        ``status`` would call the hidden pair parked and ``list`` would
        call them shortcuts.
        """
        return ["--hide-host-apps"]

    def _classify(self, result: RunResult, timeout: float | None) -> Result | None:
        """``None`` for a clean run, else the failure result for it.

        The failure is scrubbed of the SteamGridDB key as a whole (hard
        rule 4): its ``events`` list reaches the frontend too, not just
        ``message``/``stderr``, so every collecting callable and every
        long run's failure is covered here once.
        """
        found = self._classify_raw(result, timeout)
        return None if found is None else self._scrub(found, self._effective_key())

    def _classify_raw(self, result: RunResult, timeout: float | None) -> Result | None:
        if result.timed_out:
            return failure("timeout", f"timed out after {timeout:g} s", timeout_s=timeout)
        if not any(e.get("event") == "start" for e in result.events):
            return failure(
                "cli-protocol",
                "The installed CLI did not understand the request (see the log)",
                exit=result.exit,
                stderr=self._redact(result.stderr_tail()),
            )
        for index, event in enumerate(result.events):
            if event.get("event") == "error":
                return failure(
                    "cli-error",
                    self._redact(str(event.get("message", ""))),
                    exit=event.get("exit", result.exit),
                    events=result.events[:index],
                )
        if result.exit != 0:
            tail = result.stderr_tail().strip() or f"the CLI exited {result.exit}"
            return failure("cli-error", self._redact(tail), exit=result.exit, events=result.events)
        return None

    async def _collect(
        self,
        subcommand: str,
        args: list[str],
        *,
        timeout: float,
        needs_owned: bool = False,
    ) -> tuple[RunResult | None, Result | None]:
        gate = self._cli_gate()
        if gate is not None:
            return None, gate
        if needs_owned and not self.store.owned_apps_exists():
            return None, failure("owned-apps-missing", "Steam library not loaded")
        argv = [*self.cli, "--json", subcommand, *args]
        try:
            result = await self._spawn(argv, timeout=timeout)
        except OSError as exc:
            return None, failure("io", f"could not run the CLI: {exc}")
        return result, self._classify(result, timeout)

    @staticmethod
    def _notes(result: RunResult) -> list[str]:
        return [str(e.get("message", "")) for e in result.events if e.get("event") == "note"]

    @staticmethod
    def _of(result: RunResult, name: str) -> list[dict[str, Any]]:
        return [e for e in result.events if e.get("event") == name]

    # ------------------------------------------------------------------
    # versions and capabilities

    @guarded
    async def cli_version(self) -> Result:
        self.installed_version = await asyncio.to_thread(self._read_installed)
        self.bundled_version = await asyncio.to_thread(self._read_bundled)
        was_ok = self.cli_ok
        self._update_cli_ok()
        if self.cli_ok and (self._capabilities is None or not was_ok):
            self._capabilities = None
            await self.cli_capabilities()
        pinned = self._pinned()
        installed = install.format_version(self.installed_version)
        return {
            "ok": True,
            "installed": installed,
            "bundled": install.format_version(self.bundled_version),
            "minimum": install.format_version(install.MIN_CLI_VERSION),
            "too_old": self.installed_version is not None and not self.cli_ok,
            "installed_path": self.installed_cli,
            "bundled_path": self.bundled_cli,
            "pinned": pinned,
            "plugin_version": self.plugin_version or self._package_field("version"),
            "log_path": self.log_path,
            "install_error": self.install_error,
            "capabilities": dict(self._capabilities or {"art_commit": False}),
        }

    def _package_field(self, name: str) -> str | None:
        try:
            with open(os.path.join(self.plugin_dir, "package.json"), encoding="utf-8") as handle:
                value = json.load(handle).get(name)
        except (OSError, ValueError, AttributeError):
            return None
        return value if isinstance(value, str) else None

    def _pinned(self) -> str | None:
        return self._package_field("moonlightSteamSync")

    @guarded
    async def cli_capabilities(self) -> Result:
        if self._capabilities is not None:
            return {"ok": True, **self._capabilities}
        gate = self._cli_gate()
        if gate is not None:
            return gate
        try:
            result = await self._spawn(
                [*self.cli, "art", "--help"], timeout=self.TIMEOUT_SHORT, json_mode=False
            )
        except OSError as exc:
            return failure("io", f"could not run the CLI: {exc}")
        if result.timed_out:
            return failure("timeout", f"timed out after {self.TIMEOUT_SHORT:g} s")
        self._capabilities = {"art_commit": "--commit" in result.stdout}
        return {"ok": True, **self._capabilities}

    @guarded
    async def doctor(self) -> Result:
        gate = self._cli_gate()
        if gate is not None:
            return gate
        try:
            result = await self._spawn(
                [*self.cli, "doctor"], timeout=self.TIMEOUT_SHORT, json_mode=False
            )
        except OSError as exc:
            return failure("io", f"could not run the CLI: {exc}")
        if result.timed_out:
            return failure("timeout", f"timed out after {self.TIMEOUT_SHORT:g} s")
        if result.exit != 0:
            return failure(
                "cli-error",
                self._redact(result.stderr_tail().strip() or f"doctor exited {result.exit}"),
                exit=result.exit,
            )
        lines: dict[str, str] = {}
        for line in result.stdout.splitlines():
            if ":" not in line:
                continue
            label, _, value = line.partition(":")
            if label.strip():
                lines[label.strip()] = value.strip()
        return {"ok": True, "lines": lines, "raw": self._redact(result.stdout)}

    # ------------------------------------------------------------------
    # collecting runs

    @guarded
    async def status(self) -> Result:
        result, fail = await self._collect(
            "status",
            [*self._owned_args(), *self._host_app_args()],
            timeout=self.TIMEOUT_SHORT,
            needs_owned=True,
        )
        if fail is not None:
            return fail
        assert result is not None
        return {"ok": True, "entries": self._of(result, "entry"), "notes": self._notes(result)}

    def _list_result(self, result: RunResult) -> Result:
        apps = self._of(result, "app")
        end = ev.last_of(result.events, "end") or {}
        count = end.get("count")
        return {
            "ok": True,
            "apps": apps,
            "host": end.get("host"),
            "count": count if isinstance(count, int) else len(apps),
            "notes": self._notes(result),
        }

    def _reachable(self, host: str, listed: Result) -> Result:
        """A reachable ``check_host`` result, memoised.

        ``ignored`` (additive to spec 3.7's shape) is the number of ``app``
        events with kind ``ignored`` -- ``ignore.json`` and ``config.ignore``
        together -- so the panel's *Ignored* counter needs no second
        ``moonlight list``.
        """
        result: Result = {
            "ok": True,
            "host": host,
            "reachable": True,
            "count": listed["count"],
            "ignored": sum(1 for app in listed["apps"] if app.get("kind") == "ignored"),
            "checked_at": iso_now(),
        }
        self._host_memo[host] = (time.monotonic(), result)
        return result

    @guarded
    async def list_apps(self) -> Result:
        result, fail = await self._collect(
            "list",
            self._list_args(),
            timeout=self.TIMEOUT_LONG,
            needs_owned=True,
        )
        if fail is not None:
            return fail
        assert result is not None
        listed = self._list_result(result)
        if isinstance(listed["host"], str) and listed["host"]:
            self._reachable(listed["host"], listed)
        return listed

    @guarded
    async def list_cached(self, host: str) -> Result:
        if not isinstance(host, str) or not host.strip():
            return failure("bad-request", "a host name is required")
        result, fail = await self._collect(
            "list",
            ["--host", host.strip(), "--cached", *self._list_args()],
            timeout=self.TIMEOUT_SHORT,
            needs_owned=True,
        )
        if fail is not None:
            return fail
        assert result is not None
        return self._list_result(result)

    async def _cached_host_info(self, name: str) -> tuple[str | None, int | None]:
        """``last_seen`` / ``cached_count`` for ``name`` from ``host show``."""
        shown = await self.hosts()
        if not shown.get("ok"):
            return None, None
        for cached in shown.get("cached_hosts") or []:
            if isinstance(cached, dict) and str(cached.get("name", "")).lower() == name.lower():
                count = cached.get("count")
                return cached.get("when"), count if isinstance(count, int) else None
        return None, None

    async def _unreachable(self, host: str, fail: Result) -> Result:
        last_seen, cached_count = await self._cached_host_info(host)
        result: Result = {
            "ok": True,
            "host": host,
            "reachable": False,
            "message": fail.get("message", ""),
            "exit": 3,
            "last_seen": last_seen,
            "cached_count": cached_count,
            "checked_at": iso_now(),
        }
        self._host_memo[host] = (time.monotonic(), result)
        return result

    @staticmethod
    def _is_unreachable(fail: Result | None) -> bool:
        return bool(fail and fail.get("error") == "cli-error" and fail.get("exit") == 3)

    @guarded
    async def check_host(self, name: str, force: bool = False) -> Result:
        if not isinstance(name, str) or not name.strip():
            return failure("bad-request", "a host name is required")
        name = name.strip()
        memo = self._host_memo.get(name)
        if memo is not None and not force and time.monotonic() - memo[0] < self.CHECK_HOST_TTL:
            return memo[1]
        result, fail = await self._collect(
            "list",
            ["--host", name, *self._list_args()],
            timeout=self.TIMEOUT_LONG,
            needs_owned=True,
        )
        if self._is_unreachable(fail):
            assert fail is not None
            return await self._unreachable(name, fail)
        if fail is not None:
            return fail
        assert result is not None
        return self._reachable(name, self._list_result(result))

    # ------------------------------------------------------------------
    # hosts

    @guarded
    async def hosts(self) -> Result:
        result, fail = await self._collect("host", ["show"], timeout=self.TIMEOUT_SHORT)
        active: str | None = None
        source: str | None = None
        cached_hosts: list[Any] = []
        if fail is not None:
            # "no host configured" is contractual: spec 3.4.6's `host` bullet
            # pins the wording of `host show`'s exit-1 error, and the CLI's own
            # tests assert it. Anything else that exits 1 is a real failure.
            no_host = (
                fail.get("error") == "cli-error"
                and fail.get("exit") == 1
                and "no host configured" in str(fail.get("message", ""))
            )
            if not no_host:
                return fail
        else:
            assert result is not None
            shown = ev.last_of(result.events, "host") or {}
            active = shown.get("name") if isinstance(shown.get("name"), str) else None
            source = shown.get("source") if isinstance(shown.get("source"), str) else None
            raw_cached = shown.get("cached_hosts")
            cached_hosts = raw_cached if isinstance(raw_cached, list) else []
        if not self.store.hosts_seeded():
            seed: list[str] = []
            names = [active] + [c.get("name") for c in cached_hosts if isinstance(c, dict)]
            for name in names:
                if isinstance(name, str) and name and name.lower() not in {s.lower() for s in seed}:
                    seed.append(name)
            self.store.set_hosts(seed)
            self._log(f"seeded known hosts: {seed}")
        known = self.store.settings()["hosts"]
        # The active host too, when it is not among the known ones (set by
        # `--host` or the CLI's config after the seed): the panel offers it
        # in the dropdown, so it gets its Wake as well. Moonlight.conf is
        # parsed once for the whole map.
        entries = wake.moonlight_entries(self.home)
        wanted: list[str] = []
        for name in [active, *known]:
            if isinstance(name, str) and name.lower() not in {w.lower() for w in wanted}:
                wanted.append(name)
        wake_map = {
            name: info for name in wanted if (info := self._wake_info(name, entries)) is not None
        }
        return {
            "ok": True,
            "active": active,
            "source": source,
            "cached_hosts": cached_hosts,
            "known": known,
            "wake": wake_map,
        }

    # ------------------------------------------------------------------
    # Wake-on-LAN (spec 3.18)

    def _wake_info(
        self, name: str, entries: list[dict[str, Any]] | None = None
    ) -> dict[str, Any] | None:
        """``{mac, source, addresses}`` for ``name``: the setting first, else Moonlight's list.

        ``entries`` is ``wake.moonlight_entries`` already read, for a caller
        resolving several names; ``None`` reads it here.
        """
        if entries is None:
            entries = wake.moonlight_entries(self.home)
        entry = wake.find_host(entries, name)
        addresses = list(entry["addresses"]) if entry is not None else []  # type: ignore[arg-type]
        stored = self.store.wake_mac(name)
        if stored is not None:
            return {"mac": stored, "source": "settings", "addresses": addresses}
        if entry is not None and isinstance(entry.get("mac"), str):
            return {"mac": entry["mac"], "source": "moonlight", "addresses": addresses}
        return None

    @guarded
    async def wake_host(self, name: str) -> Result:
        """Send a Wake-on-LAN magic packet to ``name`` (spec 3.18). No CLI, no busy guard.

        The MAC is the Host page's setting when one is stored, else the one
        in Moonlight's own host list; with neither the answer is ``no-mac``.
        The packet goes to the broadcast address and to every address
        Moonlight knows for the host, in a worker thread (a hostname among
        them resolves with a blocking ``getaddrinfo``); only when not one
        datagram could be sent is it ``io``. Sending proves nothing about
        the PC, so the result only says what went out; the panel's *Retry*
        is the check.
        """
        if not isinstance(name, str) or not name.strip():
            return failure("bad-request", "a host name is required")
        name = name.strip()
        info = self._wake_info(name)
        if info is None:
            return failure(
                "no-mac",
                f"No MAC address known for {name}: Moonlight has none for it; "
                "enter one on the Host page",
            )
        # Off the loop: a hostname in Moonlight's address list (a manualaddress
        # or DDNS name) resolves with a blocking getaddrinfo, and a stale one
        # can take seconds per port, which must not stall a run's relay.
        sent, errors = await asyncio.to_thread(
            wake.send_magic_packet, info["mac"], info["addresses"]
        )
        for line in errors:
            self._log(f"wake_host {name}: {line}")
        if sent == 0:
            why = errors[0] if errors else "no target"
            return failure("io", f"could not send a Wake-on-LAN packet: {why}")
        self._log(f"wake_host {name}: {sent} packets sent ({info['source']} MAC)")
        self._host_memo.pop(name, None)
        return {
            "ok": True,
            "host": name,
            "mac": info["mac"],
            "source": info["source"],
            "sent": sent,
        }

    @guarded
    async def set_wake_mac(self, name: str, mac: Any = None) -> Result:
        """Store or drop (``mac`` ``None`` / empty) one known host's Wake-on-LAN MAC."""
        if not isinstance(name, str) or not name.strip():
            return failure("bad-request", "a host name is required")
        name = name.strip()
        known = self._known_match(name)
        if known is None:
            return failure("bad-request", f"{name} is not a known host; add it first")
        stored = self.store.set_wake_mac(known, mac)
        return {"ok": True, "host": known, "mac": stored, "wake": self._wake_info(known)}

    def _known_match(self, name: str) -> str | None:
        for known in self.store.settings()["hosts"]:
            if known.lower() == name.lower():
                return known
        return None

    @guarded
    async def set_host(self, name: str) -> Result:
        if not isinstance(name, str):
            return failure("bad-request", "a host name is required")
        name = name.strip()
        if name == "":
            result, fail = await self._collect("host", ["clear"], timeout=self.TIMEOUT_SHORT)
            if fail is not None:
                return fail
            assert result is not None
            shown = ev.last_of(result.events, "host") or {}
            active = shown.get("name")
            return {"ok": True, "active": active if isinstance(active, str) else None}
        known = self._known_match(name)
        if known is None:
            return failure("bad-request", f"{name} is not a known host; add it first")
        result, fail = await self._collect("host", ["set", known], timeout=self.TIMEOUT_SHORT)
        if fail is not None:
            return fail
        assert result is not None
        shown = ev.last_of(result.events, "host") or {}
        active = shown.get("name")
        return {"ok": True, "active": active if isinstance(active, str) else known}

    @guarded
    async def add_host(self, name: str) -> Result:
        if not isinstance(name, str):
            return failure("bad-request", "a host name is required")
        name = name.strip()
        if not name or any(ch.isspace() for ch in name) or "/" in name:
            return failure("bad-request", "a host name has no spaces or slashes")
        result, fail = await self._collect(
            "list",
            ["--host", name, *self._list_args()],
            timeout=self.TIMEOUT_LONG,
            needs_owned=True,
        )
        if self._is_unreachable(fail):
            assert fail is not None
            self._host_memo[name] = (
                time.monotonic(),
                {
                    "ok": True,
                    "host": name,
                    "reachable": False,
                    "message": fail.get("message", ""),
                    "exit": 3,
                    "last_seen": None,
                    "cached_count": None,
                    "checked_at": iso_now(),
                },
            )
            return fail
        if fail is not None:
            return fail
        assert result is not None
        listed = self._list_result(result)
        count = listed["count"]
        self._reachable(name, listed)
        shown = await self.hosts()  # seeds settings.hosts first when needed
        known = list(self.store.settings()["hosts"])
        if self._known_match(name) is None:
            known.append(name)
            self.store.set_hosts(known)
        made_active = False
        if shown.get("ok") and shown.get("active") is None:
            _, set_fail = await self._collect("host", ["set", name], timeout=self.TIMEOUT_SHORT)
            made_active = set_fail is None
            if set_fail is not None:
                self._log(f"add_host: host set {name} failed: {set_fail.get('message')}")
        return {"ok": True, "count": count, "made_active": made_active}

    @guarded
    async def forget_host(self, name: str) -> Result:
        if not isinstance(name, str) or not name.strip():
            return failure("bad-request", "a host name is required")
        name = name.strip()
        shown = await self.hosts()
        if shown.get("ok"):
            active = shown.get("active")
            if isinstance(active, str) and active.lower() == name.lower():
                return failure("bad-request", "switch to another host first")
        elif shown.get("error") not in ("cli-missing", "cli-too-old"):
            return shown
        remaining = [h for h in self.store.settings()["hosts"] if h.lower() != name.lower()]
        self.store.set_hosts(remaining)
        self._host_memo.pop(name, None)
        return {"ok": True, "known": remaining}

    # ------------------------------------------------------------------
    # plugin files

    @guarded
    async def get_settings(self) -> Result:
        return {"ok": True, "settings": self.store.settings()}

    @guarded
    async def set_settings(self, patch: Any) -> Result:
        return {"ok": True, "settings": self.store.set_settings(patch)}

    @guarded
    async def set_default_layout(self, url: Any = None, title: Any = None) -> Result:
        """Store or clear the plugin's default controller layout (spec 3.16.2).

        No CLI and no busy guard: this only touches ``settings.json`` and
        ``pending.json``. ``url`` ``None`` clears the default; otherwise it
        must start with one of ``settings.DEFAULT_LAYOUT_SCHEMES``. Either
        way ``pending.layout_walk`` is set, so PR-10's walk (unset or apply)
        picks it up at the next load or panel open.
        """
        settings = self.store.set_default_layout(url, title, when=iso_now())
        self._log(f"default layout set: {url}" if url else "default layout cleared")
        return {"ok": True, "settings": settings, "pending": self.store.pending()}

    @guarded
    async def get_ignored(self) -> Result:
        return {"ok": True, "ignored": self.store.ignored()}

    @guarded
    async def write_owned_apps(self, steamid3: Any, apps: Any) -> Result:
        if isinstance(steamid3, bool) or not isinstance(steamid3, int) or steamid3 <= 0:
            return failure("bad-request", "steamid3 must be a positive integer")
        if not isinstance(apps, dict):
            return failure("bad-request", "apps must be an object of appid -> name")
        if not apps:
            return failure("owned-apps-empty", "Steam library not loaded")
        normalized: dict[str, str] = {}
        for appid, name in apps.items():
            key = str(appid)
            if not key.isdigit():
                return failure("bad-request", f"appid {key!r} is not a number")
            if not isinstance(name, str):
                return failure("bad-request", f"the name for appid {key} is not a string")
            normalized[key] = name
        count = self.store.write_owned_apps(steamid3, normalized)
        return {"ok": True, "count": count}

    @guarded
    async def pending(self) -> Result:
        return {"ok": True, **self.store.pending()}

    @guarded
    async def clear_pending(self, key: str) -> Result:
        return {"ok": True, **self.store.clear_pending(key)}

    @guarded
    async def log_tail(self, n: int = 50) -> Result:
        if isinstance(n, bool) or not isinstance(n, int) or n < 1:
            return failure("bad-request", "n must be a positive integer")
        n = min(n, 500)
        try:
            with open(self.log_path, encoding="utf-8", errors="replace") as handle:
                lines = collections.deque(handle, maxlen=n)
        except FileNotFoundError:
            return {"ok": True, "lines": []}
        key = self._effective_key()
        return {"ok": True, "lines": [self._redact(line.rstrip("\n"), key) for line in lines]}

    # ------------------------------------------------------------------
    # SteamGridDB key

    @guarded
    async def sgdb_key_state(self) -> Result:
        return keys.key_state(self.home, self.env).public()

    @guarded
    async def set_sgdb_key(self, key: Any) -> Result:
        try:
            state = keys.set_key(self.home, self.env, key)
        except keys.KeyRefused as exc:
            return failure(exc.code, exc.message)
        self._log("sgdb key file written")
        return state.public()

    @guarded
    async def clear_sgdb_key(self) -> Result:
        state = keys.clear_key(self.home, self.env)
        self._log("sgdb key file removed")
        return state.public()

    @guarded
    async def test_sgdb_key(self) -> Result:
        args = ["Portal"]
        if self.store.owned_apps_exists():
            args += self._owned_args()
        result, fail = await self._collect("search", args, timeout=self.TIMEOUT_LONG)
        if fail is not None:
            if fail.get("error") == "cli-error" and "401" in str(fail.get("message", "")):
                fail["message"] = "SteamGridDB rejected the key"
            elif fail.get("error") == "cli-error" and fail.get("exit") == 4:
                # The CLI's network hard stop: the key was never judged, so
                # do not let the failure read as a verdict on it.
                fail["message"] = (
                    "Could not reach SteamGridDB (network), so the key was not "
                    f"tested: {fail.get('message', '')}"
                )
            return fail
        assert result is not None
        if any(c.get("source") == "sgdb" for c in self._of(result, "candidate")):
            return {"ok": True}
        notes = self._notes(result)
        message = notes[0] if notes else 'SteamGridDB returned nothing for "Portal"'
        return failure("cli-error", self._redact(message), exit=result.exit, events=result.events)

    # ------------------------------------------------------------------
    # matching and ignoring (the Titles page)

    @staticmethod
    def _positional(value: str, options: list[str]) -> list[str]:
        """``[value, *options]``, the spec's argv order.

        A value that starts with ``-`` would be read by argparse as an
        option, so it goes last behind ``--`` instead: ``[*options, "--",
        value]`` (the same arguments to argparse).
        """
        if value.startswith("-"):
            return [*options, "--", value]
        return [value, *options]

    @staticmethod
    def _title_name(name: Any) -> str | None:
        """``name`` when it is a usable Moonlight name, else ``None``."""
        if not isinstance(name, str) or not name.strip():
            return None
        if "\n" in name or "\x00" in name:
            return None
        return name

    @guarded
    async def search(self, term: Any = None) -> Result:
        """``--json search "term" [--owned-apps …]`` -> the ``candidate`` events.

        ``--owned-apps`` is passed only when the file exists (spec 3.7), so
        a search still works before the library has loaded (every
        candidate then reads ``owned: false``). Candidates keep the CLI's
        order; the Change match modal groups them (owned first, then Steam
        before SteamGridDB).
        """
        term = self._title_name(term)
        if term is None:
            return failure("bad-request", "a search term is required")
        options = self._owned_args() if self.store.owned_apps_exists() else []
        result, fail = await self._collect(
            "search", self._positional(term.strip(), options), timeout=self.TIMEOUT_LONG
        )
        if fail is not None:
            return fail
        assert result is not None
        found = {
            "ok": True,
            "candidates": self._of(result, "candidate"),
            "notes": self._notes(result),
        }
        return self._scrub(found, self._effective_key())

    async def _match(self, name: str, selector: list[str]) -> Result:
        """``--json match NAME <selector> --defer-art`` -> the ``pinned`` event.

        ``--defer-art`` always (Decision 8): the pin is written to
        ``matches.json`` only, marked ``stale_art``, and the next sync
        replaces the entry and re-fetches its art in its one restart.

        Shares the long runs' busy guard, in both directions: a ``match``
        writes ``matches.json``, which a running ``sync`` / ``art`` /
        ``remove`` child is writing too -- so a match is refused while a run
        is going, and a run is refused while a match is in flight.
        """
        busy = self._busy()
        if busy is not None:
            return busy
        self._matching += 1
        try:
            result, fail = await self._collect(
                "match",
                self._positional(name, [*selector, "--defer-art"]),
                timeout=self.TIMEOUT_SHORT,
            )
        finally:
            self._matching -= 1
        if fail is not None:
            return fail
        assert result is not None
        pinned = ev.last_of(result.events, "pinned")
        if pinned is None:
            unconfirmed = failure(
                "cli-error",
                "the CLI did not confirm the pin (no pinned event)",
                exit=result.exit,
                events=result.events,
            )
            return self._scrub(unconfirmed, self._effective_key())
        self._log(f"match: {selector[0]} for {name!r}")
        confirmed = {"ok": True, "pinned": pinned, "notes": self._notes(result)}
        return self._scrub(confirmed, self._effective_key())

    @staticmethod
    def _appid(value: Any) -> int | None:
        """A positive integer id, else ``None`` (``bool`` is not an id)."""
        if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
            return None
        return value

    @guarded
    async def pin(
        self, name: Any = None, steam: Any = None, sgdb: Any = None, none: Any = False
    ) -> Result:
        """Pin exactly one of ``--steam APPID``, ``--sgdb ID`` or ``--none``."""
        name = self._title_name(name)
        if name is None:
            return failure("bad-request", "a title name is required")
        chosen: list[list[str]] = []
        if steam is not None:
            appid = self._appid(steam)
            if appid is None:
                return failure("bad-request", "steam must be a positive Steam appid")
            chosen.append(["--steam", str(appid)])
        if sgdb is not None:
            game = self._appid(sgdb)
            if game is None:
                return failure("bad-request", "sgdb must be a positive SteamGridDB id")
            chosen.append(["--sgdb", str(game)])
        if none is not False and none is not None:
            if none is not True:
                return failure("bad-request", "none must be true or false")
            chosen.append(["--none"])
        if len(chosen) != 1:
            return failure("bad-request", "pin needs exactly one of steam, sgdb or none")
        return await self._match(name, chosen[0])

    @guarded
    async def unpin(self, name: Any = None) -> Result:
        """``match NAME --unpin --defer-art``: the next run re-resolves the title."""
        name = self._title_name(name)
        if name is None:
            return failure("bad-request", "a title name is required")
        return await self._match(name, ["--unpin"])

    @guarded
    async def set_ignored(self, name: Any = None, ignored: Any = None) -> Result:
        """Add ``name`` to ``ignore.json`` (or remove it); sorted, idempotent.

        Takes effect on the next ``sync`` / ``list`` through
        ``--ignore-file``. The ``check_host`` memo is dropped because its
        ``ignored`` count is now stale.
        """
        name = self._title_name(name)
        if name is None:
            return failure("bad-request", "a title name is required")
        if not isinstance(ignored, bool):
            return failure("bad-request", "ignored must be true or false")
        names = self.store.set_ignored(name, ignored)
        self._host_memo.clear()
        self._log(f"{'ignored' if ignored else 'unignored'} {name!r}")
        return {"ok": True, "ignored": names}

    def match_cache_path(self) -> str:
        """The CLI's ``matches.json``, as the child would resolve it."""
        return match_cache_path(self.home, self._child_env())

    @guarded
    async def reset_match_cache(self) -> Result:
        """Delete the CLI's ``matches.json`` so the next run re-resolves every title.

        The user's decision of 2026-09-23: the whole file goes, pins
        included (a title pinned from the Titles page has to be pinned
        again). The file is the CLI's own cache and the one CLI file the
        plugin touches: it is deleted, never edited, and only under the busy
        guard in both directions, since a run or a ``match`` child could be
        writing it. The CLI has no reset of its own (only ``match --unpin``
        per title, and a miss is not asked again for seven days), which is
        why the plugin does it. ``removed`` says whether there was a file;
        ``titles`` / ``pins`` are what it held, for the toast. ``hosts/``
        beside it is left alone: the list cache holds no match.
        """
        busy = self._busy()
        if busy is not None:
            return busy
        path = self.match_cache_path()
        titles, pins = match_cache_counts(path)
        try:
            os.remove(path)
        except FileNotFoundError:
            removed = False
        else:
            removed = True
        self._log(
            f"reset match cache: {'deleted' if removed else 'no file at'} {path} "
            f"({titles} titles, {pins} pinned)"
        )
        return {"ok": True, "removed": removed, "titles": titles, "pins": pins}

    # ------------------------------------------------------------------
    # controller layouts (spec 3.10)

    @guarded
    async def layouts(self) -> Result:
        """``layouts.json``: the last layout result per hidden shortcut."""
        return {"ok": True, **self.store.layouts()}

    @guarded
    async def record_layout(
        self,
        shortcut_appid: Any = None,
        real_appid: Any = None,
        result: Any = None,
        url: Any = None,
    ) -> Result:
        """Upsert one shortcut's ``{real_appid, result, url, when, applied}``
        atomically.

        ``result`` is ``copied`` / ``kept`` / ``unavailable`` / ``default``
        (a Stream press or the post-restart walk) or ``picker`` (*Choose
        layout*). No CLI and no Steam file is involved: this only records
        what the frontend did through Steam Input. ``real_appid`` may be
        ``None`` for any result (spec 3.16.2): host apps, the client and a
        title never matched have no game behind them. ``applied`` is
        computed by ``Store.record_layout`` (its docstring has the table).
        """
        data = self.store.record_layout(shortcut_appid, real_appid, result, url, when=iso_now())
        game = "no game" if real_appid is None else f"Steam {real_appid}"
        self._log(f"layout {result} for shortcut {shortcut_appid} ({game}): {url or '-'}")
        return {"ok": True, **data}

    # ------------------------------------------------------------------
    # long runs

    def _busy(self) -> Result | None:
        """The one busy guard, shared by the long runs and by ``match``.

        ``kind`` says which side is holding it: a run kind (``sync`` /
        ``art`` / ``remove``) or ``"match"`` for a pin or unpin still being
        written. The frontend turns the two into different sentences
        (``errorText``).
        """
        if self._run is not None and self._run.running:
            return failure("busy", "A sync is already running", kind=self._run.kind)
        if self._matching:
            return failure("busy", "A match change is still being saved", kind="match")
        return None

    @staticmethod
    def _bool_opt(opts: dict[str, Any], key: str, default: bool) -> bool:
        value = opts.get(key, default)
        if not isinstance(value, bool):
            raise SettingsError(f"{key} must be true or false")
        return value

    def _opts(self, opts: Any) -> dict[str, Any]:
        if opts is None:
            return {}
        if not isinstance(opts, dict):
            raise SettingsError("opts must be an object")
        return opts

    @guarded
    async def start_sync(self, opts: Any = None) -> Result:
        opts = self._opts(opts)
        retry = self._bool_opt(opts, "retry_missing", bool(self.store.settings()["retry_missing"]))
        immediate = self._bool_opt(opts, "immediate_restart", False)
        gate = self._cli_gate() or self._busy()
        if gate is not None:
            return gate
        if not self.store.owned_apps_exists():
            return failure("owned-apps-missing", "Steam library not loaded")
        args = [
            *self._owned_args(),
            *self._ignore_args(),
            "--client-shortcut",
            "--park-unpublished",
            *self._host_app_args(),
            "--commit",
            "await-exit",
        ]
        if retry:
            args.append("--retry-missing")
        return self._start_run(
            "sync", "sync", args, {"retry_missing": retry, "immediate_restart": immediate}
        )

    @guarded
    async def start_art_refetch(self, opts: Any = None) -> Result:
        opts = self._opts(opts)
        immediate = self._bool_opt(opts, "immediate_restart", False)
        gate = self._cli_gate() or self._busy()
        if gate is not None:
            return gate
        caps = await self.cli_capabilities()
        if not caps.get("ok"):
            return caps
        if not caps.get("art_commit"):
            return failure(
                "cli-too-old",
                "re-fetching art from Game Mode needs a CLI whose art command accepts --commit",
                installed=install.format_version(self.installed_version),
                minimum=install.format_version(install.MIN_CLI_VERSION),
            )
        busy = self._busy()
        if busy is not None:
            return busy
        return self._start_run(
            "art", "art", ["--force", "--commit", "await-exit"], {"immediate_restart": immediate}
        )

    @guarded
    async def start_remove_all(self, opts: Any = None) -> Result:
        opts = self._opts(opts)
        immediate = self._bool_opt(opts, "immediate_restart", False)
        gate = self._cli_gate() or self._busy()
        if gate is not None:
            return gate
        return self._start_run(
            "remove",
            "remove",
            ["--all", "--client", "--commit", "await-exit"],
            {"immediate_restart": immediate},
        )

    def _start_run(
        self, kind: str, subcommand: str, args: list[str], opts: dict[str, Any]
    ) -> Result:
        """Register the run synchronously (the busy guard) and start its task."""
        run = RunState(
            kind=kind,
            opts=opts,
            started=iso_now(),
            recent=collections.deque(maxlen=self.EVENT_RING),
        )
        self._run = run
        argv = [*self.cli, "--json", subcommand, *args]
        run.task = asyncio.get_running_loop().create_task(self._drive(run, argv))
        return {"ok": True, "kind": kind}

    async def _on_run_event(self, run: RunState, event: dict[str, Any], key: str) -> None:
        name = event.get("event")
        run.events.append(event)
        run.recent.append(event)
        if name == "plan":
            run.plan = event
        elif name == "awaiting-steam-exit":
            # Written *before* the event is relayed: a reload or a crash
            # mid-wait must still find the persistent restart row (spec 3.9).
            previous = self.store.pending()
            self.store.write_pending(
                {
                    **previous,
                    "restart_needed": "write",
                    "layout_walk": False,
                    "since": iso_now(),
                    "last_plan": run.plan,
                    "last_kind": run.kind,
                }
            )
            run.awaiting_exit = True
        elif name == "commit" and event.get("written") is True:
            run.awaiting_exit = False
            if run.kind == "remove":
                self.store.delete_layouts()
            self.store.write_pending(
                {
                    **self.store.pending(),
                    "restart_needed": "none",
                    "layout_walk": run.kind != "remove",
                    "since": iso_now(),
                    "last_plan": run.plan,
                    "last_kind": run.kind,
                }
            )
        await self._emit("sync_event", {"kind": run.kind, "event": self._scrub(event, key)})

    def _run_started(self, run: RunState, proc: asyncio.subprocess.Process) -> None:
        """The run's child exists; honour a stop that arrived before it did."""
        run.proc = proc
        run.spawned = True
        if run.stop_requested:
            self._log(f"stop: SIGINT to the {run.kind} run (asked for before it started)")
            self._interrupt(proc)

    async def _drive(self, run: RunState, argv: list[str]) -> None:
        key = self._effective_key()
        exit_code: int
        try:
            result = await self._spawn(
                argv,
                timeout=None,
                on_event=lambda event: self._on_run_event(run, event, key),
                on_proc=lambda proc: self._run_started(run, proc),
            )
            exit_code = result.exit
            run.failure = self._classify(result, None)
        except CliOutputError as exc:
            self._log(f"{run.kind}: {exc}")
            exit_code = exc.exit
            run.failure = failure("io", f"could not run the CLI: {exc}")
        except OSError as exc:
            self._log(f"{run.kind}: could not start: {exc}")
            exit_code = 127
            run.failure = failure("io", f"could not run the CLI: {exc}")
        except Exception:
            self._log(f"{run.kind} failed:\n{traceback.format_exc()}")
            exit_code = 1
            run.failure = failure("bad-request", "the run failed; see the log")
        if (
            run.stop_requested
            and exit_code != 0
            and not ev.saw(run.events, "start")
            # ... and a child really existed, or died of a signal. Without
            # this a spawn failure (OSError -> exit 127, no child) that
            # happened to coincide with a stop would be reported as a clean
            # stop and its io failure thrown away.
            and (run.spawned or exit_code < 0)
        ):
            # The stop landed before the CLI could install its SIGINT handler,
            # so the signal killed it outright (exit -2) with nothing printed.
            # That is still a clean stop, not a protocol error.
            self._log(f"{run.kind}: stopped before the CLI printed anything (exit {exit_code})")
            exit_code = 130
            run.failure = None
        run.exit = exit_code
        try:
            pending = ev.next_pending(
                self.store.pending(),
                kind=run.kind,
                events=run.events,
                exit_code=exit_code,
                now=iso_now(),
            )
            pending = self.store.write_pending(pending)
        except OSError as exc:
            self._log(f"could not write pending.json: {exc}")
            pending = self.store.pending()
        run.running = False
        run.awaiting_exit = False
        run.proc = None
        self._last_run = run
        fail = run.failure
        await self._emit(
            "sync_done",
            {
                "kind": run.kind,
                "exit": exit_code,
                "pending": pending,
                "summary": ev.last_of(run.events, "summary"),
                "commit": ev.last_of(run.events, "commit"),
                "failure": (
                    None
                    if fail is None
                    else {k: v for k, v in fail.items() if k in ("error", "message", "exit")}
                ),
            },
        )

    @guarded
    async def stop_sync(self) -> Result:
        run = self._run
        if run is None or not run.running:
            return {"ok": True, "running": False}
        run.stop_requested = True
        if run.proc is None:
            # Registered (the busy guard says "running") but not spawned yet:
            # _run_started sends the signal as soon as the child exists.
            self._log(f"stop: the {run.kind} run has not spawned yet; it will be interrupted")
            return {"ok": True, "running": True}
        self._log(f"stop: SIGINT to the {run.kind} run")
        self._interrupt(run.proc)
        return {"ok": True, "running": True}

    @guarded
    async def sync_state(self) -> Result:
        run = self._run
        last = self._last_run
        running = run is not None and run.running
        shown = run if running else last
        events: list[dict[str, Any]] = []
        if shown is not None:
            recent = list(shown.recent)
            if shown.plan is not None and not any(e is shown.plan for e in recent):
                events.append(shown.plan)
            events.extend(recent)
        key = self._effective_key()
        return {
            "ok": True,
            "running": running,
            "kind": run.kind if running and run is not None else None,
            "started": run.started if running and run is not None else None,
            "opts": dict(run.opts) if running and run is not None else {},
            "awaiting_exit": bool(running and run is not None and run.awaiting_exit),
            "last_exit": last.exit if last is not None else None,
            "last_kind": last.kind if last is not None else None,
            "events": [self._scrub(e, key) for e in events],
        }

    async def wait_for_run(self) -> None:
        """Test helper: wait until the current long run (if any) has finished."""
        run = self._run
        if run is not None and run.task is not None:
            await run.task
