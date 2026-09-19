import { ButtonItem, ConfirmModal, Field, TextField, ToggleField, showModal } from "@decky/ui";
import { toaster } from "@decky/api";
import { useEffect, useState, type ReactNode } from "react";

import { backend, controller } from "../instance";
import { errorText, isFailure, type KeyState, type Result } from "../lib/cli";
import { actionsReady } from "../lib/state";
import { useStore } from "./useStore";

const KEY_LINK = "Get a key at steamgriddb.com/profile/preferences/api";

/**
 * The SteamGridDB key field (spec 3.8 "Artwork page"). The backend only ever
 * returns the key's last four characters; the typed key goes straight to
 * `set_sgdb_key` and the field is cleared.
 */
function KeyField() {
  const [state, setState] = useState<KeyState | null>(null);
  const [draft, setDraft] = useState("");
  const [note, setNote] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const load = async () => {
    const result = await backend.sgdb_key_state();
    if (isFailure(result)) setNote(errorText(result));
    else setState(result);
  };
  useEffect(() => {
    void load();
  }, []);

  const run = async (action: () => Promise<Result>, success: string) => {
    setBusy(true);
    setNote(null);
    const result = await action();
    setBusy(false);
    setNote(isFailure(result) ? errorText(result) : success);
    await load();
  };

  const save = () =>
    run(async () => {
      const result = await backend.set_sgdb_key(draft);
      if (!isFailure(result)) setDraft("");
      return result;
    }, "Saved");
  const test = () => run(() => backend.test_sgdb_key(), "SteamGridDB accepted the key");
  const remove = () => run(() => backend.clear_sgdb_key(), "Removed");

  if (!state) return <Field label="SteamGridDB API key" description={note ?? "Loading…"} focusable={false} />;

  if (state.config_parse_error) {
    return (
      <Field
        label="SteamGridDB API key"
        description="config.toml could not be read; fix it in Desktop Mode"
        focusable={false}
      />
    );
  }

  const entry = (
    <>
      <TextField
        label="SteamGridDB API key"
        description={KEY_LINK}
        bIsPassword
        value={draft}
        disabled={busy}
        onChange={(e) => setDraft(e.target.value)}
      />
      <ButtonItem layout="below" disabled={busy || !draft.trim()} onClick={() => void save()}>
        Save
      </ButtonItem>
    </>
  );

  let body: ReactNode;
  switch (state.source) {
    case "config":
      body = (
        <TextField
          label="SteamGridDB API key"
          description={`set in config.toml (ends in …${state.hint ?? ""})`}
          disabled
          value=""
        />
      );
      break;
    case "env":
      body = (
        <>
          <Field
            label="SteamGridDB API key"
            description={`set in the environment (SGDB_API_KEY), ends in …${state.hint ?? ""}; it wins over a saved key`}
            focusable={false}
          />
          <ButtonItem layout="below" disabled={busy} onClick={() => void test()}>
            Test
          </ButtonItem>
          {entry}
        </>
      );
      break;
    case "file":
      body = (
        <>
          <Field
            label="SteamGridDB API key"
            description={`set, ends in …${state.hint ?? ""}`}
            focusable={false}
          />
          <ButtonItem layout="below" disabled={busy} onClick={() => void test()}>
            Test
          </ButtonItem>
          <ButtonItem layout="below" disabled={busy} onClick={() => void remove()}>
            Remove
          </ButtonItem>
        </>
      );
      break;
    default:
      body = entry;
  }
  return (
    <>
      {body}
      {note ? <Field description={note} focusable={false} /> : null}
    </>
  );
}

/** Settings → Artwork: the key, *Retry missing art*, *Re-fetch all art*. */
export function ArtworkPage() {
  const state = useStore(controller.store);
  const artCommit = !!state.cliVersion?.capabilities.art_commit;
  const titles = state.entries ? state.entries.filter((e) => !e.client).length : null;

  const refetch = () =>
    showModal(
      <ConfirmModal
        strTitle="Re-fetch all art"
        strDescription={`Re-download every image for ${titles ?? "all"} titles? This takes a while and Steam restarts once at the end.`}
        strOKButtonText="Re-fetch"
        strCancelButtonText="Cancel"
        onOK={() => {
          void controller.run("art").then((failed) => {
            if (!failed) {
              toaster.toast({ title: "Moonlight Sync", body: "Re-fetching art; progress is in the Quick Access menu" });
            }
          });
        }}
      />,
    );

  return (
    <div>
      <KeyField />
      <ToggleField
        label="Retry missing art"
        description="Look again for images that were missing last time, on the next sync"
        checked={!!state.settings?.retry_missing}
        disabled={!state.settings}
        onChange={(checked) => void controller.setSettings({ retry_missing: checked })}
      />
      <ButtonItem
        layout="below"
        label="Re-fetch all art"
        description={artCommit ? "Re-download every image; Steam restarts once" : "needs a newer CLI"}
        disabled={!artCommit || !actionsReady(state) || !!state.run?.running}
        onClick={refetch}
      >
        Re-fetch
      </ButtonItem>
    </div>
  );
}
