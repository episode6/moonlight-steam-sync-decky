import { addEventListener, definePlugin, removeEventListener, routerHook } from "@decky/api";
import { DialogButton, Navigation, Router, staticClasses } from "@decky/ui";
import { FaCog, FaListUl, FaMoon } from "react-icons/fa";

import { QuickAccess } from "./components/QuickAccess";
import { SettingsPage } from "./components/SettingsPage";
import { SETTINGS_ROUTE, TITLES_ROUTE, controller } from "./instance";
import type { SyncDonePayload, SyncEventPayload } from "./lib/cli";
import { watchRunningApps } from "./lib/steam";

function runningAppids(): number[] {
  try {
    const running = Router.MainRunningApp;
    return running ? [Number(running.appid)] : [];
  } catch {
    return [];
  }
}

function open(route: string) {
  Navigation.Navigate(route);
  Navigation.CloseSideMenus();
}

const HEADER_BUTTON = { height: 28, width: 40, minWidth: 0, padding: "10px 12px" };

/** The panel's header: the Titles page (spec 3.8, "opened from the panel's header") and Settings. */
function TitleView() {
  return (
    <div className={staticClasses.Title} style={{ display: "flex", alignItems: "center", width: "100%", gap: 6 }}>
      <div style={{ flexGrow: 1 }}>Moonlight Sync</div>
      <DialogButton style={HEADER_BUTTON} onClick={() => open(TITLES_ROUTE)} onOKActionDescription="Titles">
        <FaListUl style={{ marginTop: -4 }} />
      </DialogButton>
      <DialogButton style={HEADER_BUTTON} onClick={() => open(SETTINGS_ROUTE)} onOKActionDescription="Settings">
        <FaCog style={{ marginTop: -4 }} />
      </DialogButton>
    </div>
  );
}

export default definePlugin(() => {
  routerHook.addRoute(SETTINGS_ROUTE, SettingsPage);

  const onEvent = addEventListener<[SyncEventPayload]>("sync_event", (payload) =>
    controller.onSyncEvent(payload),
  );
  const onDone = addEventListener<[SyncDonePayload]>("sync_done", (payload) => {
    void controller.onSyncDone(payload);
  });

  let unwatch: () => void = () => undefined;
  try {
    unwatch = watchRunningApps(runningAppids(), (running) => controller.setInGame(running));
  } catch (error) {
    console.warn("Moonlight Sync: could not watch running apps", error);
  }

  // The load order runs here, not when the panel opens (spec 3.8).
  void controller.load();

  return {
    name: "Moonlight Sync",
    titleView: <TitleView />,
    content: <QuickAccess />,
    icon: <FaMoon />,
    onDismount() {
      removeEventListener("sync_event", onEvent);
      removeEventListener("sync_done", onDone);
      unwatch();
      routerHook.removeRoute(SETTINGS_ROUTE);
    },
  };
});
