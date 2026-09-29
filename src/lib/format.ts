/** Small text helpers for the panel: relative times (past and future), dates and the *Last sync* line. */

import type { Pending, SummaryEvent } from "./cli";

function pad(n: number): string {
  return String(n).padStart(2, "0");
}

function startOfDay(date: Date): number {
  return new Date(date.getFullYear(), date.getMonth(), date.getDate()).getTime();
}

let clockSource: () => boolean | null = () => null;

/**
 * Where the 24-hour preference comes from: Steam's own setting at plugin
 * load (`steam.ts`'s `steamClock24h`), asked at every formatted time.
 * `null` (unknown, or no source set) is the 12-hour clock.
 */
export function setClockSource(source: () => boolean | null): void {
  clockSource = source;
}

function uses24h(): boolean {
  try {
    return clockSource() === true;
  } catch {
    return false;
  }
}

/** A time of day, "14:02", or with `hour12` "2:02 PM" (midnight "12:00 AM"). */
function clockText(when: Date, hour12: boolean): string {
  const hours = when.getHours();
  if (!hour12) return `${pad(hours)}:${pad(when.getMinutes())}`;
  return `${hours % 12 || 12}:${pad(when.getMinutes())} ${hours < 12 ? "AM" : "PM"}`;
}

/**
 * "today 2:02 PM", "yesterday 9:15 AM", "3 days ago", or the date for older
 * ones. The clock follows Steam's 24-hour setting ("today 14:02") unless
 * `hour12` says otherwise.
 */
export function relativeTime(
  iso: string | null | undefined,
  now: Date = new Date(),
  { hour12 = !uses24h() }: { hour12?: boolean } = {},
): string {
  if (!iso) return "never";
  const when = new Date(iso);
  if (Number.isNaN(when.getTime())) return iso;
  const days = Math.round((startOfDay(now) - startOfDay(when)) / 86_400_000);
  const clock = clockText(when, hour12);
  if (days <= 0) return `today ${clock}`;
  if (days === 1) return `yesterday ${clock}`;
  if (days < 7) return `${days} days ago`;
  return `${when.getFullYear()}-${pad(when.getMonth() + 1)}-${pad(when.getDate())}`;
}

/**
 * The future counterpart of `relativeTime`: "in 12 minutes", "in 2 hours",
 * then the date. A time that is missing, unreadable, already past or less
 * than a minute away reads "in a minute".
 */
export function timeUntil(iso: string | null | undefined, now: Date = new Date()): string {
  const when = iso ? new Date(iso) : null;
  const ms = when && !Number.isNaN(when.getTime()) ? when.getTime() - now.getTime() : 0;
  const minutes = Math.ceil(ms / 60_000);
  if (minutes <= 1) return "in a minute";
  if (minutes < 60) return `in ${minutes} minutes`;
  // The date only from a full day away, so it is never today's.
  if (minutes >= 24 * 60) return `on ${dateText(iso!)}`;
  const hours = Math.round(minutes / 60);
  return hours === 1 ? "in an hour" : `in ${hours} hours`;
}

/** A timestamp's local date, `2026-09-27`; the text itself when it does not parse. */
export function dateText(iso: string): string {
  const when = new Date(iso);
  if (!iso || Number.isNaN(when.getTime())) return iso;
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

/** The panel's *Last sync* row: "Today 2:02 PM · 2 added, 1 removed" (mockup screen 1). */
export function lastSyncLine(pending: Pending | null, now: Date = new Date()): string {
  if (!pending?.last_summary) return "Never";
  return `${capitalize(relativeTime(pending.since, now))} · ${summaryLine(pending.last_summary)}`;
}
