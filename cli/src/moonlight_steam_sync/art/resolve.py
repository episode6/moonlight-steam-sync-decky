"""Step A of spec 3.5: a Moonlight title -> a Steam appid and/or a SGDB id.

Also home to the match cache, which is the resumability contract's record of
"this title is resolved" (spec 3.9 item 2):

* ``~/.cache/moonlight-steam-sync/matches.json``, one entry per Moonlight app
  name;
* written with an atomic ``os.replace`` **immediately after each title is
  resolved**, never batched to the end of the run;
* a title with no match is recorded, but only a title that *has* a match
  stops the next run from looking: a sync is a manual act, so every run
  searches again for what the last one did not find (the user's decision of
  2026-10-31; through 0.13.2 a miss was not re-queried for 7 days). One run
  searches a title once (``Resolver._searched``). ``art --force`` ignores
  the cache outright -- except for **pins**.

A *pin* (``how == "pinned"``, written by the ``match`` subcommand, decky
spec 3.4.4) is the tool's own record of "the user chose this match". It is
the one cache entry ``art --force`` never overwrites;
only ``match --unpin`` (or a later ``match``) removes it.

``stale_art`` is a fact about the grid files on disk ("they belong to an
earlier match"), not about the match, so it outlives the entry it was set
on: :meth:`MatchCache.put` carries it forward onto whatever resolution
replaces the entry, and only :meth:`MatchCache.pin` (the user's fresh
choice) or :meth:`MatchCache.clear_stale_art` (the art was re-fetched)
drops it. ``match --unpin --defer-art`` therefore leaves a placeholder
(``how == "unpinned"``, no ids) that carries the flag; the resolver treats
it as a cache miss, so the next run still re-resolves.

Matching order (spec 3.5 step A): config override, then a pin, then the
cache, then SteamGridDB autocomplete, then -- if there is no key, or
SteamGridDB returned nothing, or only a weak answer (a fuzzy pick, or an
exact one with no Steam release; see :meth:`Resolver._search`) -- Steam's
own store search. Both searches use the same normalisation and the same
pick rules.
"""

from __future__ import annotations

import json
import os
import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from moonlight_steam_sync.art.http import HardStop, HttpError
from moonlight_steam_sync.art.sgdb import SgdbClient, steam_appid_from_game
from moonlight_steam_sync.art.steamstore import SteamStoreClient

CACHE_VERSION = 1

#: ``Match.how`` of an entry written by ``match`` (decky spec 3.4.4).
HOW_PINNED = "pinned"

#: ``Match.how`` of the placeholder ``match --unpin --defer-art`` leaves
#: behind to carry ``stale_art`` until the next run re-resolves the title
#: (decky spec 3.4.4). Never authoritative: the resolver treats it as a
#: cache miss and the ``--json`` reports show it as no match at all.
HOW_UNPINNED = "unpinned"

#: ``Match.how`` of a title that is, to the letter, the name of a game the
#: account owns (``sync --owned-apps``; :meth:`Resolver._owned_match`).
HOW_OWNED = "owned:exact"

_TRADEMARKS = str.maketrans({"™": "", "®": "", "©": ""})
_TRAILING_YEAR = re.compile(r"\(\s*(?:19|20)\d{2}\s*\)\s*$")
_NON_WORD = re.compile(r"[\W_]+", re.UNICODE)


def normalise(name: str) -> str:
    """Casefold, drop (tm)/(R)/(C), strip a trailing ``(YYYY)``, punctuation -> space.

    >>> normalise("Hades II™ (2024)")
    'hades ii'
    """
    return normalise_strict(_TRAILING_YEAR.sub("", name.strip()))


def normalise_strict(name: str) -> str:
    """:func:`normalise` without the trailing-year rule, for the owned-name match.

    Steam tells a re-release from its original by the year (``DOOM`` and
    ``DOOM (1993)``), and the owned-name match must not fold the two: a
    title that reads ``DOOM`` is only the owned game called exactly that.

    >>> normalise_strict("DOOM (1993)")
    'doom 1993'
    """
    text = name.translate(_TRADEMARKS).casefold().strip()
    text = _NON_WORD.sub(" ", text)
    return " ".join(text.split())


def cache_dir() -> Path:
    """``$XDG_CACHE_HOME/moonlight-steam-sync`` (``~/.cache`` by default)."""
    base = os.environ.get("XDG_CACHE_HOME") or str(Path.home() / ".cache")
    return Path(base) / "moonlight-steam-sync"


def default_cache_path() -> Path:
    return cache_dir() / "matches.json"


def _now() -> datetime:
    return datetime.now(UTC)


def _iso(moment: datetime) -> str:
    return moment.astimezone(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


@dataclass
class Match:
    """What we know about one Moonlight title.

    ``how`` is the match chain's verdict, printed by ``art --explain``:
    ``override``, ``pinned`` (``match``, decky spec 3.4.4), ``unpinned``
    (the placeholder ``match --unpin --defer-art`` leaves; not a
    resolution), ``owned:exact`` (the title is an owned game's name,
    ``sync --owned-apps``), ``cache``, ``sgdb:exact-verified``, ``sgdb:exact``,
    ``sgdb:fuzzy``, ``steamstore:exact``, ``steamstore:fuzzy``, ``none`` or
    ``skipped`` (``art = false`` in ``[overrides]``).
    """

    name: str
    steam_appid: int | None = None
    sgdb_id: int | None = None
    matched_name: str | None = None
    how: str = "none"
    when: str = field(default_factory=lambda: _iso(_now()))
    #: ``match --defer-art`` (decky spec 3.4.4): the grid files on disk
    #: belong to an earlier match and the next ``sync`` should re-fetch
    #: them. Persisted only when true, so a cache with no such entry is
    #: byte-identical to one written before the field existed
    #: (``CACHE_VERSION`` stays 1).
    stale_art: bool = False
    #: Human-readable match chain; never persisted.
    explain: list[str] = field(default_factory=list, compare=False)
    #: True when the search failed for a transient reason (a 5xx, a timeout,
    #: a 429 that exhausted its retries). Never persisted and never cached:
    #: a failed lookup is not an answer, so it must not read as one.
    transient: bool = field(default=False, compare=False)

    @property
    def found(self) -> bool:
        return self.steam_appid is not None or self.sgdb_id is not None

    @property
    def skipped(self) -> bool:
        return self.how == "skipped"

    @property
    def pinned(self) -> bool:
        return self.how == HOW_PINNED

    @property
    def unpinned(self) -> bool:
        """The ``--unpin --defer-art`` placeholder: a stale-art marker, not a match."""
        return self.how == HOW_UNPINNED

    def to_json(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "steam_appid": self.steam_appid,
            "sgdb_id": self.sgdb_id,
            "matched_name": self.matched_name,
            "how": self.how,
            "when": self.when,
        }
        if self.stale_art:
            # Only when set: an entry without the flag serialises exactly as
            # it did before the field existed (decky spec 3.11).
            payload["stale_art"] = True
        return payload

    @classmethod
    def from_json(cls, name: str, data: Mapping[str, Any]) -> Match:
        return cls(
            name=name,
            steam_appid=_as_int(data.get("steam_appid")),
            sgdb_id=_as_int(data.get("sgdb_id")),
            matched_name=data.get("matched_name"),
            how=str(data.get("how") or "none"),
            when=str(data.get("when") or ""),
            stale_art=data.get("stale_art") is True,
        )


def _as_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


class MatchCache:
    """``matches.json``: load once, flush after every title (spec 3.9 item 2)."""

    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self._entries: dict[str, Match] = {}
        self._dirty = False
        self._load()

    def _load(self) -> None:
        try:
            raw = self.path.read_text(encoding="utf-8")
        except (FileNotFoundError, NotADirectoryError):
            return
        except OSError:
            return
        try:
            payload = json.loads(raw)
        except ValueError:
            # A corrupt cache is a cache miss, never a crash: the whole point
            # of the file is that it can be thrown away and rebuilt.
            return
        titles = payload.get("titles") if isinstance(payload, Mapping) else None
        if not isinstance(titles, Mapping):
            return
        for name, data in titles.items():
            if isinstance(data, Mapping):
                self._entries[str(name)] = Match.from_json(str(name), data)

    def __contains__(self, name: str) -> bool:
        return name in self._entries

    def __len__(self) -> int:
        return len(self._entries)

    def names(self) -> Iterable[str]:
        return tuple(self._entries)

    def get(self, name: str) -> Match | None:
        return self._entries.get(name)

    def put(self, match: Match, *, keep_stale_art: bool = True) -> None:
        """Record a resolution and write the file straight away.

        ``stale_art`` belongs to the grid files, not to the match, so by
        default it is carried forward from the entry being replaced: a
        deferred ``match`` (or ``--unpin``) followed by a re-resolution
        still leaves a flagged entry for ``sync`` to act on. Only
        :meth:`pin` -- the user's own fresh choice -- passes
        ``keep_stale_art=False``; :meth:`clear_stale_art` is the other way
        the flag goes.
        """
        previous = self._entries.get(match.name)
        if keep_stale_art and previous is not None and previous.stale_art:
            match.stale_art = True
        self._entries[match.name] = match
        self._dirty = True
        self.flush()

    def pin(self, match: Match) -> Match:
        """Record ``match`` as the user's choice for its title (decky spec 3.4.4).

        Replaces whatever entry the title had -- its ids and any
        ``stale_art`` flag belong to the old match -- with a
        ``how == "pinned"`` entry, and writes the file straight away.
        """
        pinned = Match(
            name=match.name,
            steam_appid=match.steam_appid,
            sgdb_id=match.sgdb_id,
            matched_name=match.matched_name,
            how=HOW_PINNED,
        )
        self.put(pinned, keep_stale_art=False)
        return pinned

    def unpin(self, name: str, *, stale_art: bool = False) -> bool:
        """Forget the title's match so the next run re-resolves it.

        Deletes the entry outright, or -- with ``stale_art`` (``match
        --unpin --defer-art`` on a title that has a shortcut, so the grid
        files on disk belong to the match being forgotten) -- replaces it
        with a ``how == "unpinned"`` placeholder whose only content is the
        flag. :meth:`Resolver.resolve` treats that placeholder as a miss,
        and :meth:`put` carries the flag onto the resolution that replaces
        it, so ``sync`` still sees ``stale_art`` after re-resolving.

        Returns whether the title had an entry before the call.
        """
        had_entry = self._entries.pop(name, None) is not None
        if stale_art:
            self._entries[name] = Match(name=name, how=HOW_UNPINNED, stale_art=True)
        elif not had_entry:
            return False
        self._dirty = True
        self.flush()
        return had_entry

    def mark_stale_art(self, name: str) -> bool:
        """Flag the title's grid files as belonging to an earlier match.

        ``match --defer-art`` (decky spec 3.4.4): the next ``sync`` deletes
        and re-fetches them. A no-op (returns ``False``) for a title with no
        entry.
        """
        entry = self._entries.get(name)
        if entry is None:
            return False
        if not entry.stale_art:
            entry.stale_art = True
            self._dirty = True
            self.flush()
        return True

    def clear_stale_art(self, name: str) -> None:
        """Drop the ``stale_art`` flag once the art has been re-fetched."""
        entry = self._entries.get(name)
        if entry is not None and entry.stale_art:
            entry.stale_art = False
            self._dirty = True
            self.flush()

    def flush(self) -> None:
        """Atomic whole-file replace; a no-op when nothing changed."""
        if not self._dirty:
            return
        payload = {
            "version": CACHE_VERSION,
            "titles": {name: match.to_json() for name, match in sorted(self._entries.items())},
        }
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_name(self.path.name + ".tmp")
        tmp.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        os.replace(tmp, self.path)
        self._dirty = False


def pick(
    candidates: Iterable[Mapping[str, Any]],
    wanted: str,
    *,
    name_key: str = "name",
    prefer_verified: bool = True,
) -> tuple[dict[str, Any] | None, str]:
    """The pick rules from spec 3.5 step A.2, shared by both searches.

    In order: an exact normalised match that is ``verified``; an exact
    normalised match; the first result whose normalised name is a prefix of
    ours or vice-versa (reported as ``fuzzy``); else nothing.
    """
    target = normalise(wanted)
    results = [c for c in candidates if isinstance(c, Mapping)]
    exact = [c for c in results if normalise(str(c.get(name_key) or "")) == target]
    if prefer_verified:
        for candidate in exact:
            if candidate.get("verified"):
                return dict(candidate), "exact-verified"
    if exact:
        return dict(exact[0]), "exact"
    if target:
        for candidate in results:
            other = normalise(str(candidate.get(name_key) or ""))
            if other and (other.startswith(target) or target.startswith(other)):
                return dict(candidate), "fuzzy"
    return None, "none"


@dataclass
class Resolver:
    """Title -> :class:`Match`, with the cache and the overrides applied."""

    cache: MatchCache
    sgdb: SgdbClient | None = None
    store: SteamStoreClient | None = None
    overrides: Mapping[str, Mapping[str, Any]] = field(default_factory=dict)
    #: ``art --force``: ignore the cache entirely and re-resolve -- except
    #: a pin, which is the user's own choice (decky spec 3.4.4).
    force: bool = False
    #: ``sync --owned-apps``: the account's games, Steam appid -> display
    #: name (decky spec 3.4.1). A title that *is* one of those names, to
    #: the letter after :func:`normalise_strict`, is that game
    #: (``how == "owned:exact"``) before any search is made; ``None`` (an
    #: ``art`` run, a plain ``sync``) turns the step off.
    owned: Mapping[int, str] | None = None
    #: Titles this run has already searched and found nothing for. A
    #: ``Resolver`` lives for one run, and ``sync --owned-apps`` resolves every
    #: title twice in it (ahead of the plan, then in the art phase), so a miss
    #: costs one search per run, not two.
    _searched: set[str] = field(default_factory=set, init=False, repr=False, compare=False)
    _owned_index: Mapping[str, tuple[int, ...]] = field(
        default_factory=dict, init=False, repr=False, compare=False
    )
    _owned_index_for: Mapping[int, str] | None = field(
        default=None, init=False, repr=False, compare=False
    )

    def resolve(self, name: str) -> Match:
        """Resolve ``name``, flushing the cache before returning (spec 3.5 A.4).

        Order: a ``[overrides]`` entry in ``config.toml`` (config beats
        cache, so it also beats a pin), then a pinned cache entry --
        checked *before* ``force``, so it never overwrites a pin -- then the
        owned-name match (below), then the ordinary cache (an entry with no
        match only counts within the run that searched for it), then the
        searches. An ``unpinned`` placeholder
        (``match --unpin --defer-art``) is a cache miss: it only exists to
        carry ``stale_art`` onto the resolution that :meth:`MatchCache.put`
        writes over it.

        The owned-name match (``sync --owned-apps``): a title that is,
        after :func:`normalise_strict`, the name of exactly one game the
        account owns is that game, with no lookup -- the library itself is
        the authority on what it is called, and a title newer than the
        search sources' catalogues is the title most likely to be
        mismatched by them (2026-10-29). It runs ahead of the cache so a
        cached *weak* match (no Steam appid, or a fuzzy one) heals the
        next run; a cached match that already has an appid by an exact
        search stands, and so does a pin. SteamGridDB is then asked once
        for the id behind that appid (``games/steam/{appid}``), for
        community art; a transient failure there keeps the match for this
        run only, uncached.
        """
        explain: list[str] = []

        override = self._override(name)
        if override is not None:
            if override.get("art") is False:
                match = Match(name=name, how="skipped", explain=["override: art = false"])
                return match
            steam_appid = _as_int(override.get("steam"))
            sgdb_id = _as_int(override.get("sgdb"))
            explain.append(f"override: steam={steam_appid} sgdb={sgdb_id}")
            if sgdb_id is not None and steam_appid is None:
                looked_up = self._cached_override(name, sgdb_id)
                if looked_up is not None:
                    steam_appid = looked_up
                    explain.append(f"cache: steam appid {looked_up} for the pinned sgdb id")
                elif self._sgdb_usable():
                    steam_appid, _failed = self._steam_appid_for(sgdb_id, explain)
            match = Match(
                name=name,
                steam_appid=steam_appid,
                sgdb_id=sgdb_id,
                matched_name=name,
                how="override",
                explain=explain,
            )
            self.cache.put(match)
            return match

        cached = self.cache.get(name)
        if cached is not None and cached.pinned:
            cached.explain = [
                f"pinned: steam={cached.steam_appid} sgdb={cached.sgdb_id} when={cached.when}"
            ]
            return cached
        if self.force or (cached is not None and cached.unpinned):
            cached = None
        if cached is not None and (cached.found or name in self._searched):
            if not (cached.steam_appid is None or cached.how.endswith(":fuzzy")):
                cached.explain = [f"cache: how={cached.how} when={cached.when}"]
                return cached
            owned_match = self._owned_match(name, explain)
            if owned_match is None:
                cached.explain = [f"cache: how={cached.how} when={cached.when}"]
                return cached
            explain.insert(0, f"cache: how={cached.how} when={cached.when} (weak; owned name wins)")
            if cached.how.endswith(":fuzzy"):
                # The grid files on disk were fetched for the fuzzy pick,
                # another game: a `rematched` replacement, not a rename.
                owned_match.stale_art = True
                explain.append("art on disk is the fuzzy pick's; flagged stale")
        else:
            owned_match = self._owned_match(name, explain)
        if owned_match is not None:
            if not owned_match.transient:
                self.cache.put(owned_match)
            return owned_match

        match = self._search(name, explain)
        if match.transient:
            # Do not write a negative result we are not sure about.
            return match
        self.cache.put(match)
        self._searched.add(name)
        return match

    # -- internals -------------------------------------------------------

    def _owned_match(self, name: str, explain: list[str]) -> Match | None:
        """The owned game ``name`` is the name of, or ``None`` (see :meth:`resolve`).

        Exactly one owned game may carry the name: two that do (``DOOM``
        and ``DOOM (1993)`` are distinct under :func:`normalise_strict`,
        but a re-release and its original can share a name to the letter)
        leave the searches to decide. The SteamGridDB id, when a key is
        configured, comes from ``games/steam/{appid}``; a 404 there is a
        definite "no community art", anything else keeps the match for
        this run only (``transient``).
        """
        if not self.owned:
            return None
        wanted = normalise_strict(name)
        if not wanted:
            return None
        appids = self._owned_by_name().get(wanted)
        if not appids:
            return None
        if len(appids) > 1:
            explain.append(f"owned name: {len(appids)} owned games are called that; searching")
            return None
        (steam_appid,) = appids
        match = Match(
            name=name,
            steam_appid=steam_appid,
            sgdb_id=None,
            matched_name=self.owned[steam_appid],
            how=HOW_OWNED,
            explain=explain,
        )
        explain.append(f"owned name: steam appid {steam_appid} ({match.matched_name!r})")
        if self._sgdb_usable():
            assert self.sgdb is not None
            try:
                game = self.sgdb.game_by_steam_appid(steam_appid)
            except HardStop:
                raise
            except HttpError as exc:
                explain.append(f"sgdb games/steam/{steam_appid} failed: {exc} (not cached)")
                match.transient = True
                return match
            match.sgdb_id = _as_int(game.get("id")) if game is not None else None
            explain.append(
                f"sgdb games/steam/{steam_appid} -> "
                f"{match.sgdb_id if match.sgdb_id is not None else 'no sgdb game'}"
            )
        return match

    def _owned_by_name(self) -> Mapping[str, tuple[int, ...]]:
        """``normalise_strict(display name) -> owned appids``, built once per map."""
        owned = self.owned or {}
        if self._owned_index_for is not owned:
            index: dict[str, list[int]] = {}
            for appid, display_name in owned.items():
                index.setdefault(normalise_strict(str(display_name)), []).append(int(appid))
            self._owned_index = {k: tuple(sorted(v)) for k, v in index.items() if k}
            # The mapping itself, not its id(): a kept reference cannot be
            # reused by a later, different map of the same length.
            self._owned_index_for = owned
        return self._owned_index

    def _override(self, name: str) -> Mapping[str, Any] | None:
        value = self.overrides.get(name)
        return value if isinstance(value, Mapping) else None

    def _cached_override(self, name: str, sgdb_id: int) -> int | None:
        """The Steam appid a previous run already looked up for this pin.

        An ``[overrides] sgdb = N`` pin otherwise costs one
        ``games/id/N?platformdata=steam`` call *per run*, against spec 3.9's
        "a second pass does only the remaining work". Only a cached entry
        written by the same pin counts, so editing the pin re-queries.
        """
        if self.force:
            return None
        cached = self.cache.get(name)
        if cached is None or cached.how != "override" or cached.sgdb_id != sgdb_id:
            return None
        return cached.steam_appid

    def _sgdb_usable(self) -> bool:
        return self.sgdb is not None and self.sgdb.enabled

    def _search(self, name: str, explain: list[str]) -> Match:
        """SteamGridDB autocomplete, then -- when it had nothing, or only a
        *weak* answer -- Steam's own store search.

        A SteamGridDB answer is weak when it is a fuzzy pick, or an exact
        one for a game SteamGridDB has no Steam release for. Both happen
        for a game released since SteamGridDB last caught up (measured
        2026-10-29: a brand-new title with no SteamGridDB entry at all
        fuzzy-matched its franchise's first game, and another had a
        verified entry nobody had linked to Steam yet), and both used to
        end the search, so the store's exact hit -- the appid the account
        owns -- was never asked for. Now an exact store hit replaces a
        fuzzy SteamGridDB pick outright (that pick was a different game)
        and lends its appid to an unlinked exact one (the SteamGridDB id
        stays for community art, and ``how`` stays ``sgdb:exact*``). A
        store answer that is not exact changes nothing.

        A weak answer the store does not firm up is cached as it stands,
        except when a lookup failed along the way, which is never cached:
        a failed store search keeps an unlinked exact match for this run
        only but drops a fuzzy one outright (a fuzzy pick is a different
        game, and this run would otherwise fetch that game's art, which
        the next run's kind change would then rename onto the right one),
        and a failed ``games/id`` lookup -- "no Steam release" is not
        known, only unanswered -- keeps the exact match for this run only
        unless the store's exact hit supplied the appid anyway.
        """
        transient = False
        weak: Match | None = None
        release_lookup_failed = False
        if self._sgdb_usable():
            assert self.sgdb is not None
            try:
                results = self.sgdb.search(name)
            except HardStop:
                raise
            except HttpError as exc:
                explain.append(f"sgdb autocomplete failed: {exc}")
                results, transient = [], True
            chosen, how = pick(results, name)
            if not transient:
                explain.append(f"sgdb autocomplete: {len(results)} result(s) -> {how}")
            if chosen is not None:
                sgdb_id = _as_int(chosen.get("id"))
                steam_appid, release_lookup_failed = (
                    self._steam_appid_for(sgdb_id, explain)
                    if sgdb_id is not None
                    else (None, False)
                )
                match = Match(
                    name=name,
                    steam_appid=steam_appid,
                    sgdb_id=sgdb_id,
                    matched_name=str(chosen.get("name") or ""),
                    how=f"sgdb:{how}",
                    explain=explain,
                )
                if how != "fuzzy" and steam_appid is not None:
                    return match
                weak = match
                if how == "fuzzy":
                    explain.append("sgdb match is weak (fuzzy)")
                elif release_lookup_failed:
                    explain.append("sgdb match is weak (steam release lookup failed)")
                else:
                    explain.append("sgdb match is weak (no steam release)")
        else:
            explain.append("sgdb: no api key, skipping")

        if self.store is not None:
            store_failed = False
            try:
                items = self.store.search(name)
            except HardStop:
                raise
            except HttpError as exc:
                explain.append(f"steam storesearch failed: {exc}")
                items, transient, store_failed = [], True, True
            chosen, how = pick(items, name, prefer_verified=False)
            if not store_failed:
                explain.append(f"steam storesearch: {len(items)} result(s) -> {how}")
            store_appid = _as_int(chosen.get("id")) if chosen is not None else None
            if chosen is not None and weak is None:
                return Match(
                    name=name,
                    steam_appid=store_appid,
                    sgdb_id=None,
                    matched_name=str(chosen.get("name") or ""),
                    how=f"steamstore:{how}",
                    explain=explain,
                )
            exact_store = chosen is not None and how == "exact" and store_appid is not None
            if weak is not None and exact_store:
                if weak.how == "sgdb:fuzzy":
                    explain.append("steam storesearch exact match replaces the fuzzy sgdb one")
                    return Match(
                        name=name,
                        steam_appid=store_appid,
                        sgdb_id=None,
                        matched_name=str(chosen.get("name") or ""),
                        how="steamstore:exact",
                        explain=explain,
                    )
                explain.append(f"steam appid {store_appid} from the store's exact match")
                weak.steam_appid = store_appid
                return weak

        if weak is not None:
            if transient and weak.how == "sgdb:fuzzy":
                explain.append("fuzzy sgdb match dropped (store lookup failed; not cached)")
                return Match(name=name, how="none", explain=explain, transient=True)
            if transient or release_lookup_failed:
                explain.append("weak sgdb match kept for this run (a lookup failed; not cached)")
                weak.transient = True
            return weak
        if transient:
            explain.append("no match (a lookup failed; not cached)")
            return Match(name=name, how="none", explain=explain, transient=True)
        explain.append("no match")
        return Match(name=name, how="none", explain=explain)

    def _steam_appid_for(self, sgdb_id: int, explain: list[str]) -> tuple[int | None, bool]:
        """``(steam appid, lookup failed)`` for a SteamGridDB game.

        ``(None, False)`` is SteamGridDB's definite "no Steam release";
        ``(None, True)`` is an unanswered ``games/id`` call (an
        :class:`HttpError`), which :meth:`_search` does not cache. The
        override path ignores the flag: a pinned sgdb id is re-queried
        every run until it answers (:meth:`_cached_override`).
        """
        if not self._sgdb_usable():
            return None, False
        assert self.sgdb is not None
        try:
            game = self.sgdb.game(sgdb_id)
        except HardStop:
            raise
        except HttpError as exc:
            explain.append(f"sgdb games/id/{sgdb_id} failed: {exc}")
            return None, True
        steam_appid = steam_appid_from_game(game)
        explain.append(
            f"sgdb games/id/{sgdb_id}?platformdata=steam -> "
            f"{steam_appid if steam_appid is not None else 'no steam release'}"
        )
        return steam_appid, False
