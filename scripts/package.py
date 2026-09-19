#!/usr/bin/env python3
"""Build out/Moonlight-Sync.zip without Docker (spec 3.6.2).

Reproduces the layout of the Decky CLI's ``zip_plugin()``: everything under
one top-level directory named after ``plugin.json``'s ``name`` (``Moonlight
Sync/``, which is the directory decky-loader installs the plugin into), the
five root files, ``dist/`` (mandatory), ``py_modules/`` (0755, no
``__pycache__``), ``backend/out/*`` as ``bin/*`` (0755), and the contents of
``defaults/`` at the root when that directory exists.

    python3 scripts/package.py [--root DIR] [--out PATH] [--require-cli] [--list]

Without ``backend/out/moonlight-steam-sync.pyz`` it warns and packages
anyway (the plugin's About page then says the bundle is missing);
``--require-cli`` makes that an error, which is what a release uses.
Standard library only.
"""

from __future__ import annotations

import argparse
import json
import os
import stat
import sys
import time
import zipfile
from pathlib import Path

ROOT_FILES = ("plugin.json", "package.json", "main.py", "README.md", "LICENSE")
PYZ = "moonlight-steam-sync.pyz"
EXEC_MODE = 0o755
FILE_MODE = 0o644
DIR_MODE = 0o755


def _date_time(path: Path) -> tuple[int, int, int, int, int, int]:
    mtime = max(path.stat().st_mtime, 315532800)  # zip cannot store dates before 1980
    return time.localtime(mtime)[:6]


def _skip(path: Path) -> bool:
    return "__pycache__" in path.parts or path.suffix == ".pyc"


def _walk(directory: Path) -> list[Path]:
    """``directory`` and everything below it, sorted, directories before their contents."""
    found = [directory]
    for dirpath, dirnames, filenames in os.walk(directory):
        dirnames[:] = sorted(d for d in dirnames if d != "__pycache__")
        base = Path(dirpath)
        found.extend(base / d for d in dirnames)
        found.extend(base / f for f in sorted(filenames))
    return sorted(found, key=lambda p: p.relative_to(directory).parts)


class Packager:
    def __init__(self, root: Path, out: Path) -> None:
        self.root = root
        self.out = out
        self.entries: list[str] = []

    def plan(self, require_cli: bool) -> list[tuple[Path, str, int]]:
        """``(source, archive name, mode)`` for every entry, in order."""
        meta = json.loads((self.root / "plugin.json").read_text())
        top = meta["name"]
        if not (self.root / "dist" / "index.js").exists():
            raise SystemExit("package.py: dist/index.js is missing; run `pnpm run build` first")
        items: list[tuple[Path, str, int]] = []
        for name in ROOT_FILES:
            source = self.root / name
            if not source.exists():
                raise SystemExit(f"package.py: {name} is missing")
            items.append((source, f"{top}/{name}", FILE_MODE))
        for sub, mode in (("dist", FILE_MODE), ("py_modules", EXEC_MODE)):
            directory = self.root / sub
            if not directory.exists():
                continue
            for path in _walk(directory):
                if _skip(path):
                    continue
                rel = path.relative_to(self.root).as_posix()
                items.append((path, f"{top}/{rel}", mode))
        pyz = self.root / "backend" / "out" / PYZ
        if not pyz.exists():
            if require_cli:
                raise SystemExit(
                    f"package.py: backend/out/{PYZ} is missing; run backend/entrypoint.sh"
                )
            print(f"::warning::packaging without bin/{PYZ}", file=sys.stderr)
        backend_out = self.root / "backend" / "out"
        if backend_out.exists():
            items.append((backend_out, f"{top}/bin", EXEC_MODE))
            for path in _walk(backend_out)[1:]:
                rel = path.relative_to(backend_out).as_posix()
                items.append((path, f"{top}/bin/{rel}", EXEC_MODE))
        defaults = self.root / "defaults"
        if defaults.exists():
            for path in _walk(defaults)[1:]:
                rel = path.relative_to(defaults).as_posix()
                items.append((path, f"{top}/{rel}", FILE_MODE))
        return items

    def build(self, require_cli: bool) -> list[str]:
        items = self.plan(require_cli)
        self.out.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.out.with_name(self.out.name + ".tmp")
        names: list[str] = []
        with zipfile.ZipFile(tmp, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for source, name, mode in items:
                if source.is_dir():
                    info = zipfile.ZipInfo(name.rstrip("/") + "/", _date_time(source))
                    info.external_attr = ((stat.S_IFDIR | DIR_MODE) << 16) | 0x10
                    archive.writestr(info, b"")
                    names.append(info.filename)
                    continue
                info = zipfile.ZipInfo(name, _date_time(source))
                info.compress_type = zipfile.ZIP_DEFLATED
                info.external_attr = (stat.S_IFREG | mode) << 16
                archive.writestr(info, source.read_bytes())
                names.append(name)
        os.replace(tmp, self.out)
        return names


def main(argv: list[str] | None = None) -> int:
    default_root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--root", type=Path, default=default_root, help="the plugin repo root")
    parser.add_argument(
        "--out", type=Path, default=None, help="the zip to write (default out/Moonlight-Sync.zip)"
    )
    parser.add_argument(
        "--require-cli",
        action="store_true",
        help=f"fail when backend/out/{PYZ} is missing (releases)",
    )
    parser.add_argument("--list", action="store_true", help="print every entry")
    args = parser.parse_args(argv)
    root = args.root.resolve()
    out = args.out if args.out is not None else root / "out" / "Moonlight-Sync.zip"
    names = Packager(root, out).build(args.require_cli)
    if args.list:
        for name in names:
            print(name)
    print(f"package.py: {out} ({len(names)} entries)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
