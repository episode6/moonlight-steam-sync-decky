/**
 * The frontend's behaviour, independent of React and of `@decky/*`:
 * the load order and first run (spec 3.8), runs and their events, the
 * restart flow (spec 3.9), the Stream press and the controller-layout copy
 * (spec 3.10), host switching (spec 3.12) and the settings-page actions.
 * `index.tsx` wires it to the real backend (`makeBackend(callable)`), the
 * real Steam client (`steam.ts`) and the real modal/toaster; the tests wire
 * it to fakes.
 */

import {
  errorText,
  isFailure,
  isSteamUserMismatch,
  type AppEvent,
  type Backend,
  type EntryEvent,
  type Failure,
  type LayoutResult,
  type PinnedEvent,
  type Result,
  type RunKind,
  type RunOpts,
  type SettingsPatch,
  type SyncDonePayload,
  type SyncEventPayload,
} from "./cli";
import type { PinChoice } from "./join";
import {
  copyEnabled,
  copyLayout,
  WALK_POLL_MS,
  WALK_STEP_MS,
  WALK_TIMEOUT_MS,
  walkPairs,
  type LayoutOutcome,
  type SteamInput,
} from "./layouts";
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
  type HostAppKey,
} from "./state";

export interface SteamPort {
  ownedApps(): Record<string, string> | null;
  currentSteamId3(): number | null;
  runShortcut(appid: number): boolean;
  shutdownSteam(): void;
  /** The Steam Input seam `copyLayout` runs over (spec 3.10). */
  input(): SteamInput;
  /** `appStore.GetAppOverviewByAppID(appid)` is non-null (the shortcut list is loaded). */
  overviewLoaded(appid: number): boolean;
  /** The client has `SteamClient.Apps.ShowControllerConfigurator` (else *Choose layout* is hidden). */
  canChooseLayout(): boolean;
  /** Open Steam's layout picker for a shortcut; `false` when the client cannot. */
  showControllerConfigurator(appid: number): boolean;
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

/** What the Titles page renders from (spec 3.8, PR-6's amendment). */
export interface TitlesData {
  /** `list`'s apps: live, or from the per-host cache when the host is unreachable. */
  apps: AppEvent[];
  /** `status`'s entries (empty when `status` failed; `statusError` says why). */
  entries: EntryEvent[];
  /** `ignore.json`. */
  ignored: string[];
  host: string;
  /**
   * `live` = a fresh `list`; `cached` = the per-host cache because the host
   * is unreachable; `syncing` = the cache because a run is rewriting it.
   */
  source: "live" | "cached" | "syncing";
  /** The cache's timestamp for a cached listing ("cached from <when>"). */
  cachedWhen: string | null;
  /** The CLI's message when the live listing failed with exit 3. */
  unreachable: string | null;
  statusError: string | null;
}

export type TitlesLoad =
  | { ok: true; data: TitlesData }
  | { ok: false; message: string; neverSynced: boolean };

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
  /** The layout walk in progress (spec 3.10: never two at once). */
  private walking: Promise<void> | null = null;

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
      // Step 1 answered with a failure (an io/protocol failure, not "CLI
      // missing" -- that is a `cli` state; see readCli's `cliError`), so
      // there is nothing to render and steps 3-5 never ran. Forget the
      // cached promise, so the next panelOpened() runs the whole order
      // again rather than resolving straight away. (The panel's Retry goes
      // through refreshCli(), which finishes the order in place.)
      if (this.state.cli === null) this.loading = null;
    }
  }

  private async loadOrder(): Promise<void> {
    // (1) the CLI
    const cliOk = await this.readCli();

    // (2) in parallel: settings, hosts, pending, sync_state (and layouts.json,
    // a plugin file like settings)
    const [settings, hosts, pending, syncState, layouts] = await Promise.all([
      this.backend.get_settings(),
      cliOk ? this.backend.hosts() : Promise.resolve(null),
      this.backend.pending(),
      this.backend.sync_state(),
      this.backend.layouts(),
    ]);
    this.store.set({
      settings: isFailure(settings) ? null : settings.settings,
      hosts: hosts && !isFailure(hosts) ? hosts : null,
      pending: isFailure(pending) ? null : pending,
      layouts: isFailure(layouts) ? {} : layouts.entries,
    });
    if (!isFailure(syncState)) {
      const run = runFromSyncState(syncState);
      if (run) this.store.set({ run });
      if (run?.running && run.awaiting) this.onAwaiting();
    }
    await this.refreshIgnored();
    this.store.set({ loaded: true });
    if (!cliOk) return; // steps 3-5 need the CLI
    await this.finishLoad();
  }

  /**
   * Step 1: read the CLI's version. `false` when it is missing, too old or
   * could not be read at all; the last case leaves `cli` null and records
   * `cliError`, which the panel offers a Retry for.
   */
  private async readCli(): Promise<boolean> {
    const version = await this.backend.cli_version();
    if (isFailure(version)) {
      this.store.set({ cliError: errorText(version) });
      return false;
    }
    this.store.set((s) => withCliVersion(s, version));
    return this.state.cli?.state === "ok";
  }

  /** Steps 3-5, once the CLI is known to be there. */
  private async finishLoad(): Promise<void> {
    // (3) the library, then owned-apps.json
    await this.loadLibrary();
    if (this.state.library !== "ready") return;

    // (4) status + reachability, then the layout walk when a sync's restart
    // just happened (`pending.layout_walk`, spec 3.10); the persistent
    // restart row renders from `pending`. The walk can take 90 s, so the
    // load does not wait for it (it is kept from running twice by itself).
    await Promise.all([this.refreshStatus(), this.checkHost(false)]);
    void this.layoutWalk();
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

  /**
   * One rewrite of owned-apps.json at a time: concurrent calls that all hit
   * the same steamid3 mismatch share it instead of each writing the file.
   */
  private rewritingOwned: Promise<Failure | null> | null = null;

  private rewriteOwnedApps(): Promise<Failure | null> {
    if (!this.rewritingOwned) {
      this.rewritingOwned = this.writeOwnedApps().finally(() => {
        this.rewritingOwned = null;
      });
    }
    return this.rewritingOwned;
  }

  /** A collecting call, retried once after rewriting owned-apps.json on a steamid3 mismatch. */
  private async withOwnedRetry<T extends object>(call: () => Promise<Result<T>>): Promise<Result<T>> {
    const result = await call();
    if (isFailure(result) && isSteamUserMismatch(result)) {
      const failed = await this.rewriteOwnedApps();
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

  async refreshLayouts(): Promise<void> {
    const result = await this.backend.layouts();
    if (!isFailure(result)) this.store.set({ layouts: result.entries });
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
    // layouts.json too: a remove run deletes it
    await Promise.all([this.refreshStatus(), this.refreshHosts(), this.refreshIgnored(), this.refreshLayouts()]);
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
  // the Titles page (spec 3.8)

  /** When a cached listing was taken, from its apps or from `host show`. */
  private cachedStamp(active: string, apps: AppEvent[]): string | null {
    return (
      apps.find((app) => app.cached_when)?.cached_when ??
      this.state.hosts?.cached_hosts.find((c) => c.name.toLowerCase() === active.toLowerCase())?.when ??
      null
    );
  }

  /**
   * `list_apps()`, `status()` and `ignore.json` for the Titles page. When
   * the live listing fails with exit 3 (host unreachable) the page reads
   * `list_cached(active)` instead; exit 3 there means there is no cache for
   * the host yet ("never synced").
   *
   * While a run is going the page reads `list_cached(active)` from the
   * start (`source: "syncing"`): a live `list` would race the running CLI's
   * own listing and cache write, and buys nothing because the page re-lists
   * when the run finishes.
   */
  async loadTitles(): Promise<TitlesLoad> {
    const active = this.state.hosts?.active;
    if (!active) return { ok: false, message: "No host yet; add one on the Host page", neverSynced: false };
    const running = !!this.state.run?.running;
    const [listed, status, ignored] = await Promise.all([
      running
        ? this.withOwnedRetry(() => this.backend.list_cached(active))
        : this.withOwnedRetry(() => this.backend.list_apps()),
      this.withOwnedRetry(() => this.backend.status()),
      this.backend.get_ignored(),
    ]);
    let apps: AppEvent[];
    let source: TitlesData["source"] = running ? "syncing" : "live";
    let cachedWhen: string | null = null;
    let unreachable: string | null = null;
    if (!isFailure(listed)) {
      apps = listed.apps;
      if (running) cachedWhen = this.cachedStamp(active, apps);
    } else if (running) {
      const neverSynced = listed.error === "cli-error" && listed.exit === 3;
      const message = neverSynced
        ? `${active} was never synced; this list fills in when the sync finishes`
        : errorText(listed);
      return { ok: false, message, neverSynced };
    } else if (listed.error === "cli-error" && listed.exit === 3) {
      unreachable = listed.message;
      const cached = await this.withOwnedRetry(() => this.backend.list_cached(active));
      if (isFailure(cached)) {
        const neverSynced = cached.error === "cli-error" && cached.exit === 3;
        return {
          ok: false,
          message: neverSynced ? `${active} is unreachable and was never synced` : errorText(cached),
          neverSynced,
        };
      }
      apps = cached.apps;
      source = "cached";
      cachedWhen = this.cachedStamp(active, apps);
    } else {
      return { ok: false, message: errorText(listed), neverSynced: false };
    }
    // Only fold status into the shared store when nothing is running: while
    // a run is going the panel's counters and stream map belong to the run
    // (the Titles page is reading the cache anyway), and a mid-run `status`
    // snapshot would flicker them. The page still gets these entries below.
    if (!isFailure(status) && !running) this.store.set((s) => withStatus(s, status.entries));
    const ignoredNames = isFailure(ignored) ? [] : ignored.ignored;
    if (!isFailure(ignored)) this.store.set({ ignoredCount: ignoredNames.length });
    return {
      ok: true,
      data: {
        apps,
        entries: isFailure(status) ? [] : status.entries,
        ignored: ignoredNames,
        host: active,
        source,
        cachedWhen,
        unreachable,
        statusError: isFailure(status) ? errorText(status) : null,
      },
    };
  }

  /** *Use this* in the Change match modal: `pin` with `--defer-art` (Decision 8). */
  pinTitle(name: string, choice: PinChoice): Promise<Result<{ pinned: PinnedEvent; notes: string[] }>> {
    return this.backend.pin(name, choice.steam, choice.sgdb, choice.none);
  }

  /** *Ignore* / *Unignore*: `ignore.json` only; the next sync applies it. */
  async setIgnored(name: string, ignored: boolean): Promise<Result<{ ignored: string[] }>> {
    const result = await this.backend.set_ignored(name, ignored);
    if (!isFailure(result)) {
      // The panel's Ignored counter: check_host's count is stale now (the
      // backend dropped its memo), so fall back to ignore.json's size.
      const reach = this.state.reach;
      this.store.set({
        ignoredCount: result.ignored.length,
        reach: reach?.reachable ? { ...reach, ignored: undefined } : reach,
      });
    }
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

  /**
   * A press of the panel's *Desktop* / *Steam Big Picture* button. It starts
   * a stream, so like the Stream button it is only a toast while anything is
   * running.
   */
  openHostApp(key: HostAppKey): boolean {
    const appid = this.state.hostApps[key];
    if (appid === null) return false;
    if (this.state.inGame) {
      this.ui.toast("Moonlight Sync", "Something is already running");
      return false;
    }
    const ok = this.steam.runShortcut(appid);
    if (!ok) this.ui.toast("Moonlight Sync", "That shortcut is not loaded yet; restart Steam first");
    return ok;
  }

  // -------------------------------------------------------------------------
  // the Stream button and controller layouts (spec 3.9, 3.10)

  /** Is there a Stream button for this owned game right now? */
  hasStream(steamAppid: number): boolean {
    return this.state.streamMap.has(steamAppid);
  }

  /**
   * A press of the Stream button on an owned game's library page: while
   * anything is running only a toast; otherwise the layout copy (strategy
   * `copy` and the Advanced toggle on), recorded, then the hidden shortcut
   * is run through Steam. `false` when nothing was launched.
   */
  async streamPress(steamAppid: number): Promise<boolean> {
    const shortcut = this.state.streamMap.get(steamAppid);
    if (shortcut === undefined) return false;
    if (this.state.inGame) {
      this.ui.toast("Moonlight Sync", "Something is already running");
      return false;
    }
    if (copyEnabled(this.state.settings)) await this.copyAndRecord(steamAppid, shortcut);
    const ok = this.steam.runShortcut(shortcut);
    if (!ok) this.ui.toast("Moonlight Sync", "The Stream shortcut is not loaded yet; restart Steam");
    return ok;
  }

  /**
   * *Choose layout* on a Titles row: Steam's own layout picker for the
   * hidden shortcut, recorded as `picker` (under either strategy; under
   * `picker` it is the only layout affordance). `false` when the client has
   * no such method, in which case the pages hide the action.
   */
  async chooseLayout(shortcutAppid: number, realAppid: number): Promise<boolean> {
    if (!this.steam.showControllerConfigurator(shortcutAppid)) return false;
    await this.recordLayout(shortcutAppid, realAppid, "picker", null);
    return true;
  }

  canChooseLayout(): boolean {
    return this.steam.canChooseLayout();
  }

  private async copyAndRecord(realAppid: number, shortcutAppid: number): Promise<LayoutOutcome> {
    const outcome = await copyLayout(realAppid, shortcutAppid, this.steam.input());
    await this.recordLayout(shortcutAppid, realAppid, outcome.result, outcome.url);
    return outcome;
  }

  private async recordLayout(
    shortcutAppid: number,
    realAppid: number,
    result: LayoutResult,
    url: string | null,
  ): Promise<void> {
    const recorded = await this.backend.record_layout(shortcutAppid, realAppid, result, url);
    if (!isFailure(recorded)) this.store.set({ layouts: recorded.entries });
  }

  /**
   * The post-restart walk (spec 3.10): when `pending.layout_walk` says a
   * sync's restart just happened, copy the layout of every pair in the
   * stream map once the shortcut list is loaded, then clear the flag. With
   * the copy off (strategy `picker`, or the toggle) the flag is cleared at
   * once. Never runs twice at the same time: a call while one is going
   * returns that walk's promise.
   */
  layoutWalk(): Promise<void> {
    if (!this.walking) {
      this.walking = this.doWalk().finally(() => {
        this.walking = null;
      });
    }
    return this.walking;
  }

  private async doWalk(): Promise<void> {
    if (!this.state.pending?.layout_walk) return;
    if (!copyEnabled(this.state.settings)) {
      await this.clearWalk();
      return;
    }
    if (this.state.entries === null) {
      // `status` has not answered (it failed, or has not run yet), so the
      // stream map is empty for want of data rather than because there is
      // nothing to walk. Leave pending.layout_walk set and do nothing: the
      // next load, or the panel's Retry, walks once status is in.
      return;
    }
    this.store.set({ walking: true });
    try {
      const pairs = walkPairs(this.state.streamMap);
      // Readiness: every shortcut in the map resolves to an overview, polled
      // every 2 s for at most 90 s (normally immediate).
      const deadline = this.timing.now() + WALK_TIMEOUT_MS;
      const unresolved = () => pairs.filter((pair) => !this.steam.overviewLoaded(pair.shortcutAppid));
      while (unresolved().length && this.timing.now() < deadline) await this.timing.sleep(WALK_POLL_MS);
      for (const { realAppid, shortcutAppid } of pairs) {
        if (this.steam.overviewLoaded(shortcutAppid)) {
          await this.copyAndRecord(realAppid, shortcutAppid);
        } else {
          console.warn(`Moonlight Sync: shortcut ${shortcutAppid} (Steam ${realAppid}) never loaded; layout not copied`);
          await this.recordLayout(shortcutAppid, realAppid, "unavailable", null);
        }
        await this.timing.sleep(WALK_STEP_MS);
      }
      await this.clearWalk();
    } finally {
      this.store.set({ walking: false });
    }
  }

  private async clearWalk(): Promise<void> {
    const result = await this.backend.clear_pending("layout_walk");
    if (!isFailure(result)) this.store.set({ pending: result });
    else if (this.state.pending) this.store.set({ pending: { ...this.state.pending, layout_walk: false } });
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

  /**
   * Re-read the CLI state: About's *Refresh* after an install by hand, and the
   * panel's Retry when `cli_version()` itself failed. When the CLI turns out
   * to be there and the load stopped short of it, the rest of the load order
   * (hosts, the library, status, reachability) runs now.
   */
  async refreshCli(): Promise<void> {
    if (!(await this.readCli())) return;
    if (this.state.library !== "waiting") return; // steps 3-5 already ran
    if (!this.state.hosts) await this.refreshHosts();
    await this.finishLoad();
  }
}
