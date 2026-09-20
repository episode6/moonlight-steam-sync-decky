import { ButtonItem, PanelSection, PanelSectionRow, TextField, staticClasses } from "@decky/ui";
import { callable, definePlugin } from "@decky/api";
import { useState } from "react";
import { FaStethoscope } from "react-icons/fa";
import { plog, probeV1, probeV2, probeV3, probeV3Summary, probeV4, probeV5 } from "./probes";

const backendLogPath = callable<[], { ok: boolean; path?: string }>("log_path");

function Content() {
  const [appids, setAppids] = useState("");
  const [shortcut, setShortcut] = useState("");
  const [url, setUrl] = useState("");
  const [indexOverride, setIndexOverride] = useState("");
  const [busy, setBusy] = useState<string | null>(null);
  const [status, setStatus] = useState("idle");

  const run = (name: string, fn: () => Promise<void>) => async () => {
    if (busy) return;
    setBusy(name);
    setStatus(`${name} running…`);
    try {
      await fn();
      setStatus(`${name} finished; see the log`);
    } catch (e) {
      const msg = e instanceof Error ? `${e.name}: ${e.message}` : String(e);
      await plog(`${name} threw at the top level: ${msg}`);
      setStatus(`${name} threw: ${msg}`);
    } finally {
      setBusy(null);
    }
  };

  return (
    <>
      <PanelSection title="Inputs">
        <PanelSectionRow>
          <TextField label="Appids (comma-separated, V1)" value={appids} onChange={(e) => setAppids(e.target.value)} />
        </PanelSectionRow>
        <PanelSectionRow>
          <TextField label="Shortcut appid (V2, V5)" value={shortcut} onChange={(e) => setShortcut(e.target.value)} />
        </PanelSectionRow>
        <PanelSectionRow>
          <TextField label="workshop:// URL (V2)" value={url} onChange={(e) => setUrl(e.target.value)} />
        </PanelSectionRow>
        <PanelSectionRow>
          <TextField
            label="Controller index override (V1, V2; blank = found by type)"
            value={indexOverride}
            onChange={(e) => setIndexOverride(e.target.value)}
          />
        </PanelSectionRow>
      </PanelSection>
      <PanelSection title="Probes">
        <PanelSectionRow>
          <ButtonItem layout="below" disabled={!!busy} onClick={run("V1", () => probeV1(appids, indexOverride))}>
            V1 layouts: config per appid + Deck controller index
          </ButtonItem>
        </PanelSectionRow>
        <PanelSectionRow>
          <ButtonItem layout="below" disabled={!!busy} onClick={run("V2", () => probeV2(shortcut, url, indexOverride))}>
            V2 set workshop URL on the shortcut, read back
          </ButtonItem>
        </PanelSectionRow>
        <PanelSectionRow>
          <ButtonItem layout="below" disabled={!!busy} onClick={run("V4", () => probeV4())}>
            V4 dump allApps (first 20) + steamid3
          </ButtonItem>
        </PanelSectionRow>
        <PanelSectionRow>
          <ButtonItem layout="below" disabled={!!busy} onClick={run("V5 (no run)", () => probeV5(shortcut, false))}>
            V5 overview + gameid of the shortcut (no launch)
          </ButtonItem>
        </PanelSectionRow>
        <PanelSectionRow>
          <ButtonItem layout="below" disabled={!!busy} onClick={run("V5 (run)", () => probeV5(shortcut, true))}>
            V5 RunGame the shortcut (launches it)
          </ButtonItem>
        </PanelSectionRow>
      </PanelSection>
      <PanelSection title="V3: restart watch (shuts Steam down)">
        <PanelSectionRow>
          <ButtonItem layout="below" disabled={!!busy} onClick={run("V3", () => probeV3())}>
            V3 watch pgrep for 60 s, then StartShutdown(false)
          </ButtonItem>
        </PanelSectionRow>
        <PanelSectionRow>
          <ButtonItem layout="below" disabled={!!busy} onClick={run("V3 summary", () => probeV3Summary())}>
            V3 log the watch summary (after Steam is back)
          </ButtonItem>
        </PanelSectionRow>
      </PanelSection>
      <PanelSection title="Status">
        <PanelSectionRow>
          <ButtonItem
            layout="below"
            onClick={async () => {
              try {
                const r = await backendLogPath();
                setStatus(`log: ${r?.path ?? JSON.stringify(r)}`);
              } catch (e) {
                setStatus(`log_path threw: ${e}`);
              }
            }}
          >
            Show log path
          </ButtonItem>
        </PanelSectionRow>
        <PanelSectionRow>
          <div style={{ fontSize: "12px", wordBreak: "break-all" }}>{status}</div>
        </PanelSectionRow>
      </PanelSection>
    </>
  );
}

export default definePlugin(() => {
  plog("frontend loaded");
  return {
    name: "steam-input-probe",
    titleView: <div className={staticClasses.Title}>Steam Input probe</div>,
    content: <Content />,
    icon: <FaStethoscope />,
    onDismount() {
      console.log("[steam-input-probe] frontend unloading");
    },
  };
});
