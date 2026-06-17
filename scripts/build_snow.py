#!/usr/bin/env python3
"""
Add the SNOW layer to data/county_panel.json (the county x storm-episode panel
from build_panel.py). For each county-episode it computes, from GHCN-Daily snow
depth (SNWD, inches) via RCC-ACIS, two winter-hazard signals:

  snowDepthPreIn - peak antecedent snow depth in the ~14 days BEFORE the episode
                   (county max over all stations) - the snowpack available to melt.
  snowMeltIn     - largest single-day DECREASE in snow depth across a window that
                   starts a few days before the episode and runs through it
                   (county max of per-station 1-day drops) - a rapid-melt /
                   snowmelt-flood signal (think the classic late-winter rain-on-snow
                   and warm-up events that drive Upper-Midwest river flooding).

SOURCE / METHOD
  - GHCN-Daily element SNWD (snow depth) served by RCC-ACIS MultiStnData. SNWD is
    reported in inches in the ACIS English/standard unit set. We pull every GHCN
    station in a county (ACIS supports a `county=<5-digit FIPS>` meta filter on
    MultiStnData) for the relevant date window, then reduce to the county:
       * snowDepthPreIn = max station depth over the 14 antecedent days
       * snowMeltIn     = max over stations of the largest single-day drop
                          (depth[d] - depth[d+1]) inside the melt window
  - GHCN SNWD is the *accessible* snowpack proxy. True snow water equivalent (SWE)
    from NOHRSC SNODAS is the physically-correct quantity, but the SNODAS daily
    grid archive is ~90 GB and is intentionally DEFERRED here; depth is a coarse
    but freely-queryable stand-in (1 in SWE ~= 10 in fresh snow, very roughly).

SEASONALITY
  - Snow depth / melt is only meaningful for cold-season episodes. For any episode
    whose begin month is OUTSIDE Dec-Apr we skip the network call entirely and set
    both fields to 0.0. (May-Nov snowpack in Region 5 is effectively zero.)

BATCHING (mirrors build_precip.py)
  - We batch by (state, begin-year) and within a batch issue one MultiStnData call
    per county for the union date window, so the number of calls scales with the
    number of distinct cold-season counties rather than with episodes.

ADDITIVE / IDEMPOTENT
  - Loads data/county_panel.json, stamps the two fields onto each row in place,
    writes the list back compact. Never reads or writes costs, disasters.json, or
    any other field. Safe to re-run (it overwrites only its own two fields).

Run from repo root (after build_panel.py):  python3 scripts/build_snow.py
Network-only; needs no local source files beyond data/county_panel.json.
"""
import os, json, time, datetime as dt, urllib.request, collections
HERE=os.path.dirname(os.path.abspath(__file__)); ROOT=os.path.dirname(HERE); DATA=os.path.join(ROOT,"data")

# Cold-season months for which snow signals are meaningful in Region 5.
SNOW_MONTHS={12,1,2,3,4}
# Days of antecedent margin to look back for snowpack + the melt window lead-in.
PRE_DAYS=14
MELT_LEAD=4   # start the melt window this many days before the episode begin

def acis_multistn(fips, sdate, edate, retries=4):
    """MultiStnData: every GHCN station in `fips` (5-digit) with daily SNWD (inches)."""
    body=json.dumps({
        "county":fips,
        "sdate":sdate,"edate":edate,
        "elems":[{"name":"snwd","interval":"dly","units":"inch"}],
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
    """ACIS daily value -> float inches. 'M' (missing) and 'T' (trace) -> None/0."""
    if v in (None,"","M","S"): return None
    if v=="T": return 0.0
    try:
        f=float(v); return f if f>=0 else None
    except: return None

def build_county_series(fips, sdate, edate):
    """fips -> list of per-station {date: depth_inches} dicts for the window."""
    d=acis_multistn(fips, sdate, edate)
    if not d: return []
    start=dt.date.fromisoformat(sdate)
    out=[]
    for stn in d.get("data",[]):
        vals=stn.get("data",[])
        series={}
        for i,v in enumerate(vals):
            depth=num(v)
            if depth is None: continue
            series[(start+dt.timedelta(days=i)).isoformat()]=depth
        if series: out.append(series)
    return out

def peak_depth(stations, days):
    """county max snow depth over the day list."""
    best=0.0; seen=False
    for s in stations:
        for d in days:
            v=s.get(d.isoformat())
            if v is not None: best=max(best,v); seen=True
    return round(best,1) if seen else 0.0

def max_one_day_drop(stations, days):
    """county max of the largest single-day depth DECREASE within the window."""
    best=0.0
    iso=[d.isoformat() for d in days]
    for s in stations:
        for a,b in zip(iso, iso[1:]):
            va=s.get(a); vb=s.get(b)
            if va is None or vb is None: continue
            drop=va-vb
            if drop>best: best=drop
    return round(best,1)

def main():
    panel=os.path.join(DATA,"county_panel.json")
    rows=json.load(open(panel))

    # Set season default first so out-of-season rows are always stamped.
    cold=[]
    for r in rows:
        if int(r.get("month",0)) in SNOW_MONTHS:
            cold.append(r)
        else:
            r["snowDepthPreIn"]=0.0; r["snowMeltIn"]=0.0

    # Batch cold-season rows by (state, begin-year) like build_precip.py, then one
    # county call per distinct county per batch covering the union window.
    by=collections.defaultdict(list)
    for r in cold: by[(r["state"], int(r["begin"][:4]))].append(r)
    total=len(by); done=0
    for (state,year),group in sorted(by.items()):
        done+=1
        byco=collections.defaultdict(list)
        for r in group: byco[r["fips"]].append(r)
        nstn=0
        for fips,co_rows in byco.items():
            # Union window across this county's cold-season episodes (+ margins).
            begins=[dt.date.fromisoformat(r["begin"]) for r in co_rows]
            ends=[dt.date.fromisoformat(r["end"]) for r in co_rows]
            sd=min(begins)-dt.timedelta(days=PRE_DAYS)
            ed=max(ends)
            stations=build_county_series(fips, sd.isoformat(), ed.isoformat())
            nstn+=len(stations); time.sleep(0.4)
            for r in co_rows:
                b=dt.date.fromisoformat(r["begin"]); e=dt.date.fromisoformat(r["end"])
                if (e-b).days>30: e=b+dt.timedelta(days=30)
                ante=[b-dt.timedelta(days=i) for i in range(1,PRE_DAYS+1)]
                melt_start=b-dt.timedelta(days=MELT_LEAD)
                melt_days=[melt_start+dt.timedelta(days=i)
                           for i in range((e-melt_start).days+1)]
                r["snowDepthPreIn"]=peak_depth(stations, ante)
                r["snowMeltIn"]=max_one_day_drop(stations, melt_days)
        print(f"  [{done}/{total}] {state} {year}: {len(group)} cold-season episodes, "
              f"{len(byco)} counties, {nstn} station-series  "
              f"(maxDepth={max((r.get('snowDepthPreIn',0) for r in group),default=0)}\")")

    json.dump(rows,open(panel,"w"),separators=(",",":"))
    print(f"wrote snow (snowDepthPreIn, snowMeltIn) onto {len(rows)} rows -> data/county_panel.json")

if __name__=="__main__":
    main()
