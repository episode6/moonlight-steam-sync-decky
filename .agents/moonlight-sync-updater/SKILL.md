---
name: moonlight-sync-updater
description: >-
  The Moonlight Sync plugin's self-update (update spec,
  ~/specs/moonlight-steam-sync/self-update.md): the release / branch-build
  check, the update channel and the hand-off to Decky's installer. Covers
  src/lib/updates.ts (parseReleases, checkReleases, offerOf, installable,
  stagedMatches, installRequestOf, the texts), src/lib/decky.ts (the only
  module touching Decky's globals, hard rule 12), their tests and
  tests/fixtures/update/, the backend's update_check / update_channel /
  loader_version and main.py's empty _uninstall, and how controller.test.ts
  tests loadUpdates / checkUpdates / installUpdate / setUpdateChannel. Load
  before changing anything about update checks, channels, the Updates page's
  logic or installing an update.
---

# Moonlight Sync self-updater

Reference split out of the root `AGENTS.md`, whose hard rules (cited here as
"hard rule N") apply throughout. Related: `moonlight-sync-update-staging`
(the backend download and verification every install goes through),
`moonlight-sync-frontend` (controller.ts's updater entry points),
`moonlight-sync-ci` (builds.yml, which publishes branch builds).

## Module map: the updater's frontend

```
src/lib/                    pure modules (vitest)
  updates.ts                the updater's logic (update spec §3.4, §3.7, §3.12.4,
                            §3.12.5): REPO (the repository's slug, spelled here only,
                            and the only file under src/ with a download URL),
                            RELEASES_API, DOWNLOAD_BASE, ASSET, PLUGIN_NAME,
                            MIN_UPDATER_VERSION ([0, 12, 0], the first release with the updater),
                            MIN_LOADER_VERSION, INSTALL_TYPES_LOADER_VERSION,
                            CHECK_MIN_INTERVAL_MS, NOTES_MAX_CHARS, TAG_RE,
                            RELEASE_TAG_RE, REF_RE (the backend's, spelled alike:
                            test_hard_rules.py holds it and TAG_RE equal),
                            BUILD_TAG_PREFIX, BUILD_ASSET, BUILD_MAX_BYTES,
                            STABLE_CHANNEL / BRANCH_CHANNEL_PREFIX, INSTALL_TYPE; the
                            NetPort / HttpAnswer seam; Release (StableRelease |
                            BranchBuild: `kind` "branch", `ref`, `version` null,
                            `updatedAt` the zip's upload, a digest always, `build`
                            null until fetched) / Offer / Installed / ChannelOption /
                            CheckResult / UpdateInfo / UpdatePhase (idle / checking /
                            downloading / asking); parseReleases()
                            (phase 1's releases unchanged: drafts, prereleases,
                            non-vX.Y.Z tags and releases without the zip skipped, the
                            zip's `digest` as 64 lower-case hex or null, highest
                            first; then branch builds by ref: a non-draft prerelease
                            tagged `build-…` within TAG_RE with the zip and a digest,
                            `ref` the title when it matches REF_RE else the tag
                            without `build-`, the latest-uploaded kept when two give
                            one ref; no URL kept), assetUrl() (throws on a bad tag),
                            parseBuild(text, ref) (the backend's parse_build rules
                            plus 64 KiB, `kind` "branch" and the entry's own `ref`),
                            checkReleases(net, channel) (one GET of the list; the
                            §3.4 table: bad-release, rate-limited with retryAt from
                            `retry-after` else `x-ratelimit-reset`, network; on a
                            branch channel a second GET of that branch's
                            `build.json` only, from assetUrl, whose failure leaves
                            `build` null and never fails the check), channelRef() /
                            channelOf(settings) (anything not a channel reads as
                            `stable`; every caller reads the channel through it),
                            installedOf(cliVersion) ({version, build}),
                            branchEntryOf(), channelsOf() (Releases, `main`, the
                            other branches by name with `updatedAt`, the selected
                            one always there), offerOf(installed, releases, channel)
                            (§3.12.4's six rows: stable updates a release, switches
                            a branch build to the newest release; a branch channel
                            switches to its build unless the same ref and sha are
                            installed, nothing without an entry or its `build`; a
                            digest and >= MIN_UPDATER_VERSION for a release; only a
                            `build.json` with `kind` "branch" makes a branch build),
                            installable() (releases only, whatever the channel; each
                            a `switch` from a branch build, else update / reinstall /
                            downgrade, empty when the installed version does not
                            parse), installType(), loaderSupported(),
                            updateCheckEnabled(), stagedMatches(offer, staged) (the
                            staging answered what the offer asked for: its digest
                            lower-cased; a release's version exactly; a branch
                            build's `build.json` of kind "branch" with the offer's
                            ref and a commit), installRequestOf(offer, staged,
                            loader) (the staged `file://` artifact and hash, the
                            name, installType(action), and the release's version or
                            branchVersionText() of the staged zip's own version and
                            `build.json`: `<zip version> (<ref> @ <sha7>)`, the
                            shape decky.ts accepts), and the texts:
                            updateRowView() (the panel's row, on the channel),
                            installedText() (a branch build's ref, sha7 and built
                            time), builtFromText() (About's *Built from*: the
                            same for a release's build.json too, the tag its
                            ref; BUILD_UNKNOWN_TEXT without one), latestText(…, channel) ("No build of <ref> is
                            published"; a branch offer's "built <when>"),
                            versionLabel(), installButtonText() (`Switch to` for a
                            switch; `Downloading…` / `Waiting for Decky…`)
  updates.test.ts           the fixture parsed (phase 1's releases unchanged, then the
                            branch builds; every skip, the ref rule, the duplicate
                            ref), every digest form, assetUrl's refusals, one test per
                            checkReleases row, the `build.json` request made for the
                            selected branch only and its failures, parseBuild,
                            channelOf / channelsOf, one test per row of §3.12.4's
                            offer table and its edges, installable,
                            installType / loaderSupported, stagedMatches,
                            installRequestOf over a staged answer,
                            branchVersionText, REF_RE, the texts
  decky.ts                  the Decky seam (update spec §3.5, §3.12.5), the one module
                            touching Decky's globals (hard rule 12): INSTALL_ROUTE,
                            FILE_ARTIFACT_PREFIX (`file:///`), STAGED_DIR /
                            STAGED_FILE_PREFIX / STAGED_FILE_SUFFIX /
                            STAGED_HASH_DIGITS (the backend's `staged_path` name,
                            spelled here; test_hard_rules.py holds the two equal),
                            INSTALL_NAME, REF_RE (updates.ts's, spelled here too;
                            decky.test.ts holds them equal): literals, nothing
                            imported from updates.ts, so the allowlist does not move
                            with it; InstallRequest, DeckyInstaller,
                            deckyInstaller(scope = globalThis): the router is
                            `scope.DeckyBackend`, else `scope.opener.DeckyBackend`,
                            every read guarded; request() reads each field once and
                            refuses (calling nothing) unless the hash is 64
                            lower-case hex digits, the artifact is exactly `file://`
                            and an absolute path ending in
                            `/update/staged/Moonlight-Sync-<the hash's first 12>.zip`
                            (no URL of any scheme, no empty / `.` / `..` step, no
                            backslash, control character, `?`, `#` or `%`; a space is
                            fine, Decky reads the path raw), the name is `Moonlight
                            Sync`, the version is a release's (non-empty, not `dev` in
                            any case, of `[0-9A-Za-z.+-]`) or exactly `<such a
                            version> (<REF_RE ref> @ <7 lower-case hex>)`, and the
                            install type an integer 1-4; then one positional
                            `call(INSTALL_ROUTE, artifact, name, version, hash,
                            installType)`, false when it throws
  decky.test.ts             the router on the scope / on `opener` / absent / behind a
                            throwing getter, the call's arguments (the staged path
                            raw, a space in it), branch builds' versions, every
                            refusal with nothing called (every URL: the release's,
                            http, file://host/, file:/, FILE:///, relative paths, the
                            name mid-path, another zip under the runtime directory, a
                            hash whose first 12 are not the file's; the step,
                            backslash, query, percent, control-character and getter
                            cases; every version form), REF_RE equal to updates.ts's
```

## Backend contract: the self-update's settings

The self-update's backend part (update spec §3.3; the update spec is
`~/specs/moonlight-steam-sync/self-update.md`) is three small things,
with no request and no new callable.
`settings.update_check` (default `true`, `BOOL_SETTINGS`, a plain
`set_settings` key) is the switch for checking for a newer release when
the plugin loads; the check itself is the frontend's. `cli_version()`
carries an additive `loader_version`, Decky Loader's version as
`decky.DECKY_VERSION` spells it (`"v3.2.9"`), `""` when unknown: `main.py`
passes `getattr(decky, "DECKY_VERSION", "")` to `Backend(loader_version=…)`.
And `main.py`'s `_uninstall` stays `pass`: Decky's installer stops the old
copy with `stop(uninstall=True)` on every update, not only on a real
uninstall, so anything there would run at each update (hard rule 12);
`tests/test_main.py` holds it to returning `None` and writing, removing
and spawning nothing. The check and the hand-off are the frontend's
(`updates.ts`, `decky.ts`, the controller's `loadUpdates` /
`checkUpdates` / `installUpdate` / `cancelUpdate` / `setUpdateChannel`):
the backend makes no request of its own but the staging's download (the
`moonlight-sync-update-staging` skill), and the updater calls no backend
callable but `set_settings`
(`update_check`, `update_channel`), `stage_update` and `cancel_update`.
`settings.update_channel` (update spec §3.12.4, default `"stable"`) is
what the updater follows: exactly `"stable"`, or `"branch:"` followed by a
ref matching `updates.REF_RE` (`settings.is_channel`); `set_settings`
refuses anything else as `bad-request` (a non-string, an empty or
out-of-pattern ref, another word, whitespace around it), and a hand-broken
value in the file reads back as `"stable"` rather than failing
`get_settings`. The Updates page's *Channel* picker is the one thing that
sets it (`setUpdateChannel`, update spec §3.12.5); the frontend reads it
only through `channelOf`, and `tests/test_hard_rules.py` holds its two
fixed parts (`STABLE_CHANNEL`, `BRANCH_CHANNEL_PREFIX`) spelled alike in
`settings.py` and `updates.ts`.

## Testing the updater

- The updater (update spec §3.9) never makes a request in a test.
  `tests/fixtures/update/releases.json` is GitHub's releases list,
  hand-written and trimmed (nothing real; hashes are 64 repeated hex
  digits; download URLs on `example.invalid`, so "no URL kept" is
  provable): a newer `v0.13.0`, the installed `v0.12.0`, `v0.11.0` below
  `MIN_UPDATER_VERSION`, a draft, a prerelease, `v0.12.1` with a `null`
  digest, `v0.12.2` without the zip, a `v1.2` tag and one string entry,
  out of order; and the branch builds of §3.12.4: `build-main` and
  `build-feature-x` (title `feature/x`), `build-odd-title` (a title that
  is not a ref, so its ref is the tag's), `build-no-digest` and a draft
  `build-drafted` (both skipped). `update/build-main.json` is `main`'s
  `build.json` (an upper-case sha, to prove the lower-casing).
  `updates.test.ts` reads them through `src/test/fixtures.ts`'s
  `fixtureText` and scripts a `NetPort` per §3.4 table row (answers by
  URL for the `build.json` request);
  `decky.test.ts` drives `deckyInstaller` over plain scope objects (a
  recording router, `opener`, throwing getters) with staged `file://`
  artifacts under a runtime directory with a space in it, every URL it
  refuses built from `updates.ts`'s `assetUrl` (so the slug stays out of
  it); `controller.test.ts`'s `FakeUi` carries the three `UiPort`
  members: `net()` answers `netAnswers[url]`, else `netAnswer` (by
  default a 200 with no release, so older tests see no update toast and
  their calls are unchanged; an `Error` rejects; `holdNet` parks the
  GET) and pushes `net:<url>` to the `order` log, `installer()` records
  requests and pushes `install:<version>` (`holdInstall` parks it), and
  `leaveSettings()` pushes `leave`; the fake backend's calls push
  `call:<name>`. So the staged order (update spec §3.12.5) is asserted
  whole: `call:stage_update`, `leave`, `install:0.13.0` for a release on
  `stable` (no check); `net:<list>`, `net:<build.json>`,
  `call:stage_update`, `leave`, `install:0.12.0 (main @ abc1234)` for a
  branch build; `call:stage_update` then the failure's toast for a failed
  staging or a mismatched answer; `call:stage_update`,
  `call:cancel_update` and no toast for a cancel. The updater's tests
  answer `stage_update` with what was asked for (`stagedFor`: the staged
  path of the hash, a branch's `build.json` at `main`'s commit), or park
  it (`holdStage` / `answerStage`) for the phases, *Cancel*, the plugin
  turned off mid-download and the refusals while downloading. Its channel
  tests (update spec §3.12.4, §3.12.5) set `settingsFile.update_channel`
  and answer `build-main`'s `build.json` through `netAnswers`: the second
  request made for the followed branch only, the announced `main @
  <sha7>`, a failed `build.json` failing nothing, the forced check before
  a branch build's staging (its failure, a stored `retryAt`, no offer
  after it, a walk started during it, the plugin turned off during it),
  a switch back to a release staged with install type 4, and the
  *Channel* picker (`setUpdateChannel`: stored, then checked within the
  minute; the same channel; a refused `set_settings`; the check's failure
  toasted). `state.test.ts` holds the panel's row on a channel, and
  `tests/test_backend.py` `update_channel`'s validation and its
  hand-broken read. Decky's dialog, the `file://` install and the reload
  are device checks (DEVICE-CHECKLIST §16, §17).
