#!/bin/sh
# Install (or update) the Moonlight Sync Decky plugin from the latest
# GitHub release.
#
# Downloads the release zip (Moonlight-Sync.zip, spec 3.6.2) plus its
# published sha256 checksum, verifies it, and unzips it into
# ~/homebrew/plugins/ (Decky Loader's plugin directory), then restarts
# plugin_loader so the new plugin loads.
#
#   curl -fsSL https://raw.githubusercontent.com/episode6/moonlight-steam-sync-decky/main/install.sh | sh
#
# Safe to re-run: it always fetches the latest tag and overwrites the
# previous install (there is no version check, so it re-downloads and
# reinstalls every time even when already current). Set
# MOONLIGHT_SYNC_VERSION to a specific tag (e.g. v0.1.0) to pin instead of
# tracking latest, and PLUGIN_DIR to install somewhere other than
# ~/homebrew/plugins.
#
# ~/homebrew/plugins/ belongs to root on a stock Decky Loader install, so
# both unzipping into it and restarting plugin_loader need sudo. This
# script runs `sudo` exactly where those two steps need it, interactively:
# it is never run with a cached/NOPASSWD assumption or any non-interactive
# sudo flag, so you will be prompted for your password on the terminal.
#
# This installs the plugin only. moonlight-steam-sync, the CLI it drives
# (https://github.com/episode6/moonlight-steam-sync), has its own
# install.sh; the plugin bundles and installs a pinned copy of it the first
# time it loads, so there is nothing else to install by hand.

set -eu

REPO="episode6/moonlight-steam-sync-decky"
PLUGIN_DIR="${PLUGIN_DIR:-"$HOME/homebrew/plugins"}"
ASSET="Moonlight-Sync.zip"
VERSION="${MOONLIGHT_SYNC_VERSION:-latest}"

if [ "$VERSION" = "latest" ]; then
    RELEASE_PATH="latest/download"
else
    RELEASE_PATH="download/${VERSION}"
fi

BASE_URL="https://github.com/${REPO}/releases/${RELEASE_PATH}"

require() {
    command -v "$1" >/dev/null 2>&1 || {
        echo "install.sh: '$1' is required but was not found on PATH." >&2
        exit 1
    }
}

require curl
require sha256sum
require unzip
require sudo

TMP_DIR=$(mktemp -d)
trap 'rm -rf "$TMP_DIR"' EXIT

echo "Downloading ${ASSET} (${VERSION}) from ${REPO}..."
curl -fsSL "${BASE_URL}/${ASSET}" -o "${TMP_DIR}/${ASSET}"
curl -fsSL "${BASE_URL}/${ASSET}.sha256" -o "${TMP_DIR}/${ASSET}.sha256"

echo "Verifying checksum..."
# Compare hashes rather than `sha256sum -c` against the recorded filename:
# harmless either way, and it keeps this working even against a
# ${ASSET}.sha256 recorded under a different name (e.g. a build path).
EXPECTED=$(awk '{print $1}' "${TMP_DIR}/${ASSET}.sha256")
ACTUAL=$(sha256sum "${TMP_DIR}/${ASSET}" | awk '{print $1}')
if [ "$EXPECTED" != "$ACTUAL" ]; then
    echo "install.sh: checksum mismatch for ${ASSET}." >&2
    echo "  expected: ${EXPECTED}" >&2
    echo "  actual:   ${ACTUAL}" >&2
    exit 1
fi
echo "sha256: ${ACTUAL}"

echo
echo "Installing into ${PLUGIN_DIR}/ (this needs sudo: that directory"
echo "belongs to root on a stock Decky Loader install). You may be asked"
echo "for your password now."
sudo mkdir -p "$PLUGIN_DIR"
sudo unzip -o "${TMP_DIR}/${ASSET}" -d "$PLUGIN_DIR"

echo
echo "Restarting plugin_loader so Moonlight Sync loads (needs sudo again)."
sudo systemctl restart plugin_loader

echo
echo "Installed Moonlight Sync ${VERSION} to ${PLUGIN_DIR}/Moonlight Sync."
echo "Look for it in the Quick Access menu's Decky tab."
