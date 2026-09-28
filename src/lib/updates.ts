/**
 * The updater's logic (update spec 3.4, 3.7, 3.12.4): what GitHub says
 * exists, what is offered on the selected channel, and what Decky's
 * installer is handed once the backend has staged the zip (update spec
 * 3.12.5). Pure (hard rule 9): the requests go through a `NetPort`
 * (`instance.tsx` wires it over `@decky/api`'s no-CORS fetch), the download
 * is the backend's `stage_update`, and the hand-off goes through `decky.ts`.
 *
 * Hard rule 12: download URLs are built from the constants below and a
 * validated tag, never taken from a response (`parseReleases` keeps none),
 * and nothing is offered without GitHub's sha256 of the zip. This file (and
 * its test) is the only one under `src/` that spells a download URL, and
 * Decky is never handed one.
 */

import { errorText, type BuildInfo, type CliVersion, type Settings, type StagedUpdate, type UpdateChannel } from "./cli";
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
 * 0.12.0 is the first release that carries the updater.
 */
export const MIN_UPDATER_VERSION: Version = [0, 12, 0];
export const MIN_LOADER_VERSION: Version = [3, 0, 0];
/** Decky's install types 3 (downgrade) and 4 (overwrite) exist from this loader on. */
export const INSTALL_TYPES_LOADER_VERSION: Version = [3, 1, 0];
export const CHECK_MIN_INTERVAL_MS = 60_000;
export const NOTES_MAX_CHARS = 8000;
export const TAG_RE = /^[A-Za-z0-9._-]{1,100}$/;
export const RELEASE_TAG_RE = /^v(\d+)\.(\d+)\.(\d+)$/;
/**
 * A branch's name as `build.json` and `update_channel` carry it (update spec
 * 3.12.1): the backend's `updates.REF_RE`, spelled alike
 * (`tests/test_hard_rules.py` holds the two, and `TAG_RE`, equal).
 */
export const REF_RE = /^[A-Za-z0-9._/-]{1,100}$/;
/** A branch's rolling prerelease is tagged `build-<slug>` (update spec 3.12.2). */
export const BUILD_TAG_PREFIX = "build-";
/** The asset a branch's release names its build in, uploaded last (update spec 3.12.2). */
export const BUILD_ASSET = "build.json";
/** The longest `build.json` answer read, in UTF-8 bytes; a real one is under 300. */
export const BUILD_MAX_BYTES = 64 * 1024;
export const STABLE_CHANNEL = "stable";
export const BRANCH_CHANNEL_PREFIX = "branch:";
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
    /** Carried for a conditional request later; nothing reads it yet (an unauthenticated 304 still costs a request, update spec 2.5). */
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

/** A published release, `vX.Y.Z`. */
export interface StableRelease {
  /** `v0.12.0` */
  tag: string;
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

/**
 * A branch's rolling build (update spec 3.12.2 / 3.12.4): the prerelease
 * `build-<slug>`. It has no version of its own (the zip carries the last
 * release's number, hard rule 8) and is kept only with a digest.
 */
export interface BranchBuild {
  /** `build-main` */
  tag: string;
  kind: "branch";
  /** The branch's name: the release's title when it is a ref, else the tag without `build-`. */
  ref: string;
  version: null;
  /** ISO, the zip asset's `updated_at`: when this build's zip was uploaded. */
  updatedAt: string;
  /** ISO, when the rolling release was first published. */
  publishedAt: string;
  /** The body, cut to `NOTES_MAX_CHARS`. */
  notes: string;
  size: number;
  /** 64 hex digits, lower case; never `null` (an entry without one is not kept). */
  digest: string;
  /**
   * The release's `build.json`, fetched by `checkReleases` for the selected
   * channel's entry only; `null` until then, and when it could not be read
   * (a branch being republished has none, update spec 8 A3).
   */
  build: BuildInfo | null;
}

export type Release = StableRelease | BranchBuild;

export type Offer = Release & { action: UpdateAction; label: string };

/** What is installed, as `cli_version()` says: `plugin_version` and `build`. */
export interface Installed {
  version: string | null | undefined;
  /** The installed zip's `build.json`; `null` for a release without one. */
  build: BuildInfo | null | undefined;
}

/** A *Channel* option (update spec 3.12.4); `updatedAt` is the branch build's, when there is one. */
export interface ChannelOption {
  id: UpdateChannel;
  label: string;
  updatedAt?: string;
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

/**
 * What the updater is doing (update spec 3.6, 3.12.5): `checking` GitHub,
 * `downloading` (the backend stages the zip), `asking` Decky.
 */
export type UpdatePhase = "idle" | "checking" | "downloading" | "asking";

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

/**
 * The branch a channel follows, or `null` for `stable` and for anything
 * that is not a channel (`"branch:"`, `"nightly"`, a ref outside `REF_RE`,
 * whitespace around it): such a value reads as `stable` everywhere.
 */
export function channelRef(channel: string | null | undefined): string | null {
  if (typeof channel !== "string" || !channel.startsWith(BRANCH_CHANNEL_PREFIX)) return null;
  const ref = channel.slice(BRANCH_CHANNEL_PREFIX.length);
  return REF_RE.test(ref) ? ref : null;
}

/**
 * The selected channel (`settings.update_channel`, update spec 3.12.4);
 * absent, unread or not a channel reads as `stable` (the backend refuses to
 * store one that is not, so that is only a hand-broken file). Every caller
 * reads the channel through this.
 */
export function channelOf(settings: Pick<Settings, "update_channel"> | null | undefined): UpdateChannel {
  const ref = channelRef(settings?.update_channel);
  return ref === null ? STABLE_CHANNEL : `${BRANCH_CHANNEL_PREFIX}${ref}`;
}

/** What `cli_version()` says is installed; `null` before it answered. */
export function installedOf(info: Pick<CliVersion, "plugin_version" | "build"> | null | undefined): Installed | null {
  return info ? { version: info.plugin_version, build: info.build ?? null } : null;
}

/** The installed zip is a branch's build: its `build.json` says `kind: "branch"` (a `release` one is a release). */
function branchBuildOf(installed: Installed | null): BuildInfo | null {
  const build = installed?.build;
  return build && build.kind === "branch" ? build : null;
}

/** `main @ abc1234`: a build's ref and the first 7 digits of its commit. */
function buildLabel(build: Pick<BuildInfo, "ref" | "sha">): string {
  return `${build.ref} @ ${build.sha.toLowerCase().slice(0, 7)}`;
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

function stringOr(value: unknown, fallback: string): string {
  return typeof value === "string" ? value : fallback;
}

/** When an ISO time was, for ordering; a missing or broken one is the oldest. */
function timeOf(iso: string): number {
  const time = Date.parse(iso);
  return Number.isNaN(time) ? -Infinity : time;
}

/** A branch build's entry (update spec 3.12.4), or `null` when it is not one. */
function branchBuildEntry(item: Record<string, unknown>, tag: string, zip: Record<string, unknown>): BranchBuild | null {
  if (item.prerelease !== true || !tag.startsWith(BUILD_TAG_PREFIX) || !TAG_RE.test(tag)) return null;
  const digest = digestOf(zip.digest);
  // Nothing is offered without a hash, so an entry without one is not kept.
  if (!digest) return null;
  const name = item.name;
  const ref = typeof name === "string" && REF_RE.test(name) ? name : tag.slice(BUILD_TAG_PREFIX.length);
  if (!REF_RE.test(ref)) return null;
  return {
    tag,
    kind: "branch",
    ref,
    version: null,
    updatedAt: stringOr(zip.updated_at, ""),
    publishedAt: stringOr(item.published_at, ""),
    notes: typeof item.body === "string" ? item.body.slice(0, NOTES_MAX_CHARS) : "",
    size: typeof zip.size === "number" && Number.isFinite(zip.size) ? zip.size : 0,
    digest,
    build: null,
  };
}

/**
 * The API's array of releases (update spec 3.4, 3.12.4). Kept: a release
 * that is not a draft nor a prerelease, with a `vX.Y.Z` tag and the
 * plugin's zip (phase 1's rule, unchanged), highest version first; then a
 * branch build, a prerelease that is not a draft, tagged `build-…` within
 * `TAG_RE`, with the zip and its digest, by ref. Two builds that give the
 * same ref (only possible by hand) keep the one whose zip was uploaded
 * last. Anything else is skipped without an error. No URL from the
 * response is kept.
 */
export function parseReleases(raw: unknown): Release[] {
  if (!Array.isArray(raw)) return [];
  const releases: [Version, StableRelease][] = [];
  const builds = new Map<string, BranchBuild>();
  for (const item of raw) {
    if (!isObject(item) || item.draft !== false) continue;
    const tag = item.tag_name;
    if (typeof tag !== "string") continue;
    const assets = Array.isArray(item.assets) ? item.assets : [];
    const zip = assets.find((asset): asset is Record<string, unknown> => isObject(asset) && asset.name === ASSET);
    if (!zip) continue;
    const build = branchBuildEntry(item, tag, zip);
    if (build) {
      const other = builds.get(build.ref);
      if (!other || timeOf(build.updatedAt) > timeOf(other.updatedAt)) builds.set(build.ref, build);
      continue;
    }
    if (item.prerelease !== false) continue;
    const match = RELEASE_TAG_RE.exec(tag);
    if (!match) continue;
    const version: Version = [Number(match[1]), Number(match[2]), Number(match[3])];
    releases.push([
      version,
      {
        tag,
        kind: "release",
        version: version.join("."),
        publishedAt: stringOr(item.published_at, ""),
        notes: typeof item.body === "string" ? item.body.slice(0, NOTES_MAX_CHARS) : "",
        size: typeof zip.size === "number" && Number.isFinite(zip.size) ? zip.size : 0,
        digest: digestOf(zip.digest),
      },
    ]);
  }
  releases.sort((a, b) => compareVersions(b[0], a[0]));
  const branches = [...builds.values()].sort((a, b) => byName(a.ref, b.ref));
  return [...releases.map(([, release]) => release), ...branches];
}

/** Plain code-unit order, the same on every device. */
function byName(a: string, b: string): number {
  return a < b ? -1 : a > b ? 1 : 0;
}

const HEX40_RE = /^[0-9a-fA-F]{40}$/;

/**
 * The selected branch's `build.json`, as fetched from its release (update
 * spec 3.12.4): the backend's `updates.parse_build` rules (a JSON object,
 * `schema` the integer 1, a `ref` matching `REF_RE`, a `sha` of 40 hex
 * digits, lower-cased; the known keys only, `built_at` / `run` strings or
 * `null`), and also: at most `BUILD_MAX_BYTES`, `kind` `"branch"`, and
 * `ref` the entry's own. Anything else is `null`.
 */
export function parseBuild(text: string, ref: string): BuildInfo | null {
  if (typeof text !== "string" || text.length > BUILD_MAX_BYTES) return null;
  if (new TextEncoder().encode(text).length > BUILD_MAX_BYTES) return null;
  let data: unknown;
  try {
    data = JSON.parse(text);
  } catch {
    return null;
  }
  if (!isObject(data)) return null;
  // JSON cannot tell 1.0 from 1 once parsed; `true` is not 1 here.
  if (data.schema !== 1) return null;
  if (data.kind !== "branch") return null;
  if (typeof data.ref !== "string" || !REF_RE.test(data.ref) || data.ref !== ref) return null;
  if (typeof data.sha !== "string" || !HEX40_RE.test(data.sha)) return null;
  return {
    schema: 1,
    kind: "branch",
    ref: data.ref,
    sha: data.sha.toLowerCase(),
    built_at: typeof data.built_at === "string" ? data.built_at : null,
    run: typeof data.run === "string" ? data.run : null,
  };
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
 * The selected branch's `build.json` (update spec 3.12.4), from its
 * release's asset URL built from the constants and the validated tag. A
 * rejected request, a status other than 200 or a file `parseBuild` refuses
 * is `null`: never a failed check.
 */
async function fetchBuild(net: NetPort, entry: BranchBuild): Promise<BuildInfo | null> {
  try {
    const answer = await net.get(assetUrl(entry.tag, BUILD_ASSET), {});
    return answer.status === 200 ? parseBuild(answer.text, entry.ref) : null;
  } catch {
    return null;
  }
}

/**
 * A check (update spec 3.4, 3.12.4): the repository's releases,
 * unauthenticated, in one request. On a branch channel, a second request
 * for that channel's build only (never on `stable`, never for another
 * branch's entry, never when the branch has no entry), whose answer is the
 * entry's `build`; it never fails the check. `now` (epoch ms) dates a
 * `retry-after`.
 */
export async function checkReleases(
  net: NetPort,
  channel: string = STABLE_CHANNEL,
  now: () => number = Date.now,
): Promise<CheckResult> {
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
    if (!Array.isArray(raw)) {
      return { ok: false, error: "bad-release", message: "GitHub's answer was not a list of releases", retryAt: null };
    }
    const releases = parseReleases(raw);
    const entry = branchEntryOf(releases, channel);
    if (!entry) return { ok: true, releases };
    const build = await fetchBuild(net, entry);
    return { ok: true, releases: releases.map((release) => (release === entry ? { ...entry, build } : release)) };
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

/** The selected branch's build entry, or `null` on `stable` and for a branch with none. */
export function branchEntryOf(releases: readonly Release[] | null, channel: string | null | undefined): BranchBuild | null {
  const ref = channelRef(channel);
  if (ref === null || !releases) return null;
  return releases.find((release): release is BranchBuild => release.kind === "branch" && release.ref === ref) ?? null;
}

/**
 * The *Channel* options (update spec 3.12.4): `stable` first, as
 * "Releases", then `main`, then every other branch with a build by name,
 * each with its build's `updatedAt`. The selected channel is always there,
 * without an `updatedAt` when its branch has no build.
 */
export function channelsOf(releases: readonly Release[] | null, channel: string | null | undefined): ChannelOption[] {
  const branches = new Map<string, ChannelOption>();
  for (const release of releases ?? []) {
    if (release.kind === "branch") {
      branches.set(release.ref, { id: `${BRANCH_CHANNEL_PREFIX}${release.ref}`, label: release.ref, updatedAt: release.updatedAt });
    }
  }
  const selected = channelRef(channel);
  if (selected !== null && !branches.has(selected)) {
    branches.set(selected, { id: `${BRANCH_CHANNEL_PREFIX}${selected}`, label: selected });
  }
  const refs = [...branches.keys()].sort((a, b) => (a === "main" ? -1 : b === "main" ? 1 : byName(a, b)));
  return [{ id: STABLE_CHANNEL, label: "Releases" }, ...refs.map((ref) => branches.get(ref)!)];
}

/** The highest installable release, if any. */
function newestRelease(releases: readonly Release[]): [Version, StableRelease] | null {
  let best: [Version, StableRelease] | null = null;
  for (const release of releases) {
    if (release.kind !== "release") continue;
    const version = installableVersion(release);
    if (version && (!best || compareVersions(version, best[0]) > 0)) best = [version, release];
  }
  return best;
}

/**
 * What is offered (update spec 3.12.4's table), or `null`:
 *
 * - `stable`, a release installed (or a zip whose `build.json` says
 *   `release`, or none): the highest installable release as an `update`
 *   when it is higher than the installed version; nothing when that
 *   version does not parse.
 * - `stable`, a branch build installed: a `switch` to the highest
 *   installable release, label its version, whatever the versions say.
 * - `branch:<ref>`: nothing when the branch has no entry or its `build` is
 *   unknown (`latestText` says "No build of <ref> is published"), nor when
 *   the installed build has that `ref` and `sha` (compared lower-cased and
 *   in full); otherwise a `switch` to the entry, label `<ref> @ <first 7 of
 *   sha>`. The installed version plays no part.
 *
 * `installed` `null` (`cli_version()` not read) offers nothing on either.
 */
export function offerOf(
  installed: Installed | null,
  releases: readonly Release[] | null,
  channel: string | null | undefined,
): Offer | null {
  if (!installed || !releases) return null;
  const installedBuild = branchBuildOf(installed);
  const ref = channelRef(channel);
  if (ref !== null) {
    const entry = branchEntryOf(releases, channel);
    if (!entry?.build) return null;
    const same =
      installedBuild !== null &&
      installedBuild.ref === entry.build.ref &&
      installedBuild.sha.toLowerCase() === entry.build.sha.toLowerCase();
    return same ? null : { ...entry, action: "switch", label: buildLabel(entry.build) };
  }
  const best = newestRelease(releases);
  if (!best) return null;
  if (installedBuild) return { ...best[1], action: "switch", label: best[1].version };
  const current = versionOf(installed.version);
  if (!current || compareVersions(best[0], current) <= 0) return null;
  return { ...best[1], action: "update", label: best[1].version };
}

/**
 * *Install another version*'s list: every installable release (never a
 * branch build, whatever the channel), label its version. With a release
 * installed, each is an update, a reinstall or a downgrade of the
 * installed version, and the list is empty when that version does not
 * parse, since no action could be named. With a branch build installed,
 * each is a `switch`: a release is not compared with a build.
 */
export function installable(installed: Installed | null, releases: readonly Release[] | null): Offer[] {
  if (!installed || !releases) return [];
  const fromBranch = branchBuildOf(installed) !== null;
  const current = versionOf(installed.version);
  if (!fromBranch && !current) return [];
  const offers: Offer[] = [];
  for (const release of releases) {
    if (release.kind !== "release") continue;
    const version = installableVersion(release);
    if (!version) continue;
    const action = fromBranch ? "switch" : actionFor(version, current!);
    offers.push({ ...release, action, label: release.version });
  }
  return offers;
}

/** A commit: 40 hex digits, either case (its label lower-cases it). */
const COMMIT_RE = /^[0-9a-fA-F]{40}$/;

/**
 * The staging answered what was asked for (update spec 3.12.5): the
 * backend validated the zip, and this checks that its answer is the one the
 * offer asked for before anything reaches Decky. The hash is the offer's
 * digest, lower-cased; for a release the zip's version is the offer's,
 * exactly; for a branch build the zip has a `build.json` of `kind: "branch"`
 * with the offer's ref and a commit (the version handed to Decky is built
 * from it). Anything else is `false`.
 */
export function stagedMatches(offer: Offer, staged: StagedUpdate): boolean {
  if (!offer.digest || typeof staged.hash !== "string" || staged.hash !== offer.digest.toLowerCase()) return false;
  if (typeof staged.artifact !== "string" || typeof staged.version !== "string") return false;
  if (offer.kind === "release") return staged.version === offer.version;
  const build = staged.build;
  return (
    !!build &&
    build.kind === "branch" &&
    build.ref === offer.ref &&
    typeof build.sha === "string" &&
    COMMIT_RE.test(build.sha)
  );
}

/**
 * What Decky's installer is handed (update spec 3.12.5): the staged zip's
 * `file://` artifact and hash, the plugin's name, the install type for the
 * offer's action, and the version: the release's own, or for a branch build
 * `branchVersionText` of the staged zip's own version and `build.json` (what
 * is in the zip is the truth, not what the list said). Throws for a branch
 * build whose zip has no `build.json`: the caller checks `stagedMatches`
 * first. `decky.ts` checks every field again.
 */
export function installRequestOf(
  offer: Offer,
  staged: StagedUpdate,
  loaderVersion: string | null | undefined,
): InstallRequest {
  let version: string;
  if (offer.kind === "release") {
    version = offer.version;
  } else {
    if (!staged.build) throw new Error(`${offer.tag}'s zip has no build.json`);
    version = branchVersionText(staged.version, staged.build);
  }
  return {
    artifact: staged.artifact,
    name: PLUGIN_NAME,
    version,
    hash: staged.hash,
    installType: installType(offer.action, loaderVersion),
  };
}

/**
 * The version Decky is handed for a branch build (update spec 3.12.4):
 * `<the zip's version> (<ref> @ <first 7 of sha>)`, e.g. `0.12.0 (main @
 * abc1234)`, from the staged zip's `package.json` version and
 * `build.json`. Decky shows it in its dialog; `decky.ts` accepts exactly
 * this shape besides a release's version.
 */
export function branchVersionText(zipVersion: string, build: Pick<BuildInfo, "ref" | "sha">): string {
  return `${zipVersion} (${buildLabel(build)})`;
}

// ---------------------------------------------------------------------------
// texts (update spec 3.7)

type UpdateState = Pick<AppState, "settings" | "cliVersion" | "update" | "updatePhase">;

/** The panel's *Update to …* row, or `null` when there is nothing to offer right now. */
export function updateRowView(state: UpdateState): { text: string; tag: string } | null {
  if (!pluginEnabled(state.settings) || !state.update || state.updatePhase !== "idle") return null;
  if (!loaderSupported(state.cliVersion?.loader_version)) return null;
  const offer = offerOf(installedOf(state.cliVersion), state.update.releases, channelOf(state.settings));
  return offer ? { text: `Update to ${offer.label}`, tag: offer.tag } : null;
}

/**
 * *Installed*: the plugin's version; for a branch build also its ref, the
 * first 7 of its commit and when it was built (`0.11.0 · main @ abc1234 ·
 * built today 13:03`), the last part only when `build.json` says.
 */
export function installedText(installed: Installed | null, now: Date = new Date()): string {
  const version = installed?.version || "unknown";
  const build = branchBuildOf(installed);
  if (!build) return version;
  const built = build.built_at ? ` · built ${relativeTime(build.built_at, now)}` : "";
  return `${version} · ${buildLabel(build)}${built}`;
}

/** About's *Built from* for a zip without a `build.json`. */
export const BUILD_UNKNOWN_TEXT = "not recorded in this build";

/**
 * About's *Built from*: what the installed zip's `build.json` says, a
 * release's as well as a branch's: its ref (the tag or the branch), the
 * first 7 of its commit and when it was built (`main @ abc1234 · built
 * today 13:03`). `BUILD_UNKNOWN_TEXT` for a zip without one: a release from
 * before the file existed, or a build of a checkout that was not exactly a
 * commit. The whole commit is About's *Commit* row.
 */
export function builtFromText(build: BuildInfo | null | undefined, now: Date = new Date()): string {
  if (!build) return BUILD_UNKNOWN_TEXT;
  const built = build.built_at ? ` · built ${relativeTime(build.built_at, now)}` : "";
  return `${buildLabel(build)}${built}`;
}

/**
 * *Latest*: what the last check found on the channel, or why it could not.
 * On a branch channel whose branch has no entry, or whose `build.json`
 * could not be read (as while it is being republished), "No build of
 * <ref> is published". A branch build's offer says when it was built
 * (`build.json`'s `built_at`, else the zip's upload time) where a
 * release's says when it was released.
 */
export function latestText(
  update: UpdateInfo,
  phase: UpdatePhase,
  offer: Offer | null,
  channel: string | null | undefined,
  now: Date = new Date(),
): string {
  if (phase === "checking") return "Checking…";
  if (update.error) {
    const text = errorText(update.error, now);
    return update.checkedAt ? `${text} · last checked ${relativeTime(update.checkedAt, now)}` : text;
  }
  if (!update.checkedAt) return "Not checked yet";
  const ref = channelRef(channel);
  if (ref !== null && !branchEntryOf(update.releases, channel)?.build) return `No build of ${ref} is published`;
  const checked = `checked ${relativeTime(update.checkedAt, now)}`;
  if (offer?.kind === "branch") {
    return `${offer.label} · built ${relativeTime(offer.build?.built_at || offer.updatedAt, now)} · ${checked}`;
  }
  if (offer) return `${offer.label} · released ${relativeTime(offer.publishedAt, now)} · ${checked}`;
  return `Up to date · ${checked}`;
}

/** An option of *Install another version*: `0.12.0 · 2026-10-01`, or `0.11.0 · reinstall`. */
export function versionLabel(offer: Offer): string {
  return offer.action === "reinstall" ? `${offer.label} · reinstall` : `${offer.label} · ${dateText(offer.publishedAt)}`;
}

/**
 * The page's install button: `Switch to <label>` for a `switch` (to a
 * branch's build, or back to a release from one), else `Update to
 * <label>`; `Downloading…` while the backend stages the zip, `Waiting for
 * Decky…` while Decky is asked.
 */
export function installButtonText(offer: Offer, phase: UpdatePhase): string {
  if (phase === "downloading") return "Downloading…";
  if (phase === "asking") return "Waiting for Decky…";
  return offer.action === "switch" ? `Switch to ${offer.label}` : `Update to ${offer.label}`;
}
