#!/usr/bin/env python3
"""Write build.json, what a CI build says about itself (update spec 3.12.1).

    python3 scripts/build_info.py --kind KIND --ref REF --sha SHA --run RUN [--out PATH]

``scripts/package.py`` puts the file in the zip as ``Moonlight Sync/build.json``
when it exists at the repo root. ``release.yml``'s build job and ``ci.yml``'s
``package`` job write it with ``release`` and the tag on a tag, else ``branch``
and the branch's name; ``builds.yml`` with ``branch`` and the branch it
builds. The version is not in it: ``package.json`` has it (hard rule 8).

    {"schema": 1, "kind": "branch", "ref": "main",
     "sha": "<40 hex>", "built_at": "2026-10-02T14:03:11Z", "run": "123456/1"}

``KIND`` is ``release`` or ``branch``; ``SHA`` is 40 hex digits (written
lower-cased); ``REF`` matches ``^[A-Za-z0-9._/-]{1,100}$``. A refusal writes
nothing and prints one line on stderr. Its exit code:

- ``3`` (``EXIT_REF_REFUSED``): the kind and the sha are good and only the
  ``REF`` is outside the pattern. A branch name GitHub allows but the
  pattern refuses (one with ``+`` or ``@``) ends here. ``ci.yml`` and
  ``release.yml`` treat exactly this code, on a branch, as "no build.json
  for this zip" (a notice, amendment A1); ``builds.yml`` fails on it, so
  such a branch cannot have a published build.
- ``1``: a bad ``KIND`` or ``SHA`` (checked first), always a failure.
- ``2``: argparse's own, a missing or unknown option.

``built_at`` is the current time in UTC. Standard library only.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from pathlib import Path

SCHEMA = 1
KINDS = ("release", "branch")
SHA_RE = re.compile(r"[0-9a-fA-F]{40}")
REF_RE = re.compile(r"[A-Za-z0-9._/-]{1,100}")
EXIT_REFUSED = 1
EXIT_REF_REFUSED = 3


class RefRefused(ValueError):
    """The kind and the sha are good; only the ref is outside ``REF_RE``."""


def build_info(kind: str, ref: str, sha: str, run: str, now: float | None = None) -> dict:
    """The file's contents, keys in the spec's order; ``ValueError`` on a bad
    argument, ``RefRefused`` (checked last) when only the ref is bad."""
    if kind not in KINDS:
        raise ValueError(f"--kind must be one of {', '.join(KINDS)}, not {kind!r}")
    if not SHA_RE.fullmatch(sha):
        raise ValueError(f"--sha must be 40 hex digits, not {sha!r}")
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
