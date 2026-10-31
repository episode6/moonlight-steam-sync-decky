"""The store's asset list (``GetItems``): the URL, the parser, the per-slot URLs."""

from __future__ import annotations

import json
from urllib.parse import parse_qs, urlsplit

from moonlight_steam_sync.art import steamstore
from moonlight_steam_sync.art.steamstore import StoreAssets, parse_store_assets

# The shape measured on 2026-10-31 for Phantom Blade Zero (4115450), the
# app whose every unhashed CDN URL was a 404: one hash per asset, the newer
# ``library_capsule`` filenames, a ``?t=`` stamp on every URL.
HASHED = {
    "asset_url_format": "steam/apps/4115450/${FILENAME}?t=1793261976",
    "main_capsule": "98af27aecb2eedd674e4e18b5fb3e58754729589/capsule_616x353.jpg",
    "header": "7f882f889630270d3d3fb93825ac6f55b55e7a6c/header.jpg",
    "library_capsule": "471e77854910665c03eb9a53ad06f2ac12903acd/library_capsule.jpg",
    "library_capsule_2x": "471e77854910665c03eb9a53ad06f2ac12903acd/library_capsule_2x.jpg",
    "library_hero": "1cd52ca84a3d974c4206e9cb90231956324c5999/library_hero.jpg",
    "library_hero_2x": "1cd52ca84a3d974c4206e9cb90231956324c5999/library_hero_2x.jpg",
    "community_icon": "ce420dc458dd3d7af276f48fbaa44a05876760dc",
    "last_modified": 1793261976,
}
BASE = "https://shared.akamai.steamstatic.com/store_item_assets/steam/apps/4115450"


def item(appid: int, assets: dict | None, success: int = 1) -> dict:
    payload: dict = {"item_type": 0, "id": appid, "success": success, "appid": appid}
    if assets is not None:
        payload["assets"] = assets
    return {"response": {"store_items": [payload]}}


def test_the_get_items_url_asks_for_one_app_with_its_assets() -> None:
    url = steamstore.get_items_url(4115450)
    parts = urlsplit(url)
    assert f"{parts.scheme}://{parts.netloc}{parts.path}" == steamstore.GET_ITEMS_URL
    request = json.loads(parse_qs(parts.query)["input_json"][0])
    assert request == {
        "ids": [{"appid": 4115450}],
        "context": {"language": "english", "country_code": "US"},
        "data_request": {"include_assets": True},
    }
    assert url == steamstore.get_items_url(4115450)  # stable: the fixtures key on it


def test_hashed_assets_become_urls_under_the_store_assets_host() -> None:
    assets = parse_store_assets(item(4115450, HASHED), 4115450)
    assert isinstance(assets, StoreAssets)
    assert assets.urls("portrait") == [
        f"{BASE}/471e77854910665c03eb9a53ad06f2ac12903acd/library_capsule_2x.jpg?t=1793261976",
        f"{BASE}/471e77854910665c03eb9a53ad06f2ac12903acd/library_capsule.jpg?t=1793261976",
    ]
    assert assets.urls("landscape") == [
        f"{BASE}/7f882f889630270d3d3fb93825ac6f55b55e7a6c/header.jpg?t=1793261976"
    ]
    assert assets.urls("hero") == [
        f"{BASE}/1cd52ca84a3d974c4206e9cb90231956324c5999/library_hero.jpg?t=1793261976"
    ]
    # The store lists no logo; the unhashed CDN path stays the official source.
    assert assets.urls("logo") == []
    assert assets.icon_hash == "ce420dc458dd3d7af276f48fbaa44a05876760dc"


def test_an_older_apps_plain_filenames_work_the_same_way() -> None:
    assets = parse_store_assets(
        item(
            1245620,
            {
                "asset_url_format": "steam/apps/1245620/${FILENAME}?t=1790290043",
                "header": "header.jpg",
                "library_capsule": "library_600x900.jpg",
                "library_capsule_2x": "library_600x900_2x.jpg",
                "library_hero": "library_hero.jpg",
                "community_icon": "b6e290dd5a92ce98f89089a207733c70c41a1871",
            },
        ),
        1245620,
    )
    assert assets.urls("portrait")[0] == (
        "https://shared.akamai.steamstatic.com/store_item_assets/steam/apps/1245620/"
        "library_600x900_2x.jpg?t=1790290043"
    )


def test_a_missing_asset_is_skipped_not_invented() -> None:
    assets = parse_store_assets(
        item(1, {"asset_url_format": "steam/apps/1/${FILENAME}", "header": "x/header.jpg"}), 1
    )
    assert assets.urls("portrait") == []
    assert assets.urls("hero") == []
    assert assets.icon_hash is None


def test_an_app_the_store_does_not_list_is_none() -> None:
    # Measured: an unknown appid answers 200 with success 15 and appid 0.
    unknown = {
        "response": {
            "store_items": [
                {"item_type": 0, "id": 999999999, "success": 15, "visible": False, "appid": 0}
            ]
        }
    }
    assert parse_store_assets(unknown, 999999999) is None
    assert parse_store_assets(item(5, None), 5) is None
    assert parse_store_assets(item(5, HASHED, success=2), 5) is None
    assert parse_store_assets({"response": {}}, 5) is None
    assert parse_store_assets([], 5) is None
    assert parse_store_assets(item(6, HASHED), 5) is None  # another app's item


def test_a_format_without_the_filename_placeholder_is_refused() -> None:
    no_placeholder = {"asset_url_format": "steam/apps/1/", "header": "h"}
    assert parse_store_assets(item(1, no_placeholder), 1) is None
