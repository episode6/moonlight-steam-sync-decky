import { ConfirmModal, showModal } from "@decky/ui";
import { toaster } from "@decky/api";

import { controller } from "../instance";
import type { LayoutInspection } from "../lib/controller";

/**
 * Where *Use as the default layout* was pressed, for the "no layout chosen
 * yet" hint: a Titles row points at *Choose layout*, the library gear menu
 * at the same menu's *Controller settings*, the panel's *Make default* at
 * the *Layout* button beside it (Decision 67).
 */
export type AdoptFrom = "titles" | "gear-menu" | "panel";

const UNSELECTED_HINT: Record<AdoptFrom, string> = {
  titles: "Use Choose layout first.",
  "gear-menu": "Pick one under Controller settings first.",
  panel: "Use Layout first.",
};

/** The toast for a title *Use as the default layout* cannot adopt from (spec 3.16.5), the texts exactly. */
export function inspectionToast(
  name: string,
  reason: Exclude<LayoutInspection, { ok: true }>["reason"],
  from: AdoptFrom = "titles",
): string {
  switch (reason) {
    case "no-controller":
      return "Connect a controller first";
    case "unselected":
      return `“${name}” has no layout chosen yet. ${UNSELECTED_HINT[from]}`;
    case "not-shareable":
      return (
        `This layout was edited in place and only exists for “${name}”. ` +
        "In Steam's layout screen choose Export, select the exported copy, then try again."
      );
  }
}

/**
 * *Use as the default layout* while a layout walk is going (spec 3.16.5):
 * the change would wait for the walk, up to its 90 s readiness poll, with
 * nothing to show for it, so it is refused with this toast, as Advanced's
 * *Clear* is disabled meanwhile.
 */
export const WALK_RUNNING_TOAST = "A layout walk is still running. Try again when it finishes.";

/**
 * *Use as the default layout* (spec 3.16.5, Decision 43): read the
 * selection `appid` has for the controller in use, refuse what cannot be
 * shared, and confirm before every entry gets it. Shared by the Titles
 * row's *Layout* menu (`appid` is the entry), the library gear menu
 * (Decision 56: `appid` is the game itself, or the entry on its own page)
 * and the panel's *Make default* (Decision 67: `appid` is the client).
 */
export async function adoptAsDefault(appid: number, name: string, from: AdoptFrom): Promise<void> {
  if (controller.state.walking) {
    toaster.toast({ title: "Moonlight Sync", body: WALK_RUNNING_TOAST });
    return;
  }
  const found = await controller.inspectLayout(appid);
  if (!found.ok) {
    toaster.toast({ title: "Moonlight Sync", body: inspectionToast(name, found.reason, from) });
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
