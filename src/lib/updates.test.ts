import { describe, expect, it } from "vitest";

import { fixtureText } from "../test/fixtures";
import type { BuildInfo, StagedUpdate } from "./cli";
import {
  ASSET,
  assetUrl,
  branchEntryOf,
  branchVersionText,
  BUILD_MAX_BYTES,
  BUILD_UNKNOWN_TEXT,
  builtFromText,
  channelOf,
  channelRef,
  channelsOf,
  checkReleases,
  DOWNLOAD_BASE,
  installable,
  installButtonText,
  installedOf,
  installedText,
  installRequestOf,
  installType,
  latestText,
  loaderSupported,
  MIN_UPDATER_VERSION,
  NOTES_MAX_CHARS,
  offerOf,
  parseBuild,
  parseReleases,
  PLUGIN_NAME,
  REF_RE,
  RELEASES_API,
  REPO,
  stagedMatches,
  TAG_RE,
  updateCheckEnabled,
  versionLabel,
  type BranchBuild,
  type HttpAnswer,
  type Installed,
  type NetPort,
  type Offer,
  type Release,
  type StableRelease,
  type UpdateInfo,
} from "./updates";

const RAW: unknown = JSON.parse(fixtureText("update/releases.json"));
const RELEASES = parseReleases(RAW);
const hex = (digit: string) => digit.repeat(64);
/** `build-main.json`'s commit, lower-cased. */
const MAIN_SHA = "abc1234def5678abc1234def5678abc1234def56";
const OTHER_SHA = "fedcba9876543210fedcba9876543210fedcba98";
const BUILD_MAIN_URL = `${DOWNLOAD_BASE}/build-main/build.json`;

const now = new Date(2026, 9, 21, 15, 30);
const local = (m: number, d: number, h: number, min: number) => new Date(2026, m, d, h, min).toISOString();

function release(version: string, digest: string | null = hex("a"), publishedAt = "2026-10-01T12:00:00Z"): StableRelease {
  return { tag: `v${version}`, kind: "release", version, publishedAt, notes: "", size: 1, digest };
}

function buildInfo(ref: string, sha = MAIN_SHA, kind: BuildInfo["kind"] = "branch", built_at: string | null = null): BuildInfo {
  return { schema: 1, kind, ref, sha, built_at, run: null };
}

/** A branch's entry, with its `build.json` read (or not, `build: null`). */
function branch(ref: string, build: BuildInfo | null = buildInfo(ref), updatedAt = "2026-10-26T08:00:00Z"): BranchBuild {
  return {
    tag: `build-${ref.replace(/[^A-Za-z0-9._-]/g, "-")}`,
    kind: "branch",
    ref,
    version: null,
    updatedAt,
    publishedAt: "2026-10-10T08:00:00Z",
    notes: "",
    size: 1,
    digest: hex("e"),
    build,
  };
}

const at = (version: string | null, build: BuildInfo | null = null): Installed => ({ version, build });

function answer(status: number, text = "", headers: Partial<HttpAnswer["headers"]> = {}): HttpAnswer {
  return {
    status,
    headers: { "x-ratelimit-remaining": null, "x-ratelimit-reset": null, "retry-after": null, etag: null, ...headers },
    text,
  };
}

/**
 * A NetPort that answers from a script and records what it was asked:
 * `byUrl` answers for its URLs, `reply` for any other.
 */
function scripted(reply: HttpAnswer | Error, byUrl: Record<string, HttpAnswer | Error> = {}) {
  const asked: [string, Record<string, string>][] = [];
  const net: NetPort = {
    async get(url, headers) {
      asked.push([url, headers]);
      const scriptedReply = byUrl[url] ?? reply;
      if (scriptedReply instanceof Error) throw scriptedReply;
      return scriptedReply;
    },
  };
  return { net, asked };
}

describe("the constants", () => {
  it("name this repository's API and downloads, and the plugin's zip", () => {
    expect(REPO).toBe("episode6/moonlight-steam-sync-decky");
    expect(RELEASES_API).toBe("https://api.github.com/repos/episode6/moonlight-steam-sync-decky/releases?per_page=100");
    expect(DOWNLOAD_BASE).toBe("https://github.com/episode6/moonlight-steam-sync-decky/releases/download");
    expect(ASSET).toBe("Moonlight-Sync.zip");
    expect(PLUGIN_NAME).toBe("Moonlight Sync");
    expect(MIN_UPDATER_VERSION).toEqual([0, 12, 0]);
  });
});

describe("parseReleases (the fixture)", () => {
  it("keeps the published releases with a vX.Y.Z tag and the zip, highest first, as phase 1 did", () => {
    // Skipped: the draft, the prerelease, v0.12.2 (no zip), v1.2 (not
    // vX.Y.Z) and the string entry. Phase 1's result, unchanged.
    expect(RELEASES.filter((r) => r.kind === "release").map((r) => r.tag)).toEqual([
      "v0.13.0",
      "v0.12.1",
      "v0.12.0",
      "v0.11.0",
    ]);
  });

  it("then the branch builds with a digest, by ref (update spec 3.12.4)", () => {
    // Skipped: build-no-digest (no hash, nothing offered without one) and
    // build-drafted (a draft).
    expect(RELEASES.map((r) => r.tag)).toEqual([
      "v0.13.0",
      "v0.12.1",
      "v0.12.0",
      "v0.11.0",
      "build-feature-x",
      "build-main",
      "build-odd-title",
    ]);
  });

  it("reads a branch build's fields: the title as its ref, else the tag's, the zip's upload time, no build yet", () => {
    const branches = RELEASES.filter((r): r is BranchBuild => r.kind === "branch");
    expect(branches.map((b) => b.ref)).toEqual(["feature/x", "main", "odd-title"]);
    expect(branches.find((b) => b.ref === "main")).toEqual({
      tag: "build-main",
      kind: "branch",
      ref: "main",
      version: null,
      updatedAt: "2026-10-26T08:00:00Z",
      publishedAt: "2026-10-10T08:00:00Z",
      notes: "Build of `main` at abc1234def5678abc1234def5678abc1234def56. Untested: installed from Moonlight Sync's Updates page.",
      size: 1400002,
      digest: hex("e"),
      build: null,
    });
    // the digest lower-cased, as a release's is
    expect(branches[0].digest).toBe("abcdef".repeat(10) + "abcd");
  });

  const entry = (over: Record<string, unknown> = {}, zip: Record<string, unknown> = {}) => ({
    tag_name: "build-topic",
    name: "topic",
    draft: false,
    prerelease: true,
    assets: [{ name: ASSET, digest: `sha256:${hex("c")}`, updated_at: "2026-10-26T08:00:00Z", ...zip }],
    ...over,
  });

  it("a branch build must be a prerelease, not a draft, tagged build- within TAG_RE, with the zip and its digest", () => {
    expect(parseReleases([entry()]).map((r) => r.tag)).toEqual(["build-topic"]);
    expect(parseReleases([entry({ prerelease: false })])).toEqual([]);
    expect(parseReleases([entry({ draft: true })])).toEqual([]);
    expect(parseReleases([entry({ draft: undefined })])).toEqual([]);
    expect(parseReleases([entry({ tag_name: "topic" })])).toEqual([]);
    expect(parseReleases([entry({ tag_name: "nightly-topic" })])).toEqual([]);
    expect(parseReleases([entry({ tag_name: "build-a/b" })])).toEqual([]);
    expect(parseReleases([entry({ tag_name: `build-${"a".repeat(95)}` })])).toEqual([]);
    expect(parseReleases([entry({ assets: [] })])).toEqual([]);
    expect(parseReleases([entry({}, { name: "Moonlight-Sync.zip.sha256" })])).toEqual([]);
    for (const digest of [null, undefined, hex("c"), `sha256:${"c".repeat(63)}`]) {
      expect(parseReleases([entry({}, { digest })]), String(digest)).toEqual([]);
    }
  });

  it("the ref: the title when it is one, else the tag without build-, else no entry", () => {
    const refOf = (over: Record<string, unknown>) => (parseReleases([entry(over)])[0] as BranchBuild | undefined)?.ref;
    expect(refOf({ name: "feature/x" })).toBe("feature/x");
    expect(refOf({ name: "has space" })).toBe("topic");
    expect(refOf({ name: "" })).toBe("topic");
    expect(refOf({ name: null })).toBe("topic");
    expect(refOf({ name: "a".repeat(101) })).toBe("topic");
    expect(refOf({ tag_name: "build-", name: "no ref" })).toBeUndefined();
  });

  it("two builds of one ref keep the one whose zip was uploaded last", () => {
    const older = entry({ tag_name: "build-a-b", name: "a/b" }, { updated_at: "2026-10-01T00:00:00Z" });
    const newer = entry({ tag_name: "build-a-b2", name: "a/b" }, { updated_at: "2026-10-02T00:00:00Z" });
    for (const raw of [
      [older, newer],
      [newer, older],
    ]) {
      const kept = parseReleases(raw);
      expect(kept.map((r) => r.tag)).toEqual(["build-a-b2"]);
    }
    // an upload time that does not parse counts as the oldest
    const undated = entry({ tag_name: "build-a-b3", name: "a/b" }, { updated_at: "soon" });
    expect(parseReleases([newer, undated]).map((r) => r.tag)).toEqual(["build-a-b2"]);
    expect(parseReleases([undated, older]).map((r) => r.tag)).toEqual(["build-a-b"]);
  });

  it("reads each field, the zip's digest without its prefix, and nothing else", () => {
    expect(RELEASES[0]).toEqual({
      tag: "v0.13.0",
      kind: "release",
      version: "0.13.0",
      publishedAt: "2026-10-20T12:00:00Z",
      notes: "## Added\n\n- A newer release, made up for the tests.",
      size: 1300000,
      digest: hex("a"),
    });
    expect(RELEASES[1].digest).toBeNull();
  });

  it("keeps no URL from the response", () => {
    const text = JSON.stringify(RELEASES);
    expect(text).not.toMatch(/https?:/);
    expect(text).not.toContain("example.invalid");
  });

  it("skips anything that is not an array or not a release, without an error", () => {
    expect(parseReleases(null)).toEqual([]);
    expect(parseReleases({ tag_name: "v1.0.0" })).toEqual([]);
    expect(parseReleases([null, 3, [], { tag_name: 7 }, { tag_name: "v1.0.0", draft: false, prerelease: false }])).toEqual([]);
  });

  it("cuts the notes and tolerates missing fields", () => {
    const [only] = parseReleases([
      { tag_name: "v1.0.0", draft: false, prerelease: false, body: "x".repeat(NOTES_MAX_CHARS + 5), assets: [{ name: ASSET }] },
    ]);
    expect(only.notes).toHaveLength(NOTES_MAX_CHARS);
    expect(only).toMatchObject({ publishedAt: "", size: 0, digest: null });
  });

  it("reads a digest only as sha256 and 64 hex digits, lower-cased", () => {
    const digestOf = (digest: unknown) =>
      parseReleases([{ tag_name: "v1.0.0", draft: false, prerelease: false, assets: [{ name: ASSET, digest }] }])[0].digest;
    expect(digestOf(`sha256:${hex("A")}`)).toBe(hex("a"));
    expect(digestOf(`sha256:${hex("0")}`)).toBe(hex("0"));
    expect(digestOf(undefined)).toBeNull();
    expect(digestOf(null)).toBeNull();
    expect(digestOf(42)).toBeNull();
    expect(digestOf(hex("a"))).toBeNull(); // no prefix
    expect(digestOf(`sha512:${hex("a")}`)).toBeNull();
    expect(digestOf(`sha256:${"a".repeat(63)}`)).toBeNull();
    expect(digestOf(`sha256:${"a".repeat(65)}`)).toBeNull();
    expect(digestOf(`sha256:${"g".repeat(64)}`)).toBeNull();
    expect(digestOf(` sha256:${hex("a")}`)).toBeNull();
    expect(digestOf(`sha256:${hex("a")}\n`)).toBeNull();
  });
});

describe("assetUrl", () => {
  it("builds the URL from the constants and the tag", () => {
    expect(assetUrl("v0.13.0", ASSET)).toBe(
      "https://github.com/episode6/moonlight-steam-sync-decky/releases/download/v0.13.0/Moonlight-Sync.zip",
    );
  });

  it("throws on a tag that is not one", () => {
    for (const tag of ["", "../main", "v1/2", "v1 2", "v1?x", "v1#x", "%2e%2e", "..", ".", "a".repeat(101), "v1\n"]) {
      expect(() => assetUrl(tag, ASSET), tag).toThrow();
    }
  });
});

describe("checkReleases (update spec 3.4's table)", () => {
  it("asks once, for the list, with GitHub's headers", async () => {
    const { net, asked } = scripted(answer(200, "[]"));
    await checkReleases(net);
    expect(asked).toEqual([[RELEASES_API, { Accept: "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28" }]]);
  });

  it("200 with an array: the releases", async () => {
    const { net } = scripted(answer(200, fixtureText("update/releases.json")));
    expect(await checkReleases(net)).toEqual({ ok: true, releases: RELEASES });
  });

  it("200 with anything else: bad-release", async () => {
    for (const text of ["{}", "not json", "", "null"]) {
      const { net } = scripted(answer(200, text));
      expect(await checkReleases(net)).toEqual({
        ok: false,
        error: "bad-release",
        message: "GitHub's answer was not a list of releases",
        retryAt: null,
      });
    }
  });

  it("403 or 429 with the limit spent: rate-limited until x-ratelimit-reset", async () => {
    const reset = Date.UTC(2026, 9, 21, 14, 0) / 1000;
    for (const status of [403, 429]) {
      const { net } = scripted(answer(status, "{}", { "x-ratelimit-remaining": "0", "x-ratelimit-reset": String(reset) }));
      expect(await checkReleases(net)).toMatchObject({
        ok: false,
        error: "rate-limited",
        retryAt: "2026-10-21T14:00:00.000Z",
      });
    }
  });

  it("403 or 429 with a retry-after: rate-limited until now plus that", async () => {
    const at = Date.UTC(2026, 9, 21, 13, 0);
    const { net } = scripted(answer(429, "", { "retry-after": "120" }));
    expect(await checkReleases(net, "stable", () => at)).toMatchObject({
      error: "rate-limited",
      retryAt: "2026-10-21T13:02:00.000Z",
    });
    // neither header readable: rate-limited, with no time to say
    const { net: vague } = scripted(answer(403, "", { "x-ratelimit-remaining": "0" }));
    expect(await checkReleases(vague)).toMatchObject({ error: "rate-limited", retryAt: null });
  });

  it("any other status: network, with the status", async () => {
    for (const reply of [answer(403, "{}", { "x-ratelimit-remaining": "12" }), answer(404), answer(500), answer(304)]) {
      const { net } = scripted(reply);
      expect(await checkReleases(net)).toEqual({
        ok: false,
        error: "network",
        message: `GitHub answered ${reply.status}`,
        retryAt: null,
      });
    }
  });

  it("no answer: network", async () => {
    const { net } = scripted(new TypeError("Failed to fetch"));
    expect(await checkReleases(net)).toEqual({ ok: false, error: "network", message: "no answer from GitHub", retryAt: null });
  });
});

describe("checkReleases on a channel (update spec 3.12.4)", () => {
  const LIST = answer(200, fixtureText("update/releases.json"));
  const BUILD_MAIN = answer(200, fixtureText("update/build-main.json"));

  it("stable: the one request, never a build.json", async () => {
    const { net, asked } = scripted(LIST);
    expect(await checkReleases(net, "stable")).toEqual({ ok: true, releases: RELEASES });
    expect(asked.map(([url]) => url)).toEqual([RELEASES_API]);
  });

  it("a branch channel: a second request, for that branch's build.json only, with no headers", async () => {
    const { net, asked } = scripted(LIST, { [BUILD_MAIN_URL]: BUILD_MAIN });
    const result = await checkReleases(net, "branch:main");
    expect(asked).toEqual([
      [RELEASES_API, { Accept: "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28" }],
      ["https://github.com/episode6/moonlight-steam-sync-decky/releases/download/build-main/build.json", {}],
    ]);
    if (!result.ok) throw new Error("not ok");
    // that entry gains its build, sha lower-cased; nothing else changes
    expect(branchEntryOf(result.releases, "branch:main")?.build).toEqual({
      schema: 1,
      kind: "branch",
      ref: "main",
      sha: MAIN_SHA,
      built_at: "2026-10-26T07:58:00Z",
      run: "123456/1",
    });
    expect(result.releases.map((r) => (r.kind === "branch" && r.ref === "main" ? { ...r, build: null } : r))).toEqual(
      RELEASES,
    );
  });

  it("a branch whose title is not a ref, or that has a slash, is asked for by its tag", async () => {
    const { net, asked } = scripted(LIST);
    await checkReleases(net, "branch:feature/x");
    await checkReleases(net, "branch:odd-title");
    expect(asked.map(([url]) => url)).toEqual([
      RELEASES_API,
      `${DOWNLOAD_BASE}/build-feature-x/build.json`,
      RELEASES_API,
      `${DOWNLOAD_BASE}/build-odd-title/build.json`,
    ]);
  });

  it("no second request when the channel's branch has no entry, nor for a channel that is not one", async () => {
    for (const channel of ["branch:gone", "branch:no-digest", "branch:drafted", "branch:", "nightly", "branch:a b"]) {
      const { net, asked } = scripted(LIST);
      expect(await checkReleases(net, channel), channel).toEqual({ ok: true, releases: RELEASES });
      expect(asked.map(([url]) => url), channel).toEqual([RELEASES_API]);
    }
  });

  it("a failed second request never fails the check: the entry's build stays null", async () => {
    for (const reply of [
      answer(404, "Not Found"),
      answer(500, fixtureText("update/build-main.json")),
      answer(200, "not json"),
      answer(200, JSON.stringify({ ...JSON.parse(fixtureText("update/build-main.json")), ref: "feature/x" })),
      new TypeError("Failed to fetch"),
    ]) {
      const { net, asked } = scripted(LIST, { [BUILD_MAIN_URL]: reply });
      const result = await checkReleases(net, "branch:main");
      expect(asked).toHaveLength(2);
      expect(result).toEqual({ ok: true, releases: RELEASES });
    }
  });

  it("a failed list asks for no build.json", async () => {
    const { net, asked } = scripted(answer(502), { [BUILD_MAIN_URL]: BUILD_MAIN });
    expect(await checkReleases(net, "branch:main")).toMatchObject({ ok: false, error: "network" });
    expect(asked).toHaveLength(1);
  });
});

describe("parseBuild (a branch's build.json, update spec 3.12.4)", () => {
  const good = { schema: 1, kind: "branch", ref: "main", sha: MAIN_SHA, built_at: "2026-10-26T07:58:00Z", run: "1/1" };
  const text = (over: Record<string, unknown>) => JSON.stringify({ ...good, ...over });

  it("the known keys only, the sha lower-cased", () => {
    expect(parseBuild(text({ extra: "x", sha: MAIN_SHA.toUpperCase() }), "main")).toEqual({
      schema: 1,
      kind: "branch",
      ref: "main",
      sha: MAIN_SHA,
      built_at: "2026-10-26T07:58:00Z",
      run: "1/1",
    });
    expect(parseBuild(text({ built_at: 5, run: null }), "main")).toMatchObject({ built_at: null, run: null });
    expect(parseBuild(JSON.stringify({ schema: 1, kind: "branch", ref: "main", sha: MAIN_SHA }), "main")).toMatchObject({
      built_at: null,
      run: null,
    });
  });

  it("refuses what the backend's parse_build refuses", () => {
    for (const bad of [
      "not json",
      "[]",
      "null",
      '"main"',
      text({ schema: 2 }),
      text({ schema: "1" }),
      text({ schema: true }),
      text({ schema: undefined }),
      text({ kind: "nightly" }),
      text({ ref: "a b" }),
      text({ ref: "" }),
      text({ ref: 7 }),
      text({ sha: MAIN_SHA.slice(1) }),
      text({ sha: MAIN_SHA + "0" }),
      text({ sha: "g".repeat(40) }),
      text({ sha: null }),
    ]) {
      expect(parseBuild(bad, "main"), bad).toBeNull();
    }
  });

  it("and also a release's build, another ref's, and more than 64 KiB", () => {
    expect(parseBuild(text({ kind: "release" }), "main")).toBeNull();
    expect(parseBuild(text({ ref: "feature/x" }), "main")).toBeNull();
    expect(parseBuild(text({}), "Main")).toBeNull();
    const padded = (size: number) => {
      const base = text({ run: "" });
      return base.replace('"run":""', `"run":"${"x".repeat(size - base.length)}"`);
    };
    expect(padded(BUILD_MAX_BYTES)).toHaveLength(BUILD_MAX_BYTES);
    expect(parseBuild(padded(BUILD_MAX_BYTES), "main")).not.toBeNull();
    expect(parseBuild(padded(BUILD_MAX_BYTES + 1), "main")).toBeNull();
    // counted in UTF-8 bytes: under the limit in characters, over it in bytes
    const wide = text({ run: "é".repeat(BUILD_MAX_BYTES / 2) });
    expect(wide.length).toBeLessThan(BUILD_MAX_BYTES);
    expect(parseBuild(wide, "main")).toBeNull();
  });
});

describe("channels (update spec 3.12.4)", () => {
  it("channelOf: absent, unread or not a channel reads as stable", () => {
    expect(channelOf(null)).toBe("stable");
    expect(channelOf({})).toBe("stable");
    expect(channelOf({ update_channel: "stable" })).toBe("stable");
    expect(channelOf({ update_channel: "branch:main" })).toBe("branch:main");
    expect(channelOf({ update_channel: "branch:feature/x" })).toBe("branch:feature/x");
    for (const broken of ["branch:", "nightly", "branch:a b", "branch:a+b", " branch:main", "branch:main ", "Stable", ""]) {
      expect(channelOf({ update_channel: broken }), broken).toBe("stable");
    }
    expect(channelOf({ update_channel: `branch:${"a".repeat(101)}` })).toBe("stable");
  });

  it("channelRef: the branch, or null", () => {
    expect(channelRef("branch:main")).toBe("main");
    expect(channelRef("stable")).toBeNull();
    expect(channelRef("branch:")).toBeNull();
    expect(channelRef(undefined)).toBeNull();
  });

  it("channelsOf: Releases, main, then the others by name, each with its build's upload time", () => {
    expect(channelsOf(RELEASES, "stable")).toEqual([
      { id: "stable", label: "Releases" },
      { id: "branch:main", label: "main", updatedAt: "2026-10-26T08:00:00Z" },
      { id: "branch:feature/x", label: "feature/x", updatedAt: "2026-10-24T10:00:00Z" },
      { id: "branch:odd-title", label: "odd-title", updatedAt: "2026-10-23T10:00:00Z" },
    ]);
  });

  it("channelsOf: the selected channel is always there, without an updatedAt when it has no build", () => {
    expect(channelsOf(RELEASES, "branch:gone").map((c) => [c.id, c.updatedAt])).toEqual([
      ["stable", undefined],
      ["branch:main", "2026-10-26T08:00:00Z"],
      ["branch:feature/x", "2026-10-24T10:00:00Z"],
      ["branch:gone", undefined],
      ["branch:odd-title", "2026-10-23T10:00:00Z"],
    ]);
    expect(channelsOf(null, "branch:main")).toEqual([
      { id: "stable", label: "Releases" },
      { id: "branch:main", label: "main" },
    ]);
    expect(channelsOf([release("0.13.0")], "branch:x")).toEqual([
      { id: "stable", label: "Releases" },
      { id: "branch:x", label: "x" },
    ]);
    // a channel that does not parse is stable, which is always there
    expect(channelsOf(null, "nightly")).toEqual([{ id: "stable", label: "Releases" }]);
  });
});

describe("offerOf on stable (phase 1, and update spec 3.12.4's first three rows)", () => {
  it("row 1, a release older than the newest: an update to it", () => {
    expect(offerOf(at("0.12.0"), RELEASES, "stable")).toMatchObject({ tag: "v0.13.0", action: "update", label: "0.13.0" });
    expect(offerOf(at("0.12.0-dev"), RELEASES, "stable")).toMatchObject({ tag: "v0.13.0" });
    // a build.json that says release is a release
    expect(offerOf(at("0.12.0", buildInfo("v0.12.0", MAIN_SHA, "release")), RELEASES, "stable")).toMatchObject({
      tag: "v0.13.0",
      action: "update",
    });
  });

  it("row 3, the newest release (or newer): nothing", () => {
    expect(offerOf(at("0.13.0"), RELEASES, "stable")).toBeNull();
    expect(offerOf(at("0.14.0"), RELEASES, "stable")).toBeNull();
    expect(offerOf(at("0.13.0", buildInfo("v0.13.0", MAIN_SHA, "release")), RELEASES, "stable")).toBeNull();
  });

  it("row 2, a branch build: a switch to the newest release, label its version, whatever the versions say", () => {
    const main = buildInfo("main");
    for (const version of ["0.12.0", "0.13.0", "0.14.0", "dev", null]) {
      expect(offerOf(at(version, main), RELEASES, "stable"), String(version)).toMatchObject({
        tag: "v0.13.0",
        kind: "release",
        action: "switch",
        label: "0.13.0",
      });
    }
  });

  it("row 2 never switches to a release without a digest nor one below the minimum", () => {
    const main = buildInfo("main");
    expect(offerOf(at("0.14.0", main), [release("0.13.1", null), release("0.13.0")], "stable")).toMatchObject({
      tag: "v0.13.0",
      action: "switch",
    });
    expect(offerOf(at("0.14.0", main), [release("0.13.0", null)], "stable")).toBeNull();
    expect(offerOf(at("0.14.0", main), [release("0.11.0")], "stable")).toBeNull();
    expect(offerOf(at("0.14.0", main), [branch("main")], "stable")).toBeNull();
  });

  it("never a release without a digest, nor one below the minimum, nor a branch build", () => {
    // the highest has no digest: the next one with a digest is offered
    expect(offerOf(at("0.12.0"), [release("0.13.1", null), release("0.13.0")], "stable")).toMatchObject({
      tag: "v0.13.0",
    });
    expect(offerOf(at("0.12.0"), [release("0.13.0", null)], "stable")).toBeNull();
    expect(offerOf(at("0.10.0"), [release("0.11.0")], "stable")).toBeNull();
    expect(offerOf(at("0.10.0"), [branch("main")], "stable")).toBeNull();
  });

  it("nothing when the installed version does not parse, or before a check, or before cli_version", () => {
    for (const version of [null, undefined, "", "dev", "unknown"]) {
      expect(offerOf({ version, build: null }, RELEASES, "stable")).toBeNull();
    }
    expect(offerOf(at("0.12.0"), null, "stable")).toBeNull();
    expect(offerOf(null, RELEASES, "stable")).toBeNull();
  });

  it("a channel that does not parse is stable", () => {
    const withMain = RELEASES.map((r) => (r.kind === "branch" && r.ref === "main" ? { ...r, build: buildInfo("main") } : r));
    for (const channel of ["branch:", "nightly", "branch:a b", undefined, null]) {
      expect(offerOf(at("0.12.0"), withMain, channel), String(channel)).toMatchObject({ tag: "v0.13.0", action: "update" });
    }
  });
});

describe("offerOf on a branch channel (update spec 3.12.4's last three rows)", () => {
  const releases = (build: BuildInfo | null = buildInfo("main")): Release[] => [release("0.13.0"), branch("main", build), branch("feature/x")];

  it("row 4, the same ref and the same sha installed: nothing", () => {
    expect(offerOf(at("0.13.0", buildInfo("main")), releases(), "branch:main")).toBeNull();
    // compared lower-cased
    expect(offerOf(at("0.13.0", buildInfo("main", MAIN_SHA.toUpperCase())), releases(), "branch:main")).toBeNull();
  });

  it("row 5, anything else with the entry's build known: a switch, label <ref> @ <first 7 of sha>", () => {
    const expected = { tag: "build-main", kind: "branch", action: "switch", label: "main @ abc1234" };
    // a release installed
    expect(offerOf(at("0.12.0"), releases(), "branch:main")).toMatchObject(expected);
    expect(offerOf(at("0.13.0", buildInfo("v0.13.0", MAIN_SHA, "release")), releases(), "branch:main")).toMatchObject(
      expected,
    );
    // the same ref, another commit
    expect(offerOf(at("0.12.0", buildInfo("main", OTHER_SHA)), releases(), "branch:main")).toMatchObject(expected);
    // another branch's build with the same commit
    expect(offerOf(at("0.12.0", buildInfo("feature/x")), releases(), "branch:main")).toMatchObject(expected);
    // shas compared in full: the first 7 alike is not the same build
    const near = MAIN_SHA.slice(0, 39) + "8";
    expect(offerOf(at("0.12.0", buildInfo("main", near)), releases(), "branch:main")).toMatchObject(expected);
    // the offer carries the entry's digest and build
    expect(offerOf(at("0.12.0"), releases(), "branch:main")).toMatchObject({ digest: hex("e"), build: buildInfo("main") });
  });

  it("row 5 does not depend on the installed version at all", () => {
    for (const version of ["0.12.0", "0.13.0", "9.9.9", "dev", "", null, undefined]) {
      expect(offerOf({ version, build: null }, releases(), "branch:main"), String(version)).toMatchObject({
        action: "switch",
        label: "main @ abc1234",
      });
    }
  });

  it("row 6, no entry for the ref or its build null: nothing", () => {
    expect(offerOf(at("0.12.0"), releases(null), "branch:main")).toBeNull();
    expect(offerOf(at("0.12.0"), releases(), "branch:gone")).toBeNull();
    expect(offerOf(at("0.12.0"), [release("0.13.0")], "branch:main")).toBeNull();
    // the fixture as parsed: no build.json read yet
    expect(offerOf(at("0.12.0"), RELEASES, "branch:main")).toBeNull();
    // never a release on a branch channel
    expect(offerOf(at("0.10.0"), releases(null), "branch:main")).toBeNull();
  });

  it("nothing before a check or before cli_version", () => {
    expect(offerOf(at("0.12.0"), null, "branch:main")).toBeNull();
    expect(offerOf(null, releases(), "branch:main")).toBeNull();
  });
});

describe("installable (Install another version)", () => {
  it("every release with a digest from the minimum up, each against the installed version", () => {
    expect(installable(at("0.12.0"), RELEASES).map((o) => [o.tag, o.action, o.label])).toEqual([
      ["v0.13.0", "update", "0.13.0"],
      ["v0.12.0", "reinstall", "0.12.0"],
    ]);
    expect(installable(at("0.13.0"), RELEASES).map((o) => [o.tag, o.action])).toEqual([
      ["v0.13.0", "reinstall"],
      ["v0.12.0", "downgrade"],
    ]);
  });

  it("leaves out no digest, below the minimum, and every branch build", () => {
    const withBuild = RELEASES.map((r) => (r.kind === "branch" ? { ...r, build: buildInfo(r.ref) } : r));
    const tags = installable(at("0.12.0"), withBuild).map((o) => o.tag);
    expect(tags).not.toContain("v0.12.1"); // null digest
    expect(tags).not.toContain("v0.11.0"); // below MIN_UPDATER_VERSION
    expect(tags.filter((tag) => tag.startsWith("build-"))).toEqual([]);
  });

  it("with a branch build installed: every one a switch, label its version", () => {
    for (const version of ["0.12.0", "0.13.0", "dev"]) {
      expect(installable(at(version, buildInfo("main")), RELEASES).map((o) => [o.tag, o.action, o.label])).toEqual([
        ["v0.13.0", "switch", "0.13.0"],
        ["v0.12.0", "switch", "0.12.0"],
      ]);
    }
    // a release's build.json is a release
    expect(installable(at("0.12.0", buildInfo("v0.12.0", MAIN_SHA, "release")), RELEASES).map((o) => o.action)).toEqual([
      "update",
      "reinstall",
    ]);
  });

  it("nothing when the installed version does not parse, or before cli_version", () => {
    expect(installable(at("dev"), RELEASES)).toEqual([]);
    expect(installable(at(null), RELEASES)).toEqual([]);
    expect(installable(null, RELEASES)).toEqual([]);
  });
});

describe("installedOf", () => {
  it("cli_version's plugin_version and build; null before it answered", () => {
    expect(installedOf(null)).toBeNull();
    expect(installedOf({ plugin_version: "0.12.0" })).toEqual({ version: "0.12.0", build: null });
    expect(installedOf({ plugin_version: "0.12.0", build: buildInfo("main") })).toEqual({
      version: "0.12.0",
      build: buildInfo("main"),
    });
  });
});

describe("the loader", () => {
  it("installType per action; 3 and 4 become 2 before loader v3.1.0", () => {
    expect(installType("reinstall", "v3.2.9")).toBe(1);
    expect(installType("update", "v3.2.9")).toBe(2);
    expect(installType("downgrade", "v3.2.9")).toBe(3);
    expect(installType("switch", "v3.2.9")).toBe(4);
    expect(installType("reinstall", "v3.0.4")).toBe(1);
    expect(installType("update", "v3.0.4")).toBe(2);
    expect(installType("downgrade", "v3.0.4")).toBe(2);
    expect(installType("switch", "v3.0.4")).toBe(2);
    // a version that does not parse counts as current
    expect(installType("downgrade", "")).toBe(3);
    expect(installType("downgrade", "dev")).toBe(3);
  });

  it("loaderSupported: false only for a version that parses below 3.0.0", () => {
    expect(loaderSupported("v2.12.3")).toBe(false);
    expect(loaderSupported("v3.0.0")).toBe(true);
    expect(loaderSupported("v3.2.9")).toBe(true);
    expect(loaderSupported("3.2.9")).toBe(true);
    expect(loaderSupported("")).toBe(true);
    expect(loaderSupported("dev")).toBe(true);
    expect(loaderSupported(undefined)).toBe(true);
  });

  it("updateCheckEnabled: absent reads as on", () => {
    expect(updateCheckEnabled(null)).toBe(true);
    expect(updateCheckEnabled({})).toBe(true);
    expect(updateCheckEnabled({ update_check: true })).toBe(true);
    expect(updateCheckEnabled({ update_check: false })).toBe(false);
  });
});

/** A staged zip's `file://` artifact, as the backend answers it (`updates.staged_path`). */
const artifactOf = (hash: string) => `file:///data/Moonlight Sync/update/staged/Moonlight-Sync-${hash.slice(0, 12)}.zip`;

describe("stagedMatches: the staging answered what the offer asked for", () => {
  const offer: Offer = { ...release("0.13.0"), action: "update", label: "0.13.0" };
  const good: StagedUpdate = { artifact: artifactOf(hex("a")), hash: hex("a"), version: "0.13.0", build: null };
  const main: Offer = { ...branch("main"), action: "switch", label: "main @ abc1234" };
  const goodMain: StagedUpdate = { artifact: artifactOf(hex("e")), hash: hex("e"), version: "0.12.0", build: buildInfo("main") };

  it("a release: the offer's digest and version", () => {
    expect(stagedMatches(offer, good)).toBe(true);
    // a release's zip may carry a build.json of kind release: it plays no part
    expect(stagedMatches(offer, { ...good, build: buildInfo("v0.13.0", MAIN_SHA, "release") })).toBe(true);
    expect(stagedMatches(offer, { ...good, hash: hex("b") })).toBe(false);
    expect(stagedMatches(offer, { ...good, hash: hex("A") })).toBe(false);
    expect(stagedMatches(offer, { ...good, version: "0.13.1" })).toBe(false);
    expect(stagedMatches(offer, { ...good, version: "v0.13.0" })).toBe(false);
    expect(stagedMatches({ ...offer, digest: null }, good)).toBe(false);
  });

  it("the offer's digest is compared lower-cased", () => {
    expect(stagedMatches({ ...offer, digest: hex("A") }, good)).toBe(true);
  });

  it("a branch build: the digest, and a build.json of kind branch with the offer's ref", () => {
    expect(stagedMatches(main, goodMain)).toBe(true);
    // the version is the zip's own, whatever it is
    expect(stagedMatches(main, { ...goodMain, version: "0.99.0" })).toBe(true);
    expect(stagedMatches(main, { ...goodMain, hash: hex("a") })).toBe(false);
    expect(stagedMatches(main, { ...goodMain, build: null })).toBe(false);
    expect(stagedMatches(main, { ...goodMain, build: buildInfo("main", MAIN_SHA, "release") })).toBe(false);
    expect(stagedMatches(main, { ...goodMain, build: buildInfo("feature/x") })).toBe(false);
    expect(stagedMatches(main, { ...goodMain, build: { ...buildInfo("main"), sha: "abc1234" } })).toBe(false);
  });

  it("an answer whose fields are not strings", () => {
    expect(stagedMatches(offer, { ...good, artifact: null } as unknown as StagedUpdate)).toBe(false);
    expect(stagedMatches(offer, { ...good, version: 13 } as unknown as StagedUpdate)).toBe(false);
    expect(stagedMatches(offer, { ...good, hash: undefined } as unknown as StagedUpdate)).toBe(false);
  });
});

describe("installRequestOf: the staged zip", () => {
  const offer = (o: Partial<Extract<Offer, { kind: "release" }>> = {}): Offer => ({ ...release("0.13.0"), action: "update", label: "0.13.0", ...o });
  const staged: StagedUpdate = { artifact: artifactOf(hex("a")), hash: hex("a"), version: "0.13.0", build: null };

  it("the staged artifact and hash, the plugin's name, the release's version and the type", () => {
    expect(installRequestOf(offer(), staged, "v3.2.9")).toEqual({
      artifact: artifactOf(hex("a")),
      name: "Moonlight Sync",
      version: "0.13.0",
      hash: hex("a"),
      installType: 2,
    });
    expect(installRequestOf(offer({ action: "downgrade" }), staged, "v3.0.4").installType).toBe(2);
    expect(installRequestOf(offer({ action: "reinstall" }), staged, "v3.2.9").installType).toBe(1);
  });

  it("a switch back to a release is install type 4 (2 before loader v3.1.0)", () => {
    expect(installRequestOf(offer({ action: "switch" }), staged, "v3.2.9")).toMatchObject({ version: "0.13.0", installType: 4 });
    expect(installRequestOf(offer({ action: "switch" }), staged, "v3.0.4").installType).toBe(2);
  });

  it("a branch build: the version from the staged zip's own version and build.json", () => {
    const build: Offer = { ...branch("main"), action: "switch", label: "main @ abc1234" };
    const zip: StagedUpdate = {
      artifact: artifactOf(hex("e")),
      hash: hex("e"),
      version: "0.12.0",
      build: buildInfo("main", OTHER_SHA),
    };
    // the zip's commit, not the one the list said
    expect(installRequestOf(build, zip, "v3.2.9")).toEqual({
      artifact: artifactOf(hex("e")),
      name: "Moonlight Sync",
      version: "0.12.0 (main @ fedcba9)",
      hash: hex("e"),
      installType: 4,
    });
    expect(installRequestOf(build, zip, "v3.0.4").installType).toBe(2);
    expect(() => installRequestOf(build, { ...zip, build: null }, "v3.2.9")).toThrow();
  });
});

describe("branchVersionText, the version Decky is handed for a branch build", () => {
  it("<the zip's version> (<ref> @ <first 7 of sha>)", () => {
    expect(branchVersionText("0.12.0", buildInfo("main"))).toBe("0.12.0 (main @ abc1234)");
    expect(branchVersionText("0.12.0", buildInfo("feature/x", OTHER_SHA.toUpperCase()))).toBe("0.12.0 (feature/x @ fedcba9)");
  });
});

describe("the patterns", () => {
  it("REF_RE: TAG_RE plus the slash, 1 to 100 characters", () => {
    for (const ref of ["main", "feature/x", "a.b_c-d", "a".repeat(100)]) expect(REF_RE.test(ref), ref).toBe(true);
    for (const ref of ["", "a b", "a+b", "a@b", "a".repeat(101), "main\n"]) expect(REF_RE.test(ref), ref).toBe(false);
    expect(TAG_RE.test("a/b")).toBe(false);
  });
});

describe("the texts (update spec 3.7)", () => {
  const offer: Offer = { ...release("0.13.0", hex("a"), local(9, 20, 12, 0)), action: "update", label: "0.13.0" };
  const checked: UpdateInfo = { releases: [offer], checkedAt: local(9, 21, 15, 2), error: null };

  it("installedText", () => {
    expect(installedText(at("0.11.0"))).toBe("0.11.0");
    expect(installedText(at(null))).toBe("unknown");
    expect(installedText(null)).toBe("unknown");
    // a release's build.json says nothing more
    expect(installedText(at("0.11.0", buildInfo("v0.11.0", MAIN_SHA, "release", local(9, 21, 13, 3))), now)).toBe("0.11.0");
  });

  it("installedText for a branch build: its ref, the first 7 of its commit, when it was built", () => {
    const main = buildInfo("main", MAIN_SHA, "branch", local(9, 21, 13, 3));
    expect(installedText(at("0.11.0", main), now)).toBe("0.11.0 · main @ abc1234 · built today 13:03");
    expect(installedText(at("0.11.0", { ...main, built_at: null }), now)).toBe("0.11.0 · main @ abc1234");
    expect(installedText(at(null, main), now)).toBe("unknown · main @ abc1234 · built today 13:03");
  });

  it("builtFromText: About's row, for a branch's build, a release's and a zip that says nothing", () => {
    const main = buildInfo("main", MAIN_SHA, "branch", local(9, 21, 13, 3));
    expect(builtFromText(main, now)).toBe("main @ abc1234 · built today 13:03");
    // a build made outside CI: no run, the same text
    expect(builtFromText({ ...main, run: null }, now)).toBe("main @ abc1234 · built today 13:03");
    expect(builtFromText({ ...main, built_at: null }, now)).toBe("main @ abc1234");
    expect(builtFromText({ ...main, sha: MAIN_SHA.toUpperCase() }, now)).toBe("main @ abc1234 · built today 13:03");
    expect(builtFromText(buildInfo("v0.11.0", MAIN_SHA, "release", local(9, 21, 13, 3)), now)).toBe(
      "v0.11.0 @ abc1234 · built today 13:03",
    );
    expect(builtFromText(null, now)).toBe(BUILD_UNKNOWN_TEXT);
    expect(builtFromText(undefined, now)).toBe(BUILD_UNKNOWN_TEXT);
  });

  it("latestText, row by row", () => {
    expect(latestText(checked, "checking", offer, "stable", now)).toBe("Checking…");
    expect(latestText({ releases: null, checkedAt: null, error: null }, "idle", null, "stable", now)).toBe(
      "Not checked yet",
    );
    expect(latestText(checked, "idle", offer, "stable", now)).toBe("0.13.0 · released yesterday 12:00 · checked today 15:02");
    expect(latestText(checked, "idle", null, "stable", now)).toBe("Up to date · checked today 15:02");
    const network = { ok: false as const, error: "network" as const, message: "GitHub answered 502", retryAt: null };
    expect(latestText({ ...checked, error: network }, "idle", offer, "stable", now)).toBe(
      "Could not reach GitHub: GitHub answered 502 · last checked today 15:02",
    );
    expect(latestText({ releases: null, checkedAt: null, error: network }, "idle", null, "stable", now)).toBe(
      "Could not reach GitHub: GitHub answered 502",
    );
    const limited = { ok: false as const, error: "rate-limited" as const, message: "", retryAt: local(9, 21, 15, 42) };
    expect(latestText({ releases: null, checkedAt: null, error: limited }, "idle", null, "stable", now)).toBe(
      "GitHub is limiting requests from this network. Try again in 12 minutes",
    );
  });

  it("latestText on a branch channel", () => {
    const main = branch("main", buildInfo("main", MAIN_SHA, "branch", local(9, 21, 13, 3)), local(9, 21, 13, 5));
    const update: UpdateInfo = { releases: [release("0.13.0"), main], checkedAt: local(9, 21, 15, 2), error: null };
    const switchTo: Offer = { ...main, action: "switch", label: "main @ abc1234" };
    expect(latestText(update, "idle", switchTo, "branch:main", now)).toBe(
      "main @ abc1234 · built today 13:03 · checked today 15:02",
    );
    // without built_at, the zip's upload time
    const undated: Offer = { ...switchTo, build: { ...main.build!, built_at: null } };
    expect(latestText(update, "idle", undated, "branch:main", now)).toBe(
      "main @ abc1234 · built today 13:05 · checked today 15:02",
    );
    // the installed build is the branch's
    expect(latestText(update, "idle", null, "branch:main", now)).toBe("Up to date · checked today 15:02");
    // no entry for the ref, or its build.json unread (as while it is republished)
    expect(latestText(update, "idle", null, "branch:gone", now)).toBe("No build of gone is published");
    const unread = { ...update, releases: [release("0.13.0"), { ...main, build: null }] };
    expect(latestText(unread, "idle", null, "branch:main", now)).toBe("No build of main is published");
    // the rows before it come first
    expect(latestText(unread, "checking", null, "branch:main", now)).toBe("Checking…");
    expect(latestText({ releases: null, checkedAt: null, error: null }, "idle", null, "branch:main", now)).toBe(
      "Not checked yet",
    );
    const network = { ok: false as const, error: "network" as const, message: "no answer from GitHub", retryAt: null };
    expect(latestText({ ...unread, error: network }, "idle", null, "branch:main", now)).toBe(
      "Could not reach GitHub: no answer from GitHub · last checked today 15:02",
    );
    // a channel that does not parse is stable
    expect(latestText(unread, "idle", null, "branch:", now)).toBe("Up to date · checked today 15:02");
  });

  it("versionLabel: the date, or reinstall", () => {
    expect(versionLabel(offer)).toBe("0.13.0 · 2026-10-20");
    expect(versionLabel({ ...offer, action: "downgrade" })).toBe("0.13.0 · 2026-10-20");
    expect(versionLabel({ ...offer, action: "reinstall" })).toBe("0.13.0 · reinstall");
  });

  it("installButtonText", () => {
    expect(installButtonText(offer, "idle")).toBe("Update to 0.13.0");
    expect(installButtonText(offer, "checking")).toBe("Update to 0.13.0");
    expect(installButtonText(offer, "downloading")).toBe("Downloading…");
    expect(installButtonText(offer, "asking")).toBe("Waiting for Decky…");
  });

  it("installButtonText for a switch, to a branch build or back to a release", () => {
    const build: Offer = { ...branch("main"), action: "switch", label: "main @ abc1234" };
    expect(installButtonText(build, "idle")).toBe("Switch to main @ abc1234");
    expect(installButtonText({ ...offer, action: "switch" }, "idle")).toBe("Switch to 0.13.0");
    expect(installButtonText(build, "downloading")).toBe("Downloading…");
    expect(installButtonText(build, "asking")).toBe("Waiting for Decky…");
  });
});
