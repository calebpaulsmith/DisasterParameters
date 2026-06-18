#!/usr/bin/env python3
"""
Build data/county_declarations.json — the geographic rollup behind the county map and
the Geography view. Per COUNTY: how many times it's been in a declared disaster, the
list of those disasters, and the real Public-Assistance dollars OBLIGATED + project
worksheets there. Per STATE: disasters, PA obligated, projects, IHP approved.

SOURCE / METHOD
  - Designated counties per disaster: OpenFEMA pull cached in data/_disasters_raw.json
    (`counties` = {3-digit code: name}, with `stateFips`). Full FIPS = stateFips+code.
    Counted only for disasters in data/disasters.json (the committed ledger), so the map
    and ledger agree; date/type/title/tags come from there.
  - Per-county PA dollars + projects: OpenFEMA PublicAssistanceFundedProjectsDetails
    (one record per project worksheet), summing `federalShareObligated` and counting
    worksheets by stateNumberCode+countyCode. Worksheets with no county (statewide /
    management) go to a per-state `statewide` bucket, so county sums + statewide = the
    state's project obligation. NEEDS NETWORK (CORS-open OpenFEMA); offline/regenerable.
  - Per-state totals (paObligated, paProjects, ihpApproved, nDisasters): summed straight
    from data/disasters.json so the state view matches the ledger exactly.

ADDITIVE / IDEMPOTENT. Re-run any time: python3 scripts/build_county_map.py
"""
import os, json, collections, datetime as dt, urllib.request, urllib.parse, time

DATA=os.path.join(os.path.dirname(__file__),"..","data")
STATE_NAME={"IL":"Illinois","IN":"Indiana","MI":"Michigan","MN":"Minnesota","OH":"Ohio","WI":"Wisconsin"}
STATE_POP={"IL":12549689,"IN":6785528,"MI":10037261,"MN":5706494,"OH":11799448,"WI":5893718}
PA_URL="https://www.fema.gov/api/open/v2/PublicAssistanceFundedProjectsDetails"

def load(name): return json.load(open(os.path.join(DATA,name)))

def get(url,retries=4):
    for i in range(retries):
        try:
            req=urllib.request.Request(url,headers={"User-Agent":"DisasterParameters/geo (public open data)"})
            with urllib.request.urlopen(req,timeout=90) as r:
                return json.loads(r.read().decode("utf-8","replace"))
        except Exception:
            time.sleep(2*(i+1))
    return None

def pull_pa_by_county(dns):
    """disasterNumber set → (county_fips -> {pa,projects}), (state -> {pa,projects} statewide bucket)."""
    county=collections.defaultdict(lambda:{"pa":0.0,"projects":0})
    statewide=collections.defaultdict(lambda:{"pa":0.0,"projects":0})
    sel="disasterNumber,stateNumberCode,countyCode,county,federalShareObligated"
    for k,dn in enumerate(sorted(dns),1):
        skip=0; got=0
        while True:
            q=urllib.parse.urlencode({"$filter":f"disasterNumber eq {dn}","$select":sel,
                                      "$top":1000,"$skip":skip,"$format":"json"})
            d=get(f"{PA_URL}?{q}")
            recs=(d or {}).get("PublicAssistanceFundedProjectsDetails",[]) if d else []
            if not recs: break
            for r in recs:
                amt=r.get("federalShareObligated") or 0
                try: amt=float(amt)
                except Exception: amt=0.0
                sc=str(r.get("stateNumberCode") or "").zfill(2)
                cc=r.get("countyCode")
                if cc and str(cc).strip() and str(cc)!="000":
                    fips=sc+str(cc).zfill(3)
                    county[fips]["pa"]+=amt; county[fips]["projects"]+=1
                else:
                    statewide[sc]["pa"]+=amt; statewide[sc]["projects"]+=1
            got+=len(recs); skip+=len(recs)
            if len(recs)<1000: break
        print(f"  [{k}/{len(dns)}] DR-{dn}: {got} project worksheets")
    return county, statewide

def main():
    raw=load("_disasters_raw.json"); disasters=load("disasters.json")
    geo={c["f"]:c for c in load("r5_counties.json")}
    by_dn={r["disasterNumber"]:r for r in raw}
    meta={d["disasterNumber"]:d for d in disasters}
    sfips2abbr={str(r.get("stateFips")).zfill(2):r.get("state") for r in raw if r.get("stateFips") and r.get("state")}

    # --- per-county designations + disaster lists (from the committed ledger) ---
    dn_fips=collections.defaultdict(set)
    for dn,r in by_dn.items():
        if dn not in meta: continue
        sf=str(r.get("stateFips") or "").zfill(2)
        for code in (r.get("counties") or {}): dn_fips[dn].add(sf+str(code).zfill(3))
    missing=[dn for dn in meta if not dn_fips.get(dn)]
    if missing:
        miss=set(missing)
        for row in load("county_panel.json"):
            if row.get("declared") and row.get("dn") in miss and row.get("fips"):
                dn_fips[row["dn"]].add(row["fips"])

    counties={}
    for dn,fipset in dn_fips.items():
        d=meta[dn]
        rec={"dn":dn,"date":d.get("begin"),"end":d.get("end"),"it":d.get("incidentType"),
             "title":d.get("title"),"tags":d.get("tags",[]),
             "pa":(d.get("costs") or {}).get("paTotal",0),"ihp":(d.get("costs") or {}).get("ihpTotal",0)}
        for fips in fipset:
            g=geo.get(fips)
            if not g: continue
            c=counties.setdefault(fips,{"name":g["n"],"state":g["s"],"count":0,"paObligated":0,"paProjects":0,"disasters":[]})
            c["disasters"].append(rec)

    # --- per-county PA obligated $ + projects (from PA Funded Projects Details) ---
    print(f"pulling PA project detail for {len(meta)} disasters…")
    pa_county,pa_state=pull_pa_by_county(set(meta))
    for fips,v in pa_county.items():
        g=geo.get(fips)
        if not g: continue
        c=counties.setdefault(fips,{"name":g["n"],"state":g["s"],"count":0,"paObligated":0,"paProjects":0,"disasters":[]})
        c["paObligated"]=round(v["pa"]); c["paProjects"]=v["projects"]

    for fips,c in counties.items():
        c["disasters"].sort(key=lambda x:(x["date"] or ""),reverse=True)
        c["count"]=len(c["disasters"])

    # --- per-state rollup (from the committed ledger = matches the table) ---
    states={}
    for s in STATE_NAME:
        ds=[d for d in disasters if d["state"]==s]
        states[s]={"name":STATE_NAME[s],"pop":STATE_POP[s],"nDisasters":len(ds),
            "paObligated":sum((d.get("costs") or {}).get("paTotal",0) for d in ds),
            "paProjects":sum((d.get("costs") or {}).get("paProjects",0) for d in ds),
            "ihpApproved":sum((d.get("costs") or {}).get("ihpTotal",0) for d in ds)}
    statewide={sfips2abbr.get(sf,sf):{"paObligated":round(v["pa"]),"paProjects":v["projects"]}
               for sf,v in pa_state.items() if sfips2abbr.get(sf) in STATE_NAME}

    out={"generated":dt.date.today().isoformat()[:7],
         "source":"OpenFEMA designated areas + PublicAssistanceFundedProjectsDetails (federalShareObligated) joined to the committed ledger",
         "nCounties":len(counties),"nWithAny":sum(1 for c in counties.values() if c["count"]),
         "maxCount":max((c["count"] for c in counties.values()),default=0),
         "maxPA":max((c["paObligated"] for c in counties.values()),default=0),
         "maxProjects":max((c["paProjects"] for c in counties.values()),default=0),
         "states":states,"statewide":statewide,"counties":counties}
    p=os.path.join(DATA,"county_declarations.json")
    json.dump(out,open(p,"w"),separators=(",",":"))
    print(f"wrote {p}: {len(counties)} counties · max {out['maxCount']} decl · "
          f"max ${out['maxPA']:,} PA · max {out['maxProjects']} projects")

if __name__=="__main__":
    main()
