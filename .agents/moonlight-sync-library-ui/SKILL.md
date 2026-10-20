---
name: moonlight-sync-library-ui
description: >-
  The Moonlight Sync plugin's React UI and Steam library integration:
  src/components/ (QuickAccess panel, SettingsPage, HostPage, TitlesPage,
  ChangeMatchModal, ArtworkPage, AdvancedPage, UpdatesPage, AboutPage,
  StreamButton, StreamingTab, RestartModal, EnabledToggle, adoptDefault),
  src/routes/ (libraryTabs.tsx, the Streaming tab patch on /library;
  libraryApp.tsx, the Stream button on /library/app/:appid; tree.ts) and their
  pure halves src/lib/library.ts (hidden shortcuts, the Streaming collection,
  spec 3.15 / 3.17 / 3.19), tabs.ts and appPage.ts (gamepad focus order). Load
  before changing any component, route patch, panel or settings page layout,
  or the hidden-shortcut / Streaming tab / collection behaviour.
---

# Moonlight Sync library patches and UI

Reference split out of the root `AGENTS.md`, whose hard rules (cited here as
"hard rule N") apply throughout. Related: `moonlight-sync-frontend` (the
controller and store these components render),
`moonlight-sync-controller-layouts`, `moonlight-sync-updater` (UpdatesPage's
logic).

## Module map: the library patches and the UI

```
src/lib/                    pure modules (vitest)
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
src/routes/tree.ts          Overview / TreeNode / isOverview, shared by the two
                            route patches
src/components/             adoptDefault (inspectLayout -> refusal toasts -> ConfirmModal
                            -> setDefaultLayout for Advanced's *Make default*, the one
                            place a default is adopted since Decision 74 (the Titles
                            row's and the library gear menu's items went; the panel's
                            since Decision 77); the walk-running refusal),
                            QuickAccess (Decision 67: LaunchRow, the Moonlight /
                            Desktop / Steam Big Picture icon buttons on one line, the
                            caption under it following `onGamepadFocus` and back to
                            Moonlight's on `onGamepadBlur` (a blur clears only its
                            own key); no layout row since Decision 77 (Advanced
                            has its buttons); *Sync now* has no
                            description; HostRow over `hostRowView`: with several
                            hosts a `Field` with `childrenContainerWidth="max"`
                            around a `Dropdown` (a Field's control column stops at
                            half the row otherwise, and DropdownItem has no such
                            prop), the Dropdown in a `width: 0; min-width: 100%`
                            div (the "max" column never shrinks, so without it
                            the description ran under the dropdown; with it
                            the description keeps its width and the host's
                            name ellipsizes, measured 2026-09-29), the circle
                            and the count as its description,
                            `disabled` on the Field as on the Dropdown so the
                            whole row dims while busy, as the DropdownItem did;
                            with one host no row at all; an error's text in a row
                            of its own under the switcher, which draws the divider
                            the Field then leaves out; then *Check* + *Wake*
                            whenever the host is not known reachable, the latter
                            only when `wakeInfoOf` finds a MAC, in a `Field` with
                            `childrenLayout="below"` (a ButtonItem's own: *Sync
                            now*'s padding and divider, so the panel is spaced
                            alike with or without them); UpdateRow, the
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
                            during a sync only for `recent`; Thumb tries a row's
                            `thumbnails` in turn on `onError`, then the striped
                            placeholder, keyed on the URLs; no layout text and no
                            layout action (Decisions 75 to 77: Advanced's *Layout*
                            and *Make default* are the only ones)), ChangeMatchModal,
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
                            AdvancedPage (*Default controller layout*, Decision 77:
                            defaultLayoutDescription() over the settings and
                            `clientAppid` ("Sync once" while the Moonlight shortcut
                            does not exist), then one row of buttons: *Layout*
                            (chooseClientLayout, hidden when the client has no
                            configurator), *Make default* (adoptAsDefault on the
                            client) and *Clear* with its confirm, the last two hidden
                            under `picker`; *Hide Stream shortcuts* and *Streaming
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
```
