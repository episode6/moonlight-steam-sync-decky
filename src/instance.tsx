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
import { currentSteamId3, ownedApps, runShortcut, shutdownSteam } from "./lib/steam";

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
  { ownedApps, currentSteamId3, runShortcut, shutdownSteam },
  ui,
);

/** Where the settings route lives. */
export const SETTINGS_ROUTE = "/moonlight-sync";
