"""Build the release zipapp exactly the way the release does -- through the
repo root's ``scripts/build_cli.py``, which ``backend/entrypoint.sh`` runs
for the plugin zip and the release's own ``moonlight-steam-sync.pyz`` asset
-- and smoke-run it the same way -- ``--version`` and ``doctor`` -- so a
regression in the packaging invocation (spec 3.1) fails locally, not only in
CI's own build of the workflow.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

#: cli/, the CLI's own root (its README, pyproject.toml and src/).
REPO_ROOT = Path(__file__).resolve().parent.parent
#: The repository root: the plugin, with the shared build script.
MONOREPO_ROOT = REPO_ROOT.parent


def _build_pyz(tmp_path: Path) -> Path:
    out = tmp_path / "moonlight-steam-sync.pyz"
    subprocess.run(
        [
            sys.executable,
            str(MONOREPO_ROOT / "scripts" / "build_cli.py"),
            "--root",
            str(MONOREPO_ROOT),
            "--out",
            str(out),
        ],
        check=True,
        capture_output=True,
        timeout=60,
    )
    return out


def test_zipapp_builds_and_reports_its_version(tmp_path):
    pyz = _build_pyz(tmp_path)
    assert pyz.is_file()

    result = subprocess.run(
        [sys.executable, str(pyz), "--version"],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr
    # Exactly the embedded __version__, even though this interpreter may
    # have the CLI pip-installed (editable) at some other version.
    from moonlight_steam_sync import __version__

    assert result.stdout.split()[-1] == __version__


def test_zipapp_doctor_smoke_run(tmp_path):
    """``doctor`` (spec 3.3) must run to completion -- exit 0 -- with no
    Steam install, no ``moonlight`` binary and no config file present, which
    is exactly the state of a CI runner or a fresh install."""
    pyz = _build_pyz(tmp_path)

    env = {
        "PATH": "/usr/bin:/bin",
        "HOME": str(tmp_path),
        "XDG_CONFIG_HOME": str(tmp_path / "config"),
        "XDG_CACHE_HOME": str(tmp_path / "cache"),
    }
    result = subprocess.run(
        [sys.executable, str(pyz), "doctor"],
        capture_output=True,
        text=True,
        timeout=30,
        env=env,
    )
    assert result.returncode == 0, result.stderr
    assert "python:" in result.stdout
    assert "steam dir:" in result.stdout


def _extract_git_checkout_command(readme: str) -> str:
    """Pull the fenced shell block that follows "run from a git checkout"
    out of README.md, so this test fails the moment the documented command
    and the actual package layout (``src/`` layout, spec 3.1) drift apart --
    exactly the way they did when the README told the user to run
    ``python3 -m moonlight_steam_sync`` from the repo root with no
    ``PYTHONPATH``, which fails against ``[tool.setuptools.packages.find]
    where = ["src"]``."""
    match = re.search(
        r"run from a git checkout instead:\n\n```sh\n(.*?)\n```",
        readme,
        re.DOTALL,
    )
    assert match, "README.md's git-checkout install snippet has moved or been reworded"
    lines = [line for line in match.group(1).splitlines() if line.strip()]
    # The last non-empty line is the command that actually runs the tool;
    # the ones before it are `git clone` / `cd`.
    return lines[-1]


def test_readme_git_checkout_command_actually_works():
    readme = (REPO_ROOT / "README.md").read_text()
    command = _extract_git_checkout_command(readme)

    # The snippet is meant to be run with cwd already at the repo root (it
    # follows `git clone` + `cd moonlight-steam-sync`), so run it from here
    # verbatim through the shell rather than re-deriving PYTHONPATH.
    result = subprocess.run(
        command,
        shell=True,
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=30,
        env={**os.environ, "PYTHONPATH": ""},
    )
    assert result.returncode == 0, (
        f"README's documented command `{command}` failed:\n{result.stderr}"
    )
    assert "moonlight-steam-sync" in result.stdout
