/**
 * The Steam-client touchpoints (spec 3.9): the owned-apps map, the current
 * user's steamid3, running a shortcut, and shutting Steam down. No layout
 * code (that is PR-7), and nothing that writes a Steam file: the plugin never
 * calls AddShortcut, RemoveShortcut, SetShortcutName, SetAppLaunchOptions,
 * SetAppHiddenState or SetCustomArtworkForApp.
 *
 * Only globals are used here (`SteamClient`, `collectionStore`, `appStore`,
 * `App`), so this module imports nothing from `@decky/*`; the pure helpers
 * (`buildOwnedMap`, `steamId3FromSteam64`) are unit-tested.
 */

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
