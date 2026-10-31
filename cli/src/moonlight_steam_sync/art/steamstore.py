"""Steam store search, the store's asset list, the icon hash, the CDN URLs.

This is the "official art" half of spec 3.5, and the only half that works
without a SteamGridDB key (spec 6.12). Everything here is an unauthenticated
public endpoint verified live on 2026-09-16 and again on 2026-10-31 (spec
2.2):

* ``https://store.steampowered.com/api/storesearch/?term=...&l=english&cc=US``
  -> ``items[{id, name}]``, used to turn a title into a Steam appid when
  SteamGridDB has nothing;
* ``https://api.steampowered.com/IStoreBrowseService/GetItems/v1/`` with
  ``include_assets`` -> the store's own list of the app's assets
  (:class:`StoreAssets`): an ``asset_url_format`` such as
  ``steam/apps/<appid>/${FILENAME}?t=<stamp>`` and one filename per asset.
  **Steam moved new apps' art to hashed paths** -- an app published since
  mid-2025 keeps its capsule at
  ``<40 hex>/library_capsule.jpg``, its header at ``<other hash>/header.jpg``
  and so on, each asset behind its own hash, and the plain
  ``steam/apps/<appid>/header.jpg`` answers 404 for it (measured 2026-10-31
  on Phantom Blade Zero, appid 4115450, whose every unhashed URL was a 404
  while the hashed ones served). The filenames themselves also vary
  (``library_capsule.jpg`` for a new app, ``library_600x900.jpg`` for an
  old one), so the only way to build a URL that works for every app is to
  ask the store which files it has. Served from
  ``https://shared.akamai.steamstatic.com/store_item_assets/``, which also
  serves the old unhashed files, hashes or not. The answer carries the
  ``community_icon`` hash too, so a title whose assets were listed costs no
  ``GetApps`` call;
* ``https://api.steampowered.com/ICommunityService/GetApps/v1/?appids[0]=<id>``
  -> the app's ``icon`` hash, the fallback for the icon when ``GetItems``
  has nothing for the app (delisted from the store, say);
* the unhashed ``cdn.cloudflare.steamstatic.com`` asset paths Steam ROM
  Manager rebuilds from ``platformdata=steam`` metadata, still served for
  apps published before the move, and the only official source of the logo
  (``GetItems`` does not list a ``logo.png``; a new app's logo comes from
  SteamGridDB).

Note that ``library_header.jpg`` does **not** exist on the CDN -- the
landscape/header slot is plain ``header.jpg``.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlencode

from moonlight_steam_sync.art.http import Fetcher

STORE_SEARCH_URL = "https://store.steampowered.com/api/storesearch/"
GET_APPS_URL = "https://api.steampowered.com/ICommunityService/GetApps/v1/"
GET_ITEMS_URL = "https://api.steampowered.com/IStoreBrowseService/GetItems/v1/"
CDN_BASE = "https://cdn.cloudflare.steamstatic.com"
#: Where ``GetItems``' ``asset_url_format`` is served from (the store page
#: itself links its images here).
STORE_ASSETS_BASE = "https://shared.akamai.steamstatic.com/store_item_assets"

#: The ``GetItems`` asset keys that fill a slot, in the order to try them
#: (2x first, like the unhashed builders below). No logo: ``GetItems`` has
#: no logo asset, and no icon here -- that is :attr:`StoreAssets.icon_hash`.
STORE_ASSET_KEYS: dict[str, tuple[str, ...]] = {
    "portrait": ("library_capsule_2x", "library_capsule"),
    "landscape": ("header",),
    "hero": ("library_hero",),
}


@dataclass(frozen=True)
class StoreAssets:
    """What ``GetItems`` lists for one app: a URL format and the files it has.

    ``url_format`` is the store's ``asset_url_format``
    (``steam/apps/<appid>/${FILENAME}?t=<stamp>``) and ``files`` maps each
    asset key to the filename to put in its place -- ``<hash>/header.jpg``
    for an app on hashed paths, plain ``header.jpg`` for an older one.
    """

    url_format: str
    files: Mapping[str, str] = field(default_factory=dict)
    #: The community icon hash (``community_icon``), or ``None``.
    icon_hash: str | None = None

    def url(self, key: str) -> str | None:
        """The full URL of the asset ``key``, or ``None`` when the app has none."""
        filename = self.files.get(key)
        if not filename:
            return None
        return store_asset_url(self.url_format, filename)

    def urls(self, slot_key: str) -> list[str]:
        """The URLs to try for ``slot_key``, best first (empty for the logo)."""
        return [
            url
            for url in (self.url(key) for key in STORE_ASSET_KEYS.get(slot_key, ()))
            if url is not None
        ]


def store_asset_url(url_format: str, filename: str) -> str:
    """``url_format`` with ``${FILENAME}`` filled in, under :data:`STORE_ASSETS_BASE`."""
    return f"{STORE_ASSETS_BASE}/{url_format.replace('${FILENAME}', filename)}"


def portrait_urls(appid: int) -> list[str]:
    """Portrait capsule (600x900), 2x first."""
    return [
        f"{CDN_BASE}/steam/apps/{appid}/library_600x900_2x.jpg",
        f"{CDN_BASE}/steam/apps/{appid}/library_600x900.jpg",
    ]


def landscape_urls(appid: int) -> list[str]:
    """Landscape/header capsule (460x215)."""
    return [f"{CDN_BASE}/steam/apps/{appid}/header.jpg"]


def hero_urls(appid: int) -> list[str]:
    """Hero banner."""
    return [f"{CDN_BASE}/steam/apps/{appid}/library_hero.jpg"]


def logo_urls(appid: int) -> list[str]:
    """Transparent logo drawn over the hero."""
    return [f"{CDN_BASE}/steam/apps/{appid}/logo.png"]


def icon_url(appid: int, icon_hash: str) -> str:
    """The 32x32 client icon, addressed by the hash :func:`app_icon_hash` returns."""
    return f"{CDN_BASE}/steamcommunity/public/images/apps/{appid}/{icon_hash}.jpg"


def store_search_url(term: str) -> str:
    return f"{STORE_SEARCH_URL}?{urlencode({'term': term, 'l': 'english', 'cc': 'US'})}"


def get_apps_url(appid: int) -> str:
    return f"{GET_APPS_URL}?{urlencode({'appids[0]': appid})}"


def get_items_url(appid: int) -> str:
    """``GetItems`` for one app with its assets, as one GET (``input_json``)."""
    request = {
        "ids": [{"appid": appid}],
        "context": {"language": "english", "country_code": "US"},
        "data_request": {"include_assets": True},
    }
    input_json = json.dumps(request, separators=(",", ":"), sort_keys=True)
    return f"{GET_ITEMS_URL}?{urlencode({'input_json': input_json})}"


def parse_store_assets(payload: Any, appid: int) -> StoreAssets | None:
    """The :class:`StoreAssets` in a ``GetItems`` response, or ``None``.

    ``None`` is "the store has nothing for this app" (not listed, ``success``
    other than 1 -- an unknown appid answers 200 with ``success: 15`` -- or
    no ``assets``): a definite answer, not a failure, so the caller falls
    back to the unhashed CDN paths and, for the icon, ``GetApps``.
    """
    if not isinstance(payload, Mapping):
        return None
    items = (payload.get("response") or {}).get("store_items") or []
    if not isinstance(items, list):
        return None
    for item in items:
        if not isinstance(item, Mapping) or item.get("appid") != appid:
            continue
        if item.get("success", 1) != 1:
            return None
        assets = item.get("assets")
        if not isinstance(assets, Mapping):
            return None
        url_format = assets.get("asset_url_format")
        if not isinstance(url_format, str) or "${FILENAME}" not in url_format:
            return None
        files = {
            key: value
            for key, value in assets.items()
            if isinstance(value, str) and value and key != "asset_url_format"
        }
        icon = assets.get("community_icon")
        return StoreAssets(
            url_format=url_format,
            files=files,
            icon_hash=str(icon) if isinstance(icon, str) and icon else None,
        )
    return None


@dataclass
class SteamStoreClient:
    """The three JSON endpoints; the CDN builders above need no client."""

    fetcher: Fetcher

    def assets(self, appid: int) -> StoreAssets | None:
        """``GetItems`` -> the app's :class:`StoreAssets`; ``None`` when the store has nothing."""
        return parse_store_assets(self.fetcher.get_json(get_items_url(appid)), appid)

    def search(self, term: str) -> list[dict[str, Any]]:
        """``storesearch`` -> ``items``, best-first, as Steam ranks them."""
        payload = self.fetcher.get_json(store_search_url(term))
        if not isinstance(payload, Mapping):
            return []
        items = payload.get("items") or []
        return [i for i in items if isinstance(i, dict)] if isinstance(items, list) else []

    def app_icon_hash(self, appid: int) -> str | None:
        """The ``icon`` hash for ``appid``, or ``None`` when Steam has none."""
        payload = self.fetcher.get_json(get_apps_url(appid))
        if not isinstance(payload, Mapping):
            return None
        apps = (payload.get("response") or {}).get("apps") or []
        if not isinstance(apps, list):
            return None
        for app in apps:
            if not isinstance(app, Mapping):
                continue
            icon = app.get("icon")
            if icon:
                return str(icon)
        return None
