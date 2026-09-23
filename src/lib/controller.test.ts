import { beforeEach, describe, expect, it } from "vitest";

import { loadFixture } from "../test/fixtures";
import type {
  Backend,
  CliEvent,
  DefaultLayout,
  LayoutEntry,
  LayoutResult,
  Pending,
  RunKind,
  Settings,
  SyncDonePayload,
} from "./cli";
import {
  Controller,
  DISABLED_FAILURE,
  appliedToast,
  clearedToast,
  type RestartPrompt,
  type SteamPort,
  type UiPort,
} from "./controller";
import { eventsOf, lastOf } from "./events";
import type { SteamInput } from "./layouts";
import { STREAMING_COLLECTION, hiddenPlan, pluginEnabled, streamingTabEnabled, type LibraryPort } from "./library";
import { restartRowView } from "./state";

const PENDING: Pending = {
  restart_needed: "none",
  layout_walk: false,
  since: null,
  last_summary: null,
  last_plan: null,
  last_kind: null,
};

/** The plugin's default layout, once set (spec 3.16). */
const DEFAULT: DefaultLayout = { url: "workshop://2810081311", title: "Gamepad with camera controls", when: "2026-09-21T10:00:00Z" };

const baseSettings = (): Settings => ({
  version: 1,
  hosts: ["MY-GAMING-PC", "OFFICE-PC"],
  copy_layouts: true,
  restart_countdown_s: 5,
  retry_missing: false,
  default_layout: null,
});

type Calls = [string, unknown[]][];

/** A scripted backend: every callable records its call and answers from `answers`. */
function fakeBackend(calls: Calls, answers: Partial<Record<keyof Backend, unknown>> = {}): Backend {
  const defaults: Partial<Record<keyof Backend, unknown>> = {
    cli_version: {
      ok: true,
      installed: "0.4.0",
      bundled: "0.4.0",
      minimum: "0.4.0",
      too_old: false,
      installed_path: "~/.local/bin/moonlight-steam-sync",
      bundled_path: "",
      pinned: "0.4.0",
      plugin_version: "0.1.0",
      log_path: "",
      install_error: null,
      capabilities: { art_commit: true },
    },
    get_settings: () => ({ ok: true, settings: { ...settingsFile } }),
    // stores like the backend does (spec 3.16.2): settings first, then the walk flag
    set_default_layout: (url: string | null, title: string | null) => {
      settingsFile.default_layout = url === null ? null : { url, title: title ?? "", when: "2026-09-21T10:00:00Z" };
      return { ok: true, settings: { ...settingsFile }, pending: { ...PENDING, layout_walk: true } };
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
    get_ignored: { ok: true, ignored: ["Demo Launcher"] },
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
    // upserts like the backend does, answering with the whole file; `applied`
    // follows settings.py's table (spec 3.16.2, Decision 53)
    record_layout: (shortcut: number, real: number | null, result: LayoutResult, url: string | null) => {
      const prev = layoutsFile[String(shortcut)];
      const prevApplied = prev ? (prev.applied !== undefined ? prev.applied : prev.result === "copied" ? prev.url : null) : null;
      const applied =
        result === "default" || result === "copied" ? url : result === "kept" ? (url === prevApplied ? prevApplied : null) : prevApplied;
      layoutsFile[String(shortcut)] = { real_appid: real, result, url, when: "2026-09-18T14:02:00Z", applied };
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

/** A scripted Steam Input: a selection per appid, and a log of every set and clear. */
class FakeInput implements SteamInput {
  index: number | null = 15;
  urls = new Map<number, string>();
  titles = new Map<number, string>();
  sets: [number, number, string][] = [];
  clears: [number, number][] = [];
  gets: number[] = [];
  /** When set, `setConfig` "sticks" this URL instead of the requested one. */
  sticksAs: string | null = null;
  throwOnSet = false;
  /** Absent on a client without `ClearSelectedConfigForApp` (spec 3.16.3). */
  clearConfig?: (appid: number, controllerIndex: number) => Promise<void>;
  constructor() {
    this.clearConfig = async (appid, idx) => {
      this.clears.push([appid, idx]);
      this.urls.set(appid, "default://cleared");
    };
  }
  controllerIndex() {
    return this.index;
  }
  async getConfig(appid: number) {
    this.gets.push(appid);
    const URL = this.urls.get(appid);
    const Title = this.titles.get(appid);
    return URL === undefined ? null : Title === undefined ? { URL } : { URL, Title };
  }
  async setConfig(appid: number, idx: number, url: string) {
    if (this.throwOnSet) throw new Error("Steam Input refused");
    this.sets.push([appid, idx, url]);
    this.urls.set(appid, this.sticksAs ?? url);
  }
}

/** A scripted client library: the hidden set, the collections, and a log of every change. */
class FakeLibrary implements LibraryPort {
  hiding = true;
  collecting = true;
  /** `false`: the client cannot say what is hidden. */
  readable = true;
  hidden = new Set<number>();
  collections = new Map<string, Set<number>>();
  log: string[] = [];
  canHide() {
    return this.hiding;
  }
  isHidden(appid: number) {
    return this.readable ? this.hidden.has(appid) : null;
  }
  setHidden(appids: readonly number[], hidden: boolean) {
    if (!appids.length) return;
    this.log.push(`${hidden ? "hide" : "show"} ${[...appids].sort().join(",")}`);
    for (const appid of appids) {
      if (hidden) this.hidden.add(appid);
      else this.hidden.delete(appid);
    }
  }
  canCollect() {
    return this.collecting;
  }
  collectionApps(name: string) {
    const apps = this.collections.get(name);
    return apps ? [...apps] : null;
  }
  /** `true`: a just-added member is not listed until the next read (an unmeasured client). */
  lateAdds = false;
  private late: [string, number[]] | null = null;
  async updateCollection(name: string, add: readonly number[], remove: readonly number[]) {
    this.log.push(`update +${[...add].sort().join(",")} -${[...remove].sort().join(",")}`);
    const apps = this.collections.get(name) ?? new Set<number>();
    if (this.lateAdds) this.late = [name, [...add]];
    else for (const appid of add) apps.add(appid);
    for (const appid of remove) apps.delete(appid);
    this.collections.set(name, apps);
  }
  /** The client's next tick: the late adds land. */
  settle() {
    if (!this.late) return;
    const [name, add] = this.late;
    this.late = null;
    const apps = this.collections.get(name);
    if (apps) for (const appid of add) apps.add(appid);
  }
  async deleteCollection(name: string) {
    if (this.collections.delete(name)) this.log.push("delete");
  }
}

class FakeSteam implements SteamPort {
  lib = new FakeLibrary();
  library() {
    return this.lib;
  }
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
  bodies: string[] = [];
  showRestart(prompt: RestartPrompt) {
    this.prompts.push(prompt);
    return { close: () => this.closed++ };
  }
  toast(title: string, body: string) {
    this.toasts.push(title);
    this.bodies.push(body);
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
let layoutsFile: Record<string, LayoutEntry>;
/** What the fake backend's `set_default_layout` has stored (reset per test). */
let settingsFile: Settings;

beforeEach(() => {
  calls = [];
  steam = new FakeSteam();
  ui = new FakeUi();
  layoutsFile = {};
  settingsFile = baseSettings();
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
                installed: "0.4.0",
                bundled: "0.4.0",
                minimum: "0.4.0",
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
                installed: "0.4.0",
                bundled: "0.4.0",
                minimum: "0.4.0",
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
          minimum: "0.4.0",
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
      installed: "0.4.0",
      bundled: "0.4.0",
      minimum: "0.4.0",
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

  it("a throw while reading the library ends in 'failed', never a stuck 'loading'", async () => {
    steam.ownedApps = () => {
      throw new TypeError("Cannot read properties of undefined (reading 'get')");
    };
    const controller = new Controller(fakeBackend(calls), steam, ui, instantTiming());
    await controller.load();
    expect(controller.state.library).toBe("failed");
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
      { event: "start", schema: 1, version: "0.4.0", command: "sync" },
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

  it("Desktop / Steam Big Picture run their shortcut, and only when the host has one", async () => {
    // The fixture's pair is hidden (--hide-host-apps); the buttons are its only launcher.
    const entries = eventsOf(loadFixture("common/status.ndjson"), "entry").filter(
      (e) => e.name !== "Steam Big Picture",
    );
    const controller = await loaded({ status: { ok: true, entries, notes: [] } });
    expect(controller.openHostApp("desktop")).toBe(true);
    expect(controller.openHostApp("bigPicture")).toBe(false);
    expect(steam.launched).toEqual([3000000101]);
    // Like the Stream button: a running game does not hold the launch back.
    controller.setInGame(true);
    expect(controller.openHostApp("desktop")).toBe(true);
    expect(steam.launched).toEqual([3000000101, 3000000101]);
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
    expect(load.data.apps).toHaveLength(9);
    expect(load.data.entries).toHaveLength(8);
    expect(load.data.ignored).toEqual(["Demo Launcher"]);
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
    const controller = await loaded({ set_ignored: { ok: true, ignored: ["Demo Launcher", "Tunic"] } });
    const reach = () => controller.state.reach;
    expect((reach() as { ignored?: number }).ignored).toBe(1);
    expect((await controller.setIgnored("Tunic", true)).ok).toBe(true);
    expect(calls).toEqual([["set_ignored", ["Tunic", true]]]);
    expect(controller.state.ignoredCount).toBe(2);
    expect((reach() as { ignored?: number }).ignored).toBeUndefined();
  });
});

describe("the Stream button and the default controller layout (spec 3.9, 3.10, 3.16)", () => {
  const BALATRO = 2379780;
  const BALATRO_SHORTCUT = 2718281828;
  const SEA = 1244090;
  const SEA_SHORTCUT = 2987654321;
  /** Every non-parked entry of common/status.ndjson, in order (spec 3.16.4, Decision 48). */
  const TARGETS: [number, number | null][] = [
    [BALATRO_SHORTCUT, BALATRO],
    [3000000101, 226620], // Desktop
    [3000000011, 1145360], // Hades II, visible
    [SEA_SHORTCUT, SEA],
    [3000000102, null], // Steam Big Picture
    [3000000007, null], // Tunic, unmatched
    [2400000001, null], // the Moonlight client entry
  ];
  const withDefault = () => ({ ok: true, settings: { ...baseSettings(), default_layout: DEFAULT } });

  async function loaded(answers: Partial<Record<keyof Backend, unknown>> = {}) {
    const controller = new Controller(fakeBackend(calls, answers), steam, ui, instantTiming());
    await controller.load();
    await controller.layoutWalk();
    calls.length = 0;
    return controller;
  }

  const recorded = () => calls.filter(([n]) => n === "record_layout").map(([, args]) => args);

  it("a press puts the default on the hidden shortcut, records it and runs the shortcut", async () => {
    const controller = await loaded({ get_settings: withDefault() });
    steam.steamInput.urls.set(BALATRO_SHORTCUT, "default://balatro");
    expect(await controller.streamPress(BALATRO)).toBe(true);
    expect(steam.steamInput.sets).toEqual([[BALATRO_SHORTCUT, 15, DEFAULT.url]]);
    expect(recorded()).toEqual([[BALATRO_SHORTCUT, BALATRO, "default", DEFAULT.url]]);
    expect(steam.launched).toEqual([BALATRO_SHORTCUT]);
    expect(controller.state.layouts[String(BALATRO_SHORTCUT)]).toMatchObject({ result: "default", applied: DEFAULT.url });
    // the real game's selection is never read
    expect(steam.steamInput.gets).not.toContain(BALATRO);
  });

  it("a second press is idempotent: the default is already there, nothing is set again", async () => {
    const controller = await loaded({ get_settings: withDefault() });
    await controller.streamPress(BALATRO);
    await controller.streamPress(BALATRO);
    expect(steam.steamInput.sets).toHaveLength(1);
    expect(recorded().map((args) => args[2])).toEqual(["default", "default"]);
    expect(steam.launched).toEqual([BALATRO_SHORTCUT, BALATRO_SHORTCUT]);
    // a layout picked by hand afterwards is never overwritten
    steam.steamInput.urls.set(BALATRO_SHORTCUT, "workshop://999");
    await controller.streamPress(BALATRO);
    expect(steam.steamInput.sets).toHaveLength(1);
    expect(controller.state.layouts[String(BALATRO_SHORTCUT)]).toMatchObject({ result: "kept", url: "workshop://999", applied: null });
  });

  it("with no default a press makes no Steam Input call and records nothing, and still launches", async () => {
    const controller = await loaded();
    steam.steamInput.urls.set(BALATRO_SHORTCUT, "default://balatro");
    expect(await controller.streamPress(BALATRO)).toBe(true);
    expect(steam.steamInput.sets).toEqual([]);
    expect(steam.steamInput.gets).toEqual([]);
    expect(names()).not.toContain("record_layout");
    expect(steam.launched).toEqual([BALATRO_SHORTCUT]);
  });

  it("a press never unsets: a cleared default leaves the shortcut's layout alone", async () => {
    const controller = await loaded();
    layoutsFile[String(BALATRO_SHORTCUT)] = {
      real_appid: BALATRO,
      result: "default",
      url: "workshop://1",
      when: "x",
      applied: "workshop://1",
    };
    steam.steamInput.urls.set(BALATRO_SHORTCUT, "workshop://1");
    expect(await controller.streamPress(BALATRO)).toBe(true);
    expect(steam.steamInput.clears).toEqual([]);
    expect(names()).not.toContain("record_layout");
  });

  it("a press while something is running still launches (Moonlight's UI handles it)", async () => {
    const controller = await loaded({ get_settings: withDefault() });
    controller.setInGame(true);
    expect(await controller.streamPress(BALATRO)).toBe(true);
    expect(ui.toasts).toEqual([]);
    expect(steam.launched).toEqual([BALATRO_SHORTCUT]);
    expect(names()).toContain("record_layout");
  });

  it("a game without a Stream button is not launched", async () => {
    const controller = await loaded();
    expect(controller.hasStream(BALATRO)).toBe(true);
    expect(controller.hasStream(620)).toBe(false);
    expect(await controller.streamPress(620)).toBe(false);
    expect(steam.launched).toEqual([]);
  });

  it("the picker strategy makes no Steam Input calls on a press, even with a default stored", async () => {
    const controller = await loaded({
      get_settings: { ok: true, settings: { ...baseSettings(), default_layout: DEFAULT, layout_strategy: "picker" } },
    });
    expect(await controller.streamPress(BALATRO)).toBe(true);
    expect(steam.steamInput.sets).toEqual([]);
    expect(steam.steamInput.gets).toEqual([]);
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

  it("the panel's layout buttons open the hidden host app's picker, even while a game runs", async () => {
    const controller = await loaded();
    expect(controller.state.hostApps).toEqual({ desktop: 3000000101, bigPicture: 3000000102 });
    controller.setInGame(true); // neither the launch nor the configurator is held back
    expect(await controller.chooseHostAppLayout("desktop")).toBe(true);
    expect(await controller.chooseHostAppLayout("bigPicture")).toBe(true);
    expect(steam.configuratorOpened).toEqual([3000000101, 3000000102]);
    // picker only: no game behind it, and Steam Input is never touched
    expect(recorded()).toEqual([
      [3000000101, null, "picker", null],
      [3000000102, null, "picker", null],
    ]);
    expect(controller.state.layouts["3000000101"]).toMatchObject({ real_appid: null, result: "picker" });
    expect(steam.launched).toEqual([]);
    steam.configurator = false;
    expect(await controller.chooseHostAppLayout("desktop")).toBe(false);
    expect(recorded()).toHaveLength(2);
  });

  it("a host app the host does not publish has no layout button to press", async () => {
    const entries = eventsOf(loadFixture("common/status.ndjson"), "entry").filter((e) => !e.host_app);
    const controller = await loaded({ status: { ok: true, entries, notes: [] } });
    expect(await controller.chooseHostAppLayout("desktop")).toBe(false);
    expect(steam.configuratorOpened).toEqual([]);
    expect(names()).not.toContain("record_layout");
  });

  it("Desktop's Steam match never makes it a Stream button", async () => {
    const controller = await loaded();
    // status.ndjson: hidden, published, matched to Steam 226620 -- and host_app.
    expect(controller.hasStream(226620)).toBe(false);
    expect([...controller.state.streamMap.values()]).not.toContain(3000000101);
  });

  it("a remove run's sync_done re-reads layouts.json", async () => {
    const controller = await loaded();
    await controller.run("remove");
    calls.length = 0;
    await controller.onSyncDone(done("remove", loadFixture("common/remove.ndjson"), 0));
    expect(names()).toContain("layouts");
  });

  describe("inspectLayout (Use as the default layout, spec 3.16.5)", () => {
    it("reads one selection: the URL and its title, else the layout's kind", async () => {
      const controller = await loaded();
      steam.steamInput.urls.set(BALATRO_SHORTCUT, DEFAULT.url);
      steam.steamInput.titles.set(BALATRO_SHORTCUT, "  Gamepad with camera controls ");
      expect(await controller.inspectLayout(BALATRO_SHORTCUT)).toEqual({
        ok: true,
        url: DEFAULT.url,
        title: "Gamepad with camera controls",
      });
      expect(steam.steamInput.gets).toEqual([BALATRO_SHORTCUT]);
      steam.steamInput.urls.set(3000000011, "template://controller_neptune_gamepad.vdf");
      expect(await controller.inspectLayout(3000000011)).toEqual({
        ok: true,
        url: "template://controller_neptune_gamepad.vdf",
        title: "template layout",
      });
    });

    it("refuses: no controller, nothing chosen, a layout that cannot be shared", async () => {
      const controller = await loaded();
      steam.steamInput.index = null;
      expect(await controller.inspectLayout(BALATRO_SHORTCUT)).toEqual({ ok: false, reason: "no-controller" });
      steam.steamInput.index = 15;
      expect(await controller.inspectLayout(BALATRO_SHORTCUT)).toEqual({ ok: false, reason: "unselected" });
      steam.steamInput.urls.set(BALATRO_SHORTCUT, "default://balatro");
      expect(await controller.inspectLayout(BALATRO_SHORTCUT)).toEqual({ ok: false, reason: "unselected" });
      steam.steamInput.urls.set(BALATRO_SHORTCUT, "autosave:///x/config/2718281828/controller_neptune.vdf");
      expect(await controller.inspectLayout(BALATRO_SHORTCUT)).toEqual({ ok: false, reason: "not-shareable" });
    });
  });

  describe("the layout walk", () => {
    const walkPending = { ok: true, ...PENDING, layout_walk: true, last_kind: "sync" };

    it("runs at load over every non-parked entry, then clears the flag", async () => {
      steam.steamInput.urls.set(SEA_SHORTCUT, "template://sea.vdf"); // chosen by hand
      const controller = new Controller(
        fakeBackend(calls, { pending: walkPending, get_settings: withDefault() }),
        steam,
        ui,
        instantTiming(),
      );
      await controller.load();
      const counts = await controller.layoutWalk();
      const set = TARGETS.filter(([shortcut]) => shortcut !== SEA_SHORTCUT).map(([shortcut]) => [shortcut, 15, DEFAULT.url]);
      expect(steam.steamInput.sets).toEqual(set);
      expect(recorded()).toEqual(
        TARGETS.map(([shortcut, real]) =>
          shortcut === SEA_SHORTCUT ? [shortcut, real, "kept", "template://sea.vdf"] : [shortcut, real, "default", DEFAULT.url],
        ),
      );
      expect(counts).toEqual({ applied: 6, unset: 0, kept: 1, unavailable: 0 });
      const order = names();
      expect(order.indexOf("status")).toBeLessThan(order.indexOf("record_layout"));
      expect(order.lastIndexOf("record_layout")).toBeLessThan(order.lastIndexOf("clear_pending"));
      expect(calls.filter(([n]) => n === "clear_pending").map(([, a]) => a)).toEqual([["layout_walk"]]);
      expect(controller.state.pending?.layout_walk).toBe(false);
      expect(controller.state.walking).toBe(false);
      // the parked entry was never touched
      expect(steam.steamInput.gets).not.toContain(2555555555);
    });

    it("does not run without the flag", async () => {
      await loaded({ get_settings: withDefault() });
      expect(names()).not.toContain("clear_pending");
      expect(steam.steamInput.sets).toEqual([]);
    });

    it("clears the flag at once under the picker strategy", async () => {
      const controller = new Controller(
        fakeBackend(calls, {
          pending: walkPending,
          get_settings: { ok: true, settings: { ...baseSettings(), default_layout: DEFAULT, layout_strategy: "picker" } },
        }),
        steam,
        ui,
        instantTiming(),
      );
      await controller.load();
      expect(await controller.layoutWalk()).toEqual({ applied: 0, unset: 0, kept: 0, unavailable: 0 });
      expect(steam.steamInput.sets).toEqual([]);
      expect(steam.steamInput.gets).toEqual([]);
      expect(names()).not.toContain("record_layout");
      expect(calls.filter(([n]) => n === "clear_pending").map(([, a]) => a)).toEqual([["layout_walk"]]);
    });

    it("keeps the flag when status failed, so the next load walks", async () => {
      // No targets because `status` did not answer is not "nothing to walk":
      // clearing the flag here would lose the walk for good.
      const controller = new Controller(
        fakeBackend(calls, {
          pending: walkPending,
          get_settings: withDefault(),
          status: { ok: false, error: "io", message: "status: could not run the CLI" },
        }),
        steam,
        ui,
        instantTiming(),
      );
      await controller.load();
      expect(await controller.layoutWalk()).toBeNull();
      expect(controller.state.entries).toBeNull();
      expect(names()).not.toContain("clear_pending");
      expect(names()).not.toContain("record_layout");
      expect(steam.steamInput.sets).toEqual([]);
      expect(controller.state.pending?.layout_walk).toBe(true);
      expect(controller.state.walking).toBe(false);
    });

    it("waits for the shortcut list, records 'unavailable' for one that never loads, and gives up after 90 s", async () => {
      steam.loaded = new Set(TARGETS.map(([shortcut]) => shortcut).filter((shortcut) => shortcut !== SEA_SHORTCUT));
      const timing = instantTiming();
      const controller = new Controller(
        fakeBackend(calls, { pending: walkPending, get_settings: withDefault() }),
        steam,
        ui,
        timing,
      );
      await controller.load();
      const counts = await controller.layoutWalk();
      expect(timing.now()).toBeGreaterThanOrEqual(90_000);
      expect(recorded().find(([shortcut]) => shortcut === SEA_SHORTCUT)).toEqual([SEA_SHORTCUT, SEA, "unavailable", null]);
      expect(steam.steamInput.sets.map(([shortcut]) => shortcut)).not.toContain(SEA_SHORTCUT);
      expect(counts).toEqual({ applied: 6, unset: 0, kept: 0, unavailable: 1 });
      expect(controller.state.pending?.layout_walk).toBe(false);
    });

    it("applies once the list has loaded, polling every 2 s", async () => {
      steam.loaded = new Set();
      const timing = instantTiming();
      const controller = new Controller(
        fakeBackend(calls, { pending: walkPending, get_settings: withDefault() }),
        steam,
        ui,
        timing,
      );
      const base = timing.sleep;
      let polls = 0;
      timing.sleep = async (ms: number) => {
        await base(ms);
        if (ms === 2_000 && ++polls === 3) steam.loaded = null; // loaded after three polls
      };
      await controller.load();
      await controller.layoutWalk();
      expect(polls).toBe(3);
      expect(recorded()).toHaveLength(TARGETS.length);
      expect(recorded().every((args) => args[2] === "default")).toBe(true);
    });

    it("never runs twice at once", async () => {
      const controller = new Controller(
        fakeBackend(calls, { pending: walkPending, get_settings: withDefault() }),
        steam,
        ui,
        instantTiming(),
      );
      await controller.load();
      const first = controller.layoutWalk();
      const second = controller.layoutWalk();
      expect(second).toBe(first);
      await first;
      expect(calls.filter(([n]) => n === "clear_pending")).toHaveLength(1);
    });

    it("moves a pre-upgrade copied title and the plugin's own earlier default, and leaves the rest", async () => {
      layoutsFile[String(BALATRO_SHORTCUT)] = { real_appid: BALATRO, result: "copied", url: "workshop://1", when: "x" };
      layoutsFile[String(SEA_SHORTCUT)] = { real_appid: SEA, result: "default", url: "workshop://2", when: "x", applied: "workshop://2" };
      layoutsFile["3000000011"] = { real_appid: 1145360, result: "kept", url: "workshop://3", when: "x", applied: null };
      steam.steamInput.urls.set(BALATRO_SHORTCUT, "workshop://1");
      steam.steamInput.urls.set(SEA_SHORTCUT, "workshop://2");
      steam.steamInput.urls.set(3000000011, "workshop://3");
      steam.steamInput.urls.set(3000000007, "workshop://1"); // Tunic: hand-set to the very URL, no record
      const controller = new Controller(
        fakeBackend(calls, {
          pending: walkPending,
          get_settings: withDefault(),
          layouts: () => ({ ok: true, version: 1, entries: { ...layoutsFile } }),
        }),
        steam,
        ui,
        instantTiming(),
      );
      await controller.load();
      const counts = await controller.layoutWalk();
      expect(steam.steamInput.sets.map(([shortcut]) => shortcut).sort()).toEqual(
        [BALATRO_SHORTCUT, SEA_SHORTCUT, 3000000101, 3000000102, 2400000001].sort(),
      );
      expect(counts).toEqual({ applied: 5, unset: 0, kept: 2, unavailable: 0 });
      expect(controller.state.layouts["3000000011"]).toMatchObject({ result: "kept", url: "workshop://3", applied: null });
      expect(controller.state.layouts["3000000007"]).toMatchObject({ result: "kept", url: "workshop://1", applied: null });
    });

    it("with no default set it is the unset pass: only entries still on a plugin-set layout are cleared", async () => {
      layoutsFile[String(BALATRO_SHORTCUT)] = { real_appid: BALATRO, result: "default", url: "workshop://1", when: "x", applied: "workshop://1" };
      layoutsFile[String(SEA_SHORTCUT)] = { real_appid: SEA, result: "default", url: "workshop://1", when: "x", applied: "workshop://1" };
      layoutsFile["3000000011"] = { real_appid: 1145360, result: "copied", url: "workshop://1", when: "x" }; // legacy: never unset
      steam.steamInput.urls.set(BALATRO_SHORTCUT, "workshop://1");
      steam.steamInput.urls.set(SEA_SHORTCUT, "workshop://changed-by-hand");
      steam.steamInput.urls.set(3000000011, "workshop://1");
      const controller = new Controller(
        fakeBackend(calls, {
          pending: walkPending,
          layouts: () => ({ ok: true, version: 1, entries: { ...layoutsFile } }),
        }),
        steam,
        ui,
        instantTiming(),
      );
      await controller.load();
      const counts = await controller.layoutWalk();
      expect(steam.steamInput.clears).toEqual([[BALATRO_SHORTCUT, 15]]);
      expect(steam.steamInput.sets).toEqual([]);
      expect(recorded()).toEqual([
        [BALATRO_SHORTCUT, BALATRO, "kept", "default://cleared"],
        [SEA_SHORTCUT, SEA, "kept", "workshop://changed-by-hand"],
      ]);
      expect(counts).toEqual({ applied: 0, unset: 1, kept: 1, unavailable: 0 });
      expect(controller.state.layouts[String(BALATRO_SHORTCUT)]).toMatchObject({ applied: null });
      expect(controller.state.layouts[String(SEA_SHORTCUT)]).toMatchObject({ applied: null });
      expect(controller.state.pending?.layout_walk).toBe(false);
    });
  });

  describe("setDefaultLayout (spec 3.16.4)", () => {
    it("stores it, walks every entry and toasts the counts", async () => {
      steam.steamInput.urls.set(SEA_SHORTCUT, "template://sea.vdf");
      const controller = await loaded();
      expect(await controller.setDefaultLayout(DEFAULT.url, DEFAULT.title)).toBeNull();
      expect(calls.find(([n]) => n === "set_default_layout")?.[1]).toEqual([DEFAULT.url, DEFAULT.title]);
      expect(controller.state.settings?.default_layout).toMatchObject({ url: DEFAULT.url, title: DEFAULT.title });
      expect(steam.steamInput.sets).toHaveLength(TARGETS.length - 1);
      expect(controller.state.pending?.layout_walk).toBe(false);
      expect(ui.bodies).toEqual(["Default layout applied to 6 titles · 1 kept their own"]);
      const order = names();
      expect(order.indexOf("set_default_layout")).toBeLessThan(order.indexOf("record_layout"));
      expect(order.lastIndexOf("record_layout")).toBeLessThan(order.lastIndexOf("clear_pending"));
    });

    it("is not held back by a running game", async () => {
      const controller = await loaded();
      controller.setInGame(true);
      expect(await controller.setDefaultLayout(DEFAULT.url, DEFAULT.title)).toBeNull();
      expect(steam.steamInput.sets).toHaveLength(TARGETS.length);
      expect(steam.launched).toEqual([]);
    });

    it("waits for a walk in progress before the backend call, so that walk cannot clear the new flag", async () => {
      steam.loaded = new Set(); // the load's walk polls for 90 s
      const controller = new Controller(
        fakeBackend(calls, { pending: { ...PENDING, layout_walk: true }, get_settings: withDefault() }),
        steam,
        ui,
        instantTiming(),
      );
      await controller.load();
      const walk = controller.layoutWalk();
      const set = controller.setDefaultLayout("workshop://2", "Two");
      await walk;
      await set;
      const order = names();
      expect(order.indexOf("clear_pending")).toBeLessThan(order.indexOf("set_default_layout"));
      expect(calls.filter(([n]) => n === "clear_pending")).toHaveLength(2);
      expect(controller.state.pending?.layout_walk).toBe(false);
    });

    it("waits for a walk that began during the backend call, then walks again as its own", async () => {
      // The load's walk fires once its wait for the shortcut list ends,
      // which can be while set_default_layout is in flight: it passed the
      // flag check under the old default and would clear the flag this
      // change just set.
      const controller = await loaded({
        get_settings: withDefault(),
        set_default_layout: async (url: string | null, title: string | null) => {
          void controller.layoutWalk();
          // the intruding walk has put the old default on its first target
          while (!calls.some(([n]) => n === "record_layout")) await Promise.resolve();
          settingsFile.default_layout = { url: url!, title: title ?? "", when: "2026-09-21T10:00:00Z" };
          return { ok: true, settings: { ...settingsFile }, pending: { ...PENDING, layout_walk: true } };
        },
      });
      controller.store.set({ pending: { ...PENDING, layout_walk: true, last_kind: "sync" } }); // a sync's restart
      expect(await controller.setDefaultLayout("workshop://2", "Two")).toBeNull();
      expect(recorded()[0]).toEqual([BALATRO_SHORTCUT, BALATRO, "default", DEFAULT.url]); // the race was real
      // one clear, by this change's own walk; the intruder left the flag
      expect(calls.filter(([n]) => n === "clear_pending")).toHaveLength(1);
      expect(calls.findIndex(([n]) => n === "clear_pending")).toBeGreaterThan(calls.findIndex(([n]) => n === "set_default_layout"));
      expect(controller.state.pending?.layout_walk).toBe(false);
      for (const [shortcut] of TARGETS) {
        expect(controller.state.layouts[String(shortcut)]).toMatchObject({ result: "default", url: "workshop://2", applied: "workshop://2" });
      }
      expect(ui.bodies).toEqual(["Default layout applied to 7 titles"]);
    });

    it("with status unavailable the walk is deferred and the toast says so", async () => {
      const controller = await loaded({ status: { ok: false, error: "io", message: "status: could not run the CLI" } });
      expect(controller.state.entries).toBeNull();
      expect(await controller.setDefaultLayout(DEFAULT.url, DEFAULT.title)).toBeNull();
      expect(controller.state.settings?.default_layout).toMatchObject({ url: DEFAULT.url });
      expect(controller.state.pending?.layout_walk).toBe(true); // the next load walks
      expect(names()).not.toContain("record_layout");
      expect(names()).not.toContain("clear_pending");
      expect(steam.steamInput.sets).toEqual([]);
      expect(await controller.setDefaultLayout(null, null)).toBeNull();
      expect(controller.state.pending?.layout_walk).toBe(true);
      expect(steam.steamInput.clears).toEqual([]);
      delete steam.steamInput.clearConfig;
      expect(await controller.setDefaultLayout(null, null)).toBeNull();
      expect(ui.bodies).toEqual([
        "Default layout set. It is applied once your titles have loaded.",
        "Default layout cleared. It is taken off your titles once they have loaded.",
        "Default layout cleared. This Steam client cannot unset a layout, so titles keep the one they have.",
      ]);
    });

    it("serialises two calls: each one's walk finishes before the next stores", async () => {
      const controller = await loaded();
      const first = controller.setDefaultLayout("workshop://1", "One");
      const second = controller.setDefaultLayout("workshop://2", "Two");
      await Promise.all([first, second]);
      const sets = calls.map(([n], i) => [n, i] as const).filter(([n]) => n === "set_default_layout").map(([, i]) => i);
      const clears = calls.map(([n], i) => [n, i] as const).filter(([n]) => n === "clear_pending").map(([, i]) => i);
      expect(sets).toHaveLength(2);
      expect(clears).toHaveLength(2);
      expect(clears[0]).toBeLessThan(sets[1]);
      // every entry ends on the second default, put there by the plugin
      for (const [shortcut] of TARGETS) {
        expect(controller.state.layouts[String(shortcut)]).toMatchObject({ result: "default", url: "workshop://2", applied: "workshop://2" });
      }
      expect(ui.bodies).toEqual(["Default layout applied to 7 titles", "Default layout applied to 7 titles"]);
    });

    it("says to export the layout when Steam accepted it nowhere", async () => {
      steam.steamInput.sticksAs = "default://nope";
      const controller = await loaded();
      await controller.setDefaultLayout(DEFAULT.url, DEFAULT.title);
      expect(ui.bodies).toEqual([
        "Steam did not accept this layout on other titles. Export it in Steam's layout screen, select the exported copy, then set it as the default again.",
      ]);
      expect(appliedToast({ applied: 0, unset: 0, kept: 3, unavailable: 0 })).toBe(
        "Default layout applied to 0 titles · 3 kept their own",
      );
      expect(appliedToast({ applied: 2, unset: 0, kept: 1, unavailable: 4 })).toBe(
        "Default layout applied to 2 titles · 1 kept their own · 4 unavailable",
      );
    });

    it("a refused store is toasted and walks nothing", async () => {
      const controller = await loaded({
        set_default_layout: { ok: false, error: "bad-request", message: "url must start with workshop:// or template://" },
      });
      const result = await controller.setDefaultLayout("autosave:///x.vdf", "x");
      expect(result).toMatchObject({ ok: false, error: "bad-request" });
      expect(names()).not.toContain("record_layout");
      expect(ui.bodies).toEqual(["url must start with workshop:// or template://"]);
    });

    it("clearing runs the unset pass and toasts what was removed", async () => {
      const controller = await loaded({ get_settings: withDefault() });
      await controller.setDefaultLayout(DEFAULT.url, DEFAULT.title); // every entry on it
      steam.steamInput.urls.set(SEA_SHORTCUT, "workshop://mine"); // then one is changed by hand
      calls.length = 0;
      ui.bodies.length = 0;
      expect(await controller.setDefaultLayout(null, null)).toBeNull();
      expect(calls.find(([n]) => n === "set_default_layout")?.[1]).toEqual([null, null]);
      expect(controller.state.settings?.default_layout).toBeNull();
      expect(steam.steamInput.clears.map(([shortcut]) => shortcut).sort()).toEqual(
        TARGETS.map(([shortcut]) => shortcut).filter((shortcut) => shortcut !== SEA_SHORTCUT).sort(),
      );
      expect(ui.bodies).toEqual(["Default layout cleared · removed from 6 titles"]);
      expect(controller.state.layouts[String(SEA_SHORTCUT)]).toMatchObject({ result: "kept", url: "workshop://mine", applied: null });
      expect(controller.state.pending?.layout_walk).toBe(false);
      expect(clearedToast({ applied: 0, unset: 2, kept: 0, unavailable: 1 }, true)).toBe(
        "Default layout cleared · removed from 2 titles · 1 unavailable",
      );
    });

    it("clearing on a client that cannot unset a layout says so, and touches nothing", async () => {
      const controller = await loaded({ get_settings: withDefault() });
      await controller.setDefaultLayout(DEFAULT.url, DEFAULT.title);
      delete steam.steamInput.clearConfig;
      calls.length = 0;
      ui.bodies.length = 0;
      expect(await controller.setDefaultLayout(null, null)).toBeNull();
      expect(steam.steamInput.clears).toEqual([]);
      expect(names()).not.toContain("record_layout");
      expect(controller.state.settings?.default_layout).toBeNull();
      expect(controller.state.pending?.layout_walk).toBe(false);
      expect(ui.bodies).toEqual([
        "Default layout cleared. This Steam client cannot unset a layout, so titles keep the one they have.",
      ]);
    });

    it("under picker nothing is set or cleared, and the flag is dropped", async () => {
      const controller = await loaded({
        get_settings: { ok: true, settings: { ...baseSettings(), layout_strategy: "picker" } },
      });
      settingsFile.layout_strategy = "picker";
      await controller.setDefaultLayout(DEFAULT.url, DEFAULT.title);
      await controller.setDefaultLayout(null, null);
      expect(steam.steamInput.sets).toEqual([]);
      expect(steam.steamInput.clears).toEqual([]);
      expect(steam.steamInput.gets).toEqual([]);
      expect(names()).not.toContain("record_layout");
      expect(calls.filter(([n]) => n === "clear_pending")).toHaveLength(2);
    });
  });
});

describe("hidden state and the Streaming group (spec 3.15, 3.17)", () => {
  const BALATRO = 2379780;
  const SEA = 1244090;
  const [BALATRO_S, DESKTOP, HADES, SEA_S, SPIRITFARER, BIG_PICTURE, TUNIC, CLIENT] = [
    2718281828, 3000000101, 3000000011, 2987654321, 2555555555, 3000000102, 3000000007, 2400000001,
  ];
  const sorted = (ids: Iterable<number>) => [...ids].sort((a, b) => a - b);
  const members = () => sorted(steam.lib.collections.get(STREAMING_COLLECTION) ?? []);
  /** `set_settings` answering with the patch applied, like the backend. */
  const patched = (patch: object) => ({
    ok: true,
    settings: { ...baseSettings(), hosts: [], ...patch },
  });
  /** A settings file with Stream shortcuts shown: the group is the fallback collection. */
  const shown = () => ({ ok: true, settings: { ...baseSettings(), hide_stream_shortcuts: false } });

  async function loaded(answers: Partial<Record<keyof Backend, unknown>> = {}) {
    const controller = new Controller(fakeBackend(calls, answers), steam, ui, instantTiming());
    await controller.load();
    await controller.reconcileLibrary();
    return controller;
  }

  it("hides every hidden entry at load and, with the tab standing in, writes no collection", async () => {
    // a visible entry somebody hid in the client
    steam.lib.hidden.add(TUNIC);
    await loaded();
    expect(sorted(steam.lib.hidden)).toEqual(sorted([BALATRO_S, DESKTOP, SEA_S, SPIRITFARER, BIG_PICTURE, CLIENT]));
    expect(steam.lib.collections.has(STREAMING_COLLECTION)).toBe(false);
    expect(steam.lib.log.filter((line) => !line.startsWith("hide") && !line.startsWith("show"))).toEqual([]);
  });

  it("takes an older version's owned games out of the collection and leaves what it does not know", async () => {
    // v0.4.0 put the real games in; 570 is somebody else's (another device, or the user)
    steam.lib.collections.set(STREAMING_COLLECTION, new Set([BALATRO, SEA, 570]));
    await loaded();
    expect(members()).toEqual([570]);
  });

  it("deletes the collection once nothing of it is left", async () => {
    steam.lib.collections.set(STREAMING_COLLECTION, new Set([BALATRO, SEA]));
    await loaded();
    expect(steam.lib.collections.has(STREAMING_COLLECTION)).toBe(false);
  });

  it("changes nothing the second time", async () => {
    const controller = await loaded({ get_settings: shown() });
    steam.lib.log = [];
    await controller.reconcileLibrary();
    expect(steam.lib.log).toEqual([]);
  });

  it("with Stream shortcuts shown, collects this device's shortcuts and never a real game", async () => {
    const controller = await loaded({ set_settings: patched, get_settings: shown() });
    expect(sorted(steam.lib.hidden)).toEqual(sorted([DESKTOP, SPIRITFARER, BIG_PICTURE, CLIENT]));
    // the Stream shortcuts and the visible ones; never the client, a host app, a parked entry
    expect(members()).toEqual(sorted([BALATRO_S, SEA_S, HADES, TUNIC]));
    // hidden again: the tab is alone, and the shortcuts stay (another
    // device keeping the collection shares their appids; only the group
    // turned off takes them out)
    await controller.setSettings({ hide_stream_shortcuts: true });
    await controller.reconcileLibrary();
    expect(members()).toEqual(sorted([BALATRO_S, SEA_S, HADES, TUNIC]));
  });

  it("with the tab alone, removes only the real games and leaves shortcuts, parked or not", async () => {
    // a v0.4.0 collection plus shortcuts another device (or this one, earlier) put in
    steam.lib.collections.set(STREAMING_COLLECTION, new Set([BALATRO, HADES, SPIRITFARER, 570]));
    await loaded();
    expect(members()).toEqual(sorted([HADES, SPIRITFARER, 570]));
  });

  it("with Stream shortcuts shown, leaves a parked title alone: it may be live on another device", async () => {
    steam.lib.collections.set(STREAMING_COLLECTION, new Set([SPIRITFARER]));
    await loaded({ get_settings: shown() });
    expect(members()).toEqual(sorted([BALATRO_S, SEA_S, HADES, TUNIC, SPIRITFARER]));
  });

  it("never deletes a collection on the pass that filled it, even when the client lists the adds late", async () => {
    steam.lib.lateAdds = true;
    const controller = await loaded({ get_settings: shown() });
    expect(steam.lib.collections.has(STREAMING_COLLECTION)).toBe(true);
    expect(steam.lib.log).not.toContain("delete");
    steam.lib.settle();
    await controller.reconcileLibrary();
    expect(members()).toEqual(sorted([BALATRO_S, SEA_S, HADES, TUNIC]));
  });

  it("turning the group off takes every member this device knows out, parked too, and leaves the rest alone afterwards", async () => {
    steam.lib.collections.set(STREAMING_COLLECTION, new Set([570, SPIRITFARER]));
    const controller = await loaded({ set_settings: patched, get_settings: shown() });
    expect(members()).toEqual(sorted([BALATRO_S, SEA_S, HADES, TUNIC, 570, SPIRITFARER]));
    await controller.setSettings({ streaming_collection: false });
    await controller.reconcileLibrary();
    expect(members()).toEqual([570]);
    // and one the user fills under that name later is theirs
    steam.lib.collections.set(STREAMING_COLLECTION, new Set([570, HADES]));
    await controller.reconcileLibrary();
    expect(members()).toEqual(sorted([570, HADES]));
  });

  it("turning the group off deletes a collection that was all this device's", async () => {
    const controller = await loaded({ set_settings: patched, get_settings: shown() });
    await controller.setSettings({ streaming_collection: false });
    expect(steam.lib.collections.has(STREAMING_COLLECTION)).toBe(false);
  });

  it("skips an entry the client has not loaded, and picks it up on the next call", async () => {
    steam.loaded = new Set([BALATRO_S, DESKTOP, SEA_S, SPIRITFARER, BIG_PICTURE, TUNIC, CLIENT, BALATRO, SEA]);
    const controller = await loaded({ get_settings: shown() });
    expect(steam.lib.collections.get(STREAMING_COLLECTION)?.has(HADES)).toBe(false);
    steam.loaded = null;
    await controller.reconcileLibrary();
    expect(steam.lib.collections.get(STREAMING_COLLECTION)?.has(HADES)).toBe(true);
  });

  it("sets the state regardless when the client cannot say what is hidden", async () => {
    steam.lib.readable = false;
    await loaded();
    expect(sorted(steam.lib.hidden)).toEqual(sorted([BALATRO_S, DESKTOP, SEA_S, SPIRITFARER, BIG_PICTURE, CLIENT]));
  });

  it("does nothing on a client with neither call", async () => {
    steam.lib.hiding = false;
    steam.lib.collecting = false;
    const controller = await loaded({ get_settings: shown() });
    expect(steam.lib.log).toEqual([]);
    expect(controller.canHideShortcuts()).toBe(false);
    expect(controller.canKeepCollection()).toBe(false);
  });

  it("does nothing without a status, or while a run is going", async () => {
    await loaded({ status: { ok: false, error: "cli-error", message: "boom", exit: 1 } });
    expect(steam.lib.log).toEqual([]);
    const controller = await loaded();
    steam.lib.log = [];
    steam.lib.hidden.clear();
    await controller.sync();
    await controller.reconcileLibrary();
    expect(steam.lib.log).toEqual([]);
  });

  it("after Remove everything, deletes the collection once the client has dropped the removed shortcuts", async () => {
    // the members' overviews are gone with the shortcuts, so the client lists none
    steam.lib.collections.set(STREAMING_COLLECTION, new Set());
    await loaded({
      status: { ok: true, entries: [], notes: [] },
      pending: { ok: true, ...PENDING, last_kind: "remove" },
    });
    expect(steam.lib.collections.has(STREAMING_COLLECTION)).toBe(false);
  });

  it("leaves a collection somebody already had alone while there is nothing to stream", async () => {
    steam.lib.collections.set(STREAMING_COLLECTION, new Set([570]));
    await loaded({ status: { ok: true, entries: [], notes: [] }, get_settings: shown() });
    expect(members()).toEqual([570]);
    expect(steam.lib.log).toEqual([]);
  });

  it("applies nothing when a run starts during the load's wait", async () => {
    steam.loaded = new Set(); // nothing loads: the wait runs its 90 s
    const controller = new Controller(fakeBackend(calls), steam, ui, instantTiming());
    await controller.load();
    const reconcile = controller.reconcileLibrary(true);
    await controller.sync();
    steam.loaded = null;
    await reconcile;
    expect(steam.lib.log).toEqual([]);
  });

  it("survives a client that throws", async () => {
    steam.lib.setHidden = () => {
      throw new Error("no such store");
    };
    await expect(loaded({ get_settings: shown() })).resolves.toBeDefined();
    // and the collection is still kept
    expect(members()).toEqual(sorted([BALATRO_S, SEA_S, HADES, TUNIC]));
  });
});

describe("the on/off toggle (spec 3.19)", () => {
  const BALATRO = 2379780;
  const [BALATRO_S, DESKTOP, HADES, SEA_S, SPIRITFARER, BIG_PICTURE, TUNIC, CLIENT] = [
    2718281828, 3000000101, 3000000011, 2987654321, 2555555555, 3000000102, 3000000007, 2400000001,
  ];
  const EVERY_ENTRY = [BALATRO_S, DESKTOP, HADES, SEA_S, SPIRITFARER, BIG_PICTURE, TUNIC, CLIENT];
  const HIDDEN_WHEN_ON = [BALATRO_S, DESKTOP, SEA_S, SPIRITFARER, BIG_PICTURE, CLIENT];
  const sorted = (ids: Iterable<number>) => [...ids].sort((a, b) => a - b);
  /** `set_settings` storing the patch, like the backend. */
  const setSettings = (patch: Partial<Settings>) => {
    Object.assign(settingsFile, patch);
    return { ok: true, settings: { ...settingsFile } };
  };

  async function loaded(answers: Partial<Record<keyof Backend, unknown>> = {}) {
    const controller = new Controller(fakeBackend(calls, { set_settings: setSettings, ...answers }), steam, ui, instantTiming());
    await controller.load();
    await controller.reconcileLibrary();
    calls.length = 0;
    return controller;
  }

  it("reads absent as on, and off hides every entry", () => {
    expect(pluginEnabled(null)).toBe(true);
    expect(pluginEnabled({ enabled: false })).toBe(false);
    expect(streamingTabEnabled({ enabled: false, streaming_collection: true })).toBe(false);
    expect(streamingTabEnabled({ enabled: true, streaming_collection: true })).toBe(true);
    const entries = eventsOf(loadFixture("common/status.ndjson"), "entry");
    expect(sorted(hiddenPlan(entries, false, false).hide)).toEqual(sorted(EVERY_ENTRY));
    expect(hiddenPlan(entries, false, false).show).toEqual([]);
    expect(sorted(hiddenPlan(entries, true).hide)).toEqual(sorted(HIDDEN_WHEN_ON));
  });

  it("off hides the visible shortcuts too and takes this device's members out of the collection", async () => {
    settingsFile.hide_stream_shortcuts = false;
    const controller = await loaded();
    expect(sorted(steam.lib.collections.get(STREAMING_COLLECTION) ?? [])).toEqual(sorted([BALATRO_S, SEA_S, HADES, TUNIC]));
    expect(await controller.setEnabled(false)).toMatchObject({ ok: true });
    expect(controller.enabled).toBe(false);
    expect(calls[0]).toEqual(["set_settings", [{ enabled: false }]]);
    expect(sorted(steam.lib.hidden)).toEqual(sorted(EVERY_ENTRY));
    expect(steam.lib.collections.has(STREAMING_COLLECTION)).toBe(false);
    // and a second reconcile adds nothing back
    steam.lib.log = [];
    await controller.reconcileLibrary();
    expect(steam.lib.log).toEqual([]);
  });

  it("off refuses runs, settings and the default layout, and a Stream press launches nothing", async () => {
    const controller = await loaded();
    await controller.setEnabled(false);
    calls.length = 0;
    ui.bodies.length = 0;
    expect(await controller.run("sync")).toEqual(DISABLED_FAILURE);
    expect(controller.state.message).toBe("Moonlight Sync is off");
    expect(await controller.setSettings({ restart_countdown_s: 3 })).toEqual(DISABLED_FAILURE);
    expect(await controller.setDefaultLayout(DEFAULT.url, DEFAULT.title)).toEqual(DISABLED_FAILURE);
    expect(ui.bodies).toEqual(["Moonlight Sync is off"]);
    expect(await controller.streamPress(BALATRO)).toBe(false);
    controller.store.set({ pending: { ...PENDING, restart_needed: "write", last_kind: "sync" } });
    await controller.restartRow();
    expect(steam.launched).toEqual([]);
    expect(names()).toEqual([]);
    expect(steam.steamInput.sets).toEqual([]);
  });

  it("off at load: every entry is hidden, the host is not probed, the walk waits with its flag", async () => {
    settingsFile.enabled = false;
    settingsFile.default_layout = DEFAULT;
    calls.length = 0;
    const controller = new Controller(
      fakeBackend(calls, { set_settings: setSettings, pending: { ok: true, ...PENDING, layout_walk: true, last_kind: "sync" } }),
      steam,
      ui,
      instantTiming(),
    );
    await controller.load();
    await controller.reconcileLibrary();
    expect(await controller.layoutWalk()).toBeNull();
    expect(sorted(steam.lib.hidden)).toEqual(sorted(EVERY_ENTRY));
    expect(names()).not.toContain("check_host");
    expect(names()).not.toContain("clear_pending");
    expect(steam.steamInput.sets).toEqual([]);
    expect(controller.state.pending?.layout_walk).toBe(true);
    expect(controller.state.reach).toBeNull();

    // on again: the client is put back, the host checked, the walk run
    calls.length = 0;
    expect(await controller.setEnabled(true)).toMatchObject({ ok: true });
    await controller.layoutWalk();
    expect(sorted(steam.lib.hidden)).toEqual(sorted(HIDDEN_WHEN_ON));
    expect(names()).toContain("check_host");
    expect(names()).toContain("clear_pending");
    expect(steam.steamInput.sets.length).toBeGreaterThan(0);
  });

  it("is refused while a run is going", async () => {
    const controller = await loaded();
    await controller.sync();
    calls.length = 0;
    expect(await controller.setEnabled(false)).toMatchObject({ ok: false, error: "busy", kind: "sync" });
    expect(names()).toEqual([]);
    expect(controller.enabled).toBe(true);
  });

  it("a refused store is toasted and changes nothing", async () => {
    const controller = await loaded({ set_settings: { ok: false, error: "io", message: "disk full" } });
    expect(await controller.setEnabled(false)).toMatchObject({ ok: false, error: "io" });
    expect(ui.bodies).toEqual(["disk full"]);
    expect(controller.enabled).toBe(true);
    expect(sorted(steam.lib.hidden)).toEqual(sorted(HIDDEN_WHEN_ON));
  });
});

describe("Wake-on-LAN (spec 3.18)", () => {
  async function loaded(answers: Partial<Record<keyof Backend, unknown>> = {}) {
    const controller = new Controller(fakeBackend(calls, answers), steam, ui, instantTiming());
    await controller.load();
    calls.length = 0;
    return controller;
  }

  it("sends to the active host and toasts what went out", async () => {
    const controller = await loaded({
      wake_host: { ok: true, host: "MY-GAMING-PC", mac: "aa:bb:cc:dd:ee:0f", source: "moonlight", sent: 24 },
    });
    const result = await controller.wakeHost();
    expect(result).toMatchObject({ ok: true, sent: 24 });
    expect(calls).toEqual([["wake_host", ["MY-GAMING-PC"]]]);
    expect(ui.bodies).toEqual(["Wake-on-LAN packet sent to MY-GAMING-PC. Give it a minute, then Retry."]);
  });

  it("a host with no MAC is a toast pointing at the Host page", async () => {
    const message = "No MAC address known for MY-GAMING-PC: Moonlight has none for it; enter one on the Host page";
    const controller = await loaded({ wake_host: { ok: false, error: "no-mac", message } });
    const result = await controller.wakeHost();
    expect(result).toMatchObject({ ok: false, error: "no-mac" });
    expect(ui.bodies).toEqual([message]);
  });

  it("does nothing without an active host", async () => {
    const controller = await loaded({
      hosts: { ok: true, active: null, source: null, cached_hosts: [], known: [] },
    });
    expect(await controller.wakeHost()).toBeNull();
    expect(names()).not.toContain("wake_host");
    expect(ui.bodies).toEqual([]);
  });

  it("the Host page's MAC field stores through set_wake_mac and refreshes hosts", async () => {
    const controller = await loaded({
      set_wake_mac: { ok: true, host: "OFFICE-PC", mac: "11:22:33:44:55:66", wake: null },
    });
    const result = await controller.setWakeMac("OFFICE-PC", "11-22-33-44-55-66");
    expect(result).toMatchObject({ ok: true, mac: "11:22:33:44:55:66" });
    expect(names()).toEqual(["set_wake_mac", "hosts"]);
    expect(calls[0][1]).toEqual(["OFFICE-PC", "11-22-33-44-55-66"]);
  });

  it("a refused MAC skips the refresh", async () => {
    const controller = await loaded({
      set_wake_mac: { ok: false, error: "bad-request", message: "a MAC address looks like aa:bb:cc:dd:ee:ff" },
    });
    expect(await controller.setWakeMac("OFFICE-PC", "nope")).toMatchObject({ ok: false, error: "bad-request" });
    expect(names()).toEqual(["set_wake_mac"]);
  });
});
