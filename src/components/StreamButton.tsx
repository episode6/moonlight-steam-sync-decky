import { DialogButton, Focusable } from "@decky/ui";
import { useState, type CSSProperties } from "react";

import { controller } from "../instance";
import { defaultLayoutOf, layoutLine } from "../lib/layouts";
import { layoutEntryFor } from "../lib/state";
import { useStore } from "./useStore";

/** The mockup's purple Stream button (screen 3). */
const BUTTON: CSSProperties = {
  width: "auto",
  minWidth: 0,
  padding: "10px 24px",
  fontWeight: 600,
  background: "linear-gradient(90deg, #6d3df0, #8a5cff)",
  boxShadow: "0 0 0 2px rgba(138,92,255,0.35)",
};

interface Props {
  /** The owned game's Steam appid (the page being shown). */
  appid: number;
  name?: string;
}

/**
 * The Stream button on an owned game's library page (spec 3.9, mockup
 * screen 3), injected by `routes/libraryApp.tsx`. Renders nothing unless the
 * stream map has this appid (a hidden shortcut exists for it and the active
 * host publishes it). A press puts the default controller layout on the
 * hidden shortcut when one is set (spec 3.16), then runs the shortcut
 * through Steam, whether or not a game is running (Moonlight's own UI
 * handles a stream that is already going). The layout line shows only
 * while a default is set.
 */
export function StreamButton({ appid, name }: Props) {
  const state = useStore(controller.store);
  const [busy, setBusy] = useState(false);
  const shortcut = state.streamMap.get(appid);
  if (shortcut === undefined) return null;

  const host = state.hosts?.active ?? "the host";
  const title = name ?? String(appid);
  const layout = defaultLayoutOf(state.settings)
    ? `Controller layout: ${busy ? "applying…" : layoutLine(layoutEntryFor(state, shortcut))}`
    : "";
  const press = async () => {
    setBusy(true);
    try {
      await controller.streamPress(appid);
    } finally {
      setBusy(false);
    }
  };

  return (
    <Focusable
      flow-children="horizontal"
      style={{ display: "flex", alignItems: "center", gap: 14, padding: "6px 2.8vw 8px" }}
    >
      <DialogButton style={BUTTON} disabled={busy} onClick={() => void press()} onOKActionDescription="Stream">
        Stream
      </DialogButton>
      <div style={{ fontSize: 12, opacity: 0.75, lineHeight: 1.4 }}>
        <div>
          Streams “{title}” from {host}
          {layout ? ` · ${layout}` : ""}
        </div>
        <div style={{ opacity: 0.7 }}>Stream button added by Moonlight Sync</div>
      </div>
    </Focusable>
  );
}
