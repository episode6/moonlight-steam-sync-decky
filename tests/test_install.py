"""The bundled CLI's install/upgrade into ~/.local/bin (spec 3.6.1)."""

from __future__ import annotations

import os
import stat
import sys

import pytest

from conftest import FAKE_CLI, run
from moonlight_sync import install
from moonlight_sync.backend import Backend


def ensure(env):
    return install.ensure_installed(str(env.python), str(env.bundled_path), str(env.installed_path))


def test_missing_installed_is_copied(install_env) -> None:
    install_env.bundled("moonlight-steam-sync.pyz 0.4.0")
    assert not install_env.installed_path.parent.exists()  # ~/.local/bin is created
    report = ensure(install_env)
    assert report.action == "installed"
    assert report.error is None
    assert report.bundled == (0, 4, 0)
    assert report.installed == (0, 4, 0)
    assert install_env.installed_path.read_bytes() == install_env.bundled_path.read_bytes()
    assert stat.S_IMODE(install_env.installed_path.stat().st_mode) == 0o755
    assert not os.path.exists(str(install_env.installed_path) + ".tmp")


def test_older_installed_is_replaced_atomically(install_env, monkeypatch) -> None:
    install_env.bundled("moonlight-steam-sync.pyz 0.4.0")
    install_env.installed("moonlight-steam-sync 0.2.0")
    calls = []
    real_replace = os.replace

    def spy(src, dst):
        calls.append((src, dst))
        return real_replace(src, dst)

    monkeypatch.setattr(install.os, "replace", spy)
    report = ensure(install_env)
    assert report.action == "upgraded"
    assert report.installed == (0, 4, 0)
    assert calls == [(str(install_env.installed_path) + ".tmp", str(install_env.installed_path))]
    assert install_env.installed_path.read_bytes() == install_env.bundled_path.read_bytes()
    assert stat.S_IMODE(install_env.installed_path.stat().st_mode) == 0o755


def test_newer_installed_is_untouched(install_env) -> None:
    install_env.bundled("moonlight-steam-sync.pyz 0.4.0")
    install_env.installed("moonlight-steam-sync 0.4.1")
    before = install_env.installed_path.read_bytes()
    report = ensure(install_env)
    assert report.action == "kept"
    assert report.installed == (0, 4, 1)
    assert install_env.installed_path.read_bytes() == before


def test_same_version_is_untouched(install_env) -> None:
    install_env.bundled("moonlight-steam-sync.pyz 0.4.0")
    install_env.installed("moonlight-steam-sync 0.4.0")
    before = install_env.installed_path.read_bytes()
    assert ensure(install_env).action == "kept"
    assert install_env.installed_path.read_bytes() == before


def test_unreadable_bundle_is_an_error_and_nothing_is_replaced(install_env) -> None:
    install_env.bundled("CRASH")  # the bundle runs but reports no version
    install_env.installed("moonlight-steam-sync 0.2.0")
    before = install_env.installed_path.read_bytes()
    report = ensure(install_env)
    assert report.action == "failed"
    assert "did not report a version" in (report.error or "")
    assert install_env.installed_path.read_bytes() == before


@pytest.mark.skipif(os.geteuid() == 0, reason="root can read a 000 file")
def test_bundle_without_read_permission(install_env) -> None:
    install_env.bundled("moonlight-steam-sync.pyz 0.4.0").chmod(0)
    try:
        report = ensure(install_env)
    finally:
        install_env.bundled_path.chmod(0o644)
    assert report.action == "failed"
    assert "not readable" in (report.error or "")
    assert not install_env.installed_path.exists()


@pytest.mark.skipif(os.geteuid() == 0, reason="root can write a read-only directory")
def test_copy_failure_leaves_installed_alone(install_env) -> None:
    install_env.bundled("moonlight-steam-sync.pyz 0.4.0")
    install_env.installed("moonlight-steam-sync 0.2.0")
    before = install_env.installed_path.read_bytes()
    install_env.installed_path.parent.chmod(0o555)
    try:
        report = ensure(install_env)
    finally:
        install_env.installed_path.parent.chmod(0o755)
    assert report.action == "failed"
    assert report.error and "could not install" in report.error
    assert install_env.installed_path.read_bytes() == before
    assert not os.path.exists(str(install_env.installed_path) + ".tmp")


def test_no_bundle_is_not_an_error(install_env) -> None:
    report = ensure(install_env)
    assert report.action == "none"
    assert report.error is None
    assert report.bundled is None


@pytest.mark.parametrize(
    ("line", "expected"),
    [
        ("moonlight-steam-sync 0.3.0", (0, 3, 0)),
        ("moonlight-steam-sync.pyz 0.3.0", (0, 3, 0)),
        ("prog 0.4.0.dev1", (0, 4, 0)),
        ("__main__.py 1.2.3rc1", (1, 2, 3)),
        ("garbage", None),
        ("moonlight-steam-sync v0.3", None),
        ("", None),
    ],
)
def test_read_version(install_env, line, expected) -> None:
    script = install_env.bundled(line) if line else install_env.bundled_path
    if not line:
        script.write_text("")
    assert install.read_version([str(install_env.python), str(script)]) == expected


def test_read_version_failures_are_none(tmp_path) -> None:
    assert install.read_version([str(tmp_path / "no-such-python")]) is None
    assert install.read_version([sys.executable, "-c", "import sys; sys.exit(3)"]) is None
    assert (
        install.read_version([sys.executable, "-c", "import time; time.sleep(5)"], timeout=0.2)
        is None
    )


def make_backend_with_shim(tmp_path, install_env) -> Backend:
    return Backend(
        settings_dir=str(tmp_path / "settings"),
        log_dir=str(tmp_path / "logs"),
        plugin_dir=str(install_env.plugin_dir),
        home=str(install_env.home),
        plugin_version="0.1.0",
        emit=None,
        python=str(install_env.python),
        env={"PATH": os.environ.get("PATH", "")},
    )


def test_startup_installs_the_bundle_and_about_shows_both(tmp_path, install_env) -> None:
    install_env.bundled("moonlight-steam-sync.pyz 0.4.0")
    (install_env.plugin_dir / "package.json").write_text('{"version": "0.4.0"}\n')
    backend = make_backend_with_shim(tmp_path, install_env)
    run(backend.startup())
    assert install_env.installed_path.exists()
    info = run(backend.cli_version())
    assert info["ok"] is True
    assert info["installed"] == "0.4.0"
    assert info["bundled"] == "0.4.0"
    assert info["minimum"] == "0.4.0"
    assert info["too_old"] is False
    assert info["install_error"] is None
    assert info["installed_path"] == str(install_env.installed_path)
    assert info["bundled_path"] == str(install_env.bundled_path)
    log = (tmp_path / "logs" / "moonlight-sync.log").read_text()
    assert "bundled 0.4.0, installed 0.4.0, action installed" in log


def test_too_old_short_circuits_without_spawning(tmp_path, install_env) -> None:
    install_env.installed("moonlight-steam-sync 0.2.0")
    backend = make_backend_with_shim(tmp_path, install_env)
    run(backend.startup())
    info = run(backend.cli_version())
    assert info["installed"] == "0.2.0"
    assert info["bundled"] is None
    assert info["too_old"] is True
    spawned = []

    async def no_spawn(*args, **kwargs):
        spawned.append(args)
        raise AssertionError("must not spawn")

    backend._spawn = no_spawn  # type: ignore[method-assign]
    result = run(backend.status())
    assert result == {
        "ok": False,
        "error": "cli-too-old",
        "message": "CLI too old (0.2.0, needs 0.4.0) — see About",
        "installed": "0.2.0",
        "minimum": "0.4.0",
    }
    for call in (backend.hosts(), backend.list_apps(), backend.start_sync(), backend.doctor()):
        assert run(call)["error"] == "cli-too-old"
    assert spawned == []


def test_missing_cli_short_circuits(tmp_path, install_env) -> None:
    backend = make_backend_with_shim(tmp_path, install_env)
    run(backend.startup())
    info = run(backend.cli_version())
    assert info["installed"] is None
    assert info["too_old"] is False
    assert run(backend.status())["error"] == "cli-missing"
    assert run(backend.start_sync())["error"] == "cli-missing"
    # plugin-file callables still work without a CLI
    assert run(backend.get_settings())["ok"] is True
    assert run(backend.write_owned_apps(12345678, {"620": "Portal 2"}))["ok"] is True
    assert run(backend.sgdb_key_state())["ok"] is True


def test_min_cli_version_is_the_one_constant() -> None:
    assert install.MIN_CLI_VERSION == (0, 4, 0)
    assert FAKE_CLI.exists()
