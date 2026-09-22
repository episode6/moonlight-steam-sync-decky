import { describe, expect, it } from "vitest";

import { loadFixture } from "../test/fixtures";
import type { DefaultLayout, LayoutEntry } from "./cli";
import { eventsOf } from "./events";
import {
  DEFAULT_LAYOUT_SCHEMES,
  DEFAULT_LAYOUT_STRATEGY,
  DECK_CONTROLLER_TYPE,
  DECK_CONTROLLER_TYPE_STRING,
  appliedUrl,
  applyDefault,
  deckControllerIndexFrom,
  defaultLayoutOf,
  isDefaultUrl,
  isShareableUrl,
  isUnselected,
  layoutControllerIndexFrom,
  layoutKindText,
  layoutLine,
  layoutStatusText,
  layoutStrategy,
  menuLayoutSourceOf,
  unsetApplied,
  walkTargets,
  type SteamInput,
} from "./layouts";

const REAL = 1245620; // ELDEN RING
const SHORTCUT = 0x80000000 + 42;
const DECK = 15; // deckyemu measured 15: never 0 (spec 2.2)
const WHEN = "2026-09-21T10:00:00Z";

const DEFAULT: DefaultLayout = { url: "workshop://2810081311", title: "Gamepad with camera controls", when: WHEN };
const OLD_DEFAULT = "workshop://1000";

/**
 * A mocked `SteamClient.Input`: a selection per appid, a log of every
 * `SetSelectedConfigForApp` / `ClearSelectedConfigForApp`, and knobs for
 * the failure modes.
 */
class FakeInput implements SteamInput {
  index: number | null = DECK;
  urls = new Map<number, string>();
  /** Appids whose config Steam only offers (`bSelected: false`), as probe V1 read an untouched game. */
  unselected = new Set<number>();
  sets: [number, number, string][] = [];
  clears: [number, number][] = [];
  gets: number[] = [];
  /** What the shortcut reads back after a set (default: what was set). */
  readBack: ((url: string) => string) | null = null;
  /** What a clear leaves behind (default: Steam's guess). */
  afterClear: string | null = "default://elden ring";
  throwOnSet = false;
  throwOnGet = false;
  throwOnClear = false;
  /** Absent on a client without `ClearSelectedConfigForApp`. */
  clearConfig?: (appid: number, controllerIndex: number) => Promise<void>;
  constructor() {
    this.clearConfig = async (appid, controllerIndex) => {
      if (this.throwOnClear) throw new Error("ClearSelectedConfigForApp failed");
      this.clears.push([appid, controllerIndex]);
      if (this.afterClear === null) this.urls.delete(appid);
      else this.urls.set(appid, this.afterClear);
    };
  }
  controllerIndex() {
    return this.index;
  }
  async getConfig(appid: number) {
    this.gets.push(appid);
    if (this.throwOnGet) throw new Error("no");
    const URL = this.urls.get(appid);
    return URL === undefined ? null : { URL, Title: "x", bSelected: !this.unselected.has(appid) };
  }
  async setConfig(appid: number, controllerIndex: number, url: string) {
    if (this.throwOnSet) throw new Error("SetSelectedConfigForApp failed");
    this.sets.push([appid, controllerIndex, url]);
    this.urls.set(appid, this.readBack ? this.readBack(url) : url);
    this.unselected.delete(appid);
  }
}

const record = (result: LayoutEntry["result"], url: string | null, applied?: string | null): LayoutEntry => ({
  real_appid: REAL,
  result,
  url,
  when: WHEN,
  ...(applied === undefined ? {} : { applied }),
});

describe("applyDefault (spec 3.16.3)", () => {
  it("sets the default on a shortcut that only has Steam's guess, no URL, or an offered template", async () => {
    for (const setup of [
      (input: FakeInput) => input.urls.set(SHORTCUT, "default://elden ring"),
      () => undefined,
      (input: FakeInput) => {
        input.urls.set(SHORTCUT, "template://controller_neptune_gamepad_joystick.vdf");
        input.unselected.add(SHORTCUT);
      },
    ]) {
      const input = new FakeInput();
      setup(input);
      expect(await applyDefault(SHORTCUT, DEFAULT, null, input)).toEqual({ result: "default", url: DEFAULT.url });
      expect(input.sets).toEqual([[SHORTCUT, DECK, DEFAULT.url]]);
    }
  });

  it("keeps the shortcut's own selection with no record, and never sets", async () => {
    const input = new FakeInput();
    input.urls.set(SHORTCUT, "template://controller_neptune_keyboard.vdf");
    expect(await applyDefault(SHORTCUT, DEFAULT, null, input)).toEqual({
      result: "kept",
      url: "template://controller_neptune_keyboard.vdf",
    });
    expect(input.sets).toEqual([]);
  });

  it("keeps a hand-picked layout that happens to be the default itself (the title it was adopted from)", async () => {
    const input = new FakeInput();
    input.urls.set(SHORTCUT, DEFAULT.url);
    // no record, and a record that says the plugin never set anything here
    expect(await applyDefault(SHORTCUT, DEFAULT, null, input)).toEqual({ result: "kept", url: DEFAULT.url });
    expect(await applyDefault(SHORTCUT, DEFAULT, record("kept", DEFAULT.url, null), input)).toEqual({
      result: "kept",
      url: DEFAULT.url,
    });
    expect(input.sets).toEqual([]);
  });

  it("selection = applied = default: already there, no set", async () => {
    const input = new FakeInput();
    input.urls.set(SHORTCUT, DEFAULT.url);
    expect(await applyDefault(SHORTCUT, DEFAULT, record("default", DEFAULT.url, DEFAULT.url), input)).toEqual({
      result: "default",
      url: DEFAULT.url,
    });
    expect(input.sets).toEqual([]);
  });

  it("selection = applied but the default moved on: the plugin's own layout is replaced", async () => {
    const input = new FakeInput();
    input.urls.set(SHORTCUT, OLD_DEFAULT);
    expect(await applyDefault(SHORTCUT, DEFAULT, record("default", OLD_DEFAULT, OLD_DEFAULT), input)).toEqual({
      result: "default",
      url: DEFAULT.url,
    });
    expect(input.sets).toEqual([[SHORTCUT, DECK, DEFAULT.url]]);
  });

  it("a legacy copied record with the same URL counts as plugin-applied and is replaced (Decision 46)", async () => {
    const input = new FakeInput();
    input.urls.set(SHORTCUT, "workshop://777");
    expect(await applyDefault(SHORTCUT, DEFAULT, record("copied", "workshop://777"), input)).toEqual({
      result: "default",
      url: DEFAULT.url,
    });
    expect(input.sets).toHaveLength(1);
  });

  it("a copied record but a different URL now: the user changed it since, kept", async () => {
    const input = new FakeInput();
    input.urls.set(SHORTCUT, "autosave:///x/config/2147483690/controller_neptune.vdf");
    expect(await applyDefault(SHORTCUT, DEFAULT, record("copied", "workshop://777"), input)).toEqual({
      result: "kept",
      url: "autosave:///x/config/2147483690/controller_neptune.vdf",
    });
    expect(input.sets).toEqual([]);
  });

  it("an edited-in-place layout after the default landed is the user's: kept", async () => {
    const input = new FakeInput();
    input.urls.set(SHORTCUT, "autosave:///x/controller_neptune.vdf");
    expect(
      (await applyDefault(SHORTCUT, DEFAULT, record("default", DEFAULT.url, DEFAULT.url), input)).result,
    ).toBe("kept");
    expect(input.sets).toEqual([]);
  });

  it("is unavailable without a controller, and makes no calls", async () => {
    const input = new FakeInput();
    input.index = null;
    expect(await applyDefault(SHORTCUT, DEFAULT, null, input)).toEqual({ result: "unavailable", url: null });
    expect(input.sets).toEqual([]);
    expect(input.gets).toEqual([]);
  });

  it("is unavailable when the read-back differs, reporting the URL that did not stick", async () => {
    const input = new FakeInput();
    input.readBack = () => "default://elden ring";
    expect(await applyDefault(SHORTCUT, DEFAULT, null, input)).toEqual({ result: "unavailable", url: DEFAULT.url });
  });

  it("is unavailable when a Steam call throws, never a rejection", async () => {
    const input = new FakeInput();
    input.throwOnSet = true;
    await expect(applyDefault(SHORTCUT, DEFAULT, null, input)).resolves.toEqual({ result: "unavailable", url: null });
    input.throwOnSet = false;
    input.throwOnGet = true;
    await expect(applyDefault(SHORTCUT, DEFAULT, null, input)).resolves.toEqual({ result: "unavailable", url: null });
  });

  it("is idempotent, and a later hand change survives the next call", async () => {
    const input = new FakeInput();
    input.urls.set(SHORTCUT, "default://elden ring");
    const first = await applyDefault(SHORTCUT, DEFAULT, null, input);
    expect(first.result).toBe("default");
    // recorded as the backend would: applied = the URL just set
    const entry = record("default", first.url, first.url);
    expect(await applyDefault(SHORTCUT, DEFAULT, entry, input)).toEqual({ result: "default", url: DEFAULT.url });
    expect(input.sets).toHaveLength(1);
    input.urls.set(SHORTCUT, "workshop://999");
    expect(await applyDefault(SHORTCUT, DEFAULT, entry, input)).toEqual({ result: "kept", url: "workshop://999" });
    expect(input.sets).toHaveLength(1);
  });

  it("never reads any appid but the shortcut's: the real game is not an input", async () => {
    const input = new FakeInput();
    input.urls.set(REAL, "workshop://from-the-real-game");
    await applyDefault(SHORTCUT, DEFAULT, record("copied", "workshop://777"), input);
    await applyDefault(SHORTCUT, DEFAULT, null, input);
    expect(new Set(input.gets)).toEqual(new Set([SHORTCUT]));
  });

  it("isUnselected: no URL, default://, or bSelected false; a missing bSelected decides nothing", () => {
    expect(isUnselected(null)).toBe(true);
    expect(isUnselected({ URL: "default://x", bSelected: true })).toBe(true);
    expect(isUnselected({ URL: "template://a.vdf", bSelected: false })).toBe(true);
    expect(isUnselected({ URL: "template://a.vdf" })).toBe(false);
    // a layout edited in place is a choice, though its eSelectionType reads 0
    expect(isUnselected({ URL: "autosave:///x/controller_neptune.vdf", bSelected: true })).toBe(false);
  });

  it("appliedUrl: the explicit field, else a legacy copied record's URL", () => {
    expect(appliedUrl(null)).toBeNull();
    expect(appliedUrl(record("copied", "workshop://1"))).toBe("workshop://1");
    expect(appliedUrl(record("copied", "workshop://1", null))).toBeNull();
    expect(appliedUrl(record("kept", "workshop://1"))).toBeNull();
    expect(appliedUrl(record("kept", "workshop://1", "workshop://1"))).toBe("workshop://1");
    expect(appliedUrl(record("default", "workshop://2", "workshop://2"))).toBe("workshop://2");
    expect(appliedUrl(record("unavailable", null, "workshop://2"))).toBe("workshop://2");
  });
});

describe("unsetApplied (spec 3.16.3, Decision 51)", () => {
  it("does nothing without an explicit applied, including a legacy copied record", async () => {
    const input = new FakeInput();
    input.urls.set(SHORTCUT, "workshop://1");
    expect(await unsetApplied(SHORTCUT, null, input)).toBeNull();
    expect(await unsetApplied(SHORTCUT, record("copied", "workshop://1"), input)).toBeNull();
    expect(await unsetApplied(SHORTCUT, record("kept", "workshop://1", null), input)).toBeNull();
    expect(input.clears).toEqual([]);
    expect(input.gets).toEqual([]);
  });

  it("keeps a hand-changed selection, with no clear (which drops applied when recorded)", async () => {
    const input = new FakeInput();
    input.urls.set(SHORTCUT, "workshop://999");
    expect(await unsetApplied(SHORTCUT, record("default", "workshop://1", "workshop://1"), input)).toEqual({
      result: "kept",
      url: "workshop://999",
    });
    expect(input.clears).toEqual([]);
    // an entry already back on Steam's guess reads the same way
    input.urls.set(SHORTCUT, "default://elden ring");
    expect(await unsetApplied(SHORTCUT, record("default", "workshop://1", "workshop://1"), input)).toEqual({
      result: "kept",
      url: "default://elden ring",
    });
    expect(input.clears).toEqual([]);
  });

  it("clears a selection that is still ours and reads back Steam's default", async () => {
    const input = new FakeInput();
    input.urls.set(SHORTCUT, "workshop://1");
    expect(await unsetApplied(SHORTCUT, record("default", "workshop://1", "workshop://1"), input)).toEqual({
      result: "kept",
      url: "default://elden ring",
      cleared: true,
    });
    expect(input.clears).toEqual([[SHORTCUT, DECK]]);
    input.afterClear = null;
    input.urls.set(SHORTCUT, "workshop://1");
    expect(await unsetApplied(SHORTCUT, record("default", "workshop://1", "workshop://1"), input)).toEqual({
      result: "kept",
      url: null,
      cleared: true,
    });
  });

  it("is unavailable, carrying ours, when the read-back is still selected or the clear throws", async () => {
    const input = new FakeInput();
    input.urls.set(SHORTCUT, "workshop://1");
    input.afterClear = "workshop://1";
    expect(await unsetApplied(SHORTCUT, record("default", "workshop://1", "workshop://1"), input)).toEqual({
      result: "unavailable",
      url: "workshop://1",
    });
    input.throwOnClear = true;
    await expect(unsetApplied(SHORTCUT, record("default", "workshop://1", "workshop://1"), input)).resolves.toEqual({
      result: "unavailable",
      url: "workshop://1",
    });
  });

  it("is null on a client without clearConfig, or without a controller", async () => {
    const input = new FakeInput();
    input.urls.set(SHORTCUT, "workshop://1");
    const entry = record("default", "workshop://1", "workshop://1");
    delete input.clearConfig;
    expect(await unsetApplied(SHORTCUT, entry, input)).toBeNull();
    const noPad = new FakeInput();
    noPad.index = null;
    noPad.urls.set(SHORTCUT, "workshop://1");
    expect(await unsetApplied(SHORTCUT, entry, noPad)).toBeNull();
    expect(noPad.gets).toEqual([]);
  });
});

describe("what can be a default (spec 3.16.1)", () => {
  it("isShareableUrl: workshop:// and template:// only", () => {
    expect(DEFAULT_LAYOUT_SCHEMES).toEqual(["workshop://", "template://"]);
    expect(isShareableUrl("workshop://2810081311")).toBe(true);
    expect(isShareableUrl("template://controller_neptune_gamepad.vdf")).toBe(true);
    expect(isShareableUrl("autosave:///x/controller_neptune.vdf")).toBe(false);
    expect(isShareableUrl("localconfig://x")).toBe(false);
    expect(isShareableUrl("default://elden ring")).toBe(false);
    expect(isShareableUrl("")).toBe(false);
    expect(isShareableUrl(null)).toBe(false);
    expect(isShareableUrl(undefined)).toBe(false);
  });

  it("defaultLayoutOf: the setting under copy; null under picker, when unset, or broken", () => {
    expect(defaultLayoutOf({ default_layout: DEFAULT })).toEqual(DEFAULT);
    expect(defaultLayoutOf({ default_layout: DEFAULT, layout_strategy: "copy" })).toEqual(DEFAULT);
    expect(defaultLayoutOf({ default_layout: DEFAULT, layout_strategy: "picker" })).toBeNull();
    expect(defaultLayoutOf({ default_layout: null })).toBeNull();
    expect(defaultLayoutOf(null)).toBeNull();
    expect(defaultLayoutOf({ default_layout: { ...DEFAULT, when: null } })).toEqual({ ...DEFAULT, when: null });
    expect(defaultLayoutOf({ default_layout: { ...DEFAULT, url: "autosave:///x.vdf" } })).toBeNull();
    expect(defaultLayoutOf({ default_layout: { url: DEFAULT.url } as never })).toBeNull();
  });
});

describe("the controller to set the layout for (layoutControllerIndexFrom)", () => {
  const deck = { nControllerIndex: DECK, eControllerType: DECK_CONTROLLER_TYPE };
  const a = { nControllerIndex: 0, eControllerType: 10 };
  const b = { nControllerIndex: 1, eControllerType: 45 };
  it("prefers the Deck's, then the listed active one, then the only one", () => {
    expect(layoutControllerIndexFrom([a, deck], undefined, 0)).toBe(DECK);
    expect(layoutControllerIndexFrom([a, b], undefined, 1)).toBe(1);
    expect(layoutControllerIndexFrom([a, b], undefined, 7)).toBeNull();
    expect(layoutControllerIndexFrom([a, b])).toBeNull();
    expect(layoutControllerIndexFrom([a])).toBe(0);
    expect(layoutControllerIndexFrom([], undefined, 0)).toBeNull();
    expect(layoutControllerIndexFrom(null, undefined, 0)).toBeNull();
  });
});

describe("the Deck controller index by type (spec 2.2)", () => {
  const controllers = [
    { nControllerIndex: 0, eControllerType: 30 }, // an Xbox pad plugged in first
    { nControllerIndex: DECK, eControllerType: DECK_CONTROLLER_TYPE },
  ];

  it("finds it by the enum value, not at index 0", () => {
    expect(deckControllerIndexFrom(controllers)).toBe(DECK);
  });

  it("finds it through Steam's type string when the caller has that mapping", () => {
    const typeString = (type: number) => (type === DECK_CONTROLLER_TYPE ? DECK_CONTROLLER_TYPE_STRING : "controller_xbox360");
    expect(deckControllerIndexFrom(controllers, typeString)).toBe(DECK);
    expect(deckControllerIndexFrom(controllers, () => "controller_xbox360")).toBeNull();
  });

  it("is null with no list or no Deck controller in it", () => {
    expect(deckControllerIndexFrom(null)).toBeNull();
    expect(deckControllerIndexFrom(undefined)).toBeNull();
    expect(deckControllerIndexFrom([])).toBeNull();
    expect(deckControllerIndexFrom([{ nControllerIndex: 0, eControllerType: 30 }])).toBeNull();
    expect(deckControllerIndexFrom([null as unknown as { nControllerIndex: number; eControllerType: number }])).toBeNull();
  });
});

describe("the strategy switch (spec 3.10)", () => {
  it("defaults to copy and honours a hand-set picker", () => {
    expect(DEFAULT_LAYOUT_STRATEGY).toBe("copy");
    expect(layoutStrategy(null)).toBe("copy");
    expect(layoutStrategy({})).toBe("copy");
    expect(layoutStrategy({ layout_strategy: "picker" })).toBe("picker");
    expect(layoutStrategy({ layout_strategy: "copy" })).toBe("copy");
    expect(layoutStrategy({ layout_strategy: "mirror" as never })).toBe("copy");
  });
});

describe("what the walk covers (spec 3.16.4, Decision 48)", () => {
  const entries = eventsOf(loadFixture("common/status.ndjson"), "entry");

  it("every non-parked entry in status order: stream entries, host apps, visible shortcuts and the client", () => {
    expect(walkTargets(entries)).toEqual([
      { shortcutAppid: 2718281828, realAppid: 2379780 }, // Balatro, a Stream entry
      { shortcutAppid: 3000000101, realAppid: 226620 }, // Desktop, a host app (its match is not used for anything)
      { shortcutAppid: 3000000011, realAppid: 1145360 }, // Hades II, a visible shortcut
      { shortcutAppid: 2987654321, realAppid: 1244090 }, // Sea of Stars
      { shortcutAppid: 3000000102, realAppid: null }, // Steam Big Picture
      { shortcutAppid: 3000000007, realAppid: null }, // Tunic, unmatched
      { shortcutAppid: 2400000001, realAppid: null }, // the Moonlight client entry
    ]);
    expect(walkTargets(entries).map((t) => t.shortcutAppid)).not.toContain(2555555555); // Spiritfarer is parked
  });

  it("dedupes by appid and takes nothing from an empty status", () => {
    expect(walkTargets([entries[0], { ...entries[0], name: "Balatro (again)" }])).toHaveLength(1);
    expect(walkTargets([])).toEqual([]);
  });
});

describe("what the pages show", () => {
  it("default layout / copied / own layout / Steam default / unavailable / picker opened", () => {
    expect(layoutStatusText(null)).toBeNull();
    expect(layoutStatusText(record("default", "workshop://1", "workshop://1"))).toBe("default layout");
    expect(layoutStatusText(record("copied", "workshop://1"))).toBe("copied");
    expect(layoutStatusText(record("kept", "template://x.vdf"))).toBe("own layout");
    expect(layoutStatusText(record("kept", "default://elden ring"))).toBe("Steam default");
    expect(layoutStatusText(record("kept", null))).toBe("Steam default");
    expect(layoutStatusText(record("unavailable", "workshop://1"))).toBe("unavailable");
    expect(layoutStatusText(record("picker", null))).toBe("picker opened");
  });

  it("names the layout kind on the library page", () => {
    expect(isDefaultUrl(undefined)).toBe(true);
    expect(isDefaultUrl("default://x")).toBe(true);
    expect(isDefaultUrl("workshop://1")).toBe(false);
    expect(layoutKindText("workshop://1")).toBe("Workshop layout");
    expect(layoutKindText("template://x.vdf")).toBe("template layout");
    expect(layoutKindText("localconfig://x")).toBe("localconfig layout");
    expect(layoutKindText(null)).toBe("Steam default");
    expect(layoutLine(record("default", "workshop://1", "workshop://1"))).toBe("Workshop layout · default layout");
    expect(layoutLine(record("copied", "workshop://1"))).toBe("Workshop layout · copied");
    expect(layoutLine(record("kept", "workshop://2"))).toBe("own layout");
    expect(layoutLine(null)).toBe("not set yet");
  });
});

describe("the library gear menu's source (spec 3.16.5, Decision 56)", () => {
  const entries = eventsOf(loadFixture("common/status.ndjson"), "entry");
  const streamMap = new Map([[2379780, 2718281828]]); // Balatro

  it("a real game with a Stream entry reads its own selection", () => {
    expect(menuLayoutSourceOf(entries, streamMap, 2379780)).toEqual({ appid: 2379780, kind: "game" });
  });

  it("one of the plugin's non-parked entries reads itself; a parked one gets nothing", () => {
    expect(menuLayoutSourceOf(entries, streamMap, 3000000011)).toEqual({ appid: 3000000011, kind: "entry" }); // Hades II, visible
    expect(menuLayoutSourceOf(entries, streamMap, 2400000001)).toEqual({ appid: 2400000001, kind: "entry" }); // the client
    expect(menuLayoutSourceOf(entries, streamMap, 2555555555)).toBeNull(); // Spiritfarer, parked
  });

  it("any other game gets nothing, and before status answered only the stream map counts", () => {
    expect(menuLayoutSourceOf(entries, streamMap, 1145360)).toBeNull(); // Hades, the visible shortcut's game
    expect(menuLayoutSourceOf(null, new Map(), 2379780)).toBeNull();
    expect(menuLayoutSourceOf(null, streamMap, 2379780)).toEqual({ appid: 2379780, kind: "game" });
  });
});
