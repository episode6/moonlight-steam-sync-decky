"""cli/install.sh: the CLI-only installer (no Decky plugin).

Modelled on test_install_sh.py: the real script runs unmodified, with
MOONLIGHT_STEAM_SYNC_BASE_URL pointing the real `curl` at a file:// releases
tree, and HOME / INSTALL_DIR under tmp_path so no real ~/.local/bin or rc
file is touched. The "zipapp" is a shell script that prints a version, which
is all the installer's closing `--version` needs.
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
    not all(shutil.which(tool) for tool in ("curl", "sha256sum", "sh", "python3")),
    reason="needs sh, curl, sha256sum and python3",
)

ASSET = "moonlight-steam-sync.pyz"
PATH_LINE = 'export PATH="$HOME/.local/bin:$PATH"'


def release(tmp_path: Path, version: str = "latest", reported: str = "9.9.9") -> Path:
    """A releases tree laid out as GitHub serves it: ``<root>/latest/download/``
    or ``<root>/download/<tag>/``, holding the pyz and its checksum."""
    root = tmp_path / "releases"
    subpath = "latest/download" if version == "latest" else f"download/{version}"
    directory = root / subpath
    directory.mkdir(parents=True, exist_ok=True)
    payload = f"#!/bin/sh\necho moonlight-steam-sync {reported}\n".encode()
    (directory / ASSET).write_bytes(payload)
    digest = hashlib.sha256(payload).hexdigest()
    (directory / f"{ASSET}.sha256").write_text(f"{digest}  {ASSET}\n")
    return root


def run_install(
    tmp_path: Path, base: Path, extra_env: dict[str, str] | None = None
) -> subprocess.CompletedProcess[str]:
    home = tmp_path / "home"
    home.mkdir(exist_ok=True)
    env = dict(os.environ)
    env["HOME"] = str(home)
    env["SHELL"] = "/bin/bash"
    env["MOONLIGHT_STEAM_SYNC_BASE_URL"] = base.as_uri()
    env.pop("INSTALL_DIR", None)
    env.pop("NO_MODIFY_PATH", None)
    env.pop("MOONLIGHT_STEAM_SYNC_VERSION", None)
    if extra_env:
        env.update(extra_env)
    return subprocess.run(
        ["sh", str(ROOT / "cli" / "install.sh")],
        capture_output=True,
        text=True,
        env=env,
        cwd=str(tmp_path),
        timeout=60,
        check=False,
    )


def installed(tmp_path: Path) -> Path:
    return tmp_path / "home" / ".local" / "bin" / "moonlight-steam-sync"


def test_installs_the_latest_release_executable_and_runs_it(tmp_path: Path) -> None:
    result = run_install(tmp_path, release(tmp_path))
    assert result.returncode == 0, result.stderr
    target = installed(tmp_path)
    assert stat.S_IMODE(target.stat().st_mode) == 0o755
    assert "moonlight-steam-sync 9.9.9" in result.stdout
    assert not target.with_name("moonlight-steam-sync.new").exists()


def test_the_path_line_is_added_to_the_rc_file_once(tmp_path: Path) -> None:
    base = release(tmp_path)
    for _ in range(2):
        result = run_install(tmp_path, base)
        assert result.returncode == 0, result.stderr
    rc = (tmp_path / "home" / ".bashrc").read_text()
    assert rc.count(PATH_LINE) == 1


def test_no_modify_path_only_prints_the_line(tmp_path: Path) -> None:
    result = run_install(tmp_path, release(tmp_path), {"NO_MODIFY_PATH": "1"})
    assert result.returncode == 0, result.stderr
    assert PATH_LINE in result.stdout
    assert not (tmp_path / "home" / ".bashrc").exists()


def test_a_pinned_version_downloads_that_tag(tmp_path: Path) -> None:
    base = release(tmp_path, version="v1.2.3", reported="1.2.3")
    result = run_install(tmp_path, base, {"MOONLIGHT_STEAM_SYNC_VERSION": "v1.2.3"})
    assert result.returncode == 0, result.stderr
    assert "moonlight-steam-sync 1.2.3" in result.stdout


def test_install_dir_is_honoured(tmp_path: Path) -> None:
    target_dir = tmp_path / "elsewhere"
    result = run_install(
        tmp_path, release(tmp_path), {"INSTALL_DIR": str(target_dir), "NO_MODIFY_PATH": "1"}
    )
    assert result.returncode == 0, result.stderr
    assert (target_dir / "moonlight-steam-sync").exists()
    assert not installed(tmp_path).exists()


def test_wrong_checksum_fails_and_installs_nothing(tmp_path: Path) -> None:
    base = release(tmp_path)
    (base / "latest" / "download" / f"{ASSET}.sha256").write_text(f"{'0' * 64}  {ASSET}\n")
    result = run_install(tmp_path, base)
    assert result.returncode == 1
    assert "checksum mismatch" in result.stderr
    assert not installed(tmp_path).exists()


def test_a_missing_release_fails_and_installs_nothing(tmp_path: Path) -> None:
    base = release(tmp_path)
    (base / "latest" / "download" / ASSET).unlink()
    result = run_install(tmp_path, base)
    assert result.returncode == 1
    assert f"could not download {base.as_uri()}/latest/download/{ASSET}" in result.stderr
    assert "(is latest released?" in result.stderr
    assert not installed(tmp_path).exists()


def test_it_installs_from_this_repos_releases() -> None:
    text = (ROOT / "cli" / "install.sh").read_text()
    assert 'REPO="episode6/moonlight-steam-sync-decky"' in text
    assert f'ASSET="{ASSET}"' in text
