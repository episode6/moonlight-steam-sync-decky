import { ToggleField } from "@decky/ui";

import { controller } from "../instance";
import { DISABLED_TEXT, pluginEnabled } from "../lib/library";
import type { AppState } from "../lib/state";

/**
 * The plugin's on/off toggle (spec 3.19), *Enable Sync*, at the top of the
 * Quick Access panel and, while off, the one control the settings route
 * shows. Off hides every Moonlight shortcut, keeps the Stream buttons, the
 * Streaming tab and the gear-menu item out of the library, refuses runs and
 * locks the other settings: for a Deck travelling away from its host. It is
 * disabled while a run is going (the run owns the library until it ends)
 * and until the settings have loaded.
 *
 * The panel's toggle has no description (Decision 67); the settings route,
 * where it is the only thing on the page while off, says what off means.
 */
export function EnabledToggle({ state, explainOff = false }: { state: AppState; explainOff?: boolean }) {
  const enabled = pluginEnabled(state.settings);
  return (
    <ToggleField
      label="Enable Sync"
      description={explainOff && !enabled ? DISABLED_TEXT : undefined}
      checked={enabled}
      disabled={!state.settings || !!state.run?.running}
      onChange={(checked) => void controller.setEnabled(checked)}
    />
  );
}
