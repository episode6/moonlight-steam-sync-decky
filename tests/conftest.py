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

pytest-asyncio is not used: async callables are driven with :func:`run`.
"""

from __future__ import annotations

import asyncio
import json
import os
import stat
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "py_modules"))

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
