---
name: moonlight-sync-update-staging
description: >-
  The Moonlight Sync backend's update staging (update spec 3.12.3 / 3.12.5 /
  3.12.6): stage_update / cancel_update, py_modules/moonlight_sync/fetch.py
  (the downloader script, its URL allowlist and redirect guard), updates.py
  (validate_zip, staged_path, parse_sidecar, read_build, cleanup), the
  runtime-dir layout, install.py's equal-version replace, and their tests
  (test_fetch.py, test_updates.py, test_backend_updates.py,
  tests/updatezip.py, the no_network fixture). Load before touching the
  download, the checksum or zip validation, anything under the runtime
  directory's update/, or the network rules of the backend.
---

# Moonlight Sync update staging

Reference split out of the root `AGENTS.md`, whose hard rules (cited here as
"hard rule N") apply throughout. Related: `moonlight-sync-updater` (the
frontend that calls `stage_update` and hands the result to Decky),
`moonlight-sync-backend` (the rest of the contract).

## Module map: the staging's modules

```
py_modules/moonlight_sync/  the backend (imports nothing from decky)
  fetch.py                  the downloader (update spec 3.12.3): a *script* the backend
                            runs with the system python3 -I, never imported, stdlib
                            only, Python 3.11. check_url() (the one allowlist, for
                            the first URL and every redirect: printable ASCII with
                            no backslash before parsing, `https://` exactly, host
                            github.com or *.githubusercontent.com, port 443, no user
                            info; --allow-file admits file:/// and nothing else),
                            RedirectGuard (checks in http_error_30x and
                            redirect_request, before the hop is opened; five hops at
                            most), build_opener() (a hand-built OpenerDirector: https
                            only, file under --allow-file, no proxy,
                            ssl.create_default_context()), download() (64 KiB chunks
                            to DEST.part, O_EXCL | O_NOFOLLOW, 0600, hashed and
                            counted as it goes, os.replace only on success), run() /
                            main() (exactly one JSON line and exit 0 whatever
                            happens; messages carry scheme, host and path only)
  updates.py                the staging's pure half (update spec 3.12.3): REPO,
                            DOWNLOAD_BASE, ASSET / ASSET_SHA, the limits, TAG_RE /
                            REF_RE (always fullmatch), Source, asset_url() (a
                            validated tag and one of the two assets), parse_sidecar(),
                            parse_build() / read_build() (the known keys only),
                            validate_zip() (BadZip(message), one check per rule, the
                            central-directory checks before testzip(), nothing
                            extracted), staged_path() (the name from the validated
                            hash alone), ensure_staged_dir() (0700, no symlinked
                            steps), cleanup() / remove_parts() (regular files directly
                            in update/staged/, symlinks removed as links, never
                            raise), strip_queries(); nothing at its top level is
                            named `updater`
```

## Backend contract: the staging

The staging (update spec 3.12.3, PR-U4a) needs no CLI; since PR-U4c
every install goes through it (update spec 3.12.5), a release's included,
and Decky is handed its `file://` artifact, never a URL. `cli_version()` carries an additive `build`: the plugin
zip's own `build.json` through `updates.read_build` (the known keys only),
`null` without one. `stage_update(tag, sha256, version=None, ref=None)`
checks its whole request first (`tag` against `TAG_RE` and not `.` / `..`,
`sha256` 64 hex digits, exactly one of `version` (it parses) and `ref`
(`REF_RE`), strings only: else `bad-request`, with nothing touched or
spawned), then the busy guards (a run or a `match` as `_busy()` answers,
`busy` kind `"key"` for a key fetch, kind `"update"` for another
staging; the staging's own guard is not the runs'), then downloads into
the runtime directory (`DECKY_PLUGIN_RUNTIME_DIR`, `~/homebrew/data/Moonlight
Sync`, `update/` and `update/staged/` created `0700` on demand; never the
plugin directory, hard rule 12): the release's `Moonlight-Sync.zip.sha256`
sidecar into `staged/sidecar.txt` (removed after every staging), which
must name `sha256` (Decision U20: GitHub's digest and the uploaded
checksum agree; a 404 or an unreadable one is `bad-release`, one naming
another hash `bad-release` "A new build is being published. Try again in a
minute" for a `ref`, "the release's checksums disagree" for a `version`);
then the zip to `staged_path(sha256)` unless a regular file there already
hashes to it (a file that does not is removed), with `--sha256`, the
downloader's reported hash compared again; then `validate_zip` either way
(`bad-zip` with its message, the file removed; a release's own
`build.json` must name `v<version>`). `hash-mismatch` passes
through, `too-large` is `bad-zip`, an HTTP 404 `bad-release`, any other
HTTP status or a network failure (a body cut short included) `network`,
a downloader still running after its socket timeout plus
`FETCH_ANSWER_GRACE` (10 s) is killed and answers `timeout` with that
limit as `timeout_s`. The answer is `{ok, artifact:
"file://" + <absolute staged path, raw>, hash, build, version}`: the path
is always `staged_path`, never a string from a response. The downloader is
`fetch.py`, run as `[<system python3>, "-I", fetch.py, options, "--", url,
dest]` through `_child_env()` (the system interpreter has SteamOS's CA
store, Decky's PyInstaller one does not, spec 2.5; `-I` keeps the
package's directory off `sys.path` and ignores `PYTHON*` variables), its
stderr discarded, its one stdout line read; it only opens `https` URLs on
`github.com` or `*.githubusercontent.com` (every redirect checked before
it is followed, five at most, no proxy, TLS verified), and `--allow-file`
(a `file:///` URL) is passed only when the backend's `update_source` says
so, which only the tests' does. Every step is logged with the tag, a size
and the first 12 hex digits of the hash, never a query string.
`cancel_update()` kills the downloader (`{ok, running}`) and the
interrupted `stage_update` answers `cancelled`; `unload()` does the same,
waits for the child and removes its part file; either one landing while
the downloader is being spawned kills it the moment it exists. Every exit releases the
guard. `startup()` runs `updates.cleanup` (staged files older than an
hour, every `*.part`; creates nothing). `install.ensure_installed`
replaces an installed CLI of the bundled one's version whose bytes differ
(`replaced`, Decision U12: a branch build carries the last release's
version); a newer installed CLI is still kept and nothing is downgraded.
The frontend (update spec 3.12.5) calls `stage_update` with exactly one
of a release's `version` and a branch build's `ref`, the other `null`,
checks the answer against its offer (`stagedMatches`: the hash, a
release's version, a branch build's `build.json` ref), and hands Decky
the answer's `artifact` and `hash` with, for a branch build, the version
built from the answer's own `version` and `build`; `decky.ts` accepts
only `file://` and an absolute path ending in the `staged_path` name of
that hash. A `bad-release` answer's message is shown as it is
(`stagingErrorText`); `cancelled` is shown as nothing.

## Testing the staging

- The staging (update spec 3.12.6) never opens a socket either: its three
  modules use `conftest.py`'s `no_network` fixture (`pytestmark`), which
  fails a test on any `socket.connect` / `connect_ex` off the loopback.
  `tests/updatezip.py`'s `build_zip(path, *, version, name, top, flags,
  build, extra, omit)` writes a zip shaped like `package.py`'s; hostile
  entries go in `extra` as `(ZipInfo, data)`, and `patch_central()`
  rewrites a central-directory record for what `zipfile` never writes (an
  encrypted flag, sizes that lie). `tests/test_fetch.py` runs the real
  `fetch.py` with `sys.executable -I` against `file://` URLs
  (`--allow-file`): the download and its hash, `--sha256` right and wrong,
  `--max-bytes`, a missing file (http 404), a stale part file, a symlink
  at the part path, `DEST` untouched and no part file after every failure,
  `bad-url` for `http://`, other hosts, `api.github.com` and `file://`
  without the flag, bad arguments; exactly one stdout line, exit 0 and an
  empty stderr every time. It loads the script as a module
  (`spec_from_file_location`) for `check_url` (the accepted and refused
  URLs), `RedirectGuard` called directly with fake requests (a hop off the
  allowlist, to `http`, to `file:` with the flag on, the five-hop limit),
  `build_opener`'s handlers and schemes, `run()` over fake openers (a
  refused redirect, an HTTP error, a query string that never reaches the
  output, `Content-Length` over the limit refused unread, the count
  deciding, a body cut short (`IncompleteRead`, an `OSError`) as `network` and a failed write as `io`, an uncaught exception as its class name) and a real
  `OpenerDirector` over a fake `https_open`, which proves urllib asks the
  guard before it opens a hop. `tests/test_updates.py` has one test per
  `validate_zip` rule and `read_build`, `asset_url`, `parse_sidecar`,
  `staged_path` and `cleanup` cases. `tests/test_backend_updates.py`
  stages from a `file://` tree through an `updates.Source(download_base,
  allow_file=True)` with `python=sys.executable`: end to end for a release
  and a branch, the argv, every `bad-request` (nothing spawned or
  created), the reuse and the re-validation of a staged file, the
  sidecar's failures, `hash-mismatch`, `bad-zip`, a download cut short
  (`network`), a downloader that says nothing (`io`) or hangs (`timeout`,
  `fake_python` shims, `FETCH_ANSWER_GRACE` patched short), each busy
  kind, the guard released after an exception, `cancel_update` and
  `unload` killing a downloader stuck mid-zip (its part file gone) and
  landing during the spawn (`asyncio.create_subprocess_exec` patched to
  cancel first), the startup cleanup, `cli_version()`'s `build`, and the
  plugin directory byte-identical after a staging. `no_network` only sees
  the test process: `test_fetch.py`'s `run_script` first proves from the
  argv that the real script cannot reach the network (arguments refused
  before any URL is used, or every URL a `file:///` one under
  `--allow-file` or refused by `check_url` in-process). A failed `close`
  of the part file is `io` and closes nothing twice.
  `tests/test_install.py`
  holds the `replaced` case (equal version: equal bytes kept, other bytes
  replaced atomically, a failed replace leaving the file, a symlink
  replaced by the file itself with its old target untouched), and
  `tests/test_hard_rules.py` that `fetch.py` imports the standard library
  only and parses as Python 3.11, that nothing under `py_modules` or
  `main.py` imports it, that no backend file turns TLS verification off
  (`CERT_NONE`, `_create_unverified_context`, `check_hostname = False`, a
  `verify_mode` assignment), and that `main.py` names neither
  `update_source` nor `allow_file` and no `py_modules` file says
  `allow_file=True`.
