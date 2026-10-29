"""scripts/set_version.py: the one version written in both of its spellings
(hard rule 8), and build_cli.py's cli_spelling, the rule it writes by."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from conftest import ROOT

SCRIPT = ROOT / "scripts" / "set_version.py"
INIT = Path("cli") / "src" / "moonlight_steam_sync" / "__init__.py"

sys.path.insert(0, str(ROOT / "scripts"))
import build_cli  # noqa: E402

PACKAGE_JSON = {
    "name": "x",
    "version": "0.13.2",
    "description": "a plugin, with a non-ASCII word: café",
    "scripts": {"build": "rollup -c"},
}
INIT_TEXT = (
    '"""The CLI."""\n\n#: shared with package.json\n__version__ = "0.13.2"\n\n\n'
    "def version() -> str:\n    return __version__\n"
)


@pytest.fixture
def tree(tmp_path: Path) -> Path:
    (tmp_path / "package.json").write_text(
        json.dumps(PACKAGE_JSON, indent=2, ensure_ascii=False) + "\n"
    )
    (tmp_path / INIT).parent.mkdir(parents=True)
    (tmp_path / INIT).write_text(INIT_TEXT)
    return tmp_path


def set_version(root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args, "--root", str(root)],
        capture_output=True,
        text=True,
        check=False,
    )


@pytest.mark.parametrize(
    ("plugin", "cli"),
    [
        ("0.14.0", "0.14.0"),
        ("0.14.0-SNAPSHOT", "0.14.0.dev0"),
        ("1.0.0-SNAPSHOT", "1.0.0.dev0"),
        ("1.2.3rc1", "1.2.3rc1"),
    ],
)
def test_cli_spelling(plugin: str, cli: str) -> None:
    assert build_cli.cli_spelling(plugin) == cli


def test_a_release_version_is_written_alike_in_both(tree: Path) -> None:
    result = set_version(tree, "0.14.0")
    assert result.returncode == 0, result.stderr
    assert (
        result.stdout.strip() == "set_version.py: package.json 0.14.0, the CLI's __version__ 0.14.0"
    )
    package = json.loads((tree / "package.json").read_text())
    assert package["version"] == "0.14.0"
    assert (tree / INIT).read_text() == INIT_TEXT.replace("0.13.2", "0.14.0")


def test_a_snapshot_is_dev0_in_the_cli(tree: Path) -> None:
    result = set_version(tree, "0.14.0-SNAPSHOT")
    assert result.returncode == 0, result.stderr
    assert (
        result.stdout.strip()
        == "set_version.py: package.json 0.14.0-SNAPSHOT, the CLI's __version__ 0.14.0.dev0"
    )
    assert json.loads((tree / "package.json").read_text())["version"] == "0.14.0-SNAPSHOT"
    assert (tree / INIT).read_text() == INIT_TEXT.replace("0.13.2", "0.14.0.dev0")
    # What it wrote is what build_cli.py accepts.
    assert build_cli.cli_version(tree) == build_cli.cli_spelling(build_cli.plugin_version(tree))


def test_the_version_is_the_only_change_to_package_json(tree: Path) -> None:
    before = (tree / "package.json").read_text()
    assert set_version(tree, "0.14.0-SNAPSHOT").returncode == 0
    after = (tree / "package.json").read_text()
    assert after == before.replace('"version": "0.13.2"', '"version": "0.14.0-SNAPSHOT"')
    assert "café" in after and after.endswith("\n")


@pytest.mark.parametrize(
    "version",
    [
        "0.14",
        "0.14.0.1",
        "v0.14.0",
        "0.14.0-snapshot",
        "0.14.0.dev0",
        "0.14.0-SNAPSHOT1",
        "01.2.3",
        "dev",
        "",
    ],
)
def test_any_other_shape_is_refused_and_nothing_written(tree: Path, version: str) -> None:
    before = ((tree / "package.json").read_text(), (tree / INIT).read_text())
    result = set_version(tree, version)
    assert result.returncode == 1
    assert result.stderr.strip() == f"set_version.py: {version!r} is not X.Y.Z or X.Y.Z-SNAPSHOT"
    assert ((tree / "package.json").read_text(), (tree / INIT).read_text()) == before


def test_a_package_json_without_a_version_is_refused(tree: Path) -> None:
    (tree / "package.json").write_text('{"name": "x"}\n')
    result = set_version(tree, "0.14.0")
    assert result.returncode == 1
    assert "package.json has no version" in result.stderr
    assert (tree / INIT).read_text() == INIT_TEXT


def test_an_init_without_a_version_is_refused(tree: Path) -> None:
    (tree / INIT).write_text("x = 1\n")
    result = set_version(tree, "0.14.0")
    assert result.returncode == 1
    assert "no __version__" in result.stderr
    assert json.loads((tree / "package.json").read_text())["version"] == "0.13.2"


def test_the_repo_s_two_spellings_agree() -> None:
    # Hard rule 8 as the scripts see it: the real tree builds.
    assert build_cli.cli_version(ROOT) == build_cli.cli_spelling(build_cli.plugin_version(ROOT))


def test_the_real_package_json_has_the_shape_the_script_rewrites() -> None:
    # set_version.py rewrites package.json whole with json.dumps(indent=2);
    # as long as the file keeps that shape, a bump changes the version line
    # and nothing else. A reformat (prettier, say) would show up here first.
    text = (ROOT / "package.json").read_text(encoding="utf-8")
    assert json.dumps(json.loads(text), indent=2, ensure_ascii=False) + "\n" == text
