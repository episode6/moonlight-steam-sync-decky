/**
 * The updater's logic (update spec 3.4, 3.7): what GitHub says exists, what
 * is offered, and what Decky's installer is handed. Pure (hard rule 9): the
 * one request goes through a `NetPort` (`instance.tsx` wires it over
 * `@decky/api`'s no-CORS fetch), and the hand-off through `decky.ts`.
 *
 * Hard rule 12: download URLs are built from the constants below and a
 * validated tag, never taken from a response (`parseReleases` keeps none),
 * and nothing is offered without GitHub's sha256 of the zip.
 */

import { errorText, type Settings } from "./cli";
import type { InstallRequest } from "./decky";
import { dateText, relativeTime } from "./format";
import { pluginEnabled } from "./library";
import type { AppState } from "./state";
import { compareVersions, parseVersion, type Version } from "./version";

export const REPO = "episode6/moonlight-steam-sync-decky";
export const RELEASES_API = `https://api.github.com/repos/${REPO}/releases?per_page=100`;
export const DOWNLOAD_BASE = `https://github.com/${REPO}/releases/download`;
export const ASSET = "Moonlight-Sync.zip";
/** `plugin.json`'s name, the zip's folder. */
export const PLUGIN_NAME = "Moonlight Sync";
/**
 * The oldest release offered: an older one has no updater, so installing it
 * would leave `install.sh` as the only way forward (Decision U5).
 * [verify] at release time that the release carrying the updater is 0.12.0;
 * if it gets another number, change this in that release's PR.
 */
export const MIN_UPDATER_VERSION: Version = [0, 12, 0];
export const MIN_LOADER_VERSION: Version = [3, 0, 0];
/** Decky's install types 3 (downgrade) and 4 (overwrite) exist from this loader on. */
export const INSTALL_TYPES_LOADER_VERSION: Version = [3, 1, 0];
export const CHECK_MIN_INTERVAL_MS = 60_000;
export const NOTES_MAX_CHARS = 8000;
export const TAG_RE = /^[A-Za-z0-9._-]{1,100}$/;
export const RELEASE_TAG_RE = /^v(\d+)\.(\d+)\.(\d+)$/;
/** Decky's `PluginInstallType` per action (update spec 2.3). */
export const INSTALL_TYPE = { reinstall: 1, update: 2, downgrade: 3, switch: 4 } as const;

// ---------------------------------------------------------------------------
// the network seam

export interface HttpAnswer {
  status: number;
  /** Lower-case names; only the four the updater reads. `null` when absent. */
  headers: {
    "x-ratelimit-remaining": string | null;
    "x-ratelimit-reset": string | null;
    "retry-after": string | null;
    etag: string | null;
  };
  text: string;
}

export interface NetPort {
  /** One GET. Rejects when no answer came (offline, DNS, TLS). */
  get(url: string, headers: Record<string, string>): Promise<HttpAnswer>;
}

// ---------------------------------------------------------------------------
// types

export type UpdateAction = "update" | "reinstall" | "downgrade" | "switch";

export interface Release {
  /** `v0.12.0` */
  tag: string;
  /** Phase 2 adds `branch`. */
  kind: "release";
  /** `0.12.0` */
  version: string;
  /** ISO */
  publishedAt: string;
  /** The body, cut to `NOTES_MAX_CHARS`. */
  notes: string;
  size: number;
  /** 64 hex digits, lower case; `null` when GitHub gave none. */
  digest: string | null;
}

export interface Offer extends Release {
  action: UpdateAction;
  label: string;
}

export type CheckFailure = {
  ok: false;
  error: "rate-limited" | "network" | "bad-release";
  message: string;
  retryAt: string | null;
};

export type CheckResult = { ok: true; releases: Release[] } | CheckFailure;

/** `AppState["update"]` while the plugin is on. */
export interface UpdateInfo {
  /** The last successful check's releases; null before one. */
  releases: Release[] | null;
  /** ISO, of the last successful check. */
  checkedAt: string | null;
  /** The last check's failure. */
  error: CheckFailure | null;
}

export type UpdatePhase = "idle" | "checking" | "asking";

// ---------------------------------------------------------------------------
// versions

/** `version.ts`'s `parseVersion`, after a leading `v`. */
function versionOf(text: string | null | undefined): Version | null {
  if (typeof text !== "string") return null;
  return parseVersion(text.trim().replace(/^v/, ""));
}

/** *Check for updates automatically* (`settings.update_check`, update spec 3.3); absent reads as on. */
export function updateCheckEnabled(settings: Pick<Settings, "update_check"> | null | undefined): boolean {
  return settings?.update_check !== false;
}

/** Decky can install from a plugin: false only for a loader known to be older than 3.0.0. */
export function loaderSupported(loaderVersion: string | null | undefined): boolean {
  const loader = versionOf(loaderVersion);
  return loader === null || compareVersions(loader, MIN_LOADER_VERSION) >= 0;
}

/** Decky's install type for an action; 3 and 4 become 2 on a loader older than 3.1.0. */
export function installType(action: UpdateAction, loaderVersion: string | null | undefined): number {
  const type: number = INSTALL_TYPE[action];
  const loader = versionOf(loaderVersion);
  if (type > 2 && loader !== null && compareVersions(loader, INSTALL_TYPES_LOADER_VERSION) < 0) {
    return INSTALL_TYPE.update;
  }
  return type;
}

// ---------------------------------------------------------------------------
// the list of releases

const DIGEST_RE = /^sha256:([0-9a-fA-F]{64})$/;

function digestOf(value: unknown): string | null {
  if (typeof value !== "string") return null;
  const match = DIGEST_RE.exec(value);
  return match ? match[1].toLowerCase() : null;
}

function isObject(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

/**
 * The API's array of releases, as far as phase 1 needs it: a release that
 * is not a draft nor a prerelease, with a `vX.Y.Z` tag and the plugin's
 * zip; anything else is skipped without an error. Highest version first.
 * No URL from the response is kept.
 */
export function parseReleases(raw: unknown): Release[] {
  if (!Array.isArray(raw)) return [];
  const releases: [Version, Release][] = [];
  for (const item of raw) {
    if (!isObject(item) || item.draft !== false || item.prerelease !== false) continue;
    const tag = item.tag_name;
    if (typeof tag !== "string") continue;
    const match = RELEASE_TAG_RE.exec(tag);
    if (!match) continue;
    const assets = Array.isArray(item.assets) ? item.assets : [];
    const zip = assets.find((asset): asset is Record<string, unknown> => isObject(asset) && asset.name === ASSET);
    if (!zip) continue;
    const version: Version = [Number(match[1]), Number(match[2]), Number(match[3])];
    releases.push([
      version,
      {
        tag,
        kind: "release",
        version: version.join("."),
        publishedAt: typeof item.published_at === "string" ? item.published_at : "",
        notes: typeof item.body === "string" ? item.body.slice(0, NOTES_MAX_CHARS) : "",
        size: typeof zip.size === "number" && Number.isFinite(zip.size) ? zip.size : 0,
        digest: digestOf(zip.digest),
      },
    ]);
  }
  releases.sort((a, b) => compareVersions(b[0], a[0]));
  return releases.map(([, release]) => release);
}

/** A release asset's URL, from the constants and a checked tag (hard rule 12). */
export function assetUrl(tag: string, name: string): string {
  if (!TAG_RE.test(tag) || /^\.+$/.test(tag)) throw new Error(`not a release tag: ${JSON.stringify(tag)}`);
  return `${DOWNLOAD_BASE}/${tag}/${name}`;
}

const API_HEADERS = { Accept: "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28" };

/** When a rate-limited answer says to come back: `retry-after` seconds from now, else `x-ratelimit-reset`. */
function retryAtOf(answer: HttpAnswer, now: number): string | null {
  const after = Number(answer.headers["retry-after"]);
  if (answer.headers["retry-after"] !== null && Number.isFinite(after) && after >= 0) {
    return new Date(now + after * 1000).toISOString();
  }
  const reset = Number(answer.headers["x-ratelimit-reset"]);
  if (answer.headers["x-ratelimit-reset"] !== null && Number.isFinite(reset) && reset > 0) {
    return new Date(reset * 1000).toISOString();
  }
  return null;
}

/**
 * The one request of a check (update spec 3.4): the repository's releases,
 * unauthenticated. `now` (epoch ms) dates a `retry-after`.
 */
export async function checkReleases(net: NetPort, now: () => number = Date.now): Promise<CheckResult> {
  let answer: HttpAnswer;
  try {
    answer = await net.get(RELEASES_API, { ...API_HEADERS });
  } catch {
    return { ok: false, error: "network", message: "no answer from GitHub", retryAt: null };
  }
  if (answer.status === 200) {
    let raw: unknown;
    try {
      raw = JSON.parse(answer.text);
    } catch {
      raw = null;
    }
    if (Array.isArray(raw)) return { ok: true, releases: parseReleases(raw) };
    return { ok: false, error: "bad-release", message: "GitHub's answer was not a list of releases", retryAt: null };
  }
  const limited = answer.headers["x-ratelimit-remaining"] === "0" || answer.headers["retry-after"] !== null;
  if ((answer.status === 403 || answer.status === 429) && limited) {
    return {
      ok: false,
      error: "rate-limited",
      message: "GitHub is limiting requests",
      retryAt: retryAtOf(answer, now()),
    };
  }
  return { ok: false, error: "network", message: `GitHub answered ${answer.status}`, retryAt: null };
}

// ---------------------------------------------------------------------------
// what is offered

function actionFor(release: Version, installed: Version): UpdateAction {
  const order = compareVersions(release, installed);
  return order > 0 ? "update" : order < 0 ? "downgrade" : "reinstall";
}

/** Installable: a digest, and a version with the updater in it. */
function installableVersion(release: Release): Version | null {
  if (!release.digest) return null;
  const version = versionOf(release.version);
  return version && compareVersions(version, MIN_UPDATER_VERSION) >= 0 ? version : null;
}

/**
 * The highest installable release, as an `update`, when it is higher than
 * the installed version; `null` otherwise, and when the installed version
 * does not parse.
 */
export function offerOf(installed: string | null | undefined, releases: readonly Release[] | null): Offer | null {
  const current = versionOf(installed);
  if (!current || !releases) return null;
  let best: [Version, Release] | null = null;
  for (const release of releases) {
    const version = installableVersion(release);
    if (version && (!best || compareVersions(version, best[0]) > 0)) best = [version, release];
  }
  if (!best || compareVersions(best[0], current) <= 0) return null;
  return { ...best[1], action: "update", label: best[1].version };
}

/**
 * *Install another version*'s list: every installable release, each an
 * update, a reinstall or a downgrade of the installed version. Empty when
 * the installed version does not parse, since no action could be named.
 */
export function installable(installed: string | null | undefined, releases: readonly Release[] | null): Offer[] {
  const current = versionOf(installed);
  if (!current || !releases) return [];
  const offers: Offer[] = [];
  for (const release of releases) {
    const version = installableVersion(release);
    if (version) offers.push({ ...release, action: actionFor(version, current), label: release.version });
  }
  return offers;
}

/** What Decky's installer is handed for an offer (update spec 3.5); throws without a digest. */
export function installRequestOf(offer: Offer, loaderVersion: string | null | undefined): InstallRequest {
  if (!offer.digest) throw new Error(`${offer.tag} has no sha256`);
  return {
    artifact: assetUrl(offer.tag, ASSET),
    name: PLUGIN_NAME,
    version: offer.version,
    hash: offer.digest,
    installType: installType(offer.action, loaderVersion),
  };
}

// ---------------------------------------------------------------------------
// texts (update spec 3.7)

type UpdateState = Pick<AppState, "settings" | "cliVersion" | "update" | "updatePhase">;

/** The panel's *Update to …* row, or `null` when there is nothing to offer right now. */
export function updateRowView(state: UpdateState): { text: string; tag: string } | null {
  if (!pluginEnabled(state.settings) || !state.update || state.updatePhase !== "idle") return null;
  if (!loaderSupported(state.cliVersion?.loader_version)) return null;
  const offer = offerOf(state.cliVersion?.plugin_version, state.update.releases);
  return offer ? { text: `Update to ${offer.label}`, tag: offer.tag } : null;
}

/** *Installed*: the plugin's version. */
export function installedText(version: string | null | undefined): string {
  return version || "unknown";
}

/** *Latest*: what the last check found, or why it could not. */
export function latestText(update: UpdateInfo, phase: UpdatePhase, offer: Offer | null, now: Date = new Date()): string {
  if (phase === "checking") return "Checking…";
  if (update.error) {
    const text = errorText(update.error, now);
    return update.checkedAt ? `${text} · last checked ${relativeTime(update.checkedAt, now)}` : text;
  }
  if (!update.checkedAt) return "Not checked yet";
  const checked = `checked ${relativeTime(update.checkedAt, now)}`;
  if (offer) return `${offer.label} · released ${relativeTime(offer.publishedAt, now)} · ${checked}`;
  return `Up to date · ${checked}`;
}

/** An option of *Install another version*: `0.12.0 · 2026-10-01`, or `0.11.0 · reinstall`. */
export function versionLabel(offer: Offer): string {
  return offer.action === "reinstall" ? `${offer.label} · reinstall` : `${offer.label} · ${dateText(offer.publishedAt)}`;
}

/** The page's install button. */
export function installButtonText(offer: Offer, phase: UpdatePhase): string {
  return phase === "asking" ? "Waiting for Decky…" : `Update to ${offer.label}`;
}
