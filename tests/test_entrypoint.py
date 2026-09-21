"""backend/entrypoint.sh: the strict download-and-verify step (spec 3.6.2).

The script runs from a copy of backend/ under tmp_path (so the real
backend/out/ is never touched) with MSY_CLI_BASE_URL pointing at a file://
directory of fixtures.
"""

from __future__ import annotations

import hashlib
import os
import shutil
import stat
import subprocess
from pathlib import Path

import pytest

from conftest import ROOT

pytestmark = pytest.mark.skipif(
    not (shutil.which("curl") and shutil.which("sha256sum") and shutil.which("sh")),
    reason="needs sh, curl and sha256sum",
)

PYZ = "moonlight-steam-sync.pyz"


@pytest.fixture
def sandbox(tmp_path: Path) -> Path:
    plugin = tmp_path / "plugin"
    (plugin / "backend").mkdir(parents=True)
    shutil.copy2(ROOT / "backend" / "entrypoint.sh", plugin / "backend" / "entrypoint.sh")
    (plugin / "package.json").write_text('{\n  "name": "x",\n  "moonlightSteamSync": "0.3.0"\n}\n')
    return plugin


def release(tmp_path: Path, payload: bytes = b"#!/usr/bin/env python3\nPK fake zipapp\n") -> Path:
    directory = tmp_path / "release"
    directory.mkdir(exist_ok=True)
    (directory / PYZ).write_bytes(payload)
    digest = hashlib.sha256(payload).hexdigest()
    (directory / f"{PYZ}.sha256").write_text(f"{digest}  {PYZ}\n")
    return directory


def run_entrypoint(plugin: Path, base: Path | None) -> subprocess.CompletedProcess[str]:
    env = dict(os.environ)
    if base is not None:
        env["MSY_CLI_BASE_URL"] = base.as_uri()
    return subprocess.run(
        ["sh", str(plugin / "backend" / "entrypoint.sh")],
        capture_output=True,
        text=True,
        env=env,
        cwd=str(plugin.parent),
        timeout=60,
        check=False,
    )


def out_file(plugin: Path) -> Path:
    return plugin / "backend" / "out" / PYZ


def test_good_checksum_installs_with_mode_0755(sandbox: Path, tmp_path: Path) -> None:
    base = release(tmp_path)
    result = run_entrypoint(sandbox, base)
    assert result.returncode == 0, result.stderr
    assert out_file(sandbox).read_bytes() == (base / PYZ).read_bytes()
    assert stat.S_IMODE(out_file(sandbox).stat().st_mode) == 0o755
    assert "moonlight-steam-sync v0.3.0 ->" in result.stdout


def test_wrong_checksum_fails_and_leaves_nothing(sandbox: Path, tmp_path: Path) -> None:
    base = release(tmp_path)
    (base / f"{PYZ}.sha256").write_text(f"{'0' * 64}  {PYZ}\n")
    result = run_entrypoint(sandbox, base)
    assert result.returncode == 1
    assert "checksum mismatch" in result.stderr
    assert not out_file(sandbox).exists()


def test_missing_asset_fails_and_leaves_nothing(sandbox: Path, tmp_path: Path) -> None:
    base = release(tmp_path)
    (base / PYZ).unlink()
    result = run_entrypoint(sandbox, base)
    assert result.returncode == 1
    assert "could not download" in result.stderr
    assert not out_file(sandbox).exists()


def test_missing_checksum_fails_and_leaves_nothing(sandbox: Path, tmp_path: Path) -> None:
    base = release(tmp_path)
    (base / f"{PYZ}.sha256").unlink()
    result = run_entrypoint(sandbox, base)
    assert result.returncode == 1
    assert not out_file(sandbox).exists()


def test_empty_checksum_file_fails(sandbox: Path, tmp_path: Path) -> None:
    base = release(tmp_path)
    (base / f"{PYZ}.sha256").write_text("")
    result = run_entrypoint(sandbox, base)
    assert result.returncode == 1
    assert not out_file(sandbox).exists()


def test_missing_pin_fails(sandbox: Path, tmp_path: Path) -> None:
    (sandbox / "package.json").write_text('{"name": "x"}\n')
    result = run_entrypoint(sandbox, release(tmp_path))
    assert result.returncode == 1
    assert "no moonlightSteamSync pin in package.json" in result.stderr
    assert not out_file(sandbox).exists()


def test_the_real_package_json_carries_the_pin() -> None:
    text = (ROOT / "package.json").read_text()
    assert '"moonlightSteamSync": "0.4.0"' in text
