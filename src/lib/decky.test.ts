import { describe, expect, it } from "vitest";

import {
  deckyInstaller,
  FILE_ARTIFACT_PREFIX,
  INSTALL_ROUTE,
  REF_RE as DECKY_REF_RE,
  STAGED_DIR,
  STAGED_FILE_PREFIX,
  STAGED_FILE_SUFFIX,
  STAGED_HASH_DIGITS,
  type InstallRequest,
} from "./decky";
import { ASSET, assetUrl, BUILD_ASSET, branchVersionText, PLUGIN_NAME, REF_RE } from "./updates";

const HASH = "a".repeat(64);
const OTHER_HASH = "b".repeat(64);
/** Where the backend stages a zip: the runtime directory has a space in it (update spec 2.3). */
const RUNTIME = "/data/homebrew/data/Moonlight Sync";
const staged = (hash = HASH, runtime = RUNTIME) => `file://${runtime}/update/staged/Moonlight-Sync-${hash.slice(0, 12)}.zip`;
const ARTIFACT = staged();
const GOOD: InstallRequest = { artifact: ARTIFACT, name: "Moonlight Sync", version: "0.13.0", hash: HASH, installType: 2 };
const BRANCH_VERSION = "0.12.0 (main @ abc1234)";

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
  it("are the route, a file:// artifact and the backend's staged name", () => {
    expect(INSTALL_ROUTE).toBe("utilities/install_plugin");
    expect(FILE_ARTIFACT_PREFIX).toBe("file:///");
    expect(`${STAGED_DIR}${STAGED_FILE_PREFIX}${"c".repeat(STAGED_HASH_DIGITS)}${STAGED_FILE_SUFFIX}`).toBe(
      "/update/staged/Moonlight-Sync-cccccccccccc.zip",
    );
    expect(GOOD.name).toBe(PLUGIN_NAME);
  });

  it("the ref pattern equals updates.ts's, spelled separately", () => {
    expect(DECKY_REF_RE.source).toBe(REF_RE.source);
    expect(DECKY_REF_RE.flags).toBe(REF_RE.flags);
  });

  it("branchVersionText's shape is accepted", async () => {
    const { router, calls } = fakeRouter();
    const version = branchVersionText("0.12.0", { ref: "feature/x", sha: "fedcba9".padEnd(40, "0") });
    expect(await deckyInstaller({ DeckyBackend: router }).request({ ...GOOD, version })).toBe(true);
    expect(calls[0][3]).toBe("0.12.0 (feature/x @ fedcba9)");
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
    expect(calls).toEqual([[INSTALL_ROUTE, ARTIFACT, "Moonlight Sync", "0.13.0", HASH, 2]]);
  });

  it("the staged path is handed as it is: raw, the space unencoded", async () => {
    const { router, calls } = fakeRouter();
    await deckyInstaller({ DeckyBackend: router }).request(GOOD);
    expect(calls[0][1]).toBe("file:///data/homebrew/data/Moonlight Sync/update/staged/Moonlight-Sync-aaaaaaaaaaaa.zip");
  });

  it("any absolute runtime directory, the shortest included", async () => {
    const { router, calls } = fakeRouter();
    for (const runtime of ["", "/x", "/a b/c-d/e_f.g"]) {
      expect(await deckyInstaller({ DeckyBackend: router }).request({ ...GOOD, artifact: staged(HASH, runtime) }), runtime).toBe(
        true,
      );
    }
    expect(calls).toHaveLength(3);
  });

  it("a branch build's version: <version> (<ref> @ <7 hex>)", async () => {
    const { router, calls } = fakeRouter();
    for (const version of [BRANCH_VERSION, "0.12.0 (feature/x.y_z-1 @ 0123456)", "1.2.3-rc.1+b (a @ fffffff)"]) {
      expect(await deckyInstaller({ DeckyBackend: router }).request({ ...GOOD, version }), version).toBe(true);
    }
    expect(calls.map((call) => call[3])).toEqual([
      BRANCH_VERSION,
      "0.12.0 (feature/x.y_z-1 @ 0123456)",
      "1.2.3-rc.1+b (a @ fffffff)",
    ]);
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
  const dir = `${RUNTIME}/update/staged`;
  const name = `Moonlight-Sync-${HASH.slice(0, 12)}.zip`;
  const refusals: [string, Partial<Record<keyof InstallRequest, unknown>>][] = [
    // no URL at all (update spec 3.12.5)
    ["the release's https URL", { artifact: assetUrl("v0.13.0", ASSET) }],
    ["an https URL ending in the staged name", { artifact: `https://github.invalid/update/staged/${name}` }],
    ["an http URL", { artifact: assetUrl("v0.13.0", ASSET).replace("https:", "http:") }],
    ["another asset's URL", { artifact: assetUrl("build-main", BUILD_ASSET) }],
    ["file://host/", { artifact: `file://localhost${dir}/${name}` }],
    ["file:/ (one slash)", { artifact: `file:${dir}/${name}` }],
    ["FILE:///", { artifact: ARTIFACT.replace("file://", "FILE://") }],
    ["File:///", { artifact: ARTIFACT.replace("file://", "File://") }],
    ["a bare absolute path", { artifact: `${dir}/${name}` }],
    ["a relative path", { artifact: `update/staged/${name}` }],
    ["file:// and a relative path", { artifact: `file://update/staged/${name}` }],
    ["a leading space", { artifact: ` ${ARTIFACT}` }],
    // the path's shape
    ["the name in the middle of the path", { artifact: `file://${dir}/${name}/x.zip` }],
    ["the name with something after it", { artifact: `${ARTIFACT}.zip` }],
    ["the name alone, not under update/staged", { artifact: `file://${RUNTIME}/${name}` }],
    ["another zip under the runtime directory", { artifact: `file://${RUNTIME}/update/Moonlight-Sync-${HASH.slice(0, 12)}.zip` }],
    ["another zip in the staged directory", { artifact: `file://${dir}/Moonlight-Sync.zip` }],
    ["the staged directory's part file", { artifact: `file://${dir}/${name}.part` }],
    ["a name one digit short", { artifact: `file://${dir}/Moonlight-Sync-${HASH.slice(0, 11)}.zip` }],
    ["a name with the whole hash", { artifact: `file://${dir}/Moonlight-Sync-${HASH}.zip` }],
    ["upper-case digits in the name", { artifact: `file://${dir}/Moonlight-Sync-${"A".repeat(12)}.zip` }],
    ["a name of another hash", { artifact: staged(OTHER_HASH) }],
    ["a .. step", { artifact: `file://${RUNTIME}/../x/update/staged/${name}` }],
    ["a . step", { artifact: `file://${RUNTIME}/./update/staged/${name}` }],
    ["an empty step", { artifact: `file://${RUNTIME}//update/staged/${name}` }],
    ["a trailing .. over the name", { artifact: `${ARTIFACT}/..` }],
    ["a backslash", { artifact: `file://${RUNTIME}\\x/update/staged/${name}` }],
    ["a query", { artifact: `file://${dir}/?/../${name}` }],
    ["a query after the name", { artifact: `${ARTIFACT}?x=1` }],
    ["a fragment", { artifact: `file://${dir}#/${name}` }],
    ["a percent sign", { artifact: `file://${RUNTIME.replace(" ", "%20")}/update/staged/${name}` }],
    ["an encoded dot-dot", { artifact: `file://${RUNTIME}/%2e%2e/update/staged/${name}` }],
    ["a newline", { artifact: `file://${RUNTIME}\n/update/staged/${name}` }],
    ["a newline at the end", { artifact: `${ARTIFACT}\n` }],
    ["a NUL", { artifact: `file://${RUNTIME}\u0000/update/staged/${name}` }],
    ["a tab", { artifact: `file://${RUNTIME}\t/update/staged/${name}` }],
    ["DEL", { artifact: `file://${RUNTIME}\u007f/update/staged/${name}` }],
    ["a C1 control character", { artifact: `file://${RUNTIME}\u0085/update/staged/${name}` }],
    ["a line separator", { artifact: `file://${RUNTIME}${String.fromCharCode(0x2028)}/update/staged/${name}` }],
    ["file:/// alone", { artifact: "file:///" }],
    ["a non-string artifact", { artifact: { toString: () => ARTIFACT } }],
    // the hash
    ["a short hash", { hash: "a".repeat(63) }],
    ["a long hash", { hash: "a".repeat(65) }],
    ["an empty hash", { hash: "" }],
    ["an upper-case hash", { hash: "A".repeat(64) }],
    ["a prefixed hash", { hash: `sha256:${"a".repeat(64)}` }],
    ["a non-hex hash", { hash: "g".repeat(64) }],
    ["a non-string hash", { hash: 123 }],
    ["a hash whose first 12 digits are not the file's", { hash: `${"a".repeat(11)}b${"a".repeat(52)}` }],
    // the name
    ["another name", { name: "Other Plugin" }],
    ["the zip's file name", { name: "Moonlight-Sync.zip" }],
    ["a name with a space around", { name: " Moonlight Sync" }],
    // the version
    ["dev", { version: "dev" }],
    ["Dev", { version: "Dev" }],
    ["DEV", { version: "DEV" }],
    ["an empty version", { version: "" }],
    ["a version with whitespace", { version: " 0.13.0" }],
    ["a version with a slash", { version: "0.13.0/../x" }],
    ["a non-string version", { version: 13 }],
    // a branch build's version
    ["dev as a branch build's version", { version: "dev (main @ abc1234)" }],
    ["Dev as a branch build's version", { version: "Dev (main @ abc1234)" }],
    ["a branch build's version without a version", { version: " (main @ abc1234)" }],
    ["a branch build's version without a ref", { version: "0.12.0 ( @ abc1234)" }],
    ["a ref outside REF_RE", { version: "0.12.0 (main+x @ abc1234)" }],
    ["a ref of 101 characters", { version: `0.12.0 (${"a".repeat(101)} @ abc1234)` }],
    ["six hex digits", { version: "0.12.0 (main @ abc123)" }],
    ["eight hex digits", { version: "0.12.0 (main @ abc12345)" }],
    ["upper-case hex digits", { version: "0.12.0 (main @ ABC1234)" }],
    ["no space before the parenthesis", { version: "0.12.0(main @ abc1234)" }],
    ["two spaces", { version: "0.12.0  (main @ abc1234)" }],
    ["no closing parenthesis", { version: "0.12.0 (main @ abc1234" }],
    ["something after it", { version: "0.12.0 (main @ abc1234) x" }],
    ["a newline after it", { version: `${BRANCH_VERSION}\n` }],
    ["a version with a slash, in a branch build's", { version: "0.12/0 (main @ abc1234)" }],
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
        return reads === 1 ? ARTIFACT : assetUrl("v0.13.0", ASSET);
      },
    } as InstallRequest;
    expect(await deckyInstaller({ DeckyBackend: router }).request(shifty)).toBe(true);
    expect(calls[0][1]).toBe(ARTIFACT);
    expect(reads).toBe(1);
  });

  it("a hash whose getter changes its answer is sent as it was checked", async () => {
    const { router, calls } = fakeRouter();
    let reads = 0;
    const shifty = {
      ...GOOD,
      get hash() {
        reads++;
        return reads === 1 ? HASH : OTHER_HASH;
      },
    } as InstallRequest;
    expect(await deckyInstaller({ DeckyBackend: router }).request(shifty)).toBe(true);
    expect(calls[0][4]).toBe(HASH);
  });
});
