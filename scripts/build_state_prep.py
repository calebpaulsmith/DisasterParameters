#!/usr/bin/env python3
"""OFFLINE: add per-state NON-DISASTER PREPAREDNESS grant $ to
data/county_declarations.json states: EMPG (Emergency Management Performance
Grants) and AFG (Assistance to Firefighters Grants). Both are state-level (no
county) — a separate preparedness layer. All-time totals. Needs network.
Run from repo root:  python3 scripts/build_state_prep.py
"""
import json, os, urllib.request, urllib.parse, time
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
    for _ in range(40):
        u=f"https://www.fema.gov/api/open/{ver}/{ent}?$filter={urllib.parse.quote(flt)}&$select={urllib.parse.quote(sel)}&$top=1000&$skip={skip}&$format=json"
        txt=fetch(u)
        if not txt: break
        recs=json.loads(txt).get(ent,[])
        if not recs: break
        out+=recs; skip+=len(recs)
        if len(recs)<1000: break
    return out
cd=json.load(open(os.path.join(DATA,"county_declarations.json"))); states=cd["states"]
for ab,full in NAMES.items():
    empg=pages("EmergencyManagementPerformanceGrants","v2",f"state eq '{full}'","fundingAmount")
    e=round(sum(float(r.get("fundingAmount") or 0) for r in empg))
    afg=pages("NonDisasterAssistanceFirefighterGrants","v1",f"vendorState eq '{ab}'","awardAmount,vendorName")
    a=round(sum(float(r.get("awardAmount") or 0) for r in afg))
    vend={}
    for r in afg: vend[r.get("vendorName") or "?"]=vend.get(r.get("vendorName") or "?",0)+float(r.get("awardAmount") or 0)
    vlist=[{"name":k,"afg":round(v)} for k,v in sorted(vend.items(),key=lambda x:-x[1])[:30]]
    if ab in states:
        states[ab]["empg"]=e; states[ab]["afg"]=a; states[ab]["afgVendors"]=vlist; states[ab]["nAfg"]=len(afg)
    print(f"  {ab}: EMPG ${e:,} ({len(empg)} awards) · AFG ${a:,} ({len(afg)} awards)")
json.dump(cd,open(os.path.join(DATA,"county_declarations.json"),"w"),separators=(",",":"))
print("wrote per-state EMPG + AFG")
