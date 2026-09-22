/**
 * Controller layouts for the plugin's shortcuts (spec 3.10, 3.16), pure.
 *
 * - **The strategy switch.** `DEFAULT_LAYOUT_STRATEGY` is the one constant
 *   that decides between `copy` (the plugin sets layouts through Steam
 *   Input) and `picker` (no Steam Input calls anywhere; the Titles row's
 *   *Choose layout* is the only affordance, and the whole default-layout
 *   feature is off and hidden). `settings.json`'s `layout_strategy`
 *   overrides it by hand on the device. The PR-0 probe V2 (2026-09-20)
 *   confirmed `copy`: a `workshop://` URL set on a shortcut reads back,
 *   given the fifth `SetSelectedConfigForApp` argument
 *   (`CONFIG_SELECTION_USER`). Flipping it would be this constant plus the
 *   README's "Controller layouts" section.
 * - **The default layout** (spec 3.16) replaces the copy from the real
 *   game: one layout the user adopts from a title they set up with Steam's
 *   own configurator (`isShareableUrl`: `workshop://` or `template://`),
 *   applied to every non-parked entry by `applyDefault`, whose one
 *   invariant is that **a selection the plugin did not make is never
 *   overwritten** (`appliedUrl` is what the plugin last set, from
 *   `layouts.json`). `unsetApplied` takes it off again when the default is
 *   cleared (Decision 51). Both take the `SteamInput` seam so they are
 *   unit-tested; `steam.ts` implements the seam over `SteamClient.Input`.
 * - The Deck's built-in controller index is found by type, never assumed to
 *   be 0 (spec 2.2); a device without one (a SteamOS box with a separate
 *   pad) falls back to the active or only connected controller
 *   (`layoutControllerIndexFrom`).
 */

import type { DefaultLayout, EntryEvent, LayoutEntry, LayoutStrategy, Settings } from "./cli";

// ---------------------------------------------------------------------------
// the strategy switch

/** `copy`, confirmed by PR-0 probe V2: a layout set through Steam Input sticks. */
export const DEFAULT_LAYOUT_STRATEGY: LayoutStrategy = "copy";

export const LAYOUT_STRATEGIES: readonly LayoutStrategy[] = ["copy", "picker"];

/** `settings.layout_strategy` when it is a known value, else the default. */
export function layoutStrategy(settings: Pick<Settings, "layout_strategy"> | null | undefined): LayoutStrategy {
  const value = settings?.layout_strategy;
  return value !== undefined && LAYOUT_STRATEGIES.includes(value) ? value : DEFAULT_LAYOUT_STRATEGY;
}

// ---------------------------------------------------------------------------
// the default layout (spec 3.16.1)

/**
 * What can be a default: a `workshop://` layout (community, or a personal
 * one that was *exported*, which PR-0 probe V2 proved sticks on another app)
 * or a `template://` one (Steam's built-ins, expected to **[verify,
 * DEVICE-CHECKLIST]**; the read-back decides per entry, so a wrong guess
 * fails safe as `unavailable`). `autosave://` is a file under one appid and
 * `default://` is no choice at all: both are refused before anything is
 * stored. The backend's `DEFAULT_LAYOUT_SCHEMES` is the same tuple.
 */
export const DEFAULT_LAYOUT_SCHEMES = ["workshop://", "template://"] as const;

export function isShareableUrl(url: string | null | undefined): boolean {
  return typeof url === "string" && DEFAULT_LAYOUT_SCHEMES.some((scheme) => url.startsWith(scheme));
}

/**
 * The plugin's default layout: `null` under `picker` (no Steam Input call is
 * made anywhere then, so the whole feature is off) and when none is set.
 * The backend already reads a broken `default_layout` as `null`; the shape
 * is checked again here so a stale store can never make the walk set a URL
 * that is not shareable.
 */
export function defaultLayoutOf(
  settings: Pick<Settings, "layout_strategy" | "default_layout"> | null | undefined,
): DefaultLayout | null {
  if (layoutStrategy(settings) !== "copy") return null;
  const def = settings?.default_layout;
  if (!def || typeof def !== "object" || !isShareableUrl(def.url) || typeof def.title !== "string") return null;
  return def;
}

// ---------------------------------------------------------------------------
// the Steam Input seam

/** What Steam Input reports for an app on a controller (`URL` is what matters). */
export interface LayoutConfig {
  URL?: string;
  Title?: string;
  /**
   * `false` on a config Steam only *offers*: PR-0 probe V1 read a game whose
   * controller settings were never opened as `template://…` with
   * `bSelected: false`. (`eSelectionType` is not the signal: a layout edited
   * in place is a user's choice and reads 0, like Steam's guess.)
   */
  bSelected?: boolean;
}

/** The Steam Input touchpoints `applyDefault` / `unsetApplied` need; `steam.ts` implements them. */
export interface SteamInput {
  /** The controller the layout is set for (`layoutControllerIndexFrom`); `null` when none is connected. */
  controllerIndex(): number | null;
  /** `SteamClient.Input.GetConfigForAppAndController`. */
  getConfig(appid: number, controllerIndex: number): Promise<LayoutConfig | null>;
  /** `SteamClient.Input.SetSelectedConfigForApp(appid, index, url, false, CONFIG_SELECTION_USER)`. */
  setConfig(appid: number, controllerIndex: number, url: string): Promise<void>;
  /**
   * `SteamClient.Input.ClearSelectedConfigForApp(appid, index)` **[verify,
   * DEVICE-CHECKLIST]**: the name and its two arguments are unmeasured (PR-0
   * probe V2 only found that setting the old `default://` URL back does not
   * restore it). Absent on a client without the call; the default can still
   * be cleared then, and titles keep the layout they have.
   */
  clearConfig?(appid: number, controllerIndex: number): Promise<void>;
}

/** Steam's own guess for an app reads back as `default://<lowercased name>` (spec 2.2). */
export const DEFAULT_URL_PREFIX = "default://";

/** No selection: nothing chosen, or Steam's guess. */
export function isDefaultUrl(url: string | null | undefined): boolean {
  return !url || url.startsWith(DEFAULT_URL_PREFIX);
}

/**
 * Nobody chose this config: no URL, Steam's `default://` guess (which reads
 * `bSelected: true`, so the prefix is still needed), or any URL Steam
 * reports with `bSelected: false`. A missing `bSelected` decides nothing.
 */
export function isUnselected(config: LayoutConfig | null | undefined): boolean {
  return isDefaultUrl(config?.URL) || config?.bSelected === false;
}

export interface LayoutOutcome {
  result: "default" | "kept" | "unavailable";
  /**
   * The shortcut's selection after the call: the default's URL, its own
   * choice, Steam's guess (or `null`) when nothing was set; for a read-back
   * mismatch, the URL that did not stick (what the device check wants to
   * see). After a clear: what the entry reads now, or the URL that would
   * not clear.
   */
  url: string | null;
  /** `unsetApplied` only: `clearConfig` ran and the entry read back unselected. */
  cleared?: boolean;
}

/**
 * The last URL the plugin itself set on a shortcut (spec 3.16.3): the
 * backend's `applied`, or, for a record written before that field existed,
 * the URL of a `copied` result (a pre-3.16 copy counts as plugin-applied,
 * Decision 46). `null` when the selection is one the plugin did not make,
 * or there is no record.
 */
export function appliedUrl(entry: LayoutEntry | null | undefined): string | null {
  if (!entry) return null;
  if (entry.applied !== undefined) return entry.applied;
  return entry.result === "copied" ? entry.url : null;
}

/**
 * Put the default layout on a shortcut (spec 3.16.3), the rule exactly:
 *
 * - no controller → `unavailable`;
 * - the shortcut has a selection that is not the one the plugin made
 *   (`appliedUrl`) → `kept`: **a selection the plugin did not make is never
 *   overwritten** (a layout picked by hand, one edited in place after the
 *   default landed -- it turns `autosave://` -- and the title the default
 *   was adopted from, whose `applied` is null);
 * - the shortcut is already on the default, put there by the plugin →
 *   `default`, no write;
 * - otherwise (nothing selected, an offered `template://` with
 *   `bSelected: false`, or still exactly what the plugin put there while
 *   the default moved on) set the default and read it back: the same URL →
 *   `default`, anything else → `unavailable`.
 *
 * The real game's appid is not an input. Never rejects: a throwing Steam
 * call is `unavailable`. Idempotent: a second call finds the default there.
 */
export async function applyDefault(
  shortcutAppid: number,
  def: DefaultLayout,
  entry: LayoutEntry | null | undefined,
  input: SteamInput,
): Promise<LayoutOutcome> {
  try {
    const idx = input.controllerIndex();
    if (idx === null) return { result: "unavailable", url: null };
    const mine = await input.getConfig(shortcutAppid, idx);
    const ours = appliedUrl(entry);
    if (!isUnselected(mine)) {
      const current = mine!.URL!;
      if (current !== ours) return { result: "kept", url: current };
      if (ours === def.url) return { result: "default", url: def.url };
      // else: still exactly what the plugin put there, and the default moved on
    }
    await input.setConfig(shortcutAppid, idx, def.url);
    const after = await input.getConfig(shortcutAppid, idx);
    return after?.URL === def.url ? { result: "default", url: def.url } : { result: "unavailable", url: def.url };
  } catch {
    return { result: "unavailable", url: null };
  }
}

/**
 * Take the plugin's layout off a shortcut after the default was cleared
 * (spec 3.16.3, Decision 51). `ours` is the record's explicit `applied`
 * **only**, never the legacy-`copied` fallback, so an upgrade with no
 * default ever set unsets nothing. `null` (nothing to do, nothing to
 * record) when there is no `applied`, no `clearConfig` on this client, or no
 * controller. A selection that is not ours, or none → `kept` with what is
 * there, which drops `applied`. Else clear and read back: unselected →
 * `kept` with the read-back (reads "Steam default"), `cleared: true`; still
 * selected, or a throw → `unavailable` with `ours`, so `applied` is carried
 * and a later default still moves the entry.
 */
export async function unsetApplied(
  shortcutAppid: number,
  entry: LayoutEntry | null | undefined,
  input: SteamInput,
): Promise<LayoutOutcome | null> {
  const ours = entry?.applied ?? null;
  if (ours === null || typeof input.clearConfig !== "function") return null;
  try {
    const idx = input.controllerIndex();
    if (idx === null) return null;
    const mine = await input.getConfig(shortcutAppid, idx);
    if (isUnselected(mine) || mine!.URL !== ours) return { result: "kept", url: mine?.URL ?? null };
    await input.clearConfig(shortcutAppid, idx);
    const after = await input.getConfig(shortcutAppid, idx);
    if (isUnselected(after)) return { result: "kept", url: after?.URL ?? null, cleared: true };
    return { result: "unavailable", url: ours };
  } catch {
    return { result: "unavailable", url: ours };
  }
}

// ---------------------------------------------------------------------------
// the Deck controller, by type (spec 2.2: its index is not 0)

/**
 * `EControllerType.SteamControllerNeptune` (the Deck's built-in controller)
 * **[verify V1/V2]**: the enum value is still unmeasured on a Deck (the PR-0
 * probes ran on a SteamOS box with a separate Steam Controller: type 10,
 * `controller_steamcontroller_triton`) and is only the fallback for a client
 * whose `ControllerStore` has no `GetControllerTypeString`; the type string
 * below is the path spec 2.2 sanctions.
 */
export const DECK_CONTROLLER_TYPE = 4;

/** The type string Steam's own code uses for it (the sanctioned way to find the controller). */
export const DECK_CONTROLLER_TYPE_STRING = "controller_steamcontroller_neptune";

export interface ControllerLike {
  nControllerIndex: number;
  eControllerType: number;
}

/**
 * The index of the Deck's built-in controller in `controllers`, found by
 * type: through `typeString` (Steam's `GetControllerTypeString`) when the
 * caller has it, else by the `eControllerType` enum value. `null` when no
 * such controller is listed (docked with the built-in one off, or no list).
 */
export function deckControllerIndexFrom(
  controllers: readonly ControllerLike[] | null | undefined,
  typeString?: (type: number) => string,
): number | null {
  if (!Array.isArray(controllers)) return null;
  for (const controller of controllers) {
    if (!controller || typeof controller.nControllerIndex !== "number") continue;
    const type = controller.eControllerType;
    const isDeck = typeString ? typeString(type) === DECK_CONTROLLER_TYPE_STRING : type === DECK_CONTROLLER_TYPE;
    if (isDeck) return controller.nControllerIndex;
  }
  return null;
}

/**
 * The fifth argument Steam's own configurator passes to
 * `SetSelectedConfigForApp` for a layout the user picked (it reads back as
 * `eSelectionType: 1`). Measured by PR-0 probe V2: without it the call
 * returns normally and selects nothing.
 */
export const CONFIG_SELECTION_USER = 1;

/**
 * The controller the layout is set for: the Deck's built-in one when it is
 * listed (by type); on a device that has none (a SteamOS box with a
 * separate pad, PR-0 probe V1) the active controller when it is listed,
 * else the only listed one. `null` with nothing connected, or with several
 * non-Deck controllers and no active one among them.
 */
export function layoutControllerIndexFrom(
  controllers: readonly ControllerLike[] | null | undefined,
  typeString?: (type: number) => string,
  activeIndex?: number | null,
): number | null {
  const deck = deckControllerIndexFrom(controllers, typeString);
  if (deck !== null) return deck;
  if (!Array.isArray(controllers)) return null;
  const indices = controllers
    .filter((controller) => controller && typeof controller.nControllerIndex === "number")
    .map((controller) => controller.nControllerIndex);
  if (typeof activeIndex === "number" && indices.includes(activeIndex)) return activeIndex;
  return indices.length === 1 ? indices[0] : null;
}

// ---------------------------------------------------------------------------
// what the pages show

/**
 * "default layout" / "own layout" / "Steam default" / "unavailable" /
 * "picker opened"; `null` with no record. "copied" stays for a record the
 * spec 3.10 copy wrote before the default layout replaced it.
 */
export function layoutStatusText(entry: LayoutEntry | null | undefined): string | null {
  if (!entry) return null;
  switch (entry.result) {
    case "default":
      return "default layout";
    case "copied":
      return "copied";
    case "kept":
      return isDefaultUrl(entry.url) ? "Steam default" : "own layout";
    case "unavailable":
      return "unavailable";
    case "picker":
      return "picker opened";
    default:
      return null;
  }
}

/** "Workshop layout", "template layout", "Steam default", or the URL's scheme. */
export function layoutKindText(url: string | null | undefined): string {
  if (isDefaultUrl(url)) return "Steam default";
  const scheme = url!.split("://", 1)[0];
  if (scheme === "workshop") return "Workshop layout";
  if (scheme === "template") return "template layout";
  return `${scheme} layout`;
}

/** The library page's note: "Workshop layout · default layout", "own layout", "not set yet". */
export function layoutLine(entry: LayoutEntry | null | undefined): string {
  const status = layoutStatusText(entry);
  if (!status) return "not set yet";
  if (entry!.result === "default" || entry!.result === "copied") return `${layoutKindText(entry!.url)} · ${status}`;
  return status;
}

// ---------------------------------------------------------------------------
// the post-restart walk (spec 3.10, 3.16.4)

export const WALK_POLL_MS = 2_000;
export const WALK_TIMEOUT_MS = 90_000;
export const WALK_STEP_MS = 50;

export interface WalkTarget {
  shortcutAppid: number;
  /** `match.steam_appid` when the entry has one; `null` for a host app, the client, a title never matched. */
  realAppid: number | null;
}

/**
 * What the walk covers (spec 3.16.4, Decision 48): every `status` entry that
 * is not parked, in order, deduped by appid -- the Stream entries, the
 * visible shortcuts, the two host apps and the Moonlight client entry.
 * Parked entries are skipped: another host's sync sets `layout_walk` again
 * when they unpark.
 */
export function walkTargets(entries: readonly EntryEvent[]): WalkTarget[] {
  const seen = new Set<number>();
  const targets: WalkTarget[] = [];
  for (const entry of entries) {
    if (entry.parked !== false || seen.has(entry.appid)) continue;
    seen.add(entry.appid);
    const steam = entry.match?.steam_appid;
    targets.push({ shortcutAppid: entry.appid, realAppid: typeof steam === "number" ? steam : null });
  }
  return targets;
}

// ---------------------------------------------------------------------------
// the library gear menu (spec 3.16.5, Decision 56)

export interface MenuLayoutSource {
  /** The appid whose selection *Use as Moonlight Sync default layout* reads. */
  appid: number;
  /** `game`: a real game with a Stream entry, read as itself; `entry`: one of the plugin's own non-parked entries. */
  kind: "game" | "entry";
}

/**
 * What the gear menu on a library page adopts a default from (spec 3.16.5,
 * Decision 56): a real game the stream map covers reads *its own*
 * selection, the one the same menu's *Controller settings* edits (not the
 * hidden shortcut's, which the game's page never shows); one of the
 * plugin's own non-parked entries, on the page it has when visible, reads
 * itself as its Titles row does. Any other page gets no item.
 */
export function menuLayoutSourceOf(
  entries: readonly EntryEvent[] | null,
  streamMap: ReadonlyMap<number, number>,
  appid: number,
): MenuLayoutSource | null {
  if (streamMap.has(appid)) return { appid, kind: "game" };
  const entry = entries?.find((e) => e.appid === appid && e.parked === false);
  return entry ? { appid, kind: "entry" } : null;
}
