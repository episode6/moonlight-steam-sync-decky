import {
  DialogBody,
  DialogButton,
  DialogFooter,
  DialogHeader,
  Focusable,
  ModalRoot,
  Spinner,
  TextField,
} from "@decky/ui";
import { toaster } from "@decky/api";
import { useEffect, useRef, useState } from "react";

import { backend, controller } from "../instance";
import { errorText, isFailure, type CandidateEvent, type PinnedEvent } from "../lib/cli";
import { candidateRows, matchSummary, noMatchRow, type CandidateRow, type TitleRow } from "../lib/join";
import { Pill } from "./Pill";

interface Props {
  row: TitleRow;
  /** The row's new match, before the next `list` confirms it. */
  onPinned(pinned: PinnedEvent, matchedName: string | null): void;
  /** Injected by `showModal`. */
  closeModal?: () => void;
}

function Candidate({
  row,
  disabled,
  pinning,
  onUse,
}: {
  row: CandidateRow;
  disabled: boolean;
  pinning: boolean;
  onUse(): void;
}) {
  return (
    <DialogButton
      disabled={disabled}
      onClick={onUse}
      onOKActionDescription="Use this"
      style={{
        display: "grid",
        gridTemplateColumns: "1fr auto",
        alignItems: "center",
        gap: 10,
        textAlign: "left",
        padding: "6px 10px",
        minWidth: 0,
        marginTop: 5,
        outline: row.current ? "1px solid rgba(255,255,255,0.35)" : undefined,
      }}
    >
      <div style={{ minWidth: 0 }}>
        <div style={{ fontWeight: 600 }}>{row.name}</div>
        <div style={{ fontSize: 11, opacity: 0.7, fontFamily: "monospace" }}>{row.detail}</div>
      </div>
      <div>{pinning ? <Spinner style={{ width: 16, height: 16 }} /> : <Pill tone={row.tone}>{row.outcome}</Pill>}</div>
    </DialogButton>
  );
}

/**
 * Change match (spec 3.8, mockup screen 5): search Steam's store and
 * SteamGridDB, then pin a result, or pin "no match". Results are one list,
 * owned games first, then Steam before SteamGridDB; each row shows what the next sync makes of
 * the title (`becomes stream button` for a game this account owns), the
 * current match is marked, and *No match* comes last. *Use this* pins with
 * `--defer-art` (Decision 8), so nothing changes until the next sync, which
 * also re-fetches the title's art. *Cancel* does nothing.
 */
export function ChangeMatchModal({ row, onPinned, closeModal }: Props) {
  const [term, setTerm] = useState(row.name);
  const [searching, setSearching] = useState(false);
  const [candidates, setCandidates] = useState<CandidateEvent[] | null>(null);
  const [notes, setNotes] = useState<string[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [pinning, setPinning] = useState<string | null>(null);
  const searchId = useRef(0);

  const search = async (text: string) => {
    const query = text.trim();
    if (!query) return;
    const id = ++searchId.current;
    setSearching(true);
    setError(null);
    const result = await backend.search(query);
    if (id !== searchId.current) return; // a newer search is running
    setSearching(false);
    if (isFailure(result)) {
      setError(errorText(result));
      setCandidates([]);
      setNotes([]);
      return;
    }
    setCandidates(result.candidates);
    setNotes(result.notes);
  };

  useEffect(() => {
    void search(row.name);
  }, []); // eslint-disable-line react-hooks/exhaustive-deps -- search once, for the title, on open

  const use = async (choice: CandidateRow) => {
    if (pinning) return;
    setPinning(choice.key);
    setError(null);
    const result = await controller.pinTitle(row.name, choice.choice);
    setPinning(null);
    if (isFailure(result)) {
      setError(errorText(result));
      return;
    }
    onPinned(result.pinned, choice.source === "none" ? null : choice.name);
    toaster.toast({ title: "Moonlight Sync", body: "Pinned; sync to apply" });
    closeModal?.();
  };

  const summary = matchSummary(row.match);
  const rows = [...candidateRows(candidates ?? [], row.match), noMatchRow(row.match)];

  return (
    <ModalRoot closeModal={closeModal}>
      <DialogHeader>Change match for “{row.name}”</DialogHeader>
      <DialogBody>
        <div style={{ fontSize: 12, opacity: 0.75, marginBottom: 8 }}>
          {summary.lead}
          {summary.name ? <b>{summary.name}</b> : null}
          {summary.tail}
          {summary.overrideWins ? " An override in config.toml wins over a pin." : null}
        </div>
        <Focusable flow-children="horizontal" style={{ display: "flex", gap: 8, alignItems: "flex-end" }}>
          <div style={{ flexGrow: 1 }}>
            <TextField
              value={term}
              disabled={!!pinning}
              onChange={(e) => setTerm(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter") void search(term);
              }}
            />
          </div>
          <DialogButton
            style={{ minWidth: 0, width: "auto", padding: "8px 16px" }}
            disabled={searching || !!pinning || !term.trim()}
            onClick={() => void search(term)}
          >
            Search
          </DialogButton>
        </Focusable>
        {searching ? (
          <div style={{ display: "flex", gap: 8, alignItems: "center", marginTop: 8, opacity: 0.8 }}>
            <Spinner style={{ width: 16, height: 16 }} /> Searching Steam and SteamGridDB…
          </div>
        ) : null}
        {notes.map((note) => (
          <div key={note} style={{ fontSize: 11.5, opacity: 0.7, marginTop: 6 }}>
            {note}
          </div>
        ))}
        {!searching && candidates !== null && candidates.length === 0 && !error ? (
          <div style={{ fontSize: 12, opacity: 0.7, marginTop: 6 }}>No results for “{term.trim()}”.</div>
        ) : null}
        {error ? <div style={{ fontSize: 12, color: "#ff9a9a", marginTop: 6 }}>{error}</div> : null}
        <Focusable style={{ display: "flex", flexDirection: "column", marginTop: 6 }}>
          {rows.map((candidate) => (
            <Candidate
              key={candidate.key}
              row={candidate}
              disabled={!!pinning}
              pinning={pinning === candidate.key}
              onUse={() => void use(candidate)}
            />
          ))}
        </Focusable>
      </DialogBody>
      <DialogFooter>
        <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 10 }}>
          <span style={{ fontSize: 11.5, opacity: 0.7 }}>
            Pins survive art --force. The next sync applies it and re-fetches the art.
          </span>
          <DialogButton style={{ minWidth: 0, width: "auto", padding: "8px 16px" }} onClick={() => closeModal?.()}>
            Cancel
          </DialogButton>
        </div>
      </DialogFooter>
    </ModalRoot>
  );
}
