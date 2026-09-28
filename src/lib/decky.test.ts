import { describe, expect, it } from "vitest";

import { deckyInstaller, INSTALL_ROUTE, RELEASE_URL_PREFIX, type InstallRequest } from "./decky";
import { ASSET, DOWNLOAD_BASE, PLUGIN_NAME } from "./updates";

const URL = `${RELEASE_URL_PREFIX}v0.13.0/Moonlight-Sync.zip`;
const HASH = "a".repeat(64);
const GOOD: InstallRequest = { artifact: URL, name: "Moonlight Sync", version: "0.13.0", hash: HASH, installType: 2 };

/** A stand-in for Decky's websocket router: records each call, answers or throws. */
function fakeRouter(answer: "resolve" | "reject" | "throw" = "resolve") {
  const calls: unknown[][] = [];
  return {
    calls,
    router: {
      call(...args: unknown[]) {
        calls.push(args);
        if (answer === "throw") throw new Error("socket closed");
        return answer === "reject" ? Promise.reject(new Error("unknown route")) : Promise.resolve(undefined);
      },
    },
  };
}

describe("the allowlist's constants", () => {
  it("equal updates.ts's, spelled separately", () => {
    expect(RELEASE_URL_PREFIX).toBe(`${DOWNLOAD_BASE}/`);
    expect(RELEASE_URL_PREFIX).toBe("https://github.com/episode6/moonlight-steam-sync-decky/releases/download/");
    expect(INSTALL_ROUTE).toBe("utilities/install_plugin");
    expect(GOOD.name).toBe(PLUGIN_NAME);
    expect(URL.endsWith(`/${ASSET}`)).toBe(true);
  });
});

describe("finding Decky's router", () => {
  it("on the scope itself (SharedJSContext)", async () => {
    const { router, calls } = fakeRouter();
    const installer = deckyInstaller({ DeckyBackend: router });
    expect(installer.available()).toBe(true);
    expect(await installer.request(GOOD)).toBe(true);
    expect(calls).toHaveLength(1);
  });

  it("else on window.opener (the other windows)", async () => {
    const { router, calls } = fakeRouter();
    const installer = deckyInstaller({ DeckyBackend: undefined, opener: { DeckyBackend: router } });
    expect(installer.available()).toBe(true);
    expect(await installer.request(GOOD)).toBe(true);
    expect(calls).toHaveLength(1);
  });

  it("absent: not available, and nothing asked", async () => {
    for (const scope of [{}, null, undefined, { opener: null }, { DeckyBackend: {} }, { DeckyBackend: { call: "no" } }]) {
      const installer = deckyInstaller(scope);
      expect(installer.available()).toBe(false);
      expect(await installer.request(GOOD)).toBe(false);
    }
  });

  it("the default scope is globalThis, where the tests have no router", () => {
    expect(deckyInstaller().available()).toBe(false);
  });

  it("a getter that throws reads as absent", async () => {
    const throwing = {
      get DeckyBackend(): unknown {
        throw new Error("denied");
      },
      get opener(): unknown {
        throw new Error("denied");
      },
    };
    expect(deckyInstaller(throwing).available()).toBe(false);
    expect(await deckyInstaller(throwing).request(GOOD)).toBe(false);
    // the scope's own throws, the opener's is still found
    const { router, calls } = fakeRouter();
    const half = {
      get DeckyBackend(): unknown {
        throw new Error("denied");
      },
      opener: { DeckyBackend: router },
    };
    expect(await deckyInstaller(half).request(GOOD)).toBe(true);
    expect(calls).toHaveLength(1);
  });
});

describe("the call", () => {
  it("is the install route with the five arguments, positional, in Decky's order", async () => {
    const { router, calls } = fakeRouter();
    await deckyInstaller({ DeckyBackend: router }).request(GOOD);
    expect(calls).toEqual([[INSTALL_ROUTE, URL, "Moonlight Sync", "0.13.0", HASH, 2]]);
  });

  it("a call that rejects or throws answers false", async () => {
    expect(await deckyInstaller({ DeckyBackend: fakeRouter("reject").router }).request(GOOD)).toBe(false);
    expect(await deckyInstaller({ DeckyBackend: fakeRouter("throw").router }).request(GOOD)).toBe(false);
  });

  it("each install type from 1 to 4 is accepted", async () => {
    const { router, calls } = fakeRouter();
    for (const installType of [1, 2, 3, 4]) {
      expect(await deckyInstaller({ DeckyBackend: router }).request({ ...GOOD, installType })).toBe(true);
    }
    expect(calls.map((call) => call[5])).toEqual([1, 2, 3, 4]);
  });
});

describe("the refusals: nothing is asked of Decky", () => {
  const refusals: [string, Partial<Record<keyof InstallRequest, unknown>>][] = [
    // the artifact
    ["a file:// artifact", { artifact: "file:///tmp/Moonlight-Sync.zip" }],
    ["another repository", { artifact: "https://github.com/someone/else/releases/download/v0.13.0/Moonlight-Sync.zip" }],
    ["a look-alike repository", { artifact: "https://github.com/episode6/moonlight-steam-sync-decky-fork/releases/download/v1/Moonlight-Sync.zip" }],
    ["http", { artifact: URL.replace("https:", "http:") }],
    ["upper-case host", { artifact: URL.replace("github.com", "GitHub.com") }],
    ["a URL with ..", { artifact: `${RELEASE_URL_PREFIX}../../other/Moonlight-Sync.zip` }],
    ["a tag with .. inside", { artifact: `${RELEASE_URL_PREFIX}v1..2/Moonlight-Sync.zip` }],
    ["a tag of one dot", { artifact: `${RELEASE_URL_PREFIX}./Moonlight-Sync.zip` }],
    ["an encoded dot-dot", { artifact: `${RELEASE_URL_PREFIX}%2e%2e/%2e%2e/Moonlight-Sync.zip` }],
    ["an encoded slash", { artifact: `${RELEASE_URL_PREFIX}v0.13.0%2F..%2FMoonlight-Sync.zip` }],
    ["a backslash", { artifact: `${RELEASE_URL_PREFIX}v0.13.0\\Moonlight-Sync.zip` }],
    ["a query", { artifact: `${URL}?x=1` }],
    ["a fragment", { artifact: `${URL}#x` }],
    ["a space", { artifact: `${RELEASE_URL_PREFIX}v0.13.0 /Moonlight-Sync.zip` }],
    ["a newline", { artifact: `${URL}\n` }],
    ["a control character", { artifact: `${RELEASE_URL_PREFIX}v0.13.0\u0000/Moonlight-Sync.zip` }],
    ["another asset", { artifact: `${RELEASE_URL_PREFIX}v0.13.0/moonlight-steam-sync.pyz` }],
    ["a deeper path", { artifact: `${RELEASE_URL_PREFIX}v0.13.0/x/Moonlight-Sync.zip` }],
    ["no tag", { artifact: `${RELEASE_URL_PREFIX}Moonlight-Sync.zip` }],
    ["the prefix alone", { artifact: RELEASE_URL_PREFIX }],
    ["a non-string artifact", { artifact: { toString: () => URL } }],
    // the hash
    ["a short hash", { hash: "a".repeat(63) }],
    ["a long hash", { hash: "a".repeat(65) }],
    ["an empty hash", { hash: "" }],
    ["an upper-case hash", { hash: "A".repeat(64) }],
    ["a prefixed hash", { hash: `sha256:${"a".repeat(64)}` }],
    ["a non-hex hash", { hash: "g".repeat(64) }],
    ["a non-string hash", { hash: 123 }],
    // the name
    ["another name", { name: "Other Plugin" }],
    ["the zip's file name", { name: "Moonlight-Sync.zip" }],
    ["a name with a space around", { name: " Moonlight Sync" }],
    // the version
    ["dev", { version: "dev" }],
    ["Dev", { version: "Dev" }],
    ["an empty version", { version: "" }],
    ["a version with whitespace", { version: " 0.13.0" }],
    ["a version with a slash", { version: "0.13.0/../x" }],
    ["a non-string version", { version: 13 }],
    // the install type
    ["install type 0", { installType: 0 }],
    ["install type 5", { installType: 5 }],
    ["a fractional install type", { installType: 2.5 }],
    ["NaN", { installType: Number.NaN }],
    ["a string install type", { installType: "2" }],
  ];

  for (const [what, change] of refusals) {
    it(what, async () => {
      const { router, calls } = fakeRouter();
      const req = { ...GOOD, ...change } as InstallRequest;
      expect(await deckyInstaller({ DeckyBackend: router }).request(req)).toBe(false);
      expect(calls).toEqual([]);
    });
  }

  it("a request that is not an object", async () => {
    const { router, calls } = fakeRouter();
    expect(await deckyInstaller({ DeckyBackend: router }).request(null as unknown as InstallRequest)).toBe(false);
    expect(calls).toEqual([]);
  });

  it("a request whose getters change their answer is sent as it was checked", async () => {
    const { router, calls } = fakeRouter();
    let reads = 0;
    const shifty = {
      ...GOOD,
      get artifact() {
        reads++;
        return reads === 1 ? URL : "https://elsewhere.invalid/evil.zip";
      },
    } as InstallRequest;
    expect(await deckyInstaller({ DeckyBackend: router }).request(shifty)).toBe(true);
    expect(calls[0][1]).toBe(URL);
  });
});
