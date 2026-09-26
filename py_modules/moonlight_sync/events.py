"""The CLI's ``--json`` event stream (spec 3.4.6) and the restart table (spec 3.9).

:func:`restart_decision` is the same table as ``src/lib/restart.ts``'s
``restartDecision``; both are tested against the NDJSON files under
``tests/fixtures`` so they cannot drift apart.
"""

from __future__ import annotations

import json
from typing import Any

Event = dict[str, Any]


def parse_line(line: str) -> Event | None:
    """One stdout line -> an event object, or ``None`` when it is not one.

    A line that is not JSON, or is JSON without a string ``"event"``, is
    not an event; the runner logs it and never relays it.
    """
    text = line.strip()
    if not text:
        return None
    try:
        obj = json.loads(text)
    except ValueError:
        return None
    if not isinstance(obj, dict) or not isinstance(obj.get("event"), str):
        return None
    return obj


def last_of(events: list[Event], name: str) -> Event | None:
    for event in reversed(events):
        if event.get("event") == name:
            return event
    return None


def saw(events: list[Event], name: str) -> bool:
    return any(event.get("event") == name for event in events)


def _filled(events: list[Event]) -> int:
    summary = last_of(events, "summary")
    if summary is None:
        return 0
    filled = summary.get("filled", 0)
    return filled if isinstance(filled, int) and not isinstance(filled, bool) else 0


def restart_decision(events: list[Event], exit_code: int | None) -> str:
    """``"write"`` | ``"art"`` | ``"none"`` for a run's events (spec 3.9).

    - Trigger 1: the run emitted ``awaiting-steam-exit`` -> ``"write"``
      (a file write is coming, or was refused/stopped and still is).
    - Triggers 2 and 3: no wait, and ``summary.filled > 0`` (a finished
      art-only run, or a stopped run that saved images) -> ``"art"``.
    - Otherwise ``"none"`` (nothing to do, unreachable, nothing saved).

    ``exit_code`` is accepted for symmetry with the frontend's
    ``restartDecision(events, exit)``; the table does not depend on it.
    """
    del exit_code
    if saw(events, "awaiting-steam-exit"):
        return "write"
    if _filled(events) > 0:
        return "art"
    return "none"


def committed(events: list[Event]) -> bool:
    """True when the run emitted ``commit`` with ``written: true``."""
    commit = last_of(events, "commit")
    return bool(commit and commit.get("written") is True)


def settles_pending_write(kind: str, last_kind: Any) -> bool:
    """Does a clean run of ``kind`` settle a pending ``"write"`` left by
    ``last_kind``? (spec Decision 31.)

    A run that exits 0 without ever emitting ``awaiting-steam-exit`` wrote
    nothing *and had nothing to write* -- but only for its own kind. So it
    settles a pending write of the same kind, and a ``sync`` also settles a
    pending ``art`` (a sync patches icons too). A pending ``remove`` is only
    ever settled by another ``remove``: neither a sync nor an art run would
    have planned those removals.
    """
    if kind == last_kind:
        return True
    return kind == "sync" and last_kind == "art"


def next_pending(
    previous: dict[str, Any],
    *,
    kind: str,
    events: list[Event],
    exit_code: int | None,
    now: str,
) -> dict[str, Any]:
    """The ``pending.json`` a finished run leaves behind (spec 3.9).

    - ``commit.written`` -> ``restart_needed: "none"`` and ``layout_walk``
      true (false for a ``remove`` run: the entries are gone).
    - awaited but not written (Later, stopped, timed out) -> stays ``"write"``.
    - art only / stopped with images -> ``"art"``.
    - nothing -> ``restart_needed`` unchanged...

    ...**except** that a clean run (exit 0, no wait) settles a pending
    ``"write"`` it covers (:func:`settles_pending_write`, spec Decision 31):
    there is demonstrably nothing left to write for that kind, so the
    persistent restart row goes away -- to ``"art"`` when the run saved
    images, else to ``"none"``. A run that does not cover the pending kind,
    or that exited non-zero, leaves it exactly as it was.

    ``last_summary`` and ``since`` are the panel's *Last sync* row and always
    describe the run that just finished. ``last_kind`` and ``last_plan``
    describe the run that **owns** the current ``restart_needed`` instead, so
    they only move when a run sets or settles it: while a pending ``"write"``
    stands, whatever left it keeps naming itself. Otherwise a `sync` that
    found nothing to do would rename a pending `remove`'s write to
    ``"sync"`` -- which would make the restart row re-run `start_sync`, and
    make the sync after that settle the write as "same kind", clearing a
    pending remove with two syncs (exactly what Decision 31 forbids).
    Nothing reads ``last_kind`` as "the kind of the last summary":
    `Controller.restartRow()` uses it for the row's re-run and the *Last
    sync* row is built from ``since`` + ``last_summary``.

    ``synced_hosts`` gains the plan's host, stamped ``now``, whenever a
    ``sync`` got as far as its ``plan``, whatever its exit: the host was
    listed and planned for, which is what the Titles page shows. No other
    kind plans, and nothing drops a host from it.
    """
    pending = dict(previous)
    was_pending = previous.get("restart_needed", "none")
    was_kind = previous.get("last_kind")
    summary = last_of(events, "summary")
    plan = last_of(events, "plan")
    host = plan.get("host") if plan is not None else None
    if kind == "sync" and isinstance(host, str) and host:
        synced = previous.get("synced_hosts")
        pending["synced_hosts"] = {**(synced if isinstance(synced, dict) else {}), host: now}

    def owns() -> None:
        """This run set or settled ``restart_needed``: it owns the state now."""
        pending["last_kind"] = kind
        pending["last_plan"] = plan

    if summary is not None:
        pending.update(last_summary=summary, since=now)
    if committed(events):
        owns()
        pending.update(restart_needed="none", layout_walk=kind != "remove", since=now)
        return pending
    decision = restart_decision(events, exit_code)
    if decision == "write":
        owns()
        pending["restart_needed"] = "write"
        return pending
    # Decision 31: only a run that covers the pending write may lower it.
    may_lower = was_pending != "write" or (
        exit_code == 0 and settles_pending_write(kind, was_kind)
    )
    if not may_lower:
        return pending  # last_kind / last_plan still name the run that owns it
    if decision == "art":
        owns()
        pending.update(restart_needed="art", since=now)
    elif was_pending == "write":
        owns()
        pending.update(restart_needed="none", since=now)
    return pending
