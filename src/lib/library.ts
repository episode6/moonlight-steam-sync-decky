/**
 * What the plugin keeps in step inside the Steam client's own library state
 * after every `status` (spec 3.15, 3.17): the hidden state of the CLI's
 * entries, and the **Streaming** group -- a synthetic library tab (spec
 * 3.17, `tabs.ts` and `routes/libraryTabs.tsx`), or, while *Hide Stream
 * shortcuts* is off, a real *Streaming* collection of this device's
 * Moonlight shortcuts only.
 *
 * Hiding exists because of one device finding (2026-09-21): the current
 * client ignores `IsHidden` in `shortcuts.vdf`. Hidden state lives in the
 * client's own "hidden" collection, which only the running client can
 * change, so the CLI cannot hide anything and the plugin mirrors `status`'s
 * `hidden` into the client instead. This is the one exception to "the CLI
 * is the only writer", and it touches no file: everything goes through
 * `collectionStore`.
 *
 * The tab replaced a collection of the streamable titles (Decision 55): a
 * user collection syncs through Steam Cloud, so one holding owned games was
 * fought over by two devices on different hosts, each reconcile removing
 * the other's members. The fallback collection holds shortcuts only, and
 * the reconcile removes only members this device's `status` knows: another
 * device's members, and anything the user put there, are left alone.
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

/**
 * The plugin is on at all (spec 3.19): the `enabled` setting, absent reads
 * as on. Off, every one of the CLI's entries is hidden in the client, the
 * library gets no Stream button, tab or menu item, and nothing runs; only
 * the toggle itself is live.
 */
export function pluginEnabled(settings: Pick<Settings, "enabled"> | null | undefined): boolean {
  return settings?.enabled !== false;
}

/** The text under the panel's and the settings route's toggle while the plugin is off (spec 3.19). */
export const DISABLED_TEXT =
  "Off: every Moonlight shortcut is hidden and the library gets no Stream buttons or Streaming tab. Nothing syncs and the settings are locked until it is on again.";

export function hideStreamEnabled(settings: Pick<Settings, "hide_stream_shortcuts"> | null | undefined): boolean {
  return settings?.hide_stream_shortcuts !== false;
}

/** The *Streaming* group (tab or fallback collection) is wanted at all: the `streaming_collection` setting. */
export function streamingCollectionEnabled(
  settings: Pick<Settings, "streaming_collection"> | null | undefined,
): boolean {
  return settings?.streaming_collection !== false;
}

/**
 * The synthetic *Streaming* tab is shown (spec 3.17): whenever the group is
 * wanted, whatever *Hide Stream shortcuts* says (the user, 2026-09-21: the
 * tab works in both states), and the plugin is on (spec 3.19). With Stream
 * shortcuts shown, the fallback collection comes *in addition*.
 */
export function streamingTabEnabled(
  settings: Pick<Settings, "streaming_collection" | "enabled"> | null | undefined,
): boolean {
  return pluginEnabled(settings) && streamingCollectionEnabled(settings);
}

/**
 * The *Streaming* tab's tiles (spec 3.17): every title that can be streamed
 * from the active host, one appid each -- the real Steam game for a title
 * with a Stream button (the stream map's keys), the Moonlight shortcut
 * itself for a visible one. Never the client, a default host app, a parked
 * or an unpublished entry.
 */
export function streamingMembers(entries: readonly EntryEvent[]): number[] {
  const members = new Set<number>(streamMapFromStatus(entries).keys());
  for (const entry of entries) {
    if (entry.client || entry.host_app || entry.parked || !entry.published || entry.hidden) continue;
    members.add(entry.appid);
  }
  return [...members];
}

/**
 * The fallback collection's members (spec 3.17): only while Stream
 * shortcuts are shown (`hideStream` false), alongside the tab, every
 * Moonlight shortcut the client shows -- published, not parked, not the client, not a host app --
 * whether `status` calls it hidden (a Stream entry) or not. Never a real
 * Steam appid: those are what synced across devices and fought.
 */
export function collectionMembers(entries: readonly EntryEvent[], hideStream: boolean): number[] {
  if (hideStream) return [];
  const members: number[] = [];
  for (const entry of entries) {
    if (entry.client || entry.host_app || entry.parked || !entry.published) continue;
    members.push(entry.appid);
  }
  return members;
}

/**
 * Every appid this device's `status` accounts for: each entry's shortcut and
 * the real game behind each Stream button. A collection member outside this
 * set is not the plugin's to remove (another device's, or the user's). This
 * is what the group being turned off takes out (`retireCollection`): after
 * that the device never touches the collection again, so no loop can start.
 */
export function knownAppids(entries: readonly EntryEvent[]): Set<number> {
  const known = new Set<number>(streamMapFromStatus(entries).keys());
  for (const entry of entries) known.add(entry.appid);
  return known;
}

/**
 * What the reconcile may remove from the collection (spec 3.17). Shortcut
 * appids hash from the exe and the name, so two devices under one account
 * share them for the titles both hosts have; a device that removed every
 * shortcut it knew would fight a device that keeps the collection. So: the
 * real games behind Stream buttons always (v0.4.0 put them in; no device
 * wants them now), and this device's shortcuts only while it keeps the
 * collection itself (`hideStream` false) and only the non-parked ones -- a
 * parked title is another host's, and maybe live on another device. With
 * the tab alone in effect the shortcuts stay, hidden and out of sight,
 * until the group is turned off.
 */
export function removableAppids(entries: readonly EntryEvent[], hideStream: boolean): Set<number> {
  const removable = new Set<number>(streamMapFromStatus(entries).keys());
  if (hideStream) return removable;
  for (const entry of entries) if (!entry.parked) removable.add(entry.appid);
  return removable;
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
 * With the plugin off (`enabled` false, spec 3.19) every entry is hidden,
 * visible ones included: a Deck away from its host shows no Moonlight tile.
 */
export function hiddenPlan(entries: readonly EntryEvent[], hideStream: boolean, enabled = true): HiddenPlan {
  const plan: HiddenPlan = { hide: [], show: [] };
  for (const entry of entries) {
    if (!enabled) {
      plan.hide.push(entry.appid);
      continue;
    }
    const always = entry.client || entry.parked || entry.host_app === true;
    (entry.hidden && (always || hideStream) ? plan.hide : plan.show).push(entry.appid);
  }
  return plan;
}

/**
 * `wanted` against `current`: what to add, and what to remove -- only
 * members in `known` (this device's own entries), so a member another
 * device or the user added stays.
 */
export function collectionDiff(
  wanted: readonly number[],
  current: readonly number[],
  known: ReadonlySet<number>,
): { add: number[]; remove: number[] } {
  const want = new Set(wanted);
  const have = new Set(current);
  return {
    add: wanted.filter((id) => !have.has(id)),
    remove: current.filter((id) => !want.has(id) && known.has(id)),
  };
}
