/**
 * The Titles page's data (spec 3.8, mockup screens 4 and 5), pure.
 *
 * - `joinTitles` joins `list`'s `app` events with `status`'s `entry` events
 *   by Moonlight name into one row per title, with its kind badge, chips,
 *   match line and thumbnail. Parked entries only `status` knows about (the
 *   other hosts' titles, hidden in place) become parked rows too.
 * - `filterRows` / `pageOf` are the five filters, the *Show parked* chip and
 *   the pages of 50.
 * - `candidateRows` / `noMatchRow` / `matchSummary` are the Change match
 *   modal: one list, owned games first, then Steam before SteamGridDB, each
 *   with the outcome a pin would produce, the current match marked, and a
 *   final *No match*.
 */

import type { AppEvent, CandidateEvent, EntryEvent, LayoutEntry, Match, PinnedEvent, SameGameAs } from "./cli";
import { layoutStatusText } from "./layouts";

// ---------------------------------------------------------------------------
// rows

export type RowKind = "stream" | "shortcut" | "ignored" | "parked" | "duplicate";

/** Pill colours, after the mockup's legend. */
export type Tone = "stream" | "ok" | "warn" | "bad" | "neutral";

export type BadgeId = "stream" | "shortcut" | "unmatched" | "ignored" | "parked" | "duplicate";

export interface Badge {
  id: BadgeId;
  text: string;
  tone: Tone;
}

export type ChipId = "fuzzy" | "pinned" | "same-game" | "stale-art";

export interface Chip {
  id: ChipId;
  text: string;
  tone: Tone;
}

export interface TitleRow {
  /** The Moonlight name (the key everything joins on). */
  name: string;
  kind: RowKind;
  /** The one kind badge: what the next sync does with this title. */
  badge: Badge;
  chips: Chip[];
  /** "Balatro · Steam 2379780", "Sea of Stars · SGDB 5322710", "no match", "same game as …". */
  matchLine: string;
  match: Match | null;
  /** Steam's capsule for a title matched to a Steam appid; `null` = the placeholder. */
  thumbnail: string | null;
  /** The owned shortcut for this name, from `status` (none for an ignored or duplicate title). */
  entry: EntryEvent | null;
  ignored: boolean;
  /** `plugin`: in `ignore.json` (Unignore works); `config`: only in the CLI's `config.toml`. */
  ignoredBy: "plugin" | "config" | null;
  unmatched: boolean;
  duplicateOf: string | null;
  sameGameAs: SameGameAs[];
  /**
   * The last layout result for a Stream button's hidden shortcut
   * ("copied" / "own layout" / "Steam default" / "unavailable" / "picker
   * opened", spec 3.10); `null` for other rows and before any copy.
   */
  layout: string | null;
  /** The hidden shortcut and the owned game a *Choose layout* / copy would work on. */
  layoutTarget: { shortcutAppid: number; realAppid: number } | null;
}

export const BADGES: Record<BadgeId, Badge> = {
  stream: { id: "stream", text: "stream button", tone: "stream" },
  shortcut: { id: "shortcut", text: "shortcut", tone: "ok" },
  unmatched: { id: "unmatched", text: "unmatched", tone: "bad" },
  ignored: { id: "ignored", text: "ignored", tone: "neutral" },
  parked: { id: "parked", text: "parked", tone: "neutral" },
  // "carries a warning chip like fuzzy" (spec 3.8): the badge is that warning
  duplicate: { id: "duplicate", text: "duplicate", tone: "warn" },
};

export const STALE_ART_TEXT = "art refreshes on next sync";

/** Steam's library capsule for an appid (Decision 15: the frontend cannot read `grid/`). */
export function capsuleUrl(steamAppid: number): string {
  return `https://cdn.cloudflare.steamstatic.com/steam/apps/${steamAppid}/library_600x900.jpg`;
}

function hasIds(match: Match | null | undefined): boolean {
  return !!match && (match.steam_appid !== null || match.sgdb_id !== null);
}

export function isFuzzy(match: Match | null | undefined, appFuzzy = false): boolean {
  return appFuzzy || (!!match && match.how.endsWith(":fuzzy"));
}

export function isPinned(match: Match | null | undefined): boolean {
  return match?.how === "pinned";
}

/** "Balatro · Steam 2379780" / "Sea of Stars · SGDB 5322710" / "no match" (spec 3.8). */
export function matchLineOf(match: Match | null, ignored = false): string {
  if (!hasIds(match)) return ignored && !match ? "—" : "no match";
  const m = match as Match;
  const id = m.steam_appid !== null ? `Steam ${m.steam_appid}` : `SGDB ${m.sgdb_id}`;
  return m.matched_name ? `${m.matched_name} · ${id}` : id;
}

function sameGameText(other: SameGameAs): string {
  return `same game on ${other.host} as "${other.name}"`;
}

interface RowInput {
  name: string;
  kind: RowKind;
  match: Match | null;
  fuzzy: boolean;
  duplicateOf: string | null;
  sameGameAs: SameGameAs[];
  entry: EntryEvent | null;
  ignoredBy: "plugin" | "config" | null;
  layouts: Readonly<Record<string, LayoutEntry>>;
}

/**
 * The hidden shortcut a layout copy works on: a stream row whose entry is
 * hidden, not parked, and matched to a Steam appid (the stream map's rule).
 */
export function layoutTargetOf(kind: RowKind, entry: EntryEvent | null): TitleRow["layoutTarget"] {
  const steam = entry?.match?.steam_appid;
  if (kind !== "stream" || !entry || !entry.hidden || entry.parked || entry.client || typeof steam !== "number") {
    return null;
  }
  return { shortcutAppid: entry.appid, realAppid: steam };
}

function buildRow(input: RowInput): TitleRow {
  const { name, match, entry, duplicateOf, sameGameAs, ignoredBy } = input;
  const ignored = ignoredBy !== null;
  const kind: RowKind = ignored ? "ignored" : input.kind;
  const unmatched = kind === "shortcut" && !hasIds(match);
  const layoutTarget = layoutTargetOf(kind, entry);
  const layout = layoutTarget ? layoutStatusText(input.layouts[String(layoutTarget.shortcutAppid)]) : null;

  let badge: Badge;
  if (kind === "shortcut") badge = unmatched ? BADGES.unmatched : BADGES.shortcut;
  else badge = BADGES[kind];

  const chips: Chip[] = [];
  if (isFuzzy(match, input.fuzzy) && !isPinned(match)) chips.push({ id: "fuzzy", text: "fuzzy", tone: "warn" });
  if (isPinned(match)) chips.push({ id: "pinned", text: "pinned", tone: "neutral" });
  for (const other of sameGameAs) chips.push({ id: "same-game", text: sameGameText(other), tone: "warn" });
  if (entry?.stale_art) chips.push({ id: "stale-art", text: STALE_ART_TEXT, tone: "neutral" });

  const matchLine =
    kind === "duplicate" && duplicateOf ? `same game as ${duplicateOf}` : matchLineOf(match, ignored);
  const steam = match?.steam_appid;
  return {
    name,
    kind,
    badge,
    chips,
    matchLine,
    match,
    thumbnail: typeof steam === "number" ? capsuleUrl(steam) : null,
    entry,
    ignored,
    ignoredBy,
    unmatched,
    duplicateOf,
    sameGameAs,
    layout,
    layoutTarget,
  };
}

const collator = new Intl.Collator("en", { sensitivity: "base", numeric: true });

/** By name, case-insensitively (the mockup's "sorted by name"); exact order breaks ties. */
export function compareNames(a: string, b: string): number {
  return collator.compare(a, b) || (a < b ? -1 : a > b ? 1 : 0);
}

/**
 * One row per title: every `app` of `list`, joined by name with its owned
 * `entry` from `status` (never the client entry), plus a parked row for each
 * parked entry `list` did not mention. `ignoreFile` is `ignore.json`: a name
 * in it is ignored (and can be unignored) even before the next `list` says
 * so; a name `list` calls ignored that is not in it is ignored by the CLI's
 * `config.toml`, which the plugin never writes. `layouts` is `layouts.json`'s
 * `entries`, for the stream rows' layout text.
 */
export function joinTitles(
  apps: readonly AppEvent[],
  entries: readonly EntryEvent[],
  ignoreFile: readonly string[] = [],
  layouts: Readonly<Record<string, LayoutEntry>> = {},
): TitleRow[] {
  const byName = new Map<string, EntryEvent>();
  for (const entry of entries) {
    if (!entry.client && !byName.has(entry.name)) byName.set(entry.name, entry);
  }
  const inFile = new Set(ignoreFile);
  const seen = new Set<string>();
  const rows: TitleRow[] = [];
  for (const app of apps) {
    if (seen.has(app.name)) continue;
    seen.add(app.name);
    const ignoredBy = inFile.has(app.name) ? "plugin" : app.kind === "ignored" ? "config" : null;
    rows.push(
      buildRow({
        name: app.name,
        kind: app.kind,
        match: app.match,
        fuzzy: app.fuzzy,
        duplicateOf: app.duplicate_of,
        sameGameAs: app.same_game_as ?? [],
        entry: byName.get(app.name) ?? null,
        ignoredBy,
        layouts,
      }),
    );
  }
  for (const entry of byName.values()) {
    if (seen.has(entry.name) || !entry.parked) continue;
    seen.add(entry.name);
    rows.push(
      buildRow({
        name: entry.name,
        kind: "parked",
        match: entry.match,
        fuzzy: false,
        duplicateOf: null,
        sameGameAs: [],
        entry,
        ignoredBy: inFile.has(entry.name) ? "plugin" : null,
        layouts,
      }),
    );
  }
  return rows.sort((a, b) => compareNames(a.name, b.name));
}

// ---------------------------------------------------------------------------
// filters and paging

export type TitleFilter = "all" | "stream" | "shortcut" | "unmatched" | "ignored";

export const FILTERS: readonly { id: TitleFilter; label: string }[] = [
  { id: "all", label: "All" },
  { id: "stream", label: "Stream buttons" },
  { id: "shortcut", label: "Shortcuts" },
  { id: "unmatched", label: "Unmatched" },
  { id: "ignored", label: "Ignored" },
];

/** Does `row` belong under `filter`? Parked rows are handled by `filterRows`. */
export function matchesFilter(row: TitleRow, filter: TitleFilter): boolean {
  switch (filter) {
    case "all":
      return true;
    case "stream":
      return row.kind === "stream";
    case "shortcut":
      return row.kind === "shortcut";
    case "unmatched":
      return row.unmatched;
    case "ignored":
      return row.ignored;
  }
}

/**
 * The rows a filter shows, in order. Parked rows (the other hosts' titles)
 * are hidden unless *Show parked* is on, and then listed under *All* only:
 * a parked title is none of the other four until its host is active again.
 */
export function filterRows(rows: readonly TitleRow[], filter: TitleFilter, showParked = false): TitleRow[] {
  return rows.filter((row) =>
    row.kind === "parked" ? showParked && filter === "all" : matchesFilter(row, filter),
  );
}

/** How many rows each filter would show (parked rows only ever count toward `all`). */
export function filterCounts(rows: readonly TitleRow[], showParked = false): Record<TitleFilter, number> {
  const counts = { all: 0, stream: 0, shortcut: 0, unmatched: 0, ignored: 0 };
  for (const filter of FILTERS) counts[filter.id] = filterRows(rows, filter.id, showParked).length;
  return counts;
}

export function parkedCount(rows: readonly TitleRow[]): number {
  return rows.filter((row) => row.kind === "parked").length;
}

/** Titles the active host publishes (everything but parked rows). */
export function publishedCount(rows: readonly TitleRow[]): number {
  return rows.length - parkedCount(rows);
}

export const PAGE_SIZE = 50;

export interface Page {
  rows: TitleRow[];
  /** Rows not rendered yet. */
  remaining: number;
  hasMore: boolean;
}

/** The first `pages` pages of 50 (at least one). */
export function pageOf(rows: readonly TitleRow[], pages: number, size = PAGE_SIZE): Page {
  const shown = Math.max(1, Math.floor(pages)) * size;
  const slice = rows.slice(0, shown);
  const remaining = rows.length - slice.length;
  return { rows: slice, remaining, hasMore: remaining > 0 };
}

/** "Show 50 more (73 left)". */
export function loadMoreLabel(page: Page, size = PAGE_SIZE): string {
  return `Show ${Math.min(size, page.remaining)} more (${page.remaining} left)`;
}

/**
 * `apps` with `pinned`'s title re-pointed, until the next `list` says so
 * itself: `how: "pinned"`, no longer fuzzy. `matchedName` is the chosen
 * candidate's name (`null` for *No match*).
 */
export function applyPin(apps: readonly AppEvent[], pinned: PinnedEvent, matchedName: string | null): AppEvent[] {
  return apps.map((app) =>
    app.name === pinned.name
      ? {
          ...app,
          fuzzy: false,
          match: {
            steam_appid: pinned.steam_appid,
            sgdb_id: pinned.sgdb_id,
            matched_name: pinned.steam_appid === null && pinned.sgdb_id === null ? null : matchedName,
            how: "pinned",
          },
        }
      : app,
  );
}

// ---------------------------------------------------------------------------
// the Change match modal

export type Outcome = "becomes stream button" | "shortcut";

/** What `pin` gets for a choice: exactly one selector (spec 3.7). */
export interface PinChoice {
  steam: number | null;
  sgdb: number | null;
  none: boolean;
}

export interface CandidateRow {
  key: string;
  source: "steam" | "sgdb" | "none";
  name: string;
  /** "Steam 1145350 · owned on this account · current match". */
  detail: string;
  outcome: string;
  tone: Tone;
  current: boolean;
  choice: PinChoice;
}

/**
 * A pin of an owned Steam game is how a title becomes a Stream button on the
 * next sync (pins count as exact, spec 3.2); anything else is a shortcut.
 */
export function outcomeOf(candidate: CandidateEvent): Outcome {
  return candidate.owned ? "becomes stream button" : "shortcut";
}

const candidateKey = (candidate: CandidateEvent) => `${candidate.source}:${candidate.id}`;

/**
 * The key of the one row that is the current match, or `null`.
 *
 * At most one row may be marked. A pinned or resolved match can carry both a
 * `steam_appid` and an `sgdb_id`, and both a Steam-store and a SteamGridDB
 * candidate could answer to them -- but only when the SGDB lookup failed,
 * because the real CLI already drops a Steam-store candidate whose appid
 * equals an SGDB candidate's `steam_appid` (spec 3.4.6, the `search` bullet:
 * "SGDB wins"). So the SGDB candidate wins here too, and the Steam one is
 * the current match only when no SGDB candidate answers.
 */
export function currentCandidateKey(
  candidates: readonly CandidateEvent[],
  current: Match | null,
): string | null {
  if (!current) return null;
  if (current.sgdb_id !== null) {
    const sgdb = candidates.find((c) => c.source === "sgdb" && c.id === current.sgdb_id);
    if (sgdb) return candidateKey(sgdb);
  }
  if (current.steam_appid !== null) {
    const steam = candidates.find((c) => c.source === "steam" && c.id === current.steam_appid);
    if (steam) return candidateKey(steam);
  }
  return null;
}

function candidateDetail(candidate: CandidateEvent, current: boolean): string {
  const parts: string[] = [];
  if (candidate.source === "steam") {
    parts.push(`Steam ${candidate.id}`);
  } else {
    parts.push(`SteamGridDB ${candidate.id}`);
    parts.push(candidate.steam_appid !== null ? `Steam ${candidate.steam_appid}` : "community art only");
  }
  if (candidate.owned) parts.push("owned on this account");
  if (current) parts.push("current match");
  return parts.join(" · ");
}

/**
 * `search`'s candidates as one list: the games owned on this account first
 * (the ones a pin turns into a Stream button), then the rest; within each
 * group Steam first, then SteamGridDB, each in the CLI's order.
 */
export function candidateRows(candidates: readonly CandidateEvent[], current: Match | null): CandidateRow[] {
  const bySource = [
    ...candidates.filter((c) => c.source === "steam"),
    ...candidates.filter((c) => c.source === "sgdb"),
  ];
  const ordered = [...bySource.filter((c) => c.owned), ...bySource.filter((c) => !c.owned)];
  const currentKey = currentCandidateKey(candidates, current);
  return ordered.map((candidate) => {
    const isCurrent = candidateKey(candidate) === currentKey;
    const outcome = outcomeOf(candidate);
    return {
      key: candidateKey(candidate),
      source: candidate.source,
      name: candidate.name,
      detail: candidateDetail(candidate, isCurrent),
      outcome,
      tone: outcome === "becomes stream button" ? "stream" : "ok",
      current: isCurrent,
      choice:
        candidate.source === "steam"
          ? { steam: candidate.id, sgdb: null, none: false }
          : { steam: null, sgdb: candidate.id, none: false },
    };
  });
}

/** The final row: pin "no match" (a shortcut with art found by name on SteamGridDB). */
export function noMatchRow(current: Match | null): CandidateRow {
  const isCurrent = isPinned(current) && !hasIds(current);
  return {
    key: "none",
    source: "none",
    name: "No match",
    detail: `Keep as a shortcut, search SteamGridDB by name for art${isCurrent ? " · current match" : ""}`,
    outcome: "pinned",
    tone: "neutral",
    current: isCurrent,
    choice: { steam: null, sgdb: null, none: true },
  };
}

function howText(how: string): string {
  if (how.endsWith(":fuzzy")) return "by a fuzzy title search";
  if (how === "pinned") return "by a pin";
  if (how === "override") return "by an override in config.toml";
  if (how.endsWith(":exact") || how.endsWith(":exact-verified")) return "by an exact title search";
  return "";
}

export interface MatchSummary {
  /** Text before the bold name ("Currently matched to "), or the whole line when `name` is null. */
  lead: string;
  name: string | null;
  /** Text after the name (" (Steam 1145360) by a fuzzy title search."). */
  tail: string;
  /** A `config.toml` override wins over any pin (spec 3.4.4). */
  overrideWins: boolean;
}

/** The modal's subtitle: "Currently matched to **Hades** (Steam 1145360) by a fuzzy title search." */
export function matchSummary(match: Match | null): MatchSummary {
  const overrideWins = match?.how === "override";
  if (!match) return { lead: "Not matched yet.", name: null, tail: "", overrideWins };
  if (!hasIds(match)) {
    return {
      lead: isPinned(match) ? "Pinned to no match." : "Currently no match.",
      name: null,
      tail: "",
      overrideWins,
    };
  }
  const id = match.steam_appid !== null ? `Steam ${match.steam_appid}` : `SteamGridDB ${match.sgdb_id}`;
  const how = howText(match.how);
  return {
    lead: "Currently matched to ",
    name: match.matched_name ?? id,
    tail: `${match.matched_name ? ` (${id})` : ""}${how ? ` ${how}` : ""}.`,
    overrideWins,
  };
}
