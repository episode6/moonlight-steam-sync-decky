#!/bin/sh
# Download and verify the pinned moonlight-steam-sync CLI (spec 3.6.1, 3.6.2).
#
# The one downloader: CI's package job, the release workflow, a developer's
# machine, and the Decky CLI's store builder (which runs this script as the
# ENTRYPOINT of backend/Dockerfile and packages backend/out/ as bin/).
#
# - The pin is package.json's "moonlightSteamSync" (the one place it lives):
#   /plugin/package.json inside the Decky container, else ../package.json.
# - Downloads moonlight-steam-sync.pyz and moonlight-steam-sync.pyz.sha256
#   from https://github.com/episode6/moonlight-steam-sync/releases/download/v<pin>/
#   (MSY_CLI_BASE_URL overrides the base; tests point it at file:// fixtures),
#   verifies with `sha256sum -c`, and moves the pyz to backend/out/ (mode 0755).
# - Always strict: a missing release or asset, a missing checksum or a
#   mismatch is exit 1 with nothing left in out/. The "CLI not released yet"
#   leniency lives in CI's workflow step, never here.
#
# POSIX sh; needs only curl, sha256sum, sed, mktemp, mkdir, mv, chmod, rm.
set -eu

HERE=$(cd "$(dirname "$0")" && pwd)
if [ -f /plugin/package.json ]; then
  PKG=/plugin/package.json
else
  PKG="$HERE/../package.json"
fi

PIN=""
if [ -f "$PKG" ]; then
  PIN=$(sed -n '/"moonlightSteamSync"/{s/.*"moonlightSteamSync"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/p;q;}' "$PKG")
fi
if [ -z "$PIN" ]; then
  echo "entrypoint.sh: no moonlightSteamSync pin in package.json" >&2
  exit 1
fi

BASE="${MSY_CLI_BASE_URL:-https://github.com/episode6/moonlight-steam-sync/releases/download/v$PIN}"
NAME=moonlight-steam-sync.pyz

TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT INT TERM

for asset in "$NAME" "$NAME.sha256"; do
  if ! curl -fsSL -o "$TMP/$asset" "$BASE/$asset"; then
    echo "entrypoint.sh: could not download $BASE/$asset (is moonlight-steam-sync v$PIN released?)" >&2
    exit 1
  fi
done

if ! (cd "$TMP" && sha256sum -c "$NAME.sha256" >&2); then
  echo "entrypoint.sh: checksum mismatch for $NAME v$PIN; refusing to use it" >&2
  exit 1
fi

OUT="$HERE/out"
mkdir -p "$OUT"
chmod 755 "$TMP/$NAME"
mv "$TMP/$NAME" "$OUT/$NAME"
echo "entrypoint.sh: moonlight-steam-sync v$PIN -> $OUT/$NAME"
