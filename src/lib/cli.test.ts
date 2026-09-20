import { describe, expect, it } from "vitest";

import { errorText, isSteamUserMismatch, makeBackend, type CallableFactory, type Failure } from "./cli";

const fail = (error: Failure["error"], extra: Partial<Failure> = {}): Failure => ({
  ok: false,
  error,
  message: "backend text",
  ...extra,
});

describe("errorText (spec 3.8 error strings)", () => {
  it("maps every code once", () => {
    expect(errorText(fail("cli-missing"))).toBe("CLI not installed — see About");
    expect(errorText(fail("cli-too-old", { installed: "0.2.0", minimum: "0.3.0" }))).toBe(
      "CLI too old (0.2.0, needs 0.3.0) — see About",
    );
    expect(errorText(fail("cli-protocol"))).toBe(
      "The installed CLI did not understand the request (see the log)",
    );
    expect(errorText(fail("cli-error", { message: "list: moonlight: host X unreachable" }))).toBe(
      "list: moonlight: host X unreachable",
    );
    expect(errorText(fail("timeout", { timeout_s: 90 }))).toBe("Timed out after 90 s");
    expect(errorText(fail("busy"))).toBe("A sync is already running");
    expect(errorText(fail("owned-apps-missing"))).toBe("Steam library not loaded");
    expect(errorText(fail("owned-apps-empty"))).toBe("Steam library not loaded");
    expect(errorText(fail("bad-request"))).toBe("backend text");
    expect(errorText(fail("io"))).toBe("backend text");
  });

  it("spots the steamid3 mismatch", () => {
    expect(
      isSteamUserMismatch({
        error: "cli-error",
        message: "sync: owned-apps file is for Steam user 1 but sync would write to user 2",
      }),
    ).toBe(true);
    expect(isSteamUserMismatch({ error: "io", message: "owned-apps file is for Steam user" })).toBe(false);
    expect(isSteamUserMismatch(null)).toBe(false);
  });
});

describe("makeBackend", () => {
  it("calls by name with positional args and turns a rejected call into io", async () => {
    const calls: [string, unknown[]][] = [];
    const callable: CallableFactory = <A extends unknown[], R>(name: string) =>
      (async (...args: A) => {
        calls.push([name, args]);
        if (name === "stop_sync") throw new Error("socket closed");
        return { ok: true, name } as R;
      }) as (...args: A) => Promise<R>;
    const backend = makeBackend(callable);
    expect(await backend.check_host("OFFICE-PC", true)).toEqual({ ok: true, name: "check_host" });
    expect(calls[0]).toEqual(["check_host", ["OFFICE-PC", true]]);
    await backend.pin("Hades II", 1145350, null, false);
    await backend.set_ignored("Desktop", true);
    expect(calls.slice(1)).toEqual([
      ["pin", ["Hades II", 1145350, null, false]],
      ["set_ignored", ["Desktop", true]],
    ]);
    const stopped = await backend.stop_sync();
    expect(stopped.ok).toBe(false);
    expect(stopped.ok === false && stopped.error).toBe("io");
  });
});
