# Agent guidance for moonlight-steam-sync-decky

The harness-neutral guide for this repo; `CLAUDE.md` is a symlink to it.
The design is `~/specs/moonlight-steam-sync/decky-plugin.md` (sections 3.6
to 3.13 are the plugin); the self-update is
`~/specs/moonlight-steam-sync/self-update.md` (cited as "update spec
§N"); this file is the day-to-day summary.

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
   CLI's. The CLI has no reset of its own (only `match --unpin` per title,
   and a miss is not re-queried for seven days), which is why.
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
   workflow spells the number.
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

## Module map

```
plugin.json                 name "Moonlight Sync", flags []
package.json                scripts, deps, "version" (the plugin's and the CLI's)
project-icon.svg            the repo's icon (moved over with the CLI)
install.sh                  the end-user installer: curl the latest (or pinned) release
                            zip + .sha256, verify, unzip into ~/homebrew/plugins/, restart
                            plugin_loader (two explained sudo prompts, never non-interactive)
cli/                        the moonlight-steam-sync CLI (its own AGENTS.md, README.md,
                            CHANGELOG.md up to 0.4.0, pyproject.toml, src/, tests/,
                            scripts/record_fixtures.py); install.sh: the CLI-only
                            installer, curl the release's moonlight-steam-sync.pyz +
                            .sha256 into ~/.local/bin (MOONLIGHT_STEAM_SYNC_VERSION,
                            INSTALL_DIR, NO_MODIFY_PATH, and the
                            MOONLIGHT_STEAM_SYNC_BASE_URL test seam)
DEVICE-CHECKLIST.md         every on-device check (PR-0 probes, PR-5/6/7/8 items, §3.14,
                            §3.15 and the §3.16 default layout's [verify] items, then
                            §3.17-§3.20; the key fetch is §14, the panel's launch and
                            layout rows §15, updating from the plugin §16: V1-V7 of
                            update spec §3.9, via *Install another version* ->
                            reinstall until a newer release exists; the staged
                            hand-off and the channels §17: V8-V10 of update spec
                            §3.12.5, the branch's `build.json` through the
                            loader's fetch and a build made on the device,
                            amendment A5), in order
main.py                     thin decky Plugin: builds Backend, one line per callable;
                            no __init__ and `_backend` / `_startup` as class attributes, with
                            `_get` / `_ready` as classmethods, so it is correct whether the
                            loader instantiates the class (api_version > 0, ours) or calls
                            through the bare class (api_version 0); passes
                            `getattr(decky, "DECKY_VERSION", "")` as the Backend's
                            `loader_version` and `decky.DECKY_PLUGIN_RUNTIME_DIR` as its
                            `runtime_dir` (never an `update_source`: the downloads
                            always come from this repository's releases);
                            `stage_update(tag, sha256, version=None, ref=None)` and
                            `cancel_update()` (update spec §3.12.3); `_uninstall` is
                            `pass` on purpose (Decky runs it on every update, hard rule
                            12, update spec §2.3 / §3.3)
py_modules/moonlight_sync/  the backend (imports nothing from decky)
  backend.py                every callable, the _spawn seam, NDJSON relay, busy guard,
                            timeouts, pending rules on sync_done. _spawn is where the
                            SteamGridDB key is scrubbed (once per spawn, over every parsed
                            event and every stdout/stderr line), so RunResult and therefore
                            every result, relayed event and log line is clean by construction;
                            match_cache_path() (the CLI's matches.json as the child resolves
                            it: $XDG_CACHE_HOME from the child's env, else <home>/.cache) and
                            reset_match_cache() (Advanced's *Reset match cache*: deletes the
                            file whole, pins included, under the busy guard; answers
                            {removed, titles, pins} for the toast; no CLI);
                            the staging (update spec 3.12.3): `runtime_dir`,
                            `update_source` (an `updates.Source`, the tests' seam),
                            FETCH_SCRIPT (fetch.py beside it), _fetch() (the
                            downloader as `[python, "-I", fetch.py, options, "--",
                            url, dest]` through _child_env(), stderr to /dev/null,
                            one stdout line of at most FETCH_LINE_LIMIT, killed after
                            its timeout + FETCH_ANSWER_GRACE, which answers `timeout`
                            with that limit as `timeout_s`; a cancel that landed
                            during the spawn kills it as soon as it exists; no
                            line or anything but an object with a boolean `ok` is
                            `io`), stage_update() (the seven
                            steps; UpdateJob is its "update" busy guard, released on
                            every exit with the sidecar and any part file removed),
                            cancel_update() / _cancel_staging() (unload's: kill,
                            wait, remove *.part), startup's updates.cleanup(),
                            cli_version()'s `build` (updates.read_build)
  fetch.py                  the downloader (update spec 3.12.3): a *script* the backend
                            runs with the system python3 -I, never imported, stdlib
                            only, Python 3.11. check_url() (the one allowlist, for
                            the first URL and every redirect: printable ASCII with
                            no backslash before parsing, `https://` exactly, host
                            github.com or *.githubusercontent.com, port 443, no user
                            info; --allow-file admits file:/// and nothing else),
                            RedirectGuard (checks in http_error_30x and
                            redirect_request, before the hop is opened; five hops at
                            most), build_opener() (a hand-built OpenerDirector: https
                            only, file under --allow-file, no proxy,
                            ssl.create_default_context()), download() (64 KiB chunks
                            to DEST.part, O_EXCL | O_NOFOLLOW, 0600, hashed and
                            counted as it goes, os.replace only on success), run() /
                            main() (exactly one JSON line and exit 0 whatever
                            happens; messages carry scheme, host and path only)
  updates.py                the staging's pure half (update spec 3.12.3): REPO,
                            DOWNLOAD_BASE, ASSET / ASSET_SHA, the limits, TAG_RE /
                            REF_RE (always fullmatch), Source, asset_url() (a
                            validated tag and one of the two assets), parse_sidecar(),
                            parse_build() / read_build() (the known keys only),
                            validate_zip() (BadZip(message), one check per rule, the
                            central-directory checks before testzip(), nothing
                            extracted), staged_path() (the name from the validated
                            hash alone), ensure_staged_dir() (0700, no symlinked
                            steps), cleanup() / remove_parts() (regular files directly
                            in update/staged/, symlinks removed as links, never
                            raise), strip_queries(); nothing at its top level is
                            named `updater`
  install.py                read_version(), MIN_CLI_VERSION, atomic install/upgrade;
                            sha256_file(); an equal version with other bytes is
                            `replaced` (Decision U12), a newer one `kept`
  settings.py               settings.json / ignore.json / owned-apps.json /
                            pending.json / layouts.json / added.json, all .tmp +
                            os.replace; added() / note_titles() (`added.json`,
                            `{version: 1, titles: {<Moonlight name>: <when> | null}}`:
                            the names `status` lists, a new one stamped, a known one
                            kept, a gone one dropped, the first call all `null`);
                            pending()'s `synced_hosts` seed for an older file
                            (the last plan's host, stamped `since`);
                            `update_channel` (update spec 3.12.4): is_channel()
                            (exactly `stable`, or `branch:` + a ref matching
                            updates.REF_RE), refused otherwise, a hand-broken
                            value read back as `stable`
  keys.py                   SteamGridDB key sources (config -> env -> file), key file
  wake.py                   Wake-on-LAN (spec 3.18): parse_mac(), magic_packet(),
                            moonlight_hosts() / moonlight_entries() / find_host() /
                            moonlight_host() (Moonlight.conf's [hosts] group, the
                            flatpak path then the native one, read only: QSettings
                            INI, the MAC an @ByteArray of 6 bytes or empty, the
                            whole value quoted when a raw byte is a comma or a
                            bracket -- a device's 2026-09-23; hosts() reads the
                            entries once for its whole map),
                            send_magic_packet() (broadcast + every address Moonlight
                            knows, WAKE_PORTS; the SOCKET seam so no test sends a
                            datagram; run through asyncio.to_thread, since a hostname
                            among the addresses resolves with a blocking
                            getaddrinfo). Moonlight's CLI has no wake action
                            (list / quit / stream / pair only), so the plugin sends
                            it. But every one of those actions wakes the host on
                            its own (ComputerSeeker calls NvComputer::wake() before
                            it looks; a magic packet captured 2026-09-23), which is
                            why no Moonlight command ever runs unasked (Decision 66)
  events.py                 parse_line(), restart_decision(), next_pending()
  cdp.py                    the Chrome DevTools Protocol client over Steam's CEF
                            debugger (spec 3.20.2; the port Decky injects through):
                            DEBUGGER, targets() (one GET of /json/list),
                            Session (a stdlib websocket: handshake, masking, the
                            three length forms, fragments, ping, close; evaluate()
                            = Runtime.evaluate returnByValue + awaitPromise, an
                            EvaluateError on a thrown exception; navigate() =
                            Page.navigate, the tab reset's, an errorText reply
                            DebuggerUnavailable; both over one _call), the CONNECT /
                            TARGETS seams the tests replace, as wake.SOCKET is;
                            DebuggerUnavailable (a ConnectionError) for a refused
                            port, a timeout, a closed socket and a CDP-level error
                            reply (a context destroyed by a navigation), which the
                            fetch retries. The one module that talks to the port
  sgdbpage.py               the key fetch (spec 3.20.3): SGDB_HOST / SGDB_API_PAGE /
                            STEAM_OPENID_HOST / KEY_RE, the JS snippets one per page
                            state (JS_PAGE, JS_LOGIN_LINK, JS_NAVIGATE,
                            JS_OPENID_SUBMIT, JS_OPENID_FORM, JS_KEY, JS_GENERATE) so
                            a SteamGridDB redesign is a one-file change, the failure
                            texts, fetch_key(targets, connect, stop, clock, on_state)
                            -> the key (pure over the seams; raises
                            FetchFailed(code, message, detail)): waiting -> login
                            (the link's host and realm checked, one navigate) ->
                            steam-sign-in (one submit, Decision 60) / steam-login
                            (the user types, the form is polled) -> reading (one
                            navigate to the API page per URL, JS_KEY once complete,
                            JS_GENERATE once, Decision 61, and never while a code
                            element shows nor on a Regenerate / new key / Revoke
                            control, Decision 63; a complete document at the API
                            URL without the page's body, JS_API_BODY, asked
                            before JS_GENERATE so nothing on it is clicked, is
                            not judged: polled API_PAGE_GRACE_S (per visit to a
                            complete API page), reloaded once per fetch, polled
                            again, then TEXT_API_NOT_LOADED, Decision 69
                            -- the page a failed attempt leaves in the tab, which
                            the frontend's open has not yet replaced when the
                            fetch first polls) -> done. A session per
                            poll, closed after it; only a `page` target on one of
                            the two hosts is ever evaluated in; the stop event's
                            wait() is the 500 ms poll, so a cancel lands within one.
                            reset_tab(listed, targets, connect, sleep) (Decision
                            70, run by start_sgdb_key_fetch after the port probe):
                            the page target on either host, the tab a previous
                            fetch left, gets a Page.navigate to RESET_URL
                            (about:blank; no script evaluated), and the listing is
                            re-read every RESET_POLL_S, RESET_POLLS times at most
                            (RESET_WAIT_S as a count), until it is off both hosts;
                            answers the host it was on -- also when a listing read
                            after the navigate fails, since the tab was blanked
backend/entrypoint.sh       the one CLI build step (strict): scripts/build_cli.py into
                            backend/out/, then a --version smoke run; also the Decky
                            store hook (/plugin/cli/src inside its container)
backend/Dockerfile          template's holo-base image, only for `decky plugin build`
scripts/build_cli.py        cli/src -> moonlight-steam-sync.pyz (zipapp, deflated,
                            `/usr/bin/env python3`, moonlight_steam_sync/ only: no
                            __pycache__ or egg-info), refusing a __version__ that is not
                            package.json's "version"
scripts/build_info.py       build.json (update spec 3.12.1): --kind release|branch --ref
                            --sha --run [--out], {schema: 1, kind, ref, sha, built_at,
                            run} in that order; refuses (one stderr line, nothing
                            written) a kind outside the two, a sha that is not 40 hex
                            digits or a run that is not ^[0-9]+/[0-9]+$ with exit 1,
                            then a ref outside
                            ^[A-Za-z0-9._/-]{1,100}$ with exit 3 (EXIT_REF_REFUSED:
                            ci.yml / release.yml skip build.json on it for a branch,
                            amendment A1; builds.yml fails, so a branch with a `+` or
                            an `@` cannot be published); CI writes it at the root
                            before package.py, never committed (.gitignore);
                            from_git(root) (amendment A5, for a build made outside
                            CI): {kind: branch, ref: the branch checked out, sha:
                            HEAD, run: null}, NoGitBuild unless root is the top of
                            a git checkout, on a branch, with nothing uncommitted
                            or untracked (`git -C root`, GIT_DIR and its kin
                            dropped from the environment), RefRefused for a name
                            outside the pattern; the branch is `symbolic-ref HEAD`
                            without BRANCH_PREFIX (`refs/heads/`), what
                            github.ref_name is, never `--short` (which answers
                            `heads/main` beside a tag named `main`); a failure of
                            git's own carries the first line of its stderr, or
                            that git did not run / did not answer; git's bytes
                            are read as UTF-8 with errors="replace" whatever the
                            locale, so a branch named in other bytes is a refused
                            name, never a UnicodeDecodeError
scripts/package.py          Docker-free zip: out/Moonlight-Sync.zip ("Moonlight Sync/");
                            OPTIONAL_ROOT_FILES (build.json) from the root when it
                            exists, 0644, after the five root files; without a root
                            build.json, build_info.from_git's, written into the zip
                            only (never to the root, so none goes stale), else no
                            build.json; a root build.json that is not a file is
                            never replaced by git's; one stderr line in every case
                            (from the root, from git, or why there is none)
src/index.tsx               definePlugin: events (sync_event / sync_done, sgdb_key_event /
                            sgdb_key_done), settings route, running-app watch, load()
src/instance.tsx            the Controller wired to callable / Steam / showModal / toaster;
                            the Steam seam's navigateToExternalWeb / navigateBack pass
                            @decky/ui's Navigation to steam.ts's openExternalWeb() /
                            leaveExternalWeb(); the UiPort's updater seams (update spec
                            §3.5): installer() = decky.ts's deckyInstaller(), net() =
                            one `fetchNoCors(url, {method: "GET", headers})` read into
                            an HttpAnswer (status, the four headers through
                            `headers.get`, text()), leaveSettings() =
                            Navigation.NavigateBack() (guarded); SETTINGS_ROUTE,
                            TITLES_ROUTE, UPDATES_ROUTE (`/moonlight-sync/updates`)
src/lib/                    pure modules (vitest)
  cli.ts                    every §3.4.6 event type, Result/Failure, Backend, makeBackend,
                            errorText (the §3.8 strings; the key fetch's `no-debugger` /
                            `cancelled` / `sgdb-page` / `timeout` are the backend's text
                            verbatim, `busy` kind `"key"` its own sentence; the
                            updater's frontend-only codes, update spec §3.6:
                            `update-unsupported`, `rate-limited` with "Try again
                            <timeUntil(retryAt)>" (errorText's optional `now`),
                            `network`, `bad-release`, which the staging answers
                            too; the staging's own, update spec §3.12.5:
                            `hash-mismatch`, `bad-zip` and `busy` kind `"update"`),
                            stagingErrorText() (a `stage_update` failure's text:
                            errorText's, except a `bad-release` with a message,
                            which is the backend's words for the user, first
                            letter upper-cased; the controller's staging is its one
                            caller, so the frontend check's texts stay errorText's),
                            the staging's types
                            (update spec 3.12.3: `stage_update` / `cancel_update`,
                            StagedUpdate, BuildInfo, CliVersion's `build`),
                            Settings' / SettingsPatch's `update_channel` and the
                            UpdateChannel type (`stable` | `branch:<ref>`),
                            SGDB_API_PAGE, KeyFetchState, SgdbKeyEventPayload /
                            SgdbKeyDonePayload (its failure `error` narrowed to
                            SgdbKeyFetchError) (spec 3.20)
  events.ts                 NDJSON parsing, lastOf/eventsOf
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
  state.ts                  AppState, Store, reducers (runs, counters, stream map),
                            `update` (the updater's releases / checkedAt / error, null
                            while off) and `updatePhase` (idle / checking /
                            downloading / asking),
                            `titlesEpoch` (bumped by a match-cache reset; a mounted
                            TitlesPage re-lists off it), `sgdbKey` (sgdb_key_state:
                            source + hint, never the key) and `keyFetch` ({state} of
                            the fetch in flight, else null), keyFetchOffered() (the
                            *Get key from SteamGridDB…* button: `none` / `file` only,
                            never `config` / `env`) and keyFetchText() (spec 3.20.4's
                            state texts),
                            wakeInfoOf() (a host's `wake` entry, any case),
                            cachedHostOf() (its `cached_hosts` entry, any case: the
                            host row's count until something asked, a sync's exit-3
                            *last seen*, the Titles page's stamp),
                            hostOptions() (the switcher's hosts: `known`, the active
                            one in front when it is not among them) and
                            hostRowView() (the panel's host, the user's decision of
                            2026-09-27: `switcher` only with more than one host,
                            `tone` ok / bad / unknown for the circle, `text` the
                            count -- the listing's, else the cached one, else
                            "never synced", "Checking…" during the first check --
                            and `error`, the status text with *last seen* (for a
                            host never listed "never synced", and that only
                            without the row, whose `text` says it already), only
                            when the host answered with one; nothing about what
                            other hosts have parked),
                            hostSynced() (`pending.synced_hosts` names the host, any
                            case; an unread `pending` counts as synced),
                            HOST_APPS / hostAppsFromStatus() (the panel's Desktop and
                            Steam Big Picture buttons, by Moonlight name, blind to
                            `hidden`), launchButtons() / launchCaption() (the panel's
                            icon launch row, Decision 67: Moonlight always, disabled
                            until the client shortcut exists, then each published host
                            app; the line under it names the focused one, else
                            Moonlight), clientLayoutCaption() (the line under the
                            layout row: whose layout, and the default's title);
                            an `entry.host_app` entry counts toward none of
                            stream / shortcuts / unmatched and is never in the stream
                            map (spec §3.14.1); the layout walk reads `entries`, not
                            the map, so the host apps and the client are walked too
  controller.ts             load order, runs, restart flow, hosts, settings actions,
                            the updater (update spec §3.6; UiPort's installer() /
                            net() / leaveSettings()): loadUpdates() (doLoad's last
                            step, after the finally, never awaited; skipped while off
                            and once `update` is set, so a load re-run after a failed
                            cli_version() does not ask twice; the empty state, then
                            checkUpdates(false) when the settings were read (a
                            failed get_settings asks nothing), update_check is on
                            and the loader is supported), checkUpdates(manual,
                            {fresh, quiet}) (nothing unless idle and on; no request
                            before a rate-limited retryAt, nor for Check now within
                            CHECK_MIN_INTERVAL_MS unless `fresh`, which toasts the
                            stored failure; checkReleases on channelOf(settings),
                            offerOf over installedOf(cliVersion) and that channel,
                            so a followed branch's new build is announced as a
                            release is; the automatic check toasts only an offer, a
                            manual one only its failure, a `quiet` one nothing; a
                            failure keeps the last releases; an epoch drops a check
                            that lands after the plugin went off; answers `checked`
                            / `failed` / `skipped`), updatesSupported(),
                            setUpdateCheck(), installUpdate(tag) (update spec
                            §3.12.5, in this order: refused with a toast while off,
                            during a run, the walk or a key fetch, when unsupported,
                            silently while not idle; on a branch channel a
                            `fresh, quiet` check first, whose failure (or a stored
                            retryAt) ends the install with its errorText, and whose
                            result without an offer for the tag with latestText's
                            text, the refusals asked again after it; the offer from
                            installable() then the channel's offerOf, else "That
                            version cannot be installed"; `downloading` and
                            stage_update(tag, digest, version | null, ref | null),
                            a failure toasted with stagingErrorText, `cancelled`
                            silently; stagedMatches() else bad-zip's text; then
                            `asking`, leaveSettings(), installer().request() with
                            installRequestOf(offer, staged), a toast when Decky did
                            not take it; `idle` in every path, a throw included; an
                            answer after the plugin went off lands nowhere, by the
                            same epoch as a check), cancelUpdate() (cancel_update()
                            while `downloading`, nothing otherwise; a refused cancel
                            toasted), setUpdateChannel(channel) (the *Channel*
                            picker, after the page's confirm: nothing for the
                            channel already selected or while not idle;
                            setSettings({update_channel}), a refusal toasted and no
                            check, else a `fresh` manual check of the new channel),
                            run() answers "An update is being installed" and
                            restartRow() starts nothing while `downloading` or
                            `asking`, i.e. during the install only:
                            `utilities/install_plugin` resolves once Decky has shown
                            its dialog, before the user confirms, so a run started
                            behind the open dialog is not refused (update spec 3.8),
                            setEnabled(false) cancels a download in flight
                            (cancel_update()) and clears `update`,
                            setEnabled(true) runs loadUpdates(). The updater calls
                            no backend callable but set_settings, stage_update and
                            cancel_update,
                            wakeHost() (spec 3.18: `wake_host` on the active host, a
                            toast either way, never held back),
                            refreshSgdbKey(), fetchSgdbKey() (spec 3.20.4:
                            `start_sgdb_key_fetch` first, a refusal toasted with
                            nothing opened, then navigateToExternalWeb(SGDB_API_PAGE);
                            a browser that cannot open cancels at once, quietly),
                            cancelSgdbKeyFetch() (the user is on the Artwork page, so
                            the done does not navigate back), onSgdbKeyEvent(),
                            onSgdbKeyDone() (navigateBack only when this fetch opened
                            the browser and no Cancel came since, *before* any toast;
                            ok: sgdb_key_state (a failed re-read falls back to the
                            payload's source + hint), the "SteamGridDB key saved (…hint)"
                            toast, then test_sgdb_key with its verdict toasted;
                            failed: its message toasted, nothing else),
                            loadTitles() (list_cached only, never a live list -- a
                            `moonlight list` wakes the PC, Decision 66; `syncing`
                            while a run is going; `status` only reaches the shared store
                            when no run is going, the page always gets its entries;
                            a host no sync planned for, hostSynced(), is `neverSynced`
                            with no backend call, whatever a *Check* or an add cached,
                            and the page shows its line and *Sync now*, no rows; the
                            line says it fills in only while a `sync` runs, since an
                            art or remove run never plans; the page re-loads when a
                            run starts and again when it ends),
                            checkHost() (the row's *Check* and nothing else: never on
                            load, panel open or the toggle; addHost() paints the row
                            from add_host's own count, no memo read -- PR 46's review),
                            reachFromRun() (a finished sync paints the host row: a
                            `plan` event is green with published + ignored, a stopped
                            sync included, exit 3 red with *last seen* from
                            `cached_hosts`; art / remove say nothing),
                            pinTitle, setIgnored, resetMatchCache() (Advanced's
                            *Reset match cache*: refused while off or while a run
                            is going, else `reset_match_cache`, a `titlesEpoch`
                            bump on success and a toast either way,
                            resetMatchCacheToast() for the wording),
                            streamPress() (the stream-map guard only, never inGame --
                            Decision 57, the user's 2026-09-22: Moonlight's UI handles a
                            stream already going; applyDefault when a default is set,
                            record, run; never an unset), chooseLayout() (a `null`
                            real appid = a host app or the client: picker only),
                            chooseClientLayout() (the panel's *Layout*, Decision 67:
                            the Moonlight shortcut's configurator; not held back by
                            inGame, and neither is openHostApp()),
                            inspectLayout() (one getConfig: url + title, or
                            no-controller / unselected / not-shareable),
                            setDefaultLayout(url, title) (spec 3.16.4: serialised on
                            its own chain, awaits a walk in progress *before* the
                            backend call, stores settings + pending, awaits a walk
                            that began *during* the call (it leaves the flag: doWalk
                            skips clearWalk when `defaultChanges` moved under it),
                            layoutWalk(), toasts the counts -- or the deferred text
                            when the walk resolved `null`; `null` clears and the walk
                            is the unset pass; not held back by inGame or a run),
                            layoutWalk() (WalkCounts, or `null` when `entries` is
                            null: the flag stays for the next load;
                            `walkTargets(entries)`, the default
                            read per target -> applyDefault, none -> unsetApplied;
                            picker clears the flag at once), reconcileLibrary() (spec 3.15, 3.17: after every
                            status that reaches the store -- load, run done, Titles,
                            Retry, the two settings -- never while a run is going;
                            serialised; differences only; the load's call waits up to
                            90 s for the shortcut list and runs *before* the walk;
                            an unloaded appid is skipped until next time; hiding and
                            the collection fail independently; `entries` and the run
                            guard are read *after* the wait), settleCollection()
                            (the shortcut collection: `collectionMembers` wanted,
                            removals limited to `removableAppids` -- real appids
                            always, this device's non-parked shortcuts only while
                            Stream shortcuts are shown -- deleted once empty but
                            never on a pass that added, since a just-added member
                            may be listed late; so a v0.4.0 collection loses its
                            owned games at the first load and a collection somebody
                            had under the name keeps its members),
                            retireCollection() (the setting turned off: wanted = []
                            with every `knownAppids` removable), `enabled` /
                            setEnabled() (spec 3.19: `set_settings({enabled})`,
                            then off: retireCollection -- only while the group
                            setting is on, a same-named collection made after
                            the group went off is the user's -- + a reconcile
                            that hides every entry; on: a reconcile and the
                            deferred walk, no checkHost; busy while a run is
                            going. Off, run() / setSettings() /
                            setDefaultLayout() / the restart row answer
                            DISABLED_FAILURE, loadTitles() answers its message,
                            streamPress() launches nothing, checkHost() skips,
                            doWalk resolves null with the flag kept; every
                            other entry point (pins, ignore, hosts, wake, the
                            host-app buttons, Choose layout) is UI-only: the
                            panel and the settings route hide them while off)
  layouts.ts                DEFAULT_LAYOUT_STRATEGY (the one switch), layoutStrategy(),
                            DEFAULT_LAYOUT_SCHEMES / isShareableUrl() (workshop://,
                            template://), defaultLayoutOf() (null under picker or unset),
                            the SteamInput seam (clearConfig optional, feature-detected),
                            isUnselected() (no URL, default://, or bSelected false),
                            appliedUrl() (`applied`, else a legacy `copied` url),
                            applyDefault() (the §3.16.3 rule: a selection the plugin did
                            not make is never overwritten; the real game is not an
                            input), unsetApplied() (explicit `applied` only; `cleared`
                            on a successful clearConfig), deckControllerIndexFrom() (by
                            type: the type string when the client has it -- final either
                            way -- else the enum), layoutControllerIndexFrom() (the
                            Deck's, else the active or only connected controller),
                            CONFIG_SELECTION_USER, the status texts, walkTargets()
                            (every non-parked entry, deduped) and the walk's timings
  layouts.test.ts           applyDefault's cases + idempotence, unsetApplied, the
                            shareable schemes, defaultLayoutOf, walkTargets over the
                            status fixture, the index by type, the strategy switch
  library.ts                spec 3.15 / 3.17, the pure half: STREAMING_COLLECTION (found by
                            name, no id stored), the LibraryPort seam, streamingMembers()
                            (the tab's tiles: the stream map's real appids + visible
                            published shortcuts; never the client, a host app, a
                            parked entry), streamingTabEnabled() (the group
                            setting alone: the tab is there in both hide states), collectionMembers() (the
                            fallback collection: shortcuts only, and only while
                            Stream shortcuts are shown), knownAppids() (the retire
                            set), removableAppids() (the reconcile's: shortcuts
                            only while the device keeps the collection, never a
                            parked one, so devices sharing shortcut appids do not
                            fight), hiddenPlan()
                            (`hidden` from status is the truth; *Hide Stream shortcuts*
                            governs Stream entries only, the client / host apps / parked
                            are hidden regardless; a visible entry is shown, which is
                            what unparks it; a third argument, `enabled`, false hides
                            every entry, spec 3.19), pluginEnabled() / DISABLED_TEXT
                            (the on/off toggle, spec 3.19: the `enabled` key, absent
                            reads on; streamingTabEnabled() is false while off;
                            DISABLED_TEXT is under the settings route's toggle only),
                            collectionDiff(wanted, current, removable)
                            (removes only removable members)
  contextMenu.ts            spec 3.16.5, the gear menu's lookup, pure: MODULE_MARKER
                            (an export reading `.LibraryContextMenu)`), WRAPPER_PATTERN
                            (`{navigator:t,instance:r,...e}`, `$` allowed in the
                            names), wrappersOf() over a module's exports (every
                            match, export order), menuClassOf() (the fake-rendered
                            element's type, a class with `render` and
                            MENU_CLASS_METHOD = `GetTargetApps`), findMenuClass()
                            (the first candidate that renders it); the measured
                            sources are in contextMenu.test.ts. Until 2026-09-23 the
                            lookup keyed on `().appDetailsSpotlight`, which the client
                            has in no component, so the item never appeared
  tabs.ts                   spec 3.17, the Streaming tab's pure half: STREAMING_TAB_ID,
                            findElement() (a React-element walk with no React),
                            templateOf() (the first built-in tab's element with a
                            `collection` prop: the grid to clone), isLibraryTabs()
                            (a `tabs` array is the library's, not Settings'),
                            footerOf(), syntheticCollection() (the Collection surface
                            over overviews: allApps / visibleApps / apps, read-only)
  tabs.test.ts              the walk, the template, the synthetic collection
  appPage.ts                the owned game's page, pure: streamRowIndex() (where the
                            Stream row goes in the page column's children: the index
                            of the child with `appDetailsClasses.AppDetailsOverviewPanel`,
                            else 1). The client's gamepad navigation sorts a column's
                            children by document position (`compareDocumentPosition`,
                            measured on a Deck 2026-09-26), and other plugins splice
                            their own children in at index 1, some drawn over the
                            header (ProtonDB Badges), so a row at a fixed index 1 was
                            focused in the wrong order whenever it patched last;
                            hasClass() (an element's `className` has the marker as one
                            whole class: the panel here, the InnerContainer column in
                            `libraryApp.tsx`)
  appPage.test.ts           the index with and without another plugin's child, before
                            and after; the fallback; hasClass
  join.ts                   the Titles page: list + status joined by name into rows
                            (badge, chips, match line, capsule), filters, Show parked,
                            pages of 50, applyPin; the Change match rows (candidateRows,
                            noMatchRow, matchSummary); the `host-app` kind (badge
                            `host app`, under *All* only, never unmatched, every
                            candidate `art only`) and layoutTargetOf(), whose
                            `realAppid` is `null` for a hidden host-app row;
                            layoutSourceOf() (any non-parked entry: what *Use as the
                            default layout* reads, and what the row's layout text is for);
                            the order (spec 3.21): a row's
                            `added` (status's time for its entry's name, own keys
                            only), TitleSort, titleSortOf(settings)
                            (`titles_recent_first`, absent = by name), sortRows()
                            (`recent`: rows with a time first, the latest on top,
                            ties and the rest by name; a new array), sortText() (the
                            headline's), addedText() ("added today 14:02")
  __tests__/join.test.ts    the join, every badge/chip, filters, sort, paging (fixtures)
  restart.ts                restartDecision() (the §3.9 table), modal text
  version.ts                version parsing, the CLI-missing / too-old row,
                            BUNDLED_CLI_RULE (About's text for when the bundled CLI
                            is installed, Decision U12's equal-version replace included)
  format.ts                 relative times (relativeTime(); timeUntil(), the future
                            form: "in 12 minutes", a missing or past time "in a
                            minute"), dateText(), the Last sync line
  steam.ts                  ownedApps() (a throwing `allAppsCollection` getter, as early
                            in the client's boot, is "not loaded yet"), currentSteamId3(), runShortcut(),
                            shutdownSteam(), watchRunningApps(), steamInput() over
                            SteamClient.Input (clearConfig only when the client has
                            ClearSelectedConfigForApp, unmeasured), controllerIndex() (ControllerStore or
                            controllerStore, else the guarded list watch; plus the
                            active-controller watch),
                            overviewLoaded(), showControllerConfigurator(),
                            libraryPort() (collectionStore: BIsHidden / SetAppsAsHidden,
                            userCollections / NewUnsavedCollection / AsDragDropCollection
                            / Save / Delete, every one feature-detected, none probed on
                            a device yet), openExternalWeb(nav, url) /
                            leaveExternalWeb(nav) (spec 3.20.4: NavigateToExternalWeb
                            [verify], else the measured SteamClient.URL.ExecuteSteamURL
                            of steam://openurl/<url>; then CloseSideMenus;
                            NavigateBack never throws) (globals only; `Navigation` is
                            passed in)
src/routes/libraryTabs.tsx  the /library patch (spec 3.17): digs from the route element
                            for a `tabs` array some tab of which renders a collection
                            (`isLibraryTabs`), patching the first component element
                            of each level's output on the way (afterPatch on a
                            function, wrapReactClass + prototype render on a class,
                            wrapReactType on memo / forwardRef; one WeakMap cache per
                            level, four levels at most), then injectStreamingTab():
                            appends {id, "Streaming", <StreamingTab template>, the
                            template's footer}, or removes it when the setting is off,
                            and activeTabFor(): the dig carries the rendering
                            component's props, and when the library page's `tab`
                            prop asked for the Streaming tab but the bar's
                            `activeTab` is another (the page validates the id
                            against its memoised tab array in its own render,
                            before the injection, and falls back to its first
                            tab), the bar element gets the Streaming id back.
                            Measured on a device 2026-09-22 (route element -> the
                            library home, which reads the route's tab id -> the
                            page with `tab` -> the tabbed page {tabs, activeTab,
                            onShowTab} behind an observer wrapper -> the tab row,
                            which renders and cycles over `tabs`); the dig stays
                            for a client that adds a level (DEVICE-CHECKLIST §10)
src/routes/libraryApp.tsx   the /library/app/:appid patch (routerHook.addPatch, afterPatch
                            on renderFunc, then on the returned element's
                            renderChildrenFunc, then createReactTreePatcher on the
                            app-details component -- the one with `overview` props -- whose
                            own output is the first tree that holds the InnerContainer;
                            renderFunc's output does not, found on device 2026-09-21),
                            written fresh; injects StreamButton directly before the
                            overview panel (`appPage.ts`'s `streamRowIndex`)
src/routes/libraryContextMenu.tsx  the library gear menu patch (spec 3.16.5, Decision 56):
                            the menu class is reached through its wrapper component
                            (findModuleChild over `contextMenu.ts`'s `wrappersOf`,
                            fakeRenderComponent on each candidate, the element's
                            `type`, checked by `menuClassOf`), its `render`
                            afterPatch'ed to append one keyed MenuItem, *Use as
                            Moonlight Sync default layout*, on a real game in the
                            stream map (reads the game's own selection) or a
                            non-parked entry's own page (`menuLayoutSourceOf`), for
                            the page in the menu's own `props.overview` (or a bare
                            `appid` prop); `copy` only. The scan is not on the boot
                            path: `ensureLibraryContextMenuPatched()` runs it once,
                            from the two route patches' first render, and never
                            again (@decky/ui's module map is filled once at init
                            and never sees a later chunk, so a retry would find
                            nothing new); an unrecognised client warns and is left
                            alone; markers, menu class and the `overview` prop
                            measured on the SteamOS box 2026-09-23, the item in an
                            open menu a device check
src/routes/tree.ts          Overview / TreeNode / isOverview, shared by the three
                            route patches
src/components/             adoptDefault (inspectLayout -> refusal toasts -> ConfirmModal
                            -> setDefaultLayout, shared by the Titles row, the gear
                            menu and the panel's *Make default*, each with its own
                            "no layout chosen yet" hint; the walk-running refusal),
                            QuickAccess (Decision 67: LaunchRow, the Moonlight /
                            Desktop / Steam Big Picture icon buttons on one line, the
                            caption under it following `onGamepadFocus` and back to
                            Moonlight's on `onGamepadBlur` (a blur clears only its
                            own key);
                            ClientLayoutRow, *Layout* (chooseClientLayout, hidden
                            when the client has no configurator) and *Make default*
                            (adoptAsDefault on the client, hidden under `picker`),
                            with clientLayoutCaption under it; *Sync now* has no
                            description; HostRow over `hostRowView`: with several
                            hosts a `Field` with `childrenContainerWidth="max"`
                            around a `Dropdown` (a Field's control column stops at
                            half the row otherwise, and DropdownItem has no such
                            prop), the circle and the count as its description,
                            `disabled` on the Field as on the Dropdown so the
                            whole row dims while busy, as the DropdownItem did;
                            with one host no row at all; an error's text in a row
                            of its own under the switcher, which draws the divider
                            the Field then leaves out; then *Check* + *Wake*
                            whenever the host is not known reachable, the latter
                            only when `wakeInfoOf` finds a MAC; UpdateRow, the
                            panel's very last row in the main panel and the
                            CLI-missing / too-old one (not the Retry panel, where
                            `cliVersion` is null and nothing can be offered, nor
                            during a run): *Update to X* over
                            `updateRowView`, opening UPDATES_ROUTE and closing the
                            side menus as the header's buttons do), SyncProgress,
                            RestartModal, SettingsPage (Host, Artwork, Titles,
                            Advanced, Updates, About; while off none of them),
                            UpdatesPage (update spec §3.7, §3.12.5: *Installed*,
                            *Channel* (a DropdownItem over channelsOf() on
                            channelOf(settings), disabled unless idle; a branch
                            asks first with a ConfirmModal through showModal,
                            "Follow <ref>?", as Advanced's confirms are shown;
                            *Releases* asks nothing; then setUpdateChannel()),
                            *Latest* with *Check now*, the offer's install button
                            (`Downloading…` / `Waiting for Decky…`), a *Cancel*
                            ButtonItem under it while `downloading`
                            (cancelUpdate()), *What's new in X* in About's log-box
                            style, *Check for updates automatically*, *Install
                            another version* over installable() / versionLabel();
                            only *Installed* and the unsupported text when
                            !updatesSupported(); no confirm of its own before an
                            install, Decky's dialog is it), HostPage (no MAC field since
                            2026-09-26: Moonlight's list is the one Wake source),
                            TitlesPage (the *Recently added* chip beside *Show
                            parked*: setSettings({titles_recent_first}), the rows
                            through sortRows() after the filter, each with
                            addedText() while it is on, the headline's sortText(),
                            during a sync only for `recent`;
                            layout text; the *Layout* menu:
                            *Choose layout…* and *Use as the default layout*, which
                            inspects, toasts the refusal texts or confirms), ChangeMatchModal,
                            Pill, StreamButton (renders only when streamMap has the
                            appid; the layout line only while a default is set), ArtworkPage
                            (the key field over the store's `sgdbKey`; in the `none` /
                            `file` states *Get key from SteamGridDB…* and its
                            ConfirmModal with spec 3.20.4's text; while a fetch is in
                            flight the field says keyFetchText() and *Cancel* stands
                            where *Save* / the button were),
                            StreamingTab (the tab's content: cloneElement of the
                            template with a syntheticCollection of the loaded
                            streamingMembers, live from the store, inside its own
                            TabErrorBoundary, keyed on the member set so a new
                            collection retries the grid; the nothing-to-show line
                            and the grid's error are each a Focusable with
                            `focusableIfNoChildren` and a no-op `onActivate`
                            (either suffices), since a panel with nothing
                            to focus is skipped under gamepad navigation and the
                            tab with it -- reported 2026-09-22, cause unmeasured;
                            libraryTabs.tsx logs the bar's shape once and every
                            `onShowTab` call for the §10 report),
                            AdvancedPage (*Default controller layout* + *Clear*
                            with its confirm, *Hide Stream shortcuts* and *Streaming
                            tab* (the `streaming_collection` key; its text adds the
                            shortcut collection when Stream shortcuts are shown; never
                            disabled, the tab needs no client call), *Reset match
                            cache* (a ConfirmModal, then resetMatchCache(); disabled
                            while a run is going), AboutPage (its rows, *Decky
                            Loader* = `loader_version`, *Bundled CLI install* =
                            version.ts's BUNDLED_CLI_RULE, *Built from* =
                            updates.ts's builtFromText over `cli_version().build`
                            and, when there is one, *Commit* = its whole sha;
                            the log tail),
                            EnabledToggle (spec 3.19: the *Enable Sync* on/off
                            ToggleField, at the top of the panel in every state
                            and, while off, the whole settings route; no
                            description on the panel, DISABLED_TEXT on the route
                            while off (`explainOff`); disabled while a run is going)
src/test/fixtures.ts        loads tests/fixtures for vitest
tests/                      pytest: fake_cli.py, fixtures/, conftest.py, test_*.py,
                            test_install_sh.py (install.sh end to end via
                            MOONLIGHT_SYNC_BASE_URL against a file:// fixture,
                            sudo/systemctl shimmed on PATH), test_cli_install_sh.py
                            (cli/install.sh the same way, HOME in tmp_path);
                            updatezip.py (build_zip(), good and hostile plugin zips,
                            and patch_central() for what zipfile never writes),
                            test_fetch.py, test_updates.py, test_backend_updates.py
                            (the staging, update spec 3.12.6)
.github/workflows/release.yml  entrypoint.sh (the CLI from cli/src) + doctor smoke +
                            package.py --require-cli; on a v* tag (which must be
                            v<package.json version>) Moonlight-Sync.zip,
                            moonlight-steam-sync.pyz and their .sha256 files attached to
                            one GitHub release; the build job also runs on pull_request
.github/workflows/builds.yml   branch builds (update spec 3.12.2): push / workflow_dispatch
                            / delete only, never a pull-request event; `gate` (publish
                            for main, a dispatch, or a branch whose build-<slug> release
                            exists; a release titled with another branch's name is
                            that branch's, amendment A2), `build` (release.yml's steps,
                            repeated), `publish` (the title checked again, the tag
                            moved to the commit built, the release made or edited as a
                            prerelease never latest, four assets then build.json),
                            `cleanup` (a deleted branch's release and tag, when its
                            title is that branch's)
```

PR-6 made `search` / `pin` / `unpin` / `set_ignored` real (the Titles page
and the Change match modal); PR-7 added the Stream button, the layout copy
and `layouts` / `record_layout`; PR-9 / PR-10 (spec §3.16) replaced the
copy with the default layout and `set_default_layout`, so every callable
is real. The UI pins with `match … --defer-art` only (Decision 8) and uses
no `unpin` yet (the spec's modal has no unpin action); the callable exists
for the contract.

**The default controller layout (spec §3.16).** One layout the user adopts
from a title they set up with Steam's own configurator (Titles → *Layout*
→ *Use as the default layout*: `inspectLayout` reads that title's
selection, refuses `autosave://` / `default://` / unselected with the
§3.16.5 texts, a `ConfirmModal`, then `setDefaultLayout`), stored by the
backend as `settings.default_layout` and put on every non-parked entry by
`applyDefault` -- on each Stream press, in the walk after a sync's restart
and at once when the default changes. **The one rule, exactly (§3.16.3): a
selection the plugin did not make is never overwritten.** `ours =
appliedUrl(record)` is what the plugin last set (`applied` from
`layouts.json`, or a legacy `copied` record's url, Decision 46); a selected
URL that is not `ours` is `kept` (hand-picked, edited in place after the
default landed, or the very title the default was adopted from), `ours ===
def.url` is `default` with no write, anything else (unselected, an offered
`template://`, or still `ours` while the default moved on) is set and read
back. The real game's appid is not an input any more. Clearing (Decision
51) runs the same walk as the unset pass: `unsetApplied` takes the plugin's
layout off entries whose explicit `applied` is still selected, through
`clearConfig` (`SteamClient.Input.ClearSelectedConfigForApp(appid, index)`,
**unmeasured**, feature-detected: without it the default is still cleared
and titles keep what they have); the legacy-`copied` fallback is never
unset. `copy_layouts` is a dead, still-valid settings key (Decision 47).
Two edges of `setDefaultLayout`: a walk that begins during its backend
call (the load's, once its wait for the shortcut list ends) passed its
flag check under the old default, so `doWalk` leaves the flag set when
`defaultChanges` moved under it and the change walks again after it; and
with `status` unavailable (`entries === null`) the walk is deferred
(`layoutWalk()` resolves `null`, the flag stays) and the toast says the
layout is applied, or taken off, once the titles have loaded (Decision
54) rather than counting a walk that never ran. *Use as the default
layout* is refused with a toast while `state.walking` (the Titles row
cannot say why, as Advanced's disabled *Clear* cannot either).

**The layout strategy switch (spec §3.10).** PR-7 was built before the PR-0
probes ran. `DEFAULT_LAYOUT_STRATEGY = "copy"` in `src/lib/layouts.ts` is
the one place the default lives; `settings.json`'s `layout_strategy`
overrides it per device (no UI). Probe V2 (does `SetSelectedConfigForApp`
with a `workshop://` id published for one app stick on a shortcut?)
ran on 2026-09-20 and **confirmed `copy`** -- with one correction: the call
takes five arguments, the last being the selection type
(`CONFIG_SELECTION_USER = 1`, what Steam's own configurator passes); with
four it returns normally and selects nothing. The same session found the
store global is `ControllerStore` (not `controllerStore`), that
`SteamClient.Input.RegisterForControllerListChanges` does not exist on that
client (so `watchControllers()` guards every registration), and that the
device had no Deck controller at all, which is why
`layoutControllerIndexFrom()` falls back to the active or only connected
controller. Should a later client break the set, flip the constant to
`"picker"` and rewrite the README's "Controller layouts" section; nothing
else moves. Under `picker` no Steam Input call is made anywhere
(`defaultLayoutOf()` is `null`, so the whole §3.16 feature is off and its
UI hidden, and the walk clears its flag at once); *Choose layout…*
(`SteamClient.Apps.ShowControllerConfigurator`, hidden when absent) is the
only layout affordance.

## Backend contract in one paragraph

Every callable returns `{"ok": true, …}` or `{"ok": false, "error": <code>,
"message": …}` (codes: `cli-missing`, `cli-too-old`, `cli-protocol`,
`cli-error`, `timeout`, `busy`, `owned-apps-missing`, `owned-apps-empty`,
`bad-request`, `io`, `no-mac`, `no-debugger`, `cancelled`, `sgdb-page`,
`network`, `bad-release`, `hash-mismatch`, `bad-zip`) and
never raises. Argv is `[python3, <installed cli>,
"--json", <subcommand>, …]` (`doctor`, `--version` and `art --help` have no
`--json`), `cwd` and `HOME` are the deck user's home, and the child gets
`MOONLIGHT_STEAM_SYNC_FROM_PLUGIN=1`. Every `sync`, `list` (live and
`--cached`: `list_apps`, `list_cached`, `check_host`, `add_host`) and
`status` call carries `--hide-host-apps` (`Backend._host_app_args()`, spec
§3.14), always and with no setting, like `--client-shortcut` /
`--park-unpublished`: the CLI writes `Desktop` / `Steam Big Picture` hidden
(kind `host-app`) and the panel's buttons replace the two tiles. The three
subcommands must agree, or `status` would call the hidden pair parked and
`list` would call them shortcuts; `search`, `match`, `art` and `remove` do
not take the flag. It is why the minimum CLI is 0.4.0 and not a capability
probe: an older argparse answers the flag with exit 2, which is also
`EXIT_STEAM_RUNNING`. The child never inherits
plugin_loader's PyInstaller `LD_LIBRARY_PATH` (`/tmp/_MEI…`, an older
bundled OpenSSL that breaks both `flatpak` and the CLI's `import ssl`):
`Backend._child_env()` restores `LD_LIBRARY_PATH_ORIG` or drops the `_MEI*`
entries, and any new subprocess the backend spawns must go through it. It
also sets `PYTHONUNBUFFERED=1`: the CLI prints its events without flushing,
and over a pipe Python block-buffers stdout, so `awaiting-steam-exit` would
otherwise arrive only with the exit, after the 60 s wait had already failed
(found on device 2026-09-21; `tests/fake_cli.py` deliberately does not flush
stdout either, so the suite fails without the variable). Long runs (`start_sync`,
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
finished. `synced_hosts` (`{<host>: <when>}`) gains the plan's host
whenever a `sync` reached its `plan`, whatever the exit, and never loses
one: the host cache cannot say "synced", since a *Check* or an `add_host`
writes it too. A `pending.json` from before the key reads as the last
plan's host alone (`settings._legacy_synced_hosts`). `restart_countdown_s` is 0-30 everywhere
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
{real_appid, result, url, when, applied}}}`, `result` one of `copied` /
`kept` / `unavailable` / `picker` / `default`; a broken file reads as
empty), and `start_remove_all` deletes the file on `commit.written`.
`real_appid` may be `null` for any result now (spec 3.16.2: the walk covers
entries with no Steam game behind them -- host apps, the client, a title
never matched -- not only *Choose layout* on a default host app).
`applied` is the last URL *the plugin itself* set on that shortcut,
computed by `record_layout` so no caller has to (spec 3.16.2, Decision
53): it is set to `url` on `default` *and* `copied` (both a URL the plugin
just set), kept on `kept` only when the kept `url` is the previous
`applied` (still the plugin's own selection, what the spec 3.10 copy
reports on a title it copied earlier) and cleared to `null` for any other
`kept` (a selection the plugin did not make), and carried forward unchanged
on `unavailable` / `picker`; a legacy `copied` record with no `applied` key
on disk migrates its `url` in as `applied` the first time it is touched
again (Decision 46), so the first walk after a default is set can move it.
The table held under the PR-7 frontend too, which recorded `copied` /
`kept` from the layout copy on every Stream press and walk until PR-10;
under `applyDefault` a `kept` never carries the plugin's own URL, so the
rule reduces to `null` there, and nothing writes `copied` any more.
`settings.json` has `default_layout`, `null` by default, else `{url, title,
when}`; it is changed only through `set_default_layout(url, title)`
(`@guarded`, no CLI, no busy guard), which needs no argument to validate
but `url`, when not `null`, must start with `workshop://` or `template://`
(`settings.DEFAULT_LAYOUT_SCHEMES`) and stay under 2048 characters, and
`title` under 200; `set_settings` refuses the key outright
(`"default_layout is changed with set_default_layout"`). Either a stored
url or a clear always sets `pending.layout_walk = true`, so the walk
resumes at the next load even if the plugin unloads mid-write, and a
hand-broken `default_layout` value reads back as `null` rather than
failing `get_settings`. `copy_layouts` stays in `DEFAULT_SETTINGS` and
`_validate_setting` for an older `settings.json` or frontend and is read
by nothing (Decision 47).
`stop_sync` and `unload` also cover the moment between the busy guard and
the spawn: they flag the run, the SIGINT goes out as soon as its child
exists, and a run the signal killed before the CLI printed anything is
reported as exit 130 rather than as a protocol error.
`reset_match_cache()` (Advanced's *Reset match cache*, the user's decision
of 2026-09-23) needs no CLI but shares the busy guard in both directions,
like `pin`: it deletes the CLI's `matches.json` whole (`match_cache_path()`:
`$XDG_CACHE_HOME` from the child's env, else `<home>/.cache`, then
`moonlight-steam-sync/matches.json`, the CLI's own `cache_dir()` rule), pins
included, never edits it, leaves `hosts/` alone, and answers `{removed,
titles, pins}` (a missing file is `removed: false` and still `ok`; a broken
one counts as empty and is deleted all the same). The frontend toasts the
counts and bumps `titlesEpoch`, so a Titles page still mounted re-lists (a
fresh one lists on mount); the next `sync` re-resolves every title. The
button is disabled while a run is going; a `match` still in flight is only
caught by the backend's busy answer (the frontend has no signal for it).
The Titles page's *Recently added* order (spec 3.21, the user's
decision of 2026-09-28) is the plugin's own record, since nothing
else has one: the CLI keeps no time per shortcut, `shortcuts.vdf` has
none, and a run's `title` events name the titles that were already there
too (the art phase covers every owned entry), so they cannot say what a
sync added. `status()` therefore carries an additive `added`
(`{<Moonlight name>: <iso time> | null}` over the entries it just read,
never the client entry nor a `host_app` one: a new host's `Desktop` /
`Steam Big Picture` would otherwise sit among the games its first sync
added, PR 68's review) and keeps it in `added.json`
(`Backend._note_added` -> `Store.note_titles`): a name seen for the first
time is stamped with `iso_now()`, a known one keeps its time, one that is
gone is dropped (so a title removed and synced again counts as added
again), and the very first call, with no readable file, records every
name with `null`, "there before the plugin kept track". The stamp is the
first `status` after the sync that added the title (the frontend asks for
one when a run ends and at every load), not the commit itself; the titles
of one sync share it. A kind flip keeps the name, so a replaced entry is
not new; a sync run from the bare CLI is stamped at the plugin's next
`status`. The record is by Moonlight name, across hosts, not per host or
per entry, which is the shortcut's own identity (its appid is `crc32(Exe
+ AppName)`): `status` lists every host's entries, so a name another
host's parked entry already carries is known, and the active host
publishing it later unparks that entry and stamps nothing. Nothing is
awaited between `note_titles`'s read and its write, so two `status` calls
in flight at once (`refreshStatus` and `loadTitles` when a run ends with
the Titles page open) record one after the other and the second keeps
the first's stamp. A file that cannot be written fails nothing (`status` answers
the times it has), a broken one reads as no file, and a failed `status`
records nothing. No CLI flag, event or file is involved (hard rules 1 and
7 stand). `settings.titles_recent_first` (default `false`,
`BOOL_SETTINGS`, a plain `set_settings` key) is the chip's state, so the
page reopens in the order last chosen; the frontend reads it through
`join.ts`'s `titleSortOf` and sorts with `sortRows` after the filter,
before the pages of 50. `tests/test_backend.py` holds the record (the
baseline, the stamp, the drop, a host app never stamped, two calls at
once, the unchanged file not rewritten, broken files, a refused write),
`__tests__/join.test.ts` the order, and
`controller.test.ts` that `loadTitles` hands `added` on (`{}` from a
backend without it or a failed `status`) and that the setting moves
nothing in the library.
The on/off toggle (spec 3.19) is one boolean, `settings.enabled` (default
`true`, `BOOL_SETTINGS` in `settings.py`, a plain `set_settings` key): the
backend knows nothing else of it, the frontend reads it everywhere it
touches the client (`pluginEnabled`), and a run started before the toggle
went off finishes on its own.
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
the backend makes no request of its own but the staging's download
(below), and the updater calls no backend callable but `set_settings`
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
The key fetch from the Game Mode browser (spec 3.20) needs no CLI and is
not under the runs' busy guard (Decision 62: no `matches.json` involved, so
a sync may run meanwhile and a fetch may start during a sync); it has its
own, `busy` with kind `"key"`. `start_sgdb_key_fetch()` probes
`cdp.TARGETS()` once (so `no-debugger` comes back here, before the
frontend opens the browser), resets the tab a previous fetch left on
SteamGridDB or Steam to `about:blank` (`sgdbpage.reset_tab` over the
probe's listing, Decision 70: the Game Mode browser's one tab outlives
`NavigateBack`, and without the reset the fetch's first polls read the
page the last attempt left there; a reset the debugger refuses is logged
and the fetch starts anyway), then runs `sgdbpage.fetch_key` in a worker
thread (`asyncio.to_thread`, a `threading.Event` for cancellation) and
answers `{ok, started}`; each state change is `sgdb_key_event {state}`
(never page contents) and the end `sgdb_key_done {ok: true, source, hint}`
or `{ok: false, error, message}` with `error` one of `no-debugger`,
`timeout` (180 s), `cancelled`, `sgdb-page` (the login page changed, no
key and no generate button, a thrown snippet, a redirect loop) or
`keys.KeyRefused`'s codes (`set in config.toml`). The key is handed to
`keys.set_key` and nowhere else: not a result, an event, a log line or an
exception message (`FetchFailed.detail` is fixed text or, for a thrown
snippet, the error's class name alone; `_redact` covers the rest); a failed
or cancelled fetch writes no file. An unavailable debugger is retried for
`DEBUGGER_RETRY_S` from the first poll on (the port was already probed; the
frontend's own navigation can destroy the page context under that poll).
Every exit frees the `"key"` guard: a probe that raises anything, and a
`keys.set_key` that raises something other than `KeyRefused` / `OSError`
(`io`, "Could not save the key"). `targets()` goes through an opener
that ignores `http_proxy`, and an answer that is not HTTP is
`DebuggerUnavailable`. `cancel_sgdb_key_fetch()`
sets the event (`{ok, running}`), `unload()` cancels the same way and waits
`KEY_FETCH_UNLOAD_WAIT`. The queued state emits are awaited before the
done emit, so the frontend sees them in order. The frontend (PR-14)
opens `SGDB_API_PAGE` in the Game Mode browser only after
`start_sgdb_key_fetch` answered `ok`, navigates back on `sgdb_key_done`
before any toast, and follows a success with `sgdb_key_state()` and
`test_sgdb_key()`.
Wake-on-LAN (spec 3.18) needs no CLI and no busy guard: `hosts()` carries
an additive `wake` map (`{<host>: {mac, source, addresses}}` over the known
hosts plus the active one when it is not among them, from Moonlight's own
`Moonlight.conf` entry, read once per call, `source` always `"moonlight"`;
a host Moonlight has no MAC for is absent, and the panel shows no *Wake*
for it); `wake_host(name)` sends the magic packet to the broadcast
address and every address Moonlight knows for the host on `WAKE_PORTS`, in
a worker thread (a hostname among them resolves with a blocking
`getaddrinfo`), answers `{host, mac, source, sent}`, `no-mac` when
Moonlight knows no MAC, `io` only when not one datagram went out, and
drops the `check_host` memo so the next *Check* asks. The Host page's MAC
field, `set_wake_mac` and the `wake_macs` setting went on 2026-09-26 (the
user's decision: rely on Moonlight's settings alone); `wake_macs` is a
retired key (`settings.RETIRED_SETTINGS`): left in an older file, never
reported, refused by `set_settings`. Sending proves nothing about the PC,
so the frontend's toast says to Check in a minute rather than polling.
**No Moonlight command runs unasked (Decision 66, the user's
2026-09-23).** Moonlight's command line sends a magic packet on every
`list` and `stream` (its ComputerSeeker wakes the matching host before it
looks; captured on the LAN, the PC came up), so the plugin runs a
Moonlight command only on the user's *Check*, on `add_host`, on a run and
on a Stream press: `check_host` is not called at load, on panel open, when
the toggle goes on, after a library retry or after an add, and the Titles
page reads `list_cached` only (`list_apps` stays for the contract, called
by nothing in the frontend). A finished sync and a made-active add each
stand in for the check (`reachFromRun`, `add_host`'s `count`). The CLI's
`status`, `host show`, `match`, `search`,
`art` and `remove` never run Moonlight and are unaffected.
The staging (update spec 3.12.3, PR-U4a) needs no CLI; since PR-U4c
every install goes through it (update spec 3.12.5), a release's included,
and Decky is handed its `file://` artifact, never a URL. `cli_version()` carries an additive `build`: the plugin
zip's own `build.json` through `updates.read_build` (the known keys only),
`null` without one. `stage_update(tag, sha256, version=None, ref=None)`
checks its whole request first (`tag` against `TAG_RE` and not `.` / `..`,
`sha256` 64 hex digits, exactly one of `version` (it parses) and `ref`
(`REF_RE`), strings only: else `bad-request`, with nothing touched or
spawned), then the busy guards (a run or a `match` as `_busy()` answers,
`busy` kind `"key"` for a key fetch, kind `"update"` for another
staging; the staging's own guard is not the runs'), then downloads into
the runtime directory (`DECKY_PLUGIN_RUNTIME_DIR`, `~/homebrew/data/Moonlight
Sync`, `update/` and `update/staged/` created `0700` on demand; never the
plugin directory, hard rule 12): the release's `Moonlight-Sync.zip.sha256`
sidecar into `staged/sidecar.txt` (removed after every staging), which
must name `sha256` (Decision U20: GitHub's digest and the uploaded
checksum agree; a 404 or an unreadable one is `bad-release`, one naming
another hash `bad-release` "A new build is being published. Try again in a
minute" for a `ref`, "the release's checksums disagree" for a `version`);
then the zip to `staged_path(sha256)` unless a regular file there already
hashes to it (a file that does not is removed), with `--sha256`, the
downloader's reported hash compared again; then `validate_zip` either way
(`bad-zip` with its message, the file removed; a release's own
`build.json` must name `v<version>`). `hash-mismatch` passes
through, `too-large` is `bad-zip`, an HTTP 404 `bad-release`, any other
HTTP status or a network failure (a body cut short included) `network`,
a downloader still running after its socket timeout plus
`FETCH_ANSWER_GRACE` (10 s) is killed and answers `timeout` with that
limit as `timeout_s`. The answer is `{ok, artifact:
"file://" + <absolute staged path, raw>, hash, build, version}`: the path
is always `staged_path`, never a string from a response. The downloader is
`fetch.py`, run as `[<system python3>, "-I", fetch.py, options, "--", url,
dest]` through `_child_env()` (the system interpreter has SteamOS's CA
store, Decky's PyInstaller one does not, spec 2.5; `-I` keeps the
package's directory off `sys.path` and ignores `PYTHON*` variables), its
stderr discarded, its one stdout line read; it only opens `https` URLs on
`github.com` or `*.githubusercontent.com` (every redirect checked before
it is followed, five at most, no proxy, TLS verified), and `--allow-file`
(a `file:///` URL) is passed only when the backend's `update_source` says
so, which only the tests' does. Every step is logged with the tag, a size
and the first 12 hex digits of the hash, never a query string.
`cancel_update()` kills the downloader (`{ok, running}`) and the
interrupted `stage_update` answers `cancelled`; `unload()` does the same,
waits for the child and removes its part file; either one landing while
the downloader is being spawned kills it the moment it exists. Every exit releases the
guard. `startup()` runs `updates.cleanup` (staged files older than an
hour, every `*.part`; creates nothing). `install.ensure_installed`
replaces an installed CLI of the bundled one's version whose bytes differ
(`replaced`, Decision U12: a branch build carries the last release's
version); a newer installed CLI is still kept and nothing is downgraded.
The frontend (update spec 3.12.5) calls `stage_update` with exactly one
of a release's `version` and a branch build's `ref`, the other `null`,
checks the answer against its offer (`stagedMatches`: the hash, a
release's version, a branch build's `build.json` ref), and hands Decky
the answer's `artifact` and `hash` with, for a branch build, the version
built from the answer's own `version` and `build`; `decky.ts` accepts
only `file://` and an absolute path ending in the `staged_path` name of
that hash. A `bad-release` answer's message is shown as it is
(`stagingErrorText`); `cancelled` is shown as nothing.

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
- `ci.yml` has no probes job: the kit's tests, plugin build and runner
  smoke test run only in `probe.yml`, path-filtered to `probes/**`.

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
  the real seam over stubbed globals; the route patch, the button, the
  *Layout* menu and `ClearSelectedConfigForApp` itself are device checks,
  not unit tests. The key fetch's frontend (spec 3.20.4) runs over the
  same fake backend in `controller.test.ts` (an `order` log interleaves
  backend calls, the fake Steam seam's `open:` / `back` navigations and
  toasts, so the step order is asserted), `state.test.ts` holds the
  button's presence per key source (`keyFetchOffered`), and
  `steam.test.ts` the `NavigateToExternalWeb` / `steam://openurl/`
  fallback; the modal, the browser and `NavigateBack` are device checks
  (DEVICE-CHECKLIST §14).
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
  (`package.json`'s, spelled once more as the CLI's `__version__` and in no
  script or workflow; the match is anchored, so a third-party pin that
  shares the number does not count), the CLI's empty `dependencies`, the
  placeholder SteamGridDB key (`tests/fixtures/sgdb/api.html`'s) spelled nowhere else under `tests/`
  but that file, and, over a whole browser fetch, the key in no result,
  event or log line (hard rule 4 for spec 3.20); and hard rule 12's names
  under `src/` (`files_naming`, comments and tests included):
  `confirm_plugin_install` nowhere, `DeckyBackend` and `utilities/` only in
  `lib/decky.ts` and its test, `api.github.com` only in `lib/updates.ts`
  and its test, `fetchNoCors` only in `instance.tsx`, the repository's
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
- The key fetch (spec 3.20) never opens a socket in a test: `conftest.py`'s
  `fake_browser` fixture installs a `FakeBrowser` as `cdp.TARGETS` /
  `cdp.CONNECT` (the Game Mode browser as the seams see it: the page
  target once `open_page()` ran, beside `SharedJSContext`, Big Picture and
  ad `iframe` targets; a session's `evaluate` runs the snippet's mirror
  over the current page and then plays the site: the API page bounces to
  `/login` until signed in, the login link goes to Steam, the OpenID
  submit signs in and returns home, *Generate* gives the account a key,
  *Revoke* is recorded and must never happen; `answers` scripts one
  snippet's value or exception, `on_poll` changes the browser per poll,
  `loading_polls` makes a fresh page read as loading first, `api_fixture`
  names the API page's fixture, or a list of them consumed one per load
  with the last standing). The pages are
  `tests/fixtures/sgdb/*.html` (`login`, `openid`, `api`, `api-no-key`,
  `api-revoke-only`, Decision 63's `api-hidden-key` / `api-regenerate`,
  and Decision 69's `api-unrendered` / `api-stray-generate`, complete
  documents at the API URL without the page's body, the latter with a
  *Generate* control that must never be pressed, hand-written from spec
  3.20.1 with the placeholder key), parsed by `tests/fakedom.py`: a minimal DOM (`querySelector` /
  `querySelectorAll` over tag, class, id, `[attr=v]`, `[attr*=v]`,
  descendants and lists; `textContent`, `innerText`, `value`, `href`, a
  recording `click()`, `readyState`, `location.href`) and `evaluate(js,
  document)`, the snippets' Python mirrors: the same control flow with
  every selector and regex literal read out of the snippet's own text, so
  a changed selector changes what the mirror queries and a changed shape
  fails. `tests/test_sgdbpage.py` drives `fetch_key` over the fake with a
  fake clock whose `wait()` is the poll (one test per state-table row and
  per failure, the four rules, cancellation, the 180 s timeout) and the
  backend's thread with `POLL_INTERVAL_S` patched short (the events, the
  0600 key file, `busy`, cancel, `unload`, a refused key, the busy-guard
  independence, the stale tab blanked before the fetch's first poll and a
  refused reset that still starts the fetch); `reset_tab` itself over the
  fake (a tab on either host blanked with one `Page.navigate` and no
  evaluate, no tab or another host untouched, the listing's wait). `tests/test_cdp.py` runs the real websocket client
  against a loopback fake debugger in a thread (handshake, masking, the
  126- and 127-length forms, a fragmented reply, a ping, close, a
  protocol error, a timeout, `navigate()`'s `Page.navigate` with its
  `errorText` and error replies) and `targets()` over a stubbed `urlopen`.
- The staging (update spec 3.12.6) never opens a socket either: its three
  modules use `conftest.py`'s `no_network` fixture (`pytestmark`), which
  fails a test on any `socket.connect` / `connect_ex` off the loopback.
  `tests/updatezip.py`'s `build_zip(path, *, version, name, top, flags,
  build, extra, omit)` writes a zip shaped like `package.py`'s; hostile
  entries go in `extra` as `(ZipInfo, data)`, and `patch_central()`
  rewrites a central-directory record for what `zipfile` never writes (an
  encrypted flag, sizes that lie). `tests/test_fetch.py` runs the real
  `fetch.py` with `sys.executable -I` against `file://` URLs
  (`--allow-file`): the download and its hash, `--sha256` right and wrong,
  `--max-bytes`, a missing file (http 404), a stale part file, a symlink
  at the part path, `DEST` untouched and no part file after every failure,
  `bad-url` for `http://`, other hosts, `api.github.com` and `file://`
  without the flag, bad arguments; exactly one stdout line, exit 0 and an
  empty stderr every time. It loads the script as a module
  (`spec_from_file_location`) for `check_url` (the accepted and refused
  URLs), `RedirectGuard` called directly with fake requests (a hop off the
  allowlist, to `http`, to `file:` with the flag on, the five-hop limit),
  `build_opener`'s handlers and schemes, `run()` over fake openers (a
  refused redirect, an HTTP error, a query string that never reaches the
  output, `Content-Length` over the limit refused unread, the count
  deciding, a body cut short (`IncompleteRead`, an `OSError`) as `network` and a failed write as `io`, an uncaught exception as its class name) and a real
  `OpenerDirector` over a fake `https_open`, which proves urllib asks the
  guard before it opens a hop. `tests/test_updates.py` has one test per
  `validate_zip` rule and `read_build`, `asset_url`, `parse_sidecar`,
  `staged_path` and `cleanup` cases. `tests/test_backend_updates.py`
  stages from a `file://` tree through an `updates.Source(download_base,
  allow_file=True)` with `python=sys.executable`: end to end for a release
  and a branch, the argv, every `bad-request` (nothing spawned or
  created), the reuse and the re-validation of a staged file, the
  sidecar's failures, `hash-mismatch`, `bad-zip`, a download cut short
  (`network`), a downloader that says nothing (`io`) or hangs (`timeout`,
  `fake_python` shims, `FETCH_ANSWER_GRACE` patched short), each busy
  kind, the guard released after an exception, `cancel_update` and
  `unload` killing a downloader stuck mid-zip (its part file gone) and
  landing during the spawn (`asyncio.create_subprocess_exec` patched to
  cancel first), the startup cleanup, `cli_version()`'s `build`, and the
  plugin directory byte-identical after a staging. `no_network` only sees
  the test process: `test_fetch.py`'s `run_script` first proves from the
  argv that the real script cannot reach the network (arguments refused
  before any URL is used, or every URL a `file:///` one under
  `--allow-file` or refused by `check_url` in-process). A failed `close`
  of the part file is `io` and closes nothing twice.
  `tests/test_install.py`
  holds the `replaced` case (equal version: equal bytes kept, other bytes
  replaced atomically, a failed replace leaving the file, a symlink
  replaced by the file itself with its old target untouched), and
  `tests/test_hard_rules.py` that `fetch.py` imports the standard library
  only and parses as Python 3.11, that nothing under `py_modules` or
  `main.py` imports it, that no backend file turns TLS verification off
  (`CERT_NONE`, `_create_unverified_context`, `check_hostname = False`, a
  `verify_mode` assignment), and that `main.py` names neither
  `update_source` nor `allow_file` and no `py_modules` file says
  `allow_file=True`.
- `tests/test_entrypoint.py` runs `backend/entrypoint.sh` from a sandbox
  copy of `backend/`, `scripts/build_cli.py`, `cli/src` and a
  `package.json` (the zipapp's entries, mode and `--version`; a version
  mismatch, a missing source) and holds the real CLI's `__version__` to
  `package.json`'s; `tests/test_package.py` builds a fixture tree and checks
  the exact zip entry list and modes, with a root `build.json` and without
  one, and that `fetch.py` and `updates.py` ship (0755); its `checkout`
  fixture commits the tree to a scratch git repository on `main` (the
  machine's git configuration shut out), for the `build.json` a build
  outside CI gets: the branch and `HEAD`, `run` `null`, read back through
  `updates.parse_build`, the root's file (or a directory of its name)
  winning over git, a tag named `main` beside the branch, and none for an
  edited, untracked or staged change, a detached `HEAD`, a refused branch
  name (one in UTF-8 and one in Latin-1 bytes too, under `LC_ALL=C` with
  `PYTHONUTF8=0`), a tree inside another checkout, no checkout, a checkout git calls
  dubious (`GIT_TEST_ASSUME_DIFFERENT_OWNER=1`, git's own message quoted)
  and no `git` on `PATH`; each asserts the stderr line.
  `tests/test_build_info.py` runs `scripts/build_info.py` with
  `sys.executable` in `tmp_path`: the keys and their order, `built_at`'s
  form, `--out`, and every refusal (one stderr line, nothing written; exit
  3 for the ref alone, 1 for a bad kind, sha or run, the ref bad too or
  not, 2 for argparse).
- `tests/test_hard_rules.py` also reads `.github/workflows/builds.yml` as
  text (no YAML parser is a dev dependency): the triggers are exactly
  `push`, `workflow_dispatch` and `delete` and no line outside a comment
  names `pull_request`; the top-level permissions are `contents: read` and
  `contents: write` is on `publish` and `cleanup` only; no workflow's
  `run:` script contains a `${{ }}` expression; the slug line is spelled
  identically in `gate` and `cleanup`, every `tag=` is `build-${slug}`
  and guarded before any `gh` call, and that line and guard run under
  `bash` over sample branch names (`café` is `build-caf-` under
  `C.UTF-8`, the runner's locale); every script passes `bash -n`; and
  the previous `build.json` is deleted before the first upload and the
  new one uploaded in a step of its own after the other four.
  It also holds `ci.yml`'s and `release.yml`'s "Write build.json" steps
  identical and runs that step under `bash` in `tmp_path` over a copy of
  `build_info.py` and a stale `build.json`: a branch (with `BUILD_SHA`,
  never `GITHUB_SHA`) and a tag are written, a refused branch name is a
  notice with no `build.json` left, a refused tag or a bad sha fails. And
  it runs `gate`'s, `cleanup`'s and `publish`'s scripts under `bash`
  with a fake `gh` on `PATH` (`FAKE_GH`, a shell script logging every
  argv: `release view` answers `FAKE_GH_RELEASE`, `none`, `fail` or
  `title=<name>`, or with `--json assets` the names in `FAKE_GH_ASSETS`;
  a GET through `api` answers `FAKE_GH_REF`, `missing` as gh's `HTTP
  404`, `exists` or `fail`; every write succeeds) and the `GITHUB_*`
  variables set:
  `publish` from the `GITHUB_OUTPUT` file for `main` with and without its
  release, a branch without one, with its own and with another branch's
  (amendment A2), a dispatch or `main` on another branch's tag failing, an
  API failure failing, a title that tries a workflow command shown
  defanged; `cleanup` deleting only its own release (the argv log), none
  and another's left alone, an API failure failing; `publish`'s five
  steps run in order by name, stopping at the first failure as the job
  does, with the whole argv log compared: a first build (`POST git/refs`
  with `refs/tags/build-<slug>` and the run's sha, `create --verify-tag`,
  no delete-asset), a republish (`PATCH` with `force=true`, `edit`
  without `--verify-tag`, the old `build.json` deleted before the
  uploads, `build.json` last in a call of its own), another branch's
  title (no `api` call and no write, and the create-or-edit step alone
  refusing too), an API failure (nothing after it); every tag in every
  call is `build-<slug>`.
- The CLI's own suite is `cli/tests` (see `cli/AGENTS.md`, "Testing"): it
  has its own conftest and fakes, runs apart from `tests/` (`python3 -m
  pytest cli`), and `cli/tests/test_release_zipapp.py` builds through
  `scripts/build_cli.py`.

On-device checks are not merge criteria; they are collected in
`DEVICE-CHECKLIST.md` (arrives with PR-8).

## CI and release outline

- `.github/workflows/ci.yml` (push to `main`, every `pull_request`):
  `shellcheck` (`sh -n` on `install.sh`, `backend/entrypoint.sh` and
  `cli/install.sh`, then `ludeeus/action-shellcheck` over the whole tree),
  `frontend` (pnpm 9, Node 20: typecheck, lint, vitest, build, upload
  `dist`), `backend` (Python 3.13.5: ruff over the whole repo, `cli/`
  included; pytest `tests/`), `cli` (Python 3.11 -- the CLI's floor -- and
  3.13.5: `pip install --no-deps -e ./cli`, pytest `cli`, then
  `scripts/build_cli.py` and the zipapp's `--version` and `doctor` smoke
  runs), `package` (after all three: `backend/entrypoint.sh`, then
  `scripts/build_info.py` -- `release` and the tag on a tag, else `branch`
  and `github.head_ref || github.ref_name`, with the sha
  `github.event.pull_request.head.sha || github.sha` (a pull request's
  head commit, not the merge commit `GITHUB_SHA` names there, amendment
  A4), both passed through `env:`; on a branch, `build_info.py`'s exit 3 (the name is outside the `ref`
  pattern) is a `::notice::` and a zip without `build.json`, since this
  workflow publishes nothing from a branch (amendment A1), and any other
  failure fails; the step first removes any `build.json` at the root --
  then `scripts/package.py --require-cli` and the `Moonlight-Sync`
  artifact).
  When SteamOS moves to a new Python, change `3.13.5` in all three
  workflows (`ci.yml`, `release.yml`, `builds.yml`).
- `.github/workflows/release.yml`: the same frontend build, then
  `entrypoint.sh` (the CLI from `cli/src`, its `--version` smoke run), a
  `doctor` smoke run, `build_info.py` (the same step as `ci.yml`'s, text
  for text, so a release's zip
  carries `build.json` with `kind: release` and the tag; it is inside the
  zip, not a fifth asset), `package.py --require-cli`, and `sha256sum` of
  `Moonlight-Sync.zip` and `moonlight-steam-sync.pyz` against their bare
  filenames. On a `v*` tag it first checks the tag is `v` + `package.json`'s
  `"version"`, and the tag-gated `github-release` job attaches all four
  files to one release through an idempotent `gh release view || create` /
  `upload --clobber` step. The build job also runs on `pull_request` and
  `workflow_dispatch`, so it is exercised before any tag.
- `.github/workflows/builds.yml` (update spec 3.12.2): a rolling
  prerelease per branch, tagged `build-<slug>` (the branch's name with
  every character outside `[A-Za-z0-9._-]` replaced by `-`, cut to 80),
  titled with the branch's name. Triggers are `push` (every branch),
  `workflow_dispatch` and `delete`, **never `pull_request` or
  `pull_request_target`**, so code from a fork never reaches a release;
  top-level permissions `contents: read`. `gate` answers `publish=true`
  for `main`, for a `workflow_dispatch` and for a push to a branch whose
  `build-<slug>` release already exists (`gh release view`; "release not
  found" is `false`, any other failure fails the job), so a branch
  publishes once asked and from then on with every push (Decision U10); a
  dispatch on a tag fails. The slug is lossy (`a/b` and `a-b` are both
  `build-a-b`), so a release belongs to the branch its title names
  (amendment A2): `gate` reads the title (`--json name --jq .name`), a
  push to a branch whose tag another branch's release holds is `false`
  with a notice, and `main` or a dispatch in that case fails the job
  naming the holder (delete that release or rename the branch). A title
  is text somebody chose: it is compared as a quoted variable and shown
  with every character outside `[A-Za-z0-9._/@+-]` as `?`. `build`
  repeats `release.yml`'s build job (Decision U11: same actions and versions, Python 3.13.5, no tag check),
  writes `build.json` with `branch` and the branch, and uploads the
  artifact `Moonlight-Sync-build` (the zip, the pyz, their sidecars,
  `build.json`). `publish` (`contents: write`) moves the tag through the
  API to the run's `GITHUB_SHA`, the commit built (`POST git/refs`, or
  `PATCH git/refs/tags/build-<slug>` with `force`) after reading the
  release's title again (another branch with the same slug may have
  published since the gate; a title that is not this branch's fails the
  job before anything is written, and the create-or-edit step checks it
  once more, so an edit never retitles another branch's release),
  creates the release or edits it with `--prerelease --latest=false` every time (so
  `releases/latest` keeps naming the newest `v*`), removes the release's
  previous `build.json` asset when the asset list (`gh release view --json
  assets`) has one (amendment A3: otherwise a republish, or a run
  cancelled mid-upload, would leave the last build's `build.json` beside
  new or half-replaced files; the list decides, so no `gh` error text is
  relied on, and any failure fails the job), uploads the four files with
  `--clobber` and then, in a step of its own, `build.json`: `--clobber`
  deletes an asset before uploading its replacement, so `build.json`
  arriving last says the four beside it are its own. `cleanup` (`contents:
  write`, `delete` events of a branch only) runs `gh release delete
  build-<slug> --cleanup-tag --yes` only when the release's title is the
  deleted branch's name; no release, or another branch's, is a success
  that deletes nothing. Every
  branch name, ref and event field reaches a script through `env:` as a
  quoted variable, never as a `${{ }}` inside `run:`; the slug is one line,
  identical in `gate` and `cleanup`; every tag the workflow moves or
  deletes is built as `build-<slug>` and checked (the slug's characters,
  the `build-` prefix, `git check-ref-format`) before any `gh` call, so it
  can never touch a `v*` release. A tag made with `GITHUB_TOKEN` starts no
  workflow, and `release.yml` listens for `v*` only. **Immutable releases
  must stay off for the repository**: a rolling release cannot exist with
  them. A branch can be built only once `builds.yml` is on it (a branch cut
  before it reached `main` needs a rebase), `delete` runs the default
  branch's copy, and a branch `build_info.py` refuses (a `+` or `@` in
  its name) cannot be built.
- `install.sh`: the plugin installer (curl the release zip + `.sha256`,
  verify, remove any previous install, unzip into `~/homebrew/plugins/`,
  restart `plugin_loader`); its `MOONLIGHT_SYNC_BASE_URL` seam lets
  `tests/test_install_sh.py` point the real `curl` at a `file://` fixture
  tree, with only `sudo`/`systemctl` shimmed on `PATH`, so no sudo and no
  network are ever touched by the test. `cli/install.sh` is the CLI-only
  installer (the release's `moonlight-steam-sync.pyz` into `~/.local/bin`,
  adding it to `PATH` in the rc file once), with the same kind of seam,
  `MOONLIGHT_STEAM_SYNC_BASE_URL`, for `tests/test_cli_install_sh.py`. The
  README advertises it only in its "Command-line tool only" section, near
  the end: the plugin is the recommended install.
- The plugin PRs are stacked (PR-0 → PR-5 → PR-6 → PR-7 → PR-8), each branch
  on the previous one; never push to `main`, force-push only with
  `--force-with-lease` on this stack's own branches.

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
`install.sh`.

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

## Docs to keep current

README (install, updating, panel, restart, hosts, Titles page, hidden
shortcuts and the Streaming tab, key, files, the CLI-only install,
developing), this file (module map, harness, release), `CHANGELOG.md`
`[Unreleased]`, `DEVICE-CHECKLIST.md`, and docstrings, in the same PR as
the change. A CLI change also keeps `cli/README.md` (its usage and
`--help` text) and `cli/AGENTS.md` current; its changelog entry goes in the
root `CHANGELOG.md`.
