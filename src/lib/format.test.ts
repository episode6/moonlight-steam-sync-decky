import { describe, expect, it } from "vitest";

import type { Pending, SummaryEvent } from "./cli";
import { dateText, lastSyncLine, relativeTime, summaryLine, timeUntil } from "./format";

const now = new Date(2026, 8, 18, 15, 30);
const local = (d: number, h: number, m: number) => new Date(2026, 8, d, h, m).toISOString();

const summary: SummaryEvent = {
  event: "summary",
  added: 2,
  replaced: 0,
  removed: 1,
  filled: 9,
  missing: 0,
  unmatched: [],
  duplicates: {},
  pending: 0,
  stopped_early: false,
  stop_reason: null,
  exit: 0,
};

describe("relativeTime", () => {
  it("today, yesterday, days, dates", () => {
    expect(relativeTime(local(18, 14, 2), now)).toBe("today 14:02");
    expect(relativeTime(local(17, 9, 5), now)).toBe("yesterday 09:05");
    expect(relativeTime(local(15, 9, 5), now)).toBe("3 days ago");
    expect(relativeTime(local(1, 9, 5), now)).toBe("2026-09-01");
    expect(relativeTime(null, now)).toBe("never");
  });
});

describe("timeUntil and dateText", () => {
  const at = (h: number, m: number, s = 0) => new Date(2026, 8, 18, h, m, s).toISOString();

  it("minutes, hours, then the date", () => {
    expect(timeUntil(at(15, 42), now)).toBe("in 12 minutes");
    expect(timeUntil(at(15, 31, 30), now)).toBe("in 2 minutes");
    expect(timeUntil(at(16, 30), now)).toBe("in an hour");
    expect(timeUntil(at(18, 10), now)).toBe("in 3 hours");
    expect(timeUntil(new Date(2026, 8, 21, 9, 0).toISOString(), now)).toBe("on 2026-09-21");
  });

  it("a minute when unknown, past, unreadable or under a minute away", () => {
    expect(timeUntil(null, now)).toBe("in a minute");
    expect(timeUntil(undefined, now)).toBe("in a minute");
    expect(timeUntil("soon", now)).toBe("in a minute");
    expect(timeUntil(at(15, 0), now)).toBe("in a minute");
    expect(timeUntil(at(15, 30, 40), now)).toBe("in a minute");
  });

  it("dateText is the local date", () => {
    expect(dateText(local(1, 9, 5))).toBe("2026-09-01");
    expect(dateText("")).toBe("");
    expect(dateText("later")).toBe("later");
  });
});

describe("the Last sync row", () => {
  it("matches the mockup", () => {
    const pending: Pending = {
      restart_needed: "none",
      layout_walk: false,
      since: local(18, 14, 2),
      last_summary: summary,
      last_plan: null,
      last_kind: "sync",
      synced_hosts: {},
    };
    expect(lastSyncLine(pending, now)).toBe("Today 14:02 · 2 added, 1 removed");
    expect(lastSyncLine(null, now)).toBe("Never");
  });

  it("summarises art-only and empty runs", () => {
    expect(summaryLine({ ...summary, added: 0, removed: 0, filled: 1 })).toBe("1 image");
    expect(summaryLine({ ...summary, added: 0, removed: 0, filled: 0 })).toBe("nothing to do");
    expect(summaryLine({ ...summary, stop_reason: "interrupted" })).toBe("2 added, 1 removed, stopped");
  });
});
