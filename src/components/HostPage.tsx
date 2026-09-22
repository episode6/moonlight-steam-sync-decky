import { ButtonItem, ConfirmModal, DialogButton, Field, Focusable, TextField, showModal } from "@decky/ui";
import { toaster } from "@decky/api";
import { useState } from "react";

import { controller } from "../instance";
import { errorText, isFailure, type WakeInfo } from "../lib/cli";
import { relativeTime } from "../lib/format";
import { actionsReady, wakeInfoOf } from "../lib/state";
import { confirmSwitch } from "./confirmSwitch";
import { useStore } from "./useStore";

function confirmForget(name: string, onError: (message: string) => void) {
  showModal(
    <ConfirmModal
      strTitle={`Forget ${name}?`}
      strDescription="Its parked tiles stay until you remove everything."
      strOKButtonText="Forget"
      strCancelButtonText="Cancel"
      onOK={() => {
        void controller.forgetHost(name).then((result) => {
          if (isFailure(result)) onError(errorText(result));
        });
      }}
    />,
  );
}

/**
 * One host's Wake-on-LAN MAC (spec 3.18): what the panel's *Wake* sends to.
 * Moonlight's own list supplies it when the client learned one (shown, not
 * editable away: an entered MAC overrides it); otherwise the field is where
 * to type it. Saving an empty field drops the entered MAC.
 */
function WakeMacRow({ name, wake, onError }: { name: string; wake: WakeInfo | null; onError: (m: string) => void }) {
  const stored = wake?.source === "settings" ? wake.mac : "";
  const [draft, setDraft] = useState(stored);
  const [saving, setSaving] = useState(false);
  const description =
    wake === null
      ? "Not known: enter the PC's MAC address (aa:bb:cc:dd:ee:ff) to enable Wake in the panel"
      : wake.source === "moonlight"
        ? `${wake.mac} from Moonlight's host list; enter one here to override it`
        : "Entered here; clear the field to go back to Moonlight's own";
  const save = async () => {
    setSaving(true);
    const result = await controller.setWakeMac(name, draft.trim() || null);
    setSaving(false);
    if (isFailure(result)) {
      onError(errorText(result));
      return;
    }
    setDraft(result.mac ?? "");
    toaster.toast({
      title: "Moonlight Sync",
      body: result.mac ? `${name} wakes with ${result.mac}` : `Cleared the entered MAC for ${name}`,
    });
  };
  return (
    <Field label={`${name}: Wake-on-LAN MAC`} description={description} childrenLayout="below">
      <Focusable style={{ display: "flex", gap: 8, alignItems: "center" }}>
        <div style={{ flex: 1 }}>
          <TextField value={draft} disabled={saving} onChange={(e) => setDraft(e.target.value)} />
        </div>
        <DialogButton
          style={{ minWidth: 0, padding: "8px 14px" }}
          disabled={saving || draft.trim() === stored}
          onClick={() => void save()}
        >
          Save
        </DialogButton>
      </Focusable>
    </Field>
  );
}

/**
 * Settings → Host (spec 3.8): the known hosts with their cached title count
 * and *last seen*, *Switch*, *Forget*, and *Add host* (`list --host NAME` is
 * the pairing check; there is nothing on the PC to ask). Under each host,
 * its Wake-on-LAN MAC (spec 3.18).
 */
export function HostPage() {
  const state = useStore(controller.store);
  const [draft, setDraft] = useState("");
  const [checking, setChecking] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const hosts = state.hosts;
  const ready = actionsReady(state);
  const active = hosts?.active?.toLowerCase() ?? null;

  const add = async () => {
    const name = draft.trim();
    if (!name) return;
    setChecking(true);
    setError(null);
    const result = await controller.addHost(name);
    setChecking(false);
    if (isFailure(result)) {
      const text = errorText(result);
      setError(result.exit === 3 ? `${text} — pair the Deck with it in Moonlight first` : text);
      return;
    }
    setDraft("");
    toaster.toast({ title: "Moonlight Sync", body: `Added ${name} (${result.count} apps)` });
  };

  return (
    <div>
      {!ready ? (
        <Field
          description={state.cli?.text || "Waiting for the Steam library to load…"}
          focusable={false}
        />
      ) : null}
      {(hosts?.known ?? []).map((name) => {
        const cached = hosts?.cached_hosts.find((c) => c.name.toLowerCase() === name.toLowerCase());
        const isActive = name.toLowerCase() === active;
        const detail = cached
          ? `${cached.count} titles cached · last seen ${relativeTime(cached.when)}`
          : "never synced";
        return (
          <div key={name}>
            <Field label={isActive ? `${name} (active)` : name} description={detail} childrenLayout="inline">
              <Focusable style={{ display: "flex", gap: 8 }}>
                {!isActive ? (
                  <DialogButton
                    style={{ minWidth: 0, padding: "8px 14px" }}
                    disabled={!ready || !!state.run?.running}
                    onClick={() => confirmSwitch(controller, name)}
                  >
                    Switch
                  </DialogButton>
                ) : null}
                <DialogButton
                  style={{ minWidth: 0, padding: "8px 14px" }}
                  /* The backend refuses to forget the active host; don't offer it. */
                  disabled={isActive}
                  onClick={() => confirmForget(name, setError)}
                >
                  Forget
                </DialogButton>
              </Focusable>
            </Field>
            <WakeMacRow name={name} wake={wakeInfoOf(hosts, name)} onError={setError} />
          </div>
        );
      })}
      {hosts && hosts.known.length === 0 ? (
        <Field description="No hosts yet. Add the gaming PC you stream from." focusable={false} />
      ) : null}
      <TextField
        label="Add host"
        description="The host's name as Moonlight knows it (the Deck must already be paired with it)"
        value={draft}
        disabled={checking}
        onChange={(e) => setDraft(e.target.value)}
      />
      <ButtonItem layout="below" disabled={!ready || checking || !draft.trim()} onClick={() => void add()}>
        {checking ? "Checking…" : "Check and add"}
      </ButtonItem>
      {error ? <Field description={error} focusable={false} /> : null}
    </div>
  );
}
