import { ButtonItem, ConfirmModal, Field, TextField, ToggleField, showModal } from "@decky/ui";
import { toaster } from "@decky/api";
import { useEffect, useState, type ReactNode } from "react";

import { backend, controller } from "../instance";
import { errorText, isFailure, type Result } from "../lib/cli";
import { Controller } from "../lib/controller";
import { actionsReady, keyFetchOffered, keyFetchText } from "../lib/state";
import { useStore } from "./useStore";

const KEY_LINK = "Get a key at steamgriddb.com/profile/preferences/api";

/** The consent modal's text (spec 3.20.4), exactly. */
const FETCH_TITLE = "Sign in to SteamGridDB with Steam?";
const FETCH_TEXT =
  "Moonlight Sync opens steamgriddb.com in Steam's browser and signs you in with your Steam account " +
  "(SteamGridDB gets your public Steam ID, nothing else), then reads your API key from your SteamGridDB " +
  "preferences and saves it on this device. Your key is never shown or sent anywhere else.";

function confirmFetch() {
  showModal(
    <ConfirmModal
      strTitle={FETCH_TITLE}
      strDescription={FETCH_TEXT}
      strOKButtonText="Continue"
      strCancelButtonText="Cancel"
      onOK={() => void controller.fetchSgdbKey()}
    />,
  );
}

/**
 * The SteamGridDB key field (spec 3.8 "Artwork page"). The backend only ever
 * returns the key's last four characters; the typed key goes straight to
 * `set_sgdb_key` and the field is cleared. With no key or the plugin's own
 * key file, *Get key from SteamGridDB…* reads it out of the Game Mode
 * browser instead (spec 3.20.4): the key state and the fetch in flight are
 * the store's (`sgdbKey`, `keyFetch`), so the field follows
 * `sgdb_key_event` / `sgdb_key_done` like everything else.
 */
function KeyField() {
  const { sgdbKey: state, keyFetch } = useStore(controller.store);
  const [draft, setDraft] = useState("");
  const [note, setNote] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const load = async () => {
    const failed = await controller.refreshSgdbKey();
    if (failed) setNote(errorText(failed));
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
  const test = () => run(() => backend.test_sgdb_key(), Controller.KEY_ACCEPTED);
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

  // While a fetch is in flight (spec 3.20.4 step 3) the description says
  // where it is and *Cancel* stands where *Save* / *Get key…* were.
  const fetching = keyFetchOffered(state) ? keyFetch : null;
  const fetchButton = !keyFetchOffered(state) ? null : fetching ? (
    <ButtonItem layout="below" onClick={() => void controller.cancelSgdbKeyFetch()}>
      Cancel
    </ButtonItem>
  ) : (
    <ButtonItem layout="below" disabled={busy} onClick={confirmFetch}>
      Get key from SteamGridDB…
    </ButtonItem>
  );

  const entry = (
    <>
      <TextField
        label="SteamGridDB API key"
        description={fetching ? keyFetchText(fetching) : KEY_LINK}
        bIsPassword
        value={draft}
        disabled={busy || !!fetching}
        onChange={(e) => setDraft(e.target.value)}
      />
      {fetching ? null : (
        <ButtonItem layout="below" disabled={busy || !draft.trim()} onClick={() => void save()}>
          Save
        </ButtonItem>
      )}
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
            description={fetching ? keyFetchText(fetching) : `set, ends in …${state.hint ?? ""}`}
            focusable={false}
          />
          <ButtonItem layout="below" disabled={busy || !!fetching} onClick={() => void test()}>
            Test
          </ButtonItem>
          <ButtonItem layout="below" disabled={busy || !!fetching} onClick={() => void remove()}>
            Remove
          </ButtonItem>
          {fetchButton}
        </>
      );
      break;
    default:
      body = (
        <>
          {entry}
          {fetchButton}
        </>
      );
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
