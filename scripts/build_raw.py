#!/usr/bin/env python3
"""
Rebuild data/_disasters_raw.json — the GIT-IGNORED intermediate that carries each
Region 5 disaster's designated COUNTIES (FIPS) and stateFips. The committed
data/disasters.json has dates/costs/hazards but NOT the per-disaster county list,
and build_panel.py needs that county list to label which county-episodes are
"declared". add_history.py only ever APPENDS to _disasters_raw.json, so a fresh
clone (where the file is git-ignored and absent) has no way to reproduce it — this
script does, by re-pulling OpenFEMA DisasterDeclarationsSummaries for the R5 states.

Output schema (one object per disaster, matching what add_history.py writes):
  disasterNumber, state, title, incidentType, begin, end, fy,
  iaDeclared, paDeclared, stateFips, counties {3-digit FIPS: area name}

Run from repo root:  python3 scripts/build_raw.py
Network-only (OpenFEMA, CORS/public). Re-pull is idempotent.
"""
import os, json, time, urllib.request, urllib.parse
HERE=os.path.dirname(os.path.abspath(__file__)); ROOT=os.path.dirname(HERE); DATA=os.path.join(ROOT,"data")
R5=["IL","IN","MI","MN","OH","WI"]
# disasters.json spans FY2008-2026; pad the window so nothing is missed.
START_FY, END_FY = 2007, 2027

def get(url, tries=4):
    for _ in range(tries):
        try:
            with urllib.request.urlopen(url, timeout=60) as r: return json.load(r)
        except Exception: time.sleep(1.5)
    return None

def pull():
    base="https://www.fema.gov/api/open/v2/DisasterDeclarationsSummaries"
    sel=("disasterNumber,state,declarationType,declarationTitle,incidentType,"
         "incidentBeginDate,incidentEndDate,fyDeclared,ihProgramDeclared,"
         "paProgramDeclared,fipsStateCode,fipsCountyCode,designatedArea")
    out={}
    for st in R5:
        skip=0
        while True:
            flt=(f"state eq '{st}' and declarationType eq 'DR' "
                 f"and fyDeclared ge {START_FY} and fyDeclared le {END_FY}")
            url=f"{base}?$filter={urllib.parse.quote(flt)}&$select={sel}&$top=1000&$skip={skip}&$format=json"
            d=get(url); rows=(d or {}).get("DisasterDeclarationsSummaries",[])
            if not rows: break
            for r in rows:
                dn=r["disasterNumber"]; o=out.get(dn)
                if o is None:
                    o=out[dn]=dict(
                        disasterNumber=dn, state=r["state"], title=r["declarationTitle"],
                        incidentType=r["incidentType"], begin=r["incidentBeginDate"][:10],
                        end=(r.get("incidentEndDate") or r["incidentBeginDate"])[:10],
                        fy=r["fyDeclared"], iaDeclared=bool(r.get("ihProgramDeclared")),
                        paDeclared=bool(r.get("paProgramDeclared")),
                        stateFips=r["fipsStateCode"], counties={})
                cc=r.get("fipsCountyCode")
                if cc and cc!="000":
                    o["counties"][cc]=(r.get("designatedArea") or "").replace(" (County)","")
            skip+=1000
            if len(rows)<1000: break
        print(f"  {st}: {sum(1 for v in out.values() if v['state']==st)} disasters")
    return out

def main():
    pulled=pull()
    # Keep the disasters present in the committed disasters.json (the source of truth),
    # but write every R5 DR we pulled so the file is a faithful superset for the panel.
    dn_have={x["disasterNumber"] for x in json.load(open(os.path.join(DATA,"disasters.json")))}
    recs=sorted(pulled.values(), key=lambda x:-x["disasterNumber"])
    missing=sorted(dn_have-{r["disasterNumber"] for r in recs})
    if missing:
        print(f"  WARN: {len(missing)} disasters in disasters.json not returned by OpenFEMA: {missing}")
    json.dump(recs, open(os.path.join(DATA,"_disasters_raw.json"),"w"), separators=(",",":"))
    ncty=sum(len(r["counties"]) for r in recs)
    print(f"wrote {len(recs)} raw disasters ({ncty} designated counties) -> data/_disasters_raw.json")
    print(f"  ({len(dn_have & {r['disasterNumber'] for r in recs})}/{len(dn_have)} disasters.json rows have county lists)")

if __name__=="__main__":
    main()
