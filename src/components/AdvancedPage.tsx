import { ButtonItem, ConfirmModal, DialogButton, Field, SliderField, ToggleField, showModal } from "@decky/ui";

import { controller } from "../instance";
import { relativeTime } from "../lib/format";
import { defaultLayoutOf, layoutKindText, layoutStrategy } from "../lib/layouts";
import { hideStreamEnabled, STREAMING_COLLECTION, streamingCollectionEnabled } from "../lib/library";
import { STREAMING_TAB_TITLE } from "../lib/tabs";
import { actionsReady } from "../lib/state";
import { useStore } from "./useStore";

/** The *Default controller layout* field's text (spec 3.16.5). */
export function defaultLayoutDescription(
  settings: Parameters<typeof defaultLayoutOf>[0],
  now: Date = new Date(),
): string {
  if (layoutStrategy(settings) === "picker") {
    return 'Off for this device: settings.json sets layout_strategy to "picker", so layouts are only chosen by hand (Titles → Layout → Choose layout…)';
  }
  const def = defaultLayoutOf(settings);
  if (!def) return "None. Titles → Layout → Use as the default layout, on a title you have set up";
  const set = def.when ? ` · set ${relativeTime(def.when, now)}` : "";
  return `${def.title} · ${layoutKindText(def.url)}${set}`;
}

/** The *Streaming tab* toggle's text: the tab, or the fallback collection while Stream shortcuts are shown. */
export function streamingGroupDescription(hideStream: boolean, canCollect: boolean): string {
  if (hideStream) {
    return `A "${STREAMING_TAB_TITLE}" tab in the library with every title the active host can stream: the game's own page when you own it, the shortcut otherwise. Nothing is written to your collections`;
  }
  if (!canCollect) return "With Stream shortcuts shown, the group is a collection, and this Steam client has none a plugin can edit";
  return `With Stream shortcuts shown, a "${STREAMING_COLLECTION}" collection of this device's Moonlight shortcuts instead of the tab (it syncs through Steam Cloud, so only shortcuts go in it). Off: they leave the collection`;
}

/**
 * Settings → Advanced (spec 3.8): the default controller layout (spec 3.16:
 * shown, and cleared, here; adopted from a title's row on the Titles page),
 * *Hide Stream shortcuts* (spec 3.15) and the *Streaming* tab (spec 3.17,
 * a collection of shortcuts while Stream shortcuts are shown), the restart
 * countdown, and *Remove everything this plugin created*.
 */
export function AdvancedPage() {
  const state = useStore(controller.store);
  const settings = state.settings;
  const entries = state.entries?.length ?? null;
  const picker = layoutStrategy(settings) === "picker";
  const defaultLayout = defaultLayoutOf(settings);
  const canHide = controller.canHideShortcuts();
  const canCollect = controller.canKeepCollection();
  const hideStream = canHide && hideStreamEnabled(settings);
  // the tab needs no client call; the fallback collection does
  const canGroup = hideStream || canCollect;

  const clearDefault = () =>
    showModal(
      <ConfirmModal
        strTitle="Clear the default layout?"
        strDescription="It is taken off every title that still has it. Titles whose layout you chose yourself are left alone."
        strOKButtonText="Clear"
        strCancelButtonText="Cancel"
        onOK={() => {
          void controller.setDefaultLayout(null, null);
        }}
      />,
    );

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
      <Field label="Default controller layout" description={defaultLayoutDescription(settings)} focusable={picker}>
        {picker ? null : (
          <DialogButton
            style={{ minWidth: 0, width: "auto", padding: "6px 14px" }}
            disabled={!settings || !defaultLayout || state.walking}
            onClick={clearDefault}
          >
            Clear
          </DialogButton>
        )}
      </Field>
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
        label="Streaming tab"
        description={streamingGroupDescription(hideStream, canCollect)}
        checked={canGroup && streamingCollectionEnabled(settings)}
        disabled={!settings || !canGroup}
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
