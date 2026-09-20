"""A stand-in for decky-loader's ``decky`` module, for tests that import main.py.

The real module is injected by decky-loader at plugin start (see the
template's ``decky.pyi``). This stub reads the same ``DECKY_*`` environment
variables the loader exports, so a test sets them with ``monkeypatch.setenv``
and then imports ``main`` fresh. ``emit`` records into :data:`emitted`.
"""

from __future__ import annotations

import logging
import os
from typing import Any

HOME = os.environ.get("HOME", "")
USER = os.environ.get("USER", "deck")
DECKY_VERSION = "v3.0.0-test"
DECKY_USER = os.environ.get("DECKY_USER", "deck")
DECKY_USER_HOME = os.environ.get("DECKY_USER_HOME", HOME)
DECKY_HOME = os.environ.get("DECKY_HOME", os.path.join(DECKY_USER_HOME, "homebrew"))
DECKY_PLUGIN_SETTINGS_DIR = os.environ.get(
    "DECKY_PLUGIN_SETTINGS_DIR", os.path.join(DECKY_HOME, "settings", "Moonlight Sync")
)
DECKY_PLUGIN_RUNTIME_DIR = os.environ.get(
    "DECKY_PLUGIN_RUNTIME_DIR", os.path.join(DECKY_HOME, "data", "Moonlight Sync")
)
DECKY_PLUGIN_LOG_DIR = os.environ.get(
    "DECKY_PLUGIN_LOG_DIR", os.path.join(DECKY_HOME, "logs", "Moonlight Sync")
)
DECKY_PLUGIN_DIR = os.environ.get(
    "DECKY_PLUGIN_DIR", os.path.join(DECKY_HOME, "plugins", "Moonlight Sync")
)
DECKY_PLUGIN_NAME = "Moonlight Sync"
DECKY_PLUGIN_VERSION = os.environ.get("DECKY_PLUGIN_VERSION", "0.1.0")
DECKY_PLUGIN_AUTHOR = "episode6"
DECKY_PLUGIN_LOG = os.path.join(DECKY_PLUGIN_LOG_DIR, "plugin.log")

logger = logging.getLogger("decky-stub")

emitted: list[tuple[str, tuple[Any, ...]]] = []


async def emit(event: str, *args: Any) -> None:
    emitted.append((event, args))


def migrate_any(target_dir: str, *files_or_directories: str) -> dict[str, str]:
    return {}


def migrate_settings(*files_or_directories: str) -> dict[str, str]:
    return {}


def migrate_runtime(*files_or_directories: str) -> dict[str, str]:
    return {}


def migrate_logs(*files_or_directories: str) -> dict[str, str]:
    return {}
