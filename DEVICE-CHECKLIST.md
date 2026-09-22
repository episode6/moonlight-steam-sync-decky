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
   should show the bundled and installed CLI both at `0.4.0`; the plugin
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
- [ ] **Desktop** / **Steam Big Picture** show on the panel when the active
      host publishes them, each starts its stream with the controller
      layout chosen on that shortcut, and neither shows once its entry is
      ignored and synced away.
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
      CLI whose art command accepts --commit" — never "CLI too old (0.4.0,
      needs 0.4.0)".
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

*The layout items in this section were written for the copy from the real
Steam game, which spec 3.16 (§8 below) replaced with a default layout you
adopt: nothing copies from the real game any more, there is no Advanced
toggle, and the Titles row's *Choose layout* is now **Layout → Choose
layout…**. Run the button, guard, route-patch, picker-strategy and
controller-index items here as written; the copy-specific ones are marked
and superseded by §8.*

- [ ] **Button placement.** With a host active and a sync done, open the
      library page of an owned game the host publishes: expect a Stream
      row. Open a game the host does not publish (or one parked / matched
      to nothing): expect no Stream row.
- [ ] ~~**First press copies a community layout.**~~ Superseded by §8
      (nothing copies from the real game any more). With **no default
      layout set**, press *Stream* on a game whose real entry has a
      `workshop://` layout: expect the launch with no layout change and no
      `layouts.json` write.
- [ ] **A hand-picked layout on the hidden entry is never overwritten.**
      Pick a layout on the hidden shortcut (Titles row's *Layout → Choose
      layout…*, or Steam's own picker), set a different default layout
      (§8), press *Stream*, then *Sync now* and restart when prompted.
      Expect the hidden shortcut to keep the hand-picked layout after all
      three, `layouts.json` to read `"kept"` with that URL and `"applied":
      null`, the row to read "own layout".
- [ ] ~~**Steam default.**~~ Superseded by §8: with a default set, a
      hidden shortcut on Steam's default gets the default layout on its
      first press (`"default"`); without one, nothing is written.
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
- [ ] ~~**Advanced toggle.**~~ Removed: the toggle is gone (spec Decision
      47). Settings → Advanced shows *Default controller layout* instead
      (§8); "no default set" is the off switch.
- [ ] **Post-restart layout walk.** With a default layout set (§8), make a
      sync write shortcuts, restart when prompted, wait up to 90 s after
      Steam is back. Expect `layouts.json` to gain an entry per non-parked
      entry (default / kept / unavailable), the log to show the walk
      starting, each target, and "layout walk done"; the panel to show no
      restart row afterward.
- [ ] **Choose layout.** On a Stream row, press *Layout* → *Choose
      layout…*: expect Steam's controller configurator to open for the
      hidden shortcut (its title matching the game), `layouts.json` to
      record `"picker"` for that appid; on a client without
      `SteamClient.Apps.ShowControllerConfigurator` expect the menu item to
      be absent instead of erroring.
- [ ] **Picker strategy.** Set `"layout_strategy": "picker"` in
      `settings.json` (§0.4 above) and reload. Expect a Stream press to
      launch with no layout change and no `layouts.json` write, the
      Advanced *Default controller layout* field to read "Off for this
      device…" with no *Clear* button, no walk after a sync's restart, no
      *Use as the default layout* in any *Layout* menu, and *Choose
      layout…* as the only layout action; remove the key and reload to
      return to `copy`.
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

## 6. Host apps: the panel buttons replace the tiles (spec 3.14)

Needs a host that publishes `Desktop` and `Steam Big Picture` under those
names, and ideally an install from before this change: two visible tiles,
one of them with a controller layout chosen on it. Note each tile's appid
first (`moonlight-steam-sync --json status`).

- [ ] **The first sync hides the two tiles in place.** Upgrade the plugin,
      press *Sync now*. Expect the plan to count them as hidden, never as
      replaced (the log's CLI line says `N to hide`; no `replace` event for
      either name), one Steam restart, and afterwards no `Desktop` /
      `Steam Big Picture` tile anywhere in the library, non-Steam
      collection included.
- [ ] **Same appid, nothing lost.** `--json status --hide-host-apps` shows
      both entries with the appids noted above, `hidden: true`,
      `parked: false`, `host_app: true`, and their artwork slots still
      filled; no image was downloaded for them by that sync.
- [ ] **Both panel buttons launch.** *Desktop* and *Steam Big Picture* each
      start their stream from the Quick Access panel; Recent Games and the
      in-game overlay show the entry with its artwork.
- [ ] **Each layout button opens the configurator.** The gamepad button
      beside *Desktop* opens Steam's controller configurator for Desktop
      (the Quick Access menu closes and the configurator is in front), and
      likewise for *Steam Big Picture*. Check what a screen reader / the
      focus ring says: "Choose controller layout for Desktop". D-pad right
      from the launch button reaches it, and D-pad up/down still walks the
      panel's rows.
- [ ] **A layout chosen before the upgrade is still selected** when the
      configurator opens (same appid), and it applies in the stream.
- [ ] **While a game runs** the two launch buttons are disabled ("A game is
      running; exit it first") and the two layout buttons still work.
- [ ] **On a client without `SteamClient.Apps.ShowControllerConfigurator`**
      (if one turns up) the rows fall back to the plain full-width launch
      buttons and the Titles rows' *Layout* menus have no *Choose
      layout…* (only *Use as the default layout*).
- [ ] **Counters.** Do this one *before* the first sync: `status` carries
      the flag from the upgrade on, so the two still-visible tiles already
      read `host_app: true`. Right after the upgrade *Shortcuts* is two
      lower than before (and *Unmatched* lower by however many of the two
      had no match); *Stream buttons* is unchanged. The sync that hides the
      two then moves none of the three.
- [ ] **Titles page.** Both rows read **host app**, show under *All* only,
      and have *Change match*, *Layout* and *Ignore*. *Layout → Choose
      layout…* opens the same configurator and the row then says `layout:
      picker opened`. In *Change match* every result reads **art only**,
      including a game this account owns; pin one, sync, and expect the
      entry to stay a hidden host app with new artwork and no Stream button
      on that game's library page.
- [ ] **No layout copied onto them.** *(Written for the layout copy that
      spec 3.16 replaced; §8 covers them now.)* Without a default layout
      set, after a sync's restart the layout walk never touches the two
      entries (`layouts.json` has no `copied` / `kept` / `unavailable`
      record for their appids, only `picker` with `real_appid: null` once
      *Choose layout…* was used). With a default set they get it, like
      every other entry (§8).
- [ ] **Ignore removes the button.** Ignore `Desktop` on the Titles page and
      sync: the entry is removed and the panel's *Desktop* row is gone.
      Unignore and sync: it comes back, hidden from the start.
- [ ] **Switching hosts.** With a second host that does not publish them,
      the two entries are parked (counted under parked, buttons gone); back
      on the first host they are unparked *hidden*, never as tiles.
- [ ] **Getting the tiles back** (README, "The Quick Access panel"): the
      full command there (`--owned-apps`, `--ignore-file`,
      `--client-shortcut`, `--park-unpublished`, no `--hide-host-apps`), run
      from a terminal, shows the two tiles again with art and layout intact
      and changes nothing else: every Stream button stays hidden, no ignored
      title comes back, the Moonlight client entry stays. The next *Sync
      now* hides the two again.

## 7. Hidden shortcuts and the Streaming collection (spec 3.15)

None of `collectionStore.SetAppsAsHidden`, `BIsHidden`, `userCollections`,
`NewUnsavedCollection`, `AsDragDropCollection` or a collection's `Save` /
`Delete` was probed before this was built; every item here is a first
measurement. **Spec 3.17 changed the collection items below:** the
collection now exists only with *Hide Stream shortcuts* off, beside the tab, and holds
shortcuts only; §10 has the items that replace the collection ones here,
and the hiding items still stand.

- [ ] In the CEF console: `typeof collectionStore.SetAppsAsHidden`,
      `typeof collectionStore.BIsHidden`, `typeof
      collectionStore.NewUnsavedCollection` are all `"function"`, and
      Settings → Advanced shows both toggles enabled (a disabled toggle
      says the client has no such call).
- [ ] After the plugin loads with an existing install: the *Non-Steam* tab
      holds only the visible shortcuts (the panel's **Shortcuts** counter),
      no Stream-button shortcut, no `Moonlight`, no `Desktop` / `Steam Big
      Picture`, no parked title. They are all under Steam's *Hidden*.
- [ ] A **Streaming** collection exists and its size is the panel's
      **Stream buttons** + **Shortcuts**. An owned game in it opens the real
      game's page (with the Stream button); an unowned one is the shortcut.
- [ ] A Stream press still launches the (now hidden) shortcut, and the
      panel's *Open Moonlight*, *Desktop* and *Steam Big Picture* still work.
- [ ] *Hide Stream shortcuts* off: the Stream-button shortcuts appear under
      *Non-Steam* within a moment, the other hidden entries do not, and the
      collection is unchanged. Stream a game, quit: its shortcut is at the
      front of Home. On again: they are gone again.
- [ ] *Streaming collection* off: the collection is deleted. On: it is
      back, complete.
- [ ] Sync after the host gains a title: once Steam has restarted, the new
      Stream shortcut is hidden and the game is in the collection without
      opening the panel (allow 90 s). Note whether the tile is visible for
      a moment first.
- [ ] Switch hosts and sync: the first host's visible tiles are hidden
      (parked) and leave the collection; switching back shows them again.
- [ ] *Remove everything*: after the restart the collection is gone and
      Steam's *Hidden* holds none of the plugin's entries.
- [ ] After a host switch (or an *Ignore* + sync) that removes a visible
      shortcut: the collection's `allApps` no longer lists its appid (the
      plugin cannot remove a member whose overview is gone, so the client
      has to drop it itself).
- [ ] The first sync on a fresh install creates the collection with every
      member in it (the port saves a new collection empty, then adds).
- [ ] Open the panel and the Titles page a few times: nothing in the
      library flickers and `collectionStore` is not written again (the
      reconcile only applies differences).

## 8. The default controller layout (spec 3.16)

The plugin never reads the real game's layout any more: one layout you
adopt from a title is put on every entry the plugin manages, and a
selection the plugin did not make is never overwritten (`applied` in
`layouts.json` is what the plugin last set per shortcut). Two things here
are unmeasured on any device: whether a `template://` layout sticks on
other titles, and the name and arguments of the call that clears a
selection (`SteamClient.Input.ClearSelectedConfigForApp(appid,
controllerIndex)`, spec 3.16.3 **[verify]**). Do this section with a
controller connected; *Use as the default layout* answers "Connect a
controller first" otherwise.

- [ ] **Adopt a community layout.** On a title's row (Titles page) whose
      hidden shortcut you gave a `workshop://` community layout (*Layout →
      Choose layout…*), press *Layout → Use as the default layout*. Expect
      a confirm titled `Use “<layout title>” as the default layout?`; after
      OK, a toast `Default layout applied to N titles` (N = every non-parked
      entry that had no layout of its own, host apps and the Moonlight entry
      included) plus ` · M kept their own` for the ones that had; Settings →
      Advanced → *Default controller layout* reading `<title> · Workshop
      layout · set today …`; `layouts.json` with `"default"` and `"applied"`
      set to the URL for each. A fresh title (a game the host just started
      publishing, after its sync and restart) streams on it without any
      press first, and its Titles row reads "default layout".
- [ ] **Adopt from the gear menu [verify].** Open a streamed game's library
      page, press its gear button. Expect *Use as Moonlight Sync default
      layout* as the menu's last item (spec 3.16.5, Decision 56); on a game
      the host does not publish, and on any page while the strategy is
      `picker`, expect no item. With no layout chosen for the game itself,
      expect the toast `“<game>” has no layout chosen yet. Pick one under
      Controller settings first.`; pick a `workshop://` layout under that
      menu's *Controller settings*, then the item again: expect the same
      confirm and toast as the Titles row gives. If the item never appears,
      open the library first (the menu patch installs on the first library
      render, not at plugin load), then check the CEF console for
      `Moonlight Sync: the library context menu was not found` and report
      it: the wrapper's marker (`().appDetailsSpotlight`,
      `src/routes/libraryContextMenu.tsx`) has to be re-measured on that
      client. No warning but no item either means the menu class was
      found but its `render` gave a tree without a `MenuItem` list, or
      its `props` carry the page under neither `overview` nor `appid`:
      in the console, `findLibraryContextMenu` is not exported, so read
      the props from a patched instance (`console.log(this.props)` in a
      temporary build) and report the keys. Also long-press a streamed
      game's tile in the library: the same menu, so the item should be
      there too.
- [ ] **Adopt a `template://` layout [verify].** Pick one of Steam's own
      templates on a title, adopt it. Expect the same toast; check
      `layouts.json`: every other entry must read `"default"` with the
      `template://` URL. If they read `"unavailable"` instead (the URL did
      not stick when read back), report it: `template://` then has to come
      out of `DEFAULT_LAYOUT_SCHEMES` (spec 3.16.1, Decision 49), a
      Fable-class decision.
- [ ] **An edited-in-place layout is refused.** Edit a title's layout in
      Steam's layout screen without exporting it (it reads
      `autosave:///…`), then *Use as the default layout* on it. Expect only
      the toast `This layout was edited in place and only exists for
      “<name>”. In Steam's layout screen choose Export, select the exported
      copy, then try again.`, no confirm, no change.
- [ ] **An exported personal layout works.** Export that layout, select the
      exported copy on the title (it now reads `workshop://…`), adopt it:
      expect the normal confirm and toast.
- [ ] **A title with no layout is refused.** On a row whose entry was never
      given a layout (reads `default://…`, or a `template://` Steam only
      offers), expect the toast `“<name>” has no layout chosen yet. Use
      Choose layout first.`
- [ ] **Hand-picked survives, plugin-applied moves.** With a default set,
      pick a different layout by hand on one title (*Choose layout…*), then
      adopt a *second* default from another title. Expect the hand-picked
      title unchanged (`"kept"`, `"applied": null`, row "own layout"), every
      plugin-applied title on the new default, the title you adopted *from*
      unchanged, and the toast's `M kept their own` counting the hand-picked
      one and the source.
- [ ] **A pre-upgrade copied title moves.** On an install upgraded from a
      version that copied layouts from the real game (`layouts.json` has
      `"copied"` records without an `"applied"` key), set a default: expect
      those titles to move to it (Decision 46) as long as their selection is
      still the copied URL.
- [ ] **Clear [verify].** Settings → Advanced → *Clear*: expect the confirm
      `Clear the default layout?`, then the toast `Default layout cleared ·
      removed from N titles`. Every plugin-applied title must be back on
      Steam's default (the layout screen shows nothing selected; the row
      reads "Steam default", `"applied": null`), and hand-picked ones must
      keep their layout. In the CEF console first check `typeof
      SteamClient.Input.ClearSelectedConfigForApp`: if it is not
      `"function"`, the toast reads `Default layout cleared. This Steam
      client cannot unset a layout, so titles keep the one they have.` and
      nothing changes on any title; if it is a function but titles are not
      back on Steam's default afterwards (`"unavailable"` with the old URL
      in `layouts.json`), the call's name or arguments are wrong: report
      it (spec 3.16.3), do not guess at another.
- [ ] **A sync's new titles get it after the restart.** With a default
      set, add a title on the host, *Sync now*, restart: within 90 s the new
      shortcut is on the default (`layouts.json`, and the layout screen).
- [ ] **The host apps, the client entry and a visible shortcut get it.**
      After any of the above, check `layouts.json` for `Desktop`, `Steam
      Big Picture`, `Moonlight` and a visible (non-Stream) shortcut:
      `"default"` with `"real_appid": null` for the first three.
- [ ] **Not held back.** Start a game, then adopt or clear a default from
      the Titles page: it goes through (the toast appears) while the game
      runs; a Stream press is still refused meanwhile.

## 9. Fixtures vs. real CLI

- [ ] Run, on the device, against the real installed CLI:
      `moonlight-steam-sync --json list --hide-host-apps`, `--json status
      --hide-host-apps` (the plugin always passes that flag, and the
      fixtures carry its keys: `kind: "host-app"`, `entry.host_app`), `--json host
      show`, `--json search "Portal"`. Diff each event's key set against
      the corresponding fixture under `tests/fixtures/common/` (§3.6.3 of
      the spec: `tests/test_fixtures.py` checks the fixtures against the
      schema, but never against a real CLI run). A mismatch means the CLI
      and the plugin have drifted from the spec's §3.4.6 schema on one side
      or the other — escalate to a Fable-class model rather than editing
      either side ad hoc.

## 10. The Streaming tab (spec 3.17)

The `/library` route's render tree was never measured: the patch digs for
the tab bar's `tabs` array (four component levels at most) and clones a
built-in tab's grid element with a synthetic collection whose surface is a
guess at the client's `Collection`. Every item is a first measurement.

- [ ] With an install that has synced: the library's tab bar has a
      **Streaming** tab after *Non-Steam*, and it opens. If there is no
      tab, note the CEF console: `Moonlight Sync: could not patch the
      library tabs` names a throw; silence means the walk never found a
      `tabs` array (report the route element's shape: `typeof
      route.children.type`, whether `props.renderFunc` exists).
- [ ] The tab can be **reached**: L1/R1 from *Non-Steam* lands on it, and
      moving along the tab row with the D-pad stops on it (found
      2026-09-22: the tab was in the bar and both skipped it; the plugin's
      own empty and error panels are focusable since, the grid is the
      client's). If it is still skipped, report from the CEF console
      the one `Moonlight Sync: library tabs found on …` line (the bar's
      prop names, `activeTab`, a built-in tab's keys, the template's type
      and prop names) and whether a `Moonlight Sync: library tabs,
      onShowTab("MoonlightSyncStreaming")` line appears when you try:
      none means the bar never asked for it (its navigation reads
      something other than `tabs`, or the tab's header is not
      focusable); one that does not open it means the library refused
      the id. Also say whether Settings → About's log panel takes focus:
      it is a plain `Focusable` over text, the shape the empty tab had,
      and the tab's panels add `focusableIfNoChildren` and a no-op
      `onActivate` on top (both unmeasured), so a log panel that focuses
      means a plain `Focusable` already suffices, and one that does not
      says the panels lean on those two.
- [ ] The tab's tiles are the panel's **Stream buttons** + **Shortcuts**:
      an owned game opens the real game's page (with the Stream button),
      an unowned one is the shortcut. Sorting, the footer legend and the
      focus ring behave like *Non-Steam*'s. A blank tab, or a line that
      starts *Moonlight Sync could not draw this tab on this client*
      (the plugin's own error boundary; the console has the same error
      with its component stack), means the grid read something the
      synthetic collection lacks: report the console error, do not guess
      at the field.
- [ ] Steam's own tabs are unchanged, and Settings → Moonlight Sync's
      tab bar has no Streaming tab (the injection only takes a tab bar
      some tab of which renders a collection).
- [ ] Nothing remounts: switching between library tabs and back does not
      flash or reload the grid (each patched component type is cached).
- [ ] The tab is not a collection: *Collections* has no *Streaming* entry,
      and on a second machine signed into the account nothing appears.
- [ ] **Upgrade from v0.4.0**: the old *Streaming* collection loses this
      device's owned games and shortcuts at the first load and is gone
      once empty; a member the plugin never made (add one by hand first)
      stays, and so does the collection.
- [ ] After a sync that adds or removes a title, the tab follows without
      reopening the library (its content reads the store).
- [ ] *Hide Stream shortcuts* off: the Streaming tab stays (its tiles
      unchanged) and a *Streaming* collection appears within a moment
      with the Stream shortcuts and the visible shortcuts, no owned game.
      On again: the collection and its shortcuts stay (hidden, so the
      collection looks empty in the library), and the tab is untouched.
- [ ] *Streaming tab* off: the tab is gone (leave the library and come
      back) and this device's shortcuts leave the collection, parked ones
      too (deleted once empty). On: both back.
- [ ] The first sync with the collection in effect on a fresh install
      creates it with every member in it: whether the client lists a
      just-added member at once is unmeasured, so the reconcile never
      deletes on the pass that added; if the collection is there but
      empty after that pass, the next reconcile (open the Titles page)
      must **not** delete it.
- [ ] Switch hosts and sync: the tab shows the new host's titles only.
- [ ] *Remove everything*: after the restart the tab reads "Nothing to
      stream from … yet" and, with the collection in effect, the
      collection is gone once the client has dropped the removed
      shortcuts.
- [ ] Unload the plugin (Decky → the plugin's menu → Uninstall, or a
      reload): leave the library and come back: the tab is gone, and the
      library still works if it had been the active tab.
