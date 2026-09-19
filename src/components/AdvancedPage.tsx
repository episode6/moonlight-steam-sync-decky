import { ButtonItem, ConfirmModal, SliderField, ToggleField, showModal } from "@decky/ui";

import { controller } from "../instance";
import { actionsReady } from "../lib/state";
import { useStore } from "./useStore";

/**
 * Settings → Advanced (spec 3.8): the layout-copy toggle (read by PR-7), the
 * restart countdown, and *Remove everything this plugin created*.
 */
export function AdvancedPage() {
  const state = useStore(controller.store);
  const settings = state.settings;
  const entries = state.entries?.length ?? null;

  const removeAll = () =>
    showModal(
      <ConfirmModal
        strTitle="Remove everything this plugin created?"
        strDescription={`Removes every shortcut, Stream button and image Moonlight Sync created (${entries ?? "all"} entries). Pins and ignored titles are kept. Steam restarts once.`}
        strOKButtonText="Remove everything"
        strCancelButtonText="Cancel"
        bDestructiveWarning
        onOK={() => {
          void controller.run("remove");
        }}
      />,
    );

  return (
    <div>
      <ToggleField
        label="Copy controller layouts from the Steam game"
        description="When a hidden shortcut has no layout of its own, give it the one chosen for the real game"
        checked={!!settings?.copy_layouts}
        disabled={!settings}
        onChange={(checked) => void controller.setSettings({ copy_layouts: checked })}
      />
      <SliderField
        label="Restart countdown"
        description="Seconds before Steam restarts after a sync; 0 asks without counting down"
        value={settings?.restart_countdown_s ?? 5}
        min={0}
        max={30}
        step={1}
        showValue
        valueSuffix=" s"
        disabled={!settings}
        onChange={(value) => void controller.setSettings({ restart_countdown_s: value })}
      />
      <ButtonItem
        layout="below"
        label="Remove everything this plugin created"
        description="Shortcuts, Stream buttons and their images; Steam restarts once"
        disabled={!actionsReady(state) || !!state.run?.running}
        onClick={removeAll}
      >
        Remove everything
      </ButtonItem>
    </div>
  );
}
