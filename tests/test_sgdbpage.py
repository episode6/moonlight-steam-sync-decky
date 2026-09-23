"""The key fetch (spec 3.20.3): the state machine over the seams, its rules,
and ``Backend.start_sgdb_key_fetch`` / ``cancel_sgdb_key_fetch`` / ``unload``.

The pure half drives ``sgdbpage.fetch_key`` over ``conftest.FakeBrowser``
(the fixtures through ``fakedom``) with a fake clock whose ``wait`` is the
poll; the backend half runs the real worker thread with the poll interval
shortened. The placeholder key is read out of ``api.html`` here, never
spelled: ``test_hard_rules.py`` holds the literal and the leak check.
"""

from __future__ import annotations

import asyncio
import json
import stat
from pathlib import Path
from typing import Any

import pytest

import fakedom
from conftest import SGDB_HOME, SGDB_LOGIN, FakeBrowser, run
from moonlight_sync import cdp, sgdbpage
from moonlight_sync.keys import key_file_path

KEY = fakedom.evaluate(sgdbpage.JS_KEY, fakedom.Document.from_fixture("api.html"))
STEAM_HOSTS = {sgdbpage.SGDB_HOST, sgdbpage.STEAM_OPENID_HOST}


class Clock:
    """``fetch_key``'s ``stop`` and ``clock`` in one: ``wait`` advances time."""

    def __init__(self, *, cancel_after_waits: int | None = None) -> None:
        self.now = 0.0
        self.waits = 0
        self.cancelled = False
        self.cancel_after_waits = cancel_after_waits

    def __call__(self) -> float:
        return self.now

    def is_set(self) -> bool:
        return self.cancelled

    def set(self) -> None:
        self.cancelled = True

    def wait(self, timeout: float | None = None) -> bool:
        self.now += timeout or 0.0
        self.waits += 1
        if self.cancel_after_waits is not None and self.waits >= self.cancel_after_waits:
            self.cancelled = True
        return self.cancelled


def fetch(browser: FakeBrowser, clock: Clock | None = None) -> tuple[str | None, Any, list[str]]:
    """``(key, failure, states)`` of one fetch over ``browser``."""
    clock = clock or Clock()
    states: list[str] = []
    try:
        key = sgdbpage.fetch_key(browser.targets, browser.connect, clock, clock, states.append)
    except sgdbpage.FetchFailed as exc:
        return None, exc, states
    return key, None, states


def hosts_evaluated_in(browser: FakeBrowser) -> set[str]:
    return {sgdbpage.host_of(url) or "" for url, _ in browser.evaluated}


# ---------------------------------------------------------------------------
# the snippets over the fixtures (fakedom)


def test_key_snippet_reads_the_one_code_element() -> None:
    assert sgdbpage.KEY_RE.match(KEY)
    assert (
        fakedom.evaluate(sgdbpage.JS_KEY, fakedom.Document.from_fixture("api-no-key.html")) is None
    )
    # a code element that is not a key does not count (api-revoke-only has one)
    assert (
        fakedom.evaluate(sgdbpage.JS_KEY, fakedom.Document.from_fixture("api-revoke-only.html"))
        is None
    )


def test_key_snippet_answers_null_for_two_keys() -> None:
    html = (
        '<div class="profile"><p><code>0000000000000000000000000000000a</code></p>'
        "<p><code>0000000000000000000000000000000b</code></p></div>"
    )
    assert fakedom.evaluate(sgdbpage.JS_KEY, fakedom.Document.from_html(html)) is None


def test_login_link_snippet_finds_steams_anchor_only_on_the_login_page() -> None:
    link = fakedom.evaluate(sgdbpage.JS_LOGIN_LINK, fakedom.Document.from_fixture("login.html"))
    assert sgdbpage.login_link_ok(link)
    for name in ("openid.html", "api.html", "api-no-key.html", "api-revoke-only.html"):
        assert fakedom.evaluate(sgdbpage.JS_LOGIN_LINK, fakedom.Document.from_fixture(name)) is None


def test_openid_submit_clicks_the_openid_forms_button_and_no_other() -> None:
    document = fakedom.Document.from_fixture("openid.html")
    assert fakedom.evaluate(sgdbpage.JS_OPENID_FORM, document) is True
    assert fakedom.evaluate(sgdbpage.JS_OPENID_SUBMIT, document) is True
    assert [c.attrs.get("id") for c in document.clicks] == ["imageLogin"]
    form = document.query_selector("#openidForm")
    assert form is not None
    form.remove()
    assert fakedom.evaluate(sgdbpage.JS_OPENID_FORM, document) is False
    assert fakedom.evaluate(sgdbpage.JS_OPENID_SUBMIT, document) is False
    assert len(document.clicks) == 1  # the password form's submit was not touched


def test_generate_snippet_clicks_generate_and_never_revoke() -> None:
    document = fakedom.Document.from_fixture("api-no-key.html")
    assert fakedom.evaluate(sgdbpage.JS_GENERATE, document) is True
    assert [c.inner_text for c in document.clicks] == ["Generate API Key"]
    with_key = fakedom.Document.from_fixture("api.html")
    assert fakedom.evaluate(sgdbpage.JS_GENERATE, with_key) is False
    assert with_key.clicks == []


@pytest.mark.parametrize("js", fakedom.ALL_SNIPPETS)
def test_no_snippet_clicks_anything_on_the_revoke_only_page(js: str) -> None:
    """The rule: the only button is Revoke API Key (and a link that says
    both revoke and generate); every snippet clicks nothing."""
    document = fakedom.Document.from_fixture("api-revoke-only.html", sgdbpage.SGDB_API_PAGE)
    fakedom.evaluate(js, document)
    assert document.clicks == []


def test_every_snippet_guards_revoke_by_text() -> None:
    """Belt and braces for the mirror: the one snippet that clicks by text
    carries the literal exclusion, and no other snippet clicks by text."""
    assert "revoke" in sgdbpage.JS_GENERATE
    for js in fakedom.ALL_SNIPPETS:
        if js != sgdbpage.JS_GENERATE:
            assert "click" not in js or js == sgdbpage.JS_OPENID_SUBMIT


def test_login_link_ok_requires_steam_and_the_realm() -> None:
    good = "https://steamcommunity.com/openid/login?openid.realm=https%3A%2F%2Fwww.steamgriddb.com"
    assert sgdbpage.login_link_ok(good)
    assert not sgdbpage.login_link_ok(None)
    assert not sgdbpage.login_link_ok("https://steamcommunity.com/openid/login")
    assert not sgdbpage.login_link_ok(
        "https://steamcommunity.com/openid/login?openid.realm=https%3A%2F%2Fevil.example"
    )
    assert not sgdbpage.login_link_ok(
        "https://evil.example/openid/login?openid.realm=https%3A%2F%2Fwww.steamgriddb.com"
    )
    assert not sgdbpage.login_link_ok(
        "http://steamcommunity.com/openid/login?openid.realm=https%3A%2F%2Fwww.steamgriddb.com"
    )


def test_page_kind_and_the_target_filter() -> None:
    assert sgdbpage.page_kind(SGDB_LOGIN) == "login"
    assert sgdbpage.page_kind(SGDB_LOGIN + "/") == "login"
    assert sgdbpage.page_kind(SGDB_HOME + "login/steam?x=1") == "sgdb"
    assert sgdbpage.page_kind(sgdbpage.SGDB_API_PAGE) == "sgdb"
    assert sgdbpage.page_kind("https://steamcommunity.com/openid/login?x") == "steam"
    assert sgdbpage.page_kind("https://steamloopback.host/routes/externalweb") is None
    assert sgdbpage.page_kind("https://steamgriddb.com/") is None  # no www: not the measured host
    browser = FakeBrowser()
    assert sgdbpage.find_target(browser.targets()) is None
    browser.open_page()
    target = sgdbpage.find_target(browser.targets())
    assert target is not None and target["id"] == "BROWSER"


# ---------------------------------------------------------------------------
# the rows of the state table


def test_the_whole_flow_from_a_signed_out_browser() -> None:
    browser = FakeBrowser()
    browser.on_poll = lambda b: b.open_page() if b.polls == 3 else None
    key, failure, states = fetch(browser)
    assert failure is None
    assert key == KEY
    assert states == ["waiting", "login", "steam-sign-in", "reading", "done"]
    # the site's redirects, as the fake plays them: the API page bounced to
    # /login, the login link went to Steam, the submit returned home, then
    # the API page for real
    assert browser.clicks == ["Sign In"]
    assert browser.revoked is False
    assert hosts_evaluated_in(browser) <= STEAM_HOSTS


def test_waiting_ignores_iframes_and_the_other_targets() -> None:
    browser = FakeBrowser()
    browser.on_poll = lambda b: b.open_page() if b.polls == 4 else None
    key, failure, states = fetch(browser)
    assert failure is None and key == KEY
    assert states[0] == "waiting"
    assert all(ws.endswith("/BROWSER") for ws in browser.connected)
    assert browser.connected  # it did connect, to the browser only


def test_login_navigates_to_the_checked_link_once() -> None:
    browser = FakeBrowser()
    browser.open_page()
    assert browser.url == SGDB_LOGIN
    key, failure, _ = fetch(browser)
    assert failure is None and key == KEY
    navigations = [js for _, js in browser.evaluated if js.startswith("location.href")]
    assert len(navigations) == 2
    first, second = (json.loads(n[len("location.href = ") : -len("; true")]) for n in navigations)
    assert sgdbpage.login_link_ok(first)
    assert second == sgdbpage.SGDB_API_PAGE


def test_login_without_a_link_fails_login_changed() -> None:
    browser = FakeBrowser()
    browser.open_page()
    browser.answers[sgdbpage.JS_LOGIN_LINK] = None
    key, failure, states = fetch(browser)
    assert key is None
    assert (failure.code, failure.message) == ("sgdb-page", sgdbpage.TEXT_LOGIN_CHANGED)
    assert states == ["login"]
    assert browser.navigations == [sgdbpage.SGDB_API_PAGE]  # only the frontend's own


@pytest.mark.parametrize(
    "link",
    [
        "https://evil.example/openid/login?openid.realm=https%3A%2F%2Fwww.steamgriddb.com",
        "https://steamcommunity.com/openid/login?openid.realm=https%3A%2F%2Fevil.example",
        "https://steamcommunity.com/openid/login",
    ],
)
def test_login_with_a_link_elsewhere_fails_and_does_not_navigate(link: str) -> None:
    browser = FakeBrowser()
    browser.open_page()
    browser.answers[sgdbpage.JS_LOGIN_LINK] = link
    _, failure, _ = fetch(browser)
    assert (failure.code, failure.message) == ("sgdb-page", sgdbpage.TEXT_LOGIN_CHANGED)
    assert not any(js.startswith("location.href") for _, js in browser.evaluated)


def test_steam_sign_in_submits_once() -> None:
    browser = FakeBrowser()
    browser.open_page()
    _, failure, states = fetch(browser)
    assert failure is None
    assert browser.clicks == ["Sign In"]
    assert sum(1 for _, js in browser.evaluated if js == sgdbpage.JS_OPENID_SUBMIT) == 1
    assert "steam-sign-in" in states and "steam-login" not in states


def test_steam_login_waits_for_the_form_then_submits_once() -> None:
    browser = FakeBrowser(steam_needs_password=True)
    browser.open_page()

    def on_poll(b: FakeBrowser) -> None:
        if b.polls == 6:
            b.steam_logged_in()

    browser.on_poll = on_poll
    key, failure, states = fetch(browser)
    assert failure is None and key == KEY
    assert states == ["login", "steam-sign-in", "steam-login", "steam-sign-in", "reading", "done"]
    submits = [js for _, js in browser.evaluated if js == sgdbpage.JS_OPENID_SUBMIT]
    assert len(submits) == 2  # the first answered false (no form), the second clicked
    assert browser.clicks == ["Sign In"]
    # while waiting, only the form's presence was polled
    polled = [js for _, js in browser.evaluated if js == sgdbpage.JS_OPENID_FORM]
    assert len(polled) >= 2


def test_reading_navigates_from_another_page_to_the_api_page_once() -> None:
    browser = FakeBrowser(signed_in=True)
    browser.open_page(SGDB_HOME)
    key, failure, states = fetch(browser)
    assert failure is None and key == KEY
    assert states == ["reading", "done"]
    assert browser.navigations == [SGDB_HOME, sgdbpage.SGDB_API_PAGE]


def test_reading_waits_for_the_api_page_to_be_complete() -> None:
    browser = FakeBrowser(signed_in=True, loading_polls=2)
    browser.open_page()
    key, failure, _ = fetch(browser)
    assert failure is None and key == KEY
    key_polls = [js for _, js in browser.evaluated if js == sgdbpage.JS_KEY]
    page_polls = [js for _, js in browser.evaluated if js == sgdbpage.JS_PAGE]
    assert len(key_polls) == 1 and len(page_polls) == 3


def test_reading_generates_a_key_once_when_there_is_none() -> None:
    browser = FakeBrowser(signed_in=True, has_key=False)
    browser.open_page()
    clock = Clock()
    key, failure, states = fetch(browser, clock)
    assert failure is None and key == KEY
    assert browser.clicks == ["Generate API Key"]
    assert browser.revoked is False
    assert states == ["reading", "done"]


def test_reading_fails_no_key_when_there_is_no_generate_button() -> None:
    browser = FakeBrowser(signed_in=True, api_fixture="api-revoke-only.html")
    browser.open_page()
    _, failure, _ = fetch(browser)
    assert (failure.code, failure.message) == ("sgdb-page", sgdbpage.TEXT_NO_KEY)
    assert browser.clicks == []
    assert browser.revoked is False


def test_reading_fails_no_key_when_generate_shows_none_within_fifteen_seconds() -> None:
    browser = FakeBrowser(signed_in=True, has_key=False)
    browser.open_page()
    browser.answers[sgdbpage.JS_KEY] = None  # the page never shows one
    clock = Clock()
    _, failure, _ = fetch(browser, clock)
    assert (failure.code, failure.message) == ("sgdb-page", sgdbpage.TEXT_NO_KEY)
    generates = [js for _, js in browser.evaluated if js == sgdbpage.JS_GENERATE]
    assert len(generates) == 1
    assert sgdbpage.GENERATE_WAIT_S <= clock.now < sgdbpage.GENERATE_WAIT_S + 2


def test_reading_fails_page_changed_on_a_key_that_is_not_one() -> None:
    browser = FakeBrowser(signed_in=True)
    browser.open_page()
    browser.answers[sgdbpage.JS_KEY] = "not a key"
    _, failure, _ = fetch(browser)
    assert (failure.code, failure.message) == ("sgdb-page", sgdbpage.TEXT_PAGE_CHANGED)


# ---------------------------------------------------------------------------
# the failures


def test_no_debugger_at_the_first_poll() -> None:
    browser = FakeBrowser()
    browser.unavailable = True
    _, failure, states = fetch(browser)
    assert (failure.code, failure.message) == ("no-debugger", sgdbpage.TEXT_NO_DEBUGGER)
    assert states == []


def test_a_debugger_that_drops_out_later_is_retried_for_ten_seconds() -> None:
    browser = FakeBrowser()
    browser.open_page()

    def on_poll(b: FakeBrowser) -> None:
        b.unavailable = b.polls >= 3

    browser.on_poll = on_poll
    clock = Clock()
    _, failure, states = fetch(browser, clock)
    assert failure.code == "no-debugger"
    assert "login" in states
    assert sgdbpage.DEBUGGER_RETRY_S <= clock.now < sgdbpage.DEBUGGER_RETRY_S + 2


def test_a_debugger_that_comes_back_within_ten_seconds_continues() -> None:
    browser = FakeBrowser()
    browser.open_page()

    def on_poll(b: FakeBrowser) -> None:
        b.unavailable = 3 <= b.polls <= 8

    browser.on_poll = on_poll
    key, failure, _ = fetch(browser)
    assert failure is None and key == KEY


def test_timeout_after_three_minutes_of_waiting() -> None:
    browser = FakeBrowser()  # the browser never opens
    clock = Clock()
    _, failure, states = fetch(browser, clock)
    assert (failure.code, failure.message) == ("timeout", sgdbpage.TEXT_TIMEOUT)
    assert states == ["waiting"]
    assert sgdbpage.SGDB_FETCH_TIMEOUT_S <= clock.now < sgdbpage.SGDB_FETCH_TIMEOUT_S + 1
    assert clock.waits == int(sgdbpage.SGDB_FETCH_TIMEOUT_S / sgdbpage.POLL_INTERVAL_S)


def test_cancelled_mid_waiting() -> None:
    browser = FakeBrowser()
    clock = Clock(cancel_after_waits=3)
    _, failure, states = fetch(browser, clock)
    assert (failure.code, failure.message) == ("cancelled", sgdbpage.TEXT_CANCELLED)
    assert states == ["waiting"]
    assert clock.waits == 3


def test_cancelled_mid_steam_login() -> None:
    browser = FakeBrowser(steam_needs_password=True)
    browser.open_page()
    clock = Clock(cancel_after_waits=6)
    _, failure, states = fetch(browser, clock)
    assert failure.code == "cancelled"
    assert states[-1] == "steam-login"
    assert browser.clicks == []


def test_cancelled_before_the_first_poll() -> None:
    browser = FakeBrowser()
    clock = Clock()
    clock.set()
    _, failure, states = fetch(browser, clock)
    assert failure.code == "cancelled"
    assert browser.polls == 0 and states == []


def test_an_evaluate_error_fails_page_changed() -> None:
    browser = FakeBrowser()
    browser.open_page()
    browser.answers[sgdbpage.JS_LOGIN_LINK] = cdp.EvaluateError("TypeError: boom")
    _, failure, _ = fetch(browser)
    assert (failure.code, failure.message) == ("sgdb-page", sgdbpage.TEXT_PAGE_CHANGED)
    assert "boom" in failure.detail


# ---------------------------------------------------------------------------
# the rules


def test_one_click_each_a_second_visit_to_login_fails() -> None:
    """Steam's return bounces back to /login (a redirect loop): no second
    navigation, a failure instead."""
    browser = FakeBrowser()
    browser.open_page()
    original = browser.navigate

    def navigate(url: str) -> None:
        if url.startswith(SGDB_HOME + "login/steam"):
            original(SGDB_LOGIN)  # the sign-in did not take
        else:
            original(url)

    browser.navigate = navigate  # type: ignore[method-assign]
    _, failure, states = fetch(browser)
    assert failure.code == "sgdb-page"
    assert states == ["login", "steam-sign-in", "login"]
    navigations = [js for _, js in browser.evaluated if js.startswith("location.href")]
    assert len(navigations) == 1
    assert browser.clicks == ["Sign In"]


def test_one_click_each_a_second_visit_to_steam_fails() -> None:
    browser = FakeBrowser()
    browser.open_page()
    original = browser.navigate

    def navigate(url: str) -> None:
        # signed in and asked for the API page, the site sends the browser
        # to Steam once more (a second visit to steam-sign-in)
        if url == sgdbpage.SGDB_API_PAGE and browser.signed_in:
            original("https://steamcommunity.com/openid/login?again=1")
        else:
            original(url)

    browser.navigate = navigate  # type: ignore[method-assign]
    _, failure, states = fetch(browser)
    assert failure.code == "sgdb-page"
    assert states == ["login", "steam-sign-in", "reading"]
    assert browser.clicks == ["Sign In"]  # one submit, never a second


def test_only_steamgriddbs_own_targets_are_evaluated_in() -> None:
    browser = FakeBrowser()
    browser.on_poll = lambda b: b.open_page() if b.polls == 2 else None
    key, failure, _ = fetch(browser)
    assert failure is None and key == KEY
    assert hosts_evaluated_in(browser) <= STEAM_HOSTS
    assert all(ws.endswith("/BROWSER") for ws in browser.connected)


def test_a_session_is_closed_after_every_poll() -> None:
    browser = FakeBrowser(signed_in=True)
    browser.open_page()
    fetch(browser)
    assert browser.closed_sessions == len(browser.connected) >= 1


def test_navigate_urls_are_only_the_api_page_or_the_checked_link() -> None:
    browser = FakeBrowser()
    browser.open_page()
    fetch(browser)
    for _, js in browser.evaluated:
        if js.startswith("location.href"):
            url = json.loads(js[len("location.href = ") : -len("; true")])
            assert url == sgdbpage.SGDB_API_PAGE or sgdbpage.login_link_ok(url)


def test_states_and_failures_never_carry_the_key() -> None:
    browser = FakeBrowser()
    browser.open_page()
    key, failure, states = fetch(browser)
    assert key == KEY
    assert KEY not in json.dumps(states)
    browser = FakeBrowser(signed_in=True)
    browser.open_page()
    browser.answers[sgdbpage.JS_GENERATE] = cdp.EvaluateError(f"leaked {KEY}")
    browser.answers[sgdbpage.JS_KEY] = None
    _, failure, _ = fetch(browser)
    assert KEY not in failure.message and KEY not in str(failure)


# ---------------------------------------------------------------------------
# the backend: the thread, the events, the key file


@pytest.fixture
def fast_polls(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sgdbpage, "POLL_INTERVAL_S", 0.01)
    monkeypatch.setattr(sgdbpage, "DEBUGGER_RETRY_S", 0.2)


async def wait_done(backend: Any, timeout: float = 5.0) -> dict[str, Any]:
    deadline = asyncio.get_running_loop().time() + timeout
    while not backend.emitted.of("sgdb_key_done"):
        assert asyncio.get_running_loop().time() < deadline, "no sgdb_key_done"
        await asyncio.sleep(0.01)
    fetch = backend._key_fetch
    if fetch is not None and fetch.task is not None:
        await fetch.task
    return backend.emitted.of("sgdb_key_done")[-1]


def test_backend_fetches_and_writes_the_key_file(backend, fake_browser, fast_polls) -> None:
    browser = fake_browser()

    async def scenario():
        started = await backend.start_sgdb_key_fetch()
        assert started["ok"] is True
        await asyncio.sleep(0.05)  # a few polls of nothing
        browser.open_page()  # what the frontend does next
        done = await wait_done(backend)
        return started, done, await backend.sgdb_key_state()

    started, done, state = run(scenario())
    assert done == {"ok": True, "source": "file", "hint": KEY[-4:]}
    assert state["source"] == "file" and state["hint"] == KEY[-4:]
    path = Path(key_file_path(backend.home))
    assert path.read_text() == KEY + "\n"
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    events = [e["state"] for e in backend.emitted.of("sgdb_key_event")]
    assert events == ["waiting", "login", "steam-sign-in", "reading", "done"]
    names = [name for name, _ in backend.emitted.calls]
    assert names[-1] == "sgdb_key_done" and names.count("sgdb_key_done") == 1
    assert browser.revoked is False
    log = run(backend.log_tail(100))["lines"]
    assert any("sgdb key fetched from the browser" in line for line in log)


def test_backend_busy_while_a_fetch_is_in_flight(backend, fake_browser, fast_polls) -> None:
    fake_browser()  # never opens: the fetch waits until cancelled

    async def scenario():
        first = await backend.start_sgdb_key_fetch()
        second = await backend.start_sgdb_key_fetch()
        cancelled = await backend.cancel_sgdb_key_fetch()
        done = await wait_done(backend)
        again = await backend.cancel_sgdb_key_fetch()
        return first, second, cancelled, done, again

    first, second, cancelled, done, again = run(scenario())
    assert first["ok"] is True
    assert second == {
        "ok": False,
        "error": "busy",
        "message": "A key fetch is already in progress",
        "kind": "key",
    }
    assert cancelled == {"ok": True, "running": True}
    assert done == {"ok": False, "error": "cancelled", "message": sgdbpage.TEXT_CANCELLED}
    assert again == {"ok": True, "running": False}
    assert not Path(key_file_path(backend.home)).exists()


def test_backend_no_debugger_comes_back_from_start(backend, fake_browser) -> None:
    browser = fake_browser()
    browser.unavailable = True
    result = run(backend.start_sgdb_key_fetch())
    assert result == {
        "ok": False,
        "error": "no-debugger",
        "message": sgdbpage.TEXT_NO_DEBUGGER,
    }
    assert backend.emitted.calls == []

    async def again():
        # the guard is free again
        browser.unavailable = False
        started = await backend.start_sgdb_key_fetch()
        await backend.unload()
        return started

    assert run(again())["ok"] is True


def test_backend_unload_cancels_the_fetch(backend, fake_browser, fast_polls) -> None:
    fake_browser()

    async def scenario():
        assert (await backend.start_sgdb_key_fetch())["ok"] is True
        await asyncio.sleep(0.05)
        await backend.unload()
        return backend.emitted.of("sgdb_key_done")

    done = run(scenario())
    assert done == [{"ok": False, "error": "cancelled", "message": sgdbpage.TEXT_CANCELLED}]
    assert backend._key_fetch.done is True


def test_backend_a_refused_key_is_the_fetchs_failure(backend, fake_browser, fast_polls) -> None:
    """keys.set_key's own refusal (a key in config.toml) ends the fetch; no
    file is written."""
    browser = fake_browser(signed_in=True)
    config = Path(backend.home) / ".config" / "moonlight-steam-sync" / "config.toml"
    config.parent.mkdir(parents=True)
    config.write_text('[steamgriddb]\napi_key = "ffffffffffffffffffffffffffffffff"\n')

    async def scenario():
        assert (await backend.start_sgdb_key_fetch())["ok"] is True
        browser.open_page()
        return await wait_done(backend)

    done = run(scenario())
    assert done == {"ok": False, "error": "bad-request", "message": "set in config.toml"}
    assert not Path(key_file_path(backend.home)).exists()


def test_backend_a_page_failure_is_reported_and_writes_nothing(
    backend, fake_browser, fast_polls
) -> None:
    browser = fake_browser(signed_in=True, api_fixture="api-revoke-only.html")

    async def scenario():
        assert (await backend.start_sgdb_key_fetch())["ok"] is True
        browser.open_page()
        return await wait_done(backend)

    done = run(scenario())
    assert done == {"ok": False, "error": "sgdb-page", "message": sgdbpage.TEXT_NO_KEY}
    assert not Path(key_file_path(backend.home)).exists()
    assert browser.revoked is False


@pytest.mark.scenario("full-sync")
def test_backend_fetch_is_not_under_the_runs_busy_guard(
    backend, fake_browser, fast_polls, steam_gone
) -> None:
    """Decision 62: a fetch may start during a sync, and a sync during a fetch."""
    browser = fake_browser(signed_in=True)
    assert run(backend.write_owned_apps(12345678, {"2379780": "Balatro"}))["ok"]

    async def scenario():
        started = await backend.start_sgdb_key_fetch()
        sync = await backend.start_sync()
        steam_gone()
        browser.open_page()
        done = await wait_done(backend)
        await backend.wait_for_run()
        return started, sync, done

    started, sync, done = run(scenario())
    assert started["ok"] is True and sync["ok"] is True
    assert done["ok"] is True
    assert run(backend.sync_state())["last_exit"] == 0


@pytest.mark.scenario("full-sync")
def test_backend_a_fetch_may_start_during_a_sync(backend, fake_browser, fast_polls, steam_gone):
    browser = fake_browser(signed_in=True)
    assert run(backend.write_owned_apps(12345678, {"2379780": "Balatro"}))["ok"]

    async def scenario():
        sync = await backend.start_sync()
        started = await backend.start_sgdb_key_fetch()
        browser.open_page()
        done = await wait_done(backend)
        steam_gone()
        await backend.wait_for_run()
        return sync, started, done

    sync, started, done = run(scenario())
    assert sync["ok"] is True and started["ok"] is True and done["ok"] is True
