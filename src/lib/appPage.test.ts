import { describe, expect, it } from "vitest";

import { streamRowIndex } from "./appPage";

const PANEL = "_1_cYNJSvS6IXs9vLTEYjy5";

const header = { type: "de", props: { className: "_2gZXhRmKUk68pA28-5ZmGQ tXlLvuTxOVL1w3aVPX4bm" } };
const panel = { type: "g", props: { className: PANEL } };
/** Another plugin's child: a component element with no class of its own (ProtonDB Badges' medal). */
const badge = { type: () => null, props: {} };
const row = { key: "moonlight-sync-stream", props: {} };

/** What `injectStreamRow` does with the index. */
function insert(children: unknown[]): unknown[] {
  const next = [...children];
  next.splice(streamRowIndex(next, PANEL), 0, row);
  return next;
}

describe("streamRowIndex", () => {
  it("is right before the overview panel on the client's own column", () => {
    expect(insert([header, panel, [null]])).toEqual([header, row, panel, [null]]);
  });

  // The Deck's 2026-09-26: the row at index 1 sat ahead of the badge, which is drawn above it.
  it("puts the row after a child another plugin added first", () => {
    expect(insert([header, badge, panel, [null]])).toEqual([header, badge, row, panel, [null]]);
  });

  it("stays behind a child another plugin adds at index 1 afterwards", () => {
    const children = insert([header, panel]);
    children.splice(1, 0, badge);
    expect(children).toEqual([header, badge, row, panel]);
  });

  it("finds the panel among several classes, and only as a whole class", () => {
    expect(streamRowIndex([header, badge, { props: { className: `${PANEL} Panel Focusable` } }], PANEL)).toBe(2);
    expect(streamRowIndex([header, badge, { props: { className: `${PANEL}x` } }], PANEL)).toBe(1);
  });

  it("falls back to right after the header when the panel is not recognised", () => {
    expect(streamRowIndex([header, badge, [null]], PANEL)).toBe(1);
    expect(streamRowIndex([header, badge, panel], undefined)).toBe(1);
    expect(streamRowIndex([header, null, "text", 3, panel], "")).toBe(1);
  });

  it("never points past the end", () => {
    expect(streamRowIndex([], PANEL)).toBe(0);
    expect(streamRowIndex([header], PANEL)).toBe(1);
  });
});
