#!/usr/bin/env python3
"""
Refresh the AUTHORITATIVE cost figures for every disaster already in data/disasters.json
from OpenFEMA, and propagate them into the geography rollup — obligations reconcile for
years, so recent disasters' figures move long after the row was first added (e.g. DR-4880
MI PA went $12.4M → $64.2M between mid-2025 pulls and Aug 2026).

WHAT IT TOUCHES (nothing else — hazards/gages/identity are left alone):
  - disasters.json: costs.* (FemaWebDisasterSummaries: PA total/A-B/C-G, HMGP, IHP
    HA/ONA, IA registrations) + costs.paProjects (PublicAssistanceFundedProjectsDetails
    $inlinecount) + the pa/ihp mirrors.
  - county_declarations.json: each county's disasters[] entries' DR-wide pa/ihp figures;
    per-state rollups (nDisasters/paObligated/paProjects/ihpApproved/ihpHousing/ihpOna/
    iaRegistrations — all ledger-sourced by design); the ihpAudit LEDGER side + flags
    (registrant side untouched — that's a different dataset, see build_county_ihp.py);
    the ihpByYear proxy buckets (state = ledger by incident year; county = allocation
    weighted by DR-wide IHP, mirroring build_county_byyear.py).

County paObligated/paByYear (worksheet-level) and county IHP $ (registrant-level) come
from their own datasets and are NOT re-pulled here — the audit blocks report the
cross-dataset residuals. Needs network (~2 requests per disaster). Run any time:
    python3 scripts/refresh_ledger_costs.py
"""
import os, sys, json, collections, urllib.request, time

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "..", "data")

def load(n): return json.load(open(os.path.join(DATA, n)))
def num(x):
    try: return float(x or 0)
    except Exception: return 0.0
def yr(s):
    s = str(s or "")[:4]
    return s if (s.isdigit() and "1990" <= s <= "2099") else None
def srt(d): return {k: round(v) for k, v in sorted(d.items()) if round(v)}

def get(url, retries=4):
    for i in range(retries):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "DisasterParameters/cost-refresh"}), timeout=60) as r:
                return json.loads(r.read().decode("utf-8", "replace"))
        except Exception:
            time.sleep(1.5 * (i + 1))
    return None

def pull_costs(dn):
    d = get(f"https://www.fema.gov/api/open/v1/FemaWebDisasterSummaries?$filter=disasterNumber%20eq%20{dn}&$format=json")
    arr = (d or {}).get("FemaWebDisasterSummaries", []); s = arr[0] if arr else {}
    pc = get("https://www.fema.gov/api/open/v2/PublicAssistanceFundedProjectsDetails"
             f"?$filter=disasterNumber%20eq%20{dn}&$top=1&$inlinecount=allpages&$format=json")
    proj = ((pc or {}).get("metadata") or {}).get("count", 0) or 0
    n = lambda x: round(num(x))
    return dict(paTotal=n(s.get("totalObligatedAmountPa")), paEmergencyAB=n(s.get("totalObligatedAmountCatAb")),
                paPermanentCG=n(s.get("totalObligatedAmountCatC2g")), paProjects=int(proj),
                hmgp=n(s.get("totalObligatedAmountHmgp")), ihpTotal=n(s.get("totalAmountIhpApproved")),
                ihpHousing=n(s.get("totalAmountHaApproved")), ihpOna=n(s.get("totalAmountOnaApproved")),
                iaRegistrations=int(num(s.get("totalNumberIaApproved"))))

def main():
    disasters = load("disasters.json")
    moved = 0
    for i, d in enumerate(disasters, 1):
        dn = d["disasterNumber"]
        c = pull_costs(dn)
        old = d.get("costs") or {}
        if any(c[k] != old.get(k) for k in c):
            moved += 1
            print(f"  [{i}/{len(disasters)}] DR-{dn}-{d['state']}: PA {old.get('paTotal',0):,} -> {c['paTotal']:,} · "
                  f"IHP {old.get('ihpTotal',0):,} -> {c['ihpTotal']:,} · projects {old.get('paProjects',0)} -> {c['paProjects']}")
        d["costs"] = c; d["pa"] = c["paTotal"]; d["ihp"] = c["ihpTotal"]
    json.dump(disasters, open(os.path.join(DATA, "disasters.json"), "w"), separators=(",", ":"))
    print(f"refreshed costs: {moved}/{len(disasters)} disasters moved; wrote disasters.json")

    # ---- propagate into county_declarations.json ----
    cd = load("county_declarations.json")
    meta = {d["disasterNumber"]: d for d in disasters}
    for c in cd["counties"].values():
        for x in c.get("disasters", []):
            m = meta.get(x["dn"])
            if m:
                x["pa"] = (m.get("costs") or {}).get("paTotal", 0)
                x["ihp"] = (m.get("costs") or {}).get("ihpTotal", 0)

    L = collections.defaultdict(lambda: {"n": 0, "pa": 0.0, "proj": 0, "ihp": 0.0, "ha": 0.0, "ona": 0.0, "reg": 0})
    for d in disasters:
        c = d.get("costs") or {}; s = L[d["state"]]
        s["n"] += 1; s["pa"] += num(c.get("paTotal")); s["proj"] += int(c.get("paProjects") or 0)
        s["ihp"] += num(c.get("ihpTotal")); s["ha"] += num(c.get("ihpHousing")); s["ona"] += num(c.get("ihpOna"))
        s["reg"] += int(c.get("iaRegistrations") or 0)
    ihp_state = collections.defaultdict(lambda: collections.defaultdict(float))
    for d in disasters:
        y = yr(d.get("begin")); ih = num((d.get("costs") or {}).get("ihpTotal"))
        if y and ih: ihp_state[d["state"]][y] += ih
    for ab, st in cd["states"].items():
        s = L[ab]
        st["nDisasters"] = s["n"]; st["paObligated"] = round(s["pa"]); st["paProjects"] = s["proj"]
        st["ihpApproved"] = round(s["ihp"]); st["ihpHousing"] = round(s["ha"]); st["ihpOna"] = round(s["ona"])
        st["iaRegistrations"] = s["reg"]
        y = srt(ihp_state.get(ab, {}))
        if y: st["ihpByYear"] = y
        if ab in cd.get("ihpAudit", {}):
            A = cd["ihpAudit"][ab]
            A["ledgerIhp"] = round(s["ihp"]); A["ledgerHa"] = round(s["ha"]); A["ledgerOna"] = round(s["ona"]); A["ledgerReg"] = s["reg"]
            A["residual"] = A["ledgerIhp"] - A["registrantTotal"]
            pct = (A["residual"] / A["ledgerIhp"]) if A["ledgerIhp"] else 0.0
            A["pctGap"] = round(pct, 4)
            flags = []
            if A["undeclared"] > 0: flags.append("UNDECLARED_COUNTY_$")
            if A["unmatched"] > 0: flags.append("UNMATCHED_NAME_$")
            if abs(pct) > 0.01: flags.append(f"LEDGER_GAP_{pct*100:.1f}%")
            A["flags"] = flags

    # county ihpByYear proxy: same allocation as build_county_byyear.py, with the fresh DR weights
    for o in cd["counties"].values():
        tot = o.get("ihpApproved", 0) or 0; ds = o.get("disasters") or []
        if not tot or not ds: continue
        wsum = sum((x.get("ihp") or 0) for x in ds)
        acc = collections.defaultdict(float)
        for x in ds:
            y = yr(x.get("date"))
            if not y: continue
            w = (x.get("ihp") or 0)
            acc[y] += tot * (w / wsum) if wsum else tot / len(ds)
        if srt(acc): o["ihpByYear"] = srt(acc)

    json.dump(cd, open(os.path.join(DATA, "county_declarations.json"), "w"), separators=(",", ":"))
    print("propagated into county_declarations.json (DR-wide figures, state rollups, ihpAudit ledger side, ihpByYear)")
    for ab in sorted(cd["states"]):
        A = cd.get("ihpAudit", {}).get(ab, {})
        if A:
            print(f"  {ab}: ledger IHP ${A['ledgerIhp']:,} · registrant ${A['registrantTotal']:,} · "
                  f"residual ${A['residual']:,} ({A['pctGap']*100:.1f}%) {','.join(A['flags']) or 'ok'}")

if __name__ == "__main__":
    main()
