"""scripts/build_info.py: build.json, what a CI build says about itself
(update spec 3.12.1)."""

from __future__ import annotations

import calendar
import json
import re
import subprocess
import sys
import time
from pathlib import Path

import pytest

from conftest import ROOT

SCRIPT = ROOT / "scripts" / "build_info.py"
SHA = "a1b2c3d4e5f60718293a4b5c6d7e8f9012345678"


def build_info(cwd: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        cwd=cwd,
        capture_output=True,
        text=True,
        check=False,
    )


def valid(**overrides: str) -> list[str]:
    values = {"kind": "branch", "ref": "main", "sha": SHA, "run": "123456/1", **overrides}
    return [part for key, value in values.items() for part in (f"--{key}", value)]


def test_writes_build_json_in_the_current_directory(tmp_path: Path) -> None:
    before = int(time.time())
    result = build_info(tmp_path, *valid())
    after = int(time.time())
    assert result.returncode == 0, result.stderr
    assert result.stderr == ""
    text = (tmp_path / "build.json").read_text()
    data = json.loads(text)
    assert list(data) == ["schema", "kind", "ref", "sha", "built_at", "run"]
    assert data["schema"] == 1
    assert data["kind"] == "branch"
    assert data["ref"] == "main"
    assert data["sha"] == SHA
    assert data["run"] == "123456/1"
    assert re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ", data["built_at"])
    stamp = calendar.timegm(time.strptime(data["built_at"], "%Y-%m-%dT%H:%M:%SZ"))
    assert before <= stamp <= after
    assert text.endswith("\n")
    assert list(tmp_path.iterdir()) == [tmp_path / "build.json"]


def test_a_release_names_its_tag(tmp_path: Path) -> None:
    assert build_info(tmp_path, *valid(kind="release", ref="v1.2.3")).returncode == 0
    data = json.loads((tmp_path / "build.json").read_text())
    assert (data["kind"], data["ref"]) == ("release", "v1.2.3")


def test_out_and_a_branch_with_slashes(tmp_path: Path) -> None:
    target = tmp_path / "somewhere" / "info.json"
    target.parent.mkdir()
    result = build_info(tmp_path, *valid(ref="self-update/u3_builds.v2"), "--out", str(target))
    assert result.returncode == 0, result.stderr
    assert json.loads(target.read_text())["ref"] == "self-update/u3_builds.v2"
    assert not (tmp_path / "build.json").exists()


def test_an_upper_case_sha_is_written_lower_case(tmp_path: Path) -> None:
    assert build_info(tmp_path, *valid(sha=SHA.upper())).returncode == 0
    assert json.loads((tmp_path / "build.json").read_text())["sha"] == SHA


def test_a_hundred_character_ref_is_allowed(tmp_path: Path) -> None:
    assert build_info(tmp_path, *valid(ref="a" * 100)).returncode == 0


@pytest.mark.parametrize(
    ("override", "message"),
    [
        ({"kind": "tag"}, "--kind must be one of release, branch"),
        ({"kind": ""}, "--kind must be one of release, branch"),
        ({"sha": SHA[:-1]}, "--sha must be 40 hex digits"),
        ({"sha": SHA + "0"}, "--sha must be 40 hex digits"),
        ({"sha": SHA[:-1] + "g"}, "--sha must be 40 hex digits"),
        ({"sha": SHA + "\n"}, "--sha must be 40 hex digits"),
        ({"ref": ""}, "--ref must match"),
        ({"ref": "a" * 101}, "--ref must match"),
        ({"ref": "feature+x"}, "--ref must match"),
        ({"ref": "someone@work"}, "--ref must match"),
        ({"ref": "with space"}, "--ref must match"),
        ({"ref": "main\n"}, "--ref must match"),
        ({"ref": "caf\u00e9"}, "--ref must match"),
    ],
)
def test_refuses_a_bad_argument(tmp_path: Path, override: dict[str, str], message: str) -> None:
    result = build_info(tmp_path, *valid(**override))
    assert result.returncode == 1
    assert result.stdout == ""
    lines = result.stderr.splitlines()
    assert len(lines) == 1
    assert lines[0].startswith(f"build_info.py: {message}")
    assert list(tmp_path.iterdir()) == []


def test_a_refusal_leaves_an_existing_file_alone(tmp_path: Path) -> None:
    (tmp_path / "build.json").write_text("old\n")
    assert build_info(tmp_path, *valid(kind="nightly")).returncode == 1
    assert (tmp_path / "build.json").read_text() == "old\n"
