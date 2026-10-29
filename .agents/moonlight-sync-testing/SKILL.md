---
name: moonlight-sync-testing
description: >-
  How the Moonlight Sync plugin is tested without a Steam Deck:
  tests/fake_cli.py and its FAKE_CLI_* env vars, the hand-written NDJSON
  fixtures under tests/fixtures (shared by pytest and vitest through
  src/test/fixtures.ts), tests/conftest.py (backend / make_backend, scenario
  marks), test_main.py, test_hard_rules.py's mechanical checks, the CLI's own
  suite and DEVICE-CHECKLIST.md for on-device checks. Load before writing or
  changing tests, fixtures or the fake CLI, when a test fails for unclear
  reasons, or when deciding what is a unit test versus a device check.
---

# Moonlight Sync off-device test harness

Reference split out of the root `AGENTS.md`, whose hard rules (cited here as
"hard rule N") apply throughout. Related: `moonlight-sync-sgdb-key-fetch`,
`moonlight-sync-updater`, `moonlight-sync-update-staging` and
`moonlight-sync-ci` each hold their own area's test notes.

## Module map: the test tree

```
DEVICE-CHECKLIST.md         every on-device check (PR-0 probes, PR-5/6/7/8 items, §3.14,
                            §3.15 and the §3.16 default layout's [verify] items, then
                            §3.17-§3.20; the key fetch is §14, the panel's launch
                            row and Advanced's layout buttons §15, updating from
                            the plugin §16: V1-V7 of
                            update spec §3.9, via *Install another version* ->
                            reinstall until a newer release exists; the staged
                            hand-off and the channels §17: V8-V10 of update spec
                            §3.12.5, the branch's `build.json` through the
                            loader's fetch and a build made on the device,
                            amendment A5), in order
src/test/fixtures.ts        loads tests/fixtures for vitest
tests/                      pytest: fake_cli.py, fixtures/, conftest.py, test_*.py,
                            test_install_sh.py (install.sh end to end via
                            MOONLIGHT_SYNC_BASE_URL against a file:// fixture,
                            sudo/systemctl/passwd shimmed on PATH, their state in
                            tmp_path/fakestate; the temporary password's every path;
                            a missing Decky Loader's, over a fixture installer),
                            test_cli_install_sh.py
                            (cli/install.sh the same way, HOME in tmp_path);
                            updatezip.py (build_zip(), good and hostile plugin zips,
                            and patch_central() for what zipfile never writes),
                            test_fetch.py, test_updates.py, test_backend_updates.py
                            (the staging, update spec 3.12.6)
```

## The test harness (off-device)

There is no Steam Deck during development; everything else is tested.

- `tests/fake_cli.py` stands in for the CLI. Driven by env vars:
  `FAKE_CLI_FIXTURES` (directories, `os.pathsep`-joined, searched in order),
  `FAKE_CLI_ARGV_LOG`, `FAKE_CLI_VERSION` (< 0.3.0 rejects the new flags
  like argparse: stderr only, exit 2; < 0.4.0 rejects `--hide-host-apps`
  the same way), `FAKE_CLI_ART_COMMIT`,
  `FAKE_CLI_STEAM_GONE_FILE` / `FAKE_CLI_WAIT_S` (the await-exit wait),
  `FAKE_CLI_SIGINT_DURING_WAIT=immediate|deferred`, `FAKE_CLI_SLEEP_MS`,
  `FAKE_CLI_EXIT`, `FAKE_CLI_STDERR`, `FAKE_CLI_NOISE` (a non-JSON stdout
  line), `FAKE_CLI_NOISE_BYTES` (one stdout line of that many bytes),
  `FAKE_CLI_GRANDCHILD_S` / `FAKE_CLI_GRANDCHILD_PIDFILE` (a `sleep`
  grandchild that keeps the pipes open after the fake exits),
  `FAKE_CLI_FIXTURE_<SUB>[_<ACTION>]` (another fixture basename, e.g.
  `FAKE_CLI_FIXTURE_HOST_SHOW=host-none`). A missing fixture exits 99.
  On SIGINT it prints the fixture's summary with `stopped_early` and, unless
  it had already printed `commit written:true`, `added`/`replaced`/`removed`
  zeroed (nothing reached `shortcuts.vdf`; `filled` stands, art files are
  written as the run goes), then `error` exit 130.
- `tests/fixtures/<scenario>/<command>.ndjson` are hand-written from §3.4.6
  (`full-sync`, `art-only`, `nothing-to-do`, `unreachable`, `stopped`,
  `refused`, `common/`); `tests/test_fixtures.py` checks every event's key
  set against the schema. The fixtures are what the CLI says *under
  `--hide-host-apps`*, since the plugin always passes it: `entry.host_app`
  on every `status` entry (with a hidden, published `Desktop` / `Steam Big
  Picture` pair, `Desktop` deliberately matched to a Steam game),
  `kind: "host-app"` apps in `list`, `plan.host_app` and
  `added_by_kind["host-app"]` in every `sync`. `common/` also holds the alternates picked with
  `FAKE_CLI_FIXTURE_MATCH` / `FAKE_CLI_FIXTURE_SEARCH` (`match-none`,
  `match-sgdb`, `match-unknown`, `match-silent`, `search-empty`,
  `search-no-key`). The frontend's `events.test.ts`, `restart.test.ts`,
  `state.test.ts`, `controller.test.ts`, `layouts.test.ts` and
  `__tests__/join.test.ts` read the same files, so the Python and
  TypeScript sides cannot drift. `applyDefault` / `unsetApplied` and the
  Stream press / walk / `setDefaultLayout` run over a scripted `SteamInput`
  (`layouts.test.ts`, `controller.test.ts`, whose fake `record_layout`
  computes `applied` by the backend's table) and `steam.test.ts` drives
  the real seam over stubbed globals; the route patch, the button,
  Advanced's *Layout* and `ClearSelectedConfigForApp` itself are device checks,
  not unit tests. The key fetch's frontend (spec 3.20.4) runs over the
  same fake backend in `controller.test.ts` (an `order` log interleaves
  backend calls, the fake Steam seam's `open:` / `back` navigations and
  toasts, so the step order is asserted), `state.test.ts` holds the
  button's presence per key source (`keyFetchOffered`), and
  `steam.test.ts` the `NavigateToExternalWeb` / `steam://openurl/`
  fallback; the modal, the browser and `NavigateBack` are device checks
  (DEVICE-CHECKLIST §14).
- `tests/conftest.py`: `backend` / `make_backend` (a started Backend over
  the fake; `@pytest.mark.scenario("full-sync")` puts that scenario in front
  of `common/`), `steam_gone`, `install_env` (a `python3` shim that prints
  the first line of the file it runs). Async callables are driven with
  `asyncio.run` (`conftest.run`); a long run is started and awaited inside
  one coroutine (`backend.wait_for_run()`).
- `tests/test_main.py` imports the real `main.py` through the
  `tests/stubs/decky.py` stub, with the fake CLI copied to
  `<home>/.local/bin/moonlight-steam-sync`. The stub's `DECKY_VERSION`
  is `v3.0.0-test`; a test deletes it to prove `loader_version` reads `""`.
- `tests/test_hard_rules.py` greps for what can be proven mechanically:
  `flags: []`, no live shortcut API call in `src/`, one version
  (`package.json`'s `X.Y.Z` or `X.Y.Z-SNAPSHOT`, spelled once more as the
  CLI's `__version__`, `.dev0` for a snapshot, and in no script or
  workflow in either spelling; the match is anchored, so a third-party
  pin that shares the number does not count), the CLI's empty `dependencies`, the
  placeholder SteamGridDB key (`tests/fixtures/sgdb/api.html`'s) spelled nowhere else under `tests/`
  but that file, and, over a whole browser fetch, the key in no result,
  event or log line (hard rule 4 for spec 3.20); and hard rule 12's names
  under `src/` (`files_naming`, comments and tests included):
  `confirm_plugin_install` nowhere, `DeckyBackend` and `utilities/` only in
  `lib/decky.ts` and its test, `api.github.com` only in `lib/updates.ts`
  and its test, `fetchNoCors` only in `instance.tsx` (and its one call
  `cache: "no-store"`, amendment A6), the repository's
  slug and `releases/download` only in `updates.ts` and its test (no
  download URL is built anywhere else). Each is an equality, so a rename
  that loses the name fails too. It also holds `updates.ts`'s `REF_RE`
  and `TAG_RE` spelled exactly as the backend's `updates.REF_RE` /
  `TAG_RE`, its `STABLE_CHANNEL` and `BRANCH_CHANNEL_PREFIX` as
  `settings.py`'s (update spec §3.12.4: the *Channel* picker writes what
  the frontend spells), and `decky.ts`'s staged file name
  (`STAGED_DIR`, `STAGED_FILE_PREFIX`, the hash's first
  `STAGED_HASH_DIGITS`, `STAGED_FILE_SUFFIX`) equal to what the
  backend's `updates.staged_path` builds (update spec §3.12.5), each read
  out of the TypeScript source by a regular expression.
- The CLI's own suite is `cli/tests` (see `cli/AGENTS.md`, "Testing"): it
  has its own conftest and fakes, runs apart from `tests/` (`python3 -m
  pytest cli`), and `cli/tests/test_release_zipapp.py` builds through
  `scripts/build_cli.py`.

On-device checks are not merge criteria; they are collected in
`DEVICE-CHECKLIST.md` (arrives with PR-8).
