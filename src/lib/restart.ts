/**
 * The restart decision table (spec 3.9), shared in spirit with the backend.
 *
 * `restartDecision(events, exit)` is the same table as `backend.py`'s
 * `events.restart_decision`: both are tested against `tests/fixtures`
 * (full-sync -> write, art-only -> art, nothing-to-do -> none,
 * stopped -> art, unreachable -> none), so they cannot drift apart.
 *
 * - Trigger 1, a write is coming: the run emitted `awaiting-steam-exit`.
 *   The CLI emits `commit` only after the client has gone, so this event --
 *   not `sync_done` -- is when the frontend prompts.
 * - Trigger 2, art only: no wait, and `summary.filled > 0`.
 * - Trigger 3, stopped: as 2, with the "Stopped" wording.
 */

import type { CliEvent, PlanEvent, RunKind, SummaryEvent } from "./cli";
import { lastOf } from "./events";

export type RestartKind = "write" | "art" | "none";

export interface RestartDecision {
  kind: RestartKind;
  /** The modal's title (or, for `none`, the panel's one-line outcome; may be ""). */
  title: string;
  /** The line above the countdown ("" when there is none). */
  description: string;
}

function plural(n: number, one: string, many: string): string {
  return `${n} ${n === 1 ? one : many}`;
}

/** The run kind, from the `start` event's `command`. */
export function runKindOf(events: readonly CliEvent[]): RunKind {
  const start = lastOf(events, "start");
  const command = start?.command;
  return command === "art" || command === "remove" ? command : "sync";
}

/** "Sync finished: 2 added, 1 replaced, 1 parked" (spec 3.9; Q3 split when present). */
export function finishTitle(
  kind: RunKind,
  plan: PlanEvent | null,
  summary: SummaryEvent | null,
): string {
  if (kind === "remove") {
    return summary ? `Removed everything: ${plural(summary.removed, "entry", "entries")}` : "Removed everything";
  }
  if (kind === "art") return "Artwork re-fetched";
  if (summary?.added_by_kind) {
    const { shortcut, stream } = summary.added_by_kind;
    // Only under --hide-host-apps, and only worth a mention when one was
    // added: otherwise "0 shortcuts, 0 Stream buttons" beside "2 added".
    const hostApps = summary.added_by_kind["host-app"] ?? 0;
    const tail = hostApps > 0 ? `, ${plural(hostApps, "host app", "host apps")}` : "";
    return `Sync finished: ${plural(shortcut, "shortcut", "shortcuts")}, ${plural(stream, "Stream button", "Stream buttons")}${tail}`;
  }
  if (!plan) return "Sync finished";
  const parts = [`${plan.to_add} added`, `${plan.to_replace} replaced`];
  if (plan.to_park > 0) parts.push(`${plan.to_park} parked`);
  if (plan.to_unpark > 0) parts.push(`${plan.to_unpark} unparked`);
  return `Sync finished: ${parts.join(", ")}`;
}

function stopped(summary: SummaryEvent | null, exit: number | null): boolean {
  return !!summary?.stop_reason || exit === 130 || exit === 4;
}

export function restartDecision(events: readonly CliEvent[], exit: number | null): RestartDecision {
  const kind = runKindOf(events);
  const plan = lastOf(events, "plan");
  const summary = lastOf(events, "summary");
  if (lastOf(events, "awaiting-steam-exit")) {
    return { kind: "write", title: finishTitle(kind, plan, summary), description: "" };
  }
  const filled = summary?.filled ?? 0;
  if (filled > 0) {
    if (stopped(summary, exit)) {
      return {
        kind: "art",
        title: `Stopped; ${plural(filled, "image was", "images were")} saved`,
        description: "Restart Steam to show them, or sync again to resume.",
      };
    }
    return {
      kind: "art",
      title: "New artwork needs a Steam restart to show",
      description: `${plural(filled, "image", "images")} saved`,
    };
  }
  if (stopped(summary, exit)) {
    return { kind: "none", title: "Stopped; sync again to resume", description: "" };
  }
  const error = lastOf(events, "error");
  if (error) {
    const text = error.exit === 3 ? `Host unreachable: ${error.message}` : error.message;
    return { kind: "none", title: text, description: "" };
  }
  return { kind: "none", title: "", description: "" };
}

/** The ticking line under the modal's title (spec 3.9, including the in-game guard). */
export function countdownLine(secondsLeft: number, countdownEnabled: boolean, inGame: boolean): string {
  if (inGame) return "A game is running. Restart Steam when you're done.";
  if (!countdownEnabled) return "Restart Steam to show them.";
  return `Restarting Steam in ${secondsLeft} s to show them.`;
}

/**
 * The panel's one-line outcome after `sync_done` for a run that waited for
 * the client and ended without writing: exit 2 is the CLI's 60 s timeout.
 */
export function unwrittenMessage(exit: number): string {
  return exit === 2 ? "Steam did not restart; sync again to apply" : "";
}
