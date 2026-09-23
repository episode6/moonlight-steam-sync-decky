/**
 * The frontend's behaviour, independent of React and of `@decky/*`:
 * the load order and first run (spec 3.8), runs and their events, the
 * restart flow (spec 3.9), the Stream press and the default controller
 * layout (spec 3.10, 3.16), host switching (spec 3.12) and the
 * settings-page actions.
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
  type WakeResult,
} from "./cli";
import type { PinChoice } from "./join";
import {
  applyDefault,
  defaultLayoutOf,
  isShareableUrl,
  isUnselected,
  layoutKindText,
  layoutStrategy,
  unsetApplied,
  WALK_POLL_MS,
  WALK_STEP_MS,
  WALK_TIMEOUT_MS,
  walkTargets,
  type LayoutConfig,
  type SteamInput,
} from "./layouts";
import {
  collectionDiff,
  collectionMembers,
  knownAppids,
  removableAppids,
  hiddenPlan,
  hideStreamEnabled,
  pluginEnabled,
  STREAMING_COLLECTION,
  streamingCollectionEnabled,
  type LibraryPort,
} from "./library";
import { restartDecision, unwrittenMessage, type RestartDecision } from "./restart";
import {
  applyRunDone,
  applyRunEvent,
  initialState,
  layoutEntryFor,
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
  /** The Steam Input seam `applyDefault` / `unsetApplied` run over (spec 3.10, 3.16). */
  input(): SteamInput;
  /** `appStore.GetAppOverviewByAppID(appid)` is non-null (the shortcut list is loaded). */
  overviewLoaded(appid: number): boolean;
  /** The client has `SteamClient.Apps.ShowControllerConfigurator` (else *Choose layout* is hidden). */
  canChooseLayout(): boolean;
  /** Open Steam's layout picker for a shortcut; `false` when the client cannot. */
  showControllerConfigurator(appid: number): boolean;
  /** The client's hidden state and collections (spec 3.15). */
  library(): LibraryPort;
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

/** What one layout walk did (spec 3.16.4). */
export interface WalkCounts {
  /** Entries now on the default (result `default`, whether just set or already there). */
  applied: number;
  /** Entries whose plugin-set layout a successful `clearConfig` took off. */
  unset: number;
  /** Entries left alone: a selection the plugin did not make. */
  kept: number;
  unavailable: number;
}

/** What *Use as the default layout* finds on a title (spec 3.16.5). */
export type LayoutInspection =
  | { ok: true; url: string; title: string }
  | { ok: false; reason: "no-controller" | "unselected" | "not-shareable" };

const NO_WALK: WalkCounts = { applied: 0, unset: 0, kept: 0, unavailable: 0 };

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

/** The toast after a default was set (spec 3.16.4), the texts exactly. */
export function appliedToast({ applied, kept, unavailable }: WalkCounts): string {
  if (applied === 0 && unavailable > 0) {
    return (
      "Steam did not accept this layout on other titles. Export it in Steam's layout screen, " +
      "select the exported copy, then set it as the default again."
    );
  }
  let text = `Default layout applied to ${applied} titles`;
  if (kept > 0) text += ` · ${kept} kept their own`;
  if (unavailable > 0) text += ` · ${unavailable} unavailable`;
  return text;
}

/** What a write refused while the plugin is off answers (spec 3.19). */
export const DISABLED_FAILURE: Failure = { ok: false, error: "bad-request", message: "Moonlight Sync is off" };

const CANNOT_UNSET_TOAST =
  "Default layout cleared. This Steam client cannot unset a layout, so titles keep the one they have.";

/** The toast after a clear (spec 3.16.4); `canClear` is whether the client has `clearConfig`. */
export function clearedToast({ unset, unavailable }: WalkCounts, canClear: boolean): string {
  if (!canClear) return CANNOT_UNSET_TOAST;
  let text = `Default layout cleared · removed from ${unset} titles`;
  if (unavailable > 0) text += ` · ${unavailable} unavailable`;
  return text;
}

/**
 * The toast when the walk could not run because `status` has not answered
 * (spec 3.16.4, Decision 54): the default is stored, `pending.layout_walk`
 * stays set, and the next load walks. A clear on a client without
 * `clearConfig` keeps its own text, since nothing is unset later either.
 */
export function deferredToast(cleared: boolean, canClear: boolean): string {
  if (cleared && !canClear) return CANNOT_UNSET_TOAST;
  return cleared
    ? "Default layout cleared. It is taken off your titles once they have loaded."
    : "Default layout set. It is applied once your titles have loaded.";
}

export class Controller {
  readonly store = new Store<AppState>(initialState());
  private loading: Promise<void> | null = null;
  private prompt: PromptHandle | null = null;
  private lastRunOpts: RunOpts = {};
  private mismatchRetried = false;
  /** The run a `start_*` call is starting, until the call answers. */
  private starting: { kind: RunKind; immediate: boolean } | null = null;
  /** The layout walk in progress (spec 3.10: never two at once). */
  private walking: Promise<WalkCounts | null> | null = null;
  /**
   * Bumped on every stored change of the default (spec 3.16.4): a walk that
   * began before a bump leaves `pending.layout_walk` set, since the targets
   * it passed before the change got the old default.
   */
  private defaultChanges = 0;
  /** The tail of the library reconciles (spec 3.15: one after the other, never two at once). */
  private reconciling: Promise<void> = Promise.resolve();
  /** The tail of the default-layout changes (spec 3.16.4: serialised, each one's walk before the next). */
  private settingDefault: Promise<unknown> = Promise.resolve();

  constructor(
    private readonly backend: Backend,
    private readonly steam: SteamPort,
    private readonly ui: UiPort,
    private readonly timing: Timing = realTiming,
  ) {}

  get state(): AppState {
    return this.store.get();
  }

  /** The plugin is on (spec 3.19): the `enabled` setting, absent reads as on. */
  get enabled(): boolean {
    return pluginEnabled(this.state.settings);
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
    // Hiding first: right after a sync's restart it is what takes the new
    // tiles out of the library, and the walk can take minutes.
    void this.reconcileLibrary(true).then(() => this.layoutWalk());
  }

  /** Step 3: poll the library every 500 ms (60 s at most), then write owned-apps.json. */
  async loadLibrary(): Promise<void> {
    this.store.set({ library: "loading" });
    try {
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
    } catch (error) {
      // Never leave "loading" behind: the row would spin for good, and the
      // failed row is the one with a way out.
      console.warn("Moonlight Sync: reading the Steam library failed", error);
      this.store.set({ library: "failed" });
    }
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
    // Off: no probe of a host the Deck is away from (spec 3.19).
    if (!active || !this.enabled || this.state.cli?.state !== "ok" || this.state.library !== "ready") return;
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

  /** A user-initiated run (Sync now, Re-fetch all art, Remove everything); refused while the plugin is off. */
  run(kind: RunKind): Promise<Failure | null> {
    if (!this.enabled) {
      this.store.set({ message: errorText(DISABLED_FAILURE) });
      return Promise.resolve(DISABLED_FAILURE);
    }
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
    void this.reconcileLibrary();
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
    // Off (spec 3.19): the row is not shown, and the write it would start is refused.
    if (this.state.inGame || !this.enabled) return;
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

  /** The panel's *Wake* on an unreachable host (spec 3.18): what its toast says, exactly. */
  static wakeToast(result: WakeResult): string {
    return `Wake-on-LAN packet sent to ${result.host}. Give it a minute, then Retry.`;
  }

  /**
   * Send a magic packet to the active host (spec 3.18). A toast either way:
   * the packet proves nothing about the PC, so the row's *Retry* stays the
   * check. Never held back by a run or `inGame`: nothing is written.
   */
  async wakeHost(): Promise<Result<WakeResult> | null> {
    const active = this.state.hosts?.active;
    if (!active) return null;
    const result = await this.backend.wake_host(active);
    this.ui.toast("Moonlight Sync", isFailure(result) ? errorText(result) : Controller.wakeToast(result));
    return result;
  }

  /** The Host page's MAC field (spec 3.18); `null` or empty drops it. */
  async setWakeMac(name: string, mac: string | null): Promise<Result<{ mac: string | null }>> {
    const result = await this.backend.set_wake_mac(name, mac);
    if (!isFailure(result)) await this.refreshHosts();
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
    if (!isFailure(status) && !running) {
      this.store.set((s) => withStatus(s, status.entries));
      void this.reconcileLibrary();
    }
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
   * A press of the panel's *Desktop* / *Steam Big Picture* button. Like the
   * Stream button it is never held back by a running game: Moonlight's own
   * UI handles a stream that is already going.
   */
  openHostApp(key: HostAppKey): boolean {
    const appid = this.state.hostApps[key];
    if (appid === null) return false;
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
   * A press of the Stream button on an owned game's library page: the
   * default layout is put on the hidden shortcut when one is set (spec
   * 3.16.4; never touching a selection the plugin did not make), recorded,
   * then the shortcut is run through Steam. `false` when nothing was
   * launched. Never held back by a running game (the user's decision of
   * 2026-09-22): Moonlight's own UI handles a stream that is already going,
   * and Steam handles the switch. The press never unsets a layout: that is
   * the walk after a clear.
   */
  async streamPress(steamAppid: number): Promise<boolean> {
    const shortcut = this.state.streamMap.get(steamAppid);
    // Off (spec 3.19): the button is not rendered, and a stale press launches nothing.
    if (shortcut === undefined || !this.enabled) return false;
    const def = defaultLayoutOf(this.state.settings);
    if (def) {
      const outcome = await applyDefault(shortcut, def, layoutEntryFor(this.state, shortcut), this.steam.input());
      await this.recordLayout(shortcut, steamAppid, outcome.result, outcome.url);
    }
    const ok = this.steam.runShortcut(shortcut);
    if (!ok) this.ui.toast("Moonlight Sync", "The Stream shortcut is not loaded yet; restart Steam");
    return ok;
  }

  /**
   * *Choose layout* on a Titles row: Steam's own layout picker for the
   * hidden shortcut, recorded as `picker` (under either strategy; under
   * `picker` it is the only layout affordance). `false` when the client has
   * no such method, in which case the pages hide the action. `realAppid`
   * is `null` for a default host app (the panel's layout buttons and its
   * Titles row, spec 3.14.1): there is no game behind it, only the picker.
   */
  async chooseLayout(shortcutAppid: number, realAppid: number | null): Promise<boolean> {
    if (!this.steam.showControllerConfigurator(shortcutAppid)) return false;
    await this.recordLayout(shortcutAppid, realAppid, "picker", null);
    return true;
  }

  /**
   * The panel's layout button beside *Desktop* / *Steam Big Picture* (spec
   * 3.14.1, Decision 39): a hidden entry has no library page, so this is the
   * way to its controller configurator. Like the launch beside it, it is
   * not held back while a game runs (Decision 57).
   */
  chooseHostAppLayout(key: HostAppKey): Promise<boolean> {
    const appid = this.state.hostApps[key];
    return appid === null ? Promise.resolve(false) : this.chooseLayout(appid, null);
  }

  canChooseLayout(): boolean {
    return this.steam.canChooseLayout();
  }

  /**
   * *Use as the default layout* on a Titles row (spec 3.16.5): one read of
   * the title's selection for the controller in use. `title` is the
   * config's own `Title`, else the layout's kind. A layout Steam cannot
   * report (a throwing call) reads as not chosen.
   */
  async inspectLayout(appid: number): Promise<LayoutInspection> {
    const input = this.steam.input();
    const idx = input.controllerIndex();
    if (idx === null) return { ok: false, reason: "no-controller" };
    let config: LayoutConfig | null;
    try {
      config = await input.getConfig(appid, idx);
    } catch {
      config = null;
    }
    if (isUnselected(config)) return { ok: false, reason: "unselected" };
    const url = config!.URL!;
    if (!isShareableUrl(url)) return { ok: false, reason: "not-shareable" };
    const title = config!.Title?.trim() || layoutKindText(url);
    return { ok: true, url, title };
  }

  /**
   * Set (or, with `null`, clear) the default layout (spec 3.16.4, Decisions
   * 45, 51, 52): the backend stores it and raises `pending.layout_walk`,
   * then every non-parked entry is walked (put on the new default, or taken
   * off the old one) and a toast says what happened. Calls are serialised,
   * and each waits for a walk already in progress *before* the backend
   * call, so that walk's `clearWalk` cannot clear the flag this one sets.
   * A walk that begins *during* the call (the load's, once its wait for the
   * shortcut list ends) is waited for too, and this change then walks
   * again: that walk leaves the flag set (`defaultChanges`), since the
   * targets it passed before the store update got the old default. When
   * `status` has not answered the walk is deferred to the next load and the
   * toast says so (Decision 54). Not held back by a running game or a run:
   * it changes no file the CLI writes, and appids do not move until the
   * restart, which re-walks.
   */
  setDefaultLayout(url: string | null, title: string | null): Promise<Failure | null> {
    const next = this.settingDefault.then(() => this.doSetDefaultLayout(url, title));
    this.settingDefault = next.catch(() => undefined);
    return next;
  }

  private async doSetDefaultLayout(url: string | null, title: string | null): Promise<Failure | null> {
    if (!this.enabled) {
      this.ui.toast("Moonlight Sync", errorText(DISABLED_FAILURE));
      return DISABLED_FAILURE;
    }
    if (this.walking) await this.walking;
    const result = await this.backend.set_default_layout(url, title);
    if (isFailure(result)) {
      this.ui.toast("Moonlight Sync", errorText(result));
      return result;
    }
    this.store.set({ settings: result.settings, pending: result.pending });
    this.defaultChanges++;
    // A walk that began while the call was in flight passed its flag check
    // before this change: wait it out (it does not clear the flag, see
    // doWalk), then walk as this change's own.
    if (this.walking) await this.walking;
    const counts = await this.layoutWalk();
    const cleared = url === null;
    const canClear = !!this.steam.input().clearConfig;
    let text: string;
    if (counts === null) text = deferredToast(cleared, canClear);
    else text = cleared ? clearedToast(counts, canClear) : appliedToast(counts);
    this.ui.toast("Moonlight Sync", text);
    return null;
  }

  private async recordLayout(
    shortcutAppid: number,
    realAppid: number | null,
    result: LayoutResult,
    url: string | null,
  ): Promise<void> {
    const recorded = await this.backend.record_layout(shortcutAppid, realAppid, result, url);
    if (!isFailure(recorded)) this.store.set({ layouts: recorded.entries });
  }

  /**
   * The layout walk (spec 3.10, 3.16.4): when `pending.layout_walk` says a
   * sync's restart just happened, or the default was set or cleared, put
   * the default layout on every non-parked entry (`walkTargets`) once the
   * shortcut list is loaded -- or, with no default, take the plugin's
   * layout off each entry that still has it -- then clear the flag. Under
   * the `picker` strategy the flag is cleared at once. Never runs twice at
   * the same time: a call while one is going returns that walk's promise.
   * Resolves `null` when the walk had to be deferred: `status` has not
   * answered, so the flag is left for the next load.
   */
  layoutWalk(): Promise<WalkCounts | null> {
    if (!this.walking) {
      this.walking = this.doWalk().finally(() => {
        this.walking = null;
      });
    }
    return this.walking;
  }

  private async doWalk(): Promise<WalkCounts | null> {
    if (!this.state.pending?.layout_walk) return NO_WALK;
    // Off (spec 3.19): no Steam Input call; the flag stays and the walk
    // runs when the plugin is turned on again.
    if (!this.enabled) return null;
    if (layoutStrategy(this.state.settings) !== "copy") {
      await this.clearWalk();
      return NO_WALK;
    }
    if (this.state.entries === null) {
      // `status` has not answered (it failed, or has not run yet), so there
      // are no targets for want of data rather than because there is
      // nothing to walk. Leave pending.layout_walk set and do nothing: the
      // next load, or the panel's Retry, walks once status is in.
      return null;
    }
    const changes = this.defaultChanges;
    const counts: WalkCounts = { ...NO_WALK };
    this.store.set({ walking: true });
    try {
      const targets = walkTargets(this.state.entries);
      // Readiness: every target resolves to an overview, polled every 2 s
      // for at most 90 s (normally immediate).
      const deadline = this.timing.now() + WALK_TIMEOUT_MS;
      const unresolved = () => targets.filter((target) => !this.steam.overviewLoaded(target.shortcutAppid));
      while (unresolved().length && this.timing.now() < deadline) await this.timing.sleep(WALK_POLL_MS);
      const input = this.steam.input();
      for (const { realAppid, shortcutAppid } of targets) {
        // Per target: a clear that lands mid-walk turns the rest of it into
        // the unset pass (and its own walk follows, serialised).
        const def = defaultLayoutOf(this.state.settings);
        const entry = layoutEntryFor(this.state, shortcutAppid);
        if (!this.steam.overviewLoaded(shortcutAppid)) {
          // Only recorded for an entry the walk would have touched.
          if (def || entry?.applied) {
            console.warn(`Moonlight Sync: shortcut ${shortcutAppid} never loaded; layout not set`);
            await this.recordLayout(shortcutAppid, realAppid, "unavailable", def ? null : (entry?.applied ?? null));
            counts.unavailable++;
          }
        } else if (def) {
          const outcome = await applyDefault(shortcutAppid, def, entry, input);
          await this.recordLayout(shortcutAppid, realAppid, outcome.result, outcome.url);
          counts[outcome.result === "default" ? "applied" : outcome.result]++;
        } else {
          const outcome = await unsetApplied(shortcutAppid, entry, input);
          if (outcome) {
            await this.recordLayout(shortcutAppid, realAppid, outcome.result, outcome.url);
            if (outcome.cleared) counts.unset++;
            else if (outcome.result === "unavailable") counts.unavailable++;
            else counts.kept++;
          }
        }
        await this.timing.sleep(WALK_STEP_MS);
      }
      // The default changed under this walk (setDefaultLayout stored it
      // after the walk began): the targets passed before then got the old
      // one, so the flag stays for the walk that change runs next.
      if (changes === this.defaultChanges) await this.clearWalk();
    } finally {
      this.store.set({ walking: false });
    }
    return counts;
  }

  private async clearWalk(): Promise<void> {
    const result = await this.backend.clear_pending("layout_walk");
    if (!isFailure(result)) this.store.set({ pending: result });
    else if (this.state.pending) this.store.set({ pending: { ...this.state.pending, layout_walk: false } });
  }

  // -------------------------------------------------------------------------
  // hidden state and the Streaming collection (spec 3.15)

  canHideShortcuts(): boolean {
    return this.steam.library().canHide();
  }

  canKeepCollection(): boolean {
    return this.steam.library().canCollect();
  }

  /**
   * Bring the client in line with the last `status`: the CLI's hidden entries
   * hidden (the client ignores `IsHidden` in `shortcuts.vdf`), the visible
   * ones shown, and the *Streaming* collection holding every streamable
   * title. Only differences are applied, so a second call changes nothing.
   * Does nothing without a `status` or while a run is going (checked after
   * the wait, too). `wait` (the
   * load after a restart) first gives the shortcut list 90 s to load; an
   * entry the client still does not know is skipped until the next call.
   */
  reconcileLibrary(wait = false): Promise<void> {
    this.reconciling = this.reconciling.then(() =>
      this.doReconcile(wait).catch((error) => {
        console.warn("Moonlight Sync: updating the library failed", error);
      }),
    );
    return this.reconciling;
  }

  private async doReconcile(wait: boolean): Promise<void> {
    const library = this.steam.library();
    const loaded = (appid: number) => this.steam.overviewLoaded(appid);
    if (wait) {
      const deadline = this.timing.now() + WALK_TIMEOUT_MS;
      const waiting = () => !!this.state.entries?.some((entry) => !loaded(entry.appid));
      while (waiting() && this.timing.now() < deadline) await this.timing.sleep(WALK_POLL_MS);
    }
    // Read after the wait: a run started meanwhile owns the library now, and
    // a `status` that came in meanwhile is the newer plan.
    const entries = this.state.entries;
    if (entries === null || this.state.run?.running) return;
    const settings = this.state.settings;
    const enabled = pluginEnabled(settings);
    if (library.canHide()) {
      // Off (spec 3.19): every entry hidden, whatever status and the setting say.
      const plan = hiddenPlan(entries, hideStreamEnabled(settings), enabled);
      try {
        library.setHidden(plan.hide.filter((id) => loaded(id) && library.isHidden(id) !== true), true);
        library.setHidden(plan.show.filter((id) => loaded(id) && library.isHidden(id) !== false), false);
      } catch (error) {
        // the collection does not depend on it
        console.warn("Moonlight Sync: hiding shortcuts failed", error);
      }
    }
    // Off: the collection is left alone here; turning the setting (or the
    // plugin, spec 3.19) off is what retires it (setSettings / setEnabled),
    // so a collection the user made under the same name afterwards is never
    // touched.
    if (!enabled || !library.canCollect() || !streamingCollectionEnabled(settings)) return;
    // The shortcut collection (spec 3.17): this device's shortcuts while
    // Stream shortcuts are shown, nothing wanted while the tab is alone --
    // and only the real games (v0.4.0's) removable then, so a device on the
    // tab never fights one keeping the collection over shared shortcuts.
    const hideStream = hideStreamEnabled(settings);
    await this.settleCollection(collectionMembers(entries, hideStream), removableAppids(entries, hideStream));
  }

  /**
   * Bring the *Streaming* collection to `wanted`, removing only members in
   * `removable` (spec 3.17: another device's, and the user's, stay), and
   * delete it once nothing is left in it -- never on a pass that added
   * something, since whether the client lists a just-added member at once
   * is unmeasured (a next pass deletes an empty one). A collection somebody
   * already had under the name keeps its members, so it stays.
   */
  private async settleCollection(wanted: readonly number[], removable: ReadonlySet<number>): Promise<void> {
    const library = this.steam.library();
    const current = library.collectionApps(STREAMING_COLLECTION);
    if (current === null && !wanted.length) return;
    const diff = collectionDiff(wanted, current ?? [], removable);
    const add = diff.add.filter((id) => this.steam.overviewLoaded(id));
    if (add.length || diff.remove.length) await library.updateCollection(STREAMING_COLLECTION, add, diff.remove);
    if (add.length) return;
    const left = library.collectionApps(STREAMING_COLLECTION);
    if (left !== null && !left.length) await library.deleteCollection(STREAMING_COLLECTION);
  }

  /** A settings-page change; refused while the plugin is off (spec 3.19: `setEnabled` is the one live switch). */
  async setSettings(patch: SettingsPatch): Promise<Result> {
    if (!this.enabled) return DISABLED_FAILURE;
    const result = await this.backend.set_settings(patch);
    if (isFailure(result)) return result;
    this.store.set({ settings: result.settings });
    if ("hide_stream_shortcuts" in patch || "streaming_collection" in patch) {
      if (patch.streaming_collection === false) await this.retireCollection();
      void this.reconcileLibrary();
    }
    return result;
  }

  /**
   * The plugin's on/off toggle (spec 3.19). Off: this device's members
   * leave the fallback collection, then every entry is hidden (the
   * reconcile, which reads the new setting). On: the reconcile restores
   * what `status` and the settings say, the deferred layout walk runs and
   * the host is checked again. Refused while a run is going (the toggle is
   * disabled then too): the run owns the library until it is done.
   */
  async setEnabled(on: boolean): Promise<Result> {
    if (this.state.run?.running) {
      return { ok: false, error: "busy", message: "a run is going", kind: this.state.run.kind };
    }
    const result = await this.backend.set_settings({ enabled: on });
    if (isFailure(result)) {
      this.ui.toast("Moonlight Sync", errorText(result));
      return result;
    }
    this.store.set({ settings: result.settings, message: null });
    if (on) {
      await this.reconcileLibrary();
      void this.layoutWalk();
      void this.checkHost(false);
    } else {
      await this.retireCollection();
      await this.reconcileLibrary();
    }
    return result;
  }

  /**
   * The *Streaming* group turned off: this device's members leave the
   * fallback collection and it is deleted once empty (serialised with the
   * reconcile). Without a `status` nothing is known, so nothing moves.
   */
  private retireCollection(): Promise<void> {
    this.reconciling = this.reconciling.then(async () => {
      const entries = this.state.entries;
      if (!entries || !this.steam.library().canCollect()) return;
      await this.settleCollection([], knownAppids(entries)).catch((error) =>
        console.warn("Moonlight Sync: retiring the Streaming collection failed", error),
      );
    });
    return this.reconciling;
  }

  setInGame(inGame: boolean): void {
    if (this.state.inGame !== inGame) this.store.set({ inGame });
  }

  /** The library row's *Retry* (step 3 again). */
  async retryLibrary(): Promise<void> {
    await this.loadLibrary();
    if (this.state.library === "ready") {
      await Promise.all([this.refreshStatus(), this.checkHost(false)]);
      void this.reconcileLibrary();
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
