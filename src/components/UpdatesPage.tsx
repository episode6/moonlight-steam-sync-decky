import { ButtonItem, DialogButton, DropdownItem, Field, Focusable, ToggleField } from "@decky/ui";

import { controller } from "../instance";
import { errorText } from "../lib/cli";
import {
  installable,
  installButtonText,
  installedText,
  latestText,
  offerOf,
  updateCheckEnabled,
  versionLabel,
} from "../lib/updates";
import { useStore } from "./useStore";

/** About's log box, for the release notes. */
const NOTES_BOX = {
  fontFamily: "monospace",
  fontSize: 11,
  whiteSpace: "pre-wrap",
  wordBreak: "break-word",
  maxHeight: 320,
  overflowY: "auto",
  background: "rgba(0,0,0,0.3)",
  padding: 8,
  borderRadius: 4,
} as const;

/**
 * Settings → Updates (update spec 3.7): the installed version, what the
 * last check found, the update's button and notes, the automatic check's
 * toggle and *Install another version*. There is no confirm of the
 * plugin's own: Decky's dialog is the confirmation, and its text names the
 * action and the version (Decision U3). The route leaves this page out
 * entirely while the plugin is off (update spec 3.2).
 */
export function UpdatesPage() {
  const state = useStore(controller.store);
  const info = state.cliVersion;
  const installed = info?.plugin_version ?? null;
  const installedRow = <Field label="Installed" description={installedText(installed)} focusable={false} />;

  if (!controller.updatesSupported()) {
    return (
      <div>
        {installedRow}
        <Field
          label="Updates"
          description={errorText({ ok: false, error: "update-unsupported", message: "" })}
          focusable={false}
        />
      </div>
    );
  }

  const update = state.update ?? { releases: null, checkedAt: null, error: null };
  const phase = state.updatePhase;
  const idle = phase === "idle";
  const offer = offerOf(installed, update.releases);
  const others = installable(installed, update.releases);

  return (
    <div>
      {installedRow}
      <Field label="Latest" description={latestText(update, phase, offer)}>
        <DialogButton
          style={{ minWidth: 0, width: "auto", padding: "6px 14px" }}
          disabled={!idle}
          onClick={() => void controller.checkUpdates(true)}
        >
          Check now
        </DialogButton>
      </Field>
      {offer ? (
        <ButtonItem layout="below" disabled={!idle} onClick={() => void controller.installUpdate(offer.tag)}>
          {installButtonText(offer, phase)}
        </ButtonItem>
      ) : null}
      {offer?.notes ? (
        <div style={{ padding: "10px 0" }}>
          <div style={{ fontWeight: 600, marginBottom: 6 }}>What&apos;s new in {offer.label}</div>
          <Focusable style={NOTES_BOX}>{offer.notes}</Focusable>
        </div>
      ) : null}
      <ToggleField
        label="Check for updates automatically"
        description="When the plugin loads, asks GitHub for the list of releases. Nothing is installed without asking."
        checked={updateCheckEnabled(state.settings)}
        disabled={!state.settings}
        onChange={(checked) => void controller.setUpdateCheck(checked)}
      />
      {others.length ? (
        <DropdownItem
          label="Install another version"
          strDefaultLabel="Choose a version…"
          rgOptions={others.map((other) => ({ data: other.tag, label: versionLabel(other) }))}
          selectedOption={null}
          disabled={!idle}
          onChange={(option) => void controller.installUpdate(option.data as string)}
        />
      ) : null}
    </div>
  );
}
