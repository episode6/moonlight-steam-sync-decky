import { describe, expect, it } from "vitest";

import type { Pending, SummaryEvent } from "./cli";
import { lastSyncLine, relativeTime, summaryLine } from "./format";

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

describe("the Last sync row", () => {
  it("matches the mockup", () => {
    const pending: Pending = {
      restart_needed: "none",
      layout_walk: false,
      since: local(18, 14, 2),
      last_summary: summary,
      last_plan: null,
      last_kind: "sync",
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
