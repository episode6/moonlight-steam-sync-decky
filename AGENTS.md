# Agent guidance for moonlight-steam-sync-decky

The harness-neutral guide for this repo; `CLAUDE.md` is a symlink to it.
The design is `~/specs/moonlight-steam-sync/decky-plugin.md` (sections 3.6
to 3.13 are the plugin); the self-update is
`~/specs/moonlight-steam-sync/self-update.md` (cited as "update spec
§N"); this file is the always-relevant core, and the reference is in
the repo skills listed under "Skills: the reference".

## What this is

**Moonlight Sync**, a Decky Loader plugin that drives the
moonlight-steam-sync CLI from Game Mode: a Python backend that shells out to
`~/.local/bin/moonlight-steam-sync --json …` and relays its NDJSON events,
and a TypeScript frontend (Quick Access panel, settings route with the
Titles page, restart prompt, and the updater that hands a newer release
to Decky's own installer). The CLI is the product; the plugin is a thin
UI over it.

**The CLI lives in `cli/`** (moved here from the now-archived
[episode6/moonlight-steam-sync](https://github.com/episode6/moonlight-steam-sync)
on 2026-09-23, at its `v0.4.0`). It keeps its own guide,
[`cli/AGENTS.md`](cli/AGENTS.md) (its hard rules -- Python 3.11 floor, zero
runtime dependencies, stdlib only, never `moonlight list --csv`, never
writing `config.toml` -- its module map, the resumability contract, its
fixtures), its own `cli/README.md` and `cli/pyproject.toml`, and its own
test suite (`cli/tests`). Read that guide before touching anything under
`cli/`. The plugin still talks to the CLI only as a subprocess, over the
spec's contract (hard rule 7): the backend never imports
`moonlight_steam_sync`, and a change to a flag, subcommand or event key is
a change to both halves in one PR.

## Hard rules

Breaking any of these is a blocker, not a judgement call.

1. **The CLI is the only writer.** The plugin never writes under the Steam
   directory (`shortcuts.vdf`, `userdata/`, `grid/`, controller configs) and
   never calls `AddShortcut`, `RemoveShortcut`, `SetShortcutName`,
   `SetAppLaunchOptions`, `SetAppHiddenState` or `SetCustomArtworkForApp`.
   It never writes the CLI's `config.toml` either. **The one exception**
   (spec §3.15, the user's decision of 2026-09-21): the client ignores
   `IsHidden` in `shortcuts.vdf`, so the plugin mirrors `status`'s `hidden`
   into the client and, while Stream shortcuts are shown, keeps the
   *Streaming* collection of shortcuts beside the tab (spec §3.17), both through
   `collectionStore` and only in `steam.ts`'s `libraryPort()`
   (`tests/test_hard_rules.py` holds it there). It writes no file and
   touches only the CLI's own entries plus its own members of that one
   collection. The *Streaming* tab (spec §3.17) is a route patch on the
   library's tab bar and writes nothing anywhere. **The one CLI file the
   plugin touches** (the user's decision of 2026-09-23, not in the spec):
   Advanced's *Reset match cache* deletes the CLI's `matches.json` whole,
   pins included, through `reset_match_cache` and only under the busy
   guard (a run or a `match` child writes that file). It is deleted, never
   edited; `hosts/` beside it and everything else of the CLI's stays the
   CLI's. The CLI has no reset of its own (only `match --unpin` per title:
   a miss is retried by every sync, but a match stands), which is why.
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
   never against CLI 0.2.0 behaviour. The minimum CLI is `0.4.0`
   (`install.MIN_CLI_VERSION`, the one place it lives). The contract is
   additive-only; the plugin runs whatever CLI is installed, which may be
   newer or older than the bundled one.
8. **One version.** `package.json`'s `"version"` is the plugin's and the
   CLI's: the CLI's `__version__` (`cli/src/moonlight_steam_sync/__init__.py`)
   is its one other spelling, `scripts/build_cli.py` refuses to build when
   they differ, and a release tag must be `v<version>`. No script or
   workflow spells the number. Between releases `main` carries the next
   version as `X.Y.Z-SNAPSHOT`, which the CLI spells `X.Y.Z.dev0` (PEP 440
   has no `-SNAPSHOT`; `build_cli.py`'s `cli_spelling` is that rule's one
   home and `scripts/set_version.py` writes both); a release is the bare
   `X.Y.Z`, set on its `release/vX.Y.Z` branch and never on `main`, and
   a hotfix of it adds a fourth part, `X.Y.Z.1` (the
   `moonlight-sync-release` skill has the flow).
9. **`src/lib/` is pure**: no `@decky/*`, `react` or `react-icons` import
   (an eslint `no-restricted-imports` rule enforces it), so vitest can load
   all of it. Decky-facing code lives in `src/components/`, `src/instance.tsx`
   and `src/index.tsx`.
10. **Stay out of `probes/`** unless the task is the PR-0 probe kit. It is
    its own throwaway plugin with its own lockfile and workflow
    (`probe.yml`); the root tooling ignores it explicitly (below).
11. Anything the spec does not settle that changes behaviour, a contract,
    a file or scope: stop and escalate (spec §5), do not improvise.
12. **Updates go through Decky's installer, confirmed by the user.** The
    plugin never writes its own plugin directory. It hands Decky
    (`utilities/install_plugin`) a zip its backend staged and verified,
    always with a non-empty sha256, the name `Moonlight Sync` and a
    version that is never `dev`. It never calls
    `utilities/confirm_plugin_install`: the confirmation is the user's,
    in Decky's dialog. Download URLs are built from constants and a
    validated tag, never taken from a response. `main.py`'s `_uninstall`
    does nothing, since Decky runs it on every update.
    `src/lib/decky.ts` is the only place that touches Decky's globals.

The updater's further invariants (update spec §3.2), each held by a
test: nothing is installed unasked (a check may run on its own, a
hand-off only follows a button press); the updater is silent while the
plugin is off (no check, no toast, no panel row, no *Updates* page); it
never runs a Moonlight command and never touches the Steam directory; the
SteamGridDB key is not involved; an update is never offered without a
hash. Since the staged hand-off (update spec §3.12.5, Decision U17) every
install, a release's included, is downloaded and verified by the backend
before Decky is asked, so no install can remove the plugin: an install
that cannot succeed is refused before Decky removes anything, and Decky
is never handed a URL. `tests/test_hard_rules.py` greps `src/` for rule
12's names: `confirm_plugin_install` nowhere, `DeckyBackend` and
`utilities/` only in `lib/decky.ts` (and its test), `api.github.com` only
in `lib/updates.ts` (and its test), `fetchNoCors` only in `instance.tsx`,
the repository's slug and `releases/download` only in `updates.ts` (and
its test), so no download URL is built anywhere else.

## Skills: the reference

The module map, backend contract, test harness, CI and release steps are
repo skills (`.agents/<name>/SKILL.md`, linked from
`.claude/skills/<name>`). Load the one for the area before changing it:

- `moonlight-sync-frontend`: `src/index.tsx`, `src/instance.tsx`, the
  `src/lib` core (`controller.ts`, `state.ts`, `cli.ts`, `join.ts`, …).
- `moonlight-sync-library-ui`: `src/components/`, `src/routes/`,
  `library.ts` / `tabs.ts` / `appPage.ts`.
- `moonlight-sync-controller-layouts`: `layouts.ts`, spec 3.16 / 3.10.
- `moonlight-sync-backend`: `main.py`, `py_modules/`, the backend contract.
- `moonlight-sync-sgdb-key-fetch`: `cdp.py`, `sgdbpage.py` (spec 3.20).
- `moonlight-sync-updater`: `updates.ts`, `decky.ts`, the update settings.
- `moonlight-sync-update-staging`: `stage_update`, `fetch.py`, `updates.py`.
- `moonlight-sync-testing`: the off-device harness, `DEVICE-CHECKLIST.md`.
- `moonlight-sync-ci`: root files, workflows, `scripts/`, `backend/`.
- `moonlight-sync-installers`: `install.sh`, `cli/install.sh`.
- `moonlight-sync-release`: cutting a release, the release history.

## Commands

```sh
npx --yes pnpm@9 install          # pnpm is pinned to major 9 (lockfileVersion 9.0)
pnpm run typecheck                # tsc --noEmit
pnpm run lint                     # eslint .
pnpm run test                     # vitest run (src/**/*.test.ts, node environment)
pnpm run build                    # rollup -> dist/index.js
python3 -m pytest                 # tests/ only (pyproject testpaths)
pip install -r requirements-dev.txt && pip install --no-deps -e ./cli
python3 -m pytest cli             # the CLI's suite (cli/pyproject.toml's settings)
ruff check .                      # plugin and cli/; probes/ excluded in ruff.toml
backend/entrypoint.sh             # build cli/src -> backend/out/moonlight-steam-sync.pyz
python3 scripts/package.py        # out/Moonlight-Sync.zip (pnpm run package)
gh workflow run builds.yml --ref <branch>   # publish a branch's build (then every push)
python3 scripts/set_version.py X.Y.Z[-SNAPSHOT]   # the one version, both spellings
python3 scripts/ship_release.py --output REPORT.json [--dry-run]   # from release/vX.Y.Z
```

Run long commands through `tee` to a log file, never `tail`. Never push
to `main`; force-push only with `--force-with-lease`, and only on the
PR's own branch.

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
- `ci.yml` has no probes job: the kit's tests, plugin build and runner
  smoke test run only in `probe.yml`, path-filtered to `probes/**`.

## Docs to keep current

README (install, updating, panel, restart, hosts, Titles page, hidden
shortcuts and the Streaming tab, key, files, the CLI-only install,
developing), this file (what this is, hard rules, commands, the skills
index), the skill for each area the change touches
(`.agents/moonlight-sync-*/SKILL.md`: its module map entries, its part of
the backend contract, its test notes; the release history in
`moonlight-sync-release`), `CHANGELOG.md` `[Unreleased]`,
`DEVICE-CHECKLIST.md`, and docstrings, in the same PR as the change. A new
module or area goes into an existing skill's module map, or a new skill
listed above. A CLI change also keeps `cli/README.md` (its usage and
`--help` text) and `cli/AGENTS.md` current; its changelog entry goes in the
root `CHANGELOG.md`.
