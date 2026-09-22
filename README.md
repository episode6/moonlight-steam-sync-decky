# Moonlight Sync

A [Decky Loader](https://github.com/SteamDeckHomebrew/decky-loader) plugin
that runs [moonlight-steam-sync](https://github.com/episode6/moonlight-steam-sync)
from Game Mode. One press of **Sync now** in the Quick Access menu lists
what your Moonlight host publishes, adds a dressed Steam shortcut (with
artwork from Steam's CDN and SteamGridDB) for each title, and restarts Steam
once so the library shows them. Games your Deck's Steam account already owns
get a hidden shortcut instead of a second tile, and a **Stream** button on
the game's own library page that launches it. A **Titles** page lists every
title with what it was matched to, and is where a wrong match gets fixed.

Nothing runs on the gaming PC: the plugin needs only a stock
Sunshine / Apollo / GeForce host that the Deck's Moonlight client is paired
with.

**Status:** released through `v0.5.0`. Its first device run (a generic
SteamOS machine) produced the `v0.1.1` fixes; it has **not been run on a
Steam Deck yet** (`DEVICE-CHECKLIST.md`). It bundles moonlight-steam-sync
**0.4.0** and needs 0.4.0 or newer.

## Requirements

- SteamOS (Steam Deck or a Deck-like) with Decky Loader.
- A Moonlight client on the Deck (native `moonlight` or the Flathub
  flatpak), already paired with your host.
- moonlight-steam-sync **0.4.0 or newer**. The plugin bundles the version it
  was built for and installs it for you (below), so there is nothing to
  install separately.

## Install

There is no store listing yet; install from the GitHub release with the
one-liner below, or by hand ("Manual install"). To run something newer than
the latest release, build from source (see "Developing") or use the
`Moonlight-Sync` artifact of a CI run as the manual zip.

```sh
curl -fsSL https://raw.githubusercontent.com/episode6/moonlight-steam-sync-decky/main/install.sh | sh
```

`install.sh` downloads the latest (or a `MOONLIGHT_SYNC_VERSION`-pinned)
release's `Moonlight-Sync.zip` and its `.sha256`, verifies the checksum,
removes any previous `Moonlight Sync/` install so files an older release
shipped and the new one no longer does cannot linger, unzips the new one
into `~/homebrew/plugins/` and restarts `plugin_loader` so the new plugin
loads. Both the install and the restart run through `sudo` (Decky's plugin
directory belongs to root on a stock install), so you will be asked for
your password twice on the terminal; the script never runs `sudo`
non-interactively. A stock Steam Deck ships with no password for the
`deck` user, so if you have never set one, run `passwd` in a Desktop Mode
terminal first. It is safe to re-run: it always re-downloads and
reinstalls, even when already current, so re-running it is also how you
pick up a new release.

### Manual install

Download `Moonlight-Sync.zip` from a release, copy it to the Deck, and in a
Desktop Mode terminal or over SSH:

```sh
sudo rm -rf ~/homebrew/plugins/"Moonlight Sync"
sudo unzip -o Moonlight-Sync.zip -d ~/homebrew/plugins/
sudo systemctl restart plugin_loader
```

The zip holds a single `Moonlight Sync/` directory, which is the plugin's
directory under `~/homebrew/plugins/`. Restarting `plugin_loader` loads it;
Moonlight Sync then appears in the Quick Access menu's Decky tab.

### Uninstall

```sh
sudo rm -rf ~/homebrew/plugins/"Moonlight Sync"
sudo systemctl restart plugin_loader
```

This removes only the plugin. It never touches the CLI it bundled
(`~/.local/bin/moonlight-steam-sync`), your Steam shortcuts, or anything
under the Steam directory (the CLI is the only writer there, see "Hard
rules" in `AGENTS.md`); uninstall the CLI separately if you want it gone
too — see [episode6/moonlight-steam-sync](https://github.com/episode6/moonlight-steam-sync)
for how it was installed and how to remove it.

None of this has been run on a real Steam Deck yet; see
[`DEVICE-CHECKLIST.md`](DEVICE-CHECKLIST.md) for the full list of on-device
checks to run once you have one.

## The bundled CLI

The zip carries `bin/moonlight-steam-sync.pyz`, the CLI release pinned in
`package.json` (`"moonlightSteamSync"`). Every time the plugin loads it
compares that copy with `~/.local/bin/moonlight-steam-sync`:

- missing there, or older → the bundled one is copied into place
  (atomically, `~/.local/bin` is created if needed);
- the same or newer → left alone. A newer CLI you installed by hand stays.

The plugin always runs the copy in `~/.local/bin`, through `python3`, so a
shortcut made from Game Mode and one made from a terminal belong to the same
tool. Settings → **About** shows both versions, the pinned release, the
minimum the plugin needs (0.4.0) and any install error. If the installed CLI
is missing or older than 0.4.0 the panel shows a single row, "CLI not
installed — see About" or "CLI too old (0.2.0, needs 0.4.0) — see About",
and every CLI action is disabled; the settings pages that only touch the
plugin's own files keep working. A zip packaged before the CLI release
existed has no bundle; About then says "bundled CLI: none (built before the
CLI release)" and you can install the CLI with its own `install.sh`.

## The Quick Access panel

- **Host**: a dropdown of your known hosts with the active one selected. A
  green dot and "N apps" when `moonlight list` answered; a red dot, the
  error, and "last seen <when>" from the last successful listing when it did
  not (checked each time the menu opens, at most every 10 s; **Retry**
  checks again). Choosing another host asks first ("Switch to OFFICE-PC?
  MY-GAMING-PC's tiles are parked, not removed"), then switches and syncs.
- **Sync now**: the full sync. While it runs the panel shows a progress bar
  over the titles, the last five titles and where their images came from,
  the plan, and **Stop** (everything done so far is kept; sync again to
  resume).
- **Open Moonlight**: starts the Moonlight client itself, through a hidden
  "Moonlight" shortcut the first sync creates (until then it reads "Sync
  once to enable").
- **Desktop** and **Steam Big Picture**: the two entries every Sunshine /
  Apollo host publishes by default get a button each, which launches that
  entry's synced shortcut. **These buttons replace the two library tiles:**
  every sync the plugin runs passes `--hide-host-apps`, so the CLI keeps the
  two shortcuts (Steam's controller layouts are per shortcut) but writes
  them hidden. On an existing install the first sync hides the two tiles in
  place: same appid, so their artwork and any controller layout you chose
  are untouched. A button only shows when the active host publishes the
  entry and it is not ignored (an ignored entry has no shortcut to launch).
  Like the Stream button, they do nothing while a game is already running.
  - The small **gamepad button** beside each one (*Choose controller layout
    for Desktop* / *… Steam Big Picture*) opens Steam's controller
    configurator for that hidden entry, which has no library page to reach
    it from. It works while a game is running too, since it starts nothing,
    and it is left out on a Steam client that cannot open the configurator.
  - **Getting the tiles back.** There is no plugin setting for this. From a
    terminal (Desktop Mode or SSH), run the plugin's own sync without
    `--hide-host-apps`:

    ```sh
    cd ~/homebrew/settings/"Moonlight Sync"
    moonlight-steam-sync sync --owned-apps owned-apps.json \
      --ignore-file ignore.json --client-shortcut --park-unpublished
    ```

    The CLI sees two published, hidden shortcuts and shows them again (it
    restarts Steam to write, as a terminal sync always does). Keep the other
    flags: a bare `sync --park-unpublished` knows nothing of your owned
    games or the plugin's ignore list, so it would also turn Stream buttons
    back into visible tiles and re-add every title ignored on the Titles
    page. The exact command the plugin last ran is in
    `~/homebrew/logs/Moonlight Sync/moonlight-sync.log`. The next sync from
    the plugin hides the two again, so
    this only lasts if you sync from the terminal from then on. A host whose
    two entries were renamed is not affected: only the names `Desktop` and
    `Steam Big Picture` (any case) are host apps.
- Four counters from the last status: **Stream buttons** (hidden entries for
  games you own), **Shortcuts**, **Unmatched**, **Ignored**; and **Last
  sync** ("Today 14:02 · 2 added, 1 removed"). The two host apps count
  toward none of the first three.

On the very first run there is no host yet: the panel says "No host yet" and
**Add a host** opens the Host page.

## The Stream button

A title the host publishes that resolves to a game this Steam account owns
gets no visible tile. Instead its real library page grows a **Stream**
button (a row under the header, above Play / Install), with a note saying
which host it streams from and, while a default controller layout is set,
the state of its layout. Pressing it runs the hidden shortcut the sync
created, so Steam owns the session: the overlay works, the Recent Games
shelf shows it, and the layout picked for that hidden entry applies. The
button appears only while the active host publishes the game (the last
`status` says the entry is hidden, not parked and published); switch hosts
and the other host's buttons go away until you switch back. While any game
is running a press only shows "Something is already running".

The button is added to the library page by patching Steam's
`/library/app/:appid` route with Decky's own primitives, and it is the
only thing the plugin changes on that page. Nothing is written to Steam's
files by the plugin: the hidden shortcut is the CLI's, and the button just
runs it.

## Hidden shortcuts and the Streaming tab

The CLI marks the shortcut behind every Stream button (and the Moonlight
client entry, `Desktop` / `Steam Big Picture`, and another host's parked
titles) `IsHidden` in `shortcuts.vdf`. The current Steam client ignores that
field: what is hidden lives in the client's own *Hidden* collection, which
only the running client can change. So after every `status` (at load, after
a sync, on the Titles page) the plugin brings the client in line, changing
only what differs:

- **Hidden.** Every entry the CLI calls hidden is hidden in the client, and
  every entry it calls visible is shown (which is what brings a parked tile
  back). Settings → **Advanced** → *Hide Stream shortcuts* (on by default)
  governs the Stream-button shortcuts only. Turn it off to have them under
  *Non-Steam* again, where a streamed game comes to the front of Home as
  its shortcut; the client entry, the two host apps and parked titles stay
  hidden either way. Because the CLI's word is final here, hide a Moonlight
  title with **Ignore** on the Titles page rather than Steam's own *Hide
  this game*, which the next sync would undo.
- **The *Streaming* tab.** A tab of the library's own tab bar, after
  *Non-Steam*, with one tile for every title the active host can stream
  right now: the real Steam game when it has a Stream button, the
  Moonlight shortcut otherwise. It is drawn by the plugin from the client's
  own grid and written nowhere: it is not a collection, so it does not
  sync through Steam Cloud, and two devices synced to different hosts each
  see their own. (Earlier versions kept a real *Streaming* collection; its
  owned games synced to every machine, and two devices on different hosts
  kept removing each other's. On upgrade the plugin takes this device's
  games out of that collection and deletes it once it is empty.) Settings
  → **Advanced** → *Streaming tab* (on by default) turns it off.
- **The shortcut collection.** With *Hide Stream shortcuts* off, the tab
  stays and a real *Streaming* collection comes alongside it, holding this
  device's Moonlight shortcuts only, never an owned game. It is found by
  its name; the plugin only ever adds its own entries and removes them
  again while it keeps the collection (that is, while *Hide Stream
  shortcuts* is off), so anything else in it (another device's shortcuts,
  a title you put there) stays, and it is deleted once nothing is left in
  it. Two devices under one account get the same appid for a shortcut of
  the same title, so a device with the tab alone leaves shortcut members
  where they are (hidden, so out of sight) rather than fight a device
  that keeps the collection; a parked title is left alone for the same
  reason. The *Streaming tab* toggle turned off takes every entry this
  device knows out. While another device still runs a version with the
  old collection, it keeps putting its owned games back and this one
  keeps taking them out; upgrade both.

Right after a sync's restart both wait (up to 90 s) for the client to load
its shortcut list; anything still missing then is picked up the next time.
On a client without these calls the two toggles are disabled and say so.

## The one restart

Steam only reads `shortcuts.vdf` at startup, so a sync that changes it ends
in one Steam restart. The CLI does all the work (listing, matching, every
image) while Steam keeps running, then waits for Steam to exit. The plugin
asks: "Sync finished: 2 added, 1 replaced — Restarting Steam in 5 s to show
them", with **Restart now** and **Later** (B). The countdown length is a
setting, 0 to 30 seconds (0 means no countdown, just the buttons; the
ceiling is 30 because the CLI stops waiting for Steam after 60 s, and a
longer countdown would race it), and it never starts while a game is
running ("A game is running. Restart Steam when you're done.").

In Game Mode, asking Steam to shut down *is* the restart: the session brings
it straight back, and the CLI writes the file in between. **Later** stops
the waiting CLI without writing anything and leaves a **Restart Steam to
apply** row in the panel; pressing it runs the sync again (no downloads:
everything is cached) and restarts at once. A sync that only saved new
artwork (nothing to write) offers the same restart ("New artwork needs a
Steam restart to show"), and so does a stopped sync that saved images. The
pending restart survives the plugin reloading.

## Hosts

Settings → **Host** lists the hosts you added, each with its cached title
count and when it was last seen, the active one marked:

- **Add host**: type the name Moonlight knows the PC by and press **Check
  and add**. The plugin runs `moonlight list` against it as the pairing
  check (there is nothing on the PC to ask); it is added only when that
  works. The first host you add becomes the active one.
- **Switch**: parks the current host's tiles (hidden, with their art and
  layouts kept) and syncs the other host. Switching back later is one
  listing, no downloads and one restart.
- **Forget**: removes a host from the list (not the active one). Its parked
  tiles stay until you remove everything.

## The Titles page

The list button in the panel's header (or Settings → **Titles**) opens
every title the active host publishes, sorted by name, with what the next
sync does with it. Each row has Steam's library capsule when the title is
matched to a Steam game (a striped placeholder otherwise), the name, the
match line (`Balatro · Steam 2379780`, `Sea of Stars · SGDB 5322710`, or
`no match`) and one badge:

- **stream button**: matched to a game this Steam account owns; a hidden
  shortcut named after the game, whose library page gets the Stream button.
- **shortcut**: a visible shortcut with artwork, as today.
- **unmatched**: a shortcut without a Steam or SteamGridDB match.
- **host app**: `Desktop` or `Steam Big Picture`, a hidden shortcut the
  panel's button launches (see "The Quick Access panel"). It is listed
  under *All* only. **Change match** still works and only changes its
  artwork (every result reads **art only**: no match makes a host app a
  Stream button); **Layout** → *Choose layout…* opens its controller
  configurator, and *Use as the default layout* adopts the layout it has;
  **Ignore** removes the entry, and its panel button, on the next sync.
- **ignored**: nothing is created for it.
- **duplicate**: matched to the same owned game as another title (the line
  reads "same game as …"); the first title gets the hidden entry and this
  one gets no tile at all. It is almost always a wrong match: change it, or
  pin it to *No match* to give it its own tile.
- **parked**: a title only another host publishes, hidden in place with its
  art kept. Parked titles are left out until you press **Show parked**, and
  then listed under *All*.

Chips flag what is worth a look: **fuzzy** (matched by a fuzzy title
search, which never makes a Stream button), **pinned** (you chose the
match), **same game on OFFICE-PC as "…"** (the other host publishes this
game under a different name; align the names on the host side or pin one),
and **art refreshes on next sync** (after a pin). The filters are *All*,
*Stream buttons*, *Shortcuts*, *Unmatched* and *Ignored*; rows render 50 at
a time with a "Show 50 more" row at the end, so a 500-title host stays
quick to scroll with the D-pad. When the host is unreachable the page shows
the last listing it cached ("titles cached from <when>"), or says it was
never synced. While a sync is running it shows that cached listing too
("refreshes when the sync finishes") instead of asking the host again in
the middle of the run, and re-lists on its own as soon as the run ends.

**Change match** searches Steam's store and SteamGridDB (prefilled with
the title's name; edit it and **Search** again) and shows the results as
one list, the games this account owns first, then Steam's results before
SteamGridDB's, each with what it would make of the title: **becomes stream
button** for a game this account owns, **shortcut** otherwise (**art only** for every result on a host-app row). The current match is marked, and the last row is
**No match** (a plain shortcut with art found by name on SteamGridDB).
Pressing a row pins it; **Cancel** (B) changes nothing. Changing a match is
disabled while a sync runs.

**How a pin becomes a Stream button.** A pin is written to the CLI's own
match cache (`how: "pinned"`, the same `matches.json` a terminal run
uses) and nothing else changes yet ("Pinned; sync to apply"): no Steam
restart per pin. On the next **Sync now** the CLI sees the pin, and a pin
counts as an exact match, so a title pinned to a game you own becomes a
**stream button**: its visible shortcut is replaced by a hidden one named
after the Steam game, the art is fetched again from the new match, and the
usual one restart shows the result. Pinning anything else, or *No match*,
keeps the title a shortcut with art from the new match. Pins survive
**Re-fetch all art** and **Retry missing art**; an `[overrides]` entry in
`config.toml` still wins over a pin (the modal says so when one applies).

**Ignore** adds the title to the plugin's ignore list (`ignore.json`,
passed to the CLI as `--ignore-file`) and **Unignore** takes it out; the
next sync applies it. A title ignored in the CLI's `config.toml` reads
"Ignored in config.toml" and can only be unignored there, since the plugin
never writes that file.

## Controller layouts

Steam keeps a controller layout per app, and everything the plugin
manages is a stream: a streamed game runs as its own hidden shortcut, so
the layout you picked for the real game does not apply to it by itself.
The plugin therefore keeps **one default controller layout** that every
entry it manages starts on, and each title stays customisable on its own.

- **Adopting a default.** There is no layout list of the plugin's own (Steam
  has no API that returns a picked layout by name). Instead, set a layout up
  on any title with Steam's own configurator (Titles → **Layout** → *Choose
  layout…*, or the game's controller settings), then on that title's row
  choose **Layout** → *Use as the default layout*. The plugin reads the
  layout that title has for the controller in use, asks you to confirm, and
  puts it on every entry that has no layout of its own: Stream buttons'
  hidden shortcuts, visible shortcuts, `Desktop` / `Steam Big Picture` and
  the Moonlight entry. A toast says how many titles took it and how many
  kept their own. Parked titles (another host's) get it when they come
  back.
- **What can be a default.** A community layout or a personal layout you
  **exported** (both read back from Steam Input as `workshop://…`), or one
  of Steam's built-in templates (`template://…`). A layout you edited in
  place without exporting only exists for that one title (`autosave://…`):
  *Use as the default layout* refuses it and says so. In Steam's layout
  screen choose **Export**, select the exported copy on that title, then
  try again. A title that has no layout chosen yet cannot be adopted from
  either.
- **What is overwritten, and what never is.** The plugin only ever changes a
  selection it made itself (it remembers, per shortcut, the last layout it
  set). A layout you chose yourself on a title, a layout you edited in
  place after the default landed, and the title you adopted the default
  *from* are left alone, by every Stream press, every sync and every
  change of the default. A title still on the plugin's earlier default
  moves to the new one; a title copied from its Steam game by an older
  version of the plugin counts as plugin-set and moves too. A hand-picked
  layout that happens to be the same as the default is still yours.
- **When it runs.** On every press of a Stream button (before the launch;
  once the shortcut is on the default nothing is set again), once after a
  sync's Steam restart over every non-parked entry (as soon as Steam has
  loaded the shortcut list, polled every 2 s for up to 90 s; anything that
  never loads is recorded as unavailable and gets it on its next press),
  and at once when the default is set or cleared. Changing the default is
  not held back by a running game or a sync. While that walk is running,
  *Use as the default layout* answers "A layout walk is still running" and
  **Clear** is disabled; if the plugin has not loaded your titles yet (its
  status check failed), the change is kept and the toast says the layout is
  applied, or taken off, once they have loaded.
- **Clearing.** Settings → **Advanced** → *Default controller layout* shows
  the current default and has **Clear**, which takes the plugin's layout off
  every title that still has it (they go back to Steam's default; titles
  whose layout you chose yourself are left alone) and stops applying one.
  This uses a Steam client call that has not been measured on a device
  yet; on a client without it, the default is still cleared and titles keep
  the layout they have (the toast says so).
- **What you see.** Each row of the Titles page shows the last result for
  its entry: **default layout**, **own layout** (a choice of yours),
  **Steam default**, **unavailable** (no controller was connected, or the
  selection did not stick when read back) or **picker opened**. The
  library page's note next to the Stream button shows the same while a
  default is set. The results live in `layouts.json` in the plugin's
  settings directory; the plugin never writes Steam's controller config
  files, only asks Steam Input to select (or clear) a layout.
- **Which controller.** Layouts are per controller. The Deck's built-in
  controller is found by type, never assumed to be index 0 (a paired pad
  can take that slot). The sanctioned way is Steam's own type string
  (`controller_steamcontroller_neptune` from
  `ControllerStore.GetControllerTypeString`); *only* on a client without
  that function does the plugin fall back to the enum value `4`
  (`DECK_CONTROLLER_TYPE` in `src/lib/layouts.ts`), which is still
  unverified on a Deck. When the client has the type string its answer is
  final: another pad is never taken for the Deck's because it shares an
  enum value. On a device with no built-in controller (a SteamOS box with
  a separate pad) the plugin uses the active controller, or the only
  connected one; with several pads and none active, or none connected,
  nothing is set (**unavailable**, and *Use as the default layout* asks you
  to connect a controller first).

**The PR-0 device probes ran on 2026-09-20**, on a SteamOS machine with a
separate Steam Controller rather than a Deck. Probe V2 confirmed that a
`workshop://` layout published for one app, set on a shortcut through
`SetSelectedConfigForApp`, reads back and sticks -- provided the call
carries the fifth, selection-type argument Steam's own configurator passes
(with four it returns normally and does nothing). Probe V1 found a
community layout and an exported personal layout both read back as
`workshop://…`, a layout edited in place as `autosave:///…` (a file path
under one appid, which is why it is refused as a default), and an untouched
game as `template://…` with `bSelected: false` -- a layout Steam offers, not
one anybody chose, which the plugin therefore treats as no selection (a
fresh shortcut itself reads `default://<lowercased name>`). Whether a
`template://` default sticks on other titles, and the name and arguments of
the call that clears a selection, are still to be measured
(`DEVICE-CHECKLIST.md`); a `template://` that does not stick is recorded as
**unavailable** per title, never as a wrong layout. A Deck itself is still
untested. The fallback stays built in:

- `layout_strategy` in `settings.json` (`"copy"`, the default, or
  `"picker"`; no UI, edit the file by hand) switches the behaviour on a
  device without a rebuild. Under `picker` the plugin makes no Steam Input
  calls at all: a Stream press just launches, there is no walk after a
  sync's restart, the default layout is off (the Advanced field says so and
  *Use as the default layout* is not offered), and **Layout** → *Choose
  layout…* (recorded as *picker opened*) is the only layout affordance.
- The default lives in one place, `DEFAULT_LAYOUT_STRATEGY` in
  `src/lib/layouts.ts`. If a later client breaks the set, flipping that
  constant to `"picker"` and rewriting this section is the whole change.

## SteamGridDB key

Settings → **Artwork** has the SteamGridDB API key field (get a key at
steamgriddb.com/profile/preferences/api). The key is stored where the CLI
itself looks for it, `~/.config/moonlight-steam-sync/sgdb-api-key` (mode
0600), so the plugin and a terminal share one key. The CLI's precedence
applies: `[steamgriddb].api_key` in `config.toml` wins (the field is then
disabled and reads "set in config.toml"), then `SGDB_API_KEY` in the
environment ("set in the environment"), then the key file. The plugin
never writes `config.toml`, and it only ever shows the key's last four
characters. **Test** runs a search to check the key; **Remove** deletes the
key file and nothing else. The same page has **Retry missing art** (look
again for images that were missing last time) and **Re-fetch all art**,
which needs a CLI whose `art` command accepts `--commit` and says "needs a
newer CLI" otherwise.

Settings → **Advanced** has *Default controller layout* with its **Clear**
button (see "Controller layouts"; the default itself is adopted from a
title's row on the Titles page), *Hide Stream shortcuts*, *Streaming
tab*, the restart countdown (0-30 s), and **Remove everything
this plugin created** (every shortcut, hidden entry and image the tool made;
pins and ignored titles are kept; Steam restarts once; the layout records
go with the entries).

## Files

Everything the plugin writes lives in its own directories, never under
Steam's:

- `~/homebrew/settings/Moonlight Sync/`: `settings.json`, `ignore.json`
  (the Titles page's ignore list, a sorted JSON list of names),
  `owned-apps.json` (the owned games, rewritten before every sync),
  `pending.json` (a restart that is still pending, and whether the layout
  walk after a sync's restart is still due), `layouts.json` (the last
  layout result per hidden shortcut: `{"version": 1, "entries":
  {"<shortcut appid>": {"real_appid", "result", "url", "when",
  "applied"}}}`; `real_appid` is `null` for an entry with no Steam game
  behind it, such as Desktop / Steam Big Picture or the Moonlight client;
  `applied` is the last layout URL the plugin itself put on that shortcut,
  or `null` when the selection is one you made).
- `~/homebrew/logs/Moonlight Sync/moonlight-sync.log`: every CLI call with
  its arguments, the CLI's own messages verbatim, and both CLI versions at
  startup.
- `~/.local/bin/moonlight-steam-sync` (the CLI install) and the SteamGridDB
  key file above.

`settings.json` also carries `layout_strategy` (`"copy"` or `"picker"`),
which has no UI: it is the hand-editable switch described under
"Controller layouts", for trying the fallback on a device;
`hide_stream_shortcuts` / `streaming_collection` (the *Streaming tab*
toggle: the key kept its name), the two Advanced toggles above; and
`default_layout` (`null`, or `{"url", "title", "when"}`, the
adopted default controller layout), which the plugin changes only through
its own `set_default_layout` call, never through the other settings.

A pin from the Titles page is written by the CLI itself (`moonlight-steam-sync
match … --defer-art`) into its own match cache,
`~/.cache/moonlight-steam-sync/matches.json`, where a terminal run sees it
too.

What the plugin never does: write `shortcuts.vdf`, anything under Steam's
`userdata/` or `grid/`, or controller config files (the CLI is the one
writer); call Steam's live shortcut APIs (`AddShortcut`, `RemoveShortcut`,
`SetShortcutName`, `SetAppLaunchOptions`, `SetCustomArtworkForApp`); write
the CLI's `config.toml`; run as root; or install anything on the gaming PC.
The one thing it changes in the running client is the hidden state of the
CLI's own entries and the fallback *Streaming* collection (above), because
no file the CLI could write does either; the *Streaming* tab is drawn, not
stored.

## Developing

Needs Node 20+ with pnpm 9, and Python 3.13 (what SteamOS ships). No Docker:
the plugin zip is built by `scripts/package.py`, which reproduces the Decky
CLI's layout.

```sh
pnpm install
pnpm run build                 # dist/index.js
backend/entrypoint.sh          # the pinned CLI -> backend/out/ (strict: fails if the pinned release does not exist)
python3 scripts/package.py     # out/Moonlight-Sync.zip (warns and skips bin/ without the CLI)

pnpm run typecheck && pnpm run lint && pnpm run test
python3 -m pip install -r requirements-dev.txt
ruff check . && python3 -m pytest
```

Then copy `out/Moonlight-Sync.zip` to the Deck and install it as above.
`decky plugin build` (Docker) still works through `backend/Dockerfile` and
`backend/entrypoint.sh`, but it is only for a store submission. See
[`AGENTS.md`](AGENTS.md) for the module map and the test harness.

## License

MIT (see `LICENSE`). Scaffolded from the Decky plugin template (BSD
3-Clause); see [`THIRD_PARTY_NOTICES.md`](THIRD_PARTY_NOTICES.md).
