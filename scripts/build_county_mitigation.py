#!/usr/bin/env python3
"""OFFLINE: add per-county NON-DISASTER hazard-mitigation grant $ (FMA, PDM,
BRIC, LPDM, RFC, SRL — everything in HMA projects except HMGP) to
data/county_declarations.json, as a separate "mitigation investment" layer.

These are competitive/annual grants NOT tied to a disaster declaration. Source:
OpenFEMA HazardMitigationAssistanceProjects v4. Dollars conserved: a project
lands in its county (if in the rollup) or the state's STATEWIDE bucket.
Run from repo root:  python3 scripts/build_county_mitigation.py
"""
import json, os, urllib.request, urllib.parse, time
HERE=os.path.dirname(os.path.abspath(__file__)); ROOT=os.path.dirname(HERE); DATA=os.path.join(ROOT,"data")
FIPS2AB={"17":"IL","18":"IN","26":"MI","27":"MN","39":"OH","55":"WI"}
def fetch(url,timeout=55,retries=4):
    for _ in range(retries):
        try:
            with urllib.request.urlopen(url,timeout=timeout) as r: return r.read().decode("utf-8","replace")
        except Exception: time.sleep(1.0)
    return None
def projects(sc):
    out=[]; skip=0
    for _ in range(30):
        flt=urllib.parse.quote(f"stateNumberCode eq '{sc}' and programArea ne 'HMGP'")
        sel=urllib.parse.quote("programArea,subrecipient,countyCode,federalShareObligated,projectAmount")
        u=(f"https://www.fema.gov/api/open/v4/HazardMitigationAssistanceProjects"
           f"?$filter={flt}&$select={sel}&$top=1000&$skip={skip}&$format=json")
        txt=fetch(u)
        if not txt: break
        recs=json.loads(txt).get("HazardMitigationAssistanceProjects",[])
        if not recs: break
        out+=recs; skip+=len(recs)
        if len(recs)<1000: break
    return out

cd=json.load(open(os.path.join(DATA,"county_declarations.json"))); cty=cd["counties"]; states=cd["states"]
cAgg={}; sAgg={s:{"mit":0.0,"prog":{},"apps":{}} for s in states}; total={s:0.0 for s in states}
def addprog(d,pa,fed): d[pa]=d.get(pa,0)+fed
def addapp(d,nm,fed): d[nm]=d.get(nm,0)+fed
for sc,ab in FIPS2AB.items():
    recs=projects(sc); time.sleep(0.1); n=0
    for r in recs:
        fed=float(r.get("federalShareObligated") or r.get("projectAmount") or 0)
        pa=r.get("programArea") or "?"; sub=(r.get("subrecipient") or "(unnamed)").strip()
        cc=r.get("countyCode"); fips=f"{sc}{int(cc):03d}" if cc not in (None,"") else None
        total[ab]+=fed
        if sub.lower()=="statewide" or not fips or fips not in cty:
            sAgg[ab]["mit"]+=fed; addprog(sAgg[ab]["prog"],pa,fed); addapp(sAgg[ab]["apps"],sub,fed)
        else:
            a=cAgg.setdefault(fips,{"mit":0.0,"prog":{},"apps":{}}); a["mit"]+=fed; addprog(a["prog"],pa,fed); addapp(a["apps"],sub,fed); n+=1
    print(f"  {ab}: {len(recs)} non-HMGP projects, {n} county-tied")
def applist(d): 
    L=[{"name":k,"mit":round(v)} for k,v in d.items()]; L.sort(key=lambda x:-x["mit"]); return L
def progmap(d): return {k:round(v) for k,v in sorted(d.items(),key=lambda x:-x[1])}
for fips,a in cAgg.items():
    cty[fips]["mitObligated"]=round(a["mit"]); cty[fips]["mitByProgram"]=progmap(a["prog"]); cty[fips]["mitApplicants"]=applist(a["apps"])[:40]; cty[fips]["nMitApplicants"]=len(a["apps"])
for ab,st in states.items():
    csum=sum(round(a["mit"]) for f,a in cAgg.items() if cty.get(f,{}).get("state")==ab); sw=round(sAgg[ab]["mit"])
    st["mitObligated"]=csum+sw; st["mitStatewide"]=sw; st["mitByProgram"]=progmap(sAgg[ab]["prog"]) if False else None
    st["mitStatewideApplicants"]=applist(sAgg[ab]["apps"])   # no-county mit grantees — browsable, mirrors hmgpStatewideApplicants
    # state-level program totals = county + statewide
    pall={}
    for f,a in cAgg.items():
        if cty.get(f,{}).get("state")==ab:
            for k,v in a["prog"].items(): pall[k]=pall.get(k,0)+v
    for k,v in sAgg[ab]["prog"].items(): pall[k]=pall.get(k,0)+v
    st["mitByProgram"]=progmap(pall)
    print(f"  {ab}: total ${st['mitObligated']:,} (county ${csum:,} + statewide ${sw:,}) | feed ${round(total[ab]):,} | {st['mitByProgram']}")
json.dump(cd,open(os.path.join(DATA,"county_declarations.json"),"w"),separators=(",",":"))
print(f"wrote non-disaster mitigation for {len(cAgg)} counties + statewide buckets")
