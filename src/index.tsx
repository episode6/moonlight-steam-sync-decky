import { addEventListener, definePlugin, removeEventListener, routerHook } from "@decky/api";
import { DialogButton, Navigation, Router, staticClasses } from "@decky/ui";
import { FaCog, FaListUl, FaMoon } from "react-icons/fa";

import { QuickAccess } from "./components/QuickAccess";
import { SettingsPage } from "./components/SettingsPage";
import { SETTINGS_ROUTE, TITLES_ROUTE, controller } from "./instance";
import type { SgdbKeyDonePayload, SgdbKeyEventPayload, SyncDonePayload, SyncEventPayload } from "./lib/cli";
import { watchControllers, watchRunningApps } from "./lib/steam";
import { patchLibraryApp } from "./routes/libraryApp";
import { patchLibraryContextMenu } from "./routes/libraryContextMenu";
import { patchLibraryTabs } from "./routes/libraryTabs";

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
  // The SteamGridDB key fetch from the Game Mode browser (spec 3.20.4).
  const onKeyEvent = addEventListener<[SgdbKeyEventPayload]>("sgdb_key_event", (payload) =>
    controller.onSgdbKeyEvent(payload),
  );
  const onKeyDone = addEventListener<[SgdbKeyDonePayload]>("sgdb_key_done", (payload) => {
    void controller.onSgdbKeyDone(payload);
  });

  let unwatch: () => void = () => undefined;
  try {
    unwatch = watchRunningApps(runningAppids(), (running) => controller.setInGame(running));
  } catch (error) {
    console.warn("Moonlight Sync: could not watch running apps", error);
  }

  // The controller list, for the Deck controller's index (spec 3.10).
  let unwatchControllers: () => void = () => undefined;
  try {
    unwatchControllers = watchControllers();
  } catch (error) {
    console.warn("Moonlight Sync: could not watch controllers", error);
  }

  // The Stream button on owned games' library pages (spec 3.9).
  let unpatchLibrary: () => void = () => undefined;
  try {
    unpatchLibrary = patchLibraryApp();
  } catch (error) {
    console.warn("Moonlight Sync: could not patch the library page", error);
  }

  // The Streaming tab in the library's tab bar (spec 3.17).
  let unpatchTabs: () => void = () => undefined;
  try {
    unpatchTabs = patchLibraryTabs();
  } catch (error) {
    console.warn("Moonlight Sync: could not patch the library tabs", error);
  }

  // *Use as Moonlight Sync default layout* in the library gear menu (spec 3.16.5).
  let unpatchMenu: () => void = () => undefined;
  try {
    unpatchMenu = patchLibraryContextMenu();
  } catch (error) {
    console.warn("Moonlight Sync: could not patch the library context menu", error);
  }

  // The load order runs here, not when the panel opens (spec 3.8); it starts
  // the post-restart layout walk when one is pending (spec 3.10).
  void controller.load();

  return {
    name: "Moonlight Sync",
    titleView: <TitleView />,
    content: <QuickAccess />,
    icon: <FaMoon />,
    onDismount() {
      removeEventListener("sync_event", onEvent);
      removeEventListener("sync_done", onDone);
      removeEventListener("sgdb_key_event", onKeyEvent);
      removeEventListener("sgdb_key_done", onKeyDone);
      unwatch();
      unwatchControllers();
      unpatchLibrary();
      unpatchTabs();
      unpatchMenu();
      routerHook.removeRoute(SETTINGS_ROUTE);
    },
  };
});
