/** Small text helpers for the panel: relative times and the *Last sync* line. */

import type { Pending, SummaryEvent } from "./cli";

function pad(n: number): string {
  return String(n).padStart(2, "0");
}

function startOfDay(date: Date): number {
  return new Date(date.getFullYear(), date.getMonth(), date.getDate()).getTime();
}

/** "today 14:02", "yesterday 09:15", "3 days ago", or the date for older ones. */
export function relativeTime(iso: string | null | undefined, now: Date = new Date()): string {
  if (!iso) return "never";
  const when = new Date(iso);
  if (Number.isNaN(when.getTime())) return iso;
  const days = Math.round((startOfDay(now) - startOfDay(when)) / 86_400_000);
  const clock = `${pad(when.getHours())}:${pad(when.getMinutes())}`;
  if (days <= 0) return `today ${clock}`;
  if (days === 1) return `yesterday ${clock}`;
  if (days < 7) return `${days} days ago`;
  return `${when.getFullYear()}-${pad(when.getMonth() + 1)}-${pad(when.getDate())}`;
}

function capitalize(text: string): string {
  return text ? text[0].toUpperCase() + text.slice(1) : text;
}

/** "2 added, 1 removed" / "5 images" / "nothing to do". */
export function summaryLine(summary: SummaryEvent): string {
  const parts: string[] = [];
  if (summary.added) parts.push(`${summary.added} added`);
  if (summary.replaced) parts.push(`${summary.replaced} replaced`);
  if (summary.removed) parts.push(`${summary.removed} removed`);
  if (!parts.length && summary.filled) {
    parts.push(`${summary.filled} ${summary.filled === 1 ? "image" : "images"}`);
  }
  if (summary.stop_reason) parts.push("stopped");
  return parts.length ? parts.join(", ") : "nothing to do";
}

/** The panel's *Last sync* row: "Today 14:02 · 2 added, 1 removed" (mockup screen 1). */
export function lastSyncLine(pending: Pending | null, now: Date = new Date()): string {
  if (!pending?.last_summary) return "Never";
  return `${capitalize(relativeTime(pending.since, now))} · ${summaryLine(pending.last_summary)}`;
}
