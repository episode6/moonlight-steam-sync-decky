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
    expect(errorText(fail("cli-too-old", { installed: "0.2.0", minimum: "0.4.0" }))).toBe(
      "CLI too old (0.2.0, needs 0.4.0) — see About",
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
    expect(errorText(fail("no-mac"))).toBe("backend text");
    expect(errorText(fail("no-mac", { message: "" }))).toBe(
      "No MAC address known for this host: Moonlight has none for it",
    );
  });

  it("keeps the backend's own text when 'too old' is not about the version", () => {
    // start_art_refetch's refusal: the version is fine, `art` has no --commit.
    expect(
      errorText(
        fail("cli-too-old", {
          installed: "0.4.0",
          minimum: "0.4.0",
          message: "re-fetching art from Game Mode needs a CLI whose art command accepts --commit",
        }),
      ),
    ).toBe("re-fetching art from Game Mode needs a CLI whose art command accepts --commit");
  });

  it("says the key fetch's failures in the backend's words (spec 3.20.3)", () => {
    const text = "Steam's debugger port is not reachable; enter the key by hand";
    expect(errorText(fail("no-debugger", { message: text }))).toBe(text);
    expect(errorText(fail("cancelled", { message: "The key fetch was cancelled" }))).toBe(
      "The key fetch was cancelled",
    );
    expect(errorText(fail("sgdb-page", { message: "SteamGridDB's page has changed; enter the key by hand" }))).toBe(
      "SteamGridDB's page has changed; enter the key by hand",
    );
    // The fetch's 180 s: no `timeout_s`, so the backend's text stands.
    expect(errorText(fail("timeout", { message: "Timed out waiting for the SteamGridDB page" }))).toBe(
      "Timed out waiting for the SteamGridDB page",
    );
    // Its own busy guard, not the runs'.
    expect(errorText(fail("busy", { kind: "key" }))).toBe("A key fetch is already in progress");
    expect(errorText(fail("busy", { kind: "sync" }))).toBe("A sync is already running");
  });

  it("says the updater's failures in its own words (update spec 3.6)", () => {
    const now = new Date(Date.UTC(2026, 9, 21, 13, 0));
    expect(errorText(fail("update-unsupported"))).toBe(
      "This Decky Loader cannot install updates from a plugin. Update Decky Loader, or update with install.sh from Desktop Mode",
    );
    expect(errorText(fail("rate-limited", { retryAt: "2026-10-21T13:12:00Z" }), now)).toBe(
      "GitHub is limiting requests from this network. Try again in 12 minutes",
    );
    // no time from GitHub, or one already past: a minute
    expect(errorText(fail("rate-limited", { retryAt: null }), now)).toBe(
      "GitHub is limiting requests from this network. Try again in a minute",
    );
    expect(errorText(fail("rate-limited", { retryAt: "2026-10-21T12:00:00Z" }), now)).toBe(
      "GitHub is limiting requests from this network. Try again in a minute",
    );
    expect(errorText(fail("network", { message: "no answer from GitHub" }))).toBe(
      "Could not reach GitHub: no answer from GitHub",
    );
    expect(errorText(fail("bad-release"))).toBe("GitHub's answer could not be read. Check again later");
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
    await backend.start_sgdb_key_fetch();
    await backend.cancel_sgdb_key_fetch();
    expect(calls.slice(3)).toEqual([
      ["start_sgdb_key_fetch", []],
      ["cancel_sgdb_key_fetch", []],
    ]);
    await backend.stage_update("build-main", "ab".repeat(32), null, "main");
    await backend.cancel_update();
    expect(calls.slice(5)).toEqual([
      ["stage_update", ["build-main", "ab".repeat(32), null, "main"]],
      ["cancel_update", []],
    ]);
    const stopped = await backend.stop_sync();
    expect(stopped.ok).toBe(false);
    expect(stopped.ok === false && stopped.error).toBe("io");
  });
});
