# Device probes for the Moonlight Sync plugin (spec PR-0)

Five measurements of undocumented Steam client behaviour that the plugin
design depends on. They run on a Steam Deck (or any SteamOS machine with
Decky Loader installed) with Steam in **Game Mode**. Nothing here is shipped:
`run_probes.py` is throwaway tooling and `steam-input-probe/` is a throwaway
Decky plugin. Neither writes under the Steam directory; the only
state-changing calls are the ones each probe is about (`SetSelectedConfigForApp`
on a shortcut you made for the purpose, `StartShutdown`, `RunGame`), and each
sits behind an explicit flag or button.

The results go into the spec (`~/specs/moonlight-steam-sync/decky-plugin.md`,
§2 amendment) and confirm or flip Decisions 3 and 9 before PR-3, PR-4 and
PR-7 are built. Paste them into the table at the end of this file first.

There are two ways to run the probes. **The scripted runner over SSH is the
primary one**; the button plugin is the fallback when the runner is not an
option (no SSH session you want to keep open, or the DevTools port refuses a
second client).

## 1. Primary: `run_probes.py` over SSH

### 1.1 One-time setup on the Deck

1. Switch to Desktop Mode once, open Konsole and give the `deck` user a
   password (SteamOS ships without one; `sudo` needs it):
   ```sh
   passwd
   ```
2. Enable SSH so the Deck can be driven while it sits in Game Mode:
   ```sh
   sudo systemctl enable --now sshd
   ```
3. Note the Deck's IP (Settings → Internet, or `ip -4 addr` in Konsole) and
   check the login from your PC: `ssh deck@<deck-ip>`.
4. Get this directory onto the Deck (SteamOS has `git` and Python 3.13.5;
   the runner needs nothing from the plugin build):
   ```sh
   git clone https://github.com/episode6/moonlight-steam-sync-decky ~/moonlight-steam-sync-decky
   # or, from the PC:  scp -r probes deck@<deck-ip>:~/probes
   ```
5. Create the venv with the runner's one dependency (the shipped CLI stays
   dependency-free; this is throwaway tooling):
   ```sh
   python3 -m venv ~/.cache/msy-probes && ~/.cache/msy-probes/bin/pip install websockets
   ```
6. Make sure Decky Loader is installed. Decky enables Steam's CEF remote
   debugging port (`http://localhost:8080/json`), which is what the runner
   talks to. With Steam in Game Mode, this must list a `SharedJSContext`
   target:
   ```sh
   curl -s http://localhost:8080/json | grep -c SharedJSContext
   ```
   If the port is closed the runner exits 3 with
   `is Decky installed and is Steam in Game Mode?`.

Below, `run_probes.py` means `~/.cache/msy-probes/bin/python3 ~/moonlight-steam-sync-decky/probes/run_probes.py`
(adjust the path if you copied `probes/` elsewhere). `--help` documents every
subcommand and works without the venv.

### 1.2 Pick the test games and make the throwaway shortcuts

Do this in Game Mode on the Deck, before running anything. You need four
Steam games you own and have installed, one per V1 case, plus two shortcuts.

| case | what to set up | how (Game Mode) |
|---|---|---|
| (a) community layout | a game whose controller layout is a **community Workshop layout** | game page → controller icon → *Community layouts* → pick any → *Apply layout* |
| (b) personal layout saved to the cloud | a game on a layout you **exported as a personal layout** | game page → controller icon → *Edit layout* → change one binding → gear → *Export layout* → name it, keep it personal (not shared) → back, then pick it under *Your layouts* → *Apply layout* |
| (c) edited in place (autosaved) | a game whose layout you changed **without exporting** | game page → controller icon → *Edit layout* → change one binding → press B to leave; do not export |
| (d) never touched | a game whose controller settings you have never opened | anything you have not customised |

Write down the four appids (the number in the game's store URL, or take them
from `run_probes.py v4`, which lists the library). Case (a) is also the game
whose Workshop layout is copied in V2, so pick one with community layouts.

Two throwaway **non-Steam shortcuts** for V2 and V5. Steam adds shortcuts
from Desktop Mode only: Desktop Mode → Steam → *Games* → *Add a Non-Steam
Game to My Library…* → tick any harmless program (a text editor is fine) →
*Add selected programs*. Then right-click the new entry → *Properties…* and
set the name:

- one named **exactly** like game (a), character for character (the V2 "same
  name" case; §2.2 of the spec says Steam Input keys a shortcut's layout by
  lowercased name);
- one named differently, e.g. `msy probe shortcut` (the V2 "different name"
  case; also the V5 launch target).

Repeat the Properties step for the second shortcut. Return to Game Mode.
Their appids are the ones `run_probes.py v4` prints under `shortcuts`
(every appid at or above `0x80000000` = 2147483648). Delete both shortcuts
when the probes are done; the plugin never creates or removes shortcuts.

### 1.3 Run the probes, in this order

Steam in Game Mode, SSH session open, all from the Deck:

```sh
# V4: library shape and steamid3 (read-only). Also prints the shortcut appids.
run_probes.py v4

# V1: selected layout per game and the Deck controller index (read-only).
run_probes.py v1 --appids <a>,<b>,<c>,<d>
#   If the output says the Deck index was "not found by type", V1 has already probed
#   every listed controller index (or 15) and marked those rows "index not confirmed
#   by type"; re-run with --controller-index N once the right one is clear (v2 takes it too).

# V5, first without --run (read-only), then launching the differently-named shortcut.
run_probes.py v5 --shortcut <different-name-shortcut-appid>
run_probes.py v5 --shortcut <different-name-shortcut-appid> --run
#   -> the shortcut's program must appear on the Deck; quit it before going on.

# V2: copy game (a)'s Workshop layout onto each shortcut and read it back.
#   URL: take `configs.<a>.config.URL` from the V1 output (it should be workshop://<id>),
#   or any URL under `candidates.<a>.flat`.
run_probes.py v2 --shortcut <same-name-shortcut-appid>      --url 'workshop://<id>' --restore
run_probes.py v2 --shortcut <different-name-shortcut-appid> --url 'workshop://<id>' --restore
#   --restore puts the previous selection back; drop it to leave the layout applied.
#   v2 refuses without --url and refuses any appid below 0x80000000.

# V3, last: Steam exits and gamescope restarts it. ~90 s of pgrep samples, then a reconnect.
run_probes.py v3            # asks for confirmation; --yes skips the prompt
```

`all` runs v1, v4 and v5 (without `--run`) in one go, v2 only when `--url` is
given and v3 last only with `--yes`:

```sh
run_probes.py all --appids <a>,<b>,<c>,<d> --shortcut <same-name-shortcut-appid> --url 'workshop://<id>' --restore --yes
```

Every subcommand prints one JSON object and appends it to
`probes/probe-results.json` (next to the script). V3 also writes every
sample to `probes/probe-v3-pgrep.log`. When done, render the results table
and paste it over the empty one in §5:

```sh
run_probes.py --markdown
```

The rendered table is already redacted for the repo: it never prints the
Steam ID (the V4 row is a verdict, "numeric, N digits; matches a
`userdata/<id>` folder: yes/no", checked on the Deck when `v4` runs), library
titles, or an absolute home path (`$HOME` and `/home/<name>` become `~` in
the V3 process-identity row). Still read it once before committing: the
case labels carry the names of the games and shortcuts you chose. The raw
values stay in `probe-results.json` and `probe-v3-pgrep.log`, which are
gitignored.

Exit codes: 0 the probe ran (its JSON may still carry an `error` key with a
`shape` of what was found instead — that is a result, paste it), 1 transport
failure (no `SharedJSContext` target, a websocket or handshake error, the
`websockets` package missing), 2 refused or usage error, 3 the DevTools port
is closed.

Copy `probe-results.json`, `probe-v3-pgrep.log` and the rendered table back
to the PC (`scp deck@<deck-ip>:~/moonlight-steam-sync-decky/probes/probe-*.{json,log} .`).

## 2. Fallback: the `steam-input-probe` button plugin

The same five probes as Quick Access Menu buttons, for when the runner is
not an option. Every button logs to the Decky console (`console.log` with a
`[steam-input-probe]` prefix) **and** to `~/homebrew/logs/steam-input-probe.log`,
each line prefixed with an ISO timestamp in milliseconds. The file is the
record; read it from Desktop Mode afterwards.

### 2.1 Build (on the PC; the Deck has no node)

```sh
cd probes/steam-input-probe
npx --yes pnpm@9 install --frozen-lockfile
npx --yes pnpm@9 run build          # -> dist/index.js
```

(`npx --yes pnpm@9 exec tsc --noEmit` type-checks; CI runs both plus
`python3 -m py_compile main.py`.)

### 2.2 Install on the Deck

The plugin directory must be named `steam-input-probe` and needs
`plugin.json`, `package.json`, `main.py` and `dist/`. First get those four
onto the Deck as `~/steam-input-probe`, by whichever route you have:

```sh
# (i) with SSH (from probes/steam-input-probe on the PC; the target directory must exist
#     before scp can copy several sources into it)
ssh deck@<deck-ip> mkdir -p ~/steam-input-probe
scp -r plugin.json package.json main.py dist deck@<deck-ip>:~/steam-input-probe/

# (ii) without SSH, over the LAN: serve the directory from the PC ...
python3 -m http.server 8000            # in probes/steam-input-probe, on the PC
#     ... and fetch it in Konsole on the Deck (Desktop Mode)
mkdir -p ~/steam-input-probe/dist && cd ~/steam-input-probe
for f in plugin.json package.json main.py dist/index.js; do curl -fsSO --output-dir "$(dirname "$f")" "http://<pc-ip>:8000/$f"; done

# (iii) without a network: copy probes/steam-input-probe (minus node_modules) to a USB
#       stick, plug it into the Deck, and in Desktop Mode copy it to ~/steam-input-probe
#       with Dolphin or `cp -r /run/media/deck/<stick>/steam-input-probe ~/`.
```

`~/homebrew/plugins` is root-owned, so the install itself needs `sudo`
(Konsole in Desktop Mode, or over SSH):

```sh
sudo mkdir -p ~/homebrew/plugins/steam-input-probe
sudo cp -r ~/steam-input-probe/. ~/homebrew/plugins/steam-input-probe/
sudo systemctl restart plugin_loader
```

Back in Game Mode: Quick Access (… button) → Decky (plug icon) → *Steam
Input probe*. The first line in the log after the restart is
`backend loaded`, then `frontend loaded` when the panel is first opened.
`plugin.json` carries `"flags": []` (never `_root`): the backend runs as the
`deck` user like the CLI does.

### 2.3 Uninstall

```sh
sudo rm -rf ~/homebrew/plugins/steam-input-probe
sudo systemctl restart plugin_loader
```

(or Decky → settings → Plugins → uninstall). The log file stays.

### 2.4 The panel

Four text fields (appids for V1; a shortcut appid for V2 and V5; a
`workshop://` URL for V2; an optional controller index override for V1 and
V2, blank = found by type) and one button per probe:

- **V1 layouts** — controllers with index and type string, the Deck
  controller index found by type, `GetConfigForAppAndController` per appid,
  then the candidates streamed by `RegisterForControllerConfigInfoMessages`
  + `QueryControllerConfigsForApp` (unregistered after 4 s). Each candidate
  line carries the message's own `appID` and whether it matches the queried
  appid: the subscription is global, so a late message for the previous
  appid shows up under the next query. When the Deck index is not found by
  type the probe does not abort: it queries every listed controller index
  (or 15 when none is listed) and tags those lines `[index not confirmed by
  type]`, so the answers are in the log without another build.
- **V2 set workshop URL** — config before, `SetSelectedConfigForApp(appid,
  idx, url, false)`, read back after 1 s. Refuses an appid below `0x80000000`
  and a URL that is not `workshop://<id>`. Uses the confirmed Deck index, the
  override, or (tagged unconfirmed) the first listed index / 15. The plugin
  does not restore the previous selection; pick it again in the layout
  picker (or use `run_probes.py v2 --restore`).
- **V4 dump allApps** — total count, `app_type` histogram, the first 20
  entries, every shortcut in the library, `App.m_CurrentUser.strSteamID` and
  the derived steamid3.
- **V5 overview / V5 RunGame** — `appStore.GetAppOverviewByAppID(appid)`
  (`gameid` and a few fields; on a miss, the `appStore` method names matching
  `/overview/i`), and with the second button `SteamClient.Apps.RunGame(gameid, "", -1, 100)`.
- **V3 watch + StartShutdown** — the backend starts the 60 s `pgrep -x steam`
  watch (100 ms) and only after its acknowledgement the frontend calls
  `SteamClient.User.StartShutdown(false)`. Steam exits, gamescope restarts it,
  the watch keeps running inside plugin_loader and writes its summary to the
  log. A sample where `pgrep` itself fails (exit status other than 0/1, e.g.
  a library-loading error under plugin_loader's environment) is logged as
  `pids=error`, counted as `pgrep_errors`, and never counted as a gap. **V3
  summary** logs the watcher's state again afterwards.

Every Steam global is guarded and every call is wrapped; a failure is logged
with the surrounding shape (`Object.keys`, prototype method names, `typeof`
of the expected methods), so a wrong guess about an API is diagnosable from
the log without another build.

## 3. What each probe answers and which decision it gates

| probe | question | gates |
|---|---|---|
| V1 | What does `GetConfigForAppAndController(appid, deckIndex)` return for a game on (a) a community Workshop layout, (b) a personal layout saved to the cloud, (c) an edited-in-place (autosaved) layout, (d) a game never touched? Which controller index is the Deck's built-in controller, found by type? What does the candidate stream look like? | §3.10 `copyLayout()` (PR-7): which URL kinds copy and which must be re-picked; the on-disk follow-up in §7 |
| V2 | Does `SetSelectedConfigForApp(shortcutAppid, idx, "workshop://<id published for the real game>", false)` stick on a hidden shortcut named exactly like the game, and on one named differently? | **Decision 3 / §3.3 naming** (hidden entries named with the owned game's display name for Steam Input identity), §3.10; if it sticks for neither, PR-7 downgrades the copy to *Choose layout* via `ShowControllerConfigurator` |
| V3 | Between `StartShutdown(false)` and the new client, does `pgrep -x steam` go empty, for how long, and does a wrapper script named `steam` ever match on its own? Does Steam come back? | **§3.5 `--commit await-exit`** (PR-4): the CLI polls every 100 ms and writes in that gap, so the gap must comfortably exceed **500 ms**; under that, escalate (backend `steam -shutdown` fallback, Decision 9); §2.3 |
| V4 | Is `collectionStore.allAppsCollection.allApps` the owned-apps source (`appid`, `display_name`, `app_type`), and is steamid3 = `App.m_CurrentUser.strSteamID` − 76561197960265728? | **§3.9 owned map** and `write_owned_apps(steamid3, …)` (PR-5); the CLI's `--owned-apps` steamid3 check (§3.4.1) |
| V5 | Is `appStore.GetAppOverviewByAppID(appid).gameid` the value `SteamClient.Apps.RunGame(gameid, "", -1, 100)` wants, and does it launch a shortcut from Game Mode? | **§3.9 Stream button** `runShortcut()` (PR-7) and *Open Moonlight* (PR-5) |

Note: the `session:` line of `moonlight-steam-sync doctor` (`gamescope` in
Game Mode, `desktop` in Desktop Mode) is the CLI half of PR-0 and lives in
the CLI repo (`episode6/moonlight-steam-sync`, folded into its PR-1); it is
not part of this kit.

## 4. Step-by-step procedure per probe (plugin path; the runner does the same)

Set up the games and shortcuts as in §1.2 first.

**V1**
1. Type the four appids, comma-separated, into *Appids*; press *V1 layouts*.
2. Expect in the log: one `controller index=… typeString=…` line per
   controller, then `deck controller index by type: N`; then one
   `V1 GetConfigForAppAndController(appid, N) [name app_type=1] -> {…}` per
   appid; then `V1 candidate appid=… URL=… Title=… publishedFileID=…
   bOfficial=… eExportType=… bSelected=…` lines for each.
3. Record the `URL` (and `Title`) per case in the table. The spec expects
   (a) `workshop://…`, (b) `workshop://…` (personal layouts are unlisted
   Workshop files), (c) `localconfig://…` or `autosave://…`, (d) `default://…`.
   Also note `eExportType` of the selected candidate (1 PersonalLocal,
   2 PersonalCloud, 3 Community, 4 Template).
4. If the Deck index is `NOT FOUND`, the `controller list attempts` and
   `type-string attempts` lines say which lookup failed and what the
   `controllerStore` shape is. The probe still runs: every listed controller
   index (or 15 when nothing was listed) is queried and those lines are
   tagged `[index not confirmed by type]`. Record the URL of whichever index
   answers with the layout you set up, then type that index into the
   override field (or pass `--controller-index N` to the runner) for V2.
   deckyemu measured index 15; the value is not 0.
5. Each `V1 candidate` line says `msg.appID=… forThisAppid=yes|NO|unknown`.
   Only count the `yes` ones for the queried game; a `NO` is a late message
   from the previous query (the subscription is global), and `unknown` means
   the message has no `appID` field at all (note that in the table).

**V2**
1. *Shortcut appid* = the same-named shortcut; *workshop:// URL* = game (a)'s
   URL from V1. Press *V2 set workshop URL*.
2. Expect `V2 before: {…}`, `V2 SetSelectedConfigForApp(…) -> …`,
   `V2 after 1 s: {…}`, `V2 result: stuck=true|false …`.
3. Repeat with the differently-named shortcut.
4. Expected: `stuck=true` for the same name (inherited Steam Input identity);
   unknown for the different name. Both true → Decision 3 can drop the naming
   rule (keep it for the candidate list). Both false → PR-7's copy becomes
   *Choose layout* (`ShowControllerConfigurator`).
5. Optionally re-run V1 on the shortcut appids to see what a shortcut's
   `default://<lowercased name>` looks like before any selection.

**V3**
1. Close every game. Press *V3 watch + StartShutdown*. Steam exits and comes
   back on its own (gamescope-session); wait for it.
2. Read the log from Desktop Mode (or press *V3 summary* once the panel is
   back): `steam-watch change sample t=… pids=… pgrep-a(…)=[…] cmdline=[…]`
   on every change, `steam-watch heartbeat …` once a second, then
   `steam-watch summary …` and `steam-watch gap #1: empty at t=… non-empty
   at t=… gap_ms=…`.
3. Expected: `pgrep -x steam` goes empty for **seconds** (well over 500 ms).
   The `cmdline` on each change shows whether a pid is the real client
   (`…/ubuntu12_32/steam …`) or a wrapper script (`/bin/bash /usr/bin/steam …`)
   — a wrapper that stays alive while the client is gone would hide the gap
   from the CLI's `pgrep -x steam`, which is exactly what this probe checks.
4. If the plugin panel never comes back, the watch still ran: plugin_loader is
   a systemd service, not part of the session.
5. `pgrep_errors=N` in the summary (with `pids=error` change lines) means
   pgrep itself failed N times; those samples are excluded from the gaps. If
   every sample is an error, the watch measured nothing: the `pgrep-error=[…]`
   text says why (the runner path does not have this problem).

**V4**
1. Press *V4 dump allApps*.
2. Expect `V4 allApps total count=N`, the `app_type` histogram, 20 `V4 app[i]
   appid=… display_name=… app_type=…` lines, the shortcuts list, then
   `V4 App.m_CurrentUser.strSteamID raw="7656119…"` and `V4 steamid3=…`.
3. Expected: `total` is the whole library including shortcuts; owned games
   have `app_type` 1 (8 demo, 65536 beta), shortcuts `1073741824`; steamid3
   equals the folder name under `~/.local/share/Steam/userdata/`.

**V5**
1. *Shortcut appid* = the differently-named shortcut. Press *V5 overview*.
2. Expect `V5 overview appid=… display_name=… app_type=… gameid="…" typeof
   gameid=string`. Expected: `gameid` is a string equal to the appid for a
   shortcut (Steam's `gameid` for shortcuts is the 64-bit game id; note
   whether it equals the appid or a larger number).
3. Press *V5 RunGame*. Expected: the shortcut's program launches in Game
   Mode; the log shows `V5 RunGame(…) -> …`. Quit the program afterwards.
4. If `GetAppOverviewByAppID` is missing, the log lists the `appStore` method
   names matching `/overview/i`.

## 5. Results

Fill from `run_probes.py --markdown` (or from the plugin log by hand).
Left empty on purpose: the probes have not been run.

| probe | case | expected | observed | notes |
|---|---|---|---|---|
| V1 | Deck controller index by type | found (deckyemu measured 15) | | |
| V1 | (a) community Workshop layout, appid … | `workshop://…` | | |
| V1 | (b) personal layout saved to the cloud, appid … | `workshop://…` | | |
| V1 | (c) edited in place (autosaved), appid … | `localconfig://…` or `autosave://…` | | |
| V1 | (d) never touched, appid … | `default://…` | | |
| V1 | candidate stream for (a) | non-empty; the selected one has `bSelected` | | |
| V2 | shortcut named exactly like (a) | `stuck=true` | | |
| V2 | shortcut named differently | unknown | | |
| V3 | gap: `pgrep -x steam` empty → non-empty | seconds; > 500 ms | | |
| V3 | process identity on each change | real client (`ubuntu12_32/steam`), not only a wrapper script | | |
| V3 | Steam came back (runner reconnects) | yes | | |
| V4 | `allAppsCollection.allApps` | total > 0; `appid`, `display_name`, `app_type` present | | |
| V4 | steamid3 from `App.m_CurrentUser.strSteamID` | numeric; equals the `userdata/<id>` folder | | |
| V5 | `GetAppOverviewByAppID(shortcut).gameid` | string | | |
| V5 | `RunGame(gameid, "", -1, 100)` | the shortcut launches | | |

### Raw log excerpts

Paste the relevant lines here (from `~/homebrew/logs/steam-input-probe.log`,
`probes/probe-results.json` or `probes/probe-v3-pgrep.log`). Replace any
Steam ID or home path with a placeholder before committing.

```
(none yet)
```

## 6. Notes for whoever reads the results

- `RegisterForControllerConfigInfoMessages`: spec §2.2 writes it as
  `(appId, cb)`, the `@decky/ui` 4.12 typing as `(cb)`. Both the runner and
  the plugin use the typed form and log `fn.length`; if the candidates stay
  empty, that is the first thing to check. The subscription is global and
  each message carries its own `appID`, which is how the runner's table and
  the plugin's log attribute candidates to a query (never by timing alone).
- The V3 watch in the plugin runs `pgrep` with plugin_loader's
  `LD_LIBRARY_PATH` restored from `LD_LIBRARY_PATH_ORIG` (PyInstaller sets
  both), because the loader's bundled libraries can stop system binaries
  from starting. Either way a failing `pgrep` is an error sample, not a gap.
- The type-string lookup for the Deck controller tries
  `controllerStore.GetControllerTypeString`, then
  `SteamClient.Input.GetControllerTypeString`, and falls back to
  `eControllerType === 4` (`SteamControllerNeptune`); the log says which one
  answered.
- Both V3 implementations sample with `pgrep -x steam` because that is what
  the CLI's `steam.is_running()` does; the point is to measure what the CLI
  will see, not the best possible detector.
- The runner shares Steam's `SharedJSContext` target with Decky itself.
  Modern CEF allows several DevTools clients on one target; if a connection
  is refused with a 500 while Decky is running, use the plugin path.
