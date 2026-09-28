/**
 * The plugin's one Controller, wired to the real backend (`@decky/api`'s
 * `callable`), the real Steam client (`lib/steam.ts`), the real modal and
 * toaster, and the updater's three seams: Decky's installer
 * (`lib/decky.ts`), the loader's no-CORS fetch and leaving the settings
 * route. Components import `controller` from here.
 */

import { callable, fetchNoCors, toaster } from "@decky/api";
import { Navigation, showModal } from "@decky/ui";

import { RestartModal } from "./components/RestartModal";
import { makeBackend, type CallableFactory } from "./lib/cli";
import { Controller, type UiPort } from "./lib/controller";
import { deckyInstaller } from "./lib/decky";
import {
  controllerConfiguratorAvailable,
  currentSteamId3,
  leaveExternalWeb,
  libraryPort,
  openExternalWeb,
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
  // The updater (update spec 3.5): Decky's installer through `lib/decky.ts`,
  // the one module that touches Decky's globals (hard rule 12).
  installer: () => deckyInstaller(),
  // The list of releases, and a followed branch's build.json, through the
  // loader (the zip itself is the backend's download; update spec 2.5: the status,
  // the body and the rate-limit headers all come through).
  net: () => ({
    async get(url, headers) {
      const response = await fetchNoCors(url, { method: "GET", headers });
      const header = (name: string) => response.headers.get(name);
      return {
        status: response.status,
        headers: {
          "x-ratelimit-remaining": header("x-ratelimit-remaining"),
          "x-ratelimit-reset": header("x-ratelimit-reset"),
          "retry-after": header("retry-after"),
          etag: header("etag"),
        },
        text: await response.text(),
      };
    },
  }),
  // Off the settings route before Decky unloads the plugin under it (Decision U4).
  leaveSettings: () => {
    try {
      Navigation.NavigateBack();
    } catch (error) {
      console.warn("Moonlight Sync: could not leave the settings page", error);
    }
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
    // The key fetch's browser (spec 3.20.4): `Navigation.NavigateToExternalWeb`,
    // else `steam://openurl/` through `SteamClient.URL.ExecuteSteamURL`.
    navigateToExternalWeb: (url) => openExternalWeb(Navigation, url),
    navigateBack: () => leaveExternalWeb(Navigation),
  },
  ui,
);

/** Where the settings route lives. */
export const SETTINGS_ROUTE = "/moonlight-sync";

/** The Titles page (spec 3.8), a page of the settings route opened from the panel's header. */
export const TITLES_ROUTE = `${SETTINGS_ROUTE}/titles`;

/** The Updates page (update spec 3.7), opened from the panel's *Update to …* row. */
export const UPDATES_ROUTE = `${SETTINGS_ROUTE}/updates`;
