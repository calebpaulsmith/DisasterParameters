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
import os, json, collections, datetime as dt, statistics
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
 "winter":"In Region 5 a snow/ice storm rarely triggers a federal declaration on its own — the consequent spring SNOWMELT FLOODING usually does (see the Flooding chart). Snowfall/snowpack severity is deferred to the follow-up data pass, so winter shows little here by design.",
}
HAZARD_LABEL={"flood":"Flooding","tornado":"Tornado","wind":"Wind","hail":"Hail","winter":"Winter storm"}

# ── DECLARED-vs-NON SEPARATION ────────────────────────────────────────────────
# Every empirical metric we can compute per state-storm episode, with display bins.
# Ranked at runtime by how well each SEPARATES declared from non-declared episodes
# (AUC). decl_any (any federal declaration) is the label — this view is purely
# "what distinguishes an episode that got declared from one that didn't".
SEPARATORS=[
 ("nCountiesOverThreshold","counties with a notable hazard","",
    [("1",1,2),("2–3",2,4),("4–7",4,8),("8–15",8,16),("≥16",16,None)],
    "how many counties in the storm system cleared a real hazard bar (over flood stage, or a damaging wind/hail/tornado)"),
 ("nCountiesOverFlood","counties above flood stage","",
    [("0",0,1),("1",1,2),("2–3",2,4),("4–7",4,8),("≥8",8,None)],
    "counties where a gaged river reached NWS flood stage during the episode"),
 ("sumRainFootprintIn","rainfall footprint (rain × area)","in",
    [("<0.5",0,0.5),("0.5–2",0.5,2),("2–5",2,5),("5–10",5,10),("≥10",10,None)],
    "episode rainfall summed across affected counties — depth and breadth together"),
 ("maxRainDayMaxIn","peak 1-day rainfall","in",
    [("<1",0,1),("1–2",1,2),("2–4",2,4),("4–6",4,6),("≥6",6,None)],
    "heaviest single-day rainfall at any county in the system"),
 ("sumDamageProxy","Storm Events property damage","$",
    [("$0",0,1),("<$100k",1,100000),("$100k–1M",100000,1000000),("$1M–10M",1000000,10000000),("≥$10M",10000000,None)],
    "NOAA Storm Events property-damage estimate, summed over the system (under-records flood)"),
 ("nCounties","counties in the storm system","",
    [("1",1,2),("2–4",2,5),("5–9",5,10),("10–19",10,20),("≥20",20,None)],
    "raw size of the storm system in counties"),
 ("sumPopExposed","population in affected counties","",
    [("<50k",0,50000),("50k–250k",50000,250000),("250k–1M",250000,1000000),("1M–3M",1000000,3000000),("≥3M",3000000,None)],
    "people living in the affected counties (Census)"),
 ("rainEventARIyr","rainfall rarity (Atlas-14)","yr",
    [("<2",0,2),("2–10",2,10),("10–25",10,25),("25–50",25,50),("≥50",50,None)],
    "how rare the event rainfall is against the county's own climatology (recurrence interval)"),
 ("maxFtAboveFlood","river crest above flood stage","ft",
    [("below",-99,0),("0–2",0,2),("2–5",2,5),("5–10",5,10),("≥10",10,None)],
    "USGS observed crest minus NWS flood stage (gaged counties only — sparse)"),
 ("maxEF","peak tornado EF","EF",
    [("none",-1,0),("EF0",0,1),("EF1",1,2),("EF2+",2,None)],
    "strongest tornado in the system (intensity, not extent)"),
 ("maxGustMph","peak wind gust","mph",
    [("<50",0,50),("50–65",50,65),("65–80",65,80),("≥80",80,None)],
    "strongest measured wind gust (intensity, not extent)"),
 ("maxHailIn","max hail size","in",
    [("<0.75",0,0.75),("0.75–1.5",0.75,1.5),("1.5–2.5",1.5,2.5),("≥2.5",2.5,None)],
    "largest hailstone (intensity, not extent)"),
]
# features fed to the combined (logistic) separator; log-scaled ones are heavy-tailed.
COMBO_FEATURES=["nCountiesOverThreshold","nCountiesOverFlood","sumRainFootprintIn",
    "maxRainDayMaxIn","sumDamageProxy","sumPopExposed","rainEventARIyr","nCounties"]
COMBO_LOG={"sumRainFootprintIn","sumDamageProxy","sumPopExposed","rainEventARIyr"}

def pct(vals,p):
    vals=sorted(v for v in vals if v is not None)
    if not vals: return None
    k=(len(vals)-1)*p/100; f=int(k)
    return vals[f]+(vals[min(f+1,len(vals)-1)]-vals[f])*(k-f)

def load(name): return json.load(open(os.path.join(DATA,name)))

def distribution(rows, key, bins, decl_fn):
    """bins with explicit total (n), declared count, and the declared disasters' DR
    numbers (dns) for drill-down. decl_fn(r) decides what counts as a declaration in
    THIS context — for a hazard's chart it's 'declared AND that hazard was a tagged
    cause', so e.g. a tornado riding a flood declaration doesn't inflate the flood rate."""
    out=[]; any_data=False
    for lab,lo,hi in bins:
        sub=[r for r in rows if (r.get(key) is not None) and r[key]>=lo and (hi is None or r[key]<hi)]
        decl=[r for r in sub if decl_fn(r)]
        dns=sorted({r["dn"] for r in decl if r.get("dn")})
        if sub: any_data=True
        out.append({"lab":lab,"lo":lo,"hi":hi,"n":len(sub),"declared":len(decl),"dns":dns})
    return out if any_data else None

def at_least(rows, key, value, decl_fn):
    """events with driver >= value: total + declared (the 'compare to past events/non-events' line)."""
    sub=[r for r in rows if (r.get(key) is not None) and r[key]>=value]
    d=sum(1 for r in sub if decl_fn(r))
    return {"n":len(sub),"declared":d}

def decl_any(r): return bool(r.get("declared"))

def auc(rows,key):
    """Rank AUC = P(a random DECLARED episode scores higher than a random non-declared
    one) on this metric. 0.5 = no separation; →1 = perfect separator. Ties count 0.5."""
    import bisect
    D=sorted((r.get(key) or 0) for r in rows if r.get("declared"))
    N=sorted((r.get(key) or 0) for r in rows if not r.get("declared"))
    if not D or not N: return None
    tot=0.0
    for v in D:
        lo=bisect.bisect_left(N,v); hi=bisect.bisect_right(N,v); tot+=lo+0.5*(hi-lo)
    return round(tot/(len(D)*len(N)),3)

def combined_auc(rows):
    """Best linear separation across COMBO_FEATURES via a small logistic fit. Returns
    (auc, [(feature, standardized-weight)…] sorted by |weight|). In-sample — this is a
    separability read, not a forecast."""
    import math,bisect
    def fv(r):
        return [math.log1p(r.get(k) or 0) if k in COMBO_LOG else (r.get(k) or 0) for k in COMBO_FEATURES]
    X=[fv(r) for r in rows]; y=[1 if r.get("declared") else 0 for r in rows]
    if sum(y)<20: return None,[]
    cols=list(zip(*X))
    ms=[(sum(c)/len(c), (statistics.pstdev(c) or 1)) for c in cols]
    X=[[(v-ms[i][0])/ms[i][1] for i,v in enumerate(row)] for row in X]
    w=[0.0]*len(COMBO_FEATURES); b=0.0; lr=0.3; n=len(X)
    for _ in range(300):
        gw=[0.0]*len(w); gb=0.0
        for xi,yi in zip(X,y):
            z=b+sum(w[j]*xi[j] for j in range(len(w)))
            z=max(-30,min(30,z)); p=1/(1+math.exp(-z)); e=p-yi
            for j in range(len(w)): gw[j]+=e*xi[j]
            gb+=e
        for j in range(len(w)): w[j]-=lr*gw[j]/n
        b-=lr*gb/n
    def scr(xi): return b+sum(w[j]*xi[j] for j in range(len(w)))
    D=sorted(scr(x) for x,t in zip(X,y) if t); N=sorted(scr(x) for x,t in zip(X,y) if not t)
    tot=0.0
    for v in D:
        lo=bisect.bisect_left(N,v); hi=bisect.bisect_right(N,v); tot+=lo+0.5*(hi-lo)
    wl=sorted(zip(COMBO_FEATURES,w),key=lambda t:-abs(t[1]))
    return round(tot/(len(D)*len(N)),3),[(k,round(v,3)) for k,v in wl]

def build_separation(rows,name,pop):
    """The whole deliverable: every empirical metric ranked by how well it separates
    declared from non-declared episodes, with the two distributions (bins) for each."""
    nd=sum(1 for r in rows if r.get("declared"))
    seps=[]
    for key,label,unit,bins,basis in SEPARATORS:
        vals=[r.get(key) for r in rows if r.get(key) is not None]
        if not vals or min(vals)==max(vals): continue   # unpopulated / no variation (e.g. sparse stage) → omit, don't imply "no separation"
        a=auc(rows,key)
        if a is None: continue
        b=distribution(rows,key,bins,decl_any)
        if not b: continue
        dv=[(r.get(key) or 0) for r in rows if r.get("declared")]
        nv=[(r.get(key) or 0) for r in rows if not r.get("declared")]
        seps.append({"key":key,"label":label,"unit":unit,"basis":basis,"auc":a,
                     "medN":round(pct(nv,50) or 0,2),"medD":round(pct(dv,50) or 0,2),
                     "p90N":round(pct(nv,90) or 0,2),"p90D":round(pct(dv,90) or 0,2),
                     "bins":b})
    seps.sort(key=lambda s:-s["auc"])
    cauc,weights=combined_auc(rows)
    return {"name":name,"pop":pop,"nEpisodes":len(rows),"nDeclared":nd,
            "baseRate":round(nd/max(1,len(rows)),3),"combinedAUC":cauc,
            "weights":weights,"separators":seps}

def hazard_profile(srows_all, decl_for):
    prof=[]
    for h in HAZARD_MEMBER:
        mem=gated_members(h,srows_all); df=decl_for(h); d=sum(1 for r in mem if df(r))
        if mem: prof.append({"hazard":h,"label":HAZARD_LABEL[h],"nEpisodes":len(mem),
                             "nDeclared":d,"declaredRate":round(d/len(mem),3),"gate":hazard_gate(h)})
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
    """NOTABLE = NOAA Storm Events property damage > 0."""
    return (r.get("sumDamageProxy") or 0)>0

# The damage>0 gate strips trivial $0 NWS reports that flatten the curve — but Storm Events
# RECORDS wind/tornado damage well and UNDER-records riverine/agricultural FLOOD loss (a
# declared flood often logs $0; the real loss is FEMA PA on public infrastructure). So we
# apply the gate ONLY to wind & tornado; flood, hail and winter use every member episode.
NOTABLE_HAZARDS={"wind","tornado"}
def hazard_gate(h):
    return "damage>0" if h in NOTABLE_HAZARDS else "all episodes"
def gated_members(h, srows_all):
    mem=[r for r in srows_all if HAZARD_MEMBER[h](r)]
    if h in NOTABLE_HAZARDS: mem=[r for r in mem if is_notable(r)]
    return mem

# ATTRIBUTION: a hazard's declared rate counts a declaration only when that hazard was a
# tagged CAUSE of the disaster (the thing that "pushed it over", or one of them) — not just
# any declaration the episode happened to fall inside. Disaster tags come from disasters.json.
HAZARD_TAGS={"flood":{"Flooding","Dam-Levee"},"tornado":{"Tornado"},
 "wind":{"Wind"},"hail":{"Hail"},"winter":{"Snow-Ice"}}
def make_decl_for(dn2tags):
    def decl_for(h):
        tags=HAZARD_TAGS.get(h,set())
        return lambda r: bool(r.get("declared")) and bool(dn2tags.get(r.get("dn"),set()) & tags)
    return decl_for

def build_context(state_panel,county_panel,disasters,gages):
    rr=lambda v: round(v) if v is not None else None
    states={}
    for s in STATE_NAME:
        srows_all=[r for r in state_panel if r["state"]==s]
        decl=[r for r in srows_all if r["declared"] and r["paTotal"]>0]
        pa=[r["paTotal"] for r in decl]; ih=[r["ihpTotal"] for r in decl if r["ihpTotal"]>0]
        dis_s=[d for d in disasters if d["state"]==s]
        states[s]={"name":STATE_NAME[s],"pop":STATE_POP[s],
            "separation":build_separation(srows_all, STATE_NAME[s], STATE_POP[s]),
            "costSummary":{"n":len(decl),"paMedian":rr(pct(pa,50)),"paP90":rr(pct(pa,90)),"paMax":rr(max(pa)) if pa else None,
                "ihpMedian":rr(pct(ih,50)),"ihpP90":rr(pct(ih,90)),"ihpMax":rr(max(ih)) if ih else None,
                "source":"declared state-episodes + OpenFEMA (PA obligated / IHP approved)"},
            "nDisasters":len(dis_s),
            "analogs":sorted([analog(d) for d in dis_s],key=lambda a:a["date"],reverse=True),
            "counties":county_flood_reference(s,gages,county_panel)}
    region=build_separation(state_panel,"All Region 5",sum(STATE_POP.values()))
    nd=sum(r["declared"] for r in state_panel)
    return {"generated":dt.date.today().isoformat()[:7],"build":"separation",
        "kind":"information",
        "note":"What separates an episode that got a federal declaration from one that didn't — every "
            "empirical metric, ranked by separation power (AUC). No forecast. PA is obligated, IHP approved.",
        "insight":"EXTENT separates, peak intensity barely does: how many counties cross a hazard bar is "
            "the strongest single signal (AUC ~0.70), while peak EF / gust / hail sit near a coin-flip "
            "(~0.55). Two notes from the fit: rainfall RARITY (Atlas-14) separates worse than raw rain "
            "extent, and — holding extent fixed — RURAL counties cross the line more easily than metros "
            "(the per-capita threshold). Declarations are only moderately predictable from weather alone; "
            "assessment and cost-share politics carry the rest.",
        "provenance":{
            "unit":"state-storm episode — each NOAA Storm Events episode's counties aggregated to the state level",
            "declaredRule":"declared = at least one designated county of the episode fell inside a FEMA "
                "disaster (OpenFEMA, state level). ANY declaration counts — this view is declared-vs-not, "
                "not per-hazard attribution",
            "metric":"AUC = chance a random declared episode scores higher than a random non-declared one "
                "on that metric (0.5 = no separation, 1.0 = perfect). 'combined' is a small in-sample "
                "logistic fit across the extent/severity metrics — a separability read, not a forecast",
            "envelope":"each metric is the peak/sum across the episode's counties (peak envelope or footprint sum)",
            "caveat":"Storm Events under-records flood damage; river-stage and snow metrics are sparse "
                "(gaged/cold-season only). ARI via NOAA Atlas-14; exposure via Census (population only — "
                "no housing key in this environment)",
            "source":"scripts/build_context.py over data/state_panel.json (NOAA Storm Events + OpenFEMA + USGS + Atlas-14 + Census)"},
        "panel":{"episodes":len(state_panel),"declared":nd,
                 "baseRate":round(nd/max(1,len(state_panel)),3),
                 "source":"scripts/build_state_panel.py"},
        "region":region,
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
    dn2tags={d["disasterNumber"]:set(d.get("tags") or []) for d in disasters}
    decl_for=make_decl_for(dn2tags)
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
            ctx=at_least(gated_members(hz_fam, srows), key, v, decl_for(hz_fam))
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
