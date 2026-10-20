---
name: moonlight-sync-frontend
description: >-
  The Moonlight Sync Decky plugin's TypeScript frontend core: src/index.tsx
  (definePlugin, the backend events), src/instance.tsx (the Controller wired
  to callable / Steam / toaster, the UiPort seams) and the pure src/lib
  modules controller.ts (load order, runs, restart flow, hosts, settings,
  Titles loading, the updater and key-fetch flows, reconcileLibrary, the
  on/off toggle), state.ts (AppState, store, host row, launch row), cli.ts
  (event types, errorText), events.ts, join.ts (Titles page rows, thumbnails,
  Recently added order), restart.ts, version.ts, format.ts and steam.ts (the
  SteamClient globals). Load before changing, reviewing or debugging any of
  those files, the Quick Access panel's logic, the restart prompt, or how the
  frontend calls the backend.
---

# Moonlight Sync frontend core

Reference split out of the root `AGENTS.md`, whose hard rules (cited here as
"hard rule N") apply throughout. Related: `moonlight-sync-library-ui` (the
React components and route patches), `moonlight-sync-controller-layouts`,
`moonlight-sync-updater`, `moonlight-sync-backend` (the callables these
modules call), `moonlight-sync-testing`.

## Module map: the frontend core

```
src/index.tsx               definePlugin: events (sync_event / sync_done, sgdb_key_event /
                            sgdb_key_done), settings route, running-app watch, load()
src/instance.tsx            the Controller wired to callable / Steam / showModal / toaster;
                            the Steam seam's navigateToExternalWeb / navigateBack pass
                            @decky/ui's Navigation to steam.ts's openExternalWeb() /
                            leaveExternalWeb(); the UiPort's updater seams (update spec
                            §3.5): installer() = decky.ts's deckyInstaller(), net() =
                            one `fetchNoCors(url, {method: "GET", headers, cache:
                            "no-store"})` read into an HttpAnswer (status, the four
                            headers through `headers.get`, text()); `no-store` since
                            the loader proxies the request through CEF's HTTP cache
                            with GitHub's headers passed through, so a branch's
                            `build.json` (`Last-Modified`, no `Cache-Control`) read
                            as the build before the last push for hours (update
                            spec amendment A6; test_hard_rules.py holds it),
                            leaveSettings() =
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
                            Moonlight);
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
                            run starts and again when it ends; `artVersion` is
                            join.ts's artVersionOf(pending.since), the thumbnails'
                            version, which onSyncDone moves in the same store set
                            that ends the run),
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
                            chooseClientLayout() (Advanced's *Layout*, Decisions 67
                            and 77:
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
  join.ts                   the Titles page: list + status joined by name into rows
                            (badge, chips, match line, thumbnails), filters, Show parked,
                            pages of 50, applyPin / markStaleArt; the thumbnails
                            (Decision 15 as amended 2026-10-17), best first: the
                            entry's own portrait, customPortraitUrl() =
                            CUSTOM_IMAGES_BASE (`https://steamloopback.host/
                            customimages/`, where the client serves `grid/`) +
                            `<appid>p.<slots.portrait>?v=<artVersionOf(pending.since)>`
                            (the name stays when a run replaces the art, so the
                            version moves when a run finished and only then:
                            loads in between keep their URLs), skipped
                            while `stale_art` (the old match's art), then
                            capsuleUrl() for a Steam match (the old CDN path,
                            a 404 for some newer games); the page's Thumb tries
                            each in turn, then the placeholder; the Change match rows (candidateRows,
                            noMatchRow, matchSummary); the `host-app` kind (badge
                            `host app`, under *All* only, never unmatched, every
                            candidate `art only`);
                            the order (spec 3.21): a row's
                            `added` (status's time for its entry's name, own keys
                            only), TitleSort, titleSortOf(settings)
                            (`titles_recent_first`, absent = by name), sortRows()
                            (`recent`: rows with a time first, the latest on top,
                            ties and the rest by name; a new array), sortText() (the
                            headline's), addedText() ("added today 2:02 PM")
  __tests__/join.test.ts    the join, every badge/chip, filters, sort, paging (fixtures)
  restart.ts                restartDecision() (the §3.9 table), modal text
  version.ts                version parsing, the CLI-missing / too-old row,
                            BUNDLED_CLI_RULE (About's text for when the bundled CLI
                            is installed, Decision U12's equal-version replace included)
  format.ts                 relative times (relativeTime(), its clock 12-hour unless
                            setClockSource()'s source, steam.ts's steamClock24h at
                            plugin load and read at every call, says 24-hour, or an
                            explicit `hour12`; timeUntil(), the future form: "in 12
                            minutes", a missing or past time "in a minute"),
                            dateText(), the Last sync line
  steam.ts                  ownedApps() (a throwing `allAppsCollection` getter, as early
                            in the client's boot, is "not loaded yet"), steamClock24h()
                            (Settings → System → *24-hour clock*:
                            `settingsStore.friendSettings.b24HourClock`, else
                            `m_FriendSettings` (each read in its own try, so a
                            throwing getter still falls back), measured on a Deck
                            2026-09-29; `null` when neither gives a boolean),
                            currentSteamId3(), runShortcut(),
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
```

PR-6 made `search` / `pin` / `unpin` / `set_ignored` real (the Titles page
and the Change match modal); PR-7 added the Stream button, the layout copy
and `layouts` / `record_layout`; PR-9 / PR-10 (spec §3.16) replaced the
copy with the default layout and `set_default_layout`, so every callable
is real. The UI pins with `match … --defer-art` only (Decision 8) and uses
no `unpin` yet (the spec's modal has no unpin action); the callable exists
for the contract.
