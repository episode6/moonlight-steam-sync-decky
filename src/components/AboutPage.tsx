import { ButtonItem, Field, Focusable } from "@decky/ui";
import { useEffect, useState } from "react";

import { backend, controller } from "../instance";
import { isFailure } from "../lib/cli";
import { bundledLine } from "../lib/version";
import { useStore } from "./useStore";

const LOG_LINES = 50;

/** Settings → About (spec 3.8): every `cli_version()` field, the log path and its tail. */
export function AboutPage() {
  const state = useStore(controller.store);
  const [lines, setLines] = useState<string[]>([]);
  const info = state.cliVersion;

  const refresh = async () => {
    await controller.refreshCli();
    const tail = await backend.log_tail(LOG_LINES);
    if (!isFailure(tail)) setLines(tail.lines);
  };
  useEffect(() => {
    void refresh();
  }, []);

  const row = (label: string, value: string | null | undefined) => (
    <Field label={label} description={value ?? "—"} focusable={false} />
  );

  return (
    <div>
      {state.cli && state.cli.state !== "ok" ? row("CLI", state.cli.text) : null}
      {row("Installed CLI", info?.installed ?? "not installed")}
      {row("Installed at", info?.installed_path)}
      {row("Bundled CLI", info ? bundledLine(info) : null)}
      {row("Bundled at", info?.bundled_path)}
      {row("Minimum CLI", info?.minimum)}
      {info?.install_error ? row("Install error", info.install_error) : null}
      {row("Plugin version", info?.plugin_version)}
      {row(
        "Re-fetch all art from Game Mode",
        info ? (info.capabilities.art_commit ? "supported" : "needs a newer CLI") : null,
      )}
      {row("Log", info?.log_path)}
      <ButtonItem layout="below" onClick={() => void refresh()}>
        Refresh
      </ButtonItem>
      <Focusable
        style={{
          fontFamily: "monospace",
          fontSize: 11,
          whiteSpace: "pre-wrap",
          wordBreak: "break-all",
          maxHeight: 320,
          overflowY: "auto",
          background: "rgba(0,0,0,0.3)",
          padding: 8,
          borderRadius: 4,
        }}
      >
        {lines.length ? lines.join("\n") : "(the log is empty)"}
      </Focusable>
    </div>
  );
}
