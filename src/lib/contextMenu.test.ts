import { describe, expect, it } from "vitest";

import { MENU_CLASS_METHOD, MODULE_MARKER, WRAPPER_PATTERN, findMenuClass, menuClassOf, wrappersOf } from "./contextMenu";

// The sources measured on a SteamOS device 2026-09-23 (webpack's minified
// names, verbatim): the wrapper, the positioning-options export and a
// neighbour from the same module. (The lookup keyed on
// `().appDetailsSpotlight` until 2026-09-23; that client has it in no
// component, these sources included.)
const WRAPPER_SOURCE = "function De(e){const t=(0,p.br)(),r=(0,J.$2)();return(0,n.jsx)(Fe,{navigator:t,instance:r,...e})}";
const OPTIONS_SOURCE = "function We(){return{bFitToWindow:!0,strClassName:(0,Q.A)(G().contextMenu,se().LibraryContextMenu)}}";
const OTHER_SOURCE = "function Re(e){switch(e){case s.Bl:case s.MT:case s.NF:case s.aL:return!0;default:return!1}}";

type AnyFunction = (...args: unknown[]) => unknown;

/** A function whose `toString()` is `source`, so the lookup reads it as the client's export. */
function withSource(source: string): AnyFunction {
  const fn = (): void => undefined;
  fn.toString = () => source;
  return fn;
}

const measuredModule = {
  uU: withSource(WRAPPER_SOURCE),
  k2: withSource(OTHER_SOURCE),
  zq: withSource(OPTIONS_SOURCE),
  aT: 3,
};

/** A stand-in for the class the wrapper renders, with the measured prototype. */
class MenuStandIn {
  GetTargetApps(): unknown[] {
    return [];
  }
  render(): unknown {
    return null;
  }
}

describe("wrappersOf (spec 3.16.5)", () => {
  it("finds the wrapper in the measured module", () => {
    expect(wrappersOf(measuredModule)).toEqual([measuredModule.uU]);
  });

  it("the markers match the measured sources", () => {
    expect(OPTIONS_SOURCE).toContain(MODULE_MARKER);
    expect(WRAPPER_SOURCE).toMatch(WRAPPER_PATTERN);
    expect(OTHER_SOURCE).not.toMatch(WRAPPER_PATTERN);
  });

  it("a minified name may carry $ or _", () => {
    expect("function De($){const t=(0,p.br)(),r=(0,J.$2)();return(0,n.jsx)(Fe,{navigator:t,instance:r,...$})}").toMatch(WRAPPER_PATTERN);
    expect("return(0,n.jsx)(Fe,{navigator:_t,instance:$r,...e$})").toMatch(WRAPPER_PATTERN);
  });

  it("lists every match in export order", () => {
    const second = withSource("function Ge(e){return(0,n.jsx)(Ke,{navigator:a,instance:b,...e})}");
    expect(wrappersOf({ ...measuredModule, second })).toEqual([measuredModule.uU, second]);
  });

  it("wants both the module marker and the wrapper", () => {
    expect(wrappersOf({ uU: measuredModule.uU })).toEqual([]);
    expect(wrappersOf({ zq: measuredModule.zq, k2: measuredModule.k2 })).toEqual([]);
  });

  it("is empty over a non-module and an empty module", () => {
    expect(wrappersOf(null)).toEqual([]);
    expect(wrappersOf(3)).toEqual([]);
    expect(wrappersOf({})).toEqual([]);
    expect(wrappersOf({ a: "text" })).toEqual([]);
  });

  it("a throwing getter hides only itself", () => {
    const module = { ...measuredModule };
    Object.defineProperty(module, "bad", {
      enumerable: true,
      get() {
        throw new Error("not loaded");
      },
    });
    expect(wrappersOf(module)).toEqual([measuredModule.uU]);
  });
});

describe("menuClassOf", () => {
  const wrapper = measuredModule.uU;

  it("is the rendered element's type when it is the menu class", () => {
    expect(menuClassOf(wrapper, () => ({ type: MenuStandIn, props: {} }))).toBe(MenuStandIn);
    expect(MENU_CLASS_METHOD).toBe("GetTargetApps");
  });

  it("is null when the render throws, gives no element, a host element or a function component", () => {
    expect(
      menuClassOf(wrapper, () => {
        throw new Error("hooks");
      }),
    ).toBeNull();
    expect(menuClassOf(wrapper, () => null)).toBeNull();
    expect(menuClassOf(wrapper, () => ({ type: "div", props: {} }))).toBeNull();
    expect(menuClassOf(wrapper, () => ({ type: () => null, props: {} }))).toBeNull();
  });

  it("is null for a class without the menu's method", () => {
    class Other {
      render(): unknown {
        return null;
      }
    }
    expect(menuClassOf(wrapper, () => ({ type: Other, props: {} }))).toBeNull();
  });
});

describe("findMenuClass", () => {
  it("tries each wrapper and takes the first that renders the menu class", () => {
    const other = withSource("other");
    const render = (component: AnyFunction): unknown => (component === measuredModule.uU ? { type: MenuStandIn, props: {} } : { type: "div", props: {} });
    expect(findMenuClass([other, measuredModule.uU], render)).toBe(MenuStandIn);
    expect(findMenuClass([other], render)).toBeNull();
    expect(findMenuClass([], render)).toBeNull();
  });
});
