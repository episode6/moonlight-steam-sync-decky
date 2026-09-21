import { describe, expect, it } from "vitest";

import { allFixtures, fixtureText, loadFixture } from "../test/fixtures";
import { EVENT_NAMES } from "./cli";
import { eventsOf, isCliEvent, lastOf, parseLine, parseNdjson } from "./events";

describe("parsing the backend's fixtures", () => {
  it("finds every scenario the spec names", () => {
    expect(allFixtures()).toEqual(
      expect.arrayContaining([
        "full-sync/sync.ndjson",
        "art-only/sync.ndjson",
        "nothing-to-do/sync.ndjson",
        "unreachable/sync.ndjson",
        "unreachable/list.ndjson",
        "stopped/sync.ndjson",
        "refused/sync.ndjson",
        "common/list.ndjson",
        "common/list-cached.ndjson",
        "common/status.ndjson",
        "common/host.ndjson",
        "common/host-none.ndjson",
        "common/search.ndjson",
        "common/match.ndjson",
        "common/match-unpin.ndjson",
        "common/remove.ndjson",
        "common/art.ndjson",
      ]),
    );
  });

  it.each(allFixtures())("%s parses every data line into a known event", (name) => {
    const dataLines = fixtureText(name)
      .split("\n")
      .filter((line) => line.trim() && !line.startsWith("#"));
    const events = loadFixture(name);
    expect(events).toHaveLength(dataLines.length);
    expect(events[0]).toMatchObject({ event: "start", schema: 1, version: "0.4.0" });
    for (const event of events) expect(EVENT_NAMES).toContain(event.event);
  });

  it("types the full-sync run", () => {
    const events = loadFixture("full-sync/sync.ndjson");
    const plan = lastOf(events, "plan");
    expect(plan?.to_add).toBe(2);
    expect(plan?.to_replace).toBe(1);
    expect(plan?.to_park).toBe(1);
    expect(eventsOf(events, "title").map((t) => t.name)).toEqual(["Balatro", "Cocoon", "Tunic"]);
    expect(lastOf(events, "commit")?.written).toBe(true);
    expect(lastOf(events, "summary")?.filled).toBe(9);
  });

  it("types list, status, host and search events", () => {
    const apps = eventsOf(loadFixture("common/list.ndjson"), "app");
    expect(apps).toHaveLength(9);
    expect(apps.find((a) => a.kind === "duplicate")?.duplicate_of).toBe("Sea of Stars");
    expect(apps.find((a) => a.fuzzy)?.name).toBe("Hades II");
    const entries = eventsOf(loadFixture("common/status.ndjson"), "entry");
    expect(entries.filter((e) => e.client)).toHaveLength(1);
    expect(entries.find((e) => e.stale_art)?.name).toBe("Sea of Stars");
    const host = lastOf(loadFixture("common/host.ndjson"), "host");
    expect(host?.cached_hosts.map((c) => c.name)).toEqual(["MY-GAMING-PC", "OFFICE-PC"]);
    const candidates = eventsOf(loadFixture("common/search.ndjson"), "candidate");
    expect(candidates.map((c) => c.source)).toEqual(["sgdb", "sgdb", "steam", "steam"]);
    expect(candidates.filter((c) => c.owned)).toHaveLength(1);
  });
});

describe("parseLine", () => {
  it("drops blanks, comments, non-JSON and unknown events", () => {
    expect(parseLine("")).toBeNull();
    expect(parseLine("# a comment")).toBeNull();
    expect(parseLine("Traceback (most recent call last):")).toBeNull();
    expect(parseLine('{"event":"mystery"}')).toBeNull();
    expect(parseLine('{"no":"event"}')).toBeNull();
    expect(parseLine("[1,2]")).toBeNull();
    expect(parseLine('{"event":"note","message":"hi"}')).toEqual({ event: "note", message: "hi" });
  });

  it("parseNdjson keeps order", () => {
    const events = parseNdjson('{"event":"note","message":"a"}\nnoise\n{"event":"end"}\n');
    expect(events.map((e) => e.event)).toEqual(["note", "end"]);
    expect(isCliEvent(events[0])).toBe(true);
  });
});
