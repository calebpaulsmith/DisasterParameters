#!/usr/bin/env python3
"""
Build data/disaster_county_ihp.json — a per-DISASTER × per-COUNTY IHP rollup so the
Geography disaster drill-down can show each designated county's IHP for THAT disaster
(approved $, HA/ONA split, valid-registration count) instead of the county's all-time IHP.

WHY a committed file (not a live browser fetch): IHP is registrant-level
(IndividualsAndHouseholdsProgramValidRegistrations) — the biggest Region 5 disasters carry
70k–117k registrant rows, far too heavy to pull live on mobile. PA can be fetched live because
PublicAssistanceFundedProjectsSummaries is pre-aggregated by applicant×county; IHP cannot. So we
precompute the same per-disaster county aggregate build_county_ihp.py already pulls, and commit it.

Same dataset + same county→FIPS mapping (+ norm()) as build_county_ihp.py, so the per-disaster
buckets here SUM (across a county's disasters) to that script's all-time county ihpApproved —
modulo the registrant rows whose county can't be resolved to an R5 declared FIPS, which we do NOT
drop: they're conserved in the per-disaster audit (undeclared / unmatched), mirroring cd["ihpAudit"].

Output (compact):
  {
    "meta": {...},
    "byDisaster": { "<dn>": { "<fips>": [ihp, ha, ona, regs], ... }, ... },   # rounded ints
    "audit":      { "<dn>": {"inSet":$, "undeclared":$, "unmatched":$, "rows":n}, ... }
  }

Region 5 IHP-bearing disasters only (ihpTotal>0 or iaRegistrations>0). Needs network.
Resumable per-disaster cache: data/_ihp_dc_cache.json. Run any time:
  python3 scripts/build_disaster_county_ihp.py
"""
import json, os, time, urllib.request, urllib.parse, collections

DATA = os.path.join(os.path.dirname(__file__), "..", "data")
URL = "https://www.fema.gov/api/open/v2/IndividualsAndHouseholdsProgramValidRegistrations"
SEL = "county,damagedStateAbbreviation,ihpAmount,haAmount,onaAmount"
R5 = {"IL", "IN", "MI", "MN", "OH", "WI"}

def load(name): return json.load(open(os.path.join(DATA, name)))
def norm(s): return (s or "").lower().replace("(county)", "").replace("county", "").replace(".", "").replace("'", "").replace(" ", "").replace("-", "").strip()
def num(x):
    try: return float(x or 0)
    except Exception: return 0.0

def get(u, retries=5):
    for i in range(retries):
        try:
            with urllib.request.urlopen(urllib.request.Request(u, headers={"User-Agent": "DisasterParameters/dcihp"}), timeout=180) as r:
                return json.loads(r.read().decode("utf-8", "replace"))
        except Exception:
            time.sleep(2 * (i + 1))
    return None

def pull_disaster(dn):
    """→ list of [state, county, ihp, ha, ona, regs] aggregated for this disaster."""
    agg = collections.defaultdict(lambda: [0.0, 0.0, 0.0, 0])
    skip = 0
    while True:
        q = urllib.parse.urlencode({"$filter": f"disasterNumber eq {dn}", "$select": SEL, "$top": 1000, "$skip": skip, "$format": "json"})
        d = get(f"{URL}?{q}")
        recs = (d or {}).get("IndividualsAndHouseholdsProgramValidRegistrations", []) if d else []
        if not recs: break
        for r in recs:
            k = (r.get("damagedStateAbbreviation") or "", r.get("county") or "")
            a = agg[k]
            a[0] += num(r.get("ihpAmount")); a[1] += num(r.get("haAmount")); a[2] += num(r.get("onaAmount")); a[3] += 1
        skip += len(recs)
        if len(recs) < 1000: break
    return [[k[0], k[1], round(v[0], 2), round(v[1], 2), round(v[2], 2), v[3]] for k, v in agg.items()]

def main():
    disasters = load("disasters.json")
    ihp_dns = [d["disasterNumber"] for d in disasters
               if (d.get("costs") or {}).get("ihpTotal", 0) > 0 or (d.get("costs") or {}).get("iaRegistrations", 0) > 0]
    cd = load("county_declarations.json")
    counties = cd["counties"]
    name2fips = {(c["s"], norm(c["n"])): c["f"] for c in load("r5_counties.json")}

    cache_path = os.path.join(DATA, "_ihp_dc_cache.json")
    cache = json.load(open(cache_path)) if os.path.exists(cache_path) else {}
    for i, dn in enumerate(ihp_dns, 1):
        if str(dn) in cache: continue
        cache[str(dn)] = pull_disaster(dn)
        json.dump(cache, open(cache_path, "w"), separators=(",", ":"))
        print(f"  [{i}/{len(ihp_dns)}] DR-{dn}: {len(cache[str(dn)])} county-buckets, "
              f"{sum(r[5] for r in cache[str(dn)])} registrant rows", flush=True)

    by_disaster, audit = {}, {}
    for dn in ihp_dns:
        rows = cache[str(dn)]
        fips_map = {}
        inset = und = unm = 0.0
        nrows = 0
        for st, cnty, ihp, ha, ona, regs in rows:
            nrows += regs
            fips = name2fips.get((st, norm(cnty))) if st in R5 else None
            if fips and fips in counties:
                b = fips_map.get(fips) or [0.0, 0.0, 0.0, 0]
                b[0] += ihp; b[1] += ha; b[2] += ona; b[3] += regs
                fips_map[fips] = b
                inset += ihp
            elif fips:
                und += ihp        # valid R5 county but not in this disaster's declared set
            else:
                unm += ihp        # unresolved name / non-R5 (e.g. tribal/reservation, border)
        by_disaster[str(dn)] = {f: [round(b[0]), round(b[1]), round(b[2]), b[3]] for f, b in fips_map.items()}
        audit[str(dn)] = {"inSet": round(inset), "undeclared": round(und), "unmatched": round(unm), "rows": nrows}

    out = {
        "meta": {
            "source": "OpenFEMA IndividualsAndHouseholdsProgramValidRegistrations v2 (registrant-level), "
                      "aggregated per disaster × county; county name→FIPS via r5_counties.json (norm).",
            "fields": "byDisaster[dn][fips] = [ihpApproved, haApproved, onaApproved, validRegistrations] (rounded).",
            "note": "Per-disaster county IHP. Sums (over a county's disasters) reconcile with county_declarations "
                    "ihpApproved modulo unresolved rows (see audit undeclared/unmatched — money conserved, never dropped). "
                    "Registrant-pull $ differ from the ledger (FemaWebDisasterSummaries) state IHP — different datasets.",
            "disasters": len(ihp_dns),
        },
        "byDisaster": by_disaster,
        "audit": audit,
    }
    json.dump(out, open(os.path.join(DATA, "disaster_county_ihp.json"), "w"), separators=(",", ":"))
    tot_in = sum(a["inSet"] for a in audit.values())
    tot_und = sum(a["undeclared"] for a in audit.values())
    tot_unm = sum(a["unmatched"] for a in audit.values())
    print(f"\nWrote data/disaster_county_ihp.json — {len(ihp_dns)} disasters")
    print(f"  conserved $: inSet={tot_in:,.0f}  undeclared={tot_und:,.0f}  unmatched={tot_unm:,.0f}")

if __name__ == "__main__":
    main()
