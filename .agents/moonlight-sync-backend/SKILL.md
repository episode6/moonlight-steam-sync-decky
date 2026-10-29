---
name: moonlight-sync-backend
description: >-
  The Moonlight Sync plugin's Python backend and the callable contract:
  main.py (the Decky Plugin class), py_modules/moonlight_sync backend.py
  (every callable, _spawn, NDJSON relay, busy guard, timeouts, _child_env),
  install.py, settings.py (settings.json, pending.json, layouts.json,
  added.json), keys.py, wake.py (Wake-on-LAN), events.py; result and error
  codes, the CLI argv and --hide-host-apps, pending-write rules, layouts.json
  / record_layout / set_default_layout, reset_match_cache, the Recently added
  record, the enabled toggle, and Decision 66 (no Moonlight command unasked).
  Load before adding or changing a backend callable, a settings key, a file
  the backend writes, how the CLI is spawned, or any event / result shape the
  frontend reads.
---

# Moonlight Sync backend and its contract

Reference split out of the root `AGENTS.md`, whose hard rules (cited here as
"hard rule N") apply throughout. Related: `moonlight-sync-sgdb-key-fetch`
and `moonlight-sync-update-staging` (the backend's two larger features),
`moonlight-sync-updater` (the self-update settings),
`moonlight-sync-testing` (fake_cli.py, fixtures, conftest).

## Module map: the backend

```
main.py                     thin decky Plugin: builds Backend, one line per callable;
                            no __init__ and `_backend` / `_startup` as class attributes, with
                            `_get` / `_ready` as classmethods, so it is correct whether the
                            loader instantiates the class (api_version > 0, ours) or calls
                            through the bare class (api_version 0); passes
                            `getattr(decky, "DECKY_VERSION", "")` as the Backend's
                            `loader_version` and `decky.DECKY_PLUGIN_RUNTIME_DIR` as its
                            `runtime_dir` (never an `update_source`: the downloads
                            always come from this repository's releases);
                            `stage_update(tag, sha256, version=None, ref=None)` and
                            `cancel_update()` (update spec §3.12.3); `_uninstall` is
                            `pass` on purpose (Decky runs it on every update, hard rule
                            12, update spec §2.3 / §3.3)
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
                            {removed, titles, pins} for the toast; no CLI);
                            the staging (update spec 3.12.3): `runtime_dir`,
                            `update_source` (an `updates.Source`, the tests' seam),
                            FETCH_SCRIPT (fetch.py beside it), _fetch() (the
                            downloader as `[python, "-I", fetch.py, options, "--",
                            url, dest]` through _child_env(), stderr to /dev/null,
                            one stdout line of at most FETCH_LINE_LIMIT, killed after
                            its timeout + FETCH_ANSWER_GRACE, which answers `timeout`
                            with that limit as `timeout_s`; a cancel that landed
                            during the spawn kills it as soon as it exists; no
                            line or anything but an object with a boolean `ok` is
                            `io`), stage_update() (the seven
                            steps; UpdateJob is its "update" busy guard, released on
                            every exit with the sidecar and any part file removed),
                            cancel_update() / _cancel_staging() (unload's: kill,
                            wait, remove *.part), startup's updates.cleanup(),
                            cli_version()'s `build` (updates.read_build)
  install.py                read_version() / read_version_text(), is_snapshot(),
                            MIN_CLI_VERSION, atomic install/upgrade; sha256_file();
                            an equal version with other bytes is `replaced`
                            (Decision U12), so is a snapshot (.dev0 / -SNAPSHOT)
                            when the bundle is a release, a newer one `kept`
  settings.py               settings.json / ignore.json / owned-apps.json /
                            pending.json / layouts.json / added.json, all .tmp +
                            os.replace; added() / note_titles() (`added.json`,
                            `{version: 1, titles: {<Moonlight name>: <when> | null}}`:
                            the names `status` lists, a new one stamped, a known one
                            kept, a gone one dropped, the first call all `null`);
                            pending()'s `synced_hosts` seed for an older file
                            (the last plan's host, stamped `since`);
                            `update_channel` (update spec 3.12.4): is_channel()
                            (exactly `stable`, or `branch:` + a ref matching
                            updates.REF_RE), refused otherwise, a hand-broken
                            value read back as `stable`
  keys.py                   SteamGridDB key sources (config -> env -> file), key file
  wake.py                   Wake-on-LAN (spec 3.18): parse_mac(), magic_packet(),
                            moonlight_hosts() / moonlight_entries() / find_host() /
                            moonlight_host() (Moonlight.conf's [hosts] group, the
                            flatpak path then the native one, read only: QSettings
                            INI, the MAC an @ByteArray of 6 bytes or empty, the
                            whole value quoted when a raw byte is a comma or a
                            bracket -- a device's 2026-09-23; hosts() reads the
                            entries once for its whole map),
                            send_magic_packet() (broadcast + every address Moonlight
                            knows, WAKE_PORTS; the SOCKET seam so no test sends a
                            datagram; run through asyncio.to_thread, since a hostname
                            among the addresses resolves with a blocking
                            getaddrinfo). Moonlight's CLI has no wake action
                            (list / quit / stream / pair only), so the plugin sends
                            it. But every one of those actions wakes the host on
                            its own (ComputerSeeker calls NvComputer::wake() before
                            it looks; a magic packet captured 2026-09-23), which is
                            why no Moonlight command ever runs unasked (Decision 66)
  events.py                 parse_line(), restart_decision(), next_pending()
```

## Backend contract

Every callable returns `{"ok": true, …}` or `{"ok": false, "error": <code>,
"message": …}` (codes: `cli-missing`, `cli-too-old`, `cli-protocol`,
`cli-error`, `timeout`, `busy`, `owned-apps-missing`, `owned-apps-empty`,
`bad-request`, `io`, `no-mac`, `no-debugger`, `cancelled`, `sgdb-page`,
`network`, `bad-release`, `hash-mismatch`, `bad-zip`) and
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
finished. `synced_hosts` (`{<host>: <when>}`) gains the plan's host
whenever a `sync` reached its `plan`, whatever the exit, and never loses
one: the host cache cannot say "synced", since a *Check* or an `add_host`
writes it too. A `pending.json` from before the key reads as the last
plan's host alone (`settings._legacy_synced_hosts`). `restart_countdown_s` is 0-30 everywhere
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
The Titles page's *Recently added* order (spec 3.21, the user's
decision of 2026-09-28) is the plugin's own record, since nothing
else has one: the CLI keeps no time per shortcut, `shortcuts.vdf` has
none, and a run's `title` events name the titles that were already there
too (the art phase covers every owned entry), so they cannot say what a
sync added. `status()` therefore carries an additive `added`
(`{<Moonlight name>: <iso time> | null}` over the entries it just read,
never the client entry nor a `host_app` one: a new host's `Desktop` /
`Steam Big Picture` would otherwise sit among the games its first sync
added, PR 68's review) and keeps it in `added.json`
(`Backend._note_added` -> `Store.note_titles`): a name seen for the first
time is stamped with `iso_now()`, a known one keeps its time, one that is
gone is dropped (so a title removed and synced again counts as added
again), and the very first call, with no readable file, records every
name with `null`, "there before the plugin kept track". The stamp is the
first `status` after the sync that added the title (the frontend asks for
one when a run ends and at every load), not the commit itself; the titles
of one sync share it. A kind flip keeps the name, so a replaced entry is
not new; a sync run from the bare CLI is stamped at the plugin's next
`status`. The record is by Moonlight name, across hosts, not per host or
per entry, which is the shortcut's own identity (its appid is `crc32(Exe
+ AppName)`): `status` lists every host's entries, so a name another
host's parked entry already carries is known, and the active host
publishing it later unparks that entry and stamps nothing. Nothing is
awaited between `note_titles`'s read and its write, so two `status` calls
in flight at once (`refreshStatus` and `loadTitles` when a run ends with
the Titles page open) record one after the other and the second keeps
the first's stamp. A file that cannot be written fails nothing (`status` answers
the times it has), a broken one reads as no file, and a failed `status`
records nothing. No CLI flag, event or file is involved (hard rules 1 and
7 stand). `settings.titles_recent_first` (default `false`,
`BOOL_SETTINGS`, a plain `set_settings` key) is the chip's state, so the
page reopens in the order last chosen; the frontend reads it through
`join.ts`'s `titleSortOf` and sorts with `sortRows` after the filter,
before the pages of 50. `tests/test_backend.py` holds the record (the
baseline, the stamp, the drop, a host app never stamped, two calls at
once, the unchanged file not rewritten, broken files, a refused write),
`__tests__/join.test.ts` the order, and
`controller.test.ts` that `loadTitles` hands `added` on (`{}` from a
backend without it or a failed `status`) and that the setting moves
nothing in the library.
The on/off toggle (spec 3.19) is one boolean, `settings.enabled` (default
`true`, `BOOL_SETTINGS` in `settings.py`, a plain `set_settings` key): the
backend knows nothing else of it, the frontend reads it everywhere it
touches the client (`pluginEnabled`), and a run started before the toggle
went off finishes on its own.

Wake-on-LAN (spec 3.18) needs no CLI and no busy guard: `hosts()` carries
an additive `wake` map (`{<host>: {mac, source, addresses}}` over the known
hosts plus the active one when it is not among them, from Moonlight's own
`Moonlight.conf` entry, read once per call, `source` always `"moonlight"`;
a host Moonlight has no MAC for is absent, and the panel shows no *Wake*
for it); `wake_host(name)` sends the magic packet to the broadcast
address and every address Moonlight knows for the host on `WAKE_PORTS`, in
a worker thread (a hostname among them resolves with a blocking
`getaddrinfo`), answers `{host, mac, source, sent}`, `no-mac` when
Moonlight knows no MAC, `io` only when not one datagram went out, and
drops the `check_host` memo so the next *Check* asks. The Host page's MAC
field, `set_wake_mac` and the `wake_macs` setting went on 2026-09-26 (the
user's decision: rely on Moonlight's settings alone); `wake_macs` is a
retired key (`settings.RETIRED_SETTINGS`): left in an older file, never
reported, refused by `set_settings`. Sending proves nothing about the PC,
so the frontend's toast says to Check in a minute rather than polling.
**No Moonlight command runs unasked (Decision 66, the user's
2026-09-23).** Moonlight's command line sends a magic packet on every
`list` and `stream` (its ComputerSeeker wakes the matching host before it
looks; captured on the LAN, the PC came up), so the plugin runs a
Moonlight command only on the user's *Check*, on `add_host`, on a run and
on a Stream press: `check_host` is not called at load, on panel open, when
the toggle goes on, after a library retry or after an add, and the Titles
page reads `list_cached` only (`list_apps` stays for the contract, called
by nothing in the frontend). A finished sync and a made-active add each
stand in for the check (`reachFromRun`, `add_host`'s `count`). The CLI's
`status`, `host show`, `match`, `search`,
`art` and `remove` never run Moonlight and are unaffected.
