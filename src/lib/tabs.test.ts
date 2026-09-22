import { describe, expect, it } from "vitest";

import {
  activeTabFor,
  findElement,
  footerOf,
  hasStreamingTab,
  isLibraryTabs,
  STREAMING_TAB_ID,
  syntheticCollection,
  templateOf,
} from "./tabs";

/** A React-element-shaped plain object. */
const el = (type: unknown, props: Record<string, unknown> = {}, key: string | null = null) => ({ type, key, props });

const collection = { id: "NonSteam", displayName: "Non-Steam", allApps: [{ appid: 2718281828 }] };
const grid = el("Grid", { collection, eSortBy: 1 });
const nonSteam = {
  id: "NonSteam",
  title: "Non-Steam",
  content: el("div", { children: [null, el("span"), grid] }),
  footer: { onOptionsActionDescription: "Sort" },
};
const installed = { id: "Installed", title: "Installed", content: el("Spinner") };
const settingsTabs = [
  { id: "General", title: "General", content: el("div", { children: el("Toggle", { checked: true }) }) },
  { id: "Advanced", title: "Advanced", content: el("Field", { collection: "not one" }) },
];

describe("the Streaming tab's pure half (spec 3.17)", () => {
  it("finds an element depth-first through children and arrays", () => {
    expect(findElement(nonSteam.content, (e) => e.type === "Grid")).toBe(grid);
    expect(findElement(nonSteam.content, (e) => e.type === "Table")).toBeNull();
    expect(findElement(null, () => true)).toBeNull();
    expect(findElement("text", () => true)).toBeNull();
  });

  it("stops at a bounded depth on a tree that nests too far", () => {
    let tree: unknown = el("Grid", { collection });
    for (let i = 0; i < 40; i++) tree = el("div", { children: tree });
    expect(findElement(tree, (e) => e.type === "Grid")).toBeNull();
  });

  it("takes the first built-in tab that renders a collection as the template", () => {
    expect(templateOf([installed, nonSteam])).toBe(grid);
    expect(templateOf([installed])).toBeNull();
    expect(templateOf(settingsTabs)).toBeNull();
    // never its own tab, should a stale one carry a collection
    expect(templateOf([{ id: STREAMING_TAB_ID, content: grid }])).toBeNull();
  });

  it("recognises the library's tab bar and not another Tabs", () => {
    expect(isLibraryTabs([installed, nonSteam])).toBe(true);
    expect(isLibraryTabs(settingsTabs)).toBe(false);
    expect(isLibraryTabs("tabs")).toBe(false);
  });

  it("borrows the template's footer", () => {
    expect(footerOf([installed, nonSteam])).toEqual(nonSteam.footer);
    expect(footerOf([installed])).toBeUndefined();
  });

  it("knows its own tab", () => {
    expect(hasStreamingTab([installed, nonSteam])).toBe(false);
    expect(hasStreamingTab([installed, { id: STREAMING_TAB_ID }])).toBe(true);
  });

  it("puts the requested Streaming tab back after the library's fallback to its first tab", () => {
    const withOurs = [installed, nonSteam, { id: STREAMING_TAB_ID }];
    // the page asked for ours and answered with its first tab: ours
    expect(activeTabFor(STREAMING_TAB_ID, "Installed", withOurs)).toBe(STREAMING_TAB_ID);
    // already ours: unchanged
    expect(activeTabFor(STREAMING_TAB_ID, STREAMING_TAB_ID, withOurs)).toBe(STREAMING_TAB_ID);
    // the page asked for another tab, or for none: whatever it decided
    expect(activeTabFor("NonSteam", "NonSteam", withOurs)).toBe("NonSteam");
    expect(activeTabFor(undefined, "Installed", withOurs)).toBe("Installed");
    expect(activeTabFor(null, "Installed", withOurs)).toBe("Installed");
    // ours requested but not in the bar (the setting off, no template): left alone
    expect(activeTabFor(STREAMING_TAB_ID, "Installed", [installed, nonSteam])).toBe("Installed");
  });

  it("builds a read-only collection over the overviews, deduped", () => {
    const a = { appid: 620 };
    const b = { appid: 2718281828 };
    const made = syntheticCollection([a, b, a]);
    expect(made.id).toBe(STREAMING_TAB_ID);
    expect(made.displayName).toBe("Streaming");
    expect(made.allApps).toEqual([a, b]);
    expect(made.visibleApps).toEqual([a, b]);
    expect(made.apps.get(620)).toBe(a);
    expect(made.GetAppCountWithToolsFilter()).toBe(2);
    expect(made.bIsDynamic).toBe(false);
    expect(made.AsDragDropCollection()).toBeNull();
    expect(syntheticCollection([]).allApps).toEqual([]);
  });
});
