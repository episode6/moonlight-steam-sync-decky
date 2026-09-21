/**
 * The backend's callables and the CLI's `--json` events, typed.
 *
 * Every event of spec 3.4.6 has a type here; `Result<T>` is the backend's
 * `{ok: true, ...} | Failure` convention (spec 3.7). This module is pure:
 * `makeBackend` takes `@decky/api`'s `callable` as an argument (index.tsx
 * passes it in), so vitest can load everything under `src/lib/`.
 */

// ---------------------------------------------------------------------------
// events (spec 3.4.6)

export interface Match {
  steam_appid: number | null;
  sgdb_id: number | null;
  matched_name: string | null;
  how: string;
}

export type SlotName = "portrait" | "landscape" | "hero" | "logo" | "icon";
export type TitleSlotValue = "steam" | "sgdb" | "kept" | "missing" | "skipped" | "cached-miss";
/**
 * `host-app` (spec 3.14): the host's default `Desktop` / `Steam Big Picture`,
 * written hidden. `sync` and `list` only say it under `--hide-host-apps`,
 * which the backend always passes; `art` says it for a hidden default host
 * app whatever the flags.
 */
export type TitleKind = "stream" | "shortcut" | "host-app";
export type AppKind = "stream" | "shortcut" | "host-app" | "ignored" | "parked" | "duplicate";
export type RunKind = "sync" | "art" | "remove";

export interface StartEvent {
  event: "start";
  schema: number;
  version: string;
  command: string;
}

export interface PlanEvent {
  event: "plan";
  host: string;
  published: number;
  ignored: number;
  present: number;
  to_add: number;
  to_replace: number;
  to_park: number;
  to_unpark: number;
  to_remove: number;
  pending: number;
  limit: number | null;
  stream: number;
  shortcut: number;
  /** Published `host-app` titles this run; only under `--hide-host-apps`. */
  host_app?: number;
  parked: number;
  duplicates: Record<string, string>;
}

export interface ReplaceEvent {
  event: "replace";
  name: string;
  old_appid: number;
  new_appid: number;
  reason: "kind-changed" | "name-changed" | "rematched";
}

export interface TitleEvent {
  event: "title";
  index: number;
  total: number;
  name: string;
  kind: TitleKind;
  appid: number;
  match: Match | null;
  slots: Partial<Record<SlotName, TitleSlotValue>>;
}

export interface AwaitingSteamExitEvent {
  event: "awaiting-steam-exit";
  timeout_s: number;
}

export interface CommitEvent {
  event: "commit";
  written: boolean;
  restarted: boolean;
  backup: string;
  relaunch_error: string;
}

export interface SummaryEvent {
  event: "summary";
  added: number;
  replaced: number;
  removed: number;
  filled: number;
  missing: number;
  unmatched: string[];
  duplicates: Record<string, string>;
  pending: number;
  stopped_early: boolean;
  stop_reason: string | null;
  exit: number;
  /**
   * On every `sync` summary from CLI 0.3.0 on (zeros included), never on an
   * `art` or `remove` one -- spec 3.4.6, spec 3.13 A3. Still optional here so
   * an older CLI's summary parses; the finish line only uses it when present.
   */
  added_by_kind?: { stream: number; shortcut: number; "host-app"?: number };
}

export interface SameGameAs {
  name: string;
  host: string;
}

export interface AppEvent {
  event: "app";
  name: string;
  label: "added" | "ignored" | "new" | "parked";
  kind: AppKind;
  match: Match | null;
  fuzzy: boolean;
  duplicate_of: string | null;
  same_game_as: SameGameAs[];
  cached: boolean;
  cached_when: string | null;
}

/** `list`: count + host; `status` / `ignore` / `doctor`: count; `search`: nothing. */
export interface EndEvent {
  event: "end";
  count?: number;
  host?: string;
}

export type EntrySlots = Record<SlotName, string | null>;

export interface EntryEvent {
  event: "entry";
  name: string;
  app_name: string;
  appid: number;
  hidden: boolean;
  parked: boolean;
  published: boolean;
  client: boolean;
  /**
   * The entry's Moonlight name is a default host app, whatever `hidden`
   * says (spec 3.14); only under `status --hide-host-apps`.
   */
  host_app?: boolean;
  match: Match | null;
  slots: EntrySlots;
  stale_art: boolean;
  cached: boolean;
  cached_when: string | null;
}

export interface CachedHost {
  name: string;
  when: string;
  count: number;
}

export interface HostEvent {
  event: "host";
  name: string;
  source: "state" | "config" | "flag";
  cached_hosts: CachedHost[];
}

export interface CandidateEvent {
  event: "candidate";
  source: "steam" | "sgdb";
  id: number;
  name: string;
  verified: boolean;
  owned: boolean;
  steam_appid: number | null;
}

export interface PinnedEvent {
  event: "pinned";
  name: string;
  steam_appid: number | null;
  sgdb_id: number | null;
  override_line: string | null;
}

export interface NoteEvent {
  event: "note";
  message: string;
}

export interface ErrorEvent {
  event: "error";
  exit: number;
  message: string;
}

export type CliEvent =
  | StartEvent
  | PlanEvent
  | ReplaceEvent
  | TitleEvent
  | AwaitingSteamExitEvent
  | CommitEvent
  | SummaryEvent
  | AppEvent
  | EndEvent
  | EntryEvent
  | HostEvent
  | CandidateEvent
  | PinnedEvent
  | NoteEvent
  | ErrorEvent;

export type EventName = CliEvent["event"];

export const EVENT_NAMES: readonly EventName[] = [
  "start",
  "plan",
  "replace",
  "title",
  "awaiting-steam-exit",
  "commit",
  "summary",
  "app",
  "end",
  "entry",
  "host",
  "candidate",
  "pinned",
  "note",
  "error",
];

// ---------------------------------------------------------------------------
// results (spec 3.7)

export type ErrorCode =
  | "cli-missing"
  | "cli-too-old"
  | "cli-protocol"
  | "cli-error"
  | "timeout"
  | "busy"
  | "owned-apps-missing"
  | "owned-apps-empty"
  | "bad-request"
  | "io";

export interface Failure {
  ok: false;
  error: ErrorCode;
  message: string;
  exit?: number;
  events?: CliEvent[];
  installed?: string;
  minimum?: string;
  stderr?: string;
  /** Which side of the busy guard answered: a run kind, or `"match"`. */
  kind?: RunKind | "match";
  timeout_s?: number;
}

export type Result<T extends object = object> = ({ ok: true } & T) | Failure;

export type LayoutStrategy = "copy" | "picker";

/** `settings.default_layout` (spec 3.16.2): the plugin's adopted layout, or unset. */
export interface DefaultLayout {
  url: string;
  title: string;
  when: string;
}

export interface Settings {
  version: number;
  hosts: string[];
  /** @deprecated spec 3.16 / Decision 47: replaced by `default_layout`; read by nothing. */
  copy_layouts: boolean;
  restart_countdown_s: number;
  retry_missing: boolean;
  layout_strategy?: LayoutStrategy;
  /** Hide Stream-button shortcuts in the client (spec 3.15); absent reads as on. */
  hide_stream_shortcuts?: boolean;
  /** Keep the *Streaming* collection (spec 3.15); absent reads as on. */
  streaming_collection?: boolean;
  /** The plugin's adopted controller layout (spec 3.16.2); `null` when unset. */
  default_layout: DefaultLayout | null;
}

export type SettingsPatch = Partial<
  Pick<
    Settings,
    | "copy_layouts"
    | "restart_countdown_s"
    | "retry_missing"
    | "layout_strategy"
    | "hide_stream_shortcuts"
    | "streaming_collection"
  >
>;

export interface CliVersion {
  installed: string | null;
  bundled: string | null;
  minimum: string;
  too_old: boolean;
  installed_path: string;
  bundled_path: string;
  pinned: string | null;
  plugin_version: string | null;
  log_path: string;
  install_error: string | null;
  capabilities: { art_commit: boolean };
}

export interface HostsInfo {
  active: string | null;
  source: "state" | "config" | "flag" | null;
  cached_hosts: CachedHost[];
  known: string[];
}

export interface HostReachable {
  host: string;
  reachable: true;
  count: number;
  /** Additive: `app` events of kind `ignored` in that listing. */
  ignored?: number;
  checked_at: string;
}

export interface HostUnreachable {
  host: string;
  reachable: false;
  message: string;
  exit: number;
  last_seen: string | null;
  cached_count: number | null;
  checked_at: string;
}

export type HostCheck = HostReachable | HostUnreachable;

export type RestartNeeded = "none" | "art" | "write";

export interface Pending {
  restart_needed: RestartNeeded;
  layout_walk: boolean;
  since: string | null;
  last_summary: SummaryEvent | null;
  last_plan: PlanEvent | null;
  last_kind: RunKind | null;
}

export interface RunOpts {
  retry_missing?: boolean;
  immediate_restart?: boolean;
}

export interface SyncState {
  running: boolean;
  kind: RunKind | null;
  started: string | null;
  opts: RunOpts;
  awaiting_exit: boolean;
  last_exit: number | null;
  last_kind: RunKind | null;
  events: CliEvent[];
}

export interface KeyState {
  source: "config" | "env" | "file" | "none";
  hint: string | null;
  config_parse_error: boolean;
}

/**
 * What one layout action recorded for a hidden shortcut (spec 3.10 / 3.16).
 * `"default"`: the entry is on the plugin's default layout. `"copied"` is
 * no longer written by anything but stays valid so an older file and an
 * older frontend still round-trip.
 */
export type LayoutResult = "copied" | "kept" | "unavailable" | "picker" | "default";

export interface LayoutEntry {
  /** `null` for any result now (spec 3.16.2): the walk covers entries with no Steam game. */
  real_appid: number | null;
  result: LayoutResult;
  url: string | null;
  when: string;
  /**
   * The last URL *the plugin itself* set on this shortcut, or `null`
   * (spec 3.16.2): computed by the backend, so `layouts.ts`'s `appliedUrl`
   * only needs to fall back for a record written before this field existed.
   */
  applied?: string | null;
}

/** `layouts.json`: `entries` keyed by the shortcut appid as a string. */
export interface LayoutsInfo {
  version: number;
  entries: Record<string, LayoutEntry>;
}

export interface ListResult {
  apps: AppEvent[];
  host: string | null;
  count: number;
  notes: string[];
}

/** `sync_event` payload. */
export interface SyncEventPayload {
  kind: RunKind;
  event: CliEvent;
}

/** `sync_done` payload. */
export interface SyncDonePayload {
  kind: RunKind;
  exit: number;
  pending: Pending;
  summary: SummaryEvent | null;
  commit: CommitEvent | null;
  failure: { error: ErrorCode; message: string; exit?: number } | null;
}

export interface Backend {
  cli_version(): Promise<Result<CliVersion>>;
  cli_capabilities(): Promise<Result<{ art_commit: boolean }>>;
  doctor(): Promise<Result<{ lines: Record<string, string>; raw: string }>>;
  log_tail(n: number): Promise<Result<{ lines: string[] }>>;
  status(): Promise<Result<{ entries: EntryEvent[]; notes: string[] }>>;
  list_apps(): Promise<Result<ListResult>>;
  list_cached(host: string): Promise<Result<ListResult>>;
  check_host(name: string, force: boolean): Promise<Result<HostCheck>>;
  hosts(): Promise<Result<HostsInfo>>;
  set_host(name: string): Promise<Result<{ active: string | null }>>;
  add_host(name: string): Promise<Result<{ count: number; made_active: boolean }>>;
  forget_host(name: string): Promise<Result<{ known: string[] }>>;
  get_settings(): Promise<Result<{ settings: Settings }>>;
  set_settings(patch: SettingsPatch): Promise<Result<{ settings: Settings }>>;
  /** Store (`url` starting with a `DEFAULT_LAYOUT_SCHEMES` prefix) or clear (`null`) the default layout (spec 3.16.2). */
  set_default_layout(
    url: string | null,
    title: string | null,
  ): Promise<Result<{ settings: Settings; pending: Pending }>>;
  get_ignored(): Promise<Result<{ ignored: string[] }>>;
  write_owned_apps(steamid3: number, apps: Record<string, string>): Promise<Result<{ count: number }>>;
  pending(): Promise<Result<Pending>>;
  clear_pending(key: "restart_needed" | "layout_walk"): Promise<Result<Pending>>;
  start_sync(opts: RunOpts): Promise<Result<{ kind: RunKind }>>;
  start_art_refetch(opts: RunOpts): Promise<Result<{ kind: RunKind }>>;
  start_remove_all(opts: RunOpts): Promise<Result<{ kind: RunKind }>>;
  stop_sync(): Promise<Result<{ running: boolean }>>;
  sync_state(): Promise<Result<SyncState>>;
  sgdb_key_state(): Promise<Result<KeyState>>;
  set_sgdb_key(key: string): Promise<Result<KeyState>>;
  clear_sgdb_key(): Promise<Result<KeyState>>;
  test_sgdb_key(): Promise<Result>;
  /** `--json search TERM`: candidates in the CLI's order (SGDB first when a key is set). */
  search(term: string): Promise<Result<{ candidates: CandidateEvent[]; notes: string[] }>>;
  /** `match NAME --steam | --sgdb | --none --defer-art`: exactly one of the three. */
  pin(
    name: string,
    steam: number | null,
    sgdb: number | null,
    none: boolean,
  ): Promise<Result<{ pinned: PinnedEvent; notes: string[] }>>;
  /** `match NAME --unpin --defer-art`: the next run re-resolves the title. */
  unpin(name: string): Promise<Result<{ pinned: PinnedEvent; notes: string[] }>>;
  /** Add or remove one exact name in `ignore.json` (sorted, idempotent). */
  set_ignored(name: string, ignored: boolean): Promise<Result<{ ignored: string[] }>>;
  /** `layouts.json` (spec 3.10). */
  layouts(): Promise<Result<LayoutsInfo>>;
  /** Upsert one shortcut's layout result atomically; answers with the whole file. */
  record_layout(
    shortcut_appid: number,
    real_appid: number | null,
    result: LayoutResult,
    url: string | null,
  ): Promise<Result<LayoutsInfo>>;
}

/** `@decky/api`'s `callable`, as far as this module needs it. */
export type CallableFactory = <Args extends unknown[], Return>(
  name: string,
) => (...args: Args) => Promise<Return>;

const CALLABLES = [
  "cli_version",
  "cli_capabilities",
  "doctor",
  "log_tail",
  "status",
  "list_apps",
  "list_cached",
  "check_host",
  "hosts",
  "set_host",
  "add_host",
  "forget_host",
  "get_settings",
  "set_settings",
  "set_default_layout",
  "get_ignored",
  "write_owned_apps",
  "pending",
  "clear_pending",
  "start_sync",
  "start_art_refetch",
  "start_remove_all",
  "stop_sync",
  "sync_state",
  "sgdb_key_state",
  "set_sgdb_key",
  "clear_sgdb_key",
  "test_sgdb_key",
  "search",
  "pin",
  "unpin",
  "set_ignored",
  "layouts",
  "record_layout",
] as const satisfies readonly (keyof Backend)[];

/**
 * Wrap every backend callable. A transport failure (the loader rejecting the
 * call) becomes an `io` Failure, so callers only ever see `Result`s.
 */
export function makeBackend(callable: CallableFactory): Backend {
  const backend: Record<string, unknown> = {};
  for (const name of CALLABLES) {
    const call = callable<unknown[], unknown>(name);
    backend[name] = async (...args: unknown[]) => {
      try {
        return await call(...args);
      } catch (error) {
        return { ok: false, error: "io", message: `backend call ${name} failed: ${String(error)}` };
      }
    };
  }
  return backend as unknown as Backend;
}

// ---------------------------------------------------------------------------
// error text (spec 3.8 "Error strings"), mapped once and used everywhere

export function errorText(failure: Failure): string {
  switch (failure.error) {
    case "cli-missing":
      return "CLI not installed — see About";
    case "cli-too-old":
      // The backend also answers `cli-too-old` for a CLI of the right version
      // whose `art` command has no `--commit` (spec 3.13 Q1). "(0.4.0, needs
      // 0.4.0)" would be nonsense there, so its own message stands.
      if (failure.installed && failure.minimum && failure.installed !== failure.minimum) {
        return `CLI too old (${failure.installed}, needs ${failure.minimum}) — see About`;
      }
      return failure.message || "CLI too old — see About";
    case "cli-protocol":
      return "The installed CLI did not understand the request (see the log)";
    case "cli-error":
      return failure.message;
    case "timeout":
      return failure.timeout_s !== undefined
        ? `Timed out after ${failure.timeout_s} s`
        : failure.message || "Timed out";
    case "busy":
      return failure.kind === "match"
        ? "A match change is still being saved"
        : "A sync is already running";
    case "owned-apps-missing":
    case "owned-apps-empty":
      return "Steam library not loaded";
    case "bad-request":
    case "io":
    default:
      return failure.message;
  }
}

export function isFailure<T extends object>(result: Result<T>): result is Failure {
  return result.ok === false;
}

/** The CLI's steamid3 mismatch (spec 3.4.1): rewrite owned-apps.json and retry once. */
export const OWNED_APPS_USER_MISMATCH = "owned-apps file is for Steam user";

export function isSteamUserMismatch(failure: { error: string; message: string } | null): boolean {
  return !!failure && failure.error === "cli-error" && failure.message.includes(OWNED_APPS_USER_MISMATCH);
}
