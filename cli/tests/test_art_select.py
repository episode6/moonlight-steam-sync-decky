"""Slot filenames, source order, the magic-byte sniff and the .part dance (spec 3.5/3.9)."""

from __future__ import annotations

import pytest

from moonlight_steam_sync.art import steamstore
from moonlight_steam_sync.art.http import NetworkError
from moonlight_steam_sync.art.resolve import Match
from moonlight_steam_sync.art.select import (
    HERO,
    ICON,
    LANDSCAPE,
    LOGO,
    PORTRAIT,
    SLOTS,
    Selector,
    existing_slot_file,
    slot_basename,
    sniff_extension,
)
from moonlight_steam_sync.art.sgdb import SgdbClient, asset_query
from moonlight_steam_sync.art.steamstore import SteamStoreClient
from tests.art_fixtures import (
    FIXTURE_DIR,
    FakeTransport,
    load_manifest,
    make_fetcher,
    store_url,
)

APPID = 2864321987

PORTRAIT_2X = store_url(1245620, "library_600x900_2x.jpg")


def make_selector(transport: FakeTransport | None = None, **kwargs):
    transport = transport or FakeTransport()
    fetcher = make_fetcher(transport)
    selector = Selector(
        fetcher=fetcher,
        sgdb=SgdbClient(api_key="fixture-key", fetcher=fetcher),
        store=SteamStoreClient(fetcher=fetcher),
        **kwargs,
    )
    return selector, transport


def test_slot_filenames_match_what_steam_reads() -> None:
    assert slot_basename(APPID, PORTRAIT) == f"{APPID}p"
    assert slot_basename(APPID, LANDSCAPE) == f"{APPID}"
    assert slot_basename(APPID, HERO) == f"{APPID}_hero"
    assert slot_basename(APPID, LOGO) == f"{APPID}_logo"
    assert slot_basename(APPID, ICON) == f"{APPID}_icon"
    assert [slot.key for slot in SLOTS] == ["portrait", "landscape", "hero", "logo", "icon"]


def test_sniff_only_accepts_png_and_jpeg() -> None:
    assert sniff_extension(b"\x89PNG\r\n\x1a\n....") == ".png"
    assert sniff_extension(b"\xff\xd8\xff\xe0") == ".jpg"
    assert sniff_extension((FIXTURE_DIR / "images" / "tiny.webp").read_bytes()) is None
    assert sniff_extension(b"<html>") is None
    assert sniff_extension(b"") is None


def test_existing_slot_file_finds_any_honoured_extension_and_ignores_parts(tmp_path) -> None:
    (tmp_path / f"{APPID}p.jpg").write_bytes(b"x")
    (tmp_path / f"{APPID}_hero.part").write_bytes(b"x")
    (tmp_path / f"{APPID}.json").write_text("{}")
    assert existing_slot_file(tmp_path, APPID, PORTRAIT).name == f"{APPID}p.jpg"
    assert existing_slot_file(tmp_path, APPID, HERO) is None
    # The optional logo-position JSON is not artwork and must not count as the
    # landscape slot.
    assert existing_slot_file(tmp_path, APPID, LANDSCAPE) is None


def test_the_landscape_slot_is_not_satisfied_by_the_portrait_file(tmp_path) -> None:
    (tmp_path / f"{APPID}p.png").write_bytes(b"x")
    assert existing_slot_file(tmp_path, APPID, LANDSCAPE) is None


def test_official_sources_are_tried_in_cdn_order(tmp_path) -> None:
    selector, transport = make_selector()
    match = Match(name="Elden Ring", steam_appid=1245620, sgdb_id=5297)
    fill = selector.fill(PORTRAIT, match, appid=APPID, grid_dir=tmp_path)
    assert fill.source == "official"
    # The store is asked which files it has, then its 2x capsule is taken.
    assert fill.url == PORTRAIT_2X
    assert transport.calls == [steamstore.get_items_url(1245620), PORTRAIT_2X]
    assert fill.path.name == f"{APPID}p.jpg"


def test_a_404_on_the_2x_portrait_falls_through_to_the_1x(tmp_path) -> None:
    selector, transport = make_selector()
    match = Match(name="Hades II", steam_appid=1145350, sgdb_id=5468)
    fill = selector.fill(PORTRAIT, match, appid=APPID, grid_dir=tmp_path)
    assert fill.url.endswith("library_600x900.jpg?t=1700000000")
    assert [c for c in transport.calls if "library_600x900" in c] == [
        store_url(1145350, "library_600x900_2x.jpg"),
        store_url(1145350, "library_600x900.jpg"),
    ]


BRAND_NEW = Match(name="Brand New Sequel", steam_appid=610200, how="steamstore:exact")
HASHED_HERO = store_url(610200, "cccc000000000000000000000000000000000003/library_hero.jpg")


def test_a_new_apps_art_is_fetched_from_the_hashed_paths_the_store_lists(tmp_path) -> None:
    """Steam serves an app published since mid-2025 only from paths with a
    hash per asset (measured 2026-10-31): the unhashed CDN URL is a 404 for
    it, so the store's own file list has to be asked and used."""
    selector, transport = make_selector()
    fill = selector.fill(HERO, BRAND_NEW, appid=APPID, grid_dir=tmp_path)
    assert fill.source == "official"
    assert fill.url == HASHED_HERO
    assert transport.calls == [steamstore.get_items_url(610200), HASHED_HERO]
    assert (tmp_path / f"{APPID}_hero.jpg").is_file()


def test_the_store_is_asked_once_per_title_and_its_icon_hash_is_used(tmp_path) -> None:
    selector, transport = make_selector()
    for slot in SLOTS:
        selector.fill(slot, BRAND_NEW, appid=APPID, grid_dir=tmp_path)
    get_items = [c for c in transport.calls if "GetItems" in c]
    assert get_items == [steamstore.get_items_url(610200)]
    assert not any("GetApps" in c for c in transport.calls)
    assert steamstore.icon_url(610200, "5a5a5a5a5a5a") in transport.calls
    # The logo is the one slot the store does not list: unhashed CDN (a 404
    # for a new app), and this title has no SteamGridDB id, so it stays open.
    assert sorted(p.name for p in tmp_path.iterdir()) == [
        f"{APPID}.jpg", f"{APPID}_hero.jpg", f"{APPID}_icon.jpg", f"{APPID}p.jpg",
    ]


def test_the_unhashed_cdn_and_getapps_serve_an_app_the_store_no_longer_lists(tmp_path) -> None:
    """``Delisted Relic``: GetItems answers ``success: 15``, a definite "not in
    the store", so the unhashed paths and the GetApps hash are tried next --
    and nothing is marked a failed lookup."""
    selector, transport = make_selector()
    match = Match(name="Delisted Relic", steam_appid=700700, sgdb_id=8600)
    fill = selector.fill(PORTRAIT, match, appid=APPID, grid_dir=tmp_path)
    assert fill.url == steamstore.portrait_urls(700700)[0]
    assert selector.last_attempt_failed is False
    icon = selector.fill(ICON, match, appid=APPID, grid_dir=tmp_path)
    assert icon.url == steamstore.icon_url(700700, "6b6b6b6b")
    assert [c for c in transport.calls if "GetItems" in c or "GetApps" in c] == [
        steamstore.get_items_url(700700),
        steamstore.get_apps_url(700700),
    ]


def test_a_failed_store_lookup_marks_every_slot_failed_and_is_not_retried(tmp_path) -> None:
    """A store outage must not turn into cached misses: each slot that would
    have asked the store is told the lookup failed, the unhashed paths are
    still tried, and the store is asked once for the run, not once per slot."""
    get_items = steamstore.get_items_url(610200)
    selector, transport = make_selector(FakeTransport(fail_with={get_items: NetworkError("down")}))
    assert selector.fill(HERO, BRAND_NEW, appid=APPID, grid_dir=tmp_path) is None
    assert selector.last_attempt_failed is True
    # The fetcher retries a network failure; the one lookup is those retries.
    asked = transport.calls.count(get_items)
    assert asked >= 1
    assert [c for c in transport.calls if c != get_items] == [steamstore.hero_urls(610200)[0]]
    assert selector.fill(LANDSCAPE, BRAND_NEW, appid=APPID, grid_dir=tmp_path) is None
    assert selector.last_attempt_failed is True
    assert transport.calls.count(get_items) == asked


def test_a_store_lookup_failure_does_not_stop_a_slot_the_unhashed_cdn_still_has(tmp_path) -> None:
    get_items = steamstore.get_items_url(700700)
    selector, _ = make_selector(FakeTransport(fail_with={get_items: NetworkError("down")}))
    match = Match(name="Delisted Relic", steam_appid=700700, sgdb_id=8600)
    fill = selector.fill(HERO, match, appid=APPID, grid_dir=tmp_path)
    assert fill is not None and fill.url == steamstore.hero_urls(700700)[0]


def test_community_assets_are_sorted_by_score_before_the_first_is_taken(tmp_path) -> None:
    selector, _ = make_selector()
    match = Match(name="Fan Made Adventure", sgdb_id=7001)
    fill = selector.fill(PORTRAIT, match, appid=APPID, grid_dir=tmp_path)
    assert fill.source == "community"
    # The fixture lists the score-42 asset first; the score-97 one must win.
    assert fill.url.endswith("fan-portrait-best.png")


def test_community_fallback_can_be_switched_off(tmp_path) -> None:
    selector, transport = make_selector(community_fallback=False)
    match = Match(name="Fan Made Adventure", sgdb_id=7001)
    assert selector.fill(PORTRAIT, match, appid=APPID, grid_dir=tmp_path) is None
    assert transport.calls == []


def test_bytes_that_are_not_png_or_jpeg_are_rejected_and_the_next_source_wins(
    tmp_path,
) -> None:
    selector, _ = make_selector()
    match = Match(name="Fan Made Adventure", sgdb_id=7001)
    fill = selector.fill(LOGO, match, appid=APPID, grid_dir=tmp_path)
    # The `official` logo is a .png URL serving WebP bytes; it must be dropped
    # and the `white` style used instead.
    assert fill.url.endswith("fan-logo-white.png")
    assert not (tmp_path / f"{APPID}_logo.part").exists()
    assert sorted(p.name for p in tmp_path.iterdir()) == [f"{APPID}_logo.png"]


CLQ = Match(name="Custom Logo Quest", steam_appid=512300, sgdb_id=8200)


def clq_logo_queries(transport: FakeTransport) -> list[str]:
    return [call for call in transport.calls if "/logos/game/8200" in call]


def test_a_custom_logo_beats_a_higher_scored_black_one(tmp_path) -> None:
    selector, transport = make_selector()
    fill = selector.fill(LOGO, CLQ, appid=APPID, grid_dir=tmp_path)
    assert fill.source == "community"
    # The `official` logo serves WebP bytes and there is no `white` one;
    # `black` (score 80) is drawn for light backgrounds, so `custom` (score
    # 30) is asked for first and the any-style query is never made.
    assert fill.url.endswith("clq-logo-custom.png")
    queries = clq_logo_queries(transport)
    assert len(queries) == 3
    assert "styles=official" in queries[0]
    assert "styles=white" in queries[1]
    assert "styles=custom" in queries[2]


def test_the_any_style_logo_query_skips_a_logo_already_tried(tmp_path) -> None:
    responses = load_manifest()
    custom = next(url for url in responses if "/logos/game/8200" in url and "custom" in url)
    white = next(url for url in responses if "/logos/game/8200" in url and "white" in url)
    responses[custom] = responses[white]  # an empty envelope
    selector, transport = make_selector(FakeTransport(responses=responses))
    fill = selector.fill(LOGO, CLQ, appid=APPID, grid_dir=tmp_path)
    # The any-style query lists the failed score-90 `official` logo first;
    # downloading it again would fail again and leave the slot empty.
    assert fill.url.endswith("clq-logo-black.png")
    queries = clq_logo_queries(transport)
    assert len(queries) == 4
    assert "styles" not in queries[3]
    assert "types=static" in queries[3]
    official = [url for url in selector.attempted if url.endswith("clq-logo-official.png")]
    assert len(official) == 1


def test_logo_queries_ask_for_png_only(tmp_path) -> None:
    # SteamGridDB answers 400 to a logos query whose `mimes` names
    # image/jpeg, which used to fail every community logo.
    selector, transport = make_selector()
    selector.fill(LOGO, CLQ, appid=APPID, grid_dir=tmp_path)
    logo_queries = [call for call in transport.calls if "/logos/game/" in call]
    assert logo_queries
    assert all(call.endswith("mimes=image/png") for call in logo_queries)


def test_the_client_defaults_mimes_per_kind_and_refuses_jpeg_logos() -> None:
    assert asset_query("logos")["mimes"] == "image/png"
    assert asset_query("icons", styles="official")["mimes"] == "image/png"
    assert asset_query("grids", dimensions="600x900")["mimes"] == "image/png,image/jpeg"
    assert asset_query("heroes")["mimes"] == "image/png,image/jpeg"
    with pytest.raises(ValueError):
        asset_query("logos", mimes="image/png,image/jpeg")


def test_the_any_style_logo_query_is_skipped_once_a_styled_one_fills_the_slot(
    tmp_path,
) -> None:
    selector, transport = make_selector()
    match = Match(name="Old Console Classic", steam_appid=400910, sgdb_id=8100)
    fill = selector.fill(LOGO, match, appid=APPID, grid_dir=tmp_path)
    assert fill.url.endswith("occ-logo.png")
    logo_queries = [call for call in transport.calls if "/logos/game/8100" in call]
    assert len(logo_queries) == 1
    assert "styles=official" in logo_queries[0]


def test_webp_is_never_requested(tmp_path) -> None:
    selector, transport = make_selector()
    match = Match(name="Fan Made Adventure", sgdb_id=7001)
    for slot in SLOTS:
        selector.fill(slot, match, appid=APPID, grid_dir=tmp_path)
    assert not any("webp" in call.lower() for call in transport.calls)
    assert not any(path.suffix == ".webp" for path in tmp_path.iterdir())


def test_requesting_webp_from_the_client_is_a_programming_error() -> None:
    selector, _ = make_selector()
    with pytest.raises(ValueError, match="WebP"):
        selector.sgdb.assets("grids", 7001, mimes="image/webp")


def test_an_exception_mid_download_leaves_only_a_part_file(tmp_path) -> None:
    selector, _ = make_selector(FakeTransport(truncate_after={PORTRAIT_2X: 1}))
    # A connection that dies mid-body is a structured NetworkError, not the
    # bare OSError that used to walk past every handler in the stack.
    with pytest.raises(NetworkError):
        selector.download(PORTRAIT_2X, tmp_path / f"{APPID}p")
    assert sorted(p.name for p in tmp_path.iterdir()) == [f"{APPID}p.part"]


def test_a_mid_download_drop_is_a_failed_attempt_not_a_crash(tmp_path) -> None:
    selector, _ = make_selector(FakeTransport(truncate_after={PORTRAIT_2X: 1}))
    match = Match(name="Elden Ring", steam_appid=1245620)
    # fill() survives it, flags the attempt as failed (so the slot is never
    # cached as a genuine miss) and falls through to the next source.
    assert selector.fill(PORTRAIT, match, appid=APPID, grid_dir=tmp_path) is None
    assert selector.last_attempt_failed is True
    assert sorted(p.name for p in tmp_path.iterdir()) == [f"{APPID}p.part"]


def test_force_replaces_a_slot_file_that_has_a_different_extension(tmp_path) -> None:
    stale = tmp_path / f"{APPID}p.png"
    stale.write_bytes(b"\x89PNG\r\n\x1a\nold")
    selector, _ = make_selector()
    match = Match(name="Elden Ring", steam_appid=1245620)
    fill = selector.fill(PORTRAIT, match, appid=APPID, grid_dir=tmp_path)
    assert fill.path.name == f"{APPID}p.jpg"
    # One file per slot: the old .png is gone, so Steam has no choice to make
    # and the next run cannot report the stale file as "kept".
    assert sorted(p.name for p in tmp_path.iterdir()) == [f"{APPID}p.jpg"]


def test_a_stale_part_is_overwritten_by_the_next_run(tmp_path) -> None:
    (tmp_path / f"{APPID}p.part").write_bytes(b"garbage from a killed run")
    selector, _ = make_selector()
    match = Match(name="Elden Ring", steam_appid=1245620)
    fill = selector.fill(PORTRAIT, match, appid=APPID, grid_dir=tmp_path)
    assert fill.path.name == f"{APPID}p.jpg"
    assert sorted(p.name for p in tmp_path.iterdir()) == [f"{APPID}p.jpg"]


def test_the_icon_slot_needs_the_icon_hash(tmp_path) -> None:
    selector, transport = make_selector()
    match = Match(name="Elden Ring", steam_appid=1245620)
    fill = selector.fill(ICON, match, appid=APPID, grid_dir=tmp_path)
    assert fill.source == "official"
    assert fill.url.endswith("/1c1c1c1c1c1c1c1c1c1c.jpg")
    # The hash comes with the store's asset list, so GetApps is not called.
    assert any("GetItems" in call for call in transport.calls)
    assert not any("GetApps" in call for call in transport.calls)


def test_landscape_falls_from_920x430_to_460x215(tmp_path) -> None:
    selector, transport = make_selector()
    match = Match(name="Fan Made Adventure", sgdb_id=7001)
    fill = selector.fill(LANDSCAPE, match, appid=APPID, grid_dir=tmp_path)
    assert fill.url.endswith("fan-landscape.png")
    queried = [c for c in transport.calls if "/grids/game/7001" in c]
    assert "dimensions=920x430" in queried[0]
    assert "dimensions=460x215" in queried[1]
