"""The plugin's own files under ``DECKY_PLUGIN_SETTINGS_DIR`` (spec 3.7).

- ``settings.json``   plugin settings (never the active host: that is the
  CLI's state file)
- ``ignore.json``     the ``--ignore-file`` list, sorted
- ``owned-apps.json`` the ``--owned-apps`` file (spec 3.4.1)
- ``pending.json``    the restart/walk flags of spec 3.9, the *Last sync*
  row and ``synced_hosts`` (every host a sync has planned for)
- ``layouts.json``    per-shortcut layout results (PR-7)

Every write is ``.tmp`` + ``os.replace``. None of these files is under the
Steam directory, and ``config.toml`` is never touched.
"""

from __future__ import annotations

import contextlib
import copy
import json
import os
from typing import Any

from . import wake

SETTINGS_FILE = "settings.json"
IGNORE_FILE = "ignore.json"
OWNED_APPS_FILE = "owned-apps.json"
PENDING_FILE = "pending.json"
LAYOUTS_FILE = "layouts.json"

#: Defaults for ``settings.json``. ``hosts`` is deliberately absent from the
#: file until it has been seeded once from ``host show`` (spec 3.7); readers
#: see ``[]`` until then.
DEFAULT_SETTINGS: dict[str, Any] = {
    "version": 1,
    # the whole plugin on or off (spec 3.19): off hides every entry in the
    # client, injects nothing into the library and refuses runs, for a
    # Deck away from its host; the toggle is the one setting still live
    "enabled": True,
    "copy_layouts": True,
    "restart_countdown_s": 5,
    "retry_missing": False,
    "layout_strategy": "copy",
    "hide_stream_shortcuts": True,
    # the *Streaming* group (spec 3.17): the library tab, or the fallback
    # collection while Stream shortcuts are shown; the key kept its name
    "streaming_collection": True,
    "default_layout": None,
    # Wake-on-LAN (spec 3.18): {<host name>: "aa:bb:cc:dd:ee:ff"}, entered on
    # the Host page for a host whose MAC Moonlight's own list does not carry
    "wake_macs": {},
}

#: The countdown can never outlast the CLI's own await-exit wait (60 s),
#: which would race it, so the slider and the file both stop at 30
#: (spec Decision 30). A larger value stored by an older build is
#: clamped on read rather than making settings.json unreadable.
RESTART_COUNTDOWN_MAX = 30
LAYOUT_STRATEGIES = ("copy", "picker")
#: The settings ``set_settings`` accepts as plain booleans.
BOOL_SETTINGS = (
    "enabled",
    "copy_layouts",
    "retry_missing",
    "hide_stream_shortcuts",
    "streaming_collection",
)

#: What one layout copy (or *Choose layout*) can record (spec 3.10 / 3.16).
#: ``default`` is spec 3.16: the entry is on the plugin's default layout.
LAYOUT_RESULTS = ("copied", "kept", "unavailable", "picker", "default")

#: URL schemes ``set_default_layout`` accepts (spec 3.16.1 / Decision 49):
#: a Workshop item (community, or a personal layout that was *exported*) or
#: a ``template://`` stock layout with ``bSelected: true``. ``autosave://``
#: (edited in place, a file path under one appid) and ``default://`` (no
#: choice at all) are refused up front rather than tried, since two apps
#: sharing one autosave file is unmeasured and not fail-safe.
DEFAULT_LAYOUT_SCHEMES = ("workshop://", "template://")
#: The longest a stored default layout's URL or title may be.
DEFAULT_LAYOUT_URL_MAX = 2048
DEFAULT_LAYOUT_TITLE_MAX = 200
#: Non-Steam shortcuts live at and above this appid (the CLI's ``| 0x80000000``).
SHORTCUT_APPID_FLOOR = 0x80000000

DEFAULT_LAYOUTS: dict[str, Any] = {"version": 1, "entries": {}}

DEFAULT_PENDING: dict[str, Any] = {
    "restart_needed": "none",
    "layout_walk": False,
    "since": None,
    "last_summary": None,
    "last_plan": None,
    "last_kind": None,
    #: ``{<host>: <iso time>}``: every host a ``sync`` has listed and planned
    #: for, in the plan's spelling. The Titles page lists nothing for a host
    #: missing here: a *Check* or an add caches a host's list too.
    "synced_hosts": {},
}

PENDING_KEYS = ("restart_needed", "layout_walk")


def _legacy_synced_hosts(data: dict[str, Any]) -> dict[str, Any]:
    """``synced_hosts`` for a ``pending.json`` from before the key: the host
    of the last recorded plan (only a ``sync`` plans), stamped with ``since``,
    so an upgrade does not blank the Titles page of the host being synced.
    Any other host counts as synced from its next sync."""
    plan = data.get("last_plan")
    host = plan.get("host") if isinstance(plan, dict) else None
    if not isinstance(host, str) or not host:
        return {}
    since = data.get("since")
    return {host: since if isinstance(since, str) else None}


class SettingsError(ValueError):
    """A request the settings layer refuses (the callable's ``bad-request``)."""


def write_json_atomic(path: str, data: Any, *, mode: int | None = None) -> None:
    """Write ``data`` as JSON to ``path`` via ``.tmp`` + ``os.replace``."""
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    tmp = path + ".tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as handle:
            json.dump(data, handle, indent=2, sort_keys=True, ensure_ascii=False)
            handle.write("\n")
        if mode is not None:
            os.chmod(tmp, mode)
        os.replace(tmp, path)
    except BaseException:
        with contextlib.suppress(OSError):
            os.unlink(tmp)
        raise


def read_json(path: str, default: Any) -> Any:
    """The parsed file, or a deep copy of ``default`` when it does not exist."""
    if not os.path.exists(path):
        return copy.deepcopy(default)
    with open(path, encoding="utf-8") as handle:
        return json.load(handle)


class Store:
    """Typed access to the files in one settings directory."""

    def __init__(self, settings_dir: str) -> None:
        self.dir = settings_dir

    def path(self, name: str) -> str:
        return os.path.join(self.dir, name)

    # -- startup ---------------------------------------------------------

    def ensure_files(self) -> None:
        """Create ``settings.json`` (defaults) and ``ignore.json`` (``[]``) when absent."""
        os.makedirs(self.dir, exist_ok=True)
        if not os.path.exists(self.path(SETTINGS_FILE)):
            write_json_atomic(self.path(SETTINGS_FILE), dict(DEFAULT_SETTINGS))
        if not os.path.exists(self.path(IGNORE_FILE)):
            write_json_atomic(self.path(IGNORE_FILE), [])

    # -- settings.json ---------------------------------------------------

    def _raw_settings(self) -> dict[str, Any]:
        raw = read_json(self.path(SETTINGS_FILE), {})
        return raw if isinstance(raw, dict) else {}

    def hosts_seeded(self) -> bool:
        return "hosts" in self._raw_settings()

    def settings(self) -> dict[str, Any]:
        """Defaults overlaid with the file; ``hosts`` is ``[]`` until seeded.

        ``restart_countdown_s`` is clamped to ``RESTART_COUNTDOWN_MAX`` on the
        way out: a file written before Decision 30 lowered the ceiling to 30
        still reads, it just counts down from 30.
        """
        merged = dict(DEFAULT_SETTINGS)
        merged["hosts"] = []
        for key, value in self._raw_settings().items():
            if key in merged:
                merged[key] = value
        macs = merged.get("wake_macs")
        merged["wake_macs"] = dict(macs) if isinstance(macs, dict) else {}
        countdown = merged["restart_countdown_s"]
        if isinstance(countdown, int) and not isinstance(countdown, bool):
            merged["restart_countdown_s"] = max(0, min(countdown, RESTART_COUNTDOWN_MAX))
        else:
            merged["restart_countdown_s"] = DEFAULT_SETTINGS["restart_countdown_s"]
        merged["default_layout"] = _sanitize_default_layout(merged["default_layout"])
        return merged

    def set_settings(self, patch: Any) -> dict[str, Any]:
        """Merge ``patch`` into the file after validating every key; returns the result."""
        if not isinstance(patch, dict):
            raise SettingsError("settings patch must be an object")
        for key, value in patch.items():
            _validate_setting(key, value)
        raw = self._raw_settings()
        raw.update(patch)
        raw["version"] = 1
        write_json_atomic(self.path(SETTINGS_FILE), raw)
        return self.settings()

    def set_default_layout(self, url: Any, title: Any, *, when: str) -> dict[str, Any]:
        """Store or clear ``default_layout`` (spec 3.16.2); always sets ``layout_walk``.

        ``url`` ``None`` clears it (``title`` is ignored) and still flags a
        walk: the unset pass of 3.16.4 has to run so entries the plugin put
        on the old default get it taken off. Otherwise ``url`` must be a
        ``str`` starting with one of ``DEFAULT_LAYOUT_SCHEMES``, at most
        ``DEFAULT_LAYOUT_URL_MAX`` characters, and ``title`` a ``str`` (empty
        allowed), stripped and at most ``DEFAULT_LAYOUT_TITLE_MAX``
        characters; anything else is a ``SettingsError`` (the callable's
        ``bad-request``). Settings are written first, then ``pending``.
        """
        if url is None:
            value = None
        else:
            if (
                isinstance(url, bool)
                or not isinstance(url, str)
                or not url.startswith(DEFAULT_LAYOUT_SCHEMES)
                or len(url) > DEFAULT_LAYOUT_URL_MAX
            ):
                raise SettingsError(
                    f"url must be a string starting with one of {DEFAULT_LAYOUT_SCHEMES}, "
                    f"at most {DEFAULT_LAYOUT_URL_MAX} characters"
                )
            if isinstance(title, bool) or not isinstance(title, str):
                raise SettingsError("title must be a string")
            title = title.strip()
            if len(title) > DEFAULT_LAYOUT_TITLE_MAX:
                raise SettingsError(f"title must be at most {DEFAULT_LAYOUT_TITLE_MAX} characters")
            value = {"url": url, "title": title, "when": when}
        raw = self._raw_settings()
        for key, default in DEFAULT_SETTINGS.items():
            raw.setdefault(key, default)
        raw["default_layout"] = value
        write_json_atomic(self.path(SETTINGS_FILE), raw)
        pending = self.pending()
        pending["layout_walk"] = True
        self.write_pending(pending)
        return self.settings()

    def set_hosts(self, hosts: list[str]) -> list[str]:
        raw = self._raw_settings()
        for key, value in DEFAULT_SETTINGS.items():
            raw.setdefault(key, value)
        raw["hosts"] = list(hosts)
        keep = {h.lower() for h in hosts}
        macs = raw.get("wake_macs")
        if isinstance(macs, dict):
            raw["wake_macs"] = {k: v for k, v in macs.items() if k.lower() in keep}
        write_json_atomic(self.path(SETTINGS_FILE), raw)
        return list(hosts)

    def wake_mac(self, name: str) -> str | None:
        """The stored Wake-on-LAN MAC for ``name`` (any case), normalised, or ``None``."""
        macs = self.settings()["wake_macs"]
        for host, mac in macs.items():
            if host.lower() == name.lower():
                return wake.parse_mac(mac)
        return None

    def set_wake_mac(self, name: str, mac: Any) -> str | None:
        """Store (``mac`` a MAC in any usual spelling) or drop (``None`` / ``""``) one host's MAC.

        Returns the normalised MAC now stored, or ``None`` after a drop. The
        key is the host's name as given; an existing key of another case is
        replaced.
        """
        if mac is None or (isinstance(mac, str) and not mac.strip()):
            normalised = None
        else:
            normalised = wake.parse_mac(mac)
            if normalised is None:
                raise SettingsError("a MAC address looks like aa:bb:cc:dd:ee:ff")
        raw = self._raw_settings()
        for key, value in DEFAULT_SETTINGS.items():
            raw.setdefault(key, value)
        macs = raw.get("wake_macs")
        if not isinstance(macs, dict):
            macs = {}
        macs = {k: v for k, v in macs.items() if k.lower() != name.lower()}
        if normalised is not None:
            macs[name] = normalised
        raw["wake_macs"] = macs
        write_json_atomic(self.path(SETTINGS_FILE), raw)
        return normalised

    # -- ignore.json -----------------------------------------------------

    def ignored(self) -> list[str]:
        data = read_json(self.path(IGNORE_FILE), [])
        if not isinstance(data, list):
            return []
        return sorted(str(name) for name in data)

    def set_ignored(self, name: str, ignored: bool) -> list[str]:
        """Add or remove one exact Moonlight name; the file stays sorted and unique.

        Idempotent: ignoring an ignored name or unignoring one that is not
        in the list leaves the list as it was (the file is only rewritten
        when its contents are not already that sorted list). Only
        ``ignore.json`` is touched; a name ignored in the CLI's
        ``config.toml`` stays ignored (the tool never writes that file).
        """
        current = set(self.ignored())
        wanted = sorted(current | {name} if ignored else current - {name})
        path = self.path(IGNORE_FILE)
        if not os.path.exists(path) or read_json(path, []) != wanted:
            write_json_atomic(path, wanted)
        return wanted

    # -- owned-apps.json -------------------------------------------------

    def owned_apps_exists(self) -> bool:
        return os.path.exists(self.path(OWNED_APPS_FILE))

    def write_owned_apps(self, steamid3: int, apps: dict[str, str]) -> int:
        write_json_atomic(
            self.path(OWNED_APPS_FILE),
            {"version": 1, "steamid3": steamid3, "apps": apps},
        )
        return len(apps)

    # -- pending.json ----------------------------------------------------

    def pending(self) -> dict[str, Any]:
        merged = copy.deepcopy(DEFAULT_PENDING)
        data = read_json(self.path(PENDING_FILE), {})
        if isinstance(data, dict):
            for key in merged:
                if key in data:
                    merged[key] = data[key]
            if "synced_hosts" not in data:
                merged["synced_hosts"] = _legacy_synced_hosts(data)
        if not isinstance(merged["synced_hosts"], dict):
            merged["synced_hosts"] = {}
        return merged

    def write_pending(self, pending: dict[str, Any]) -> dict[str, Any]:
        merged = copy.deepcopy(DEFAULT_PENDING)
        merged.update({key: pending[key] for key in DEFAULT_PENDING if key in pending})
        write_json_atomic(self.path(PENDING_FILE), merged)
        return merged

    def clear_pending(self, key: str) -> dict[str, Any]:
        if key not in PENDING_KEYS:
            raise SettingsError(f"unknown pending key {key!r}; expected one of {PENDING_KEYS}")
        pending = self.pending()
        pending[key] = "none" if key == "restart_needed" else False
        return self.write_pending(pending)

    # -- layouts.json ----------------------------------------------------

    def layouts(self) -> dict[str, Any]:
        """``{"version": 1, "entries": {<shortcut appid>: {...}}}`` (spec 3.10).

        The file is a record of results, not a source of truth, so one that
        is missing, unparsable or not of that shape reads as empty rather
        than failing the callable; the next ``record_layout`` rewrites it.
        """
        try:
            data = read_json(self.path(LAYOUTS_FILE), DEFAULT_LAYOUTS)
        except ValueError:
            data = copy.deepcopy(DEFAULT_LAYOUTS)
        entries = data.get("entries") if isinstance(data, dict) else None
        if not isinstance(entries, dict):
            entries = {}
        return {"version": 1, "entries": entries}

    def record_layout(
        self,
        shortcut_appid: int,
        real_appid: int | None,
        result: str,
        url: str | None,
        *,
        when: str,
    ) -> dict[str, Any]:
        """Upsert one shortcut's entry atomically; returns the whole file.

        ``real_appid`` may be ``None`` for any result (spec 3.16.2): the
        walk covers entries with no Steam game behind them (host apps, the
        client, a title never matched), not only a ``picker`` result.

        ``applied`` (spec 3.16.2/3.16.3) is the last URL *the plugin itself*
        set on the shortcut, computed here so the frontend never has to:
        ``prev_applied = prev.get("applied")``, or ``prev["url"]`` when
        ``prev`` has no ``applied`` key and ``prev["result"] == "copied"``
        (a pre-3.16 copy counts as plugin-applied, Decision 46, so it
        migrates to the default on the first walk after one is set). Then
        ``default`` and ``copied`` set ``applied = url`` (both are a URL the
        plugin just set; Decision 53); ``kept`` keeps ``prev_applied`` when
        ``url`` *is* ``prev_applied`` (the selection kept is still the
        plugin's own, which is what the spec 3.10 copy reports on a title it
        copied earlier) and clears it to ``None`` otherwise (the user made
        their own choice); ``unavailable`` / ``picker`` carry
        ``prev_applied`` forward unchanged (or ``None`` with no ``prev``).

        The table has to hold under the spec 3.10 frontend too: until PR-10
        lands, every Stream press and walk still records ``copied`` /
        ``kept`` here, and PR-10's ``applyDefault`` only reports ``kept``
        for a URL that is not the plugin's, so the ``kept`` rule reduces to
        ``None`` there.
        """
        if isinstance(shortcut_appid, bool) or not isinstance(shortcut_appid, int):
            raise SettingsError("shortcut_appid must be an integer")
        if shortcut_appid < SHORTCUT_APPID_FLOOR:
            raise SettingsError(
                "shortcut_appid must be a non-Steam shortcut appid (0x80000000 or above)"
            )
        if result not in LAYOUT_RESULTS:
            raise SettingsError(f"result must be one of {', '.join(LAYOUT_RESULTS)}")
        if real_appid is not None:
            if isinstance(real_appid, bool) or not isinstance(real_appid, int) or real_appid <= 0:
                raise SettingsError("real_appid must be a positive integer")
            if real_appid >= SHORTCUT_APPID_FLOOR:
                raise SettingsError("real_appid must be a Steam appid (below 0x80000000)")
        if url is not None and not isinstance(url, str):
            raise SettingsError("url must be a string or null")
        data = self.layouts()
        prev = data["entries"].get(str(shortcut_appid))
        if prev is None:
            prev_applied = None
        elif "applied" in prev:
            prev_applied = prev["applied"]
        elif prev.get("result") == "copied":
            prev_applied = prev.get("url")
        else:
            prev_applied = None
        if result in ("default", "copied"):
            applied = url or None
        elif result == "kept":
            applied = prev_applied if url and url == prev_applied else None
        else:  # "unavailable", "picker"
            applied = prev_applied
        data["entries"][str(shortcut_appid)] = {
            "real_appid": real_appid,
            "result": result,
            "url": url or None,
            "when": when,
            "applied": applied,
        }
        write_json_atomic(self.path(LAYOUTS_FILE), data)
        return data

    def delete_layouts(self) -> None:
        with contextlib.suppress(FileNotFoundError):
            os.unlink(self.path(LAYOUTS_FILE))


def _sanitize_default_layout(value: Any) -> dict[str, Any] | None:
    """``value`` when it is a dict with a shareable ``url`` and a ``title``
    string, else ``None`` (a hand-broken file reads as "no default")."""
    if not isinstance(value, dict):
        return None
    url = value.get("url")
    title = value.get("title")
    if not isinstance(url, str) or not url.startswith(DEFAULT_LAYOUT_SCHEMES):
        return None
    if not isinstance(title, str):
        return None
    when = value.get("when")
    return {"url": url, "title": title, "when": when if isinstance(when, str) else None}


def _validate_setting(key: str, value: Any) -> None:
    if key == "hosts":
        raise SettingsError("hosts are changed with add_host / forget_host")
    if key == "version":
        raise SettingsError("version is not a setting")
    if key == "default_layout":
        raise SettingsError("default_layout is changed with set_default_layout")
    if key == "wake_macs":
        raise SettingsError("wake_macs is changed with set_wake_mac")
    if key in BOOL_SETTINGS:
        if not isinstance(value, bool):
            raise SettingsError(f"{key} must be true or false")
        return
    if key == "restart_countdown_s":
        if isinstance(value, bool) or not isinstance(value, int):
            raise SettingsError("restart_countdown_s must be a whole number of seconds")
        if not 0 <= value <= RESTART_COUNTDOWN_MAX:
            raise SettingsError(f"restart_countdown_s must be 0-{RESTART_COUNTDOWN_MAX}")
        return
    if key == "layout_strategy":
        if value not in LAYOUT_STRATEGIES:
            raise SettingsError(f"layout_strategy must be one of {', '.join(LAYOUT_STRATEGIES)}")
        return
    raise SettingsError(f"unknown setting {key!r}")
