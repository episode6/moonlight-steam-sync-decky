import { addEventListener, definePlugin, removeEventListener, routerHook } from "@decky/api";
import { DialogButton, Navigation, Router, staticClasses } from "@decky/ui";
import { FaCog, FaMoon } from "react-icons/fa";

import { QuickAccess } from "./components/QuickAccess";
import { SettingsPage } from "./components/SettingsPage";
import { SETTINGS_ROUTE, controller } from "./instance";
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

function TitleView() {
  return (
    <div className={staticClasses.Title} style={{ display: "flex", alignItems: "center", width: "100%" }}>
      <div style={{ flexGrow: 1 }}>Moonlight Sync</div>
      <DialogButton
        style={{ height: 28, width: 40, minWidth: 0, padding: "10px 12px" }}
        onClick={() => {
          Navigation.Navigate(SETTINGS_ROUTE);
          Navigation.CloseSideMenus();
        }}
      >
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
