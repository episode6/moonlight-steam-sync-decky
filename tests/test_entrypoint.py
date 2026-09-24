"""backend/entrypoint.sh and scripts/build_cli.py: the CLI built from cli/src.

The script runs from a sandbox copy of the repo's relevant parts under
tmp_path (backend/entrypoint.sh, scripts/build_cli.py, cli/src and a
package.json), so the real backend/out/ is never touched.
"""

from __future__ import annotations

import json
import shutil
import stat
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest

from conftest import ROOT

pytestmark = pytest.mark.skipif(not shutil.which("sh"), reason="needs sh")

sys.path.insert(0, str(ROOT / "scripts"))
import build_cli  # noqa: E402

PYZ = "moonlight-steam-sync.pyz"
INIT = Path("cli") / "src" / "moonlight_steam_sync" / "__init__.py"


def plugin_version() -> str:
    return json.loads((ROOT / "package.json").read_text())["version"]


@pytest.fixture
def sandbox(tmp_path: Path) -> Path:
    plugin = tmp_path / "plugin"
    (plugin / "backend").mkdir(parents=True)
    (plugin / "scripts").mkdir()
    shutil.copy2(ROOT / "backend" / "entrypoint.sh", plugin / "backend" / "entrypoint.sh")
    shutil.copy2(ROOT / "scripts" / "build_cli.py", plugin / "scripts" / "build_cli.py")
    shutil.copytree(
        ROOT / "cli" / "src",
        plugin / "cli" / "src",
        ignore=shutil.ignore_patterns("__pycache__", "*.egg-info"),
    )
    (plugin / "package.json").write_text(
        json.dumps({"name": "x", "version": plugin_version()}, indent=2) + "\n"
    )
    return plugin


def run_entrypoint(plugin: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["sh", str(plugin / "backend" / "entrypoint.sh")],
        capture_output=True,
        text=True,
        cwd=str(plugin.parent),
        timeout=120,
        check=False,
    )


def out_file(plugin: Path) -> Path:
    return plugin / "backend" / "out" / PYZ


def test_builds_a_runnable_zipapp_with_mode_0755(sandbox: Path) -> None:
    result = run_entrypoint(sandbox)
    assert result.returncode == 0, result.stderr
    pyz = out_file(sandbox)
    assert stat.S_IMODE(pyz.stat().st_mode) == 0o755
    assert pyz.read_bytes().startswith(b"#!/usr/bin/env python3\n")
    assert f"moonlight-steam-sync v{plugin_version()} ->" in result.stdout
    assert result.stdout.strip().endswith(plugin_version())


def test_the_zipapp_holds_the_package_only(sandbox: Path) -> None:
    # What an editable install and a test run leave behind in cli/src.
    package = sandbox / "cli" / "src" / "moonlight_steam_sync"
    (package / "__pycache__").mkdir()
    (package / "__pycache__" / "sync.cpython-313.pyc").write_bytes(b"x")
    (sandbox / "cli" / "src" / "moonlight_steam_sync.egg-info").mkdir()
    (sandbox / "cli" / "src" / "moonlight_steam_sync.egg-info" / "PKG-INFO").write_text("x")
    result = run_entrypoint(sandbox)
    assert result.returncode == 0, result.stderr
    names = zipfile.ZipFile(out_file(sandbox)).namelist()
    assert "__main__.py" in names
    assert "moonlight_steam_sync/__init__.py" in names
    assert "moonlight_steam_sync/art/sgdb.py" in names
    assert all(
        name == "__main__.py" or name.startswith("moonlight_steam_sync/") for name in names
    ), names
    assert not [name for name in names if "__pycache__" in name or name.endswith(".pyc")]


def test_a_version_mismatch_fails_and_leaves_nothing(sandbox: Path) -> None:
    (sandbox / "package.json").write_text('{"name": "x", "version": "99.0.0"}\n')
    result = run_entrypoint(sandbox)
    assert result.returncode == 1
    assert "is not package.json's version (99.0.0)" in result.stderr
    assert not out_file(sandbox).exists()


def test_a_failed_build_removes_an_older_zipapp(sandbox: Path) -> None:
    out_file(sandbox).parent.mkdir(parents=True)
    out_file(sandbox).write_text("an older build")
    (sandbox / "package.json").write_text('{"name": "x"}\n')
    result = run_entrypoint(sandbox)
    assert result.returncode == 1
    assert "no version in package.json" in result.stderr
    assert not out_file(sandbox).exists()


def test_a_missing_cli_source_fails(sandbox: Path) -> None:
    shutil.rmtree(sandbox / "cli")
    result = run_entrypoint(sandbox)
    assert result.returncode == 1
    assert "could not build the CLI" in result.stderr
    assert not out_file(sandbox).exists()


def test_the_cli_shares_the_plugins_version() -> None:
    # One version for both: a plugin release is a CLI release.
    assert build_cli.cli_version(ROOT) == plugin_version()
    assert build_cli.plugin_version(ROOT) == plugin_version()
    assert (ROOT / INIT).exists()
