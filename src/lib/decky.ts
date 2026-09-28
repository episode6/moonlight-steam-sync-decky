/**
 * The Decky seam (update spec 3.5): the one place that touches Decky
 * Loader's own globals (hard rule 12). Decky's installer is the websocket
 * route `utilities/install_plugin`, reached through the router Decky puts on
 * the window of the context plugin code runs in (update spec 2.3, 2.4); it
 * only stores the request and shows Decky's own dialog, whose OK is the
 * user's to press. This module never answers that dialog.
 *
 * Pure, globals only, like `steam.ts`: nothing here imports `@decky/*`, and
 * the scope the router is looked up on is a parameter, so vitest drives it
 * over plain objects. Nothing is imported from `updates.ts` either: the
 * allowlist below is spelled out here so it does not move when the
 * updater's constants do (`decky.test.ts` holds the two equal).
 */

/** Decky's install route (update spec 2.3): `(artifact, name, version, hash, install_type)`. */
export const INSTALL_ROUTE = "utilities/install_plugin";

/** The only URLs Decky is ever handed: this repository's release assets. */
export const RELEASE_URL_PREFIX = "https://github.com/episode6/moonlight-steam-sync-decky/releases/download/";

/** The one asset under a release tag Decky is handed: the plugin's zip. */
export const RELEASE_ASSET = "Moonlight-Sync.zip";

/** `plugin.json`'s name, and the zip's top-level folder (update spec 2.3). */
export const INSTALL_NAME = "Moonlight Sync";

export interface InstallRequest {
  /** A URL under `RELEASE_URL_PREFIX`: `<prefix><tag>/Moonlight-Sync.zip`. */
  artifact: string;
  /** Always `Moonlight Sync`. */
  name: string;
  /** Never `dev`, never empty. */
  version: string;
  /** The zip's sha256: 64 lower-case hex digits. */
  hash: string;
  /** Decky's `PluginInstallType`, 1 (reinstall) to 4 (overwrite). */
  installType: number;
}

export interface DeckyInstaller {
  /** Decky's websocket router is reachable and has `call`. */
  available(): boolean;
  /** Ask Decky to prompt for the install; false when it could not be asked. */
  request(req: InstallRequest): Promise<boolean>;
}

/** A tag as it may sit in the URL: `TAG_RE`'s characters, and not only dots. */
const URL_TAG_RE = /^[A-Za-z0-9._-]{1,100}$/;
const HASH_RE = /^[0-9a-f]{64}$/;
/** A version Decky can put in a path of its store request: no space, no slash, no control character. */
const VERSION_RE = /^[0-9A-Za-z.+-]{1,64}$/;

interface Router {
  call(route: string, ...args: unknown[]): unknown;
}

function routerOn(holder: unknown): Router | null {
  if (holder === null || (typeof holder !== "object" && typeof holder !== "function")) return null;
  const router = (holder as { DeckyBackend?: unknown }).DeckyBackend;
  if (router === null || (typeof router !== "object" && typeof router !== "function")) return null;
  return typeof (router as { call?: unknown }).call === "function" ? (router as Router) : null;
}

/**
 * Decky's router: `scope.DeckyBackend` (plugin code runs in
 * `SharedJSContext`, where it lives), else `scope.opener.DeckyBackend` (the
 * other windows only see it there). Every read is guarded: a getter that
 * throws reads as absent.
 */
function findRouter(scope: unknown): Router | null {
  try {
    const own = routerOn(scope);
    if (own) return own;
  } catch {
    // fall through to the opener
  }
  try {
    const opener = (scope as { opener?: unknown } | null | undefined)?.opener;
    return routerOn(opener);
  } catch {
    return null;
  }
}

/**
 * The artifact is exactly `<RELEASE_URL_PREFIX><tag>/Moonlight-Sync.zip`,
 * the tag of `TAG_RE`'s characters and not only dots. That shape already
 * leaves out `..`, `?`, `#`, `%`, a backslash, whitespace and every control
 * character; the spec's explicit checks stay on top of it.
 */
function artifactAllowed(artifact: string): boolean {
  if (!artifact.startsWith(RELEASE_URL_PREFIX)) return false;
  if (artifact.includes("..") || artifact.includes("?") || artifact.includes("#")) return false;
  const rest = artifact.slice(RELEASE_URL_PREFIX.length);
  const slash = rest.indexOf("/");
  if (slash < 0) return false;
  const tag = rest.slice(0, slash);
  if (!URL_TAG_RE.test(tag) || /^\.+$/.test(tag)) return false;
  return rest.slice(slash + 1) === RELEASE_ASSET;
}

/**
 * Whether `request` may hand these values to Decky (update spec 3.5, hard
 * rule 12): checked here whatever the caller already guarantees. Each
 * value is a plain string or number read once by the caller.
 */
export function installAllowed(
  artifact: unknown,
  name: unknown,
  version: unknown,
  hash: unknown,
  installType: unknown,
): boolean {
  if (typeof artifact !== "string" || !artifactAllowed(artifact)) return false;
  if (typeof hash !== "string" || !HASH_RE.test(hash)) return false;
  if (name !== INSTALL_NAME) return false;
  if (typeof version !== "string" || !VERSION_RE.test(version) || version.toLowerCase() === "dev") return false;
  if (typeof installType !== "number" || !Number.isInteger(installType)) return false;
  return installType >= 1 && installType <= 4;
}

export function deckyInstaller(scope: unknown = globalThis): DeckyInstaller {
  return {
    available: () => findRouter(scope) !== null,
    async request(req: InstallRequest): Promise<boolean> {
      // Each field read once, so what was checked is what is sent.
      let artifact: unknown, name: unknown, version: unknown, hash: unknown, installType: unknown;
      try {
        ({ artifact, name, version, hash, installType } = req);
      } catch {
        return false;
      }
      if (!installAllowed(artifact, name, version, hash, installType)) return false;
      const router = findRouter(scope);
      if (!router) return false;
      try {
        await router.call(INSTALL_ROUTE, artifact, name, version, hash, installType);
        return true;
      } catch {
        return false;
      }
    },
  };
}
