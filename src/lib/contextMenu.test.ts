import { describe, expect, it } from "vitest";

import { MENU_CLASS_METHOD, MODULE_MARKER, WRAPPER_PATTERN, menuClassOf, wrapperOf } from "./contextMenu";

// The sources measured on a SteamOS device 2026-09-23 (webpack's minified
// names, verbatim): the wrapper, the positioning-options export and a
// neighbour from the same module.
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

describe("wrapperOf (spec 3.16.5)", () => {
  it("finds the wrapper in the measured module", () => {
    expect(wrapperOf(measuredModule)).toBe(measuredModule.uU);
  });

  it("the markers match the measured sources", () => {
    expect(OPTIONS_SOURCE).toContain(MODULE_MARKER);
    expect(WRAPPER_SOURCE).toMatch(WRAPPER_PATTERN);
    expect(OTHER_SOURCE).not.toMatch(WRAPPER_PATTERN);
  });

  it("wants both the module marker and the wrapper", () => {
    expect(wrapperOf({ uU: measuredModule.uU })).toBeNull();
    expect(wrapperOf({ zq: measuredModule.zq, k2: measuredModule.k2 })).toBeNull();
  });

  it("is null over a non-module and an empty module", () => {
    expect(wrapperOf(null)).toBeNull();
    expect(wrapperOf(3)).toBeNull();
    expect(wrapperOf({})).toBeNull();
    expect(wrapperOf({ a: "text" })).toBeNull();
  });

  it("a throwing getter hides only itself", () => {
    const module = { ...measuredModule };
    Object.defineProperty(module, "bad", {
      enumerable: true,
      get() {
        throw new Error("not loaded");
      },
    });
    expect(wrapperOf(module)).toBe(measuredModule.uU);
  });

  it("the old marker is in no export any more", () => {
    // The lookup keyed on `().appDetailsSpotlight` until 2026-09-23; the
    // client has it in no component. This is what the measured module
    // looks like to that marker.
    const sources = Object.values(measuredModule).filter((v): v is AnyFunction => typeof v === "function");
    expect(sources.some((fn) => fn.toString().includes("().appDetailsSpotlight"))).toBe(false);
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
