"""scripts/ship_release.py: the GitHub release made from a release branch,
run against a fixture checkout (a scratch repo on release/v0.14.0, pushed to
a bare `origin`) and a fake `gh` on PATH that logs its argv."""

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
BRANCH = "release/v0.14.0"

pytestmark = pytest.mark.skipif(
    not shutil.which("sh") or not shutil.which("git"), reason="needs sh and git"
)

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

GIT_ENV = {
    "GIT_CONFIG_GLOBAL": os.devnull,
    "GIT_CONFIG_SYSTEM": os.devnull,
    "GIT_AUTHOR_NAME": "t",
    "GIT_AUTHOR_EMAIL": "t@example.invalid",
    "GIT_COMMITTER_NAME": "t",
    "GIT_COMMITTER_EMAIL": "t@example.invalid",
}


def clean_env(home: Path) -> dict[str, str]:
    """The environment with the machine's git configuration shut out."""
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    return {**env, **GIT_ENV, "HOME": str(home)}


def git(root: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(root), *args],
        capture_output=True,
        text=True,
        check=True,
        env=clean_env(root.parent),
    ).stdout.strip()


@pytest.fixture
def tree(tmp_path: Path) -> Path:
    """A checkout of release/v0.14.0 at version 0.14.0, pushed to a bare origin."""
    root = tmp_path / "repo"
    (root / INIT).parent.mkdir(parents=True)
    write_version(root, "0.14.0", "0.14.0")
    (root / "CHANGELOG.md").write_text(CHANGELOG)
    git(root, "init", "-q", "-b", BRANCH)
    commit_all(root, "release")
    origin = tmp_path / "origin.git"
    subprocess.run(
        ["git", "init", "-q", "--bare", str(origin)], check=True, env=clean_env(tmp_path)
    )
    git(root, "remote", "add", "origin", str(origin))
    git(root, "push", "-q", "origin", BRANCH)
    return root


def write_version(root: Path, plugin: str, cli: str) -> None:
    (root / "package.json").write_text(
        json.dumps({"name": "x", "version": plugin}, indent=2) + "\n"
    )
    (root / INIT).write_text(f'__version__ = "{cli}"\n')


def commit_all(root: Path, message: str) -> None:
    git(root, "add", "-A")
    git(root, "commit", "-q", "-m", message)


def commit_and_push(root: Path, message: str) -> None:
    commit_all(root, message)
    git(root, "push", "-q", "origin", "HEAD")


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
        **clean_env(tmp),
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
URL = "https://github.com/episode6/moonlight-steam-sync-decky/releases/tag/v0.14.0"


def test_ships_the_branch_checked_out_with_the_changelog_section(tree: Path) -> None:
    result, calls, notes = ship(tree)
    assert result.returncode == 0, result.stderr
    assert len(calls) == 1
    argv = calls[0].split()
    assert argv[:8] == [
        "release",
        "create",
        "v0.14.0",
        "--target",
        BRANCH,
        "--title",
        "v0.14.0",
        "--notes-file",
    ]
    assert notes == EXPECTED_NOTES + "\n"
    assert report(tree) == {
        "success": True,
        "dry_run": False,
        "tag": "v0.14.0",
        "title": "v0.14.0",
        "version": "0.14.0",
        "branch": BRANCH,
        "notes": EXPECTED_NOTES,
        "url": URL,
    }
    assert f"created {URL}" in result.stdout
    assert not list(tree.parent.glob("release-notes-*"))


def test_branch_may_name_the_one_checked_out(tree: Path) -> None:
    result, calls, _ = ship(tree, "--branch", BRANCH)
    assert result.returncode == 0, result.stderr
    assert len(calls) == 1 and f"--target {BRANCH}" in calls[0]


def test_a_dry_run_runs_nothing_and_reports_the_command(tree: Path) -> None:
    result, calls, _ = ship(tree, "--dry-run")
    assert result.returncode == 0, result.stderr
    assert calls == []
    got = report(tree)
    assert got["dry_run"] is True and got["success"] is True and "url" not in got
    assert got["command"] == (
        f"gh release create v0.14.0 --target {BRANCH} --title v0.14.0 --notes-file RELEASE_NOTES.md"
    )
    assert "- **A thing.** It does things." in result.stdout
    assert not list(tree.parent.glob("release-notes-*"))


def test_another_branch_than_the_one_checked_out_is_refused(tree: Path) -> None:
    result, calls, _ = ship(tree, "--branch", "release/v0.15.0")
    assert result.returncode == 1
    assert f"release/v0.15.0 is not the branch checked out ({BRANCH})" in result.stderr
    assert calls == []
    assert not (tree.parent / "report.json").exists()
    # A dry run only warns.
    result, calls, _ = ship(tree, "--branch", "release/v0.15.0", "--dry-run")
    assert result.returncode == 0, result.stderr
    assert "[dry-run] warning: release/v0.15.0 is not the branch checked out" in result.stderr
    assert calls == [] and report(tree)["branch"] == "release/v0.15.0"


def test_a_local_commit_origin_lacks_is_refused(tree: Path) -> None:
    (tree / "CHANGELOG.md").write_text(CHANGELOG.replace("A fix.", "A fix, reworded."))
    commit_all(tree, "not pushed")
    head = git(tree, "rev-parse", "HEAD")[:7]
    result, calls, _ = ship(tree)
    assert result.returncode == 1
    assert f"not the local {head}: pull (or push)" in result.stderr
    assert calls == []
    assert not (tree.parent / "report.json").exists()
    # A dry run only warns, and still shows the local notes.
    result, calls, _ = ship(tree, "--dry-run")
    assert result.returncode == 0, result.stderr
    assert f"[dry-run] warning: origin/{BRANCH} is at" in result.stderr
    assert calls == [] and "A fix, reworded." in report(tree)["notes"]


def test_a_branch_origin_does_not_have_is_refused(tree: Path) -> None:
    git(tree, "checkout", "-q", "-b", "release/v0.15.0")
    result, calls, _ = ship(tree)
    assert result.returncode == 1
    assert "origin/release/v0.15.0 is at nothing" in result.stderr
    assert calls == []


def test_a_detached_head_is_refused(tree: Path) -> None:
    git(tree, "checkout", "-q", "--detach")
    result, calls, _ = ship(tree)
    assert result.returncode == 1
    assert "cannot read the current branch" in result.stderr
    assert calls == []


def test_a_snapshot_is_refused_before_anything_runs(tree: Path) -> None:
    write_version(tree, "0.14.0-SNAPSHOT", "0.14.0.dev0")
    commit_and_push(tree, "snapshot")
    result, calls, _ = ship(tree)
    assert result.returncode == 1
    assert "0.14.0-SNAPSHOT, a snapshot" in result.stderr
    assert calls == []
    assert not (tree.parent / "report.json").exists()


def test_a_branch_that_is_not_a_release_branch_is_refused(tree: Path) -> None:
    git(tree, "checkout", "-q", "-b", "topic")
    git(tree, "push", "-q", "origin", "topic")
    result, calls, _ = ship(tree)
    assert result.returncode == 1
    assert "topic is not a release/* branch" in result.stderr
    assert calls == []
    # A dry run only warns (main itself is still refused for its snapshot
    # version; this is for a release-shaped branch under another name).
    result, calls, _ = ship(tree, "--dry-run")
    assert result.returncode == 0, result.stderr
    assert "[dry-run] warning: topic is not a release/* branch" in result.stderr
    assert calls == []


def test_a_cli_version_that_disagrees_is_refused(tree: Path) -> None:
    write_version(tree, "0.14.0", "0.13.2")
    commit_and_push(tree, "mismatch")
    result, calls, _ = ship(tree)
    assert result.returncode == 1
    assert "the CLI's __version__ (0.13.2) is not package.json's version (0.14.0)" in result.stderr
    assert calls == []


def test_a_missing_cli_version_is_refused(tree: Path) -> None:
    (tree / INIT).write_text("x = 1\n")
    commit_and_push(tree, "no version")
    result, calls, _ = ship(tree)
    assert result.returncode == 1
    assert "no __version__ in cli/src/moonlight_steam_sync/__init__.py" in result.stderr
    assert calls == []


def test_a_missing_changelog_section_is_refused(tree: Path) -> None:
    write_version(tree, "0.15.0", "0.15.0")
    commit_and_push(tree, "bump")
    result, calls, _ = ship(tree)
    assert result.returncode == 1
    assert "no '## [0.15.0] - YYYY-MM-DD' section" in result.stderr
    assert calls == []


def test_an_empty_changelog_section_is_a_warning(tree: Path) -> None:
    (tree / "CHANGELOG.md").write_text(
        "## [Unreleased]\n\n## [0.14.0] - 2026-11-02\n\n## [0.13.2] - 2026-10-29\n\n- x\n"
    )
    commit_and_push(tree, "empty")
    result, calls, notes = ship(tree)
    assert result.returncode == 0, result.stderr
    assert "[0.14.0] section is empty" in result.stderr
    assert len(calls) == 1 and notes == "\n"
    assert report(tree)["notes"] == ""


def test_a_failed_gh_fails_with_its_message(tree: Path) -> None:
    result, calls, _ = ship(tree, fail_gh=True)
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
