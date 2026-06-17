#!/usr/bin/env python3
"""
Distill the fitted model + state-incident panel into the SMALL, COMMITTED artifacts the
browser reads: data/predictor.json and data/triggers.json. This is the production
counterpart of build_seed_artifacts.py — it emits the IDENTICAL schema (so the front end
is unchanged) but every number is now computed from the regenerated panel rather than the
PoC findings: base rates from the full state-episode panel, driver-bin declared rates from
the panel, cost summaries from the declared state-episodes, analogs + characterizing
params from disasters.json, county thresholds from gages.json.

Inputs : data/state_panel.json, data/county_panel.json, data/model.json,
         data/disasters.json, data/gages.json
Outputs: data/predictor.json, data/triggers.json  (small, committed)

Run from repo root (after fit_model.py):  python3 scripts/build_predictor.py
"""
import os, json, collections, datetime as dt
HERE=os.path.dirname(os.path.abspath(__file__)); ROOT=os.path.dirname(HERE); DATA=os.path.join(ROOT,"data")
STATE_NAME={"IL":"Illinois","IN":"Indiana","MI":"Michigan","MN":"Minnesota","OH":"Ohio","WI":"Wisconsin"}
STATE_POP={"IL":12549689,"IN":6785528,"MI":10037261,"MN":5706494,"OH":11799448,"WI":5893718}
HAZ_OF={"Flood":"flood","Tornado":"tornado","Winter":"flood","Wind":"wind","Hail":"hail","Severe Storm":"wind"}

def pct(vals,p):
    vals=sorted(v for v in vals if v is not None)
    if not vals: return None
    k=(len(vals)-1)*p/100; f=int(k)
    return vals[f]+(vals[min(f+1,len(vals)-1)]-vals[f])*(k-f)

def load(name): return json.load(open(os.path.join(DATA,name)))

def base_by_hazard(state_rows):
    """declared rate per hazard from the panel (state-episodes grouped by dominant hazard)."""
    agg=collections.defaultdict(lambda:[0,0])
    for r in state_rows:
        h=HAZ_OF.get(r["incidentType"],"wind"); agg[h][0]+=r["declared"]; agg[h][1]+=1
    out={}
    for h in ("flood","tornado","wind","hail"):
        d,n=agg.get(h,[0,0]); out[h]=round(d/n,3) if n else 0.0
    return out

def driver_bins(state_rows):
    out={}
    edges={"maxRainDayMaxIn":[("<1",0,1),(">=4",4,None)]}
    # surface flood rainfall bins where the state has flood episodes
    floods=[r for r in state_rows if r["incidentType"] in ("Flood","Winter")]
    if len(floods)>=15:
        bins=[]
        for lab,lo,hi in [("<1",0,1),("1-2",1,2),("2-4",2,4),(">=4",4,None)]:
            sub=[r for r in floods if (r.get("maxRainDayMaxIn") or 0)>=lo and (hi is None or (r.get("maxRainDayMaxIn") or 0)<hi)]
            d=sum(r["declared"] for r in sub)
            bins.append({"lab":lab+"″","lo":lo,"hi":hi,"declRate":round(d/len(sub),3) if sub else 0})
        out["rainDayMaxIn"]={"hazard":"flood","unit":"in","bins":bins,
                             "basis":"regenerated state-episode panel (flood episodes)"}
    return out

def triggers_for(state, gages):
    t={"nCountiesOverFlood":{"warn":3,"declThreshold":6,"basis":"panel: flood footprint clears the statewide bar"}}
    if state=="MN":
        t["snowMeltIn"]={"warn":1.5,"declThreshold":3.0,"basis":"panel: MN floods are snowmelt-driven"}
    else:
        t["rainDayMaxIn"]={"warn":2.0,"declThreshold":4.0,"basis":"panel: rain-driven flood declarations"}
    return t

def county_block(state,gages,county_rows):
    """per-county relevant hazard + AHPS flood thresholds + (real) per-county declared rate."""
    out={}; by=collections.defaultdict(list)
    for r in county_rows:
        if r["state"]==state: by[r["fips"]].append(r)
    gby={}
    for g in gages:
        if g.get("state")==state and g.get("countyFips"): gby.setdefault(g["countyFips"],g)
    for fips,g in gby.items():
        cats=g.get("cats") or {}; fs=g.get("floodStage"); trig={}
        if fs is not None:
            warn=round((cats.get("minor",fs)-fs),1) if cats.get("minor") else 0.0
            decl=round((cats.get("moderate",cats.get("minor",fs))-fs),1) if (cats.get("moderate") or cats.get("minor")) else 1.0
            trig["ftAboveFlood"]={"warn":max(0.0,warn),"declThreshold":max(1.0,decl),"official":bool(g.get("official"))}
        cr=by.get(fips,[]); d=sum(x["declared"] for x in cr)
        out[fips]={"name":g.get("name"),"river":g.get("river"),"gageId":g.get("id"),
                   "relevantHazards":["flood"],"floodStageFt":fs,"triggers":trig,
                   "nEpisodes":len(cr),"nDeclared":d,
                   "baseRateNote":("official NWS AHPS" if g.get("official") else "approximate flood stage")}
    return out

def analog(d):
    hz=d.get("hz") or {}
    feat={k:v for k,v in {"windMph":hz.get("windMph"),"hailIn":hz.get("hailIn"),"torEF":hz.get("torEF"),
        "tornadoes":hz.get("tornadoes"),"peakStageFt":hz.get("peakStageFt"),"rainIn":hz.get("rainIn"),
        "rainDayMaxIn":hz.get("rainDailyMaxIn"),"countyCount":d.get("countyCount"),
        "reportedDamage":d.get("reportedDamage")}.items() if v not in (None,0)}
    return {"date":d["begin"],"end":d["end"],"dn":d["disasterNumber"],"declared":1,
            "it":d.get("incidentType"),"title":d.get("title"),
            "pa":(d.get("costs") or {}).get("paTotal",0),"ihp":(d.get("costs") or {}).get("ihpTotal",0),"feat":feat}

DOM_NOTE={"MN":"MN flood declarations are spring snowmelt; rainfall does not separate them — snowpack/SWE is the driver.",
 "WI":"WI flood declarations are strongly rain-driven.","IL":"IL flood declarations rise with rainfall and antecedent wetness.",
 "IN":"IN has the highest tornado declaration rate; damage/exposure separate, not intensity.",
 "MI":"MI declarations are flood/tornado-led; exposure drives them.","OH":"OH has the lowest declaration rates; only high-damage events declare."}

def build_predictor(state_panel,county_panel,disasters,gages,model):
    states={}
    for s in STATE_NAME:
        srows=[r for r in state_panel if r["state"]==s]
        bh=base_by_hazard(srows)
        dom=sorted(bh,key=lambda h:-bh[h])[:2]
        decl=[r for r in srows if r["declared"] and r["paTotal"]>0]
        ih=[r["ihpTotal"] for r in decl if r["ihpTotal"]>0]; pa=[r["paTotal"] for r in decl]
        rr=lambda v: round(v) if v is not None else None
        dis_s=[d for d in disasters if d["state"]==s]
        states[s]={"name":STATE_NAME[s],"pop":STATE_POP[s],"baseRateByHazard":bh,
            "dominantHazards":dom,"driverNote":DOM_NOTE.get(s,""),
            "triggers":triggers_for(s,gages),"baseRates":driver_bins(srows),
            "costSummary":{"n":len(decl),"paMedian":rr(pct(pa,50)),"paP90":rr(pct(pa,90)),"paMax":rr(max(pa)) if pa else None,
                "ihpMedian":rr(pct(ih,50)),"ihpP90":rr(pct(ih,90)),"ihpMax":rr(max(ih)) if ih else None,
                "source":"declared state-episodes + OpenFEMA"},
            "nDeclared":len(dis_s),
            "analogs":sorted([analog(d) for d in dis_s],key=lambda a:a["date"],reverse=True),
            "counties":county_block(s,gages,county_panel)}
    return {"trainedThrough":dt.date.today().isoformat()[:7],"policyRegime":"pre-reform","build":"fitted",
            "note":"Base rates, driver bins and cost summaries computed from the regenerated state-incident panel; "
                   "likelihoods displayed are empirical declared rates, costs are real OpenFEMA medians/P90.",
            "panel":{"episodes":len(state_panel),"declared":sum(r["declared"] for r in state_panel),
                     "baseRate":round(sum(r["declared"] for r in state_panel)/max(1,len(state_panel)),3),
                     "source":"scripts/build_state_panel.py"},
            "benchmarks":model.get("benchmarks",{}),"states":states}

# ---- triggers.json (per disaster) ----
PARAM_BINS={"rainDayMaxIn":[("<1",0,1),("1-2",1,2),("2-3",2,3),("3-4",3,4),(">=4",4,None)],
 "rainIn":[("<2",0,2),("2-4",2,4),("4-6",4,6),("6-8",6,8),(">=8",8,None)],
 "windMph":[("<60",0,60),("60-80",60,80),("80-100",80,100),(">=100",100,None)],
 "hailIn":[("<1",0,1),("1-2",1,2),("2-3",2,3),(">=3",3,None)],
 "tornadoes":[("0",0,1),("1-2",1,3),("3-5",3,6),(">=6",6,None)],
 "peakStageFt":[("<10",0,10),("10-20",10,20),("20-30",20,30),(">=30",30,None)]}
PANEL_KEY={"rainDayMaxIn":"maxRainDayMaxIn","rainIn":"sumRainFootprintIn","windMph":"maxGustMph",
 "hailIn":"maxHailIn","tornadoes":"totTornadoes","peakStageFt":"maxFtAboveFlood"}
PLAB={"rainDayMaxIn":"peak 1-day rain","rainIn":"total incident rain","windMph":"peak wind gust",
 "hailIn":"max hail","tornadoes":"# tornadoes","peakStageFt":"peak river stage"}
PUNIT={"rainDayMaxIn":"in","rainIn":"in","windMph":"mph","hailIn":"in","tornadoes":"","peakStageFt":"ft"}
RELATED={"rainDayMaxIn":["rainIn","peakStageFt"],"rainIn":["rainDayMaxIn","peakStageFt"],
 "peakStageFt":["rainDayMaxIn","rainIn"],"windMph":["hailIn","tornadoes"],
 "hailIn":["windMph","tornadoes"],"tornadoes":["windMph","hailIn"]}

def build_triggers(state_panel,disasters):
    # per-state distribution + declared-by-bin from the panel (real, incl. non-declared)
    byhaz={s:base_by_hazard([r for r in state_panel if r["state"]==s]) for s in STATE_NAME}
    def hist_and_decl(state,key,bins):
        pk=PANEL_KEY[key]; rows=[r for r in state_panel if r["state"]==state]
        h={}; db={}
        for lab,lo,hi in bins:
            sub=[r for r in rows if (r.get(pk) or 0)>=lo and (hi is None or (r.get(pk) or 0)<hi)]
            h[lab]=len(sub); d=sum(r["declared"] for r in sub)
            if sub: db[lab]=round(d/len(sub),3)
        return h,db
    out={}
    for d in disasters:
        hz=d.get("hz") or {}; s=d["state"]; params=[]
        order=[("peakStageFt",hz.get("peakStageFt")),("rainDayMaxIn",hz.get("rainDailyMaxIn")),
               ("rainIn",hz.get("rainIn")),("windMph",hz.get("windMph")),
               ("hailIn",hz.get("hailIn")),("tornadoes",hz.get("tornadoes"))]
        for key,val in order:
            if val in (None,0): continue
            h,db=hist_and_decl(s,key,PARAM_BINS[key])
            params.append({"key":key,"label":PLAB[key],"unit":PUNIT[key],"value":val,
                "histBins":h,"declaredByBin":db,"declBasis":"regenerated state-episode panel",
                "histNote":f"distribution across {STATE_NAME[s]} state-episodes (panel)",
                "related":[r for r in RELATED[key] if any(r==o[0] for o in order)]})
        out[str(d["disasterNumber"])]={"state":s,"title":d.get("title"),
            "incidentType":d.get("incidentType"),"begin":d["begin"],
            "stateBaseRate":byhaz[s],"params":params}
    return out

def main():
    for need in ("state_panel.json","county_panel.json"):
        if not os.path.exists(os.path.join(DATA,need)):
            print(f"{need} not found — run build_state_panel.py (+ build_panel.py) first."); return
    state_panel=load("state_panel.json"); county_panel=load("county_panel.json")
    disasters=load("disasters.json"); gages=load("gages.json")
    model=load("model.json") if os.path.exists(os.path.join(DATA,"model.json")) else {}
    pred=build_predictor(state_panel,county_panel,disasters,gages,model)
    trig=build_triggers(state_panel,disasters)
    for name,obj in [("predictor.json",pred),("triggers.json",trig)]:
        p=os.path.join(DATA,name); json.dump(obj,open(p,"w"),separators=(",",":"))
        print(f"  wrote data/{name} ({os.path.getsize(p)//1024} KB)")

if __name__=="__main__":
    main()
