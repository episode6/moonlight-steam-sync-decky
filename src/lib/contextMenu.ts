/**
 * The library gear menu's lookup, the pure half (spec 3.16.5, Decision
 * 56): how the menu class is recognised among the client's webpack
 * modules, over plain exports and sources so vitest can run it against
 * the sources measured on a device. `src/routes/libraryContextMenu.tsx`
 * feeds it `findModuleChild` and `fakeRenderComponent` and patches the
 * class it finds.
 *
 * Measured on a SteamOS device 2026-09-23: the module has twelve exports,
 * the wrapper is `function De(e){const t=(0,p.br)(),r=(0,J.$2)();return
 * (0,n.jsx)(Fe,{navigator:t,instance:r,...e})}`, another export reads
 * `strClassName:(0,Q.A)(G().contextMenu,se().LibraryContextMenu)`, and
 * the class's prototype has `render`, `GetTargetApps`,
 * `ShowControllerConfig`, `BuildManageSubmenu`, `GetPrimaryActionMenuItem`
 * and reads the page from `this.props.overview`.
 */

/**
 * The source text that marks the menu's module: one of its exports (the
 * menu's positioning options) reads the `LibraryContextMenu` style class.
 * Measured on a SteamOS device 2026-09-23.
 */
export const MODULE_MARKER = ".LibraryContextMenu)";

/**
 * The wrapper component's body, in that module: it renders the menu class
 * with a `navigator` and an `instance` it read from hooks, spread over its
 * own props (`{navigator:t,instance:r,...e}` once minified). Measured with
 * the module marker.
 */
export const WRAPPER_PATTERN = /navigator:\w+,instance:\w+,\.\.\.\w+\}/;

/** A method the menu class has and no other component reached this way would: the class is checked for it before its `render` is patched. */
export const MENU_CLASS_METHOD = "GetTargetApps";

/** Any function: a module export, a component, a class. */
export type AnyFunction = (...args: unknown[]) => unknown;

/** The menu class as the route patch needs it: a `render` on its prototype to patch. */
export interface MenuClass {
  prototype: { render: () => unknown };
}

/** The function exports of a module, by name; a throwing getter on one export hides only itself. */
function functionExportsOf(module: unknown): Map<string, AnyFunction> {
  const found = new Map<string, AnyFunction>();
  if (typeof module !== "object" || module === null) return found;
  for (const name of Object.keys(module)) {
    try {
      const value = (module as Record<string, unknown>)[name];
      if (typeof value === "function") found.set(name, value as AnyFunction);
    } catch {
      continue;
    }
  }
  return found;
}

/**
 * The menu's wrapper component, pure over a module's exports: in a module
 * one function export of which carries `MODULE_MARKER`, the function
 * export whose source matches `WRAPPER_PATTERN`; else `null`.
 */
export function wrapperOf(module: unknown): (AnyFunction) | null {
  const functions = functionExportsOf(module);
  if (functions.size === 0) return null;
  const sources = new Map<string, string>();
  for (const [name, fn] of functions) {
    try {
      sources.set(name, fn.toString());
    } catch {
      continue;
    }
  }
  if (![...sources.values()].some((source) => source.includes(MODULE_MARKER))) return null;
  for (const [name, source] of sources) {
    if (WRAPPER_PATTERN.test(source)) return functions.get(name) ?? null;
  }
  return null;
}

/**
 * The menu class behind a wrapper: what the wrapper renders, when that is
 * a class with `render` and `MENU_CLASS_METHOD`; else `null`. `render`
 * fake-renders the wrapper (`fakeRenderComponent` in production).
 */
export function menuClassOf(wrapper: AnyFunction, render: (component: AnyFunction) => unknown): MenuClass | null {
  let element: unknown;
  try {
    element = render(wrapper);
  } catch {
    return null;
  }
  const type: unknown = (element as { type?: unknown } | null | undefined)?.type;
  if (typeof type !== "function") return null;
  const prototype = (type as { prototype?: Record<string, unknown> }).prototype;
  if (typeof prototype?.render !== "function" || typeof prototype[MENU_CLASS_METHOD] !== "function") return null;
  return type as unknown as MenuClass;
}
