/**
 * The owned game's library page, the pure half of `routes/libraryApp.tsx`:
 * where the Stream row goes among the children of the page's column.
 *
 * The column is the client's `[header, overview panel, …]`, and the row is
 * drawn between the two. Other plugins add children of their own to the
 * same array, conventionally at index 1, and some of those are positioned
 * absolutely over the header (ProtonDB Badges' medal). The client's gamepad
 * navigation orders a column's children by document position, not by where
 * they are drawn (its nav node sorts with `compareDocumentPosition`;
 * measured on a Deck 2026-09-26), so a row at index 1 that landed ahead of
 * such a badge was reached *after* it going up from Play, though it is
 * drawn below it. The row therefore goes directly before the overview
 * panel: whatever another plugin adds after the header, before or after
 * this patch ran, is ahead of the row in the document, as on screen.
 *
 * Nothing here imports React or `@decky/*`: a React element is a plain
 * object with `props`, which is all this reads.
 */

/** As much of a child element as the lookup reads. */
interface ChildLike {
  props?: { className?: unknown } | null;
}

function hasClass(child: unknown, marker: string): boolean {
  const className = (child as ChildLike | null | undefined)?.props?.className;
  return typeof className === "string" && className.split(/\s+/).includes(marker);
}

/**
 * The index to insert the Stream row at: that of the overview panel (the
 * child carrying `panelClass`, `appDetailsClasses.AppDetailsOverviewPanel`),
 * else right after the header as before, on a client whose panel is not
 * recognised.
 */
export function streamRowIndex(children: readonly unknown[], panelClass: string | undefined): number {
  if (panelClass) {
    const panel = children.findIndex((child) => hasClass(child, panelClass));
    if (panel >= 0) return panel;
  }
  return Math.min(1, children.length);
}
