/**
 * The synthetic *Streaming* library tab, the pure half (spec 3.17). The
 * client's library home renders its tab bar from a `tabs` array (a `Tab`
 * per built-in tab: id, title, content, footer); `routes/libraryTabs.tsx`
 * finds that array in the render tree and appends one more tab. The tab's
 * content is the client's own grid: the content element of a built-in tab
 * that carries a `collection` prop, cloned with a *synthetic* collection --
 * a plain object with the surface the grid reads, holding this device's
 * streamable titles. Nothing is written to `collectionStore`, so nothing
 * syncs through Steam Cloud (Decision 55).
 *
 * Nothing here imports React or `@decky/*`: a React element is a plain
 * object with `type` and `props`, which is all the walk below needs.
 */

export const STREAMING_TAB_ID = "MoonlightSyncStreaming";
export const STREAMING_TAB_TITLE = "Streaming";

/** As much of a React element as the walk reads. */
export interface ElementLike {
  type?: unknown;
  key?: string | null;
  props?: Record<string, unknown> & { children?: unknown; collection?: unknown };
}

/** A built-in library tab, as far as the injection reads it. */
export interface TabLike {
  id?: unknown;
  title?: unknown;
  content?: unknown;
  footer?: unknown;
}

/** A collection object as the client's grid reads one (best effort, unmeasured). */
export interface CollectionLike {
  id: string;
  displayName: string;
  /** Every member's overview, in tile order. */
  allApps: unknown[];
  /** The members the grid shows (the same list: hidden state is the reconcile's, not the tab's). */
  visibleApps: unknown[];
  apps: Map<number, unknown>;
  bIsDynamic: false;
  bIsEditable: false;
  bAllowsDragAndDrop: false;
  bIsDeletable: false;
  GetAppCountWithToolsFilter(): number;
  AsDragDropCollection(): null;
  AsDeletableCollection(): null;
  AsEditableCollection(): null;
}

const MAX_DEPTH = 12;

/** Depth-first over `props.children`, like `findInReactTree`; `null` when nothing matches. */
export function findElement(
  root: unknown,
  match: (element: ElementLike) => boolean,
  depth = 0,
): ElementLike | null {
  if (!root || typeof root !== "object" || depth > MAX_DEPTH) return null;
  if (Array.isArray(root)) {
    for (const item of root) {
      const found = findElement(item, match, depth + 1);
      if (found) return found;
    }
    return null;
  }
  const element = root as ElementLike;
  if (element.props && typeof element.props === "object" && match(element)) return element;
  return findElement(element.props?.children, match, depth + 1);
}

function looksLikeCollection(value: unknown): boolean {
  const c = value as { allApps?: unknown } | null | undefined;
  return !!c && typeof c === "object" && Array.isArray(c.allApps);
}

/**
 * The element to clone for the tab's content: inside a built-in tab's
 * content, the first element whose `collection` prop looks like a
 * collection. `null` when no tab has one (another client: no tab is added).
 */
export function templateOf(tabs: readonly TabLike[]): ElementLike | null {
  for (const tab of tabs) {
    if (!tab || typeof tab !== "object" || tab.id === STREAMING_TAB_ID) continue;
    const found = findElement(tab.content, (element) => looksLikeCollection(element.props?.collection));
    if (found) return found;
  }
  return null;
}

/** The library's tab bar and not another `Tabs` (Settings uses one too): some tab renders a collection. */
export function isLibraryTabs(tabs: unknown): tabs is TabLike[] {
  return Array.isArray(tabs) && templateOf(tabs) !== null;
}

export function hasStreamingTab(tabs: readonly TabLike[]): boolean {
  return tabs.some((tab) => tab?.id === STREAMING_TAB_ID);
}

/**
 * The `activeTab` the tab bar should get. Measured on a device
 * (2026-09-22): the library page reads the tab id the route asked for
 * (its `tab` prop), and, in its own render, falls back to its first tab
 * when its memoised tab array has no such id -- which it never has for
 * the Streaming tab, since the tab is added to the array only once that
 * render is out. The tabbed page below resolves `activeTab` against the
 * array as it is *after* the injection, so putting the requested id back
 * on the bar element is all it takes. Anything else is left as the page
 * decided.
 */
export function activeTabFor(requested: unknown, current: unknown, tabs: readonly TabLike[]): unknown {
  if (requested !== STREAMING_TAB_ID || current === STREAMING_TAB_ID) return current;
  return hasStreamingTab(tabs) ? STREAMING_TAB_ID : current;
}

/** The tab whose `footer` the Streaming tab borrows (its content is the same grid): the template's. */
export function footerOf(tabs: readonly TabLike[]): unknown {
  const template = templateOf(tabs);
  if (!template) return undefined;
  return tabs.find((tab) => findElement(tab?.content, (element) => element === template))?.footer;
}

/**
 * The synthetic collection behind the tab: the surface of the client's
 * `Collection` that a grid reads, over `overviews` (`appStore` overviews of
 * the members, in order; ones the client has not loaded are already left
 * out). Not editable, not dynamic, never saved.
 */
export function syntheticCollection(overviews: readonly { appid: number }[]): CollectionLike {
  const apps = new Map<number, unknown>();
  for (const overview of overviews) apps.set(overview.appid, overview);
  const list = [...apps.values()];
  return {
    id: STREAMING_TAB_ID,
    displayName: STREAMING_TAB_TITLE,
    allApps: list,
    visibleApps: list,
    apps,
    bIsDynamic: false,
    bIsEditable: false,
    bAllowsDragAndDrop: false,
    bIsDeletable: false,
    GetAppCountWithToolsFilter: () => list.length,
    AsDragDropCollection: () => null,
    AsDeletableCollection: () => null,
    AsEditableCollection: () => null,
  };
}
