#!/usr/bin/env python3
"""Set the one version in both of its spellings (AGENTS.md hard rule 8).

    python3 scripts/set_version.py X.Y.Z[-SNAPSHOT] [--root DIR]

Writes ``package.json``'s ``"version"`` as given and the CLI's
``__version__`` (``cli/src/moonlight_steam_sync/__init__.py``) as
``scripts/build_cli.py``'s ``cli_spelling`` says: the same string, except
that ``X.Y.Z-SNAPSHOT`` (what ``main`` carries between releases) is
``X.Y.Z.dev0`` for the CLI, PEP 440's spelling of "before X.Y.Z". The
release-branch flow (the moonlight-sync-release skill) runs it twice per
release: on ``main`` for the next snapshot and on the release branch to
strip the suffix. It refuses (exit 1, nothing written) any other shape of
version, and refuses to touch a file it cannot read as expected.
``package.json`` is rewritten with its two-space indentation and trailing
newline, so a version is the only change. Standard library only.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from build_cli import _VERSION_RE, PACKAGE, cli_spelling  # noqa: E402

VERSION_PATTERN = re.compile(r"^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)(-SNAPSHOT)?$")


def set_version(root: Path, version: str) -> tuple[str, str]:
    """Write ``version`` into both files; the two spellings written, or ``SystemExit``."""
    if not VERSION_PATTERN.match(version):
        raise SystemExit(f"set_version.py: {version!r} is not X.Y.Z or X.Y.Z-SNAPSHOT")
    package_path = root / "package.json"
    init_path = root / "cli" / "src" / PACKAGE / "__init__.py"
    try:
        package = json.loads(package_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise SystemExit(f"set_version.py: cannot read package.json: {error}") from None
    if not isinstance(package, dict) or not isinstance(package.get("version"), str):
        raise SystemExit("set_version.py: package.json has no version")
    try:
        init = init_path.read_text(encoding="utf-8")
    except OSError as error:
        raise SystemExit(f"set_version.py: cannot read the CLI's __init__.py: {error}") from None
    if _VERSION_RE.search(init) is None:
        raise SystemExit(f"set_version.py: no __version__ in cli/src/{PACKAGE}/__init__.py")
    cli = cli_spelling(version)
    package["version"] = version
    package_path.write_text(
        json.dumps(package, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    init_path.write_text(_VERSION_RE.sub(f'__version__ = "{cli}"', init, count=1), encoding="utf-8")
    return version, cli


def main(argv: list[str] | None = None) -> int:
    default_root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("version", help="X.Y.Z, or X.Y.Z-SNAPSHOT between releases")
    parser.add_argument("--root", type=Path, default=default_root, help="the repo root")
    args = parser.parse_args(argv)
    plugin, cli = set_version(args.root.resolve(), args.version)
    print(f"set_version.py: package.json {plugin}, the CLI's __version__ {cli}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
