/**
 * The plugin's one Controller, wired to the real backend (`@decky/api`'s
 * `callable`), the real Steam client (`lib/steam.ts`) and the real modal and
 * toaster. Components import `controller` from here.
 */

import { callable, toaster } from "@decky/api";
import { showModal } from "@decky/ui";

import { RestartModal } from "./components/RestartModal";
import { makeBackend, type CallableFactory } from "./lib/cli";
import { Controller, type UiPort } from "./lib/controller";
import {
  controllerConfiguratorAvailable,
  currentSteamId3,
  libraryPort,
  overviewLoaded,
  ownedApps,
  runShortcut,
  showControllerConfigurator,
  shutdownSteam,
  steamInput,
} from "./lib/steam";

export const backend = makeBackend(callable as CallableFactory);

const ui: UiPort = {
  showRestart(prompt) {
    const modal = showModal(<RestartModal prompt={prompt} store={controller.store} />);
    return { close: () => modal.Close() };
  },
  toast(title, body) {
    toaster.toast({ title, body });
  },
};

export const controller = new Controller(
  backend,
  {
    ownedApps,
    currentSteamId3,
    runShortcut,
    shutdownSteam,
    input: steamInput,
    overviewLoaded,
    canChooseLayout: controllerConfiguratorAvailable,
    showControllerConfigurator,
    library: libraryPort,
  },
  ui,
);

/** Where the settings route lives. */
export const SETTINGS_ROUTE = "/moonlight-sync";

/** The Titles page (spec 3.8), a page of the settings route opened from the panel's header. */
export const TITLES_ROUTE = `${SETTINGS_ROUTE}/titles`;
