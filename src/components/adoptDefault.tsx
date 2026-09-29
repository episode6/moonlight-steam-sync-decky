import { ConfirmModal, showModal } from "@decky/ui";
import { toaster } from "@decky/api";

import { controller } from "../instance";
import type { LayoutInspection } from "../lib/controller";

/**
 * The toast for a layout *Make default* cannot adopt (spec 3.16.5), the
 * texts exactly; "no layout chosen yet" points at the *Layout* button
 * beside it (Decision 67).
 */
export function inspectionToast(name: string, reason: Exclude<LayoutInspection, { ok: true }>["reason"]): string {
  switch (reason) {
    case "no-controller":
      return "Connect a controller first";
    case "unselected":
      return `“${name}” has no layout chosen yet. Use Layout first.`;
    case "not-shareable":
      return (
        `This layout was edited in place and only exists for “${name}”. ` +
        "In Steam's layout screen choose Export, select the exported copy, then try again."
      );
  }
}

/**
 * *Make default* while a layout walk is going (spec 3.16.5):
 * the change would wait for the walk, up to its 90 s readiness poll, with
 * nothing to show for it, so it is refused with this toast, as Advanced's
 * *Clear* is disabled meanwhile.
 */
export const WALK_RUNNING_TOAST = "A layout walk is still running. Try again when it finishes.";

/**
 * The panel's *Make default* (spec 3.16.5, Decisions 43, 67 and 74): read
 * the selection `appid` (the client entry) has for the controller in use,
 * refuse what cannot be shared, and confirm before every entry gets it.
 * The one way to adopt a default: the Titles row and the library gear menu
 * no longer offer it (Decision 74).
 */
export async function adoptAsDefault(appid: number, name: string): Promise<void> {
  if (controller.state.walking) {
    toaster.toast({ title: "Moonlight Sync", body: WALK_RUNNING_TOAST });
    return;
  }
  const found = await controller.inspectLayout(appid);
  if (!found.ok) {
    toaster.toast({ title: "Moonlight Sync", body: inspectionToast(name, found.reason) });
    return;
  }
  showModal(
    <ConfirmModal
      strTitle={`Use “${found.title}” as the default layout?`}
      strDescription="Every streaming title without a layout of its own gets it, now and after each sync. Titles whose layout you chose yourself are left alone."
      strOKButtonText="Use as default"
      strCancelButtonText="Cancel"
      onOK={() => {
        void controller.setDefaultLayout(found.url, found.title);
      }}
    />,
  );
}
