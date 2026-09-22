/**
 * The library gear menu patch (spec 3.16.5, Decision 56): the context menu
 * a library page's gear button opens (the same component the library's
 * tiles open on a long press) gets one more item, *Use as Moonlight Sync
 * default layout*, on a real game that has a Stream entry and on the pages
 * of the plugin's own visible entries. Written from `@decky/ui`'s
 * primitives -- `findModuleChild`, `fakeRenderComponent`, `afterPatch`,
 * `findInReactTree`, `MenuItem` -- and nothing else.
 *
 * The client does not export the menu component by name. It is reached
 * through the function component that wraps it (the one whose source
 * reads the app-details spotlight class), rendered once with stubbed hooks
 * to get the element it returns, whose `type` is the menu class; its
 * `render` is then patched, and the handler appends the item to whatever
 * list of menu items the render returned, keyed so a re-render of the same
 * tree adds nothing twice. The item reads the store at render time (the
 * menu is rendered fresh each time it opens), so it needs no hook. Anything
 * unexpected -- the wrapper not found, a menu of another shape, a page
 * with no overview -- leaves the menu untouched; the patch never throws
 * into Steam's render. **[verify]**: the wrapper's marker and the menu's
 * shape are measured on no device yet.
 */

import { MenuItem, afterPatch, fakeRenderComponent, findInReactTree, findModuleChild } from "@decky/ui";
import type { ReactElement } from "react";

import { adoptAsDefault } from "../components/adoptDefault";
import { controller } from "../instance";
import { layoutStrategy, menuLayoutSourceOf } from "../lib/layouts";

/** The `key` of the injected item, so a re-render of an already patched menu adds nothing. */
const MENU_ITEM_KEY = "moonlight-sync-default-layout";

/** The source text every client so far has had in the wrapper component's body. */
const WRAPPER_MARKER = "().appDetailsSpotlight";

export const MENU_ITEM_LABEL = "Use as Moonlight Sync default layout";

interface Overview {
  appid: number;
  display_name?: string;
}

interface TreeNode {
  key?: string | null;
  type?: unknown;
  props?: Record<string, unknown> & { children?: unknown; overview?: unknown };
  _owner?: { pendingProps?: { overview?: unknown } } | null;
}

interface MenuClass {
  prototype: { render: () => unknown };
}

function isOverview(value: unknown): value is Overview {
  return typeof (value as Overview | null | undefined)?.appid === "number";
}

/** The menu class, reached through its wrapper component; `null` when this client has neither in the expected shape. */
export function findLibraryContextMenu(): MenuClass | null {
  const wrapper: unknown = findModuleChild((module: unknown) => {
    if (typeof module !== "object" || module === null) return undefined;
    for (const name of Object.keys(module)) {
      const value = (module as Record<string, unknown>)[name];
      if (typeof value === "function" && value.toString().includes(WRAPPER_MARKER)) return value;
    }
    return undefined;
  });
  if (typeof wrapper !== "function") return null;
  let element: unknown;
  try {
    element = fakeRenderComponent(wrapper);
  } catch {
    return null;
  }
  const type: unknown = (element as TreeNode | null | undefined)?.type;
  if (typeof type !== "function") return null;
  const candidate = type as unknown as Partial<MenuClass>;
  return typeof candidate.prototype?.render === "function" ? (candidate as MenuClass) : null;
}

/** The array of menu items in a rendered menu: the first children array that holds a `MenuItem`, else the root's. */
function menuItemsOf(rendered: unknown): unknown[] | null {
  const withItems = findInReactTree(
    rendered,
    (n: TreeNode) => Array.isArray(n?.props?.children) && n.props.children.some((c) => (c as TreeNode | null)?.type === MenuItem),
  ) as TreeNode | undefined;
  if (withItems) return withItems.props!.children as unknown[];
  const root = (rendered as TreeNode | null | undefined)?.props?.children;
  return Array.isArray(root) ? root : null;
}

/**
 * Append the item to a rendered menu for `overview`'s page; a no-op when
 * the page gets none (no Stream entry, the strategy is `picker`, the menu
 * is not the shape expected). `true` when the item is there afterwards.
 */
export function injectLayoutItem(rendered: unknown, overview: Overview | null): boolean {
  if (!overview) return false;
  const state = controller.state;
  if (layoutStrategy(state.settings) !== "copy") return false;
  const source = menuLayoutSourceOf(state.entries, state.streamMap, overview.appid);
  if (!source) return false;
  const items = menuItemsOf(rendered);
  if (!items) return false;
  const name = overview.display_name ?? String(overview.appid);
  const item: ReactElement = (
    <MenuItem key={MENU_ITEM_KEY} onSelected={() => void adoptAsDefault(source.appid, name, "gear-menu")}>
      {MENU_ITEM_LABEL}
    </MenuItem>
  );
  const at = items.findIndex((child) => (child as TreeNode | null)?.key === MENU_ITEM_KEY);
  if (at >= 0) items[at] = item;
  else items.push(item);
  return true;
}

/** The page's overview: the menu's own prop, else the owner's (a class's `render` has no args to read it from). */
function overviewOf(instance: { props?: { overview?: unknown } } | undefined, rendered: unknown): Overview | null {
  const own = instance?.props?.overview;
  if (isOverview(own)) return own;
  const owner = (rendered as TreeNode | null | undefined)?._owner?.pendingProps?.overview;
  return isOverview(owner) ? owner : null;
}

/** Install the menu patch; the returned function removes it (`onDismount`). On a client not recognised it only warns. */
export function patchLibraryContextMenu(): () => void {
  const menu = findLibraryContextMenu();
  if (!menu) {
    console.warn("Moonlight Sync: the library context menu was not found; no gear-menu item");
    return () => undefined;
  }
  const patch = afterPatch(menu.prototype, "render", function (this: { props?: { overview?: unknown } }, _args: unknown[], rendered: unknown) {
    try {
      injectLayoutItem(rendered, overviewOf(this, rendered));
    } catch (error) {
      console.warn("Moonlight Sync: could not patch the library context menu", error);
    }
    return rendered;
  });
  return () => patch.unpatch();
}
