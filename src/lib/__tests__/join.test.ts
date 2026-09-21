import { describe, expect, it } from "vitest";

import { loadFixture } from "../../test/fixtures";
import type { AppEvent, CandidateEvent, EntryEvent, Match } from "../cli";
import { eventsOf, lastOf } from "../events";
import {
  applyPin,
  candidateRows,
  capsuleUrl,
  compareNames,
  currentCandidateKey,
  filterCounts,
  filterRows,
  joinTitles,
  layoutTargetOf,
  loadMoreLabel,
  matchSummary,
  noMatchRow,
  PAGE_SIZE,
  pageOf,
  parkedCount,
  publishedCount,
  STALE_ART_TEXT,
  type TitleRow,
} from "../join";

// The documented shapes (spec 3.4.6), from the same NDJSON the backend tests replay.
const apps = eventsOf(loadFixture("common/list.ndjson"), "app");
const entries = eventsOf(loadFixture("common/status.ndjson"), "entry");
const candidates = eventsOf(loadFixture("common/search.ndjson"), "candidate");

const rowsOf = (ignoreFile: string[] = []) => joinTitles(apps, entries, ignoreFile);
const byName = (rows: TitleRow[], name: string) => {
  const row = rows.find((r) => r.name === name);
  if (!row) throw new Error(`no row ${name}`);
  return row;
};
const chipTexts = (row: TitleRow) => row.chips.map((c) => c.text);
const names = (rows: TitleRow[]) => rows.map((r) => r.name);

function app(name: string, overrides: Partial<AppEvent> = {}): AppEvent {
  return {
    event: "app",
    name,
    label: "added",
    kind: "shortcut",
    match: { steam_appid: null, sgdb_id: 1, matched_name: name, how: "sgdb:exact" },
    fuzzy: false,
    duplicate_of: null,
    same_game_as: [],
    cached: false,
    cached_when: null,
    ...overrides,
  };
}

describe("joinTitles: list joined with status by name", () => {
  const rows = rowsOf();

  it("has one row per app, sorted by name, and never the client entry", () => {
    expect(names(rows)).toEqual([
      "Balatro",
      "Demo Launcher",
      "Desktop",
      "Hades II",
      "Sea of Stars",
      "Sea of Stars (GOG)",
      "Spiritfarer",
      "Steam Big Picture",
      "Tunic",
    ]);
    expect(rows.some((r) => r.name === "Moonlight")).toBe(false);
  });

  it("attaches the owned entry by name (none for ignored and duplicate titles)", () => {
    expect(byName(rows, "Balatro").entry?.appid).toBe(2718281828);
    expect(byName(rows, "Hades II").entry?.appid).toBe(3000000011);
    expect(byName(rows, "Demo Launcher").entry).toBeNull();
    expect(byName(rows, "Sea of Stars (GOG)").entry).toBeNull();
    expect(byName(rows, "Desktop").entry?.appid).toBe(3000000101);
  });

  it("stream button: matched to an owned game, with the Steam capsule", () => {
    const row = byName(rows, "Balatro");
    expect(row.kind).toBe("stream");
    expect(row.badge).toEqual({ id: "stream", text: "stream button", tone: "stream" });
    expect(row.matchLine).toBe("Balatro · Steam 2379780");
    expect(row.thumbnail).toBe(
      "https://cdn.cloudflare.steamstatic.com/steam/apps/2379780/library_600x900.jpg",
    );
  });

  it("same game as: the same_game_as chip names the other host and title", () => {
    const row = byName(rows, "Balatro");
    expect(row.chips).toEqual([
      { id: "same-game", text: 'same game on OFFICE-PC as "Balatro (Epic)"', tone: "warn" },
    ]);
  });

  it("shortcut + fuzzy: a fuzzy match stays a shortcut and says so", () => {
    const row = byName(rows, "Hades II");
    expect(row.kind).toBe("shortcut");
    expect(row.badge.text).toBe("shortcut");
    expect(row.unmatched).toBe(false);
    expect(row.matchLine).toBe("Hades · Steam 1145360");
    expect(row.chips).toEqual([{ id: "fuzzy", text: "fuzzy", tone: "warn" }]);
  });

  it("pinned + stale_art: a pin shows pinned (not fuzzy) and the art refresh", () => {
    const row = byName(rows, "Sea of Stars");
    expect(row.kind).toBe("stream");
    expect(chipTexts(row)).toEqual(["pinned", STALE_ART_TEXT]);
    expect(STALE_ART_TEXT).toBe("art refreshes on next sync");
  });

  it("duplicate: a warning badge and 'same game as <winner>' in the match line", () => {
    const row = byName(rows, "Sea of Stars (GOG)");
    expect(row.kind).toBe("duplicate");
    expect(row.badge).toEqual({ id: "duplicate", text: "duplicate", tone: "warn" });
    expect(row.matchLine).toBe("same game as Sea of Stars");
    expect(row.duplicateOf).toBe("Sea of Stars");
  });

  it("parked: another host's title, hidden in place", () => {
    const row = byName(rows, "Spiritfarer");
    expect(row.kind).toBe("parked");
    expect(row.badge).toEqual({ id: "parked", text: "parked", tone: "neutral" });
    expect(row.entry?.parked).toBe(true);
    expect(row.matchLine).toBe("Spiritfarer: Farewell Edition · Steam 972660");
  });

  it("unmatched: a shortcut with no Steam or SteamGridDB id, and the placeholder", () => {
    const row = byName(rows, "Tunic");
    expect(row.kind).toBe("shortcut");
    expect(row.unmatched).toBe(true);
    expect(row.badge).toEqual({ id: "unmatched", text: "unmatched", tone: "bad" });
    expect(row.matchLine).toBe("no match");
    expect(row.thumbnail).toBeNull();
    expect(row.chips).toEqual([]);
  });

  it("ignored: from config.toml unless it is in ignore.json", () => {
    const fromConfig = byName(rows, "Demo Launcher");
    expect(fromConfig.kind).toBe("ignored");
    expect(fromConfig.badge).toEqual({ id: "ignored", text: "ignored", tone: "neutral" });
    expect(fromConfig.ignoredBy).toBe("config");
    expect(fromConfig.matchLine).toBe("—");
    expect(fromConfig.thumbnail).toBeNull();
    expect(byName(rowsOf(["Demo Launcher"]), "Demo Launcher").ignoredBy).toBe("plugin");
  });

  it("host app: a neutral badge, never a stream button or unmatched, whatever its match", () => {
    const desktop = byName(rows, "Desktop");
    expect(desktop.kind).toBe("host-app");
    expect(desktop.badge).toEqual({ id: "host-app", text: "host app", tone: "neutral" });
    // Its match is a Steam game, which only feeds the art (spec 3.14).
    expect(desktop.matchLine).toBe("Desktop Dungeons · Steam 226620");
    expect(desktop.thumbnail).toBe(capsuleUrl(226620));
    expect(desktop.chips).toEqual([]);
    expect(desktop.entry?.hidden).toBe(true);

    const bigPicture = byName(rows, "Steam Big Picture");
    expect(bigPicture.kind).toBe("host-app");
    expect(bigPicture.badge.text).toBe("host app");
    expect(bigPicture.matchLine).toBe("no match");
    expect(bigPicture.unmatched).toBe(false);
  });

  it("host app: Ignore stays, and wins over the kind", () => {
    const row = byName(rowsOf(["Desktop"]), "Desktop");
    expect(row.kind).toBe("ignored");
    expect(row.badge.id).toBe("ignored");
    expect(row.ignoredBy).toBe("plugin");
    expect(row.layoutTarget).toBeNull();
  });

  it("a name in ignore.json is ignored before the next list says so", () => {
    const row = byName(rowsOf(["Tunic"]), "Tunic");
    expect(row.kind).toBe("ignored");
    expect(row.badge.id).toBe("ignored");
    expect(row.ignoredBy).toBe("plugin");
    expect(row.unmatched).toBe(false);
    expect(byName(rowsOf(["Tunic"]), "Hades II").ignored).toBe(false);
  });

  it("every badge of spec 3.8 is derived from the fixtures", () => {
    const all = rowsOf();
    const badges = new Set(all.map((r) => r.badge.text));
    expect([...badges].sort()).toEqual(
      ["duplicate", "host app", "ignored", "parked", "shortcut", "stream button", "unmatched"].sort(),
    );
    const chips = new Set(all.flatMap((r) => r.chips.map((c) => c.id)));
    expect([...chips].sort()).toEqual(["fuzzy", "pinned", "same-game", "stale-art"]);
    expect(all.some((r) => r.matchLine.startsWith("same game as "))).toBe(true);
  });

  it("a parked entry list does not mention still gets a parked row", () => {
    const withoutSpiritfarer = apps.filter((a) => a.name !== "Spiritfarer");
    const rows2 = joinTitles(withoutSpiritfarer, entries);
    const row = byName(rows2, "Spiritfarer");
    expect(row.kind).toBe("parked");
    expect(row.match?.steam_appid).toBe(972660);
  });

  it("an entry list does not mention that is not parked gets no row", () => {
    const rows2 = joinTitles(
      apps.filter((a) => a.name !== "Tunic"),
      entries,
    );
    expect(names(rows2)).not.toContain("Tunic");
  });

  it("the first app of a repeated name wins", () => {
    const rows2 = joinTitles([app("Tunic"), app("Tunic", { kind: "stream" })], []);
    expect(rows2).toHaveLength(1);
    expect(rows2[0].kind).toBe("shortcut");
  });

  it("with no status (it failed) rows still come from list", () => {
    const rows2 = joinTitles(apps, []);
    expect(rows2).toHaveLength(9);
    expect(byName(rows2, "Sea of Stars").chips.map((c) => c.id)).toEqual(["pinned"]);
  });

  it("the cached listing joins the same way", () => {
    const cached = eventsOf(loadFixture("common/list-cached.ndjson"), "app");
    const rows2 = joinTitles(cached, entries);
    expect(rows2.map((r) => r.badge.text)).toEqual(rowsOf().map((r) => r.badge.text));
  });

  it("a match known only by its SteamGridDB id reads SGDB <id> and has no capsule", () => {
    const [row] = joinTitles(
      [app("Sea of Stars (GOG)", { match: { steam_appid: null, sgdb_id: 5322710, matched_name: "Sea of Stars", how: "sgdb:exact" } })],
      [],
    );
    expect(row.matchLine).toBe("Sea of Stars · SGDB 5322710");
    expect(row.thumbnail).toBeNull();
    expect(row.badge.text).toBe("shortcut");
  });

  it("an app not in matches.json yet (match null) reads no match", () => {
    const [row] = joinTitles([app("New Game", { match: null, label: "new" })], []);
    expect(row.matchLine).toBe("no match");
    expect(row.unmatched).toBe(true);
  });
});

describe("filters and the Show parked chip", () => {
  const rows = rowsOf();

  it("All leaves the parked rows out until Show parked is on", () => {
    expect(names(filterRows(rows, "all"))).toEqual([
      "Balatro",
      "Demo Launcher",
      "Desktop",
      "Hades II",
      "Sea of Stars",
      "Sea of Stars (GOG)",
      "Steam Big Picture",
      "Tunic",
    ]);
    expect(names(filterRows(rows, "all", true))).toContain("Spiritfarer");
    expect(filterRows(rows, "all", true)).toHaveLength(9);
  });

  it("Stream buttons, Shortcuts, Unmatched, Ignored", () => {
    expect(names(filterRows(rows, "stream"))).toEqual(["Balatro", "Sea of Stars"]);
    expect(names(filterRows(rows, "shortcut"))).toEqual(["Hades II", "Tunic"]);
    expect(names(filterRows(rows, "unmatched"))).toEqual(["Tunic"]);
    expect(names(filterRows(rows, "ignored"))).toEqual(["Demo Launcher"]);
  });

  it("a host-app row shows under All only (spec 3.14.1)", () => {
    for (const filter of ["stream", "shortcut", "unmatched", "ignored"] as const) {
      expect(names(filterRows(rows, filter, true))).not.toContain("Desktop");
      // unmatched as it is, Steam Big Picture is no Unmatched row either
      expect(names(filterRows(rows, filter, true))).not.toContain("Steam Big Picture");
    }
  });

  it("parked rows only ever show under All", () => {
    for (const filter of ["stream", "shortcut", "unmatched", "ignored"] as const) {
      expect(names(filterRows(rows, filter, true))).not.toContain("Spiritfarer");
    }
  });

  it("counts per filter, published and parked", () => {
    expect(filterCounts(rows)).toEqual({ all: 8, stream: 2, shortcut: 2, unmatched: 1, ignored: 1 });
    expect(filterCounts(rows, true).all).toBe(9);
    expect(publishedCount(rows)).toBe(8);
    expect(parkedCount(rows)).toBe(1);
  });

  it("filtering keeps the name order", () => {
    const shuffled = [...rows].reverse();
    expect(names(filterRows(shuffled, "all"))).toEqual(names(filterRows(rows, "all")).reverse());
  });
});

describe("sorting and pages of 50", () => {
  it("sorts by name case-insensitively, numbers numerically", () => {
    const sorted = joinTitles([app("banana"), app("Game 10"), app("Apple"), app("Game 2"), app("cherry")], []);
    expect(names(sorted)).toEqual(["Apple", "banana", "cherry", "Game 2", "Game 10"]);
    expect(compareNames("a", "A")).not.toBe(0); // ties are broken, so the order is total
  });

  it("renders 50 at a time with a load-more row", () => {
    const many = joinTitles(
      Array.from({ length: 123 }, (_, i) => app(`Title ${String(i).padStart(3, "0")}`)),
      [],
    );
    expect(PAGE_SIZE).toBe(50);
    const first = pageOf(many, 1);
    expect(first.rows).toHaveLength(50);
    expect(first.rows[0].name).toBe("Title 000");
    expect(first.remaining).toBe(73);
    expect(first.hasMore).toBe(true);
    expect(loadMoreLabel(first)).toBe("Show 50 more (73 left)");
    const second = pageOf(many, 2);
    expect(second.rows).toHaveLength(100);
    expect(loadMoreLabel(second)).toBe("Show 23 more (23 left)");
    const all = pageOf(many, 3);
    expect(all.rows).toHaveLength(123);
    expect(all.hasMore).toBe(false);
    expect(pageOf(many, 0).rows).toHaveLength(50); // at least one page
  });

  it("a short list is one page with no load-more row", () => {
    const page = pageOf(rowsOf(), 1);
    expect(page.rows).toHaveLength(9);
    expect(page.hasMore).toBe(false);
    expect(page.remaining).toBe(0);
  });
});

describe("applyPin: the row after Use this, before the next list", () => {
  it("re-points the title, drops fuzzy and shows pinned", () => {
    const pinned = lastOf(loadFixture("common/match.ndjson"), "pinned")!;
    const row = byName(joinTitles(applyPin(apps, pinned, "Hades II"), entries), "Hades II");
    expect(row.match).toEqual({ steam_appid: 1145350, sgdb_id: 5406129, matched_name: "Hades II", how: "pinned" });
    expect(row.matchLine).toBe("Hades II · Steam 1145350");
    expect(chipTexts(row)).toEqual(["pinned"]);
    expect(row.thumbnail).toBe(capsuleUrl(1145350));
  });

  it("No match pins a shortcut with no ids", () => {
    const pinned = lastOf(loadFixture("common/match-none.ndjson"), "pinned")!;
    const row = byName(joinTitles(applyPin(apps, pinned, "ignored name"), entries), "Tunic");
    expect(row.match).toEqual({ steam_appid: null, sgdb_id: null, matched_name: null, how: "pinned" });
    expect(row.badge.text).toBe("unmatched");
    expect(chipTexts(row)).toEqual(["pinned"]);
  });

  it("leaves every other title alone", () => {
    const pinned = lastOf(loadFixture("common/match.ndjson"), "pinned")!;
    const after = applyPin(apps, pinned, "Hades II");
    expect(after.filter((a) => a.name !== "Hades II")).toEqual(apps.filter((a) => a.name !== "Hades II"));
  });
});

describe("the Change match modal's rows", () => {
  const hades: Match = byName(rowsOf(), "Hades II").match!;

  it("one list, owned first, then Steam before SteamGridDB, each in the CLI's order", () => {
    const rows = candidateRows(candidates, hades);
    expect(rows.map((r) => r.key)).toEqual(["sgdb:5406129", "steam:2300320", "steam:1172470", "sgdb:36072"]);
  });

  it("owned candidates keep Steam before SteamGridDB among themselves", () => {
    const candidate = (source: "steam" | "sgdb", id: number, owned: boolean): CandidateEvent => ({
      event: "candidate", source, id, name: `Game ${id}`, verified: true, owned, steam_appid: null,
    });
    const rows = candidateRows(
      [candidate("sgdb", 1, false), candidate("sgdb", 2, true), candidate("steam", 3, false), candidate("steam", 4, true)],
      null,
    );
    expect(rows.map((r) => r.key)).toEqual(["steam:4", "sgdb:2", "steam:3", "sgdb:1"]);
  });

  it("the outcome comes from candidate.owned", () => {
    const rows = candidateRows(candidates, hades);
    const owned = rows.find((r) => r.key === "sgdb:5406129")!;
    expect(owned.outcome).toBe("becomes stream button");
    expect(owned.tone).toBe("stream");
    expect(owned.detail).toBe("SteamGridDB 5406129 · Steam 1145350 · owned on this account");
    for (const row of rows.filter((r) => r.key !== "sgdb:5406129")) {
      expect(row.outcome).toBe("shortcut");
      expect(row.tone).toBe("ok");
    }
  });

  it("on a host-app row every candidate is art only: no pin changes its kind", () => {
    const rows = candidateRows(candidates, hades, true);
    expect(rows.map((r) => r.key)).toEqual(candidateRows(candidates, hades).map((r) => r.key));
    expect(rows.some((r) => r.detail.includes("owned on this account"))).toBe(true);
    for (const row of rows) {
      expect(row.outcome).toBe("art only");
      expect(row.tone).toBe("neutral");
    }
    expect(noMatchRow(hades, true).detail).toBe("Search SteamGridDB by name for art");
    expect(noMatchRow(hades).detail).toBe("Keep as a shortcut, search SteamGridDB by name for art");
  });

  it("marks the current match", () => {
    const rows = candidateRows(candidates, hades);
    expect(rows.filter((r) => r.current).map((r) => r.key)).toEqual(["sgdb:36072"]);
    expect(rows.find((r) => r.current)?.detail).toBe("SteamGridDB 36072 · Steam 1145360 · current match");
    const steamOnly = eventsOf(loadFixture("common/search-no-key.ndjson"), "candidate");
    const rows2 = candidateRows(steamOnly, { ...hades, sgdb_id: null });
    expect(rows2.filter((r) => r.current).map((r) => r.key)).toEqual(["steam:1145360"]);
    expect(rows2[0].detail).toBe("Steam 1145350 · owned on this account");
    expect(candidateRows(candidates, null).some((r) => r.current)).toBe(false);
  });

  it("at most one row is the current match, and the SGDB one wins", () => {
    // A match can carry both ids. The real CLI drops a Steam-store candidate
    // whose appid equals an SGDB candidate's steam_appid (spec 3.4.6,
    // "SGDB wins"), so both only reach the modal when that lookup failed --
    // and then the SGDB row is still the current one.
    const both: Match = { steam_appid: 1145360, sgdb_id: 36072, matched_name: "Hades", how: "pinned" };
    const clash: CandidateEvent[] = [
      { event: "candidate", source: "steam", id: 1145360, name: "Hades", verified: true, owned: false, steam_appid: 1145360 },
      { event: "candidate", source: "sgdb", id: 36072, name: "Hades", verified: true, owned: false, steam_appid: 1145360 },
    ];
    expect(candidateRows(clash, both).filter((r) => r.current).map((r) => r.key)).toEqual(["sgdb:36072"]);
    expect(currentCandidateKey(clash, both)).toBe("sgdb:36072");

    // No SGDB candidate answers: the Steam one is the current match.
    const steamOnlyList = clash.filter((c) => c.source === "steam");
    expect(candidateRows(steamOnlyList, both).filter((r) => r.current).map((r) => r.key)).toEqual([
      "steam:1145360",
    ]);
    expect(currentCandidateKey(steamOnlyList, both)).toBe("steam:1145360");

    // Neither answers: nothing is marked.
    expect(currentCandidateKey([], both)).toBeNull();
  });

  it("never marks more than one row over any of the search fixtures", () => {
    for (const fixture of ["common/search.ndjson", "common/search-no-key.ndjson", "common/search-empty.ndjson"]) {
      const list = eventsOf(loadFixture(fixture), "candidate");
      for (const match of [hades, null, { ...hades, sgdb_id: null }, { ...hades, steam_appid: null }]) {
        expect(candidateRows(list, match).filter((r) => r.current).length).toBeLessThanOrEqual(1);
      }
    }
  });

  it("no search fixture breaks the CLI's de-dup rule", () => {
    // A fixture must be producible by the real CLI: it drops a Steam-store
    // candidate whose appid equals an SGDB candidate's steam_appid.
    for (const fixture of ["common/search.ndjson", "common/search-no-key.ndjson", "common/search-empty.ndjson"]) {
      const list = eventsOf(loadFixture(fixture), "candidate");
      const sgdbAppids = new Set(
        list.filter((c) => c.source === "sgdb" && c.steam_appid !== null).map((c) => c.steam_appid),
      );
      for (const steam of list.filter((c) => c.source === "steam")) {
        expect(sgdbAppids.has(steam.id)).toBe(false);
      }
    }
  });

  it("an SGDB title without a Steam release is community art only", () => {
    const [row] = candidateRows(
      [{ event: "candidate", source: "sgdb", id: 77, name: "Indie", verified: false, owned: false, steam_appid: null }],
      null,
    );
    expect(row.detail).toBe("SteamGridDB 77 · community art only");
  });

  it("each row pins exactly one selector", () => {
    const rows = candidateRows(candidates, hades);
    expect(rows[1].choice).toEqual({ steam: 2300320, sgdb: null, none: false });
    expect(rows[0].choice).toEqual({ steam: null, sgdb: 5406129, none: false });
    expect(noMatchRow(hades).choice).toEqual({ steam: null, sgdb: null, none: true });
  });

  it("the final No match row, current when pinned to no match", () => {
    const row = noMatchRow(hades);
    expect(row.name).toBe("No match");
    expect(row.outcome).toBe("pinned");
    expect(row.current).toBe(false);
    const none: Match = { steam_appid: null, sgdb_id: null, matched_name: null, how: "pinned" };
    expect(noMatchRow(none).current).toBe(true);
    expect(noMatchRow({ ...none, how: "none" }).current).toBe(false);
  });

  it("the subtitle says what the title is matched to and how", () => {
    expect(matchSummary(hades)).toEqual({
      lead: "Currently matched to ",
      name: "Hades",
      tail: " (Steam 1145360) by a fuzzy title search.",
      overrideWins: false,
    });
    expect(matchSummary(null).lead).toBe("Not matched yet.");
    const tunic = byName(rowsOf(), "Tunic").match;
    expect(matchSummary(tunic).lead).toBe("Currently no match.");
    expect(matchSummary({ steam_appid: null, sgdb_id: null, matched_name: null, how: "pinned" }).lead).toBe(
      "Pinned to no match.",
    );
    const pinned = byName(rowsOf(), "Sea of Stars").match;
    expect(matchSummary(pinned).tail).toBe(" (Steam 1244090) by a pin.");
    const exact = byName(rowsOf(), "Balatro").match;
    expect(matchSummary(exact).tail).toBe(" (Steam 2379780) by an exact title search.");
    expect(matchSummary({ ...exact!, how: "override" }).overrideWins).toBe(true);
  });
});

describe("EntryEvent typing sanity", () => {
  it("the status fixture has the client entry the join skips", () => {
    const client: EntryEvent | undefined = entries.find((e) => e.client);
    expect(client?.name).toBe("Moonlight");
  });
});

describe("the layout text per row (spec 3.10)", () => {
  const when = "2026-09-18T14:02:00Z";
  const layouts = {
    "2718281828": { real_appid: 2379780, result: "copied" as const, url: "workshop://1", when },
    "2987654321": { real_appid: 1244090, result: "kept" as const, url: "template://sea.vdf", when },
  };

  it("stream rows carry copied / own layout / Steam default / unavailable from layouts.json", () => {
    const rows = joinTitles(apps, entries, [], layouts);
    expect(byName(rows, "Balatro").layout).toBe("copied");
    expect(byName(rows, "Sea of Stars").layout).toBe("own layout");
    const kept = joinTitles(apps, entries, [], {
      "2718281828": { real_appid: 2379780, result: "kept", url: "default://balatro", when },
    });
    expect(byName(kept, "Balatro").layout).toBe("Steam default");
    const unavailable = joinTitles(apps, entries, [], {
      "2718281828": { real_appid: 2379780, result: "unavailable", url: null, when },
    });
    expect(byName(unavailable, "Balatro").layout).toBe("unavailable");
    const picker = joinTitles(apps, entries, [], {
      "2718281828": { real_appid: 2379780, result: "picker", url: null, when },
    });
    expect(byName(picker, "Balatro").layout).toBe("picker opened");
  });

  it("is null before any copy and for rows that have no hidden shortcut", () => {
    const rows = joinTitles(apps, entries, [], layouts);
    expect(byName(rowsOf(), "Balatro").layout).toBeNull(); // no layouts.json yet
    for (const name of ["Hades II", "Tunic", "Demo Launcher", "Sea of Stars (GOG)", "Spiritfarer"]) {
      expect(byName(rows, name).layout).toBeNull();
      expect(byName(rows, name).layoutTarget).toBeNull();
    }
  });

  it("names the pair Choose layout and the copy work on", () => {
    const rows = joinTitles(apps, entries, [], layouts);
    expect(byName(rows, "Balatro").layoutTarget).toEqual({ shortcutAppid: 2718281828, realAppid: 2379780 });
    expect(byName(rows, "Sea of Stars").layoutTarget).toEqual({ shortcutAppid: 2987654321, realAppid: 1244090 });
    expect(layoutTargetOf("stream", null)).toBeNull();
    expect(layoutTargetOf("shortcut", entries[0])).toBeNull();
    expect(layoutTargetOf("stream", { ...entries[0], parked: true })).toBeNull();
  });

  it("a host-app row is picker only: a target with no real appid (spec 3.14.1)", () => {
    const desktopEntry = entries.find((e) => e.name === "Desktop")!;
    const rows = joinTitles(apps, entries, [], {
      ...layouts,
      "3000000101": { real_appid: null, result: "picker", url: null, when },
    });
    // Desktop's match has a Steam appid; it is still never the copy's source.
    expect(desktopEntry.match?.steam_appid).toBe(226620);
    expect(byName(rows, "Desktop").layoutTarget).toEqual({ shortcutAppid: 3000000101, realAppid: null });
    expect(byName(rows, "Desktop").layout).toBe("picker opened");
    expect(byName(rows, "Steam Big Picture").layoutTarget).toEqual({ shortcutAppid: 3000000102, realAppid: null });
    expect(byName(rows, "Steam Big Picture").layout).toBeNull();
    // Still a visible tile (not synced under the flag yet): its library page has the configurator.
    expect(layoutTargetOf("host-app", { ...desktopEntry, hidden: false })).toBeNull();
    expect(layoutTargetOf("host-app", { ...desktopEntry, parked: true })).toBeNull();
    expect(layoutTargetOf("host-app", null)).toBeNull();
  });
});
