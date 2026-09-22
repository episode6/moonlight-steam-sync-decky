/**
 * The *Streaming* tab's content (spec 3.17): the client's own library grid,
 * borrowed from a built-in tab (`template`, the element that carries a
 * `collection` prop) and cloned with a synthetic collection of this
 * device's streamable titles, read live from the store. The grid is the
 * client's, its surface unmeasured, so it renders inside an error
 * boundary: should it throw on this client, the tab shows the error and
 * the library around it is untouched.
 *
 * Every state the plugin draws itself (nothing to show, the grid threw)
 * is a `Focusable` that takes focus when it has no focusable children:
 * under gamepad navigation a panel with nothing to focus is passed over,
 * and a tab whose content cannot take focus is a tab the user cannot
 * reach (reported on a device 2026-09-22: the tab was in the bar and was
 * skipped). The grid itself is left as the client renders it.
 */

import { Focusable } from "@decky/ui";
import { cloneElement, Component, useMemo, type ErrorInfo, type ReactElement, type ReactNode } from "react";

import { controller } from "../instance";
import { streamingMembers } from "../lib/library";
import { loadedOverviews } from "../lib/steam";
import { syntheticCollection, type ElementLike } from "../lib/tabs";
import { useStore } from "./useStore";

const TEXT_STYLE = { padding: "24px 32px", opacity: 0.7 } as const;

/**
 * Not in `@decky/ui`'s typings, but the client's `Focusable` honours it: a
 * panel with no focusable child takes focus itself. Unmeasured, so the
 * panel also carries a no-op `onActivate`, which is what makes a container
 * focusable on every client `@decky/ui` code relies on; either suffices.
 */
const FOCUSABLE_IF_EMPTY = { focusableIfNoChildren: true } as Record<string, unknown>;

function noop(): void {}

export function streamingEmptyText(active: string | null | undefined): string {
  return active ? `Nothing to stream from ${active} yet. Sync from the Moonlight Sync panel.` : "No host yet. Add one from the Moonlight Sync panel.";
}

export function streamingErrorText(error: unknown): string {
  const message = error instanceof Error ? error.message : String(error);
  return `Moonlight Sync could not draw this tab on this client: ${message}`;
}

/** A line of the plugin's own text, focusable so the tab can be reached and read. */
function TextPanel({ children }: { children: ReactNode }) {
  return (
    <Focusable style={TEXT_STYLE} onActivate={noop} {...FOCUSABLE_IF_EMPTY}>
      {children}
    </Focusable>
  );
}

interface BoundaryState {
  error: unknown;
  failed: boolean;
}

/**
 * Catches a throw from the client's grid: logs it (the device report wants
 * the error, DEVICE-CHECKLIST §10) and shows it in a focusable line, so
 * the tab still opens. The client's own `ErrorBoundary` draws a box with
 * nothing to focus, which would keep the tab unreachable. It never resets
 * itself: `StreamingTab` keys it on the member set, so a new collection
 * remounts it and the grid is tried again.
 */
class TabErrorBoundary extends Component<{ children: ReactNode }, BoundaryState> {
  state: BoundaryState = { error: null, failed: false };

  static getDerivedStateFromError(error: unknown): BoundaryState {
    return { error, failed: true };
  }

  componentDidCatch(error: unknown, info: ErrorInfo): void {
    console.warn("Moonlight Sync: the Streaming tab's grid threw", error, info.componentStack);
  }

  render(): ReactNode {
    if (this.state.failed) return <TextPanel>{streamingErrorText(this.state.error)}</TextPanel>;
    return this.props.children;
  }
}

export function StreamingTab({ template }: { template: ElementLike }) {
  const state = useStore(controller.store);
  const members = state.entries ? streamingMembers(state.entries) : [];
  // One collection object per member set, not per render: the store changes
  // on every progress line, and a fresh object each time could re-sort the
  // grid or reset its scroll.
  const key = members.join(",");
  const collection = useMemo(() => {
    const overviews = loadedOverviews(members);
    return overviews.length ? syntheticCollection(overviews) : null;
    // eslint-disable-next-line react-hooks/exhaustive-deps -- `key` stands for `members`
  }, [key]);
  if (!collection) return <TextPanel>{streamingEmptyText(state.hosts?.active)}</TextPanel>;
  return (
    <TabErrorBoundary key={key}>
      {cloneElement(template as ReactElement<{ collection: unknown }>, { collection })}
    </TabErrorBoundary>
  );
}
