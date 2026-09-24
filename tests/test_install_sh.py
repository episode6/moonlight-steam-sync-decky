"""install.sh: the end-user installer (spec section 4 PR-8).

The real script runs unmodified from the repo root, with
MOONLIGHT_SYNC_BASE_URL pointing at a file:// directory of fixtures and
PLUGIN_DIR redirected into tmp_path so nothing needs sudo. install.sh reads
MOONLIGHT_SYNC_BASE_URL itself (the same seam as cli/install.sh's
MOONLIGHT_STEAM_SYNC_BASE_URL) to override the release base URL, so the real
`curl` runs unmodified against the file:// fixture. `sudo` is still stubbed
on PATH with a wrapper that just execs its argument list (mkdir, unzip,
systemctl -- none of which need real root against a tmp_path target), so
the real install.sh runs unmodified and unsudo'd end to end.
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


def _fake_zip_bytes(version: str = "0.1.0") -> bytes:
    """The shape scripts/package.py produces: a "Moonlight Sync/" directory
    with plugin.json and package.json at its root."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as archive:
        archive.writestr("Moonlight Sync/plugin.json", '{"name": "Moonlight Sync"}\n')
        archive.writestr(
            "Moonlight Sync/package.json",
            '{\n  "name": "moonlight-steam-sync-decky",\n  "version": "' + version + '"\n}\n',
        )
    return buf.getvalue()


def release(tmp_path: Path, payload: bytes | None = None, version: str = "latest") -> Path:
    """Build a fixture releases tree and return its root.

    install.sh appends `latest/download` or `download/<tag>` to whatever
    MOONLIGHT_SYNC_BASE_URL/https://github.com/<repo>/releases is, exactly
    as it would for a real GitHub release, so the fixture mirrors that
    layout: the assets live under `<root>/<version-subpath>/`, not at the
    root itself.
    """
    root = tmp_path / "releases"
    subpath = "latest/download" if version == "latest" else f"download/{version}"
    directory = root / subpath
    directory.mkdir(parents=True, exist_ok=True)
    payload = payload if payload is not None else _fake_zip_bytes()
    (directory / ASSET).write_bytes(payload)
    digest = hashlib.sha256(payload).hexdigest()
    (directory / f"{ASSET}.sha256").write_text(f"{digest}  {ASSET}\n")
    return root


def asset_dir(base: Path, version: str = "latest") -> Path:
    """The directory under a `release()` root that holds the assets for
    `version` ("latest" or a tag), matching install.sh's own RELEASE_PATH.
    """
    subpath = "latest/download" if version == "latest" else f"download/{version}"
    return base / subpath


def fake_bin(tmp_path: Path) -> Path:
    """A directory prepended to PATH with `sudo` and `systemctl` shims.

    `sudo` just execs its argument list: everything install.sh runs under
    sudo (mkdir -p, rm -rf, unzip, systemctl restart) is either harmless or
    replaced by a fake below. The real `curl` is used unmodified; the
    fixture URL is supplied via MOONLIGHT_SYNC_BASE_URL instead.
    """
    directory = tmp_path / "fakebin"
    directory.mkdir(exist_ok=True)
    (directory / "sudo").write_text("#!/bin/sh\nexec \"$@\"\n")
    (directory / "systemctl").write_text("#!/bin/sh\necho fake-systemctl \"$@\"\n")
    for name in ("sudo", "systemctl"):
        (directory / name).chmod(0o755)
    return directory


def run_install(
    tmp_path: Path,
    base: Path,
    plugin_dir: Path,
    extra_env: dict[str, str] | None = None,
    extra_path_dirs: tuple[Path, ...] = (),
) -> subprocess.CompletedProcess[str]:
    env = dict(os.environ)
    bindir = fake_bin(tmp_path)
    path_prefix = "".join(f"{d}:" for d in extra_path_dirs)
    env["PATH"] = f"{path_prefix}{bindir}:{env['PATH']}"
    env["PLUGIN_DIR"] = str(plugin_dir)
    env["MOONLIGHT_SYNC_BASE_URL"] = base.as_uri()
    if extra_env:
        env.update(extra_env)
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
    (asset_dir(base) / f"{ASSET}.sha256").write_text(f"{'0' * 64}  {ASSET}\n")
    plugin_dir = tmp_path / "plugins"
    result = run_install(tmp_path, base, plugin_dir)
    assert result.returncode == 1
    assert "checksum mismatch" in result.stderr
    assert not plugin_dir.exists()


def test_missing_asset_fails(tmp_path: Path) -> None:
    base = release(tmp_path)
    (asset_dir(base) / ASSET).unlink()
    plugin_dir = tmp_path / "plugins"
    result = run_install(tmp_path, base, plugin_dir)
    assert result.returncode == 1
    # curl -f prints nothing useful on a 404, so install.sh says which URL
    # failed and why it probably did (as backend/entrypoint.sh does).
    assert f"install.sh: could not download {base.as_uri()}" in result.stderr
    assert f"{ASSET} (is latest released?)" in result.stderr
    assert not plugin_dir.exists()


def test_missing_checksum_fails(tmp_path: Path) -> None:
    base = release(tmp_path)
    (asset_dir(base) / f"{ASSET}.sha256").unlink()
    plugin_dir = tmp_path / "plugins"
    result = run_install(tmp_path, base, plugin_dir)
    assert result.returncode == 1
    assert f"install.sh: could not download {base.as_uri()}" in result.stderr
    assert f"{ASSET}.sha256 (is latest released?)" in result.stderr
    assert not plugin_dir.exists()


def test_missing_pinned_release_names_the_version(tmp_path: Path) -> None:
    base = release(tmp_path, version="v0.1.0")
    plugin_dir = tmp_path / "plugins"
    result = run_install(
        tmp_path, base, plugin_dir, extra_env={"MOONLIGHT_SYNC_VERSION": "v9.9.9"}
    )
    assert result.returncode == 1
    assert "(is v9.9.9 released?)" in result.stderr
    assert not plugin_dir.exists()


def test_reinstall_removes_files_the_new_release_no_longer_ships(tmp_path: Path) -> None:
    """unzip -o only overwrites what the new zip ships, so install.sh removes
    the plugin directory first; a module an older release dropped there must
    not survive the reinstall."""
    base = release(tmp_path)
    plugin_dir = tmp_path / "plugins"
    stale = plugin_dir / "Moonlight Sync" / "stale.py"
    stale.parent.mkdir(parents=True)
    stale.write_text("# shipped by an older release\n")
    result = run_install(tmp_path, base, plugin_dir)
    assert result.returncode == 0, result.stderr
    assert not stale.exists()
    assert (plugin_dir / "Moonlight Sync" / "plugin.json").exists()


def test_the_final_line_reports_the_version_that_landed(tmp_path: Path) -> None:
    """With the default "latest" the tag is unknown here, so the line reads
    package.json out of what was just unzipped."""
    base = release(tmp_path, payload=_fake_zip_bytes("0.4.2"))
    plugin_dir = tmp_path / "plugins"
    result = run_install(tmp_path, base, plugin_dir)
    assert result.returncode == 0, result.stderr
    assert "Installed Moonlight Sync 0.4.2 to" in result.stdout
    assert "Installed Moonlight Sync latest" not in result.stdout


def test_the_final_line_falls_back_to_the_requested_version(tmp_path: Path) -> None:
    """A zip with no package.json (or an unreadable one) still gets a line."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as archive:
        archive.writestr("Moonlight Sync/plugin.json", '{"name": "Moonlight Sync"}\n')
    base = release(tmp_path, payload=buf.getvalue(), version="v0.1.0")
    plugin_dir = tmp_path / "plugins"
    result = run_install(
        tmp_path, base, plugin_dir, extra_env={"MOONLIGHT_SYNC_VERSION": "v0.1.0"}
    )
    assert result.returncode == 0, result.stderr
    assert "Installed Moonlight Sync v0.1.0 to" in result.stdout


def logging_curl_bin(tmp_path: Path) -> tuple[Path, Path]:
    """A directory prepended to PATH with a `curl` that logs the URL it
    was asked to fetch (one per line) to `log` before delegating to the
    real curl, so a test can assert exactly which URL install.sh built.
    """
    directory = tmp_path / "curllog_bin"
    directory.mkdir(exist_ok=True)
    log = tmp_path / "curl.log"
    real_curl = shutil.which("curl")
    assert real_curl is not None
    (directory / "curl").write_text(
        "#!/bin/sh\n"
        f'echo "$*" >> "{log}"\n'
        f'exec {real_curl} "$@"\n'
    )
    (directory / "curl").chmod(0o755)
    return directory, log


def test_default_version_hits_the_latest_download_path(tmp_path: Path) -> None:
    base = release(tmp_path)
    plugin_dir = tmp_path / "plugins"
    curl_dir, log = logging_curl_bin(tmp_path)
    result = run_install(tmp_path, base, plugin_dir, extra_path_dirs=(curl_dir,))
    assert result.returncode == 0, result.stderr
    logged = log.read_text()
    assert "releases/latest/download/Moonlight-Sync.zip" in logged


def test_missing_required_command_fails(tmp_path: Path) -> None:
    plugin_dir = tmp_path / "plugins"
    bindir = fake_bin(tmp_path)
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
    base = release(tmp_path, version="v0.1.0")
    plugin_dir = tmp_path / "plugins"
    curl_dir, log = logging_curl_bin(tmp_path)
    result = run_install(
        tmp_path,
        base,
        plugin_dir,
        extra_env={"MOONLIGHT_SYNC_VERSION": "v0.1.0"},
        extra_path_dirs=(curl_dir,),
    )
    assert result.returncode == 0, result.stderr
    assert "v0.1.0" in result.stdout
    logged = log.read_text()
    assert "releases/download/v0.1.0/Moonlight-Sync.zip" in logged


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
