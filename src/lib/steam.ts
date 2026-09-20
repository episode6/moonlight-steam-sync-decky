/**
 * The Steam-client touchpoints (spec 3.9, 3.10): the owned-apps map, the
 * current user's steamid3, running a shortcut, shutting Steam down, the
 * running-app watch, and the Steam Input seam for the layout copy (read a
 * selection, set a selection, the index of the controller to copy for) plus
 * Steam's layout picker. Nothing here writes a Steam file: the plugin never
 * calls AddShortcut, RemoveShortcut, SetShortcutName, SetAppLaunchOptions,
 * SetAppHiddenState or SetCustomArtworkForApp.
 *
 * Only globals are used here (`SteamClient`, `collectionStore`, `appStore`,
 * `ControllerStore`, `App`), so this module imports nothing from `@decky/*`;
 * the pure helpers (`buildOwnedMap`, `steamId3FromSteam64`, and
 * `layouts.ts`'s `copyLayout` / `layoutControllerIndexFrom`) are unit-tested.
 */

import {
  CONFIG_SELECTION_USER,
  layoutControllerIndexFrom,
  type ControllerLike,
  type LayoutConfig,
  type SteamInput,
} from "./layouts";

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

/** The last list `RegisterForControllerListChanges` delivered (the fallback when the store is not a global). */
let lastControllers: ControllerLike[] | null = null;
/** The last `nActiveController` `RegisterForActiveControllerChanges` delivered. */
let activeController: number | null = null;

interface Unregisterable {
  unregister(): void;
}

/**
 * Keep `lastControllers` and `activeController` current from
 * `SteamClient.Input`. Either registration may be missing: the client the
 * PR-0 probes ran on has no `RegisterForControllerListChanges` at all, and
 * calling it unguarded would throw while the plugin loads. Returns the
 * unregister function.
 */
export function watchControllers(): () => void {
  const input = SteamClient.Input as unknown as Record<string, unknown>;
  const registrations: Unregisterable[] = [];
  const register = (name: string, callback: (message: unknown) => void) => {
    const fn = input[name];
    if (typeof fn !== "function") return;
    try {
      registrations.push((fn as (cb: (message: unknown) => void) => Unregisterable).call(input, callback));
    } catch {
      // a client that has the name but refuses the call: the store is still there
    }
  };
  register("RegisterForControllerListChanges", (controllers) => {
    lastControllers = Array.isArray(controllers) ? (controllers as ControllerLike[]) : null;
  });
  register("RegisterForActiveControllerChanges", (message) => {
    const index = (message as { nActiveController?: unknown } | null)?.nActiveController;
    activeController = typeof index === "number" ? index : null;
  });
  return () => {
    for (const registration of registrations) registration.unregister();
    lastControllers = null;
    activeController = null;
  };
}

/**
 * The controller whose layout is copied (`layoutControllerIndexFrom`): the
 * Deck's built-in one by type (spec 2.2; it is not 0), else the active or
 * only connected one; `null` with none. The store global is `ControllerStore`
 * on the client the PR-0 probes measured; `controllerStore` is the older
 * spelling.
 */
export function controllerIndex(): number | null {
  const store = (globals().ControllerStore ?? globals().controllerStore) as ControllerStoreLike | undefined;
  let listed: ControllerLike[] | null = null;
  try {
    listed = store?.GetControllers?.() ?? null;
  } catch {
    listed = null;
  }
  // Prefer a list that has something in it: `GetControllers()` can be empty
  // for a moment while the client rebuilds it (a dock, a client start), and
  // the watched list still names the controller then.
  const controllers = listed && listed.length ? listed : (lastControllers ?? listed);
  const typeString =
    typeof store?.GetControllerTypeString === "function" ? store.GetControllerTypeString.bind(store) : undefined;
  // The eControllerType fallback is for a client that has no
  // GetControllerTypeString at all (see DECK_CONTROLLER_TYPE). When the
  // client *does* have it, its answer is final: an unrelated controller
  // whose enum value happens to be 4 is never taken for the Deck's.
  return layoutControllerIndexFrom(controllers, typeString, activeController);
}

/** The Steam Input seam of `layouts.ts`, over `SteamClient.Input`. */
export function steamInput(): SteamInput {
  return {
    controllerIndex,
    async getConfig(appid, controllerIndex) {
      const config = (await SteamClient.Input.GetConfigForAppAndController(appid, controllerIndex)) as
        | LayoutConfig
        | null
        | undefined;
      return config ?? null;
    },
    async setConfig(appid, controllerIndex, url) {
      // Five arguments, as Steam's own configurator calls it: with four the
      // call returns normally and selects nothing (PR-0 probe V2). @decky/ui
      // still types the four-argument form.
      const set = SteamClient.Input.SetSelectedConfigForApp as unknown as (
        appid: number,
        controllerIndex: number,
        url: string,
        unknown: boolean,
        selectionType: number,
      ) => Promise<void>;
      await set.call(SteamClient.Input, appid, controllerIndex, url, false, CONFIG_SELECTION_USER);
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
