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
DEVICE-CHECKLIST.md         every on-device check (PR-0 probes, PR-5/6/7/8 items, §3.14,
                            §3.15 and the §3.16 default layout's [verify] items, then
                            §3.17-§3.20; the key fetch is §14), in order
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
                            every result, relayed event and log line is clean by construction;
                            match_cache_path() (the CLI's matches.json as the child resolves
                            it: $XDG_CACHE_HOME from the child's env, else <home>/.cache) and
                            reset_match_cache() (Advanced's *Reset match cache*: deletes the
                            file whole, pins included, under the busy guard; answers
                            {removed, titles, pins} for the toast; no CLI)
  install.py                read_version(), MIN_CLI_VERSION, atomic install/upgrade
  settings.py               settings.json / ignore.json / owned-apps.json /
                            pending.json / layouts.json, all .tmp + os.replace
  keys.py                   SteamGridDB key sources (config -> env -> file), key file
  wake.py                   Wake-on-LAN (spec 3.18): parse_mac(), magic_packet(),
                            moonlight_hosts() / moonlight_entries() / find_host() /
                            moonlight_host() (Moonlight.conf's [hosts] group, the
                            flatpak path then the native one, read only: QSettings
                            INI, the MAC an @ByteArray of 6 bytes or empty; hosts()
                            reads the entries once for its whole map),
                            send_magic_packet() (broadcast + every address Moonlight
                            knows, WAKE_PORTS; the SOCKET seam so no test sends a
                            datagram; run through asyncio.to_thread, since a hostname
                            among the addresses resolves with a blocking
                            getaddrinfo). Moonlight's CLI has no wake action
                            (list / quit / stream / pair only), so the plugin sends it
  events.py                 parse_line(), restart_decision(), next_pending()
  cdp.py                    the Chrome DevTools Protocol client over Steam's CEF
                            debugger (spec 3.20.2; the port Decky injects through):
                            DEBUGGER, targets() (one GET of /json/list),
                            Session (a stdlib websocket: handshake, masking, the
                            three length forms, fragments, ping, close; evaluate()
                            = Runtime.evaluate returnByValue + awaitPromise, an
                            EvaluateError on a thrown exception), the CONNECT /
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
                            control, Decision 63) -> done. A session per
                            poll, closed after it; only a `page` target on one of
                            the two hosts is ever evaluated in; the stop event's
                            wait() is the 500 ms poll, so a cancel lands within one
backend/entrypoint.sh       the one CLI downloader (strict), also the Decky store hook
backend/Dockerfile          template's holo-base image, only for `decky plugin build`
scripts/package.py          Docker-free zip: out/Moonlight-Sync.zip ("Moonlight Sync/")
src/index.tsx               definePlugin: events (sync_event / sync_done, sgdb_key_event /
                            sgdb_key_done), settings route, running-app watch, load()
src/instance.tsx            the Controller wired to callable / Steam / showModal / toaster;
                            the Steam seam's navigateToExternalWeb / navigateBack pass
                            @decky/ui's Navigation to steam.ts's openExternalWeb() /
                            leaveExternalWeb()
src/lib/                    pure modules (vitest)
  cli.ts                    every §3.4.6 event type, Result/Failure, Backend, makeBackend,
                            errorText (the §3.8 strings; the key fetch's `no-debugger` /
                            `cancelled` / `sgdb-page` / `timeout` are the backend's text
                            verbatim, `busy` kind `"key"` its own sentence),
                            SGDB_API_PAGE, KeyFetchState, SgdbKeyEventPayload /
                            SgdbKeyDonePayload (its failure `error` narrowed to
                            SgdbKeyFetchError) (spec 3.20)
  events.ts                 NDJSON parsing, lastOf/eventsOf
  state.ts                  AppState, Store, reducers (runs, counters, stream map),
                            `titlesEpoch` (bumped by a match-cache reset; a mounted
                            TitlesPage re-lists off it), `sgdbKey` (sgdb_key_state:
                            source + hint, never the key) and `keyFetch` ({state} of
                            the fetch in flight, else null), keyFetchOffered() (the
                            *Get key from SteamGridDB…* button: `none` / `file` only,
                            never `config` / `env`) and keyFetchText() (spec 3.20.4's
                            state texts),
                            wakeInfoOf() (a host's `wake` entry, any case),
                            HOST_APPS / hostAppsFromStatus() (the panel's Desktop and
                            Steam Big Picture buttons, by Moonlight name, blind to
                            `hidden`); an `entry.host_app` entry counts toward none of
                            stream / shortcuts / unmatched and is never in the stream
                            map (spec §3.14.1); the layout walk reads `entries`, not
                            the map, so the host apps and the client are walked too
  controller.ts             load order, runs, restart flow, hosts, settings actions,
                            wakeHost() (spec 3.18: `wake_host` on the active host, a
                            toast either way, never held back), setWakeMac(),
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
                            loadTitles() (list -> list_cached fallback, and list_cached
                            while a run is going; `status` only reaches the shared store
                            when no run is going, the page always gets its entries),
                            pinTitle, setIgnored, resetMatchCache() (Advanced's
                            *Reset match cache*: refused while off or while a run
                            is going, else `reset_match_cache`, a `titlesEpoch`
                            bump on success and a toast either way,
                            resetMatchCacheToast() for the wording),
                            streamPress() (the stream-map guard only, never inGame --
                            Decision 57, the user's 2026-09-22: Moonlight's UI handles a
                            stream already going; applyDefault when a default is set,
                            record, run; never an unset), chooseLayout() (a `null`
                            real appid = a host app: picker only), chooseHostAppLayout()
                            (the panel's layout buttons; not held back by inGame, and
                            neither is openHostApp()),
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
                            that hides every entry; on: a reconcile, the
                            deferred walk, a checkHost; busy while a run is
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
                            reads on; streamingTabEnabled() is false while off),
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
  join.ts                   the Titles page: list + status joined by name into rows
                            (badge, chips, match line, capsule), filters, Show parked,
                            pages of 50, applyPin; the Change match rows (candidateRows,
                            noMatchRow, matchSummary); the `host-app` kind (badge
                            `host app`, under *All* only, never unmatched, every
                            candidate `art only`) and layoutTargetOf(), whose
                            `realAppid` is `null` for a hidden host-app row;
                            layoutSourceOf() (any non-parked entry: what *Use as the
                            default layout* reads, and what the row's layout text is for)
  __tests__/join.test.ts    the join, every badge/chip, filters, sort, paging (fixtures)
  restart.ts                restartDecision() (the §3.9 table), modal text
  version.ts                version parsing, the CLI-missing / too-old row
  format.ts                 relative times, the Last sync line
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
                            written fresh; injects StreamButton
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
                            -> setDefaultLayout, shared by the Titles row and the gear
                            menu; the walk-running refusal), QuickAccess (HostAppRow: the launch button plus the icon-only
                            layout button, plain ButtonItem when the client has no
                            configurator; the unreachable row's *Retry* + *Wake*, the
                            latter only when `wakeInfoOf` finds a MAC), SyncProgress,
                            RestartModal, SettingsPage, HostPage (+ WakeMacRow per host:
                            the entered MAC, or Moonlight's shown), TitlesPage (layout text; the *Layout* menu:
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
                            while a run is going), AboutPage,
                            EnabledToggle (spec 3.19: the *Moonlight Sync* on/off
                            ToggleField, at the top of the panel in every state
                            and, while off, the whole settings route; disabled
                            while a run is going)
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
`bad-request`, `io`, `no-mac`, `no-debugger`, `cancelled`, `sgdb-page`) and
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
The on/off toggle (spec 3.19) is one boolean, `settings.enabled` (default
`true`, `BOOL_SETTINGS` in `settings.py`, a plain `set_settings` key): the
backend knows nothing else of it, the frontend reads it everywhere it
touches the client (`pluginEnabled`), and a run started before the toggle
went off finishes on its own.
The key fetch from the Game Mode browser (spec 3.20) needs no CLI and is
not under the runs' busy guard (Decision 62: no `matches.json` involved, so
a sync may run meanwhile and a fetch may start during a sync); it has its
own, `busy` with kind `"key"`. `start_sgdb_key_fetch()` probes
`cdp.TARGETS()` once (so `no-debugger` comes back here, before the
frontend opens the browser), then runs `sgdbpage.fetch_key` in a worker
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
hosts plus the active one when it is not among them, the Host page's
`wake_macs` setting first, else Moonlight's own `Moonlight.conf` entry,
read once per call; a host with neither is absent, and the panel shows no
*Wake* for it); `wake_host(name)` sends the magic packet to the broadcast
address and every address Moonlight knows for the host on `WAKE_PORTS`, in
a worker thread (a hostname among them resolves with a blocking
`getaddrinfo`), answers `{host, mac, source, sent}`, `no-mac` when nothing knows a MAC,
`io` only when not one datagram went out, and drops the `check_host` memo
so the next *Retry* asks; `set_wake_mac(name, mac)` stores a known host's
MAC normalised (`None` / empty drops it; `set_settings` refuses the
`wake_macs` key) and `forget_host` drops the forgotten host's. Sending
proves nothing about the PC, so the frontend's toast says to Retry in a
minute rather than polling.

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
  `package.json`, the placeholder SteamGridDB key
  (`tests/fixtures/sgdb/api.html`'s) spelled nowhere else under `tests/`
  but that file, and, over a whole browser fetch, the key in no result,
  event or log line (hard rule 4 for spec 3.20).
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
  `loading_polls` makes a fresh page read as loading first). The pages are
  `tests/fixtures/sgdb/*.html` (`login`, `openid`, `api`, `api-no-key`,
  `api-revoke-only`, and Decision 63's `api-hidden-key` / `api-regenerate`,
  hand-written from spec 3.20.1 with the placeholder
  key), parsed by `tests/fakedom.py`: a minimal DOM (`querySelector` /
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
  independence). `tests/test_cdp.py` runs the real websocket client
  against a loopback fake debugger in a thread (handshake, masking, the
  126- and 127-length forms, a fragmented reply, a ping, close, a
  protocol error, a timeout) and `targets()` over a stubbed `urlopen`.
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

**No agent pushes a tag or creates a release** unless the user asks for
that release explicitly (they did for `v0.1.1`, 2026-09-20, which moved the
pin to the CLI's `v0.3.1`). It happens only once the pinned
moonlight-steam-sync release exists: `release.yml`'s
build job fails hard on the missing CLI release **only when it runs from
a `v*` tag push**; its `pull_request` and `workflow_dispatch` runs tolerate
the CLI not being released yet with the same `::warning::` CI's `package`
job prints, so the workflow stays green on every PR in this stack. The
CLI's `v0.3.0` was released on 2026-09-20 and the plugin's `v0.1.0`
follows it; the lenient path only matters again when the pin moves to a
CLI release that does not exist yet.

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

Modelled on the CLI repo's own "Cutting a release" (the example below is
the plugin's first release, `v0.1.0`, which waited for the CLI's `v0.3.0`;
substitute the version being cut), once the pinned CLI release exists and
everything intended for the plugin release has merged to `main`:

```sh
git checkout main && git pull

# 1. package.json's "version" is the single source of truth
#    (decky-loader exports it as DECKY_PLUGIN_VERSION); it is already
#    "0.1.0" as of this PR, so this step is only needed for v0.2.0+.
$EDITOR package.json

# 2. Move the CHANGELOG's [Unreleased] entries into a new dated
#    [X.Y.Z] section and open a new empty [Unreleased] section above it
#    (v0.1.0's entry is already dated, so this step too is only needed
#    for v0.2.0+).
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

README (install, panel, restart, hosts, Titles page, hidden shortcuts and
the Streaming tab, key, files,
developing), this file (module map, harness, release), `CHANGELOG.md`
`[Unreleased]`, `DEVICE-CHECKLIST.md`, and docstrings, in the same PR as
the change.
