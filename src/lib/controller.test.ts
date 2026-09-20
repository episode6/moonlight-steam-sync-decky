import { beforeEach, describe, expect, it } from "vitest";

import { loadFixture } from "../test/fixtures";
import type {
  Backend,
  CliEvent,
  Pending,
  RunKind,
  SyncDonePayload,
} from "./cli";
import { Controller, type RestartPrompt, type SteamPort, type UiPort } from "./controller";
import { eventsOf, lastOf } from "./events";
import type { SteamInput } from "./layouts";
import { restartRowView } from "./state";

const PENDING: Pending = {
  restart_needed: "none",
  layout_walk: false,
  since: null,
  last_summary: null,
  last_plan: null,
  last_kind: null,
};

type Calls = [string, unknown[]][];

/** A scripted backend: every callable records its call and answers from `answers`. */
function fakeBackend(calls: Calls, answers: Partial<Record<keyof Backend, unknown>> = {}): Backend {
  const defaults: Partial<Record<keyof Backend, unknown>> = {
    cli_version: {
      ok: true,
      installed: "0.3.0",
      bundled: "0.3.0",
      minimum: "0.3.0",
      too_old: false,
      installed_path: "~/.local/bin/moonlight-steam-sync",
      bundled_path: "",
      pinned: "0.3.0",
      plugin_version: "0.1.0",
      log_path: "",
      install_error: null,
      capabilities: { art_commit: true },
    },
    get_settings: {
      ok: true,
      settings: {
        version: 1,
        hosts: ["MY-GAMING-PC", "OFFICE-PC"],
        copy_layouts: true,
        restart_countdown_s: 5,
        retry_missing: false,
      },
    },
    hosts: {
      ok: true,
      active: "MY-GAMING-PC",
      source: "state",
      cached_hosts: [],
      known: ["MY-GAMING-PC", "OFFICE-PC"],
    },
    pending: { ok: true, ...PENDING },
    sync_state: {
      ok: true,
      running: false,
      kind: null,
      started: null,
      opts: {},
      awaiting_exit: false,
      last_exit: null,
      last_kind: null,
      events: [],
    },
    get_ignored: { ok: true, ignored: ["Desktop"] },
    write_owned_apps: { ok: true, count: 2 },
    status: { ok: true, entries: eventsOf(loadFixture("common/status.ndjson"), "entry"), notes: [] },
    check_host: {
      ok: true,
      host: "MY-GAMING-PC",
      reachable: true,
      count: 7,
      ignored: 1,
      checked_at: "2026-09-18T14:02:00Z",
    },
    start_sync: { ok: true, kind: "sync" },
    start_art_refetch: { ok: true, kind: "art" },
    start_remove_all: { ok: true, kind: "remove" },
    stop_sync: { ok: true, running: true },
    clear_pending: { ok: true, ...PENDING },
    set_host: { ok: true, active: "OFFICE-PC" },
    layouts: { ok: true, version: 1, entries: {} },
    // upserts like the backend does, answering with the whole file
    record_layout: (shortcut: number, real: number, result: string, url: string | null) => {
      layoutsFile[String(shortcut)] = { real_appid: real, result, url, when: "2026-09-18T14:02:00Z" };
      return { ok: true, version: 1, entries: { ...layoutsFile } };
    },
  };
  return new Proxy({} as Backend, {
    get(_target, name: string) {
      return async (...args: unknown[]) => {
        calls.push([name, args]);
        const answer = (answers as Record<string, unknown>)[name] ?? (defaults as Record<string, unknown>)[name];
        return typeof answer === "function" ? (answer as (...a: unknown[]) => unknown)(...args) : answer ?? { ok: true };
      };
    },
  });
}

/** A scripted Steam Input: a selection per appid, and a log of every set. */
class FakeInput implements SteamInput {
  index: number | null = 15;
  urls = new Map<number, string>();
  sets: [number, number, string][] = [];
  /** When set, `setConfig` "sticks" this URL instead of the requested one. */
  sticksAs: string | null = null;
  throwOnSet = false;
  deckControllerIndex() {
    return this.index;
  }
  async getConfig(appid: number) {
    const URL = this.urls.get(appid);
    return URL === undefined ? null : { URL };
  }
  async setConfig(appid: number, idx: number, url: string) {
    if (this.throwOnSet) throw new Error("Steam Input refused");
    this.sets.push([appid, idx, url]);
    this.urls.set(appid, this.sticksAs ?? url);
  }
}

class FakeSteam implements SteamPort {
  apps: Record<string, string> | null = { "2379780": "Balatro", "1244090": "Sea of Stars" };
  steamid3: number | null = 12345678;
  shutdowns = 0;
  launched: number[] = [];
  steamInput = new FakeInput();
  /** Shortcut appids whose overview is loaded (`null` = every one). */
  loaded: Set<number> | null = null;
  configurator = true;
  configuratorOpened: number[] = [];
  ownedApps() {
    return this.apps;
  }
  currentSteamId3() {
    return this.steamid3;
  }
  runShortcut(appid: number) {
    this.launched.push(appid);
    return true;
  }
  shutdownSteam() {
    this.shutdowns++;
  }
  input() {
    return this.steamInput;
  }
  overviewLoaded(appid: number) {
    return this.loaded === null || this.loaded.has(appid);
  }
  canChooseLayout() {
    return this.configurator;
  }
  showControllerConfigurator(appid: number) {
    if (!this.configurator) return false;
    this.configuratorOpened.push(appid);
    return true;
  }
}

class FakeUi implements UiPort {
  prompts: RestartPrompt[] = [];
  closed = 0;
  toasts: string[] = [];
  showRestart(prompt: RestartPrompt) {
    this.prompts.push(prompt);
    return { close: () => this.closed++ };
  }
  toast(title: string) {
    this.toasts.push(title);
  }
}

const instantTiming = () => {
  let t = 0;
  return { sleep: async (ms: number) => void (t += ms), now: () => t };
};

function relay(controller: Controller, kind: RunKind, events: CliEvent[]) {
  for (const event of events) controller.onSyncEvent({ kind, event });
}

function done(kind: RunKind, events: CliEvent[], exit: number, pending: Partial<Pending> = {}): SyncDonePayload {
  const error = lastOf(events, "error");
  return {
    kind,
    exit,
    pending: { ...PENDING, ...pending },
    summary: lastOf(events, "summary"),
    commit: lastOf(events, "commit"),
    failure: error ? { error: "cli-error", message: error.message, exit: error.exit } : null,
  };
}

let calls: Calls;
let steam: FakeSteam;
let ui: FakeUi;
/** What the fake backend's `record_layout` has written (reset per test). */
let layoutsFile: Record<string, { real_appid: number; result: string; url: string | null; when: string }>;

beforeEach(() => {
  calls = [];
  steam = new FakeSteam();
  ui = new FakeUi();
  layoutsFile = {};
});

const names = () => calls.map(([name]) => name);

describe("load order (spec 3.8)", () => {
  it("cli_version, then the parallel reads, then owned apps before status and check_host", async () => {
    const controller = new Controller(fakeBackend(calls), steam, ui, instantTiming());
    await controller.load();
    const order = names();
    expect(order[0]).toBe("cli_version");
    expect(order.slice(1, 6).sort()).toEqual(["get_settings", "hosts", "layouts", "pending", "sync_state"]);
    expect(order.indexOf("write_owned_apps")).toBeLessThan(order.indexOf("status"));
    expect(order.indexOf("write_owned_apps")).toBeLessThan(order.indexOf("check_host"));
    expect(calls.find(([n]) => n === "write_owned_apps")?.[1]).toEqual([
      12345678,
      { "2379780": "Balatro", "1244090": "Sea of Stars" },
    ]);
    expect(calls.find(([n]) => n === "check_host")?.[1]).toEqual(["MY-GAMING-PC", false]);
    const state = controller.state;
    expect(state.library).toBe("ready");
    expect(state.counters).toEqual({ stream: 2, shortcuts: 2, unmatched: 1, parked: 1 });
    expect(state.clientAppid).toBe(2400000001);
    expect(state.reach?.reachable).toBe(true);
    expect(state.ignoredCount).toBe(1);
  });

  it("a failed cli_version says why and the next panelOpened() runs the whole order", async () => {
    let attempts = 0;
    const controller = new Controller(
      fakeBackend(calls, {
        cli_version: () => {
          attempts += 1;
          return attempts === 1
            ? { ok: false, error: "io", message: "could not run the CLI: [Errno 13] denied" }
            : {
                ok: true,
                installed: "0.3.0",
                bundled: "0.3.0",
                minimum: "0.3.0",
                too_old: false,
                capabilities: { art_commit: true },
              };
        },
      }),
      steam,
      ui,
      instantTiming(),
    );
    await controller.panelOpened();
    expect(controller.state.cli).toBeNull();
    expect(controller.state.cliError).toBe("could not run the CLI: [Errno 13] denied");
    expect(controller.state.library).toBe("waiting"); // steps 3-5 never ran
    expect(names()).not.toContain("status");

    calls.length = 0;
    await controller.panelOpened();
    expect(attempts).toBe(2);
    expect(controller.state.cli?.state).toBe("ok");
    expect(controller.state.library).toBe("ready");
    expect(names()).toContain("status"); // steps 3-5 ran this time
  });

  it("refreshCli() after a failed step 1 runs the whole order, not just the version", async () => {
    let attempts = 0;
    const controller = new Controller(
      fakeBackend(calls, {
        cli_version: () => {
          attempts += 1;
          return attempts === 1
            ? { ok: false, error: "io", message: "boom" }
            : {
                ok: true,
                installed: "0.3.0",
                bundled: "0.3.0",
                minimum: "0.3.0",
                too_old: false,
                capabilities: { art_commit: true },
              };
        },
      }),
      steam,
      ui,
      instantTiming(),
    );
    await controller.load();
    calls.length = 0;
    await controller.refreshCli();
    expect(controller.state.cli?.state).toBe("ok");
    expect(names()).toContain("status");
  });

  it("a missing CLI stops after the plugin-file reads", async () => {
    const controller = new Controller(
      fakeBackend(calls, {
        cli_version: {
          ok: true,
          installed: null,
          bundled: null,
          minimum: "0.3.0",
          too_old: false,
          capabilities: { art_commit: false },
        },
      }),
      steam,
      ui,
      instantTiming(),
    );
    await controller.load();
    expect(controller.state.cli?.text).toBe("CLI not installed — see About");
    expect(names()).not.toContain("hosts");
    expect(names()).not.toContain("write_owned_apps");
    expect(names()).not.toContain("status");
    expect(controller.state.settings).not.toBeNull();
  });

  it("a failed cli_version leaves a Retry that finishes the load", async () => {
    let answered = false;
    const ok = {
      ok: true,
      installed: "0.3.0",
      bundled: "0.3.0",
      minimum: "0.3.0",
      too_old: false,
      capabilities: { art_commit: true },
    };
    const backend = fakeBackend(calls, {
      cli_version: () =>
        answered ? ok : { ok: false, error: "io", message: "the backend did not answer" },
    });
    const controller = new Controller(backend, steam, ui, instantTiming());
    await controller.load();
    expect(controller.state.cli).toBeNull();
    expect(controller.state.cliError).toBe("the backend did not answer");
    expect(controller.state.library).toBe("waiting");
    expect(names()).not.toContain("status");

    answered = true; // the backend answers this time
    await controller.refreshCli();
    expect(controller.state.cli?.state).toBe("ok");
    expect(controller.state.cliError).toBeNull();
    expect(controller.state.library).toBe("ready");
    expect(names()).toContain("hosts");
    expect(names()).toContain("status");
    expect(names()).toContain("check_host");
  });

  it("waits for the library and gives up after 60 s", async () => {
    steam.apps = null;
    const controller = new Controller(fakeBackend(calls), steam, ui, instantTiming());
    await controller.load();
    expect(controller.state.library).toBe("failed");
    expect(names()).not.toContain("write_owned_apps");
    expect(names()).not.toContain("status");
    // Retry once the library is there
    steam.apps = { "620": "Portal 2" };
    await controller.retryLibrary();
    expect(controller.state.library).toBe("ready");
    expect(names()).toContain("status");
  });

  it("an empty account is 'library not loaded'", async () => {
    const controller = new Controller(
      fakeBackend(calls, {
        write_owned_apps: { ok: false, error: "owned-apps-empty", message: "Steam library not loaded" },
      }),
      steam,
      ui,
      instantTiming(),
    );
    await controller.load();
    expect(controller.state.library).toBe("failed");
  });

  it("re-attaches to a run in progress", async () => {
    const events = loadFixture("full-sync/sync.ndjson").slice(0, 5);
    const controller = new Controller(
      fakeBackend(calls, {
        sync_state: {
          ok: true,
          running: true,
          kind: "sync",
          started: "2026-09-18T14:00:00Z",
          opts: {},
          awaiting_exit: false,
          last_exit: null,
          last_kind: null,
          events,
        },
      }),
      steam,
      ui,
      instantTiming(),
    );
    await controller.load();
    expect(controller.state.run?.running).toBe(true);
    expect(controller.state.run?.titles).toHaveLength(2);
  });
});

describe("runs and the restart flow (spec 3.9)", () => {
  async function loaded(answers: Partial<Record<keyof Backend, unknown>> = {}) {
    const controller = new Controller(fakeBackend(calls, answers), steam, ui, instantTiming());
    await controller.load();
    calls.length = 0;
    return controller;
  }

  it("Sync now writes owned apps first", async () => {
    const controller = await loaded();
    expect(await controller.sync()).toBeNull();
    expect(names().slice(0, 2)).toEqual(["write_owned_apps", "start_sync"]);
    expect(calls[1][1]).toEqual([{}]);
    expect(controller.state.run?.running).toBe(true);
  });

  it("trigger 1: the prompt appears on awaiting-steam-exit, not on sync_done", async () => {
    const controller = await loaded();
    await controller.sync();
    const events = loadFixture("full-sync/sync.ndjson");
    const wait = events.findIndex((e) => e.event === "awaiting-steam-exit");
    relay(controller, "sync", events.slice(0, wait));
    expect(ui.prompts).toHaveLength(0);
    relay(controller, "sync", [events[wait]]);
    expect(ui.prompts).toHaveLength(1);
    expect(ui.prompts[0].decision.title).toBe("Sync finished: 2 added, 1 replaced, 1 parked");
    expect(ui.prompts[0].countdownSeconds).toBe(5);
    expect(ui.toasts).toHaveLength(1);
    expect(controller.state.pending?.restart_needed).toBe("write");
    ui.prompts[0].onRestartNow();
    expect(steam.shutdowns).toBe(1);
  });

  it("Later stops the run and leaves the persistent row, which re-arms with an immediate restart", async () => {
    const controller = await loaded();
    await controller.sync();
    const events = loadFixture("refused/sync.ndjson");
    relay(controller, "sync", events);
    ui.prompts[0].onLater();
    await Promise.resolve();
    expect(names()).toContain("stop_sync");
    const stopped = [
      ...events,
      { event: "error", exit: 130, message: "interrupted; resume with the same command" } as CliEvent,
    ];
    await controller.onSyncDone(done("sync", stopped, 130, { restart_needed: "write", last_kind: "sync" }));
    expect(controller.state.pending?.restart_needed).toBe("write");
    expect(controller.state.message).toBeNull();
    calls.length = 0;
    await controller.restartRow();
    expect(names().slice(0, 2)).toEqual(["write_owned_apps", "start_sync"]);
    expect(calls[1][1]).toEqual([{ immediate_restart: true }]);
    // the re-run's wait restarts Steam at once, with no prompt
    const promptsBefore = ui.prompts.length;
    relay(controller, "sync", events);
    expect(steam.shutdowns).toBe(1);
    expect(ui.prompts).toHaveLength(promptsBefore);
  });

  /** A start_sync whose answer is held back until `answer()` is called. */
  function heldStart() {
    let answer: () => void = () => undefined;
    const start_sync = () =>
      new Promise((resolve) => {
        answer = () => resolve({ ok: true, kind: "sync" });
      });
    return { start_sync, answer: () => answer() };
  }

  async function settle() {
    for (let i = 0; i < 5; i++) await Promise.resolve();
  }

  it("a re-armed run restarts at once even when its wait beats the start_sync answer", async () => {
    const held = heldStart();
    const controller = await loaded({
      pending: { ok: true, ...PENDING, restart_needed: "write", last_kind: "sync" },
      start_sync: held.start_sync,
    });
    const started = controller.restartRow();
    await settle();
    expect(names()).toContain("start_sync");
    relay(controller, "sync", loadFixture("refused/sync.ndjson"));
    expect(steam.shutdowns).toBe(1);
    expect(ui.prompts).toHaveLength(0);
    held.answer();
    await started;
    expect(controller.state.run?.immediate).toBe(true);
    expect(controller.state.run?.running).toBe(true);
    expect(ui.prompts).toHaveLength(0);
  });

  it("a prompt shown before the start_sync answer arrives stays open", async () => {
    const held = heldStart();
    const controller = await loaded({ start_sync: held.start_sync });
    const started = controller.sync();
    await settle();
    relay(controller, "sync", loadFixture("refused/sync.ndjson"));
    expect(ui.prompts).toHaveLength(1);
    held.answer();
    await started;
    expect(ui.closed).toBe(0);
    expect(controller.state.run?.immediate).toBe(false);
    expect(steam.shutdowns).toBe(0);
  });

  it("the persistent row re-runs the kind that was pending", async () => {
    const controller = await loaded({
      pending: { ok: true, ...PENDING, restart_needed: "write", last_kind: "remove" },
    });
    await controller.restartRow();
    expect(names()).toContain("start_remove_all");
  });

  it("the CLI's 60 s timeout closes the prompt and says so", async () => {
    const controller = await loaded();
    await controller.sync();
    const events = loadFixture("refused/sync.ndjson");
    relay(controller, "sync", events);
    const timedOut = [
      ...events,
      { event: "error", exit: 2, message: "sync: steam did not exit; shortcuts.vdf not written" } as CliEvent,
    ];
    await controller.onSyncDone(done("sync", timedOut, 2, { restart_needed: "write" }));
    expect(ui.closed).toBe(1);
    expect(controller.state.message).toBe("Steam did not restart; sync again to apply");
  });

  it("trigger 2: art only prompts at sync_done; Restart now clears the flag first", async () => {
    const controller = await loaded();
    await controller.sync();
    const events = loadFixture("art-only/sync.ndjson");
    relay(controller, "sync", events);
    expect(ui.prompts).toHaveLength(0);
    await controller.onSyncDone(done("sync", events, 0, { restart_needed: "art" }));
    expect(ui.prompts).toHaveLength(1);
    expect(ui.prompts[0].decision.title).toBe("New artwork needs a Steam restart to show");
    calls.length = 0;
    ui.prompts[0].onRestartNow();
    await new Promise((resolve) => setTimeout(resolve, 0));
    expect(calls[0]).toEqual(["clear_pending", ["restart_needed"]]);
    expect(steam.shutdowns).toBe(1);
  });

  it("the persistent row is refused while a game is running, on both paths", async () => {
    for (const restart_needed of ["write", "art"] as const) {
      calls = [];
      steam = new FakeSteam();
      ui = new FakeUi();
      const controller = await loaded({
        pending: { ok: true, ...PENDING, restart_needed, last_kind: "sync" },
      });
      controller.setInGame(true);
      expect(restartRowView(controller.state)).toEqual({
        description: "A game is running; exit it first",
        disabled: true,
      });
      await controller.restartRow();
      expect(calls).toEqual([]);
      expect(steam.shutdowns).toBe(0);
      // and it works again once the game is closed
      controller.setInGame(false);
      expect(restartRowView(controller.state)?.disabled).toBe(false);
      await controller.restartRow();
      expect(names().length).toBeGreaterThan(0);
    }
  });

  it("an immediate run whose wait starts in-game shows the modal instead of shutting Steam down", async () => {
    const controller = await loaded({
      pending: { ok: true, ...PENDING, restart_needed: "write", last_kind: "sync" },
    });
    await controller.restartRow();
    expect(controller.state.run?.immediate).toBe(true);
    controller.setInGame(true);
    relay(controller, "sync", loadFixture("refused/sync.ndjson"));
    expect(steam.shutdowns).toBe(0);
    expect(ui.prompts).toHaveLength(1); // the RestartModal, which says so itself
    expect(ui.toasts[0]).toBeDefined();
  });

  it("the art row does the same two calls", async () => {
    const controller = await loaded({ pending: { ok: true, ...PENDING, restart_needed: "art" } });
    await controller.restartRow();
    expect(calls[0]).toEqual(["clear_pending", ["restart_needed"]]);
    expect(steam.shutdowns).toBe(1);
  });

  it("trigger 3: stopped with images prompts; without images it just says so", async () => {
    const controller = await loaded();
    await controller.sync();
    const events = loadFixture("stopped/sync.ndjson");
    relay(controller, "sync", events);
    await controller.onSyncDone(done("sync", events, 130, { restart_needed: "art" }));
    expect(ui.prompts[0].decision.title).toBe("Stopped; 1 image was saved");

    await controller.sync();
    const none = events.map((e) => (e.event === "summary" ? { ...e, filled: 0 } : e));
    relay(controller, "sync", none);
    await controller.onSyncDone(done("sync", none, 130));
    expect(ui.prompts).toHaveLength(1);
    expect(controller.state.message).toBe("Stopped; sync again to resume");
  });

  it("an unreachable host is a message, and nothing changes", async () => {
    const controller = await loaded();
    await controller.sync();
    const events = loadFixture("unreachable/sync.ndjson");
    relay(controller, "sync", events);
    await controller.onSyncDone(done("sync", events, 3));
    expect(ui.prompts).toHaveLength(0);
    expect(controller.state.message).toBe("Host unreachable: sync: moonlight: host MY-GAMING-PC unreachable");
  });

  it("a steamid3 mismatch rewrites owned-apps.json and retries once", async () => {
    const controller = await loaded();
    await controller.sync();
    const mismatch: CliEvent[] = [
      { event: "start", schema: 1, version: "0.3.0", command: "sync" },
      {
        event: "error",
        exit: 1,
        message: "sync: owned-apps file is for Steam user 1 but sync would write to user 12345678",
      },
    ];
    relay(controller, "sync", mismatch);
    calls.length = 0;
    await controller.onSyncDone(done("sync", mismatch, 1));
    expect(names().slice(0, 2)).toEqual(["write_owned_apps", "start_sync"]);
    relay(controller, "sync", mismatch);
    calls.length = 0;
    await controller.onSyncDone(done("sync", mismatch, 1));
    expect(names()).not.toContain("start_sync"); // only once
  });

  it("a failed start is shown and no run begins", async () => {
    const controller = await loaded({
      start_sync: { ok: false, error: "busy", message: "A sync is already running", kind: "sync" },
    });
    expect(await controller.sync()).not.toBeNull();
    expect(controller.state.message).toBe("A sync is already running");
    expect(controller.state.run).toBeNull();
  });

  it("switching hosts sets the host, then syncs", async () => {
    const controller = await loaded();
    await controller.switchHost("OFFICE-PC");
    expect(names()).toEqual(["set_host", "hosts", "write_owned_apps", "start_sync"]);
    expect(calls[0][1]).toEqual(["OFFICE-PC"]);
  });

  it("Open Moonlight runs the client entry", async () => {
    const controller = await loaded();
    expect(controller.openMoonlight()).toBe(true);
    expect(steam.launched).toEqual([2400000001]);
  });
});

describe("the Titles page (spec 3.8)", () => {
  const apps = eventsOf(loadFixture("common/list.ndjson"), "app");
  const cachedApps = eventsOf(loadFixture("common/list-cached.ndjson"), "app");
  const listed = { ok: true, apps, host: "MY-GAMING-PC", count: 7, notes: [] };
  const unreachable = {
    ok: false,
    error: "cli-error",
    message: "list: moonlight: host MY-GAMING-PC unreachable",
    exit: 3,
  };

  async function loaded(answers: Partial<Record<keyof Backend, unknown>> = {}) {
    const controller = new Controller(
      fakeBackend(calls, { list_apps: listed, ...answers }),
      steam,
      ui,
      instantTiming(),
    );
    await controller.load();
    calls.length = 0;
    return controller;
  }

  it("reads the live list, status and ignore.json", async () => {
    const controller = await loaded();
    const load = await controller.loadTitles();
    expect(names().sort()).toEqual(["get_ignored", "list_apps", "status"]);
    expect(load.ok).toBe(true);
    if (!load.ok) return;
    expect(load.data.source).toBe("live");
    expect(load.data.apps).toHaveLength(7);
    expect(load.data.entries).toHaveLength(6);
    expect(load.data.ignored).toEqual(["Desktop"]);
    expect(load.data.host).toBe("MY-GAMING-PC");
    expect(load.data.unreachable).toBeNull();
    expect(load.data.cachedWhen).toBeNull();
  });

  it("falls back to the per-host cache when the host is unreachable", async () => {
    const controller = await loaded({
      list_apps: unreachable,
      list_cached: { ok: true, apps: cachedApps, host: "MY-GAMING-PC", count: 7, notes: [] },
    });
    const load = await controller.loadTitles();
    expect(calls.find(([n]) => n === "list_cached")?.[1]).toEqual(["MY-GAMING-PC"]);
    expect(load.ok).toBe(true);
    if (!load.ok) return;
    expect(load.data.source).toBe("cached");
    expect(load.data.cachedWhen).toBe("2026-09-18T14:02:00Z");
    expect(load.data.unreachable).toBe("list: moonlight: host MY-GAMING-PC unreachable");
  });

  it("reads the cache instead of a live list while a run is going", async () => {
    const controller = await loaded({
      list_cached: { ok: true, apps: cachedApps, host: "MY-GAMING-PC", count: 7, notes: [] },
    });
    await controller.sync();
    calls.length = 0;
    const countersBefore = controller.state.counters;
    const entriesBefore = controller.state.entries;
    const clientBefore = controller.state.clientAppid;
    const load = await controller.loadTitles();
    expect(names()).toContain("list_cached");
    expect(names()).not.toContain("list_apps");
    expect(load.ok).toBe(true);
    if (!load.ok) return;
    expect(load.data.source).toBe("syncing");
    expect(load.data.cachedWhen).toBe("2026-09-18T14:02:00Z");
    expect(load.data.unreachable).toBeNull();
    // the mid-run status snapshot reaches the page but not the shared store:
    // the panel's counters and stream map stay as the run left them
    expect(load.data.entries.length).toBeGreaterThan(0);
    expect(controller.state.counters).toEqual(countersBefore);
    expect(controller.state.entries).toEqual(entriesBefore);
    expect(controller.state.clientAppid).toBe(clientBefore);
  });

  it("a run with no cache yet says the list fills in when it finishes", async () => {
    const controller = await loaded({
      list_cached: { ...unreachable, message: "list: no cached app list for host MY-GAMING-PC" },
    });
    await controller.sync();
    expect(await controller.loadTitles()).toEqual({
      ok: false,
      message: "MY-GAMING-PC was never synced; this list fills in when the sync finishes",
      neverSynced: true,
    });
  });

  it("an unreachable host with no cache is never synced", async () => {
    const controller = await loaded({
      list_apps: unreachable,
      list_cached: { ...unreachable, message: "list: no cached app list for host MY-GAMING-PC" },
    });
    expect(await controller.loadTitles()).toEqual({
      ok: false,
      message: "MY-GAMING-PC is unreachable and was never synced",
      neverSynced: true,
    });
  });

  it("any other list failure is shown as is", async () => {
    const controller = await loaded({
      list_apps: { ok: false, error: "timeout", message: "timed out after 90 s", timeout_s: 90 },
    });
    expect(await controller.loadTitles()).toEqual({
      ok: false,
      message: "Timed out after 90 s",
      neverSynced: false,
    });
    expect(names()).not.toContain("list_cached");
  });

  it("a failed status still shows the list", async () => {
    const controller = await loaded({
      status: { ok: false, error: "bad-request", message: "status went wrong" },
    });
    const load = await controller.loadTitles();
    expect(load.ok && load.data.entries).toEqual([]);
    expect(load.ok && load.data.statusError).toBe("status went wrong");
  });

  it("no host yet: nothing is called", async () => {
    const controller = await loaded({
      hosts: { ok: true, active: null, source: null, cached_hosts: [], known: [] },
    });
    expect((await controller.loadTitles()).ok).toBe(false);
    expect(calls).toEqual([]);
  });

  it("retries once after rewriting owned apps on a steamid3 mismatch", async () => {
    let first = true;
    const controller = await loaded({
      list_apps: () => {
        if (!first) return listed;
        first = false;
        return {
          ok: false,
          error: "cli-error",
          message: "list: owned-apps file is for Steam user 1 but sync would write to user 2",
          exit: 1,
        };
      },
    });
    expect((await controller.loadTitles()).ok).toBe(true);
    expect(names().filter((n) => n === "list_apps")).toHaveLength(2);
    expect(names().filter((n) => n === "write_owned_apps")).toHaveLength(1);
  });

  it("two concurrent mismatches rewrite owned apps once and both retry", async () => {
    const mismatch = (what: string) => ({
      ok: false,
      error: "cli-error",
      message: `${what}: owned-apps file is for Steam user 1 but sync would write to user 2`,
      exit: 1,
    });
    let listFirst = true;
    let armed = false; // the load order's own status() call must succeed first
    const controller = await loaded({
      list_apps: () => {
        if (!listFirst) return listed;
        listFirst = false;
        return mismatch("list");
      },
      status: () => {
        if (!armed) return { ok: true, entries: [], notes: [] };
        armed = false;
        return mismatch("status");
      },
    });
    armed = true;
    const load = await controller.loadTitles();
    expect(load.ok).toBe(true);
    expect(names().filter((n) => n === "write_owned_apps")).toHaveLength(1);
    expect(names().filter((n) => n === "list_apps")).toHaveLength(2);
    expect(names().filter((n) => n === "status")).toHaveLength(2);
  });

  it("Use this pins exactly the chosen selector", async () => {
    const controller = await loaded({ pin: { ok: true, pinned: {}, notes: [] } });
    await controller.pinTitle("Hades II", { steam: 1145350, sgdb: null, none: false });
    await controller.pinTitle("Tunic", { steam: null, sgdb: null, none: true });
    expect(calls).toEqual([
      ["pin", ["Hades II", 1145350, null, false]],
      ["pin", ["Tunic", null, null, true]],
    ]);
  });

  it("Ignore writes ignore.json and the Ignored counter follows it", async () => {
    const controller = await loaded({ set_ignored: { ok: true, ignored: ["Desktop", "Tunic"] } });
    const reach = () => controller.state.reach;
    expect((reach() as { ignored?: number }).ignored).toBe(1);
    expect((await controller.setIgnored("Tunic", true)).ok).toBe(true);
    expect(calls).toEqual([["set_ignored", ["Tunic", true]]]);
    expect(controller.state.ignoredCount).toBe(2);
    expect((reach() as { ignored?: number }).ignored).toBeUndefined();
  });
});

describe("the Stream button and controller layouts (spec 3.9, 3.10)", () => {
  const BALATRO = 2379780;
  const BALATRO_SHORTCUT = 2718281828;
  const SEA = 1244090;
  const SEA_SHORTCUT = 2987654321;

  async function loaded(answers: Partial<Record<keyof Backend, unknown>> = {}) {
    const controller = new Controller(fakeBackend(calls, answers), steam, ui, instantTiming());
    await controller.load();
    await controller.layoutWalk();
    calls.length = 0;
    return controller;
  }

  const recorded = () => calls.filter(([n]) => n === "record_layout").map(([, args]) => args);

  it("a press copies the layout, records it and runs the hidden shortcut", async () => {
    const controller = await loaded();
    steam.steamInput.urls.set(BALATRO, "workshop://12345");
    expect(await controller.streamPress(BALATRO)).toBe(true);
    expect(steam.steamInput.sets).toEqual([[BALATRO_SHORTCUT, 15, "workshop://12345"]]);
    expect(recorded()).toEqual([[BALATRO_SHORTCUT, BALATRO, "copied", "workshop://12345"]]);
    expect(steam.launched).toEqual([BALATRO_SHORTCUT]);
    expect(controller.state.layouts[String(BALATRO_SHORTCUT)]?.result).toBe("copied");
  });

  it("a second press is idempotent: the shortcut now has its own selection", async () => {
    const controller = await loaded();
    steam.steamInput.urls.set(BALATRO, "workshop://12345");
    await controller.streamPress(BALATRO);
    await controller.streamPress(BALATRO);
    expect(steam.steamInput.sets).toHaveLength(1);
    expect(recorded().map((args) => args[2])).toEqual(["copied", "kept"]);
    expect(controller.state.layouts[String(BALATRO_SHORTCUT)]?.url).toBe("workshop://12345");
    expect(steam.launched).toEqual([BALATRO_SHORTCUT, BALATRO_SHORTCUT]);
  });

  it("while something is running a press only toasts", async () => {
    const controller = await loaded();
    controller.setInGame(true);
    expect(await controller.streamPress(BALATRO)).toBe(false);
    expect(ui.toasts).toEqual(["Moonlight Sync"]);
    expect(steam.launched).toEqual([]);
    expect(names()).not.toContain("record_layout");
  });

  it("a game without a Stream button is not launched", async () => {
    const controller = await loaded();
    expect(controller.hasStream(BALATRO)).toBe(true);
    expect(controller.hasStream(620)).toBe(false);
    expect(await controller.streamPress(620)).toBe(false);
    expect(steam.launched).toEqual([]);
  });

  it("the Advanced toggle off skips the copy but still launches", async () => {
    const controller = await loaded({
      get_settings: {
        ok: true,
        settings: { version: 1, hosts: ["MY-GAMING-PC"], copy_layouts: false, restart_countdown_s: 5, retry_missing: false },
      },
    });
    steam.steamInput.urls.set(BALATRO, "workshop://12345");
    expect(await controller.streamPress(BALATRO)).toBe(true);
    expect(steam.steamInput.sets).toEqual([]);
    expect(names()).not.toContain("record_layout");
    expect(steam.launched).toEqual([BALATRO_SHORTCUT]);
  });

  it("the picker strategy makes no Steam Input calls on a press", async () => {
    const controller = await loaded({
      get_settings: {
        ok: true,
        settings: {
          version: 1,
          hosts: ["MY-GAMING-PC"],
          copy_layouts: true,
          restart_countdown_s: 5,
          retry_missing: false,
          layout_strategy: "picker",
        },
      },
    });
    steam.steamInput.urls.set(BALATRO, "workshop://12345");
    expect(await controller.streamPress(BALATRO)).toBe(true);
    expect(steam.steamInput.sets).toEqual([]);
    expect(names()).not.toContain("record_layout");
    expect(steam.launched).toEqual([BALATRO_SHORTCUT]);
  });

  it("Choose layout opens Steam's picker and records 'picker'; hidden when the client lacks it", async () => {
    const controller = await loaded();
    expect(controller.canChooseLayout()).toBe(true);
    expect(await controller.chooseLayout(BALATRO_SHORTCUT, BALATRO)).toBe(true);
    expect(steam.configuratorOpened).toEqual([BALATRO_SHORTCUT]);
    expect(recorded()).toEqual([[BALATRO_SHORTCUT, BALATRO, "picker", null]]);
    steam.configurator = false;
    expect(controller.canChooseLayout()).toBe(false);
    expect(await controller.chooseLayout(BALATRO_SHORTCUT, BALATRO)).toBe(false);
    expect(recorded()).toHaveLength(1);
  });

  it("a remove run's sync_done re-reads layouts.json", async () => {
    const controller = await loaded();
    await controller.run("remove");
    calls.length = 0;
    await controller.onSyncDone(done("remove", loadFixture("common/remove.ndjson"), 0));
    expect(names()).toContain("layouts");
  });

  describe("the post-restart walk", () => {
    const walkPending = { ok: true, ...PENDING, layout_walk: true, last_kind: "sync" };

    it("runs at load over every pair in the stream map, then clears the flag", async () => {
      steam.steamInput.urls.set(BALATRO, "workshop://1");
      steam.steamInput.urls.set(SEA, "template://sea.vdf");
      const controller = new Controller(fakeBackend(calls, { pending: walkPending }), steam, ui, instantTiming());
      await controller.load();
      await controller.layoutWalk();
      expect(steam.steamInput.sets).toEqual([
        [BALATRO_SHORTCUT, 15, "workshop://1"],
        [SEA_SHORTCUT, 15, "template://sea.vdf"],
      ]);
      expect(recorded()).toEqual([
        [BALATRO_SHORTCUT, BALATRO, "copied", "workshop://1"],
        [SEA_SHORTCUT, SEA, "copied", "template://sea.vdf"],
      ]);
      const order = names();
      expect(order.indexOf("status")).toBeLessThan(order.indexOf("record_layout"));
      expect(order.lastIndexOf("record_layout")).toBeLessThan(order.lastIndexOf("clear_pending"));
      expect(calls.filter(([n]) => n === "clear_pending").map(([, a]) => a)).toEqual([["layout_walk"]]);
      expect(controller.state.pending?.layout_walk).toBe(false);
      expect(controller.state.walking).toBe(false);
    });

    it("does not run without the flag", async () => {
      await loaded();
      expect(names()).not.toContain("clear_pending");
      expect(steam.steamInput.sets).toEqual([]);
    });

    it("clears the flag at once under the picker strategy or with the toggle off", async () => {
      for (const settings of [
        { copy_layouts: true, layout_strategy: "picker" },
        { copy_layouts: false, layout_strategy: "copy" },
      ]) {
        calls.length = 0;
        steam = new FakeSteam();
        steam.steamInput.urls.set(BALATRO, "workshop://1");
        const controller = new Controller(
          fakeBackend(calls, {
            pending: walkPending,
            get_settings: {
              ok: true,
              settings: { version: 1, hosts: ["MY-GAMING-PC"], restart_countdown_s: 5, retry_missing: false, ...settings },
            },
          }),
          steam,
          ui,
          instantTiming(),
        );
        await controller.load();
        await controller.layoutWalk();
        expect(steam.steamInput.sets).toEqual([]);
        expect(names()).not.toContain("record_layout");
        expect(calls.filter(([n]) => n === "clear_pending").map(([, a]) => a)).toEqual([["layout_walk"]]);
      }
    });

    it("keeps the flag when status failed, so the next load walks", async () => {
      // An empty stream map because `status` did not answer is not "nothing
      // to walk": clearing the flag here would lose the walk for good.
      steam.steamInput.urls.set(BALATRO, "workshop://1");
      const controller = new Controller(
        fakeBackend(calls, {
          pending: walkPending,
          status: { ok: false, error: "io", message: "status: could not run the CLI" },
        }),
        steam,
        ui,
        instantTiming(),
      );
      await controller.load();
      await controller.layoutWalk();
      expect(controller.state.entries).toBeNull();
      expect(names()).not.toContain("clear_pending");
      expect(names()).not.toContain("record_layout");
      expect(steam.steamInput.sets).toEqual([]);
      expect(controller.state.pending?.layout_walk).toBe(true);
      expect(controller.state.walking).toBe(false);
    });

    it("waits for the shortcut list, records 'unavailable' for one that never loads, and gives up after 90 s", async () => {
      steam.steamInput.urls.set(BALATRO, "workshop://1");
      steam.steamInput.urls.set(SEA, "workshop://2");
      steam.loaded = new Set([BALATRO_SHORTCUT]); // Sea of Stars' shortcut never resolves
      const timing = instantTiming();
      const controller = new Controller(fakeBackend(calls, { pending: walkPending }), steam, ui, timing);
      await controller.load();
      await controller.layoutWalk();
      expect(timing.now()).toBeGreaterThanOrEqual(90_000);
      expect(recorded()).toEqual([
        [BALATRO_SHORTCUT, BALATRO, "copied", "workshop://1"],
        [SEA_SHORTCUT, SEA, "unavailable", null],
      ]);
      expect(steam.steamInput.sets).toEqual([[BALATRO_SHORTCUT, 15, "workshop://1"]]);
      expect(controller.state.pending?.layout_walk).toBe(false);
    });

    it("copies once the list has loaded, polling every 2 s", async () => {
      steam.steamInput.urls.set(BALATRO, "workshop://1");
      steam.loaded = new Set();
      const timing = instantTiming();
      const controller = new Controller(fakeBackend(calls, { pending: walkPending }), steam, ui, timing);
      const base = timing.sleep;
      let polls = 0;
      timing.sleep = async (ms: number) => {
        await base(ms);
        if (ms === 2_000 && ++polls === 3) steam.loaded = null; // loaded after three polls
      };
      await controller.load();
      await controller.layoutWalk();
      expect(polls).toBe(3);
      expect(recorded().map((args) => args[2])).toEqual(["copied", "kept"]);
    });

    it("never runs twice at once", async () => {
      steam.steamInput.urls.set(BALATRO, "workshop://1");
      const controller = new Controller(fakeBackend(calls, { pending: walkPending }), steam, ui, instantTiming());
      await controller.load();
      const first = controller.layoutWalk();
      const second = controller.layoutWalk();
      expect(second).toBe(first);
      await first;
      expect(calls.filter(([n]) => n === "clear_pending")).toHaveLength(1);
    });
  });
});
