/**
 * What the plugin keeps in step inside the Steam client's own library state
 * after every `status` (spec 3.15): the **Streaming** collection and the
 * hidden state of the CLI's entries.
 *
 * Both exist because of one device finding (2026-09-21): the current client
 * ignores `IsHidden` in `shortcuts.vdf`. Hidden state lives in the client's
 * own "hidden" collection, which only the running client can change, so the
 * CLI cannot hide anything and the plugin mirrors `status`'s `hidden` into
 * the client instead. This is the one exception to "the CLI is the only
 * writer", and it touches no file: both go through `collectionStore`.
 *
 * This module is the pure half (what should be where); `steam.ts` holds the
 * `LibraryPort` over the real globals and `Controller.reconcileLibrary()`
 * applies the difference.
 */

import type { EntryEvent, Settings } from "./cli";
import { streamMapFromStatus } from "./state";

/** The collection's name, which is also how it is found again (no id is stored). */
export const STREAMING_COLLECTION = "Streaming";

/** The client's library state, as far as the reconcile needs it (`steam.ts` implements it). */
export interface LibraryPort {
  /** The client can hide and unhide apps at all (else the setting is shown disabled). */
  canHide(): boolean;
  /** `null` when the client cannot say; the reconcile then sets the state regardless. */
  isHidden(appid: number): boolean | null;
  setHidden(appids: readonly number[], hidden: boolean): void;
  /** The client has user collections the plugin can create and edit. */
  canCollect(): boolean;
  /** The appids in the named collection; `null` when there is no such collection. */
  collectionApps(name: string): number[] | null;
  /** Create the collection when absent, then add / remove. Appids with no overview are skipped. */
  updateCollection(name: string, add: readonly number[], remove: readonly number[]): Promise<void>;
  deleteCollection(name: string): Promise<void>;
}

export function hideStreamEnabled(settings: Pick<Settings, "hide_stream_shortcuts"> | null | undefined): boolean {
  return settings?.hide_stream_shortcuts !== false;
}

export function streamingCollectionEnabled(
  settings: Pick<Settings, "streaming_collection"> | null | undefined,
): boolean {
  return settings?.streaming_collection !== false;
}

/**
 * Every title that can be streamed from the active host, one appid each: the
 * real Steam game for a title with a Stream button (the stream map's keys),
 * the Moonlight shortcut itself for a visible one. Never the client, a
 * default host app, a parked or an unpublished entry.
 */
export function streamingMembers(entries: readonly EntryEvent[]): number[] {
  const members = new Set<number>(streamMapFromStatus(entries).keys());
  for (const entry of entries) {
    if (entry.client || entry.host_app || entry.parked || !entry.published || entry.hidden) continue;
    members.add(entry.appid);
  }
  return [...members];
}

export interface HiddenPlan {
  hide: number[];
  show: number[];
}

/**
 * Where each of the CLI's entries belongs. `status`'s `hidden` is the truth
 * (it is `IsHidden` on disk); `hideStream` (the *Hide Stream shortcuts*
 * setting) only governs Stream-button entries. The client entry, the default
 * host apps and parked entries are hidden whatever it says: the panel's
 * buttons replace the first three and a parked tile belongs to another host.
 * An entry `status` calls visible is shown again, which is what unparks it.
 */
export function hiddenPlan(entries: readonly EntryEvent[], hideStream: boolean): HiddenPlan {
  const plan: HiddenPlan = { hide: [], show: [] };
  for (const entry of entries) {
    const always = entry.client || entry.parked || entry.host_app === true;
    (entry.hidden && (always || hideStream) ? plan.hide : plan.show).push(entry.appid);
  }
  return plan;
}

/** `wanted` against `current`: what to add and what to remove. */
export function collectionDiff(
  wanted: readonly number[],
  current: readonly number[],
): { add: number[]; remove: number[] } {
  const want = new Set(wanted);
  const have = new Set(current);
  return { add: wanted.filter((id) => !have.has(id)), remove: current.filter((id) => !want.has(id)) };
}
