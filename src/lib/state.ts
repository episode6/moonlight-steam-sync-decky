/**
 * The frontend's one store (spec 3.6): CLI state, settings, hosts, the
 * pending flags, the last `status` snapshot and what it derives (counters,
 * the stream map), host reachability, the progress of the current run, the
 * layout results of `layouts.json` (spec 3.10), and the SteamGridDB key's
 * state and the key fetch in flight (spec 3.20.4).
 *
 * Pure: reducers are plain functions over plain data and `Store` is a tiny
 * subscribe/notify container, so everything here is unit-tested with vitest.
 * The React hook that reads it lives in `src/components/useStore.ts`.
 */

import type {
  CliEvent,
  CliVersion,
  CommitEvent,
  EntryEvent,
  HostCheck,
  HostsInfo,
  KeyFetchState,
  KeyState,
  LayoutEntry,
  Pending,
  PlanEvent,
  RunKind,
  Settings,
  SummaryEvent,
  SyncDonePayload,
  SyncState,
  TitleEvent,
  WakeInfo,
} from "./cli";
import { cliStatus, type CliStatus } from "./version";

// ---------------------------------------------------------------------------
// derived data

export interface Counters {
  /** Hidden, non-client, non-parked entries: a Stream button each. */
  stream: number;
  /** Visible entries. */
  shortcuts: number;
  /** Non-client, non-parked entries whose match is `none` (or missing). */
  unmatched: number;
  /** Parked entries (the other hosts' titles, hidden in place). */
  parked: number;
}

/** The four counters of the panel (spec 3.8), from `status` entries. */
export function countersFromStatus(entries: readonly EntryEvent[]): Counters {
  const counters: Counters = { stream: 0, shortcuts: 0, unmatched: 0, parked: 0 };
  for (const entry of entries) {
    if (entry.client) continue;
    if (entry.parked) {
      counters.parked++;
      continue;
    }
    // A default host app (spec 3.14) is none of the three: hidden, it is no
    // Stream button; its panel button is what stands for it.
    if (entry.host_app) continue;
    if (entry.hidden) counters.stream++;
    else counters.shortcuts++;
    if (!entry.match || entry.match.how === "none") counters.unmatched++;
  }
  return counters;
}

/**
 * `Map<steamAppid, shortcutAppid>` from `status` (spec 3.9): hidden, not
 * parked, published, not the client, with a Steam match. PR-7 puts a Stream
 * button on each key's library page. A default host app is never in it
 * (spec 3.14): a hidden `Desktop` whose match happens to be a Steam game
 * would put a Stream button on that game's page, and the layout walk
 * iterates this map.
 */
export function streamMapFromStatus(entries: readonly EntryEvent[]): Map<number, number> {
  const map = new Map<number, number>();
  for (const entry of entries) {
    const steam = entry.match?.steam_appid;
    if (entry.host_app) continue;
    if (entry.hidden && !entry.parked && entry.published && !entry.client && typeof steam === "number") {
      map.set(steam, entry.appid);
    }
  }
  return map;
}

/** The client entry's appid for *Open Moonlight* (spec 3.4.5), or `null`. */
export function clientAppid(entries: readonly EntryEvent[]): number | null {
  const client = entries.find((entry) => entry.client);
  return client ? client.appid : null;
}

/**
 * The two entries every Sunshine / Apollo host publishes out of the box, in
 * the order the panel shows them. They get a launch button each on the panel.
 */
export const HOST_APPS = [
  { key: "desktop", name: "Desktop", description: "Stream the host's desktop" },
  { key: "bigPicture", name: "Steam Big Picture", description: "Stream the host's Steam in Big Picture" },
] as const;

export type HostAppKey = (typeof HOST_APPS)[number]["key"];

/**
 * The shortcut appid per default host app, or `null` when the active host
 * does not publish it (or it is ignored, so it has no entry). Matched on the
 * Moonlight name, never `app_name`, and regardless of `hidden`, so the
 * buttons keep working whichever way the CLI writes these two.
 */
export function hostAppsFromStatus(entries: readonly EntryEvent[]): Record<HostAppKey, number | null> {
  const apps: Record<HostAppKey, number | null> = { desktop: null, bigPicture: null };
  for (const app of HOST_APPS) {
    const wanted = app.name.toLowerCase();
    const entry = entries.find(
      (e) => !e.client && !e.parked && e.published && e.name.trim().toLowerCase() === wanted,
    );
    if (entry) apps[app.key] = entry.appid;
  }
  return apps;
}

/**
 * A host's Wake-on-LAN info (spec 3.18), by name in any case: `hosts()` keys
 * `wake` by the known host's stored spelling while the active host's name
 * comes from the CLI's state file.
 */
export function wakeInfoOf(hosts: HostsInfo | null, name: string | null): WakeInfo | null {
  if (!hosts?.wake || !name) return null;
  const wanted = name.toLowerCase();
  for (const [host, info] of Object.entries(hosts.wake)) {
    if (host.toLowerCase() === wanted) return info;
  }
  return null;
}

/**
 * The host row's subtitle (spec 3.8): the other known hosts and how many
 * titles each has parked.
 *
 * `status` carries one parked total, which can only be attributed to a single
 * other host ("active host · OFFICE-PC parked (198 titles kept)"). With two or
 * more the total says nothing about any one of them, so the line names each
 * host with the size of its last listing instead ("active host · parked from
 * OFFICE-PC (312 titles), LIVING-ROOM-PC (40 titles)") and drops the count for
 * a host that has never been listed.
 */
export function otherHostsLine(hosts: HostsInfo | null, parked: number): string {
  if (!hosts?.active) return "";
  const others = hosts.known.filter((name) => name.toLowerCase() !== hosts.active!.toLowerCase());
  if (!others.length) return "active host";
  if (others.length === 1) {
    const titles = `${parked} ${parked === 1 ? "title" : "titles"} kept`;
    return `active host · ${others[0]} parked (${titles})`;
  }
  const cached = new Map(hosts.cached_hosts.map((host) => [host.name.toLowerCase(), host.count]));
  const parts = others.map((name) => {
    const count = cached.get(name.toLowerCase());
    return count === undefined ? name : `${name} (${count} ${count === 1 ? "title" : "titles"})`;
  });
  return `active host · parked from ${parts.join(", ")}`;
}

// ---------------------------------------------------------------------------
// the SteamGridDB key from the Game Mode browser (spec 3.20.4)

/** A key fetch in flight: where the backend's state machine is. */
export interface KeyFetch {
  state: KeyFetchState;
}

/**
 * Is *Get key from SteamGridDB…* offered for this key state? Only with no
 * key or the plugin's own key file (`none`, `file`): under `config` or
 * `env` the file it writes would be ignored (spec 3.20.4), and a
 * `config.toml` that does not parse is fixed in Desktop Mode first.
 */
export function keyFetchOffered(key: KeyState | null): boolean {
  if (!key || key.config_parse_error) return false;
  return key.source === "none" || key.source === "file";
}

/** The key field's description while a fetch is in flight (spec 3.20.4 step 3). */
export function keyFetchText(fetch: KeyFetch): string {
  switch (fetch.state) {
    case "waiting":
      return "Waiting for SteamGridDB…";
    case "login":
    case "steam-sign-in":
      return "Signing in with Steam…";
    case "steam-login":
      return "Steam is asking you to log in on the page";
    case "reading":
    case "done":
    default:
      return "Reading your key…";
  }
}

// ---------------------------------------------------------------------------
// run progress

export const RECENT_TITLES = 5;
const MAX_EVENTS = 400;

export interface RunProgress {
  kind: RunKind;
  running: boolean;
  /** The CLI is waiting for the client to exit right now. */
  awaiting: boolean;
  /** This run emitted `awaiting-steam-exit` at some point. */
  sawAwaiting: boolean;
  /** Restart immediately on `awaiting-steam-exit`, no modal (the persistent row). */
  immediate: boolean;
  plan: PlanEvent | null;
  /** The last few `title` events, oldest first. */
  titles: TitleEvent[];
  progress: { index: number; total: number } | null;
  summary: SummaryEvent | null;
  commit: CommitEvent | null;
  exit: number | null;
  failure: SyncDonePayload["failure"];
  /** Events so far (capped), for `restartDecision`. */
  events: CliEvent[];
}

export function newRun(kind: RunKind, immediate = false): RunProgress {
  return {
    kind,
    running: true,
    awaiting: false,
    sawAwaiting: false,
    immediate,
    plan: null,
    titles: [],
    progress: null,
    summary: null,
    commit: null,
    exit: null,
    failure: null,
    events: [],
  };
}

/** Fold one relayed CLI event into the run's progress. */
export function applyRunEvent(run: RunProgress, event: CliEvent): RunProgress {
  const next: RunProgress = { ...run, events: [...run.events, event].slice(-MAX_EVENTS) };
  if (run.plan && !next.events.includes(run.plan)) next.events.unshift(run.plan);
  switch (event.event) {
    case "plan":
      next.plan = event;
      break;
    case "title":
      next.titles = [...run.titles, event].slice(-RECENT_TITLES);
      next.progress = { index: event.index, total: event.total };
      break;
    case "awaiting-steam-exit":
      next.awaiting = true;
      next.sawAwaiting = true;
      break;
    case "commit":
      next.commit = event;
      next.awaiting = false;
      break;
    case "summary":
      next.summary = event;
      break;
    default:
      break;
  }
  return next;
}

/** The run ended (`sync_done`). */
export function applyRunDone(run: RunProgress, done: SyncDonePayload): RunProgress {
  return {
    ...run,
    kind: done.kind,
    running: false,
    awaiting: false,
    exit: done.exit,
    summary: done.summary ?? run.summary,
    commit: done.commit ?? run.commit,
    failure: done.failure,
  };
}

/** Rebuild progress from `sync_state()` after a reload mid-run (spec 3.8 step 2). */
export function runFromSyncState(state: SyncState): RunProgress | null {
  const kind = state.kind ?? state.last_kind;
  if (!kind || (!state.running && !state.events.length)) return null;
  let run = newRun(kind, !!state.opts?.immediate_restart);
  for (const event of state.events) run = applyRunEvent(run, event);
  run.awaiting = state.awaiting_exit;
  run.running = state.running;
  if (!state.running) run.exit = state.last_exit;
  return run;
}

/** 0..1 over `title.index / total`; `null` before the first title. */
export function progressFraction(run: RunProgress): number | null {
  if (!run.progress || run.progress.total <= 0) return null;
  return Math.min(1, Math.max(0, run.progress.index / run.progress.total));
}

// ---------------------------------------------------------------------------
// the store

export type LibraryState = "waiting" | "loading" | "ready" | "failed";

export interface AppState {
  loaded: boolean;
  cliVersion: CliVersion | null;
  cli: CliStatus | null;
  /** Why `cli_version()` itself failed (then `cli` stays null and Retry shows). */
  cliError: string | null;
  settings: Settings | null;
  hosts: HostsInfo | null;
  pending: Pending | null;
  library: LibraryState;
  entries: EntryEvent[] | null;
  counters: Counters | null;
  streamMap: Map<number, number>;
  clientAppid: number | null;
  /** The *Desktop* / *Steam Big Picture* shortcuts, when the host publishes them. */
  hostApps: Record<HostAppKey, number | null>;
  reach: HostCheck | null;
  reachLoading: boolean;
  /** Ignored names, for the counter when `check_host` did not count them. */
  ignoredCount: number | null;
  /**
   * Bumped when what `list` / `status` would say changed behind the Titles
   * page's back (a match-cache reset), so an already-mounted page re-lists.
   */
  titlesEpoch: number;
  run: RunProgress | null;
  /** A one-line outcome under the panel's buttons ("Stopped; sync again to resume"). */
  message: string | null;
  inGame: boolean;
  /** `layouts.json`: the last layout result per hidden shortcut, keyed by its appid (spec 3.10). */
  layouts: Record<string, LayoutEntry>;
  /** The post-restart layout walk is running. */
  walking: boolean;
  /** `sgdb_key_state()`: where the key comes from and its last four characters, never the key. */
  sgdbKey: KeyState | null;
  /** The key fetch from the Game Mode browser in flight (spec 3.20.4), or `null`. */
  keyFetch: KeyFetch | null;
}

export function initialState(): AppState {
  return {
    loaded: false,
    cliVersion: null,
    cli: null,
    cliError: null,
    settings: null,
    hosts: null,
    pending: null,
    library: "waiting",
    entries: null,
    counters: null,
    streamMap: new Map(),
    clientAppid: null,
    hostApps: { desktop: null, bigPicture: null },
    reach: null,
    reachLoading: false,
    ignoredCount: null,
    titlesEpoch: 0,
    run: null,
    message: null,
    inGame: false,
    layouts: {},
    walking: false,
    sgdbKey: null,
    keyFetch: null,
  };
}

export function withCliVersion(state: AppState, info: CliVersion): AppState {
  return { ...state, cliVersion: info, cli: cliStatus(info), cliError: null };
}

/** The layout record for a hidden shortcut, or `null` (spec 3.10). */
export function layoutEntryFor(state: Pick<AppState, "layouts">, shortcutAppid: number): LayoutEntry | null {
  return state.layouts[String(shortcutAppid)] ?? null;
}

export function withStatus(state: AppState, entries: EntryEvent[]): AppState {
  return {
    ...state,
    entries,
    counters: countersFromStatus(entries),
    streamMap: streamMapFromStatus(entries),
    clientAppid: clientAppid(entries),
    hostApps: hostAppsFromStatus(entries),
  };
}

/** The ignored counter: `check_host`'s count when it listed, else `ignore.json`'s size. */
export function ignoredCounter(state: AppState): number | null {
  if (state.reach?.reachable && typeof state.reach.ignored === "number") return state.reach.ignored;
  return state.ignoredCount;
}

/** Is the CLI usable (installed and new enough)? */
export function cliReady(state: AppState): boolean {
  return state.cli?.state === "ok";
}

/** Can CLI-backed rows be pressed (CLI ready and the owned-apps file written)? */
/** What the persistent *Restart Steam to apply* row renders, or `null`
 * when there is nothing to restart for (spec 3.9, Decision 29).
 *
 * Both of the row's paths end in a Steam restart -- "write" starts an
 * immediate run that shuts the client down the moment the CLI waits for it,
 * "art" shuts it down itself -- so both are disabled while a game is
 * running. `Controller.restartRow()` refuses in the same case.
 */
export function restartRowView(state: AppState): { description: string; disabled: boolean } | null {
  const pending = state.pending;
  if (!pending || pending.restart_needed === "none") return null;
  if (state.run?.running) return { description: "finishing the previous run\u2026", disabled: true };
  if (state.inGame) return { description: "A game is running; exit it first", disabled: true };
  if (pending.restart_needed === "art") {
    return { description: "New artwork shows after a Steam restart", disabled: false };
  }
  return {
    description: "The last sync is ready to write; Steam restarts once",
    disabled: !actionsReady(state),
  };
}

export function actionsReady(state: AppState): boolean {
  return cliReady(state) && state.library === "ready";
}

export type Listener = () => void;

export class Store<S> {
  private state: S;
  private readonly listeners = new Set<Listener>();

  constructor(initial: S) {
    this.state = initial;
  }

  get(): S {
    return this.state;
  }

  set(update: Partial<S> | ((state: S) => S)): void {
    this.state =
      typeof update === "function"
        ? (update as (state: S) => S)(this.state)
        : { ...this.state, ...update };
    for (const listener of [...this.listeners]) listener();
  }

  subscribe(listener: Listener): () => void {
    this.listeners.add(listener);
    return () => {
      this.listeners.delete(listener);
    };
  }
}
