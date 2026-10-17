"""SteamGridDB API v2 client (spec 2.2).

Thin wrapper over :class:`~moonlight_steam_sync.art.http.Fetcher`: build the
URL, send the bearer token, unwrap the ``{"success": true, "data": ...}``
envelope. Selection policy lives in :mod:`moonlight_steam_sync.art.select`,
not here.

Two invariants this module enforces for every asset query, because they are
decisions the rest of the tool depends on (spec 6.5):

* ``types=static`` -- animated assets are WebP-only, and we have no way to
  convert them without Pillow;
* ``mimes`` never includes ``image/webp`` -- Steam does not read WebP out of
  ``grid/``;
* ``logos`` and ``icons`` ask for PNG alone (:data:`MIMES_BY_KIND`): the
  logos endpoint answers 400 to a ``mimes`` that names ``image/jpeg``
  (measured 2026-10-17), which failed every community logo through 0.13.0.

``nsfw``, ``humor`` and ``epilepsy`` are left unsent so the API's own
``false`` defaults apply (spec 3.5).
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any
from urllib.parse import quote, urlencode

from moonlight_steam_sync.art.http import Fetcher, HttpError

BASE_URL = "https://www.steamgriddb.com/api/v2"

#: The only mime types we will accept in ``grid/``; WebP is deliberately absent.
#: The default for grids and heroes.
STATIC_IMAGE_MIMES = "image/png,image/jpeg"
PNG_ONLY_MIMES = "image/png"
#: ``mimes`` per asset kind where it is not :data:`STATIC_IMAGE_MIMES`. The
#: logos endpoint refuses ``image/jpeg`` with a 400; icons are PNG by choice.
MIMES_BY_KIND = {"logos": PNG_ONLY_MIMES, "icons": PNG_ONLY_MIMES}


def asset_query(kind: str, **params: Any) -> dict[str, Any]:
    """The query string of ``GET /{kind}/game/{id}``, filters applied.

    ``types=static``, then ``params`` (``None`` values dropped), then the
    kind's ``mimes`` unless ``params`` named one. Refuses WebP for every kind
    and JPEG for ``logos``, which SteamGridDB would answer with a 400.
    :mod:`moonlight_steam_sync.art.select` and the fixture recorder both
    build their URLs here, so they cannot drift.
    """
    query: dict[str, Any] = {"types": "static"}
    query.update({k: v for k, v in params.items() if v is not None})
    query.setdefault("mimes", MIMES_BY_KIND.get(kind, STATIC_IMAGE_MIMES))
    mimes = str(query["mimes"]).lower()
    if "webp" in mimes:
        raise ValueError("WebP is never requested (spec 6.5)")
    if kind == "logos" and "jpeg" in mimes:
        raise ValueError("SteamGridDB answers 400 to a logos query naming image/jpeg")
    return query


class SgdbError(HttpError):
    """SteamGridDB answered, but with ``success: false``."""


@dataclass
class SgdbClient:
    """The handful of SteamGridDB endpoints this tool uses."""

    api_key: str
    fetcher: Fetcher
    base_url: str = BASE_URL

    @property
    def enabled(self) -> bool:
        """False when no API key is configured (spec 6.12: the key is optional)."""
        return bool(self.api_key)

    def url(self, path: str, params: Mapping[str, Any] | None = None) -> str:
        """Build a fully qualified URL; exposed so ``--explain`` can print it."""
        url = f"{self.base_url}{path}"
        if params:
            url = f"{url}?{urlencode(dict(params), safe='/,')}"
        return url

    def _get_data(self, path: str, params: Mapping[str, Any] | None = None) -> Any:
        url = self.url(path, params)
        payload = self.fetcher.get_json(
            url, headers={"Authorization": f"Bearer {self.api_key}"}
        )
        if not isinstance(payload, dict):
            raise SgdbError(f"{url}: unexpected response shape")
        if not payload.get("success", False):
            errors = payload.get("errors") or ["unknown error"]
            raise SgdbError(f"{url}: {'; '.join(str(e) for e in errors)}")
        return payload.get("data")

    def search(self, term: str) -> list[dict[str, Any]]:
        """``GET /search/autocomplete/{term}`` -> games, best-first."""
        data = self._get_data(f"/search/autocomplete/{quote(term, safe='')}")
        return list(data) if isinstance(data, list) else []

    def game(self, sgdb_id: int) -> dict[str, Any]:
        """``GET /games/id/{id}?platformdata=steam``.

        The API has returned both an object and a one-element list here over
        time; normalise to a dict.
        """
        data = self._get_data(f"/games/id/{sgdb_id}", {"platformdata": "steam"})
        if isinstance(data, list):
            data = data[0] if data else {}
        return data if isinstance(data, dict) else {}

    def assets(self, kind: str, sgdb_id: int, **params: Any) -> list[dict[str, Any]]:
        """``GET /{kind}/game/{id}`` with :func:`asset_query`'s filters applied.

        ``kind`` is one of ``grids``, ``heroes``, ``logos``, ``icons``.
        Results come back sorted by ``score`` descending (spec 3.5).
        """
        query = asset_query(kind, **params)
        data = self._get_data(f"/{kind}/game/{sgdb_id}", query)
        assets = [a for a in data if isinstance(a, dict)] if isinstance(data, list) else []
        return sorted(assets, key=lambda a: _score(a), reverse=True)


def _score(asset: Mapping[str, Any]) -> float:
    value = asset.get("score", 0)
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def steam_appid_from_game(game: Mapping[str, Any]) -> int | None:
    """Pull ``external_platform_data.steam[0].id`` out of a ``game`` payload.

    SteamGridDB returns that id as a string; ``None`` when the game has no
    Steam release, which is exactly the "non-Steam game, community art only"
    case from spec 3.5.
    """
    platform_data = game.get("external_platform_data") or {}
    steam_entries = platform_data.get("steam") or []
    if not isinstance(steam_entries, list) or not steam_entries:
        return None
    first = steam_entries[0]
    if not isinstance(first, Mapping):
        return None
    raw = first.get("id")
    try:
        return int(raw)
    except (TypeError, ValueError):
        return None
