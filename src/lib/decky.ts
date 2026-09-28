/**
 * The Decky seam (update spec 3.5, 3.12.5): the one place that touches Decky
 * Loader's own globals (hard rule 12). Decky's installer is the websocket
 * route `utilities/install_plugin`, reached through the router Decky puts on
 * the window of the context plugin code runs in (update spec 2.3, 2.4); it
 * only stores the request and shows Decky's own dialog, whose OK is the
 * user's to press. This module never answers that dialog.
 *
 * What Decky is handed is always a zip the backend staged and verified
 * (`stage_update`, update spec 3.12.3), as a `file://` artifact: never a
 * URL. Decky removes the installed plugin before it compares the hash or
 * opens the zip (update spec 2.3), so only bytes already known to match the
 * hash and to be a build of this plugin ever reach it.
 *
 * Pure, globals only, like `steam.ts`: nothing here imports `@decky/*`, and
 * the scope the router is looked up on is a parameter, so vitest drives it
 * over plain objects. Nothing is imported from `updates.ts` either: the
 * allowlist below is spelled out here so it does not move when the
 * updater's constants do (`decky.test.ts` and `tests/test_hard_rules.py`
 * hold the spellings equal).
 */

/** Decky's install route (update spec 2.3): `(artifact, name, version, hash, install_type)`. */
export const INSTALL_ROUTE = "utilities/install_plugin";

/**
 * The only artifacts Decky is ever handed (update spec 3.12.5): `file://`
 * and an absolute path. Decky reads the rest of a `file://` artifact as a
 * path, raw (update spec 2.3), and skips its download and its store request
 * for it. No URL is accepted at all.
 */
export const FILE_ARTIFACT_PREFIX = "file:///";

/**
 * Where the backend stages a zip (`updates.staged_path`, update spec
 * 3.12.3): `<runtime dir>/update/staged/Moonlight-Sync-<first 12 hex digits
 * of its sha256>.zip`. Spelled here, not taken from the backend's answer;
 * `tests/test_hard_rules.py` holds the two spellings of the name equal.
 */
export const STAGED_DIR = "/update/staged/";
export const STAGED_FILE_PREFIX = "Moonlight-Sync-";
export const STAGED_FILE_SUFFIX = ".zip";
/** How many of the hash's first hex digits name the staged file. */
export const STAGED_HASH_DIGITS = 12;

/** `plugin.json`'s name, and the zip's top-level folder (update spec 2.3). */
export const INSTALL_NAME = "Moonlight Sync";

/**
 * A branch's name, as a branch build's version carries it: `updates.ts`'s
 * `REF_RE`, spelled here too so this module imports nothing from the
 * updater (`decky.test.ts` holds the two equal).
 */
export const REF_RE = /^[A-Za-z0-9._/-]{1,100}$/;

export interface InstallRequest {
  /**
   * `file://` and the staged zip's absolute path, raw:
   * `file:///…/update/staged/Moonlight-Sync-<first 12 of hash>.zip`.
   */
  artifact: string;
  /** Always `Moonlight Sync`. */
  name: string;
  /**
   * A release's version (`0.13.0`), or a branch build's `<version> (<ref> @
   * <first 7 of sha>)` (`updates.ts`'s `branchVersionText`). Never `dev`,
   * never empty.
   */
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

const HASH_RE = /^[0-9a-f]{64}$/;
/** A release's version, and a branch build's version part: no space, no slash, no control character. */
const VERSION_RE = /^[0-9A-Za-z.+-]{1,64}$/;
/** A branch build's version: `<version> (<ref> @ <7 lower-case hex digits>)`, each part checked on its own. */
const BRANCH_VERSION_RE = /^(\S+) \((\S+) @ ([0-9a-f]{7})\)$/;
/** No staged path has one: a C0 or C1 control character, DEL, a line or paragraph separator. */
function hasControl(text: string): boolean {
  for (let i = 0; i < text.length; i++) {
    const code = text.charCodeAt(i);
    if (code < 0x20 || (code >= 0x7f && code <= 0x9f) || code === 0x2028 || code === 0x2029) return true;
  }
  return false;
}

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
 * The artifact is exactly `file://` and an absolute path ending in
 * `/update/staged/Moonlight-Sync-<first 12 of hash>.zip`, the hash the
 * request's own (update spec 3.12.5). The path has no empty, `.` or `..`
 * step, no backslash, no control character, and no `?`, `#` or `%`: Decky
 * does not decode it, so nothing in it is a URL's. A space is allowed (the
 * runtime directory is `Moonlight Sync`'s).
 */
function artifactAllowed(artifact: string, hash: string): boolean {
  if (!artifact.startsWith(FILE_ARTIFACT_PREFIX)) return false;
  const path = artifact.slice("file://".length);
  if (/[\\?#%]/.test(path) || hasControl(path)) return false;
  const steps = path.slice(1).split("/");
  if (steps.some((step) => step === "" || step === "." || step === "..")) return false;
  const name = `${STAGED_FILE_PREFIX}${hash.slice(0, STAGED_HASH_DIGITS)}${STAGED_FILE_SUFFIX}`;
  return path.endsWith(`${STAGED_DIR}${name}`);
}

/** A version's number part: `VERSION_RE`, and never `dev` in any case. */
function versionPartAllowed(version: string): boolean {
  return VERSION_RE.test(version) && version.toLowerCase() !== "dev";
}

/**
 * A release's version, or exactly what `branchVersionText` builds: `<version>
 * (<ref> @ <first 7 of sha>)`, the ref of `REF_RE`'s characters.
 */
function versionAllowed(version: string): boolean {
  if (versionPartAllowed(version)) return true;
  const branch = BRANCH_VERSION_RE.exec(version);
  return branch !== null && versionPartAllowed(branch[1]) && REF_RE.test(branch[2]);
}

/**
 * Whether `request` may hand these values to Decky (update spec 3.5,
 * 3.12.5, hard rule 12): checked here whatever the caller already
 * guarantees. Each value is a plain string or number read once by the
 * caller.
 */
export function installAllowed(
  artifact: unknown,
  name: unknown,
  version: unknown,
  hash: unknown,
  installType: unknown,
): boolean {
  if (typeof hash !== "string" || !HASH_RE.test(hash)) return false;
  if (typeof artifact !== "string" || !artifactAllowed(artifact, hash)) return false;
  if (name !== INSTALL_NAME) return false;
  if (typeof version !== "string" || !versionAllowed(version)) return false;
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
