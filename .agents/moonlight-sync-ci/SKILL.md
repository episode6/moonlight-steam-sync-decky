---
name: moonlight-sync-ci
description: >-
  The Moonlight Sync repo's CI and build pipeline: the root plugin.json and
  package.json (scripts, the one version), .github/workflows/ci.yml,
  release.yml's build job, builds.yml (rolling build-<slug> prereleases per
  branch: gate, build, publish, cleanup), scripts/build_cli.py (the zipapp),
  scripts/build_info.py (build.json), scripts/package.py (Moonlight-Sync.zip),
  scripts/set_version.py and scripts/ship_release.py (the release-branch
  flow's two tools), backend/entrypoint.sh and backend/Dockerfile, and their
  tests (test_entrypoint.py, test_package.py, test_build_info.py,
  test_set_version.py, test_ship_release.py, test_hard_rules.py's workflow
  checks). Load before changing any workflow,
  build or packaging script, the Python version CI uses, or when CI fails.
---

# Moonlight Sync CI and builds

Reference split out of the root `AGENTS.md`, whose hard rules (cited here as
"hard rule N") apply throughout. Related: `moonlight-sync-release` (cutting
a tagged release), `moonlight-sync-installers`, `moonlight-sync-updater`
(what consumes the branch builds).

## Module map: root files, build scripts and workflows

```
plugin.json                 name "Moonlight Sync", flags []
package.json                scripts, deps, "version" (the plugin's and the CLI's)
project-icon.svg            the repo's icon (moved over with the CLI)
backend/entrypoint.sh       the one CLI build step (strict): scripts/build_cli.py into
                            backend/out/, then a --version smoke run; also the Decky
                            store hook (/plugin/cli/src inside its container)
backend/Dockerfile          template's holo-base image, only for `decky plugin build`
scripts/build_cli.py        cli/src -> moonlight-steam-sync.pyz (zipapp, deflated,
                            `/usr/bin/env python3`, moonlight_steam_sync/ only: no
                            __pycache__ or egg-info), refusing a __version__ that is not
                            package.json's "version" in the CLI's spelling (cli_spelling:
                            X.Y.Z-SNAPSHOT is X.Y.Z.dev0, the rule's one home)
scripts/set_version.py      the one version in both spellings: package.json's "version" as
                            given (X.Y.Z or X.Y.Z-SNAPSHOT, anything else refused with
                            nothing written) and the CLI's __version__ as build_cli.py's
                            cli_spelling says (a snapshot's -SNAPSHOT is .dev0, PEP 440);
                            package.json rewritten with its two-space indent and newline
scripts/ship_release.py     the release from a release branch (the moonlight-sync-release
                            skill): package.json's version (a -SNAPSHOT refused, the CLI's
                            __version__ cross-checked), --branch or the branch checked out
                            (must be release/*; a dry run only warns), CHANGELOG.md's
                            `## [X.Y.Z] - date` section as the notes (missing: an error;
                            empty: a warning), `gh release create vX.Y.Z --target <branch>
                            --title vX.Y.Z --notes-file …` (gh is the one tool it runs),
                            --dry-run prints and runs nothing, --output (required) gets a
                            JSON report; the tag then triggers release.yml
scripts/build_info.py       build.json (update spec 3.12.1): --kind release|branch --ref
                            --sha --run [--out], {schema: 1, kind, ref, sha, built_at,
                            run} in that order; refuses (one stderr line, nothing
                            written) a kind outside the two, a sha that is not 40 hex
                            digits or a run that is not ^[0-9]+/[0-9]+$ with exit 1,
                            then a ref outside
                            ^[A-Za-z0-9._/-]{1,100}$ with exit 3 (EXIT_REF_REFUSED:
                            ci.yml / release.yml skip build.json on it for a branch,
                            amendment A1; builds.yml fails, so a branch with a `+` or
                            an `@` cannot be published); CI writes it at the root
                            before package.py, never committed (.gitignore);
                            from_git(root) (amendment A5, for a build made outside
                            CI): {kind: branch, ref: the branch checked out, sha:
                            HEAD, run: null}, NoGitBuild unless root is the top of
                            a git checkout, on a branch, with nothing uncommitted
                            or untracked (`git -C root`, GIT_DIR and its kin
                            dropped from the environment), RefRefused for a name
                            outside the pattern; the branch is `symbolic-ref HEAD`
                            without BRANCH_PREFIX (`refs/heads/`), what
                            github.ref_name is, never `--short` (which answers
                            `heads/main` beside a tag named `main`); a failure of
                            git's own carries the first line of its stderr, or
                            that git did not run / did not answer; git's bytes
                            are read as UTF-8 with errors="replace" whatever the
                            locale, so a branch named in other bytes is a refused
                            name, never a UnicodeDecodeError
scripts/package.py          Docker-free zip: out/Moonlight-Sync.zip ("Moonlight Sync/");
                            OPTIONAL_ROOT_FILES (build.json) from the root when it
                            exists, 0644, after the five root files; without a root
                            build.json, build_info.from_git's, written into the zip
                            only (never to the root, so none goes stale), else no
                            build.json; a root build.json that is not a file is
                            never replaced by git's; one stderr line in every case
                            (from the root, from git, or why there is none)
.github/workflows/release.yml  entrypoint.sh (the CLI from cli/src) + doctor smoke +
                            package.py --require-cli; on a v* tag (which must be
                            v<package.json version>, never a -SNAPSHOT) Moonlight-Sync.zip,
                            moonlight-steam-sync.pyz and their .sha256 files attached to
                            one GitHub release; the build job also runs on pull_request
.github/workflows/builds.yml   branch builds (update spec 3.12.2): push / workflow_dispatch
                            / delete only, never a pull-request event; `gate` (publish
                            for main, a dispatch, or a branch whose build-<slug> release
                            exists; a release titled with another branch's name is
                            that branch's, amendment A2), `build` (release.yml's steps,
                            repeated), `publish` (the title checked again, the tag
                            moved to the commit built, the release made or edited as a
                            prerelease never latest, four assets then build.json),
                            `cleanup` (a deleted branch's release and tag, when its
                            title is that branch's)
```

## CI and release outline

- `.github/workflows/ci.yml` (push to `main` and to `release/**`, every
  `pull_request`):
  `shellcheck` (`sh -n` on `install.sh`, `backend/entrypoint.sh` and
  `cli/install.sh`, then `ludeeus/action-shellcheck` over the whole tree),
  `frontend` (pnpm 9, Node 20: typecheck, lint, vitest, build, upload
  `dist`), `backend` (Python 3.13.5: ruff over the whole repo, `cli/`
  included; pytest `tests/`), `cli` (Python 3.11 -- the CLI's floor -- and
  3.13.5: `pip install --no-deps -e ./cli`, pytest `cli`, then
  `scripts/build_cli.py` and the zipapp's `--version` and `doctor` smoke
  runs), `package` (after all three: `backend/entrypoint.sh`, then
  `scripts/build_info.py` -- `release` and the tag on a tag, else `branch`
  and `github.head_ref || github.ref_name`, with the sha
  `github.event.pull_request.head.sha || github.sha` (a pull request's
  head commit, not the merge commit `GITHUB_SHA` names there, amendment
  A4), both passed through `env:`; on a branch, `build_info.py`'s exit 3 (the name is outside the `ref`
  pattern) is a `::notice::` and a zip without `build.json`, since this
  workflow publishes nothing from a branch (amendment A1), and any other
  failure fails; the step first removes any `build.json` at the root --
  then `scripts/package.py --require-cli` and the `Moonlight-Sync`
  artifact).
  When SteamOS moves to a new Python, change `3.13.5` in all three
  workflows (`ci.yml`, `release.yml`, `builds.yml`).
- `.github/workflows/release.yml`: the same frontend build, then
  `entrypoint.sh` (the CLI from `cli/src`, its `--version` smoke run), a
  `doctor` smoke run, `build_info.py` (the same step as `ci.yml`'s, text
  for text, so a release's zip
  carries `build.json` with `kind: release` and the tag; it is inside the
  zip, not a fifth asset), `package.py --require-cli`, and `sha256sum` of
  `Moonlight-Sync.zip` and `moonlight-steam-sync.pyz` against their bare
  filenames. On a `v*` tag it first checks that `package.json`'s
  `"version"` is not a `-SNAPSHOT` (`main`'s between releases: a release
  only ever comes from a `release/*` branch, where the release PR set the
  bare version) and that the tag is `v` + that version, and the tag-gated
  `github-release` job attaches all four
  files to one release through an idempotent `gh release view || create` /
  `upload --clobber` step. The build job also runs on `pull_request` and
  `workflow_dispatch`, so it is exercised before any tag.
- `.github/workflows/builds.yml` (update spec 3.12.2): a rolling
  prerelease per branch, tagged `build-<slug>` (the branch's name with
  every character outside `[A-Za-z0-9._-]` replaced by `-`, cut to 80),
  titled with the branch's name. Triggers are `push` (every branch),
  `workflow_dispatch` and `delete`, **never `pull_request` or
  `pull_request_target`**, so code from a fork never reaches a release;
  top-level permissions `contents: read`. `gate` answers `publish=true`
  for `main`, for a `workflow_dispatch` and for a push to a branch whose
  `build-<slug>` release already exists (`gh release view`; "release not
  found" is `false`, any other failure fails the job), so a branch
  publishes once asked and from then on with every push (Decision U10); a
  dispatch on a tag fails. The slug is lossy (`a/b` and `a-b` are both
  `build-a-b`), so a release belongs to the branch its title names
  (amendment A2): `gate` reads the title (`--json name --jq .name`), a
  push to a branch whose tag another branch's release holds is `false`
  with a notice, and `main` or a dispatch in that case fails the job
  naming the holder (delete that release or rename the branch). A title
  is text somebody chose: it is compared as a quoted variable and shown
  with every character outside `[A-Za-z0-9._/@+-]` as `?`. `build`
  repeats `release.yml`'s build job (Decision U11: same actions and versions, Python 3.13.5, no tag check),
  writes `build.json` with `branch` and the branch, and uploads the
  artifact `Moonlight-Sync-build` (the zip, the pyz, their sidecars,
  `build.json`). `publish` (`contents: write`) moves the tag through the
  API to the run's `GITHUB_SHA`, the commit built (`POST git/refs`, or
  `PATCH git/refs/tags/build-<slug>` with `force`) after reading the
  release's title again (another branch with the same slug may have
  published since the gate; a title that is not this branch's fails the
  job before anything is written, and the create-or-edit step checks it
  once more, so an edit never retitles another branch's release),
  creates the release or edits it with `--prerelease --latest=false` every time (so
  `releases/latest` keeps naming the newest `v*`), removes the release's
  previous `build.json` asset when the asset list (`gh release view --json
  assets`) has one (amendment A3: otherwise a republish, or a run
  cancelled mid-upload, would leave the last build's `build.json` beside
  new or half-replaced files; the list decides, so no `gh` error text is
  relied on, and any failure fails the job), uploads the four files with
  `--clobber` and then, in a step of its own, `build.json`: `--clobber`
  deletes an asset before uploading its replacement, so `build.json`
  arriving last says the four beside it are its own. `cleanup` (`contents:
  write`, `delete` events of a branch only) runs `gh release delete
  build-<slug> --cleanup-tag --yes` only when the release's title is the
  deleted branch's name; no release, or another branch's, is a success
  that deletes nothing. Every
  branch name, ref and event field reaches a script through `env:` as a
  quoted variable, never as a `${{ }}` inside `run:`; the slug is one line,
  identical in `gate` and `cleanup`; every tag the workflow moves or
  deletes is built as `build-<slug>` and checked (the slug's characters,
  the `build-` prefix, `git check-ref-format`) before any `gh` call, so it
  can never touch a `v*` release. A tag made with `GITHUB_TOKEN` starts no
  workflow, and `release.yml` listens for `v*` only. **Immutable releases
  must stay off for the repository**: a rolling release cannot exist with
  them. A branch can be built only once `builds.yml` is on it (a branch cut
  before it reached `main` needs a rebase), `delete` runs the default
  branch's copy, and a branch `build_info.py` refuses (a `+` or `@` in
  its name) cannot be built.
- The plugin PRs are stacked (PR-0 → PR-5 → PR-6 → PR-7 → PR-8), each branch
  on the previous one (`AGENTS.md`'s *Commands* has the push rules).

## Testing the build scripts and workflows

- `tests/test_entrypoint.py` runs `backend/entrypoint.sh` from a sandbox
  copy of `backend/`, `scripts/build_cli.py`, `cli/src` and a
  `package.json` (the zipapp's entries, mode and `--version`; a version
  mismatch, a missing source) and holds the real CLI's `__version__` to
  `package.json`'s; `tests/test_package.py` builds a fixture tree and checks
  the exact zip entry list and modes, with a root `build.json` and without
  one, and that `fetch.py` and `updates.py` ship (0755); its `checkout`
  fixture commits the tree to a scratch git repository on `main` (the
  machine's git configuration shut out), for the `build.json` a build
  outside CI gets: the branch and `HEAD`, `run` `null`, read back through
  `updates.parse_build`, the root's file (or a directory of its name)
  winning over git, a tag named `main` beside the branch, and none for an
  edited, untracked or staged change, a detached `HEAD`, a refused branch
  name (one in UTF-8 and one in Latin-1 bytes too, under `LC_ALL=C` with
  `PYTHONUTF8=0`), a tree inside another checkout, no checkout, a checkout git calls
  dubious (`GIT_TEST_ASSUME_DIFFERENT_OWNER=1`, git's own message quoted)
  and no `git` on `PATH`; each asserts the stderr line.
  `tests/test_set_version.py` runs `scripts/set_version.py` against a
  fixture tree (`--root`): `cli_spelling`'s table, a release written alike
  in both files, a snapshot as `.dev0` in the CLI (and what it wrote is
  what `build_cli.py` accepts), the version the only change to
  `package.json` (indent, newline, non-ASCII kept), every other shape
  (`0.14`, `v0.14.0`, `0.14.0-snapshot`, `0.14.0.dev0`, `01.2.3`, …)
  refused with nothing written, a file without a version refused, and the
  real tree's two spellings agreeing. `tests/test_ship_release.py` runs
  `scripts/ship_release.py` against a fixture tree with a fake `gh` on
  `PATH` that logs its argv and copies the notes file: the one `release
  create v0.14.0 --target release/v0.14.0 --title v0.14.0 --notes-file`
  call with the `## [0.14.0]` section (headings kept, up to the next
  `## `) and the JSON report; a dry run (no call, `command` in the
  report); the branch read from a scratch checkout (`symbolic-ref`); a
  snapshot, a non-release branch (a warning on a dry run), a CLI version
  that disagrees and a missing section each refused before `gh` runs and
  without a report; an empty section a warning; a failing `gh` reported
  with its stderr, the notes temp file removed either way.
  `tests/test_build_info.py` runs `scripts/build_info.py` with
  `sys.executable` in `tmp_path`: the keys and their order, `built_at`'s
  form, `--out`, and every refusal (one stderr line, nothing written; exit
  3 for the ref alone, 1 for a bad kind, sha or run, the ref bad too or
  not, 2 for argparse).
- `tests/test_hard_rules.py` also reads `.github/workflows/builds.yml` as
  text (no YAML parser is a dev dependency): the triggers are exactly
  `push`, `workflow_dispatch` and `delete` and no line outside a comment
  names `pull_request`; the top-level permissions are `contents: read` and
  `contents: write` is on `publish` and `cleanup` only; no workflow's
  `run:` script contains a `${{ }}` expression; the slug line is spelled
  identically in `gate` and `cleanup`, every `tag=` is `build-${slug}`
  and guarded before any `gh` call, and that line and guard run under
  `bash` over sample branch names (`café` is `build-caf-` under
  `C.UTF-8`, the runner's locale); every script passes `bash -n`; and
  the previous `build.json` is deleted before the first upload and the
  new one uploaded in a step of its own after the other four.
  It also holds `ci.yml`'s and `release.yml`'s "Write build.json" steps
  identical and runs that step under `bash` in `tmp_path` over a copy of
  `build_info.py` and a stale `build.json`: a branch (with `BUILD_SHA`,
  never `GITHUB_SHA`) and a tag are written, a refused branch name is a
  notice with no `build.json` left, a refused tag or a bad sha fails. And
  it runs `gate`'s, `cleanup`'s and `publish`'s scripts under `bash`
  with a fake `gh` on `PATH` (`FAKE_GH`, a shell script logging every
  argv: `release view` answers `FAKE_GH_RELEASE`, `none`, `fail` or
  `title=<name>`, or with `--json assets` the names in `FAKE_GH_ASSETS`;
  a GET through `api` answers `FAKE_GH_REF`, `missing` as gh's `HTTP
  404`, `exists` or `fail`; every write succeeds) and the `GITHUB_*`
  variables set:
  `publish` from the `GITHUB_OUTPUT` file for `main` with and without its
  release, a branch without one, with its own and with another branch's
  (amendment A2), a dispatch or `main` on another branch's tag failing, an
  API failure failing, a title that tries a workflow command shown
  defanged; `cleanup` deleting only its own release (the argv log), none
  and another's left alone, an API failure failing; `publish`'s five
  steps run in order by name, stopping at the first failure as the job
  does, with the whole argv log compared: a first build (`POST git/refs`
  with `refs/tags/build-<slug>` and the run's sha, `create --verify-tag`,
  no delete-asset), a republish (`PATCH` with `force=true`, `edit`
  without `--verify-tag`, the old `build.json` deleted before the
  uploads, `build.json` last in a call of its own), another branch's
  title (no `api` call and no write, and the create-or-edit step alone
  refusing too), an API failure (nothing after it); every tag in every
  call is `build-<slug>`.
