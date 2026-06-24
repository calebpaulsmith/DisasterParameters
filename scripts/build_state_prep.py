#!/usr/bin/env python3
"""OFFLINE: per-STATE non-disaster PREPAREDNESS grants for the Geography view:
EMPG (EmergencyManagementPerformanceGrants) + AFG (NonDisasterAssistance-
FirefighterGrants). Both are state-level (no county). Stores totals plus, for the
state-grant presentation: by-YEAR series, EMPG by project type, AFG by program,
and top AFG recipient departments. All-time. Needs network.
Run from repo root:  python3 scripts/build_state_prep.py
"""
import json, os, urllib.request, urllib.parse, time, re
HERE=os.path.dirname(os.path.abspath(__file__)); ROOT=os.path.dirname(HERE); DATA=os.path.join(ROOT,"data")
NAMES={"IL":"Illinois","IN":"Indiana","MI":"Michigan","MN":"Minnesota","OH":"Ohio","WI":"Wisconsin"}
def fetch(url,timeout=55,retries=4):
    for _ in range(retries):
        try:
            with urllib.request.urlopen(url,timeout=timeout) as r: return r.read().decode("utf-8","replace")
        except Exception: time.sleep(1.0)
    return None
def pages(ent,ver,flt,sel):
    out=[]; skip=0
    for _ in range(60):
        u=f"https://www.fema.gov/api/open/{ver}/{ent}?$filter={urllib.parse.quote(flt)}&$select={urllib.parse.quote(sel)}&$top=1000&$skip={skip}&$format=json"
        txt=fetch(u)
        if not txt: break
        recs=json.loads(txt).get(ent,[])
        if not recs: break
        out+=recs; skip+=len(recs)
        if len(recs)<1000: break
    return out
def yr(s):
    m=re.search(r"(19|20)\d\d",str(s or "")); return m.group(0) if m else None
def srt(d,n=None):
    L=sorted(d.items(),key=lambda x:-x[1]); L=L[:n] if n else L; return {k:round(v) for k,v in L}
cd=json.load(open(os.path.join(DATA,"county_declarations.json"))); states=cd["states"]
for ab,full in NAMES.items():
    empg=pages("EmergencyManagementPerformanceGrants","v2",f"state eq '{full}'","fundingAmount,reportingPeriod,projectType")
    eByYear={}; eByType={}; et=0.0
    for r in empg:
        amt=float(r.get("fundingAmount") or 0); et+=amt
        y=yr(r.get("reportingPeriod")); 
        if y: eByYear[y]=eByYear.get(y,0)+amt
        t=(r.get("projectType") or "Other").strip(); eByType[t]=eByType.get(t,0)+amt
    afg=pages("NonDisasterAssistanceFirefighterGrants","v1",f"vendorState eq '{ab}'","awardAmount,vendorName,fiscalYear,programName")
    aByYear={}; aByProg={}; vend={}; at=0.0
    for r in afg:
        amt=float(r.get("awardAmount") or 0); at+=amt
        y=str(r.get("fiscalYear") or "").strip()[:4]
        if y: aByYear[y]=aByYear.get(y,0)+amt
        p=(r.get("programName") or "AFG").strip(); aByProg[p]=aByProg.get(p,0)+amt
        vend[r.get("vendorName") or "?"]=vend.get(r.get("vendorName") or "?",0)+amt
    if ab in states:
        st=states[ab]
        st["empg"]=round(et); st["empgByYear"]=srt(eByYear); st["empgByType"]=srt(eByType,12)
        st["afg"]=round(at); st["afgByYear"]=srt(aByYear); st["afgByProgram"]=srt(aByProg,8)
        st["afgVendors"]=[{"name":k,"afg":round(v)} for k,v in sorted(vend.items(),key=lambda x:-x[1])[:40]]; st["nAfg"]=len(afg)
    print(f"  {ab}: EMPG ${round(et):,} ({len(empg)}, {len(eByYear)}y, {len(eByType)} types) · AFG ${round(at):,} ({len(afg)}, {len(aByYear)}y, {len(aByProg)} progs)")
json.dump(cd,open(os.path.join(DATA,"county_declarations.json"),"w"),separators=(",",":"))
print("wrote EMPG+AFG with by-year / breakdowns / recipients")
