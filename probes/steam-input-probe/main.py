"""Backend of the steam-input-probe plugin (Moonlight Sync spec, PR-0).

Two jobs, nothing else:

* ``log(line)`` appends one line to ``~/homebrew/logs/steam-input-probe.log``
  with an ISO timestamp in milliseconds. Every probe in the frontend logs
  through it, so the whole run can be read from the file alone.
* ``start_steam_watch()`` starts the V3 watcher: an asyncio task that runs
  ``pgrep -x steam`` every 100 ms for 60 s, logs every state change (with
  ``pgrep -a -x steam`` and ``/proc/<pid>/cmdline`` so a wrapper script
  named ``steam`` can be told apart from the real client), a heartbeat once
  a second, and a summary of every gap (empty -> non-empty). The task lives
  in plugin_loader, so it survives the Steam client being shut down.

The backend never touches the Steam directory and never runs the CLI. Its
only write is the log file above.
"""

from __future__ import annotations

import asyncio
import datetime
import os
import time
from typing import Any

import decky

WATCH_DURATION_S = 60.0
WATCH_INTERVAL_MS = 100
HEARTBEAT_MS = 1000


def _now_iso() -> str:
    return datetime.datetime.now().astimezone().isoformat(timespec="milliseconds")


def _log_path() -> str:
    home = getattr(decky, "DECKY_HOME", None)
    if not home:
        user_home = getattr(decky, "DECKY_USER_HOME", None) or os.path.expanduser("~")
        home = os.path.join(user_home, "homebrew")
    return os.path.join(home, "logs", "steam-input-probe.log")


def _fmt_pids(pids: list[int]) -> str:
    return ",".join(str(p) for p in pids) if pids else "-"


def compute_gaps(samples: list[tuple[int, list[int]]]) -> list[dict[str, Any]]:
    """Every run of empty samples: from the first empty sample to the first
    non-empty one after it. ``back_at_ms`` is None when the run is still
    empty at the end of the recording. Mirrors run_probes.compute_gaps."""
    gaps: list[dict[str, Any]] = []
    open_gap: dict[str, Any] | None = None
    for t_ms, pids in samples:
        if not pids:
            if open_gap is None:
                open_gap = {"empty_at_ms": t_ms, "back_at_ms": None, "gap_ms": None, "empty_samples": 0}
            open_gap["empty_samples"] += 1
        elif open_gap is not None:
            open_gap["back_at_ms"] = t_ms
            open_gap["gap_ms"] = t_ms - open_gap["empty_at_ms"]
            gaps.append(open_gap)
            open_gap = None
    if open_gap is not None:
        gaps.append(open_gap)
    return gaps


class Plugin:
    _watch_task: asyncio.Task | None = None
    _watch_state: dict[str, Any] = {"running": False, "started": None, "samples": 0, "changes": [], "gaps": []}

    # ---- logging ---------------------------------------------------------

    def _write(self, line: str) -> str:
        path = _log_path()
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(f"{_now_iso()} {line}\n")
        return path

    async def log(self, line: str = "") -> dict[str, Any]:
        try:
            path = self._write(str(line))
            return {"ok": True, "path": path}
        except Exception as exc:  # noqa: BLE001 - the frontend logs it
            decky.logger.exception("log failed")
            return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}

    async def log_path(self) -> dict[str, Any]:
        return {"ok": True, "path": _log_path()}

    # ---- V3: the Steam restart watcher -----------------------------------

    async def _pgrep(self, *args: str) -> tuple[int, str]:
        proc = await asyncio.create_subprocess_exec(
            "pgrep", *args, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
        )
        out, err = await proc.communicate()
        text = out.decode(errors="replace").strip()
        if err:
            text += " stderr=" + err.decode(errors="replace").strip()
        return int(proc.returncode if proc.returncode is not None else -1), text

    @staticmethod
    def _cmdline(pid: int) -> str:
        try:
            with open(f"/proc/{pid}/cmdline", "rb") as fh:
                raw = fh.read()
            return raw.replace(b"\0", b" ").decode(errors="replace").strip() or "<empty>"
        except OSError as exc:
            return f"<unreadable: {exc}>"

    async def _watch(self, duration_s: float, interval_ms: int) -> None:
        state = self._watch_state
        samples: list[tuple[int, list[int]]] = []
        start = time.monotonic()
        last_pids: list[int] | None = None
        last_heartbeat = -HEARTBEAT_MS
        max_poll_ms = 0
        prev_t = 0
        try:
            self._write(
                f"steam-watch start duration_s={duration_s} interval_ms={interval_ms} "
                f"uid={os.getuid()} pid={os.getpid()}"
            )
            while True:
                t_ms = round((time.monotonic() - start) * 1000)
                if t_ms >= duration_s * 1000:
                    break
                rc, out = await self._pgrep("-x", "steam")
                pids = sorted(int(p) for p in out.split() if p.isdigit())
                samples.append((t_ms, pids))
                state["samples"] = len(samples)
                if len(samples) > 1:
                    max_poll_ms = max(max_poll_ms, t_ms - prev_t)
                prev_t = t_ms
                if pids != last_pids:
                    rc_a, out_a = await self._pgrep("-a", "-x", "steam")
                    cmdlines = "; ".join(f"{p}: {self._cmdline(p)}" for p in pids) or "-"
                    was = "none" if last_pids is None else _fmt_pids(last_pids)
                    line = (
                        f"steam-watch change sample t={t_ms} rc={rc} pids={_fmt_pids(pids)} "
                        f"(was pids={was}) pgrep-a(rc={rc_a})=[{out_a.replace(chr(10), '; ') or '-'}] "
                        f"cmdline=[{cmdlines}]"
                    )
                    self._write(line)
                    state["changes"].append({"t_ms": t_ms, "rc": rc, "pids": pids, "wall": _now_iso()})
                    last_pids = pids
                if t_ms - last_heartbeat >= HEARTBEAT_MS:
                    last_heartbeat = t_ms
                    self._write(
                        f"steam-watch heartbeat t={t_ms} rc={rc} pids={_fmt_pids(pids)} "
                        f"samples={len(samples)} max_poll_ms={max_poll_ms}"
                    )
                elapsed_ms = (time.monotonic() - start) * 1000 - t_ms
                await asyncio.sleep(max(0.0, (interval_ms - elapsed_ms) / 1000))
        except asyncio.CancelledError:
            self._write("steam-watch cancelled (plugin unloading)")
            raise
        except Exception as exc:  # noqa: BLE001
            self._write(f"steam-watch error {type(exc).__name__}: {exc}")
            decky.logger.exception("steam watch failed")
        finally:
            gaps = compute_gaps(samples)
            state["gaps"] = gaps
            state["running"] = False
            total_ms = int((time.monotonic() - start) * 1000)
            self._write(
                f"steam-watch summary duration_ms={total_ms} samples={len(samples)} "
                f"changes={len(state['changes'])} gaps={len(gaps)} max_poll_ms={max_poll_ms}"
            )
            for i, gap in enumerate(gaps, 1):
                back = gap["back_at_ms"]
                self._write(
                    f"steam-watch gap #{i}: empty at t={gap['empty_at_ms']} "
                    + (
                        f"non-empty at t={back} gap_ms={gap['gap_ms']}"
                        if back is not None
                        else "still empty at the end of the watch (gap open)"
                    )
                    + f" empty_samples={gap['empty_samples']}"
                )
            if not gaps:
                self._write("steam-watch gap: none (pgrep -x steam never came back empty)")
            self._write("steam-watch done")

    async def start_steam_watch(
        self, duration_s: float = WATCH_DURATION_S, interval_ms: int = WATCH_INTERVAL_MS
    ) -> dict[str, Any]:
        """Start the watcher and return at once; the frontend calls
        StartShutdown(false) only after this acknowledgement."""
        try:
            if self._watch_task is not None and not self._watch_task.done():
                return {"ok": False, "busy": True, "error": "a steam watch is already running"}
            duration_s = float(duration_s)
            interval_ms = int(interval_ms)
            if not (1 <= duration_s <= 600) or not (20 <= interval_ms <= 5000):
                return {"ok": False, "error": "duration_s must be 1..600 and interval_ms 20..5000"}
            self._watch_state = {
                "running": True,
                "started": _now_iso(),
                "samples": 0,
                "changes": [],
                "gaps": [],
                "duration_s": duration_s,
                "interval_ms": interval_ms,
            }
            self._watch_task = asyncio.get_running_loop().create_task(self._watch(duration_s, interval_ms))
            # Let the task take its first sample so the log shows the baseline
            # before the client goes away.
            await asyncio.sleep(interval_ms / 1000 * 2)
            return {"ok": True, "started": self._watch_state["started"], "duration_s": duration_s, "path": _log_path()}
        except Exception as exc:  # noqa: BLE001
            decky.logger.exception("start_steam_watch failed")
            return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}

    async def steam_watch_state(self) -> dict[str, Any]:
        state = dict(self._watch_state)
        state["running"] = self._watch_task is not None and not self._watch_task.done()
        return {"ok": True, **state}

    # ---- lifecycle ---------------------------------------------------------

    async def _main(self) -> None:
        decky.logger.info("steam-input-probe backend loaded; log file %s", _log_path())
        try:
            self._write("backend loaded")
        except Exception:  # noqa: BLE001
            decky.logger.exception("cannot write the probe log")

    async def _unload(self) -> None:
        task = self._watch_task
        if task is not None and not task.done():
            task.cancel()
            try:
                await task
            except (asyncio.CancelledError, Exception):  # noqa: BLE001
                pass
        decky.logger.info("steam-input-probe backend unloaded")

    async def _uninstall(self) -> None:
        pass
