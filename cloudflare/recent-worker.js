/**
 * Cloudflare Worker — daily-refreshed "recent obligations" feed for the
 * DisasterParameters Geography "Recent activity" sub-filter.
 *
 * Mirrors scripts/build_county_recent.py: pulls the two FEMA programs that carry a
 * per-item obligation DATE — Public Assistance (lastObligationDate) and Hazard
 * Mitigation v4 (initialObligationDate) — national, date-windowed (the indexed,
 * fast path), filters to Region 5 (IL/IN/MI/MN/OH/WI), drops COVID-19, and emits
 * the SAME JSON schema as data/recent.json so the browser can read either source.
 *
 * Two handlers:
 *   - scheduled(): cron-built payload -> KV (key "recent.json"). Wire a daily trigger.
 *   - fetch():     serves the cached payload from KV (CORS-open). If KV is empty it
 *                  builds on demand so the first request never 404s.
 *
 * The browser uses this for the 1-year window (which a single live national pull
 * can't serve — it truncates at OpenFEMA's 10,000-row cap) and as a fallback when a
 * live fetch fails. Short windows (7–90d) are fetched live straight from OpenFEMA.
 *
 * DEPLOY: see cloudflare/README.md (wrangler.toml + KV namespace + cron trigger).
 */

const PA_URL = "https://www.fema.gov/api/open/v2/PublicAssistanceFundedProjectsDetails";
const HM_URL = "https://www.fema.gov/api/open/v4/HazardMitigationAssistanceProjects";
const R5 = new Set(["IL", "IN", "MI", "MN", "OH", "WI"]);
const FIPS2AB = { "17": "IL", "18": "IN", "26": "MI", "27": "MN", "39": "OH", "55": "WI" };
const ABBR = { Illinois: "IL", Indiana: "IN", Michigan: "MI", Minnesota: "MN", Ohio: "OH", Wisconsin: "WI" };
const COVID = new Set([4489, 4494, 4507, 4515, 4520, 4531]);
const WINDOW_DAYS = 400;   // 1yr + buffer
const PAGE = 1000;
const KV_KEY = "recent.json";

const num = (x) => { const v = Math.round(Number(x)); return Number.isFinite(v) ? v : 0; };

function cutoffIso(days) {
  const d = new Date(Date.now() - days * 86400000);
  return d.toISOString().slice(0, 10) + "T00:00:00.000Z";
}

function fipsOf(sc, cc) {
  sc = String(sc ?? "").padStart(2, "0");
  if (cc == null || String(cc).trim() === "" || String(cc) === "000") return null;
  return sc + String(cc).padStart(3, "0");
}

async function paginate(base, filter, orderby, select, key) {
  const out = [];
  let skip = 0;
  for (;;) {
    const url = `${base}?$filter=${encodeURIComponent(filter)}` +
      `&$orderby=${encodeURIComponent(orderby)}` +
      `&$select=${encodeURIComponent(select)}` +
      `&$top=${PAGE}&$skip=${skip}&$format=json`;
    const res = await fetch(url, { headers: { "User-Agent": "DisasterParameters/recent-worker" } });
    if (!res.ok) throw new Error(`${key} ${res.status}`);
    const recs = ((await res.json())[key]) || [];
    if (!recs.length) break;
    out.push(...recs);
    skip += recs.length;
    if (recs.length < PAGE) break;
  }
  return out;
}

async function buildPA() {
  const cut = cutoffIso(WINDOW_DAYS);
  const sel = "disasterNumber,stateAbbreviation,stateNumberCode,countyCode,county," +
    "damageCategoryDescrip,federalShareObligated,lastObligationDate";
  const recs = await paginate(PA_URL, `lastObligationDate ge '${cut}'`,
    "lastObligationDate desc", sel, "PublicAssistanceFundedProjectsDetails");
  const rows = [];
  let newest = "";
  for (const r of recs) {
    if (!R5.has(r.stateAbbreviation) || COVID.has(r.disasterNumber)) continue;
    const date = (r.lastObligationDate || "").slice(0, 10);
    if (date > newest) newest = date;
    rows.push({
      f: fipsOf(r.stateNumberCode, r.countyCode),
      s: r.stateAbbreviation,
      dn: r.disasterNumber,
      amt: num(r.federalShareObligated),
      date,
      cat: r.damageCategoryDescrip,
      cty: r.county,
    });
  }
  return { rows, newest };
}

async function buildHM() {
  const cut = cutoffIso(WINDOW_DAYS);
  const sel = "disasterNumber,state,stateNumberCode,countyCode,county,programArea," +
    "projectType,subrecipient,federalShareObligated,initialObligationDate";
  const recs = await paginate(HM_URL, `initialObligationDate ne null and initialObligationDate ge '${cut}'`,
    "initialObligationDate desc", sel, "HazardMitigationAssistanceProjects");
  const rows = [];
  let newest = "";
  for (const r of recs) {
    let ab = ABBR[r.state] || FIPS2AB[String(r.stateNumberCode ?? "").padStart(2, "0")];
    if (!R5.has(ab) || COVID.has(r.disasterNumber)) continue;
    const fed = num(r.federalShareObligated);
    if (!fed) continue;
    const date = (r.initialObligationDate || "").slice(0, 10);
    if (date > newest) newest = date;
    const sub = (r.subrecipient || "").trim();
    rows.push({
      f: sub.toLowerCase() === "statewide" ? null : fipsOf(r.stateNumberCode, r.countyCode),
      s: ab,
      dn: r.disasterNumber,
      amt: fed,
      date,
      prog: r.programArea,
      cty: r.county,
      sub: sub || null,
    });
  }
  return { rows, newest };
}

async function buildPayload() {
  const [pa, hm] = await Promise.all([buildPA(), buildHM()]);
  pa.rows.sort((a, b) => (a.date < b.date ? 1 : -1));
  hm.rows.sort((a, b) => (a.date < b.date ? 1 : -1));
  const now = new Date();
  return {
    generated: now.toISOString().slice(0, 10),
    generatedAt: now.toISOString().replace(/\.\d+Z$/, "Z"),
    windowDays: WINDOW_DAYS,
    asOf: { PA: pa.newest, HM: hm.newest },
    source: "OpenFEMA PublicAssistanceFundedProjectsDetails (lastObligationDate) + " +
      "HazardMitigationAssistanceProjects v4 (initialObligationDate); Region 5, COVID-19 excluded. " +
      "Real OpenFEMA figures — not endorsed by FEMA.",
    note: "Refreshed daily by Cloudflare Worker. Raw dated obligation rows (federal share); bucket by " +
      "'f' (county FIPS; null = statewide) for any window. Counts are obligation ACTIVITY, not new declarations.",
    pa: pa.rows,
    hm: hm.rows,
  };
}

const CORS = {
  "Access-Control-Allow-Origin": "*",
  "Access-Control-Allow-Methods": "GET, OPTIONS",
  "Cache-Control": "public, max-age=3600",
  "Content-Type": "application/json; charset=utf-8",
};

export default {
  // Daily cron -> rebuild and cache in KV
  async scheduled(event, env, ctx) {
    const payload = await buildPayload();
    await env.RECENT_KV.put(KV_KEY, JSON.stringify(payload));
  },

  // Serve the cached payload (build on demand if KV is cold)
  async fetch(request, env, ctx) {
    if (request.method === "OPTIONS") return new Response(null, { headers: CORS });
    try {
      let body = env.RECENT_KV ? await env.RECENT_KV.get(KV_KEY) : null;
      if (!body) {
        const payload = await buildPayload();
        body = JSON.stringify(payload);
        if (env.RECENT_KV) ctx.waitUntil(env.RECENT_KV.put(KV_KEY, body));
      }
      return new Response(body, { headers: CORS });
    } catch (e) {
      return new Response(JSON.stringify({ error: String(e) }), { status: 502, headers: CORS });
    }
  },
};
