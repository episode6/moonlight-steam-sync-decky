/**
 * The shapes the route patches read out of Steam's React trees, shared so
 * `libraryApp.tsx`, `libraryTabs.tsx` and `libraryContextMenu.tsx` cannot
 * drift: an element's `key`, `type` and the few props they look for.
 */

/** A library page's app overview: what `/library/app/:appid` renders and the gear menu is opened for. */
export interface Overview {
  appid: number;
  display_name?: string;
}

/** A React element as the patches see it; every field optional, since anything may be in the tree. */
export interface TreeNode {
  key?: string | null;
  type?: unknown;
  props?: Record<string, unknown> & {
    children?: unknown;
    className?: unknown;
    overview?: unknown;
    tabs?: unknown;
    renderFunc?: unknown;
  };
}

export function isOverview(value: unknown): value is Overview {
  return typeof (value as Overview | null | undefined)?.appid === "number";
}
