"""The bundled CLI: version reading and the install/upgrade into ~/.local/bin.

The plugin zip carries ``bin/moonlight-steam-sync.pyz`` (spec 3.6.1). On
startup the backend compares it with ``~/.local/bin/moonlight-steam-sync``
and copies the bundle into place when the installed copy is missing or
older. It never downgrades: a newer CLI the user installed by hand stays.

Both copies are always run through an explicit interpreter
(``[python3, path, ...]``), so neither the exec bit nor the plugin_loader
service's minimal ``PATH`` matters.
"""

from __future__ import annotations

import contextlib
import os
import re
import shutil
import subprocess
from dataclasses import dataclass

#: The oldest CLI the plugin can drive (``--json``, ``--commit``, ``host``...).
#: The one place this value lives.
MIN_CLI_VERSION: tuple[int, int, int] = (0, 4, 0)

Version = tuple[int, int, int]

_VERSION_RE = re.compile(r"^(\d+)\.(\d+)\.(\d+)")


def parse_version(text: str) -> Version | None:
    """``"0.3.0"`` / ``"0.4.0.dev1"`` / ``"1.2.3rc1"`` -> a tuple; else ``None``."""
    match = _VERSION_RE.match(text.strip())
    if not match:
        return None
    return (int(match.group(1)), int(match.group(2)), int(match.group(3)))


def format_version(version: Version | None) -> str | None:
    return None if version is None else ".".join(str(part) for part in version)


def read_version(
    argv_prefix: list[str],
    *,
    env: dict[str, str] | None = None,
    cwd: str | None = None,
    timeout: float = 10,
) -> Version | None:
    """Run ``argv_prefix + ["--version"]`` and parse the last token of stdout.

    argparse prints ``%(prog)s X.Y.Z`` and ``prog`` differs between the
    installed script, the ``.pyz`` and a ``-m`` run, so only the last
    whitespace-separated token is looked at. A non-zero exit, a timeout, an
    ``OSError`` or no match all return ``None`` ("missing").
    """
    try:
        proc = subprocess.run(
            [*argv_prefix, "--version"],
            capture_output=True,
            text=True,
            timeout=timeout,
            env=env,
            cwd=cwd,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if proc.returncode != 0:
        return None
    tokens = proc.stdout.split()
    if not tokens:
        return None
    return parse_version(tokens[-1])


@dataclass
class InstallReport:
    """What :func:`ensure_installed` found and did; logged and shown in About."""

    bundled: Version | None
    installed: Version | None
    #: ``"installed"`` (was missing), ``"upgraded"`` (was older), ``"kept"``
    #: (same or newer), ``"none"`` (no usable bundle), ``"failed"``.
    action: str
    error: str | None = None


def install_file(source: str, target: str) -> None:
    """Copy ``source`` to ``target`` atomically: ``.tmp``, ``chmod 755``, ``os.replace``.

    Creates the target directory when absent. On any failure the ``.tmp`` is
    removed and the existing target is left exactly as it was.
    """
    os.makedirs(os.path.dirname(target), exist_ok=True)
    tmp = target + ".tmp"
    try:
        shutil.copyfile(source, tmp)
        os.chmod(tmp, 0o755)
        os.replace(tmp, target)
    except BaseException:
        with contextlib.suppress(OSError):
            os.unlink(tmp)
        raise


def ensure_installed(
    python: str,
    bundled_path: str,
    installed_path: str,
    *,
    env: dict[str, str] | None = None,
    cwd: str | None = None,
) -> InstallReport:
    """Install or upgrade the bundled CLI when the installed one is missing or older.

    Never downgrades and never raises: every failure becomes
    ``InstallReport.error`` with the installed copy untouched.
    """
    installed = (
        read_version([python, installed_path], env=env, cwd=cwd)
        if os.path.exists(installed_path)
        else None
    )
    if not os.path.exists(bundled_path):
        # Packaged before the CLI release existed (spec 3.6.2): nothing to
        # install, and not an error either -- About explains it.
        return InstallReport(bundled=None, installed=installed, action="none")

    if not os.access(bundled_path, os.R_OK):
        return InstallReport(
            bundled=None,
            installed=installed,
            action="failed",
            error=f"the bundled CLI at {bundled_path} is not readable",
        )
    bundled = read_version([python, bundled_path], env=env, cwd=cwd)
    if bundled is None:
        return InstallReport(
            bundled=None,
            installed=installed,
            action="failed",
            error=f"the bundled CLI at {bundled_path} did not report a version",
        )
    if installed is not None and installed >= bundled:
        return InstallReport(bundled=bundled, installed=installed, action="kept")

    try:
        install_file(bundled_path, installed_path)
    except OSError as exc:
        return InstallReport(
            bundled=bundled,
            installed=installed,
            action="failed",
            error=f"could not install {installed_path}: {exc}",
        )
    action = "installed" if installed is None else "upgraded"
    after = read_version([python, installed_path], env=env, cwd=cwd)
    return InstallReport(bundled=bundled, installed=after, action=action)
