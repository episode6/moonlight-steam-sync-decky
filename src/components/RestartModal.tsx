import { ConfirmModal } from "@decky/ui";
import { useEffect, useRef, useState } from "react";

import type { RestartPrompt } from "../lib/controller";
import { countdownLine } from "../lib/restart";
import type { AppState, Store } from "../lib/state";
import { useStore } from "./useStore";

interface Props {
  prompt: RestartPrompt;
  store: Store<AppState>;
  /** Injected by `showModal`. */
  closeModal?: () => void;
}

/**
 * The restart prompt (spec 3.9, mockup screen 6): a `ConfirmModal` because
 * a toast cannot take B. *Restart now* / the countdown reaching zero call
 * `onRestartNow`; *Later* (B) calls `onLater`. While a game is running the
 * countdown never starts (the in-game guard); with `countdownSeconds == 0`
 * there is no countdown, only the two buttons.
 */
export function RestartModal({ prompt, store, closeModal }: Props) {
  const { inGame } = useStore(store);
  const countdown = prompt.countdownSeconds > 0;
  const [left, setLeft] = useState(prompt.countdownSeconds);
  const acted = useRef(false);

  // (Re)start the countdown from the top whenever no game is running.
  useEffect(() => {
    if (!countdown || inGame) return undefined;
    setLeft(prompt.countdownSeconds);
    const timer = setInterval(() => setLeft((n) => n - 1), 1000);
    return () => clearInterval(timer);
  }, [countdown, inGame, prompt.countdownSeconds]);

  useEffect(() => {
    if (countdown && !inGame && left <= 0 && !acted.current) {
      acted.current = true;
      prompt.onRestartNow();
      closeModal?.();
    }
  }, [countdown, inGame, left, prompt, closeModal]);

  const { title, description } = prompt.decision;
  return (
    <ConfirmModal
      strTitle={title}
      strDescription={
        <div>
          {description ? <div>{description}</div> : null}
          <div>{countdownLine(Math.max(left, 0), countdown, inGame)}</div>
        </div>
      }
      strOKButtonText="Restart now"
      strCancelButtonText="Later"
      bDisableBackgroundDismiss
      onOK={() => {
        if (acted.current) return;
        acted.current = true;
        prompt.onRestartNow();
      }}
      onCancel={() => {
        if (acted.current) return;
        acted.current = true;
        prompt.onLater();
      }}
      closeModal={closeModal}
    />
  );
}
