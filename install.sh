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
# Safe to re-run: it always fetches the latest tag and replaces the
# previous install (there is no version check, so it re-downloads and
# reinstalls every time even when already current; the plugin directory is
# removed before unzipping so a file dropped by an older release that the
# new one no longer ships does not linger). Set MOONLIGHT_SYNC_VERSION to a
# specific tag (e.g. v0.1.0) to pin instead of tracking latest, and
# PLUGIN_DIR to install somewhere other than ~/homebrew/plugins.
#
# MOONLIGHT_SYNC_BASE_URL overrides the "https://github.com/<repo>/releases"
# prefix (the latest/download or download/<tag> suffix below is still
# appended, so a version pin still changes the requested URL); it exists so
# tests/test_install_sh.py can point this script at a file:// fixture tree
# instead of GitHub. There is normally no reason to set it by hand.
#
# ~/homebrew/plugins/ belongs to root on a stock Decky Loader install, so
# both unzipping into it and restarting plugin_loader need sudo. This
# script runs `sudo` exactly where those two steps need it, and with a
# password set it does so interactively: you are prompted on the terminal.
#
# A stock Steam Deck ships with no password for the `deck` user, and sudo
# refuses an account without one. So, as Decky Loader's own installer
# does, when your account has no password (and sudo needs one) this script
# offers to set a temporary one ("Decky!", the one Decky's installer uses),
# install with it, and remove it again when it exits, however it exits. It
# asks first, on the terminal, and does nothing of the kind unless you
# answer yes; answer no (or run it with no terminal to ask on) and it
# stops before installing anything, so you can run `passwd` yourself.
# Nothing here ever touches a password you set: the offer is only made to
# an account that has none.
#
# MOONLIGHT_SYNC_TTY names the terminal that question is read from
# (default /dev/tty: under `curl | sh` the script itself is on stdin). Like
# MOONLIGHT_SYNC_BASE_URL it is a seam for tests/test_install_sh.py.
#
# This installs the plugin only. moonlight-steam-sync, the CLI it drives
# (cli/ in this repo), has its own installer, cli/install.sh, for using it
# without the plugin; the plugin bundles the CLI built from the same commit
# and installs it the first time it loads, so there is nothing else to
# install by hand.

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

RELEASES_URL="${MOONLIGHT_SYNC_BASE_URL:-https://github.com/${REPO}/releases}"
BASE_URL="${RELEASES_URL}/${RELEASE_PATH}"

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

# The temporary password offered to an account that has none: Decky
# Loader's installer's own, so there is one such password to know about,
# and a known one on purpose -- were the script killed outright before it
# could remove it, a random one would lock you out of sudo.
TEMP_PASSWORD='Decky!'
TTY="${MOONLIGHT_SYNC_TTY:-/dev/tty}"
USER_NAME=$(id -un)
# The account the temporary password is on right now, else empty.
TEMP_PASSWORD_USER=""
TMP_DIR=""

# The second field of `passwd -S`: P (a password), NP (none), L (locked).
# Empty when passwd is missing or will not say, which is "do not offer".
password_status() {
    command -v passwd >/dev/null 2>&1 || return 0
    passwd -S "$1" 2>/dev/null | awk 'NR == 1 {print $2}'
}

# sudo for the install steps: interactive, except with the temporary
# password, which is fed on stdin since nobody chose it and so nobody
# should have to type it.
as_root() {
    if [ -n "$TEMP_PASSWORD_USER" ]; then
        printf '%s\n' "$TEMP_PASSWORD" | sudo -S -p '' "$@"
    else
        sudo "$@"
    fi
}

remove_temp_password() {
    # An interrupt between the mark and the set: there is nothing to
    # remove, and nothing to say.
    if [ "$(password_status "$TEMP_PASSWORD_USER")" = "NP" ]; then
        TEMP_PASSWORD_USER=""
        return 0
    fi
    # -k: never lean on a cached credential here, so this either removes
    # the password or visibly fails.
    printf '%s\n' "$TEMP_PASSWORD" |
        sudo -S -k -p '' passwd -d "$TEMP_PASSWORD_USER" >/dev/null 2>&1 || true
    if [ "$(password_status "$TEMP_PASSWORD_USER")" = "NP" ]; then
        # Drop sudo's cached credential too: the account is back to having
        # no password, and should not keep a few minutes of sudo with it.
        sudo -k 2>/dev/null || true
        echo "Removed the temporary password: ${TEMP_PASSWORD_USER} has no password again."
    else
        echo >&2
        echo "install.sh: WARNING: could not remove the temporary password." >&2
        echo "  ${TEMP_PASSWORD_USER}'s password is still '${TEMP_PASSWORD}'. Remove it with" >&2
        echo "    sudo passwd -d ${TEMP_PASSWORD_USER}" >&2
        echo "  or choose your own with \`passwd\`." >&2
    fi
    TEMP_PASSWORD_USER=""
}

cleanup() {
    status=$?
    trap - EXIT INT TERM HUP
    # Nothing below may end the cleanup early: after a hangup even an echo
    # fails (the terminal is gone), and set -e would stop there.
    set +e
    [ -z "$TEMP_PASSWORD_USER" ] || remove_temp_password
    [ -z "$TMP_DIR" ] || rm -rf "$TMP_DIR"
    exit "$status"
}
# A plain sh does not run its EXIT trap when a signal kills it, and the
# temporary password must not outlive the script: turn each signal into an
# exit.
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM
trap 'exit 129' HUP

# Only for an account with no password, and only when sudo would ask for
# one (`sudo -n true` succeeds where sudo needs none, e.g. NOPASSWD).
offer_temp_password() {
    [ "$(password_status "$USER_NAME")" = "NP" ] || return 0
    if sudo -n true 2>/dev/null; then
        return 0
    fi
    echo
    echo "Your account (${USER_NAME}) has no password, and sudo needs one."
    echo "This script can set a temporary password ('${TEMP_PASSWORD}'), install with it,"
    echo "and remove it again when it finishes (Decky Loader's installer does the same)."
    printf 'Set a temporary password for the install? [y/N] '
    answer=""
    { IFS= read -r answer <"$TTY"; } 2>/dev/null || answer=""
    case "$answer" in
        [Yy] | [Yy][Ee][Ss]) ;;
        *)
            echo
            echo "install.sh: nothing was installed. Set a password with \`passwd\`, then run this again." >&2
            exit 1
            ;;
    esac
    # Marked before it is set, so an interrupt in between still cleans up
    # (removing a password that never landed fails quietly and checks out).
    TEMP_PASSWORD_USER="$USER_NAME"
    # Without a controlling terminal (setsid), so that passwd takes the
    # password from the pipe whichever way it was built: through PAM it
    # reads stdin anyway, without PAM it asks on /dev/tty when there is one.
    set_status=0
    if command -v setsid >/dev/null 2>&1; then
        yes "$TEMP_PASSWORD" | setsid -w passwd "$USER_NAME" >/dev/null 2>&1 || set_status=$?
    else
        yes "$TEMP_PASSWORD" | passwd "$USER_NAME" >/dev/null 2>&1 || set_status=$?
    fi
    if [ "$(password_status "$USER_NAME")" = "NP" ]; then
        TEMP_PASSWORD_USER=""
        echo "install.sh: could not set the temporary password (passwd exited ${set_status})." >&2
        echo "  Nothing was installed. Set a password with \`passwd\`, then run this again." >&2
        exit 1
    fi
    # Proof before anything relies on it: sudo takes the temporary
    # password. If not, the account has a password that is not known to be
    # this one, so it is not this script's to feed to sudo or to remove.
    if ! printf '%s\n' "$TEMP_PASSWORD" | sudo -S -k -p '' true 2>/dev/null; then
        TEMP_PASSWORD_USER=""
        echo "install.sh: ${USER_NAME} now has a password, but sudo did not accept the temporary one." >&2
        echo "  Nothing was installed, and the password was left as it is: if you did not" >&2
        echo "  type one yourself just now, it is '${TEMP_PASSWORD}'. Choose your own with \`passwd\`," >&2
        echo "  then run this again." >&2
        exit 1
    fi
    echo "Temporary password set. It is removed when this script exits."
}

TMP_DIR=$(mktemp -d)

echo "Downloading ${ASSET} (${VERSION}) from ${REPO}..."
# curl exits 22 on a 404, which with -f prints nothing useful. Say which
# URL failed and the likeliest reason, as cli/install.sh does.
for asset in "${ASSET}" "${ASSET}.sha256"; do
    if ! curl -fsSL "${BASE_URL}/${asset}" -o "${TMP_DIR}/${asset}"; then
        echo "install.sh: could not download ${BASE_URL}/${asset} (is ${VERSION} released?)" >&2
        exit 1
    fi
done

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

offer_temp_password

echo
echo "Installing into ${PLUGIN_DIR}/ (this needs sudo: that directory"
if [ -n "$TEMP_PASSWORD_USER" ]; then
    echo "belongs to root on a stock Decky Loader install)."
else
    echo "belongs to root on a stock Decky Loader install). You may be asked"
    echo "for your password now."
fi
as_root mkdir -p "$PLUGIN_DIR"
# Remove any previous install first: unzip -o only overwrites files the
# new zip still ships, so a module or asset a previous release shipped
# and this one no longer does would otherwise be left behind forever.
as_root rm -rf "${PLUGIN_DIR}/Moonlight Sync"
as_root unzip -o "${TMP_DIR}/${ASSET}" -d "$PLUGIN_DIR"

echo
echo "Restarting plugin_loader so Moonlight Sync loads (needs sudo again)."
as_root systemctl restart plugin_loader

# Done with sudo: take the temporary password off now rather than at exit
# (cleanup still does it for every exit before this line).
[ -z "$TEMP_PASSWORD_USER" ] || remove_temp_password

# What landed, not what was asked for: with the default "latest" the tag
# is not otherwise known here. package.json is in the zip and its
# "version" is what decky-loader shows (DECKY_PLUGIN_VERSION).
INSTALLED=$(sed -n 's/.*"version": *"\([^"]*\)".*/\1/p' \
    "${PLUGIN_DIR}/Moonlight Sync/package.json" 2>/dev/null | head -n 1)
[ -n "$INSTALLED" ] || INSTALLED="$VERSION"

echo
echo "Installed Moonlight Sync ${INSTALLED} to ${PLUGIN_DIR}/Moonlight Sync."
echo "Look for it in the Quick Access menu's Decky tab."
