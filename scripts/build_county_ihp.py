#!/usr/bin/env python3
"""
Add per-county + per-state IHP (Individuals & Households Program) APPROVED dollars to
data/county_declarations.json, split into Housing Assistance (HA) + Other Needs Assistance (ONA),
plus IA registrations — so the Geography view can break the IA side down by metric.

SOURCE / METHOD
  - COUNTY $ from OpenFEMA IndividualsAndHouseholdsProgramValidRegistrations, one row per
    registrant. We $select county,damagedStateAbbreviation,ihpAmount,haAmount,onaAmount and sum
    each by county (mapping the registrant's county NAME + state to a 5-digit FIPS via
    r5_counties.json), plus a registrant count. ~1.08M rows for the 80 ledger disasters, so we
    $select just 5 fields and CACHE per-disaster aggregates (data/_ihp_cache.json) to stay
    resumable. NEEDS NETWORK (CORS-open OpenFEMA); offline/regenerable.
  - STATE $ come from the LEDGER (data/disasters.json costs: ihpHousing/ihpOna/ihpTotal/
    iaRegistrations summed by state) — authoritative FemaWebDisasterSummaries figures, NO network.
  - IHP is APPROVED (not obligated) — kept distinct from PA throughout.

DOLLAR-CONSERVATION AUDIT (cd["ihpAudit"])
  County $ (registrant pull) and state $ (ledger) are DIFFERENT OpenFEMA datasets, so they do not
  reconcile by construction. Every registrant dollar is bucketed per state into:
    inSet      — landed in a DECLARED county (written to the map)
    undeclared — a valid R5 county that is NOT in this region's declared county set
    unmatched  — county name could not be resolved to a FIPS (or non-R5 state)
  and compared against the ledger state total. Nothing is dropped silently: undeclared/unmatched
  money and the cross-dataset residual (ledger - registrant_total) are reported on the console
  (WARN lines) and persisted in cd["ihpAudit"] for traceability.

ADDITIVE: merges county ihpApproved/ihpHousing/ihpOna/iaRegistrations + state
ihpHousing/ihpOna/iaRegistrations + ihpAudit into the existing county_declarations.json
(run build_county_map.py first). Re-run any time: python3 scripts/build_county_ihp.py
"""
import os, json, collections, urllib.request, urllib.parse, time
DATA=os.path.join(os.path.dirname(__file__),"..","data")
URL="https://www.fema.gov/api/open/v2/IndividualsAndHouseholdsProgramValidRegistrations"
SEL="county,damagedStateAbbreviation,ihpAmount,haAmount,onaAmount"
TOL=0.01  # 1% cross-dataset gap before we flag a state
def load(n): return json.load(open(os.path.join(DATA,n)))
def norm(s): return (s or "").lower().replace("(county)","").replace("county","").replace(".","").replace("'","").replace(" ","").replace("-","").strip()
def newb(): return {"ihp":0.0,"ha":0.0,"ona":0.0,"n":0}
def addb(dst,src):
    for k in ("ihp","ha","ona","n"): dst[k]+=src[k]

def get(url,retries=4):
    for i in range(retries):
        try:
            with urllib.request.urlopen(urllib.request.Request(url,headers={"User-Agent":"DisasterParameters/ihp"}),timeout=120) as r:
                return json.loads(r.read().decode("utf-8","replace"))
        except Exception: time.sleep(2*(i+1))
    return None

def num(x):
    try: return float(x or 0)
    except Exception: return 0.0

def pull_disaster(dn):
    """→ {state|normname: {ihp,ha,ona,n}}."""
    agg=collections.defaultdict(newb); skip=0
    while True:
        q=urllib.parse.urlencode({"$filter":f"disasterNumber eq {dn}","$select":SEL,
                                  "$top":1000,"$skip":skip,"$format":"json"})
        d=get(f"{URL}?{q}")
        recs=(d or {}).get("IndividualsAndHouseholdsProgramValidRegistrations",[]) if d else []
        if not recs: break
        for r in recs:
            st=r.get("damagedStateAbbreviation"); key=f"{st}|{norm(r.get('county'))}"
            b=agg[key]; b["ihp"]+=num(r.get("ihpAmount")); b["ha"]+=num(r.get("haAmount"))
            b["ona"]+=num(r.get("onaAmount")); b["n"]+=1
        skip+=len(recs)
        if len(recs)<1000: break
    return dict(agg)

def fresh(entry):
    """True if a cached per-disaster entry already carries the HA/ONA schema."""
    if not entry: return True  # empty pull is validly empty
    return all(("ha" in v and "ona" in v) for v in entry.values())

def main():
    cd=load("county_declarations.json")
    geo=load("r5_counties.json")
    name2fips={(c["s"],norm(c["n"])):c["f"] for c in geo}
    all_r5_fips=set(c["f"] for c in geo)
    disasters=load("disasters.json")
    dns=[d["disasterNumber"] for d in disasters]

    # ---- 1. pull (resumable; re-pull stale {ihp,n}-only cache entries) ----
    cache_path=os.path.join(DATA,"_ihp_cache.json")
    cache=json.load(open(cache_path)) if os.path.exists(cache_path) else {}
    for i,dn in enumerate(dns,1):
        if str(dn) in cache and fresh(cache[str(dn)]): continue
        cache[str(dn)]=pull_disaster(dn)
        json.dump(cache,open(cache_path,"w"),separators=(",",":"))
        print(f"  [{i}/{len(dns)}] DR-{dn}: {len(cache[str(dn)])} county-buckets")

    # ---- 2. aggregate registrant $ by FIPS (for writing) and by state×bucket (for audit) ----
    by_fips=collections.defaultdict(newb)
    audit=collections.defaultdict(lambda:{"inSet":newb(),"undeclared":newb(),"unmatched":newb()})
    top_und=collections.Counter(); top_unm=collections.Counter()
    counties=cd["counties"]
    for dn,buckets in cache.items():
        for key,v in buckets.items():
            st,nm=key.split("|",1); fips=name2fips.get((st,nm))
            if not fips:
                addb(audit[st]["unmatched"],v); top_unm[key]+=int(v["n"]); continue
            addb(by_fips[fips],v)
            if fips in counties: addb(audit[st]["inSet"],v)
            else: addb(audit[st]["undeclared"],v); top_und[f"{st}|{fips}|{nm}"]+=int(v["n"])

    # ---- 3. write per-county HA/ONA/IHP/registrations (declared counties only) ----
    for c in counties.values():
        c["ihpApproved"]=0; c["ihpHousing"]=0; c["ihpOna"]=0; c["iaRegistrations"]=0
    for fips,v in by_fips.items():
        if fips in counties:
            counties[fips]["ihpApproved"]=round(v["ihp"]); counties[fips]["ihpHousing"]=round(v["ha"])
            counties[fips]["ihpOna"]=round(v["ona"]); counties[fips]["iaRegistrations"]=int(v["n"])
    cd["maxIHP"]=max((c.get("ihpApproved",0) for c in counties.values()),default=0)
    cd["maxIhpHousing"]=max((c.get("ihpHousing",0) for c in counties.values()),default=0)
    cd["maxIhpOna"]=max((c.get("ihpOna",0) for c in counties.values()),default=0)

    # ---- 4. state rollup from the LEDGER (no network) ----
    ledger=collections.defaultdict(lambda:{"ihp":0.0,"ha":0.0,"ona":0.0,"reg":0})
    for d in disasters:
        st=d.get("state"); c=d.get("costs",{}) or {}
        L=ledger[st]; L["ihp"]+=num(c.get("ihpTotal")); L["ha"]+=num(c.get("ihpHousing"))
        L["ona"]+=num(c.get("ihpOna")); L["reg"]+=int(num(c.get("iaRegistrations")))
    for st,L in ledger.items():
        if st in cd["states"]:
            s=cd["states"][st]
            s["ihpHousing"]=round(L["ha"]); s["ihpOna"]=round(L["ona"])
            s["iaRegistrations"]=int(L["reg"])
            # leave existing s["ihpApproved"] (set by build_county_map) intact

    # ---- 5. conservation audit ----
    ihpAudit={}
    for st in cd["states"]:
        a=audit.get(st,{"inSet":newb(),"undeclared":newb(),"unmatched":newb()})
        L=ledger.get(st,{"ihp":0,"ha":0,"ona":0,"reg":0})
        reg_total=a["inSet"]["ihp"]+a["undeclared"]["ihp"]+a["unmatched"]["ihp"]
        residual=L["ihp"]-reg_total
        pct=(residual/L["ihp"]) if L["ihp"] else 0.0
        flags=[]
        if a["undeclared"]["ihp"]>0: flags.append("UNDECLARED_COUNTY_$")
        if a["unmatched"]["ihp"]>0:  flags.append("UNMATCHED_NAME_$")
        if abs(pct)>TOL:             flags.append(f"LEDGER_GAP_{pct*100:.1f}%")
        ihpAudit[st]={
            "ledgerIhp":round(L["ihp"]),"ledgerHa":round(L["ha"]),"ledgerOna":round(L["ona"]),"ledgerReg":int(L["reg"]),
            "countyInSet":round(a["inSet"]["ihp"]),"undeclared":round(a["undeclared"]["ihp"]),"unmatched":round(a["unmatched"]["ihp"]),
            "registrantTotal":round(reg_total),"residual":round(residual),"pctGap":round(pct,4),
            "inSetReg":int(a["inSet"]["n"]),"undeclaredReg":int(a["undeclared"]["n"]),"unmatchedReg":int(a["unmatched"]["n"]),
            "flags":flags}
    ihpAudit["_meta"]={"note":"County $ = registrant pull (IndividualsAndHouseholdsProgramValidRegistrations); "
                       "state $ = ledger (FemaWebDisasterSummaries). Different datasets — residual = ledger - registrant_total. "
                       "Registrations also differ in kind: county iaRegistrations = valid-registration row count (pull); "
                       "state iaRegistrations = totalNumberIaApproved (ledger, approved) — not directly comparable.",
                       "tolerance":TOL,
                       "topUndeclared":[{"key":k,"n":n} for k,n in top_und.most_common(10)],
                       "topUnmatched":[{"key":k,"n":n} for k,n in top_unm.most_common(10)]}
    cd["ihpAudit"]=ihpAudit
    cd["source"]=cd.get("source","")+" + IHP HA/ONA + registrations (county: IndividualsAndHouseholds"\
                 "ProgramValidRegistrations; state: ledger) with conservation audit"

    json.dump(cd,open(os.path.join(DATA,"county_declarations.json"),"w"),separators=(",",":"))

    # ---- 6. report ----
    nz=lambda x: f"${x:,.0f}"
    print(f"\nmerged IHP HA/ONA into {sum(1 for c in counties.values() if c['ihpApproved'])} counties · "
          f"maxIHP {nz(cd['maxIHP'])}")
    print(f"{'ST':3} {'ledger IHP':>14} {'inSet':>14} {'undeclared':>12} {'unmatched':>11} {'residual':>13} {'gap%':>7}  flags")
    for st in cd["states"]:
        A=ihpAudit[st]
        print(f"{st:3} {nz(A['ledgerIhp']):>14} {nz(A['countyInSet']):>14} {nz(A['undeclared']):>12} "
              f"{nz(A['unmatched']):>11} {nz(A['residual']):>13} {A['pctGap']*100:>6.1f}%  {','.join(A['flags']) or 'ok'}")
    warn=[st for st in cd["states"] if ihpAudit[st]["flags"]]
    for st in warn:
        A=ihpAudit[st]
        print(f"WARN {st}: {','.join(A['flags'])} — undeclared {nz(A['undeclared'])} / unmatched {nz(A['unmatched'])} / "
              f"residual {nz(A['residual'])} ({A['pctGap']*100:.1f}% of ledger)")
    if top_und: print("  top undeclared-county keys (state|fips|name : registrants):",top_und.most_common(6))
    if top_unm: print("  top unmatched-name keys (state|name : registrants):",top_unm.most_common(6))
    print(f"\n{len(warn)} state(s) flagged; full per-state reconciliation persisted to county_declarations.json -> ihpAudit")

if __name__=="__main__":
    main()
