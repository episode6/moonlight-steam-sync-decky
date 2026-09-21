import {
  ButtonItem,
  DropdownItem,
  Field,
  Navigation,
  PanelSection,
  PanelSectionRow,
  Spinner,
} from "@decky/ui";
import { useEffect, type ReactNode } from "react";

import { SETTINGS_ROUTE, controller } from "../instance";
import { lastSyncLine, relativeTime } from "../lib/format";
import {
  HOST_APPS,
  actionsReady,
  ignoredCounter,
  otherHostsLine,
  restartRowView,
  type AppState,
} from "../lib/state";
import { confirmSwitch } from "./confirmSwitch";
import { SyncProgress } from "./SyncProgress";
import { useStore } from "./useStore";

const dot = (color: string) => (
  <span
    style={{
      display: "inline-block",
      width: 8,
      height: 8,
      borderRadius: "50%",
      background: color,
      marginRight: 6,
    }}
  />
);

function openSettings(page?: string) {
  Navigation.Navigate(page ? `${SETTINGS_ROUTE}/${page}` : SETTINGS_ROUTE);
  Navigation.CloseSideMenus();
}

function Counter({ value, label }: { value: number | null | undefined; label: string }) {
  return (
    <div
      style={{
        background: "rgba(255,255,255,0.06)",
        borderRadius: 4,
        padding: "6px 10px",
      }}
    >
      <div style={{ fontSize: 17, fontWeight: 600 }}>{value ?? "–"}</div>
      <div style={{ fontSize: 10, opacity: 0.7, textTransform: "uppercase" }}>{label}</div>
    </div>
  );
}

function HostRow({ state }: { state: AppState }) {
  const hosts = state.hosts;
  if (!hosts?.active) {
    return (
      <PanelSectionRow>
        <ButtonItem
          layout="below"
          label="No host yet"
          description="Add the gaming PC you stream from"
          onClick={() => openSettings("host")}
        >
          Add a host
        </ButtonItem>
      </PanelSectionRow>
    );
  }
  const reach = state.reach;
  let reachLine: ReactNode;
  if (state.reachLoading && !reach) {
    reachLine = <span>Checking {hosts.active}…</span>;
  } else if (!reach) {
    reachLine = <span>{hosts.active}</span>;
  } else if (reach.reachable) {
    reachLine = (
      <span>
        {dot("#5ba32b")}
        {reach.count} apps
      </span>
    );
  } else {
    reachLine = (
      <span>
        {dot("#d94b4b")}
        {reach.message} · last seen{" "}
        {reach.last_seen ? relativeTime(reach.last_seen) : "never synced"}
      </span>
    );
  }
  const options = hosts.known.map((name) => ({ data: name, label: name }));
  if (!hosts.known.some((name) => name.toLowerCase() === hosts.active!.toLowerCase())) {
    options.unshift({ data: hosts.active, label: hosts.active });
  }
  return (
    <>
      <PanelSectionRow>
        <DropdownItem
          label="Host"
          description={
            <div>
              <div>{reachLine}</div>
              <div style={{ opacity: 0.7 }}>{otherHostsLine(hosts, state.counters?.parked ?? 0)}</div>
            </div>
          }
          rgOptions={options}
          selectedOption={hosts.active}
          disabled={!actionsReady(state) || !!state.run?.running}
          onChange={(option) => {
            const name = option.data as string;
            if (name !== hosts.active) confirmSwitch(controller, name);
          }}
        />
      </PanelSectionRow>
      {reach && !reach.reachable ? (
        <PanelSectionRow>
          <ButtonItem layout="below" onClick={() => void controller.checkHost(true)}>
            Retry
          </ButtonItem>
        </PanelSectionRow>
      ) : null}
    </>
  );
}

function RestartRow({ state }: { state: AppState }) {
  const view = restartRowView(state);
  if (!view) return null;
  return (
    <PanelSectionRow>
      <ButtonItem
        layout="below"
        description={view.description}
        disabled={view.disabled}
        onClick={() => void controller.restartRow()}
      >
        Restart Steam to apply
      </ButtonItem>
    </PanelSectionRow>
  );
}

/** The Quick Access panel (spec 3.8, mockup screen 1). */
export function QuickAccess() {
  const state = useStore(controller.store);
  useEffect(() => {
    void controller.panelOpened();
  }, []);

  if (!state.loaded) {
    return (
      <PanelSection>
        <PanelSectionRow>
          <Field label="Loading…" focusable={false}>
            <Spinner style={{ width: 20, height: 20 }} />
          </Field>
        </PanelSectionRow>
      </PanelSection>
    );
  }

  if (state.cli && state.cli.state !== "ok") {
    return (
      <PanelSection>
        <PanelSectionRow>
          <ButtonItem layout="below" description={state.cli.text} onClick={() => openSettings("about")}>
            Open About
          </ButtonItem>
        </PanelSectionRow>
      </PanelSection>
    );
  }

  // `cli_version()` itself failed (the loader was not ready yet, say): the CLI
  // may well be fine, so offer the read again rather than a dead panel.
  if (!state.cli) {
    return (
      <PanelSection>
        <PanelSectionRow>
          <ButtonItem
            layout="below"
            description={state.cliError ?? "The plugin backend did not answer"}
            onClick={() => void controller.refreshCli()}
          >
            Retry
          </ButtonItem>
        </PanelSectionRow>
      </PanelSection>
    );
  }

  if (state.run?.running) {
    return <SyncProgress run={state.run} onStop={() => void controller.stop()} />;
  }

  const ready = actionsReady(state);
  const libraryRow =
    state.library === "loading" || state.library === "waiting" ? (
      <PanelSectionRow>
        <Field label="Loading your library…" focusable={false}>
          <Spinner style={{ width: 20, height: 20 }} />
        </Field>
      </PanelSectionRow>
    ) : state.library === "failed" ? (
      <PanelSectionRow>
        <ButtonItem
          layout="below"
          description="Steam library not loaded; close and reopen the menu"
          onClick={() => void controller.retryLibrary()}
        >
          Retry
        </ButtonItem>
      </PanelSectionRow>
    ) : null;

  const counters = state.counters;
  return (
    <PanelSection>
      {libraryRow}
      <HostRow state={state} />
      <RestartRow state={state} />
      <PanelSectionRow>
        <ButtonItem
          layout="below"
          description="Refresh the host list, add art, restart Steam if needed"
          disabled={!ready || !state.hosts?.active}
          onClick={() => void controller.sync()}
        >
          Sync now
        </ButtonItem>
      </PanelSectionRow>
      <PanelSectionRow>
        <ButtonItem
          layout="below"
          description={
            state.clientAppid === null ? "Sync once to enable" : "Launch the client without picking a game"
          }
          disabled={state.clientAppid === null}
          onClick={() => controller.openMoonlight()}
        >
          Open Moonlight
        </ButtonItem>
      </PanelSectionRow>
      {HOST_APPS.map((app) =>
        state.hostApps[app.key] === null ? null : (
          <PanelSectionRow key={app.key}>
            <ButtonItem
              layout="below"
              description={app.description}
              onClick={() => controller.openHostApp(app.key)}
            >
              {app.name}
            </ButtonItem>
          </PanelSectionRow>
        ),
      )}
      {state.message ? (
        <PanelSectionRow>
          <Field description={state.message} focusable={false} />
        </PanelSectionRow>
      ) : null}
      <PanelSectionRow>
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 6, padding: "6px 0" }}>
          <Counter value={counters?.stream} label="Stream buttons" />
          <Counter value={counters?.shortcuts} label="Shortcuts" />
          <Counter value={counters?.unmatched} label="Unmatched" />
          <Counter value={ignoredCounter(state)} label="Ignored" />
        </div>
      </PanelSectionRow>
      <PanelSectionRow>
        <Field label="Last sync" description={lastSyncLine(state.pending)} focusable={false} />
      </PanelSectionRow>
      <PanelSectionRow>
        <ButtonItem layout="below" onClick={() => openSettings()}>
          Settings
        </ButtonItem>
      </PanelSectionRow>
    </PanelSection>
  );
}
