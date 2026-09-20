/**
 * NDJSON parsing for the CLI's `--json` stream (spec 3.4.6).
 *
 * The backend relays already-parsed objects; this module is what the
 * frontend uses to accept them (an unknown `event` name is dropped, never
 * guessed at) and what the tests use to read `tests/fixtures/**` into the
 * same typed events the backend relays.
 */

import { EVENT_NAMES, type CliEvent, type EventName } from "./cli";

const KNOWN = new Set<string>(EVENT_NAMES);

export function isCliEvent(value: unknown): value is CliEvent {
  return (
    typeof value === "object" &&
    value !== null &&
    typeof (value as { event?: unknown }).event === "string" &&
    KNOWN.has((value as { event: string }).event)
  );
}

/** One line -> an event, or `null` for a blank, comment, non-JSON or unknown line. */
export function parseLine(line: string): CliEvent | null {
  const text = line.trim();
  if (!text || text.startsWith("#")) return null;
  let value: unknown;
  try {
    value = JSON.parse(text);
  } catch {
    return null;
  }
  return isCliEvent(value) ? value : null;
}

export function parseNdjson(text: string): CliEvent[] {
  const events: CliEvent[] = [];
  for (const line of text.split("\n")) {
    const event = parseLine(line);
    if (event) events.push(event);
  }
  return events;
}

export function eventsOf<N extends EventName>(
  events: readonly CliEvent[],
  name: N,
): Extract<CliEvent, { event: N }>[] {
  return events.filter((e): e is Extract<CliEvent, { event: N }> => e.event === name);
}

export function lastOf<N extends EventName>(
  events: readonly CliEvent[],
  name: N,
): Extract<CliEvent, { event: N }> | null {
  for (let i = events.length - 1; i >= 0; i--) {
    const event = events[i];
    if (event.event === name) return event as Extract<CliEvent, { event: N }>;
  }
  return null;
}
