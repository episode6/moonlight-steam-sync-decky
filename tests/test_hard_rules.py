"""Mechanical checks for the hard rules in AGENTS.md that a grep can prove."""

from __future__ import annotations

import ast
import asyncio
import json
import os
import re
import subprocess
import sys

from conftest import ROOT, run
from moonlight_sync import sgdbpage, updates
from moonlight_sync.keys import key_file_path

FORBIDDEN_CALLS = (
    "AddShortcut",
    "RemoveShortcut",
    "SetShortcutName",
    "SetAppLaunchOptions",
    "SetAppHiddenState",
    "SetCustomArtworkForApp",
)


def source_files():
    for pattern in ("src/**/*.ts", "src/**/*.tsx"):
        yield from ROOT.glob(pattern)


def test_plugin_json_has_no_root_flag() -> None:
    meta = json.loads((ROOT / "plugin.json").read_text())
    assert meta["name"] == "Moonlight Sync"
    assert meta["flags"] == []


def test_frontend_never_calls_the_live_shortcut_apis() -> None:
    call = re.compile(r"\.(" + "|".join(FORBIDDEN_CALLS) + r")\s*\(")
    offenders = [
        f"{path.relative_to(ROOT)}:{number}"
        for path in source_files()
        for number, line in enumerate(path.read_text().splitlines(), 1)
        if call.search(line)
    ]
    assert offenders == []


def test_the_client_library_is_only_touched_in_steam_ts() -> None:
    """Spec 3.15's one exception: hidden state and the fallback Streaming
    collection, through collectionStore, in `libraryPort()` and nowhere
    else. Calls only (`.Name`): `tabs.ts`'s synthetic collection *defines*
    an `AsDragDropCollection` of its own, which is no write."""
    call = re.compile(r"\.(SetAppsAsHidden|NewUnsavedCollection|AsDragDropCollection)\b")
    users = {
        str(path.relative_to(ROOT))
        for path in source_files()
        if not path.name.endswith(".test.ts") and call.search(path.read_text())
    }
    assert users == {"src/lib/steam.ts"}


def files_naming(text: str) -> set[str]:
    """Every file under src/ whose text contains `text`, comments and tests included."""
    return {str(path.relative_to(ROOT)) for path in source_files() if text in path.read_text()}


def test_the_plugin_never_names_decky_s_confirmation() -> None:
    """Hard rule 12: the confirmation is the user's, in Decky's dialog, so the
    route that answers it is spelled nowhere in the frontend."""
    assert files_naming("confirm_plugin_install") == set()


def test_decky_s_globals_are_only_touched_in_decky_ts() -> None:
    """Hard rule 12: `src/lib/decky.ts` is the only place that touches Decky's
    globals (its router and its install route)."""
    allowed = {"src/lib/decky.ts", "src/lib/decky.test.ts"}
    assert files_naming("DeckyBackend") == allowed
    assert files_naming("utilities/") == allowed


def test_the_releases_api_is_only_named_in_updates_ts() -> None:
    assert files_naming("api.github.com") == {"src/lib/updates.ts", "src/lib/updates.test.ts"}


def test_the_no_cors_fetch_is_only_wired_in_instance_tsx() -> None:
    """The updater's one request goes through `NetPort`; `instance.tsx` is the
    one place that wires it to the loader's fetch, so `src/lib` stays pure."""
    assert files_naming("fetchNoCors") == {"src/instance.tsx"}


def test_the_repository_is_spelled_only_in_the_updater_and_its_allowlist() -> None:
    """Update spec 3.4 / 3.5: `REPO` in `updates.ts` and the allowlist's own
    literal in `decky.ts` (plus their tests), so a download URL cannot be
    built anywhere else."""
    assert files_naming("episode6/moonlight-steam-sync-decky") == {
        "src/lib/updates.ts",
        "src/lib/updates.test.ts",
        "src/lib/decky.ts",
        "src/lib/decky.test.ts",
    }


def test_the_ref_and_tag_patterns_are_spelled_alike_in_both_halves() -> None:
    """Update spec 3.12.4: ``update_channel``'s ref is checked by the backend
    (``updates.REF_RE``) and read by the frontend (``updates.ts``'s
    ``REF_RE``), and a tag is checked by both before it reaches a URL; the
    two spellings must accept the same strings."""
    source = (ROOT / "src" / "lib" / "updates.ts").read_text()
    for name, python in (("REF_RE", updates.REF_RE), ("TAG_RE", updates.TAG_RE)):
        found = re.findall(rf"^export const {name} = /(.+)/;$", source, re.MULTILINE)
        assert found == [python], name


def test_backend_never_names_config_toml_for_writing() -> None:
    """keys.py reads config.toml with tomllib; nothing opens it for writing."""
    for path in (ROOT / "py_modules").rglob("*.py"):
        text = path.read_text()
        assert not re.search(r"open\([^)]*config[^)]*['\"]w", text), path


#: The key in tests/fixtures/sgdb/api.html. Spelled here and in the fixtures
#: only (the test below proves it), so a grep for it over tests/ is the
#: proof that nothing else in the suite carries it.
PLACEHOLDER_KEY = "0123456789abcdef0123456789abcdef"


def test_the_placeholder_key_is_spelled_only_in_the_fixtures_and_here() -> None:
    carriers = {
        str(path.relative_to(ROOT))
        for path in (ROOT / "tests").rglob("*")
        if path.is_file()
        and "__pycache__" not in path.parts
        and PLACEHOLDER_KEY in path.read_text(errors="replace")
    }
    assert carriers == {"tests/fixtures/sgdb/api.html", "tests/test_hard_rules.py"}


def test_the_fetched_key_never_appears_in_an_event_or_a_log_line(
    backend, fake_browser, monkeypatch
) -> None:
    """Hard rule 4 over the browser fetch (spec 3.20.3): the key crosses the
    debugger socket into keys.py and nothing else -- not a callable result,
    an sgdb_key_event, the sgdb_key_done, a log line or sync_state --
    carries more than its last four characters."""
    monkeypatch.setattr(sgdbpage, "POLL_INTERVAL_S", 0.01)
    browser = fake_browser()

    async def scenario():
        results = [await backend.start_sgdb_key_fetch()]
        browser.open_page()
        deadline = asyncio.get_running_loop().time() + 5
        while not backend.emitted.of("sgdb_key_done"):
            assert asyncio.get_running_loop().time() < deadline
            await asyncio.sleep(0.01)
        await backend._key_fetch.task
        results.append(await backend.cancel_sgdb_key_fetch())
        results.append(await backend.sgdb_key_state())
        results.append(await backend.sync_state())
        results.append(await backend.log_tail(500))
        return results

    results = run(scenario())
    assert results[2]["source"] == "file" and results[2]["hint"] == PLACEHOLDER_KEY[-4:]
    blob = json.dumps(results) + json.dumps(backend.emitted.calls)
    assert PLACEHOLDER_KEY not in blob
    assert PLACEHOLDER_KEY[:-4] not in blob
    assert backend.emitted.of("sgdb_key_done") == [
        {"ok": True, "source": "file", "hint": PLACEHOLDER_KEY[-4:]}
    ]
    with open(key_file_path(backend.home), encoding="utf-8") as handle:
        assert handle.read() == PLACEHOLDER_KEY + "\n"


def test_one_version_lives_in_package_json_and_the_cli() -> None:
    # Hard rule 8: package.json's "version" is the plugin's and the CLI's;
    # the CLI's __version__ is the one other spelling (build_cli.py refuses
    # a mismatch) and no script or workflow spells it. Anchored, so a
    # third-party pin that happens to share the number (an action's
    # `@2.0.0`, a tool's `==1.2.3`, a longer `10.9.0`) is not the version.
    package = json.loads((ROOT / "package.json").read_text())
    version = package["version"]
    assert "moonlightSteamSync" not in package
    assert package["license"] == "MIT"
    assert "remote_binary" not in package
    init = (ROOT / "cli" / "src" / "moonlight_steam_sync" / "__init__.py").read_text()
    assert f'__version__ = "{version}"' in init
    spelled = re.compile(rf"(?<![\w.@=-])v?{re.escape(version)}(?![\w.])")
    assert spelled.search(f'"{version}"') and spelled.search(f"v{version}")
    assert not spelled.search(f"@{version}") and not spelled.search(f"1{version}")
    for path in (
        ROOT / "backend" / "entrypoint.sh",
        ROOT / "scripts" / "build_cli.py",
        ROOT / "cli" / "install.sh",
        *(ROOT / ".github" / "workflows").glob("*.yml"),
    ):
        assert not spelled.search(path.read_text()), path


def test_the_cli_has_no_runtime_dependencies() -> None:
    # The CLI's own hard rules (cli/AGENTS.md): stdlib only, dependencies = [].
    pyproject = (ROOT / "cli" / "pyproject.toml").read_text()
    assert "dependencies = []" in pyproject
    assert not (ROOT / "cli" / "requirements.txt").exists()


# builds.yml (update spec 3.12.2) has write permission over releases and runs
# on any branch anyone with push access names, so its shape is held here.
# There is no YAML parser among the dev dependencies and this does not add
# one: the checks read the file's lines, which the workflow keeps simple
# (two-space indents, block `run: |` scripts).
WORKFLOWS = ROOT / ".github" / "workflows"
BUILDS = WORKFLOWS / "builds.yml"
SLUG_LINE = 'slug="${BRANCH//[^A-Za-z0-9._-]/-}"; slug="${slug:0:80}"'
TAG_LINE = 'tag="build-${slug}"'
TAG_GUARD = '"$tag" == build-?*'


def top_level_block(lines: list[str], key: str) -> list[str]:
    """The lines under a top-level `key:`, up to the next top-level line."""
    start = lines.index(f"{key}:") + 1
    block = []
    for line in lines[start:]:
        if line and not line.startswith(" "):
            break
        block.append(line)
    return block


def jobs_of(lines: list[str]) -> dict[str, list[str]]:
    """Each job's lines, by its name (the two-space keys under `jobs:`)."""
    jobs: dict[str, list[str]] = {}
    current = None
    for line in top_level_block(lines, "jobs"):
        match = re.fullmatch(r"  ([A-Za-z0-9_-]+):", line)
        if match:
            current = match.group(1)
            jobs[current] = []
        elif current is not None:
            jobs[current].append(line)
    return jobs


def run_scripts(text: str) -> list[str]:
    """Every `run:` script of a workflow, inline or block."""
    scripts = []
    lines = text.splitlines()
    for number, line in enumerate(lines):
        match = re.match(r"(\s*)(?:- )?run:\s*(.*)$", line)
        if not match:
            continue
        indent, rest = len(match.group(1)), match.group(2)
        if rest not in ("|", "|-", ">", ">-"):
            scripts.append(rest)
            continue
        body = []
        for following in lines[number + 1 :]:
            if following.strip() and len(following) - len(following.lstrip()) <= indent:
                break
            body.append(following)
        scripts.append("\n".join(body))
    return scripts


def code_lines(lines: list[str]) -> list[str]:
    return [line for line in lines if not line.lstrip().startswith("#")]


def test_builds_yml_runs_on_push_dispatch_and_delete_only() -> None:
    """Never a pull-request event: code from a fork never reaches a release."""
    lines = BUILDS.read_text().splitlines()
    triggers = [
        match.group(1)
        for line in top_level_block(lines, "on")
        if (match := re.fullmatch(r"  ([A-Za-z_]+):.*", line))
    ]
    assert triggers == ["push", "workflow_dispatch", "delete"]
    assert not any("pull_request" in line for line in code_lines(lines))


def test_builds_yml_writes_releases_from_publish_and_cleanup_only() -> None:
    lines = BUILDS.read_text().splitlines()
    assert [line for line in top_level_block(lines, "permissions") if line.strip()] == [
        "  contents: read"
    ]
    jobs = jobs_of(lines)
    assert set(jobs) == {"gate", "build", "publish", "cleanup"}
    writers = {
        name
        for name, body in jobs.items()
        if any(re.fullmatch(r"\s+contents:\s*write\s*", line) for line in body)
    }
    assert writers == {"publish", "cleanup"}
    assert sum("write" in line for line in code_lines(lines)) == 2
    for name in ("publish", "cleanup"):
        assert "    permissions:\n      contents: write\n" in "\n".join(jobs[name])


def test_no_workflow_writes_an_expression_into_a_script() -> None:
    """A ref, a branch name or an event field reaches a `run:` script through
    `env:` only, never as `${{ }}` text inside it (script injection)."""
    for path in sorted(WORKFLOWS.glob("*.yml")):
        for script in run_scripts(path.read_text()):
            assert "${{" not in script, path.name


def test_builds_yml_spells_the_slug_one_way_and_touches_build_tags_only() -> None:
    """`gate` and `cleanup` each compute the slug with the same line; every
    tag the workflow names is `build-<slug>`, guarded before `gh` runs."""
    text = BUILDS.read_text()
    lines = text.splitlines()
    jobs = jobs_of(lines)
    assert [line.strip() for line in lines if "${BRANCH//" in line] == [SLUG_LINE, SLUG_LINE]
    assert SLUG_LINE in "\n".join(jobs["gate"]) and SLUG_LINE in "\n".join(jobs["cleanup"])
    tag_lines = [line.strip() for line in lines if re.search(r"\btag=", line)]
    assert tag_lines and set(tag_lines) == {TAG_LINE}
    for script in run_scripts(text):
        if TAG_LINE in script:
            guard = script.index(TAG_GUARD)
            assert script.index(TAG_LINE) < guard
            assert "gh " not in script[:guard]
        elif "gh " in script:
            # The two upload steps, after the guarded ones in the same job.
            assert re.findall(r'gh release upload "([^"]*)"', script) == ["build-${SLUG}"]


def test_the_slug_line_and_its_guard() -> None:
    """Spec 3.12.2: every character outside [A-Za-z0-9._-] becomes `-`, cut
    to 80; a slug that makes no valid `build-` tag is refused."""
    guard = next(line.strip() for line in BUILDS.read_text().splitlines() if TAG_GUARD in line)
    script = "\n".join(
        ["set -euo pipefail", SLUG_LINE, TAG_LINE, guard, "  exit 3", "fi", 'echo "$tag"']
    )

    def slug(branch: str) -> tuple[int, str]:
        result = subprocess.run(
            ["bash", "-c", script],
            env={**os.environ, "BRANCH": branch, "LC_ALL": "C.UTF-8"},
            capture_output=True,
            text=True,
            check=False,
        )
        return result.returncode, result.stdout.strip()

    assert slug("main") == (0, "build-main")
    assert slug("self-update/u3-builds") == (0, "build-self-update-u3-builds")
    assert slug("feature+x@y") == (0, "build-feature-x-y")
    assert slug("v1.2.3") == (0, "build-v1.2.3")
    assert slug("a" * 85) == (0, "build-" + "a" * 80)
    # One `-` per character under a UTF-8 locale (the runner's is C.UTF-8).
    assert slug("caf\u00e9") == (0, "build-caf-")
    assert slug("") == (3, "")
    assert slug("a" * 79 + ".x") == (3, "")  # cut to end in "."


def test_builds_yml_scripts_parse() -> None:
    """`bash -n` over every script: CI's shellcheck job lints the repo's .sh
    files, not a workflow's inline scripts."""
    for script in run_scripts(BUILDS.read_text()):
        result = subprocess.run(
            ["bash", "-n", "-c", script], capture_output=True, text=True, check=False
        )
        assert result.returncode == 0, (script, result.stderr)


def test_builds_yml_uploads_build_json_last() -> None:
    """Spec 3.12.3: `--clobber` deletes an asset before it uploads the new
    one, so build.json goes up in a step of its own after the other four."""
    publish = "\n".join(jobs_of(BUILDS.read_text().splitlines())["publish"])
    uploads = [match.start() for match in re.finditer(r"gh release upload", publish)]
    assert len(uploads) == 2
    first, last = publish[uploads[0] : uploads[1]], publish[uploads[1] :]
    for asset in (
        "out/Moonlight-Sync.zip ",
        "out/Moonlight-Sync.zip.sha256",
        "out/moonlight-steam-sync.pyz ",
        "out/moonlight-steam-sync.pyz.sha256",
    ):
        assert asset in first
    assert "build.json" not in first.split("- name:")[0]
    assert "- name: Upload build.json, last" in first
    assert "out/build.json" in last
    assert publish.count("--prerelease --latest=false") == 2
    # Amendment A3: the previous build.json goes before any upload.
    assert 0 <= publish.index("gh release delete-asset") < uploads[0]


def build_json_step(path) -> str:
    """The "Write build.json" step of ci.yml or release.yml, as text."""
    lines = path.read_text().splitlines()
    start = lines.index("      - name: Write build.json")
    end = next(
        number
        for number in range(start + 1, len(lines))
        if lines[number].startswith("      - ") or not lines[number].startswith("      ")
    )
    return "\n".join(lines[start:end]).rstrip()


def test_ci_and_release_write_build_json_with_one_step() -> None:
    step = build_json_step(WORKFLOWS / "ci.yml")
    assert step == build_json_step(WORKFLOWS / "release.yml")
    assert "BUILD_REF: ${{ github.head_ref || github.ref_name }}" in step
    # Amendment A4: a pull request's head commit, not its merge commit.
    assert "BUILD_SHA: ${{ github.event.pull_request.head.sha || github.sha }}" in step
    assert "GITHUB_SHA" not in "\n".join(run_scripts(step))


def run_build_json_step(tmp_path, *, ref: str, ref_type: str = "branch", sha: str = "a" * 40):
    """The step's script in a scratch checkout holding a stale build.json."""
    (tmp_path / "scripts").mkdir(exist_ok=True)
    (tmp_path / "scripts" / "build_info.py").write_bytes(
        (ROOT / "scripts" / "build_info.py").read_bytes()
    )
    (tmp_path / "build.json").write_text('{"stale": true}\n')
    (script,) = run_scripts(build_json_step(WORKFLOWS / "ci.yml"))
    env = {
        **os.environ,
        "BUILD_REF": ref,
        "GITHUB_REF_TYPE": ref_type,
        "BUILD_SHA": sha,
        # What a pull request's GITHUB_SHA names: its merge commit, not written.
        "GITHUB_SHA": "f" * 40,
        "GITHUB_RUN_ID": "42",
        "GITHUB_RUN_ATTEMPT": "1",
    }
    return subprocess.run(
        ["bash", "-c", script], cwd=tmp_path, env=env, capture_output=True, text=True, check=False
    )


def test_the_build_json_step_writes_the_branch(tmp_path) -> None:
    result = run_build_json_step(tmp_path, ref="self-update/u3-builds")
    assert result.returncode == 0, result.stderr
    data = json.loads((tmp_path / "build.json").read_text())
    assert (data["kind"], data["ref"], data["run"]) == ("branch", "self-update/u3-builds", "42/1")
    assert data["sha"] == "a" * 40


def test_the_build_json_step_writes_the_tag(tmp_path) -> None:
    result = run_build_json_step(tmp_path, ref="v1.2.3", ref_type="tag")
    assert result.returncode == 0, result.stderr
    data = json.loads((tmp_path / "build.json").read_text())
    assert (data["kind"], data["ref"]) == ("release", "v1.2.3")


def test_the_build_json_step_skips_an_unusual_branch_name(tmp_path) -> None:
    """Amendment A1: a notice and no build.json, the stale one included, so
    package.py (which packages the file only when it exists) ships none."""
    result = run_build_json_step(tmp_path, ref="feature+x@y")
    assert result.returncode == 0, result.stderr
    assert "::notice::this branch's name cannot be in a build.json" in result.stdout
    assert not (tmp_path / "build.json").exists()


def test_the_build_json_step_fails_on_anything_else(tmp_path) -> None:
    assert run_build_json_step(tmp_path, ref="v1+x", ref_type="tag").returncode == 3
    assert run_build_json_step(tmp_path, ref="main", sha="nope").returncode == 1
    assert run_build_json_step(tmp_path, ref="a+b", sha="nope").returncode == 1


#: `gh` as builds.yml's scripts see it, logging every argv to FAKE_GH_LOG.
#: `release view` answers FAKE_GH_RELEASE (`none`, `fail`, `title=<name>`),
#: or with `--json assets` the names in FAKE_GH_ASSETS; a GET through `api`
#: answers FAKE_GH_REF (`missing` is gh's `HTTP 404`, `exists`, `fail`);
#: every write succeeds.
FAKE_GH = """#!/bin/sh
printf '%s\\n' "$*" >> "$FAKE_GH_LOG"
case "$1" in
  api)
    case " $* " in
      *" --method "*) exit 0 ;;
    esac
    case "${FAKE_GH_REF:-missing}" in
      missing) echo "gh: Not Found (HTTP 404)" >&2; exit 1 ;;
      exists) exit 0 ;;
      *) echo "gh: Server Error (HTTP 500)" >&2; exit 1 ;;
    esac ;;
  release)
    case "$2" in
      view)
        case " $* " in
          *" --json assets "*) printf '%s\\n' ${FAKE_GH_ASSETS:-}; exit 0 ;;
        esac
        case "$FAKE_GH_RELEASE" in
          none) echo "release not found" >&2; exit 1 ;;
          fail) echo "HTTP 502: Bad Gateway" >&2; exit 1 ;;
          title=*) printf '%s\\n' "${FAKE_GH_RELEASE#title=}"; exit 0 ;;
        esac ;;
      create|edit|delete-asset|upload|delete) exit 0 ;;
    esac ;;
esac
echo "unexpected: gh $*" >&2
exit 64
"""


def fake_gh_env(tmp_path, **env: str) -> dict[str, str]:
    """The environment for a script over the fake `gh`, its log emptied."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(exist_ok=True)
    gh = bin_dir / "gh"
    gh.write_text(FAKE_GH)
    gh.chmod(0o755)
    log = tmp_path / "gh.log"
    log.write_text("")
    return {
        **os.environ,
        "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}",
        "LC_ALL": "C.UTF-8",
        "GITHUB_REPOSITORY": "owner/repo",
        "FAKE_GH_LOG": str(log),
        **env,
    }


def run_job(tmp_path, job: str, *, branch: str, release: str, event: str = "push"):
    """`job`'s one script under bash with a fake `gh` answering `release`
    (`none`, `fail` or `title=<name>`): (exit code, outputs, gh calls, stdout)."""
    (script,) = run_scripts("\n".join(jobs_of(BUILDS.read_text().splitlines())[job]))
    output = tmp_path / "output"
    output.write_text("")
    env = fake_gh_env(
        tmp_path,
        BRANCH=branch,
        GITHUB_REF_TYPE="branch",
        GITHUB_REF=f"refs/heads/{branch}",
        GITHUB_EVENT_NAME=event,
        GITHUB_OUTPUT=str(output),
        FAKE_GH_RELEASE=release,
    )
    result = subprocess.run(
        ["bash", "-c", script], cwd=tmp_path, env=env, capture_output=True, text=True, check=False
    )
    outputs = dict(line.split("=", 1) for line in output.read_text().splitlines())
    calls = (tmp_path / "gh.log").read_text().splitlines()
    return result.returncode, outputs, calls, result.stdout


def gate(tmp_path, **kwargs):
    code, outputs, calls, stdout = run_job(tmp_path, "gate", **kwargs)
    assert all(call.startswith("release view build-") for call in calls), calls
    return code, outputs.get("publish"), stdout


def test_the_gate_publishes_main_and_a_branch_s_own_release(tmp_path) -> None:
    assert gate(tmp_path, branch="main", release="none")[:2] == (0, "true")
    assert gate(tmp_path, branch="main", release="title=main")[:2] == (0, "true")
    assert gate(tmp_path, branch="a/b", release="title=a/b")[:2] == (0, "true")
    dispatched = gate(tmp_path, branch="a/b", release="none", event="workflow_dispatch")
    assert dispatched[:2] == (0, "true")
    assert gate(tmp_path, branch="a/b", release="none")[:2] == (0, "false")


def test_the_gate_leaves_another_branch_s_release_alone(tmp_path) -> None:
    """Amendment A2: `a/b` and `a-b` share `build-a-b`; its title says whose."""
    code, publish, stdout = gate(tmp_path, branch="a/b", release="title=a-b")
    assert (code, publish) == (0, "false")
    assert "::notice::build-a-b belongs to the branch 'a-b'" in stdout
    code, publish, stdout = gate(
        tmp_path, branch="a/b", release="title=a-b", event="workflow_dispatch"
    )
    assert (code, publish) == (1, None)
    assert "::error::build-a-b belongs to the branch 'a-b': delete that release" in stdout
    assert gate(tmp_path, branch="main", release="title=other")[:2] == (1, None)
    # The title is text somebody chose: it is shown, never obeyed.
    _, _, stdout = gate(tmp_path, branch="a/b", release="title=x::warning::y")
    assert "branch 'x??warning??y'" in stdout


def test_the_gate_fails_when_github_does_not_answer(tmp_path) -> None:
    assert gate(tmp_path, branch="a/b", release="fail")[:2] == (1, None)
    assert gate(tmp_path, branch="main", release="fail")[:2] == (1, None)


def cleanup(tmp_path, **kwargs):
    code, _, calls, stdout = run_job(tmp_path, "cleanup", event="delete", **kwargs)
    deletes = [call for call in calls if call.startswith("release delete")]
    return code, deletes, stdout


def test_cleanup_deletes_only_the_branch_s_own_release(tmp_path) -> None:
    assert cleanup(tmp_path, branch="a/b", release="title=a/b")[:2] == (
        0,
        ["release delete build-a-b --repo owner/repo --cleanup-tag --yes"],
    )
    assert cleanup(tmp_path, branch="a/b", release="none")[:2] == (0, [])
    code, deletes, stdout = cleanup(tmp_path, branch="a/b", release="title=a-b")
    assert (code, deletes) == (0, [])
    assert "::notice::build-a-b belongs to the branch 'a-b'; left alone" in stdout
    assert cleanup(tmp_path, branch="a/b", release="fail")[:2] == (1, [])


PUBLISH_STEPS = [
    "Move the tag to the commit built",
    "Create or edit the release",
    "Remove the previous build.json",
    "Upload the zip, the CLI and their checksums",
    "Upload build.json, last",
]
SHA = "c0ffee" + "0" * 34


def step_script(job: str, name: str) -> str:
    """The `run:` script of `job`'s step called `name`."""
    lines = jobs_of(BUILDS.read_text().splitlines())[job]
    start = lines.index(f"      - name: {name}")
    end = next(
        (n for n in range(start + 1, len(lines)) if lines[n].startswith("      - ")), len(lines)
    )
    (script,) = run_scripts("\n".join(lines[start:end]))
    return script


def publish(tmp_path, *, release: str, ref: str, assets: str = "", steps=PUBLISH_STEPS):
    """`publish`'s steps in order over the fake `gh`, stopping at the first
    that fails, as the job does: (the failed step or None, gh calls)."""
    env = fake_gh_env(
        tmp_path,
        BRANCH="a/b",
        SLUG="a-b",
        GITHUB_SHA=SHA,
        FAKE_GH_RELEASE=release,
        FAKE_GH_REF=ref,
        FAKE_GH_ASSETS=assets,
    )
    failed = None
    for name in steps:
        result = subprocess.run(
            ["bash", "-c", step_script("publish", name)],
            cwd=tmp_path,
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode != 0:
            failed = name
            break
    calls = (tmp_path / "gh.log").read_text().splitlines()
    for call in calls:
        # Every tag of every call is this branch's.
        assert set(re.findall(r"build-[^\s/]*", call)) == {"build-a-b"}, call
        assert set(re.findall(r"refs/tags/(\S+)", call)) <= {"build-a-b"}, call
    return failed, calls


VIEW = "release view build-a-b --repo owner/repo --json name --jq .name"
GET_REF = "api repos/owner/repo/git/ref/tags/build-a-b --silent"
NOTES = (
    f"--notes Build of `a/b` at `{SHA}`. Untested: installed from Moonlight Sync's Updates page."
)
ASSETS = "release view build-a-b --repo owner/repo --json assets --jq .assets[].name"
UPLOAD_FOUR = (
    "release upload build-a-b --repo owner/repo --clobber "
    "out/Moonlight-Sync.zip out/Moonlight-Sync.zip.sha256 "
    "out/moonlight-steam-sync.pyz out/moonlight-steam-sync.pyz.sha256"
)
UPLOAD_BUILD_JSON = "release upload build-a-b --repo owner/repo --clobber out/build.json"


def test_publish_s_steps_are_these_in_this_order() -> None:
    names = [
        line.strip().removeprefix("- name: ")
        for line in jobs_of(BUILDS.read_text().splitlines())["publish"]
        if line.startswith("      - name: ")
    ]
    assert names == PUBLISH_STEPS


def test_publish_a_first_build(tmp_path) -> None:
    failed, calls = publish(tmp_path, release="none", ref="missing")
    assert failed is None
    assert calls == [
        VIEW,
        GET_REF,
        "api --method POST repos/owner/repo/git/refs "
        f"-f ref=refs/tags/build-a-b -f sha={SHA} --silent",
        VIEW,
        f"release create build-a-b --repo owner/repo --verify-tag --title a/b {NOTES} "
        "--prerelease --latest=false",
        ASSETS,
        UPLOAD_FOUR,
        UPLOAD_BUILD_JSON,
    ]


def test_publish_over_the_branch_s_own_build(tmp_path) -> None:
    failed, calls = publish(
        tmp_path, release="title=a/b", ref="exists", assets="Moonlight-Sync.zip build.json"
    )
    assert failed is None
    assert calls == [
        VIEW,
        GET_REF,
        "api --method PATCH repos/owner/repo/git/refs/tags/build-a-b "
        f"-f sha={SHA} -F force=true --silent",
        VIEW,
        f"release edit build-a-b --repo owner/repo --title a/b {NOTES} --prerelease --latest=false",
        ASSETS,
        "release delete-asset build-a-b build.json --yes --repo owner/repo",
        UPLOAD_FOUR,
        UPLOAD_BUILD_JSON,
    ]


def test_publish_deletes_no_build_json_it_does_not_see(tmp_path) -> None:
    failed, calls = publish(
        tmp_path, release="title=a/b", ref="exists", assets="Moonlight-Sync.zip"
    )
    assert failed is None
    assert not any("delete-asset" in call for call in calls)
    assert calls[-2:] == [UPLOAD_FOUR, UPLOAD_BUILD_JSON]


def test_publish_never_touches_another_branch_s_release(tmp_path) -> None:
    """Amendment A2: a same-slug branch published after the gate ran."""
    failed, calls = publish(tmp_path, release="title=a-b", ref="exists")
    assert (failed, calls) == ("Move the tag to the commit built", [VIEW])
    # Even reached on its own, the create-or-edit step does not retitle it.
    failed, calls = publish(
        tmp_path, release="title=a-b", ref="exists", steps=["Create or edit the release"]
    )
    assert (failed, calls) == ("Create or edit the release", [VIEW])


def test_publish_stops_when_github_does_not_answer(tmp_path) -> None:
    failed, calls = publish(tmp_path, release="none", ref="fail")
    assert (failed, calls) == ("Move the tag to the commit built", [VIEW, GET_REF])
    failed, calls = publish(tmp_path, release="fail", ref="exists")
    assert (failed, calls) == ("Move the tag to the commit built", [VIEW])


def test_publish_flags(tmp_path) -> None:
    """`--verify-tag` on create only; `--prerelease --latest=false` on both."""
    for release, ref in (("none", "missing"), ("title=a/b", "exists")):
        _, calls = publish(tmp_path, release=release, ref=ref)
        for call in calls:
            verb = call.split()[1] if call.startswith("release ") else None
            assert ("--verify-tag" in call) == (verb == "create"), call
            if verb in ("create", "edit"):
                assert call.endswith("--prerelease --latest=false"), call


# The update downloader (update spec 3.12.3): the code that decides which
# bytes Decky later installs as root.
PY_MODULES = ROOT / "py_modules"
FETCH_PY = PY_MODULES / "moonlight_sync" / "fetch.py"


def backend_python_files():
    yield from PY_MODULES.rglob("*.py")
    yield ROOT / "main.py"


def imports_of(path) -> list[tuple[str, int, list[str]]]:
    """``(module, level, names)`` for every import statement in ``path``."""
    found = []
    for node in ast.walk(ast.parse(path.read_text(), str(path))):
        if isinstance(node, ast.Import):
            found.extend((alias.name, 0, []) for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            found.append((node.module or "", node.level, [alias.name for alias in node.names]))
    return found


def test_fetch_py_imports_the_standard_library_only() -> None:
    for module, level, _ in imports_of(FETCH_PY):
        assert level == 0, "fetch.py makes a relative import"
        top = module.split(".")[0]
        assert top != "moonlight_sync"
        assert top == "__future__" or top in sys.stdlib_module_names, module


def test_fetch_py_parses_as_python_3_11() -> None:
    """The system interpreter runs it; the CLI's floor is 3.11."""
    ast.parse(FETCH_PY.read_text(), str(FETCH_PY), feature_version=(3, 11))


def test_nothing_imports_fetch_py() -> None:
    """The backend runs the downloader as a script; it never imports it."""
    for path in backend_python_files():
        for module, _, names in imports_of(path):
            assert module.split(".")[-1] != "fetch", path
            assert "fetch" not in names, path


def test_no_py_module_turns_certificate_verification_off() -> None:
    patterns = (
        re.compile(r"CERT_NONE"),
        re.compile(r"_create_unverified_context"),
        re.compile(r"check_hostname\s*=\s*False"),
        re.compile(r"verify_mode\s*=(?!=)"),
    )
    for path in backend_python_files():
        text = path.read_text()
        for pattern in patterns:
            assert not pattern.search(text), (path, pattern.pattern)


def test_the_download_source_is_a_test_seam_only() -> None:
    """``main.py`` never passes ``update_source`` (so the plugin downloads
    from GitHub only), and nothing in the backend turns ``allow_file`` on."""
    main = (ROOT / "main.py").read_text()
    assert "update_source" not in main and "allow_file" not in main
    for path in PY_MODULES.rglob("*.py"):
        assert not re.search(r"allow_file\s*=\s*True", path.read_text()), path
