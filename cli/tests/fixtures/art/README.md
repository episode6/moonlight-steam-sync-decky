# Artwork fixtures

> **TODO(real-data): everything in this directory is SYNTHETIC.** No byte of
> it came off the wire. It is shaped from the endpoint documentation in spec
> section 2.2 (SteamGridDB API v2 envelopes and asset fields, the style
> names, the Steam CDN and `storesearch`/`GetApps` URLs verified live on
> 2026-09-16, the `GetItems` asset lists verified live on 2026-10-31), but
> the values are invented, because no SteamGridDB API key was available
> when the artwork PR was written.
>
> **How to replace it with real data:** get a key from
> <https://www.steamgriddb.com/profile/preferences/api> and run
>
> ```sh
> SGDB_API_KEY=xxxxxxxx python3 scripts/record_fixtures.py
> ```
>
> from `cli/`. That re-queries the same call chain the tool makes and
> rewrites `manifest.json` and `responses/`. The tests look responses up **by
> URL through the manifest** and never read a fixture's literals, so this is
> a file replacement, not a test rewrite. The key is never written into
> anything the script produces; check the diff before committing anyway.

## Layout

| path | what it is |
|---|---|
| `manifest.json` | `url -> {status, body, content_type, headers}`. A URL that is not listed answers **404**, which is what the Steam CDN does for an asset a game does not have -- that is how the "no logo on the CDN" case works without a special case. |
| `responses/*.json` | one recorded JSON body each. |
| `images/tiny.{png,jpg,webp}` | 1x1 stand-in bodies. Only the magic bytes are load-bearing: the selector sniffs PNG/JPEG and rejects everything else, and `tiny.webp` exists to prove WebP never reaches `grid/`. Real captures do **not** need to replace these, and `record_fixtures.py` deliberately keeps pointing at them. |
| `make_synthetic.py` | regenerates the synthetic set, and documents what each title is for. |

Every Steam title has a `GetItems` answer (`steam-getitems-<appid>.json`),
the store's own list of its asset files, because Steam serves a game
published since mid-2025 only from hashed paths (`<hash>/header.jpg`) that
the plain CDN URLs cannot reach. The older titles list plain filenames
(`library_600x900.jpg`, served at `store_url(appid, filename)` in
`tests/art_fixtures.py`, with the `?t=1700000000` stamp both files agree
on); `Brand New Sequel` lists hashed ones; `Delisted Relic` is not listed at
all.

## The eleven titles and what each one is for

| title | case |
|---|---|
| `Elden Ring` | exact **verified** SteamGridDB match; every slot comes from the Steam CDN (the store's list of plain filenames, the icon hash with it, so `GetApps` is not called), so not one community call is made. Also the one `games/steam/{appid}` recording, for the owned-name match (`sync --owned-apps`: a title that is an owned game's name asks SteamGridDB only for the id behind the appid; a title whose appid has no recording gets a 404, the definite "no community art"). |
| `Hades II™` | a title carrying a trademark glyph (normalisation), and a 2x capsule the store lists but does not serve (404), so the 1x official portrait URL is used. |
| `Fan Made Adventure` | a **non-Steam** game (an exact SteamGridDB match with no Steam release, so the resolver asks the store too and gets an empty answer): community art only, score sorting (the fixture lists the low-score asset first), a second-choice query (`920x430` empty -> `460x215`), and an asset whose bytes are WebP behind a `.png` URL, which must be rejected. |
| `Old Console Classic` | a Steam game with **no `logo.png` on the CDN**, so the logo slot falls through to community art while the rest stay official. |
| `Totally Unknown Title` | **zero results** anywhere: no match, a `how: "none"` cache entry the next run searches past, every slot missing. |
| `Rate Limited Game` | SteamGridDB and the store both answer **429** forever, so the run hits the five-consecutive-429 hard stop and exits 4 with everything so far kept. |
| `Hollow Knight` | the adoptable SteamTinkerLaunch-era entry in `../shortcuts_synthetic.vdf`, so the `sync` end-to-end tests can adopt an existing shortcut and dress it (every slot official, like Elden Ring). |
| `Custom Logo Quest` | a Steam game with **no `logo.png` on the CDN**, an `official` SteamGridDB logo whose bytes are WebP and no `white` one, so the `custom` query beats a higher-scored `black` logo; a test that empties `custom` checks the any-style query skips the failed `official` logo it lists first. Only its logo chain is recorded. |
| `Brand New Sequel` | a game SteamGridDB does not have yet: autocomplete returns only the franchise's first game, `Brand New`, which the prefix rule picks as a **fuzzy** hit, so the store is asked and its exact hit wins (`steamstore:exact`, the wrong SteamGridDB id dropped). Its art is the **hashed-paths** case: `GetItems` lists every file behind its own hash and the unhashed CDN URLs are all 404s, as for every game published after Steam's move. No SteamGridDB id, so its logo (which the store does not list) stays missing. |
| `Unlinked Launch` | a **verified** SteamGridDB entry nobody has linked to a Steam release yet, so the store is asked and its exact hit lends its appid (`sgdb:exact-verified` with the store's appid, the SteamGridDB id kept for community art). Only the searches, the `games/id` lookup and a `GetItems` list (no images) are recorded. |
| `Delisted Relic` | an exact verified match for a Steam game the store **no longer lists**: `GetItems` answers `success: 15`, a definite "nothing here" (no failed lookup), so the unhashed CDN paths and the `GetApps` icon hash are the official sources. |

When a real device run turns up a match the heuristics get wrong, add it here
as the next case rather than special-casing it in the code.
