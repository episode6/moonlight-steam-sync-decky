"""install.sh: the end-user installer (spec section 4 PR-8).

Modelled on test_entrypoint.py: the script runs from a copy of the repo
root under tmp_path (so the real ~/homebrew/plugins is never touched), with
MOONLIGHT_SYNC_BASE_URL pointing at a file:// directory of fixtures and
PLUGIN_DIR redirected into tmp_path so nothing needs sudo. install.sh does
not read MOONLIGHT_SYNC_BASE_URL itself (it always builds the GitHub URL
from REPO/VERSION), so these tests stub `sudo` and `curl` on PATH instead:
a `curl` wrapper that rewrites the GitHub URL to the local fixture
directory, and a `sudo` wrapper that just execs its argument list (mkdir,
unzip, systemctl -- none of which need real root against a tmp_path
target), so the real install.sh runs unmodified and unsudo'd end to end.
"""

from __future__ import annotations

import hashlib
import io
import os
import shutil
import stat
import subprocess
import zipfile
from pathlib import Path

import pytest

from conftest import ROOT

_needed = ("curl", "sha256sum", "sh", "unzip")
pytestmark = pytest.mark.skipif(
    not all(shutil.which(tool) for tool in _needed),
    reason="needs sh, curl, sha256sum and unzip",
)

ASSET = "Moonlight-Sync.zip"


def _fake_zip_bytes() -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as archive:
        archive.writestr("Moonlight Sync/plugin.json", '{"name": "Moonlight Sync"}\n')
    return buf.getvalue()


def release(tmp_path: Path, payload: bytes | None = None) -> Path:
    directory = tmp_path / "release"
    directory.mkdir(exist_ok=True)
    payload = payload if payload is not None else _fake_zip_bytes()
    (directory / ASSET).write_bytes(payload)
    digest = hashlib.sha256(payload).hexdigest()
    (directory / f"{ASSET}.sha256").write_text(f"{digest}  {ASSET}\n")
    return directory


def fake_bin(tmp_path: Path, base: Path) -> Path:
    """A directory prepended to PATH with `curl` and `sudo` shims.

    `curl` rewrites any https://github.com/... URL to the local `base`
    fixture directory before delegating to the real curl, so install.sh's
    hardcoded GitHub URL resolves to our fixtures without editing the
    script. `sudo` just execs its argument list: everything install.sh
    runs under sudo (mkdir -p, unzip, systemctl restart) is either
    harmless or replaced by a fake below.
    """
    directory = tmp_path / "fakebin"
    directory.mkdir(exist_ok=True)
    real_curl = shutil.which("curl")
    assert real_curl is not None
    (directory / "curl").write_text(
        "#!/bin/sh\n"
        "args=\"\"\n"
        "for a in \"$@\"; do\n"
        "  case \"$a\" in\n"
        f"    https://github.com/*) a=\"{base.as_uri()}/$(basename \"$a\")\" ;;\n"
        "  esac\n"
        "  args=\"$args '$a'\"\n"
        "done\n"
        f"eval \"exec {real_curl} $args\"\n"
    )
    (directory / "sudo").write_text("#!/bin/sh\nexec \"$@\"\n")
    (directory / "systemctl").write_text("#!/bin/sh\necho fake-systemctl \"$@\"\n")
    for name in ("curl", "sudo", "systemctl"):
        (directory / name).chmod(0o755)
    return directory


def run_install(tmp_path: Path, base: Path, plugin_dir: Path) -> subprocess.CompletedProcess[str]:
    env = dict(os.environ)
    bindir = fake_bin(tmp_path, base)
    env["PATH"] = f"{bindir}:{env['PATH']}"
    env["PLUGIN_DIR"] = str(plugin_dir)
    return subprocess.run(
        ["sh", str(ROOT / "install.sh")],
        capture_output=True,
        text=True,
        env=env,
        cwd=str(tmp_path),
        timeout=60,
        check=False,
    )


def test_good_checksum_installs_and_restarts(tmp_path: Path) -> None:
    base = release(tmp_path)
    plugin_dir = tmp_path / "plugins"
    result = run_install(tmp_path, base, plugin_dir)
    assert result.returncode == 0, result.stderr
    assert (plugin_dir / "Moonlight Sync" / "plugin.json").exists()
    assert "fake-systemctl restart plugin_loader" in result.stdout
    assert "Installed Moonlight Sync" in result.stdout


def test_wrong_checksum_fails_and_leaves_nothing(tmp_path: Path) -> None:
    base = release(tmp_path)
    (base / f"{ASSET}.sha256").write_text(f"{'0' * 64}  {ASSET}\n")
    plugin_dir = tmp_path / "plugins"
    result = run_install(tmp_path, base, plugin_dir)
    assert result.returncode == 1
    assert "checksum mismatch" in result.stderr
    assert not plugin_dir.exists()


def test_missing_asset_fails(tmp_path: Path) -> None:
    base = release(tmp_path)
    (base / ASSET).unlink()
    plugin_dir = tmp_path / "plugins"
    result = run_install(tmp_path, base, plugin_dir)
    assert result.returncode != 0
    assert not plugin_dir.exists()


def test_missing_checksum_fails(tmp_path: Path) -> None:
    base = release(tmp_path)
    (base / f"{ASSET}.sha256").unlink()
    plugin_dir = tmp_path / "plugins"
    result = run_install(tmp_path, base, plugin_dir)
    assert result.returncode != 0
    assert not plugin_dir.exists()


def test_missing_required_command_fails(tmp_path: Path) -> None:
    base = release(tmp_path)
    plugin_dir = tmp_path / "plugins"
    bindir = fake_bin(tmp_path, base)
    # A restricted PATH directory holding symlinks to just `sh` and the
    # commands install.sh needs before the one under test -- explicitly
    # never sha256sum or unzip -- so `require` rejects the run before any
    # network call, rather than happening to find the real binaries
    # because they live in the same system directory as `sh`.
    restricted = tmp_path / "restrictedbin"
    restricted.mkdir()
    for name in ("sh", "awk", "mktemp", "rm", "basename", "dirname"):
        found = shutil.which(name)
        assert found is not None, f"{name} not found on the real PATH"
        (restricted / name).symlink_to(found)
    env = dict(os.environ)
    env["PATH"] = f"{bindir}:{restricted}"
    env["PLUGIN_DIR"] = str(plugin_dir)
    result = subprocess.run(
        ["sh", str(ROOT / "install.sh")],
        capture_output=True,
        text=True,
        env=env,
        cwd=str(tmp_path),
        timeout=60,
        check=False,
    )
    assert result.returncode == 1
    assert "is required but was not found on PATH" in result.stderr


def test_pinned_version_hits_the_download_tag_path(tmp_path: Path) -> None:
    base = release(tmp_path)
    plugin_dir = tmp_path / "plugins"
    env = dict(os.environ)
    bindir = fake_bin(tmp_path, base)
    env["PATH"] = f"{bindir}:{env['PATH']}"
    env["PLUGIN_DIR"] = str(plugin_dir)
    env["MOONLIGHT_SYNC_VERSION"] = "v0.1.0"
    result = subprocess.run(
        ["sh", str(ROOT / "install.sh")],
        capture_output=True,
        text=True,
        env=env,
        cwd=str(tmp_path),
        timeout=60,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert "v0.1.0" in result.stdout


def test_the_real_install_sh_is_syntactically_valid() -> None:
    result = subprocess.run(
        ["sh", "-n", str(ROOT / "install.sh")],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr


def test_the_real_install_sh_is_executable() -> None:
    assert stat.S_IMODE((ROOT / "install.sh").stat().st_mode) & 0o111
