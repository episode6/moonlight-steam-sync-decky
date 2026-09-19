# Moonlight Sync

A [Decky Loader](https://github.com/SteamDeckHomebrew/decky-loader) plugin
that runs [moonlight-steam-sync](https://github.com/episode6/moonlight-steam-sync)
from Game Mode. One press of **Sync now** in the Quick Access menu lists
what your Moonlight host publishes, adds a dressed Steam shortcut (with
artwork from Steam's CDN and SteamGridDB) for each title, and restarts Steam
once so the library shows them. Games your Deck's Steam account already owns
get a hidden shortcut instead of a second tile; the **Stream** button that
puts on the game's own library page comes in a later release.

Nothing runs on the gaming PC: the plugin needs only a stock
Sunshine / Apollo / GeForce host that the Deck's Moonlight client is paired
with.

**Status:** in development (plugin `0.1.0`, unreleased). Built and tested
off-device only; it has **not been run on a Steam Deck yet**. It needs
moonlight-steam-sync **0.3.0**, which is not released yet either.

## Requirements

- SteamOS (Steam Deck or a Deck-like) with Decky Loader.
- A Moonlight client on the Deck (native `moonlight` or the Flathub
  flatpak), already paired with your host.
- moonlight-steam-sync **0.3.0 or newer**. The plugin bundles the version it
  was built for and installs it for you (below), so there is nothing to
  install separately.

## Install (manual)

There is no store listing yet. Download `Moonlight-Sync.zip` (from a
release once one exists; until then, from the `Moonlight-Sync` artifact of
a CI run), copy it to the Deck, and in a Desktop Mode terminal or over SSH:

```sh
sudo unzip -o Moonlight-Sync.zip -d ~/homebrew/plugins/
sudo systemctl restart plugin_loader
```

The zip holds a single `Moonlight Sync/` directory, which is the plugin's
directory under `~/homebrew/plugins/` (`sudo` because Decky's plugin
directory belongs to root on a stock install). Restarting `plugin_loader`
loads it; Moonlight Sync then appears in the Quick Access menu's Decky tab.

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
minimum the plugin needs (0.3.0) and any install error. If the installed CLI
is missing or older than 0.3.0 the panel shows a single row, "CLI not
installed — see About" or "CLI too old (0.2.0, needs 0.3.0) — see About",
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
- Four counters from the last status: **Stream buttons** (hidden entries for
  games you own), **Shortcuts**, **Unmatched**, **Ignored**; and **Last
  sync** ("Today 14:02 · 2 added, 1 removed").

On the very first run there is no host yet: the panel says "No host yet" and
**Add a host** opens the Host page.

## The one restart

Steam only reads `shortcuts.vdf` at startup, so a sync that changes it ends
in one Steam restart. The CLI does all the work (listing, matching, every
image) while Steam keeps running, then waits for Steam to exit. The plugin
asks: "Sync finished: 2 added, 1 replaced — Restarting Steam in 5 s to show
them", with **Restart now** and **Later** (B). The countdown length is a
setting (0 means no countdown, just the buttons), and it never starts while
a game is running ("A game is running. Restart Steam when you're done.").

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

Settings → **Advanced** has *Copy controller layouts from the Steam game*
(used by a later release), the restart countdown, and **Remove everything
this plugin created** (every shortcut, hidden entry and image the tool made;
pins and ignored titles are kept; Steam restarts once).

## Files

Everything the plugin writes lives in its own directories, never under
Steam's:

- `~/homebrew/settings/Moonlight Sync/`: `settings.json`, `ignore.json`,
  `owned-apps.json` (the owned games, rewritten before every sync),
  `pending.json` (a restart that is still pending), `layouts.json`.
- `~/homebrew/logs/Moonlight Sync/moonlight-sync.log`: every CLI call with
  its arguments, the CLI's own messages verbatim, and both CLI versions at
  startup.
- `~/.local/bin/moonlight-steam-sync` (the CLI install) and the SteamGridDB
  key file above.

`settings.json` also carries `layout_strategy` (`"copy"` or `"picker"`),
which has no UI and is only for testing the controller-layout behaviour of a
later release by hand.

What the plugin never does: write `shortcuts.vdf`, anything under Steam's
`userdata/` or `grid/`, or controller config files (the CLI is the one
writer); call Steam's live shortcut APIs (`AddShortcut`, `RemoveShortcut`,
`SetShortcutName`, `SetAppLaunchOptions`, `SetAppHiddenState`,
`SetCustomArtworkForApp`); write the CLI's `config.toml`; run as root; or
install anything on the gaming PC.

## Developing

Needs Node 20+ with pnpm 9, and Python 3.13 (what SteamOS ships). No Docker:
the plugin zip is built by `scripts/package.py`, which reproduces the Decky
CLI's layout.

```sh
pnpm install
pnpm run build                 # dist/index.js
backend/entrypoint.sh          # the pinned CLI -> backend/out/ (strict: fails until it is released)
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
