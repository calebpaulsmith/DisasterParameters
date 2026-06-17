#!/usr/bin/env python3
"""
Add the PRECIPITATION layer to data/county_panel.json (the county x storm-episode
panel from build_panel.py). For each county-episode it computes, from gridded
PRISM daily precip (RCC-ACIS GridData, county-reduced):

  rainDayMaxIn  - peak single-day rainfall during the episode window (county_max)
  rainEventIn   - event-total areal rainfall over the window (county_mean sum)
  rainAnte7In   - areal rainfall in the 7 days BEFORE the episode (antecedent wetness)
  rainAnte14In  - areal rainfall in the 14 days before the episode

Strategy: pull each state's full daily county precip series once per year
(area_reduce=county_mean & county_max), ~108 calls total, and slice per episode
offline. Then re-run the declared-vs-not analysis WITH rainfall — the metric that
Storm Events can't supply for floods.

Run from repo root (after build_panel.py):  python3 scripts/build_precip.py
"""
import os, json, time, datetime as dt, urllib.request, collections, statistics as st
HERE=os.path.dirname(os.path.abspath(__file__)); ROOT=os.path.dirname(HERE); DATA=os.path.join(ROOT,"data")
STATES=["IL","IN","MI","MN","OH","WI"]

def acis_grid(state, sdate, edate, retries=4):
    body=json.dumps({"state":state,"sdate":sdate,"edate":edate,"grid":"21",
        "elems":[{"name":"pcpn","interval":"dly","area_reduce":"county_mean"},
                 {"name":"pcpn","interval":"dly","area_reduce":"county_max"}]}).encode()
    for _ in range(retries):
        try:
            req=urllib.request.Request("https://data.rcc-acis.org/GridData",data=body,
                headers={"Content-Type":"application/json"})
            with urllib.request.urlopen(req,timeout=120) as r: return json.load(r)
        except Exception: time.sleep(2)
    return None

def num(v):
    try:
        f=float(v); return f if f>=0 else 0.0
    except: return 0.0

def build_series(state, year):
    """county -> {date: (mean,max)} for [year-1 Dec 11 .. year Dec 31] (antecedent margin)."""
    out=collections.defaultdict(dict)
    sd=f"{year-1}-12-11"; ed=f"{year}-12-31"
    d=acis_grid(state, sd, ed)
    if not d: return out
    for rec in d.get("data",[]):
        date=rec[0]; cm=rec[1] if len(rec)>1 else {}; cx=rec[2] if len(rec)>2 else {}
        for fips,v in (cm.items() if isinstance(cm,dict) else []):
            out[fips][date]=[num(v), num((cx or {}).get(fips))]
    return out

def main():
    panel=os.path.join(DATA,"county_panel.json")
    rows=json.load(open(panel))
    by=collections.defaultdict(list)
    for r in rows: by[(r["state"], int(r["begin"][:4]))].append(r)
    total=len(by); done=0
    for (state,year),group in sorted(by.items()):
        ser=build_series(state,year); time.sleep(0.4); done+=1
        for r in group:
            fips=r["fips"]; s=ser.get(fips,{})
            b=dt.date.fromisoformat(r["begin"]); e=dt.date.fromisoformat(r["end"])
            if (e-b).days>30: e=b+dt.timedelta(days=30)
            win=[b+dt.timedelta(days=i) for i in range((e-b).days+1)]
            ante=[b-dt.timedelta(days=i) for i in range(1,15)]
            def mean_sum(days): return round(sum(s.get(d.isoformat(),[0,0])[0] for d in days),2)
            def max_day(days):
                vals=[s.get(d.isoformat(),[0,0])[1] for d in days]; return round(max(vals),2) if vals else 0.0
            r["rainDayMaxIn"]=max_day(win)
            r["rainEventIn"]=mean_sum(win)
            r["rainAnte7In"]=mean_sum(ante[:7])
            r["rainAnte14In"]=mean_sum(ante)
        print(f"  [{done}/{total}] {state} {year}: {len(group)} episodes  (sample rainDayMax="
              f"{max((g.get('rainDayMaxIn',0) for g in group),default=0)}\")")
    json.dump(rows,open(panel,"w"),separators=(",",":"))
    print(f"wrote precip onto {len(rows)} rows -> data/county_panel.json")
    analyze(rows)

def pct(vals,p):
    vals=[v for v in vals if v is not None]
    if not vals: return None
    vals=sorted(vals); k=(len(vals)-1)*p/100; f=int(k)
    return round(vals[f]+(vals[min(f+1,len(vals)-1)]-vals[f])*(k-f),2)

def desc(rows,state,fn,title,metrics):
    sub=[r for r in rows if r["state"]==state and fn(r) and "rainEventIn" in r]
    dec=[r for r in sub if r["declared"]]; nd=[r for r in sub if not r["declared"]]
    print(f"\n=== {state}: {title} — declared vs not (with rainfall) ===")
    print(f"  episodes {len(sub)} (declared {len(dec)} / non {len(nd)})")
    print(f"  {'metric':<20}{'declared p50/p90':>20}{'non-decl p50/p90':>20}")
    for m,lab in metrics:
        print(f"  {lab:<20}{f'{pct([r.get(m) for r in dec],50)} / {pct([r.get(m) for r in dec],90)}':>20}"
              f"{f'{pct([r.get(m) for r in nd],50)} / {pct([r.get(m) for r in nd],90)}':>20}")

def analyze(rows):
    M=[("rainDayMaxIn","peak 1-day in"),("rainEventIn","event total in"),
       ("rainAnte14In","14-day antecedent"),("dmg","$ property dmg")]
    desc(rows,"MN",lambda r:r["flood"],"flood episodes",M)
    desc(rows,"IL",lambda r:r["flood"],"flood / flash-flood episodes",M)
    desc(rows,"WI",lambda r:r["flood"],"flood episodes",M)
    # declared rate by peak-rain band for flood episodes (does rain separate?)
    for state in ("MN","IL"):
        sub=[r for r in rows if r["state"]==state and r["flood"] and "rainDayMaxIn" in r]
        print(f"\n=== {state} flood: declared rate by peak 1-day rainfall ===")
        for lab,fn in [("<1\"",lambda v:v<1),("1-2\"",lambda v:1<=v<2),("2-3\"",lambda v:2<=v<3),
                       ("3-4\"",lambda v:3<=v<4),(">=4\"",lambda v:v>=4)]:
            b=[r for r in sub if fn(r["rainDayMaxIn"])]; d=sum(r["declared"] for r in b)
            if b: print(f"  {lab:<7} {100*d/len(b):>5.0f}% declared  ({d}/{len(b)})")

if __name__=="__main__":
    main()
