import { describe, expect, it } from "vitest";

import { loadFixture } from "../test/fixtures";
import type { EntryEvent, SyncDonePayload } from "./cli";
import { eventsOf } from "./events";
import {
  actionsReady,
  applyRunDone,
  applyRunEvent,
  clientAppid,
  countersFromStatus,
  hostAppsFromStatus,
  ignoredCounter,
  initialState,
  newRun,
  otherHostsLine,
  progressFraction,
  RECENT_TITLES,
  runFromSyncState,
  Store,
  streamMapFromStatus,
  withCliVersion,
  withStatus,
} from "./state";

const entries = eventsOf(loadFixture("common/status.ndjson"), "entry");

describe("counters from status (spec 3.8)", () => {
  it("counts stream buttons, shortcuts, unmatched and parked", () => {
    // Balatro + Sea of Stars hidden; Hades II + Tunic visible; Tunic unmatched;
    // Spiritfarer parked; the client entry is not counted.
    expect(countersFromStatus(entries)).toEqual({ stream: 2, shortcuts: 2, unmatched: 1, parked: 1 });
  });

  it("an empty library is all zeros", () => {
    expect(countersFromStatus([])).toEqual({ stream: 0, shortcuts: 0, unmatched: 0, parked: 0 });
  });

  it("a missing match counts as unmatched", () => {
    const bare: EntryEvent = { ...entries[1], match: null, hidden: false };
    expect(countersFromStatus([bare]).unmatched).toBe(1);
  });
});

describe("stream map and client", () => {
  it("maps owned steam appids to their hidden shortcuts, skipping parked and the client", () => {
    expect([...streamMapFromStatus(entries)]).toEqual([
      [2379780, 2718281828],
      [1244090, 2987654321],
    ]);
  });

  it("finds the client entry for Open Moonlight", () => {
    expect(clientAppid(entries)).toBe(2400000001);
    expect(clientAppid(entries.filter((e) => !e.client))).toBeNull();
  });

  it("finds the Desktop and Steam Big Picture entries by Moonlight name", () => {
    const tunic = entries.find((e) => e.name === "Tunic")!;
    const desktop: EntryEvent = { ...tunic, name: "desktop ", app_name: "Desktop (MY-GAMING-PC)", appid: 3000000101 };
    const bigPicture: EntryEvent = { ...tunic, name: "Steam Big Picture", appid: 3000000102, hidden: true };
    expect(hostAppsFromStatus(entries)).toEqual({ desktop: null, bigPicture: null });
    expect(hostAppsFromStatus([...entries, desktop, bigPicture])).toEqual({
      desktop: 3000000101,
      bigPicture: 3000000102,
    });
    // Another host's parked copy is not launchable from this one.
    expect(hostAppsFromStatus([{ ...desktop, parked: true, published: false }]).desktop).toBeNull();
    // Only the Moonlight name counts, not what the shortcut is called.
    expect(hostAppsFromStatus([{ ...tunic, app_name: "Desktop" }]).desktop).toBeNull();
  });
});

describe("run reducers", () => {
  const events = loadFixture("full-sync/sync.ndjson");

  it("fold a full sync", () => {
    let run = newRun("sync");
    const seen: number[] = [];
    for (const event of events) {
      run = applyRunEvent(run, event);
      if (event.event === "title") seen.push(progressFraction(run)!);
    }
    expect(run.plan?.to_add).toBe(2);
    expect(run.titles.map((t) => t.name)).toEqual(["Balatro", "Cocoon", "Tunic"]);
    expect(seen).toEqual([1 / 3, 2 / 3, 1]);
    expect(run.sawAwaiting).toBe(true);
    expect(run.awaiting).toBe(false); // the commit ended the wait
    expect(run.commit?.written).toBe(true);
    expect(run.summary?.added).toBe(2);
    expect(run.events).toHaveLength(events.length);
  });

  it("awaiting is set by the wait and cleared by the commit", () => {
    let run = newRun("sync");
    for (const event of events.slice(0, 7)) run = applyRunEvent(run, event);
    expect(run.awaiting).toBe(true);
    expect(progressFraction(newRun("sync"))).toBeNull();
  });

  it("keeps only the last few titles", () => {
    let run = newRun("art");
    for (let i = 1; i <= 8; i++) {
      run = applyRunEvent(run, {
        event: "title",
        index: i,
        total: 8,
        name: `T${i}`,
        kind: "shortcut",
        appid: i,
        match: null,
        slots: {},
      });
    }
    expect(run.titles).toHaveLength(RECENT_TITLES);
    expect(run.titles[0].name).toBe("T4");
  });

  it("sync_done ends the run", () => {
    let run = newRun("sync");
    for (const event of events) run = applyRunEvent(run, event);
    const done: SyncDonePayload = {
      kind: "sync",
      exit: 0,
      pending: {
        restart_needed: "none",
        layout_walk: true,
        since: null,
        last_summary: null,
        last_plan: null,
        last_kind: "sync",
      },
      summary: run.summary,
      commit: run.commit,
      failure: null,
    };
    const ended = applyRunDone(run, done);
    expect(ended.running).toBe(false);
    expect(ended.exit).toBe(0);
  });

  it("re-attaches from sync_state after a reload", () => {
    const run = runFromSyncState({
      running: true,
      kind: "sync",
      started: "2026-09-18T14:00:00Z",
      opts: { immediate_restart: true },
      awaiting_exit: true,
      last_exit: null,
      last_kind: null,
      events: events.slice(0, 7),
    });
    expect(run?.running).toBe(true);
    expect(run?.awaiting).toBe(true);
    expect(run?.immediate).toBe(true);
    expect(run?.titles).toHaveLength(3);
    expect(
      runFromSyncState({
        running: false,
        kind: null,
        started: null,
        opts: {},
        awaiting_exit: false,
        last_exit: null,
        last_kind: null,
        events: [],
      }),
    ).toBeNull();
  });
});

describe("the store and derived flags", () => {
  it("notifies subscribers", () => {
    const store = new Store({ n: 0 });
    let calls = 0;
    const off = store.subscribe(() => calls++);
    store.set({ n: 1 });
    store.set((s) => ({ n: s.n + 1 }));
    off();
    store.set({ n: 5 });
    expect(calls).toBe(2);
    expect(store.get().n).toBe(5);
  });

  it("actions need a usable CLI and a written owned-apps file", () => {
    let state = initialState();
    expect(actionsReady(state)).toBe(false);
    state = withCliVersion(state, {
      installed: "0.3.0",
      bundled: null,
      minimum: "0.3.0",
      too_old: false,
      installed_path: "~/.local/bin/moonlight-steam-sync",
      bundled_path: "",
      pinned: "0.3.0",
      plugin_version: "0.1.0",
      log_path: "",
      install_error: null,
      capabilities: { art_commit: false },
    });
    expect(actionsReady(state)).toBe(false);
    state = { ...state, library: "ready" };
    expect(actionsReady(state)).toBe(true);
  });

  it("status fills counters, the stream map and the client appid", () => {
    const state = withStatus(initialState(), entries);
    expect(state.counters?.stream).toBe(2);
    expect(state.streamMap.size).toBe(2);
    expect(state.clientAppid).toBe(2400000001);
  });

  it("the ignored counter prefers check_host's count", () => {
    const state = { ...initialState(), ignoredCount: 3 };
    expect(ignoredCounter(state)).toBe(3);
    expect(
      ignoredCounter({
        ...state,
        reach: { host: "MY-GAMING-PC", reachable: true, count: 7, ignored: 1, checked_at: "" },
      }),
    ).toBe(1);
  });

  it("names the other hosts and their parked titles", () => {
    const hosts = { active: "MY-GAMING-PC", source: "state" as const, cached_hosts: [], known: ["MY-GAMING-PC", "OFFICE-PC"] };
    expect(otherHostsLine(hosts, 198)).toBe("active host · OFFICE-PC parked (198 titles kept)");
    expect(otherHostsLine({ ...hosts, known: ["MY-GAMING-PC"] }, 0)).toBe("active host");
    expect(otherHostsLine({ ...hosts, active: null }, 0)).toBe("");
  });

  it("never blames one parked total on several hosts", () => {
    // The total says nothing per host, so each host's last listing is shown.
    const hosts = {
      active: "MY-GAMING-PC",
      source: "state" as const,
      cached_hosts: [
        { name: "OFFICE-PC", when: "2026-09-19T10:00:00Z", count: 312 },
        { name: "MY-GAMING-PC", when: "2026-09-20T10:00:00Z", count: 40 },
      ],
      known: ["MY-GAMING-PC", "OFFICE-PC", "LIVING-ROOM-PC"],
    };
    expect(otherHostsLine(hosts, 198)).toBe(
      "active host · parked from OFFICE-PC (312 titles), LIVING-ROOM-PC",
    );
  });
});
