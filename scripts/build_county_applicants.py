#!/usr/bin/env python3
"""
Add per-county TOP APPLICANTS to data/county_declarations.json — and CONSERVE every PA
applicant dollar, including those with no county ("Statewide" / blank), so nothing is
silently dropped from the Geography applicant view.

SOURCE / METHOD
  - OpenFEMA PublicAssistanceFundedProjectsSummaries (v1): one row per
    applicant × county × disaster, with applicantName, federalObligatedAmount and
    numberOfProjects. Aggregated by (county FIPS, applicantName). County name+state →
    FIPS via r5_counties.json. Only the ledger's disasters are counted. NEEDS NETWORK;
    resumable per-disaster cache (data/_paappl_cache.json).

BUCKETING (every row lands somewhere — never `continue`-dropped):
  - inCounty   : (state,county) → an R5 FIPS that is in cd["counties"]  → counties[fips].applicants[]
  - statewide  : county is "Statewide"/blank (state agencies, no county) → states[st].paStatewideApplicants[]
  - undeclared : resolves to an R5 FIPS NOT in cd["counties"]            → audit only (counted, top list)
  - unmatched  : non-R5 state, or a county name that won't resolve       → audit only (counted, top list)

  Emits cd["paApplicantAudit"][state] mirroring cd["ihpAudit"]: per state the $ + project +
  row buckets, the ledger PA total (FemaWebDisasterSummaries, different dataset), the
  cross-dataset residual, and flags. Conservation identity (exact, modulo rounding):
      inCounty + statewide + undeclared + unmatched == totalSummaries
  The county applicant drill (Summaries v1) and county paObligated (Details v2) are different
  endpoints that classify county differently — we conserve + audit, not force them equal.

Stored: counties[fips].applicants = full list sorted by PA ({name,pa,projects,nDisasters,dns});
states[st].paStatewideApplicants = same shape for no-county applicants. nApplicants recomputed.
Additive; run after build_county_map.py, then run dedup_applicants.py. Re-run any time.
"""
import os, json, collections, urllib.request, urllib.parse, time
DATA=os.path.join(os.path.dirname(__file__),"..","data")
ENT="PublicAssistanceFundedProjectsSummaries"
URL=f"https://www.fema.gov/api/open/v1/{ENT}"
STATE_FULL={"Illinois":"IL","Indiana":"IN","Michigan":"MI","Minnesota":"MN","Ohio":"OH","Wisconsin":"WI"}
TOL=0.01
def load(n): return json.load(open(os.path.join(DATA,n)))
def norm(s): return (s or "").lower().replace("(county)","").replace("county","").replace(".","").replace("'","").replace(" ","").replace("-","").strip()
def get(u,retries=4):
    for i in range(retries):
        try:
            with urllib.request.urlopen(urllib.request.Request(u,headers={"User-Agent":"DisasterParameters/appl"}),timeout=120) as r:
                return json.loads(r.read().decode("utf-8","replace"))
        except Exception: time.sleep(2*(i+1))
    return None

def num(x):
    try: return float(x or 0)
    except Exception: return 0.0

def pull_disaster(dn):
    """→ list of [state_full, county, applicantName, pa, projects] aggregated for this disaster."""
    agg=collections.defaultdict(lambda:[0.0,0])
    sel="applicantName,county,state,federalObligatedAmount,numberOfProjects,disasterNumber"
    skip=0
    while True:
        q=urllib.parse.urlencode({"$filter":f"disasterNumber eq {dn}","$select":sel,"$top":1000,"$skip":skip,"$format":"json"})
        d=get(f"{URL}?{q}"); recs=(d or {}).get(ENT,[]) if d else []
        if not recs: break
        for r in recs:
            k=(r.get("state") or "", r.get("county") or "", r.get("applicantName") or "(unnamed)")
            a=agg[k]; a[0]+=num(r.get("federalObligatedAmount")); a[1]+=int(num(r.get("numberOfProjects")))
        skip+=len(recs)
        if len(recs)<1000: break
    return [[k[0],k[1],k[2],round(v[0],2),v[1]] for k,v in agg.items()]

def main():
    cd=load("county_declarations.json")
    name2fips={(c["s"],norm(c["n"])):c["f"] for c in load("r5_counties.json")}
    disasters=load("disasters.json"); dns=[d["disasterNumber"] for d in disasters]
    ledger=collections.defaultdict(float)
    for d in disasters: ledger[d["state"]]+=num((d.get("costs") or {}).get("paTotal"))

    cache_path=os.path.join(DATA,"_paappl_cache.json")
    cache=json.load(open(cache_path)) if os.path.exists(cache_path) else {}
    for i,dn in enumerate(dns,1):
        if str(dn) in cache: continue
        cache[str(dn)]=pull_disaster(dn)
        json.dump(cache,open(cache_path,"w"),separators=(",",":"))
        print(f"  [{i}/{len(dns)}] DR-{dn}: {len(cache[str(dn)])} applicant-county rows")

    def B(): return {"pa":0.0,"proj":0,"dns":set()}
    county=collections.defaultdict(B)          # (fips,name)
    statewide=collections.defaultdict(B)       # (st,name)
    undeclared=collections.defaultdict(B)      # (st,name,fips)
    unmatched=collections.defaultdict(B)       # (st,name,county)
    counties=cd["counties"]
    for dn,rows in cache.items():
        dn=int(dn)
        for st_full,cnty,name,pa,proj in rows:
            st=STATE_FULL.get(st_full)
            def add(d,key):
                b=d[key]; b["pa"]+=pa; b["proj"]+=proj; b["dns"].add(dn)
            if not st: add(unmatched,(st_full,name,cnty)); continue
            nc=norm(cnty)
            if not nc or nc=="statewide": add(statewide,(st,name)); continue
            fips=name2fips.get((st,nc))
            if fips and fips in counties: add(county,(fips,name))
            elif fips: add(undeclared,(st,name,fips))
            else: add(unmatched,(st,name,cnty))

    # --- write county applicants ---
    for c in counties.values(): c.pop("applicants",None); c["nApplicants"]=0
    byc=collections.defaultdict(list)
    for (fips,name),v in county.items():
        byc[fips].append({"name":name,"pa":round(v["pa"]),"projects":v["proj"],"nDisasters":len(v["dns"]),"dns":sorted(v["dns"])})
    for fips,apps in byc.items():
        apps.sort(key=lambda a:-a["pa"]); counties[fips]["applicants"]=apps; counties[fips]["nApplicants"]=len(apps)

    # --- write per-state statewide (no-county) applicants ---
    for st in cd["states"]: cd["states"][st].pop("paStatewideApplicants",None)
    bys=collections.defaultdict(list)
    for (st,name),v in statewide.items():
        bys[st].append({"name":name,"pa":round(v["pa"]),"projects":v["proj"],"nDisasters":len(v["dns"]),"dns":sorted(v["dns"])})
    for st,apps in bys.items():
        apps.sort(key=lambda a:-a["pa"])
        if st in cd["states"]: cd["states"][st]["paStatewideApplicants"]=apps

    # --- conservation audit ---
    def by_state(d, idx):
        o=collections.defaultdict(lambda:[0.0,0,0])
        for k,v in d.items(): o[k[idx]][0]+=v["pa"]; o[k[idx]][1]+=v["proj"]; o[k[idx]][2]+=1
        return o
    cby={}
    for (fips,name),v in county.items():
        stt=counties[fips]["state"]; e=cby.setdefault(stt,[0.0,0,0]); e[0]+=v["pa"]; e[1]+=v["proj"]; e[2]+=1
    sby=by_state(statewide,0); uby=by_state(undeclared,0); xby=by_state(unmatched,0)
    topU=collections.Counter(); topX=collections.Counter()
    for (st,name,fips),v in undeclared.items(): topU[f"{st}|{fips}|{name}"]+=round(v["pa"])
    for (st,name,cnty),v in unmatched.items(): topX[f"{st}|{cnty}|{name}"]+=round(v["pa"])
    audit={}
    for st in cd["states"]:
        ic=cby.get(st,[0,0,0]); sw=sby.get(st,[0,0,0]); ud=uby.get(st,[0,0,0]); xm=xby.get(st,[0,0,0])
        total=ic[0]+sw[0]+ud[0]+xm[0]; led=ledger.get(st,0.0); resid=led-total
        flags=[]
        if ud[0]>0: flags.append("UNDECLARED_$")
        if xm[0]>0: flags.append("UNMATCHED_$")
        if led and abs(resid)/led>TOL: flags.append(f"LEDGER_GAP_{resid/led*100:.1f}%")
        audit[st]={"ledgerPA":round(led),"totalSummaries":round(total),
                   "inCounty":round(ic[0]),"statewide":round(sw[0]),"undeclared":round(ud[0]),"unmatched":round(xm[0]),
                   "residualVsLedger":round(resid),"pctGap":round(resid/led,4) if led else 0,
                   "inCountyProjects":ic[1],"statewideProjects":sw[1],"undeclaredProjects":ud[1],"unmatchedProjects":xm[1],
                   "inCountyRows":ic[2],"statewideRows":sw[2],"undeclaredRows":ud[2],"unmatchedRows":xm[2],
                   "flags":flags}
    audit["_meta"]={"note":"Applicant $ = PublicAssistanceFundedProjectsSummaries v1 (per applicant×county). "
                    "inCounty+statewide+undeclared+unmatched == totalSummaries (every row bucketed). ledgerPA = "
                    "FemaWebDisasterSummaries (different dataset) → residual is cross-dataset, not a drop. "
                    "Undeclared = applicant in an R5 county with no declaration record; unmatched = non-R5 or unresolved name.",
                    "tolerance":TOL,
                    "topUndeclared":[{"key":k,"pa":v} for k,v in topU.most_common(10)],
                    "topUnmatched":[{"key":k,"pa":v} for k,v in topX.most_common(10)]}
    cd["paApplicantAudit"]=audit
    cd["source"]=cd.get("source","")+" + applicants from PublicAssistanceFundedProjectsSummaries (no-county→paStatewideApplicants; conservation audit)"
    json.dump(cd,open(os.path.join(DATA,"county_declarations.json"),"w"),separators=(",",":"))

    # report
    nz=lambda x:f"${x:,.0f}"
    print(f"\nmerged applicants into {sum(1 for c in counties.values() if c.get('applicants'))} counties · "
          f"statewide lists in {sum(1 for st in cd['states'] if cd['states'][st].get('paStatewideApplicants'))} states")
    print(f"{'ST':3} {'ledger PA':>14} {'total v1':>14} {'inCounty':>14} {'statewide':>13} {'undecl':>10} {'unmatch':>10}  flags")
    for st in cd["states"]:
        A=audit[st]
        print(f"{st:3} {nz(A['ledgerPA']):>14} {nz(A['totalSummaries']):>14} {nz(A['inCounty']):>14} "
              f"{nz(A['statewide']):>13} {nz(A['undeclared']):>10} {nz(A['unmatched']):>10}  {','.join(A['flags']) or 'ok'}")
    if topU: print("  top undeclared:",topU.most_common(5))
    if topX: print("  top unmatched:",topX.most_common(5))

if __name__=="__main__":
    main()
