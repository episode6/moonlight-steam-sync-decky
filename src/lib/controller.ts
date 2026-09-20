/**
 * The frontend's behaviour, independent of React and of `@decky/*`:
 * the load order and first run (spec 3.8), runs and their events, the
 * restart flow (spec 3.9), host switching (spec 3.12) and the settings-page
 * actions. `index.tsx` wires it to the real backend (`makeBackend(callable)`),
 * the real Steam client (`steam.ts`) and the real modal/toaster; the tests
 * wire it to fakes.
 */

import {
  errorText,
  isFailure,
  isSteamUserMismatch,
  type Backend,
  type Failure,
  type Result,
  type RunKind,
  type RunOpts,
  type SettingsPatch,
  type SyncDonePayload,
  type SyncEventPayload,
} from "./cli";
import { restartDecision, unwrittenMessage, type RestartDecision } from "./restart";
import {
  applyRunDone,
  applyRunEvent,
  initialState,
  newRun,
  runFromSyncState,
  Store,
  withCliVersion,
  withStatus,
  type AppState,
} from "./state";

export interface SteamPort {
  ownedApps(): Record<string, string> | null;
  currentSteamId3(): number | null;
  runShortcut(appid: number): boolean;
  shutdownSteam(): void;
}

export interface RestartPrompt {
  decision: RestartDecision;
  /** `settings.restart_countdown_s`; 0 = buttons only. */
  countdownSeconds: number;
  onRestartNow(): void;
  onLater(): void;
}

export interface PromptHandle {
  close(): void;
}

export interface UiPort {
  showRestart(prompt: RestartPrompt): PromptHandle;
  toast(title: string, body: string): void;
}

export interface Timing {
  sleep(ms: number): Promise<void>;
  now(): number;
}

export const LIBRARY_POLL_MS = 500;
export const LIBRARY_TIMEOUT_MS = 60_000;

const realTiming: Timing = {
  sleep: (ms) => new Promise((resolve) => setTimeout(resolve, ms)),
  now: () => Date.now(),
};

const RUN_CALLS: Record<RunKind, "start_sync" | "start_art_refetch" | "start_remove_all"> = {
  sync: "start_sync",
  art: "start_art_refetch",
  remove: "start_remove_all",
};

export class Controller {
  readonly store = new Store<AppState>(initialState());
  private loading: Promise<void> | null = null;
  private prompt: PromptHandle | null = null;
  private lastRunOpts: RunOpts = {};
  private mismatchRetried = false;
  /** The run a `start_*` call is starting, until the call answers. */
  private starting: { kind: RunKind; immediate: boolean } | null = null;

  constructor(
    private readonly backend: Backend,
    private readonly steam: SteamPort,
    private readonly ui: UiPort,
    private readonly timing: Timing = realTiming,
  ) {}

  get state(): AppState {
    return this.store.get();
  }

  // -------------------------------------------------------------------------
  // load order (spec 3.8)

  /** Runs the load order once; later calls return the same promise. */
  load(): Promise<void> {
    if (!this.loading) this.loading = this.doLoad();
    return this.loading;
  }

  private async doLoad(): Promise<void> {
    try {
      await this.loadOrder();
    } finally {
      // Step 1 answered with a failure (an io/protocol failure, not
      // "CLI missing" -- that is a `cli` state), so there is nothing to
      // render and steps 3-5 never ran. Forget the cached promise so the
      // next panelOpened() / refreshCli() runs the whole order again.
      if (this.state.cli === null) this.loading = null;
    }
  }

  private async loadOrder(): Promise<void> {
    // (1) the CLI
    const version = await this.backend.cli_version();
    if (isFailure(version)) this.store.set({ message: errorText(version) });
    else this.store.set((s) => withCliVersion(s, version));
    const cliOk = this.state.cli?.state === "ok";

    // (2) in parallel: settings, hosts, pending, sync_state
    const [settings, hosts, pending, syncState] = await Promise.all([
      this.backend.get_settings(),
      cliOk ? this.backend.hosts() : Promise.resolve(null),
      this.backend.pending(),
      this.backend.sync_state(),
    ]);
    this.store.set({
      settings: isFailure(settings) ? null : settings.settings,
      hosts: hosts && !isFailure(hosts) ? hosts : null,
      pending: isFailure(pending) ? null : pending,
    });
    if (!isFailure(syncState)) {
      const run = runFromSyncState(syncState);
      if (run) this.store.set({ run });
      if (run?.running && run.awaiting) this.onAwaiting();
    }
    await this.refreshIgnored();
    this.store.set({ loaded: true });
    if (!cliOk) return; // steps 3-5 need the CLI

    // (3) the library, then owned-apps.json
    await this.loadLibrary();
    if (this.state.library !== "ready") return;

    // (4) status + reachability (the layout walk is PR-7; the persistent
    // restart row renders from `pending`)
    await Promise.all([this.refreshStatus(), this.checkHost(false)]);
  }

  /** Step 3: poll the library every 500 ms (60 s at most), then write owned-apps.json. */
  async loadLibrary(): Promise<void> {
    this.store.set({ library: "loading" });
    const deadline = this.timing.now() + LIBRARY_TIMEOUT_MS;
    let apps = this.steam.ownedApps();
    while (!apps && this.timing.now() < deadline) {
      await this.timing.sleep(LIBRARY_POLL_MS);
      apps = this.steam.ownedApps();
    }
    if (!apps) {
      this.store.set({ library: "failed" });
      return;
    }
    const written = await this.writeOwnedApps(apps);
    this.store.set({ library: written ? "failed" : "ready" });
  }

  /** `null` on success, else the failure. */
  private async writeOwnedApps(apps?: Record<string, string> | null): Promise<Failure | null> {
    const owned = apps ?? this.steam.ownedApps();
    const steamid3 = this.steam.currentSteamId3();
    if (!owned) {
      return { ok: false, error: "owned-apps-empty", message: "Steam library not loaded" };
    }
    if (steamid3 === null) {
      return { ok: false, error: "bad-request", message: "the current Steam user is not known yet" };
    }
    const result = await this.backend.write_owned_apps(steamid3, owned);
    return isFailure(result) ? result : null;
  }

  /** A collecting call, retried once after rewriting owned-apps.json on a steamid3 mismatch. */
  private async withOwnedRetry<T extends object>(call: () => Promise<Result<T>>): Promise<Result<T>> {
    const result = await call();
    if (isFailure(result) && isSteamUserMismatch(result)) {
      const failed = await this.writeOwnedApps();
      if (!failed) return call();
    }
    return result;
  }

  // -------------------------------------------------------------------------
  // refreshes

  async refreshStatus(): Promise<void> {
    const result = await this.withOwnedRetry(() => this.backend.status());
    if (!isFailure(result)) this.store.set((s) => withStatus(s, result.entries));
  }

  async refreshHosts(): Promise<void> {
    const result = await this.backend.hosts();
    if (!isFailure(result)) this.store.set({ hosts: result });
  }

  async refreshPending(): Promise<void> {
    const result = await this.backend.pending();
    if (!isFailure(result)) this.store.set({ pending: result });
  }

  async refreshSettings(): Promise<void> {
    const result = await this.backend.get_settings();
    if (!isFailure(result)) this.store.set({ settings: result.settings });
  }

  private async refreshIgnored(): Promise<void> {
    const result = await this.backend.get_ignored();
    if (!isFailure(result)) this.store.set({ ignoredCount: result.ignored.length });
  }

  /** The host row's reachability (memoised 10 s by the backend; `force` bypasses). */
  async checkHost(force: boolean): Promise<void> {
    const active = this.state.hosts?.active;
    if (!active || this.state.cli?.state !== "ok" || this.state.library !== "ready") return;
    this.store.set({ reachLoading: true });
    const result = await this.withOwnedRetry(() => this.backend.check_host(active, force));
    this.store.set({ reachLoading: false, reach: isFailure(result) ? null : result });
    if (isFailure(result)) this.store.set({ message: errorText(result) });
  }

  /** The Quick Access panel was opened. */
  async panelOpened(): Promise<void> {
    await this.load();
    if (this.state.library === "ready" && !this.state.run?.running) {
      await Promise.all([this.checkHost(false), this.refreshPending()]);
    }
  }

  // -------------------------------------------------------------------------
  // runs

  /** Write owned-apps.json (step 5), then start a run. */
  async startRun(kind: RunKind, opts: RunOpts = {}): Promise<Failure | null> {
    const written = await this.writeOwnedApps();
    if (written) {
      this.store.set({ message: errorText(written) });
      return written;
    }
    const immediate = !!opts.immediate_restart;
    // Before the call: its first events (even awaiting-steam-exit) may reach
    // onSyncEvent before its answer does, and must see this run's intent.
    this.closePrompt();
    this.starting = { kind, immediate };
    let result: Result;
    try {
      result = await this.backend[RUN_CALLS[kind]](opts);
    } finally {
      this.starting = null;
    }
    if (isFailure(result)) {
      this.store.set({ message: errorText(result) });
      return result;
    }
    this.lastRunOpts = opts;
    // An event may have beaten the call's answer here; keep what it started.
    const current = this.state.run;
    const run =
      current?.running && current.kind === kind && current.events.length
        ? { ...current, immediate }
        : newRun(kind, immediate);
    this.store.set({ run, message: null });
    return null;
  }

  /** A user-initiated run (Sync now, Re-fetch all art, Remove everything). */
  run(kind: RunKind): Promise<Failure | null> {
    this.mismatchRetried = false;
    return this.startRun(kind);
  }

  sync(): Promise<Failure | null> {
    return this.run("sync");
  }

  async stop(): Promise<void> {
    await this.backend.stop_sync();
  }

  onSyncEvent(payload: SyncEventPayload): void {
    let run = this.state.run;
    if (!run || !run.running) {
      const starting = this.starting?.kind === payload.kind ? this.starting : null;
      run = newRun(payload.kind, starting?.immediate ?? false);
    }
    run = applyRunEvent(run, payload.event);
    this.store.set({ run });
    if (payload.event.event === "awaiting-steam-exit") this.onAwaiting();
  }

  /** Trigger 1: the CLI is waiting for the client to exit. */
  private onAwaiting(): void {
    const run = this.state.run;
    if (!run) return;
    if (this.state.pending) {
      this.store.set({ pending: { ...this.state.pending, restart_needed: "write" } });
    }
    // Decision 29, belt and braces: an immediate run whose wait begins while
    // a game is running must not pull the client out from under it. Fall
    // through to the modal, which already says so (`countdownLine`).
    if (run.immediate && !this.state.inGame) {
      this.steam.shutdownSteam();
      return;
    }
    const decision = restartDecision(run.events, null);
    this.showPrompt(decision, {
      onRestartNow: () => this.steam.shutdownSteam(),
      onLater: () => {
        void this.stop();
      },
    });
  }

  async onSyncDone(done: SyncDonePayload): Promise<void> {
    const before = this.state.run ?? newRun(done.kind);
    const run = applyRunDone(before, done);
    this.store.set({ run, pending: done.pending });

    if (isSteamUserMismatch(done.failure) && !this.mismatchRetried) {
      this.mismatchRetried = true;
      await this.startRun(done.kind, this.lastRunOpts);
      return;
    }

    let message: string | null = null;
    if (run.sawAwaiting) {
      if (!run.commit?.written) {
        this.closePrompt();
        message = unwrittenMessage(done.exit) || null;
      }
      // commit.written: the client is already going down; nothing to do.
    } else {
      const decision = restartDecision(run.events, done.exit);
      if (decision.kind === "art") {
        this.showPrompt(decision, {
          onRestartNow: () => {
            void this.restartForArt();
          },
          onLater: () => undefined,
        });
      } else if (done.failure && done.failure.error !== "cli-error") {
        message = errorText({ ok: false, ...done.failure });
      } else {
        message = decision.title || null;
      }
    }
    this.store.set({ message });
    await Promise.all([this.refreshStatus(), this.refreshHosts(), this.refreshIgnored()]);
  }

  private showPrompt(
    decision: RestartDecision,
    actions: Pick<RestartPrompt, "onRestartNow" | "onLater">,
  ): void {
    this.closePrompt();
    const countdownSeconds = this.state.settings?.restart_countdown_s ?? 5;
    this.prompt = this.ui.showRestart({ decision, countdownSeconds, ...actions });
    this.ui.toast(
      decision.title,
      this.state.inGame ? "Restart Steam when you're done playing." : "Steam needs a restart to show the changes.",
    );
  }

  private closePrompt(): void {
    if (this.prompt) {
      this.prompt.close();
      this.prompt = null;
    }
  }

  /** Art only: clear the flag, then restart (no CLI involved). */
  async restartForArt(): Promise<void> {
    await this.backend.clear_pending("restart_needed");
    this.steam.shutdownSteam();
  }

  /** The persistent *Restart Steam to apply* row (spec 3.9). */
  async restartRow(): Promise<void> {
    const pending = this.state.pending;
    if (!pending || pending.restart_needed === "none") return;
    // Decision 29: both paths end in a Steam restart, so both are refused
    // while a game is running (the row itself is disabled, `restartRowView`).
    if (this.state.inGame) return;
    if (pending.restart_needed === "art") {
      await this.restartForArt();
      return;
    }
    if (this.state.run?.running) return; // "finishing the previous run…"
    await this.startRun(pending.last_kind ?? "sync", { immediate_restart: true });
  }

  // -------------------------------------------------------------------------
  // hosts (spec 3.12)

  /** Switch to `name` (after the UI's confirm) and sync. */
  async switchHost(name: string): Promise<Failure | null> {
    const result = await this.backend.set_host(name);
    if (isFailure(result)) {
      this.store.set({ message: errorText(result) });
      return result;
    }
    this.store.set({ reach: null });
    await this.refreshHosts();
    return this.sync();
  }

  async addHost(name: string): Promise<Result<{ count: number; made_active: boolean }>> {
    const written = await this.writeOwnedApps();
    if (written) return written;
    const result = await this.withOwnedRetry(() => this.backend.add_host(name));
    await this.refreshHosts();
    if (!isFailure(result) && result.made_active) await this.checkHost(true);
    return result;
  }

  async forgetHost(name: string): Promise<Result<{ known: string[] }>> {
    const result = await this.backend.forget_host(name);
    await this.refreshHosts();
    return result;
  }

  // -------------------------------------------------------------------------
  // everything else the pages do

  openMoonlight(): boolean {
    const appid = this.state.clientAppid;
    if (appid === null) return false;
    const ok = this.steam.runShortcut(appid);
    if (!ok) this.ui.toast("Moonlight Sync", "The Moonlight shortcut is not loaded yet");
    return ok;
  }

  async setSettings(patch: SettingsPatch): Promise<Result> {
    const result = await this.backend.set_settings(patch);
    if (!isFailure(result)) this.store.set({ settings: result.settings });
    return result;
  }

  setInGame(inGame: boolean): void {
    if (this.state.inGame !== inGame) this.store.set({ inGame });
  }

  /** The library row's *Retry* (step 3 again). */
  async retryLibrary(): Promise<void> {
    await this.loadLibrary();
    if (this.state.library === "ready") {
      await Promise.all([this.refreshStatus(), this.checkHost(false)]);
    }
  }

  /** Re-read the CLI state (About after an install by hand). */
  async refreshCli(): Promise<void> {
    if (!this.loading) {
      // The load order never got past step 1 (see doLoad): run all of it
      // again rather than only re-reading the version.
      await this.load();
      return;
    }
    const version = await this.backend.cli_version();
    if (isFailure(version)) this.store.set({ message: errorText(version) });
    else this.store.set((s) => withCliVersion(s, version));
  }
}
