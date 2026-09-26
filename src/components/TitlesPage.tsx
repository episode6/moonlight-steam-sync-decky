import { DialogButton, Field, Focusable, Menu, MenuItem, Spinner, showContextMenu, showModal } from "@decky/ui";
import { toaster } from "@decky/api";
import { useCallback, useEffect, useMemo, useRef, useState, type CSSProperties, type RefObject } from "react";

import { controller } from "../instance";
import { errorText, isFailure, type PinnedEvent } from "../lib/cli";
import type { TitlesData, TitlesLoad } from "../lib/controller";
import { relativeTime } from "../lib/format";
import { layoutStrategy } from "../lib/layouts";
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
import { adoptAsDefault } from "./adoptDefault";
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
  locked,
  ignoring,
  canChooseLayout,
  canSetDefault,
  onChangeMatch,
  onIgnore,
  rowRef,
}: {
  row: TitleRow;
  /** A run is going: both edits are held until it finishes. */
  locked: boolean;
  ignoring: boolean;
  /** `SteamClient.Apps.ShowControllerConfigurator` exists (else *Choose layout…* is hidden, spec 3.10). */
  canChooseLayout: boolean;
  /** The strategy is `copy` (under `picker` the default layout is off and hidden, spec 3.16). */
  canSetDefault: boolean;
  onChangeMatch(): void;
  onIgnore(): void;
  /** Set on the last row shown, which *Show more* focuses before it grows the page. */
  rowRef?: RefObject<HTMLDivElement | null>;
}) {
  const chooseLayout = row.layoutTarget && canChooseLayout ? row.layoutTarget : null;
  const useAsDefaultSource = canSetDefault ? row.layoutSource : null;
  // The *Layout* menu (Decision 50): both layout actions in one button.
  const layoutMenu = (event: MouseEvent) =>
    showContextMenu(
      <Menu label={row.name}>
        {chooseLayout ? (
          <MenuItem onSelected={() => void controller.chooseLayout(chooseLayout.shortcutAppid, chooseLayout.realAppid)}>
            Choose layout…
          </MenuItem>
        ) : null}
        {useAsDefaultSource !== null ? (
          <MenuItem onSelected={() => void adoptAsDefault(useAsDefaultSource, row.name, "titles")}>
            Use as the default layout
          </MenuItem>
        ) : null}
      </Menu>,
      event.currentTarget ?? undefined,
    );
  return (
    <Focusable
      ref={rowRef}
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
          {row.layout ? <span style={{ marginLeft: 2 }}>· layout: {row.layout}</span> : null}
        </div>
      </div>
      <Pill tone={row.badge.tone}>{row.badge.text}</Pill>
      {!row.ignored ? (
        <DialogButton style={SMALL} disabled={locked} onClick={onChangeMatch}>
          Change match
        </DialogButton>
      ) : null}
      {chooseLayout || useAsDefaultSource !== null ? (
        <DialogButton style={SMALL} onClick={layoutMenu}>
          Layout
        </DialogButton>
      ) : null}
      {row.ignoredBy === "config" ? (
        <DialogButton style={SMALL} disabled>
          Ignored in config.toml
        </DialogButton>
      ) : (
        <DialogButton style={SMALL} disabled={locked || ignoring} onClick={onIgnore}>
          {row.ignored ? "Unignore" : "Ignore"}
        </DialogButton>
      )}
    </Focusable>
  );
}

/**
 * The page reads the per-host cache only (a live `list` wakes the PC,
 * Decision 66), so the headline says when it was listed; *Sync now* is
 * what refreshes it.
 */
function headline(data: TitlesData, rows: readonly TitleRow[]): string {
  const published = publishedCount(rows);
  const when = data.cachedWhen ? ` · listed ${relativeTime(data.cachedWhen)}` : "";
  if (data.source === "syncing") {
    return `${published} published by ${data.host}${when} · refreshes when the sync finishes`;
  }
  return `${published} published by ${data.host}${when} · sorted by name`;
}

/**
 * Settings → Titles, `/moonlight-sync/titles` (spec 3.8, mockup screen 4):
 * every title the active host publishes, joined from `list` and `status`,
 * with what the next sync does with it. Rows render 50 at a time with a
 * load-more row; *Change match* opens the picker, *Ignore* / *Unignore*
 * edits `ignore.json`. A row with a non-parked entry also shows its last
 * layout result ("default layout" / "own layout" / "Steam default" /
 * "unavailable", spec 3.10, 3.16) and has a *Layout* menu: *Choose
 * layout…*, Steam's own picker for the hidden shortcut (hidden when the
 * client lacks it), and *Use as the default layout*, which adopts this
 * title's layout for every entry (spec 3.16.5). Nothing here restarts Steam: a pin or
 * an ignore takes effect on the next sync. While a run is going the list
 * comes from the CLI's per-host cache (no live `list` racing the run), both
 * row edits are locked, and the page refreshes when the run finishes. A
 * host no sync has planned for yet shows no titles at all, only that it
 * was never synced and a *Sync now* button.
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
  const lastRowRef = useRef<HTMLDivElement>(null);

  const refresh = useCallback(async () => {
    const id = ++loadId.current;
    setLoading(true);
    const result = await controller.loadTitles();
    if (id !== loadId.current) return;
    lastLoad = result;
    setLoad(result);
    setLoading(false);
  }, []);

  // on mount, and again when a match-cache reset changed what list says
  const epoch = state.titlesEpoch;
  useEffect(() => {
    if (ready && active) void refresh();
  }, [ready, active, epoch, refresh]);

  // a sync that just finished changed what list and status say; one that
  // just started changes what the page says about them
  const wasRunning = useRef(running);
  useEffect(() => {
    if (wasRunning.current !== running && ready && active) void refresh();
    wasRunning.current = running;
  }, [running, ready, active, refresh]);

  const data = load?.ok && load.data.host === active ? load.data : null;
  const layouts = state.layouts;
  const rows = useMemo(
    () => (data ? joinTitles(data.apps, data.entries, data.ignored, layouts) : []),
    [data, layouts],
  );
  const canChooseLayout = controller.canChooseLayout();
  const canSetDefault = layoutStrategy(state.settings) === "copy";
  const shown = useMemo(() => filterRows(rows, filter, showParked), [rows, filter, showParked]);
  const counts = useMemo(() => filterCounts(rows, showParked), [rows, showParked]);
  const page = pageOf(shown, pages);

  // Gamepad focus stays on the button that was pressed, and the button moves
  // down past the new rows, so the user would land below them. Focus the last
  // row already shown first, then grow the page: the next press of down steps
  // into the first new row. Disabled controls are skipped: focus() on one is a
  // no-op (*Change match* while a run is going, *Ignored in config.toml*).
  const showMore = () => {
    const row = lastRowRef.current;
    const target = row?.querySelector<HTMLElement>("button:not(:disabled), [tabindex]") ?? row;
    target?.focus();
    requestAnimationFrame(() => setPages((current) => current + 1));
  };

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

  const syncNow = async () => {
    const failure = await controller.sync();
    if (failure) toaster.toast({ title: "Moonlight Sync", body: errorText(failure) });
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
    // No re-list: `set_ignored` touches ignore.json only, its result *is* the
    // new ignore list, and joinTitles applies it locally. `controller
    // .setIgnored` has already refreshed the panel's Ignored counter. The
    // titles themselves only change on the next sync.
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
    // Nothing is listed for a host no sync has planned for, even when a
    // *Check* or an add cached its list: only the way to sync it.
    if (load && !load.ok && load.neverSynced && !loading) {
      return (
        <div>
          <Field description={load.message} focusable={false} />
          {!running ? (
            <DialogButton style={SMALL} onClick={() => void syncNow()}>
              Sync now
            </DialogButton>
          ) : null}
        </div>
      );
    }
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
      {data.statusError ? (
        <div style={{ fontSize: 11.5, opacity: 0.7, marginBottom: 6 }}>status: {data.statusError}</div>
      ) : null}
      {running ? (
        <div style={{ fontSize: 11.5, opacity: 0.7, marginBottom: 6 }}>
          A sync is running; this list refreshes, and matches and ignores can be changed, when it
          finishes.
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
        {page.rows.map((row, index) => (
          <Row
            key={row.name}
            rowRef={index === page.rows.length - 1 ? lastRowRef : undefined}
            row={row}
            locked={running}
            ignoring={ignoring === row.name}
            canChooseLayout={canChooseLayout}
            canSetDefault={canSetDefault}
            onChangeMatch={() => changeMatch(row)}
            onIgnore={() => void toggleIgnore(row)}
          />
        ))}
        {page.hasMore ? (
          <DialogButton style={{ marginTop: 8 }} onClick={showMore}>
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
