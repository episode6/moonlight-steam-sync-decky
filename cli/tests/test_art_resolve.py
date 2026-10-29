"""Title resolution and the match cache (spec 3.5 step A, spec 3.9 item 2)."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

import pytest

from moonlight_steam_sync.art.http import NetworkError
from moonlight_steam_sync.art.resolve import (
    NEGATIVE_TTL,
    Match,
    MatchCache,
    Resolver,
    normalise,
    normalise_strict,
    pick,
)
from moonlight_steam_sync.art.sgdb import SgdbClient, steam_appid_from_game
from moonlight_steam_sync.art.steamstore import SteamStoreClient, store_search_url
from tests.art_fixtures import FakeTransport, make_fetcher


def build(tmp_path, *, api_key="fixture-key", **resolver_kwargs):
    transport = FakeTransport()
    fetcher = make_fetcher(transport)
    cache = MatchCache(tmp_path / "matches.json")
    resolver = Resolver(
        cache=cache,
        sgdb=SgdbClient(api_key=api_key, fetcher=fetcher),
        store=SteamStoreClient(fetcher=fetcher),
        **resolver_kwargs,
    )
    return resolver, transport, cache


# -- normalisation and pick rules -----------------------------------------


def test_normalise_strips_trademarks_case_punctuation_and_a_trailing_year() -> None:
    assert normalise("Hades II™") == "hades ii"
    assert normalise("ELDEN RING®") == "elden ring"
    assert normalise("Half-Life: Alyx") == "half life alyx"
    assert normalise("Doom (1993)") == "doom"
    assert normalise("  Spaced   Out  ") == "spaced out"
    # A year that is part of the title, not a suffix, survives.
    assert normalise("F1 2019 Season") == "f1 2019 season"


def test_pick_prefers_an_exact_verified_match_over_an_earlier_unverified_one() -> None:
    results = [
        {"id": 1, "name": "Elden Ring", "verified": False},
        {"id": 2, "name": "Elden Ring", "verified": True},
    ]
    chosen, how = pick(results, "Elden Ring")
    assert (chosen["id"], how) == (2, "exact-verified")


def test_pick_falls_back_to_exact_then_prefix_then_nothing() -> None:
    exact, how = pick([{"id": 1, "name": "Fan Made Adventure"}], "fan made adventure")
    assert (exact["id"], how) == (1, "exact")

    fuzzy, how = pick([{"id": 3, "name": "Portal 2: Community Edition"}], "Portal 2")
    assert (fuzzy["id"], how) == (3, "fuzzy")

    nothing, how = pick([{"id": 4, "name": "Something Else"}], "Portal 2")
    assert (nothing, how) == (None, "none")


def test_pick_ignores_verified_for_the_steam_store() -> None:
    chosen, how = pick(
        [{"id": 620, "name": "Portal 2"}], "Portal 2", prefer_verified=False
    )
    assert (chosen["id"], how) == (620, "exact")


def test_steam_appid_from_game_handles_a_missing_steam_release() -> None:
    assert steam_appid_from_game({"external_platform_data": {}}) is None
    assert (
        steam_appid_from_game({"external_platform_data": {"steam": [{"id": "1245620"}]}})
        == 1245620
    )


# -- resolution ------------------------------------------------------------


def test_exact_verified_sgdb_match_carries_the_steam_appid(tmp_path) -> None:
    resolver, transport, _ = build(tmp_path)
    match = resolver.resolve("Elden Ring")
    assert (match.how, match.sgdb_id, match.steam_appid) == ("sgdb:exact-verified", 5297, 1245620)
    assert [c for c in transport.calls if "autocomplete" in c]


def test_a_trademark_glyph_does_not_prevent_an_exact_match(tmp_path) -> None:
    resolver, _, _ = build(tmp_path)
    match = resolver.resolve("Hades II™")
    assert (match.how, match.steam_appid) == ("sgdb:exact-verified", 1145350)


def test_a_non_steam_game_resolves_with_no_steam_appid(tmp_path) -> None:
    resolver, _, _ = build(tmp_path)
    match = resolver.resolve("Fan Made Adventure")
    assert match.sgdb_id == 7001
    assert match.steam_appid is None
    assert match.how == "sgdb:exact"


def test_a_non_steam_game_asks_the_store_too_and_keeps_its_sgdb_match(tmp_path) -> None:
    # An exact SteamGridDB match with no Steam release is a weak one: the
    # store is asked, finds nothing, and the SteamGridDB match stands, cached.
    resolver, transport, cache = build(tmp_path)
    match = resolver.resolve("Fan Made Adventure")
    assert any("storesearch" in call for call in transport.calls)
    assert (match.how, match.sgdb_id, match.steam_appid) == ("sgdb:exact", 7001, None)
    assert match.transient is False
    assert "Fan Made Adventure" in cache


# -- a weak SteamGridDB answer falls through to the store (2026-10-29) -----

def test_an_exact_store_hit_replaces_a_fuzzy_sgdb_match(tmp_path) -> None:
    # SteamGridDB knows only "Brand New" (the franchise's first game), so
    # autocomplete is a prefix hit on a different game; the store has the
    # sequel itself, and that is the match -- with the wrong sgdb id dropped.
    resolver, transport, cache = build(tmp_path)
    match = resolver.resolve("Brand New Sequel")
    assert (match.how, match.steam_appid, match.sgdb_id) == ("steamstore:exact", 610200, None)
    assert match.matched_name == "Brand New Sequel"
    assert store_search_url("Brand New Sequel") in transport.calls
    assert cache.get("Brand New Sequel") == match


def test_an_exact_store_hit_lends_its_appid_to_an_unlinked_sgdb_match(tmp_path) -> None:
    # A verified SteamGridDB entry nobody has linked to Steam yet: the store's
    # exact hit supplies the appid, the SteamGridDB id stays for community
    # art, and `how` stays an exact SteamGridDB match (a `stream` kind).
    resolver, _, cache = build(tmp_path)
    match = resolver.resolve("Unlinked Launch")
    assert (match.how, match.steam_appid, match.sgdb_id) == ("sgdb:exact-verified", 620300, 8500)
    assert cache.get("Unlinked Launch") == match


@pytest.mark.parametrize("body", ["steam-storesearch-unknown", "steam-storesearch-soundtrack"])
def test_a_non_exact_store_answer_leaves_a_fuzzy_sgdb_match_alone(tmp_path, body) -> None:
    # An empty store answer, and one that is itself only a fuzzy hit (the
    # sequel's soundtrack): neither firms the match up, so the fuzzy
    # SteamGridDB pick stands and is cached, as before this fall-through.
    resolver, transport, cache = build(tmp_path)
    url = store_search_url("Brand New Sequel")
    transport.responses = dict(transport.responses)
    if body == "steam-storesearch-soundtrack":
        (tmp_path / "soundtrack.json").write_text(
            json.dumps(
                {"total": 1, "items": [{"id": 610210, "name": "Brand New Sequel Soundtrack"}]}
            )
        )
        transport.responses[url] = {
            "status": 200,
            "body": str(tmp_path / "soundtrack.json"),
            "content_type": "application/json",
        }
    else:
        transport.responses[url] = {
            "status": 200,
            "body": "responses/steam-storesearch-unknown.json",
            "content_type": "application/json",
        }
    match = resolver.resolve("Brand New Sequel")
    assert (match.how, match.steam_appid, match.sgdb_id) == ("sgdb:fuzzy", 610100, 8400)
    assert match.transient is False
    assert "Brand New Sequel" in cache


def test_a_failed_store_lookup_drops_a_fuzzy_sgdb_match_for_this_run(tmp_path) -> None:
    # A fuzzy pick is a different game: used for this run it would fetch
    # that game's art, which the next run's kind change would rename onto
    # the right one. So it is dropped, uncached, and the next run asks again.
    resolver, transport, cache = build(tmp_path)
    url = store_search_url("Brand New Sequel")
    transport.fail_with[url] = NetworkError("down")
    match = resolver.resolve("Brand New Sequel")
    assert (match.how, match.found, match.transient) == ("none", False, True)
    assert "Brand New Sequel" not in cache
    del transport.fail_with[url]
    again = resolver.resolve("Brand New Sequel")
    assert (again.how, again.steam_appid) == ("steamstore:exact", 610200)
    assert "Brand New Sequel" in cache


def test_a_failed_steam_release_lookup_is_not_cached_as_no_release(tmp_path) -> None:
    # games/id fails and the store has no exact hit: "no Steam release" is
    # unanswered, not known, so the exact match is kept for this run only.
    resolver, transport, cache = build(tmp_path)
    game_url = "https://www.steamgriddb.com/api/v2/games/id/8500?platformdata=steam"
    transport.fail_with[game_url] = NetworkError("down")
    # The store answers 404 (its URL dropped from the manifest): a failed
    # lookup too, without a second run of retries toward the hard stop.
    transport.responses = dict(transport.responses)
    del transport.responses[store_search_url("Unlinked Launch")]
    match = resolver.resolve("Unlinked Launch")
    assert (match.how, match.sgdb_id, match.steam_appid) == ("sgdb:exact-verified", 8500, None)
    assert match.transient is True
    assert "Unlinked Launch" not in cache
    assert any("steam release lookup failed" in line for line in match.explain)


def test_the_stores_exact_hit_rescues_a_failed_steam_release_lookup(tmp_path) -> None:
    resolver, transport, cache = build(tmp_path)
    game_url = "https://www.steamgriddb.com/api/v2/games/id/8500?platformdata=steam"
    transport.fail_with[game_url] = NetworkError("down")
    match = resolver.resolve("Unlinked Launch")
    assert (match.how, match.sgdb_id, match.steam_appid) == ("sgdb:exact-verified", 8500, 620300)
    assert match.transient is False
    assert cache.get("Unlinked Launch") == match


def test_a_failed_store_lookup_keeps_the_weak_sgdb_match_for_this_run_only(tmp_path) -> None:
    resolver, transport, cache = build(tmp_path)
    url = store_search_url("Unlinked Launch")
    transport.fail_with[url] = NetworkError("down")
    match = resolver.resolve("Unlinked Launch")
    assert (match.how, match.steam_appid, match.sgdb_id) == ("sgdb:exact-verified", None, 8500)
    assert match.transient is True
    assert "Unlinked Launch" not in cache
    # The next run asks again and gets the store's answer.
    del transport.fail_with[url]
    again = resolver.resolve("Unlinked Launch")
    assert again.steam_appid == 620300
    assert "Unlinked Launch" in cache


# -- the owned-name match (sync --owned-apps, 2026-10-29) ------------------

OWNED = {1245620: "ELDEN RING", 610200: "Brand New Sequel", 2280: "DOOM (1993)"}


def test_normalise_strict_keeps_a_trailing_year() -> None:
    assert normalise_strict("DOOM (1993)") == "doom 1993"
    assert normalise("DOOM (1993)") == "doom"
    assert normalise_strict("Hades II™") == "hades ii"


def test_an_owned_name_is_matched_without_a_search(tmp_path) -> None:
    resolver, transport, cache = build(tmp_path, owned=OWNED)
    match = resolver.resolve("Brand New Sequel")
    assert (match.how, match.steam_appid, match.sgdb_id) == ("owned:exact", 610200, None)
    assert match.matched_name == "Brand New Sequel"
    assert not any("autocomplete" in c or "storesearch" in c for c in transport.calls)
    # SteamGridDB's 404 for the appid is a definite answer: cached, no retry.
    assert cache.get("Brand New Sequel") == match
    transport.calls.clear()
    assert resolver.resolve("Brand New Sequel").how == "owned:exact"
    assert transport.calls == []


def test_an_owned_name_match_takes_its_sgdb_id_from_the_appid(tmp_path) -> None:
    resolver, transport, _ = build(tmp_path, owned=OWNED)
    match = resolver.resolve("elden ring")
    assert (match.how, match.steam_appid, match.sgdb_id) == ("owned:exact", 1245620, 5297)
    assert transport.calls == ["https://www.steamgriddb.com/api/v2/games/steam/1245620"]


def test_an_owned_name_match_without_a_key_has_no_sgdb_id(tmp_path) -> None:
    resolver, transport, _ = build(tmp_path, api_key="", owned=OWNED)
    match = resolver.resolve("Elden Ring")
    assert (match.how, match.steam_appid, match.sgdb_id) == ("owned:exact", 1245620, None)
    assert transport.calls == []


def test_a_failed_sgdb_lookup_keeps_an_owned_name_match_for_this_run_only(tmp_path) -> None:
    resolver, transport, cache = build(tmp_path, owned=OWNED)
    url = "https://www.steamgriddb.com/api/v2/games/steam/1245620"
    transport.fail_with[url] = NetworkError("down")
    match = resolver.resolve("Elden Ring")
    assert (match.how, match.steam_appid, match.transient) == ("owned:exact", 1245620, True)
    assert "Elden Ring" not in cache
    del transport.fail_with[url]
    assert resolver.resolve("Elden Ring").sgdb_id == 5297
    assert "Elden Ring" in cache


def test_the_year_tells_a_re_release_from_its_original(tmp_path) -> None:
    # "DOOM" is not "DOOM (1993)": the strict normalisation keeps the year,
    # so the owned step passes and the searches decide (nothing recorded
    # for "DOOM": no match).
    resolver, transport, _ = build(tmp_path, owned=OWNED)
    match = resolver.resolve("DOOM")
    assert match.how != "owned:exact"
    assert any("autocomplete" in c for c in transport.calls)
    assert resolver.resolve("DOOM (1993)").steam_appid == 2280


def test_an_ambiguous_owned_name_is_left_to_the_searches(tmp_path) -> None:
    owned = dict(OWNED) | {777: "Elden Ring"}
    resolver, transport, _ = build(tmp_path, owned=owned)
    match = resolver.resolve("Elden Ring")
    assert match.how == "sgdb:exact-verified"
    assert any("autocomplete" in c for c in transport.calls)


def test_an_owned_name_heals_a_cached_weak_match_but_not_a_strong_one(tmp_path) -> None:
    resolver, transport, cache = build(tmp_path, owned=OWNED)
    cache.put(Match(name="Brand New Sequel", steam_appid=610100, sgdb_id=8400, how="sgdb:fuzzy"))
    cache.put(Match(name="Elden Ring", steam_appid=4242, sgdb_id=4242, how="sgdb:exact-verified"))
    cache.put(Match(name="DOOM (1993)", how="none"))
    assert resolver.resolve("Brand New Sequel").how == "owned:exact"  # fuzzy: healed
    assert resolver.resolve("DOOM (1993)").steam_appid == 2280  # a cached miss: healed
    strong = resolver.resolve("Elden Ring")  # exact with an appid: trusted
    assert (strong.how, strong.steam_appid) == ("sgdb:exact-verified", 4242)
    assert not any("autocomplete" in c for c in transport.calls)


def test_a_pin_beats_the_owned_name(tmp_path) -> None:
    resolver, transport, cache = build(tmp_path, owned=OWNED)
    cache.pin(Match(name="Elden Ring", steam_appid=None, sgdb_id=None))
    match = resolver.resolve("Elden Ring")
    assert (match.how, match.steam_appid) == ("pinned", None)
    assert transport.calls == []


def test_zero_results_falls_through_to_the_store_and_then_to_no_match(tmp_path) -> None:
    resolver, transport, cache = build(tmp_path)
    match = resolver.resolve("Totally Unknown Title")
    assert match.found is False
    assert match.how == "none"
    assert any("storesearch" in call for call in transport.calls)
    # The negative result is on disk immediately (spec 3.5 A.4).
    stored = json.loads((tmp_path / "matches.json").read_text())
    assert stored["titles"]["Totally Unknown Title"]["how"] == "none"


def test_without_a_key_only_the_steam_store_is_consulted(tmp_path) -> None:
    resolver, transport, _ = build(tmp_path, api_key="")
    resolver.resolve("Totally Unknown Title")
    assert not any("steamgriddb.com" in call for call in transport.calls)
    assert any("storesearch" in call for call in transport.calls)


def test_overrides_pin_a_title_and_skip_art_entirely(tmp_path) -> None:
    resolver, transport, cache = build(
        tmp_path,
        overrides={
            "Weird Launcher Name": {"steam": 1245620},
            "Desktop": {"art": False},
        },
    )
    pinned = resolver.resolve("Weird Launcher Name")
    assert (pinned.how, pinned.steam_appid) == ("override", 1245620)
    assert transport.calls == []

    skipped = resolver.resolve("Desktop")
    assert skipped.skipped is True
    assert "Desktop" not in cache


def test_an_sgdb_pin_still_looks_up_the_steam_release(tmp_path) -> None:
    resolver, transport, _ = build(tmp_path, overrides={"Pinned": {"sgdb": 5297}})
    match = resolver.resolve("Pinned")
    assert (match.sgdb_id, match.steam_appid) == (5297, 1245620)

    # ...once. A pinned title costing one call per run would break "a second
    # pass does only the remaining work" (spec 3.9 item 1).
    before = len(transport.calls)
    again = resolver.resolve("Pinned")
    assert len(transport.calls) == before
    assert again.steam_appid == 1245620


def test_editing_an_sgdb_pin_re_queries_the_steam_release(tmp_path) -> None:
    resolver, transport, _ = build(tmp_path, overrides={"Pinned": {"sgdb": 5297}})
    resolver.resolve("Pinned")
    before = len(transport.calls)
    resolver.overrides = {"Pinned": {"sgdb": 5468}}
    match = resolver.resolve("Pinned")
    assert len(transport.calls) > before
    assert (match.sgdb_id, match.steam_appid) == (5468, 1145350)


# -- the cache -------------------------------------------------------------


def test_a_cached_positive_match_costs_no_http(tmp_path) -> None:
    resolver, transport, _ = build(tmp_path)
    resolver.resolve("Elden Ring")
    before = len(transport.calls)
    again = resolver.resolve("Elden Ring")
    assert len(transport.calls) == before
    assert again.steam_appid == 1245620
    assert again.how.startswith("sgdb:")


def test_force_ignores_the_cache(tmp_path) -> None:
    resolver, transport, _ = build(tmp_path)
    resolver.resolve("Elden Ring")
    before = len(transport.calls)
    resolver.force = True
    resolver.resolve("Elden Ring")
    assert len(transport.calls) > before


def test_a_negative_result_is_not_requeried_for_seven_days(tmp_path) -> None:
    resolver, transport, cache = build(tmp_path)
    resolver.resolve("Totally Unknown Title")
    before = len(transport.calls)
    resolver.resolve("Totally Unknown Title")
    assert len(transport.calls) == before

    # Age it past the window and it is searched again.
    stale = datetime.now(UTC) - NEGATIVE_TTL - timedelta(hours=1)
    entry = cache.get("Totally Unknown Title")
    entry.when = stale.isoformat().replace("+00:00", "Z")
    cache.put(entry)
    resolver.resolve("Totally Unknown Title")
    assert len(transport.calls) > before


def test_retry_missing_reopens_a_fresh_negative(tmp_path) -> None:
    resolver, transport, _ = build(tmp_path)
    resolver.resolve("Totally Unknown Title")
    before = len(transport.calls)
    resolver.retry_missing = True
    resolver.resolve("Totally Unknown Title")
    assert len(transport.calls) > before


def test_the_cache_file_is_replaced_atomically_and_survives_a_reload(tmp_path) -> None:
    path = tmp_path / "matches.json"
    cache = MatchCache(path)
    cache.put(Match(name="A", steam_appid=1, sgdb_id=2, how="sgdb:exact"))
    assert path.is_file()
    assert not (tmp_path / "matches.json.tmp").exists()

    cache.record_missing_slot("A", "logo")
    cache.flush()
    reloaded = MatchCache(path)
    assert reloaded.get("A").steam_appid == 1
    assert reloaded.slot_is_known_missing("A", "logo") is True
    assert reloaded.slot_is_known_missing("A", "hero") is False


def test_a_corrupt_cache_is_a_miss_not_a_crash(tmp_path) -> None:
    path = tmp_path / "matches.json"
    path.write_text("{ this is not json")
    cache = MatchCache(path)
    assert len(cache) == 0


def test_a_stale_slot_miss_is_retried(tmp_path) -> None:
    cache = MatchCache(tmp_path / "matches.json")
    cache.put(Match(name="A", steam_appid=1, how="sgdb:exact"))
    old = datetime.now(UTC) - NEGATIVE_TTL - timedelta(minutes=1)
    cache.record_missing_slot("A", "logo", when=old)
    assert cache.slot_is_known_missing("A", "logo") is False


def test_a_slot_miss_for_an_unresolved_title_is_not_recorded(tmp_path) -> None:
    # The back door onto the negative cache: a title whose own lookup failed
    # has no entry, and inventing one here would start a 7-day window off a
    # SteamGridDB 5xx or a timeout (spec 6.10).
    cache = MatchCache(tmp_path / "matches.json")
    cache.record_missing_slot("Never Resolved", "logo")
    cache.flush()
    assert "Never Resolved" not in cache
    assert not (tmp_path / "matches.json").exists()


def test_a_transient_lookup_failure_is_never_cached_as_a_miss(tmp_path) -> None:
    transport = FakeTransport()
    # Make the SteamGridDB search fail at the transport level, every time.
    url = "https://www.steamgriddb.com/api/v2/search/autocomplete/Elden%20Ring"
    transport.fail_with[url] = NetworkError("down")
    fetcher = make_fetcher(transport)
    cache = MatchCache(tmp_path / "matches.json")
    resolver = Resolver(
        cache=cache,
        sgdb=SgdbClient(api_key="k", fetcher=fetcher),
        store=None,
    )
    match = resolver.resolve("Elden Ring")
    assert match.found is False
    assert match.transient is True
    assert "Elden Ring" not in cache
    assert not (tmp_path / "matches.json").exists()
