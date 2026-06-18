#!/usr/bin/env python3
"""
Build data/covid.json — a self-contained rollup of the six Region 5 COVID-19 major
disaster declarations (incidentType "Biological", March 2020, statewide). These dwarf
the weather disasters (~7× a state's entire weather PA), so they are kept OUT of the
ledger / geography / hazard analyses and surfaced in their own COVID view instead.

SOURCE / METHOD
  - Costs from OpenFEMA FemaWebDisasterSummaries (PA obligated + Cat A-B / C-G,
    HMGP, IHP approved + Housing/ONA, IA registrations); project count from
    PublicAssistanceFundedProjectsDetails. Identity/date from data/_disasters_raw.json.
  - Category Z (management) = paTotal − paEmergencyAB − paPermanentCG (the remainder),
    same reconciliation the ledger uses. NEEDS NETWORK (CORS-open OpenFEMA).

Re-run any time: python3 scripts/build_covid.py
"""
import os, json, urllib.request, datetime as dt
DATA=os.path.join(os.path.dirname(__file__),"..","data")
COVID={4489:"IL",4494:"MI",4507:"OH",4515:"IN",4520:"WI",4531:"MN"}
STATE_NAME={"IL":"Illinois","IN":"Indiana","MI":"Michigan","MN":"Minnesota","OH":"Ohio","WI":"Wisconsin"}
STATE_POP={"IL":12549689,"IN":6785528,"MI":10037261,"MN":5706494,"OH":11799448,"WI":5893718}
def load(n): return json.load(open(os.path.join(DATA,n)))
def get(u):
    try:
        with urllib.request.urlopen(urllib.request.Request(u,headers={"User-Agent":"DisasterParameters/covid"}),timeout=90) as r:
            return json.loads(r.read().decode("utf-8","replace"))
    except Exception: return None
def n(x):
    try: return round(float(x))
    except Exception: return 0

def main():
    raw={r["disasterNumber"]:r for r in load("_disasters_raw.json")}
    states={}; reg={"paTotal":0,"ihpTotal":0,"paProjects":0,"iaRegistrations":0}
    for dn,st in COVID.items():
        s=(get(f"https://www.fema.gov/api/open/v1/FemaWebDisasterSummaries?$filter=disasterNumber%20eq%20{dn}&$format=json") or {}).get("FemaWebDisasterSummaries",[])
        s=s[0] if s else {}
        pc=get(f"https://www.fema.gov/api/open/v2/PublicAssistanceFundedProjectsDetails?$filter=disasterNumber%20eq%20{dn}&$top=1&$inlinecount=allpages&$format=json")
        proj=((pc or {}).get("metadata") or {}).get("count",0) or 0
        r=raw.get(dn,{})
        paT=n(s.get("totalObligatedAmountPa")); ab=n(s.get("totalObligatedAmountCatAb")); cg=n(s.get("totalObligatedAmountCatC2g"))
        ihp=n(s.get("totalAmountIhpApproved")); pop=STATE_POP[st]
        states[st]={"name":STATE_NAME[st],"dn":dn,"begin":r.get("begin"),"end":r.get("end"),
            "title":r.get("title") or "COVID-19 PANDEMIC","pop":pop,
            "paTotal":paT,"paEmergencyAB":ab,"paPermanentCG":cg,"catZ":max(0,paT-ab-cg),
            "hmgp":n(s.get("totalObligatedAmountHmgp")),"paProjects":int(proj),
            "ihpTotal":ihp,"ihpHousing":n(s.get("totalAmountHaApproved")),"ihpOna":n(s.get("totalAmountOnaApproved")),
            "iaRegistrations":int(s.get("totalNumberIaApproved") or 0),
            "paPerCapita":round(paT/pop,2),"ihpPerCapita":round(ihp/pop,2)}
        reg["paTotal"]+=paT; reg["ihpTotal"]+=ihp; reg["paProjects"]+=int(proj); reg["iaRegistrations"]+=states[st]["iaRegistrations"]
        print(f"  DR-{dn} {st}: PA ${paT:,} · IHP ${ihp:,} · {proj} projects")
    out={"generated":dt.date.today().isoformat()[:7],
         "source":"OpenFEMA FemaWebDisasterSummaries + PublicAssistanceFundedProjectsDetails (COVID-19, incidentType Biological)",
         "note":"Region 5 COVID-19 major disaster declarations (March 2020, statewide). PA is obligated; IHP is approved. Kept separate from the weather ledger because these obligations are ~7× a state's entire weather PA.",
         "region":reg,"states":states}
    json.dump(out,open(os.path.join(DATA,"covid.json"),"w"),separators=(",",":"))
    print(f"wrote data/covid.json — region PA ${reg['paTotal']:,} · IHP ${reg['ihpTotal']:,}")

if __name__=="__main__":
    main()
