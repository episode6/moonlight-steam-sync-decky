---
name: moonlight-sync-installers
description: >-
  The Moonlight Sync end-user installers: the root install.sh (curl the plugin
  release zip, verify, unzip into ~/homebrew/plugins, restart plugin_loader;
  the sudo prompts, the temporary Decky! password for an account without one,
  offering to install Decky Loader) and cli/install.sh (the CLI-only zipapp
  into ~/.local/bin), their test seams (MOONLIGHT_SYNC_* env vars) and
  tests/test_install_sh.py / test_cli_install_sh.py. Load before changing
  either installer script or its tests, or the README's install instructions.
---

# Moonlight Sync installers

Reference split out of the root `AGENTS.md`, whose hard rules (cited here as
"hard rule N") apply throughout. Related: `moonlight-sync-ci` (the
shellcheck job), `moonlight-sync-release` (the assets the installers
download).

## Module map: the installers

```
install.sh                  the end-user installer: curl the latest (or pinned) release
                            zip + .sha256, verify, unzip into ~/homebrew/plugins/, restart
                            plugin_loader (explained sudo prompts, interactive with the
                            user's own password; an account with none, `passwd -S`'s
                            NP, whose `sudo -n true` fails is offered a temporary one
                            as Decky's installer does: asked on MOONLIGHT_SYNC_TTY,
                            default /dev/tty, anything but a yes installs nothing;
                            `Decky!` set with `setsid -w passwd` off a pipe, proven
                            with `sudo -S -k true`, fed to `sudo -S` by as_root(),
                            removed with `passwd -d` after the restart and by the
                            EXIT trap, which INT / TERM / HUP are turned into);
                            before any of it, offer_decky(): no
                            ~/homebrew/services/PluginLoader (MOONLIGHT_SYNC_DECKY_DIR)
                            means Decky Loader is missing, and the user is asked
                            whether to install it; a yes downloads Decky's own
                            install_release.sh (MOONLIGHT_SYNC_DECKY_INSTALLER_URL)
                            with the zip and install_decky() runs it through
                            as_root(), stdin /dev/null (or the temporary password's
                            pipe, read by sudo), before the plugin's steps;
                            anything else installs nothing; ask() reads both
                            questions off one fd 3, closed after the last one
cli/                        the moonlight-steam-sync CLI (its own AGENTS.md, README.md,
                            CHANGELOG.md up to 0.4.0, pyproject.toml, src/, tests/,
                            scripts/record_fixtures.py); install.sh: the CLI-only
                            installer, curl the release's moonlight-steam-sync.pyz +
                            .sha256 into ~/.local/bin (MOONLIGHT_STEAM_SYNC_VERSION,
                            INSTALL_DIR, NO_MODIFY_PATH, and the
                            MOONLIGHT_STEAM_SYNC_BASE_URL test seam)
```

## The installers

- `install.sh`: the plugin installer (curl the release zip + `.sha256`,
  verify, remove any previous install, unzip into `~/homebrew/plugins/`,
  restart `plugin_loader`); its `MOONLIGHT_SYNC_BASE_URL` seam lets
  `tests/test_install_sh.py` point the real `curl` at a `file://` fixture
  tree, with only `sudo`/`systemctl`/`passwd` shimmed on `PATH`, so no
  sudo, no network and no real account are ever touched by the test. The
  temporary password (the user's decision of 2026-10-01: do what Decky
  Loader's installer does) is offered only to an account `passwd -S`
  calls `NP` whose `sudo -n true` fails, i.e. where sudo could not work
  at all; the question is read from `MOONLIGHT_SYNC_TTY` (default
  `/dev/tty`, since under `curl | sh` stdin is the script; the tests
  always point it at a file), and anything but `y` / `yes`, no terminal
  included, exits 1 with nothing installed. The password is Decky's own
  `Decky!`, fixed and printed on purpose: a script killed outright leaves
  a password the user knows, where a random one would lock them out of
  sudo. It is set with `yes | setsid -w passwd` (plain `passwd` without
  `setsid`): with no controlling terminal `passwd` reads the pipe
  whichever way it was built, where a non-PAM one would ask on
  `/dev/tty` (PR 75's review; SteamOS's goes through PAM, which reads
  stdin, and is what Decky's installer relies on). Nothing relies on the
  set until `sudo -S -k true` has taken the password: when it does not,
  the account has a password that is not known to be the script's (a
  `passwd` that asked the user), so the script says so, installs
  nothing and neither feeds nor removes it. It goes to `sudo -S` on
  stdin only in that mode (a user's own
  password is always typed at sudo's prompt), and is removed with `sudo
  -S -k passwd -d` right after the restart, or by the `EXIT` trap on any
  earlier exit; `INT`, `TERM` and `HUP` are trapped into an `exit`
  because a plain `sh` runs no `EXIT` trap when a signal kills it. A
  removal that fails is a warning on stderr naming the password and the
  command that removes it. The tests hold each path: yes (the argv of
  every sudo call, nothing under sudo before the password is set), every
  no, NOPASSWD sudo, an account with a password never asked, a failed
  step, each signal mid-restart, a removal or a set that fails, a set
  that lands another password.
  Decky Loader itself (the user's request of 2026-10-01) is looked for
  first, as `~/homebrew/services/PluginLoader`, the file Decky's
  installer puts there (`MOONLIGHT_SYNC_DECKY_DIR` moves the check, for
  the tests). When it is missing the script asks *Install Decky Loader
  now?* on the same terminal, before anything is downloaded; anything
  but a yes exits 1 with nothing downloaded and nothing under sudo. On a
  yes it downloads Decky's official `install_release.sh` (the latest
  release of `SteamDeckHomebrew/decky-installer`, the script Decky's
  README pipes to `sh`; `MOONLIGHT_SYNC_DECKY_INSTALLER_URL` in the
  tests, which never fetch or run the real one) along with the plugin
  zip, so every download and the checksum are done before any sudo, asks
  the temporary-password question if the account needs it, and then runs
  the installer through `as_root` (as root is how that script runs
  itself, and `SUDO_USER` is how it finds the home directory) before the
  plugin's own steps: with `bash` when there is one, since the script is
  written in bash under an `sh` shebang, and with nothing on stdin
  (`/dev/null`, or with the temporary password `as_root`'s pipe, whose
  one line sudo has read), since under `curl | sh` stdin is `install.sh`
  itself. An installer
  that fails, or exits 0 and leaves no `PluginLoader`, stops the script
  before the plugin is touched. There is no checksum to verify it
  against: Decky publishes none, and it is the same file its README has
  the user run. A Decky Loader that is already there is never
  reinstalled or updated. The final lines then say the Decky tab appears
  once Steam has restarted (the CEF debugger Decky needs is only opened
  by a Steam started after the install; unmeasured, DEVICE-CHECKLIST
  §5). Both questions go through `ask()`, which opens the terminal once
  on fd 3, so a second question reads the second line (a test's terminal
  is a file), and which is closed after the last question, before
  anything runs under sudo. The tests hold: Decky present (no question, the installer
  never requested), yes (the installer under sudo before the four
  plugin steps), every no, a stock Deck (both questions, the installer
  with the temporary password on sudo's stdin; yes then no installing
  nothing), an installer or a plugin zip that cannot be downloaded
  (nothing under sudo), an installer that fails or installs nothing, and
  the script piped to `sh` with an installer that eats its stdin.
  `cli/install.sh` is the CLI-only
  installer (the release's `moonlight-steam-sync.pyz` into `~/.local/bin`,
  adding it to `PATH` in the rc file once), with the same kind of seam,
  `MOONLIGHT_STEAM_SYNC_BASE_URL`, for `tests/test_cli_install_sh.py`. The
  README advertises it only in its "Command-line tool only" section, near
  the end: the plugin is the recommended install.
