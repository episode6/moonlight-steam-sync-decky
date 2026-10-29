"""scripts/ship_release.py: the GitHub release made from a release branch,
run against a fixture tree and a fake `gh` on PATH that logs its argv."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from conftest import ROOT

SCRIPT = ROOT / "scripts" / "ship_release.py"
INIT = Path("cli") / "src" / "moonlight_steam_sync" / "__init__.py"

pytestmark = pytest.mark.skipif(not shutil.which("sh"), reason="needs sh")

CHANGELOG = """# Changelog

## [Unreleased]

## [0.14.0] - 2026-11-02

### Added

- **A thing.** It does things.

### Fixed

- A fix.

## [0.13.2] - 2026-10-29

### Fixed

- An older fix.
"""

FAKE_GH = """#!/bin/sh
printf '%s\\n' "$*" >> "$FAKE_GH_LOG"
if [ "${FAKE_GH_FAIL:-}" = 1 ]; then echo "HTTP 422: Validation Failed" >&2; exit 1; fi
for arg in "$@"; do
  case "$last" in --notes-file) cp "$arg" "$FAKE_GH_NOTES" ;; esac
  last=$arg
done
echo "https://github.com/episode6/moonlight-steam-sync-decky/releases/tag/$3"
"""


@pytest.fixture
def tree(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    (root / INIT).parent.mkdir(parents=True)
    write_version(root, "0.14.0", "0.14.0")
    (root / "CHANGELOG.md").write_text(CHANGELOG)
    return root


def write_version(root: Path, plugin: str, cli: str) -> None:
    (root / "package.json").write_text(
        json.dumps({"name": "x", "version": plugin}, indent=2) + "\n"
    )
    (root / INIT).write_text(f'__version__ = "{cli}"\n')


def ship(
    root: Path, *args: str, fail_gh: bool = False
) -> tuple[subprocess.CompletedProcess[str], list[str], str | None]:
    """Run the script with a fake gh; the result, gh's argv log and the notes it was given."""
    tmp = root.parent
    bin_dir = tmp / "bin"
    bin_dir.mkdir(exist_ok=True)
    gh = bin_dir / "gh"
    gh.write_text(FAKE_GH)
    gh.chmod(0o755)
    log = tmp / "gh.log"
    notes = tmp / "gh.notes"
    log.unlink(missing_ok=True)
    notes.unlink(missing_ok=True)
    env = {
        **os.environ,
        "PATH": f"{bin_dir}{os.pathsep}{os.environ.get('PATH', '')}",
        "FAKE_GH_LOG": str(log),
        "FAKE_GH_NOTES": str(notes),
        "FAKE_GH_FAIL": "1" if fail_gh else "",
    }
    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--root",
            str(root),
            "--output",
            str(tmp / "report.json"),
            *args,
        ],
        capture_output=True,
        text=True,
        check=False,
        env=env,
        cwd=str(tmp),
    )
    calls = log.read_text().splitlines() if log.exists() else []
    return result, calls, notes.read_text() if notes.exists() else None


def report(root: Path) -> dict:
    return json.loads((root.parent / "report.json").read_text())


EXPECTED_NOTES = "### Added\n\n- **A thing.** It does things.\n\n### Fixed\n\n- A fix."


def test_ships_the_release_branch_with_the_changelog_section(tree: Path) -> None:
    result, calls, notes = ship(tree, "--branch", "release/v0.14.0")
    assert result.returncode == 0, result.stderr
    assert len(calls) == 1
    argv = calls[0].split()
    assert argv[:6] == ["release", "create", "v0.14.0", "--target", "release/v0.14.0", "--title"]
    assert argv[6:8] == ["v0.14.0", "--notes-file"]
    assert notes == EXPECTED_NOTES + "\n"
    assert report(tree) == {
        "success": True,
        "dry_run": False,
        "tag": "v0.14.0",
        "title": "v0.14.0",
        "version": "0.14.0",
        "branch": "release/v0.14.0",
        "notes": EXPECTED_NOTES,
        "url": "https://github.com/episode6/moonlight-steam-sync-decky/releases/tag/v0.14.0",
    }
    assert (
        "created https://github.com/episode6/moonlight-steam-sync-decky/releases/tag/v0.14.0"
        in result.stdout
    )
    assert not list(tree.parent.glob("release-notes-*"))


def test_a_dry_run_runs_nothing_and_reports_the_command(tree: Path) -> None:
    result, calls, _ = ship(tree, "--branch", "release/v0.14.0", "--dry-run")
    assert result.returncode == 0, result.stderr
    assert calls == []
    got = report(tree)
    assert got["dry_run"] is True and got["success"] is True and "url" not in got
    assert got["command"].startswith(
        "gh release create v0.14.0 --target release/v0.14.0 --title v0.14.0 --notes-file "
    )
    assert "- **A thing.** It does things." in result.stdout


def test_the_branch_defaults_to_the_one_checked_out(tree: Path) -> None:
    git = {
        "GIT_CONFIG_GLOBAL": os.devnull,
        "GIT_CONFIG_SYSTEM": os.devnull,
        "HOME": str(tree.parent),
    }
    env = {**os.environ, **git}
    subprocess.run(["git", "init", "-q", "-b", "release/v0.14.0", str(tree)], check=True, env=env)
    result, calls, _ = ship(tree)
    assert result.returncode == 0, result.stderr
    assert "--target release/v0.14.0" in calls[0]
    assert report(tree)["branch"] == "release/v0.14.0"


def test_a_snapshot_is_refused_before_anything_runs(tree: Path) -> None:
    write_version(tree, "0.14.0-SNAPSHOT", "0.14.0.dev0")
    result, calls, _ = ship(tree, "--branch", "release/v0.14.0")
    assert result.returncode == 1
    assert "0.14.0-SNAPSHOT, a snapshot" in result.stderr
    assert calls == []
    assert not (tree.parent / "report.json").exists()


def test_a_branch_that_is_not_a_release_branch_is_refused(tree: Path) -> None:
    result, calls, _ = ship(tree, "--branch", "main")
    assert result.returncode == 1
    assert "main is not a release/* branch" in result.stderr
    assert calls == []
    # A dry run only warns, so the notes can be checked from anywhere.
    result, calls, _ = ship(tree, "--branch", "main", "--dry-run")
    assert result.returncode == 0, result.stderr
    assert "[dry-run] warning: main is not a release/* branch" in result.stderr
    assert calls == []


def test_a_cli_version_that_disagrees_is_refused(tree: Path) -> None:
    write_version(tree, "0.14.0", "0.13.2")
    result, calls, _ = ship(tree, "--branch", "release/v0.14.0")
    assert result.returncode == 1
    assert "the CLI's __version__ (0.13.2) is not package.json's version (0.14.0)" in result.stderr
    assert calls == []


def test_a_missing_changelog_section_is_refused(tree: Path) -> None:
    write_version(tree, "0.15.0", "0.15.0")
    result, calls, _ = ship(tree, "--branch", "release/v0.15.0")
    assert result.returncode == 1
    assert "no '## [0.15.0] - YYYY-MM-DD' section" in result.stderr
    assert calls == []


def test_an_empty_changelog_section_is_a_warning(tree: Path) -> None:
    (tree / "CHANGELOG.md").write_text(
        "## [Unreleased]\n\n## [0.14.0] - 2026-11-02\n\n## [0.13.2] - 2026-10-29\n\n- x\n"
    )
    result, calls, notes = ship(tree, "--branch", "release/v0.14.0")
    assert result.returncode == 0, result.stderr
    assert "[0.14.0] section is empty" in result.stderr
    assert len(calls) == 1 and notes == "\n"
    assert report(tree)["notes"] == ""


def test_a_failed_gh_fails_with_its_message(tree: Path) -> None:
    result, calls, _ = ship(tree, "--branch", "release/v0.14.0", fail_gh=True)
    assert result.returncode == 1
    assert "gh release create failed: HTTP 422: Validation Failed" in result.stderr
    assert len(calls) == 1
    assert not (tree.parent / "report.json").exists()
    assert not list(tree.parent.glob("release-notes-*"))


def test_the_real_changelog_s_latest_release_has_a_section() -> None:
    # The format ship_release.py reads is the repo's: every released version
    # heads a `## [X.Y.Z] - YYYY-MM-DD` section below `## [Unreleased]`.
    text = (ROOT / "CHANGELOG.md").read_text()
    assert "\n## [Unreleased]\n" in text
    assert "\n## [0.13.2] - 2026-10-29\n" in text
