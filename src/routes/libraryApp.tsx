/**
 * The `/library/app/:appid` route patch (spec 3.9): every owned game's
 * library page gets a `StreamButton`, which renders only while the stream
 * map has that appid. Written from `@decky/ui`'s primitives -- `afterPatch`,
 * `createReactTreePatcher`, `findInReactTree` -- and nothing else.
 *
 * The route's `renderFunc` does not return the page. On the client this was
 * checked against (2026-09-21) it returns one element,
 * `<L appid renderChildrenFunc>`; that function returns the app-details
 * component (the one whose props carry `overview`), and only *its* render
 * output holds the inner container (the column with the header, the play
 * bar and the sections). So the patch goes down the same way: `renderFunc`,
 * then `renderChildrenFunc` when there is one, then the overview
 * component's type (`createReactTreePatcher`, which caches the patched type
 * so the page is not remounted on every render), and there the button row
 * is spliced in right after the header. Anything unexpected in the tree
 * (another client version, a page still loading) leaves the page untouched;
 * the patch never throws into Steam's render.
 */

import { routerHook } from "@decky/api";
import { afterPatch, appDetailsClasses, createReactTreePatcher, findInReactTree } from "@decky/ui";
import type { ReactElement } from "react";

import { StreamButton } from "../components/StreamButton";
import { SHORTCUT_APPID_FLOOR } from "../lib/steam";

export const LIBRARY_APP_ROUTE = "/library/app/:appid";

/** The `key` of the injected row, so a re-render of an already patched tree adds nothing. */
const STREAM_ROW_KEY = "moonlight-sync-stream";

interface Overview {
  appid: number;
  display_name?: string;
}

interface TreeNode {
  key?: string | null;
  type?: unknown;
  props?: Record<string, unknown> & { children?: unknown; className?: unknown; overview?: unknown };
}

function isOverview(value: unknown): value is Overview {
  return typeof (value as Overview | null | undefined)?.appid === "number";
}

/** The app-details element: the one whose props carry the page's `overview`. */
function overviewNodeOf(tree: unknown): TreeNode | null {
  const node = findInReactTree(tree, (n: TreeNode) => isOverview(n?.props?.overview)) as TreeNode | undefined;
  return node ?? null;
}

/** The column that holds the header and the play section: a node with a children array and the InnerContainer class. */
function innerContainerOf(tree: unknown): (TreeNode & { props: { children: unknown[] } }) | null {
  const marker = appDetailsClasses.InnerContainer;
  if (!marker) return null;
  const node = findInReactTree(
    tree,
    (n: TreeNode) => Array.isArray(n?.props?.children) && typeof n?.props?.className === "string" && n.props.className.includes(marker),
  ) as (TreeNode & { props: { children: unknown[] } }) | undefined;
  return node ?? null;
}

/**
 * Add the Stream row to the app-details component's render output; a no-op
 * when the tree is not the shape expected.
 */
export function injectStreamRow(rendered: unknown, overview: Overview | null): boolean {
  // Only real Steam apps get a button; a shortcut's own page never does.
  if (!overview || overview.appid <= 0 || overview.appid >= SHORTCUT_APPID_FLOOR) return false;
  const container = innerContainerOf(rendered);
  if (!container) return false;
  const children = container.props.children;
  if (children.some((child) => (child as TreeNode | null)?.key === STREAM_ROW_KEY)) return true;
  children.splice(1, 0, <StreamButton key={STREAM_ROW_KEY} appid={overview.appid} name={overview.display_name} />);
  return true;
}

/**
 * Runs over whatever holds the app-details element: patches that element's
 * type, and the handler then sees the component's props and render output.
 */
const patchAppDetails = createReactTreePatcher(
  [overviewNodeOf],
  (args: unknown[], rendered: unknown) => {
    try {
      const overview = (args[0] as { overview?: unknown } | undefined)?.overview;
      injectStreamRow(rendered, isOverview(overview) ? overview : null);
    } catch (error) {
      console.warn("Moonlight Sync: could not patch the library page", error);
    }
    return rendered;
  },
  "MoonlightSyncLibraryApp",
);

interface RenderableChild {
  props?: { renderFunc?: (...args: unknown[]) => ReactElement };
}

/** Install the route patch; the returned function removes it (`onDismount`). */
export function patchLibraryApp(): () => void {
  const patch = routerHook.addPatch(LIBRARY_APP_ROUTE, (route) => {
    const child = route.children as RenderableChild | undefined;
    if (!child || typeof child !== "object" || !child.props || typeof child.props.renderFunc !== "function") {
      return route;
    }
    afterPatch(child.props, "renderFunc", (_args: unknown[], rendered: ReactElement) => {
      try {
        const holder = findInReactTree(rendered, (n: TreeNode) => typeof n?.props?.renderChildrenFunc === "function") as
          | TreeNode
          | undefined;
        if (holder?.props) afterPatch(holder.props, "renderChildrenFunc", patchAppDetails);
        else patchAppDetails([], rendered);
      } catch (error) {
        console.warn("Moonlight Sync: could not patch the library page", error);
      }
      return rendered;
    });
    return route;
  });
  return () => routerHook.removePatch(LIBRARY_APP_ROUTE, patch);
}
