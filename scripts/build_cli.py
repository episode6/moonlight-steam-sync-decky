#!/usr/bin/env python3
"""Build the moonlight-steam-sync zipapp from cli/src (spec 3.1, 3.6.1).

The one CLI builder: ``backend/entrypoint.sh`` (CI's package job, the
release workflow, the Decky store builder) and CI's ``cli`` job run it, and
``cli/tests/test_release_zipapp.py`` builds through it too.

    python3 scripts/build_cli.py [--root DIR] [--out PATH]

Writes ``backend/out/moonlight-steam-sync.pyz`` by default: a deflated
zipapp with the ``/usr/bin/env python3`` shebang and
``moonlight_steam_sync.__main__:main`` as its entry point, holding
``moonlight_steam_sync/`` only (no ``__pycache__``, ``.pyc`` or the
``*.egg-info`` an editable install leaves in ``cli/src``), mode 0755,
written through a ``.tmp`` and ``os.replace``.

The CLI shares the plugin's version: it refuses to build (exit 1, nothing
written) when ``cli/src/moonlight_steam_sync/__init__.py``'s ``__version__``
is not ``package.json``'s ``"version"``. Standard library only.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import zipapp
from pathlib import Path

PACKAGE = "moonlight_steam_sync"
PYZ = "moonlight-steam-sync.pyz"
MAIN = f"{PACKAGE}.__main__:main"
INTERPRETER = "/usr/bin/env python3"

_VERSION_RE = re.compile(r'^__version__\s*=\s*"([^"]+)"', re.MULTILINE)


def cli_version(root: Path) -> str | None:
    """``__version__`` as written in ``cli/src/moonlight_steam_sync/__init__.py``."""
    try:
        text = (root / "cli" / "src" / PACKAGE / "__init__.py").read_text(encoding="utf-8")
    except OSError:
        return None
    match = _VERSION_RE.search(text)
    return match.group(1) if match else None


def plugin_version(root: Path) -> str | None:
    """``package.json``'s ``"version"``."""
    try:
        value = json.loads((root / "package.json").read_text(encoding="utf-8")).get("version")
    except (OSError, ValueError, AttributeError):
        return None
    return value if isinstance(value, str) else None


def _include(path: Path) -> bool:
    """zipapp's filter: ``path`` is relative to cli/src."""
    parts = path.parts
    return (
        bool(parts)
        and parts[0] == PACKAGE
        and "__pycache__" not in parts
        and path.suffix not in (".pyc", ".pyo")
    )


def build(root: Path, out: Path) -> str:
    """Build ``out`` from ``root``/cli/src; the version built, or ``SystemExit``."""
    cli = cli_version(root)
    plugin = plugin_version(root)
    if cli is None:
        raise SystemExit(f"build_cli.py: no __version__ in cli/src/{PACKAGE}/__init__.py")
    if plugin is None:
        raise SystemExit("build_cli.py: no version in package.json")
    if cli != plugin:
        raise SystemExit(
            f"build_cli.py: the CLI's __version__ ({cli}) is not package.json's version "
            f"({plugin}); they are bumped together"
        )
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.with_name(out.name + ".tmp")
    try:
        zipapp.create_archive(
            source=root / "cli" / "src",
            target=tmp,
            interpreter=INTERPRETER,
            main=MAIN,
            filter=_include,
            compressed=True,
        )
        os.chmod(tmp, 0o755)
        os.replace(tmp, out)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise
    return cli


def main(argv: list[str] | None = None) -> int:
    default_root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--root", type=Path, default=default_root, help="the repo root")
    parser.add_argument(
        "--out", type=Path, default=None, help=f"the zipapp to write (default backend/out/{PYZ})"
    )
    args = parser.parse_args(argv)
    root = args.root.resolve()
    out = args.out if args.out is not None else root / "backend" / "out" / PYZ
    version = build(root, out)
    print(f"build_cli.py: moonlight-steam-sync v{version} -> {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
