import { afterEach, beforeEach, describe, expect, it } from "vitest";

import {
  buildOwnedMap,
  controllerConfiguratorAvailable,
  currentSteamId3,
  deckControllerIndex,
  overviewLoaded,
  ownedApps,
  showControllerConfigurator,
  steamId3FromSteam64,
  steamInput,
  watchControllers,
} from "./steam";

describe("steamId3FromSteam64", () => {
  it("subtracts the steam64 base", () => {
    expect(steamId3FromSteam64("76561197960265729")).toBe(1);
    expect(steamId3FromSteam64("76561198012611406")).toBe(52345678);
    expect(steamId3FromSteam64(String(76561197960265728n + 12345678n))).toBe(12345678);
  });

  it("rejects anything that is not a steam64", () => {
    expect(steamId3FromSteam64(undefined)).toBeNull();
    expect(steamId3FromSteam64("")).toBeNull();
    expect(steamId3FromSteam64("0")).toBeNull();
    expect(steamId3FromSteam64("76561197960265728")).toBeNull();
    expect(steamId3FromSteam64("STEAM_0:1:1")).toBeNull();
    expect(steamId3FromSteam64("99999999999999999999")).toBeNull();
  });
});

describe("buildOwnedMap", () => {
  it("keeps games, demos and betas below the shortcut range", () => {
    expect(
      buildOwnedMap([
        { appid: 1245620, display_name: "ELDEN RING", app_type: 1 },
        { appid: 2379780, display_name: "Balatro", app_type: 1 },
        { appid: 400, display_name: "Portal Demo", app_type: 8 },
        { appid: 500, display_name: "A Beta", app_type: 65536 },
        { appid: 228980, display_name: "Steamworks Common Redistributables", app_type: 4 },
        { appid: 0x80000001, display_name: "A shortcut", app_type: 1073741824 },
        { appid: 0x80000002, display_name: "A shortcut typed as a game", app_type: 1 },
      ]),
    ).toEqual({
      "1245620": "ELDEN RING",
      "2379780": "Balatro",
      "400": "Portal Demo",
      "500": "A Beta",
    });
  });
});

describe("the globals", () => {
  const g = globalThis as Record<string, unknown>;
  afterEach(() => {
    delete g.collectionStore;
    delete g.App;
  });

  it("ownedApps is null until the library has loaded", () => {
    expect(ownedApps()).toBeNull();
    g.collectionStore = { allAppsCollection: { allApps: [] } };
    expect(ownedApps()).toBeNull();
    g.collectionStore = {
      allAppsCollection: { allApps: [{ appid: 620, display_name: "Portal 2", app_type: 1 }] },
    };
    expect(ownedApps()).toEqual({ "620": "Portal 2" });
  });

  it("currentSteamId3 reads App.m_CurrentUser", () => {
    expect(currentSteamId3()).toBeNull();
    g.App = { m_CurrentUser: { strSteamID: "76561197960265729" } };
    expect(currentSteamId3()).toBe(1);
  });
});

describe("the layout seam over the globals (spec 3.10)", () => {
  const g = globalThis as Record<string, unknown>;
  const deck = { nControllerIndex: 15, eControllerType: 4 };
  const xbox = { nControllerIndex: 0, eControllerType: 30 };
  let sets: unknown[][];
  let listCallback: ((controllers: unknown[]) => void) | null;
  let unregistered: number;

  beforeEach(() => {
    sets = [];
    listCallback = null;
    unregistered = 0;
    g.SteamClient = {
      Input: {
        GetConfigForAppAndController: async (appid: number) =>
          appid === 620 ? { URL: "workshop://620", Title: "x" } : undefined,
        SetSelectedConfigForApp: async (...args: unknown[]) => {
          sets.push(args);
        },
        RegisterForControllerListChanges: (cb: (controllers: unknown[]) => void) => {
          listCallback = cb;
          return { unregister: () => unregistered++ };
        },
      },
      Apps: { ShowControllerConfigurator: (appid: number) => sets.push(["configurator", appid]) },
    };
  });
  afterEach(() => {
    delete g.SteamClient;
    delete g.controllerStore;
    delete g.appStore;
  });

  it("finds the Deck controller through controllerStore, by type, else through the list watch", () => {
    expect(deckControllerIndex()).toBeNull();
    g.controllerStore = { GetControllers: () => [xbox, deck] };
    expect(deckControllerIndex()).toBe(15);
    g.controllerStore = {
      GetControllers: () => [xbox, deck],
      GetControllerTypeString: (t: number) => (t === 4 ? "controller_steamcontroller_neptune" : "controller_xbox360"),
    };
    expect(deckControllerIndex()).toBe(15);
    g.controllerStore = { GetControllers: () => [xbox] };
    expect(deckControllerIndex()).toBeNull();
    delete g.controllerStore;
    const stop = watchControllers();
    listCallback!([xbox, deck]);
    expect(deckControllerIndex()).toBe(15);
    listCallback!([xbox]);
    expect(deckControllerIndex()).toBeNull();
    stop();
    expect(unregistered).toBe(1);
  });

  it("reads and sets selections through SteamClient.Input with the Deck index and the false flag", async () => {
    g.controllerStore = { GetControllers: () => [deck] };
    const input = steamInput();
    expect(input.deckControllerIndex()).toBe(15);
    expect(await input.getConfig(620, 15)).toEqual({ URL: "workshop://620", Title: "x" });
    expect(await input.getConfig(0x80000001, 15)).toBeNull();
    await input.setConfig(0x80000001, 15, "workshop://620");
    expect(sets).toEqual([[0x80000001, 15, "workshop://620", false]]);
  });

  it("overviewLoaded asks appStore for the shortcut's overview", () => {
    expect(overviewLoaded(0x80000001)).toBe(false);
    g.appStore = { GetAppOverviewByAppID: (appid: number) => (appid === 0x80000001 ? { gameid: "1" } : null) };
    expect(overviewLoaded(0x80000001)).toBe(true);
    expect(overviewLoaded(0x80000002)).toBe(false);
  });

  it("opens Steam's layout picker only when the client has it", () => {
    expect(controllerConfiguratorAvailable()).toBe(true);
    expect(showControllerConfigurator(0x80000001)).toBe(true);
    expect(sets).toEqual([["configurator", 0x80000001]]);
    (g.SteamClient as { Apps: object }).Apps = {};
    expect(controllerConfiguratorAvailable()).toBe(false);
    expect(showControllerConfigurator(0x80000001)).toBe(false);
  });
});
