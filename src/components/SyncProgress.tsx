import { ButtonItem, Field, PanelSection, PanelSectionRow, ProgressBarWithInfo } from "@decky/ui";
import type { ComponentProps, FC } from "react";

import type { TitleEvent } from "../lib/cli";
import { progressFraction, type RunProgress } from "../lib/state";

const RUN_TITLES = {
  sync: "Syncing",
  art: "Re-fetching artwork",
  remove: "Removing everything",
} as const;

/** "steam", "sgdb, no logo", "kept" -- what one title's slots came from. */
export function slotSummary(title: TitleEvent): string {
  const values = Object.entries(title.slots);
  const sources = new Set<string>();
  const missing: string[] = [];
  for (const [slot, value] of values) {
    if (value === "steam" || value === "sgdb") sources.add(value);
    if (value === "missing" || value === "cached-miss") missing.push(slot);
  }
  if (!title.match && !values.length) return "skipped";
  const parts: string[] = sources.size ? [[...sources].join(" + ")] : ["kept"];
  if (missing.length) parts.push(`no ${missing.join(", ")}`);
  return parts.join(", ");
}

/**
 * ProgressBarWithInfo is a Field whose child column is `childrenContainerWidth:
 * "fixed"` unless told otherwise, and in the Quick Access menu the client's
 * stylesheet gives that fixed column a 270 px minimum beside an empty label
 * column, wider than the panel's 268 px of content, so the bar and its label
 * ran off the panel's right edge (measured on a Deck 2026-09-23). "max" grows
 * the column across the row instead; the client's component forwards the prop
 * to the Field, @decky/ui's props just do not declare it.
 */
const ProgressBarRow = ProgressBarWithInfo as FC<
  ComponentProps<typeof ProgressBarWithInfo> & { childrenContainerWidth?: "min" | "max" | "fixed" }
>;

function titleMark(title: TitleEvent): string {
  return Object.values(title.slots).some((v) => v === "missing" || v === "cached-miss") ? "–" : "✓";
}

function planLine(run: RunProgress): string {
  const plan = run.plan;
  if (!plan) return "";
  const parts: string[] = [];
  if (plan.to_add) parts.push(`${plan.to_add} to add`);
  if (plan.to_replace) parts.push(`${plan.to_replace} to replace`);
  if (plan.to_park) parts.push(`${plan.to_park} to park`);
  if (plan.to_unpark) parts.push(`${plan.to_unpark} to unpark`);
  const changes = parts.length ? parts.join(", ") : "no shortcut changes";
  return `${plan.published} published: ${changes}.${parts.length ? " Steam restarts once." : ""}`;
}

interface Props {
  run: RunProgress;
  onStop(): void;
}

/** The panel while a run is going (spec 3.8, mockup screen 2). */
export function SyncProgress({ run, onStop }: Props) {
  const fraction = progressFraction(run);
  const operation = run.awaiting
    ? "Waiting for Steam to restart…"
    : run.progress
      ? `Artwork: title ${run.progress.index} of ${run.progress.total}`
      : run.plan
        ? "Planning…"
        : "Listing the host…";
  return (
    <PanelSection title={RUN_TITLES[run.kind]}>
      <PanelSectionRow>
        <ProgressBarRow
          childrenContainerWidth="max"
          nProgress={fraction === null ? undefined : Math.round(fraction * 100)}
          indeterminate={fraction === null || run.awaiting}
          sOperationText={operation}
        />
      </PanelSectionRow>
      {run.titles.length > 0 ? (
        <PanelSectionRow>
          <div style={{ fontFamily: "monospace", fontSize: "11px", lineHeight: 1.5 }}>
            {run.titles.map((title) => (
              <div key={`${title.index}-${title.name}`}>
                {titleMark(title)} {title.name} <span style={{ opacity: 0.6 }}>{slotSummary(title)}</span>
              </div>
            ))}
          </div>
        </PanelSectionRow>
      ) : null}
      <PanelSectionRow>
        <ButtonItem
          layout="below"
          description="Keeps everything done so far; sync again to resume"
          onClick={onStop}
        >
          Stop
        </ButtonItem>
      </PanelSectionRow>
      {run.plan ? (
        <PanelSectionRow>
          <Field description={planLine(run)} focusable={false} />
        </PanelSectionRow>
      ) : null}
    </PanelSection>
  );
}
