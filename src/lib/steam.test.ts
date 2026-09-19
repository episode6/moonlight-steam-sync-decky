import { afterEach, describe, expect, it } from "vitest";

import { buildOwnedMap, currentSteamId3, ownedApps, steamId3FromSteam64 } from "./steam";

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
