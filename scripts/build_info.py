#!/usr/bin/env python3
"""Write build.json, what a build says about itself (update spec 3.12.1).

    python3 scripts/build_info.py --kind KIND --ref REF --sha SHA --run RUN [--out PATH]

``scripts/package.py`` puts the file in the zip as ``Moonlight Sync/build.json``
when it exists at the repo root. ``release.yml``'s build job and ``ci.yml``'s
``package`` job write it with ``release`` and the tag on a tag, else ``branch``
and the branch's name; ``builds.yml`` with ``branch`` and the branch it
builds. The version is not in it: ``package.json`` has it (hard rule 8).

A build made outside CI has no such step, so without the file
``package.py`` asks :func:`from_git` what the checkout itself says (the
spec's amendment A5): the branch checked out and its commit, ``run``
``null``. Then a zip built on a device from a clone of ``main`` names the
commit the published build of ``main`` names, and the plugin's Updates page
can tell the two are the same.

    {"schema": 1, "kind": "branch", "ref": "main",
     "sha": "<40 hex>", "built_at": "2026-10-02T14:03:11Z", "run": "123456/1"}

``KIND`` is ``release`` or ``branch``; ``SHA`` is 40 hex digits (written
lower-cased); ``RUN`` is ``<run id>/<run attempt>``, ``^[0-9]+/[0-9]+$``;
``REF`` matches ``^[A-Za-z0-9._/-]{1,100}$``. A refusal writes
nothing and prints one line on stderr. Its exit code:

- ``3`` (``EXIT_REF_REFUSED``): the kind, the sha and the run are good and only the
  ``REF`` is outside the pattern. A branch name GitHub allows but the
  pattern refuses (one with ``+`` or ``@``) ends here. ``ci.yml`` and
  ``release.yml`` treat exactly this code, on a branch, as "no build.json
  for this zip" (a notice, amendment A1); ``builds.yml`` fails on it, so
  such a branch cannot have a published build.
- ``1``: a bad ``KIND``, ``SHA`` or ``RUN`` (checked first), always a failure.
- ``2``: argparse's own, a missing or unknown option.

``built_at`` is the current time in UTC. Standard library only.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

SCHEMA = 1
KINDS = ("release", "branch")
SHA_RE = re.compile(r"[0-9a-fA-F]{40}")
RUN_RE = re.compile(r"[0-9]+/[0-9]+")
REF_RE = re.compile(r"[A-Za-z0-9._/-]{1,100}")
EXIT_REFUSED = 1
EXIT_REF_REFUSED = 3
GIT_TIMEOUT_S = 30
#: A branch's full ref, as ``git symbolic-ref HEAD`` spells it.
BRANCH_PREFIX = "refs/heads/"
#: Where git would look instead of the directory it is pointed at.
GIT_LOCATION_ENV = ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE", "GIT_COMMON_DIR")


class RefRefused(ValueError):
    """The kind, the sha and the run are good; only the ref is outside ``REF_RE``."""


class NoGitBuild(ValueError):
    """The checkout cannot name what it builds; the message says why."""


def build_info(kind: str, ref: str, sha: str, run: str | None, now: float | None = None) -> dict:
    """The file's contents, keys in the spec's order; ``ValueError`` on a bad
    argument, ``RefRefused`` (checked last) when only the ref is bad. ``run``
    is ``None`` only for a build no workflow ran (:func:`from_git`)."""
    if kind not in KINDS:
        raise ValueError(f"--kind must be one of {', '.join(KINDS)}, not {kind!r}")
    if not SHA_RE.fullmatch(sha):
        raise ValueError(f"--sha must be 40 hex digits, not {sha!r}")
    if run is not None and not RUN_RE.fullmatch(run):
        raise ValueError(f"--run must be <run id>/<run attempt> in digits, not {run!r}")
    if not REF_RE.fullmatch(ref):
        raise RefRefused(f"--ref must match ^[A-Za-z0-9._/-]{{1,100}}$, not {ref!r}")
    built_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now))
    return {
        "schema": SCHEMA,
        "kind": kind,
        "ref": ref,
        "sha": sha.lower(),
        "built_at": built_at,
        "run": run,
    }


def _git(root: Path, *args: str) -> tuple[str | None, str]:
    """git's answer in ``root`` and ``""``, or ``None`` and why there is none:
    the first line git wrote to stderr (``""`` when it wrote nothing, as
    ``--quiet`` has it), or that git did not run or did not answer."""
    env = {key: value for key, value in os.environ.items() if key not in GIT_LOCATION_ENV}
    try:
        result = subprocess.run(
            ["git", "-C", str(root), *args],
            capture_output=True,
            text=True,
            check=False,
            env=env,
            timeout=GIT_TIMEOUT_S,
        )
    except subprocess.TimeoutExpired:
        return None, f"git did not answer in {GIT_TIMEOUT_S} s"
    except (OSError, subprocess.SubprocessError) as error:
        return None, f"git did not run: {type(error).__name__}"
    if result.returncode == 0:
        return result.stdout.strip(), ""
    lines = [line.strip() for line in result.stderr.splitlines() if line.strip()]
    return None, f"git: {lines[0]}" if lines else ""


def _because(message: str, why: str) -> str:
    """``message``, with what git said in brackets when it said something."""
    return f"{message} ({why})" if why else message


def from_git(root: Path, now: float | None = None) -> dict:
    """What a build of the checkout at ``root`` says about itself: ``branch``,
    the branch checked out and its commit, ``run`` ``None`` (no workflow ran).

    ``NoGitBuild`` unless the zip would be that commit and nothing else:
    ``root`` must be the top of a git checkout (a directory inside another
    repository is not labelled with that repository's commit), on a branch
    (a detached ``HEAD`` names none) and with nothing uncommitted, untracked
    files included, since ``package.py`` ships what is on disk. ``RefRefused``
    for a branch name outside ``REF_RE``, as in :func:`build_info`.

    The branch is ``HEAD``'s full ref without ``refs/heads/``, which is what
    ``github.ref_name`` is in CI: ``symbolic-ref --short`` answers
    ``heads/main`` when a tag is named ``main`` too. When git itself fails
    (no git, a checkout it calls dubious, a timeout) the message carries
    what it said.
    """
    top, why = _git(root, "rev-parse", "--show-toplevel")
    if not top:
        raise NoGitBuild(_because("not the root of a git checkout", why))
    if Path(top).resolve() != root.resolve():
        raise NoGitBuild("not the root of a git checkout")
    head, why = _git(root, "symbolic-ref", "--quiet", "HEAD")
    if not head or not head.startswith(BRANCH_PREFIX):
        raise NoGitBuild(_because("HEAD is detached, so no branch names this build", why))
    ref = head[len(BRANCH_PREFIX) :]
    sha, why = _git(root, "rev-parse", "--verify", "--quiet", "HEAD")
    if not sha or not SHA_RE.fullmatch(sha):
        raise NoGitBuild(_because("HEAD names no commit of 40 hex digits", why))
    changes, why = _git(root, "status", "--porcelain", "--untracked-files=normal")
    if changes is None:
        raise NoGitBuild(_because("git status failed", why))
    if changes:
        raise NoGitBuild("the checkout has uncommitted changes")
    return build_info("branch", ref, sha, None, now)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--kind", required=True, help="release or branch")
    parser.add_argument("--ref", required=True, help="the tag (release) or the branch's name")
    parser.add_argument("--sha", required=True, help="the commit built, 40 hex digits")
    parser.add_argument("--run", required=True, help="the workflow run, <run id>/<run attempt>")
    parser.add_argument(
        "--out", type=Path, default=Path("build.json"), help="default build.json here"
    )
    args = parser.parse_args(argv)
    try:
        info = build_info(args.kind, args.ref, args.sha, args.run)
    except ValueError as error:
        print(f"build_info.py: {error}", file=sys.stderr)
        return EXIT_REF_REFUSED if isinstance(error, RefRefused) else EXIT_REFUSED
    tmp = args.out.with_name(args.out.name + ".tmp")
    tmp.write_text(json.dumps(info) + "\n", encoding="utf-8")
    os.replace(tmp, args.out)
    print(f"build_info.py: {args.out}: {json.dumps(info)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
