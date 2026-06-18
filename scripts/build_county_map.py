#!/usr/bin/env python3
"""
Build data/county_declarations.json — per-county federal-declaration frequency for the
Region 5 ledger map. For every county we record HOW MANY times it has been in a declared
disaster, plus WHICH disasters (number, date, incident type, title, tags) so the map can
drill down on click.

SOURCE / METHOD
  - Designated counties per disaster come from the OpenFEMA pull cached in
    data/_disasters_raw.json (`counties` = {3-digit county code: name}, with `stateFips`).
    Full county FIPS = stateFips(2) + code(3).
  - We count ONLY disasters that are in data/disasters.json (the committed ledger), so the
    map and the ledger agree, and we pull each disaster's date/type/title/tags from there.
  - Any ledger disaster missing counties in the raw pull (e.g. a very recent one) is filled
    from data/county_panel.json declared rows (fips where that disaster declared the county).
  - County names/states are normalized against data/r5_counties.json (the map geometry) so
    every emitted FIPS lines up with a drawable polygon.

ADDITIVE / LOCAL / IDEMPOTENT — reads committed JSON only, no network. Re-run any time.
"""
import os, json, collections, datetime as dt

DATA=os.path.join(os.path.dirname(__file__),"..","data")
def load(name): return json.load(open(os.path.join(DATA,name)))

def main():
    raw=load("_disasters_raw.json")
    disasters=load("disasters.json")
    geo={c["f"]:c for c in load("r5_counties.json")}          # fips -> {f,n,s,g}
    by_dn={r["disasterNumber"]:r for r in raw}
    meta={d["disasterNumber"]:d for d in disasters}

    # disasterNumber -> set(5-digit fips) of designated counties
    dn_fips=collections.defaultdict(set)
    for dn,r in by_dn.items():
        if dn not in meta: continue
        sf=str(r.get("stateFips") or "").zfill(2)
        for code in (r.get("counties") or {}):
            fips=sf+str(code).zfill(3)
            dn_fips[dn].add(fips)

    # fill any ledger disaster with no raw counties from the county panel (declared rows)
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
            if not g: continue                                  # outside R5 geometry — skip
            c=counties.setdefault(fips,{"name":g["n"],"state":g["s"],"count":0,"disasters":[]})
            c["disasters"].append(rec)
    for fips,c in counties.items():
        c["disasters"].sort(key=lambda x:(x["date"] or ""),reverse=True)
        c["count"]=len(c["disasters"])

    maxc=max((c["count"] for c in counties.values()),default=0)
    out={"generated":dt.date.today().isoformat()[:7],
         "source":"OpenFEMA designated areas (DisasterDeclarationsSummaries) joined to the committed ledger",
         "nCounties":len(counties),"nWithAny":sum(1 for c in counties.values() if c["count"]),
         "maxCount":maxc,"counties":counties}
    p=os.path.join(DATA,"county_declarations.json")
    json.dump(out,open(p,"w"),separators=(",",":"))
    print(f"wrote {p}: {len(counties)} counties, max {maxc} declarations, "
          f"{out['nWithAny']} with ≥1")

if __name__=="__main__":
    main()
