---
name: moonlight-sync-release
description: >-
  How to cut a Moonlight Sync release (one version for the plugin and the
  CLI): who may tag, bumping package.json and the CLI's __version__, the
  CHANGELOG section, gh release create, checking the release assets, and the
  history of every release so far. Load whenever asked to cut, prepare or bump
  a release, touch the version number, or write a release's CHANGELOG section.
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

Once everything intended for the release has merged to `main`
(substitute the version being cut for `X.Y.Z`):

```sh
git checkout main && git pull

# 1. Bump the one version in both of its spellings (hard rule 8):
#    package.json's "version" (decky-loader exports it as
#    DECKY_PLUGIN_VERSION) and the CLI's __version__ (cli/pyproject.toml's
#    version is dynamic and reads it). build_cli.py refuses a mismatch.
$EDITOR package.json cli/src/moonlight_steam_sync/__init__.py

# 2. Move the CHANGELOG's [Unreleased] entries (the plugin's and the
#    CLI's alike) into a new dated [X.Y.Z] section and open a new empty
#    [Unreleased] section above it. cli/CHANGELOG.md is the CLI's history
#    up to 0.4.0 and is not edited any more.
$EDITOR CHANGELOG.md

# 3. Commit the bump.
git add package.json cli/src/moonlight_steam_sync/__init__.py CHANGELOG.md
git commit -m "Release vX.Y.Z"

# 4. Push, then create the release. `gh release create` makes the tag and
#    the release page in one step; the tag reaching GitHub triggers
#    release.yml, whose build job checks the tag against package.json and
#    whose github-release job uploads the assets into the release that
#    now already exists (idempotent, see the comment on that step).
git push origin main
gh release create vX.Y.Z --target main --title vX.Y.Z --generate-notes
```

Pushing a plain `git tag` works too and takes the same path; the workflow
creates the release itself in that case. After the push, watch the
`Release` workflow to completion and confirm the release page has
`Moonlight-Sync.zip`, `moonlight-steam-sync.pyz` and both `.sha256` files
attached, then sanity-check both install paths end to end on a Deck:

```sh
curl -fsSL https://raw.githubusercontent.com/episode6/moonlight-steam-sync-decky/main/install.sh | sh
curl -fsSL https://raw.githubusercontent.com/episode6/moonlight-steam-sync-decky/main/cli/install.sh | sh
moonlight-steam-sync --version     # X.Y.Z
```

Then walk `DEVICE-CHECKLIST.md` from the top.
