"""The SteamGridDB API key: which source the CLI will use, and the key file.

Mirrors the CLI's ``config.py`` lookup order exactly (spec 3.7):

1. ``[steamgriddb].api_key`` in ``~/.config/moonlight-steam-sync/config.toml``
2. ``SGDB_API_KEY`` in the environment the CLI child inherits
3. ``~/.config/moonlight-steam-sync/sgdb-api-key``

The plugin writes only (3), the CLI's own key-file seam, and never
``config.toml``. The key itself never leaves this module except as its last
four characters (``hint``).
"""

from __future__ import annotations

import contextlib
import os
import tomllib
from dataclasses import dataclass

CONFIG_DIR_PARTS = (".config", "moonlight-steam-sync")
KEY_FILE_NAME = "sgdb-api-key"
CONFIG_FILE_NAME = "config.toml"


class KeyRefused(ValueError):
    """``set_sgdb_key`` refused: ``code`` is the callable's error code."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass
class KeyState:
    source: str  # "config" | "env" | "file" | "none"
    key: str  # the effective key; never returned to the frontend
    config_parse_error: bool = False

    @property
    def hint(self) -> str | None:
        return self.key[-4:] if self.source != "none" and self.key else None

    def public(self) -> dict[str, object]:
        """The only shape that may reach the frontend."""
        return {
            "ok": True,
            "source": self.source,
            "hint": self.hint,
            "config_parse_error": self.config_parse_error,
        }


def config_dir(home: str) -> str:
    return os.path.join(home, *CONFIG_DIR_PARTS)


def key_file_path(home: str) -> str:
    return os.path.join(config_dir(home), KEY_FILE_NAME)


def config_path(home: str) -> str:
    return os.path.join(config_dir(home), CONFIG_FILE_NAME)


def _config_key(home: str) -> tuple[str, bool]:
    """``(key, parse_error)`` from ``config.toml``; ``("", False)`` when absent."""
    path = config_path(home)
    if not os.path.exists(path):
        return "", False
    try:
        with open(path, "rb") as handle:
            data = tomllib.load(handle)
    except (OSError, tomllib.TOMLDecodeError, UnicodeDecodeError):
        return "", True
    section = data.get("steamgriddb")
    if not isinstance(section, dict):
        return "", False
    value = section.get("api_key", "")
    return (value, False) if isinstance(value, str) and value else ("", False)


def key_state(home: str, env: dict[str, str]) -> KeyState:
    """Which key the CLI (run from the plugin) will use, following its precedence."""
    config_key, parse_error = _config_key(home)
    if config_key:
        return KeyState("config", config_key, parse_error)
    env_key = env.get("SGDB_API_KEY", "")
    if env_key:
        return KeyState("env", env_key, parse_error)
    path = key_file_path(home)
    try:
        with open(path, encoding="utf-8") as handle:
            file_key = handle.read().strip()
    except (OSError, UnicodeDecodeError):
        file_key = ""
    if file_key:
        return KeyState("file", file_key, parse_error)
    return KeyState("none", "", parse_error)


def set_key(home: str, env: dict[str, str], key: object) -> KeyState:
    """Write ``key.strip()`` + newline to the key file with mode 0600, atomically.

    Refuses an empty key (``bad-request``) and a key already in
    ``config.toml`` (it would win, so the field would silently do nothing).
    With ``SGDB_API_KEY`` set the file is written anyway; the environment
    still wins and the Artwork page says so.
    """
    if not isinstance(key, str) or not key.strip():
        raise KeyRefused("bad-request", "the key is empty")
    state = key_state(home, env)
    if state.source == "config":
        raise KeyRefused("bad-request", "set in config.toml")
    directory = config_dir(home)
    os.makedirs(directory, exist_ok=True)
    path = key_file_path(home)
    tmp = path + ".tmp"
    try:
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(key.strip() + "\n")
        os.chmod(tmp, 0o600)
        os.replace(tmp, path)
    except BaseException:
        with contextlib.suppress(OSError):
            os.unlink(tmp)
        raise
    return key_state(home, env)


def clear_key(home: str, env: dict[str, str]) -> KeyState:
    """Delete the key file (and nothing else); a missing file is fine."""
    with contextlib.suppress(FileNotFoundError):
        os.unlink(key_file_path(home))
    return key_state(home, env)
