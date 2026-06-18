#!/usr/bin/env python3
"""
Add per-county IHP (Individual & Households Program) APPROVED dollars to
data/county_declarations.json, so the Geography map can toggle to a fourth metric.

SOURCE / METHOD
  - OpenFEMA IndividualsAndHouseholdsProgramValidRegistrations, one row per registrant.
    We pull only $select=county,damagedStateAbbreviation,ihpAmount and sum ihpAmount by
    county (mapping the registrant's county NAME + state to a 5-digit FIPS via
    r5_counties.json), plus a registrant count. ~1.08M rows for the 80 ledger disasters,
    so we $select just 3 fields and CACHE per-disaster aggregates (data/_ihp_cache.json)
    to stay resumable. NEEDS NETWORK (CORS-open OpenFEMA); offline/regenerable.
  - IHP is APPROVED (not obligated) — kept distinct from PA throughout.

ADDITIVE: merges ihpApproved + iaRegistrations into the existing county_declarations.json
(run build_county_map.py first). Re-run any time: python3 scripts/build_county_ihp.py
"""
import os, json, collections, urllib.request, urllib.parse, time
DATA=os.path.join(os.path.dirname(__file__),"..","data")
URL="https://www.fema.gov/api/open/v2/IndividualsAndHouseholdsProgramValidRegistrations"
def load(n): return json.load(open(os.path.join(DATA,n)))
def norm(s): return (s or "").lower().replace("(county)","").replace("county","").replace(".","").replace("'","").replace(" ","").replace("-","").strip()

def get(url,retries=4):
    for i in range(retries):
        try:
            with urllib.request.urlopen(urllib.request.Request(url,headers={"User-Agent":"DisasterParameters/ihp"}),timeout=120) as r:
                return json.loads(r.read().decode("utf-8","replace"))
        except Exception: time.sleep(2*(i+1))
    return None

def pull_disaster(dn):
    """→ {fips_or_name_key: {ihp, n}} keyed by (state, normname)."""
    agg=collections.defaultdict(lambda:{"ihp":0.0,"n":0}); skip=0
    sel="county,damagedStateAbbreviation,ihpAmount"
    while True:
        q=urllib.parse.urlencode({"$filter":f"disasterNumber eq {dn}","$select":sel,
                                  "$top":1000,"$skip":skip,"$format":"json"})
        d=get(f"{URL}?{q}")
        recs=(d or {}).get("IndividualsAndHouseholdsProgramValidRegistrations",[]) if d else []
        if not recs: break
        for r in recs:
            st=r.get("damagedStateAbbreviation"); key=(st,norm(r.get("county")))
            try: amt=float(r.get("ihpAmount") or 0)
            except Exception: amt=0.0
            agg[key]["ihp"]+=amt; agg[key]["n"]+=1
        skip+=len(recs)
        if len(recs)<1000: break
    return {f"{k[0]}|{k[1]}":v for k,v in agg.items()}

def main():
    cd=load("county_declarations.json")
    geo=load("r5_counties.json")
    name2fips={(c["s"],norm(c["n"])):c["f"] for c in geo}
    dns=[d["disasterNumber"] for d in load("disasters.json")]

    cache_path=os.path.join(DATA,"_ihp_cache.json")
    cache=json.load(open(cache_path)) if os.path.exists(cache_path) else {}
    for i,dn in enumerate(dns,1):
        if str(dn) in cache: continue
        cache[str(dn)]=pull_disaster(dn)
        json.dump(cache,open(cache_path,"w"),separators=(",",":"))
        print(f"  [{i}/{len(dns)}] DR-{dn}: {len(cache[str(dn)])} county-buckets")

    by_fips=collections.defaultdict(lambda:{"ihp":0.0,"n":0}); unmatched=collections.Counter()
    for dn,buckets in cache.items():
        for key,v in buckets.items():
            st,nm=key.split("|",1); fips=name2fips.get((st,nm))
            if not fips: unmatched[key]+=v["n"]; continue
            by_fips[fips]["ihp"]+=v["ihp"]; by_fips[fips]["n"]+=v["n"]

    counties=cd["counties"]
    for fips,c in counties.items(): c["ihpApproved"]=0; c["iaRegistrations"]=0
    for fips,v in by_fips.items():
        if fips in counties:
            counties[fips]["ihpApproved"]=round(v["ihp"]); counties[fips]["iaRegistrations"]=v["n"]
    cd["maxIHP"]=max((c.get("ihpApproved",0) for c in counties.values()),default=0)
    cd["source"]=cd.get("source","")+" + IHP approved from IndividualsAndHouseholdsProgramValidRegistrations"
    json.dump(cd,open(os.path.join(DATA,"county_declarations.json"),"w"),separators=(",",":"))
    print(f"merged IHP into {len(by_fips)} counties · maxIHP ${cd['maxIHP']:,} · "
          f"{sum(unmatched.values())} registrations in {len(unmatched)} unmatched county-keys")
    if unmatched: print("  top unmatched:",unmatched.most_common(6))

if __name__=="__main__":
    main()
