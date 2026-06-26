#!/usr/bin/env python3
"""OFFLINE: add per-county + per-state-statewide HMGP (Hazard Mitigation Grant
Program, Stafford 404) obligated $ and subrecipient lists to
data/county_declarations.json. Every dollar is conserved: a project lands in its
county (if that county is in the declaration rollup) or in the state's STATEWIDE
bucket (subrecipient=Statewide, no county, or a non-declared county).

Source: OpenFEMA HazardMitigationAssistanceProjects v4 (programArea=HMGP). Needs
network. Run from repo root:  python3 scripts/build_county_hmgp.py
"""
import json, os, urllib.request, urllib.parse, time
HERE=os.path.dirname(os.path.abspath(__file__)); ROOT=os.path.dirname(HERE); DATA=os.path.join(ROOT,"data")
FIPS2AB={"17":"IL","18":"IN","26":"MI","27":"MN","39":"OH","55":"WI"}
def fetch(url,timeout=50,retries=4):
    for _ in range(retries):
        try:
            with urllib.request.urlopen(url,timeout=timeout) as r: return r.read().decode("utf-8","replace")
        except Exception: time.sleep(1.0)
    return None
def hmgp_projects(dn):
    out=[]; skip=0
    for _ in range(12):
        flt=urllib.parse.quote(f"disasterNumber eq {dn} and programArea eq 'HMGP'")
        sel=urllib.parse.quote("subrecipient,stateNumberCode,countyCode,county,federalShareObligated,projectType,status,numberOfProperties,initialObligationDate,dateApproved")
        u=(f"https://www.fema.gov/api/open/v4/HazardMitigationAssistanceProjects"
           f"?$filter={flt}&$select={sel}&$top=1000&$skip={skip}&$format=json")
        txt=fetch(u)
        if not txt: break
        recs=json.loads(txt).get("HazardMitigationAssistanceProjects",[])
        if not recs: break
        out+=recs; skip+=len(recs)
        if len(recs)<1000: break
    return out

cd=json.load(open(os.path.join(DATA,"county_declarations.json")))
dis=json.load(open(os.path.join(DATA,"disasters.json")))
cty=cd["counties"]; states=cd["states"]
dns=[d["disasterNumber"] for d in dis if (d.get("costs") or {}).get("hmgp")]
print(f"{len(dns)} R5 disasters with HMGP; pulling projects…")

def newapps(): return {}
def addapp(d,name,r,fed,dn):
    a=d.setdefault(name,{"hmgp":0.0,"projects":0,"dns":set(),"types":{},"props":0,"d0":None,"d1":None,"counties":set(),"status":{}})
    a["hmgp"]+=fed; a["projects"]+=1; a["dns"].add(dn)
    for piece in str(r.get("projectType") or "").split(";"):
        piece=piece.strip()
        if piece: a["types"][piece]=a["types"].get(piece,0)+1
    try: a["props"]+=int(float(r.get("numberOfProperties") or 0))
    except Exception: pass
    od=str(r.get("initialObligationDate") or r.get("dateApproved") or "")[:10]
    if len(od)==10:
        if not a["d0"] or od<a["d0"]: a["d0"]=od
        if not a["d1"] or od>a["d1"]: a["d1"]=od
    cn=(r.get("county") or "").strip()
    if cn: a["counties"].add(cn)
    stts=(r.get("status") or "").strip()
    if stts: a["status"][stts]=a["status"].get(stts,0)+1
cAgg={}; sAgg={s:{"hmgp":0.0,"apps":newapps()} for s in states}; total_by_state={s:0.0 for s in states}
for i,dn in enumerate(dns):
    recs=hmgp_projects(dn); time.sleep(0.1)
    for r in recs:
        fed=float(r.get("federalShareObligated") or 0)
        sub=(r.get("subrecipient") or "(unnamed)").strip()
        sc,cc=r.get("stateNumberCode"),r.get("countyCode")
        ab=FIPS2AB.get(f"{int(sc):02d}") if sc not in (None,"") else None
        if ab is None: continue                 # outside Region 5
        total_by_state[ab]=total_by_state.get(ab,0)+fed
        fips=f"{int(sc):02d}{int(cc):03d}" if cc not in (None,"") else None
        if sub.lower()=="statewide" or not fips or fips not in cty:
            sAgg[ab]["hmgp"]+=fed; addapp(sAgg[ab]["apps"],sub,r,fed,dn)        # -> STATEWIDE bucket
        else:
            a=cAgg.setdefault(fips,{"hmgp":0.0,"apps":newapps()}); a["hmgp"]+=fed; addapp(a["apps"],sub,r,fed,dn)
    print(f"  [{i+1}/{len(dns)}] DR-{dn}: {len(recs)} proj")

def applist(apps):
    L=[]
    for k,v in apps.items():
        types=[t for t,_ in sorted(v["types"].items(),key=lambda x:-x[1])][:4]
        L.append({"name":k,"hmgp":round(v["hmgp"]),"projects":v["projects"],"nDisasters":len(v["dns"]),"dns":sorted(v["dns"]),
                  "types":types,"props":v["props"],"d0":v["d0"],"d1":v["d1"],
                  "counties":sorted(v["counties"])[:8]})
    L.sort(key=lambda x:-x["hmgp"]); return L
for fips,a in cAgg.items():
    cty[fips]["hmgpObligated"]=round(a["hmgp"]); cty[fips]["hmgpApplicants"]=applist(a["apps"]); cty[fips]["nHmgpApplicants"]=len(a["apps"])
for ab,st in states.items():
    csum=sum(round(a["hmgp"]) for f,a in cAgg.items() if cty.get(f,{}).get("state")==ab)
    sw=round(sAgg[ab]["hmgp"])
    st["hmgpObligated"]=csum+sw; st["hmgpStatewide"]=sw; st["hmgpStatewideApplicants"]=applist(sAgg[ab]["apps"])
    print(f"  {ab}: total ${st['hmgpObligated']:,}  (county ${csum:,} + statewide ${sw:,})  | project-feed ${round(total_by_state[ab]):,}")
json.dump(cd,open(os.path.join(DATA,"county_declarations.json"),"w"),separators=(",",":"))
print(f"wrote HMGP: {len(cAgg)} counties + statewide buckets for {len(states)} states")
