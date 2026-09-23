import { ToggleField } from "@decky/ui";

import { controller } from "../instance";
import { DISABLED_TEXT, pluginEnabled } from "../lib/library";
import type { AppState } from "../lib/state";

/**
 * The plugin's on/off toggle (spec 3.19), at the top of the Quick Access
 * panel and, while off, the one control the settings route shows. Off
 * hides every Moonlight shortcut, keeps the Stream buttons, the Streaming
 * tab and the gear-menu item out of the library, refuses runs and locks
 * the other settings: for a Deck travelling away from its host. It is
 * disabled while a run is going (the run owns the library until it ends)
 * and until the settings have loaded.
 */
export function EnabledToggle({ state }: { state: AppState }) {
  const enabled = pluginEnabled(state.settings);
  return (
    <ToggleField
      label="Moonlight Sync"
      description={
        enabled ? "On. Turn off while travelling: hides every Moonlight shortcut and pauses the plugin" : DISABLED_TEXT
      }
      checked={enabled}
      disabled={!state.settings || !!state.run?.running}
      onChange={(checked) => void controller.setEnabled(checked)}
    />
  );
}
