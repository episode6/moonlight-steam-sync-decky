/**
 * The `/library` route patch (spec 3.17): the synthetic *Streaming* tab.
 * The library home renders its tab bar from a `tabs` array; this patch
 * finds that array in the route's render tree and appends one tab whose
 * content is `StreamingTab` over a built-in tab's grid (`tabs.ts` picks the
 * template). Written from `@decky/ui`'s primitives -- `afterPatch`,
 * `findInReactTree`, `wrapReactType`, `wrapReactClass` -- and nothing else.
 *
 * The tree between the route element and the tab bar is not known for this
 * client (none was measured before this was built), so the patch digs:
 * at each level it looks for a `tabs` array that holds a library grid; when
 * there is none it patches the render of the first component element in
 * that level's output and looks again there, a few levels deep at most.
 * Every patched type is cached (`WeakMap`, original -> patched) so the
 * client sees a stable component type and nothing remounts per render; a
 * class component is patched on a subclass of its own (`wrapReactClass`),
 * a memo / forwardRef on a copy (`wrapReactType`), so the original types
 * are never touched. The injection only ever touches a `tabs` array some
 * tab of which renders a collection (`isLibraryTabs`), never the Settings
 * pages' tab bar. Anything unexpected leaves the library untouched; the
 * patch never throws into Steam's render.
 */

import { routerHook } from "@decky/api";
import { afterPatch, findInReactTree, wrapReactClass, wrapReactType } from "@decky/ui";
import type { ReactElement } from "react";

import { StreamingTab } from "../components/StreamingTab";
import { streamingTabEnabled } from "../lib/library";
import { controller } from "../instance";
import { footerOf, hasStreamingTab, isLibraryTabs, STREAMING_TAB_ID, STREAMING_TAB_TITLE, templateOf, type TabLike } from "../lib/tabs";
import { ensureLibraryContextMenuPatched } from "./libraryContextMenu";
import type { TreeNode } from "./tree";

export const LIBRARY_ROUTE = "/library";

/** How many component levels below the route element the tab bar is looked for. */
const MAX_DIG = 4;


/** Add the tab to a library `tabs` array; `true` when the array is the library's (with or without a change). */
export function injectStreamingTab(tabs: unknown, enabled: boolean): boolean {
  if (!isLibraryTabs(tabs)) return false;
  const index = tabs.findIndex((tab) => tab?.id === STREAMING_TAB_ID);
  if (!enabled) {
    if (index >= 0) tabs.splice(index, 1);
    return true;
  }
  if (hasStreamingTab(tabs)) return true;
  const template = templateOf(tabs);
  if (!template) return true;
  tabs.push({
    id: STREAMING_TAB_ID,
    title: STREAMING_TAB_TITLE,
    content: <StreamingTab template={template} />,
    footer: footerOf(tabs),
  });
  return true;
}

let shapeReported = false;

/** The prop names of an element, `children` aside, for the console. */
function propNames(props: unknown): string {
  if (!props || typeof props !== "object") return "-";
  return Object.keys(props).filter((k) => k !== "children").join(",") || "-";
}

/**
 * Once per session, what the tab bar and its tabs look like on this client
 * (DEVICE-CHECKLIST §10): the injection is written against a guessed
 * shape, and a tab that is in the bar but cannot be reached (2026-09-22)
 * is told apart by these -- a tab key the built-in tabs have and ours
 * lacks, a template prop tied to its own tab, or the bar's `onShowTab`
 * never being asked for the Streaming tab (traced below).
 */
function reportShape(bar: TreeNode): void {
  if (shapeReported) return;
  shapeReported = true;
  const tabs = bar.props?.tabs as TabLike[];
  const builtIn = tabs.find((tab) => tab?.id !== STREAMING_TAB_ID) as object | undefined;
  const template = templateOf(tabs);
  console.info(
    `Moonlight Sync: library tabs found on ${typeName(bar.type)}: bar props [${propNames(bar.props)}], ` +
      `activeTab ${JSON.stringify(bar.props?.activeTab ?? null)}, ` +
      `a built-in tab has [${builtIn ? Object.keys(builtIn).join(",") : "-"}], ` +
      `template ${template ? typeName(template.type) : "-"} with props [${propNames(template?.props)}]`,
  );
}

/** original `onShowTab` -> the traced one, so the bar sees one stable callback per original. */
const tracedShowTab = new WeakMap<object, (...args: unknown[]) => unknown>();

/** Log every tab the bar asks its owner to show, so a skipped Streaming tab says whether it was ever asked for. */
function traceShowTab(bar: TreeNode): void {
  const props = bar.props as Record<string, unknown> | undefined;
  const original = props?.onShowTab;
  if (!props || typeof original !== "function") return;
  let traced = tracedShowTab.get(original);
  if (!traced) {
    const call = original as (...args: unknown[]) => unknown;
    traced = (...args: unknown[]) => {
      console.debug(`Moonlight Sync: library tabs, onShowTab(${JSON.stringify(args[0] ?? null)})`);
      return call(...args);
    };
    tracedShowTab.set(original, traced);
    tracedShowTab.set(traced, traced); // seen again on a re-render: left as is
  }
  props.onShowTab = traced;
}

function isComponentElement(node: TreeNode): boolean {
  const type = node?.type;
  if (typeof type === "function") return true;
  // memo / forwardRef objects, which wrapReactType unwraps
  return !!type && typeof type === "object" && ("render" in type || "type" in type);
}

/** original type -> patched type, one cache per level so a type seen at two depths is patched for each. */
const caches: WeakMap<object, unknown>[] = Array.from({ length: MAX_DIG + 1 }, () => new WeakMap());

/**
 * Look for the tab bar in `tree`; when it is not there yet, patch the first
 * component below and look in its output, `depth` levels down at most.
 */
function dig(tree: unknown, depth: number): void {
  const bar = findInReactTree(tree, (n: TreeNode) => Array.isArray(n?.props?.tabs)) as TreeNode | undefined;
  if (bar?.props) {
    if (injectStreamingTab(bar.props.tabs, streamingTabEnabled(controller.state.settings))) {
      reportShape(bar);
      traceShowTab(bar);
    }
    return;
  }
  if (depth >= MAX_DIG) return;
  const next = findInReactTree(tree, isComponentElement) as TreeNode | undefined;
  if (!next) return;
  patchType(next, depth + 1);
}

/** A component's name for the console, so a device report can say what the dig went through. */
function typeName(type: unknown): string {
  const t = type as { displayName?: unknown; name?: unknown; type?: unknown; render?: unknown } | null;
  if (!t) return String(type);
  if (typeof t.displayName === "string") return t.displayName;
  if (typeof t.name === "string" && t.name) return t.name;
  if (typeof t === "object") return typeName(t.render ?? t.type);
  return "anonymous";
}

/** Patch `node.type`'s render so its output is dug at `depth`, through the cache. */
function patchType(node: TreeNode, depth: number): void {
  const cache = caches[depth];
  const original = node.type as object;
  const cached = cache.get(original);
  if (cached) {
    node.type = cached;
    return;
  }
  // Once per type and depth (the cache misses only the first time), so the
  // §10 device check can report the path the dig took when no bar was found.
  console.debug(`Moonlight Sync: library tabs, digging through ${typeName(original)} at depth ${depth}`);
  const handler = (_args: unknown[], rendered: unknown) => {
    try {
      dig(rendered, depth);
    } catch (error) {
      console.warn("Moonlight Sync: could not patch the library tabs", error);
    }
    return rendered;
  };
  patchRender(node as Record<string, unknown>, "type", handler);
  cache.set(original, node.type);
}

type Handler = (args: unknown[], rendered: unknown) => unknown;

/**
 * Patch the render of the component at `holder[prop]`, whatever its kind:
 * a function component is wrapped in place, a class on a subclass of its
 * own, a memo / forwardRef object on a copy whose inner `type` / `render`
 * is patched the same way.
 */
function patchRender(holder: Record<string, unknown>, prop: string, handler: Handler): void {
  const target = holder[prop];
  if (typeof target === "function") {
    const proto = (target as { prototype?: { render?: unknown } }).prototype;
    if (proto && typeof proto.render === "function") {
      wrapReactClass(holder, prop);
      afterPatch((holder[prop] as { prototype: object }).prototype, "render", handler);
    } else {
      afterPatch(holder, prop, handler);
    }
  } else if (target && typeof target === "object") {
    // A memo / forwardRef another plugin already wrapped is handed back as
    // is (`__DECKY_WRAPPED`), so that patch lands on their copy and
    // outlives this plugin's unload; accepted, it only ever adds the tab.
    wrapReactType(holder, prop);
    const inner = holder[prop] as Record<string, unknown>;
    patchRender(inner, typeof inner.render === "function" ? "render" : "type", handler);
  }
}

const patchedProps = new WeakSet<object>();

interface RenderableChild {
  type?: unknown;
  props?: { renderFunc?: (...args: unknown[]) => ReactElement };
}

/** Install the route patch; the returned function removes it (`onDismount`). */
export function patchLibraryTabs(): () => void {
  const patch = routerHook.addPatch(LIBRARY_ROUTE, (route) => {
    try {
      // The gear menu's patch installs on the first library render, not at load.
      ensureLibraryContextMenuPatched();
      const child = route.children as RenderableChild | undefined;
      if (!child || typeof child !== "object") return route;
      if (child.props && typeof child.props.renderFunc === "function") {
        // a route like /library/app/:appid: the page comes out of renderFunc
        if (!patchedProps.has(child.props)) {
          patchedProps.add(child.props);
          afterPatch(child.props, "renderFunc", (_args: unknown[], rendered: unknown) => {
            try {
              dig(rendered, 0);
            } catch (error) {
              console.warn("Moonlight Sync: could not patch the library tabs", error);
            }
            return rendered;
          });
        }
      } else if (isComponentElement(child as TreeNode)) {
        patchType(child as TreeNode, 0);
      }
    } catch (error) {
      console.warn("Moonlight Sync: could not patch the library tabs", error);
    }
    return route;
  });
  return () => routerHook.removePatch(LIBRARY_ROUTE, patch);
}
