import { SidebarNavigation } from "@decky/ui";
import { useEffect } from "react";

import { SETTINGS_ROUTE, TITLES_ROUTE, controller } from "../instance";
import { AboutPage } from "./AboutPage";
import { AdvancedPage } from "./AdvancedPage";
import { ArtworkPage } from "./ArtworkPage";
import { HostPage } from "./HostPage";
import { TitlesPage } from "./TitlesPage";

/**
 * The settings route `/moonlight-sync` (spec 3.8): Host, Titles, Artwork,
 * Advanced, About. Pages that only touch plugin files work without a CLI;
 * the rest say why they are disabled.
 */
export function SettingsPage() {
  useEffect(() => {
    void controller.load();
  }, []);
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
