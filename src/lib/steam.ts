/**
 * The Steam-client touchpoints (spec 3.9, 3.10): the owned-apps map, the
 * current user's steamid3, running a shortcut, shutting Steam down, the
 * running-app watch, and the Steam Input seam for the layout copy (read a
 * selection, set a selection, the index of the controller to copy for) plus
 * Steam's layout picker. Nothing here writes a Steam file: the plugin never
 * calls AddShortcut, RemoveShortcut, SetShortcutName, SetAppLaunchOptions
 * or SetCustomArtworkForApp. The one thing it does change in the client is
 * `libraryPort()` below (spec 3.15): the hidden state of the CLI's entries
 * and the *Streaming* collection, both through `collectionStore`, because
 * the client ignores `IsHidden` in `shortcuts.vdf`.
 *
 * Only globals are used here (`SteamClient`, `collectionStore`, `appStore`,
 * `ControllerStore`, `App`), so this module imports nothing from `@decky/*`;
 * the pure helpers (`buildOwnedMap`, `steamId3FromSteam64`, and
 * `layouts.ts`'s `applyDefault` / `layoutControllerIndexFrom`) are unit-tested.
 */

import {
  CONFIG_SELECTION_USER,
  layoutControllerIndexFrom,
  type ControllerLike,
  type LayoutConfig,
  type SteamInput,
} from "./layouts";
import type { LibraryPort } from "./library";

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

/** A user collection, as far as `libraryPort()` uses it. */
interface CollectionLike {
  displayName?: string;
  allApps?: AppLike[];
  AsDragDropCollection?(): { AddApps(apps: unknown[]): void; RemoveApps(apps: unknown[]): void };
  Save?(): Promise<unknown>;
  Delete?(): Promise<unknown>;
}

interface CollectionStoreLike {
  allAppsCollection?: { allApps?: AppLike[] };
  userCollections?: CollectionLike[];
  NewUnsavedCollection?(name: string, filter: undefined, apps: unknown[]): CollectionLike | undefined;
  BIsHidden?(appid: number): boolean;
  SetAppsAsHidden?(appids: number[], hidden: boolean): void;
}

function globals(): Record<string, unknown> {
  return globalThis as unknown as Record<string, unknown>;
}

/**
 * The owned map from `collectionStore.allAppsCollection.allApps` **[verify V4]**,
 * or `null` while the library has not loaded (no store, or no apps yet).
 * Early in the client's boot the `allAppsCollection` getter itself throws
 * (its collections are not initialised yet); that is "not loaded" too, so
 * the caller's poll goes on instead of the load order dying.
 */
export function ownedApps(): Record<string, string> | null {
  const store = globals().collectionStore as CollectionStoreLike | undefined;
  let apps: AppLike[] | undefined;
  try {
    apps = store?.allAppsCollection?.allApps;
  } catch {
    return null;
  }
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
 * calling it unguarded would throw while the plugin loads.
 * `RegisterForActiveControllerChanges` delivers the current index as soon as
 * it is registered (measured there, no pad switch needed), so no separate
 * initial read is made. Returns the unregister function.
 */
export function watchControllers(): () => void {
  const input = SteamClient.Input as unknown as Record<string, unknown>;
  const registrations: Unregisterable[] = [];
  const register = (name: string, callback: (message: unknown) => void) => {
    const fn = input[name];
    if (typeof fn !== "function") return;
    try {
      registrations.push((fn as (cb: (message: unknown) => void) => Unregisterable).call(input, callback));
    } catch (error) {
      // A client that has the name but refuses the call: the store is still
      // there. Said out loud, so the loader log shows it without a probe run.
      console.warn(`Moonlight Sync: SteamClient.Input.${name} failed`, error);
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

interface InputWithClear {
  ClearSelectedConfigForApp?: (appid: number, controllerIndex: number) => Promise<void> | void;
}

/** `SteamClient.Input.ClearSelectedConfigForApp` exists on this client **[verify, DEVICE-CHECKLIST]**. */
export function clearConfigAvailable(): boolean {
  const input = (globals().SteamClient as { Input?: InputWithClear } | undefined)?.Input;
  return typeof input?.ClearSelectedConfigForApp === "function";
}

/**
 * The Steam Input seam of `layouts.ts`, over `SteamClient.Input`.
 * `clearConfig` is only there when the client has
 * `ClearSelectedConfigForApp` (its name and two arguments are unmeasured,
 * spec 3.16.3): without it the default can still be cleared, and titles
 * keep the layout they have.
 */
export function steamInput(): SteamInput {
  const input: SteamInput = {
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
  if (clearConfigAvailable()) {
    input.clearConfig = async (appid, controllerIndex) => {
      const clear = (SteamClient.Input as unknown as InputWithClear).ClearSelectedConfigForApp!;
      await clear.call(SteamClient.Input, appid, controllerIndex);
    };
  }
  return input;
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

// ---------------------------------------------------------------------------
// hidden state and the Streaming collection (spec 3.15)

function collections(): CollectionStoreLike | undefined {
  return globals().collectionStore as CollectionStoreLike | undefined;
}

function findCollection(name: string): CollectionLike | null {
  try {
    return collections()?.userCollections?.find((c) => c?.displayName === name) ?? null;
  } catch {
    return null;
  }
}

/** The overviews `AddApps` / `RemoveApps` take; an appid the client has not loaded is left out. */
function overviews(appids: readonly number[]): unknown[] {
  const store = globals().appStore as AppStoreLike | undefined;
  return appids.map((appid) => store?.GetAppOverviewByAppID(appid)).filter((overview) => !!overview);
}

/**
 * `library.ts`'s port over `collectionStore` **[verify on device]**. Every
 * method is a no-op (or `null`) on a client without the call it needs, so a
 * client update can only switch the feature off, never break the load.
 */
export function libraryPort(): LibraryPort {
  return {
    canHide: () => typeof collections()?.SetAppsAsHidden === "function",
    isHidden(appid) {
      const store = collections();
      if (typeof store?.BIsHidden !== "function") return null;
      try {
        return !!store.BIsHidden(appid);
      } catch {
        return null;
      }
    },
    setHidden(appids, hidden) {
      const store = collections();
      if (!appids.length || typeof store?.SetAppsAsHidden !== "function") return;
      store.SetAppsAsHidden([...appids], hidden);
    },
    canCollect: () => typeof collections()?.NewUnsavedCollection === "function",
    collectionApps(name) {
      const apps = findCollection(name)?.allApps;
      return Array.isArray(apps) ? apps.map((app) => app.appid) : null;
    },
    async updateCollection(name, add, remove) {
      let collection = findCollection(name);
      const adding = overviews(add);
      if (!collection) {
        if (!adding.length) return;
        collection = collections()?.NewUnsavedCollection?.(name, undefined, []) ?? null;
        if (!collection) return;
        // Saved once empty, on the assumption that a collection only takes
        // apps once it has an id **[verify on device]**.
        await collection.Save?.();
      }
      const edit = collection.AsDragDropCollection?.();
      if (!edit) return;
      if (adding.length) edit.AddApps(adding);
      const removing = overviews(remove);
      if (removing.length) edit.RemoveApps(removing);
      await collection.Save?.();
    },
    async deleteCollection(name) {
      await findCollection(name)?.Delete?.();
    },
  };
}
