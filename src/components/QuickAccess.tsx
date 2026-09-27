import {
  ButtonItem,
  DialogButton,
  Dropdown,
  Field,
  Focusable,
  Navigation,
  PanelSection,
  PanelSectionRow,
  Spinner,
} from "@decky/ui";
import { useEffect, useState, type ReactNode } from "react";
import { FaDesktop, FaGamepad, FaMoon, FaStar, FaSteam } from "react-icons/fa";

import { SETTINGS_ROUTE, controller } from "../instance";
import { lastSyncLine } from "../lib/format";
import { layoutStrategy } from "../lib/layouts";
import {
  actionsReady,
  clientLayoutCaption,
  hostOptions,
  hostRowView,
  ignoredCounter,
  launchButtons,
  launchCaption,
  restartRowView,
  wakeInfoOf,
  type AppState,
  type HostTone,
  type LaunchKey,
} from "../lib/state";
import { pluginEnabled } from "../lib/library";
import { adoptAsDefault } from "./adoptDefault";
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

const ICON_BUTTON = {
  flex: 1,
  minWidth: 0,
  height: 44,
  padding: 0,
  display: "flex",
  alignItems: "center",
  justifyContent: "center",
} as const;

const LAYOUT_BUTTON = {
  flex: 1,
  minWidth: 0,
  padding: "0 8px",
  display: "flex",
  alignItems: "center",
  justifyContent: "center",
  gap: 8,
  whiteSpace: "nowrap",
} as const;

const LAUNCH_ICONS: Record<LaunchKey, ReactNode> = {
  moonlight: <FaMoon size={22} />,
  desktop: <FaDesktop size={22} />,
  bigPicture: <FaSteam size={22} />,
};

/**
 * The launch row (spec 3.8, Decision 67): *Open Moonlight*, *Desktop* and
 * *Steam Big Picture* as icon buttons on one line. An icon has no label
 * under gamepad focus, so the line under the row names the focused button
 * (and the footer's A legend says it too), and Moonlight's once focus has
 * left the row. A blur clears only its own key, so the result does not hang
 * on whether the old button's blur or the new one's focus comes first.
 * None is held back while a game
 * runs: Moonlight's own UI handles a stream that is already going.
 */
function LaunchRow({ state }: { state: AppState }) {
  const [focused, setFocused] = useState<LaunchKey | null>(null);
  const buttons = launchButtons(state);
  const caption = launchCaption(buttons, focused);
  return (
    <div style={{ padding: "10px 0" }}>
      <Focusable flow-children="horizontal" style={{ display: "flex", gap: 8 }}>
        {buttons.map((button) => (
          <DialogButton
            key={button.key}
            aria-label={button.label}
            style={ICON_BUTTON}
            disabled={button.disabled}
            onOKActionDescription={button.label}
            onGamepadFocus={() => setFocused(button.key)}
            onGamepadBlur={() => setFocused((current) => (current === button.key ? null : current))}
            onClick={() =>
              button.key === "moonlight" ? controller.openMoonlight() : controller.openHostApp(button.key)
            }
          >
            {LAUNCH_ICONS[button.key]}
          </DialogButton>
        ))}
      </Focusable>
      <div style={{ fontSize: 12, opacity: 0.7, marginTop: 6 }}>
        <span style={{ fontWeight: 600 }}>{caption.label}</span> · {caption.description}
      </div>
    </div>
  );
}

/**
 * The layout row (Decision 67): *Layout* opens the controller configurator
 * for the Moonlight shortcut (hidden when the client cannot), *Make
 * default* adopts that shortcut's layout as the default for every
 * streaming entry through the Titles row's flow (hidden under the `picker`
 * strategy, which has no default). Desktop and Steam Big Picture keep their
 * *Choose layout* on the Titles page. Not held back while a game runs.
 */
function ClientLayoutRow({ state, canChooseLayout }: { state: AppState; canChooseLayout: boolean }) {
  const canAdopt = layoutStrategy(state.settings) === "copy";
  if (!canChooseLayout && !canAdopt) return null;
  const appid = state.clientAppid;
  return (
    <PanelSectionRow>
      <div style={{ padding: "10px 0" }}>
        <Focusable flow-children="horizontal" style={{ display: "flex", gap: 8 }}>
          {canChooseLayout ? (
            <DialogButton
              style={LAYOUT_BUTTON}
              disabled={appid === null}
              onClick={() => {
                Navigation.CloseSideMenus();
                void controller.chooseClientLayout();
              }}
            >
              <FaGamepad size={18} />
              Layout
            </DialogButton>
          ) : null}
          {canAdopt ? (
            <DialogButton
              style={LAYOUT_BUTTON}
              disabled={appid === null}
              onClick={() => {
                if (appid !== null) void adoptAsDefault(appid, "Moonlight", "panel");
              }}
            >
              <FaStar size={15} />
              Make default
            </DialogButton>
          ) : null}
        </Focusable>
        <div style={{ fontSize: 12, opacity: 0.7, marginTop: 6 }}>{clientLayoutCaption(state)}</div>
      </div>
    </PanelSectionRow>
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

const TONE_COLORS: Record<HostTone, string> = {
  ok: "#5ba32b",
  bad: "#d94b4b",
  unknown: "#8b98a8",
};

/** The status row's text colour: Pill's `bad` tone. */
const ERROR_TEXT = "#ff9a9a";
/** The client's own `Field` separator, for a row that is not a Field. */
const SEPARATOR = "1px solid rgba(255,255,255,0.1)";

/**
 * The host (the user's decision of 2026-09-27). With more than one host:
 * the *Host* row, a circle and the number of apps under its label and the
 * switcher taking the rest of the line. With one host there is nothing to
 * switch to and the row is not drawn. Either way an error's status text
 * gets a row of its own, under the switcher and above the divider, and
 * *Check* / *Wake* follow while the host is not known reachable.
 */
function HostRow({ state }: { state: AppState }) {
  const hosts = state.hosts;
  const view = hostRowView(state);
  if (!hosts?.active || !view) {
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
  const active = hosts.active;
  const busy = !actionsReady(state) || !!state.run?.running;
  return (
    <>
      {view.switcher ? (
        <PanelSectionRow>
          {/* A Field's control column stops at half the row unless the
              Field lets it grow: "max" leaves the label column as wide as
              its text and gives the switcher the rest, so a host's name
              fits. DropdownItem has no such prop, hence Field + Dropdown. */}
          <Field
            label="Host"
            description={
              <span style={{ whiteSpace: "nowrap" }}>
                {dot(TONE_COLORS[view.tone])}
                {view.text}
              </span>
            }
            childrenContainerWidth="max"
            bottomSeparator={view.error ? "none" : "standard"}
          >
            <Dropdown
              menuLabel="Host"
              rgOptions={hostOptions(hosts).map((name) => ({ data: name, label: name }))}
              selectedOption={active}
              disabled={busy}
              onChange={(option) => {
                const name = option.data as string;
                if (name !== active) confirmSwitch(controller, name);
              }}
            />
          </Field>
        </PanelSectionRow>
      ) : null}
      {view.error ? (
        <PanelSectionRow>
          <div
            style={{
              padding: view.switcher ? "0 0 10px" : "10px 0",
              fontSize: 12,
              lineHeight: "16px",
              color: ERROR_TEXT,
              borderBottom: SEPARATOR,
            }}
          >
            {view.error}
          </div>
        </PanelSectionRow>
      ) : null}
      {!state.reach?.reachable ? (
        <PanelSectionRow>
          <Focusable style={{ display: "flex", gap: 8 }}>
            {/* *Check* is the one way the panel asks the host (Decision 66);
                the `moonlight list` behind it wakes the PC by itself, which
                is why it is never pressed for the user. */}
            <DialogButton
              style={{ minWidth: 0, flex: 1 }}
              disabled={state.reachLoading || busy}
              onClick={() => void controller.checkHost(true)}
            >
              Check
            </DialogButton>
            {/* Wake-on-LAN (spec 3.18): only when Moonlight's own host list
                knows the host's MAC; a dead button would not say why. */}
            {wakeInfoOf(hosts, active) ? (
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
        <ButtonItem layout="below" disabled={!ready || !state.hosts?.active} onClick={() => void controller.sync()}>
          Sync now
        </ButtonItem>
      </PanelSectionRow>
      <PanelSectionRow>
        <LaunchRow state={state} />
      </PanelSectionRow>
      <ClientLayoutRow state={state} canChooseLayout={canChooseLayout} />
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
