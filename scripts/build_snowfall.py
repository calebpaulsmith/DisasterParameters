#!/usr/bin/env python3
"""
Add the SNOWFALL-SEVERITY layer to data/county_panel.json — the winter-STORM
intensity metric that the panel previously lacked (Snow/Ice disasters carried only
NOAA report COUNTS, never an accumulation). For each cold-season county-episode it
computes, from GHCN-Daily snowfall (SNOW, inches) via RCC-ACIS:

  snowfallEventIn  - storm-total snowfall over the episode window (county max over
                     stations of the summed daily snowfall) - how big the storm was.
  snowfallDayMaxIn - peak single-day snowfall in the window (county max) - the
                     intensity of the heaviest day (blizzard / heavy-snow signal).

This is the snow analogue of build_precip.py's rainfall layer. Together with
build_snow.py (antecedent snow DEPTH on the ground + 1-day melt = the snowpack and
its melt) the panel now separates the two distinct winter drivers:
  * snowfall accumulation  -> winter-STORM severity (Snow/Ice declarations)
  * snowpack depth + melt  -> spring-snowmelt FLOOD fuel (MN Red/Minnesota R.)

SOURCE / METHOD
  - GHCN-Daily element SNOW (daily snowfall, inches) served by RCC-ACIS
    MultiStnData with the `county=<5-digit FIPS>` meta filter. Trace ('T') -> 0.0.
  - Reduced to the county as the MAX across stations (peak local accumulation),
    matching the "peak envelope" convention used elsewhere in the dataset.

SEASONALITY
  - Only meaningful Dec-Apr; episodes whose begin month is outside that window are
    stamped 0.0 with no network call (same guard as build_snow.py).

BATCHING (mirrors build_snow.py / build_precip.py)
  - Batch by (state, begin-year); one MultiStnData call per distinct county per
    batch covering the union window.

ADDITIVE / IDEMPOTENT
  - Loads data/county_panel.json, stamps the two fields in place, writes back
    compact. Never touches costs / disasters.json. Safe to re-run.

Run from repo root (after build_panel.py):  python3 scripts/build_snowfall.py
Network-only; needs no local source files beyond data/county_panel.json.
"""
import os, json, time, datetime as dt, urllib.request, collections
HERE=os.path.dirname(os.path.abspath(__file__)); ROOT=os.path.dirname(HERE); DATA=os.path.join(ROOT,"data")

SNOW_MONTHS={12,1,2,3,4}

def acis_multistn(fips, sdate, edate, retries=4):
    """MultiStnData: every GHCN station in `fips` (5-digit) with daily SNOW (inches)."""
    body=json.dumps({
        "county":fips,
        "sdate":sdate,"edate":edate,
        "elems":[{"name":"snow","interval":"dly","units":"inch"}],
        "meta":["sids","name"],
    }).encode()
    for _ in range(retries):
        try:
            req=urllib.request.Request("https://data.rcc-acis.org/MultiStnData",data=body,
                headers={"Content-Type":"application/json"})
            with urllib.request.urlopen(req,timeout=120) as r: return json.load(r)
        except Exception: time.sleep(2)
    return None

def num(v):
    """ACIS daily value -> float inches. 'M'/'S' (missing) -> None; 'T' (trace) -> 0.0."""
    if isinstance(v,list): v=v[0] if v else None
    if v in (None,"","M","S"): return None
    if v=="T": return 0.0
    try:
        f=float(v); return f if f>=0 else None
    except: return None

def build_county_series(fips, sdate, edate):
    """fips -> list of per-station {date: snowfall_inches} dicts for the window."""
    d=acis_multistn(fips, sdate, edate)
    if not d: return []
    start=dt.date.fromisoformat(sdate); out=[]
    for stn in d.get("data",[]):
        series={}
        for i,v in enumerate(stn.get("data",[])):
            sf=num(v)
            if sf is None: continue
            series[(start+dt.timedelta(days=i)).isoformat()]=sf
        if series: out.append(series)
    return out

def event_total_and_peak(stations, days):
    """county (max-over-stations event total, max-over-stations single-day peak)."""
    best_total=0.0; best_day=0.0; seen=False
    iso=[d.isoformat() for d in days]
    for s in stations:
        tot=0.0; has=False
        for d in iso:
            v=s.get(d)
            if v is not None:
                tot+=v; has=True
                if v>best_day: best_day=v
        if has:
            seen=True
            if tot>best_total: best_total=tot
    return (round(best_total,1) if seen else 0.0, round(best_day,1) if seen else 0.0)

def main():
    panel=os.path.join(DATA,"county_panel.json")
    rows=json.load(open(panel))

    cold=[]
    for r in rows:
        if int(r.get("month",0)) in SNOW_MONTHS:
            cold.append(r)
        else:
            r["snowfallEventIn"]=0.0; r["snowfallDayMaxIn"]=0.0

    by=collections.defaultdict(list)
    for r in cold: by[(r["state"], int(r["begin"][:4]))].append(r)
    total=len(by); done=0
    for (state,year),group in sorted(by.items()):
        done+=1
        byco=collections.defaultdict(list)
        for r in group: byco[r["fips"]].append(r)
        nstn=0
        for fips,co_rows in byco.items():
            begins=[dt.date.fromisoformat(r["begin"]) for r in co_rows]
            ends=[dt.date.fromisoformat(r["end"]) for r in co_rows]
            sd=min(begins); ed=max(ends)
            stations=build_county_series(fips, sd.isoformat(), ed.isoformat())
            nstn+=len(stations); time.sleep(0.4)
            for r in co_rows:
                b=dt.date.fromisoformat(r["begin"]); e=dt.date.fromisoformat(r["end"])
                if (e-b).days>30: e=b+dt.timedelta(days=30)
                days=[b+dt.timedelta(days=i) for i in range((e-b).days+1)]
                tot,peak=event_total_and_peak(stations, days)
                r["snowfallEventIn"]=tot; r["snowfallDayMaxIn"]=peak
        print(f"  [{done}/{total}] {state} {year}: {len(group)} cold-season episodes, "
              f"{len(byco)} counties, {nstn} station-series  "
              f"(maxEvent={max((r.get('snowfallEventIn',0) for r in group),default=0)}\")")

    json.dump(rows,open(panel,"w"),separators=(",",":"))
    print(f"wrote snowfall (snowfallEventIn, snowfallDayMaxIn) onto {len(rows)} rows -> data/county_panel.json")

if __name__=="__main__":
    main()
