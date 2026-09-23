"""The SteamGridDB key, read out of the Game Mode browser (spec 3.20.3).

SteamGridDB has no OAuth and no key-issuing API: the key exists only on the
signed-in preferences page, and sign-in is Steam OpenID. The frontend opens
that page in the Game Mode browser; :func:`fetch_key` then drives it over
Steam's CEF debugger (``cdp.py``) through a state machine keyed on the
browser target's URL, polled every ``POLL_INTERVAL_S`` for at most
``SGDB_FETCH_TIMEOUT_S``:

====================  ==============================  ===========================================
state                 the target's URL                what is done
====================  ==============================  ===========================================
``waiting``           no page target on either host   polls ``targets()``
``login``             SteamGridDB, path ``/login``    ``JS_LOGIN_LINK``, then ``JS_NAVIGATE`` to
                                                      it once its host and realm are checked
``steam-sign-in``     steamcommunity.com              ``JS_OPENID_SUBMIT`` once (Decision 60)
``steam-login``       steamcommunity.com, no form     waits for the user to log in on the page
``reading``           SteamGridDB, any other path     ``JS_NAVIGATE`` to the API page (once per
                                                      URL); there, ``JS_KEY``, else
                                                      ``JS_GENERATE`` once (Decision 61)
``done``                                              the key is returned to the caller
====================  ==============================  ===========================================

The constants and the JavaScript snippets live here, one per page state,
so a SteamGridDB redesign is a one-file change. The rules, each a test:

- **The key never leaves the backend.** ``JS_KEY``'s value is returned to
  the caller (``Backend``, which hands it to ``keys.set_key``) and goes
  nowhere else: not into a state, an exception message or a log line.
- **Never *Revoke*.** No snippet clicks anything whose text matches
  ``/revoke/i``; ``JS_GENERATE`` excludes it explicitly.
- **One click each.** ``JS_NAVIGATE`` from ``/login``, ``JS_OPENID_SUBMIT``
  and ``JS_GENERATE`` each fire at most once per fetch; a second visit to
  the same state (a redirect loop) fails with ``sgdb-page`` instead.
- **Only SteamGridDB's own targets.** Nothing is evaluated in a target
  whose host is not ``SGDB_HOST`` or ``STEAM_OPENID_HOST``, so never in
  ``SharedJSContext`` or the Big Picture target. ``JS_NAVIGATE``'s URL is
  always ``SGDB_API_PAGE`` or the login link whose realm was checked.
- **Cancellation.** The ``stop`` event is checked between polls, so a
  cancel is noticed within one ``POLL_INTERVAL_S``.

Pure: no decky import, no socket of its own (the seams are arguments), no
thread of its own (``Backend`` runs it through ``asyncio.to_thread``).
"""

from __future__ import annotations

import json
import re
import time
import urllib.parse
from collections.abc import Callable
from typing import Any, Protocol

from . import cdp

SGDB_HOST = "www.steamgriddb.com"
SGDB_API_PAGE = f"https://{SGDB_HOST}/profile/preferences/api"
SGDB_API_PATH = "/profile/preferences/api"
SGDB_LOGIN_PATH = "/login"
STEAM_OPENID_HOST = "steamcommunity.com"
#: The ``openid.realm`` the login link must carry (spec 3.20.1 item 3).
SGDB_REALM = f"https://{SGDB_HOST}"
KEY_RE = re.compile(r"^[0-9a-f]{32}$")

#: How often the browser is polled, and the whole fetch's bound: the user
#: has to press *Sign In*, possibly log in to Steam on that page first.
POLL_INTERVAL_S = 0.5
SGDB_FETCH_TIMEOUT_S = 180.0
#: A debugger that stops answering (or a page context a navigation destroyed)
#: is retried this long; the backend has already probed the port.
DEBUGGER_RETRY_S = 10.0
#: After ``JS_GENERATE`` clicked, how long the key is waited for.
GENERATE_WAIT_S = 15.0

JS_PAGE = "({href: location.href, ready: document.readyState})"
JS_LOGIN_LINK = (
    "document.querySelector('a.btn[href*=\"steamcommunity.com/openid/login\"]')?.href ?? null"
)
JS_NAVIGATE = "location.href = %s; true"  # % json.dumps(url)
JS_OPENID_SUBMIT = (
    '(() => { const b = document.querySelector("#openidForm input[type=submit]"); '
    "if (!b) return false; b.click(); return true; })()"
)
#: ``steam-login``'s poll: the form's presence, nothing clicked.
JS_OPENID_FORM = 'document.querySelector("#openidForm") !== null'
JS_KEY = (
    '(() => { const c = [...document.querySelectorAll("div.profile code")]'
    ".map(e => e.textContent.trim()).filter(t => /^[0-9a-f]{32}$/.test(t)); "
    "return c.length === 1 ? c[0] : null; })()"
)
JS_GENERATE = (
    '(() => { const b = [...document.querySelectorAll("button, a.btn, input[type=submit]")]'
    '.find(e => /generate/i.test(e.innerText || e.value || "") '
    '&& !/revoke/i.test(e.innerText || e.value || "")); '
    "if (!b) return false; b.click(); return true; })()"
)

STATES = ("waiting", "login", "steam-sign-in", "steam-login", "reading", "done")

TEXT_NO_DEBUGGER = "Steam's debugger port is not reachable; enter the key by hand"
TEXT_TIMEOUT = "Timed out waiting for the SteamGridDB page; enter the key by hand or try again"
TEXT_CANCELLED = "The key fetch was cancelled"
TEXT_LOGIN_CHANGED = "SteamGridDB's login page has changed; enter the key by hand"
TEXT_NO_KEY = "SteamGridDB shows no API key; generate one on its API page, then try again"
TEXT_PAGE_CHANGED = "SteamGridDB's page has changed; enter the key by hand"


_ERROR_NAME = re.compile(r"^[A-Za-z_$][\w$]{0,63}$")


def _error_name(exc: cdp.EvaluateError) -> str:
    """The thrown error's class name (``TypeError``) and nothing else: the
    rest of the page's description is page text, which ``detail`` never
    carries."""
    name = exc.description.split(":", 1)[0].strip()
    return name if _ERROR_NAME.match(name) else "an exception"


class FetchFailed(Exception):
    """The fetch ended without a key: ``code`` and ``message`` are the
    ``sgdb_key_done`` failure's; ``detail`` is for the log only and never
    carries page contents."""

    def __init__(self, code: str, message: str, detail: str | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.detail = detail


class Stop(Protocol):
    """What ``fetch_key`` needs of its cancellation event (``threading.Event``)."""

    def is_set(self) -> bool: ...

    def wait(self, timeout: float | None = None) -> bool: ...


def navigate_js(url: str) -> str:
    return JS_NAVIGATE % json.dumps(url)


def host_of(url: str) -> str | None:
    try:
        return urllib.parse.urlsplit(url).hostname
    except ValueError:
        return None


def page_kind(url: str) -> str | None:
    """``"login"``, ``"steam"`` or ``"sgdb"`` for a URL this fetch acts on; else ``None``."""
    host = host_of(url)
    if host == STEAM_OPENID_HOST:
        return "steam"
    if host != SGDB_HOST:
        return None
    path = urllib.parse.urlsplit(url).path.rstrip("/") or "/"
    return "login" if path == SGDB_LOGIN_PATH else "sgdb"


def is_api_page(url: str) -> bool:
    return (urllib.parse.urlsplit(url).path.rstrip("/") or "/") == SGDB_API_PATH


def login_link_ok(link: object) -> bool:
    """Steam's OpenID endpoint with SteamGridDB as the realm, and nothing else."""
    if not isinstance(link, str):
        return False
    parts = urllib.parse.urlsplit(link)
    if parts.scheme != "https" or parts.hostname != STEAM_OPENID_HOST:
        return False
    realm = urllib.parse.parse_qs(parts.query).get("openid.realm", [])
    return realm == [SGDB_REALM]


def find_target(targets: list[cdp.Target]) -> cdp.Target | None:
    """The browser's page on one of the two hosts; ad ``iframe`` targets and
    everything that is not a ``page`` are ignored."""
    for target in targets:
        if target.get("type") == "page" and page_kind(target.get("url", "")) is not None:
            return target
    return None


class _Fetch:
    def __init__(
        self,
        targets: Callable[[], list[cdp.Target]],
        connect: Callable[[str], Any],
        stop: Stop,
        clock: Callable[[], float],
        on_state: Callable[[str], Any] | None,
    ) -> None:
        self.targets = targets
        self.connect = connect
        self.stop = stop
        self.clock = clock
        self.on_state = on_state
        self.state: str | None = None
        # the one-click-each flags, per fetch
        self.login_navigated = False
        self.openid_submitted = False
        self.generate_clicked_at: float | None = None
        self.navigated_to_api: set[str] = set()
        self.unavailable_since: float | None = None

    def set_state(self, state: str) -> None:
        if state != self.state:
            self.state = state
            if self.on_state is not None:
                self.on_state(state)

    def run(self) -> str:
        deadline = self.clock() + SGDB_FETCH_TIMEOUT_S
        while True:
            if self.stop.is_set():
                raise FetchFailed("cancelled", TEXT_CANCELLED)
            if self.clock() >= deadline:
                raise FetchFailed("timeout", TEXT_TIMEOUT)
            try:
                key = self.poll()
            except cdp.DebuggerUnavailable as exc:
                now = self.clock()
                if self.unavailable_since is None:
                    self.unavailable_since = now
                # Retried from the first poll too: the backend probed the
                # port before starting, and the frontend's own navigation
                # to the API page can destroy the context under that poll.
                if now - self.unavailable_since >= DEBUGGER_RETRY_S:
                    raise FetchFailed("no-debugger", TEXT_NO_DEBUGGER, detail=str(exc)) from exc
            except cdp.EvaluateError as exc:
                raise FetchFailed(
                    "sgdb-page", TEXT_PAGE_CHANGED, detail=f"in {self.state}: {_error_name(exc)}"
                ) from exc
            else:
                self.unavailable_since = None
                if key is not None:
                    self.set_state("done")
                    return key
            if self.stop.wait(POLL_INTERVAL_S):
                raise FetchFailed("cancelled", TEXT_CANCELLED)

    def poll(self) -> str | None:
        """One look at the browser: the key, or ``None`` to poll again."""
        target = find_target(self.targets())
        if target is None:
            self.set_state("waiting")
            return None
        session = self.connect(target["webSocketDebuggerUrl"])
        try:
            page = session.evaluate(JS_PAGE)
            href = target["url"]
            ready = None
            if isinstance(page, dict):
                if isinstance(page.get("href"), str):
                    href = page["href"]
                ready = page.get("ready")
            kind = page_kind(href)
            if kind is None:
                # It left both hosts between the listing and the evaluate.
                self.set_state("waiting")
                return None
            loading = ready == "loading"
            if kind == "login":
                return self._on_login(session, loading)
            if kind == "steam":
                return self._on_steam(session, loading)
            return self._on_sgdb(session, href, ready == "complete")
        finally:
            session.close()

    def _on_login(self, session: Any, loading: bool) -> None:
        entering = self.state != "login"
        self.set_state("login")
        if self.login_navigated:
            if entering:
                raise FetchFailed(
                    "sgdb-page",
                    TEXT_PAGE_CHANGED,
                    detail="back on the login page after the sign-in",
                )
            return None  # the navigation is still on its way
        if loading:
            return None
        link = session.evaluate(JS_LOGIN_LINK)
        if not login_link_ok(link):
            raise FetchFailed(
                "sgdb-page",
                TEXT_LOGIN_CHANGED,
                detail="no Login via Steam link"
                if link is None
                else "the login link is not Steam's",
            )
        session.evaluate(navigate_js(link))
        self.login_navigated = True
        return None

    def _on_steam(self, session: Any, loading: bool) -> None:
        entering = self.state not in ("steam-sign-in", "steam-login")
        if self.openid_submitted:
            if entering:
                raise FetchFailed(
                    "sgdb-page",
                    TEXT_PAGE_CHANGED,
                    detail="back on Steam's sign-in page after submitting it",
                )
            return None  # the submit's navigation is still on its way
        if self.state == "steam-login" and (
            loading or session.evaluate(JS_OPENID_FORM) is not True
        ):
            return None
        self.set_state("steam-sign-in")
        if loading:
            return None
        clicked = session.evaluate(JS_OPENID_SUBMIT)
        if clicked is True:
            self.openid_submitted = True
            return None
        if clicked is False:
            self.set_state("steam-login")
            return None
        raise FetchFailed("sgdb-page", TEXT_PAGE_CHANGED, detail="the sign-in form answered oddly")

    def _on_sgdb(self, session: Any, href: str, complete: bool) -> str | None:
        self.set_state("reading")
        if not is_api_page(href):
            if href in self.navigated_to_api or not complete:
                return None
            session.evaluate(navigate_js(SGDB_API_PAGE))
            self.navigated_to_api.add(href)
            return None
        if not complete:
            return None
        value = session.evaluate(JS_KEY)
        if isinstance(value, str) and KEY_RE.match(value):
            return value
        if value is not None:
            raise FetchFailed(
                "sgdb-page", TEXT_PAGE_CHANGED, detail="the key snippet answered oddly"
            )
        if self.generate_clicked_at is None:
            clicked = session.evaluate(JS_GENERATE)
            if clicked is True:
                self.generate_clicked_at = self.clock()
                return None
            raise FetchFailed("sgdb-page", TEXT_NO_KEY, detail="no key and no generate button")
        if self.clock() - self.generate_clicked_at >= GENERATE_WAIT_S:
            raise FetchFailed("sgdb-page", TEXT_NO_KEY, detail="no key after generating one")
        return None


def fetch_key(
    targets: Callable[[], list[cdp.Target]],
    connect: Callable[[str], Any],
    stop: Stop,
    clock: Callable[[], float] = time.monotonic,
    on_state: Callable[[str], Any] | None = None,
) -> str:
    """Drive the browser to the key and return it; raise :class:`FetchFailed`.

    ``targets`` and ``connect`` are ``cdp.TARGETS`` / ``cdp.CONNECT`` (or
    the tests' fakes); ``stop`` is the cancellation event, whose ``wait``
    is also the poll interval; ``clock`` is monotonic seconds; ``on_state``
    is called with each new state name, never with page contents. A
    session is opened per poll and closed after it, so a page that
    navigates between polls never leaves a stale context behind.
    """
    return _Fetch(targets, connect, stop, clock, on_state).run()
