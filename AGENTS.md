# Agent guidance for moonlight-steam-sync-decky

The harness-neutral guide for this repo; `CLAUDE.md` is a symlink to it.
The design is `~/specs/moonlight-steam-sync/decky-plugin.md` (sections 3.6
to 3.13 are the plugin); this file is the day-to-day summary.

## What this is

**Moonlight Sync**, a Decky Loader plugin that drives the
[moonlight-steam-sync](https://github.com/episode6/moonlight-steam-sync) CLI
from Game Mode: a Python backend that shells out to
`~/.local/bin/moonlight-steam-sync --json …` and relays its NDJSON events,
and a TypeScript frontend (Quick Access panel, settings route with the
Titles page, restart prompt). The CLI is the product; the plugin is a thin
UI over it.

## Hard rules

Breaking any of these is a blocker, not a judgement call.

1. **The CLI is the only writer.** The plugin never writes under the Steam
   directory (`shortcuts.vdf`, `userdata/`, `grid/`, controller configs) and
   never calls `AddShortcut`, `RemoveShortcut`, `SetShortcutName`,
   `SetAppLaunchOptions`, `SetAppHiddenState` or `SetCustomArtworkForApp`.
   It never writes the CLI's `config.toml` either.
2. **No `_root`.** `plugin.json` `flags` stays `[]`: the backend must run as
   the deck user so `HOME` and the CLI's paths resolve.
3. **No MoonDeck code.** MoonDeck is GPLv3, this repo is MIT. Do not open,
   fetch or copy its source; route patches and launch flows are written from
   `@decky/ui` primitives and the spec.
4. **The SteamGridDB key never reaches the frontend** beyond its last four
   characters: not in results, events, error messages or log lines.
   `keys.py` is the only place the key is read.
5. **Nothing user-specific in the repo.** Hosts are `MY-GAMING-PC` and
   `OFFICE-PC`; no real hostnames, Steam IDs, usernames or absolute home
   paths (write `~` or `$HOME`).
6. **No host-side component.** Nothing runs on the gaming PC.
7. **Build against the spec's CLI contract** (§3.4 flags, §3.4.6 events),
   never against CLI 0.2.0 behaviour. The minimum CLI is `0.3.0`
   (`install.MIN_CLI_VERSION`, the one place it lives).
8. **One pin.** The bundled CLI release is `package.json`'s
   `"moonlightSteamSync"`; every script reads it from there.
9. **`src/lib/` is pure**: no `@decky/*`, `react` or `react-icons` import
   (an eslint `no-restricted-imports` rule enforces it), so vitest can load
   all of it. Decky-facing code lives in `src/components/`, `src/instance.tsx`
   and `src/index.tsx`.
10. **Stay out of `probes/`** unless the task is the PR-0 probe kit. It is
    its own throwaway plugin with its own lockfile and workflow
    (`probe.yml`); the root tooling ignores it explicitly (below).
11. Anything the spec does not settle that changes behaviour, a contract,
    a file or scope: stop and escalate (spec §5), do not improvise.

## Module map

```
plugin.json                 name "Moonlight Sync", flags []
package.json                scripts, deps, the CLI pin ("moonlightSteamSync")
install.sh                  the end-user installer: curl the latest (or pinned) release
                            zip + .sha256, verify, unzip into ~/homebrew/plugins/, restart
                            plugin_loader (two explained sudo prompts, never non-interactive)
DEVICE-CHECKLIST.md         every on-device check (PR-0 probes, PR-5/6/7/8 items), in order
main.py                     thin decky Plugin: builds Backend, one line per callable;
                            no __init__ and `_backend` / `_startup` as class attributes, with
                            `_get` / `_ready` as classmethods, so it is correct whether the
                            loader instantiates the class (api_version > 0, ours) or calls
                            through the bare class (api_version 0)
py_modules/moonlight_sync/  the backend (imports nothing from decky)
  backend.py                every callable, the _spawn seam, NDJSON relay, busy guard,
                            timeouts, pending rules on sync_done. _spawn is where the
                            SteamGridDB key is scrubbed (once per spawn, over every parsed
                            event and every stdout/stderr line), so RunResult and therefore
                            every result, relayed event and log line is clean by construction
  install.py                read_version(), MIN_CLI_VERSION, atomic install/upgrade
  settings.py               settings.json / ignore.json / owned-apps.json /
                            pending.json / layouts.json, all .tmp + os.replace
  keys.py                   SteamGridDB key sources (config -> env -> file), key file
  events.py                 parse_line(), restart_decision(), next_pending()
backend/entrypoint.sh       the one CLI downloader (strict), also the Decky store hook
backend/Dockerfile          template's holo-base image, only for `decky plugin build`
scripts/package.py          Docker-free zip: out/Moonlight-Sync.zip ("Moonlight Sync/")
src/index.tsx               definePlugin: events, settings route, running-app watch, load()
src/instance.tsx            the Controller wired to callable / Steam / showModal / toaster
src/lib/                    pure modules (vitest)
  cli.ts                    every §3.4.6 event type, Result/Failure, Backend, makeBackend,
                            errorText (the §3.8 strings)
  events.ts                 NDJSON parsing, lastOf/eventsOf
  state.ts                  AppState, Store, reducers (runs, counters, stream map)
  controller.ts             load order, runs, restart flow, hosts, settings actions,
                            loadTitles() (list -> list_cached fallback, and list_cached
                            while a run is going; `status` only reaches the shared store
                            when no run is going, the page always gets its entries),
                            pinTitle, setIgnored,
                            streamPress() (guard, copy, run), chooseLayout(), layoutWalk()
  layouts.ts                DEFAULT_LAYOUT_STRATEGY (the one switch), layoutStrategy(),
                            copyEnabled(), the SteamInput seam, copyLayout() (the §3.10
                            rule), deckControllerIndexFrom() (by type: the type string when
                            the client has it -- final either way -- else the enum),
                            layoutControllerIndexFrom() (the Deck's, else the active or
                            only connected controller), CONFIG_SELECTION_USER,
                            the status texts,
                            walkPairs() and the walk's timings
  layouts.test.ts           copyLayout's seven cases + idempotence, the index by type,
                            the strategy switch, the stream-map derivation
  join.ts                   the Titles page: list + status joined by name into rows
                            (badge, chips, match line, capsule), filters, Show parked,
                            pages of 50, applyPin; the Change match rows (candidateRows,
                            noMatchRow, matchSummary)
  __tests__/join.test.ts    the join, every badge/chip, filters, sort, paging (fixtures)
  restart.ts                restartDecision() (the §3.9 table), modal text
  version.ts                version parsing, the CLI-missing / too-old row
  format.ts                 relative times, the Last sync line
  steam.ts                  ownedApps(), currentSteamId3(), runShortcut(),
                            shutdownSteam(), watchRunningApps(), steamInput() over
                            SteamClient.Input, controllerIndex() (ControllerStore or
                            controllerStore, else the guarded list watch; plus the
                            active-controller watch),
                            overviewLoaded(), showControllerConfigurator() (globals only)
src/routes/libraryApp.tsx   the /library/app/:appid patch (routerHook.addPatch, afterPatch
                            on renderFunc, findInReactTree for the overview and the
                            InnerContainer), written fresh; injects StreamButton
src/components/             QuickAccess, SyncProgress, RestartModal, SettingsPage,
                            HostPage, TitlesPage (layout text, Choose layout),
                            ChangeMatchModal, Pill, StreamButton (renders only when
                            streamMap has the appid), ArtworkPage, AdvancedPage, AboutPage
src/test/fixtures.ts        loads tests/fixtures for vitest
tests/                      pytest: fake_cli.py, fixtures/, conftest.py, test_*.py,
                            test_install_sh.py (install.sh end to end via
                            MOONLIGHT_SYNC_BASE_URL against a file:// fixture,
                            sudo/systemctl shimmed on PATH)
.github/workflows/release.yml  on a v* tag: strict entrypoint.sh + package.py --require-cli,
                            Moonlight-Sync.zip + .sha256 attached to a GitHub release;
                            build-and-package also runs on pull_request, where the CLI
                            fetch tolerates the release not existing yet (a ::warning::,
                            like CI's package job) instead of failing the run
```

PR-6 made `search` / `pin` / `unpin` / `set_ignored` real (the Titles page
and the Change match modal); PR-7 added the Stream button, the layout copy
and `layouts` / `record_layout`, so every callable is real. The UI pins
with `match … --defer-art` only (Decision 8) and uses no `unpin` yet (the
spec's modal has no unpin action); the callable exists for the contract.

**The layout strategy switch (spec §3.10).** PR-7 was built before the PR-0
probes ran. `DEFAULT_LAYOUT_STRATEGY = "copy"` in `src/lib/layouts.ts` is
the one place the default lives; `settings.json`'s `layout_strategy`
overrides it per device (no UI). Probe V2 (does `SetSelectedConfigForApp`
with a `workshop://` id published for the real game stick on a shortcut?)
ran on 2026-09-20 and **confirmed `copy`** -- with one correction: the call
takes five arguments, the last being the selection type
(`CONFIG_SELECTION_USER = 1`, what Steam's own configurator passes); with
four it returns normally and selects nothing. The same session found the
store global is `ControllerStore` (not `controllerStore`), that
`SteamClient.Input.RegisterForControllerListChanges` does not exist on that
client (so `watchControllers()` guards every registration), and that the
device had no Deck controller at all, which is why
`layoutControllerIndexFrom()` falls back to the active or only connected
controller. Should a later client break the copy, flip the constant to
`"picker"` and rewrite the README's "Controller layouts" section; nothing
else moves. Under `picker` no Steam Input call is made
anywhere; *Choose layout* (`SteamClient.Apps.ShowControllerConfigurator`,
hidden when absent) is the only layout affordance.

## Backend contract in one paragraph

Every callable returns `{"ok": true, …}` or `{"ok": false, "error": <code>,
"message": …}` (codes: `cli-missing`, `cli-too-old`, `cli-protocol`,
`cli-error`, `timeout`, `busy`, `owned-apps-missing`, `owned-apps-empty`,
`bad-request`, `io`) and never raises. Argv is `[python3, <installed cli>,
"--json", <subcommand>, …]` (`doctor`, `--version` and `art --help` have no
`--json`), `cwd` and `HOME` are the deck user's home, and the child gets
`MOONLIGHT_STEAM_SYNC_FROM_PLUGIN=1`. Long runs (`start_sync`,
`start_art_refetch`, `start_remove_all`) share one busy guard and emit
`sync_event {kind, event}` per stdout line and `sync_done {kind, exit,
pending, summary, commit, failure}` at the end. `pending.json` says
`"write"` *before* an `awaiting-steam-exit` event is relayed, and
`layout_walk: true` after `commit.written`. A pending `"write"` is only
lowered by a run that covers it (`events.settles_pending_write`, spec
Decision 31): a run that exits 0 without ever waiting for the client proves
there is nothing left to write *of its own kind*, so it clears a pending
write of the same kind -- and a `sync` also clears one left by an `art` run,
since a sync patches icons too -- to `"art"` when it saved images, else
`"none"`. A pending `remove` is only ever cleared by another `remove`, and a
non-zero exit clears nothing. `last_kind` / `last_plan` name the run that
*owns* the current `restart_needed`, not the last run: they only move when a
run sets or settles it, so a `sync` that found nothing to do cannot rename a
pending `remove`'s write (which would re-run the wrong kind from the restart
row and let the next sync settle it as "same kind"). `last_summary` and
`since` are the *Last sync* row and always describe the run that just
finished. `restart_countdown_s` is 0-30 everywhere
(Decision 30: the CLI's await-exit wait times out at 60 s); a larger value
in an older `settings.json` is clamped on read, not rejected. `check_host`'s
reachable result carries an additive `ignored` count for the panel's
counter. `pin` / `unpin` always pass `--defer-art` and share the long runs'
busy guard, in both directions: a `match` writes the same `matches.json` a
run is writing, so a pin is refused while a run is going *and* `start_sync`
/ `start_art_refetch` / `start_remove_all` are refused while a `match`
child is in flight. `busy`'s `kind` says which side is holding the guard
(a run kind, or `"match"`), and `errorText` turns the two into different
sentences.
`search`, `pin` and `unpin` keep the spec's argv order (`match NAME --steam
ID --defer-art`) except that a name or term starting with `-` goes last,
behind `--`, so argparse never reads it as an option. `set_ignored` needs no
CLI and drops the `check_host` memo. `layouts()` / `record_layout(
shortcut_appid, real_appid, result, url)` need no CLI either: they read and
upsert `layouts.json` (`{version: 1, entries: {<shortcut appid>:
{real_appid, result, url, when}}}`, `result` one of `copied` / `kept` /
`unavailable` / `picker`; a broken file reads as empty), and
`start_remove_all` deletes the file on `commit.written`.
`stop_sync` and `unload` also cover the moment between the busy guard and
the spawn: they flag the run, the SIGINT goes out as soon as its child
exists, and a run the signal killed before the CLI printed anything is
reported as exit 130 rather than as a protocol error.

## Commands

```sh
npx --yes pnpm@9 install          # pnpm is pinned to major 9 (lockfileVersion 9.0)
pnpm run typecheck                # tsc --noEmit
pnpm run lint                     # eslint .
pnpm run test                     # vitest run (src/**/*.test.ts, node environment)
pnpm run build                    # rollup -> dist/index.js
python3 -m pytest                 # tests/ only (pyproject testpaths)
ruff check .                      # probes/ excluded in ruff.toml
backend/entrypoint.sh             # download + verify the pinned CLI -> backend/out/
python3 scripts/package.py        # out/Moonlight-Sync.zip (pnpm run package)
```

Run long commands through `tee` to a log file, never `tail`.

## How probes/ is kept out

- `tsconfig.json` includes only `src` and excludes `probes`.
- `eslint.config.js` ignores `probes/**`; `vitest.config.ts` includes only
  `src/**/*.test.ts` and excludes `probes/**`.
- pnpm: there is deliberately **no `pnpm-workspace.yaml`**. With one, a
  `pnpm install` inside `probes/steam-input-probe` resolves to the root
  workspace and installs the root instead of the probe (tested), which
  would break `probe.yml`. Without one the root is a single package and the
  probe's own `package.json` / lockfile are never touched. `.gitignore`
  lists the file so a pnpm prompt that writes one cannot get it committed
  again; pnpm 9 also refuses to run *any* script when it is there
  (`ERROR packages field missing or empty`).
- `ruff.toml` `extend-exclude = ["probes", …]`; `pyproject.toml`
  `testpaths = ["tests"]` and `norecursedirs` include `probes`.
- CI's `probes` job runs `pytest probes/tests` only when that directory
  exists (`hashFiles`), so it is green on a tree without the kit.

## The test harness (off-device)

There is no Steam Deck during development; everything else is tested.

- `tests/fake_cli.py` stands in for the CLI. Driven by env vars:
  `FAKE_CLI_FIXTURES` (directories, `os.pathsep`-joined, searched in order),
  `FAKE_CLI_ARGV_LOG`, `FAKE_CLI_VERSION` (< 0.3.0 rejects the new flags
  like argparse: stderr only, exit 2), `FAKE_CLI_ART_COMMIT`,
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
  set against the schema. `common/` also holds the alternates picked with
  `FAKE_CLI_FIXTURE_MATCH` / `FAKE_CLI_FIXTURE_SEARCH` (`match-none`,
  `match-sgdb`, `match-unknown`, `match-silent`, `search-empty`,
  `search-no-key`). The frontend's `events.test.ts`, `restart.test.ts`,
  `state.test.ts`, `controller.test.ts`, `layouts.test.ts` and
  `__tests__/join.test.ts` read the same files, so the Python and
  TypeScript sides cannot drift. `copyLayout` and the Stream press / walk
  run over a scripted `SteamInput` (`layouts.test.ts`, `controller.test.ts`)
  and `steam.test.ts` drives the real seam over stubbed globals; the route
  patch and the button itself are device checks, not unit tests.
- `tests/conftest.py`: `backend` / `make_backend` (a started Backend over
  the fake; `@pytest.mark.scenario("full-sync")` puts that scenario in front
  of `common/`), `steam_gone`, `install_env` (a `python3` shim that prints
  the first line of the file it runs). Async callables are driven with
  `asyncio.run` (`conftest.run`); a long run is started and awaited inside
  one coroutine (`backend.wait_for_run()`).
- `tests/test_main.py` imports the real `main.py` through the
  `tests/stubs/decky.py` stub, with the fake CLI copied to
  `<home>/.local/bin/moonlight-steam-sync`.
- `tests/test_hard_rules.py` greps for what can be proven mechanically:
  `flags: []`, no live shortcut API call in `src/`, the pin only in
  `package.json`.
- `tests/test_entrypoint.py` runs `backend/entrypoint.sh` from a copy of
  `backend/` with `MSY_CLI_BASE_URL=file://…`; `tests/test_package.py`
  builds a fixture tree and checks the exact zip entry list and modes.

On-device checks are not merge criteria; they are collected in
`DEVICE-CHECKLIST.md` (arrives with PR-8).

## CI and release outline

- `.github/workflows/ci.yml` (push to `main`, every `pull_request`):
  `shellcheck` (`sh -n` on `install.sh` and `backend/entrypoint.sh`, then
  `ludeeus/action-shellcheck` over the whole tree), `frontend` (pnpm 9, Node
  20: typecheck, lint, vitest, build, upload `dist`), `backend` (Python
  3.13.5: ruff, pytest), `probes` (guarded), `package` (HEAD-checks the
  pinned CLI's `.sha256` asset: absent → a
  `::warning title=CLI v<pin> not released::` and no `bin/`; present →
  `backend/entrypoint.sh` strict; then `scripts/package.py` and the
  `Moonlight-Sync` artifact).
- `.github/workflows/release.yml`: on a `v*` tag, the same frontend build
  then strict `entrypoint.sh`, `package.py --require-cli`,
  `Moonlight-Sync.zip` + `.sha256` (`sha256sum` against the bare filename,
  matching `install.sh`'s check) attached to the GitHub release via the
  CLI repo's idempotent `gh release view || create` / `upload --clobber`
  step. The build-and-package job also runs on `pull_request` and
  `workflow_dispatch`, exactly like CI's `package` job (HEAD-check the
  CLI's `.sha256` asset; absent → the same `::warning::` and no `bin/`;
  present → `entrypoint.sh` strict), never strict on those triggers, so it
  is exercised and green before the first tag; only the
  `github-release` job is tag-gated (`startsWith(github.ref,
  'refs/tags/')`).
- `install.sh`: the end-user installer, mirroring the CLI repo's own (curl
  the release zip + `.sha256`, verify, remove any previous install, unzip
  into `~/homebrew/plugins/`, restart `plugin_loader`); its
  `MOONLIGHT_SYNC_BASE_URL` seam (mirroring `backend/entrypoint.sh`'s
  `MSY_CLI_BASE_URL`) lets `tests/test_install_sh.py` point the real `curl`
  at a `file://` fixture tree, with only `sudo`/`systemctl` shimmed on
  `PATH`, so no sudo and no network are ever touched by the test.
- The plugin PRs are stacked (PR-0 → PR-5 → PR-6 → PR-7 → PR-8), each branch
  on the previous one; never push to `main`, force-push only with
  `--force-with-lease` on this stack's own branches.

## Cutting a release

**No agent pushes a tag or creates a release.** The user does this, and
only once moonlight-steam-sync's own `v0.3.0` exists: `release.yml`'s
build job fails hard on the missing CLI release **only when it runs from
a `v*` tag push**; its `pull_request` and `workflow_dispatch` runs tolerate
the CLI not being released yet with the same `::warning::` CI's `package`
job prints, so the workflow stays green on every PR in this stack. As of
this writing `v0.3.0` has not been released, so `v0.1.0` of the plugin has
not been cut either.

Modelled on the CLI repo's own "Cutting a release", once `v0.3.0` exists
and everything intended for `v0.1.0` has merged to `main`:

```sh
git checkout main && git pull

# 1. package.json's "version" is the single source of truth
#    (decky-loader exports it as DECKY_PLUGIN_VERSION); it is already
#    "0.1.0" as of this PR, so this step is only needed for v0.2.0+.
$EDITOR package.json

# 2. Move the CHANGELOG's prepared v0.1.0 entry out of "not yet tagged"
#    (this PR left it dated "not yet tagged"; give it today's date) and
#    open a new empty [Unreleased] section above it.
$EDITOR CHANGELOG.md

# 3. Commit the bump.
git add package.json CHANGELOG.md
git commit -m "Release v0.1.0"

# 4. Push, then create the release. `gh release create` makes the tag and
#    the release page in one step; the tag reaching GitHub triggers
#    release.yml's github-release job, which builds the zip and uploads it
#    into the release that now already exists (idempotent, see the
#    comment on that step).
git push origin main
gh release create v0.1.0 --target main --title v0.1.0 --generate-notes
```

Pushing a plain `git tag` works too and takes the same path; the workflow
creates the release itself in that case. After the push, watch the
`Release` workflow to completion and confirm the release page has
`Moonlight-Sync.zip` and `Moonlight-Sync.zip.sha256` attached, then
sanity-check the install path end to end on a Deck:

```sh
curl -fsSL https://raw.githubusercontent.com/episode6/moonlight-steam-sync-decky/main/install.sh | sh
```

Then walk `DEVICE-CHECKLIST.md` from the top.

## Docs to keep current

README (install, panel, restart, hosts, Titles page, key, files,
developing), this file (module map, harness, release), `CHANGELOG.md`
`[Unreleased]`, `DEVICE-CHECKLIST.md`, and docstrings, in the same PR as
the change.
