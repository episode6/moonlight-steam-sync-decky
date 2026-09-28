"""scripts/package.py: the Docker-free plugin zip (spec 3.6.2)."""

from __future__ import annotations

import json
import os
import re
import stat
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest

from conftest import ROOT
from moonlight_sync import updates

SCRIPT = ROOT / "scripts" / "package.py"
TOP = "Moonlight Sync"


@pytest.fixture
def tree(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    root.mkdir()
    (root / "plugin.json").write_text('{"name": "Moonlight Sync", "flags": []}\n')
    (root / "package.json").write_text('{"name": "moonlight-steam-sync-decky"}\n')
    (root / "main.py").write_text("class Plugin: ...\n")
    (root / "README.md").write_text("# Moonlight Sync\n")
    (root / "LICENSE").write_text("MIT\n")
    (root / "dist").mkdir()
    (root / "dist" / "index.js").write_text("export default 1;\n")
    pkg = root / "py_modules" / "moonlight_sync"
    pkg.mkdir(parents=True)
    (pkg / "__init__.py").write_text("")
    (pkg / "backend.py").write_text("X = 1\n")
    (pkg / "__pycache__").mkdir()
    (pkg / "__pycache__" / "backend.cpython-313.pyc").write_bytes(b"\0")
    (pkg / "stray.pyc").write_bytes(b"\0")
    (root / "src").mkdir()
    (root / "src" / "index.tsx").write_text("// not shipped\n")
    (root / "scripts").mkdir()
    (root / "tests").mkdir()
    return root


def add_cli(root: Path) -> Path:
    out = root / "backend" / "out"
    out.mkdir(parents=True)
    pyz = out / "moonlight-steam-sync.pyz"
    pyz.write_bytes(b"PK zipapp")
    return pyz


def package(root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT), "--root", str(root), *args],
        capture_output=True,
        text=True,
        check=False,
    )


def entries(root: Path) -> list[zipfile.ZipInfo]:
    with zipfile.ZipFile(root / "out" / "Moonlight-Sync.zip") as archive:
        return archive.infolist()


def test_exact_entry_list_with_the_cli(tree: Path) -> None:
    add_cli(tree)
    result = package(tree, "--require-cli", "--list")
    assert result.returncode == 0, result.stderr
    names = [info.filename for info in entries(tree)]
    assert names == [
        f"{TOP}/plugin.json",
        f"{TOP}/package.json",
        f"{TOP}/main.py",
        f"{TOP}/README.md",
        f"{TOP}/LICENSE",
        f"{TOP}/dist/",
        f"{TOP}/dist/index.js",
        f"{TOP}/py_modules/",
        f"{TOP}/py_modules/moonlight_sync/",
        f"{TOP}/py_modules/moonlight_sync/__init__.py",
        f"{TOP}/py_modules/moonlight_sync/backend.py",
        f"{TOP}/bin/",
        f"{TOP}/bin/moonlight-steam-sync.pyz",
    ]
    assert result.stdout.splitlines()[:-1] == names
    assert f"({len(names)} entries)" in result.stdout.splitlines()[-1]


def test_modes(tree: Path) -> None:
    add_cli(tree)
    assert package(tree).returncode == 0
    modes = {info.filename: stat.S_IMODE(info.external_attr >> 16) for info in entries(tree)}
    assert modes[f"{TOP}/bin/moonlight-steam-sync.pyz"] == 0o755
    assert modes[f"{TOP}/py_modules/moonlight_sync/backend.py"] == 0o755
    assert modes[f"{TOP}/py_modules/moonlight_sync/__init__.py"] == 0o755
    assert modes[f"{TOP}/main.py"] == 0o644
    assert modes[f"{TOP}/dist/index.js"] == 0o644
    for info in entries(tree):
        if not info.is_dir():
            assert info.compress_type == zipfile.ZIP_DEFLATED


def test_build_json_is_packaged_after_the_root_files(tree: Path) -> None:
    """Update spec 3.12.1: a CI build's build.json, from the root, 0644."""
    add_cli(tree)
    (tree / "build.json").write_text('{"schema": 1}\n')
    result = package(tree, "--require-cli", "--list")
    assert result.returncode == 0, result.stderr
    names = [info.filename for info in entries(tree)]
    assert names == [
        f"{TOP}/plugin.json",
        f"{TOP}/package.json",
        f"{TOP}/main.py",
        f"{TOP}/README.md",
        f"{TOP}/LICENSE",
        f"{TOP}/build.json",
        f"{TOP}/dist/",
        f"{TOP}/dist/index.js",
        f"{TOP}/py_modules/",
        f"{TOP}/py_modules/moonlight_sync/",
        f"{TOP}/py_modules/moonlight_sync/__init__.py",
        f"{TOP}/py_modules/moonlight_sync/backend.py",
        f"{TOP}/bin/",
        f"{TOP}/bin/moonlight-steam-sync.pyz",
    ]
    assert result.stdout.splitlines()[:-1] == names
    modes = {info.filename: stat.S_IMODE(info.external_attr >> 16) for info in entries(tree)}
    assert modes[f"{TOP}/build.json"] == 0o644
    with zipfile.ZipFile(tree / "out" / "Moonlight-Sync.zip") as archive:
        assert archive.read(f"{TOP}/build.json") == b'{"schema": 1}\n'


def test_without_build_json_the_zip_has_none(tree: Path) -> None:
    """Absent, the zip is what it always was (the exact list above, in
    test_exact_entry_list_with_the_cli); a directory of the name is not the file."""
    (tree / "build.json").mkdir()
    result = package(tree)
    assert result.returncode == 0
    assert not any("build.json" in info.filename for info in entries(tree))
    assert "package.py: no build.json: the root's is not a file" in result.stderr


# ---------------------------------------------------------------------------
# A build made outside CI: build.json from the git checkout (amendment A5)


def git(root: Path, *args: str) -> str:
    """git in ``root``, blind to the machine's own configuration."""
    env = {
        **{key: value for key, value in os.environ.items() if not key.startswith("GIT_")},
        "GIT_CONFIG_GLOBAL": os.devnull,
        "GIT_CONFIG_SYSTEM": os.devnull,
    }
    identity = ["-c", "user.name=Test", "-c", "user.email=test@example.invalid"]
    result = subprocess.run(
        ["git", "-C", str(root), *identity, "-c", "commit.gpgsign=false", *args],
        capture_output=True,
        text=True,
        check=True,
        env=env,
    )
    return result.stdout.strip()


@pytest.fixture
def checkout(tree: Path) -> Path:
    """``tree`` as a clone of the repository is: committed on ``main``, with
    what a build writes ignored, as the repository's own .gitignore has it."""
    add_cli(tree)
    (tree / ".gitignore").write_text("out\nbackend/out\n__pycache__/\n*.pyc\n")
    git(tree, "init", "--quiet", "--initial-branch", "main")
    git(tree, "add", "--all")
    git(tree, "commit", "--quiet", "--message", "everything")
    return tree


def packaged_build(root: Path) -> str | None:
    with zipfile.ZipFile(root / "out" / "Moonlight-Sync.zip") as archive:
        name = f"{TOP}/build.json"
        return archive.read(name).decode("utf-8") if name in archive.namelist() else None


def test_a_git_checkout_names_its_branch_and_commit(checkout: Path) -> None:
    sha = git(checkout, "rev-parse", "HEAD")
    result = package(checkout, "--require-cli", "--list")
    assert result.returncode == 0, result.stderr
    names = [info.filename for info in entries(checkout)]
    assert names[:7] == [
        f"{TOP}/plugin.json",
        f"{TOP}/package.json",
        f"{TOP}/main.py",
        f"{TOP}/README.md",
        f"{TOP}/LICENSE",
        f"{TOP}/build.json",
        f"{TOP}/dist/",
    ]
    assert result.stdout.splitlines()[:-1] == names
    assert f"package.py: build.json from git: main @ {sha[:12]}" in result.stderr
    text = packaged_build(checkout)
    assert text is not None and text.endswith("\n")
    data = json.loads(text)
    assert list(data) == ["schema", "kind", "ref", "sha", "built_at", "run"]
    assert (data["schema"], data["kind"], data["ref"], data["sha"]) == (1, "branch", "main", sha)
    assert data["run"] is None
    assert re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ", data["built_at"])
    modes = {info.filename: stat.S_IMODE(info.external_attr >> 16) for info in entries(checkout)}
    assert modes[f"{TOP}/build.json"] == 0o644
    # In the zip only: nothing is left at the root for a later build to package.
    assert not (checkout / "build.json").exists()


def test_the_backend_reads_a_git_build_as_the_branch_s(checkout: Path) -> None:
    """What the Updates page compares with the published build's build.json."""
    assert package(checkout).returncode == 0
    text = packaged_build(checkout)
    assert text is not None
    assert updates.parse_build(text) == {
        "schema": 1,
        "kind": "branch",
        "ref": "main",
        "sha": git(checkout, "rev-parse", "HEAD"),
        "built_at": json.loads(text)["built_at"],
        "run": None,
    }


def test_a_second_build_of_the_checkout_says_the_same(checkout: Path) -> None:
    """The first build's out/ is ignored, so the checkout is still its commit."""
    assert package(checkout).returncode == 0
    first = packaged_build(checkout)
    assert package(checkout).returncode == 0
    second = packaged_build(checkout)
    assert first is not None and second is not None
    assert json.loads(first)["sha"] == json.loads(second)["sha"]


def test_another_branch_is_named(checkout: Path) -> None:
    git(checkout, "switch", "--quiet", "--create", "self-update/u3_builds.v2")
    assert package(checkout).returncode == 0
    text = packaged_build(checkout)
    assert text is not None
    assert json.loads(text)["ref"] == "self-update/u3_builds.v2"


def test_the_root_s_build_json_wins_over_git(checkout: Path) -> None:
    """CI's file, written by build_info.py before package.py runs."""
    (checkout / "build.json").write_text('{"schema": 1}\n')
    result = package(checkout)
    assert result.returncode == 0, result.stderr
    assert packaged_build(checkout) == '{"schema": 1}\n'
    assert "package.py: build.json from the root" in result.stderr
    assert "from git" not in result.stderr


def test_a_directory_named_build_json_is_not_replaced_by_git_s(checkout: Path) -> None:
    """Whatever put it there, the root's build.json is the root's to decide."""
    (checkout / "build.json").mkdir()
    result = package(checkout)
    assert result.returncode == 0, result.stderr
    assert packaged_build(checkout) is None
    assert "package.py: no build.json: the root's is not a file" in result.stderr
    assert "from git" not in result.stderr


def test_a_tag_named_like_the_branch_does_not_rename_it(checkout: Path) -> None:
    """``symbolic-ref --short`` answers heads/main then; CI's ref_name is main."""
    git(checkout, "tag", "main")
    assert git(checkout, "symbolic-ref", "--short", "HEAD") == "heads/main"
    result = package(checkout)
    assert result.returncode == 0, result.stderr
    text = packaged_build(checkout)
    assert text is not None
    assert json.loads(text)["ref"] == "main"
    assert "package.py: build.json from git: main @ " in result.stderr


@pytest.mark.parametrize("change", ["edited", "untracked", "staged"])
def test_uncommitted_changes_are_not_the_commit(checkout: Path, change: str) -> None:
    if change == "edited":
        (checkout / "main.py").write_text("class Plugin: pass\n")
    else:
        (checkout / "py_modules" / "moonlight_sync" / "extra.py").write_text("Y = 2\n")
    if change == "staged":
        git(checkout, "add", "--all")
    result = package(checkout)
    assert result.returncode == 0, result.stderr
    assert packaged_build(checkout) is None
    assert "package.py: no build.json: the checkout has uncommitted changes" in result.stderr


def test_a_detached_head_names_no_branch(checkout: Path) -> None:
    git(checkout, "checkout", "--quiet", "--detach")
    result = package(checkout)
    assert result.returncode == 0, result.stderr
    assert packaged_build(checkout) is None
    # `symbolic-ref --quiet` says nothing of a detached HEAD, so nothing is quoted.
    assert "package.py: no build.json: HEAD is detached, so no branch names this build\n" in (
        result.stderr
    )


def test_a_branch_name_build_json_cannot_carry(checkout: Path) -> None:
    git(checkout, "switch", "--quiet", "--create", "feature+x")
    result = package(checkout)
    assert result.returncode == 0, result.stderr
    assert packaged_build(checkout) is None
    assert "package.py: no build.json: --ref must match" in result.stderr


@pytest.mark.parametrize("name", ["café".encode(), "café".encode("latin-1")])
def test_a_branch_named_in_bytes_that_are_not_ascii_is_refused_not_a_crash(
    checkout: Path, name: bytes
) -> None:
    """UTF-8 or not (a Latin-1 é is no UTF-8 at all), under a C locale with
    Python's UTF-8 mode off: the name is refused and the zip is still built."""
    git(checkout, "switch", "--quiet", "--create", os.fsdecode(name))
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--root", str(checkout)],
        capture_output=True,
        encoding="utf-8",
        errors="replace",
        check=False,
        env={**os.environ, "LC_ALL": "C", "LANG": "C", "PYTHONUTF8": "0"},
    )
    assert result.returncode == 0, result.stderr
    assert "Traceback" not in result.stderr
    assert packaged_build(checkout) is None
    assert "package.py: no build.json: --ref must match" in result.stderr


def test_a_directory_inside_another_checkout_is_not_that_commit(
    tree: Path, tmp_path: Path
) -> None:
    (tmp_path / ".gitignore").write_text("out\n__pycache__/\n*.pyc\n")
    git(tmp_path, "init", "--quiet", "--initial-branch", "main")
    git(tmp_path, "add", "--all")
    git(tmp_path, "commit", "--quiet", "--message", "everything")
    result = package(tree)
    assert result.returncode == 0, result.stderr
    assert packaged_build(tree) is None
    assert "package.py: no build.json: not the root of a git checkout" in result.stderr


def test_a_tree_that_is_no_checkout_has_none(tree: Path) -> None:
    result = package(tree)
    assert result.returncode == 0, result.stderr
    assert packaged_build(tree) is None
    assert "package.py: no build.json: not the root of a git checkout (git: fatal: not a git" in (
        result.stderr
    )


def test_git_s_own_refusal_is_quoted(checkout: Path) -> None:
    """A clone that belongs to another user ("dubious ownership"), as git
    itself simulates it; the machine's safe.directory is shut out."""
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--root", str(checkout)],
        capture_output=True,
        text=True,
        check=False,
        env={
            **os.environ,
            "GIT_TEST_ASSUME_DIFFERENT_OWNER": "1",
            "GIT_CONFIG_GLOBAL": os.devnull,
            "GIT_CONFIG_SYSTEM": os.devnull,
        },
    )
    assert result.returncode == 0, result.stderr
    assert packaged_build(checkout) is None
    assert "package.py: no build.json: not the root of a git checkout (git: fatal: " in (
        result.stderr
    )
    assert "dubious ownership" in result.stderr


def test_without_git_the_zip_is_still_built(checkout: Path, tmp_path: Path) -> None:
    empty = tmp_path / "no-git-here"
    empty.mkdir()
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--root", str(checkout)],
        capture_output=True,
        text=True,
        check=False,
        env={**os.environ, "PATH": str(empty)},
    )
    assert result.returncode == 0, result.stderr
    assert packaged_build(checkout) is None
    assert (
        "package.py: no build.json: not the root of a git checkout"
        " (git did not run: FileNotFoundError)"
    ) in result.stderr


def test_without_the_cli_warns_and_packages(tree: Path) -> None:
    result = package(tree)
    assert result.returncode == 0
    assert "::warning::packaging without bin/moonlight-steam-sync.pyz" in result.stderr
    names = [info.filename for info in entries(tree)]
    assert not any("/bin/" in name for name in names)
    assert f"{TOP}/dist/index.js" in names


def test_require_cli_fails_without_the_cli(tree: Path) -> None:
    result = package(tree, "--require-cli")
    assert result.returncode == 1
    assert "backend/out/moonlight-steam-sync.pyz is missing; run backend/entrypoint.sh" in (
        result.stderr
    )
    assert not (tree / "out" / "Moonlight-Sync.zip").exists()


def test_requires_a_built_frontend(tree: Path) -> None:
    (tree / "dist" / "index.js").unlink()
    result = package(tree)
    assert result.returncode == 1
    assert "run `pnpm run build` first" in result.stderr


def test_defaults_land_at_the_root(tree: Path) -> None:
    (tree / "defaults").mkdir()
    (tree / "defaults" / "themes.json").write_text("{}\n")
    assert package(tree).returncode == 0
    assert f"{TOP}/themes.json" in [info.filename for info in entries(tree)]


def test_custom_out(tree: Path, tmp_path: Path) -> None:
    target = tmp_path / "elsewhere" / "x.zip"
    assert package(tree, "--out", str(target)).returncode == 0
    assert zipfile.ZipFile(target).namelist()[0] == f"{TOP}/plugin.json"


def test_the_real_plugin_json_names_the_directory() -> None:
    import json

    meta = json.loads((ROOT / "plugin.json").read_text())
    assert meta["name"] == TOP
    assert meta["flags"] == []


def test_the_downloader_and_the_staging_are_packaged(tree: Path) -> None:
    """Update spec 3.12.6: fetch.py ships beside the backend (which runs it
    from there as a script), with updates.py."""
    pkg = tree / "py_modules" / "moonlight_sync"
    for name in ("fetch.py", "updates.py"):
        (pkg / name).write_bytes((ROOT / "py_modules" / "moonlight_sync" / name).read_bytes())
    result = package(tree, "--list")
    assert result.returncode == 0, result.stderr
    modes = {info.filename: stat.S_IMODE(info.external_attr >> 16) for info in entries(tree)}
    for name in ("fetch.py", "updates.py"):
        assert modes[f"{TOP}/py_modules/moonlight_sync/{name}"] == 0o755
        assert f"{TOP}/py_modules/moonlight_sync/{name}" in result.stdout.splitlines()
