# Device checklist

Everything below needs a real Steam Deck (or SteamOS machine with Decky
Loader) in Game Mode; none of it is a merge criterion for any plugin PR
(spec section 4: "on device" acceptance items are transcribed here, not
enforced by CI). Run it top to bottom the first time a build reaches a
Deck. Findings that contradict the spec go to a Fable-class model (spec
section 5), not decided here.

## 0. Setup

1. Get a build onto the Deck: `curl -fsSL
   https://raw.githubusercontent.com/episode6/moonlight-steam-sync-decky/main/install.sh
   | sh` (two `sudo` prompts, explained by the script). For a build newer
   than the latest release, build off-device with `pnpm install && pnpm
   run build && backend/entrypoint.sh && python3 scripts/package.py`, or
   take the `Moonlight-Sync` artifact from a CI run, and install it by
   hand — `README.md`'s "Manual install". Either way Settings → About
   should show the bundled and installed CLI both at `0.3.1`; the plugin
   installs or upgrades `~/.local/bin/moonlight-steam-sync` on first load.
2. SSH into the Deck while it sits in Game Mode (`passwd` once in Desktop
   Mode, then `sudo systemctl enable --now sshd`; see `probes/PROBES.md`
   §1.1 for the full one-time setup, which the PR-0 probes below also
   need).
3. Logs: `~/homebrew/logs/Moonlight Sync/moonlight-sync.log` (every CLI
   call with its arguments, the CLI's own stderr verbatim, both CLI
   versions at startup) and Decky's own log
   (`~/homebrew/logs/decky-loader/…` or `journalctl -u plugin_loader`) for
   backend tracebacks. Settings → About also shows a log tail and both CLI
   versions without leaving the panel.
4. To flip the controller-layout strategy by hand (no UI yet, spec §3.10):
   stop the plugin (`sudo systemctl stop plugin_loader` or unload it from
   Decky's developer menu), edit `"layout_strategy"` in
   `~/homebrew/settings/Moonlight Sync/settings.json` to `"copy"` or
   `"picker"` (removing the key restores the default, currently `"copy"`),
   then reload.
5. The CLI must work *from the plugin*, not only from SSH: plugin_loader
   is a PyInstaller binary whose `LD_LIBRARY_PATH=/tmp/_MEI…` once broke
   the CLI's `flatpak` call ("moonlight CLI not found") and its `import
   ssl` ("5 consecutive network failures"). With Moonlight installed as
   the Flathub flatpak, pick a host in the panel and search for a title in
   the match fixer; then `grep -n "not found\|network failures"
   "$HOME/homebrew/logs/Moonlight Sync/moonlight-sync.log"` must find
   nothing newer than the install. To reproduce the loader's environment
   from SSH, while plugin_loader is running (its unpack directory goes
   when it exits): `env -i HOME=$HOME PATH=/usr/bin LD_LIBRARY_PATH=$(ls
   -dt /tmp/_MEI* | head -1) python3 ~/.local/bin/moonlight-steam-sync
   doctor` — the `moonlight:` line must name the flatpak (CLI 0.3.1 or
   newer; 0.3.0 prints `not found` there, which the plugin's cleaned
   environment hides). `ls -dt` takes the newest `_MEI*` directory; if
   another PyInstaller program is running too, check that the one picked
   holds a `libssl.so.3`. The loader's own `/proc/<pid>/environ` is not
   the shortcut it looks like: the service runs as root, so reading it
   needs `sudo`, and even the backend's deck-owned process refuses.

## 1. PR-0: device probes

The primary path is the scripted runner; the throwaway `steam-input-probe`
plugin is the fallback. Full procedure, venv setup and the exact commands:
[`probes/PROBES.md`](probes/PROBES.md). The fallback button plugin logs
to `~/homebrew/logs/steam-input-probe/steam-input-probe.log` (the loader's
`DECKY_PLUGIN_LOG_DIR`; a loader old enough not to set it falls back to
`~/homebrew/logs/steam-input-probe.log`). In order:

- [ ] **Setup** (PROBES.md §1.1): SSH in, create the `~/.cache/msy-probes`
      venv, confirm the CEF DevTools port answers
      (`curl -s http://localhost:8080/json | grep -c SharedJSContext`).
- [ ] **V4**: `run_probes.py v4` — dump the first 20 of
      `collectionStore.allAppsCollection.allApps` (`appid`, `display_name`,
      `app_type`) and the current steamid3. Expect real entries and a
      plausible steamid3.
- [ ] **V1**: `run_probes.py v1 --appids <owned appid>,<another>` — dump
      `GetConfigForAppAndController` per appid plus the Deck controller
      index found by type. Expect a `template://` or `workshop://` URL for
      a game with a chosen layout, `default://…` for one left on Steam's
      guess, and the controller index (record it — it decides the
      `DECK_CONTROLLER_TYPE` fallback in `src/lib/layouts.ts` if it is not
      what the constant assumes).
- [ ] **V2** (state-changing, needs `--url`; make a throwaway shortcut
      first): `run_probes.py v2 --shortcut <APPID> --url 'workshop://…'`
      (an id published for a real game you own) — calls
      `SetSelectedConfigForApp` then reads back. Expect the read-back URL
      to equal what was set. **This decides the strategy**: if it does not
      match, flip `DEFAULT_LAYOUT_STRATEGY` to `"picker"` in
      `src/lib/layouts.ts` and rewrite the README's "Controller layouts"
      section — escalate to a Fable-class model rather than doing this
      inline.
- [ ] **V5**: `run_probes.py v5 --shortcut <APPID> [--run]` — dump
      `appStore.GetAppOverviewByAppID(appid).gameid` and, with `--run`,
      launch it. Expect a non-null overview once Steam has loaded the
      shortcut list, and (with `--run`) the shortcut to actually launch.
- [ ] **V3** (state-changing, needs `--yes` or an interactive confirm):
      `run_probes.py v3` — logs `pgrep -x steam` every 100 ms for 90 s
      around a `StartShutdown(false)` call, then reconnects to confirm
      Steam came back. Expect the log to show a clear gap between the
      client going away and coming back, confirming `StartShutdown(false)`
      is the restart from Game Mode (spec §2.3). **The measurement is
      `gaps` (from the pgrep samples), not `back_after_ms`**: that field
      is measured from the start of the watch and the reconnect only
      begins after the baseline plus the whole `--duration`, so it is
      bounded below by roughly 91 s whatever Steam does. Read it only as
      "Steam came back: yes/no" (PROBES.md §1.3).
- [ ] Run `run_probes.py all --appids … --shortcut <APPID> [--url … --yes]`
      once everything above passes individually, and paste
      `probe-results.json`'s `--markdown` table into
      `~/specs/moonlight-steam-sync/decky-plugin.md` §2 (a Fable-class
      model does the actual spec edit).

## 2. PR-5: backend, Quick Access panel

- [ ] **First load installs the bundled CLI.** With no `~/.local/bin/moonlight-steam-sync`
      present, load the plugin. Expect it to appear in `~/.local/bin` after
      load, and Settings → About to show both the bundled and installed
      versions matching the pin.
- [ ] **Counters, Sync now, the restart modal.** Press *Sync now*. Expect
      progress lines, then either the restart modal (writes pending) or
      "nothing to do"; the four counters and *Last sync* update after.
- [ ] **Stop right after Sync.** Press *Sync now*, then *Stop* within about
      a second (before the first progress line). Expect the panel to leave
      the progress view reporting a stopped run (not a run that keeps
      going), *Last sync* not claiming any added/replaced shortcuts, and
      `~/homebrew/logs/Moonlight Sync/moonlight-sync.log` (or Decky's own
      log) to show either "stop: SIGINT to the sync run" or "stop: the
      sync run has not spawned yet; it will be interrupted", exit 130.
- [ ] **Stop during the await-exit wait.** Start a sync that has writes to
      make, wait for the "close Steam" state, press *Stop*, reopen the
      panel. Expect the persistent "Restart Steam to apply" row to still be
      offered (nothing was written) and *Last sync* not to claim any
      added/replaced titles.
- [ ] **Unload during a run.** Start a sync, then reload the plugin
      (Decky's developer menu → reload, or reinstall). Expect
      `pgrep -af moonlight-steam-sync` to return nothing a few seconds
      later, and a fresh *Sync now* afterwards to start exactly one run.
- [ ] **Open Moonlight** launches the client shortcut without picking a
      game.
- [ ] **Backend not answering at load.** Force the failure (open the panel
      immediately at Game Mode start, or temporarily rename
      `~/homebrew/plugins/Moonlight Sync/py_modules` to break a callable).
      Expect a Retry row carrying the backend's message instead of an
      endless "Loading your library…" spinner; restore, press Retry, expect
      the panel to fill in without a plugin reload.
- [ ] **Unreachable host row.** With the active host unreachable, expect a
      red dot, the CLI's error message, and "last seen <relative time>"
      ("never synced" when there is no cache).
- [ ] **In-game guard.** While a game is running, expect no restart
      countdown and the text "A game is running. Restart Steam when you're
      done."
- [ ] **In-game guard on the persistent row** (Decision 29). With a
      pending "Restart Steam to apply" row (either kind: a pending write,
      or artwork), launch a game and open the panel. Expect the row to be
      disabled with the subtitle "A game is running; exit it first", and
      pressing it to do nothing. Exit the game: expect the row to become
      pressable again. Also press the row just before launching a game so
      the re-run's `awaiting-steam-exit` lands while the game is up:
      expect the restart modal (with its in-game text) rather than Steam
      shutting down under the game.
- [ ] **Later → the persistent row → immediate restart.** Press *Later* on
      the restart modal, expect the "Restart Steam to apply" row; press it,
      expect the sync to re-run with `immediate_restart: true` and shut
      down at once on the next `awaiting-steam-exit`, no modal.
- [ ] **Art-only restart** (a run with only artwork filled, no shortcut
      writes) offers the same modal/row with "New artwork needs a Steam
      restart to show".
- [ ] **Restart countdown slider.** Settings → Advanced: expect the
      countdown to run 0-30 s and no further (Decision 30 — the CLI stops
      waiting for Steam after 60 s, so a longer countdown would race it).
      Set 0 and expect the modal to show buttons with no countdown; set 30
      and expect it to count down from 30. A `settings.json` left over
      from an older build with `"restart_countdown_s": 60` must read back
      as 30, not break the settings page.
- [ ] **Re-fetch all art with no `--commit` support.** Install (or
      hand-build) a CLI whose `art --help` lacks `--commit`. Expect
      *Re-fetch all art* to be disabled, and if pressed anyway from a stale
      state, the message to read "re-fetching art from Game Mode needs a
      CLI whose art command accepts --commit" — never "CLI too old (0.3.0,
      needs 0.3.0)".
- [ ] **Host subtitle with several hosts.** Add three hosts (one active,
      two not), sync the inactive ones once each so they have cached
      listings. Expect "active host · parked from MY-GAMING-PC (N titles),
      OFFICE-PC (M titles)" with each count matching that host's last
      listing, and a host never listed showing no count. With exactly one
      inactive host, expect "active host · MY-GAMING-PC parked (N titles kept)".
- [ ] **The SteamGridDB key round-trip and Test.** Set a key on the
      Artwork page, expect only its last four characters ever shown
      anywhere (panel, events, logs); press *Test*, expect a pass/fail
      result with no more of the key revealed.

## 3. PR-6: Titles page, Change match

- [ ] **Titles list, idle.** With nothing running, press the panel
      header's list button. Expect "N published by MY-GAMING-PC · sorted by name"
      and rows with capsules, badges and chips.
- [ ] **Titles page mid-sync.** Start *Sync now*, then open Settings →
      Titles while it runs. Expect "N titles cached[ from <relative
      time>] · refreshes when the sync finishes", the note "A sync is
      running; this list refreshes and matches can be changed when it
      finishes", and *Change match* disabled on every row.
- [ ] **`list --cached` during the run, never live `list`.** While that
      sync is running, check the log: only `--json list --cached --host
      MY-GAMING-PC` was spawned, never a live `--json list --host MY-GAMING-PC`.
- [ ] **Refresh after the sync.** Let it finish (restart when prompted),
      reopen Titles: it re-lists live, the headline returns to "N published
      by MY-GAMING-PC · sorted by name", *Change match* is enabled again.
- [ ] **Never-synced host.** On a host that has never been synced, start a
      sync and open Titles mid-run. Expect "MY-GAMING-PC was never synced; this
      list fills in when the sync finishes" with a Retry button, filling in
      after the run ends.
- [ ] **Change match races a sync.** Open *Change match* on a title; before
      pressing *Use this*, start a sync from the panel; then press *Use
      this*. Expect "A sync is already running", no pin written
      (`matches.json` unchanged), the row keeps its old match.
- [ ] **Pin, then apply on next sync.** After that sync finishes, press
      *Use this* again on the same title: expect a pin, the toast "Pinned;
      sync to apply", the pinned and "art refreshes on next sync" chips,
      and the next *Sync now* to turn an owned-game pin into a Stream
      button (Hades II re-matched from a fuzzy Hades hit is the spec's own
      example: expect a Stream button on Hades II and the visible tile
      gone).
- [ ] **Ignore.** *Ignore* on a title removes its tile on the next sync;
      *Unignore* restores it.
- [ ] **Owned-apps mismatch recovery.** Sign in as a second Steam user on
      the Deck, open Titles: expect exactly one `write_owned_apps` in the
      log (recovered once), then a successful list and status — not two
      write attempts.
- [ ] **Paging.** With 300+ rows, page through with the D-pad; expect pages
      of 50 and correct navigation at both ends.

## 4. PR-7: Stream button and controller layouts

- [ ] **Button placement.** With a host active and a sync done, open the
      library page of an owned game the host publishes: expect a Stream
      row. Open a game the host does not publish (or one parked / matched
      to nothing): expect no Stream row.
- [ ] **First press copies a community layout.** Pick a `workshop://`
      layout on the real game in Steam's controller settings, then press
      *Stream*. Expect the hidden shortcut to launch with the same layout,
      and `cat ~/homebrew/settings/"Moonlight Sync"/layouts.json` to show
      that shortcut appid with result `"copied"` and the same `workshop://`
      URL; the Titles row reads "copied".
- [ ] **A hand-picked layout on the hidden entry is never overwritten.**
      Pick a different layout on the hidden shortcut (Titles row's *Choose
      layout*, or Steam's own picker), press *Stream* again, then *Sync
      now* and restart when prompted. Expect the hidden shortcut to keep
      the hand-picked layout after both, `layouts.json` to read `"kept"`
      with that URL, the row to read "own layout".
- [ ] **Steam default.** On a real game left on Steam's default layout,
      press *Stream*: expect `layouts.json` to record `"kept"`, the row to
      read "Steam default", and no layout set on the hidden shortcut.
- [ ] **One row, however often the page is opened.** Open the same owned
      game's library page several times, backing out to the library and in
      again between each (and switch to another game's page and back).
      Expect exactly one Stream row every time — never two stacked — and
      no slowdown building up as the page is re-entered. The route patch
      runs `afterPatch` on each render, so a duplicated or accumulating
      row shows up here and nowhere else.
- [ ] **Running-app guard.** Launch any game, then open another published
      game's library page and press *Stream*: expect only the toast
      "Something is already running", no launch, no `layouts.json` change.
- [ ] **Advanced toggle.** Turn off "Copy controller layouts from the Steam
      game" and press *Stream* on a game with a community layout: expect
      the launch with no copy (`layouts.json` unchanged); turn it back on
      and expect the next press to copy.
- [ ] **Post-restart layout walk.** Make a sync write shortcuts, restart
      when prompted, wait up to 90 s after Steam is back. Expect
      `layouts.json` to gain an entry per Stream button (copied / kept /
      unavailable), the log to show the walk starting, each pair, and
      "layout walk done"; the panel to show no restart row afterward.
- [ ] **Choose layout.** On a Stream row, press *Choose layout*: expect
      Steam's controller configurator to open for the hidden shortcut (its
      title matching the game), `layouts.json` to record `"picker"` for
      that appid; on a client without
      `SteamClient.Apps.ShowControllerConfigurator` expect the action to be
      absent instead of erroring.
- [ ] **Picker strategy.** Set `"layout_strategy": "picker"` in
      `settings.json` (§0.4 above) and reload. Expect a Stream press to
      launch with no layout change and no `layouts.json` write, the
      Advanced toggle disabled with its note, no walk after a sync's
      restart, and *Choose layout* as the only layout action; remove the
      key and reload to return to `copy`.
- [ ] **Controller index by type.** In the CEF console (or the PR-0 kit)
      with a Bluetooth pad also paired, run
      `ControllerStore.GetControllers().map(c => [c.nControllerIndex,
      c.eControllerType, ControllerStore.GetControllerTypeString?.(c.eControllerType)])`
      (the global is `ControllerStore`, capital C, on the client probed on
      2026-09-20; the list is empty while no controller is connected).
      Expect the built-in controller not at index 0 when the pad connected
      first, its type string `"controller_steamcontroller_neptune"`, and
      `eControllerType` `4`; if not 4, correct `DECK_CONTROLLER_TYPE` in
      `src/lib/layouts.ts`. **Still open:** the first probe device was a
      SteamOS box with a separate Steam Controller (index 0, type 10,
      `"controller_steamcontroller_triton"`), so this has not been seen on
      a Deck.

## 5. PR-8: this checklist and `install.sh`

- [ ] **`install.sh` on a Deck**: run the
      one-liner from a clean Deck (no plugin installed yet). A stock Deck
      has no password for the `deck` user, so run `passwd` in a Desktop
      Mode terminal first if you never set one. Expect two `sudo` password
      prompts (unzip into `~/homebrew/plugins/`, restart `plugin_loader`),
      then Moonlight Sync appears in the Quick Access menu's Decky tab,
      and a final line naming the version that actually landed (read from
      the installed `package.json`, not the tag asked for). Re-run it;
      expect it to succeed again (reinstall/overwrite) without asking
      anything unexpected.
- [ ] **A missing release is explained.** Run with
      `MOONLIGHT_SYNC_VERSION=v9.9.9`; expect
      `install.sh: could not download …/Moonlight-Sync.zip (is v9.9.9
      released?)` on stderr, exit 1 and nothing written to
      `~/homebrew/plugins/`.
- [ ] **`MOONLIGHT_SYNC_VERSION` pinning.** Run with
      `MOONLIGHT_SYNC_VERSION=v0.1.0 sh install.sh` (or the exact tag);
      expect the version-specific download path, not `latest/download`.
- [ ] **Uninstall.** Follow the README's "Uninstall" section
      (`sudo rm -rf ~/homebrew/plugins/"Moonlight Sync"` + restart
      `plugin_loader`); expect the Quick Access entry to disappear and
      `~/.local/bin/moonlight-steam-sync` (the CLI) to be untouched.

## 6. Fixtures vs. real CLI

- [ ] Run, on the device, against the real installed CLI:
      `moonlight-steam-sync --json list`, `--json status`, `--json host
      show`, `--json search "Portal"`. Diff each event's key set against
      the corresponding fixture under `tests/fixtures/common/` (§3.6.3 of
      the spec: `tests/test_fixtures.py` checks the fixtures against the
      schema, but never against a real CLI run). A mismatch means the CLI
      and the plugin have drifted from the spec's §3.4.6 schema on one side
      or the other — escalate to a Fable-class model rather than editing
      either side ad hoc.
