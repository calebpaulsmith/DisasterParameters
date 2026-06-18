#!/usr/bin/env python3
"""
Add per-county TOP APPLICANTS to data/county_declarations.json so the Geography view
can drill from a county into the organizations that received Public Assistance there.

SOURCE / METHOD
  - OpenFEMA PublicAssistanceFundedProjectsSummaries (v1): one row per
    applicant × county × disaster, with applicantName, federalObligatedAmount and
    numberOfProjects. We aggregate by (county FIPS, applicantName): PA obligated,
    project count, and the set of disasters. County name+state → FIPS via
    r5_counties.json. Only the ledger's disasters are counted. NEEDS NETWORK.
  - Stored as counties[fips].applicants = top 15 by PA obligated, each
    {name, pa, projects, nDisasters, dns[]}. Additive; run after build_county_map.py.

Re-run any time: python3 scripts/build_county_applicants.py
"""
import os, json, collections, urllib.request, urllib.parse, time
DATA=os.path.join(os.path.dirname(__file__),"..","data")
ENT="PublicAssistanceFundedProjectsSummaries"
URL=f"https://www.fema.gov/api/open/v1/{ENT}"
STATE_FULL={"Illinois":"IL","Indiana":"IN","Michigan":"MI","Minnesota":"MN","Ohio":"OH","Wisconsin":"WI"}
def load(n): return json.load(open(os.path.join(DATA,n)))
def norm(s): return (s or "").lower().replace("(county)","").replace("county","").replace(".","").replace("'","").replace(" ","").replace("-","").strip()
def get(u,retries=4):
    for i in range(retries):
        try:
            with urllib.request.urlopen(urllib.request.Request(u,headers={"User-Agent":"DisasterParameters/appl"}),timeout=120) as r:
                return json.loads(r.read().decode("utf-8","replace"))
        except Exception: time.sleep(2*(i+1))
    return None

def main():
    cd=load("county_declarations.json")
    name2fips={(c["s"],norm(c["n"])):c["f"] for c in load("r5_counties.json")}
    dns=[d["disasterNumber"] for d in load("disasters.json")]

    # (fips, applicantName) -> {pa, projects, dns:set}
    agg=collections.defaultdict(lambda:{"pa":0.0,"projects":0,"dns":set()})
    sel="applicantName,county,state,federalObligatedAmount,numberOfProjects,disasterNumber"
    for k,dn in enumerate(dns,1):
        skip=0; got=0
        while True:
            q=urllib.parse.urlencode({"$filter":f"disasterNumber eq {dn}","$select":sel,"$top":1000,"$skip":skip,"$format":"json"})
            d=get(f"{URL}?{q}"); recs=(d or {}).get(ENT,[]) if d else []
            if not recs: break
            for r in recs:
                st=STATE_FULL.get(r.get("state"))
                fips=name2fips.get((st,norm(r.get("county"))))
                if not fips: continue
                try: amt=float(r.get("federalObligatedAmount") or 0)
                except Exception: amt=0.0
                a=agg[(fips,r.get("applicantName") or "(unnamed)")]
                a["pa"]+=amt; a["projects"]+=int(r.get("numberOfProjects") or 0); a["dns"].add(dn)
            got+=len(recs); skip+=len(recs)
            if len(recs)<1000: break
        print(f"  [{k}/{len(dns)}] DR-{dn}: {got} applicant-county rows")

    by_county=collections.defaultdict(list)
    for (fips,name),v in agg.items():
        by_county[fips].append({"name":name,"pa":round(v["pa"]),"projects":v["projects"],
                                "nDisasters":len(v["dns"]),"dns":sorted(v["dns"])})
    nset=0
    for fips,apps in by_county.items():
        if fips in cd["counties"]:
            apps.sort(key=lambda a:-a["pa"])
            cd["counties"][fips]["applicants"]=apps[:15]
            cd["counties"][fips]["nApplicants"]=len(apps)
            nset+=1
    cd["source"]=cd.get("source","")+" + top applicants from PublicAssistanceFundedProjectsSummaries"
    json.dump(cd,open(os.path.join(DATA,"county_declarations.json"),"w"),separators=(",",":"))
    print(f"merged applicants into {nset} counties")

if __name__=="__main__":
    main()
