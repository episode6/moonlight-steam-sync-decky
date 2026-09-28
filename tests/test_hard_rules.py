"""Mechanical checks for the hard rules in AGENTS.md that a grep can prove."""

from __future__ import annotations

import asyncio
import json
import os
import re
import subprocess

from conftest import ROOT, run
from moonlight_sync import sgdbpage
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
