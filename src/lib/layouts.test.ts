import { describe, expect, it } from "vitest";

import { loadFixture } from "../test/fixtures";
import type { LayoutEntry } from "./cli";
import { eventsOf } from "./events";
import {
  DEFAULT_LAYOUT_STRATEGY,
  DECK_CONTROLLER_TYPE,
  DECK_CONTROLLER_TYPE_STRING,
  copyEnabled,
  copyLayout,
  deckControllerIndexFrom,
  isDefaultUrl,
  isUnselected,
  layoutControllerIndexFrom,
  layoutKindText,
  layoutLine,
  layoutStatusText,
  layoutStrategy,
  walkPairs,
  type SteamInput,
} from "./layouts";
import { streamMapFromStatus } from "./state";

const REAL = 1245620; // ELDEN RING
const SHORTCUT = 0x80000000 + 42;
const DECK = 15; // deckyemu measured 15: never 0 (spec 2.2)

/**
 * A mocked `SteamClient.Input`: a selection per appid, a log of every
 * `SetSelectedConfigForApp`, and knobs for the failure modes.
 */
class FakeInput implements SteamInput {
  index: number | null = DECK;
  urls = new Map<number, string>();
  /** Appids whose config Steam only offers (`bSelected: false`), as probe V1 read an untouched game. */
  unselected = new Set<number>();
  sets: [number, number, string][] = [];
  /** What the shortcut reads back after a set (default: what was set). */
  readBack: ((url: string) => string) | null = null;
  throwOnSet = false;
  throwOnGet = false;
  controllerIndex() {
    return this.index;
  }
  async getConfig(appid: number) {
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

describe("copyLayout (spec 3.10)", () => {
  it("copies a Workshop layout onto a shortcut that only has Steam's guess", async () => {
    const input = new FakeInput();
    input.urls.set(REAL, "workshop://2810081311");
    input.urls.set(SHORTCUT, "default://elden ring");
    expect(await copyLayout(REAL, SHORTCUT, input)).toEqual({ result: "copied", url: "workshop://2810081311" });
    expect(input.sets).toEqual([[SHORTCUT, DECK, "workshop://2810081311"]]);
  });

  it("copies when the shortcut has no selection at all", async () => {
    const input = new FakeInput();
    input.urls.set(REAL, "template://controller_neptune_gamepad.vdf");
    expect((await copyLayout(REAL, SHORTCUT, input)).result).toBe("copied");
  });

  it("keeps the shortcut's own template:// choice, never overwriting it", async () => {
    const input = new FakeInput();
    input.urls.set(REAL, "workshop://2810081311");
    input.urls.set(SHORTCUT, "template://controller_neptune_keyboard.vdf");
    expect(await copyLayout(REAL, SHORTCUT, input)).toEqual({
      result: "kept",
      url: "template://controller_neptune_keyboard.vdf",
    });
    expect(input.sets).toEqual([]);
  });

  it("keeps when the real game is on Steam's default (nothing chosen to copy)", async () => {
    const input = new FakeInput();
    input.urls.set(REAL, "default://elden ring");
    input.urls.set(SHORTCUT, "default://elden ring");
    expect(await copyLayout(REAL, SHORTCUT, input)).toEqual({ result: "kept", url: "default://elden ring" });
    expect(input.sets).toEqual([]);
  });

  it("keeps when the real game's URL is empty or missing", async () => {
    const input = new FakeInput();
    input.urls.set(REAL, "");
    expect(await copyLayout(REAL, SHORTCUT, input)).toEqual({ result: "kept", url: null });
    const none = new FakeInput();
    expect(await copyLayout(REAL, SHORTCUT, none)).toEqual({ result: "kept", url: null });
    expect(none.sets).toEqual([]);
  });

  it("treats a template:// Steam only offers (bSelected false) as no selection, on either side", async () => {
    // PR-0 probe V1: a game whose controller settings were never opened.
    const untouched = new FakeInput();
    untouched.urls.set(REAL, "template://controller_neptune_gamepad_joystick.vdf");
    untouched.unselected.add(REAL);
    untouched.urls.set(SHORTCUT, "default://elden ring");
    expect(await copyLayout(REAL, SHORTCUT, untouched)).toEqual({ result: "kept", url: "default://elden ring" });
    expect(untouched.sets).toEqual([]);
    // the same offer on the shortcut does not block a copy, and is not its "own layout"
    const offered = new FakeInput();
    offered.urls.set(REAL, "workshop://1");
    offered.urls.set(SHORTCUT, "template://controller_neptune_gamepad_joystick.vdf");
    offered.unselected.add(SHORTCUT);
    expect(await copyLayout(REAL, SHORTCUT, offered)).toEqual({ result: "copied", url: "workshop://1" });
    const both = new FakeInput();
    both.urls.set(REAL, "template://a.vdf");
    both.urls.set(SHORTCUT, "template://a.vdf");
    both.unselected.add(REAL).add(SHORTCUT);
    expect(await copyLayout(REAL, SHORTCUT, both)).toEqual({ result: "kept", url: null });
  });

  it("isUnselected: no URL, default://, or bSelected false; a missing bSelected decides nothing", () => {
    expect(isUnselected(null)).toBe(true);
    expect(isUnselected({ URL: "default://x", bSelected: true })).toBe(true);
    expect(isUnselected({ URL: "template://a.vdf", bSelected: false })).toBe(true);
    expect(isUnselected({ URL: "template://a.vdf" })).toBe(false);
    // a layout edited in place is a choice, though its eSelectionType reads 0
    expect(isUnselected({ URL: "autosave:///x/controller_neptune.vdf", bSelected: true })).toBe(false);
  });

  it("is unavailable without a Deck controller, and makes no calls", async () => {
    const input = new FakeInput();
    input.index = null;
    input.urls.set(REAL, "workshop://1");
    expect(await copyLayout(REAL, SHORTCUT, input)).toEqual({ result: "unavailable", url: null });
    expect(input.sets).toEqual([]);
  });

  it("is unavailable when the read-back differs, reporting the URL that did not stick", async () => {
    const input = new FakeInput();
    input.urls.set(REAL, "workshop://1");
    input.readBack = () => "default://elden ring";
    expect(await copyLayout(REAL, SHORTCUT, input)).toEqual({ result: "unavailable", url: "workshop://1" });
  });

  it("is unavailable when setConfig throws, never a rejection", async () => {
    const input = new FakeInput();
    input.urls.set(REAL, "workshop://1");
    input.throwOnSet = true;
    await expect(copyLayout(REAL, SHORTCUT, input)).resolves.toEqual({ result: "unavailable", url: null });
    input.throwOnSet = false;
    input.throwOnGet = true;
    await expect(copyLayout(REAL, SHORTCUT, input)).resolves.toEqual({ result: "unavailable", url: null });
  });

  it("a second press is idempotent: the copied selection is now the shortcut's own", async () => {
    const input = new FakeInput();
    input.urls.set(REAL, "workshop://1");
    expect((await copyLayout(REAL, SHORTCUT, input)).result).toBe("copied");
    expect(await copyLayout(REAL, SHORTCUT, input)).toEqual({ result: "kept", url: "workshop://1" });
    expect(input.sets).toHaveLength(1);
    // and a later change on the hidden entry survives the next press
    input.urls.set(SHORTCUT, "workshop://999");
    expect(await copyLayout(REAL, SHORTCUT, input)).toEqual({ result: "kept", url: "workshop://999" });
    expect(input.sets).toHaveLength(1);
  });
});

describe("the controller to copy for (layoutControllerIndexFrom)", () => {
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

  it("copies only under copy with the Advanced toggle on", () => {
    expect(copyEnabled({ copy_layouts: true })).toBe(true);
    expect(copyEnabled({ copy_layouts: false })).toBe(false);
    expect(copyEnabled({ copy_layouts: true, layout_strategy: "picker" })).toBe(false);
    expect(copyEnabled(null)).toBe(false);
  });
});

describe("the stream map feeds the walk (spec 3.9)", () => {
  it("pairs every hidden, published, matched, non-parked, non-client entry", () => {
    const entries = eventsOf(loadFixture("common/status.ndjson"), "entry");
    expect(walkPairs(streamMapFromStatus(entries))).toEqual([
      { realAppid: 2379780, shortcutAppid: 2718281828 },
      { realAppid: 1244090, shortcutAppid: 2987654321 },
    ]);
  });

  it("never walks a default host app: no layout is copied onto Desktop (spec 3.14.1)", () => {
    const entries = eventsOf(loadFixture("common/status.ndjson"), "entry");
    // Hidden, published and matched to Steam 226620: a Stream pair but for host_app.
    const desktop = entries.find((e) => e.name === "Desktop")!;
    expect(desktop.match?.steam_appid).toBe(226620);
    const pairs = walkPairs(streamMapFromStatus(entries));
    expect(pairs.map((p) => p.shortcutAppid)).not.toContain(desktop.appid);
    expect(pairs.map((p) => p.realAppid)).not.toContain(226620);
  });

  it("derives the map from the spec's filter", () => {
    const base = eventsOf(loadFixture("common/status.ndjson"), "entry")[0];
    const variants = [
      { ...base, hidden: false },
      { ...base, parked: true },
      { ...base, published: false },
      { ...base, client: true },
      { ...base, match: null },
      { ...base, match: { ...base.match!, steam_appid: null } },
      { ...base, host_app: true },
    ];
    for (const entry of variants) expect(streamMapFromStatus([entry]).size).toBe(0);
    expect(streamMapFromStatus([base]).get(2379780)).toBe(base.appid);
  });
});

describe("what the pages show", () => {
  const entry = (result: LayoutEntry["result"], url: string | null): LayoutEntry => ({
    real_appid: REAL,
    result,
    url,
    when: "2026-09-18T14:02:00Z",
  });

  it("copied / own layout / Steam default / unavailable / picker opened", () => {
    expect(layoutStatusText(null)).toBeNull();
    expect(layoutStatusText(entry("copied", "workshop://1"))).toBe("copied");
    expect(layoutStatusText(entry("kept", "template://x.vdf"))).toBe("own layout");
    expect(layoutStatusText(entry("kept", "default://elden ring"))).toBe("Steam default");
    expect(layoutStatusText(entry("kept", null))).toBe("Steam default");
    expect(layoutStatusText(entry("unavailable", "workshop://1"))).toBe("unavailable");
    expect(layoutStatusText(entry("picker", null))).toBe("picker opened");
  });

  it("names the layout kind on the library page", () => {
    expect(isDefaultUrl(undefined)).toBe(true);
    expect(isDefaultUrl("default://x")).toBe(true);
    expect(isDefaultUrl("workshop://1")).toBe(false);
    expect(layoutKindText("workshop://1")).toBe("Workshop layout");
    expect(layoutKindText("template://x.vdf")).toBe("template layout");
    expect(layoutKindText("localconfig://x")).toBe("localconfig layout");
    expect(layoutKindText(null)).toBe("Steam default");
    expect(layoutLine(entry("copied", "workshop://1"))).toBe("Workshop layout · copied");
    expect(layoutLine(entry("kept", "workshop://2"))).toBe("own layout");
    expect(layoutLine(null)).toBe("not copied yet");
  });
});
