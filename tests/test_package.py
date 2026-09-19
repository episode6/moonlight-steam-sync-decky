"""scripts/package.py: the Docker-free plugin zip (spec 3.6.2)."""

from __future__ import annotations

import stat
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest

from conftest import ROOT

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
