"""The staging's pure half (update spec 3.12.3): URLs, checks, paths.

Functions over data and paths only: no subprocess, no network, no
``decky``. The download itself is ``fetch.py``, a separate script the
backend runs (``Backend._fetch``); what it downloads is judged here. Nothing
at this module's top level is named ``updater``: Decky aliases a module of
that name, which would shadow it.

The staged files live under the plugin's runtime directory
(``DECKY_PLUGIN_RUNTIME_DIR``, ``~/homebrew/data/Moonlight Sync``), in
``update/staged/``; deleting the directory loses nothing. The plugin's own
directory is never written (hard rule 12): Decky's installer is handed a
``file://`` path to a zip :func:`validate_zip` accepted.
"""

from __future__ import annotations

import contextlib
import json
import os
import re
import stat
import time
import zipfile
from dataclasses import dataclass
from typing import Any

from .install import parse_version

REPO = "episode6/moonlight-steam-sync-decky"
DOWNLOAD_BASE = f"https://github.com/{REPO}/releases/download"
ASSET = "Moonlight-Sync.zip"
ASSET_SHA = ASSET + ".sha256"
PLUGIN_NAME = "Moonlight Sync"
ZIP_MAX_BYTES = 32 * 1024 * 1024
UNPACKED_MAX_BYTES = 128 * 1024 * 1024
DOWNLOAD_TIMEOUT_S = 120
STAGED_KEEP_S = 3600
TAG_RE = r"^[A-Za-z0-9._-]{1,100}$"
REF_RE = r"^[A-Za-z0-9._/-]{1,100}$"

#: The sidecar is one line (``<hex>  Moonlight-Sync.zip``); anything longer is not one.
SIDECAR_MAX_BYTES = 4096
#: What ``validate_zip`` reads into memory per JSON file, and ``read_build`` per file.
JSON_MAX_BYTES = 1024 * 1024
MAX_ENTRIES = 4096
#: Deflate tops out near 1032:1 on a run of one byte; nothing this plugin
#: ships comes close, a zip bomb does.
MAX_RATIO = 1000
BUILD_SCHEMA = 1
BUILD_KINDS = ("release", "branch")
TOP = PLUGIN_NAME + "/"
REQUIRED_FILES = ("main.py", "dist/index.js")
PART_SUFFIX = ".part"

_HEX64_RE = re.compile(r"[0-9a-fA-F]{64}")
_HEX40_RE = re.compile(r"[0-9a-fA-F]{40}")
_DRIVE_RE = re.compile(r"[A-Za-z]:")
_URL_QUERY_RE = re.compile(r"([A-Za-z][A-Za-z0-9+.-]*://[^\s?#'\"<>]*)[?#][^\s'\"<>]*")


@dataclass(frozen=True)
class Source:
    """Where releases are downloaded from: the seam the tests replace.

    ``main.py`` never passes one, so the plugin always downloads from this
    repository's releases on GitHub; ``allow_file`` (a ``file://`` tree in
    the tests) is ``True`` in the tests only (``tests/test_hard_rules.py``).
    """

    download_base: str = DOWNLOAD_BASE
    allow_file: bool = False


class BadZip(Exception):
    """The staged file is not a build of this plugin; the message says why."""

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


# ---------------------------------------------------------------------------
# small validators


def is_tag(value: Any) -> bool:
    """A release tag as the staging accepts one: ``TAG_RE``, and not ``.`` or
    ``..``, which the pattern allows but which would be a path step in the
    download URL."""
    return isinstance(value, str) and bool(re.fullmatch(TAG_RE, value)) and value not in (".", "..")


def is_ref(value: Any) -> bool:
    """A branch name as ``build.json`` may carry one (``REF_RE``)."""
    return isinstance(value, str) and bool(re.fullmatch(REF_RE, value))


def is_sha256(value: Any) -> bool:
    """64 hex digits, either case."""
    return isinstance(value, str) and bool(_HEX64_RE.fullmatch(value))


def strip_queries(text: str) -> str:
    """``text`` with the query and fragment of every URL in it removed."""
    return _URL_QUERY_RE.sub(r"\1", text)


# ---------------------------------------------------------------------------
# URLs, the sidecar, build.json


def asset_url(source: Source, tag: str, name: str) -> str:
    """``<download_base>/<tag>/<name>``; ``ValueError`` on a tag outside
    ``TAG_RE`` (or ``.`` / ``..``) and on a name that is not one of the
    release's two assets, so nothing but constants and a validated tag
    reaches the URL (hard rule 12)."""
    if not is_tag(tag):
        raise ValueError("not a release tag")
    if name not in (ASSET, ASSET_SHA):
        raise ValueError("not a release asset")
    return f"{source.download_base}/{tag}/{name}"


def parse_sidecar(text: str) -> str | None:
    """The first whitespace-separated token when it is 64 hex digits
    (lower-cased), else ``None``."""
    tokens = text.split()
    if not tokens or not is_sha256(tokens[0]):
        return None
    return tokens[0].lower()


def parse_build(text: str) -> dict[str, Any] | None:
    """``build.json``'s contents when they are a build's (spec 3.12.1), else
    ``None``: a JSON object with ``schema`` 1, a ``kind`` of the two, a
    ``ref`` matching ``REF_RE`` and a ``sha`` of 40 hex digits.

    Answers the known keys only (``built_at`` / ``run`` as strings or
    ``None``), ``sha`` lower-cased, so nothing else a file says reaches the
    frontend.
    """
    try:
        data = json.loads(text)
    except ValueError:
        return None
    if not isinstance(data, dict):
        return None
    # `1.0 == 1` and `True == 1` in Python; the schema is the integer 1.
    schema = data.get("schema")
    if type(schema) is not int or schema != BUILD_SCHEMA:
        return None
    kind, ref, sha = data.get("kind"), data.get("ref"), data.get("sha")
    if kind not in BUILD_KINDS or not is_ref(ref):
        return None
    if not isinstance(sha, str) or not _HEX40_RE.fullmatch(sha):
        return None
    built_at, run = data.get("built_at"), data.get("run")
    return {
        "schema": BUILD_SCHEMA,
        "kind": kind,
        "ref": ref,
        "sha": sha.lower(),
        "built_at": built_at if isinstance(built_at, str) else None,
        "run": run if isinstance(run, str) else None,
    }


def read_build(plugin_dir: str) -> dict[str, Any] | None:
    """``<plugin_dir>/build.json`` through :func:`parse_build`; a missing,
    unreadable or larger than ``JSON_MAX_BYTES`` file reads as ``None``."""
    try:
        with open(os.path.join(plugin_dir, "build.json"), "rb") as handle:
            raw = handle.read(JSON_MAX_BYTES + 1)
    except OSError:
        return None
    if len(raw) > JSON_MAX_BYTES:
        return None
    try:
        return parse_build(raw.decode("utf-8"))
    except UnicodeDecodeError:
        return None


# ---------------------------------------------------------------------------
# validate_zip: every rule its own check and its own message, in order


def validate_zip(path: str, *, version: str | None, ref: str | None) -> dict[str, Any]:
    """Raise :class:`BadZip` unless ``path`` is a build of this plugin.

    The spec's rules, with the ones that only read the central directory
    (the entry list, the names, the declared sizes) moved in front of
    ``testzip()``, so a zip bomb or an encrypted entry is refused before
    anything is inflated. Nothing is extracted: ``plugin.json``,
    ``package.json`` and ``build.json`` are read in memory, each capped at
    ``JSON_MAX_BYTES``. Answers ``{"version": <package.json's>, "build":
    <build.json's, or None>}``.
    """
    try:
        if os.path.getsize(path) > ZIP_MAX_BYTES:
            raise BadZip(f"the file is larger than {ZIP_MAX_BYTES} bytes")
        archive = zipfile.ZipFile(path)
    except BadZip:
        raise
    except (OSError, zipfile.BadZipFile, ValueError, NotImplementedError, EOFError):
        raise BadZip("the file is not a zip") from None
    with archive:
        infos = archive.infolist()
        _check_entry_count(infos)
        _check_entry_kinds(infos)
        _check_sizes(infos)
        _check_integrity(archive)
        _check_names(infos)
        names = {info.filename: info for info in infos}
        plugin = _read_json(archive, names, "plugin.json")
        _check_plugin_json(plugin)
        package = _read_json(archive, names, "package.json")
        found = _check_package_json(package)
        _check_required_files(names)
        if version is not None:
            _check_version(found, version)
        build = _check_build_json(archive, names, version=version, ref=ref)
    return {"version": found, "build": build}


def _check_entry_count(infos: list[zipfile.ZipInfo]) -> None:
    if not infos:
        raise BadZip("the zip is empty")
    if len(infos) > MAX_ENTRIES:
        raise BadZip(f"the zip has more than {MAX_ENTRIES} entries")


def _check_entry_kinds(infos: list[zipfile.ZipInfo]) -> None:
    """Regular files and directories only, stored or deflated, unencrypted."""
    for info in infos:
        if info.flag_bits & 0x1:
            raise BadZip("the zip has an encrypted entry")
        # The Unix mode, when the zip carries one (the high 16 bits of
        # external_attr): a symlink, a device or a FIFO is refused. A zip
        # without Unix modes has 0 there, which is a plain entry.
        kind = stat.S_IFMT(info.external_attr >> 16)
        if kind not in (0, stat.S_IFREG, stat.S_IFDIR):
            raise BadZip("the zip has an entry that is neither a file nor a directory")
        if info.compress_type not in (zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED):
            raise BadZip("the zip has an entry compressed with an unexpected method")


def _check_sizes(infos: list[zipfile.ZipInfo]) -> None:
    """The declared sizes, before anything is inflated."""
    if sum(info.file_size for info in infos) > UNPACKED_MAX_BYTES:
        raise BadZip(f"the zip unpacks to more than {UNPACKED_MAX_BYTES} bytes")
    for info in infos:
        if info.file_size and not info.compress_size:
            raise BadZip("the zip has an entry that claims to be empty and is not")
        if info.compress_size and info.file_size / info.compress_size > MAX_RATIO:
            raise BadZip("the zip has an entry compressed beyond any real file")


def _check_integrity(archive: zipfile.ZipFile) -> None:
    try:
        bad = archive.testzip()
    except Exception:  # zlib.error, BadZipFile, EOFError, ...: all one answer
        raise BadZip("the zip is damaged") from None
    if bad is not None:
        raise BadZip("the zip is damaged")


def _check_names(infos: list[zipfile.ZipInfo]) -> None:
    seen: set[str] = set()
    for info in infos:
        name = info.filename
        _check_name(name)
        key = name[:-1] if name.endswith("/") else name
        if key in seen:
            # Which of two same-named entries an extractor keeps is its own
            # business, so the file validated might not be the one installed.
            raise BadZip("the zip has two entries with the same name")
        seen.add(key)


def _check_name(name: str) -> None:
    # Printable ASCII only (a space is fine: the folder has one). Refuses a
    # control character, a NUL and anything zipfile decoded from a legacy
    # code page as well as any non-ASCII name: this plugin ships none.
    if not name or any(not (" " <= char <= "~") for char in name):
        raise BadZip("the zip has an entry whose name is not plain text")
    if "\\" in name:
        raise BadZip("the zip has an entry name with a backslash")
    if name.startswith("/"):
        raise BadZip("the zip has an absolute entry name")
    if _DRIVE_RE.match(name):
        raise BadZip("the zip has an entry name with a drive letter")
    if not name.startswith(TOP):
        raise BadZip(f"the zip has an entry outside {TOP}")
    parts = (name[:-1] if name.endswith("/") else name).split("/")
    if any(part in ("", ".", "..") for part in parts):
        raise BadZip("the zip has an entry name with an empty, . or .. step")


def _entry(names: dict[str, zipfile.ZipInfo], rel: str) -> zipfile.ZipInfo | None:
    info = names.get(TOP + rel)
    return None if info is None or info.is_dir() else info


def _read_json(archive: zipfile.ZipFile, names: dict[str, zipfile.ZipInfo], rel: str) -> Any:
    """``Moonlight Sync/<rel>`` parsed, read in memory with a size cap."""
    info = _entry(names, rel)
    if info is None:
        raise BadZip(f"the zip has no {TOP}{rel}")
    text = _read_text(archive, info, rel)
    try:
        return json.loads(text)
    except ValueError:
        raise BadZip(f"{rel} does not parse") from None


def _read_text(archive: zipfile.ZipFile, info: zipfile.ZipInfo, rel: str) -> str:
    if info.file_size > JSON_MAX_BYTES:
        raise BadZip(f"{rel} is larger than {JSON_MAX_BYTES} bytes")
    try:
        with archive.open(info) as handle:
            raw = handle.read(JSON_MAX_BYTES + 1)
    except Exception:
        raise BadZip(f"{rel} cannot be read") from None
    if len(raw) > JSON_MAX_BYTES:
        raise BadZip(f"{rel} is larger than {JSON_MAX_BYTES} bytes")
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        raise BadZip(f"{rel} is not UTF-8") from None


def _check_plugin_json(plugin: Any) -> None:
    if not isinstance(plugin, dict):
        raise BadZip("plugin.json is not an object")
    if plugin.get("name") != PLUGIN_NAME:
        raise BadZip(f"plugin.json does not name {PLUGIN_NAME}")
    flags = plugin.get("flags")
    if not isinstance(flags, list):
        raise BadZip("plugin.json's flags is not a list")
    # Hard rule 2: the backend runs as the deck user. Decky reads the flag
    # as `root` (and the template once spelled `_root`).
    if any(str(flag).lower() in ("root", "_root") for flag in flags):
        raise BadZip("plugin.json asks for root")


def _check_package_json(package: Any) -> str:
    if not isinstance(package, dict):
        raise BadZip("package.json is not an object")
    found = package.get("version")
    if not isinstance(found, str) or parse_version(found) is None:
        raise BadZip("package.json has no version")
    return found


def _check_required_files(names: dict[str, zipfile.ZipInfo]) -> None:
    for rel in REQUIRED_FILES:
        if _entry(names, rel) is None:
            raise BadZip(f"the zip has no {TOP}{rel}")


def _check_version(found: str, version: str) -> None:
    # Both as parsed tuples and as the exact string: parse_version reads
    # only a leading X.Y.Z, so `0.12.0-evil` parses to 0.12.0.
    if parse_version(found) != parse_version(version) or found != version:
        raise BadZip(f"the zip is version {found}, not {version}")


def _check_build_json(
    archive: zipfile.ZipFile,
    names: dict[str, zipfile.ZipInfo],
    *,
    version: str | None,
    ref: str | None,
) -> dict[str, Any] | None:
    info = _entry(names, "build.json")
    if info is None:
        if ref is not None:
            raise BadZip("the zip has no build.json, so it is not a branch build")
        return None  # every release before build.json existed
    build = parse_build(_read_text(archive, info, "build.json"))
    if build is None:
        raise BadZip("build.json does not parse")
    if ref is not None:
        if build["kind"] != "branch":
            raise BadZip("build.json does not say it is a branch build")
        if build["ref"] != ref:
            raise BadZip(f"the zip is a build of {build['ref']}, not {ref}")
    if version is not None and build["kind"] == "branch":
        raise BadZip("the zip is a branch build, not a release")
    return build


# ---------------------------------------------------------------------------
# the staged directory


def staged_dir(runtime_dir: str) -> str:
    return os.path.join(runtime_dir, "update", "staged")


def staged_path(runtime_dir: str, sha256: str) -> str:
    """``<runtime_dir>/update/staged/Moonlight-Sync-<first 12 hex>.zip``.

    The name is built from the validated hash alone, so no caller's string
    reaches the path; ``ValueError`` on anything but 64 hex digits.
    """
    if not is_sha256(sha256):
        raise ValueError("not a sha256")
    return os.path.join(staged_dir(runtime_dir), f"Moonlight-Sync-{sha256.lower()[:12]}.zip")


def ensure_staged_dir(runtime_dir: str) -> str:
    """``update/staged/`` under the runtime directory, created ``0700`` when
    absent; ``OSError`` when ``update`` or ``staged`` is anything but a real
    directory (a symlink there could point the staging anywhere)."""
    os.makedirs(runtime_dir, exist_ok=True)
    path = runtime_dir
    for step in ("update", "staged"):
        path = os.path.join(path, step)
        with contextlib.suppress(FileExistsError):
            os.mkdir(path, 0o700)
        if not stat.S_ISDIR(os.lstat(path).st_mode):
            raise NotADirectoryError(f"{path} is not a directory")
    return path


def _real_dir(path: str) -> bool:
    try:
        return stat.S_ISDIR(os.lstat(path).st_mode)
    except OSError:
        return False


def remove_parts(runtime_dir: str) -> None:
    """Remove every ``*.part`` directly in the staged directory (a killed
    downloader cannot remove its own). Never raises."""
    _sweep(runtime_dir, lambda name, st: name.endswith(PART_SUFFIX))


def cleanup(runtime_dir: str, now: float | None = None) -> None:
    """Remove every file directly in ``update/staged/`` older than
    ``STAGED_KEEP_S``, and every ``*.part`` there. Never raises.

    Regular files only, never recursing: a symlink there is removed as a
    link and never followed, a directory is left alone, and nothing happens
    when ``update`` or ``staged`` is itself a symlink.
    """
    moment = time.time() if now is None else now
    _sweep(
        runtime_dir,
        lambda name, st: name.endswith(PART_SUFFIX) or moment - st.st_mtime > STAGED_KEEP_S,
    )


def _sweep(runtime_dir: str, doomed) -> None:
    try:
        update = os.path.join(runtime_dir, "update")
        staged = staged_dir(runtime_dir)
        if not (_real_dir(update) and _real_dir(staged)):
            return
        names = os.listdir(staged)
    except Exception:
        return
    for name in names:
        path = os.path.join(staged, name)
        try:
            st = os.lstat(path)
            if stat.S_ISLNK(st.st_mode) or (stat.S_ISREG(st.st_mode) and doomed(name, st)):
                os.unlink(path)
        except Exception:
            continue
