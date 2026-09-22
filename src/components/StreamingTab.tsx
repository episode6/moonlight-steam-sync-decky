/**
 * The *Streaming* tab's content (spec 3.17): the client's own library grid,
 * borrowed from a built-in tab (`template`, the element that carries a
 * `collection` prop) and cloned with a synthetic collection of this
 * device's streamable titles, read live from the store. The grid is the
 * client's, its surface unmeasured, so it renders inside the client's
 * `ErrorBoundary`: should it throw on this client, the tab shows a line of
 * text and the library around it is untouched.
 */

import { ErrorBoundary } from "@decky/ui";
import { cloneElement, type ReactElement } from "react";

import { controller } from "../instance";
import { streamingMembers } from "../lib/library";
import { loadedOverviews } from "../lib/steam";
import { syntheticCollection, type ElementLike } from "../lib/tabs";
import { useStore } from "./useStore";

const EMPTY_STYLE = { padding: "24px 32px", opacity: 0.7 } as const;

export function streamingEmptyText(active: string | null | undefined): string {
  return active ? `Nothing to stream from ${active} yet. Sync from the Moonlight Sync panel.` : "No host yet. Add one from the Moonlight Sync panel.";
}

export function StreamingTab({ template }: { template: ElementLike }) {
  const state = useStore(controller.store);
  const members = state.entries ? streamingMembers(state.entries) : [];
  const overviews = loadedOverviews(members);
  if (!overviews.length) return <div style={EMPTY_STYLE}>{streamingEmptyText(state.hosts?.active)}</div>;
  const collection = syntheticCollection(overviews);
  return <ErrorBoundary>{cloneElement(template as ReactElement<{ collection: unknown }>, { collection })}</ErrorBoundary>;
}
