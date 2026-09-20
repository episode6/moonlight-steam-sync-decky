# Changelog

All notable changes to this project are documented in this file. The format
follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this
project uses [semantic versioning](https://semver.org/).

## [Unreleased]

Prepared for the patch release after `0.1.0`. At release time, once
moonlight-steam-sync `v0.3.1` exists, move `package.json`'s
`"moonlightSteamSync"` pin to `0.3.1` (it carries the same fix on the CLI
side); `MIN_CLI_VERSION` stays `0.3.0`, since the fix below does not depend
on it.

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
