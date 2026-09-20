/**
 * The `/library/app/:appid` route patch (spec 3.9): every owned game's
 * library page gets a `StreamButton`, which renders only while the stream
 * map has that appid. Written from `@decky/ui`'s primitives -- `afterPatch`
 * on the route's render function, `findInReactTree` for the page's overview
 * and its inner container -- and nothing else.
 *
 * What it does per render of the page: read `overview.appid` out of the
 * rendered tree, find the app-details inner container (the column holding
 * the header, the play bar and the sections), and splice the button row in
 * right after the header. Anything unexpected in the tree (another client
 * version, a page still loading) leaves the page untouched; the patch never
 * throws into Steam's render.
 */

import { routerHook } from "@decky/api";
import { afterPatch, appDetailsClasses, findInReactTree } from "@decky/ui";
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
  props?: Record<string, unknown> & { children?: unknown; className?: unknown; overview?: unknown };
}

function overviewOf(tree: unknown): Overview | null {
  const node = findInReactTree(tree, (n: TreeNode) => typeof (n?.props?.overview as Overview | undefined)?.appid === "number") as
    | TreeNode
    | undefined;
  const overview = node?.props?.overview as Overview | undefined;
  return overview && typeof overview.appid === "number" ? overview : null;
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

/** Add the Stream row to one rendered page; a no-op when the tree is not the shape expected. */
export function injectStreamRow(rendered: unknown): boolean {
  const overview = overviewOf(rendered);
  // Only real Steam apps get a button; a shortcut's own page never does.
  if (!overview || overview.appid <= 0 || overview.appid >= SHORTCUT_APPID_FLOOR) return false;
  const container = innerContainerOf(rendered);
  if (!container) return false;
  const children = container.props.children;
  if (children.some((child) => (child as TreeNode | null)?.key === STREAM_ROW_KEY)) return true;
  children.splice(1, 0, <StreamButton key={STREAM_ROW_KEY} appid={overview.appid} name={overview.display_name} />);
  return true;
}

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
        injectStreamRow(rendered);
      } catch (error) {
        console.warn("Moonlight Sync: could not patch the library page", error);
      }
      return rendered;
    });
    return route;
  });
  return () => routerHook.removePatch(LIBRARY_APP_ROUTE, patch);
}
