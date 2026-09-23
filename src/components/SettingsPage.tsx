import { PanelSection, PanelSectionRow, SidebarNavigation } from "@decky/ui";
import { useEffect } from "react";

import { SETTINGS_ROUTE, TITLES_ROUTE, controller } from "../instance";
import { pluginEnabled } from "../lib/library";
import { AboutPage } from "./AboutPage";
import { AdvancedPage } from "./AdvancedPage";
import { ArtworkPage } from "./ArtworkPage";
import { EnabledToggle } from "./EnabledToggle";
import { HostPage } from "./HostPage";
import { TitlesPage } from "./TitlesPage";
import { useStore } from "./useStore";

/**
 * The settings route `/moonlight-sync` (spec 3.8): Host, Titles, Artwork,
 * Advanced, About. Pages that only touch plugin files work without a CLI;
 * the rest say why they are disabled. While the plugin is off (spec 3.19)
 * the route shows the on/off toggle alone: no page, so no setting can
 * change until it is on again.
 */
export function SettingsPage() {
  const state = useStore(controller.store);
  useEffect(() => {
    void controller.load();
  }, []);
  if (state.loaded && !pluginEnabled(state.settings)) {
    return (
      <div style={{ marginTop: 40, padding: "0 2.8vw" }}>
        <PanelSection title="Moonlight Sync">
          <PanelSectionRow>
            <EnabledToggle state={state} />
          </PanelSectionRow>
        </PanelSection>
      </div>
    );
  }
  return (
    <div style={{ marginTop: 40, height: "calc(100% - 40px)" }}>
      <SidebarNavigation
        title="Moonlight Sync"
        showTitle
        pages={[
          { title: "Host", content: <HostPage />, route: `${SETTINGS_ROUTE}/host` },
          { title: "Titles", content: <TitlesPage />, route: TITLES_ROUTE },
          { title: "Artwork", content: <ArtworkPage />, route: `${SETTINGS_ROUTE}/artwork` },
          { title: "Advanced", content: <AdvancedPage />, route: `${SETTINGS_ROUTE}/advanced` },
          { title: "About", content: <AboutPage />, route: `${SETTINGS_ROUTE}/about` },
        ]}
      />
    </div>
  );
}
