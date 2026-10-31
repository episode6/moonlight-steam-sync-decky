#!/usr/bin/env python3
"""Regenerate the SYNTHETIC artwork fixtures in this directory.

TODO(real-data): every file this script writes is invented. It is shaped from
the endpoint documentation in spec section 2.2 (SteamGridDB API v2 response
envelopes, asset object fields, style names) and the Steam CDN/store URLs
verified live on 2026-09-16, but no byte of it came off the wire. Replace it
with real captures by running::

    SGDB_API_KEY=... python3 scripts/record_fixtures.py

which hits the real SteamGridDB, Steam store and Steam CDN endpoints for the
same eleven titles and rewrites ``manifest.json`` plus ``responses/``. The
tests read the manifest, not these literals, so a real capture is a file
replacement and not a test rewrite. Keep this script around afterwards: it
documents what each title is *for*, and it is how the fixture set gets
extended when a new match case shows up on a device.

Every Steam title also has a ``GetItems`` answer, the store's own list of
its asset files (2026-10-31): an app published before mid-2025 lists plain
filenames (``library_600x900.jpg``), a newer one lists each behind its own
hash (``<40 hex>/library_capsule.jpg``) and is a 404 on the unhashed CDN
path; ``Brand New Sequel`` is the hashed one here, ``Delisted Relic`` the
app the store no longer lists at all.

The eleven titles exercise the cases spec PR-4 asks for (the seventh serves
PR-5, the eighth the any-style logo fallback, the ninth and tenth the store
fall-through for a weak SteamGridDB match, the eleventh the unhashed CDN
fallback):

1. ``Elden Ring``          -- exact verified SteamGridDB match, every slot official.
2. ``Hades II(tm)``        -- a title with a trademark glyph; also the 2x portrait
                              missing so the 1x official URL is used.
3. ``Fan Made Adventure``  -- a non-Steam game: community art only, score sorting,
                              a second-choice query, and an asset whose bytes are
                              WebP despite a ``.png`` URL (must be rejected).
4. ``Old Console Classic`` -- a Steam game with no ``logo.png`` on the CDN, so the
                              logo slot falls through to community art.
5. ``Totally Unknown Title``-- zero results anywhere: no match, negative cache, every
                              slot missing.
6. ``Rate Limited Game``   -- SteamGridDB and the store both answer 429 forever, so
                              the run hits the five-consecutive-429 hard stop.
7. ``Hollow Knight``       -- the adoptable SteamTinkerLaunch-era entry in
                              ``tests/fixtures/shortcuts_synthetic.vdf`` (PR-2), so the
                              ``sync`` end-to-end tests can adopt it and dress it
                              (every slot official, like Elden Ring).
8. ``Custom Logo Quest``   -- a Steam game with no ``logo.png`` on the CDN, an
                              ``official`` logo whose bytes are WebP and no
                              ``white`` one, so the ``custom`` query beats a
                              higher-scored ``black`` logo; with ``custom`` emptied
                              the any-style query must skip the failed ``official``
                              logo it lists first. Only its logo chain is recorded.
9. ``Brand New Sequel``    -- SteamGridDB knows only the franchise's first game, so
                              autocomplete is a fuzzy hit; the store has the sequel
                              exactly and must win (``steamstore:exact``). Its art
                              is on hashed store paths, every unhashed URL a 404.
10. ``Unlinked Launch``    -- a verified SteamGridDB entry with no Steam release
                              linked; the store's exact hit lends its appid
                              (``sgdb:exact-verified`` with the store's appid).
11. ``Delisted Relic``     -- an exact verified match for a Steam game the store no
                              longer lists (``GetItems`` answers ``success: 15``),
                              so the unhashed CDN paths and the ``GetApps`` icon
                              hash are the official sources.

Run from the repo root::

    python3 tests/fixtures/art/make_synthetic.py
"""

from __future__ import annotations

import json
import struct
import sys
import zlib
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parents[2]
sys.path.insert(0, str(REPO_ROOT / "src"))

from moonlight_steam_sync.art import steamstore  # noqa: E402
from moonlight_steam_sync.art.sgdb import asset_query  # noqa: E402

SGDB = "https://www.steamgriddb.com/api/v2"

TODO = (
    "SYNTHETIC FIXTURE -- invented, not captured. Replace with a real capture: "
    "SGDB_API_KEY=... python3 scripts/record_fixtures.py"
)


def sgdb_url(path: str, params: dict[str, str] | None = None) -> str:
    from urllib.parse import urlencode

    url = f"{SGDB}{path}"
    if params:
        url = f"{url}?{urlencode(params, safe='/,')}"
    return url


def search_url(term: str) -> str:
    from urllib.parse import quote

    return sgdb_url(f"/search/autocomplete/{quote(term, safe='')}")


def game_url(sgdb_id: int) -> str:
    return sgdb_url(f"/games/id/{sgdb_id}", {"platformdata": "steam"})


def game_by_steam_url(steam_appid: int) -> str:
    return sgdb_url(f"/games/steam/{steam_appid}")


def asset_url(kind: str, sgdb_id: int, **params: str) -> str:
    return sgdb_url(f"/{kind}/game/{sgdb_id}", asset_query(kind, **params))


def envelope(data: object) -> dict[str, object]:
    return {"_TODO": TODO, "success": True, "data": data}


#: The ``?t=`` stamp on every synthetic store asset URL (``tests/art_fixtures.py``
#: has the same number as ``STORE_STAMP``; the two must agree).
STORE_STAMP = 1700000000

#: What ``GetItems`` lists for an app published before the move to hashed
#: paths: the same filenames the unhashed CDN serves.
UNHASHED_FILES = {
    "library_capsule_2x": "library_600x900_2x.jpg",
    "library_capsule": "library_600x900.jpg",
    "header": "header.jpg",
    "library_hero": "library_hero.jpg",
}


def store_url(appid: int, filename: str) -> str:
    """The URL ``GetItems``' ``asset_url_format`` gives ``filename`` for ``appid``."""
    return steamstore.store_asset_url(
        f"steam/apps/{appid}/${{FILENAME}}?t={STORE_STAMP}", filename
    )


def store_items(
    appid: int, name: str, files: dict[str, str] | None, icon: str | None
) -> dict[str, object]:
    """A ``GetItems`` body for one app; ``files=None`` is the store's answer for an
    appid it does not list (``success: 15``, ``appid: 0``)."""
    if files is None:
        item: dict[str, object] = {
            "item_type": 0, "id": appid, "success": 15, "visible": False,
            "name": "", "store_url_path": "app/0/", "store_url_slug": "", "appid": 0,
        }
    else:
        assets: dict[str, object] = {
            "asset_url_format": f"steam/apps/{appid}/${{FILENAME}}?t={STORE_STAMP}",
            **files,
            "last_modified": STORE_STAMP,
        }
        if icon:
            assets["community_icon"] = icon
        item = {
            "item_type": 0, "id": appid, "success": 1, "visible": True, "name": name,
            "store_url_path": f"app/{appid}/", "appid": appid, "assets": assets,
        }
    return {"_TODO": TODO, "response": {"store_items": [item]}}


def game(sgdb_id: int, name: str, steam_appid: int | None) -> dict[str, object]:
    payload: dict[str, object] = {
        "id": sgdb_id,
        "name": name,
        "types": ["steam"] if steam_appid else ["other"],
        "verified": True,
        "release_date": 1600000000,
    }
    if steam_appid is not None:
        payload["external_platform_data"] = {
            "steam": [{"id": str(steam_appid), "metadata": {"clienticon": "deadbeef"}}]
        }
    return payload


def asset(asset_id: int, url: str, *, style: str, score: int, mime: str) -> dict[str, object]:
    return {
        "id": asset_id,
        "score": score,
        "style": style,
        "width": 600,
        "height": 900,
        "mime": mime,
        "nsfw": False,
        "humor": False,
        "epilepsy": False,
        "language": "en",
        "url": url,
        "thumb": url.replace("/full/", "/thumb/"),
        "upvotes": score,
        "downvotes": 0,
        "author": {"name": "synthetic-uploader"},
    }


# --------------------------------------------------------------------------
# tiny image bodies. Only the magic bytes matter to the selector, so these are
# the smallest things that carry the right ones.
# --------------------------------------------------------------------------


def tiny_png() -> bytes:
    def chunk(tag: bytes, payload: bytes) -> bytes:
        return (
            struct.pack(">I", len(payload))
            + tag
            + payload
            + struct.pack(">I", zlib.crc32(tag + payload) & 0xFFFFFFFF)
        )

    header = struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0)
    body = zlib.compress(b"\x00\xff\xff\xff")
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", header)
        + chunk(b"IDAT", body)
        + chunk(b"IEND", b"")
    )


def tiny_jpeg() -> bytes:
    return (
        b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00"
        b"\xff\xdb\x00\x43\x00" + bytes(64) + b"\xff\xd9"
    )


def tiny_webp() -> bytes:
    payload = b"VP8 " + struct.pack("<I", 4) + b"\x00\x00\x00\x00"
    return b"RIFF" + struct.pack("<I", len(payload) + 4) + b"WEBP" + payload


def main() -> int:
    responses_dir = HERE / "responses"
    images_dir = HERE / "images"
    responses_dir.mkdir(exist_ok=True)
    images_dir.mkdir(exist_ok=True)

    (images_dir / "tiny.png").write_bytes(tiny_png())
    (images_dir / "tiny.jpg").write_bytes(tiny_jpeg())
    (images_dir / "tiny.webp").write_bytes(tiny_webp())
    (images_dir / "README.txt").write_text(
        "SYNTHETIC 1x1 images. Only the magic bytes are load-bearing: the\n"
        "selector sniffs PNG/JPEG and rejects anything else (tiny.webp is here\n"
        "to prove WebP never reaches grid/). Real captures do not need to\n"
        "replace these.\n",
        encoding="utf-8",
    )

    responses: dict[str, dict[str, object]] = {}

    def json_response(url: str, name: str, payload: object, status: int = 200) -> None:
        path = responses_dir / f"{name}.json"
        path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
        responses[url] = {
            "status": status,
            "body": f"responses/{name}.json",
            "content_type": "application/json",
        }

    def image_response(url: str, image: str) -> None:
        responses[url] = {
            "status": 200,
            "body": f"images/{image}",
            "content_type": "image/png" if image.endswith(".png") else "image/jpeg",
        }

    def rate_limited(url: str) -> None:
        responses[url] = {"status": 429, "body": None, "headers": {"Retry-After": "1"}}

    # -- 1. Elden Ring: exact verified match, all five slots official --------
    json_response(
        search_url("Elden Ring"),
        "sgdb-search-elden-ring",
        envelope(
            [
                game(9999, "Elden Ring Nightreign", 2622380) | {"verified": False},
                game(5297, "Elden Ring", 1245620),
            ]
        ),
    )
    json_response(game_url(5297), "sgdb-game-5297", envelope(game(5297, "Elden Ring", 1245620)))
    json_response(
        steamstore.get_items_url(1245620),
        "steam-getitems-1245620",
        store_items(1245620, "ELDEN RING", UNHASHED_FILES, "1c1c1c1c1c1c1c1c1c1c"),
    )
    image_response(store_url(1245620, "library_600x900_2x.jpg"), "tiny.jpg")
    image_response(store_url(1245620, "header.jpg"), "tiny.jpg")
    image_response(store_url(1245620, "library_hero.jpg"), "tiny.jpg")
    image_response(steamstore.logo_urls(1245620)[0], "tiny.png")
    # The icon hash comes with GetItems; GetApps is recorded for the fallback.
    json_response(
        steamstore.get_apps_url(1245620),
        "steam-getapps-1245620",
        {
            "_TODO": TODO,
            "response": {
                "apps": [
                    {"appid": 1245620, "name": "ELDEN RING", "icon": "1c1c1c1c1c1c1c1c1c1c"}
                ]
            },
        },
    )
    image_response(steamstore.icon_url(1245620, "1c1c1c1c1c1c1c1c1c1c"), "tiny.jpg")

    # -- 2. Hades II(tm): trademark glyph; 2x portrait missing --------------
    json_response(
        search_url("Hades II™"),
        "sgdb-search-hades-ii",
        envelope([game(5468, "Hades II", 1145350)]),
    )
    json_response(game_url(5468), "sgdb-game-5468", envelope(game(5468, "Hades II", 1145350)))
    json_response(
        steamstore.get_items_url(1145350),
        "steam-getitems-1145350",
        store_items(1145350, "Hades II", UNHASHED_FILES, "2d2d2d2d2d2d"),
    )
    # The 2x capsule the store lists is deliberately absent -> 404 -> 1x wins.
    image_response(store_url(1145350, "library_600x900.jpg"), "tiny.jpg")
    image_response(store_url(1145350, "header.jpg"), "tiny.jpg")
    image_response(store_url(1145350, "library_hero.jpg"), "tiny.jpg")
    image_response(steamstore.logo_urls(1145350)[0], "tiny.png")
    json_response(
        steamstore.get_apps_url(1145350),
        "steam-getapps-1145350",
        {
            "_TODO": TODO,
            "response": {"apps": [{"appid": 1145350, "name": "Hades II", "icon": "2d2d2d2d2d2d"}]},
        },
    )
    image_response(steamstore.icon_url(1145350, "2d2d2d2d2d2d"), "tiny.jpg")

    # -- 3. Fan Made Adventure: community only ------------------------------
    json_response(
        search_url("Fan Made Adventure"),
        "sgdb-search-fan-made-adventure",
        envelope([game(7001, "Fan Made Adventure", None) | {"verified": False}]),
    )
    json_response(
        game_url(7001), "sgdb-game-7001", envelope(game(7001, "Fan Made Adventure", None))
    )
    community = "https://cdn2.steamgriddb.com/file/sgdb-cdn/grid/full"
    json_response(
        asset_url("grids", 7001, dimensions="600x900", styles="alternate"),
        "sgdb-grids-7001-600x900",
        envelope(
            [
                # Deliberately NOT in score order: the client sorts.
                asset(101, f"{community}/fan-portrait-low.png", style="alternate", score=42,
                      mime="image/png"),
                asset(102, f"{community}/fan-portrait-best.png", style="alternate", score=97,
                      mime="image/png"),
            ]
        ),
    )
    image_response(f"{community}/fan-portrait-best.png", "tiny.png")
    json_response(
        asset_url("grids", 7001, dimensions="920x430", styles="alternate"),
        "sgdb-grids-7001-920x430-empty",
        envelope([]),
    )
    json_response(
        asset_url("grids", 7001, dimensions="460x215", styles="alternate"),
        "sgdb-grids-7001-460x215",
        envelope(
            [asset(103, f"{community}/fan-landscape.png", style="alternate", score=70,
                   mime="image/png")]
        ),
    )
    image_response(f"{community}/fan-landscape.png", "tiny.png")
    json_response(
        asset_url("heroes", 7001, dimensions="1920x620", styles="alternate"),
        "sgdb-heroes-7001-1920x620",
        envelope(
            [asset(104, f"{community}/fan-hero.jpg", style="alternate", score=55,
                   mime="image/jpeg")]
        ),
    )
    image_response(f"{community}/fan-hero.jpg", "tiny.jpg")
    json_response(
        asset_url("logos", 7001, styles="official"),
        "sgdb-logos-7001-official",
        envelope(
            # A .png URL whose bytes are actually WebP: the magic-byte sniff
            # must reject it and fall through to the `white` query.
            [asset(105, f"{community}/fan-logo-official.png", style="official", score=90,
                   mime="image/png")]
        ),
    )
    responses[f"{community}/fan-logo-official.png"] = {
        "status": 200,
        "body": "images/tiny.webp",
        "content_type": "image/png",
    }
    json_response(
        asset_url("logos", 7001, styles="white"),
        "sgdb-logos-7001-white",
        envelope(
            [asset(106, f"{community}/fan-logo-white.png", style="white", score=60,
                   mime="image/png")]
        ),
    )
    image_response(f"{community}/fan-logo-white.png", "tiny.png")
    json_response(
        asset_url("icons", 7001, styles="official"),
        "sgdb-icons-7001-official",
        envelope(
            [asset(107, f"{community}/fan-icon.png", style="official", score=80,
                   mime="image/png")]
        ),
    )
    image_response(f"{community}/fan-icon.png", "tiny.png")

    # A non-Steam game's exact SteamGridDB match is a weak one (no Steam
    # release), so the resolver asks the store too; a real one finds nothing.
    json_response(
        steamstore.store_search_url("Fan Made Adventure"),
        "steam-storesearch-fan-made-adventure",
        {"_TODO": TODO, "total": 0, "items": []},
    )

    # -- 4. Old Console Classic: Steam game, no logo on the CDN -------------
    json_response(
        search_url("Old Console Classic"),
        "sgdb-search-old-console-classic",
        envelope([game(8100, "Old Console Classic", 400910)]),
    )
    json_response(
        game_url(8100), "sgdb-game-8100", envelope(game(8100, "Old Console Classic", 400910))
    )
    json_response(
        steamstore.get_items_url(400910),
        "steam-getitems-400910",
        store_items(400910, "Old Console Classic", UNHASHED_FILES, "3e3e3e3e"),
    )
    image_response(store_url(400910, "library_600x900_2x.jpg"), "tiny.jpg")
    image_response(store_url(400910, "header.jpg"), "tiny.jpg")
    image_response(store_url(400910, "library_hero.jpg"), "tiny.jpg")
    # steamstore.logo_urls(400910)[0] is absent -> 404 -> community logo wins.
    json_response(
        asset_url("logos", 8100, styles="official"),
        "sgdb-logos-8100-official",
        envelope(
            [asset(108, f"{community}/occ-logo.png", style="official", score=75,
                   mime="image/png")]
        ),
    )
    image_response(f"{community}/occ-logo.png", "tiny.png")
    json_response(
        steamstore.get_apps_url(400910),
        "steam-getapps-400910",
        {
            "_TODO": TODO,
            "response": {
                "apps": [{"appid": 400910, "name": "Old Console Classic", "icon": "3e3e3e3e"}]
            },
        },
    )
    image_response(steamstore.icon_url(400910, "3e3e3e3e"), "tiny.jpg")

    # -- 5. Totally Unknown Title: zero results anywhere --------------------
    json_response(
        search_url("Totally Unknown Title"), "sgdb-search-unknown", envelope([])
    )
    json_response(
        steamstore.store_search_url("Totally Unknown Title"),
        "steam-storesearch-unknown",
        {"_TODO": TODO, "total": 0, "items": []},
    )

    # -- 6. Rate Limited Game: 429 forever ----------------------------------
    rate_limited(search_url("Rate Limited Game"))
    rate_limited(steamstore.store_search_url("Rate Limited Game"))

    # -- 7. Hollow Knight: the PR-2 fixture's adoptable entry, all official --
    json_response(
        search_url("Hollow Knight"),
        "sgdb-search-hollow-knight",
        envelope([game(5241, "Hollow Knight", 367520)]),
    )
    json_response(game_url(5241), "sgdb-game-5241", envelope(game(5241, "Hollow Knight", 367520)))
    json_response(
        steamstore.get_items_url(367520),
        "steam-getitems-367520",
        store_items(367520, "Hollow Knight", UNHASHED_FILES, "4f4f4f4f"),
    )
    image_response(store_url(367520, "library_600x900_2x.jpg"), "tiny.jpg")
    image_response(store_url(367520, "header.jpg"), "tiny.jpg")
    image_response(store_url(367520, "library_hero.jpg"), "tiny.jpg")
    image_response(steamstore.logo_urls(367520)[0], "tiny.png")
    json_response(
        steamstore.get_apps_url(367520),
        "steam-getapps-367520",
        {
            "_TODO": TODO,
            "response": {"apps": [{"appid": 367520, "name": "Hollow Knight", "icon": "4f4f4f4f"}]},
        },
    )
    image_response(steamstore.icon_url(367520, "4f4f4f4f"), "tiny.jpg")

    # -- 8. Custom Logo Quest: no usable official / white logo ---------------
    json_response(
        search_url("Custom Logo Quest"),
        "sgdb-search-custom-logo-quest",
        envelope([game(8200, "Custom Logo Quest", 512300)]),
    )
    json_response(
        game_url(8200), "sgdb-game-8200", envelope(game(8200, "Custom Logo Quest", 512300))
    )
    json_response(
        steamstore.get_items_url(512300),
        "steam-getitems-512300",
        store_items(512300, "Custom Logo Quest", UNHASHED_FILES, None),
    )
    # None of the listed files is recorded (this title is about its logo).
    # steamstore.logo_urls(512300)[0] is absent -> 404; the one `official`
    # logo is a .png URL serving WebP bytes, there is no `white` one, so the
    # `custom` query wins over the higher-scored `black` logo.
    official_logo = asset(109, f"{community}/clq-logo-official.png", style="official",
                          score=90, mime="image/png")
    custom_logo = asset(110, f"{community}/clq-logo-custom.png", style="custom", score=30,
                        mime="image/png")
    black_logo = asset(111, f"{community}/clq-logo-black.png", style="black", score=80,
                       mime="image/png")
    json_response(
        asset_url("logos", 8200, styles="official"),
        "sgdb-logos-8200-official",
        envelope([official_logo]),
    )
    responses[f"{community}/clq-logo-official.png"] = {
        "status": 200,
        "body": "images/tiny.webp",
        "content_type": "image/png",
    }
    json_response(
        asset_url("logos", 8200, styles="white"),
        "sgdb-logos-8200-white",
        envelope([]),
    )
    json_response(
        asset_url("logos", 8200, styles="custom"),
        "sgdb-logos-8200-custom",
        envelope([custom_logo]),
    )
    # Every style, as SteamGridDB lists them with no `styles`: the failed
    # `official` logo on top, which the selector must skip for `black`. Only
    # reached by a test that empties the `custom` query.
    json_response(
        asset_url("logos", 8200),
        "sgdb-logos-8200-any",
        # Deliberately NOT in score order: the client sorts.
        envelope([custom_logo, black_logo, official_logo]),
    )
    image_response(f"{community}/clq-logo-custom.png", "tiny.png")
    image_response(f"{community}/clq-logo-black.png", "tiny.png")

    # -- 9. Brand New Sequel: SteamGridDB has only the franchise's first game,
    #       so autocomplete fuzzy-matches it; the store has the sequel exactly.
    json_response(
        search_url("Brand New Sequel"),
        "sgdb-search-brand-new-sequel",
        envelope([game(8400, "Brand New", 610100)]),
    )
    json_response(game_url(8400), "sgdb-game-8400", envelope(game(8400, "Brand New", 610100)))
    json_response(
        steamstore.store_search_url("Brand New Sequel"),
        "steam-storesearch-brand-new-sequel",
        {
            "_TODO": TODO,
            "total": 2,
            "items": [
                {"id": 610200, "name": "Brand New Sequel", "type": "app"},
                {"id": 610210, "name": "Brand New Sequel Soundtrack", "type": "app"},
            ],
        },
    )
    # A game published after Steam moved to hashed asset paths: the store
    # lists each file behind its own hash, with the newer filenames, and
    # the unhashed steamstore.*_urls(610200) are all 404 (not recorded).
    hashed_files = {
        "library_capsule_2x": "aaaa000000000000000000000000000000000001/library_capsule_2x.jpg",
        "library_capsule": "aaaa000000000000000000000000000000000001/library_capsule.jpg",
        "header": "bbbb000000000000000000000000000000000002/header.jpg",
        "library_hero": "cccc000000000000000000000000000000000003/library_hero.jpg",
    }
    json_response(
        steamstore.get_items_url(610200),
        "steam-getitems-610200",
        store_items(610200, "Brand New Sequel", hashed_files, "5a5a5a5a5a5a"),
    )
    image_response(store_url(610200, hashed_files["library_capsule_2x"]), "tiny.jpg")
    image_response(store_url(610200, hashed_files["header"]), "tiny.jpg")
    image_response(store_url(610200, hashed_files["library_hero"]), "tiny.jpg")
    image_response(steamstore.icon_url(610200, "5a5a5a5a5a5a"), "tiny.jpg")

    # -- 10. Unlinked Launch: a verified SteamGridDB entry nobody has linked to
    #        Steam yet; the store has the game exactly.
    json_response(
        search_url("Unlinked Launch"),
        "sgdb-search-unlinked-launch",
        envelope([game(8500, "Unlinked Launch", None)]),
    )
    json_response(game_url(8500), "sgdb-game-8500", envelope(game(8500, "Unlinked Launch", None)))
    json_response(
        steamstore.store_search_url("Unlinked Launch"),
        "steam-storesearch-unlinked-launch",
        {
            "_TODO": TODO,
            "total": 1,
            "items": [{"id": 620300, "name": "Unlinked Launch", "type": "app"}],
        },
    )
    json_response(
        steamstore.get_items_url(620300),
        "steam-getitems-620300",
        store_items(620300, "Unlinked Launch", UNHASHED_FILES, None),
    )

    # -- 11. Delisted Relic: a Steam game the store no longer lists, so
    #        GetItems has nothing and the unhashed CDN paths plus the GetApps
    #        icon hash are the official sources.
    json_response(
        search_url("Delisted Relic"),
        "sgdb-search-delisted-relic",
        envelope([game(8600, "Delisted Relic", 700700)]),
    )
    json_response(game_url(8600), "sgdb-game-8600", envelope(game(8600, "Delisted Relic", 700700)))
    json_response(
        steamstore.get_items_url(700700),
        "steam-getitems-700700",
        store_items(700700, "Delisted Relic", None, None),
    )
    image_response(steamstore.portrait_urls(700700)[0], "tiny.jpg")
    image_response(steamstore.landscape_urls(700700)[0], "tiny.jpg")
    image_response(steamstore.hero_urls(700700)[0], "tiny.jpg")
    image_response(steamstore.logo_urls(700700)[0], "tiny.png")
    json_response(
        steamstore.get_apps_url(700700),
        "steam-getapps-700700",
        {
            "_TODO": TODO,
            "response": {"apps": [{"appid": 700700, "name": "Delisted Relic", "icon": "6b6b6b6b"}]},
        },
    )
    image_response(steamstore.icon_url(700700, "6b6b6b6b"), "tiny.jpg")

    # -- the owned-name match (sync --owned-apps, 2026-10-29): a title that is
    #    an owned game's name skips the searches and asks SteamGridDB only for
    #    the id behind the appid. Elden Ring has one; Brand New Sequel (a game
    #    SteamGridDB does not have yet) and Unlinked Launch (an entry not
    #    linked to Steam) answer 404, which is simply their absence here.
    json_response(
        game_by_steam_url(1245620),
        "sgdb-game-by-steam-1245620",
        envelope(game(5297, "Elden Ring", 1245620)),
    )

    manifest = {
        "_TODO": TODO,
        "_generated_by": "tests/fixtures/art/make_synthetic.py",
        "_note": (
            "url -> {status, body (a path in this directory, or null), content_type, "
            "headers}. Any URL not listed answers 404, which is what the Steam CDN "
            "does for an asset a game does not have."
        ),
        "responses": dict(sorted(responses.items())),
    }
    (HERE / "manifest.json").write_text(
        json.dumps(manifest, indent=2) + "\n", encoding="utf-8"
    )
    print(f"wrote {len(responses)} responses to {HERE}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
