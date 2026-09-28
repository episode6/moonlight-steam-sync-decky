import { describe, expect, it } from "vitest";

import { fixtureText } from "../test/fixtures";
import { RELEASE_ASSET, RELEASE_URL_PREFIX } from "./decky";
import {
  ASSET,
  assetUrl,
  checkReleases,
  DOWNLOAD_BASE,
  installable,
  installButtonText,
  installedText,
  installRequestOf,
  installType,
  latestText,
  loaderSupported,
  MIN_UPDATER_VERSION,
  NOTES_MAX_CHARS,
  offerOf,
  parseReleases,
  PLUGIN_NAME,
  RELEASES_API,
  REPO,
  updateCheckEnabled,
  versionLabel,
  type HttpAnswer,
  type NetPort,
  type Offer,
  type Release,
  type UpdateInfo,
} from "./updates";

const RAW: unknown = JSON.parse(fixtureText("update/releases.json"));
const RELEASES = parseReleases(RAW);
const hex = (digit: string) => digit.repeat(64);

const now = new Date(2026, 9, 21, 15, 30);
const local = (m: number, d: number, h: number, min: number) => new Date(2026, m, d, h, min).toISOString();

function release(version: string, digest: string | null = hex("a"), publishedAt = "2026-10-01T12:00:00Z"): Release {
  return { tag: `v${version}`, kind: "release", version, publishedAt, notes: "", size: 1, digest };
}

function answer(status: number, text = "", headers: Partial<HttpAnswer["headers"]> = {}): HttpAnswer {
  return {
    status,
    headers: { "x-ratelimit-remaining": null, "x-ratelimit-reset": null, "retry-after": null, etag: null, ...headers },
    text,
  };
}

/** A NetPort that answers once from a script and records what it was asked. */
function scripted(reply: HttpAnswer | Error) {
  const asked: [string, Record<string, string>][] = [];
  const net: NetPort = {
    async get(url, headers) {
      asked.push([url, headers]);
      if (reply instanceof Error) throw reply;
      return reply;
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

  it("agree with decky.ts's allowlist, which spells its own", () => {
    expect(RELEASE_URL_PREFIX).toBe(`${DOWNLOAD_BASE}/`);
    expect(RELEASE_ASSET).toBe(ASSET);
  });
});

describe("parseReleases (the fixture)", () => {
  it("keeps the published releases with a vX.Y.Z tag and the zip, highest first", () => {
    // Skipped: the draft, the prerelease, build-main (a prerelease until
    // phase 2), v0.12.2 (no zip), v1.2 (not vX.Y.Z) and the string entry.
    expect(RELEASES.map((r) => r.tag)).toEqual(["v0.13.0", "v0.12.1", "v0.12.0", "v0.11.0"]);
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
    expect(await checkReleases(net, () => at)).toMatchObject({ error: "rate-limited", retryAt: "2026-10-21T13:02:00.000Z" });
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

describe("offerOf", () => {
  it("offers the highest installable release when it is newer", () => {
    expect(offerOf("0.12.0", RELEASES)).toMatchObject({ tag: "v0.13.0", action: "update", label: "0.13.0" });
    expect(offerOf("0.12.0-dev", RELEASES)).toMatchObject({ tag: "v0.13.0" });
  });

  it("nothing when the installed one is equal or newer", () => {
    expect(offerOf("0.13.0", RELEASES)).toBeNull();
    expect(offerOf("0.14.0", RELEASES)).toBeNull();
  });

  it("never a release without a digest, nor one below the minimum", () => {
    // the highest has no digest: the next one with a digest is offered
    expect(offerOf("0.12.0", [release("0.13.1", null), release("0.13.0")])).toMatchObject({ tag: "v0.13.0" });
    expect(offerOf("0.12.0", [release("0.13.0", null)])).toBeNull();
    expect(offerOf("0.10.0", [release("0.11.0")])).toBeNull();
  });

  it("nothing when the installed version does not parse, or before a check", () => {
    for (const installed of [null, undefined, "", "dev", "unknown"]) expect(offerOf(installed, RELEASES)).toBeNull();
    expect(offerOf("0.12.0", null)).toBeNull();
  });
});

describe("installable (Install another version)", () => {
  it("every release with a digest from the minimum up, each against the installed version", () => {
    expect(installable("0.12.0", RELEASES).map((o) => [o.tag, o.action, o.label])).toEqual([
      ["v0.13.0", "update", "0.13.0"],
      ["v0.12.0", "reinstall", "0.12.0"],
    ]);
    expect(installable("0.13.0", RELEASES).map((o) => [o.tag, o.action])).toEqual([
      ["v0.13.0", "reinstall"],
      ["v0.12.0", "downgrade"],
    ]);
  });

  it("leaves out no digest and below the minimum", () => {
    const tags = installable("0.12.0", RELEASES).map((o) => o.tag);
    expect(tags).not.toContain("v0.12.1"); // null digest
    expect(tags).not.toContain("v0.11.0"); // below MIN_UPDATER_VERSION
  });

  it("nothing when the installed version does not parse", () => {
    expect(installable("dev", RELEASES)).toEqual([]);
    expect(installable(null, RELEASES)).toEqual([]);
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

describe("installRequestOf", () => {
  const offer = (o: Partial<Offer> = {}): Offer => ({ ...release("0.13.0"), action: "update", label: "0.13.0", ...o });

  it("the asset's URL, the plugin's name, the version, the digest and the type", () => {
    expect(installRequestOf(offer(), "v3.2.9")).toEqual({
      artifact: "https://github.com/episode6/moonlight-steam-sync-decky/releases/download/v0.13.0/Moonlight-Sync.zip",
      name: "Moonlight Sync",
      version: "0.13.0",
      hash: hex("a"),
      installType: 2,
    });
    expect(installRequestOf(offer({ action: "downgrade" }), "v3.0.4").installType).toBe(2);
    expect(installRequestOf(offer({ action: "reinstall" }), "v3.2.9").installType).toBe(1);
  });

  it("throws without a digest", () => {
    expect(() => installRequestOf(offer({ digest: null }), "v3.2.9")).toThrow();
  });
});

describe("the texts (update spec 3.7)", () => {
  const offer: Offer = { ...release("0.13.0", hex("a"), local(9, 20, 12, 0)), action: "update", label: "0.13.0" };
  const checked: UpdateInfo = { releases: [offer], checkedAt: local(9, 21, 15, 2), error: null };

  it("installedText", () => {
    expect(installedText("0.11.0")).toBe("0.11.0");
    expect(installedText(null)).toBe("unknown");
  });

  it("latestText, row by row", () => {
    expect(latestText(checked, "checking", offer, now)).toBe("Checking…");
    expect(latestText({ releases: null, checkedAt: null, error: null }, "idle", null, now)).toBe("Not checked yet");
    expect(latestText(checked, "idle", offer, now)).toBe("0.13.0 · released yesterday 12:00 · checked today 15:02");
    expect(latestText(checked, "idle", null, now)).toBe("Up to date · checked today 15:02");
    const network = { ok: false as const, error: "network" as const, message: "GitHub answered 502", retryAt: null };
    expect(latestText({ ...checked, error: network }, "idle", offer, now)).toBe(
      "Could not reach GitHub: GitHub answered 502 · last checked today 15:02",
    );
    expect(latestText({ releases: null, checkedAt: null, error: network }, "idle", null, now)).toBe(
      "Could not reach GitHub: GitHub answered 502",
    );
    const limited = { ok: false as const, error: "rate-limited" as const, message: "", retryAt: local(9, 21, 15, 42) };
    expect(latestText({ releases: null, checkedAt: null, error: limited }, "idle", null, now)).toBe(
      "GitHub is limiting requests from this network. Try again in 12 minutes",
    );
  });

  it("versionLabel: the date, or reinstall", () => {
    expect(versionLabel(offer)).toBe("0.13.0 · 2026-10-20");
    expect(versionLabel({ ...offer, action: "downgrade" })).toBe("0.13.0 · 2026-10-20");
    expect(versionLabel({ ...offer, action: "reinstall" })).toBe("0.13.0 · reinstall");
  });

  it("installButtonText", () => {
    expect(installButtonText(offer, "idle")).toBe("Update to 0.13.0");
    expect(installButtonText(offer, "checking")).toBe("Update to 0.13.0");
    expect(installButtonText(offer, "asking")).toBe("Waiting for Decky…");
  });
});
