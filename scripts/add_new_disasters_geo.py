#!/usr/bin/env python3
"""
Additively patch the GEOGRAPHY data for disasters newly added to data/disasters.json,
WITHOUT re-running the heavy county_declarations.json pipeline (the parked Tier-1b
rebuild). For every ledger disaster that county_declarations.json doesn't know yet:

  - county designations (from data/_disasters_raw.json — regenerate it first, e.g. via
    scripts/add_history.py or its pull_declarations helper) are appended to each
    designated county's `disasters` list (kept date-descending) and `count`;
  - per-county + statewide PA obligated $/projects for those disasters are pulled from
    OpenFEMA PublicAssistanceFundedProjectsDetails and added to paObligated/paProjects
    and the paByYear/paProjectsByYear buckets (true obligation year, mirroring
    build_county_byyear.py);
  - per-county IHP approved $ (HA/ONA split + registrations) is pulled from
    IndividualsAndHouseholdsProgramValidRegistrations (same SEL/norm as
    build_county_ihp.py) and added to the county fields, the per-state ihpAudit
    conservation block, AND data/disaster_county_ihp.json (byDisaster + audit), so the
    mobile per-disaster county drill has the new disasters too;
  - state rollups (nDisasters / paObligated / paProjects / ihpApproved / ihpHousing /
    ihpOna / iaRegistrations) are recomputed straight from the updated ledger, and the
    state+county ihpByYear proxy buckets are recomputed exactly as
    build_county_byyear.py does (incident year; county allocation weighted by DR IHP).

Dollars are conserved: every registrant dollar lands inSet/undeclared/unmatched in the
audit; the script asserts the per-disaster bucket identity before writing.

Run AFTER scripts/add_history.py (+ build_declared.py). Idempotent: a disaster already
present in county_declarations.json is skipped. Needs network.
    python3 scripts/add_new_disasters_geo.py
"""
import os, sys, json, collections, urllib.request, urllib.parse, time, datetime as dt

HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE)
from build_county_ihp import norm                      # single source of truth for county-name matching
DATA = os.path.join(HERE, "..", "data")
IHP_URL = "https://www.fema.gov/api/open/v2/IndividualsAndHouseholdsProgramValidRegistrations"
IHP_SEL = "county,damagedStateAbbreviation,ihpAmount,haAmount,onaAmount"
PA_URL = "https://www.fema.gov/api/open/v2/PublicAssistanceFundedProjectsDetails"
PA_SEL = "disasterNumber,stateNumberCode,countyCode,federalShareObligated,lastObligationDate"
R5 = {"IL", "IN", "MI", "MN", "OH", "WI"}

def load(n): return json.load(open(os.path.join(DATA, n)))
def num(x):
    try: return float(x or 0)
    except Exception: return 0.0
def yr(s):
    s = str(s or "")[:4]
    return s if (s.isdigit() and "1990" <= s <= "2099") else None
def srt(d): return {k: round(v) for k, v in sorted(d.items()) if round(v)}

def get(url, retries=5):
    for i in range(retries):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "DisasterParameters/geo-patch"}), timeout=120) as r:
                return json.loads(r.read().decode("utf-8", "replace"))
        except Exception:
            time.sleep(2 * (i + 1))
    return None

def paged(url, sel, flt, key):
    skip = 0
    while True:
        q = urllib.parse.urlencode({"$filter": flt, "$select": sel, "$top": 1000, "$skip": skip, "$format": "json"})
        d = get(f"{url}?{q}")
        recs = (d or {}).get(key, []) if d else []
        if not recs: return
        yield from recs
        skip += len(recs)
        if len(recs) < 1000: return

def main():
    disasters = load("disasters.json")
    raw = {r["disasterNumber"]: r for r in load("_disasters_raw.json")}
    cd = load("county_declarations.json")
    dcihp = load("disaster_county_ihp.json")
    geo = {c["f"]: c for c in load("r5_counties.json")}
    name2fips = {(c["s"], norm(c["n"])): c["f"] for c in load("r5_counties.json")}
    counties = cd["counties"]; meta = {d["disasterNumber"]: d for d in disasters}

    known = set()
    for c in counties.values():
        for x in c.get("disasters", []): known.add(x["dn"])
    new_dns = sorted(dn for dn in meta if dn not in known)
    if not new_dns:
        print("county_declarations.json already covers every ledger disaster — nothing to do."); return
    print(f"patching geography for {len(new_dns)} new disaster(s): {new_dns}")

    # ---- 1. designations from the raw declarations pull ----
    for dn in new_dns:
        r = raw.get(dn); d = meta[dn]
        if not r: raise SystemExit(f"DR-{dn} not in _disasters_raw.json — regenerate it first (scripts/add_history.py)")
        sf = str(r.get("stateFips") or "").zfill(2)
        rec = {"dn": dn, "date": d.get("begin"), "end": d.get("end"), "it": d.get("incidentType"),
               "title": d.get("title"), "tags": d.get("tags", []),
               "pa": (d.get("costs") or {}).get("paTotal", 0), "ihp": (d.get("costs") or {}).get("ihpTotal", 0)}
        n_c = 0
        for code in (r.get("counties") or {}):
            fips = sf + str(code).zfill(3); g = geo.get(fips)
            if not g: continue
            c = counties.setdefault(fips, {"name": g["n"], "state": g["s"], "count": 0,
                                           "paObligated": 0, "paProjects": 0, "disasters": []})
            c["disasters"].append(dict(rec)); n_c += 1
        print(f"  DR-{dn}: {n_c} designated counties")
    for c in counties.values():
        c["disasters"].sort(key=lambda x: (x["date"] or ""), reverse=True)
        c["count"] = len(c["disasters"])

    # ---- 2. PA worksheets for the new disasters (county $ + projects + byYear) ----
    for dn in new_dns:
        got = 0
        for w in paged(PA_URL, PA_SEL, f"disasterNumber eq {dn}", "PublicAssistanceFundedProjectsDetails"):
            got += 1
            amt = num(w.get("federalShareObligated"))
            sc = str(w.get("stateNumberCode") or "").zfill(2); cc = w.get("countyCode")
            y = yr(w.get("lastObligationDate"))
            ab = meta[dn]["state"]
            if cc and str(cc).strip() and str(cc) != "000" and (sc + str(cc).zfill(3)) in counties:
                c = counties[sc + str(cc).zfill(3)]
                c["paObligated"] = round(c.get("paObligated", 0) + amt); c["paProjects"] = c.get("paProjects", 0) + 1
                if y:
                    for k, v in (("paByYear", amt), ("paProjectsByYear", 1)):
                        b = c.setdefault(k, {}); b[y] = round(b.get(y, 0) + v)
            else:
                sw = cd.setdefault("statewide", {}).setdefault(ab, {"paObligated": 0, "paProjects": 0})
                sw["paObligated"] = round(sw["paObligated"] + amt); sw["paProjects"] += 1
            if y:  # state byYear carries county + statewide alike
                st = cd["states"][ab]
                for k, v in (("paByYear", amt), ("paProjectsByYear", 1)):
                    b = st.setdefault(k, {}); b[y] = round(b.get(y, 0) + v)
        print(f"  DR-{dn}: {got} PA worksheets folded in")

    # ---- 3. IHP registrants for the new disasters (county $ + audit + disaster_county_ihp) ----
    add_audit = collections.defaultdict(lambda: {"inSet": [0.0, 0], "undeclared": [0.0, 0], "unmatched": [0.0, 0]})
    for dn in new_dns:
        cst = (meta[dn].get("costs") or {})
        if not (cst.get("ihpTotal", 0) > 0 or cst.get("iaRegistrations", 0) > 0):
            print(f"  DR-{dn}: no IHP recorded yet — skipping registrant pull"); continue
        agg = collections.defaultdict(lambda: [0.0, 0.0, 0.0, 0])
        for r in paged(IHP_URL, IHP_SEL, f"disasterNumber eq {dn}", "IndividualsAndHouseholdsProgramValidRegistrations"):
            a = agg[(r.get("damagedStateAbbreviation") or "", r.get("county") or "")]
            a[0] += num(r.get("ihpAmount")); a[1] += num(r.get("haAmount")); a[2] += num(r.get("onaAmount")); a[3] += 1
        fips_map = {}; inset = und = unm = 0.0; nrows = 0
        for (st, cnty), v in agg.items():
            nrows += v[3]
            fips = name2fips.get((st, norm(cnty))) if st in R5 else None
            if fips and fips in counties:
                b = fips_map.setdefault(fips, [0.0, 0.0, 0.0, 0])
                for i in range(4): b[i] += v[i]
                inset += v[0]
                A = add_audit[st]["inSet"]; A[0] += v[0]; A[1] += v[3]
                c = counties[fips]
                c["ihpApproved"] = round(c.get("ihpApproved", 0) + v[0])
                c["ihpHousing"] = round(c.get("ihpHousing", 0) + v[1])
                c["ihpOna"] = round(c.get("ihpOna", 0) + v[2])
                c["iaRegistrations"] = c.get("iaRegistrations", 0) + v[3]
            elif fips:
                und += v[0]; A = add_audit[st]["undeclared"]; A[0] += v[0]; A[1] += v[3]
            else:
                unm += v[0]; A = add_audit[st]["unmatched"]; A[0] += v[0]; A[1] += v[3]
        assert abs((inset + und + unm) - sum(v[0] for v in agg.values())) < 1, f"DR-{dn}: IHP $ not conserved"
        dcihp["byDisaster"][str(dn)] = {f: [round(b[0]), round(b[1]), round(b[2]), b[3]] for f, b in fips_map.items()}
        dcihp["audit"][str(dn)] = {"inSet": round(inset), "undeclared": round(und), "unmatched": round(unm), "rows": nrows}
        print(f"  DR-{dn}: {nrows} registrant rows → {len(fips_map)} counties · inSet ${inset:,.0f} · undeclared ${und:,.0f} · unmatched ${unm:,.0f}")
    dcihp["meta"]["disasters"] = len(dcihp["byDisaster"])

    # ---- 4. state rollups + ihpAudit ledger side, straight from the updated ledger ----
    L = collections.defaultdict(lambda: {"n": 0, "pa": 0.0, "proj": 0, "ihp": 0.0, "ha": 0.0, "ona": 0.0, "reg": 0})
    for d in disasters:
        c = d.get("costs") or {}; s = L[d["state"]]
        s["n"] += 1; s["pa"] += num(c.get("paTotal")); s["proj"] += int(c.get("paProjects") or 0)
        s["ihp"] += num(c.get("ihpTotal")); s["ha"] += num(c.get("ihpHousing")); s["ona"] += num(c.get("ihpOna"))
        s["reg"] += int(c.get("iaRegistrations") or 0)
    for ab, st in cd["states"].items():
        s = L[ab]
        st["nDisasters"] = s["n"]; st["paObligated"] = round(s["pa"]); st["paProjects"] = s["proj"]
        st["ihpApproved"] = round(s["ihp"]); st["ihpHousing"] = round(s["ha"]); st["ihpOna"] = round(s["ona"])
        st["iaRegistrations"] = s["reg"]
        A = cd["ihpAudit"][ab]
        for bucket, jkey, rkey in (("inSet", "countyInSet", "inSetReg"), ("undeclared", "undeclared", "undeclaredReg"),
                                   ("unmatched", "unmatched", "unmatchedReg")):
            A[jkey] = round(A[jkey] + add_audit[ab][bucket][0]); A[rkey] = A[rkey] + add_audit[ab][bucket][1]
        A["ledgerIhp"] = round(s["ihp"]); A["ledgerHa"] = round(s["ha"]); A["ledgerOna"] = round(s["ona"]); A["ledgerReg"] = s["reg"]
        A["registrantTotal"] = A["countyInSet"] + A["undeclared"] + A["unmatched"]
        A["residual"] = A["ledgerIhp"] - A["registrantTotal"]
        pct = (A["residual"] / A["ledgerIhp"]) if A["ledgerIhp"] else 0.0
        A["pctGap"] = round(pct, 4)
        flags = []
        if A["undeclared"] > 0: flags.append("UNDECLARED_COUNTY_$")
        if A["unmatched"] > 0: flags.append("UNMATCHED_NAME_$")
        if abs(pct) > 0.01: flags.append(f"LEDGER_GAP_{pct*100:.1f}%")
        A["flags"] = flags

    # ---- 5. ihpByYear proxy recompute (mirrors build_county_byyear.py) ----
    ihp_state = collections.defaultdict(lambda: collections.defaultdict(float))
    for d in disasters:
        y = yr(d.get("begin")); ih = num((d.get("costs") or {}).get("ihpTotal"))
        if y and ih: ihp_state[d["state"]][y] += ih
    for ab, st in cd["states"].items():
        s = srt(ihp_state.get(ab, {}))
        if s: st["ihpByYear"] = s
    touched = {f for f, c in counties.items() if any(x["dn"] in set(new_dns) for x in c["disasters"])}
    for f in touched:
        o = counties[f]
        tot = o.get("ihpApproved", 0) or 0; ds = o.get("disasters") or []
        if not tot or not ds:
            o.pop("ihpByYear", None); continue
        wsum = sum((x.get("ihp") or 0) for x in ds)
        acc = collections.defaultdict(float)
        for x in ds:
            y = yr(x.get("date"))
            if not y: continue
            w = (x.get("ihp") or 0)
            acc[y] += tot * (w / wsum) if wsum else tot / len(ds)
        if srt(acc): o["ihpByYear"] = srt(acc)

    # ---- 6. header stats + write ----
    cd["nCounties"] = len(counties)
    cd["nWithAny"] = sum(1 for c in counties.values() if c["count"])
    for key, fld in (("maxCount", "count"), ("maxPA", "paObligated"), ("maxProjects", "paProjects"),
                     ("maxIHP", "ihpApproved"), ("maxIhpHousing", "ihpHousing"), ("maxIhpOna", "ihpOna")):
        cd[key] = max((c.get(fld, 0) for c in counties.values()), default=0)
    cd["generated"] = dt.date.today().isoformat()[:7]
    for c in counties.values():
        dates = [x["date"] for x in c["disasters"]]
        assert dates == sorted(dates, reverse=True), f"{c['name']} {c['state']}: disasters not date-descending"
    json.dump(cd, open(os.path.join(DATA, "county_declarations.json"), "w"), separators=(",", ":"))
    json.dump(dcihp, open(os.path.join(DATA, "disaster_county_ihp.json"), "w"), separators=(",", ":"))
    print(f"\nwrote county_declarations.json ({cd['nCounties']} counties, maxCount {cd['maxCount']}) "
          f"and disaster_county_ihp.json ({dcihp['meta']['disasters']} disasters)")
    for ab in sorted(cd["states"]):
        A = cd["ihpAudit"][ab]
        print(f"  {ab}: ledger IHP ${A['ledgerIhp']:,} · registrant ${A['registrantTotal']:,} · "
              f"residual ${A['residual']:,} ({A['pctGap']*100:.1f}%) {','.join(A['flags']) or 'ok'}")

if __name__ == "__main__":
    main()
