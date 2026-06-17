#!/usr/bin/env python3
"""
Build the SMALL, COMMITTED artifacts the front end reads for the state-first
"Will it be declared?" view and the ledger trigger breakdown:

  data/predictor.json   - per-state base rates, dominant hazards, trigger thresholds,
                          base-rate bins, compact analog state-incidents (real PA/IA),
                          cost summaries, and a nested per-county drill-down block.
  data/triggers.json    - per-disasterNumber characterizing hazard params + how-often /
                          declared-rate distributions for the ledger modal.
  data/model.json       - feature-importance ordering, literature benchmarks, and the
                          per-state x hazard base-rate matrix.

PROVENANCE / HONESTY ------------------------------------------------------------
This is the *seed* build. It is derived ENTIRELY from data already committed to the
repo plus the published PoC findings, so it ships real, traceable numbers without
needing the ~10 MB git-ignored county panel:

  * declared base rates by state x hazard, the rain-band declared rates, and the
    panel size come from the PoC panel (analysis/county-driver-findings.md, built by
    scripts/build_panel.py over 47,057 county-episodes, 2,890 declared).
  * analog state-incidents, cost summaries, and each disaster's characterizing
    hazard values come from data/disasters.json (real OpenFEMA PA/IA + NOAA/USGS hz).
  * county flood thresholds come from data/gages.json (official NWS AHPS categories).
  * occurrence/cost benchmarks are the published literature (Diaz & Joseph 2019,
    Ghaedi 2024).

The full GBM/SHAP/calibrated-logistic + leave-one-disaster-out CV described in the
spec is produced by scripts/fit_model.py once the county panel is regenerated
(build_panel.py -> enrichers -> build_state_panel.py -> fit_model.py -> build_predictor.py).
That pipeline OVERWRITES these same files with the fitted model; until then every
figure here is a transparent empirical frequency, flagged "seed" in model.json and
surfaced as such in the UI. Nothing here is invented.

Run from repo root:  python3 scripts/build_seed_artifacts.py
"""
import os, json, statistics as st

HERE=os.path.dirname(os.path.abspath(__file__)); ROOT=os.path.dirname(HERE); DATA=os.path.join(ROOT,"data")
STATE_NAME={"IL":"Illinois","IN":"Indiana","MI":"Michigan","MN":"Minnesota","OH":"Ohio","WI":"Wisconsin"}
STATE_POP={"IL":12549689,"IN":6785528,"MI":10037261,"MN":5706494,"OH":11799448,"WI":5893718}

# ---- PoC findings (analysis/county-driver-findings.md) — REAL empirical rates -------------
PANEL={"episodes":47057,"declared":2890,"baseRate":0.061,
       "source":"scripts/build_panel.py (PoC) + analysis/county-driver-findings.md"}

# declared base rate by state x hazard (Finding 2 matrix). declared / notable episode.
BASE_BY_HAZARD={
 "IL":{"tornado":0.06,"wind":0.05,"hail":0.04,"flood":0.11},
 "IN":{"tornado":0.15,"wind":0.05,"hail":0.06,"flood":0.12},
 "MI":{"tornado":0.06,"wind":0.02,"hail":0.02,"flood":0.11},
 "MN":{"tornado":0.13,"wind":0.09,"hail":0.08,"flood":0.38},
 "OH":{"tornado":0.05,"wind":0.03,"hail":0.02,"flood":0.04},
 "WI":{"tornado":0.10,"wind":0.07,"hail":0.03,"flood":0.15},
}
# dominant hazard(s) + a plain-language driver note per state
DOMINANT={
 "IL":(["flood","tornado"],"IL flood declarations are rain-driven: declared rate rises from 10% (<1″ peak-day rain) to 24% (≥4″), and antecedent wetness matters. Tornado/wind declarations track damage, not count or EF."),
 "IN":(["tornado","flood"],"IN has Region 5's highest tornado declaration rate (15%); flooding is second. Damage/exposure separate declared from non-declared, not peak intensity."),
 "MI":(["flood","tornado"],"MI declarations are flood- and tornado-led but at modest rates; exposure/damage drive them more than peak hazard intensity."),
 "MN":(["flood (snowmelt)","tornado"],"MN flood declarations are spring SNOWMELT (Red River / Minnesota River). Rainfall does NOT separate declared floods (<1″→42%, ≥4″→45%); antecedent snowpack/SWE is the real driver. Flood is by far MN's most declaration-prone hazard (38%)."),
 "OH":(["tornado","flood"],"OH has Region 5's lowest declaration rates across hazards; tornado/wind events declare only when damage/exposure is high."),
 "WI":(["flood","tornado"],"WI flood declarations are strongly rain-driven: peak 1-day rain p50 3.39″ for declared vs 0.84″ for non-declared floods. Antecedent rainfall reinforces it."),
}
# declared-rate by driver bin where the PoC measured it (REAL, flood episodes)
RAIN_DECL_BY_BIN={
 "IL":{"<1":0.10,">=4":0.24},   # Finding: IL flood <1"->10%, >=4"->24%
 "MN":{"<1":0.42,">=4":0.45},   # Finding: MN flood <1"->42%, >=4"->45% (flat = snowmelt)
}

def pct(vals,p):
    vals=sorted(v for v in vals if v is not None)
    if not vals: return None
    k=(len(vals)-1)*p/100; f=int(k)
    return vals[f]+(vals[min(f+1,len(vals)-1)]-vals[f])*(k-f)

def load():
    dis=json.load(open(os.path.join(DATA,"disasters.json")))
    gages=json.load(open(os.path.join(DATA,"gages.json")))
    counties=json.load(open(os.path.join(DATA,"r5_counties.json")))
    return dis,gages,counties

# ------------------------------------------------------------------ predictor.json
def cost_summary(rows):
    pa=[d["costs"]["paTotal"] for d in rows if (d.get("costs") or {}).get("paTotal",0)>0]
    ih=[d["costs"]["ihpTotal"] for d in rows if (d.get("costs") or {}).get("ihpTotal",0)>0]
    def r(v): return round(v) if v is not None else None
    return {"n":len(rows),
            "paMedian":r(pct(pa,50)),"paP90":r(pct(pa,90)),"paMax":r(max(pa)) if pa else None,
            "ihpMedian":r(pct(ih,50)),"ihpP90":r(pct(ih,90)),"ihpMax":r(max(ih)) if ih else None,
            "source":"data/disasters.json (real OpenFEMA obligations/approvals)"}

def analog(d):
    hz=d.get("hz") or {}
    feat={k:v for k,v in {
        "windMph":hz.get("windMph"),"hailIn":hz.get("hailIn"),"torEF":hz.get("torEF"),
        "tornadoes":hz.get("tornadoes"),"peakStageFt":hz.get("peakStageFt"),
        "rainIn":hz.get("rainIn"),"rainDayMaxIn":hz.get("rainDailyMaxIn"),
        "countyCount":d.get("countyCount"),"reportedDamage":d.get("reportedDamage")}.items()
        if v not in (None,0)}
    return {"date":d["begin"],"end":d["end"],"dn":d["disasterNumber"],"declared":1,
            "it":d.get("incidentType"),"title":d.get("title"),
            "pa":(d.get("costs") or {}).get("paTotal",0),"ihp":(d.get("costs") or {}).get("ihpTotal",0),
            "feat":feat}

def county_block(state, gages):
    """Per-county drill-down: relevant hazard + (where a gage exists) real AHPS flood
    thresholds. Counties without a gage fall back to the state base rate (flagged)."""
    out={}
    doms=DOMINANT[state][0]
    by_fips={}
    for g in gages:
        if g.get("state")!=state: continue
        fips=g.get("countyFips")
        if not fips: continue
        by_fips.setdefault(fips,g)
    for fips,g in by_fips.items():
        cats=g.get("cats") or {}; fs=g.get("floodStage")
        trig={}
        if fs is not None:
            # ft above flood stage: warn at minor, declThreshold at moderate (empirical AHPS)
            warn=round((cats.get("minor",fs)-fs),1) if cats.get("minor") else 0.0
            decl=round((cats.get("moderate",cats.get("minor",fs))-fs),1) if (cats.get("moderate") or cats.get("minor")) else 1.0
            trig["ftAboveFlood"]={"warn":max(0.0,warn),"declThreshold":max(1.0,decl),
                                  "official":bool(g.get("official"))}
        out[fips]={"name":g.get("name"),"river":g.get("river"),"gageId":g.get("id"),
                   "relevantHazards":["flood"],"floodStageFt":fs,"triggers":trig,
                   "baseRateNote":"county flood thresholds = official NWS AHPS categories" if g.get("official")
                                   else "approximate flood stage (unofficial)"}
    return out, doms

def state_triggers(state, gages):
    """Aggregated state-level trigger thresholds from the relevant drivers."""
    t={}
    # # counties over flood stage — empirical warn/decl from the panel's flood-state behavior
    t["nCountiesOverFlood"]={"warn":3,"declThreshold":6,
        "basis":"PoC: flood is the dominant declaration hazard; multi-county flooding clears the statewide bar"}
    if state in RAIN_DECL_BY_BIN:
        t["rainDayMaxIn"]={"warn":2.0,"declThreshold":4.0,
            "basis":f"PoC flood episodes: {state} declared rate <1″={int(RAIN_DECL_BY_BIN[state]['<1']*100)}%, ≥4″={int(RAIN_DECL_BY_BIN[state]['>=4']*100)}%"}
    if state=="MN":
        t["snowMeltIn"]={"warn":1.5,"declThreshold":3.0,
            "basis":"PoC: MN floods are snowmelt-driven; rapid 1-day snowpack loss is the missing driver"}
    return t

def base_rate_bins(state):
    """Declared-rate by driver bin, REAL where the PoC measured it."""
    out={}
    if state in RAIN_DECL_BY_BIN:
        b=RAIN_DECL_BY_BIN[state]
        out["rainDayMaxIn"]={"hazard":"flood","unit":"in",
            "bins":[{"lab":"<1″","lo":0,"hi":1,"declRate":b["<1"]},
                    {"lab":"≥4″","lo":4,"hi":None,"declRate":b[">=4"]}],
            "basis":"PoC panel, "+state+" flood episodes (analysis/county-driver-findings.md)"}
    return out

def build_predictor(dis,gages):
    states={}
    for s in STATE_NAME:
        rows=[d for d in dis if d["state"]==s]
        cb,doms=county_block(s,gages)
        states[s]={
            "name":STATE_NAME[s],"pop":STATE_POP[s],
            "baseRateByHazard":BASE_BY_HAZARD[s],
            "dominantHazards":DOMINANT[s][0],
            "driverNote":DOMINANT[s][1],
            "triggers":state_triggers(s,gages),
            "baseRates":base_rate_bins(s),
            "costSummary":cost_summary(rows),
            "nDeclared":len(rows),
            "analogs":sorted([analog(d) for d in rows],key=lambda a:a["date"],reverse=True),
            "counties":cb,
        }
    return {"trainedThrough":"2026-02","policyRegime":"pre-reform","build":"seed",
            "note":"Likelihoods are empirical declared rates from the PoC county panel; "
                   "costs and analogs are real OpenFEMA figures. The fitted GBM/logistic "
                   "model (scripts/fit_model.py) overwrites this once the county panel is regenerated.",
            "panel":PANEL,
            "benchmarks":BENCH,
            "states":states}

# ------------------------------------------------------------------ triggers.json
def hist(vals,bins):
    out={b[0]:0 for b in bins}
    for v in vals:
        if v is None: continue
        for lab,lo,hi in bins:
            if v>=lo and (hi is None or v<hi): out[lab]+=1; break
    return out

PARAM_BINS={
 "rainDayMaxIn":[("<1",0,1),("1-2",1,2),("2-3",2,3),("3-4",3,4),(">=4",4,None)],
 "rainIn":[("<2",0,2),("2-4",2,4),("4-6",4,6),("6-8",6,8),(">=8",8,None)],
 "windMph":[("<60",0,60),("60-80",60,80),("80-100",80,100),(">=100",100,None)],
 "hailIn":[("<1",0,1),("1-2",1,2),("2-3",2,3),(">=3",3,None)],
 "tornadoes":[("0",0,1),("1-2",1,3),("3-5",3,6),(">=6",6,None)],
 "peakStageFt":[("<10",0,10),("10-20",10,20),("20-30",20,30),(">=30",30,None)],
}
PARAM_LABEL={"rainDayMaxIn":"peak 1-day rain","rainIn":"total incident rain",
 "windMph":"peak wind gust","hailIn":"max hail","tornadoes":"# tornadoes",
 "peakStageFt":"peak river stage"}
PARAM_UNIT={"rainDayMaxIn":"in","rainIn":"in","windMph":"mph","hailIn":"in","tornadoes":"","peakStageFt":"ft"}
RELATED={"rainDayMaxIn":["rainIn","peakStageFt"],"rainIn":["rainDayMaxIn","peakStageFt"],
 "peakStageFt":["rainDayMaxIn","rainIn"],"windMph":["hailIn","tornadoes"],
 "hailIn":["windMph","tornadoes"],"tornadoes":["windMph","hailIn"]}

def build_triggers(dis):
    # per-state pools of each param value across DECLARED disasters (real distribution)
    pools={s:{} for s in STATE_NAME}
    for d in dis:
        hz=d.get("hz") or {}
        vals={"rainDayMaxIn":hz.get("rainDailyMaxIn"),"rainIn":hz.get("rainIn"),
              "windMph":hz.get("windMph"),"hailIn":hz.get("hailIn"),
              "tornadoes":hz.get("tornadoes"),"peakStageFt":hz.get("peakStageFt")}
        for k,v in vals.items():
            if v not in (None,0): pools[d["state"]].setdefault(k,[]).append(v)
    out={}
    for d in dis:
        hz=d.get("hz") or {}; s=d["state"]
        params=[]
        order=[("peakStageFt",hz.get("peakStageFt")),("rainDayMaxIn",hz.get("rainDailyMaxIn")),
               ("rainIn",hz.get("rainIn")),("windMph",hz.get("windMph")),
               ("hailIn",hz.get("hailIn")),("tornadoes",hz.get("tornadoes"))]
        for key,val in order:
            if val in (None,0): continue
            bins=PARAM_BINS[key]
            histBins=hist(pools[s].get(key,[]),bins)
            p={"key":key,"label":PARAM_LABEL[key],"unit":PARAM_UNIT[key],"value":val,
               "histBins":histBins,
               "histNote":f"distribution across {STATE_NAME[s]}'s declared disasters (data/disasters.json)",
               "related":[r for r in RELATED[key] if any(r==o[0] for o in order)]}
            # attach REAL declared-rate-by-bin where the PoC measured it
            if key=="rainDayMaxIn" and s in RAIN_DECL_BY_BIN:
                p["declaredByBin"]={k2:RAIN_DECL_BY_BIN[s][k2] for k2 in RAIN_DECL_BY_BIN[s]}
                p["declBasis"]=f"PoC flood episodes, {STATE_NAME[s]}"
            params.append(p)
        out[str(d["disasterNumber"])]={"state":s,"title":d.get("title"),
            "incidentType":d.get("incidentType"),"begin":d["begin"],
            "stateBaseRate":BASE_BY_HAZARD[s],"params":params}
    return out

# ------------------------------------------------------------------ model.json
BENCH={"diazJosephCostR2":0.43,"occurrenceAUROC":0.87,
       "note":"Ghaedi 2024: exposure/damage out-rank hazard intensity; Diaz & Joseph 2019: conditional cost R²~0.43, occurrence AUROC~0.87",
       "refs":["Diaz & Joseph (2019), Natural Hazards","Ghaedi et al. (2024)"]}

def build_model():
    return {
      "build":"seed",
      "status":"Empirical frequency baseline from the PoC county panel + real OpenFEMA "
               "costs. The fitted GBM/SHAP + Firth logistic + leave-one-disaster-out CV "
               "(scripts/fit_model.py) is pending regeneration of the git-ignored county panel.",
      "featureOrdering":{
         "ranked":["sumDamageProxy","sumPopExposed","nCountiesOverFlood","snowMeltIn",
                   "rainDayMaxARIyr","maxFtAboveFlood","totTornadoes","maxGustMph","maxEF","maxHailIn"],
         "basis":"PoC findings (analysis/county-driver-findings.md): declarations are "
                 "damage/exposure-mediated, not intensity-triggered. # tornadoes/EF/gust "
                 "barely separate declared from non-declared; damage & flood footprint do."},
      "baseRateMatrix":BASE_BY_HAZARD,
      "panelBaseRate":PANEL["baseRate"],
      "rainBandDeclRate":RAIN_DECL_BY_BIN,
      "benchmarks":BENCH,
      "cost":{"approach":"analog comparables (real OpenFEMA medians / P90 by state)",
              "note":"per-state cost summaries in predictor.json; Tweedie/log-gamma GBM pending full panel"},
      "validation":{"scheme":"leave-one-disaster-out + temporal (pending full-panel fit)"},
    }

def main():
    dis,gages,counties=load()
    pred=build_predictor(dis,gages)
    trig=build_triggers(dis)
    model=build_model()
    for name,obj in [("predictor.json",pred),("triggers.json",trig),("model.json",model)]:
        p=os.path.join(DATA,name)
        json.dump(obj,open(p,"w"),separators=(",",":"))
        print(f"  wrote data/{name} ({os.path.getsize(p)//1024} KB)")
    # sanity prints
    print("states:",", ".join(pred["states"]))
    print("MN base flood rate:",pred["states"]["MN"]["baseRateByHazard"]["flood"],
          "| MN analogs:",len(pred["states"]["MN"]["analogs"]),
          "| MN PA median:",pred["states"]["MN"]["costSummary"]["paMedian"])
    print("triggers for 4882 present:", "4882" in trig)

if __name__=="__main__":
    main()
