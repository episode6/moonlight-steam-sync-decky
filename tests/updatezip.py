"""Plugin zips for the update tests (update spec 3.12.6), good and hostile.

- :func:`build_zip` writes a zip shaped like ``scripts/package.py``'s, with
  the keyword arguments the spec lists: ``name`` (``plugin.json``'s),
  ``top`` (the folder), ``flags``, ``build`` (``build.json``: a dict, raw
  text, or ``None`` for none), ``extra`` (more entries: ``(relative name,
  data)`` under the folder, or ``(ZipInfo, data)`` written exactly as
  given, which is how the hostile entries are made) and ``omit`` (relative
  names left out).
- :func:`patch_central` rewrites one entry's central-directory record in
  place: what ``zipfile`` would never write (an encrypted flag, sizes that
  lie).
- :func:`branch_build` is a ``build.json`` for a branch.
"""

from __future__ import annotations

import json
import struct
import warnings
import zipfile
from pathlib import Path
from typing import Any

SHA = "0123abcd" * 5  # 40 hex digits


def branch_build(ref: str = "main", *, kind: str = "branch", sha: str = SHA) -> dict[str, Any]:
    return {
        "schema": 1,
        "kind": kind,
        "ref": ref,
        "sha": sha,
        "built_at": "2026-10-02T14:03:11Z",
        "run": "123456/1",
    }


def _file(name: str, data: bytes | str, mode: int = 0o644) -> tuple[zipfile.ZipInfo, bytes]:
    info = zipfile.ZipInfo(name, (2026, 9, 27, 12, 0, 0))
    info.compress_type = zipfile.ZIP_DEFLATED
    info.external_attr = (0o100000 | mode) << 16
    return info, data.encode() if isinstance(data, str) else data


def _dir(name: str) -> tuple[zipfile.ZipInfo, bytes]:
    info = zipfile.ZipInfo(name.rstrip("/") + "/", (2026, 9, 27, 12, 0, 0))
    info.external_attr = ((0o040000 | 0o755) << 16) | 0x10
    return info, b""


def build_zip(
    path: Path | str,
    *,
    version: str,
    name: str = "Moonlight Sync",
    top: str = "Moonlight Sync",
    flags: Any = (),
    build: dict[str, Any] | str | None = None,
    extra: Any = (),
    omit: Any = (),
) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    files: list[tuple[str, bytes | str]] = [
        (
            "plugin.json",
            json.dumps(
                {"name": name, "flags": list(flags) if isinstance(flags, (list, tuple)) else flags}
            ),
        ),
        ("package.json", json.dumps({"name": "moonlight-steam-sync-decky", "version": version})),
        ("main.py", "class Plugin: ...\n"),
    ]
    if build is not None:
        files.append(("build.json", build if isinstance(build, str) else json.dumps(build)))
    entries: list[tuple[zipfile.ZipInfo, bytes]] = [
        _file(f"{top}/{rel}", data) for rel, data in files if rel not in omit
    ]
    if "dist/" not in omit:
        entries.append(_dir(f"{top}/dist/"))
    if "dist/index.js" not in omit:
        entries.append(_file(f"{top}/dist/index.js", "export default 1;\n"))
    entries.append(_dir(f"{top}/py_modules/"))
    entries.append(_file(f"{top}/py_modules/moonlight_sync/__init__.py", "", 0o755))
    for item, data in extra:
        if isinstance(item, zipfile.ZipInfo):
            entries.append((item, data.encode() if isinstance(data, str) else data))
        else:
            entries.append(_file(f"{top}/{item}", data))
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")  # "Duplicate name", on purpose
        with zipfile.ZipFile(path, "w") as archive:
            for info, data in entries:
                archive.writestr(info, data)
    return path


def patch_central(
    path: Path | str,
    name: str,
    *,
    flag_bits: int | None = None,
    compress_size: int | None = None,
    file_size: int | None = None,
) -> None:
    """Rewrite ``name``'s central-directory record (every one of that name).

    The record: signature ``PK\\1\\2``, then at offset 8 the flag bits
    (2 bytes), 20 the compressed size, 24 the uncompressed size (4 each),
    28 the name's length, 46 the name.
    """
    path = Path(path)
    data = bytearray(path.read_bytes())
    encoded = name.encode()
    start = 0
    found = 0
    while (index := data.find(b"PK\x01\x02", start)) >= 0:
        (length,) = struct.unpack_from("<H", data, index + 28)
        if bytes(data[index + 46 : index + 46 + length]) == encoded:
            found += 1
            if flag_bits is not None:
                struct.pack_into("<H", data, index + 8, flag_bits)
            if compress_size is not None:
                struct.pack_into("<I", data, index + 20, compress_size)
            if file_size is not None:
                struct.pack_into("<I", data, index + 24, file_size)
        start = index + 4
    assert found, f"no central record for {name}"
    path.write_bytes(bytes(data))
