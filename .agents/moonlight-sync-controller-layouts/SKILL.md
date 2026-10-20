---
name: moonlight-sync-controller-layouts
description: >-
  The Moonlight Sync plugin's default controller layout (spec 3.16) and the
  layout strategy switch (spec 3.10, copy vs picker): src/lib/layouts.ts
  (DEFAULT_LAYOUT_STRATEGY, applyDefault's never-overwrite rule, unsetApplied,
  appliedUrl, the SteamInput seam, controller index, walkTargets),
  layouts.test.ts, setDefaultLayout / layoutWalk, Advanced's Layout / Make
  default / Clear, SetSelectedConfigForApp and ClearSelectedConfigForApp. Load
  before touching anything that reads or sets a Steam Input layout, the
  default_layout setting, layouts.json's applied field, or the layout walk.
---

# Moonlight Sync default controller layout

Reference split out of the root `AGENTS.md`, whose hard rules (cited here as
"hard rule N") apply throughout. Related: `moonlight-sync-frontend`
(controller.ts's layout entry points), `moonlight-sync-backend`
(`layouts.json`, `record_layout`, `set_default_layout`),
`moonlight-sync-library-ui` (AdvancedPage, adoptDefault).

## Module map: the layout modules

```
src/lib/                    pure modules (vitest)
  layouts.ts                DEFAULT_LAYOUT_STRATEGY (the one switch), layoutStrategy(),
                            DEFAULT_LAYOUT_SCHEMES / isShareableUrl() (workshop://,
                            template://), defaultLayoutOf() (null under picker or unset),
                            the SteamInput seam (clearConfig optional, feature-detected),
                            isUnselected() (no URL, default://, or bSelected false),
                            appliedUrl() (`applied`, else a legacy `copied` url),
                            applyDefault() (the §3.16.3 rule: a selection the plugin did
                            not make is never overwritten; the real game is not an
                            input), unsetApplied() (explicit `applied` only; `cleared`
                            on a successful clearConfig), deckControllerIndexFrom() (by
                            type: the type string when the client has it -- final either
                            way -- else the enum), layoutControllerIndexFrom() (the
                            Deck's, else the active or only connected controller),
                            CONFIG_SELECTION_USER, the status texts, walkTargets()
                            (every non-parked entry, deduped) and the walk's timings
  layouts.test.ts           applyDefault's cases + idempotence, unsetApplied, the
                            shareable schemes, defaultLayoutOf, walkTargets over the
                            status fixture, the index by type, the strategy switch
```

## The default controller layout and the strategy switch

**The default controller layout (spec §3.16).** One layout the user adopts
from the Moonlight entry they set up with Steam's own configurator
(Advanced's *Layout*, then *Make default* beside it, the one place since
Decision 74, on Advanced since Decision 77:
`inspectLayout` reads that entry's selection, refuses `autosave://` / `default://` / unselected with the
§3.16.5 texts, a `ConfirmModal`, then `setDefaultLayout`), stored by the
backend as `settings.default_layout` and put on every non-parked entry by
`applyDefault` -- on each Stream press, in the walk after a sync's restart
and at once when the default changes. **The one rule, exactly (§3.16.3): a
selection the plugin did not make is never overwritten.** `ours =
appliedUrl(record)` is what the plugin last set (`applied` from
`layouts.json`, or a legacy `copied` record's url, Decision 46); a selected
URL that is not `ours` is `kept` (hand-picked, edited in place after the
default landed, or the very title the default was adopted from), `ours ===
def.url` is `default` with no write, anything else (unselected, an offered
`template://`, or still `ours` while the default moved on) is set and read
back. The real game's appid is not an input any more. Clearing (Decision
51) runs the same walk as the unset pass: `unsetApplied` takes the plugin's
layout off entries whose explicit `applied` is still selected, through
`clearConfig` (`SteamClient.Input.ClearSelectedConfigForApp(appid, index)`,
**unmeasured**, feature-detected: without it the default is still cleared
and titles keep what they have); the legacy-`copied` fallback is never
unset. `copy_layouts` is a dead, still-valid settings key (Decision 47).
Two edges of `setDefaultLayout`: a walk that begins during its backend
call (the load's, once its wait for the shortcut list ends) passed its
flag check under the old default, so `doWalk` leaves the flag set when
`defaultChanges` moved under it and the change walks again after it; and
with `status` unavailable (`entries === null`) the walk is deferred
(`layoutWalk()` resolves `null`, the flag stays) and the toast says the
layout is applied, or taken off, once the titles have loaded (Decision
54) rather than counting a walk that never ran. *Make default* is
refused with a toast while `state.walking` (a disabled button could not
say why, as Advanced's disabled *Clear* cannot either).

**The layout strategy switch (spec §3.10).** PR-7 was built before the PR-0
probes ran. `DEFAULT_LAYOUT_STRATEGY = "copy"` in `src/lib/layouts.ts` is
the one place the default lives; `settings.json`'s `layout_strategy`
overrides it per device (no UI). Probe V2 (does `SetSelectedConfigForApp`
with a `workshop://` id published for one app stick on a shortcut?)
ran on 2026-09-20 and **confirmed `copy`** -- with one correction: the call
takes five arguments, the last being the selection type
(`CONFIG_SELECTION_USER = 1`, what Steam's own configurator passes); with
four it returns normally and selects nothing. The same session found the
store global is `ControllerStore` (not `controllerStore`), that
`SteamClient.Input.RegisterForControllerListChanges` does not exist on that
client (so `watchControllers()` guards every registration), and that the
device had no Deck controller at all, which is why
`layoutControllerIndexFrom()` falls back to the active or only connected
controller. Should a later client break the set, flip the constant to
`"picker"` and rewrite the README's "Controller layouts" section; nothing
else moves. Under `picker` no Steam Input call is made anywhere
(`defaultLayoutOf()` is `null`, so the whole §3.16 feature is off and its
UI hidden, and the walk clears its flag at once); Advanced's *Layout*
(`SteamClient.Apps.ShowControllerConfigurator`, hidden when absent) is
the only layout affordance.
