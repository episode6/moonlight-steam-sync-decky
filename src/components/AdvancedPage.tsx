import { ButtonItem, ConfirmModal, SliderField, ToggleField, showModal } from "@decky/ui";

import { controller } from "../instance";
import { layoutStrategy } from "../lib/layouts";
import { hideStreamEnabled, STREAMING_COLLECTION, streamingCollectionEnabled } from "../lib/library";
import { actionsReady } from "../lib/state";
import { useStore } from "./useStore";

/**
 * Settings → Advanced (spec 3.8): the layout-copy toggle (spec 3.10: read on
 * every Stream press and by the post-restart walk), *Hide Stream shortcuts*
 * and the *Streaming* collection (spec 3.15), the restart countdown,
 * and *Remove everything this plugin created*.
 */
export function AdvancedPage() {
  const state = useStore(controller.store);
  const settings = state.settings;
  const entries = state.entries?.length ?? null;
  const picker = layoutStrategy(settings) === "picker";
  const canHide = controller.canHideShortcuts();
  const canCollect = controller.canKeepCollection();
  const copyDescription = picker
    ? "Off for this device: settings.json sets layout_strategy to \"picker\", so layouts are only chosen by hand (Titles → Choose layout)"
    : "When a hidden Stream shortcut has no layout of its own, give it the one chosen for the real game (on each Stream press and after a sync's restart)";

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
        description={copyDescription}
        checked={!!settings?.copy_layouts}
        disabled={!settings || picker}
        onChange={(checked) => void controller.setSettings({ copy_layouts: checked })}
      />
      <ToggleField
        label="Hide Stream shortcuts"
        description={
          canHide
            ? "Keep the shortcuts behind the Stream buttons out of the library. Off: they show under Non-Steam, and a streamed game comes to the front of Home as its shortcut"
            : "This Steam client has no way for a plugin to hide a shortcut"
        }
        checked={canHide && hideStreamEnabled(settings)}
        disabled={!settings || !canHide}
        onChange={(checked) => void controller.setSettings({ hide_stream_shortcuts: checked })}
      />
      <ToggleField
        label="Streaming collection"
        description={
          canCollect
            ? `Keep a "${STREAMING_COLLECTION}" collection of every title the active host can stream, updated after each sync. Off: the collection is deleted`
            : "This Steam client has no collections a plugin can edit"
        }
        checked={canCollect && streamingCollectionEnabled(settings)}
        disabled={!settings || !canCollect}
        onChange={(checked) => void controller.setSettings({ streaming_collection: checked })}
      />
      <SliderField
        label="Restart countdown"
        /* 0-30 s: the CLI gives up waiting for Steam after 60 s, so a longer
         * countdown would race it (spec Decision 30; settings.py validates it). */
        description="Seconds before Steam restarts after a sync (0-30); 0 asks without counting down"
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
