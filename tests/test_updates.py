"""updates.py: URLs, the sidecar, build.json, validate_zip (one test per
rule), staged_path and cleanup (update spec 3.12.3 / 3.12.6)."""

from __future__ import annotations

import json
import os
import stat
import zipfile

import pytest

from moonlight_sync import updates
from updatezip import SHA, branch_build, build_zip, patch_central

pytestmark = pytest.mark.usefixtures("no_network")

TOP = "Moonlight Sync/"
HASH = "ab" * 32


# ---------------------------------------------------------------------------
# asset_url, parse_sidecar


def test_asset_url() -> None:
    source = updates.Source()
    assert updates.asset_url(source, "v0.12.0", updates.ASSET) == (
        "https://github.com/episode6/moonlight-steam-sync-decky/releases/download/"
        "v0.12.0/Moonlight-Sync.zip"
    )
    assert updates.asset_url(source, "build-main", updates.ASSET_SHA).endswith(
        "/build-main/Moonlight-Sync.zip.sha256"
    )
    other = updates.Source(download_base="file:///srv/releases", allow_file=True)
    assert (
        updates.asset_url(other, "v1", updates.ASSET)
        == "file:///srv/releases/v1/Moonlight-Sync.zip"
    )


@pytest.mark.parametrize(
    "tag", ["", ".", "..", "v1/../x", "a" * 101, "v1?x=1", "v1 x", "v1\n", "v1#x", None, 1, True]
)
def test_asset_url_refuses_a_tag_outside_the_pattern(tag) -> None:
    with pytest.raises(ValueError):
        updates.asset_url(updates.Source(), tag, updates.ASSET)


def test_asset_url_refuses_another_asset() -> None:
    with pytest.raises(ValueError):
        updates.asset_url(updates.Source(), "v1", "../../evil.zip")


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        (f"{HASH}  Moonlight-Sync.zip\n", HASH),
        (f"{HASH.upper()}\n", HASH),
        (f"  {HASH}", HASH),
        ("", None),
        ("not-a-hash Moonlight-Sync.zip", None),
        (HASH[:-1], None),
        (HASH + "0", None),
        (f"sha256:{HASH}", None),
    ],
)
def test_parse_sidecar(text, expected) -> None:
    assert updates.parse_sidecar(text) == expected


# ---------------------------------------------------------------------------
# read_build


def write_build(tmp_path, value) -> str:
    text = value if isinstance(value, str) else json.dumps(value)
    (tmp_path / "build.json").write_text(text)
    return str(tmp_path)


def test_read_build_answers_the_known_keys(tmp_path) -> None:
    raw = {**branch_build("self-update/u4a", sha=SHA.upper()), "extra": "<script>"}
    assert updates.read_build(write_build(tmp_path, raw)) == {
        "schema": 1,
        "kind": "branch",
        "ref": "self-update/u4a",
        "sha": SHA,
        "built_at": "2026-10-02T14:03:11Z",
        "run": "123456/1",
    }


def test_read_build_missing_is_none(tmp_path) -> None:
    assert updates.read_build(str(tmp_path)) is None


@pytest.mark.parametrize(
    "value",
    [
        "{not json",
        "[1, 2]",
        {**branch_build(), "schema": 2},
        {**branch_build(), "schema": True},
        {**branch_build(), "schema": 1.0},
        {**branch_build(), "kind": "nightly"},
        {**branch_build(), "sha": "abc"},
        {**branch_build(), "sha": "g" * 40},
        {**branch_build(), "ref": "a+b"},
        {**branch_build(), "ref": ""},
        {**branch_build(), "ref": "a" * 101},
        {**branch_build(), "ref": 7},
    ],
)
def test_read_build_refuses_what_is_not_a_build(tmp_path, value) -> None:
    assert updates.read_build(write_build(tmp_path, value)) is None


def test_read_build_caps_the_file(tmp_path) -> None:
    padded = json.dumps(branch_build()) + " " * updates.JSON_MAX_BYTES
    assert updates.read_build(write_build(tmp_path, padded)) is None


# ---------------------------------------------------------------------------
# validate_zip: a good zip, then one test per rule


def refused(path, message: str, *, version="0.12.0", ref=None) -> None:
    with pytest.raises(updates.BadZip) as caught:
        updates.validate_zip(str(path), version=version, ref=ref)
    assert message in caught.value.message


def test_a_release_zip_passes(tmp_path) -> None:
    path = build_zip(tmp_path / "z.zip", version="0.12.0")
    assert updates.validate_zip(str(path), version="0.12.0", ref=None) == {
        "version": "0.12.0",
        "build": None,
    }


def test_a_release_zip_with_its_release_build_json_passes(tmp_path) -> None:
    build = branch_build("v0.12.0", kind="release")
    path = build_zip(tmp_path / "z.zip", version="0.12.0", build=build)
    assert updates.validate_zip(str(path), version="0.12.0", ref=None)["build"]["kind"] == "release"


@pytest.mark.parametrize("ref", ["v0.11.0", "0.12.0", "v0.12.0-rc1", "V0.12.0", "main"])
def test_a_release_s_build_json_must_name_the_release(tmp_path, ref) -> None:
    build = branch_build(ref, kind="release")
    path = build_zip(tmp_path / "z.zip", version="0.12.0", build=build)
    refused(path, f"the zip is the build of {ref}, not of v0.12.0")


def test_a_branch_zip_passes(tmp_path) -> None:
    path = build_zip(tmp_path / "z.zip", version="0.11.0", build=branch_build("self-update/x"))
    checked = updates.validate_zip(str(path), version=None, ref="self-update/x")
    assert checked["version"] == "0.11.0"
    assert checked["build"]["ref"] == "self-update/x"


def test_the_real_package_layout_passes(tmp_path) -> None:
    """scripts/package.py's own shape: 0755 py_modules, directory entries."""
    import subprocess
    import sys

    from conftest import ROOT

    root = tmp_path / "repo"
    (root / "dist").mkdir(parents=True)
    (root / "dist" / "index.js").write_text("export default 1;\n")
    for name in ("plugin.json", "package.json", "main.py", "README.md", "LICENSE"):
        (root / name).write_bytes((ROOT / name).read_bytes())
    pkg = root / "py_modules" / "moonlight_sync"
    pkg.mkdir(parents=True)
    for source in (ROOT / "py_modules" / "moonlight_sync").glob("*.py"):
        (pkg / source.name).write_bytes(source.read_bytes())
    out = tmp_path / "out.zip"
    result = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts" / "package.py"),
            "--root",
            str(root),
            "--out",
            str(out),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    version = json.loads((ROOT / "package.json").read_text())["version"]
    assert updates.validate_zip(str(out), version=version, ref=None)["version"] == version


def test_not_a_zip(tmp_path) -> None:
    path = tmp_path / "z.zip"
    path.write_bytes(b"not a zip at all")
    refused(path, "not a zip")


def test_a_missing_file_is_not_a_zip(tmp_path) -> None:
    refused(tmp_path / "nothing.zip", "not a zip")


def test_a_file_over_the_download_limit(tmp_path, monkeypatch) -> None:
    path = build_zip(tmp_path / "z.zip", version="0.12.0")
    monkeypatch.setattr(updates, "ZIP_MAX_BYTES", 100)
    refused(path, "larger than 100 bytes")


def test_an_empty_zip(tmp_path) -> None:
    path = tmp_path / "z.zip"
    zipfile.ZipFile(path, "w").close()
    refused(path, "the zip is empty")


def test_too_many_entries(tmp_path, monkeypatch) -> None:
    path = build_zip(tmp_path / "z.zip", version="0.12.0")
    monkeypatch.setattr(updates, "MAX_ENTRIES", 3)
    refused(path, "more than 3 entries")


def test_an_encrypted_entry(tmp_path) -> None:
    path = build_zip(tmp_path / "z.zip", version="0.12.0")
    patch_central(path, TOP + "main.py", flag_bits=0x1)
    refused(path, "encrypted entry")


@pytest.mark.parametrize("kind", [stat.S_IFLNK, stat.S_IFIFO, stat.S_IFCHR, stat.S_IFBLK])
def test_a_special_file_entry(tmp_path, kind) -> None:
    info = zipfile.ZipInfo(TOP + "py_modules/link")
    info.external_attr = (kind | 0o777) << 16
    path = build_zip(tmp_path / "z.zip", version="0.12.0", extra=[(info, "/etc/passwd")])
    refused(path, "neither a file nor a directory")


def test_an_unexpected_compression_method(tmp_path) -> None:
    info = zipfile.ZipInfo(TOP + "notes.txt")
    info.compress_type = zipfile.ZIP_BZIP2
    path = build_zip(tmp_path / "z.zip", version="0.12.0", extra=[(info, "x" * 100)])
    refused(path, "unexpected method")


def test_a_bomb_by_declared_size(tmp_path) -> None:
    path = build_zip(tmp_path / "z.zip", version="0.12.0", extra=[("big.bin", b"\0" * 1000)])
    patch_central(path, TOP + "big.bin", file_size=updates.UNPACKED_MAX_BYTES + 1)
    refused(path, "unpacks to more than")


def test_the_real_sum_over_the_limit(tmp_path, monkeypatch) -> None:
    path = build_zip(tmp_path / "z.zip", version="0.12.0", extra=[("big.bin", b"x" * 5000)])
    monkeypatch.setattr(updates, "UNPACKED_MAX_BYTES", 4000)
    refused(path, "unpacks to more than 4000")


def test_an_entry_that_claims_no_compressed_bytes(tmp_path) -> None:
    path = build_zip(tmp_path / "z.zip", version="0.12.0")
    patch_central(path, TOP + "main.py", compress_size=0)
    refused(path, "claims to be empty")


def test_an_absurd_ratio(tmp_path) -> None:
    path = build_zip(tmp_path / "z.zip", version="0.12.0", extra=[("big.bin", b"\0" * 10)])
    info = next(i for i in zipfile.ZipFile(path).infolist() if i.filename == TOP + "big.bin")
    patch_central(path, TOP + "big.bin", file_size=info.compress_size * (updates.MAX_RATIO + 1))
    refused(path, "compressed beyond any real file")


def test_a_damaged_entry(tmp_path) -> None:
    path = build_zip(tmp_path / "z.zip", version="0.12.0", extra=[("data.bin", b"payload" * 50)])
    data = bytearray(path.read_bytes())
    # Flip a byte of data.bin's compressed data: the first spelling of its
    # name is its local header's, and the data follows it.
    header = data.find((TOP + "data.bin").encode())
    data[header + len(TOP + "data.bin") + 5] ^= 0xFF
    path.write_bytes(bytes(data))
    refused(path, "damaged")


def test_the_names_are_judged_before_anything_is_inflated(tmp_path) -> None:
    """A zip both misnamed and damaged reports the name: the names are read
    from the central directory, before testzip()."""
    info = zipfile.ZipInfo("Elsewhere/data.bin")
    info.compress_type = zipfile.ZIP_DEFLATED
    info.external_attr = (stat.S_IFREG | 0o644) << 16
    path = build_zip(tmp_path / "z.zip", version="0.12.0", extra=[(info, b"payload" * 50)])
    data = bytearray(path.read_bytes())
    header = data.find(b"Elsewhere/data.bin")
    data[header + len("Elsewhere/data.bin") + 5] ^= 0xFF
    path.write_bytes(bytes(data))
    with zipfile.ZipFile(path) as archive:
        assert archive.testzip() == "Elsewhere/data.bin"  # really damaged
    refused(path, "outside Moonlight Sync/")


@pytest.mark.parametrize(
    ("name", "message"),
    [
        (TOP + "a\x01b", "not plain text"),
        (TOP + "a\x7fb", "not plain text"),
        (TOP + "a\nb", "not plain text"),
        (TOP + "caf\u00e9.txt", "not plain text"),
        (TOP + "a\\b", "backslash"),
        ("/etc/cron.d/x", "absolute entry name"),
        ("//server/share/x", "absolute entry name"),
        ("C:/x", "drive letter"),
        ("c:x", "drive letter"),
        ("Other/x", "outside Moonlight Sync/"),
        ("Moonlight Sync", "outside Moonlight Sync/"),
        ("Moonlight Syncx/a", "outside Moonlight Sync/"),
        (TOP + "../x", "empty, . or .. step"),
        (TOP + "a/../../x", "empty, . or .. step"),
        (TOP + "./x", "empty, . or .. step"),
        (TOP + "a//x", "empty, . or .. step"),
        (TOP + "a/./x", "empty, . or .. step"),
    ],
)
def test_a_bad_entry_name(tmp_path, name, message) -> None:
    info = zipfile.ZipInfo(name)
    info.external_attr = (stat.S_IFREG | 0o644) << 16
    path = build_zip(tmp_path / "z.zip", version="0.12.0", extra=[(info, "x")])
    refused(path, message)


def test_a_name_with_a_nul_reads_as_zipfile_cuts_it(tmp_path) -> None:
    """zipfile (the reader here and Decky's extractall alike) ends a name at
    its first NUL, so `main.py\\0x` is `main.py` to both: a duplicate."""
    path = build_zip(tmp_path / "z.zip", version="0.12.0", extra=[("main.pyZx", "evil = 1\n")])
    path.write_bytes(path.read_bytes().replace(b"main.pyZx", b"main.py\0x"))
    refused(path, "two entries with the same name")


def test_the_top_folder_entry_itself_is_fine(tmp_path) -> None:
    info = zipfile.ZipInfo(TOP)
    info.external_attr = ((stat.S_IFDIR | 0o755) << 16) | 0x10
    path = build_zip(tmp_path / "z.zip", version="0.12.0", extra=[(info, "")])
    assert updates.validate_zip(str(path), version="0.12.0", ref=None)["version"] == "0.12.0"


def test_another_top_folder(tmp_path) -> None:
    path = build_zip(tmp_path / "z.zip", version="0.12.0", top="Moonlight-Sync")
    refused(path, "outside Moonlight Sync/")


def test_a_duplicate_name(tmp_path) -> None:
    path = build_zip(tmp_path / "z.zip", version="0.12.0", extra=[("main.py", "evil = 1\n")])
    refused(path, "two entries with the same name")


def test_a_duplicate_name_by_trailing_slash(tmp_path) -> None:
    folder = zipfile.ZipInfo(TOP + "main.py/")
    folder.external_attr = ((stat.S_IFDIR | 0o755) << 16) | 0x10
    path = build_zip(tmp_path / "z.zip", version="0.12.0", extra=[(folder, "")])
    refused(path, "two entries with the same name")


def test_no_plugin_json(tmp_path) -> None:
    refused(
        build_zip(tmp_path / "z.zip", version="0.12.0", omit=["plugin.json"]),
        "no Moonlight Sync/plugin.json",
    )


def test_plugin_json_does_not_parse(tmp_path) -> None:
    path = build_zip(
        tmp_path / "z.zip", version="0.12.0", omit=["plugin.json"], extra=[("plugin.json", "{")]
    )
    refused(path, "plugin.json does not parse")


def test_plugin_json_too_large(tmp_path) -> None:
    padded = json.dumps({"name": "Moonlight Sync", "flags": []}) + " " * updates.JSON_MAX_BYTES
    path = build_zip(
        tmp_path / "z.zip", version="0.12.0", omit=["plugin.json"], extra=[("plugin.json", padded)]
    )
    refused(path, "plugin.json is larger than")


def test_plugin_json_is_not_an_object(tmp_path) -> None:
    path = build_zip(
        tmp_path / "z.zip", version="0.12.0", omit=["plugin.json"], extra=[("plugin.json", "[]")]
    )
    refused(path, "plugin.json is not an object")


@pytest.mark.parametrize("name", ["Moonlight Sync ", "moonlight sync", "Other", ""])
def test_plugin_json_names_another_plugin(tmp_path, name) -> None:
    refused(
        build_zip(tmp_path / "z.zip", version="0.12.0", name=name), "does not name Moonlight Sync"
    )


@pytest.mark.parametrize("flags", [None, "root", {"root": True}, 0])
def test_flags_must_be_a_list(tmp_path, flags) -> None:
    path = build_zip(tmp_path / "z.zip", version="0.12.0", flags=flags)
    refused(path, "flags is not a list")


def test_flags_missing(tmp_path) -> None:
    path = build_zip(
        tmp_path / "z.zip",
        version="0.12.0",
        omit=["plugin.json"],
        extra=[("plugin.json", '{"name": "Moonlight Sync"}')],
    )
    refused(path, "flags is not a list")


@pytest.mark.parametrize("flags", [["root"], ["_root"], ["ROOT"], ["debug", "_Root"]])
def test_flags_asking_for_root(tmp_path, flags) -> None:
    refused(build_zip(tmp_path / "z.zip", version="0.12.0", flags=flags), "asks for root")


def test_other_flags_are_fine(tmp_path) -> None:
    path = build_zip(tmp_path / "z.zip", version="0.12.0", flags=["debug"])
    assert updates.validate_zip(str(path), version="0.12.0", ref=None)["version"] == "0.12.0"


def test_no_package_json(tmp_path) -> None:
    path = build_zip(tmp_path / "z.zip", version="0.12.0", omit=["package.json"])
    refused(path, "no Moonlight Sync/package.json")


@pytest.mark.parametrize("version", ["", "dev", "v0.12.0", "0.12"])
def test_package_json_version_does_not_parse(tmp_path, version) -> None:
    refused(
        build_zip(tmp_path / "z.zip", version=version),
        "package.json has no version",
        ref="main",
        version=None,
    )


@pytest.mark.parametrize("missing", ["main.py", "dist/index.js"])
def test_a_required_file_is_missing(tmp_path, missing) -> None:
    refused(
        build_zip(tmp_path / "z.zip", version="0.12.0", omit=[missing]),
        f"no Moonlight Sync/{missing}",
    )


def test_a_required_file_that_is_a_directory(tmp_path) -> None:
    folder = zipfile.ZipInfo(TOP + "dist/index.js/")
    folder.external_attr = ((stat.S_IFDIR | 0o755) << 16) | 0x10
    path = build_zip(
        tmp_path / "z.zip", version="0.12.0", omit=["dist/index.js"], extra=[(folder, "")]
    )
    refused(path, "no Moonlight Sync/dist/index.js")


@pytest.mark.parametrize("found", ["0.12.1", "0.12.0-evil", "0.12.0.dev1", "0.12.00"])
def test_the_version_must_be_the_release_s(tmp_path, found) -> None:
    refused(build_zip(tmp_path / "z.zip", version=found), f"the zip is version {found}, not 0.12.0")


def test_a_branch_build_is_not_a_release(tmp_path) -> None:
    path = build_zip(tmp_path / "z.zip", version="0.12.0", build=branch_build("main"))
    refused(path, "a branch build, not a release")


def test_a_broken_build_json_is_refused(tmp_path) -> None:
    path = build_zip(tmp_path / "z.zip", version="0.12.0", build="{broken")
    refused(path, "build.json does not parse")


def test_a_branch_needs_build_json(tmp_path) -> None:
    path = build_zip(tmp_path / "z.zip", version="0.12.0")
    refused(path, "no build.json", version=None, ref="main")


def test_a_branch_needs_kind_branch(tmp_path) -> None:
    path = build_zip(
        tmp_path / "z.zip", version="0.12.0", build=branch_build("main", kind="release")
    )
    refused(path, "does not say it is a branch build", version=None, ref="main")


@pytest.mark.parametrize("built", ["main2", "Main", "self-update/main", "main/"])
def test_a_branch_needs_its_own_ref(tmp_path, built) -> None:
    path = build_zip(tmp_path / "z.zip", version="0.12.0", build=branch_build(built))
    refused(path, f"a build of {built}, not main", version=None, ref="main")


def test_validate_zip_extracts_nothing(tmp_path) -> None:
    path = build_zip(tmp_path / "z.zip", version="0.12.0")
    before = sorted(os.listdir(tmp_path))
    updates.validate_zip(str(path), version="0.12.0", ref=None)
    assert sorted(os.listdir(tmp_path)) == before


# ---------------------------------------------------------------------------
# staged_path, ensure_staged_dir, cleanup


def test_staged_path(tmp_path) -> None:
    assert updates.staged_path(str(tmp_path), HASH.upper()) == str(
        tmp_path / "update" / "staged" / f"Moonlight-Sync-{HASH[:12]}.zip"
    )


@pytest.mark.parametrize("value", ["", "ab" * 31, "../../" + "a" * 58, "g" * 64, None, 12])
def test_staged_path_refuses_what_is_not_a_hash(tmp_path, value) -> None:
    with pytest.raises(ValueError):
        updates.staged_path(str(tmp_path), value)


def test_ensure_staged_dir_creates_0700(tmp_path) -> None:
    runtime = tmp_path / "data" / "Moonlight Sync"
    staged = updates.ensure_staged_dir(str(runtime))
    assert staged == str(runtime / "update" / "staged")
    for path in (runtime / "update", runtime / "update" / "staged"):
        assert stat.S_IMODE(path.stat().st_mode) == 0o700
    assert updates.ensure_staged_dir(str(runtime)) == staged  # twice is fine


def test_ensure_staged_dir_refuses_a_symlinked_directory(tmp_path) -> None:
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    (tmp_path / "rt" / "update").mkdir(parents=True)
    os.symlink(elsewhere, tmp_path / "rt" / "update" / "staged")
    with pytest.raises(OSError):
        updates.ensure_staged_dir(str(tmp_path / "rt"))


def staged(tmp_path):
    path = tmp_path / "update" / "staged"
    path.mkdir(parents=True)
    return path


def test_cleanup(tmp_path) -> None:
    folder = staged(tmp_path)
    now = 1_800_000_000
    old = folder / "Moonlight-Sync-aaaaaaaaaaaa.zip"
    fresh = folder / "Moonlight-Sync-bbbbbbbbbbbb.zip"
    part = folder / "Moonlight-Sync-cccccccccccc.zip.part"
    for path in (old, fresh, part):
        path.write_bytes(b"x")
    os.utime(old, (now - updates.STAGED_KEEP_S - 1,) * 2)
    os.utime(fresh, (now - 10,) * 2)
    os.utime(part, (now - 10,) * 2)
    sub = folder / "subdir"
    sub.mkdir()
    (sub / "inner.zip").write_bytes(b"x")
    os.utime(sub / "inner.zip", (0, 0))
    updates.cleanup(str(tmp_path), now)
    assert sorted(os.listdir(folder)) == ["Moonlight-Sync-bbbbbbbbbbbb.zip", "subdir"]
    assert (sub / "inner.zip").exists()  # no recursion


def test_cleanup_removes_a_symlink_as_a_link(tmp_path) -> None:
    folder = staged(tmp_path)
    target = tmp_path / "precious.txt"
    target.write_text("keep")
    os.utime(target, (0, 0))
    os.symlink(target, folder / "link.zip")
    updates.cleanup(str(tmp_path), 1_800_000_000)
    assert not os.path.lexists(folder / "link.zip")
    assert target.read_text() == "keep"


def test_cleanup_never_follows_a_symlinked_staged_directory(tmp_path) -> None:
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    victim = elsewhere / "old.part"
    victim.write_bytes(b"x")
    os.utime(victim, (0, 0))
    (tmp_path / "rt" / "update").mkdir(parents=True)
    os.symlink(elsewhere, tmp_path / "rt" / "update" / "staged")
    updates.cleanup(str(tmp_path / "rt"), 1_800_000_000)
    assert victim.exists()


def test_cleanup_never_raises_and_creates_nothing(tmp_path, monkeypatch) -> None:
    missing = tmp_path / "nothing-here"
    updates.cleanup(str(missing))
    assert not missing.exists()
    folder = staged(tmp_path)
    (folder / "x.part").write_bytes(b"x")

    def boom(*args, **kwargs):
        raise PermissionError("nope")

    monkeypatch.setattr(updates.os, "unlink", boom)
    updates.cleanup(str(tmp_path))  # swallowed
    monkeypatch.setattr(updates.os, "listdir", boom)
    updates.cleanup(str(tmp_path))


def test_remove_parts_only_touches_part_files(tmp_path) -> None:
    folder = staged(tmp_path)
    (folder / "a.zip.part").write_bytes(b"x")
    (folder / "b.zip").write_bytes(b"x")
    updates.remove_parts(str(tmp_path))
    assert os.listdir(folder) == ["b.zip"]


def test_strip_queries() -> None:
    text = "HTTP 403 from https://release-assets.githubusercontent.com/x/y?token=SECRET&a=b#frag"
    assert (
        updates.strip_queries(text)
        == "HTTP 403 from https://release-assets.githubusercontent.com/x/y"
    )


def test_nothing_at_the_top_level_is_named_updater() -> None:
    assert not hasattr(updates, "updater")
