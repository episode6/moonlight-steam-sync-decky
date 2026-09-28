"""The backend's staging (update spec 3.12.3 / 3.12.6): stage_update,
cancel_update, unload, the startup cleanup and cli_version's build.

Downloads come from a ``file://`` tree in ``tmp_path`` (a ``Source`` with
``allow_file``), through the real ``fetch.py`` run by ``sys.executable``;
nothing connects anywhere (``no_network``).
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import stat
import sys
import threading
import time
from pathlib import Path

import pytest

from conftest import run
from moonlight_sync import updates
from moonlight_sync.backend import FETCH_SCRIPT, KeyFetch, RunState, UpdateJob
from updatezip import branch_build, build_zip

pytestmark = pytest.mark.usefixtures("no_network")

TAG = "v0.12.0"
VERSION = "0.12.0"
BRANCH_TAG = "build-main"


class Releases:
    """``<tmp>/releases/<tag>/Moonlight-Sync.zip`` (+ ``.sha256``)."""

    def __init__(self, root: Path) -> None:
        self.root = root
        root.mkdir(parents=True, exist_ok=True)

    def source(self) -> updates.Source:
        return updates.Source(download_base=self.root.as_uri(), allow_file=True)

    def publish(self, tag: str, *, sidecar: str | None | bool = True, **zip_kwargs) -> str:
        folder = self.root / tag
        folder.mkdir(parents=True, exist_ok=True)
        path = build_zip(folder / updates.ASSET, **zip_kwargs)
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        if sidecar is True:
            (folder / updates.ASSET_SHA).write_text(f"{digest}  {updates.ASSET}\n")
        elif isinstance(sidecar, str):
            (folder / updates.ASSET_SHA).write_text(sidecar)
        return digest


@pytest.fixture
def releases(tmp_path) -> Releases:
    return Releases(tmp_path / "releases")


@pytest.fixture
def runtime(tmp_path) -> Path:
    # A space in it, as in ~/homebrew/data/Moonlight Sync.
    return tmp_path / "data" / "Moonlight Sync"


@pytest.fixture
def stager(make_backend, releases, runtime):
    def factory(**kwargs):
        options = dict(
            update_source=releases.source(),
            runtime_dir=str(runtime),
            python=sys.executable,
        )
        options.update(kwargs)
        return make_backend(**options)

    return factory


def staged_files(runtime: Path) -> list[str]:
    folder = runtime / "update" / "staged"
    return sorted(os.listdir(folder)) if folder.exists() else []


# ---------------------------------------------------------------------------
# end to end


def test_stage_a_release_end_to_end(stager, releases, runtime) -> None:
    digest = releases.publish(TAG, version=VERSION)
    backend = stager()
    result = run(backend.stage_update(TAG, digest.upper(), VERSION, None))
    path = updates.staged_path(str(runtime), digest)
    assert result == {
        "ok": True,
        "artifact": "file://" + path,
        "hash": digest,
        "build": None,
        "version": VERSION,
    }
    assert " " in result["artifact"]  # raw, never URL-encoded (spec 2.3)
    assert hashlib.sha256(Path(path).read_bytes()).hexdigest() == digest
    assert staged_files(runtime) == [os.path.basename(path)]  # no sidecar, no part
    for folder in (runtime / "update", runtime / "update" / "staged"):
        assert stat.S_IMODE(folder.stat().st_mode) == 0o700
    assert backend._update is None
    log = (Path(backend.log_dir) / "moonlight-sync.log").read_text()
    assert f"stage_update {TAG}: staged" in log and digest[:12] in log


def test_stage_a_branch_build_end_to_end(stager, releases, runtime) -> None:
    digest = releases.publish(BRANCH_TAG, version="0.11.0", build=branch_build("main"))
    result = run(stager().stage_update(BRANCH_TAG, digest, None, "main"))
    assert result["ok"] is True
    assert result["version"] == "0.11.0"
    assert result["build"]["kind"] == "branch" and result["build"]["ref"] == "main"
    assert result["artifact"] == "file://" + updates.staged_path(str(runtime), digest)


def test_the_argv_is_isolated_python_and_the_script_beside_the_backend(
    stager, releases, monkeypatch
) -> None:
    digest = releases.publish(TAG, version=VERSION)
    backend = stager()
    seen: list[tuple] = []
    real = asyncio.create_subprocess_exec

    async def spy(*argv, **kwargs):
        seen.append((argv, kwargs))
        return await real(*argv, **kwargs)

    monkeypatch.setattr(asyncio, "create_subprocess_exec", spy)
    assert run(backend.stage_update(TAG, digest, VERSION, None))["ok"] is True
    assert len(seen) == 2  # the sidecar, then the zip
    for argv, kwargs in seen:
        assert argv[:3] == (sys.executable, "-I", FETCH_SCRIPT)
        assert os.path.dirname(FETCH_SCRIPT) == os.path.dirname(updates.__file__)
        assert argv[-3] == "--" and "--allow-file" in argv
        assert kwargs["env"]["HOME"] == backend.home  # _child_env()
        assert kwargs["cwd"] == backend.home
        assert kwargs["stderr"] == asyncio.subprocess.DEVNULL
    sidecar_argv, zip_argv = seen[0][0], seen[1][0]
    assert "--sha256" not in sidecar_argv
    assert sidecar_argv[sidecar_argv.index("--max-bytes") + 1] == str(updates.SIDECAR_MAX_BYTES)
    assert zip_argv[zip_argv.index("--sha256") + 1] == digest
    assert zip_argv[zip_argv.index("--max-bytes") + 1] == str(updates.ZIP_MAX_BYTES)
    assert zip_argv[zip_argv.index("--timeout") + 1] == str(updates.DOWNLOAD_TIMEOUT_S)


def test_allow_file_is_passed_only_by_the_source(make_backend, runtime) -> None:
    backend = make_backend(runtime_dir=str(runtime))
    assert backend.update_source == updates.Source()
    assert backend.update_source.allow_file is False
    assert backend.update_source.download_base.startswith("https://github.com/")


def test_stage_update_leaves_the_plugin_directory_byte_identical(stager, releases) -> None:
    digest = releases.publish(TAG, version=VERSION)
    backend = stager()
    plugin = Path(backend.plugin_dir)
    (plugin / "bin").mkdir(parents=True, exist_ok=True)
    (plugin / "package.json").write_text('{"version": "0.11.0"}\n')
    (plugin / "bin" / "moonlight-steam-sync.pyz").write_bytes(b"PK zipapp")

    def tree() -> dict[str, tuple[int, bytes | None]]:
        return {
            str(p.relative_to(plugin)): (p.lstat().st_mode, None if p.is_dir() else p.read_bytes())
            for p in sorted(plugin.rglob("*"))
        }

    before = tree()
    assert run(backend.stage_update(TAG, digest, VERSION, None))["ok"] is True
    assert tree() == before


# ---------------------------------------------------------------------------
# step 1: bad-request, with nothing touched and nothing spawned


GOOD = "ab" * 32


@pytest.mark.parametrize(
    "args",
    [
        (None, GOOD, VERSION, None),
        ("", GOOD, VERSION, None),
        ("..", GOOD, VERSION, None),
        ("v1/../x", GOOD, VERSION, None),
        ("v1\n", GOOD, VERSION, None),
        (True, GOOD, VERSION, None),
        (12, GOOD, VERSION, None),
        (TAG, None, VERSION, None),
        (TAG, "ab" * 31, VERSION, None),
        (TAG, "zz" * 32, VERSION, None),
        (TAG, True, VERSION, None),
        (TAG, 0, VERSION, None),
        (TAG, GOOD, None, None),
        (TAG, GOOD, VERSION, "main"),
        (TAG, GOOD, "dev", None),
        (TAG, GOOD, "", None),
        (TAG, GOOD, True, None),
        (TAG, GOOD, 12, None),
        (TAG, GOOD, "1.2.3" + "x" * 100, None),
        (TAG, GOOD, None, "a+b"),
        (TAG, GOOD, None, ""),
        (TAG, GOOD, None, True),
        (TAG, GOOD, None, ["main"]),
    ],
)
def test_bad_request(stager, runtime, monkeypatch, args) -> None:
    backend = stager()

    async def no_spawn(*argv, **kwargs):
        raise AssertionError("spawned for a bad request")

    monkeypatch.setattr(asyncio, "create_subprocess_exec", no_spawn)
    result = run(backend.stage_update(*args))
    assert result["ok"] is False and result["error"] == "bad-request"
    assert not (runtime / "update").exists()
    assert backend._update is None


# ---------------------------------------------------------------------------
# steps 3 to 6


def test_an_already_staged_file_is_not_downloaded_again(stager, releases, runtime) -> None:
    digest = releases.publish(TAG, version=VERSION)
    backend = stager()
    assert run(backend.stage_update(TAG, digest, VERSION, None))["ok"] is True
    (releases.root / TAG / updates.ASSET).unlink()  # a download would now fail
    again = run(backend.stage_update(TAG, digest, VERSION, None))
    assert again["ok"] is True
    log = (Path(backend.log_dir) / "moonlight-sync.log").read_text()
    assert "already staged, not downloaded again" in log


def test_a_staged_file_that_does_not_hash_to_its_name_is_downloaded_again(
    stager, releases, runtime
) -> None:
    digest = releases.publish(TAG, version=VERSION)
    backend = stager()
    path = Path(updates.staged_path(str(runtime), digest))
    path.parent.mkdir(parents=True)
    path.write_bytes(b"tampered")
    assert run(backend.stage_update(TAG, digest, VERSION, None))["ok"] is True
    assert hashlib.sha256(path.read_bytes()).hexdigest() == digest


def test_an_already_staged_file_is_validated_again(stager, releases, runtime) -> None:
    """A staged file of the right hash is still judged for this request: a
    release's zip is not a build of `main`."""
    digest = releases.publish(TAG, version=VERSION)
    backend = stager()
    assert run(backend.stage_update(TAG, digest, VERSION, None))["ok"] is True
    result = run(backend.stage_update(TAG, digest, None, "main"))
    assert result["error"] == "bad-zip"
    assert staged_files(runtime) == []


def test_a_symlink_at_the_staged_path_is_removed_not_followed(
    stager, releases, runtime, tmp_path
) -> None:
    digest = releases.publish(TAG, version=VERSION)
    victim = tmp_path / "victim"
    victim.write_bytes(b"keep me")
    path = Path(updates.staged_path(str(runtime), digest))
    path.parent.mkdir(parents=True)
    os.symlink(victim, path)
    assert run(stager().stage_update(TAG, digest, VERSION, None))["ok"] is True
    assert victim.read_bytes() == b"keep me"
    assert not path.is_symlink()


def test_a_sidecar_that_disagrees_for_a_version(stager, releases, runtime) -> None:
    digest = releases.publish(TAG, version=VERSION, sidecar=f"{'cd' * 32}  x\n")
    result = run(stager().stage_update(TAG, digest, VERSION, None))
    assert result == {
        "ok": False,
        "error": "bad-release",
        "message": "the release's checksums disagree",
    }
    assert staged_files(runtime) == []


def test_a_sidecar_that_disagrees_for_a_ref(stager, releases, runtime) -> None:
    digest = releases.publish(
        BRANCH_TAG, version="0.11.0", build=branch_build("main"), sidecar=f"{'cd' * 32}\n"
    )
    result = run(stager().stage_update(BRANCH_TAG, digest, None, "main"))
    assert result == {
        "ok": False,
        "error": "bad-release",
        "message": "A new build is being published. Try again in a minute",
    }


def test_a_missing_sidecar(stager, releases, runtime) -> None:
    digest = releases.publish(TAG, version=VERSION, sidecar=None)
    result = run(stager().stage_update(TAG, digest, VERSION, None))
    assert result["error"] == "bad-release"
    assert staged_files(runtime) == []


@pytest.mark.parametrize("text", ["", "not a hash\n", "x" * 5000])
def test_a_sidecar_that_does_not_parse(stager, releases, runtime, text) -> None:
    digest = releases.publish(TAG, version=VERSION, sidecar=text)
    result = run(stager().stage_update(TAG, digest, VERSION, None))
    assert result["error"] == "bad-release"
    assert staged_files(runtime) == []


def test_a_missing_zip_is_bad_release(stager, releases, runtime) -> None:
    digest = releases.publish(TAG, version=VERSION)
    (releases.root / TAG / updates.ASSET).unlink()
    result = run(stager().stage_update(TAG, digest, VERSION, None))
    assert result == {"ok": False, "error": "bad-release", "message": "The release has no zip"}
    assert staged_files(runtime) == []


def test_a_zip_that_is_not_the_hash_is_hash_mismatch(stager, releases, runtime) -> None:
    digest = releases.publish(TAG, version=VERSION)
    (releases.root / TAG / updates.ASSET).write_bytes(b"replaced since")
    result = run(stager().stage_update(TAG, digest, VERSION, None))
    assert result["error"] == "hash-mismatch"
    assert staged_files(runtime) == []


def test_a_zip_over_the_limit_is_bad_zip(stager, releases, runtime, monkeypatch) -> None:
    digest = releases.publish(TAG, version=VERSION)
    monkeypatch.setattr(updates, "ZIP_MAX_BYTES", 100)
    result = run(stager().stage_update(TAG, digest, VERSION, None))
    assert result["error"] == "bad-zip"
    assert staged_files(runtime) == []


def test_a_zip_that_fails_validation_is_removed(stager, releases, runtime) -> None:
    digest = releases.publish(TAG, version=VERSION, flags=["root"])
    result = run(stager().stage_update(TAG, digest, VERSION, None))
    assert result == {"ok": False, "error": "bad-zip", "message": "plugin.json asks for root"}
    assert staged_files(runtime) == []


def test_a_release_whose_zip_is_another_version(stager, releases, runtime) -> None:
    digest = releases.publish(TAG, version="0.12.1")
    result = run(stager().stage_update(TAG, digest, VERSION, None))
    assert result["error"] == "bad-zip"
    assert "0.12.1" in result["message"]


def test_the_downloader_s_own_report_is_checked(stager, releases, runtime, monkeypatch) -> None:
    """A downloader that says ok for bytes of another hash is not trusted."""
    digest = releases.publish(TAG, version=VERSION)
    backend = stager()
    real = backend._fetch

    async def lying(url, dest, **kwargs):
        answer = await real(url, dest, **kwargs)
        if kwargs.get("sha256") is not None:
            answer = {**answer, "sha256": "ef" * 32}
        return answer

    monkeypatch.setattr(backend, "_fetch", lying)
    result = run(backend.stage_update(TAG, digest, VERSION, None))
    assert result["error"] == "hash-mismatch"
    assert staged_files(runtime) == []


# ---------------------------------------------------------------------------
# _fetch: what the backend makes of the downloader's answer


def fake_python(tmp_path: Path, body: str) -> str:
    """A 'python3' that runs ``body`` (Python) instead of the downloader."""
    script = tmp_path / "fake-python"
    script.write_text(f"#!{sys.executable}\nimport os, sys, time\n{body}\n")
    script.chmod(0o755)
    return str(script)


@pytest.mark.parametrize(
    "body",
    [
        "pass",
        "print('not json')",
        "print('[1, 2]')",
        'print(\'{"ok": "yes"}\')',
        "print('{\"no_ok\": true}')",
        "sys.stdout.write('x' * 200000)",
        "sys.stdout.buffer.write(b'\\xff\\xfe\\n')",
    ],
)
def test_a_downloader_that_does_not_answer_is_io(stager, tmp_path, body) -> None:
    backend = stager(python=fake_python(tmp_path, body))
    answer = run(backend._fetch("https://github.com/x", str(tmp_path / "d"), max_bytes=10))
    assert answer == {"ok": False, "error": "io", "message": "the downloader did not answer"}
    assert backend._procs == set()


def test_a_downloader_that_hangs_is_killed(stager, tmp_path, monkeypatch) -> None:
    backend = stager(python=fake_python(tmp_path, "time.sleep(60)"))
    monkeypatch.setattr(type(backend), "FETCH_ANSWER_GRACE", 0.2)
    started = time.monotonic()
    answer = run(
        backend._fetch("https://github.com/x", str(tmp_path / "d"), max_bytes=10, timeout=0.1)
    )
    assert time.monotonic() - started < 10
    assert answer["error"] == "io"
    assert backend._procs == set()


def test_a_failed_staging_answers_io_for_a_silent_downloader(stager, releases, tmp_path) -> None:
    digest = releases.publish(TAG, version=VERSION)
    backend = stager(python=fake_python(tmp_path, "pass"))
    result = run(backend.stage_update(TAG, digest, VERSION, None))
    assert result["error"] == "io"
    assert backend._update is None


# ---------------------------------------------------------------------------
# step 2: busy, and the guard released on every exit


def test_busy_from_a_run(stager, releases, runtime) -> None:
    backend = stager()
    backend._run = RunState(kind="sync", opts={}, started="now")
    result = run(backend.stage_update(TAG, GOOD, VERSION, None))
    assert (result["error"], result["kind"]) == ("busy", "sync")
    assert not (runtime / "update").exists()


def test_busy_from_a_match(stager, runtime) -> None:
    backend = stager()
    backend._matching = 1
    result = run(backend.stage_update(TAG, GOOD, VERSION, None))
    assert (result["error"], result["kind"]) == ("busy", "match")
    assert not (runtime / "update").exists()


def test_busy_from_a_key_fetch(stager, runtime) -> None:
    backend = stager()
    backend._key_fetch = KeyFetch(stop=threading.Event(), started="now")
    result = run(backend.stage_update(TAG, GOOD, VERSION, None))
    assert (result["error"], result["kind"]) == ("busy", "key")
    assert not (runtime / "update").exists()


def test_busy_from_another_staging(stager, runtime) -> None:
    backend = stager()
    other = UpdateJob(started="now")
    backend._update = other
    result = run(backend.stage_update(TAG, GOOD, VERSION, None))
    assert result == {
        "ok": False,
        "error": "busy",
        "message": "An update is already being downloaded",
        "kind": "update",
    }
    assert backend._update is other  # not released by the refused call
    assert not (runtime / "update").exists()


def test_the_guard_is_released_after_an_exception(stager, releases, monkeypatch) -> None:
    digest = releases.publish(TAG, version=VERSION)
    backend = stager()

    def boom(*args, **kwargs):
        raise RuntimeError("unexpected")

    monkeypatch.setattr(updates, "validate_zip", boom)
    result = run(backend.stage_update(TAG, digest, VERSION, None))
    assert result["ok"] is False
    assert backend._update is None
    monkeypatch.undo()
    assert run(backend.stage_update(TAG, digest, VERSION, None))["ok"] is True


def test_the_guard_is_released_after_a_failure(stager, releases) -> None:
    digest = releases.publish(TAG, version=VERSION, sidecar=None)
    backend = stager()
    assert run(backend.stage_update(TAG, digest, VERSION, None))["ok"] is False
    assert backend._update is None


CUT_SHORT_ZIP = """
argv = sys.argv[1:]
if argv[-1].endswith('.zip'):
    # What fetch.py answers for a body cut short (an IncompleteRead).
    print('{"ok": false, "error": "network", "status": null, "message": '
          '"reading https://objects.githubusercontent.com/x: IncompleteRead"}')
    sys.exit(0)
os.execv(sys.executable, [sys.executable] + argv)
"""


def test_a_download_cut_short_is_network(stager, releases, runtime, tmp_path) -> None:
    digest = releases.publish(TAG, version=VERSION)
    backend = stager(python=fake_python(tmp_path, CUT_SHORT_ZIP))
    result = run(backend.stage_update(TAG, digest, VERSION, None))
    assert result == {
        "ok": False,
        "error": "network",
        "message": "reading https://objects.githubusercontent.com/x: IncompleteRead",
    }
    assert staged_files(runtime) == []
    assert backend._update is None


# ---------------------------------------------------------------------------
# cancel_update and unload


SLOW_ZIP = """
argv = sys.argv[1:]
dest = argv[-1]
if dest.endswith('.zip'):
    with open(dest + '.part', 'wb') as handle:
        handle.write(b'half a download')
    with open(os.environ['SLOW_PIDFILE'], 'w') as handle:
        handle.write(str(os.getpid()))
    time.sleep(60)
os.execv(sys.executable, [sys.executable] + argv)
"""


def slow_backend(stager, tmp_path, releases):
    digest = releases.publish(TAG, version=VERSION)
    pidfile = tmp_path / "slow.pid"
    backend = stager(python=fake_python(tmp_path, SLOW_ZIP), env={"SLOW_PIDFILE": str(pidfile)})
    return backend, digest, pidfile


async def until(predicate, limit: float = 20.0) -> None:
    deadline = time.monotonic() + limit
    while not predicate():
        assert time.monotonic() < deadline, "timed out waiting"
        await asyncio.sleep(0.02)


def test_cancel_update(stager, releases, runtime, tmp_path) -> None:
    backend, digest, pidfile = slow_backend(stager, tmp_path, releases)
    part = updates.staged_path(str(runtime), digest) + ".part"

    async def scenario():
        task = asyncio.ensure_future(backend.stage_update(TAG, digest, VERSION, None))
        await until(lambda: pidfile.exists() and os.path.exists(part))
        proc = backend._update.proc
        cancelled = await backend.cancel_update()
        result = await task
        return cancelled, result, proc

    cancelled, result, proc = run(scenario())
    assert cancelled == {"ok": True, "running": True}
    assert result == {"ok": False, "error": "cancelled", "message": "The download was cancelled"}
    assert proc.returncode is not None
    assert not os.path.exists(part)
    assert staged_files(runtime) == []
    assert backend._update is None and backend._procs == set()
    assert run(backend.cancel_update()) == {"ok": True, "running": False}


def test_unload_kills_the_downloader(stager, releases, runtime, tmp_path) -> None:
    backend, digest, pidfile = slow_backend(stager, tmp_path, releases)
    part = updates.staged_path(str(runtime), digest) + ".part"

    async def scenario():
        task = asyncio.ensure_future(backend.stage_update(TAG, digest, VERSION, None))
        await until(lambda: pidfile.exists() and os.path.exists(part))
        proc = backend._update.proc
        await backend.unload()
        part_after_unload = os.path.exists(part)
        result = await task
        return proc, part_after_unload, result

    proc, part_after_unload, result = run(scenario())
    assert proc.returncode is not None
    assert part_after_unload is False
    assert result["error"] == "cancelled"
    assert backend._update is None


# ---------------------------------------------------------------------------
# startup, cli_version


def test_cleanup_at_startup(make_backend, runtime) -> None:
    folder = runtime / "update" / "staged"
    folder.mkdir(parents=True)
    old, fresh, part = folder / "old.zip", folder / "fresh.zip", folder / "fresh.zip.part"
    for path in (old, fresh, part):
        path.write_bytes(b"x")
    os.utime(old, (time.time() - updates.STAGED_KEEP_S - 60,) * 2)
    make_backend(runtime_dir=str(runtime))
    assert sorted(os.listdir(folder)) == ["fresh.zip"]


def test_startup_creates_nothing_in_the_runtime_directory(make_backend, runtime) -> None:
    make_backend(runtime_dir=str(runtime))
    assert not runtime.exists()


def test_cli_version_carries_build(make_backend, tmp_path) -> None:
    backend = make_backend()
    assert run(backend.cli_version())["build"] is None
    plugin = Path(backend.plugin_dir)
    plugin.mkdir(parents=True, exist_ok=True)
    (plugin / "build.json").write_text(json.dumps(branch_build("main")))
    assert run(backend.cli_version())["build"] == branch_build("main")
    (plugin / "build.json").write_text('{"schema": 9}')
    assert run(backend.cli_version())["build"] is None
