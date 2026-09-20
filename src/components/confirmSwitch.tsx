import { ConfirmModal, showModal } from "@decky/ui";

import type { Controller } from "../lib/controller";

/**
 * The one-line switch confirm (spec 3.8 / 3.12): "Switch to OFFICE-PC?
 * MY-GAMING-PC's 312 tiles are parked, not removed", then `set_host` and a
 * sync with the usual restart flow.
 */
export function confirmSwitch(controller: Controller, target: string): void {
  const { hosts, counters } = controller.state;
  const active = hosts?.active;
  const tiles = counters ? counters.stream + counters.shortcuts : null;
  const description = active
    ? `${active}'s ${tiles ?? "current"} ${tiles === 1 ? "tile is" : "tiles are"} parked, not removed. Switching syncs now and restarts Steam once.`
    : "Switching syncs now and restarts Steam once.";
  showModal(
    <ConfirmModal
      strTitle={`Switch to ${target}?`}
      strDescription={description}
      strOKButtonText="Switch and sync"
      strCancelButtonText="Cancel"
      onOK={() => {
        void controller.switchHost(target);
      }}
    />,
  );
}
