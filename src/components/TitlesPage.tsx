import { DialogButton, Field, Focusable, Spinner, showModal } from "@decky/ui";
import { toaster } from "@decky/api";
import { useCallback, useEffect, useMemo, useRef, useState, type CSSProperties } from "react";

import { controller } from "../instance";
import { errorText, isFailure, type PinnedEvent } from "../lib/cli";
import type { TitlesData, TitlesLoad } from "../lib/controller";
import { relativeTime } from "../lib/format";
import {
  applyPin,
  FILTERS,
  filterCounts,
  filterRows,
  joinTitles,
  loadMoreLabel,
  pageOf,
  parkedCount,
  publishedCount,
  type TitleFilter,
  type TitleRow,
} from "../lib/join";
import { actionsReady } from "../lib/state";
import { ChangeMatchModal } from "./ChangeMatchModal";
import { Pill } from "./Pill";
import { useStore } from "./useStore";

/** The last listing, so revisiting the page renders at once while it re-lists. */
let lastLoad: TitlesLoad | null = null;

const SMALL: CSSProperties = { minWidth: 0, width: "auto", padding: "4px 10px", fontSize: 12 };

function chipStyle(on: boolean): CSSProperties {
  return {
    ...SMALL,
    borderRadius: 12,
    padding: "3px 12px",
    background: on ? "#1a9fff" : undefined,
    color: on ? "#fff" : undefined,
  };
}

/** The capsule for a matched title; the striped placeholder otherwise (or when it fails to load). */
function Thumb({ url }: { url: string | null }) {
  const [failed, setFailed] = useState(false);
  const box: CSSProperties = { width: 32, height: 48, borderRadius: 2, flexShrink: 0, objectFit: "cover" };
  if (!url || failed) {
    return (
      <div
        style={{
          ...box,
          background: "repeating-linear-gradient(45deg, #2a3543 0 4px, #1b2838 4px 8px)",
        }}
      />
    );
  }
  return <img src={url} loading="lazy" style={box} onError={() => setFailed(true)} alt="" />;
}

function Row({
  row,
  pinLocked,
  ignoring,
  onChangeMatch,
  onIgnore,
}: {
  row: TitleRow;
  pinLocked: boolean;
  ignoring: boolean;
  onChangeMatch(): void;
  onIgnore(): void;
}) {
  return (
    <Focusable
      flow-children="horizontal"
      style={{
        display: "flex",
        alignItems: "center",
        gap: 10,
        padding: "6px 0",
        borderBottom: "1px solid rgba(255,255,255,0.08)",
      }}
    >
      {/* Keyed on the URL so a re-pointed row gets a fresh load-failure state. */}
      <Thumb key={row.thumbnail ?? "none"} url={row.thumbnail} />
      <div style={{ flexGrow: 1, minWidth: 0 }}>
        <div style={{ fontWeight: 600, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
          {row.name}
        </div>
        <div style={{ fontSize: 11.5, opacity: 0.75, display: "flex", flexWrap: "wrap", gap: 4, alignItems: "center" }}>
          <span style={{ marginRight: 2 }}>{row.matchLine}</span>
          {row.chips.map((chip) => (
            <Pill
              key={`${chip.id}:${chip.text}`}
              tone={chip.tone}
              style={chip.id === "same-game" || chip.id === "stale-art" ? { textTransform: "none" } : undefined}
            >
              {chip.text}
            </Pill>
          ))}
        </div>
      </div>
      <Pill tone={row.badge.tone}>{row.badge.text}</Pill>
      {!row.ignored ? (
        <DialogButton style={SMALL} disabled={pinLocked} onClick={onChangeMatch}>
          Change match
        </DialogButton>
      ) : null}
      {row.ignoredBy === "config" ? (
        <DialogButton style={SMALL} disabled>
          Ignored in config.toml
        </DialogButton>
      ) : (
        <DialogButton style={SMALL} disabled={ignoring} onClick={onIgnore}>
          {row.ignored ? "Unignore" : "Ignore"}
        </DialogButton>
      )}
    </Focusable>
  );
}

function headline(data: TitlesData, rows: readonly TitleRow[]): string {
  const published = publishedCount(rows);
  if (data.source === "cached") {
    return `${published} titles cached from ${relativeTime(data.cachedWhen)} · ${data.host} is unreachable · sorted by name`;
  }
  if (data.source === "syncing") {
    const when = data.cachedWhen ? ` from ${relativeTime(data.cachedWhen)}` : "";
    return `${published} titles cached${when} · refreshes when the sync finishes`;
  }
  return `${published} published by ${data.host} · sorted by name`;
}

/**
 * Settings → Titles, `/moonlight-sync/titles` (spec 3.8, mockup screen 4):
 * every title the active host publishes, joined from `list` and `status`,
 * with what the next sync does with it. Rows render 50 at a time with a
 * load-more row; *Change match* opens the picker, *Ignore* / *Unignore*
 * edits `ignore.json`. Nothing here restarts Steam: a pin or an ignore
 * takes effect on the next sync. While a run is going the list comes from
 * the CLI's per-host cache (no live `list` racing the run) and refreshes
 * when the run finishes.
 */
export function TitlesPage() {
  const state = useStore(controller.store);
  const [load, setLoad] = useState<TitlesLoad | null>(lastLoad);
  const [loading, setLoading] = useState(false);
  const [filter, setFilter] = useState<TitleFilter>("all");
  const [showParked, setShowParked] = useState(false);
  const [pages, setPages] = useState(1);
  const [ignoring, setIgnoring] = useState<string | null>(null);
  const [note, setNote] = useState<string | null>(null);
  const ready = actionsReady(state);
  const active = state.hosts?.active ?? null;
  const running = !!state.run?.running;
  const loadId = useRef(0);

  const refresh = useCallback(async () => {
    const id = ++loadId.current;
    setLoading(true);
    const result = await controller.loadTitles();
    if (id !== loadId.current) return;
    lastLoad = result;
    setLoad(result);
    setLoading(false);
  }, []);

  useEffect(() => {
    if (ready && active) void refresh();
  }, [ready, active, refresh]);

  // a sync that just finished changed what list and status say
  const wasRunning = useRef(running);
  useEffect(() => {
    if (wasRunning.current && !running && ready && active) void refresh();
    wasRunning.current = running;
  }, [running, ready, active, refresh]);

  const data = load?.ok && load.data.host === active ? load.data : null;
  const rows = useMemo(() => (data ? joinTitles(data.apps, data.entries, data.ignored) : []), [data]);
  const shown = useMemo(() => filterRows(rows, filter, showParked), [rows, filter, showParked]);
  const counts = useMemo(() => filterCounts(rows, showParked), [rows, showParked]);
  const page = pageOf(shown, pages);

  const choose = (next: TitleFilter) => {
    setFilter(next);
    setPages(1);
  };

  const onPinned = (pinned: PinnedEvent, matchedName: string | null) => {
    if (data) {
      const next: TitlesLoad = { ok: true, data: { ...data, apps: applyPin(data.apps, pinned, matchedName) } };
      lastLoad = next;
      setLoad(next);
    }
    void refresh(); // the next list reports the pin itself, and status the art refresh
  };

  const changeMatch = (row: TitleRow) => {
    showModal(<ChangeMatchModal row={row} onPinned={onPinned} />);
  };

  const toggleIgnore = async (row: TitleRow) => {
    const ignore = !row.ignored;
    setIgnoring(row.name);
    setNote(null);
    const result = await controller.setIgnored(row.name, ignore);
    setIgnoring(null);
    if (isFailure(result)) {
      setNote(errorText(result));
      return;
    }
    if (data) {
      const next: TitlesLoad = { ok: true, data: { ...data, ignored: result.ignored } };
      lastLoad = next;
      setLoad(next);
    }
    toaster.toast({
      title: "Moonlight Sync",
      body: `${ignore ? "Ignored" : "Unignored"} “${row.name}”; sync to apply`,
    });
    void refresh();
  };

  if (!ready || !active) {
    const why = !state.loaded
      ? "Loading…"
      : state.cli && state.cli.state !== "ok"
        ? state.cli.text
        : !active && state.hosts
          ? "No host yet; add one on the Host page"
          : "Loading your library…";
    return <Field description={why} focusable={false} />;
  }

  if (!data) {
    if (load && !load.ok && !loading) {
      return (
        <div>
          <Field description={load.message} focusable={false} />
          <DialogButton style={SMALL} onClick={() => void refresh()}>
            Retry
          </DialogButton>
        </div>
      );
    }
    return (
      <Field label={`Listing ${active}…`} focusable={false}>
        <Spinner style={{ width: 20, height: 20 }} />
      </Field>
    );
  }

  const parked = parkedCount(rows);
  return (
    <div>
      <div style={{ fontSize: 12, opacity: 0.75, marginBottom: 8, display: "flex", gap: 8, alignItems: "center" }}>
        <span>{headline(data, rows)}</span>
        {loading ? <Spinner style={{ width: 14, height: 14 }} /> : null}
      </div>
      {data.unreachable ? (
        <div style={{ fontSize: 11.5, color: "#ff9a9a", marginBottom: 6 }}>{data.unreachable}</div>
      ) : null}
      {data.statusError ? (
        <div style={{ fontSize: 11.5, opacity: 0.7, marginBottom: 6 }}>status: {data.statusError}</div>
      ) : null}
      {running ? (
        <div style={{ fontSize: 11.5, opacity: 0.7, marginBottom: 6 }}>
          A sync is running; this list refreshes and matches can be changed when it finishes.
        </div>
      ) : null}
      <Focusable flow-children="horizontal" style={{ display: "flex", flexWrap: "wrap", gap: 6, marginBottom: 10 }}>
        {FILTERS.map(({ id, label }) => (
          <DialogButton key={id} style={chipStyle(filter === id)} onClick={() => choose(id)}>
            {label} ({counts[id]})
          </DialogButton>
        ))}
        {parked > 0 ? (
          <DialogButton
            style={chipStyle(showParked)}
            onClick={() => {
              if (!showParked) choose("all"); // parked titles are listed under All
              setShowParked(!showParked);
            }}
          >
            Show parked ({parked})
          </DialogButton>
        ) : null}
        <DialogButton style={chipStyle(false)} disabled={loading} onClick={() => void refresh()}>
          Refresh
        </DialogButton>
      </Focusable>
      {note ? <div style={{ fontSize: 12, color: "#ff9a9a", marginBottom: 6 }}>{note}</div> : null}
      <Focusable style={{ display: "flex", flexDirection: "column" }}>
        {page.rows.map((row) => (
          <Row
            key={row.name}
            row={row}
            pinLocked={running}
            ignoring={ignoring === row.name}
            onChangeMatch={() => changeMatch(row)}
            onIgnore={() => void toggleIgnore(row)}
          />
        ))}
        {page.hasMore ? (
          <DialogButton style={{ marginTop: 8 }} onClick={() => setPages(pages + 1)}>
            {loadMoreLabel(page)}
          </DialogButton>
        ) : null}
      </Focusable>
      {shown.length === 0 ? (
        <div style={{ fontSize: 12, opacity: 0.7, marginTop: 8 }}>Nothing here.</div>
      ) : null}
    </div>
  );
}
