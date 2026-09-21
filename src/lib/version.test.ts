import { describe, expect, it } from "vitest";

import { bundledLine, cliStatus, compareVersions, parseVersion } from "./version";

describe("parseVersion", () => {
  it("reads X.Y.Z and ignores suffixes, like the backend", () => {
    expect(parseVersion("0.3.0")).toEqual([0, 3, 0]);
    expect(parseVersion("0.4.0.dev1")).toEqual([0, 4, 0]);
    expect(parseVersion("1.2.3rc1")).toEqual([1, 2, 3]);
    expect(parseVersion("v0.3")).toBeNull();
    expect(parseVersion("")).toBeNull();
    expect(parseVersion(null)).toBeNull();
  });

  it("compares numerically", () => {
    expect(compareVersions([0, 10, 0], [0, 9, 9])).toBe(1);
    expect(compareVersions([0, 3, 0], [0, 3, 0])).toBe(0);
    expect(compareVersions([0, 2, 9], [0, 3, 0])).toBe(-1);
  });
});

describe("cliStatus (spec 3.6.1)", () => {
  it("missing", () => {
    expect(cliStatus({ installed: null, minimum: "0.4.0", too_old: false })).toEqual({
      state: "missing",
      text: "CLI not installed — see About",
    });
  });

  it("too old", () => {
    expect(cliStatus({ installed: "0.2.0", minimum: "0.4.0", too_old: true })).toEqual({
      state: "too-old",
      text: "CLI too old (0.2.0, needs 0.4.0) — see About",
    });
    // the frontend agrees even if the flag were missing
    expect(cliStatus({ installed: "0.2.9", minimum: "0.4.0", too_old: false }).state).toBe("too-old");
  });

  it("ok for the minimum and newer", () => {
    expect(cliStatus({ installed: "0.4.0", minimum: "0.4.0", too_old: false }).state).toBe("ok");
    expect(cliStatus({ installed: "1.0.0", minimum: "0.4.0", too_old: false }).text).toBe("");
  });

  it("explains a zip built before the CLI release", () => {
    expect(bundledLine({ bundled: null, minimum: "0.4.0" })).toBe(
      "none (built before the CLI release); install it with the CLI's install.sh",
    );
    expect(bundledLine({ bundled: "0.4.0", minimum: "0.4.0" })).toBe("0.4.0");
  });
});
