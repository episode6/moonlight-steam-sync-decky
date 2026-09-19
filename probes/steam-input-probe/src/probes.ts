/**
 * The five probes of the Moonlight Sync spec (PR-0), written against
 * undocumented Steam client globals. Every global is guarded, every call is
 * wrapped, and every failure is logged together with the shape of what was
 * found (Object.keys, typeof of the expected methods) so a wrong guess can be
 * diagnosed from the log alone.
 *
 * Nothing here writes under the Steam directory or calls a shortcut-editing
 * API. The only state-changing calls are SetSelectedConfigForApp (V2, on a
 * shortcut appid only), StartShutdown (V3) and RunGame (V5), each behind its
 * own button.
 */
import { callable } from "@decky/api";

const PREFIX = "[steam-input-probe]";
const SHORTCUT_APPID_MIN = 0x80000000;
export const NEPTUNE_TYPE_STRING = "controller_steamcontroller_neptune";
const NEPTUNE_ENUM = 4; // EControllerType.SteamControllerNeptune in @decky/ui 4.12
const FALLBACK_INDEX = 15; // the Deck controller index deckyemu measured; used only when the type lookup fails

const backendLog = callable<[line: string], { ok: boolean; path?: string; error?: string }>("log");
const backendStartWatch = callable<
  [duration_s: number, interval_ms: number],
  { ok: boolean; busy?: boolean; error?: string; started?: string; duration_s?: number; path?: string }
>("start_steam_watch");
const backendWatchState = callable<[], Record<string, unknown>>("steam_watch_state");

// ---- logging ---------------------------------------------------------------

let chain: Promise<unknown> = Promise.resolve();

/** Console + file. File writes are serialised so the order matches the console. */
export function plog(line: string): Promise<void> {
  console.log(`${PREFIX} ${line}`);
  chain = chain
    .then(() => backendLog(line))
    .then((r) => {
      if (!r || !r.ok) console.warn(`${PREFIX} file log failed:`, r);
    })
    .catch((e) => console.warn(`${PREFIX} file log threw:`, e));
  return chain.then(() => undefined);
}

export function safe(value: unknown, depth = 4): unknown {
  const seen = new WeakSet<object>();
  const walk = (v: unknown, d: number): unknown => {
    if (v === null || v === undefined) return v;
    const t = typeof v;
    if (t === "bigint") return `${v}n`;
    if (t === "function") return `[function ${(v as Function).name || "anonymous"}/${(v as Function).length}]`;
    if (t === "symbol") return String(v);
    if (t !== "object") return v;
    if (v instanceof Error) return { error: `${v.name}: ${v.message}`, stack: v.stack };
    if (seen.has(v as object)) return "[circular]";
    seen.add(v as object);
    if (d <= 0) return `[object ${Object.keys(v as object).length} keys]`;
    if (Array.isArray(v)) return v.slice(0, 50).map((x) => walk(x, d - 1));
    if (v instanceof Map) return { "[Map]": Array.from(v.entries()).slice(0, 50).map(([k, x]) => [walk(k, d - 1), walk(x, d - 1)]) };
    if (v instanceof Set) return { "[Set]": Array.from(v.values()).slice(0, 50).map((x) => walk(x, d - 1)) };
    const out: Record<string, unknown> = {};
    for (const k of Object.keys(v as object)) {
      try {
        out[k] = walk((v as Record<string, unknown>)[k], d - 1);
      } catch (e) {
        out[k] = `[getter threw: ${e}]`;
      }
    }
    return out;
  };
  return walk(value, depth);
}

export function j(value: unknown, depth = 4): string {
  try {
    return JSON.stringify(safe(value, depth));
  } catch (e) {
    return `<unserialisable: ${e}>`;
  }
}

function errText(e: unknown): string {
  if (e instanceof Error) return `${e.name}: ${e.message}`;
  return String(e);
}

/** Own keys plus prototype-chain method names, so MobX stores show their methods. */
export function shape(obj: unknown, filter?: RegExp): Record<string, unknown> {
  if (obj === null || obj === undefined) return { typeof: typeof obj, value: String(obj) };
  if (typeof obj !== "object" && typeof obj !== "function") return { typeof: typeof obj, value: String(obj) };
  const own = Object.keys(obj as object);
  const protoMethods: string[] = [];
  let p = Object.getPrototypeOf(obj);
  let hops = 0;
  while (p && p !== Object.prototype && hops < 6) {
    for (const n of Object.getOwnPropertyNames(p)) {
      if (n !== "constructor" && !protoMethods.includes(n)) protoMethods.push(n);
    }
    p = Object.getPrototypeOf(p);
    hops++;
  }
  const pick = (names: string[]) => (filter ? names.filter((n) => filter.test(n)) : names).slice(0, 200);
  return {
    typeof: typeof obj,
    constructor: (obj as object).constructor?.name,
    ownKeys: pick(own),
    ownKeyCount: own.length,
    protoMethods: pick(protoMethods),
  };
}

function g(): Record<string, any> {
  return globalThis as unknown as Record<string, any>;
}

function typeofPath(root: unknown, path: string[]): string {
  let cur: any = root;
  for (const p of path) {
    if (cur === null || cur === undefined) return `undefined (stopped at ${p})`;
    cur = cur[p];
  }
  return typeof cur;
}

function steamInput(): any | null {
  const sc = g().SteamClient;
  if (!sc) {
    plog(`SteamClient is ${typeof sc}; globals matching /steam/i: ${j(Object.keys(g()).filter((k) => /steam/i.test(k)))}`);
    return null;
  }
  if (!sc.Input) {
    plog(`SteamClient.Input is ${typeof sc.Input}; SteamClient shape: ${j(shape(sc))}`);
    return null;
  }
  return sc.Input;
}

function sleep(ms: number): Promise<void> {
  return new Promise((r) => setTimeout(r, ms));
}

/** An optional controller index typed by the operator; null when blank, an error text when malformed. */
export function parseIndexOverride(text: string): number | null | string {
  const t = text.trim();
  if (!t) return null;
  if (!/^\d+$/.test(t)) return `controller index override "${text}" is not a non-negative integer`;
  return Number(t);
}

export function parseAppids(text: string): { appids: number[]; bad: string[] } {
  const appids: number[] = [];
  const bad: string[] = [];
  for (const part of text.split(/[,\s]+/)) {
    if (!part) continue;
    const n = Number(part);
    if (Number.isInteger(n) && n > 0) appids.push(n);
    else bad.push(part);
  }
  return { appids, bad };
}

// ---- controllers (V1, V2) --------------------------------------------------

export interface ControllerRow {
  index: number | null;
  typeEnum: unknown;
  typeString: string | null;
  typeStringSource: string;
  name: unknown;
}

/**
 * Lists controllers and finds the Deck's built-in one by type
 * (GetControllerTypeString(eControllerType) === "controller_steamcontroller_neptune", spec 2.2).
 * The type-string lookup tries controllerStore, then SteamClient.Input, then
 * falls back to the enum value 4, and says which one answered.
 */
/** An array, or any iterable (an older MobX observable array is not an Array). */
function asList(v: unknown): any[] | null {
  if (Array.isArray(v)) return v;
  if (v && typeof v === "object" && typeof (v as any)[Symbol.iterator] === "function") {
    try {
      return Array.from(v as Iterable<unknown>);
    } catch {
      return null;
    }
  }
  return null;
}

export interface ControllerScan {
  controllers: ControllerRow[];
  deckIndex: number | null;
  source: string;
}

export async function findControllers(): Promise<ControllerScan> {
  const w = g();
  const cs = w.controllerStore;
  const attempts: string[] = [];
  let list: any[] | null = null;
  if (!cs) {
    await plog(`controllerStore is ${typeof cs}; globals matching /controller/i: ${j(Object.keys(w).filter((k) => /controller/i.test(k)))}`);
  } else {
    await plog(`controllerStore shape: ${j(shape(cs, /controller|Controller|type|Type/i))}`);
    if (typeof cs.GetControllers === "function") {
      try {
        const r = cs.GetControllers();
        list = asList(r);
        if (list) attempts.push(`controllerStore.GetControllers() -> ${Array.isArray(r) ? "array" : "iterable"} of ${list.length}`);
        else attempts.push(`controllerStore.GetControllers() -> ${typeof r}: ${j(r, 2)}`);
      } catch (e) {
        attempts.push(`controllerStore.GetControllers() threw ${errText(e)}`);
      }
    } else attempts.push(`controllerStore.GetControllers is ${typeof cs.GetControllers}`);
    if (list === null) {
      for (const k of ["m_rgControllers", "controllers", "m_controllers"]) {
        const v = asList(cs[k]);
        if (v) {
          list = v;
          attempts.push(`controllerStore.${k} -> list of ${v.length}`);
          break;
        }
        attempts.push(`controllerStore.${k} is ${typeof cs[k]}`);
      }
    }
  }
  await plog(`controller list attempts: ${j(attempts)}`);
  const controllers: ControllerRow[] = [];
  let deckIndex: number | null = null;
  let source = "none";
  for (const c of list ?? []) {
    const typeEnum = c?.eControllerType;
    let typeString: string | null = null;
    let typeStringSource = "none";
    const tryFn = (label: string, fn: unknown, self: unknown) => {
      if (typeString !== null || typeof fn !== "function") return;
      try {
        const r = (fn as Function).call(self, typeEnum);
        if (typeof r === "string") {
          typeString = r;
          typeStringSource = label;
        } else attempts.push(`${label}(${typeEnum}) -> ${typeof r}`);
      } catch (e) {
        attempts.push(`${label}(${typeEnum}) threw ${errText(e)}`);
      }
    };
    tryFn("controllerStore.GetControllerTypeString", cs?.GetControllerTypeString, cs);
    tryFn("SteamClient.Input.GetControllerTypeString", w.SteamClient?.Input?.GetControllerTypeString, w.SteamClient?.Input);
    if (typeString === null && typeEnum === NEPTUNE_ENUM) {
      typeString = NEPTUNE_TYPE_STRING;
      typeStringSource = `enum fallback (eControllerType === ${NEPTUNE_ENUM})`;
    }
    const index = typeof c?.nControllerIndex === "number" ? c.nControllerIndex : typeof c?.unControllerIndex === "number" ? c.unControllerIndex : null;
    const row: ControllerRow = { index, typeEnum, typeString, typeStringSource, name: c?.strName };
    controllers.push(row);
    await plog(`controller index=${index} type=${j(typeEnum)} typeString=${typeString} (${typeStringSource}) name=${j(c?.strName)} raw=${j(c, 2)}`);
    if (deckIndex === null && typeString === NEPTUNE_TYPE_STRING && index !== null) {
      deckIndex = index;
      source = typeStringSource;
    }
  }
  if (attempts.length) await plog(`type-string attempts: ${j(attempts)}`);
  await plog(`deck controller index by type: ${deckIndex === null ? "NOT FOUND" : deckIndex} (${source}); ${controllers.length} controller(s)`);
  return { controllers, deckIndex, source };
}

/**
 * The controller indices to probe. The confirmed Deck index when the type
 * lookup found it (or the operator's override); otherwise every listed
 * controller index, or the measured fallback 15 when nothing was listed, each
 * labelled "index not confirmed by type" so the probe still answers without
 * another build.
 */
export function indexPlan(scan: ControllerScan, override: number | null): { indices: number[]; confirmed: boolean; source: string } {
  if (override !== null) return { indices: [override], confirmed: true, source: "override (typed in the panel)" };
  if (scan.deckIndex !== null) return { indices: [scan.deckIndex], confirmed: true, source: scan.source };
  const listed: number[] = [];
  for (const c of scan.controllers) {
    if (typeof c.index === "number" && !listed.includes(c.index)) listed.push(c.index);
  }
  if (listed.length) return { indices: listed, confirmed: false, source: "index not confirmed by type (every listed controller index)" };
  return { indices: [FALLBACK_INDEX], confirmed: false, source: `index not confirmed by type (no controller listed; measured fallback ${FALLBACK_INDEX})` };
}

async function planIndices(overrideText: string): Promise<{ indices: number[]; confirmed: boolean; source: string } | null> {
  const override = parseIndexOverride(overrideText);
  if (typeof override === "string") {
    await plog(`refused: ${override}`);
    return null;
  }
  const scan = await findControllers();
  const plan = indexPlan(scan, override);
  if (!plan.confirmed) await plog(`WARNING deck controller index not found by type; probing indices ${j(plan.indices)} (${plan.source})`);
  else if (override !== null) await plog(`using controller index override ${override}`);
  return plan;
}

async function getConfig(input: any, appid: number, idx: number): Promise<unknown> {
  if (typeof input.GetConfigForAppAndController !== "function") {
    await plog(`GetConfigForAppAndController is ${typeof input.GetConfigForAppAndController}; Input shape: ${j(shape(input, /config/i))}`);
    return { error: "GetConfigForAppAndController missing" };
  }
  try {
    const r = await input.GetConfigForAppAndController(appid, idx);
    return r;
  } catch (e) {
    return { error: errText(e) };
  }
}

// ---- V1 ---------------------------------------------------------------------

export async function probeV1(appidText: string, indexOverrideText = ""): Promise<void> {
  await plog(`V1 start appids="${appidText}" indexOverride="${indexOverrideText}"`);
  const { appids, bad } = parseAppids(appidText);
  if (bad.length) await plog(`V1 ignoring non-numeric appids: ${j(bad)}`);
  const plan = await planIndices(indexOverrideText);
  if (!plan) return;
  const input = steamInput();
  if (!input) {
    await plog("V1 abort: no SteamClient.Input");
    return;
  }
  await plog(`SteamClient.Input methods matching /config/i: ${j(shape(input, /config/i))}`);
  const tag = plan.confirmed ? "" : " [index not confirmed by type]";
  for (const appid of appids) {
    const overview = safeOverview(appid);
    for (const idx of plan.indices) {
      const cfg = await getConfig(input, appid, idx);
      await plog(`V1 GetConfigForAppAndController(${appid}, ${idx})${tag} [${overview}] -> ${j(cfg)}`);
    }
  }
  for (const appid of appids) {
    await logCandidates(input, appid, plan.indices[0], tag);
  }
  await plog("V1 done");
}

function safeOverview(appid: number): string {
  try {
    const store = g().appStore;
    if (!store || typeof store.GetAppOverviewByAppID !== "function") return "no appStore";
    const o = store.GetAppOverviewByAppID(appid);
    if (!o) return "no overview";
    return `${o.display_name} app_type=${o.app_type}`;
  } catch (e) {
    return `overview threw ${errText(e)}`;
  }
}

/**
 * RegisterForControllerConfigInfoMessages + QueryControllerConfigsForApp.
 * Spec 2.2 writes the register call as (appId, cb); @decky/ui 4.12 types it as
 * (cb). The probe logs fn.length, uses the typed form, and logs every raw
 * message, so whichever is right is visible in the log.
 */
async function logCandidates(input: any, appid: number, idx: number, tag = ""): Promise<void> {
  const reg = input.RegisterForControllerConfigInfoMessages;
  const query = input.QueryControllerConfigsForApp;
  if (typeof reg !== "function" || typeof query !== "function") {
    await plog(`V1 candidates: RegisterForControllerConfigInfoMessages is ${typeof reg}, QueryControllerConfigsForApp is ${typeof query}; ${j(shape(input, /Register|Query/i))}`);
    return;
  }
  await plog(`V1 candidates for ${appid} (index ${idx}${tag}): register fn.length=${reg.length} query fn.length=${query.length}`);
  const received: unknown[] = [];
  let mismatched = 0;
  let handle: any = null;
  try {
    handle = reg.call(input, (msgs: unknown) => {
      received.push(msgs);
      plog(`V1 candidates message while querying ${appid}: ${j(msgs, 3)}`);
      if (Array.isArray(msgs)) {
        for (const m of msgs) {
          const mm = m as Record<string, unknown>;
          // The subscription is global: a message's own appID says which query it answers
          // (a late message for the previous appid lands here too).
          const forThis = mm.appID === undefined ? "unknown (no appID field)" : String(mm.appID) === String(appid) ? "yes" : "NO (other appid)";
          if (forThis.startsWith("NO")) mismatched++;
          plog(`V1 candidate queried=${appid} msg.appID=${j(mm.appID)} forThisAppid=${forThis} nControllerType=${j(mm.nControllerType)} strName=${j(mm.strName)} URL=${j(mm.URL)} Title=${j(mm.Title)} publishedFileID=${j(mm.publishedFileID)} bOfficial=${j(mm.bOfficial)} eExportType=${j(mm.eExportType)} bSelected=${j(mm.bSelected)} bPersonalQueryDone=${j(mm.bPersonalQueryDone)}`);
        }
      }
    });
    await plog(`V1 register returned ${j(handle, 1)} (unregister is ${typeofPath(handle, ["unregister"])})`);
  } catch (e) {
    await plog(`V1 register threw ${errText(e)}`);
    return;
  }
  try {
    const r = await query.call(input, appid, idx, false);
    await plog(`V1 QueryControllerConfigsForApp(${appid}, ${idx}, false) -> ${j(r)}`);
  } catch (e) {
    await plog(`V1 QueryControllerConfigsForApp threw ${errText(e)}`);
  }
  await sleep(4000);
  try {
    if (handle && typeof handle.unregister === "function") handle.unregister();
    else if (typeof handle === "function") handle();
    await plog(`V1 unregistered for ${appid}; ${received.length} message batch(es) received, ${mismatched} candidate(s) carried another appID`);
  } catch (e) {
    await plog(`V1 unregister threw ${errText(e)}`);
  }
}

// ---- V2 ---------------------------------------------------------------------

export async function probeV2(appidText: string, url: string, indexOverrideText = ""): Promise<void> {
  await plog(`V2 start shortcut="${appidText}" url="${url}" indexOverride="${indexOverrideText}"`);
  const appid = Number(appidText.trim());
  if (!Number.isInteger(appid) || appid < SHORTCUT_APPID_MIN) {
    await plog(`V2 refused: appid ${appidText} is not a shortcut appid (must be >= ${SHORTCUT_APPID_MIN}); never run on a real game`);
    return;
  }
  if (!/^workshop:\/\/\d+$/.test(url.trim())) {
    await plog(`V2 refused: url must look like workshop://<publishedfileid>, got "${url}"`);
    return;
  }
  const plan = await planIndices(indexOverrideText);
  if (!plan) return;
  const input = steamInput();
  if (!input) {
    await plog("V2 abort: no SteamClient.Input");
    return;
  }
  // The first planned index: the confirmed one, or the first listed / 15 (logged as unconfirmed above).
  const deckIndex = plan.indices[0];
  await plog(`V2 using controller index ${deckIndex}${plan.confirmed ? "" : " [index not confirmed by type]"} (${plan.source})`);
  await plog(`V2 shortcut ${appid} is [${safeOverview(appid)}]`);
  const before = await getConfig(input, appid, deckIndex);
  await plog(`V2 before: ${j(before)}`);
  if (typeof input.SetSelectedConfigForApp !== "function") {
    await plog(`V2 SetSelectedConfigForApp is ${typeof input.SetSelectedConfigForApp}; ${j(shape(input, /Selected|Config/i))}`);
    return;
  }
  let setResult: unknown;
  try {
    setResult = await input.SetSelectedConfigForApp(appid, deckIndex, url.trim(), false);
  } catch (e) {
    setResult = { error: errText(e) };
  }
  await plog(`V2 SetSelectedConfigForApp(${appid}, ${deckIndex}, "${url.trim()}", false) -> ${j(setResult)}`);
  await sleep(1000);
  const after = await getConfig(input, appid, deckIndex);
  const afterUrl = (after as Record<string, unknown> | null)?.URL;
  await plog(`V2 after 1 s: ${j(after)}`);
  await plog(`V2 result: stuck=${afterUrl === url.trim()} before.URL=${j((before as any)?.URL)} after.URL=${j(afterUrl)}`);
  await plog("V2 done (the previous selection is NOT restored by the plugin; use the layout picker or run_probes.py v2 --restore)");
}

// ---- V3 ---------------------------------------------------------------------

export async function probeV3(): Promise<void> {
  await plog("V3 start: asking the backend to watch pgrep -x steam for 60 s");
  let ack: Awaited<ReturnType<typeof backendStartWatch>>;
  try {
    ack = await backendStartWatch(60, 100);
  } catch (e) {
    await plog(`V3 abort: start_steam_watch threw ${errText(e)}`);
    return;
  }
  await plog(`V3 backend ack: ${j(ack)}`);
  if (!ack || !ack.ok) {
    await plog("V3 abort: backend did not acknowledge the watch; not shutting Steam down");
    return;
  }
  const user = g().SteamClient?.User;
  if (!user || typeof user.StartShutdown !== "function") {
    await plog(`V3 abort: SteamClient.User.StartShutdown is ${typeofPath(g(), ["SteamClient", "User", "StartShutdown"])}; User shape: ${j(shape(user, /Shutdown|Restart/i))}`);
    return;
  }
  await plog("V3 calling SteamClient.User.StartShutdown(false) now; read the steam-watch lines in the log after Steam is back");
  try {
    const r = user.StartShutdown(false);
    await plog(`V3 StartShutdown returned ${j(r)}`);
  } catch (e) {
    await plog(`V3 StartShutdown threw ${errText(e)}`);
  }
}

export async function probeV3Summary(): Promise<void> {
  try {
    const s = await backendWatchState();
    await plog(`V3 watch state: ${j(s, 5)}`);
  } catch (e) {
    await plog(`V3 watch state threw ${errText(e)}`);
  }
}

// ---- V4 ---------------------------------------------------------------------

export function steamId3From64(steam64: string): string | null {
  try {
    if (!/^\d+$/.test(steam64)) return null;
    return (BigInt(steam64) - BigInt("76561197960265728")).toString();
  } catch {
    return null;
  }
}

export async function probeV4(): Promise<void> {
  await plog("V4 start");
  const w = g();
  const cs = w.collectionStore;
  if (!cs) {
    await plog(`V4 collectionStore is ${typeof cs}; globals matching /collection|store/i: ${j(Object.keys(w).filter((k) => /collection|store/i.test(k)))}`);
  } else {
    const coll = cs.allAppsCollection;
    if (!coll) {
      await plog(`V4 collectionStore.allAppsCollection is ${typeof coll}; collectionStore shape: ${j(shape(cs, /app|coll/i))}`);
    } else {
      let apps: any = null;
      try {
        apps = coll.allApps;
      } catch (e) {
        await plog(`V4 allApps getter threw ${errText(e)}`);
      }
      const arr = Array.isArray(apps) ? apps : apps && typeof apps[Symbol.iterator] === "function" ? Array.from(apps as Iterable<unknown>) : null;
      if (!arr) {
        await plog(`V4 allAppsCollection.allApps is ${typeof apps}; allAppsCollection shape: ${j(shape(coll, /app/i))}`);
      } else {
        await plog(`V4 allApps total count=${arr.length}`);
        const counts: Record<string, number> = {};
        for (const a of arr) {
          const t = String((a as any)?.app_type);
          counts[t] = (counts[t] ?? 0) + 1;
        }
        await plog(`V4 app_type histogram: ${j(counts)}`);
        arr.slice(0, 20).forEach((a: any, i: number) => {
          plog(`V4 app[${i}] appid=${j(a?.appid)} display_name=${j(a?.display_name)} app_type=${j(a?.app_type)} gameid=${j(a?.gameid)}`);
        });
        if (arr.length) await plog(`V4 app[0] shape: ${j(shape(arr[0]))}`);
        // Every shortcut in the library, so the throwaway one for V2/V5 can be found by name.
        const shortcuts = arr.filter((a: any) => typeof a?.appid === "number" && a.appid >= SHORTCUT_APPID_MIN);
        await plog(`V4 shortcuts (appid >= 0x80000000): count=${shortcuts.length}`);
        shortcuts.slice(0, 100).forEach((a: any) => {
          plog(`V4 shortcut appid=${j(a?.appid)} display_name=${j(a?.display_name)} app_type=${j(a?.app_type)} gameid=${j(a?.gameid)}`);
        });
      }
    }
  }
  const app = w.App;
  const raw = app?.m_CurrentUser?.strSteamID;
  await plog(`V4 App.m_CurrentUser.strSteamID raw=${j(raw)} typeof=${typeof raw}`);
  if (typeof raw !== "string") {
    await plog(`V4 App shape: ${j(shape(app, /user/i))}; m_CurrentUser shape: ${j(shape(app?.m_CurrentUser))}`);
  } else {
    await plog(`V4 steamid3=${steamId3From64(raw)} (steam64 - 76561197960265728, BigInt)`);
  }
  await plog("V4 done");
}

// ---- V5 ---------------------------------------------------------------------

export async function probeV5(appidText: string, run: boolean): Promise<void> {
  await plog(`V5 start shortcut="${appidText}" run=${run}`);
  const appid = Number(appidText.trim());
  if (!Number.isInteger(appid) || appid <= 0) {
    await plog(`V5 refused: "${appidText}" is not an appid`);
    return;
  }
  const w = g();
  const store = w.appStore;
  if (!store) {
    await plog(`V5 appStore is ${typeof store}; globals matching /store/i: ${j(Object.keys(w).filter((k) => /store/i.test(k)))}`);
    return;
  }
  if (typeof store.GetAppOverviewByAppID !== "function") {
    await plog(`V5 appStore.GetAppOverviewByAppID is ${typeof store.GetAppOverviewByAppID}; appStore methods matching /overview/i: ${j(shape(store, /overview/i))}`);
    return;
  }
  let overview: any;
  try {
    overview = store.GetAppOverviewByAppID(appid);
  } catch (e) {
    await plog(`V5 GetAppOverviewByAppID(${appid}) threw ${errText(e)}`);
    return;
  }
  if (!overview) {
    await plog(`V5 GetAppOverviewByAppID(${appid}) returned ${j(overview)} (no such app in the library?)`);
    return;
  }
  const gameid = overview.gameid;
  await plog(`V5 overview appid=${j(overview.appid)} display_name=${j(overview.display_name)} app_type=${j(overview.app_type)} gameid=${j(gameid)} typeof gameid=${typeof gameid} BIsShortcut=${typeof overview.BIsShortcut === "function" ? j(overview.BIsShortcut()) : "n/a"}`);
  await plog(`V5 overview shape: ${j(shape(overview))}`);
  if (!run) {
    await plog("V5 done (not run)");
    return;
  }
  const apps = w.SteamClient?.Apps;
  if (!apps || typeof apps.RunGame !== "function") {
    await plog(`V5 SteamClient.Apps.RunGame is ${typeofPath(w, ["SteamClient", "Apps", "RunGame"])}; Apps shape: ${j(shape(apps, /run|launch/i))}`);
    return;
  }
  try {
    const r = apps.RunGame(gameid, "", -1, 100);
    await plog(`V5 RunGame(${j(gameid)}, "", -1, 100) -> ${j(r)}`);
  } catch (e) {
    await plog(`V5 RunGame threw ${errText(e)}`);
  }
  await plog("V5 done");
}
