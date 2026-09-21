import { afterEach, beforeEach, describe, expect, it } from "vitest";

import {
  buildOwnedMap,
  controllerConfiguratorAvailable,
  currentSteamId3,
  controllerIndex,
  libraryPort,
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

  it("ownedApps is null while the client's collection getter still throws", () => {
    g.collectionStore = {
      get allAppsCollection(): never {
        throw new TypeError("Cannot read properties of undefined (reading 'get')");
      },
    };
    expect(ownedApps()).toBeNull();
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
  const ps5 = { nControllerIndex: 1, eControllerType: 45 };
  let listCallback: ((controllers: unknown[]) => void) | null;
  let activeCallback: ((message: unknown) => void) | null;
  let unregistered: number;

  beforeEach(() => {
    sets = [];
    listCallback = null;
    activeCallback = null;
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
        RegisterForActiveControllerChanges: (cb: (message: unknown) => void) => {
          activeCallback = cb;
          return { unregister: () => unregistered++ };
        },
      },
      Apps: { ShowControllerConfigurator: (appid: number) => sets.push(["configurator", appid]) },
    };
  });
  afterEach(() => {
    // The watched list and active index are module state that only an
    // unregister clears: reset them here so a test that fails before its own
    // stop() cannot leak into the next one.
    watchControllers()();
    delete g.SteamClient;
    delete g.controllerStore;
    delete g.ControllerStore;
    delete g.appStore;
  });

  it("finds the Deck controller through controllerStore, by type, else through the list watch", () => {
    expect(controllerIndex()).toBeNull();
    g.controllerStore = { GetControllers: () => [xbox, deck] };
    expect(controllerIndex()).toBe(15);
    g.controllerStore = {
      GetControllers: () => [xbox, deck],
      GetControllerTypeString: (t: number) => (t === 4 ? "controller_steamcontroller_neptune" : "controller_xbox360"),
    };
    expect(controllerIndex()).toBe(15);
    g.controllerStore = { GetControllers: () => [xbox, ps5] };
    expect(controllerIndex()).toBeNull();
    delete g.controllerStore;
    const stop = watchControllers();
    listCallback!([xbox, deck]);
    expect(controllerIndex()).toBe(15);
    // an empty store list (the client rebuilding it) yields to the watched one
    g.controllerStore = { GetControllers: () => [] };
    expect(controllerIndex()).toBe(15);
    g.controllerStore = { GetControllers: () => { throw new Error("no store"); } };
    expect(controllerIndex()).toBe(15);
    delete g.controllerStore;
    listCallback!([xbox, ps5]);
    expect(controllerIndex()).toBeNull();
    stop();
    expect(unregistered).toBe(2);
  });

  it("reads the store under the ControllerStore spelling the probed client uses", () => {
    g.ControllerStore = { GetControllers: () => [xbox, deck] };
    expect(controllerIndex()).toBe(15);
  });

  it("without a Deck controller, copies for the only connected one, else the active one", () => {
    // PR-0 probe V1: a SteamOS box with one separate Steam Controller at index 0.
    const triton = { nControllerIndex: 0, eControllerType: 10 };
    g.ControllerStore = {
      GetControllers: () => [triton],
      GetControllerTypeString: () => "controller_steamcontroller_triton",
    };
    expect(controllerIndex()).toBe(0);
    g.ControllerStore = { GetControllers: () => [xbox, ps5] };
    expect(controllerIndex()).toBeNull();
    const stop = watchControllers();
    activeCallback!({ nActiveController: 1 });
    expect(controllerIndex()).toBe(1);
    // an active index that is not in the list (a stale one, nothing connected) is not used
    activeCallback!({ nActiveController: 7 });
    expect(controllerIndex()).toBeNull();
    // the Deck's own controller still wins over the active one
    activeCallback!({ nActiveController: 1 });
    g.ControllerStore = { GetControllers: () => [xbox, ps5, deck] };
    expect(controllerIndex()).toBe(15);
    stop();
    g.ControllerStore = { GetControllers: () => [xbox, ps5] };
    expect(controllerIndex()).toBeNull();
  });

  it("watchControllers tolerates a client without either registration", () => {
    // The probed client has no RegisterForControllerListChanges; calling it
    // unguarded would throw while the plugin loads.
    (g.SteamClient as { Input: Record<string, unknown> }).Input = {};
    const stop = watchControllers();
    expect(controllerIndex()).toBeNull();
    stop();
    expect(unregistered).toBe(0);
  });

  it("trusts GetControllerTypeString when the client has it, with no enum fallback", () => {
    // A controller that is not a Deck but whose eControllerType happens to be
    // 4. The enum fallback exists only for a client with no type-string call;
    // using it here would take an unrelated controller for the Deck's.
    const impostor = { nControllerIndex: 3, eControllerType: 4 };
    g.controllerStore = {
      GetControllers: () => [impostor, ps5],
      GetControllerTypeString: () => "controller_ps5",
    };
    expect(controllerIndex()).toBeNull();
    // the same list, on a client without the call, still falls back by enum
    g.controllerStore = { GetControllers: () => [impostor, ps5] };
    expect(controllerIndex()).toBe(3);
  });

  it("reads and sets selections through SteamClient.Input with the index and all five arguments", async () => {
    g.controllerStore = { GetControllers: () => [deck] };
    const input = steamInput();
    expect(input.controllerIndex()).toBe(15);
    expect(await input.getConfig(620, 15)).toEqual({ URL: "workshop://620", Title: "x" });
    expect(await input.getConfig(0x80000001, 15)).toBeNull();
    await input.setConfig(0x80000001, 15, "workshop://620");
    // the fifth argument is what makes the selection stick (PR-0 probe V2)
    expect(sets).toEqual([[0x80000001, 15, "workshop://620", false, 1]]);
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

describe("libraryPort (spec 3.15)", () => {
  const g = globalThis as Record<string, unknown>;
  afterEach(() => {
    delete g.collectionStore;
    delete g.appStore;
  });

  /** A user collection like the client's: apps by overview, edited through the drag-drop view. */
  function collection(name: string, log: string[]) {
    const apps: { appid: number }[] = [];
    return {
      displayName: name,
      get allApps() {
        return apps;
      },
      AsDragDropCollection: () => ({
        AddApps: (added: { appid: number }[]) => void apps.push(...added),
        RemoveApps: (removed: { appid: number }[]) => {
          for (const app of removed) apps.splice(apps.findIndex((a) => a.appid === app.appid), 1);
        },
      }),
      Save: async () => void log.push(`save ${name}`),
      Delete: async () => void log.push(`delete ${name}`),
    };
  }

  it("is inert on a client with no such calls", async () => {
    const port = libraryPort();
    expect(port.canHide()).toBe(false);
    expect(port.canCollect()).toBe(false);
    expect(port.isHidden(1)).toBeNull();
    expect(port.collectionApps("Streaming")).toBeNull();
    port.setHidden([1], true);
    await port.updateCollection("Streaming", [1], []);
    await port.deleteCollection("Streaming");
  });

  it("reads and sets hidden state through collectionStore", () => {
    const sets: [number[], boolean][] = [];
    g.collectionStore = {
      BIsHidden: (appid: number) => appid === 7,
      SetAppsAsHidden: (appids: number[], hidden: boolean) => void sets.push([appids, hidden]),
    };
    const port = libraryPort();
    expect(port.canHide()).toBe(true);
    expect(port.isHidden(7)).toBe(true);
    expect(port.isHidden(8)).toBe(false);
    port.setHidden([], true);
    port.setHidden([8, 9], true);
    expect(sets).toEqual([[[8, 9], true]]);
  });

  it("creates the collection, then adds and removes by overview, skipping what is not loaded", async () => {
    const log: string[] = [];
    const userCollections: ReturnType<typeof collection>[] = [];
    g.appStore = { GetAppOverviewByAppID: (appid: number) => (appid === 404 ? null : { appid }) };
    g.collectionStore = {
      userCollections,
      NewUnsavedCollection: (name: string) => {
        const made = collection(name, log);
        userCollections.push(made);
        return made;
      },
    };
    const port = libraryPort();
    expect(port.canCollect()).toBe(true);
    await port.updateCollection("Streaming", [404], []);
    expect(userCollections).toEqual([]); // nothing to put in it: not created
    await port.updateCollection("Streaming", [1, 2, 404], []);
    expect(port.collectionApps("Streaming")).toEqual([1, 2]);
    await port.updateCollection("Streaming", [3], [1]);
    expect(port.collectionApps("Streaming")).toEqual([2, 3]);
    expect(userCollections).toHaveLength(1);
    await port.deleteCollection("Streaming");
    expect(log.at(-1)).toBe("delete Streaming");
  });
});
