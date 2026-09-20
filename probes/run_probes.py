#!/usr/bin/env python3
"""Scripted runner for the Moonlight Sync device probes (spec PR-0, V1-V5).

Runs on the SteamOS machine itself (over SSH, with the Deck in Game Mode)
and talks to the Steam client through the CEF DevTools port that Decky
enables: ``GET http://localhost:8080/json`` lists the targets, the
``SharedJSContext`` target's ``webSocketDebuggerUrl`` is opened, and each
probe is one ``Runtime.evaluate`` (``awaitPromise`` + ``returnByValue``).

Every probe evaluates JavaScript that guards each Steam global and returns
``{"error": ..., "shape": ...}`` instead of throwing, so a wrong guess about
an undocumented API is diagnosable from the output alone.

Subcommands (see ``--help``): v1, v2, v3, v4, v5, all. Each prints one JSON
object and appends it to ``probe-results.json`` next to this file;
``--markdown`` renders the PROBES.md results table from that file. The table
is committed, so it is redacted: no Steam ID (the V4 row is a verdict checked
against ``~/.local/share/Steam/userdata`` when v4 runs), no library titles,
home paths as ``~``. The raw values stay in probe-results.json.

When the Deck controller index is not found by type, v1 probes every listed
controller index (or 15) and marks the rows "index not confirmed by type"
instead of aborting; ``--controller-index N`` overrides the lookup for v1/v2.

Safety: v2 (SetSelectedConfigForApp) needs ``--url`` and refuses any appid
below 0x80000000, so it can only touch a shortcut, never a real game;
v5 only launches with ``--run``; v3 shuts Steam down only after a typed
confirmation or ``--yes``. The runner never writes under the Steam directory.

Exit codes: 0 the probe ran (its JSON may still report an in-page error),
1 transport failure (no SharedJSContext target, websocket error, websockets
package missing), 2 refused or usage error, 3 DevTools port closed.

Dependency: the ``websockets`` package, imported lazily (``--help`` and the
tests work without it). Create it once with
``python3 -m venv ~/.cache/msy-probes && ~/.cache/msy-probes/bin/pip install websockets``
and run with ``~/.cache/msy-probes/bin/python3 probes/run_probes.py ...``.
"""

from __future__ import annotations

import argparse
import asyncio
import datetime
import errno
import json
import os
import re
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Callable, TextIO

DEFAULT_HOST = "localhost"
DEFAULT_PORT = 8080
SHORTCUT_APPID_MIN = 0x80000000
STEAM64_BASE = 76561197960265728
DEFAULT_RESULTS = Path(__file__).resolve().with_name("probe-results.json")
DEFAULT_V3_LOG = Path(__file__).resolve().with_name("probe-v3-pgrep.log")

EXIT_OK = 0
EXIT_FAIL = 1
EXIT_REFUSED = 2
EXIT_PORT_CLOSED = 3

PORT_CLOSED_MESSAGE = (
    "run_probes.py: cannot reach Steam's CEF DevTools port at {host}:{port}: "
    "is Decky installed and is Steam in Game Mode?"
)
VENV_LINE = "python3 -m venv ~/.cache/msy-probes && ~/.cache/msy-probes/bin/pip install websockets"
VENV_HINT = (
    f"the websockets package is not importable; create the venv once with `{VENV_LINE}` "
    "and run this script with ~/.cache/msy-probes/bin/python3"
)

PROBE_NAMES = ("v1", "v2", "v3", "v4", "v5")


class PortClosed(Exception):
    """The DevTools port refused the connection."""


class ProbeError(Exception):
    """A transport-level failure (not an in-page error, which is data)."""


class Refused(Exception):
    """A state-changing probe was asked for without its explicit flag."""


WORKSHOP_URL_RE = re.compile(r"workshop://\d+")


def check_workshop_url(url: str) -> None:
    """Refuse anything that is not ``workshop://<publishedfileid>``.

    Called up front in ``main()`` for both ``v2`` and ``all`` -- so ``all``
    refuses a malformed ``--url`` before v1/v4/v5 have run -- and again in
    ``Runner.v2``, which is reachable on its own."""
    if not WORKSHOP_URL_RE.fullmatch(url):
        raise Refused(f"v2 --url must look like workshop://<publishedfileid>, got {url!r}")


# ---------------------------------------------------------------------------
# JavaScript evaluated in the SharedJSContext
# ---------------------------------------------------------------------------

# Shared helpers. Everything is guarded: a missing global returns an object
# with `error` and `shape` rather than throwing.
JS_PRELUDE = r"""
const G = globalThis;
const NEPTUNE = "controller_steamcontroller_neptune";
const NEPTUNE_ENUM = 4; // EControllerType.SteamControllerNeptune in @decky/ui 4.12
// The fifth SetSelectedConfigForApp argument Steam's own configurator passes for a
// user pick (reads back as eSelectionType 1). Measured 2026-09-20: with four
// arguments the call returns normally and selects nothing.
const SELECTION_USER = 1;
const FALLBACK_INDEX = 15; // the Deck controller index deckyemu measured; used only when the type lookup fails
const errText = (e) => (e && e.message) ? (e.name + ": " + e.message) : String(e);
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const ret = (x) => (x === undefined ? "<undefined>" : safe(x));
function safe(value, depth) {
  depth = depth === undefined ? 4 : depth;
  const seen = new WeakSet();
  const walk = (v, d) => {
    if (v === null || v === undefined) return v;
    const t = typeof v;
    if (t === "bigint") return String(v) + "n";
    if (t === "function") return "[function " + (v.name || "anonymous") + "/" + v.length + "]";
    if (t === "symbol") return String(v);
    if (t !== "object") return v;
    if (v instanceof Error) return { error: errText(v), stack: v.stack };
    if (seen.has(v)) return "[circular]";
    seen.add(v);
    if (d <= 0) return "[object " + Object.keys(v).length + " keys]";
    if (Array.isArray(v)) return v.slice(0, 50).map((x) => walk(x, d - 1));
    if (v instanceof Map) return { "[Map]": Array.from(v.entries()).slice(0, 50).map(([k, x]) => [walk(k, d - 1), walk(x, d - 1)]) };
    if (v instanceof Set) return { "[Set]": Array.from(v.values()).slice(0, 50).map((x) => walk(x, d - 1)) };
    const out = {};
    for (const k of Object.keys(v)) {
      try { out[k] = walk(v[k], d - 1); } catch (e) { out[k] = "[getter threw: " + errText(e) + "]"; }
    }
    return out;
  };
  return walk(value, depth);
}
function shape(obj, filter) {
  if (obj === null || obj === undefined || (typeof obj !== "object" && typeof obj !== "function")) {
    return { typeof: typeof obj, value: String(obj) };
  }
  const own = Object.keys(obj);
  const protoMethods = [];
  let p = Object.getPrototypeOf(obj);
  let hops = 0;
  while (p && p !== Object.prototype && hops < 6) {
    for (const n of Object.getOwnPropertyNames(p)) {
      if (n !== "constructor" && protoMethods.indexOf(n) < 0) protoMethods.push(n);
    }
    p = Object.getPrototypeOf(p);
    hops++;
  }
  const pick = (names) => (filter ? names.filter((n) => filter.test(n)) : names).slice(0, 200);
  return {
    typeof: typeof obj,
    constructor: obj.constructor && obj.constructor.name,
    ownKeys: pick(own),
    ownKeyCount: own.length,
    protoMethods: pick(protoMethods),
  };
}
function globalsMatching(re) { return Object.keys(G).filter((k) => re.test(k)); }
function steamInput() {
  const sc = G.SteamClient;
  if (!sc) return { error: "SteamClient is " + typeof sc, shape: { globalsMatchingSteam: globalsMatching(/steam/i) } };
  if (!sc.Input) return { error: "SteamClient.Input is " + typeof sc.Input, shape: shape(sc) };
  return { input: sc.Input };
}
function overviewLabel(appid) {
  try {
    const store = G.appStore;
    if (!store || typeof store.GetAppOverviewByAppID !== "function") return "no appStore";
    const o = store.GetAppOverviewByAppID(appid);
    if (!o) return "no overview";
    return String(o.display_name) + " app_type=" + String(o.app_type);
  } catch (e) { return "overview threw " + errText(e); }
}
// An array, or any iterable (an older MobX observable array is not an Array).
function asList(v) {
  if (Array.isArray(v)) return v;
  if (v && typeof v === "object" && typeof v[Symbol.iterator] === "function") {
    try { return Array.from(v); } catch (e) { return null; }
  }
  return null;
}
function findControllers() {
  // `ControllerStore` on the client probed on 2026-09-20; `controllerStore` is the older spelling.
  const cs = G.ControllerStore || G.controllerStore;
  const attempts = [];
  const out = { controllers: [], deckIndex: null, source: "none", attempts, controllerStoreShape: null };
  let list = null;
  if (!cs) {
    out.error = "ControllerStore / controllerStore is " + typeof cs;
    out.shape = { globalsMatchingController: globalsMatching(/controller/i) };
  } else {
    out.controllerStoreShape = shape(cs, /controller|type/i);
    if (typeof cs.GetControllers === "function") {
      try {
        const r = cs.GetControllers();
        list = asList(r);
        attempts.push("controllerStore.GetControllers() -> " + (list ? (Array.isArray(r) ? "array" : "iterable") + " of " + list.length : typeof r));
      } catch (e) { attempts.push("controllerStore.GetControllers() threw " + errText(e)); }
    } else attempts.push("controllerStore.GetControllers is " + typeof cs.GetControllers);
    if (list === null) {
      for (const k of ["m_rgControllers", "controllers", "m_controllers"]) {
        const v = asList(cs[k]);
        if (v) { list = v; attempts.push("controllerStore." + k + " -> list of " + v.length); break; }
        attempts.push("controllerStore." + k + " is " + typeof cs[k]);
      }
    }
  }
  for (const c of list || []) {
    const typeEnum = c && c.eControllerType;
    let typeString = null;
    let typeStringSource = "none";
    const tryFn = (label, fn, self) => {
      if (typeString !== null || typeof fn !== "function") return;
      try {
        const r = fn.call(self, typeEnum);
        if (typeof r === "string") { typeString = r; typeStringSource = label; }
        else attempts.push(label + "(" + typeEnum + ") -> " + typeof r);
      } catch (e) { attempts.push(label + "(" + typeEnum + ") threw " + errText(e)); }
    };
    tryFn("controllerStore.GetControllerTypeString", cs && cs.GetControllerTypeString, cs);
    const inp = G.SteamClient && G.SteamClient.Input;
    tryFn("SteamClient.Input.GetControllerTypeString", inp && inp.GetControllerTypeString, inp);
    if (typeString === null && typeEnum === NEPTUNE_ENUM) {
      typeString = NEPTUNE;
      typeStringSource = "enum fallback (eControllerType === " + NEPTUNE_ENUM + ")";
    }
    const index = (c && typeof c.nControllerIndex === "number") ? c.nControllerIndex
      : (c && typeof c.unControllerIndex === "number") ? c.unControllerIndex : null;
    out.controllers.push({ index, typeEnum: safe(typeEnum, 1), typeString, typeStringSource, name: c && c.strName, raw: safe(c, 2) });
    if (out.deckIndex === null && typeString === NEPTUNE && index !== null) {
      out.deckIndex = index;
      out.source = typeStringSource;
    }
  }
  return out;
}
// The controller indices to probe when the Deck's index was not confirmed by
// type: every listed controller index, else the measured fallback 15. The
// result rows carry indexConfirmed:false so they can be told apart.
function indexPlan(controllers, override) {
  if (typeof override === "number") {
    return { indices: [override], confirmed: true, source: "override (--controller-index)" };
  }
  if (controllers.deckIndex !== null) {
    return { indices: [controllers.deckIndex], confirmed: true, source: controllers.source };
  }
  const listed = [];
  for (const c of controllers.controllers) {
    if (typeof c.index === "number" && listed.indexOf(c.index) < 0) listed.push(c.index);
  }
  if (listed.length) return { indices: listed, confirmed: false, source: "index not confirmed by type (every listed controller index)" };
  return { indices: [FALLBACK_INDEX], confirmed: false, source: "index not confirmed by type (no controller listed; measured fallback " + FALLBACK_INDEX + ")" };
}
async function getConfig(input, appid, idx) {
  if (typeof input.GetConfigForAppAndController !== "function") {
    return { error: "GetConfigForAppAndController is " + typeof input.GetConfigForAppAndController, shape: shape(input, /config/i) };
  }
  try { return safe(await input.GetConfigForAppAndController(appid, idx)); }
  catch (e) { return { error: errText(e) }; }
}
async function candidates(input, appid, idx, waitMs) {
  const reg = input.RegisterForControllerConfigInfoMessages;
  const query = input.QueryControllerConfigsForApp;
  const out = { registerLength: null, queryLength: null, messages: [], flat: [] };
  if (typeof reg !== "function" || typeof query !== "function") {
    out.error = "RegisterForControllerConfigInfoMessages is " + typeof reg + ", QueryControllerConfigsForApp is " + typeof query;
    out.shape = shape(input, /Register|Query/i);
    return out;
  }
  out.registerLength = reg.length;
  out.queryLength = query.length;
  let handle = null;
  try {
    // Spec 2.2 writes (appId, cb); @decky/ui 4.12 types it as (cb). The typed form is used here.
    handle = reg.call(input, (msgs) => {
      out.messages.push(safe(msgs, 3));
      if (Array.isArray(msgs)) {
        for (const m of msgs) {
          // appID says which query the message answers: the subscription is global and
          // a late message for the previous appid lands in this batch.
          out.flat.push({ appID: m && m.appID, nControllerType: m && m.nControllerType, strName: m && m.strName,
            URL: m && m.URL, Title: m && m.Title, publishedFileID: m && m.publishedFileID,
            bOfficial: m && m.bOfficial, eExportType: m && m.eExportType, bSelected: m && m.bSelected,
            bPersonalQueryDone: m && m.bPersonalQueryDone });
        }
      }
    });
    out.registerReturned = ret(handle);
  } catch (e) { out.error = "register threw " + errText(e); return out; }
  try { out.queryReturned = ret(await query.call(input, appid, idx, false)); }
  catch (e) { out.queryError = errText(e); }
  await sleep(waitMs);
  try {
    if (handle && typeof handle.unregister === "function") handle.unregister();
    else if (typeof handle === "function") handle();
    out.unregistered = true;
  } catch (e) { out.unregisterError = errText(e); }
  return out;
}
"""

JS_BODY: dict[str, str] = {
    "ping": r"""
return { pong: true, hasSteamClient: typeof G.SteamClient !== "undefined" };
""",
    "v1": r"""
const result = { probe: "v1", appids: PARAMS.appids, controllers: findControllers(), configs: {}, candidates: {} };
const si = steamInput();
if (!si.input) { result.error = si.error; result.shape = si.shape; return result; }
result.inputShape = shape(si.input, /config/i);
const plan = indexPlan(result.controllers, PARAMS.controller_index);
result.indexPlan = plan;
if (!plan.confirmed) result.warning = "deck controller index not found by type; probing " + JSON.stringify(plan.indices) + " (" + plan.source + ")";
for (const appid of PARAMS.appids) {
  const byIndex = {};
  for (const idx of plan.indices) byIndex[idx] = await getConfig(si.input, appid, idx);
  result.configs[appid] = { label: overviewLabel(appid), index: plan.indices[0], indexConfirmed: plan.confirmed,
    indexSource: plan.source, config: byIndex[plan.indices[0]], byIndex };
}
for (const appid of PARAMS.appids) {
  result.candidates[appid] = await candidates(si.input, appid, plan.indices[0], PARAMS.candidate_wait_ms);
  result.candidates[appid].index = plan.indices[0];
  result.candidates[appid].indexConfirmed = plan.confirmed;
}
return result;
""",
    "v2": r"""
const appid = PARAMS.shortcut;
const url = PARAMS.url;
const result = { probe: "v2", shortcut: appid, url, restore: PARAMS.restore, controllers: findControllers() };
// 0x80000000 is hardcoded here, never read from PARAMS: a missing or wrong
// parameter must not be able to unlock a real game. Runner.v2 checks the
// same bound before anything is evaluated.
if (appid < 0x80000000) { result.error = "refused in page: appid below 0x80000000"; return result; }
const si = steamInput();
if (!si.input) { result.error = si.error; result.shape = si.shape; return result; }
const plan = indexPlan(result.controllers, PARAMS.controller_index);
const idx = plan.indices[0];
result.index = idx;
result.indexConfirmed = plan.confirmed;
result.indexSource = plan.source;
if (!plan.confirmed) result.warning = "deck controller index not found by type; using index " + idx + " (" + plan.source + ")";
result.label = overviewLabel(appid);
result.before = await getConfig(si.input, appid, idx);
if (typeof si.input.SetSelectedConfigForApp !== "function") {
  result.error = "SetSelectedConfigForApp is " + typeof si.input.SetSelectedConfigForApp;
  result.shape = shape(si.input, /Selected|Config/i);
  return result;
}
try { result.setReturned = ret(await si.input.SetSelectedConfigForApp(appid, idx, url, false, SELECTION_USER)); }
catch (e) { result.setError = errText(e); }
await sleep(PARAMS.readback_wait_ms);
result.after = await getConfig(si.input, appid, idx);
result.stuck = !!(result.after && result.after.URL === url);
if (PARAMS.restore) {
  const prev = result.before && result.before.URL;
  if (typeof prev === "string" && prev) {
    try { result.restoreReturned = ret(await si.input.SetSelectedConfigForApp(appid, idx, prev, false, SELECTION_USER)); }
    catch (e) { result.restoreError = errText(e); }
    await sleep(PARAMS.readback_wait_ms);
    result.afterRestore = await getConfig(si.input, appid, idx);
    result.restored = !!(result.afterRestore && result.afterRestore.URL === prev);
  } else {
    result.restoreError = "no previous URL to restore (before.URL is " + typeof prev + ")";
  }
}
return result;
""",
    "v3_shutdown": r"""
const user = G.SteamClient && G.SteamClient.User;
if (!user || typeof user.StartShutdown !== "function") {
  return { error: "SteamClient.User.StartShutdown is " + (user ? typeof user.StartShutdown : "unreachable (User is " + typeof user + ")"),
           shape: user ? shape(user, /Shutdown|Restart/i) : { globalsMatchingSteam: globalsMatching(/steam/i) } };
}
try { return { called: true, returned: ret(user.StartShutdown(false)) }; }
catch (e) { return { called: true, error: errText(e) }; }
""",
    "v4": r"""
const result = { probe: "v4" };
const cs = G.collectionStore;
if (!cs) {
  result.error = "collectionStore is " + typeof cs;
  result.shape = { globalsMatchingCollectionOrStore: globalsMatching(/collection|store/i) };
} else {
  const coll = cs.allAppsCollection;
  if (!coll) {
    result.error = "collectionStore.allAppsCollection is " + typeof coll;
    result.shape = shape(cs, /app|coll/i);
  } else {
    let apps = null;
    try { apps = coll.allApps; } catch (e) { result.allAppsGetterError = errText(e); }
    const arr = Array.isArray(apps) ? apps : (apps && typeof apps[Symbol.iterator] === "function") ? Array.from(apps) : null;
    if (!arr) {
      result.error = "allAppsCollection.allApps is " + typeof apps;
      result.shape = shape(coll, /app/i);
    } else {
      result.total = arr.length;
      const hist = {};
      for (const a of arr) { const t = String(a && a.app_type); hist[t] = (hist[t] || 0) + 1; }
      result.appTypeHistogram = hist;
      result.first20 = arr.slice(0, 20).map((a) => ({ appid: a && a.appid, display_name: a && a.display_name, app_type: a && a.app_type, gameid: a && a.gameid }));
      // Every shortcut in the library (appid >= 0x80000000), so the operator can find the throwaway one for v2/v5.
      result.shortcuts = arr.filter((a) => a && typeof a.appid === "number" && a.appid >= 2147483648).slice(0, 100)
        .map((a) => ({ appid: a.appid, display_name: a.display_name, app_type: a.app_type, gameid: a.gameid }));
      if (arr.length) result.appShape = shape(arr[0]);
    }
  }
}
const app = G.App;
const raw = app && app.m_CurrentUser && app.m_CurrentUser.strSteamID;
result.strSteamID = safe(raw, 1);
result.strSteamIDType = typeof raw;
if (typeof raw === "string" && /^\d+$/.test(raw)) {
  result.steamid3 = (BigInt(raw) - BigInt("76561197960265728")).toString();
} else {
  result.steamidError = "App.m_CurrentUser.strSteamID is not a numeric string";
  result.appShape = shape(app, /user/i);
  result.currentUserShape = shape(app && app.m_CurrentUser);
}
return result;
""",
    "v5": r"""
const appid = PARAMS.shortcut;
const result = { probe: "v5", shortcut: appid, run: PARAMS.run };
const store = G.appStore;
if (!store) { result.error = "appStore is " + typeof store; result.shape = { globalsMatchingStore: globalsMatching(/store/i) }; return result; }
if (typeof store.GetAppOverviewByAppID !== "function") {
  result.error = "appStore.GetAppOverviewByAppID is " + typeof store.GetAppOverviewByAppID;
  result.shape = shape(store, /overview/i);
  return result;
}
let overview = null;
try { overview = store.GetAppOverviewByAppID(appid); } catch (e) { result.error = "GetAppOverviewByAppID threw " + errText(e); return result; }
if (!overview) { result.error = "GetAppOverviewByAppID returned " + String(overview); return result; }
result.overview = { appid: overview.appid, display_name: overview.display_name, app_type: overview.app_type,
  gameid: overview.gameid, gameidType: typeof overview.gameid,
  BIsShortcut: typeof overview.BIsShortcut === "function" ? safe(overview.BIsShortcut()) : "n/a" };
result.overviewShape = shape(overview);
if (!PARAMS.run) return result;
const apps = G.SteamClient && G.SteamClient.Apps;
if (!apps || typeof apps.RunGame !== "function") {
  result.error = "SteamClient.Apps.RunGame is " + (apps ? typeof apps.RunGame : "unreachable (Apps is " + typeof apps + ")");
  result.shape = apps ? shape(apps, /run|launch/i) : { globalsMatchingSteam: globalsMatching(/steam/i) };
  return result;
}
try { result.runReturned = ret(apps.RunGame(overview.gameid, "", -1, 100)); result.ran = true; }
catch (e) { result.runError = errText(e); }
return result;
""",
}


def build_expression(name: str, params: dict[str, Any] | None = None) -> str:
    """The full JavaScript expression for one probe: an async IIFE whose
    promise resolves to a JSON string (a string survives returnByValue even
    when the page objects would not)."""
    if name not in JS_BODY:
        raise KeyError(name)
    return (
        "(async () => {\n"
        + JS_PRELUDE
        + "\nconst PARAMS = "
        + json.dumps(params or {})
        + ";\n"
        + JS_BODY[name]
        + "\n})().then((r) => JSON.stringify(r), (e) => JSON.stringify({ error: 'top-level: ' + (e && e.message ? e.name + ': ' + e.message : String(e)), stack: e && e.stack }))"
    )


# ---------------------------------------------------------------------------
# DevTools transport
# ---------------------------------------------------------------------------


def _websockets_connect() -> Callable[..., Any]:
    """The lazily imported ``connect``; ProbeError with the venv hint when the
    package is missing."""
    try:
        import websockets  # noqa: F401 - lazy, so --help and tests need no venv
    except ImportError as exc:
        raise ProbeError(VENV_HINT) from exc
    try:
        from websockets.asyncio.client import connect  # websockets >= 13
    except ImportError:  # pragma: no cover - older websockets
        connect = websockets.connect  # type: ignore[attr-defined]
    return connect


def _websockets_exception_class() -> type[Exception]:
    """The package's base exception (handshake failures such as InvalidStatus
    and InvalidMessage are neither OSError nor ConnectionClosed)."""
    try:
        from websockets.exceptions import WebSocketException
    except ImportError:  # pragma: no cover - only reachable after connect imported
        return ()  # type: ignore[return-value]
    return WebSocketException


class DevTools:
    """The real CEF DevTools connection. Tests replace it with a fake that
    has the same three methods."""

    def __init__(self, host: str = DEFAULT_HOST, port: int = DEFAULT_PORT, timeout_s: float = 10.0) -> None:
        self.host = host
        self.port = port
        self.timeout_s = timeout_s

    def targets(self) -> list[dict[str, Any]]:
        url = f"http://{self.host}:{self.port}/json"
        try:
            with urllib.request.urlopen(url, timeout=self.timeout_s) as resp:
                data = json.loads(resp.read().decode("utf-8"))
        except urllib.error.URLError as exc:
            reason = exc.reason
            if isinstance(reason, OSError) and reason.errno in (errno.ECONNREFUSED, errno.EHOSTUNREACH, errno.ENETUNREACH):
                raise PortClosed(str(reason)) from exc
            if isinstance(reason, ConnectionRefusedError):
                raise PortClosed(str(reason)) from exc
            raise ProbeError(f"GET {url} failed: {reason}") from exc
        except ConnectionRefusedError as exc:
            raise PortClosed(str(exc)) from exc
        except (OSError, ValueError) as exc:
            raise ProbeError(f"GET {url} failed: {exc}") from exc
        if not isinstance(data, list):
            raise ProbeError(f"GET {url} returned {type(data).__name__}, expected a list of targets")
        return data

    def shared_js_context(self) -> dict[str, Any]:
        targets = self.targets()
        for t in targets:
            if t.get("title") == "SharedJSContext" and t.get("webSocketDebuggerUrl"):
                return t
        titles = [t.get("title") for t in targets]
        raise ProbeError(f"no SharedJSContext target with a webSocketDebuggerUrl; targets: {titles}")

    def evaluate(self, name: str, params: dict[str, Any] | None = None, *, timeout_s: float = 90.0) -> Any:
        target = self.shared_js_context()
        expression = build_expression(name, params)
        return asyncio.run(self._evaluate_ws(target["webSocketDebuggerUrl"], expression, timeout_s))

    async def _evaluate_ws(self, ws_url: str, expression: str, timeout_s: float) -> Any:
        connect = _websockets_connect()
        ws_exception = _websockets_exception_class()
        message = {
            "id": 1,
            "method": "Runtime.evaluate",
            "params": {"expression": expression, "awaitPromise": True, "returnByValue": True},
        }
        try:
            async with connect(ws_url, max_size=None) as ws:
                await ws.send(json.dumps(message))
                while True:
                    raw = await asyncio.wait_for(ws.recv(), timeout=timeout_s)
                    reply = json.loads(raw)
                    if reply.get("id") == 1:
                        break
        except asyncio.TimeoutError as exc:
            raise ProbeError(f"Runtime.evaluate produced no reply within {timeout_s} s") from exc
        except OSError as exc:
            raise ProbeError(f"websocket {ws_url}: {exc}") from exc
        except ws_exception as exc:
            # ConnectionClosed*, InvalidStatus (CEF answered the upgrade with 500/404),
            # InvalidMessage (EOF mid-handshake): all plausible while Steam restarts.
            raise ProbeError(f"websocket {ws_url}: {type(exc).__name__}: {exc}") from exc
        except ValueError as exc:
            raise ProbeError(f"websocket {ws_url}: bad reply: {exc}") from exc
        if "error" in reply:
            raise ProbeError(f"Runtime.evaluate error: {reply['error']}")
        result = reply.get("result", {})
        if result.get("exceptionDetails"):
            raise ProbeError(f"Runtime.evaluate threw: {json.dumps(result['exceptionDetails'])[:2000]}")
        value = result.get("result", {}).get("value")
        if isinstance(value, str):
            try:
                return json.loads(value)
            except ValueError:
                return {"raw": value}
        return value


# ---------------------------------------------------------------------------
# V3 helpers: the pgrep watch and the gap computation
# ---------------------------------------------------------------------------

SAMPLE_RE = re.compile(r"sample t=(?P<t>\d+) rc=(?P<rc>-?\d+) pids=(?P<pids>\S+)")


def now_iso() -> str:
    return datetime.datetime.now().astimezone().isoformat(timespec="milliseconds")


def fmt_pids(pids: list[int]) -> str:
    return ",".join(str(p) for p in pids) if pids else "-"


def run_pgrep(*args: str) -> tuple[int, str]:
    """Run pgrep with the given arguments; (exit status, stdout+stderr text)."""
    try:
        proc = subprocess.run(["pgrep", *args], capture_output=True, text=True, timeout=5)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return -1, f"pgrep failed: {exc}"
    text = proc.stdout.strip()
    if proc.stderr.strip():
        text += " stderr=" + proc.stderr.strip()
    return proc.returncode, text


def read_cmdline(pid: int) -> str:
    try:
        with open(f"/proc/{pid}/cmdline", "rb") as fh:
            raw = fh.read()
    except OSError as exc:
        return f"<unreadable: {exc}>"
    return raw.replace(b"\0", b" ").decode(errors="replace").strip() or "<empty>"


def parse_pids(text: str) -> list[int]:
    return sorted(int(p) for p in text.split() if p.isdigit())


PGREP_OK_RCS = (0, 1)  # 0 matched, 1 no match; anything else (2, 3, -1) is a pgrep failure, not "Steam gone"


def sample_pids(rc: int, out: str) -> list[int] | None:
    """The pids of one sample, or None for an error sample (pgrep itself
    failed: rc 2/3, or -1 when it could not be run), which says nothing about
    whether Steam is running."""
    if rc not in PGREP_OK_RCS:
        return None
    return parse_pids(out)


def compute_gaps(samples: list[tuple[int, list[int] | None]]) -> list[dict[str, Any]]:
    """Every run of empty samples: from the first empty sample to the first
    non-empty one after it. ``back_at_ms``/``gap_ms`` are None when the run
    is still empty at the end of the recording. Error samples (pids None,
    pgrep failed) are skipped: they neither open nor close a gap."""
    gaps: list[dict[str, Any]] = []
    open_gap: dict[str, Any] | None = None
    for t_ms, pids in samples:
        if pids is None:
            continue
        if not pids:
            if open_gap is None:
                open_gap = {"empty_at_ms": t_ms, "back_at_ms": None, "gap_ms": None, "empty_samples": 0}
            open_gap["empty_samples"] += 1
        elif open_gap is not None:
            open_gap["back_at_ms"] = t_ms
            open_gap["gap_ms"] = t_ms - open_gap["empty_at_ms"]
            gaps.append(open_gap)
            open_gap = None
    if open_gap is not None:
        gaps.append(open_gap)
    return gaps


def parse_watch_log(text: str) -> list[tuple[int, list[int] | None]]:
    """Samples from a recorded watch log (this runner's or the probe
    plugin's): every line carrying ``sample t=<ms> rc=<n> pids=<a,b|-|error>``.
    A sample whose rc is not 0 or 1 is an error sample (pids None)."""
    samples: list[tuple[int, list[int] | None]] = []
    for line in text.splitlines():
        m = SAMPLE_RE.search(line)
        if not m:
            continue
        pids_text = m.group("pids")
        rc = int(m.group("rc"))
        pids: list[int] | None
        if rc not in PGREP_OK_RCS or pids_text == "error":
            pids = None
        else:
            pids = [] if pids_text == "-" else sorted(int(p) for p in pids_text.split(",") if p.isdigit())
        samples.append((int(m.group("t")), pids))
    return samples


def watch_steam(
    duration_s: float,
    interval_ms: int,
    *,
    pgrep: Callable[..., tuple[int, str]] = run_pgrep,
    clock: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], None] = time.sleep,
    cmdline: Callable[[int], str] = read_cmdline,
    log: Callable[[str], None] | None = None,
    stop: threading.Event | None = None,
) -> dict[str, Any]:
    """Sample ``pgrep -x steam`` every ``interval_ms`` for ``duration_s``.
    Every sample is logged; a state change also logs ``pgrep -a -x steam``
    and each pid's /proc cmdline. A pgrep failure (rc not 0/1) is an error
    sample: logged as ``pids=error``, counted, and excluded from the gaps.
    Returns samples, changes, gaps and the error count."""
    samples: list[tuple[int, list[int] | None]] = []
    changes: list[dict[str, Any]] = []
    start = clock()
    last_state: list[int] | str | None = None  # pids, "error", or None before the first sample
    max_poll_ms = 0
    prev_t = 0
    errors = 0
    emit = log or (lambda line: None)
    emit(f"steam-watch start duration_s={duration_s} interval_ms={interval_ms} uid={os.getuid()}")
    while True:
        t_ms = round((clock() - start) * 1000)
        if t_ms >= duration_s * 1000 or (stop is not None and stop.is_set()):
            break
        rc, out = pgrep("-x", "steam")
        pids = sample_pids(rc, out)
        samples.append((t_ms, pids))
        if len(samples) > 1:
            max_poll_ms = max(max_poll_ms, t_ms - prev_t)
        prev_t = t_ms
        state: list[int] | str = "error" if pids is None else pids
        shown = "error" if pids is None else fmt_pids(pids)
        if pids is None:
            errors += 1
        if state != last_state:
            was = "none" if last_state is None else ("error" if last_state == "error" else fmt_pids(last_state))
            if pids is None:
                emit(f"steam-watch change sample t={t_ms} rc={rc} pids=error (was pids={was}) pgrep-error=[{out.replace(chr(10), '; ') or '-'}]")
                changes.append({"t_ms": t_ms, "wall": now_iso(), "rc": rc, "pids": [], "error": out, "pgrep_a": "", "cmdline": "-"})
            else:
                rc_a, out_a = pgrep("-a", "-x", "steam")
                cmdlines = "; ".join(f"{p}: {cmdline(p)}" for p in pids) or "-"
                emit(
                    f"steam-watch change sample t={t_ms} rc={rc} pids={shown} (was pids={was}) "
                    f"pgrep-a(rc={rc_a})=[{out_a.replace(chr(10), '; ') or '-'}] cmdline=[{cmdlines}]"
                )
                changes.append({"t_ms": t_ms, "wall": now_iso(), "rc": rc, "pids": pids, "pgrep_a": out_a, "cmdline": cmdlines})
            last_state = state
        else:
            emit(f"steam-watch sample t={t_ms} rc={rc} pids={shown}")
        elapsed_ms = (clock() - start) * 1000 - t_ms
        sleep(max(0.0, (interval_ms - elapsed_ms) / 1000))
    gaps = compute_gaps(samples)
    total_ms = int((clock() - start) * 1000)
    emit(
        f"steam-watch summary duration_ms={total_ms} samples={len(samples)} changes={len(changes)} "
        f"gaps={len(gaps)} pgrep_errors={errors} max_poll_ms={max_poll_ms}"
    )
    if errors:
        emit(f"steam-watch warning: {errors} sample(s) where pgrep itself failed (rc not 0/1); they are excluded from the gaps")
    for i, gap in enumerate(gaps, 1):
        if gap["back_at_ms"] is None:
            emit(f"steam-watch gap #{i}: empty at t={gap['empty_at_ms']} still empty at the end (gap open) empty_samples={gap['empty_samples']}")
        else:
            emit(f"steam-watch gap #{i}: empty at t={gap['empty_at_ms']} non-empty at t={gap['back_at_ms']} gap_ms={gap['gap_ms']} empty_samples={gap['empty_samples']}")
    if not gaps:
        emit("steam-watch gap: none (pgrep -x steam never came back empty)")
    return {
        "samples": len(samples),
        "pgrep_errors": errors,
        "duration_ms": total_ms,
        "max_poll_ms": max_poll_ms,
        "changes": changes,
        "gaps": gaps,
        "raw_samples": samples,
    }


# ---------------------------------------------------------------------------
# Results file and the markdown table
# ---------------------------------------------------------------------------


def load_results(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8") or "[]")
    except ValueError as exc:
        raise ProbeError(f"{path} is not valid JSON: {exc}") from exc
    if not isinstance(data, list):
        raise ProbeError(f"{path} must hold a JSON list")
    return data


def append_result(path: Path, entry: dict[str, Any]) -> None:
    data = load_results(path)
    data.append(entry)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def _txt(cell: Any) -> str:
    return cell if isinstance(cell, str) else json.dumps(cell)


HOME_RE = re.compile(r"/home/[^/\s\"'|;:]+")


def redact_paths(text: str, home: str | None = None) -> str:
    """``$HOME`` and any ``/home/<name>`` become ``~``, so a cmdline or
    ``pgrep -a`` line can go into the committed table (spec §5: no absolute
    home paths in the repo). The raw text stays in probe-results.json.

    The home substitution only fires at a path boundary (the home directory
    followed by ``/`` or the end of the string), so ``/home/deckard`` is not
    mangled into ``~ard`` when home is ``/home/deck`` -- HOME_RE still
    redacts it, as another user's home. An empty home, ``~`` or ``/`` is
    skipped: there is no prefix worth substituting and ``/`` would match
    every absolute path."""
    home = home if home is not None else os.path.expanduser("~")
    home = home.rstrip("/")
    if home and home != "~" and home.startswith("/"):
        text = re.sub(re.escape(home) + r"(?=/|$)", "~", text)
    return HOME_RE.sub("~", text)


def _md(cell: Any) -> str:
    """One table cell: pipes and newlines escaped (done once, in render_markdown)."""
    return _txt(cell).replace("|", "\\|").replace("\n", " ")


def steamid3_verdict(r: dict[str, Any]) -> str:
    """The V4 steamid3 row as a verdict, never the value: the table is pasted
    into PROBES.md and committed, and a Steam ID is user-specific."""
    sid = r.get("steamid3")
    if not isinstance(sid, str) or not sid.isdigit():
        return f"not derived (strSteamID is {r.get('strSteamIDType', 'absent')})"
    check = r.get("userdata_check") or {}
    match = check.get("match")
    verdict = "yes" if match is True else "no" if match is False else "unchecked"
    if match is False and check.get("folders") is not None:
        verdict += f" ({check['folders']} numeric folder(s) under userdata)"
    return f"numeric, {len(sid)} digits; matches a ~/.local/share/Steam/userdata/<id> folder: {verdict}"


def check_userdata_folder(steamid3: str, steam_root: Path | None = None) -> dict[str, Any]:
    """Whether ``<steam_root>/userdata/<steamid3>`` exists (the CLI's own
    steamid3 check, §3.4.1). Runs on the Deck; the result carries only the
    verdict and the folder count, never the id."""
    root = steam_root if steam_root is not None else Path.home() / ".local" / "share" / "Steam"
    userdata = root / "userdata"
    if not userdata.is_dir():
        return {"match": None, "folders": None, "note": "no userdata directory under the Steam root"}
    try:
        folders = [p.name for p in userdata.iterdir() if p.is_dir() and p.name.isdigit()]
    except OSError as exc:
        return {"match": None, "folders": None, "note": f"userdata unreadable: {exc}"}
    return {"match": steamid3 in folders, "folders": len(folders)}


def _candidate_counts(flat: list[Any], appid: Any) -> str:
    """Candidates are attributed by the message's own appID (the
    subscription is global): matched / without appID / for other appids."""
    want = str(appid)
    matched = unknown = other = 0
    for m in flat:
        got = m.get("appID") if isinstance(m, dict) else None
        if got is None:
            unknown += 1
        elif str(got) == want:
            matched += 1
        else:
            other += 1
    text = f"{matched} candidate(s) for this appid"
    if unknown:
        text += f", {unknown} without appID"
    if other:
        text += f", {other} for other appids"
    return text


def _rows_for(entry: dict[str, Any]) -> list[tuple[str, str, str, str, str]]:
    probe = entry.get("probe", "?")
    r = entry.get("result") or {}
    err = r.get("error") if isinstance(r, dict) else None
    note_err = f"error: {err}" if err else ""
    rows: list[tuple[str, str, str, str, str]] = []
    if probe == "v1":
        ctl = r.get("controllers") or {}
        rows.append(("V1", "Deck controller index by type", "found (deckyemu measured 15)", _txt(ctl.get("deckIndex")), _txt(ctl.get("source", note_err))))
        for appid, item in (r.get("configs") or {}).items():
            cands = (r.get("candidates") or {}).get(str(appid)) or (r.get("candidates") or {}).get(appid) or {}
            counts = _candidate_counts(cands.get("flat") or [], appid)
            confirmed = item.get("indexConfirmed", True)
            by_index = item.get("byIndex") if isinstance(item.get("byIndex"), dict) else None
            per_index = list(by_index.items()) if by_index and not confirmed else [(item.get("index"), item.get("config"))]
            for idx, cfg in per_index:
                cfg = cfg or {}
                url = cfg.get("URL") if isinstance(cfg, dict) else None
                case = f"{appid} ({item.get('label', '')})"
                if not confirmed:
                    case += f" at index {idx} (index not confirmed by type)"
                cfg_err = cfg.get("error", "") if isinstance(cfg, dict) else ""
                rows.append(("V1", case, "workshop:// | template:// | localconfig:// or autosave:// | default://", _txt(url if url is not None else cfg), "; ".join(x for x in (counts, cfg_err) if x)))
        if not r.get("configs"):
            rows.append(("V1", "configs", "one URL per appid", "-", note_err))
    elif probe == "v2":
        before = r.get("before") or {}
        after = r.get("after") or {}
        notes = [note_err] if note_err else []
        if r.get("setError"):
            notes.append(f"set threw: {r['setError']}")
        if "restored" in r:
            notes.append(f"restored={r['restored']}")
        rows.append(("V2", f"{r.get('shortcut')} ({r.get('label', '')}) <- {r.get('url')}", "after.URL == url (sticks on a same-named shortcut; unknown otherwise)", f"stuck={r.get('stuck')} before={_txt(before.get('URL') if isinstance(before, dict) else before)} after={_txt(after.get('URL') if isinstance(after, dict) else after)}", "; ".join(notes)))
    elif probe == "v3":
        gaps = r.get("gaps") or []
        errors = r.get("pgrep_errors") or 0
        err_note = f"; {errors} pgrep error sample(s) excluded" if errors else ""
        if not gaps:
            rows.append(("V3", "gap empty -> non-empty", "> 500 ms (seconds)", "no gap recorded", _txt(r.get("note", note_err)) + err_note))
        for i, gap in enumerate(gaps, 1):
            observed = "still empty at the end" if gap.get("gap_ms") is None else f"{gap['gap_ms']} ms"
            rows.append(("V3", f"gap {i} (empty at t={gap.get('empty_at_ms')} ms)", "> 500 ms (seconds)", observed, f"steam_back={r.get('steam_back')} back_after_ms={r.get('back_after_ms')} (from the watch start, not the restart time; read the gap){err_note}"))
        # cmdline / pgrep -a carry absolute home paths: redacted here, raw in probe-results.json
        identity = "; ".join(redact_paths(str(c.get("cmdline"))) for c in (r.get("changes") or [])[:4]) or "-"
        rows.append(("V3", "process identity on change", "real client, not a wrapper script", identity, f"{len(r.get('changes') or [])} change(s)"))
    elif probe == "v4":
        first20 = r.get("first20") or []
        keys_ok = bool(first20) and all(isinstance(a, dict) and all(k in a for k in ("appid", "display_name", "app_type")) for a in first20)
        # no titles and no id in the table: it is pasted into the repo
        rows.append(("V4", "allAppsCollection.allApps", "total > 0; first 20 carry appid, display_name, app_type", f"total={r.get('total')} first20={len(first20)} entries; keys present: {'yes' if keys_ok else 'no'}", _txt(r.get("appTypeHistogram", note_err))))
        rows.append(("V4", "steamid3 from App.m_CurrentUser.strSteamID", "numeric, equals the userdata/<id> folder", steamid3_verdict(r), _txt(r.get("steamidError", ""))))
    elif probe == "v5":
        ov = r.get("overview") or {}
        rows.append(("V5", f"{r.get('shortcut')} ({ov.get('display_name', '')})", "gameid is a string and GetAppOverviewByAppID exists", f"gameid={_txt(ov.get('gameid'))} type={ov.get('gameidType')} app_type={ov.get('app_type')}", f"ran={r.get('ran', False)} {note_err} {r.get('runError', '')}".strip()))
    else:
        rows.append((probe, "-", "-", _txt(r), note_err))
    return rows


def render_markdown(results: list[dict[str, Any]]) -> str:
    lines = ["| probe | case | expected | observed | notes |", "|---|---|---|---|---|"]
    for entry in results:
        when = entry.get("when", "")
        for probe, case, expected, observed, notes in _rows_for(entry):
            notes = f"{notes} ({when})".strip() if when else notes
            lines.append(f"| {probe} | {_md(case)} | {_md(expected)} | {_md(observed)} | {_md(notes)} |")
    if len(lines) == 2:
        lines.append("| - | no results yet | - | - | run the probes first |")
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# The runner
# ---------------------------------------------------------------------------


class V3Log:
    """The v3 pgrep log: one line at a time, from either thread.

    ``Runner.v3`` writes from the main thread while the sampler thread
    writes every sample, to one ``TextIOWrapper``. This file is the raw
    data :func:`parse_watch_log` recovers the V3 gaps from, so whole lines
    matter more than a lock costs.

    Writing is also a no-op once :meth:`close` has run: ``v3`` joins the
    sampler with a timeout and then closes the file, so a sampler that
    outlived the join must not raise ``ValueError: I/O operation on closed
    file`` -- an irreversible shutdown has already happened and the record
    still has to be written.
    """

    def __init__(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        self._fh = open(path, "a", encoding="utf-8")  # noqa: SIM115 - closed by close()
        self._lock = threading.Lock()
        self._closed = False

    def __call__(self, line: str) -> None:
        stamped = f"{now_iso()} {line}"
        with self._lock:
            if self._closed:
                return
            self._fh.write(stamped + "\n")
            self._fh.flush()

    def close(self) -> None:
        """Idempotent; after it, writes are dropped instead of raising."""
        with self._lock:
            self._closed = True
            self._fh.close()


class Runner:
    def __init__(
        self,
        devtools: Any,
        *,
        out: TextIO,
        err: TextIO,
        results_path: Path,
        v3_log_path: Path = DEFAULT_V3_LOG,
        pgrep: Callable[..., tuple[int, str]] = run_pgrep,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
        cmdline: Callable[[int], str] = read_cmdline,
        stdin: TextIO | None = None,
        steam_root: Path | None = None,
    ) -> None:
        self.devtools = devtools
        self.out = out
        self.err = err
        self.results_path = results_path
        self.v3_log_path = v3_log_path
        self.pgrep = pgrep
        self.clock = clock
        self.sleep = sleep
        self.cmdline = cmdline
        self.stdin = stdin if stdin is not None else sys.stdin
        self.steam_root = steam_root  # None = ~/.local/share/Steam (tests point it at a tmp dir)

    # -- helpers --

    def record(self, probe: str, args: dict[str, Any], result: Any) -> dict[str, Any]:
        entry = {"probe": probe, "when": now_iso(), "args": args, "result": result}
        append_result(self.results_path, entry)
        return entry

    def emit(self, entry: dict[str, Any]) -> None:
        self.out.write(json.dumps(entry, indent=2) + "\n")
        self.out.flush()

    # -- probes --

    def v1(self, appids: list[int], candidate_wait_ms: int = 4000, controller_index: int | None = None) -> dict[str, Any]:
        params: dict[str, Any] = {"appids": appids, "candidate_wait_ms": candidate_wait_ms}
        if controller_index is not None:
            params["controller_index"] = controller_index
        result = self.devtools.evaluate("v1", params)
        return self.record("v1", {"appids": appids, "controller_index": controller_index}, result)

    def v2(self, shortcut: int, url: str | None, restore: bool, controller_index: int | None = None) -> dict[str, Any]:
        if not url:
            raise Refused("v2 changes the shortcut's selected layout; pass --url 'workshop://<publishedfileid>' to run it")
        if shortcut < SHORTCUT_APPID_MIN:
            raise Refused(f"v2 refuses appid {shortcut}: below 0x80000000 ({SHORTCUT_APPID_MIN}); it must be a shortcut, never a real game")
        check_workshop_url(url)
        params: dict[str, Any] = {"shortcut": shortcut, "url": url, "restore": restore, "readback_wait_ms": 1000}
        if controller_index is not None:
            params["controller_index"] = controller_index
        result = self.devtools.evaluate("v2", params)
        return self.record("v2", {"shortcut": shortcut, "url": url, "restore": restore, "controller_index": controller_index}, result)

    def v4(self) -> dict[str, Any]:
        result = self.devtools.evaluate("v4", {})
        if isinstance(result, dict) and isinstance(result.get("steamid3"), str) and result["steamid3"].isdigit():
            # checked here, on the Deck, so --markdown can print a verdict instead of the id
            result["userdata_check"] = check_userdata_folder(result["steamid3"], self.steam_root)
        return self.record("v4", {}, result)

    def v5(self, shortcut: int, run: bool) -> dict[str, Any]:
        result = self.devtools.evaluate("v5", {"shortcut": shortcut, "run": run})
        return self.record("v5", {"shortcut": shortcut, "run": run}, result)

    def confirm_v3(self, yes: bool) -> None:
        if yes:
            return
        isatty = getattr(self.stdin, "isatty", lambda: False)()
        if not isatty:
            raise Refused("v3 shuts Steam down (gamescope restarts it); pass --yes to run it non-interactively")
        self.err.write("v3 will call SteamClient.User.StartShutdown(false): Steam exits and gamescope restarts it. Continue? [y/N] ")
        self.err.flush()
        answer = self.stdin.readline().strip().lower()
        if answer not in ("y", "yes"):
            raise Refused("v3 not confirmed")

    def v3(
        self,
        *,
        yes: bool,
        duration_s: float = 90.0,
        interval_ms: int = 100,
        baseline_s: float = 1.0,
        reconnect_timeout_s: float = 120.0,
        reconnect_poll_s: float = 1.0,
    ) -> dict[str, Any]:
        """Shut Steam down, watch ``pgrep -x steam`` across the restart, then
        reconnect to the new client.

        ``gaps`` -- computed from the pgrep samples -- is the V3 measurement.
        ``back_after_ms`` is **not** the restart time: it is measured from the
        start of the watch, and the reconnect only begins after the baseline
        pause plus the full watch, so it is bounded below by
        ``baseline_s + duration_s`` whatever Steam does.

        The shutdown is irreversible, so the v3 record is appended whatever
        happens after the watch starts: a handshake error while Steam
        restarts, or Ctrl-C during the baseline, the shutdown call, the watch
        or the reconnect wait. On an interrupt the watch is stopped, joined
        and whatever it sampled is recorded before the exception is re-raised.
        """
        self.confirm_v3(yes)
        self.devtools.shared_js_context()  # fail early (port closed / no target) before touching anything
        log = V3Log(self.v3_log_path)

        watch: dict[str, Any] = {}
        stop = threading.Event()

        def sampler() -> None:
            watch.update(
                watch_steam(
                    duration_s,
                    interval_ms,
                    pgrep=self.pgrep,
                    clock=self.clock,
                    sleep=self.sleep,
                    cmdline=self.cmdline,
                    log=log,
                    stop=stop,
                )
            )

        result: dict[str, Any] = {
            "probe": "v3",
            "duration_s": duration_s,
            "interval_ms": interval_ms,
            "shutdown": {"sent_at_ms": None, "reply": None, "note": "not sent"},
            "steam_back": False,
            # Measured from the start of the watch, so never less than
            # baseline_s + duration_s. Read the gaps, not this, for V3.
            "back_after_ms": None,
            "reconnect_last_error": "reconnect not attempted",
            "log": str(self.v3_log_path),
        }
        started = self.clock()
        thread = threading.Thread(target=sampler, name="steam-watch", daemon=True)
        thread.start()
        try:
            self.sleep(baseline_s)
            shutdown_at_ms = int((self.clock() - started) * 1000)
            try:
                shutdown = {"sent_at_ms": shutdown_at_ms, "reply": self.devtools.evaluate("v3_shutdown", {}, timeout_s=10)}
            except (ProbeError, PortClosed) as exc:
                # The socket dying right after StartShutdown is the expected outcome.
                shutdown = {"sent_at_ms": shutdown_at_ms, "reply": None, "note": f"no reply (expected if Steam shut down at once): {exc}"}
            result["shutdown"] = shutdown
            log(f"steam-watch shutdown sent t={shutdown_at_ms} reply={json.dumps(shutdown.get('reply'))} note={shutdown.get('note', '')}")
            thread.join()

            try:
                deadline = self.clock() + reconnect_timeout_s
                last_error = ""
                while self.clock() < deadline:
                    try:
                        self.devtools.shared_js_context()
                        ping = self.devtools.evaluate("ping", {}, timeout_s=10)
                        if isinstance(ping, dict) and ping.get("pong"):
                            result["steam_back"] = True
                            result["back_after_ms"] = int((self.clock() - started) * 1000)
                            break
                        last_error = f"ping returned {ping!r}"
                    except (PortClosed, ProbeError) as exc:
                        last_error = str(exc)
                    except Exception as exc:  # noqa: BLE001 - anything else while Steam is half up is "not back yet"
                        last_error = f"{type(exc).__name__}: {exc}"
                        log(f"steam-watch reconnect attempt raised {last_error}")
                    self.sleep(reconnect_poll_s)
                result["reconnect_last_error"] = "" if result["steam_back"] else last_error
                log(f"steam-watch reconnect steam_back={result['steam_back']} back_after_ms={result['back_after_ms']} last_error={result['reconnect_last_error']}")
            except BaseException as exc:
                result["reconnect_last_error"] = f"interrupted: {type(exc).__name__}: {exc}"
                raise
        except BaseException as exc:
            result["interrupted"] = f"{type(exc).__name__}: {exc}"
            log(f"steam-watch interrupted: {type(exc).__name__}: {exc}")
            raise
        finally:
            # Whatever happened, stop the watch, take what it sampled and
            # write the record; the shutdown cannot be undone.
            stop.set()
            thread.join(timeout=max(10.0, interval_ms / 1000 * 20))
            result["samples"] = watch.get("samples")
            result["pgrep_errors"] = watch.get("pgrep_errors", 0)
            result["max_poll_ms"] = watch.get("max_poll_ms")
            result["changes"] = watch.get("changes", [])
            result["gaps"] = watch.get("gaps", [])
            if not result["gaps"]:
                result["note"] = "pgrep -x steam never came back empty during the watch; see the log"
            log.close()
            entry = self.record("v3", {"duration_s": duration_s, "interval_ms": interval_ms}, result)
        return entry


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def parse_appids(text: str) -> list[int]:
    appids: list[int] = []
    for part in re.split(r"[,\s]+", text.strip()):
        if not part:
            continue
        if not part.isdigit() or int(part) <= 0:
            raise argparse.ArgumentTypeError(f"not an appid: {part!r}")
        appids.append(int(part))
    if not appids:
        raise argparse.ArgumentTypeError("no appids given")
    return appids


def positive_int(text: str) -> int:
    if not text.strip().isdigit() or int(text) <= 0:
        raise argparse.ArgumentTypeError(f"not a positive integer: {text!r}")
    return int(text)


def non_negative_int(text: str) -> int:
    if not text.strip().isdigit():
        raise argparse.ArgumentTypeError(f"not a non-negative integer: {text!r}")
    return int(text)


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="run_probes.py",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description=(
            "Run the Moonlight Sync device probes (spec PR-0, V1-V5) against the Steam client\n"
            "over the CEF DevTools port that Decky enables. Run it on the SteamOS machine itself,\n"
            "over SSH, with Steam in Game Mode."
        ),
        epilog=(
            "subcommands:\n"
            "  v1 --appids 1245620,2379780      GetConfigForAppAndController per appid, the Deck controller\n"
            "     [--controller-index N]        index found by type, and the layout candidates per appid\n"
            "  v2 --shortcut APPID --url URL    SetSelectedConfigForApp(shortcut, idx, 'workshop://...', false),\n"
            "     [--restore]                   read back after 1 s; --restore puts the previous URL back.\n"
            "                                   Refuses without --url and refuses any appid below 0x80000000\n"
            "  v3 [--yes]                       log `pgrep -x steam` every 100 ms for 90 s, confirm (or --yes),\n"
            "                                   call StartShutdown(false), report the gaps, reconnect afterwards\n"
            "  v4                               first 20 of collectionStore.allAppsCollection.allApps + steamid3\n"
            "  v5 --shortcut APPID [--run]      appStore.GetAppOverviewByAppID(appid).gameid; --run calls RunGame\n"
            "  all --appids ... --shortcut ...  v1, v4, v5 (no --run); v2 only with --url; v3 last, only with --yes\n"
            "\n"
            "Every subcommand prints one JSON object and appends it to probe-results.json;\n"
            "--markdown renders the PROBES.md results table from that file. The table is redacted\n"
            "(no Steam ID, home paths as ~); the raw values stay in probe-results.json.\n"
            "\n"
            "exit codes: 0 ran, 1 transport failure, 2 refused / usage, 3 DevTools port closed\n"
            "(is Decky installed and is Steam in Game Mode?)\n"
            "\n"
            f"dependency: the websockets package, imported lazily. Create the venv once with\n  {VENV_LINE}\n"
            "and run this script with ~/.cache/msy-probes/bin/python3"
        ),
    )
    p.add_argument("--host", default=DEFAULT_HOST, help="DevTools host (default %(default)s)")
    p.add_argument("--port", type=int, default=DEFAULT_PORT, help="DevTools port (default %(default)s)")
    p.add_argument("--results", type=Path, default=DEFAULT_RESULTS, help="results file (default %(default)s)")
    p.add_argument("--markdown", action="store_true", help="render the PROBES.md results table from the results file and exit")
    sub = p.add_subparsers(dest="probe", metavar="{v1,v2,v3,v4,v5,all}")

    index_help = (
        "use this controller index instead of the one found by type (when the type lookup fails, "
        "v1 probes every listed index, or 15, and marks the rows 'index not confirmed by type')"
    )
    s1 = sub.add_parser("v1", help="layout config per appid + Deck controller index by type")
    s1.add_argument("--appids", type=parse_appids, required=True, help="comma-separated Steam appids")
    s1.add_argument("--candidate-wait-ms", type=positive_int, default=4000, help="how long to collect layout candidates per appid (default %(default)s)")
    s1.add_argument("--controller-index", type=non_negative_int, default=None, help=index_help)

    s2 = sub.add_parser("v2", help="set a workshop:// layout on a SHORTCUT and read it back")
    s2.add_argument("--shortcut", type=positive_int, required=True, help="the shortcut's appid (must be >= 0x80000000)")
    s2.add_argument("--url", help="workshop://<publishedfileid> to select; required to run")
    s2.add_argument("--restore", action="store_true", help="put the previous URL back afterwards")
    s2.add_argument("--controller-index", type=non_negative_int, default=None, help=index_help)

    s3 = sub.add_parser("v3", help="watch pgrep -x steam across StartShutdown(false)")
    s3.add_argument("--yes", action="store_true", help="skip the confirmation prompt")
    s3.add_argument("--duration", type=float, default=90.0, help="watch length in seconds (default %(default)s)")
    s3.add_argument("--interval-ms", type=positive_int, default=100, help="sampling interval (default %(default)s)")
    s3.add_argument("--reconnect-timeout", type=float, default=120.0, help="seconds to wait for Steam to come back (default %(default)s)")

    sub.add_parser("v4", help="first 20 of allAppsCollection.allApps + steamid3")

    s5 = sub.add_parser("v5", help="gameid of a shortcut via appStore; --run launches it")
    s5.add_argument("--shortcut", type=positive_int, required=True, help="the shortcut's appid")
    s5.add_argument("--run", action="store_true", help="call SteamClient.Apps.RunGame(gameid, '', -1, 100)")

    sa = sub.add_parser("all", help="v1, v4, v5 (no --run); v2 only with --url; v3 last and only with --yes")
    sa.add_argument("--appids", type=parse_appids, help="for v1 (skipped without it)")
    sa.add_argument("--shortcut", type=positive_int, help="for v5 and v2 (both skipped without it)")
    sa.add_argument("--url", help="for v2 (skipped without it)")
    sa.add_argument("--restore", action="store_true", help="v2 --restore")
    sa.add_argument("--controller-index", type=non_negative_int, default=None, help="v1/v2 --controller-index")
    sa.add_argument("--yes", action="store_true", help="also run v3, last")
    sa.add_argument("--duration", type=float, default=90.0, help="v3 watch length (default %(default)s)")
    sa.add_argument("--interval-ms", type=positive_int, default=100, help="v3 sampling interval (default %(default)s)")
    sa.add_argument("--reconnect-timeout", type=float, default=120.0, help="v3 reconnect wait (default %(default)s)")
    return p


def main(
    argv: list[str] | None = None,
    *,
    devtools_factory: Callable[[str, int], Any] | None = None,
    out: TextIO | None = None,
    err: TextIO | None = None,
    stdin: TextIO | None = None,
    pgrep: Callable[..., tuple[int, str]] = run_pgrep,
    clock: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], None] = time.sleep,
    cmdline: Callable[[int], str] = read_cmdline,
    v3_log_path: Path | None = None,
    steam_root: Path | None = None,
) -> int:
    out = out or sys.stdout
    err = err or sys.stderr
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.markdown:
        try:
            out.write(render_markdown(load_results(args.results)))
        except ProbeError as exc:
            err.write(f"run_probes.py: {exc}\n")
            return EXIT_FAIL
        return EXIT_OK
    if not args.probe:
        parser.error("a subcommand is required (v1, v2, v3, v4, v5 or all), or --markdown")

    factory = devtools_factory or (lambda host, port: DevTools(host, port))
    devtools = factory(args.host, args.port)
    runner = Runner(
        devtools,
        out=out,
        err=err,
        results_path=args.results,
        v3_log_path=v3_log_path or DEFAULT_V3_LOG,
        pgrep=pgrep,
        clock=clock,
        sleep=sleep,
        cmdline=cmdline,
        stdin=stdin,
        steam_root=steam_root,
    )
    try:
        # Refusals come before any network access, so a refused run touches
        # nothing -- and, under `all`, nothing runs before the refusal either.
        if args.probe in ("v2", "all") and args.url:
            check_workshop_url(args.url)
        if args.probe == "v2":
            if not args.url:
                raise Refused("v2 changes the shortcut's selected layout; pass --url 'workshop://<publishedfileid>' to run it")
            if args.shortcut < SHORTCUT_APPID_MIN:
                raise Refused(f"v2 refuses appid {args.shortcut}: below 0x80000000 ({SHORTCUT_APPID_MIN}); it must be a shortcut, never a real game")
        if args.probe == "v3":
            runner.confirm_v3(args.yes)

        devtools.targets()  # port check: exit 3 with the message when closed

        if args.probe == "v1":
            runner.emit(runner.v1(args.appids, args.candidate_wait_ms, args.controller_index))
        elif args.probe == "v2":
            runner.emit(runner.v2(args.shortcut, args.url, args.restore, args.controller_index))
        elif args.probe == "v3":
            runner.emit(runner.v3(yes=True, duration_s=args.duration, interval_ms=args.interval_ms, reconnect_timeout_s=args.reconnect_timeout))
        elif args.probe == "v4":
            runner.emit(runner.v4())
        elif args.probe == "v5":
            runner.emit(runner.v5(args.shortcut, args.run))
        elif args.probe == "all":
            ran: dict[str, Any] = {}
            skipped: dict[str, str] = {}
            if args.appids:
                ran["v1"] = runner.v1(args.appids, controller_index=args.controller_index)
            else:
                skipped["v1"] = "no --appids"
            ran["v4"] = runner.v4()
            if args.shortcut:
                ran["v5"] = runner.v5(args.shortcut, False)
            else:
                skipped["v5"] = "no --shortcut"
            if args.shortcut and args.url:
                if args.shortcut < SHORTCUT_APPID_MIN:
                    skipped["v2"] = f"refused: appid {args.shortcut} is below 0x80000000"
                else:
                    ran["v2"] = runner.v2(args.shortcut, args.url, args.restore, args.controller_index)
            else:
                skipped["v2"] = "no --url" if args.shortcut else "no --shortcut"
            if args.yes:
                ran["v3"] = runner.v3(yes=True, duration_s=args.duration, interval_ms=args.interval_ms, reconnect_timeout_s=args.reconnect_timeout)
            else:
                skipped["v3"] = "no --yes"
            runner.emit({"probe": "all", "when": now_iso(), "ran": ran, "skipped": skipped})
        return EXIT_OK
    except Refused as exc:
        err.write(f"run_probes.py: refused: {exc}\n")
        return EXIT_REFUSED
    except PortClosed:
        err.write(PORT_CLOSED_MESSAGE.format(host=args.host, port=args.port) + "\n")
        return EXIT_PORT_CLOSED
    except ProbeError as exc:
        err.write(f"run_probes.py: {exc}\n")
        return EXIT_FAIL
    except KeyboardInterrupt:
        err.write("run_probes.py: interrupted\n")
        return 130


if __name__ == "__main__":
    sys.exit(main())
