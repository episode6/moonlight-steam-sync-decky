#!/usr/bin/env python3
"""Ship a release branch: create the GitHub release and tag ``v<VERSION>``.

    python3 scripts/ship_release.py --output REPORT.json [--branch release/vX.Y.Z] [--dry-run]

Mirrors ``scripts/ship-release.py`` in the sibling episode6 repos (the
moonlight-sync-release skill has the whole flow). Run from the repo root
on the release branch, once its ``[VERSION] Release vX.Y.Z`` PR has merged
and the branch is pulled:

- the version is ``package.json``'s ``"version"``, cross-checked against
  the CLI's ``__version__`` the way ``scripts/build_cli.py`` does, and
  refused while it is a ``-SNAPSHOT`` (that is ``main``'s version, never
  a release's);
- the branch (``--branch``, else the one checked out) must be a
  ``release/`` branch, since ``main`` carries a snapshot and a tag there
  would fail ``release.yml``'s tag check anyway;
- the notes are ``CHANGELOG.md``'s ``## [X.Y.Z] - YYYY-MM-DD`` section,
  which the release PR wrote (a missing section is an error, an empty one
  a warning);
- ``gh release create vX.Y.Z --target <branch> --title vX.Y.Z
  --notes-file …`` creates the tag and the release page in one step. The
  tag reaching GitHub triggers ``release.yml``, whose build job checks the
  tag against ``package.json`` and whose ``github-release`` job uploads
  the four assets into the release that now exists.

``--dry-run`` prints the command and the notes and runs nothing.
``--output`` (required) gets a JSON report either way: ``success``,
``dry_run``, ``tag``, ``title``, ``version``, ``branch``, ``notes`` and,
after a real run, ``url`` (``command`` on a dry run). Standard library
only; ``gh`` is the one tool it runs.
"""

from __future__ import annotations

import argparse
import contextlib
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from build_cli import SNAPSHOT_SUFFIX, cli_spelling, cli_version, plugin_version  # noqa: E402

CHANGELOG = "CHANGELOG.md"
RELEASE_BRANCH_PREFIX = "release/"


def fail(message: str) -> None:
    print(f"ship_release.py: {message}", file=sys.stderr)
    sys.exit(1)


def current_branch(root: Path) -> str:
    try:
        result = subprocess.run(
            ["git", "-C", str(root), "symbolic-ref", "--quiet", "--short", "HEAD"],
            capture_output=True,
            text=True,
            check=True,
        )
    except (OSError, subprocess.CalledProcessError) as error:
        detail = error.stderr.strip() if isinstance(error, subprocess.CalledProcessError) else error
        fail(f"cannot read the current branch ({detail or 'detached HEAD'}); pass --branch")
    return result.stdout.strip()


def read_version(root: Path) -> str:
    """``package.json``'s version, releasable and matched by the CLI's, or exit 1."""
    plugin = plugin_version(root)
    if plugin is None:
        fail("no version in package.json (run from the repo root)")
    if plugin.endswith(SNAPSHOT_SUFFIX):
        fail(
            f"package.json's version is {plugin}, a snapshot: ship from the release branch "
            "once its [VERSION] Release PR has merged, never from main"
        )
    cli = cli_version(root)
    if cli != cli_spelling(plugin):
        fail(f"the CLI's __version__ ({cli}) is not package.json's version ({plugin})")
    return plugin


def check_release_branch(branch: str, dry_run: bool) -> None:
    if branch.startswith(RELEASE_BRANCH_PREFIX):
        return
    message = f"{branch} is not a {RELEASE_BRANCH_PREFIX}* branch; releases ship from one"
    if dry_run:
        print(f"ship_release.py: [dry-run] warning: {message}", file=sys.stderr)
    else:
        fail(message)


def changelog_notes(root: Path, version: str) -> str:
    """The body of ``## [version] - date`` in CHANGELOG.md, up to the next ``## ``."""
    try:
        lines = (root / CHANGELOG).read_text(encoding="utf-8").splitlines(keepends=True)
    except OSError as error:
        fail(f"cannot read {CHANGELOG}: {error}")
    header = re.compile(rf"^##\s+\[{re.escape(version)}\](\s|$)")
    any_header = re.compile(r"^##\s")
    notes: list[str] = []
    found = False
    for line in lines:
        if found:
            if any_header.match(line):
                break
            notes.append(line)
        elif header.match(line):
            found = True
    if not found:
        fail(f"{CHANGELOG} has no '## [{version}] - YYYY-MM-DD' section; the release PR writes it")
    content = "".join(notes).strip()
    if not content:
        print(
            f"ship_release.py: warning: {CHANGELOG}'s [{version}] section is empty", file=sys.stderr
        )
    return content


def run_gh_release(version: str, notes: str, branch: str, *, dry_run: bool) -> dict[str, object]:
    tag = f"v{version}"
    report: dict[str, object] = {
        "success": True,
        "dry_run": dry_run,
        "tag": tag,
        "title": tag,
        "version": version,
        "branch": branch,
        "notes": notes,
    }
    fd, notes_path = tempfile.mkstemp(suffix=".md", prefix="release-notes-")
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        handle.write(notes + "\n")
    try:
        command = [
            "gh",
            "release",
            "create",
            tag,
            "--target",
            branch,
            "--title",
            tag,
            "--notes-file",
            notes_path,
        ]
        if dry_run:
            print("ship_release.py: [dry-run] would run:")
            print(" ".join(command))
            print("\n[dry-run] release notes:")
            print("-" * 40)
            print(notes)
            print("-" * 40)
            report["command"] = " ".join(command)
            return report
        print(f"ship_release.py: running {' '.join(command)}")
        try:
            result = subprocess.run(command, capture_output=True, text=True, check=True)
        except OSError as error:
            fail(f"cannot run gh: {error}")
        except subprocess.CalledProcessError as error:
            fail(f"gh release create failed: {error.stderr.strip()}")
        url = result.stdout.strip()
        print(f"ship_release.py: created {url}")
        print(
            "The tag now triggers release.yml, which attaches the zip, the CLI and their checksums."
        )
        report["url"] = url
        return report
    finally:
        with contextlib.suppress(OSError):
            os.remove(notes_path)


def main(argv: list[str] | None = None) -> int:
    default_root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--branch", help="the release branch to tag (default: the one checked out)")
    parser.add_argument(
        "--dry-run", action="store_true", help="print the command and the notes, run nothing"
    )
    parser.add_argument("--output", required=True, help="where to write the JSON report")
    parser.add_argument("--root", type=Path, default=default_root, help="the repo root")
    args = parser.parse_args(argv)
    root = args.root.resolve()

    branch = args.branch or current_branch(root)
    check_release_branch(branch, args.dry_run)
    version = read_version(root)
    notes = changelog_notes(root, version)
    report = run_gh_release(version, notes, branch, dry_run=args.dry_run)

    with open(args.output, "w", encoding="utf-8") as handle:
        json.dump(report, handle, indent=2)
        handle.write("\n")
    print(f"ship_release.py: report written to {args.output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
