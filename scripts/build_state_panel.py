#!/usr/bin/env python3
"""
Lift the enriched COUNTY x episode panel up to the STATE-INCIDENT level — the unit at
which FEMA actually declares and reports (a governor requests for the state; OpenFEMA
reports PA obligated / IHP approved per disaster number; the statewide per-capita
indicator is assessed on the state aggregate). One row per (state, episode_id), with
features AGGREGATED over the member counties — the catastrophe-model chain
Hazard -> Exposure -> Vulnerability -> Loss with a declaration/threshold layer on top.

Input  : data/county_panel.json (built by build_panel.py + the enrichers; git-ignored)
Output : data/state_panel.json  (git-ignored intermediate — the modeling table)

Emitted fields per state-episode:
  state, episodeId, begin, end, season, incidentType,
  nCounties, nCountiesOverThreshold, nCountiesOverFlood,
  sumPopExposed, sumHousingExposed, sumDamageProxy,
  maxRainDayMaxIn, sumRainFootprintIn, rainEventARIyr,
  maxFtAboveFlood, maxSnowDepthPreIn, maxSnowMeltIn,
  maxSnowfallEventIn, maxSnowfallDayMaxIn, maxSweAntecedentIn, maxSweMeltIn,
  totTornadoes, maxEF, maxGustMph, maxHailIn,
  declared, dn, paTotal, ihpTotal, disasterAgeYears, mature

Run from repo root (after build_panel.py + enrichers):  python3 scripts/build_state_panel.py
"""
import os, json, datetime as dt, collections
HERE=os.path.dirname(os.path.abspath(__file__)); ROOT=os.path.dirname(HERE); DATA=os.path.join(ROOT,"data")
TODAY=dt.date.today()

def season(m):
    return {12:"winter",1:"winter",2:"winter",3:"spring",4:"spring",5:"spring",
            6:"summer",7:"summer",8:"summer",9:"fall",10:"fall",11:"fall"}[m]

def dominant_incident(rows):
    """Infer the state-episode's dominant incident type from member-county signals."""
    if any(r.get("flood") for r in rows): floods=sum(1 for r in rows if r.get("flood"))
    else: floods=0
    tors=sum(r.get("tor",0) for r in rows)
    winter=sum(1 for r in rows if r.get("winter"))
    gust=max((r.get("gust",0) for r in rows),default=0)
    hail=max((r.get("hail",0) for r in rows),default=0)
    score={"Flood":floods*2,"Tornado":tors*2,"Winter":winter*2,
           "Wind":1 if gust>=60 else 0,"Hail":1 if hail>=1 else 0}
    return max(score,key=score.get) if max(score.values())>0 else "Severe Storm"

def mx(rows,k):  return max((r.get(k) or 0 for r in rows),default=0)
def sm(rows,k):  return sum((r.get(k) or 0 for r in rows))

def main():
    panel=os.path.join(DATA,"county_panel.json")
    if not os.path.exists(panel):
        print("data/county_panel.json not found — run build_panel.py + enrichers first."); return
    rows=json.load(open(panel))
    disasters={d["disasterNumber"]:d for d in json.load(open(os.path.join(DATA,"disasters.json")))}

    groups=collections.defaultdict(list)
    for r in rows: groups[(r["state"],r["ep"])].append(r)

    out=[]
    for (state,ep),g in groups.items():
        begins=[r["begin"] for r in g if r.get("begin")]; ends=[r["end"] for r in g if r.get("end")]
        if not begins: continue
        begin=min(begins); end=max(ends or begins)
        m=int(begin[5:7])
        # declaration label: any member county inside a FEMA window carries a dn
        dns=[r["dn"] for r in g if r.get("declared") and r.get("dn")]
        dn=collections.Counter(dns).most_common(1)[0][0] if dns else None
        d=disasters.get(dn) if dn else None
        pa=(d.get("costs") or {}).get("paTotal",0) if d else 0
        ihp=(d.get("costs") or {}).get("ihpTotal",0) if d else 0
        age=None; mature=False
        if d:
            age=round((TODAY-dt.date.fromisoformat(d["begin"])).days/365.25,1); mature=age>=2
        over_flood=sum(1 for r in g if (r.get("ftAboveFlood") or 0)>0 or r.get("flood"))
        # "over threshold" = a county clearing a notable hazard bar (flood/EF1+/gust>=60/hail>=1)
        over_thr=sum(1 for r in g if r.get("flood") or (r.get("ef",-1)>=1) or (r.get("gust",0)>=60) or (r.get("hail",0)>=1))
        out.append(dict(
            state=state,episodeId=ep,begin=begin,end=end,season=season(m),
            incidentType=dominant_incident(g),
            nCounties=len(g),nCountiesOverThreshold=over_thr,nCountiesOverFlood=over_flood,
            sumPopExposed=sm(g,"population"),sumHousingExposed=sm(g,"housingUnits"),
            sumDamageProxy=round(sm(g,"dmg")),
            maxRainDayMaxIn=round(mx(g,"rainDayMaxIn"),2),sumRainFootprintIn=round(sm(g,"rainEventIn"),1),
            rainEventARIyr=round(mx(g,"rainEventARIyr"),1),
            maxFtAboveFlood=round(mx(g,"ftAboveFlood"),1),
            maxSnowDepthPreIn=round(mx(g,"snowDepthPreIn"),1),maxSnowMeltIn=round(mx(g,"snowMeltIn"),1),
            maxSnowfallEventIn=round(mx(g,"snowfallEventIn"),1),maxSnowfallDayMaxIn=round(mx(g,"snowfallDayMaxIn"),1),
            maxSweAntecedentIn=round(mx(g,"sweAntecedentIn"),2),maxSweMeltIn=round(mx(g,"sweMeltIn"),2),
            totTornadoes=sm(g,"tor"),maxEF=mx(g,"ef"),maxGustMph=round(mx(g,"gust")),maxHailIn=round(mx(g,"hail"),2),
            declared=1 if dn else 0,dn=dn,paTotal=pa,ihpTotal=ihp,
            disasterAgeYears=age,mature=mature))
    json.dump(out,open(os.path.join(DATA,"state_panel.json"),"w"),separators=(",",":"))
    nd=sum(r["declared"] for r in out)
    print(f"state-episodes: {len(out)}  declared: {nd} ({100*nd/max(1,len(out)):.1f}%)")
    print("wrote data/state_panel.json")
    # quick base-rate sanity by state x dominant incident
    bs=collections.defaultdict(lambda:[0,0])
    for r in out:
        c=bs[(r["state"],r["incidentType"])]; c[0]+=r["declared"]; c[1]+=1
    print("declared / episodes by state x dominant incident:")
    for (s,it),(d_,n) in sorted(bs.items()):
        if n>=10: print(f"  {s} {it:<14} {d_:>4}/{n:<5} {100*d_/n:5.1f}%")

if __name__=="__main__":
    main()
