"""install.sh: the end-user installer (spec section 4 PR-8).

The real script runs unmodified from the repo root, with
MOONLIGHT_SYNC_BASE_URL pointing at a file:// directory of fixtures and
PLUGIN_DIR redirected into tmp_path so nothing needs sudo. install.sh reads
MOONLIGHT_SYNC_BASE_URL itself (the same seam as cli/install.sh's
MOONLIGHT_STEAM_SYNC_BASE_URL) to override the release base URL, so the real
`curl` runs unmodified against the file:// fixture. `sudo` is still stubbed
on PATH with a wrapper that execs its argument list (mkdir, unzip,
systemctl -- none of which need real root against a tmp_path target), so
the real install.sh runs unmodified and unsudo'd end to end.

The temporary password (an account with none is offered one for the
install, as Decky Loader's installer does) runs over the same shims plus a
fake `passwd`, all three keeping their state in `tmp_path/fakestate` (see
`fake_bin`); the question is answered through MOONLIGHT_SYNC_TTY, which
`run_install` always points away from the real /dev/tty.

Decky Loader (looked for first, and offered when it is missing) is a
`PluginLoader` file under MOONLIGHT_SYNC_DECKY_DIR, which `install_env`
creates unless `without_decky` said the device has none; its installer is a
fixture script behind MOONLIGHT_SYNC_DECKY_INSTALLER_URL (a file:// URL), so
the real one is never downloaded, let alone run.
"""

from __future__ import annotations

import hashlib
import io
import os
import shutil
import signal
import stat
import subprocess
import time
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


def state_dir(tmp_path: Path) -> Path:
    """Where the shims keep their state, as files a test writes and reads:

    - `status`: what `passwd -S` says of the account (`NP` no password, `P`
      one; absent reads `P`, so a test that says nothing is never offered a
      temporary password);
    - `password`: the password `passwd` last set, removed by `passwd -d`;
    - `sudo-needs-password`: when present, `sudo` is a stock Deck's: `-n`
      fails, and a command runs only with `-S` and the account's password
      on stdin (absent, it runs anything, like a NOPASSWD sudo);
    - `passwd-sets-other`: when present, `passwd` sets a password that is
      not the one it was given (a passwd that asked on the terminal);
    - `passwd-set-fails`, `passwd-d-fails`, `systemctl-fails`,
      `systemctl-slow`: when present, that step fails (or, for the last,
      touches `systemctl-started` and takes two seconds);
    - `sudo.log`, `passwd.log`: one line per call;
    - `decky-missing`: when present, Decky Loader is not installed (see
      `without_decky`);
    - `decky-installer-fails`, `decky-installer-installs-nothing`: when
      present, the fixture Decky installer exits 1, or exits 0 without
      leaving a loader behind;
    - `decky-installer.log`: one line per run of that installer.
    """
    directory = tmp_path / "fakestate"
    directory.mkdir(exist_ok=True)
    return directory


def fake_bin(tmp_path: Path) -> Path:
    """A directory prepended to PATH with `sudo`, `systemctl` and `passwd`
    shims.

    `sudo` execs its argument list: everything install.sh runs under sudo
    (mkdir -p, rm -rf, unzip, systemctl restart, passwd -d) is either
    harmless or replaced by a fake here. The real `curl` is used
    unmodified; the fixture URL is supplied via MOONLIGHT_SYNC_BASE_URL
    instead. `passwd` is always the fake, so no test ever asks about (let
    alone changes) the account the suite runs as.
    """
    directory = tmp_path / "fakebin"
    directory.mkdir(exist_ok=True)
    state = state_dir(tmp_path)
    (directory / "sudo").write_text(
        "#!/bin/sh\n"
        f'state="{state}"\n'
        'echo "$*" >> "$state/sudo.log"\n'
        "from_stdin=0\n"
        "while [ $# -gt 0 ]; do\n"
        '    case "$1" in\n'
        "        -n)\n"
        '            if [ -e "$state/sudo-needs-password" ]; then\n'
        '                echo "sudo: a password is required" >&2\n'
        "                exit 1\n"
        "            fi\n"
        "            shift ;;\n"
        "        -S) from_stdin=1; shift ;;\n"
        "        -k) shift ;;\n"
        "        -p) shift 2 ;;\n"
        "        *) break ;;\n"
        "    esac\n"
        "done\n"
        "[ $# -gt 0 ] || exit 0\n"
        'if [ -e "$state/sudo-needs-password" ]; then\n'
        '    if [ "$from_stdin" != 1 ]; then\n'
        '        echo "sudo: a terminal is required to read the password" >&2\n'
        "        exit 1\n"
        "    fi\n"
        '    IFS= read -r given || given=""\n'
        '    if [ ! -f "$state/password" ] || [ "$given" != "$(cat "$state/password")" ]; then\n'
        '        echo "sudo: 1 incorrect password attempt" >&2\n'
        "        exit 1\n"
        "    fi\n"
        "fi\n"
        'exec "$@"\n'
    )
    (directory / "systemctl").write_text(
        "#!/bin/sh\n"
        f'state="{state}"\n'
        'if [ -e "$state/systemctl-slow" ]; then\n'
        '    : > "$state/systemctl-started"\n'
        "    sleep 2\n"
        "fi\n"
        '[ ! -e "$state/systemctl-fails" ] || exit 1\n'
        'echo fake-systemctl "$@"\n'
    )
    (directory / "passwd").write_text(
        "#!/bin/sh\n"
        f'state="{state}"\n'
        'echo "$*" >> "$state/passwd.log"\n'
        'case "$1" in\n'
        "    -S)\n"
        '        status=$(cat "$state/status" 2>/dev/null || echo P)\n'
        '        echo "$2 $status 2026-01-01 0 99999 7 -1" ;;\n'
        "    -d)\n"
        '        [ ! -e "$state/passwd-d-fails" ] || exit 1\n'
        '        rm -f "$state/password"\n'
        '        echo NP > "$state/status" ;;\n'
        "    *)\n"
        '        [ ! -e "$state/passwd-set-fails" ] || exit 1\n'
        "        IFS= read -r first || exit 1\n"
        "        IFS= read -r second || exit 1\n"
        '        [ "$first" = "$second" ] || exit 1\n'
        '        [ ! -e "$state/passwd-sets-other" ] || first="typed by hand"\n'
        '        printf "%s" "$first" > "$state/password"\n'
        '        echo P > "$state/status" ;;\n'
        "esac\n"
    )
    for name in ("sudo", "systemctl", "passwd"):
        (directory / name).chmod(0o755)
    return directory


def decky_dir(tmp_path: Path) -> Path:
    return tmp_path / "homebrew"


def decky_loader(tmp_path: Path) -> Path:
    """What install.sh takes for "Decky Loader is installed"."""
    return decky_dir(tmp_path) / "services" / "PluginLoader"


def decky_installer(tmp_path: Path) -> Path:
    """Where the fixture Decky installer is served from (`without_decky`
    writes it; with Decky installed nothing may ask for it)."""
    return tmp_path / "decky-release" / "install_release.sh"


def install_env(
    tmp_path: Path,
    base: Path,
    plugin_dir: Path,
    extra_env: dict[str, str] | None = None,
    extra_path_dirs: tuple[Path, ...] = (),
) -> dict[str, str]:
    env = dict(os.environ)
    bindir = fake_bin(tmp_path)
    path_prefix = "".join(f"{d}:" for d in extra_path_dirs)
    env["PATH"] = f"{path_prefix}{bindir}:{env['PATH']}"
    env["PLUGIN_DIR"] = str(plugin_dir)
    env["MOONLIGHT_SYNC_BASE_URL"] = base.as_uri()
    # Never the real /dev/tty: a suite run from a terminal would sit at the
    # question. A test that answers it writes the answer file (`answer`).
    env["MOONLIGHT_SYNC_TTY"] = str(tmp_path / "tty")
    # Decky Loader is there unless `without_decky` said otherwise, and its
    # installer is never the real one.
    env["MOONLIGHT_SYNC_DECKY_DIR"] = str(decky_dir(tmp_path))
    env["MOONLIGHT_SYNC_DECKY_INSTALLER_URL"] = decky_installer(tmp_path).as_uri()
    if not (state_dir(tmp_path) / "decky-missing").exists():
        loader = decky_loader(tmp_path)
        loader.parent.mkdir(parents=True, exist_ok=True)
        loader.touch()
    if extra_env:
        env.update(extra_env)
    return env


def run_install(
    tmp_path: Path,
    base: Path,
    plugin_dir: Path,
    extra_env: dict[str, str] | None = None,
    extra_path_dirs: tuple[Path, ...] = (),
) -> subprocess.CompletedProcess[str]:
    env = install_env(tmp_path, base, plugin_dir, extra_env, extra_path_dirs)
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


TEMP_PASSWORD = "Decky!"
QUESTION = "Set a temporary password for the install?"


def stock_deck(tmp_path: Path, answer: str | None = "y") -> Path:
    """The account has no password and sudo wants one; `answer` is the line
    waiting on the terminal (`None`: no terminal to read). Returns the
    shims' state directory."""
    state = state_dir(tmp_path)
    (state / "status").write_text("NP\n")
    (state / "sudo-needs-password").touch()
    if answer is not None:
        (tmp_path / "tty").write_text(answer + "\n")
    return state


def log_lines(state: Path, name: str) -> list[str]:
    path = state / name
    return path.read_text().splitlines() if path.exists() else []


def password_was_set(state: Path) -> bool:
    """Whether `passwd` was ever asked to set one (any call but -S / -d)."""
    return any(
        not line.startswith(("-S", "-d")) for line in log_lines(state, "passwd.log")
    )


def test_no_password_and_yes_installs_with_a_temporary_one(tmp_path: Path) -> None:
    base = release(tmp_path)
    plugin_dir = tmp_path / "plugins"
    state = stock_deck(tmp_path)
    result = run_install(tmp_path, base, plugin_dir)
    assert result.returncode == 0, result.stderr
    assert QUESTION in result.stdout
    assert f"'{TEMP_PASSWORD}'" in result.stdout
    assert (plugin_dir / "Moonlight Sync" / "plugin.json").exists()
    assert "fake-systemctl restart plugin_loader" in result.stdout
    # Gone again, and said so before the final line.
    assert (state / "status").read_text().strip() == "NP"
    assert not (state / "password").exists()
    removed = result.stdout.index("Removed the temporary password")
    assert removed < result.stdout.index("Installed Moonlight Sync")
    assert "You may be asked" not in result.stdout
    assert "WARNING" not in result.stderr
    # The probe, the proof that sudo takes the temporary password, the
    # four install steps with it on stdin (the shim refuses any other way),
    # the removal, then the cached credential dropped. Nothing but `true`
    # ran under sudo before the password was set and proven.
    user = subprocess.run(
        ["id", "-un"], capture_output=True, text=True, check=True
    ).stdout.strip()
    sudo = log_lines(state, "sudo.log")
    assert sudo[0] == "-n true"
    assert sudo[1] == "-S -k -p  true"
    assert [line.split()[2] for line in sudo[2:6]] == ["mkdir", "rm", "unzip", "systemctl"]
    assert all(line.startswith("-S -p ") for line in sudo[2:6])
    assert sudo[6:] == [f"-S -k -p  passwd -d {user}", "-k"]
    assert log_lines(state, "passwd.log")[:2] == [f"-S {user}", user]


@pytest.mark.parametrize("answer", ["n", "", "maybe", None])
def test_no_password_and_no_installs_nothing(tmp_path: Path, answer: str | None) -> None:
    """Anything but a yes, no answer and no terminal included: nothing is
    set, nothing is installed, and the script says what to do instead."""
    base = release(tmp_path)
    plugin_dir = tmp_path / "plugins"
    state = stock_deck(tmp_path, answer)
    result = run_install(tmp_path, base, plugin_dir)
    assert result.returncode == 1
    assert QUESTION in result.stdout
    assert "nothing was installed" in result.stderr
    assert "`passwd`" in result.stderr
    assert not plugin_dir.exists()
    assert not password_was_set(state)
    assert log_lines(state, "sudo.log") == ["-n true"]


@pytest.mark.parametrize("answer", ["y", "Y", "yes", "YES"])
def test_every_spelling_of_yes_is_a_yes(tmp_path: Path, answer: str) -> None:
    base = release(tmp_path)
    plugin_dir = tmp_path / "plugins"
    state = stock_deck(tmp_path, answer)
    result = run_install(tmp_path, base, plugin_dir)
    assert result.returncode == 0, result.stderr
    assert (state / "status").read_text().strip() == "NP"


def test_no_password_but_sudo_needs_none_asks_nothing(tmp_path: Path) -> None:
    """NOPASSWD sudo: there is nothing a temporary password would be for."""
    base = release(tmp_path)
    plugin_dir = tmp_path / "plugins"
    state = stock_deck(tmp_path)
    (state / "sudo-needs-password").unlink()
    result = run_install(tmp_path, base, plugin_dir)
    assert result.returncode == 0, result.stderr
    assert QUESTION not in result.stdout
    assert (plugin_dir / "Moonlight Sync" / "plugin.json").exists()
    assert not password_was_set(state)
    assert not any(line.startswith("-S") for line in log_lines(state, "sudo.log"))


def test_an_account_with_a_password_is_never_offered_one(tmp_path: Path) -> None:
    """The user's own password is theirs: no question, no probe, no passwd
    call but the status read, and sudo left interactive."""
    base = release(tmp_path)
    plugin_dir = tmp_path / "plugins"
    state = state_dir(tmp_path)
    (state / "status").write_text("P\n")
    (tmp_path / "tty").write_text("y\n")
    result = run_install(tmp_path, base, plugin_dir)
    assert result.returncode == 0, result.stderr
    assert QUESTION not in result.stdout
    assert "You may be asked" in result.stdout
    assert all(line.startswith("-S ") for line in log_lines(state, "passwd.log"))
    sudo = log_lines(state, "sudo.log")
    assert [line.split()[0] for line in sudo] == ["mkdir", "rm", "unzip", "systemctl"]


def test_a_failed_install_step_still_removes_the_temporary_password(tmp_path: Path) -> None:
    base = release(tmp_path)
    plugin_dir = tmp_path / "plugins"
    state = stock_deck(tmp_path)
    (state / "systemctl-fails").touch()
    result = run_install(tmp_path, base, plugin_dir)
    assert result.returncode == 1
    assert "Installed Moonlight Sync" not in result.stdout
    assert "Removed the temporary password" in result.stdout
    assert (state / "status").read_text().strip() == "NP"
    assert not (state / "password").exists()
    assert log_lines(state, "sudo.log")[-1] == "-k"


@pytest.mark.parametrize(
    ("signum", "status"), [(signal.SIGTERM, 143), (signal.SIGINT, 130), (signal.SIGHUP, 129)]
)
def test_a_signal_mid_install_still_removes_the_temporary_password(
    tmp_path: Path, signum: signal.Signals, status: int
) -> None:
    """A plain sh runs no EXIT trap for a signal, so install.sh turns each
    one into an exit; killed while plugin_loader restarts, it still takes
    the password off."""
    base = release(tmp_path)
    plugin_dir = tmp_path / "plugins"
    state = stock_deck(tmp_path)
    (state / "systemctl-slow").touch()
    process = subprocess.Popen(
        ["sh", str(ROOT / "install.sh")],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env=install_env(tmp_path, base, plugin_dir),
        cwd=str(tmp_path),
    )
    try:
        deadline = time.monotonic() + 30
        while not (state / "systemctl-started").exists():
            assert process.poll() is None, process.communicate()
            assert time.monotonic() < deadline
            time.sleep(0.02)
        assert (state / "password").read_text() == TEMP_PASSWORD
        process.send_signal(signum)
        stdout, _ = process.communicate(timeout=30)
    finally:
        if process.poll() is None:
            process.kill()
    assert process.returncode == status
    assert "Installed Moonlight Sync" not in stdout
    assert (state / "status").read_text().strip() == "NP"
    assert not (state / "password").exists()


def test_a_temporary_password_that_cannot_be_removed_is_shouted(tmp_path: Path) -> None:
    base = release(tmp_path)
    plugin_dir = tmp_path / "plugins"
    state = stock_deck(tmp_path)
    (state / "passwd-d-fails").touch()
    result = run_install(tmp_path, base, plugin_dir)
    assert result.returncode == 0, result.stderr
    assert "WARNING: could not remove the temporary password" in result.stderr
    assert f"is still '{TEMP_PASSWORD}'" in result.stderr
    assert "sudo passwd -d " in result.stderr
    assert "Removed the temporary password" not in result.stdout
    # Tried once, not once more at exit.
    assert sum("passwd -d" in line for line in log_lines(state, "sudo.log")) == 1


def test_a_temporary_password_that_cannot_be_set_installs_nothing(tmp_path: Path) -> None:
    base = release(tmp_path)
    plugin_dir = tmp_path / "plugins"
    state = stock_deck(tmp_path)
    (state / "passwd-set-fails").touch()
    result = run_install(tmp_path, base, plugin_dir)
    assert result.returncode == 1
    assert "could not set the temporary password" in result.stderr
    assert "WARNING" not in result.stderr
    assert "Removed the temporary password" not in result.stdout
    assert not plugin_dir.exists()
    assert log_lines(state, "sudo.log") == ["-n true"]


def test_a_password_that_is_not_the_temporary_one_is_left_alone(tmp_path: Path) -> None:
    """A passwd that did not take the piped password (it asked on the
    terminal and the user typed their own): sudo refuses the temporary
    one, so nothing is installed, nothing claims the password is the
    temporary one for certain, and no removal is attempted with it."""
    base = release(tmp_path)
    plugin_dir = tmp_path / "plugins"
    state = stock_deck(tmp_path)
    (state / "passwd-sets-other").touch()
    result = run_install(tmp_path, base, plugin_dir)
    assert result.returncode == 1
    assert "sudo did not accept the temporary one" in result.stderr
    assert "if you did not" in result.stderr
    assert "WARNING" not in result.stderr
    assert "Removed the temporary password" not in result.stdout
    assert not plugin_dir.exists()
    assert (state / "password").read_text() == "typed by hand"
    assert log_lines(state, "sudo.log") == ["-n true", "-S -k -p  true"]


DECKY_QUESTION = "Install Decky Loader now?"
DECKY_SCRIPT = "decky-install_release.sh"


def without_decky(tmp_path: Path, *answers: str) -> Path:
    """A device without Decky Loader, whose installer (the fixture one)
    would install it; `answers` are the lines waiting on the terminal, one
    per question in the order asked (none: no terminal to read). Returns
    the shims' state directory."""
    state = state_dir(tmp_path)
    (state / "decky-missing").touch()
    loader = decky_loader(tmp_path)
    script = decky_installer(tmp_path)
    script.parent.mkdir(parents=True, exist_ok=True)
    script.write_text(
        "#!/bin/sh\n"
        f'state="{state}"\n'
        'echo run >> "$state/decky-installer.log"\n'
        # Whatever is on stdin is eaten, as a careless installer might: it
        # must never be the script install.sh itself is being read from.
        'cat > "$state/decky-installer.stdin"\n'
        '[ ! -e "$state/decky-installer-fails" ] || exit 1\n'
        'if [ ! -e "$state/decky-installer-installs-nothing" ]; then\n'
        f'    mkdir -p "{loader.parent}"\n'
        f'    : > "{loader}"\n'
        "fi\n"
        "echo fake-decky-installer\n"
    )
    if answers:
        (tmp_path / "tty").write_text("".join(answer + "\n" for answer in answers))
    return state


def decky_installer_runs(state: Path) -> int:
    return len(log_lines(state, "decky-installer.log"))


def test_decky_installed_asks_nothing_and_fetches_no_installer(tmp_path: Path) -> None:
    """Decky Loader that is there is never touched: no question, and its
    installer is not even downloaded (the fixture URL holds no file)."""
    base = release(tmp_path)
    plugin_dir = tmp_path / "plugins"
    curl_dir, log = logging_curl_bin(tmp_path)
    (tmp_path / "tty").write_text("y\n")
    result = run_install(tmp_path, base, plugin_dir, extra_path_dirs=(curl_dir,))
    assert result.returncode == 0, result.stderr
    assert DECKY_QUESTION not in result.stdout
    assert "Decky Loader is new here" not in result.stdout
    assert "install_release.sh" not in log.read_text()
    sudo = log_lines(state_dir(tmp_path), "sudo.log")
    assert [line.split()[0] for line in sudo] == ["mkdir", "rm", "unzip", "systemctl"]


def test_no_decky_and_yes_installs_decky_then_the_plugin(tmp_path: Path) -> None:
    base = release(tmp_path)
    plugin_dir = tmp_path / "plugins"
    state = without_decky(tmp_path, "y")
    result = run_install(tmp_path, base, plugin_dir)
    assert result.returncode == 0, result.stderr
    assert DECKY_QUESTION in result.stdout
    assert str(decky_loader(tmp_path)) in result.stdout
    assert decky_installer(tmp_path).as_uri() in result.stdout
    assert "fake-decky-installer" in result.stdout
    assert decky_installer_runs(state) == 1
    assert decky_loader(tmp_path).exists()
    assert (plugin_dir / "Moonlight Sync" / "plugin.json").exists()
    # Decky's installer first, under sudo, then the plugin's four steps.
    sudo = log_lines(state, "sudo.log")
    assert sudo[0].split()[0] in ("bash", "sh")
    assert sudo[0].endswith("/" + DECKY_SCRIPT)
    assert [line.split()[0] for line in sudo[1:]] == ["mkdir", "rm", "unzip", "systemctl"]
    installed = result.stdout.index("Decky Loader is installed.")
    assert installed < result.stdout.index("Installed Moonlight Sync")
    # A Steam that was running before Decky arrived has to restart.
    assert "Decky Loader is new here" in result.stdout
    assert "Steam has" in result.stdout


@pytest.mark.parametrize("answer", ["n", "", "maybe", None])
def test_no_decky_and_no_installs_nothing(tmp_path: Path, answer: str | None) -> None:
    """Anything but a yes, no terminal included: nothing is downloaded,
    nothing runs under sudo, and the script says what to do instead."""
    base = release(tmp_path)
    plugin_dir = tmp_path / "plugins"
    state = without_decky(tmp_path, *([] if answer is None else [answer]))
    curl_dir, log = logging_curl_bin(tmp_path)
    result = run_install(tmp_path, base, plugin_dir, extra_path_dirs=(curl_dir,))
    assert result.returncode == 1
    assert DECKY_QUESTION in result.stdout
    assert "nothing was installed" in result.stderr
    assert "Install Decky Loader (https://decky.xyz)" in result.stderr
    assert not log.exists()
    assert log_lines(state, "sudo.log") == []
    assert decky_installer_runs(state) == 0
    assert not decky_loader(tmp_path).exists()
    assert not plugin_dir.exists()


def test_no_decky_on_a_stock_deck_uses_the_temporary_password(tmp_path: Path) -> None:
    """Two questions, two answers: Decky's installer runs with the
    temporary password on sudo's stdin, like the plugin's own steps, and
    the password is gone at the end."""
    base = release(tmp_path)
    plugin_dir = tmp_path / "plugins"
    stock_deck(tmp_path)
    state = without_decky(tmp_path, "y", "yes")
    result = run_install(tmp_path, base, plugin_dir)
    assert result.returncode == 0, result.stderr
    assert result.stdout.index(DECKY_QUESTION) < result.stdout.index(QUESTION)
    assert decky_installer_runs(state) == 1
    assert (plugin_dir / "Moonlight Sync" / "plugin.json").exists()
    assert (state / "status").read_text().strip() == "NP"
    assert not (state / "password").exists()
    assert "You may be asked" not in result.stdout
    sudo = log_lines(state, "sudo.log")
    assert sudo[:2] == ["-n true", "-S -k -p  true"]
    assert sudo[2].startswith("-S -p ")
    assert sudo[2].endswith("/" + DECKY_SCRIPT)
    assert [line.split()[2] for line in sudo[3:7]] == ["mkdir", "rm", "unzip", "systemctl"]


def test_yes_to_decky_but_no_to_the_password_installs_nothing(tmp_path: Path) -> None:
    """The second question reads the second line, not the first again."""
    base = release(tmp_path)
    plugin_dir = tmp_path / "plugins"
    stock_deck(tmp_path)
    state = without_decky(tmp_path, "y", "n")
    result = run_install(tmp_path, base, plugin_dir)
    assert result.returncode == 1
    assert DECKY_QUESTION in result.stdout
    assert QUESTION in result.stdout
    assert "nothing was installed" in result.stderr
    assert decky_installer_runs(state) == 0
    assert not decky_loader(tmp_path).exists()
    assert not plugin_dir.exists()
    assert not password_was_set(state)
    assert log_lines(state, "sudo.log") == ["-n true"]


def test_a_decky_installer_that_cannot_be_downloaded_installs_nothing(tmp_path: Path) -> None:
    base = release(tmp_path)
    plugin_dir = tmp_path / "plugins"
    stock_deck(tmp_path)
    state = without_decky(tmp_path, "y", "y")
    decky_installer(tmp_path).unlink()
    result = run_install(tmp_path, base, plugin_dir)
    assert result.returncode == 1
    assert f"install.sh: could not download {decky_installer(tmp_path).as_uri()}" in result.stderr
    assert "Nothing was installed" in result.stderr
    # Before the password question, so no password was ever set.
    assert QUESTION not in result.stdout
    assert not password_was_set(state)
    assert log_lines(state, "sudo.log") == []
    assert not plugin_dir.exists()


def test_a_plugin_that_cannot_be_downloaded_leaves_decky_uninstalled(tmp_path: Path) -> None:
    """Everything is downloaded and verified before anything is installed,
    Decky Loader included."""
    base = release(tmp_path)
    (asset_dir(base) / ASSET).unlink()
    plugin_dir = tmp_path / "plugins"
    state = without_decky(tmp_path, "y")
    result = run_install(tmp_path, base, plugin_dir)
    assert result.returncode == 1
    assert "(is latest released?)" in result.stderr
    assert decky_installer_runs(state) == 0
    assert log_lines(state, "sudo.log") == []
    assert not decky_loader(tmp_path).exists()


def test_a_failed_decky_installer_stops_before_the_plugin(tmp_path: Path) -> None:
    base = release(tmp_path)
    plugin_dir = tmp_path / "plugins"
    stock_deck(tmp_path)
    state = without_decky(tmp_path, "y", "y")
    (state / "decky-installer-fails").touch()
    result = run_install(tmp_path, base, plugin_dir)
    assert result.returncode == 1
    assert "Decky Loader's installer failed (exit 1)" in result.stderr
    assert "Moonlight Sync was not installed" in result.stderr
    assert decky_installer_runs(state) == 1
    assert not plugin_dir.exists()
    assert "Installed Moonlight Sync" not in result.stdout
    # The temporary password still comes off.
    assert "Removed the temporary password" in result.stdout
    assert (state / "status").read_text().strip() == "NP"
    assert not (state / "password").exists()


def test_a_decky_installer_that_installs_nothing_stops_before_the_plugin(
    tmp_path: Path,
) -> None:
    base = release(tmp_path)
    plugin_dir = tmp_path / "plugins"
    state = without_decky(tmp_path, "y")
    (state / "decky-installer-installs-nothing").touch()
    result = run_install(tmp_path, base, plugin_dir)
    assert result.returncode == 1
    assert f"there is still no {decky_loader(tmp_path)}" in result.stderr
    assert "Moonlight Sync was not installed" in result.stderr
    assert decky_installer_runs(state) == 1
    assert not plugin_dir.exists()


def test_piped_to_sh_the_decky_installer_never_reads_the_script(tmp_path: Path) -> None:
    """`curl … | sh`: install.sh is on stdin, and the fixture installer
    eats its own stdin whole. Were that the script's, sh would lose
    whatever of it it had not read yet. How much that is depends on the sh
    (dash reads a pipe 8 KiB at a time, bash a byte at a time), so the
    script is followed by more than any sh buffers and then one last
    command, which must still run."""
    base = release(tmp_path)
    plugin_dir = tmp_path / "plugins"
    state = without_decky(tmp_path, "y")
    trailer = ": padding\n" * 20000 + "echo the-trailer-ran\n"
    result = subprocess.run(
        ["sh"],
        input=(ROOT / "install.sh").read_text() + trailer,
        capture_output=True,
        text=True,
        env=install_env(tmp_path, base, plugin_dir),
        cwd=str(tmp_path),
        timeout=60,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert decky_installer_runs(state) == 1
    assert (plugin_dir / "Moonlight Sync" / "plugin.json").exists()
    assert "Installed Moonlight Sync" in result.stdout
    assert (state / "decky-installer.stdin").read_bytes() == b""
    assert "the-trailer-ran" in result.stdout


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
