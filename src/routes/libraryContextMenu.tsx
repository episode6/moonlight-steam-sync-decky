/**
 * The library gear menu patch (spec 3.16.5, Decision 56): the context menu
 * a library page's gear button opens (the same component the library's
 * tiles open on a long press) gets one more item, *Use as Moonlight Sync
 * default layout*, on a real game that has a Stream entry and on the pages
 * of the plugin's own visible entries. Written from `@decky/ui`'s
 * primitives -- `findModuleChild`, `fakeRenderComponent`, `afterPatch`,
 * `findInReactTree`, `MenuItem` -- and nothing else.
 *
 * The client does not export the menu component by name. Its module is
 * the one with an export whose source reads the `LibraryContextMenu`
 * style class (the menu's positioning options), and in that module the
 * menu is reached through the function component that wraps it (a
 * one-liner that reads a navigator and an instance from hooks and renders
 * the class with those two props spread over its own), rendered once with
 * stubbed hooks to get the element it returns, whose `type` is the menu
 * class (measured on a SteamOS device 2026-09-23: its prototype has
 * `render`, `GetTargetApps`, `ShowControllerConfig`, `BuildManageSubmenu`
 * among others, and it reads the page from `this.props.overview`). Its
 * `render` is then patched, and the handler appends the item to whatever
 * list of menu items the render returned, keyed so a re-render of the same
 * tree adds nothing twice. The item reads the store at render time (the
 * menu is rendered fresh each time it opens), so it needs no hook.
 *
 * Until 2026-09-23 the wrapper was looked for by another marker
 * (`().appDetailsSpotlight`) that the current client has in no component
 * at all (it survives only as a field name of the app-data store), so the
 * lookup found nothing, warned once and the item never appeared.
 *
 * The lookup is a scan of every export of every module, so it does not
 * run at plugin load: `ensureLibraryContextMenuPatched()` runs it once,
 * the first time a library route renders (`libraryApp.tsx`,
 * `libraryTabs.tsx` call it from their route patches), which is the first
 * moment the menu can be opened anyway. It is one attempt: `@decky/ui`'s
 * module map is filled once when the library initialises and never sees
 * a chunk Steam loads later, so a retry through it would find nothing
 * new. Anything unexpected -- the wrapper not found, a menu of another
 * shape, a page with no overview -- leaves the menu untouched, and the
 * patch never throws into Steam's render. The markers, the menu class and
 * the `overview` prop are measured on a SteamOS device (2026-09-23); the
 * item in an open menu is a device check (DEVICE-CHECKLIST.md, *Adopt
 * from the gear menu*).
 */

import { MenuItem, afterPatch, fakeRenderComponent, findInReactTree, findModuleChild, type Patch } from "@decky/ui";
import type { ReactElement } from "react";

import { adoptAsDefault } from "../components/adoptDefault";
import { controller } from "../instance";
import { type AnyFunction, type MenuClass, findMenuClass, wrappersOf } from "../lib/contextMenu";
import { layoutStrategy, menuLayoutSourceOf } from "../lib/layouts";
import { pluginEnabled } from "../lib/library";
import { isOverview, type Overview, type TreeNode } from "./tree";

/** The `key` of the injected item, so a re-render of an already patched menu adds nothing. */
const MENU_ITEM_KEY = "moonlight-sync-default-layout";

export const MENU_ITEM_LABEL = "Use as Moonlight Sync default layout";

/** The menu class, reached through its module and wrapper component; `null` when this client has neither in the expected shape. */
export function findLibraryContextMenu(): MenuClass | null {
  const wrappers: unknown = findModuleChild((module: unknown) => {
    const found = wrappersOf(module);
    return found.length > 0 ? found : undefined;
  });
  if (!Array.isArray(wrappers)) return null;
  return findMenuClass(wrappers as AnyFunction[], (component) => fakeRenderComponent(component as Parameters<typeof fakeRenderComponent>[0]));
}

/**
 * The array of menu items in a rendered menu: the first children array
 * that holds a `MenuItem`. The fallback to the root's children array is a
 * safety net for a client whose items are not `@decky/ui`'s `MenuItem`
 * (that export is found by heuristics too); it is only as good as the
 * root being the item list, which the device check settles.
 */
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
 * the page gets none (no Stream entry, the strategy is `picker`, the
 * plugin is off (spec 3.19), the menu is not the shape expected). `true`
 * when the item is there afterwards.
 */
export function injectLayoutItem(rendered: unknown, overview: Overview | null): boolean {
  if (!overview) return false;
  const state = controller.state;
  if (!pluginEnabled(state.settings) || layoutStrategy(state.settings) !== "copy") return false;
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

interface MenuProps {
  overview?: unknown;
  appid?: unknown;
}

/**
 * The page the menu is for, from the menu's own props: `overview` as the
 * app-details component has it, else a bare `appid` (the name then falls
 * back to the number in the toasts). A class's `render` has no args, and
 * the element's `_owner` is this same instance, so there is nowhere else
 * to read it from.
 */
export function overviewOf(props: MenuProps | undefined): Overview | null {
  if (isOverview(props?.overview)) return props.overview;
  return typeof props?.appid === "number" ? { appid: props.appid } : null;
}

/** The render patch, once installed; `attempted` stops a second scan when the first found nothing. */
let installed: Patch | null = null;
let attempted = false;

/**
 * Patch the menu class's `render` if it has not been tried yet: one scan,
 * at the first library route render. `true` while the patch is in place.
 */
export function ensureLibraryContextMenuPatched(): boolean {
  if (installed) return true;
  if (attempted) return false;
  attempted = true;
  const menu = findLibraryContextMenu();
  if (!menu) {
    console.warn("Moonlight Sync: the library context menu was not found; no gear-menu item");
    return false;
  }
  installed = afterPatch(menu.prototype, "render", function (this: { props?: MenuProps }, _args: unknown[], rendered: unknown) {
    try {
      injectLayoutItem(rendered, overviewOf(this?.props));
    } catch (error) {
      console.warn("Moonlight Sync: could not patch the library context menu", error);
    }
    return rendered;
  });
  return true;
}

/**
 * Arm the menu patch (it installs on the first library route render); the
 * returned function removes it (`onDismount`) and lets a reload try again.
 */
export function patchLibraryContextMenu(): () => void {
  attempted = false;
  return () => {
    const patch = installed;
    installed = null;
    attempted = false;
    try {
      patch?.unpatch();
    } catch (error) {
      console.warn("Moonlight Sync: could not unpatch the library context menu", error);
    }
  };
}
