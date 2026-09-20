/**
 * The Steam-client touchpoints (spec 3.9, 3.10): the owned-apps map, the
 * current user's steamid3, running a shortcut, shutting Steam down, the
 * running-app watch, and the Steam Input seam for the layout copy (read a
 * selection, set a selection, the Deck controller's index by type) plus
 * Steam's layout picker. Nothing here writes a Steam file: the plugin never
 * calls AddShortcut, RemoveShortcut, SetShortcutName, SetAppLaunchOptions,
 * SetAppHiddenState or SetCustomArtworkForApp.
 *
 * Only globals are used here (`SteamClient`, `collectionStore`, `appStore`,
 * `controllerStore`, `App`), so this module imports nothing from `@decky/*`;
 * the pure helpers (`buildOwnedMap`, `steamId3FromSteam64`, and
 * `layouts.ts`'s `copyLayout` / `deckControllerIndexFrom`) are unit-tested.
 */

import { deckControllerIndexFrom, type ControllerLike, type LayoutConfig, type SteamInput } from "./layouts";

/** The steam64 of account id 0 (`steam64 - this = steamid3`). */
export const STEAM64_BASE = 76561197960265728n;

/** The app types a Steam library entry may have to count as owned:
 * game (1), demo (8), beta (65536) -- spec 3.9. */
export const SUPPORTED_APP_TYPES: ReadonlySet<number> = new Set([1, 8, 65536]);

/** Non-Steam shortcuts live at and above this appid. */
export const SHORTCUT_APPID_FLOOR = 0x80000000;

/** The launch source `RunGame` takes for a library launch (spec 2.1, 3.9). */
const LAUNCH_SOURCE = 100;

export interface AppLike {
  appid: number;
  display_name: string;
  app_type: number;
}

/** `{ "<appid>": "<display name>" }` for the games, demos and betas the account owns. */
export function buildOwnedMap(apps: Iterable<AppLike>): Record<string, string> {
  const owned: Record<string, string> = {};
  for (const app of apps) {
    if (!app || typeof app.appid !== "number" || typeof app.display_name !== "string") continue;
    if (!SUPPORTED_APP_TYPES.has(app.app_type)) continue;
    if (app.appid <= 0 || app.appid >= SHORTCUT_APPID_FLOOR) continue;
    owned[String(app.appid)] = app.display_name;
  }
  return owned;
}

/** steam64 string -> steamid3 (account id); `null` for anything that is not a steam64. */
export function steamId3FromSteam64(steam64: string | null | undefined): number | null {
  if (!steam64 || !/^\d+$/.test(steam64)) return null;
  let value: bigint;
  try {
    value = BigInt(steam64);
  } catch {
    return null;
  }
  const id = value - STEAM64_BASE;
  if (id <= 0n || id > 0xffffffffn) return null;
  return Number(id);
}

interface CollectionStoreLike {
  allAppsCollection?: { allApps?: AppLike[] };
}

function globals(): Record<string, unknown> {
  return globalThis as unknown as Record<string, unknown>;
}

/**
 * The owned map from `collectionStore.allAppsCollection.allApps` **[verify V4]**,
 * or `null` while the library has not loaded (no store, or no apps yet).
 */
export function ownedApps(): Record<string, string> | null {
  const store = globals().collectionStore as CollectionStoreLike | undefined;
  const apps = store?.allAppsCollection?.allApps;
  if (!Array.isArray(apps) || apps.length === 0) return null;
  const owned = buildOwnedMap(apps);
  return Object.keys(owned).length ? owned : null;
}

/** The logged-in user's steamid3, derived from `App.m_CurrentUser.strSteamID`
 * (spec 3.9: `steamid3 = steam64 - 76561197960265728`). */
export function currentSteamId3(): number | null {
  const app = globals().App as { m_CurrentUser?: { strSteamID?: string } } | undefined;
  return steamId3FromSteam64(app?.m_CurrentUser?.strSteamID);
}

interface AppStoreLike {
  GetAppOverviewByAppID(appid: number): { gameid?: string } | null;
}

/**
 * Launch a (hidden) shortcut through Steam, so Steam owns the session:
 * `appStore.GetAppOverviewByAppID(appid).gameid` **[verify V5]** then
 * `SteamClient.Apps.RunGame(gameid, "", -1, 100)`. `false` when the
 * overview is not loaded.
 */
export function runShortcut(appid: number): boolean {
  const store = globals().appStore as AppStoreLike | undefined;
  const overview = store?.GetAppOverviewByAppID(appid);
  if (!overview?.gameid) return false;
  SteamClient.Apps.RunGame(overview.gameid, "", -1, LAUNCH_SOURCE);
  return true;
}

/** From Game Mode `StartShutdown(false)` is the restart: gamescope-session relaunches the client (spec 2.3). */
export function shutdownSteam(): void {
  SteamClient.User.StartShutdown(false);
}

/**
 * Track whether any app is running (the in-game guard, spec 3.9), via
 * `SteamClient.GameSessions.RegisterForAppLifetimeNotifications`. Returns the
 * unregister function.
 */
export function watchRunningApps(
  initial: readonly number[],
  onChange: (anyRunning: boolean) => void,
): () => void {
  const running = new Set(initial);
  onChange(running.size > 0);
  const registration = SteamClient.GameSessions.RegisterForAppLifetimeNotifications((n) => {
    if (n.bRunning) running.add(n.unAppID);
    else running.delete(n.unAppID);
    onChange(running.size > 0);
  });
  return () => registration.unregister();
}

// ---------------------------------------------------------------------------
// controller layouts (spec 3.10)

interface ControllerStoreLike {
  GetControllers?(): ControllerLike[];
  /** Steam's `EControllerType -> "controller_…"` mapping, when the store exposes it. */
  GetControllerTypeString?(type: number): string;
}

/** The last list `RegisterForControllerListChanges` delivered (the fallback when `controllerStore` is not a global). */
let lastControllers: ControllerLike[] | null = null;

/**
 * Keep `lastControllers` current from `SteamClient.Input.RegisterForControllerListChanges`,
 * so the Deck controller can be found even when `controllerStore` is not
 * exposed as a global. Returns the unregister function.
 */
export function watchControllers(): () => void {
  const registration = SteamClient.Input.RegisterForControllerListChanges((controllers) => {
    lastControllers = Array.isArray(controllers) ? (controllers as ControllerLike[]) : null;
  });
  return () => registration.unregister();
}

/** The Deck's built-in controller index, by type (spec 2.2; it is not 0), or `null`. */
export function deckControllerIndex(): number | null {
  const store = globals().controllerStore as ControllerStoreLike | undefined;
  let listed: ControllerLike[] | null = null;
  try {
    listed = store?.GetControllers?.() ?? null;
  } catch {
    listed = null;
  }
  const controllers = listed ?? lastControllers;
  const typeString = typeof store?.GetControllerTypeString === "function" ? store.GetControllerTypeString.bind(store) : undefined;
  return deckControllerIndexFrom(controllers, typeString) ?? deckControllerIndexFrom(controllers);
}

/** The Steam Input seam of `layouts.ts`, over `SteamClient.Input`. */
export function steamInput(): SteamInput {
  return {
    deckControllerIndex,
    async getConfig(appid, controllerIndex) {
      const config = (await SteamClient.Input.GetConfigForAppAndController(appid, controllerIndex)) as
        | LayoutConfig
        | null
        | undefined;
      return config ?? null;
    },
    async setConfig(appid, controllerIndex, url) {
      await SteamClient.Input.SetSelectedConfigForApp(appid, controllerIndex, url, false);
    },
  };
}

/** The shortcut list is loaded as far as this appid is concerned **[verify V5]**. */
export function overviewLoaded(appid: number): boolean {
  const store = globals().appStore as AppStoreLike | undefined;
  return !!store?.GetAppOverviewByAppID(appid);
}

interface AppsWithConfigurator {
  ShowControllerConfigurator?: (appid: number) => void;
}

/** `SteamClient.Apps.ShowControllerConfigurator` exists on this client **[verify]**. */
export function controllerConfiguratorAvailable(): boolean {
  const apps = (globals().SteamClient as { Apps?: AppsWithConfigurator } | undefined)?.Apps;
  return typeof apps?.ShowControllerConfigurator === "function";
}

/** Open Steam's layout picker for a (hidden) shortcut; `false` when the client has no such method. */
export function showControllerConfigurator(appid: number): boolean {
  if (!controllerConfiguratorAvailable()) return false;
  SteamClient.Apps.ShowControllerConfigurator(appid);
  return true;
}
