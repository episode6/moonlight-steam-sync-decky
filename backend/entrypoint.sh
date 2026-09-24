#!/bin/sh
# Build the bundled moonlight-steam-sync CLI into backend/out/ (spec 3.6.1, 3.6.2).
#
# The one step that puts the CLI into the plugin: CI's package job, the
# release workflow, a developer's machine, and the Decky CLI's store builder
# (which runs this script as the ENTRYPOINT of backend/Dockerfile, with the
# plugin root mounted at /plugin, and packages backend/out/ as bin/).
#
# - The CLI's source is this repo's cli/src (/plugin/cli/src inside the Decky
#   container, else ../cli/src); scripts/build_cli.py turns it into
#   backend/out/moonlight-steam-sync.pyz (mode 0755) and refuses to when the
#   CLI's __version__ is not package.json's "version".
# - Then smoke-runs `--version` against the built zipapp. Always strict: a
#   failed build or smoke run is exit 1 with nothing left in out/.
#
# POSIX sh; needs only python3 (3.11+) and rm.
set -eu

HERE=$(cd "$(dirname "$0")" && pwd)
if [ -f /plugin/scripts/build_cli.py ]; then
  ROOT=/plugin
else
  ROOT=$(cd "$HERE/.." && pwd)
fi

OUT="$HERE/out"
PYZ="$OUT/moonlight-steam-sync.pyz"

if ! python3 "$ROOT/scripts/build_cli.py" --root "$ROOT" --out "$PYZ"; then
  echo "entrypoint.sh: could not build the CLI from $ROOT/cli/src" >&2
  rm -f "$PYZ"
  exit 1
fi

if ! python3 "$PYZ" --version; then
  echo "entrypoint.sh: the built CLI does not run; refusing to use it" >&2
  rm -f "$PYZ"
  exit 1
fi
