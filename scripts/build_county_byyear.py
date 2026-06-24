#!/usr/bin/env python3
"""OFFLINE: add per-year OBLIGATION buckets to data/county_declarations.json so the
Geography view can show a "obligations by year" timeline and filter every figure by a
selected year range. ADDITIVE / IDEMPOTENT — only adds *ByYear fields, touches nothing
else (re-run any time: python3 scripts/build_county_byyear.py).

Each county and state gains:
  paByYear   – PublicAssistanceFundedProjectsDetails.federalShareObligated bucketed by
               year(lastObligationDate)         [TRUE obligation year]
  paProjectsByYear – count of PA project worksheets by year(lastObligationDate) (every
               dated worksheet, matching the all-time paProjects)   [TRUE obligation year]
  hmgpByYear – HazardMitigationAssistanceProjects v4 (programArea=HMGP)
               federalShareObligated by year(initialObligationDate)   [TRUE obl. year]
  mitByYear  – HazardMitigationAssistanceProjects v4 (programArea ne HMGP, the non-disaster
               FMA/PDM/BRIC/… layer) by year(initialObligationDate)   [TRUE obligation year]
  ihpByYear  – PROXY: IHP carries no obligation date, so it is bucketed by the disaster's
               INCIDENT/declaration year. State = ledger ihpTotal by year(begin); county =
               its all-time ihpApproved allocated across its disasters' incident years,
               weighted by each disaster's total IHP (conserves the county total).

Bucketing mirrors build_county_map / build_county_hmgp / build_county_mitigation exactly
(dollars conserved: a project lands in its county or the state STATEWIDE bucket), so
sum(*ByYear) reconciles with the existing all-time fields (modulo rows with a null date,
which are dropped — see the "(undated)" reconciliation note surfaced in the UI).

Needs network (CORS-open OpenFEMA). Run from repo root.
"""
import json, os, collections, urllib.request, urllib.parse, time

HERE=os.path.dirname(os.path.abspath(__file__)); ROOT=os.path.dirname(HERE); DATA=os.path.join(ROOT,"data")
FIPS2AB={"17":"IL","18":"IN","26":"MI","27":"MN","39":"OH","55":"WI"}
PA_URL="https://www.fema.gov/api/open/v2/PublicAssistanceFundedProjectsDetails"
HMA_URL="https://www.fema.gov/api/open/v4/HazardMitigationAssistanceProjects"

def get(url,retries=4,timeout=90):
    for i in range(retries):
        try:
            req=urllib.request.Request(url,headers={"User-Agent":"DisasterParameters/byyear (public open data)"})
            with urllib.request.urlopen(req,timeout=timeout) as r:
                return json.loads(r.read().decode("utf-8","replace"))
        except Exception:
            time.sleep(1.5*(i+1))
    return None

def yr(s):
    """ISO date -> 4-digit year string, or None."""
    if not s: return None
    s=str(s)[:4]
    return s if (s.isdigit() and "1990"<=s<="2099") else None

def srt(d):
    return {k:round(v) for k,v in sorted(d.items()) if round(v)}

def main():
    cd=json.load(open(os.path.join(DATA,"county_declarations.json")))
    dis=json.load(open(os.path.join(DATA,"disasters.json")))
    cty=cd["counties"]; states=cd["states"]

    # year accumulators: fips/state -> {year: $}  (+ PA worksheet COUNT by year)
    paC=collections.defaultdict(lambda:collections.defaultdict(float)); paSW=collections.defaultdict(lambda:collections.defaultdict(float))
    pjC=collections.defaultdict(lambda:collections.defaultdict(int)); pjSW=collections.defaultdict(lambda:collections.defaultdict(int))
    hmC=collections.defaultdict(lambda:collections.defaultdict(float)); hmSW=collections.defaultdict(lambda:collections.defaultdict(float))
    miC=collections.defaultdict(lambda:collections.defaultdict(float)); miSW=collections.defaultdict(lambda:collections.defaultdict(float))

    # ---- PA: per committed disaster, federalShareObligated by year(lastObligationDate) ----
    dns=sorted({d["disasterNumber"] for d in dis})
    sel=urllib.parse.quote("disasterNumber,stateNumberCode,countyCode,federalShareObligated,lastObligationDate")
    print(f"PA: pulling project detail for {len(dns)} disasters…")
    for k,dn in enumerate(dns,1):
        skip=0; got=0
        while True:
            flt=urllib.parse.quote(f"disasterNumber eq {dn}")
            d=get(f"{PA_URL}?$filter={flt}&$select={sel}&$top=1000&$skip={skip}&$format=json")
            recs=(d or {}).get("PublicAssistanceFundedProjectsDetails",[]) if d else []
            if not recs: break
            for r in recs:
                y=yr(r.get("lastObligationDate"))
                if not y: continue
                sc=str(r.get("stateNumberCode") or "").zfill(2); cc=r.get("countyCode")
                ab=FIPS2AB.get(sc)
                if not ab: continue
                try: amt=float(r.get("federalShareObligated") or 0)
                except Exception: amt=0.0
                isC = cc and str(cc).strip() and str(cc)!="000"
                fips=sc+str(cc).zfill(3) if isC else None
                if isC: pjC[fips][y]+=1                 # count EVERY dated worksheet (matches all-time paProjects)
                else:   pjSW[ab][y]+=1
                if amt:                                  # dollars: skip zero-share adjustments
                    if isC: paC[fips][y]+=amt
                    else:   paSW[ab][y]+=amt
            got+=len(recs); skip+=len(recs)
            if len(recs)<1000: break
        if k%10==0 or k==len(dns): print(f"  PA [{k}/{len(dns)}] DR-{dn}: {got} worksheets")

    # ---- HMGP: per disaster with HMGP, by year(initialObligationDate) ----
    hdns=[d["disasterNumber"] for d in dis if (d.get("costs") or {}).get("hmgp")]
    hsel=urllib.parse.quote("subrecipient,stateNumberCode,countyCode,federalShareObligated,initialObligationDate")
    print(f"HMGP: pulling projects for {len(hdns)} disasters…")
    for i,dn in enumerate(hdns,1):
        skip=0
        for _ in range(12):
            flt=urllib.parse.quote(f"disasterNumber eq {dn} and programArea eq 'HMGP'")
            d=get(f"{HMA_URL}?$filter={flt}&$select={hsel}&$top=1000&$skip={skip}&$format=json")
            recs=(d or {}).get("HazardMitigationAssistanceProjects",[]) if d else []
            if not recs: break
            for r in recs:
                y=yr(r.get("initialObligationDate"))
                if not y: continue
                fed=float(r.get("federalShareObligated") or 0)
                if not fed: continue
                sub=(r.get("subrecipient") or "").strip().lower()
                sc,cc=r.get("stateNumberCode"),r.get("countyCode")
                ab=FIPS2AB.get(f"{int(sc):02d}") if sc not in (None,"") else None
                if ab is None: continue
                fips=f"{int(sc):02d}{int(cc):03d}" if cc not in (None,"") else None
                if sub=="statewide" or not fips or fips not in cty: hmSW[ab][y]+=fed
                else: hmC[fips][y]+=fed
            skip+=len(recs); time.sleep(0.05)
            if len(recs)<1000: break
        if i%10==0 or i==len(hdns): print(f"  HMGP [{i}/{len(hdns)}] DR-{dn}")

    # ---- non-disaster mitigation: per state, programArea ne HMGP, by year(initialObligationDate) ----
    msel=urllib.parse.quote("programArea,subrecipient,countyCode,federalShareObligated,projectAmount,initialObligationDate")
    print("MIT: pulling non-HMGP HMA projects per state…")
    for sc,ab in FIPS2AB.items():
        skip=0
        for _ in range(30):
            flt=urllib.parse.quote(f"stateNumberCode eq '{sc}' and programArea ne 'HMGP'")
            d=get(f"{HMA_URL}?$filter={flt}&$select={msel}&$top=1000&$skip={skip}&$format=json")
            recs=(d or {}).get("HazardMitigationAssistanceProjects",[]) if d else []
            if not recs: break
            for r in recs:
                y=yr(r.get("initialObligationDate"))
                if not y: continue
                fed=float(r.get("federalShareObligated") or r.get("projectAmount") or 0)
                if not fed: continue
                sub=(r.get("subrecipient") or "").strip().lower(); cc=r.get("countyCode")
                fips=f"{sc}{int(cc):03d}" if cc not in (None,"") else None
                if sub=="statewide" or not fips or fips not in cty: miSW[ab][y]+=fed
                else: miC[fips][y]+=fed
            skip+=len(recs); time.sleep(0.05)
            if len(recs)<1000: break
        print(f"  MIT {ab}: done")

    # ---- IHP proxy (no network): bucket by disaster INCIDENT year ----
    # state: ledger ihpTotal by year(begin); county: allocate ihpApproved across its
    # disasters' incident years weighted by each disaster's total IHP.
    ihpStateByYear=collections.defaultdict(lambda:collections.defaultdict(float))
    for d in dis:
        ab=d.get("state"); y=yr(d.get("begin")); ih=(d.get("costs") or {}).get("ihpTotal",0) or 0
        if ab and y and ih: ihpStateByYear[ab][y]+=ih
    for fips,o in cty.items():
        tot=o.get("ihpApproved",0) or 0
        ds=o.get("disasters") or []
        if not tot or not ds: continue
        wsum=sum((x.get("ihp") or 0) for x in ds)
        acc=collections.defaultdict(float)
        for x in ds:
            y=yr(x.get("date"))
            if not y: continue
            w=(x.get("ihp") or 0)
            acc[y]+= tot*(w/wsum) if wsum else tot/len(ds)
        if acc: o["ihpByYear"]=srt(acc)

    # ---- merge PA/HMGP/MIT byYear into counties + roll up to states ----
    def rollstate(ab,cmap,sw):
        agg=collections.defaultdict(float)
        for f,yrs in cmap.items():
            if cty.get(f,{}).get("state")==ab:
                for y,v in yrs.items(): agg[y]+=v
        for y,v in sw.get(ab,{}).items(): agg[y]+=v
        return srt(agg)
    for f,yrs in paC.items():
        if f in cty and srt(yrs): cty[f]["paByYear"]=srt(yrs)
    for f,yrs in hmC.items():
        if f in cty and srt(yrs): cty[f]["hmgpByYear"]=srt(yrs)
    for f,yrs in miC.items():
        if f in cty and srt(yrs): cty[f]["mitByYear"]=srt(yrs)
    for f,yrs in pjC.items():
        if f in cty and srt(yrs): cty[f]["paProjectsByYear"]=srt(yrs)
    for ab,st in states.items():
        pa=rollstate(ab,paC,paSW); hm=rollstate(ab,hmC,hmSW); mi=rollstate(ab,miC,miSW)
        pj=rollstate(ab,pjC,pjSW); ih=srt(ihpStateByYear.get(ab,{}))
        if pa: st["paByYear"]=pa
        if hm: st["hmgpByYear"]=hm
        if mi: st["mitByYear"]=mi
        if pj: st["paProjectsByYear"]=pj
        if ih: st["ihpByYear"]=ih
        print(f"  {ab}: PA {sum(pa.values()):,} · HMGP {sum(hm.values()):,} · MIT {sum(mi.values()):,} · IHP {sum(ih.values()):,}  ({len(pa)}y/{len(hm)}y/{len(mi)}y/{len(ih)}y)")

    json.dump(cd,open(os.path.join(DATA,"county_declarations.json"),"w"),separators=(",",":"))
    print("wrote *ByYear buckets to county_declarations.json")

if __name__=="__main__":
    main()
