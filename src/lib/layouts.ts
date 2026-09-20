/**
 * Controller layouts for the hidden Stream shortcuts (spec 3.10), pure.
 *
 * - **The strategy switch.** `DEFAULT_LAYOUT_STRATEGY` is the one constant
 *   that decides between `copy` (read the real game's selection through
 *   Steam Input and set it on the hidden shortcut) and `picker` (no Steam
 *   Input calls; the Titles row's *Choose layout* is the only affordance).
 *   `settings.json`'s `layout_strategy` overrides it by hand on the device.
 *   The PR-0 probe V2 (2026-09-20) confirmed `copy`: a `workshop://` URL set
 *   on a shortcut reads back, given the fifth `SetSelectedConfigForApp`
 *   argument (`CONFIG_SELECTION_USER`). Flipping it would be this constant
 *   plus the README's "Controller layouts" section.
 * - **`copyLayout`** is the rule of spec 3.10, exactly: copy only when the
 *   hidden shortcut has no explicit selection and the real game has one;
 *   never overwrite a selection somebody made on the hidden entry. It takes
 *   a `SteamInput` seam so it is unit-tested; `steam.ts` implements the seam
 *   over `SteamClient.Input`.
 * - The Deck's built-in controller index is found by type, never assumed to
 *   be 0 (spec 2.2); a device without one (a SteamOS box with a separate
 *   pad) falls back to the active or only connected controller
 *   (`layoutControllerIndexFrom`).
 */

import type { LayoutEntry, LayoutResult, LayoutStrategy, Settings } from "./cli";

// ---------------------------------------------------------------------------
// the strategy switch

/** `copy`, confirmed by PR-0 probe V2: the copy sticks. */
export const DEFAULT_LAYOUT_STRATEGY: LayoutStrategy = "copy";

export const LAYOUT_STRATEGIES: readonly LayoutStrategy[] = ["copy", "picker"];

/** `settings.layout_strategy` when it is a known value, else the default. */
export function layoutStrategy(settings: Pick<Settings, "layout_strategy"> | null | undefined): LayoutStrategy {
  const value = settings?.layout_strategy;
  return value !== undefined && LAYOUT_STRATEGIES.includes(value) ? value : DEFAULT_LAYOUT_STRATEGY;
}

/** Does a Stream press (and the post-restart walk) copy layouts at all? */
export function copyEnabled(settings: Pick<Settings, "layout_strategy" | "copy_layouts"> | null | undefined): boolean {
  return layoutStrategy(settings) === "copy" && !!settings?.copy_layouts;
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

/** The three Steam Input touchpoints `copyLayout` needs; `steam.ts` implements them. */
export interface SteamInput {
  /** The controller whose layout is copied (`layoutControllerIndexFrom`); `null` when none is connected. */
  controllerIndex(): number | null;
  /** `SteamClient.Input.GetConfigForAppAndController`. */
  getConfig(appid: number, controllerIndex: number): Promise<LayoutConfig | null>;
  /** `SteamClient.Input.SetSelectedConfigForApp(appid, index, url, false, CONFIG_SELECTION_USER)`. */
  setConfig(appid: number, controllerIndex: number, url: string): Promise<void>;
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
  result: Exclude<LayoutResult, "picker">;
  /**
   * The hidden shortcut's selection after the call: the copied URL, its own
   * choice, Steam's guess (or `null`) when nothing was copied; for a
   * read-back mismatch, the URL that did not stick (what the device check
   * wants to see).
   */
  url: string | null;
}

/**
 * Copy the real game's layout to its hidden shortcut (spec 3.10):
 *
 * - no controller to copy for → `unavailable`;
 * - the real game is on Steam's default → `kept` (nothing to copy);
 * - the shortcut already has its own choice → `kept` (never overwritten);
 * - otherwise set the real game's URL on the shortcut and read it back:
 *   the same URL → `copied`, anything else → `unavailable`.
 *
 * Never rejects: a throwing Steam call is `unavailable`. Idempotent: after a
 * successful copy the next call reads the shortcut's own selection and keeps it.
 */
export async function copyLayout(realAppid: number, shortcutAppid: number, input: SteamInput): Promise<LayoutOutcome> {
  try {
    const idx = input.controllerIndex();
    if (idx === null) return { result: "unavailable", url: null };
    const real = await input.getConfig(realAppid, idx);
    const mine = await input.getConfig(shortcutAppid, idx);
    if (isUnselected(real)) {
      // An offered-but-unselected URL on the shortcut is not its "own layout":
      // record Steam's guess, or nothing, so the row reads "Steam default".
      const offeredOnly = isUnselected(mine) && !isDefaultUrl(mine?.URL);
      return { result: "kept", url: offeredOnly ? null : (mine?.URL ?? null) };
    }
    if (!isUnselected(mine)) return { result: "kept", url: mine!.URL! };
    const url = real!.URL!;
    await input.setConfig(shortcutAppid, idx, url);
    const after = await input.getConfig(shortcutAppid, idx);
    return after?.URL === url ? { result: "copied", url } : { result: "unavailable", url };
  } catch {
    return { result: "unavailable", url: null };
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
 * The controller whose layout `copyLayout` copies: the Deck's built-in one
 * when it is listed (by type); on a device that has none (a SteamOS box with
 * a separate pad, PR-0 probe V1) the active controller when it is listed,
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

/** "copied" / "own layout" / "Steam default" / "unavailable" / "picker opened"; `null` with no record. */
export function layoutStatusText(entry: LayoutEntry | null | undefined): string | null {
  if (!entry) return null;
  switch (entry.result) {
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

/** The library page's note: "Workshop layout · copied", "own layout", "not copied yet". */
export function layoutLine(entry: LayoutEntry | null | undefined): string {
  const status = layoutStatusText(entry);
  if (!status) return "not copied yet";
  if (entry!.result === "copied") return `${layoutKindText(entry!.url)} · copied`;
  return status;
}

// ---------------------------------------------------------------------------
// the post-restart walk (spec 3.10)

export const WALK_POLL_MS = 2_000;
export const WALK_TIMEOUT_MS = 90_000;
export const WALK_STEP_MS = 50;

export interface LayoutPair {
  realAppid: number;
  shortcutAppid: number;
}

/** The stream map as `[real, shortcut]` pairs, in map order. */
export function walkPairs(streamMap: ReadonlyMap<number, number>): LayoutPair[] {
  return [...streamMap].map(([realAppid, shortcutAppid]) => ({ realAppid, shortcutAppid }));
}
