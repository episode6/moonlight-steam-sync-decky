---
name: moonlight-sync-release
description: >-
  How to cut a Moonlight Sync release (one version for the plugin and the
  CLI) with the episode6 release-branch flow: who may tag, main's
  X.Y.Z-SNAPSHOT (the CLI's X.Y.Z.dev0) and scripts/set_version.py, cutting
  release/vX.Y.Z and its two version PRs, the CHANGELOG section,
  scripts/ship_release.py, checking the release assets, hotfixes, and the
  history of every release so far. Load whenever asked to cut a release or a
  release branch, prepare or bump a version, touch the version number, or
  write a release's CHANGELOG section.
---

# Cutting a Moonlight Sync release

Reference split out of the root `AGENTS.md`, whose hard rules (cited here as
"hard rule N") apply throughout. Related: `moonlight-sync-ci` (release.yml's
build and the github-release job), `moonlight-sync-installers`.

## Cutting a release

**No agent pushes a tag or creates a release** unless the user asks for
that release explicitly (they did for `v0.1.1`, 2026-09-20, which moved the
pin to the CLI's `v0.3.1`).

**Since the CLI moved into `cli/` (2026-09-23) one release is both.** The
CLI takes the plugin's version (it jumps from `0.4.0` to the plugin's
number), `release.yml` builds it from the tagged commit, and the release
carries `moonlight-steam-sync.pyz` beside `Moonlight-Sync.zip`, which is
what `cli/install.sh` downloads. There is no CLI release to wait for and no
pin to move any more; the history below is from when there was (until
then the plugin bundled a pinned release of the separate CLI repo, whose
releases up to `v0.4.0` stay on the archived repo).

The pin **and** `MIN_CLI_VERSION` moved to the CLI's `v0.4.0` (released
2026-09-20) together: one CLI version per plugin version, so the bundled,
minimum and fake-CLI versions are all `0.4.0` and the fixtures' `start`
events say so. The bundled-install path upgrades an older installed CLI, so
the raised minimum is invisible to users. `v0.4.0` adds `--hide-host-apps`.
Plugin `v0.2.0` (released 2026-09-20) bundles and requires that CLI but does
not pass the flag; the plugin half of spec §3.14.1 (the flag on every sync /
list / status, the `host-app` kind, counters, stream map, Choose layout,
fixtures) landed after it and is plugin `v0.3.0` (a user-visible feature,
so a minor bump; the user asked for that release on 2026-09-21). Its
release PR did steps 1-3 below (`package.json` `"version"`, the dated
CHANGELOG section), as the earlier releases' PRs did. Plugin `v0.3.1` (the
user asked for it on 2026-09-21) is a patch release for the boot-time
"Loading your library…" hang; same CLI pin and minimum. Plugin `v0.3.2`
(the user asked for it on 2026-09-21) is a patch release for the unbuffered
CLI fix (`PYTHONUNBUFFERED=1`); same CLI pin and minimum. Plugin `v0.3.3`
(the user asked for it on 2026-09-21) is a patch release for the Stream
button that never appeared (the library route patch); same CLI pin and
minimum, and its steps 1-3 rode along in the fix's own PR. Plugin `v0.4.0`
(the user asked for it on 2026-09-21) is a minor release for spec §3.15:
the plugin hides the CLI's hidden entries in the client itself (the client
ignores `IsHidden`) and keeps the *Streaming* collection, with two new
Advanced settings; same CLI pin and minimum. The plugin's `0.4.0` and the
CLI's `0.4.0` are a coincidence, not a coupling.
Plugin `v0.5.0` (the user asked for it on 2026-09-21) is a minor release for
spec §3.16, the default controller layout (PR-9 and PR-10), replacing the
layout copy; same CLI pin and minimum.
Plugin `v0.6.0` (the user asked for it on 2026-09-21) is a minor release for
spec §3.17 (the *Streaming* tab replacing the collection, PR-11) and the
gear-menu *Use as Moonlight Sync default layout* item (spec §3.16.5); same
CLI pin and minimum.
Plugin `v0.7.0` (the user asked for it on 2026-09-22) is a minor release for
spec §3.18, *Wake* in the panel's unreachable host row (Wake-on-LAN, with
the Host page's MAC field), plus the fix that makes the *Streaming* tab
reachable; same CLI pin and minimum.
Plugin `v0.8.0` (the user asked for it on 2026-09-22) is a minor release for
spec §3.19, the *Moonlight Sync* on/off toggle, plus letting Stream and the
host-app buttons launch while a game is running; same CLI pin and minimum.
Plugin `v0.9.0` (the user asked for it on 2026-09-23) is a minor release for
spec §3.20, *Get key from SteamGridDB…* (the key fetch from the Game Mode
browser), and Advanced's *Reset match cache*, plus the fix that brings back
the gear menu's *Use as Moonlight Sync default layout*; same CLI pin and
minimum.
Plugin `v0.10.0` (the user asked for it on 2026-09-24) is a minor release
for the CLI's move into `cli/` (the first release that builds and attaches
the CLI itself, so "same CLI pin" stops applying here: the CLI takes the
plugin's number, `0.10.0`, and the minimum stays `0.4.0`) and for Decision
66, no Moonlight command unasked (the host row's *Check* button). Its
bump went through a PR, since `main` only accepts changes that way.
Plugin `v0.11.0` (the user asked for it on 2026-09-27) is a minor release
for the tidier Quick Access panel (Decision 67's icon launch row and one
Moonlight layout row, the shorter host row hidden with a single host), the
Titles page's never-synced state, the Host page's MAC field removed, and
fixes to the Stream button's focus order and to the key fetch's stale tab;
the CLI takes `0.11.0`, the minimum stays `0.4.0`.
Plugin `v0.12.0` (the user asked for it on 2026-09-28) is a minor release
for the self-update (update spec PR-U1 to PR-U4c: the Updates page, the
staged hand-off to Decky's installer, the branch builds and the *Channel*
picker), About's *Built from* / *Commit*, the Titles page's *Recently
added* order and Settings listing Artwork before Titles; the CLI takes
`0.12.0`, the minimum stays `0.4.0`. It is the first release that
carries the updater, which is the version `updates.ts`'s
`MIN_UPDATER_VERSION` names (`0.12.0`, update spec §3.4's [verify],
settled by this release); every release before it is updated once with
`install.sh`. Once it is out, the user installs it with `install.sh` and
walks DEVICE-CHECKLIST §16 and §17 (the human gate after PR-U2, moved
after the release because nothing older than `0.12.0` has an updater and
nothing newer exists yet: V1-V5 reinstall it through *Install another
version*); anything found there ships as `0.12.1`, the first update the
updater itself delivers.
Plugin `v0.13.0` (the user asked for it on 2026-10-02) is a minor release,
and the first update the updater delivers (there was no `0.12.1`): the
layout buttons gathered in Advanced (Decisions 74 to 77, the Titles
page's and the gear menu's layout items removed), times on Steam's
12 / 24-hour clock, `install.sh` offering Decky Loader and a temporary
password, and fixes to the update check's HTTP cache (amendment A6) and
the panel's spacing; the CLI takes `0.13.0`, the minimum stays `0.4.0`.
Plugin `v0.13.1` (the user asked for it on 2026-10-20) is a patch release
for SteamGridDB logos (PNG-only queries, any style as a fallback) and the
Titles page's thumbnails from each shortcut's own art; the CLI takes
`0.13.1`, the minimum stays `0.4.0`.
Plugin `v0.13.2` (the user asked for it on 2026-10-29) is a patch release
for new games mismatched while SteamGridDB lags (a weak SteamGridDB match
falls through to Steam's store, and a title that is an owned game's name
matches that game before any search); the CLI takes `0.13.2`, the minimum
stays `0.4.0`.

Since 2026-10-29 releases follow the episode6 release-branch flow (the
same one the library repos, podcast-hacker and collins use, adapted to
this repo's two files and its Keep a Changelog format). The history above
this point was cut the old way, a bump committed straight to `main` and
tagged there; `v0.13.2` was the last of those, and `main` moved on to
`0.13.3-SNAPSHOT` in the PR that brought the flow in.

### The version between releases

`main` always carries the *next* release's version with `-SNAPSHOT`
after it (`0.13.3-SNAPSHOT`), so every build of `main`, About's *Plugin
version*, Decky's install dialog and the Updates page say when what is
running is a snapshot. The CLI spells the same version `X.Y.Z.dev0`
(PEP 440 has no `-SNAPSHOT`, and `pip install -e ./cli` refuses one;
`.dev0` sorts before `X.Y.Z` as semver's pre-release does). The rule
lives once, in `scripts/build_cli.py`'s `cli_spelling`; `scripts/
set_version.py X.Y.Z[-SNAPSHOT]` writes both files, and
`build_cli.py` refuses to build when they disagree. Every version
parser in the plugin (`install.parse_version`, `version.ts`'s
`parseVersion`) reads the leading `X.Y.Z` and ignores the suffix, so a
snapshot compares equal to its release: the updater offers a release to
a snapshot only through the branch-build rule (a build of a branch is
offered a *switch* to the newest release whatever the versions say,
update spec 3.12.4), and the bundled CLI's "same version, other bytes"
rule (Decision U12) is what carries a new build's CLI onto the device.
Going back from a build of `main` to a release is the one place the
numbers mislead (the snapshot's `0.13.4.dev0` parses above the release's
`0.13.3`), so `install.ensure_installed` replaces a snapshot CLI with a
release's whatever their numbers (`is_snapshot`); a newer *release* CLI
installed by hand is still kept.

A release is the bare `X.Y.Z`. It exists only on the release branch:
`release.yml` refuses a tag whose `package.json` is a `-SNAPSHOT`, and
`ship_release.py` refuses to ship a snapshot or a branch that is not
`release/*`.

### Cut the release branch

1. `main` is green (CI and the `build-main` build).
2. `<VERSION>` is `main`'s version without `-SNAPSHOT` (`0.13.3-SNAPSHOT`
   releases as `0.13.3`), unless the user wants a minor or major bump,
   which is their call, never automatic (then `<VERSION>` is that, say
   `0.14.0`).
3. Cut the branch from `main` and push it, empty:

   ```sh
   git checkout main && git pull
   git checkout -b release/v<VERSION>
   git push -u origin release/v<VERSION>
   ```

### The two version PRs

Both are drafts (the `open-pr` skill), both get CI; merge them through
GitHub, never locally. `<NEXT>` is `<VERSION>` with the patch one higher
(`0.13.3` → `0.13.4`), a patch-only bump: the next release PR picks a
bigger number if one is wanted.

**PR 1, `[VERSION] Snapshot v<NEXT>-SNAPSHOT` → `main`**, from a branch
off `main`:

```sh
python3 scripts/set_version.py <NEXT>-SNAPSHOT
```

and in `CHANGELOG.md` turn `## [Unreleased]` into `## [<VERSION>] -
<today>` (the plugin's and the CLI's entries alike; `cli/CHANGELOG.md` is
the CLI's history up to 0.4.0 and is not edited any more) and open a new
empty `## [Unreleased]` above it. If `<VERSION>` is a minor or major
bump, this PR's number is the patch above *that* (`0.14.0` → `0.14.1-SNAPSHOT`).

**PR 2, `[VERSION] Release v<VERSION>` → `release/v<VERSION>`**, from a
branch off the release branch:

```sh
python3 scripts/set_version.py <VERSION>
```

and the same CHANGELOG change (the dated `## [<VERSION>]` section with
everything since the last release, a fresh `## [Unreleased]` above it).
`scripts/ship_release.py` reads that section as the release notes, so it
has to be there and complete. The `[Unreleased]` heading stays, so the
branch's CHANGELOG has the same shape as `main`'s and a hotfix has
somewhere to go.

### Harden

Fix on `main` first, then bring the fix to the release branch with the
user-global `cherry-pick-pr` skill (a 🍒 draft PR off the release branch
that cherry-picks the squashed commit, its CHANGELOG entry moved into the
`[<VERSION>]` section). Walk `DEVICE-CHECKLIST.md` on a build of the
release branch: ask `builds.yml` for one (`gh workflow run builds.yml
--ref release/v<VERSION>`), then follow the branch from Settings →
Updates → *Channel*; its *Plugin version* reads `<VERSION>` without a
suffix, as the release will.

### Ship

Only when the user asks for the release. From the release branch, pulled
after PR 2 (and every hardening PR) merged:

```sh
git checkout release/v<VERSION> && git pull
python3 scripts/ship_release.py --dry-run --output /tmp/release.json   # the notes and the command
python3 scripts/ship_release.py --output /tmp/release.json
```

The script reads `package.json`'s version (refusing a `-SNAPSHOT`, a
CLI `__version__` that disagrees, a branch that is not `release/*` or not
the one checked out, or a local `HEAD` that is not what `origin` has for
the branch, since the tag lands on the remote's head),
takes `CHANGELOG.md`'s `## [<VERSION>] - <date>` section as the notes
and runs `gh release create v<VERSION> --target release/v<VERSION>
--title v<VERSION> --notes-file …`, which makes the tag and the release
page in one step. The tag reaching GitHub triggers `release.yml`, whose
build job checks the tag against `package.json` and whose
`github-release` job uploads the assets into the release that now
exists (idempotent, see the comment on that step; a plain `git tag` push
takes the same path and the workflow creates the release itself). The
report lands in `--output` (`tag`, `title`, `version`, `branch`, `notes`,
`url`).

After the push, watch the `Release` workflow to completion and confirm
the release page has `Moonlight-Sync.zip`, `moonlight-steam-sync.pyz` and
both `.sha256` files attached, then sanity-check both install paths end
to end on a Deck:

```sh
curl -fsSL https://raw.githubusercontent.com/episode6/moonlight-steam-sync-decky/main/install.sh | sh
curl -fsSL https://raw.githubusercontent.com/episode6/moonlight-steam-sync-decky/main/cli/install.sh | sh
moonlight-steam-sync --version     # <VERSION>
```

The updater on every installed release then offers `<VERSION>` (the
newest `v*` release is `releases/latest`; `build-*` prereleases never
are).

### Hotfixes

Not expected (the user's note of 2026-10-29: hotfixes will probably never
ship), but the branch allows one. No new branch: cherry-pick the fix into
`release/v<VERSION>` (the `cherry-pick-pr` skill), then a version PR on
that branch sets the next patch (`set_version.py <VERSION+1 patch>`, a
dated `## [<that>]` CHANGELOG section above `[<VERSION>]`) and
`ship_release.py` tags it from the same branch. `package.json` is semver
(three numbers, no fourth segment), so a hotfix takes the patch number
`main`'s snapshot was going to use: bump `main` past it in a
`[VERSION] Snapshot` PR of its own (`0.13.4-SNAPSHOT` → `0.13.5-SNAPSHOT`)
so the next release is above the hotfix.
