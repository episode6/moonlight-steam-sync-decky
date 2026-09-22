# Changelog

All notable changes to this project are documented in this file. The format
follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this
project uses [semantic versioning](https://semver.org/).

## [Unreleased]

### Fixed

- **The *Streaming* tab could be seen but not reached**: navigating the
  library's tab bar skipped it. The one way the plugin itself could cause
  that is closed: a tab whose content has nothing to focus is passed over
  by gamepad navigation, and the tab's own "nothing to stream" line and
  its error box were exactly that. Both are focusable now, and a grid
  that throws shows its error in the tab (and the console, with the
  component stack) instead of the client's empty box, and is tried again
  when the titles change. The cause is not measured on a device yet, so
  the library patch also logs the tab bar's shape once and every tab it
  is asked to show, for the case where the tab is still skipped
  (DEVICE-CHECKLIST §10).

## [0.6.0] - 2026-09-21

### Added

- **Use as Moonlight Sync default layout in the library gear menu** (spec
  §3.16.5, Decision 56). The menu a game's gear button opens now ends with
  that item on every game you stream and on the plugin's own visible
  entries, so the default can be adopted right where the layout is set up:
  it reads the game's own controller layout (the one *Controller settings*
  in the same menu edits), asks you to confirm, and applies it exactly as
  the Titles page's **Layout → Use as the default layout** does. On a
  client whose menu the plugin does not recognise the item is simply
  missing and the menu is untouched.

### Changed

- **The *Streaming* collection is now a *Streaming* tab** (spec §3.17).
  A user collection syncs through Steam Cloud, so the collection of owned
  games that v0.4.0 kept showed up on every machine, and two devices
  synced to different hosts kept removing each other's members. The group
  is now a tab in the library's own tab bar, drawn by the plugin from the
  client's grid and stored nowhere. With *Hide Stream shortcuts* off a
  real *Streaming* collection comes alongside it, but of this device's
  Moonlight shortcuts only, never an owned game, and the plugin only adds
  and removes its own entries in it (and removes shortcuts only while it
  keeps the collection itself, since two devices share a shortcut's
  appid). On upgrade, the old collection loses this device's owned games
  and is deleted once empty; a device still on the old version puts them
  back until it is upgraded too.
  Settings → Advanced → *Streaming collection* is now *Streaming tab*
  (same key in `settings.json`).

## [0.5.0] - 2026-09-21

### Added

- **A default controller layout** (spec §3.16). Everything the plugin
  manages is a stream, so every entry now starts on one layout you pick
  once: on the Titles page, a title you have set up with Steam's own
  configurator gets **Layout → Use as the default layout**, and the plugin
  puts that layout on every entry it manages (Stream buttons' hidden
  shortcuts, visible shortcuts, `Desktop` / `Steam Big Picture` and the
  Moonlight entry) — on each Stream press, after each sync's restart, and
  at once when the default changes. Only a community layout, an exported
  personal layout or a Steam template can be the default; a layout edited
  in place is refused with a note to export it first. **A layout you chose
  yourself is never overwritten**, not by a press, a sync or a change of the
  default; a title still on the plugin's earlier default (including one
  copied from its Steam game by an older version) moves to the new one.
  Settings → Advanced → *Default controller layout* shows it and has
  **Clear**, which takes the plugin's layout off every title that still has
  it (through a Steam client call not yet measured on a device; on a client
  without it the default is still cleared and titles keep their layout).
  A change made before the plugin has loaded your titles is kept and
  applied once they load (the toast says so), and one made while a layout
  walk is running waits for it or, on the Titles page, asks you to try
  again when it finishes.
  Backend: a `default_layout` setting, changed only through the new
  `set_default_layout` callable; `layouts.json` entries gain an `applied`
  field (the last URL the plugin itself set on a shortcut) and a `default`
  result.

### Removed

- **Copying the controller layout from the real Steam game**, and the
  Settings → Advanced toggle *Copy controller layouts from the Steam game*.
  The default layout above replaces it: the real game's layout is never read
  again (`copy_layouts` stays a valid, unused key in `settings.json`). The
  Titles row's *Choose layout* button is now the *Layout* menu, with
  *Choose layout…* and *Use as the default layout*.

## [0.4.0] - 2026-09-21

### Added

- **A *Streaming* collection** in the library: every title the active host
  can stream, as the real Steam game when it has a Stream button and as the
  Moonlight shortcut otherwise, kept up to date after each sync. Settings →
  Advanced → *Streaming collection* turns it off (and deletes it).
- **Settings → Advanced → *Hide Stream shortcuts*** (on by default).

### Fixed

- **Hidden shortcuts are actually hidden.** The Steam client ignores the
  `IsHidden` field the CLI writes to `shortcuts.vdf`, so every Stream
  button's shortcut, the Moonlight client entry, `Desktop` / `Steam Big
  Picture` and parked titles all still showed under *Non-Steam*. The plugin
  now hides them in the client itself, and shows an entry again whenever
  the CLI calls it visible (so hide a Moonlight tile with *Ignore*, not with
  Steam's own *Hide this game*). With *Hide Stream shortcuts* off the Stream-button shortcuts
  stay visible, so a streamed game comes to the front of Home.

## [0.3.3] - 2026-09-21

### Fixed

- **The Stream button shows up on owned games' library pages.** The route
  patch looked for the page's layout in what the route renders directly, but
  the Steam client builds the page two components further down, so the
  button was never added, however many Stream buttons the panel counted.
  The patch now follows the page down to the component that lays it out.

## [0.3.2] - 2026-09-21

### Fixed

- **A sync's shortcuts are written when Steam restarts again.** The CLI's
  "waiting for Steam to exit" event was stuck in an output buffer until the
  CLI gave up 60 s later, so the restart prompt never appeared in time, the
  run ended with "Steam did not exit" and nothing reached `shortcuts.vdf`.
  The plugin now runs the CLI unbuffered, so the prompt (or the immediate
  restart from the *Restart Steam to apply* row) happens while the CLI is
  still waiting.

## [0.3.1] - 2026-09-21

### Fixed

- **"Loading your library…" no longer spins forever after a boot.** When the
  plugin loaded before the Steam client had set up its collections, reading
  the library threw instead of answering "not yet", which killed the load
  order with the row stuck on loading until the plugin was reloaded. That
  throw now counts as "not loaded yet", so the plugin keeps polling, and any
  other failure in that step ends on the *Steam library not loaded* row.

## [0.3.0] - 2026-09-21

### Added

- **A controller-layout button beside Desktop and Steam Big Picture.** Each
  of the panel's two host-app buttons gets a small gamepad button that
  opens Steam's controller configurator for that entry. It works while a
  game is running, and is left out on a Steam client that cannot open the
  configurator. The Titles page offers the same *Choose layout* on the two
  rows.
- **A `host app` badge on the Titles page** for `Desktop` and `Steam Big
  Picture`. The rows are listed under *All* only; *Change match* only
  changes their artwork (every result reads **art only**), and *Ignore*
  removes the entry and its panel button on the next sync.

### Changed

- **The Desktop and Steam Big Picture buttons now replace the two library
  tiles.** Every `sync`, `list` and `status` the plugin runs passes the
  CLI's `--hide-host-apps`, so the two shortcuts are kept but written
  hidden. On an existing install the next sync hides the two tiles in
  place: same appid, so their artwork and any controller layout chosen on
  them are untouched. To get the tiles back, run the plugin's sync from a
  terminal without `--hide-host-apps` (the README's panel section has the
  full command: it keeps `--owned-apps`, `--ignore-file`,
  `--client-shortcut` and `--park-unpublished`); the next sync from the
  plugin hides them again. There is no plugin setting.
  A host whose two entries were renamed keeps its ordinary tiles.
- The panel's **Stream buttons**, **Shortcuts** and **Unmatched** counters
  no longer count the two host apps, no Stream button or layout copy is
  ever derived from a host app's match, and `layouts.json` records
  `real_appid: null` for *Choose layout* on one (there is no Steam game
  behind it).

## [0.2.0] - 2026-09-20

### Added

- **Desktop and Steam Big Picture buttons on the panel.** The two entries
  every Sunshine / Apollo host publishes by default each get a launch
  button under *Open Moonlight*, shown when the active host publishes the
  entry. They run the entry's synced shortcut, so its controller layout
  applies as usual.

### Changed

- **Bundles moonlight-steam-sync `v0.4.0`** (the `package.json` pin moved
  from `0.3.1`) **and needs 0.4.0 or newer** (`MIN_CLI_VERSION` moved from
  `0.3.0`): one CLI version per plugin version. The plugin installs or
  upgrades the CLI on first load, so there is nothing to do by hand.
  `v0.4.0` adds `--hide-host-apps`, which the plugin does not pass yet.
- **Change match lists the games you own first.** Search results that this
  account owns (the ones a pin turns into a Stream button) now sit at the
  top of the list, ahead of the other Steam and SteamGridDB results, so
  the likeliest pick no longer hides below unowned store hits.

## [0.1.1] - 2026-09-20

A patch release from the first device run. It bundles moonlight-steam-sync
`v0.3.1` (the `package.json` pin moved from `0.3.0`), which carries the
same library-path fix on the CLI side; `MIN_CLI_VERSION` stays `0.3.0`,
since the plugin's own fix below does not depend on it.

### Fixed

- **"moonlight CLI not found" and search/artwork stopping on "5 consecutive
  network failures", on every device.** Decky's plugin_loader is a
  PyInstaller-frozen binary that exports `LD_LIBRARY_PATH=/tmp/_MEI…` (its
  own bundled, older OpenSSL), and the backend passed its environment
  straight to the CLI. Under it the CLI's `flatpak list` died in the
  dynamic linker, which read as "Moonlight is not installed", and its own
  `import ssl` failed, so no HTTPS call ever succeeded. The backend now
  gives every CLI child the original library path back
  (`LD_LIBRARY_PATH_ORIG`, or `LD_LIBRARY_PATH` minus its `_MEI*` entries).
  Found on the first device run.
- **The SteamGridDB key test no longer blames the key for a network
  failure.** The test runs the CLI's `search`; when that ends in the CLI's
  network hard stop (exit 4, anything but an HTTP 401) the message is now
  "Could not reach SteamGridDB (network), so the key was not tested: …"
  instead of the bare CLI error, which read as a rejected key. A 401 still
  says "SteamGridDB rejected the key".

## [0.1.0] - 2026-09-20

The first release. It bundles moonlight-steam-sync `v0.3.0` (released the
same day) as `bin/moonlight-steam-sync.pyz` and installs it on first load.
Built and tested off-device; the PR-0 probes have run on a generic SteamOS
machine but nothing has run on a Steam Deck yet. `DEVICE-CHECKLIST.md`
collects everything that still needs a device.

### Added

- The Moonlight Sync Decky plugin, scaffolded from the Decky plugin
  template: `plugin.json` (no `_root`), the pinned CLI release in
  `package.json` (`"moonlightSteamSync": "0.3.0"`), MIT license.
- The backend (`main.py` over `py_modules/moonlight_sync/`): every callable
  of the plugin's contract, the CLI runner that relays `--json` events as
  `sync_event` / `sync_done`, one sync at a time, timeouts, SIGINT on stop
  and on unload (a child whose output pipes stay open, or whose output
  cannot be read, is still killed and reaped), and the plugin's own `settings.json`, `ignore.json`,
  `owned-apps.json`, `pending.json` and `layouts.json`.
- The busy guard is symmetric: a `sync`, `art` or `remove` run is refused
  while a `match` (a pin or unpin) is still being written, as well as the
  other way round, since both write `matches.json`.
- The Stream button: every owned game the active host publishes gets a
  **Stream** row on its library page (a patch of the `/library/app/:appid`
  route written from Decky's primitives) that runs the hidden shortcut
  through Steam; only a toast while a game is already running.
- Controller-layout copy: on each Stream press and once after a sync's
  restart (over every Stream button, once Steam has loaded the shortcut
  list), the real game's `workshop://` / `template://` selection is set on
  its hidden shortcut through Steam Input when the shortcut has no
  selection of its own, never overwriting one; the Deck's controller is
  found by type, and a device without one copies for the active or only
  connected controller. The first device probes (2026-09-20) corrected
  three things here before any release: `SetSelectedConfigForApp` needs its
  fifth, selection-type argument or it silently selects nothing; the
  controller store global is `ControllerStore`; and
  `RegisterForControllerListChanges` may not exist, so the controller
  watch no longer throws at load without it. A config Steam only offers
  (`bSelected: false`, how a never-configured game reads back, as
  `template://…`) counts as no selection on either side. One behaviour
  follows from the non-Deck rule: a docked Deck with its built-in
  controller off and one external pad used to get `unavailable` and now
  copies for that pad. Results (`copied` / `kept` / `unavailable`) are recorded
  in `layouts.json` (`layouts` / `record_layout`) and shown on the Titles
  row as copied / own layout / Steam default / unavailable, and next to the
  button. The Advanced toggle turns the copy off. The post-restart walk
  keeps its pending flag when `status` did not answer, so it still runs on
  the next load instead of being lost.
- **Choose layout** on a Stream button's Titles row opens Steam's own
  layout picker for the hidden shortcut (hidden when the client lacks it).
- The layout strategy switch: `DEFAULT_LAYOUT_STRATEGY` (`copy`) in
  `src/lib/layouts.ts`, overridable per device by `layout_strategy` in
  `settings.json`; `picker` makes no Steam Input calls and leaves Choose
  layout as the only layout affordance. Probe V2 confirmed `copy`.
- The Titles page (Settings → Titles, also opened from the panel's
  header): every title the active host publishes, joined from `list` and
  `status`, with Steam's capsule, the match line, a badge (stream button,
  shortcut, unmatched, ignored, parked, duplicate) and chips (fuzzy, pinned,
  same game on another host, art refreshes on next sync); the All / Stream
  buttons / Shortcuts / Unmatched / Ignored filters, Show parked, pages of
  50, and the last cached listing when the host is unreachable or while a
  sync is running.
- Change match: searches Steam's store and SteamGridDB, shows one list
  (Steam first) with what each result would make of the title ("becomes
  stream button" for an owned game), marks the current match, offers No
  match, and pins with `match --defer-art` so the next sync applies it and
  re-fetches the art. Ignore / Unignore edit the plugin's `ignore.json`.
- The backend's `search`, `pin`, `unpin` and `set_ignored`.
- The bundled CLI: installed to `~/.local/bin/moonlight-steam-sync` on load
  when missing or older (atomically, never downgrading); "CLI not
  installed" / "CLI too old" states with every CLI action disabled.
- The SteamGridDB key: stored in the CLI's own key file (mode 0600),
  following the CLI's config → environment → key-file precedence, with only
  the last four characters ever shown.
- The Quick Access panel: host dropdown with switch-and-sync, reachability
  with "last seen", Sync now with progress and Stop, Open Moonlight, the
  four counters and Last sync; the first-run "No host yet" state, and a
  Retry when the backend itself did not answer at load.
- The restart flow: a Restart now / Later prompt with a countdown (0-30 s)
  when a sync is ready to write (and for art-only or stopped runs that saved
  images), the in-game guard, and the persistent "Restart Steam to apply"
  row that re-runs the sync and restarts at once. Both the prompt and the
  persistent row honour the in-game guard: while a game is running the row
  is disabled ("A game is running; exit it first") and an immediate run that
  reaches its wait shows the prompt instead of shutting Steam down.
- Settings pages: Host (add with a pairing check, switch, forget), Artwork
  (key field, Retry missing art, Re-fetch all art), Advanced (layout-copy
  toggle, restart countdown, Remove everything) and About (both CLI
  versions, the pin, plugin version, log path and log tail).
- Docker-free packaging (`scripts/package.py`) and the strict CLI
  downloader (`backend/entrypoint.sh`); CI with frontend, backend, probe-kit
  and package jobs.
- `install.sh`: downloads the latest (or a pinned) release's
  `Moonlight-Sync.zip`, verifies its checksum, removes any previous
  `Moonlight Sync/` install (so a file an older release shipped and the
  new one no longer does cannot linger), unzips into
  `~/homebrew/plugins/`, then restarts `plugin_loader`, explaining the two
  `sudo` prompts it needs along the way (and that a stock Deck has no
  password for `deck`, so `passwd` may be needed first). A failed download
  says which URL failed and whether that version is released, rather than
  curl's silent exit 22, and the closing line names the version that
  actually landed, read from the installed `package.json`.
  `release.yml`: on a `v*` tag,
  builds and packages strictly (the CLI download and the packaging step
  both fail the run rather than warn when the pinned CLI release is
  missing) and attaches `Moonlight-Sync.zip` and `Moonlight-Sync.zip.sha256`
  to a GitHub release; its build-and-package job also runs on every pull
  request and `workflow_dispatch`, where it tolerates the CLI release not
  existing yet with the same `::warning::` CI's `package` job prints
  (never strict off a tag), so the workflow is exercised and green before
  the first tag.
- `DEVICE-CHECKLIST.md`: every on-device check from the PR-0 probes and the
  PR-5/6/7/8 amendments, in the order they need a Deck.
- A `shellcheck` CI job linting `install.sh` and `backend/entrypoint.sh`.
- Tests: pytest against a fake CLI replaying hand-written NDJSON fixtures,
  and vitest over the frontend's pure modules reading the same fixtures;
  `tests/test_install_sh.py` drives the real `install.sh` end to end
  against a `file://` fixture (via `MOONLIGHT_SYNC_BASE_URL`) with `sudo`
  and `systemctl` shimmed
  on `PATH`.
