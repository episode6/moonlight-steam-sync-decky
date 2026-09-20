# Changelog

All notable changes to this project are documented in this file. The format
follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this
project uses [semantic versioning](https://semver.org/).

## [Unreleased]

### Added

- The Moonlight Sync Decky plugin, scaffolded from the Decky plugin
  template: `plugin.json` (no `_root`), the pinned CLI release in
  `package.json` (`"moonlightSteamSync": "0.3.0"`), MIT license.
- The backend (`main.py` over `py_modules/moonlight_sync/`): every callable
  of the plugin's contract, the CLI runner that relays `--json` events as
  `sync_event` / `sync_done`, one sync at a time, timeouts, SIGINT on stop
  and on unload (a child whose output pipes stay open, or whose output
  cannot be read, is still killed and reaped), and the plugin's own `settings.json`, `ignore.json`,
  `owned-apps.json` and `pending.json`. `layouts` and `record_layout`
  answer "not yet".
- The busy guard is symmetric: a `sync`, `art` or `remove` run is refused
  while a `match` (a pin or unpin) is still being written, as well as the
  other way round, since both write `matches.json`.
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
- Tests: pytest against a fake CLI replaying hand-written NDJSON fixtures,
  and vitest over the frontend's pure modules reading the same fixtures.
