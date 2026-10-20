---
name: moonlight-sync-sgdb-key-fetch
description: >-
  The Moonlight Sync plugin's "Get key from SteamGridDB…" feature (spec 3.20):
  fetching the SteamGridDB API key through the Game Mode browser over Steam's
  CEF debugger. Covers py_modules/moonlight_sync/cdp.py (the DevTools
  websocket client), sgdbpage.py (fetch_key's page states, the JS snippets,
  reset_tab), start_sgdb_key_fetch / cancel_sgdb_key_fetch and their
  sgdb_key_event / sgdb_key_done events, and the tests (FakeBrowser,
  tests/fakedom.py, tests/fixtures/sgdb/*.html, test_sgdbpage.py,
  test_cdp.py). Load before touching any of these, SteamGridDB login / API
  page handling, or the CEF debugger.
---

# Moonlight Sync SteamGridDB key fetch

Reference split out of the root `AGENTS.md`, whose hard rules (cited here as
"hard rule N") apply throughout. Related: `moonlight-sync-backend` (keys.py,
the contract's other callables), `moonlight-sync-frontend` (fetchSgdbKey,
onSgdbKeyDone, keyFetchText), `moonlight-sync-library-ui` (ArtworkPage).

## Module map: the key fetch's modules

```
py_modules/moonlight_sync/  the backend (imports nothing from decky)
  cdp.py                    the Chrome DevTools Protocol client over Steam's CEF
                            debugger (spec 3.20.2; the port Decky injects through):
                            DEBUGGER, targets() (one GET of /json/list),
                            Session (a stdlib websocket: handshake, masking, the
                            three length forms, fragments, ping, close; evaluate()
                            = Runtime.evaluate returnByValue + awaitPromise, an
                            EvaluateError on a thrown exception; navigate() =
                            Page.navigate, the tab reset's, an errorText reply
                            DebuggerUnavailable; both over one _call), the CONNECT /
                            TARGETS seams the tests replace, as wake.SOCKET is;
                            DebuggerUnavailable (a ConnectionError) for a refused
                            port, a timeout, a closed socket and a CDP-level error
                            reply (a context destroyed by a navigation), which the
                            fetch retries. The one module that talks to the port
  sgdbpage.py               the key fetch (spec 3.20.3): SGDB_HOST / SGDB_API_PAGE /
                            STEAM_OPENID_HOST / KEY_RE, the JS snippets one per page
                            state (JS_PAGE, JS_LOGIN_LINK, JS_NAVIGATE,
                            JS_OPENID_SUBMIT, JS_OPENID_FORM, JS_KEY, JS_GENERATE) so
                            a SteamGridDB redesign is a one-file change, the failure
                            texts, fetch_key(targets, connect, stop, clock, on_state)
                            -> the key (pure over the seams; raises
                            FetchFailed(code, message, detail)): waiting -> login
                            (the link's host and realm checked, one navigate) ->
                            steam-sign-in (one submit, Decision 60) / steam-login
                            (the user types, the form is polled) -> reading (one
                            navigate to the API page per URL, JS_KEY once complete,
                            JS_GENERATE once, Decision 61, and never while a code
                            element shows nor on a Regenerate / new key / Revoke
                            control, Decision 63; a complete document at the API
                            URL without the page's body, JS_API_BODY, asked
                            before JS_GENERATE so nothing on it is clicked, is
                            not judged: polled API_PAGE_GRACE_S (per visit to a
                            complete API page), reloaded once per fetch, polled
                            again, then TEXT_API_NOT_LOADED, Decision 69
                            -- the page a failed attempt leaves in the tab, which
                            the frontend's open has not yet replaced when the
                            fetch first polls) -> done. A session per
                            poll, closed after it; only a `page` target on one of
                            the two hosts is ever evaluated in; the stop event's
                            wait() is the 500 ms poll, so a cancel lands within one.
                            reset_tab(listed, targets, connect, sleep) (Decision
                            70, run by start_sgdb_key_fetch after the port probe):
                            the page target on either host, the tab a previous
                            fetch left, gets a Page.navigate to RESET_URL
                            (about:blank; no script evaluated), and the listing is
                            re-read every RESET_POLL_S, RESET_POLLS times at most
                            (RESET_WAIT_S as a count), until it is off both hosts;
                            answers the host it was on -- also when a listing read
                            after the navigate fails, since the tab was blanked
```

## Backend contract: the key fetch

The key fetch from the Game Mode browser (spec 3.20) needs no CLI and is
not under the runs' busy guard (Decision 62: no `matches.json` involved, so
a sync may run meanwhile and a fetch may start during a sync); it has its
own, `busy` with kind `"key"`. `start_sgdb_key_fetch()` probes
`cdp.TARGETS()` once (so `no-debugger` comes back here, before the
frontend opens the browser), resets the tab a previous fetch left on
SteamGridDB or Steam to `about:blank` (`sgdbpage.reset_tab` over the
probe's listing, Decision 70: the Game Mode browser's one tab outlives
`NavigateBack`, and without the reset the fetch's first polls read the
page the last attempt left there; a reset the debugger refuses is logged
and the fetch starts anyway), then runs `sgdbpage.fetch_key` in a worker
thread (`asyncio.to_thread`, a `threading.Event` for cancellation) and
answers `{ok, started}`; each state change is `sgdb_key_event {state}`
(never page contents) and the end `sgdb_key_done {ok: true, source, hint}`
or `{ok: false, error, message}` with `error` one of `no-debugger`,
`timeout` (180 s), `cancelled`, `sgdb-page` (the login page changed, no
key and no generate button, a thrown snippet, a redirect loop) or
`keys.KeyRefused`'s codes (`set in config.toml`). The key is handed to
`keys.set_key` and nowhere else: not a result, an event, a log line or an
exception message (`FetchFailed.detail` is fixed text or, for a thrown
snippet, the error's class name alone; `_redact` covers the rest); a failed
or cancelled fetch writes no file. An unavailable debugger is retried for
`DEBUGGER_RETRY_S` from the first poll on (the port was already probed; the
frontend's own navigation can destroy the page context under that poll).
Every exit frees the `"key"` guard: a probe that raises anything, and a
`keys.set_key` that raises something other than `KeyRefused` / `OSError`
(`io`, "Could not save the key"). `targets()` goes through an opener
that ignores `http_proxy`, and an answer that is not HTTP is
`DebuggerUnavailable`. `cancel_sgdb_key_fetch()`
sets the event (`{ok, running}`), `unload()` cancels the same way and waits
`KEY_FETCH_UNLOAD_WAIT`. The queued state emits are awaited before the
done emit, so the frontend sees them in order. The frontend (PR-14)
opens `SGDB_API_PAGE` in the Game Mode browser only after
`start_sgdb_key_fetch` answered `ok`, navigates back on `sgdb_key_done`
before any toast, and follows a success with `sgdb_key_state()` and
`test_sgdb_key()`.

## Testing the key fetch

- The key fetch (spec 3.20) never opens a socket in a test: `conftest.py`'s
  `fake_browser` fixture installs a `FakeBrowser` as `cdp.TARGETS` /
  `cdp.CONNECT` (the Game Mode browser as the seams see it: the page
  target once `open_page()` ran, beside `SharedJSContext`, Big Picture and
  ad `iframe` targets; a session's `evaluate` runs the snippet's mirror
  over the current page and then plays the site: the API page bounces to
  `/login` until signed in, the login link goes to Steam, the OpenID
  submit signs in and returns home, *Generate* gives the account a key,
  *Revoke* is recorded and must never happen; `answers` scripts one
  snippet's value or exception, `on_poll` changes the browser per poll,
  `loading_polls` makes a fresh page read as loading first, `api_fixture`
  names the API page's fixture, or a list of them consumed one per load
  with the last standing). The pages are
  `tests/fixtures/sgdb/*.html` (`login`, `openid`, `api`, `api-no-key`,
  `api-revoke-only`, Decision 63's `api-hidden-key` / `api-regenerate`,
  and Decision 69's `api-unrendered` / `api-stray-generate`, complete
  documents at the API URL without the page's body, the latter with a
  *Generate* control that must never be pressed, hand-written from spec
  3.20.1 with the placeholder key), parsed by `tests/fakedom.py`: a minimal DOM (`querySelector` /
  `querySelectorAll` over tag, class, id, `[attr=v]`, `[attr*=v]`,
  descendants and lists; `textContent`, `innerText`, `value`, `href`, a
  recording `click()`, `readyState`, `location.href`) and `evaluate(js,
  document)`, the snippets' Python mirrors: the same control flow with
  every selector and regex literal read out of the snippet's own text, so
  a changed selector changes what the mirror queries and a changed shape
  fails. `tests/test_sgdbpage.py` drives `fetch_key` over the fake with a
  fake clock whose `wait()` is the poll (one test per state-table row and
  per failure, the four rules, cancellation, the 180 s timeout) and the
  backend's thread with `POLL_INTERVAL_S` patched short (the events, the
  0600 key file, `busy`, cancel, `unload`, a refused key, the busy-guard
  independence, the stale tab blanked before the fetch's first poll and a
  refused reset that still starts the fetch); `reset_tab` itself over the
  fake (a tab on either host blanked with one `Page.navigate` and no
  evaluate, no tab or another host untouched, the listing's wait). `tests/test_cdp.py` runs the real websocket client
  against a loopback fake debugger in a thread (handshake, masking, the
  126- and 127-length forms, a fragmented reply, a ping, close, a
  protocol error, a timeout, `navigate()`'s `Page.navigate` with its
  `errorText` and error replies) and `targets()` over a stubbed `urlopen`.
