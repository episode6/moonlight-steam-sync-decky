import { describe, expect, it } from "vitest";

import { loadFixture } from "../test/fixtures";
import type { CliEvent, PlanEvent, SummaryEvent } from "./cli";
import { lastOf } from "./events";
import { countdownLine, finishTitle, restartDecision, runKindOf, unwrittenMessage } from "./restart";

/** The fixture's exit, as the fake CLI computes it. */
function exitOf(events: CliEvent[]): number {
  const error = lastOf(events, "error");
  if (error) return error.exit;
  return lastOf(events, "summary")?.exit ?? 0;
}

describe("restartDecision over the shared fixtures (spec 3.9)", () => {
  it.each([
    ["full-sync/sync.ndjson", "write"],
    ["art-only/sync.ndjson", "art"],
    ["nothing-to-do/sync.ndjson", "none"],
    ["stopped/sync.ndjson", "art"],
    ["unreachable/sync.ndjson", "none"],
    ["refused/sync.ndjson", "write"],
    ["common/remove.ndjson", "write"],
    ["common/art.ndjson", "art"],
  ])("%s -> %s", (name, kind) => {
    const events = loadFixture(name);
    expect(restartDecision(events, exitOf(events)).kind).toBe(kind);
  });

  it("titles the write prompt from the plan", () => {
    const events = loadFixture("full-sync/sync.ndjson");
    // at the moment awaiting-steam-exit arrives: no commit, no summary yet
    const upToWait = events.slice(0, events.findIndex((e) => e.event === "awaiting-steam-exit") + 1);
    expect(restartDecision(upToWait, null)).toEqual({
      kind: "write",
      title: "Sync finished: 2 added, 1 replaced, 1 parked",
      description: "",
    });
  });

  it("titles the art-only prompt", () => {
    expect(restartDecision(loadFixture("art-only/sync.ndjson"), 0)).toEqual({
      kind: "art",
      title: "New artwork needs a Steam restart to show",
      description: "2 images saved",
    });
  });

  it("titles the stopped prompt", () => {
    expect(restartDecision(loadFixture("stopped/sync.ndjson"), 130)).toEqual({
      kind: "art",
      title: "Stopped; 1 image was saved",
      description: "Restart Steam to show them, or sync again to resume.",
    });
  });

  it("a stopped run with nothing saved just says so", () => {
    const events = loadFixture("stopped/sync.ndjson").map((e) =>
      e.event === "summary" ? { ...e, filled: 0 } : e,
    );
    expect(restartDecision(events, 130)).toEqual({
      kind: "none",
      title: "Stopped; sync again to resume",
      description: "",
    });
  });

  it("an unreachable host is reported, not prompted", () => {
    expect(restartDecision(loadFixture("unreachable/sync.ndjson"), 3).title).toBe(
      "Host unreachable: sync: moonlight: host MY-GAMING-PC unreachable",
    );
  });

  it("nothing to do has no title", () => {
    expect(restartDecision(loadFixture("nothing-to-do/sync.ndjson"), 0).title).toBe("");
  });

  it("remove and art runs get their own titles", () => {
    const remove = loadFixture("common/remove.ndjson");
    expect(runKindOf(remove)).toBe("remove");
    expect(restartDecision(remove.slice(0, 2), null).title).toBe("Removed everything");
    expect(restartDecision(remove, 0).title).toBe("Removed everything: 6 entries");
    const art = loadFixture("common/art.ndjson");
    expect(runKindOf(art)).toBe("art");
    expect(finishTitle("art", null, null)).toBe("Artwork re-fetched");
  });
});

describe("finishTitle", () => {
  const plan = lastOf(loadFixture("full-sync/sync.ndjson"), "plan") as PlanEvent;
  const summary = lastOf(loadFixture("full-sync/sync.ndjson"), "summary") as SummaryEvent;

  it("omits zero park counts and adds unparked", () => {
    expect(finishTitle("sync", { ...plan, to_park: 0 }, null)).toBe("Sync finished: 2 added, 1 replaced");
    expect(finishTitle("sync", { ...plan, to_park: 0, to_unpark: 3 }, null)).toBe(
      "Sync finished: 2 added, 1 replaced, 3 unparked",
    );
  });

  it("uses the per-kind split only when the summary carries it (spec 3.13 Q3)", () => {
    expect(
      finishTitle("sync", plan, { ...summary, added_by_kind: { shortcut: 12, stream: 9 } }),
    ).toBe("Sync finished: 12 shortcuts, 9 Stream buttons");
    expect(finishTitle("sync", null, null)).toBe("Sync finished");
  });
});

describe("countdownLine", () => {
  it("ticks, stops for a game, and has a buttons-only form", () => {
    expect(countdownLine(5, true, false)).toBe("Restarting Steam in 5 s to show them.");
    expect(countdownLine(5, true, true)).toBe("A game is running. Restart Steam when you're done.");
    expect(countdownLine(0, false, false)).toBe("Restart Steam to show them.");
  });

  it("explains the CLI's wait timing out", () => {
    expect(unwrittenMessage(2)).toBe("Steam did not restart; sync again to apply");
    expect(unwrittenMessage(130)).toBe("");
  });
});
