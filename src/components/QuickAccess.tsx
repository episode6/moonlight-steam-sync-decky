import {
  ButtonItem,
  DialogButton,
  DropdownItem,
  Field,
  Focusable,
  Navigation,
  PanelSection,
  PanelSectionRow,
  Spinner,
} from "@decky/ui";
import { useEffect, type ReactNode } from "react";
import { FaGamepad } from "react-icons/fa";

import { SETTINGS_ROUTE, controller } from "../instance";
import { lastSyncLine, relativeTime } from "../lib/format";
import {
  HOST_APPS,
  actionsReady,
  ignoredCounter,
  otherHostsLine,
  restartRowView,
  wakeInfoOf,
  type AppState,
  type HostAppKey,
} from "../lib/state";
import { pluginEnabled } from "../lib/library";
import { confirmSwitch } from "./confirmSwitch";
import { EnabledToggle } from "./EnabledToggle";
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

/**
 * A default host app's row (spec 3.8, 3.14.1): the launch button and, when
 * the client can open the controller configurator, an icon-only *Choose
 * layout* button beside it -- the hidden entry has no library page to reach
 * it from. Neither button is held back while a game runs: Moonlight's own
 * UI handles a stream that is already going.
 */
function HostAppRow({
  app,
  canChooseLayout,
}: {
  app: { key: HostAppKey; name: string; description: string };
  canChooseLayout: boolean;
}) {
  if (!canChooseLayout) {
    return (
      <ButtonItem
        layout="below"
        description={app.description}
        onClick={() => controller.openHostApp(app.key)}
      >
        {app.name}
      </ButtonItem>
    );
  }
  return (
    <div style={{ padding: "10px 0" }}>
      <Focusable flow-children="horizontal" style={{ display: "flex", gap: 8 }}>
        <DialogButton
          style={{ flex: 1, minWidth: 0 }}
          onClick={() => controller.openHostApp(app.key)}
        >
          {app.name}
        </DialogButton>
        <DialogButton
          aria-label={`Choose controller layout for ${app.name}`}
          style={{
            flex: "0 0 40px",
            width: 40,
            minWidth: 0,
            padding: 0,
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
          }}
          onClick={() => {
            Navigation.CloseSideMenus();
            void controller.chooseHostAppLayout(app.key);
          }}
        >
          <FaGamepad />
        </DialogButton>
      </Focusable>
      <div style={{ fontSize: 12, opacity: 0.7, marginTop: 6 }}>{app.description}</div>
    </div>
  );
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
          <Focusable style={{ display: "flex", gap: 8 }}>
            <DialogButton style={{ minWidth: 0, flex: 1 }} onClick={() => void controller.checkHost(true)}>
              Retry
            </DialogButton>
            {/* Wake-on-LAN (spec 3.18): only when a MAC is known for the host,
                from the Host page or Moonlight's own list; otherwise the Host
                page is where to enter one, so the button is not shown dead. */}
            {wakeInfoOf(hosts, hosts.active) ? (
              <DialogButton style={{ minWidth: 0, flex: 1 }} onClick={() => void controller.wakeHost()}>
                Wake
              </DialogButton>
            ) : null}
          </Focusable>
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

  // The on/off toggle (spec 3.19) heads the panel in every state below;
  // off, it is all the panel shows.
  const toggle = (
    <PanelSectionRow>
      <EnabledToggle state={state} />
    </PanelSectionRow>
  );
  if (!pluginEnabled(state.settings)) {
    return <PanelSection>{toggle}</PanelSection>;
  }

  if (state.cli && state.cli.state !== "ok") {
    return (
      <PanelSection>
        {toggle}
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
        {toggle}
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
  const canChooseLayout = controller.canChooseLayout();
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
      {toggle}
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
            <HostAppRow app={app} canChooseLayout={canChooseLayout} />
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
