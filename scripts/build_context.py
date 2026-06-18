#!/usr/bin/env python3
"""
Build the SMALL, COMMITTED artifacts for the "Conditions in Context" front end:
  data/context.json     - per state x hazard, the DISTRIBUTION of each driver metric
                          across the state-episode panel, with EXPLICIT declared AND
                          non-declared counts per bin (the denominator), plus the
                          state's hazard profile, real cost summaries, analog
                          disasters, and county flood-stage reference.
  data/event_nexus.json - per disaster, its characterizing driver values pulled from
                          its matched state-episode(s), each placed in history
                          ("events at least this severe: N, of which M were declared").

This is an INFORMATION tool, not a predictor: no probabilities, no thresholds, no
fitted model. Every number is an empirical frequency from the regenerated panel
(declared + non-declared) or a real OpenFEMA dollar figure. It deliberately surfaces
the cases where intensity does NOT separate declared from non-declared (tornado
counts, MN flood rainfall) rather than hiding them.

Inputs : data/state_panel.json, data/county_panel.json, data/disasters.json, data/gages.json
Outputs: data/context.json, data/event_nexus.json   (small, committed)

Run from repo root (after build_state_panel.py):  python3 scripts/build_context.py
"""
import os, json, collections, datetime as dt
HERE=os.path.dirname(os.path.abspath(__file__)); ROOT=os.path.dirname(HERE); DATA=os.path.join(ROOT,"data")
STATE_NAME={"IL":"Illinois","IN":"Indiana","MI":"Michigan","MN":"Minnesota","OH":"Ohio","WI":"Wisconsin"}
STATE_POP={"IL":12549689,"IN":6785528,"MI":10037261,"MN":5706494,"OH":11799448,"WI":5893718}

# ---- which state-episodes belong to each hazard family (compound events count in
#      several families; this is the honest "where does this hazard show up" view) ----
def is_flood(r):   return (r.get("nCountiesOverFlood") or 0)>0 or r.get("incidentType") in ("Flood","Winter") or (r.get("maxFtAboveFlood") or 0)>0
def is_tornado(r): return (r.get("totTornadoes") or 0)>=1
def is_wind(r):    return (r.get("maxGustMph") or 0)>=50
def is_hail(r):    return (r.get("maxHailIn") or 0)>=0.75
def is_winter(r):  return (r.get("maxSnowfallEventIn") or 0)>=1 or r.get("incidentType")=="Winter"
HAZARD_MEMBER={"flood":is_flood,"tornado":is_tornado,"wind":is_wind,"hail":is_hail,"winter":is_winter}

# ---- the driver metric(s) we surface per hazard (panel field, label, unit, bins) ----
# bins: (label, lo, hi) with hi=None meaning open-ended; an episode falls in a bin
# when lo <= value < hi.
DRIVERS={
 "flood":[
   ("maxRainDayMaxIn","peak 1-day rainfall","in",[("<1",0,1),("1–2",1,2),("2–4",2,4),("4–6",4,6),("≥6",6,None)]),
   ("rainEventARIyr","rainfall rarity (Atlas-14 recurrence)","yr",[("<2",0,2),("2–10",2,10),("10–25",10,25),("25–50",25,50),("50–100",50,100),("≥100",100,None)]),
   ("maxFtAboveFlood","river crest above flood stage","ft",[("below",-99,0),("0–2",0,2),("2–5",2,5),("5–10",5,10),("≥10",10,None)]),
   ("maxSweMeltIn","snowmelt water released (est.)","in",[("<0.25",0,0.25),("0.25–0.5",0.25,0.5),("0.5–1",0.5,1),("≥1",1,None)]),
 ],
 "tornado":[
   ("maxEF","peak EF rating","EF",[("EF0",0,1),("EF1",1,2),("EF2",2,3),("EF3+",3,None)]),
   ("totTornadoes","tornado count","",[("1",1,2),("2–3",2,4),("4–7",4,8),("≥8",8,None)]),
 ],
 "wind":[
   ("maxGustMph","peak wind gust","mph",[("50–60",50,60),("60–70",60,70),("70–85",70,85),("85–100",85,100),("≥100",100,None)]),
 ],
 "hail":[
   ("maxHailIn","max hail size","in",[("0.75–1",0.75,1),("1–2",1,2),("2–3",2,3),("≥3",3,None)]),
 ],
 "winter":[
   ("maxSnowfallEventIn","storm-total snowfall","in",[("1–6",1,6),("6–12",6,12),("12–18",12,18),("18–24",18,24),("≥24",24,None)]),
   ("maxSnowfallDayMaxIn","peak 1-day snowfall","in",[("<4",0,4),("4–8",4,8),("8–12",8,12),("≥12",12,None)]),
   ("maxSweAntecedentIn","antecedent snowpack water (est.)","in",[("<1",0,1),("1–2",1,2),("2–4",2,4),("≥4",4,None)]),
 ],
}
# footprint / exposure drivers shown for every state (the real separators per the findings)
FOOTPRINT=[
 ("nCountiesOverThreshold","counties with a notable hazard","",[("1",1,2),("2–3",2,4),("4–7",4,8),("8–15",8,16),("≥16",16,None)]),
 ("sumPopExposed","population in affected counties","",[("<50k",0,50000),("50k–250k",50000,250000),("250k–1M",250000,1000000),("1M–3M",1000000,3000000),("≥3M",3000000,None)]),
 ("sumDamageProxy","Storm Events property damage","$",[("$0",0,1),("<$100k",1,100000),("$100k–1M",100000,1000000),("$1M–10M",1000000,10000000),("≥$10M",10000000,None)]),
]
DRIVER_BASIS={
 "rainEventARIyr":"NOAA Atlas-14 recurrence interval of the event rainfall (county max)",
 "maxFtAboveFlood":"USGS observed crest minus NWS flood stage (gaged counties)",
 "maxSweMeltIn":"ESTIMATE: observed 1-day snow-depth drop × 0.30 settled-snowpack density",
 "maxSweAntecedentIn":"ESTIMATE: observed antecedent snow depth × 0.30 settled-snowpack density",
 "maxSnowfallEventIn":"GHCN storm-total snowfall (county max)",
 "maxSnowfallDayMaxIn":"GHCN peak 1-day snowfall (county max)",
}
HAZARD_CAVEAT={
 "flood":"Rainfall separates declared floods in WI/IL/IN/OH/MI, but NOT in MN — Minnesota floods are spring snowmelt, so watch snowpack/melt and river crest there.",
 "tornado":"Tornado COUNT and EF barely separate declared from non-declared episodes — footprint and property damage are the real separators (see the footprint panels).",
 "wind":"Peak gust is recorded well, but declarations track damage/extent more than the gust value.",
 "hail":"Max hail size is recorded well, but declarations track damage/extent more than the stone size.",
 "winter":"Thin sample (few winter-only declarations); snowfall is real, snowpack water (SWE) is an estimate from observed depth.",
}
HAZARD_LABEL={"flood":"Flooding","tornado":"Tornado","wind":"Wind","hail":"Hail","winter":"Winter storm"}

def pct(vals,p):
    vals=sorted(v for v in vals if v is not None)
    if not vals: return None
    k=(len(vals)-1)*p/100; f=int(k)
    return vals[f]+(vals[min(f+1,len(vals)-1)]-vals[f])*(k-f)

def load(name): return json.load(open(os.path.join(DATA,name)))

def distribution(rows, key, bins):
    """bins with explicit total (n), declared count, and the declared disasters' DR
    numbers (dns) for drill-down — the declared-vs-non denominator, fully traceable."""
    out=[]; any_data=False
    for lab,lo,hi in bins:
        sub=[r for r in rows if (r.get(key) is not None) and r[key]>=lo and (hi is None or r[key]<hi)]
        decl=[r for r in sub if r["declared"]]
        dns=sorted({r["dn"] for r in decl if r.get("dn")})
        if sub: any_data=True
        out.append({"lab":lab,"lo":lo,"hi":hi,"n":len(sub),"declared":len(decl),"dns":dns})
    return out if any_data else None

def at_least(rows, key, value):
    """events with driver >= value: total + declared (the 'compare to past events/non-events' line)."""
    sub=[r for r in rows if (r.get(key) is not None) and r[key]>=value]
    d=sum(r["declared"] for r in sub)
    return {"n":len(sub),"declared":d}

def hazard_profile(srows):
    prof=[]
    for h,member in HAZARD_MEMBER.items():
        mem=[r for r in srows if member(r)]; d=sum(r["declared"] for r in mem)
        if mem: prof.append({"hazard":h,"label":HAZARD_LABEL[h],"nEpisodes":len(mem),
                             "nDeclared":d,"declaredRate":round(d/len(mem),3)})
    return sorted(prof,key=lambda p:-p["declaredRate"])

def county_flood_reference(state,gages,county_rows):
    out={}; by=collections.defaultdict(list)
    for r in county_rows:
        if r["state"]==state: by[r["fips"]].append(r)
    seen={}
    for g in gages:
        if g.get("state")==state and g.get("countyFips"): seen.setdefault(g["countyFips"],g)
    for fips,g in seen.items():
        cr=by.get(fips,[]); d=sum(x["declared"] for x in cr)
        out[fips]={"name":g.get("name"),"river":g.get("river"),"gageId":g.get("id"),
                   "floodStageFt":g.get("floodStage"),"cats":g.get("cats"),
                   "official":bool(g.get("official")),
                   "minDeclStage":g.get("minDeclStage"),"minDeclOver":g.get("minDeclOver"),
                   "nEpisodes":len(cr),"nDeclared":d}
    return out

def analog(d):
    return {"date":d["begin"],"end":d["end"],"dn":d["disasterNumber"],
            "it":d.get("incidentType"),"title":d.get("title"),"tags":d.get("tags",[]),
            "pa":(d.get("costs") or {}).get("paTotal",0),"ihp":(d.get("costs") or {}).get("ihpTotal",0)}

def is_notable(r):
    """A NOTABLE episode = one with NOAA Storm Events property damage > 0. This is the
    declared-rate denominator the maintainer chose: it strips the many trivial $0 NWS
    reports that flatten the curve. CAVEAT: Storm Events under-records riverine/ag flood
    loss, so this excludes some real flood declarations (surfaced per state below)."""
    return (r.get("sumDamageProxy") or 0)>0

def build_context(state_panel,county_panel,disasters,gages):
    states={}
    for s in STATE_NAME:
        srows_all=[r for r in state_panel if r["state"]==s]
        srows=[r for r in srows_all if is_notable(r)]            # notable (damage>0) denominator
        prof=hazard_profile(srows)
        flood0=[r for r in srows_all if is_flood(r) and not is_notable(r) and r["declared"]]
        # per hazard, per driver: distribution over the hazard's member episodes
        dist={}
        for h,member in HAZARD_MEMBER.items():
            mem=[r for r in srows if member(r)]
            if len(mem)<10: continue
            hd={}
            for key,label,unit,bins in DRIVERS[h]:
                b=distribution(mem,key,bins)
                if b: hd[key]={"label":label,"unit":unit,"basis":DRIVER_BASIS.get(key,"regenerated state-episode panel"),"bins":b}
            if hd: dist[h]={"label":HAZARD_LABEL[h],"caveat":HAZARD_CAVEAT[h],"nEpisodes":len(mem),
                            "nDeclared":sum(r["declared"] for r in mem),"drivers":hd}
        # footprint/exposure distributions over all state-episodes that cleared any bar
        fp={}
        active=[r for r in srows if (r.get("nCountiesOverThreshold") or 0)>=1 or (r.get("nCountiesOverFlood") or 0)>=1]
        for key,label,unit,bins in FOOTPRINT:
            b=distribution(active,key,bins)
            if b: fp[key]={"label":label,"unit":unit,"bins":b}
        decl=[r for r in srows if r["declared"] and r["paTotal"]>0]
        pa=[r["paTotal"] for r in decl]; ih=[r["ihpTotal"] for r in decl if r["ihpTotal"]>0]
        rr=lambda v: round(v) if v is not None else None
        dis_s=[d for d in disasters if d["state"]==s]
        states[s]={"name":STATE_NAME[s],"pop":STATE_POP[s],
            "denominator":{"basis":"Storm Events property damage > 0 (notable episodes)",
                "nAll":len(srows_all),"nNotable":len(srows),
                "declaredAll":sum(r["declared"] for r in srows_all),
                "declaredNotable":sum(r["declared"] for r in srows),
                "floodExcluded":len(flood0),
                "floodCaveat":(f"{len(flood0)} declared flood episodes here have $0 recorded "
                    "Storm Events damage (riverine/agricultural loss isn't in that field) and are "
                    "excluded from these rates — so flood is undercounted by this filter.")},
            "hazardProfile":prof,"distributions":dist,"footprint":fp,
            "costSummary":{"n":len(decl),"paMedian":rr(pct(pa,50)),"paP90":rr(pct(pa,90)),"paMax":rr(max(pa)) if pa else None,
                "ihpMedian":rr(pct(ih,50)),"ihpP90":rr(pct(ih,90)),"ihpMax":rr(max(ih)) if ih else None,
                "source":"declared state-episodes + OpenFEMA (PA obligated / IHP approved)"},
            "nDisasters":len(dis_s),
            "analogs":sorted([analog(d) for d in dis_s],key=lambda a:a["date"],reverse=True),
            "counties":county_flood_reference(s,gages,county_panel)}
    nd=sum(r["declared"] for r in state_panel)
    notable=[r for r in state_panel if is_notable(r)]; ndn=sum(r["declared"] for r in notable)
    return {"generated":dt.date.today().isoformat()[:7],"build":"panel",
        "kind":"information","note":"Empirical frequencies from the regenerated state-episode panel. "
            "Rates are computed over NOTABLE episodes (Storm Events property damage > 0). "
            "No probabilities, no fitted model. PA is obligated, IHP approved.",
        "provenance":{
            "unit":"state-storm episode — each NOAA Storm Events episode's counties aggregated to the state level",
            "hazardMembership":"an episode counts toward a hazard if it carried that hazard's signal "
                "(flood: a county over flood stage or a Flood/Winter incident; tornado: ≥1 tornado; "
                "wind: gust ≥50 mph; hail: ≥0.75 in; winter: snowfall present)",
            "declaredRule":"declared = at least one designated county of the episode falls inside a FEMA "
                "disaster window (OpenFEMA); the bar gets cleared at the STATE level, not per county",
            "denominator":"NOTABLE episodes only — Storm Events property damage > 0; this strips the many "
                "trivial $0 NWS reports that flatten the curve",
            "metric":"each driver value is the PEAK across the episode's counties (peak envelope)",
            "caveat":"Storm Events damage under-records riverine/agricultural flood loss, so the damage>0 "
                "denominator excludes some real flood declarations (counted per state as floodExcluded)",
            "source":"scripts/build_context.py over data/state_panel.json (NOAA Storm Events + OpenFEMA)"},
        "panel":{"episodes":len(state_panel),"declared":nd,
                 "baseRate":round(nd/max(1,len(state_panel)),3),
                 "notableEpisodes":len(notable),"notableDeclared":ndn,
                 "notableBaseRate":round(ndn/max(1,len(notable)),3),
                 "source":"scripts/build_state_panel.py"},
        "states":states}

# ---- event_nexus.json : per-disaster driver values placed in history ----
EVENT_DRIVERS=[  # (panel field, label, unit, hazard) in display order
 ("maxFtAboveFlood","river crest above flood stage","ft","flood"),
 ("rainEventARIyr","rainfall rarity (Atlas-14)","yr","flood"),
 ("maxRainDayMaxIn","peak 1-day rainfall","in","flood"),
 ("maxSweMeltIn","snowmelt water released (est.)","in","flood"),
 ("maxSnowfallEventIn","storm-total snowfall","in","winter"),
 ("maxSweAntecedentIn","antecedent snowpack water (est.)","in","winter"),
 ("maxEF","peak EF rating","EF","tornado"),
 ("totTornadoes","tornado count","","tornado"),
 ("maxGustMph","peak wind gust","mph","wind"),
 ("maxHailIn","max hail size","in","hail"),
]
def primary_hazard(d):
    tags=set(d.get("tags") or []); it=d.get("incidentType","")
    if "Snow-Ice" in tags or "Snowstorm" in it or "Ice Storm" in it: return "winter"
    if "Flooding" in tags or "Flood" in it: return "flood"
    if "Tornado" in tags: return "tornado"
    if "Hail" in tags: return "hail"
    return "wind"

def build_event_nexus(state_panel,disasters):
    by_dn=collections.defaultdict(list)
    for r in state_panel:
        if r.get("dn"): by_dn[r["dn"]].append(r)
    by_state=collections.defaultdict(list)
    for r in state_panel: by_state[r["state"]].append(r)
    out={}
    for d in disasters:
        dn=d["disasterNumber"]; s=d["state"]
        mine=by_dn.get(dn,[]); srows=by_state[s]
        hz=d.get("hz") or {}
        def event_val(key):
            vals=[r.get(key) for r in mine if r.get(key) is not None]
            if vals: return max(vals)
            return None
        drivers=[]
        for key,label,unit,hz_fam in EVENT_DRIVERS:
            v=event_val(key)
            # fall back to disasters.json hz for a few where panel may be sparse
            if v in (None,0):
                fb={"maxRainDayMaxIn":hz.get("rainDailyMaxIn"),"maxFtAboveFlood":hz.get("peakStageFt"),
                    "maxGustMph":hz.get("windMph"),"maxHailIn":hz.get("hailIn"),
                    "maxEF":hz.get("torEF"),"totTornadoes":hz.get("tornadoes"),
                    "maxSnowfallEventIn":hz.get("snowfallIn"),"maxSweAntecedentIn":hz.get("sweIn")}.get(key)
                if fb in (None,0): continue
                v=fb
            member=HAZARD_MEMBER[hz_fam]
            ctx=at_least([r for r in srows if member(r) and is_notable(r)], key, v)
            drivers.append({"key":key,"label":label,"unit":unit,"hazard":hz_fam,
                "value":round(v,2),"atLeast":ctx})
        out[str(dn)]={"state":s,"stateName":STATE_NAME.get(s,s),"title":d.get("title"),
            "incidentType":d.get("incidentType"),"begin":d["begin"],"tags":d.get("tags",[]),
            "primaryHazard":primary_hazard(d),
            "footprint":{"countyCount":d.get("countyCount"),
                "popExposed":max([r.get("sumPopExposed") for r in mine] or [None]) if mine else None,
                "damageProxy":d.get("reportedDamage")},
            "drivers":drivers,
            "cost":{"pa":(d.get("costs") or {}).get("paTotal",0),"ihp":(d.get("costs") or {}).get("ihpTotal",0)}}
    return out

def main():
    for need in ("state_panel.json","county_panel.json"):
        if not os.path.exists(os.path.join(DATA,need)):
            print(f"{need} not found — run build_state_panel.py first."); return
    state_panel=load("state_panel.json"); county_panel=load("county_panel.json")
    disasters=load("disasters.json"); gages=load("gages.json")
    ctx=build_context(state_panel,county_panel,disasters,gages)
    nex=build_event_nexus(state_panel,disasters)
    for name,obj in [("context.json",ctx),("event_nexus.json",nex)]:
        p=os.path.join(DATA,name); json.dump(obj,open(p,"w"),separators=(",",":"))
        print(f"  wrote data/{name} ({os.path.getsize(p)//1024} KB)")

if __name__=="__main__":
    main()
