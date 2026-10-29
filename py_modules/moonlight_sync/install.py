"""The bundled CLI: version reading and the install/upgrade into ~/.local/bin.

The plugin zip carries ``bin/moonlight-steam-sync.pyz`` (spec 3.6.1). On
startup the backend compares it with ``~/.local/bin/moonlight-steam-sync``
and copies the bundle into place when the installed copy is missing or
older, and also when it has the same version but other bytes (update spec
3.12.3, Decision U12: a branch build's CLI carries the version its branch
does, ``X.Y.Z.dev0`` for ``main``'s ``X.Y.Z-SNAPSHOT``, which
:func:`parse_version` reads as ``X.Y.Z``, so build after build of a branch
shares one version and without this its CLI would never reach the device;
it also replaces a hand-installed build of the same version), and when the
installed copy is a snapshot (``X.Y.Z.dev0``, a build of ``main``) and the
bundle is a release, whatever their numbers: a build of ``main`` carries the
*next* release's number, so going back to a release would otherwise leave
the snapshot's CLI in place as the "newer" one. Apart from that it never
downgrades: a newer release CLI the user installed by hand stays, and so
does one of the same version whose bytes are the bundle's.

A symlink at ``~/.local/bin/moonlight-steam-sync`` is replaced by the file
itself, never written through, in both cases (older, or the same version
with other bytes): the copy goes to a ``.tmp`` beside it and ``os.replace``
swaps the link for it, so the file the link pointed to is left untouched.

Both copies are always run through an explicit interpreter
(``[python3, path, ...]``), so neither the exec bit nor the plugin_loader
service's minimal ``PATH`` matters.
"""

from __future__ import annotations

import contextlib
import hashlib
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
#: A snapshot's spelling after ``X.Y.Z``: the CLI's ``.dev0`` (PEP 440, what
#: ``scripts/build_cli.py``'s ``cli_spelling`` writes for ``package.json``'s
#: ``-SNAPSHOT``), and the plugin's ``-SNAPSHOT`` itself for good measure.
_SNAPSHOT_RE = re.compile(r"^\d+\.\d+\.\d+(\.dev\d*|-SNAPSHOT)(?![\w])")


def parse_version(text: str) -> Version | None:
    """``"0.3.0"`` / ``"0.4.0.dev1"`` / ``"1.2.3rc1"`` -> a tuple; else ``None``."""
    match = _VERSION_RE.match(text.strip())
    if not match:
        return None
    return (int(match.group(1)), int(match.group(2)), int(match.group(3)))


def is_snapshot(text: str) -> bool:
    """``"0.14.0.dev0"`` / ``"0.14.0-SNAPSHOT"`` -> True; a release, or no version, False."""
    return _SNAPSHOT_RE.match(text.strip()) is not None


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
    text = read_version_text(argv_prefix, env=env, cwd=cwd, timeout=timeout)
    return None if text is None else parse_version(text)


def read_version_text(
    argv_prefix: list[str],
    *,
    env: dict[str, str] | None = None,
    cwd: str | None = None,
    timeout: float = 10,
) -> str | None:
    """The last token of ``--version``'s stdout, unparsed (``"0.14.0.dev0"``), or ``None``."""
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
    return tokens[-1]


@dataclass
class InstallReport:
    """What :func:`ensure_installed` found and did; logged and shown in About."""

    bundled: Version | None
    installed: Version | None
    #: ``"installed"`` (was missing), ``"upgraded"`` (was older),
    #: ``"replaced"`` (the same version with other bytes, or a snapshot
    #: replaced by a release), ``"kept"`` (newer, or the same version and
    #: bytes), ``"none"`` (no usable bundle), ``"failed"``.
    action: str
    error: str | None = None


def sha256_file(path: str, chunk: int = 64 * 1024) -> str:
    """The file's sha256 as 64 lower-case hex digits, read in chunks."""
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        while block := handle.read(chunk):
            digest.update(block)
    return digest.hexdigest()


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
    """Install the bundled CLI when the installed one is missing, older, the
    same version with other bytes (``"replaced"``, Decision U12), or a
    snapshot while the bundle is a release (``"replaced"`` too).

    Otherwise never downgrades, and never raises: every failure becomes
    ``InstallReport.error`` with the installed copy untouched.
    """
    installed_text = (
        read_version_text([python, installed_path], env=env, cwd=cwd)
        if os.path.exists(installed_path)
        else None
    )
    installed = None if installed_text is None else parse_version(installed_text)
    if not os.path.exists(bundled_path):
        # Packaged without building the CLI (a developer's
        # `scripts/package.py` with no backend/out/): nothing to install,
        # and not an error either -- About explains it.
        return InstallReport(bundled=None, installed=installed, action="none")

    if not os.access(bundled_path, os.R_OK):
        return InstallReport(
            bundled=None,
            installed=installed,
            action="failed",
            error=f"the bundled CLI at {bundled_path} is not readable",
        )
    bundled_text = read_version_text([python, bundled_path], env=env, cwd=cwd)
    bundled = None if bundled_text is None else parse_version(bundled_text)
    if bundled is None or bundled_text is None:
        return InstallReport(
            bundled=None,
            installed=installed,
            action="failed",
            error=f"the bundled CLI at {bundled_path} did not report a version",
        )
    # A release's CLI replaces a snapshot's whatever their numbers (a build
    # of main is numbered after the release it follows); any other newer
    # installed CLI is kept.
    release_over_snapshot = (
        installed_text is not None and is_snapshot(installed_text) and not is_snapshot(bundled_text)
    )
    if installed is not None and installed > bundled and not release_over_snapshot:
        return InstallReport(bundled=bundled, installed=installed, action="kept")
    if installed is not None and installed == bundled:
        try:
            same = sha256_file(installed_path) == sha256_file(bundled_path)
        except OSError as exc:
            return InstallReport(
                bundled=bundled,
                installed=installed,
                action="failed",
                error=f"could not compare {installed_path} with the bundled CLI: {exc}",
            )
        if same:
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
    if installed is None:
        action = "installed"
    elif installed == bundled or release_over_snapshot:
        action = "replaced"
    else:
        action = "upgraded"
    after = read_version([python, installed_path], env=env, cwd=cwd)
    return InstallReport(bundled=bundled, installed=after, action=action)
