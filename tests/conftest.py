"""Shared fixtures: a Backend over tests/fake_cli.py, and the install sandbox.

- ``backend``      a started :class:`Backend` over the fake CLI (``common/``
  fixtures unless the test is marked ``@pytest.mark.scenario("full-sync")``,
  which puts that scenario's directory in front of ``common/``), with
  ``tmp_path`` settings/log/plugin dirs, ``home=tmp_path/"home"`` and a
  recording ``emit`` (``backend.emitted``).
- ``make_backend`` the same, as a factory taking ``Backend`` keyword
  overrides, ``env`` additions and ``start=False``.
- ``steam_gone``   creates ``FAKE_CLI_STEAM_GONE_FILE`` ("the client exited").
- ``install_env``  a fake ``~/.local/bin``, a fake bundled ``.pyz`` and a
  ``python3`` shim that prints the first line of the file it is asked to
  run, so "older installed" is ``install_env.installed("... 0.2.0")``.
- ``fake_browser`` a :class:`FakeBrowser` installed as ``cdp.TARGETS`` /
  ``cdp.CONNECT`` (spec 3.20): the Game Mode browser as the seams see it,
  serving ``tests/fixtures/sgdb`` through ``tests/fakedom.py``, so no test
  opens a socket to a debugger.

pytest-asyncio is not used: async callables are driven with :func:`run`.
"""

from __future__ import annotations

import asyncio
import json
import os
import stat
import sys
import urllib.parse
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "py_modules"))

import fakedom  # noqa: E402
from moonlight_sync import cdp, sgdbpage  # noqa: E402
from moonlight_sync.backend import Backend  # noqa: E402

FAKE_CLI = ROOT / "tests" / "fake_cli.py"
FIXTURES = ROOT / "tests" / "fixtures"
STUBS = ROOT / "tests" / "stubs"


def run(coro: Any) -> Any:
    """Drive one coroutine to completion (a fresh event loop each time)."""
    return asyncio.run(coro)


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line(
        "markers", "scenario(name): put tests/fixtures/<name> in front of common/"
    )


class Recorder:
    """A recording stand-in for ``decky.emit``."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.hooks: list[Callable[[str, dict[str, Any]], Any]] = []

    async def __call__(self, name: str, payload: dict[str, Any]) -> None:
        self.calls.append((name, payload))
        for hook in self.hooks:
            result = hook(name, payload)
            if asyncio.iscoroutine(result):
                await result

    def of(self, name: str) -> list[dict[str, Any]]:
        return [payload for event, payload in self.calls if event == name]

    def relayed(self) -> list[dict[str, Any]]:
        """The CLI events relayed as ``sync_event``, in order."""
        return [payload["event"] for payload in self.of("sync_event")]


def base_env(tmp_path: Path, scenario: str | None) -> dict[str, str]:
    # The host's own library path stays out, so the tests that set one (the
    # plugin_loader cases) do not depend on the shell pytest was run from.
    # PYTHONUNBUFFERED likewise: the fake CLI must only see the one the backend
    # sets (`Backend._child_env`), or a shell that exports it hides a regression.
    dropped = {"SGDB_API_KEY", "LD_LIBRARY_PATH", "LD_LIBRARY_PATH_ORIG", "PYTHONUNBUFFERED"}
    env = {
        key: value
        for key, value in os.environ.items()
        if not key.startswith("FAKE_CLI_") and key not in dropped
    }
    dirs = [str(FIXTURES / scenario)] if scenario else []
    dirs.append(str(FIXTURES / "common"))
    env.update(
        FAKE_CLI_FIXTURES=os.pathsep.join(dirs),
        FAKE_CLI_ARGV_LOG=str(tmp_path / "argv.jsonl"),
        FAKE_CLI_STEAM_GONE_FILE=str(tmp_path / "steam-gone"),
        FAKE_CLI_WAIT_S="5",
    )
    return env


def read_argv_log(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


class Harness:
    """What ``make_backend`` hands back besides the backend itself."""

    def __init__(self, tmp_path: Path) -> None:
        self.tmp_path = tmp_path
        self.argv_log = tmp_path / "argv.jsonl"

    def argv(self) -> list[list[str]]:
        return [entry["argv"] for entry in read_argv_log(self.argv_log)]

    def invocations(self) -> list[dict[str, Any]]:
        return read_argv_log(self.argv_log)

    def clear(self) -> None:
        if self.argv_log.exists():
            self.argv_log.unlink()


@pytest.fixture
def make_backend(tmp_path: Path, request: pytest.FixtureRequest) -> Callable[..., Backend]:
    marker = request.node.get_closest_marker("scenario")
    scenario = marker.args[0] if marker else None

    def factory(*, start: bool = True, env: dict[str, str] | None = None, **kwargs: Any) -> Backend:
        full_env = base_env(tmp_path, scenario)
        full_env.update(env or {})
        home = tmp_path / "home"
        home.mkdir(exist_ok=True)
        recorder = Recorder()
        options: dict[str, Any] = dict(
            settings_dir=str(tmp_path / "settings"),
            log_dir=str(tmp_path / "logs"),
            plugin_dir=str(tmp_path / "plugin"),
            home=str(home),
            plugin_version="0.1.0",
            emit=recorder,
            cli=[sys.executable, str(FAKE_CLI)],
            env=full_env,
        )
        options.update(kwargs)
        backend = Backend(**options)
        backend.emitted = recorder  # type: ignore[attr-defined]
        backend.harness = Harness(tmp_path)  # type: ignore[attr-defined]
        if start:
            run(backend.startup())
        return backend

    return factory


@pytest.fixture
def backend(make_backend: Callable[..., Backend]) -> Backend:
    return make_backend()


@pytest.fixture
def steam_gone(tmp_path: Path) -> Callable[[], None]:
    def create() -> None:
        (tmp_path / "steam-gone").write_text("gone\n")

    return create


class InstallEnv:
    """A sandbox for install.py: ~/.local/bin, a bundled .pyz, a python3 shim."""

    def __init__(self, tmp_path: Path) -> None:
        self.home = tmp_path / "home"
        self.plugin_dir = tmp_path / "plugin"
        self.home.mkdir(parents=True, exist_ok=True)
        (self.plugin_dir / "bin").mkdir(parents=True, exist_ok=True)
        self.installed_path = self.home / ".local" / "bin" / "moonlight-steam-sync"
        self.bundled_path = self.plugin_dir / "bin" / "moonlight-steam-sync.pyz"
        self.python = tmp_path / "python3"
        self.python.write_text(
            f"#!{sys.executable}\n"
            "import sys\n"
            "if len(sys.argv) < 3 or sys.argv[2] != '--version':\n"
            "    sys.exit(2)\n"
            "try:\n"
            "    text = open(sys.argv[1]).read().splitlines()\n"
            "except OSError:\n"
            "    sys.exit(1)\n"
            "if not text or text[0] == 'CRASH':\n"
            "    sys.exit(1)\n"
            "print(text[0])\n"
        )
        self.python.chmod(self.python.stat().st_mode | stat.S_IXUSR)

    def bundled(self, version_line: str) -> Path:
        self.bundled_path.write_text(version_line + "\n# bundled payload\n")
        return self.bundled_path

    def installed(self, version_line: str) -> Path:
        self.installed_path.parent.mkdir(parents=True, exist_ok=True)
        self.installed_path.write_text(version_line + "\n# installed payload\n")
        self.installed_path.chmod(0o755)
        return self.installed_path


@pytest.fixture
def install_env(tmp_path: Path) -> InstallEnv:
    return InstallEnv(tmp_path)


# ---------------------------------------------------------------------------
# the Game Mode browser, as cdp.TARGETS / cdp.CONNECT see it (spec 3.20)

SGDB_HOME = f"https://{sgdbpage.SGDB_HOST}/"
SGDB_LOGIN = f"https://{sgdbpage.SGDB_HOST}{sgdbpage.SGDB_LOGIN_PATH}"
SGDB_OPENID_RETURN = f"https://{sgdbpage.SGDB_HOST}/login/steam"
BROWSER_WS = "ws://127.0.0.1:8080/devtools/page/BROWSER"

#: What Steam's debugger always lists besides the browser (spec 3.20.1 item
#: 1): the plugin's own context, Big Picture and the popups. None of them
#: may ever be evaluated in.
OTHER_TARGETS: list[cdp.Target] = [
    cdp.Target(
        id="SHARED",
        type="page",
        title="SharedJSContext",
        url="https://steamloopback.host/routes/externalweb",
        webSocketDebuggerUrl="ws://127.0.0.1:8080/devtools/page/SHARED",
    ),
    cdp.Target(
        id="BPM",
        type="page",
        title="Steam Big Picture Mode",
        url="https://steamloopback.host/routes/library/home",
        webSocketDebuggerUrl="ws://127.0.0.1:8080/devtools/page/BPM",
    ),
    cdp.Target(
        id="QAM",
        type="page",
        title="QuickAccess",
        url="https://steamloopback.host/routes/quickaccess",
        webSocketDebuggerUrl="ws://127.0.0.1:8080/devtools/page/QAM",
    ),
]

_HOME_HTML = (
    "<!DOCTYPE html><html><head><title>Home - SteamGridDB</title></head>"
    '<body><div class="container"><h1>Home</h1></div></body></html>'
)


class FakeSession:
    """``cdp.Session``'s interface over the fake browser's current page."""

    def __init__(self, browser: FakeBrowser, ws_url: str) -> None:
        self.browser = browser
        self.ws_url = ws_url
        self.closed = False

    def evaluate(self, js: str, *, timeout: float = 10.0) -> Any:
        assert not self.closed, "evaluate after close"
        return self.browser.evaluate(js)

    def close(self) -> None:
        self.closed = True
        self.browser.closed_sessions += 1


class FakeBrowser:
    """The Game Mode browser: one page target once ``open_page`` ran, plus the
    targets Steam always has, and ad ``iframe`` targets beside the page.

    ``targets()`` and ``connect()`` are the two seams. A session's
    ``evaluate`` runs the snippet's mirror (``fakedom.evaluate``) over the
    current page's fixture DOM, then acts on what the page did: a
    navigation moves the browser (through the site's redirects: the API
    page needs a sign-in, Steam's return lands on the home page), the
    OpenID submit signs in, *Generate* gives the account a key, *Revoke* is
    recorded and must never happen. ``answers`` scripts one snippet's
    answer (a value, or an exception to raise) ahead of the mirror.
    """

    def __init__(
        self,
        *,
        signed_in: bool = False,
        has_key: bool = True,
        steam_needs_password: bool = False,
        api_fixture: str | None = None,
        loading_polls: int = 0,
    ) -> None:
        self.signed_in = signed_in
        self.has_key = has_key
        self.steam_needs_password = steam_needs_password
        self.api_fixture = api_fixture
        self.loading_polls = loading_polls
        self.url: str | None = None
        self.document: fakedom.Document | None = None
        self._loads_left = 0
        self.polls = 0
        self.connected: list[str] = []
        self.closed_sessions = 0
        self.evaluated: list[tuple[str, str]] = []
        self.navigations: list[str] = []
        self.clicks: list[str] = []
        self.revoked = False
        self.answers: dict[str, Any] = {}
        self.on_poll: Callable[[FakeBrowser], None] | None = None
        self.other_targets: list[cdp.Target] = list(OTHER_TARGETS)
        self.unavailable = False

    # -- the seams -------------------------------------------------------

    def targets(self) -> list[cdp.Target]:
        self.polls += 1
        if self.on_poll is not None:
            self.on_poll(self)
        if self.unavailable:
            raise cdp.DebuggerUnavailable("connection refused")
        listed = list(self.other_targets)
        if self.url is not None:
            assert self.document is not None
            listed.append(
                cdp.Target(
                    id="BROWSER",
                    type="page",
                    title=self.document.title,
                    url=self.url,
                    webSocketDebuggerUrl=BROWSER_WS,
                )
            )
            for index in (1, 2):
                listed.append(
                    cdp.Target(
                        id=f"AD{index}",
                        type="iframe",
                        title="ad",
                        url=f"https://ads.example.invalid/slot/{index}",
                        webSocketDebuggerUrl=f"ws://127.0.0.1:8080/devtools/page/AD{index}",
                    )
                )
        return listed

    def connect(self, ws_url: str) -> FakeSession:
        self.connected.append(ws_url)
        if self.unavailable:
            raise cdp.DebuggerUnavailable("connection refused")
        return FakeSession(self, ws_url)

    def install(self, monkeypatch: pytest.MonkeyPatch) -> FakeBrowser:
        monkeypatch.setattr(cdp, "TARGETS", self.targets)
        monkeypatch.setattr(cdp, "CONNECT", self.connect)
        return self

    # -- the browser -----------------------------------------------------

    def open_page(self, url: str = sgdbpage.SGDB_API_PAGE) -> None:
        """What the frontend does right after ``start_sgdb_key_fetch``."""
        self.navigate(url)

    def close_browser(self) -> None:
        self.url = None
        self.document = None

    def navigate(self, url: str) -> None:
        self.navigations.append(url)
        self._loads_left = self.loading_polls
        parts = urllib.parse.urlsplit(url)
        if parts.hostname == sgdbpage.STEAM_OPENID_HOST:
            self._show(url, self._openid_document())
            return
        if parts.hostname != sgdbpage.SGDB_HOST:
            self._show(url, fakedom.Document.from_html(_HOME_HTML, url))
            return
        path = parts.path.rstrip("/") or "/"
        if path == "/login/steam":
            self.signed_in = True
            self._show(SGDB_HOME, fakedom.Document.from_html(_HOME_HTML, SGDB_HOME))
        elif path == sgdbpage.SGDB_LOGIN_PATH:
            self._show(url, fakedom.Document.from_fixture("login.html", url))
        elif path == sgdbpage.SGDB_API_PATH:
            if not self.signed_in:
                self._show(SGDB_LOGIN, fakedom.Document.from_fixture("login.html", SGDB_LOGIN))
            else:
                fixture = self.api_fixture or ("api.html" if self.has_key else "api-no-key.html")
                self._show(url, fakedom.Document.from_fixture(fixture, url))
        else:
            self._show(url, fakedom.Document.from_html(_HOME_HTML, url))

    def _openid_document(self) -> fakedom.Document:
        document = fakedom.Document.from_fixture("openid.html", "https://steamcommunity.com/openid/login")
        if self.steam_needs_password:
            form = document.query_selector("#openidForm")
            assert form is not None
            form.remove()
        return document

    def steam_logged_in(self) -> None:
        """The user typed their Steam password on the page: the form appears."""
        self.steam_needs_password = False
        if self.url is not None and self.url.startswith("https://steamcommunity.com/"):
            self._show(self.url, self._openid_document())

    def _show(self, url: str, document: fakedom.Document) -> None:
        self.url = url
        self.document = document
        document.location._href = url

    def evaluate(self, js: str) -> Any:
        assert self.url is not None and self.document is not None, "no page open"
        self.evaluated.append((self.url, js))
        for snippet, answer in self.answers.items():
            if js == snippet:
                if isinstance(answer, BaseException):
                    raise answer
                return answer
        document = self.document
        if js == sgdbpage.JS_PAGE:
            if self._loads_left > 0:
                self._loads_left -= 1
                document.ready_state = "loading"
            else:
                document.ready_state = "complete"
        value = fakedom.evaluate(js, document)
        for element in document.clicks:
            self._clicked(element)
        document.clicks.clear()
        for url in document.navigations:
            self.navigate(url)
        document.navigations.clear()
        return value

    def _clicked(self, element: fakedom.Element) -> None:
        text = element.inner_text or element.value
        self.clicks.append(text)
        if "revoke" in text.lower():
            self.revoked = True
        elif element.attrs.get("id") == "imageLogin":
            self.navigate(SGDB_OPENID_RETURN + "?openid.mode=id_res")
        elif "generate" in text.lower():
            self.has_key = True
            self.navigate(sgdbpage.SGDB_API_PAGE)


@pytest.fixture
def fake_browser(monkeypatch: pytest.MonkeyPatch) -> Callable[..., FakeBrowser]:
    """A :class:`FakeBrowser` factory that installs each one as the seams."""

    def factory(**kwargs: Any) -> FakeBrowser:
        return FakeBrowser(**kwargs).install(monkeypatch)

    return factory
