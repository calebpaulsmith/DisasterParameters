#!/usr/bin/env python3
"""
Add the SNOWPACK layer to data/county_panel.json — the missing driver for the
Minnesota / Red River spring-snowmelt floods that rainfall can't explain.

True SWE (SNODAS) is ~90 GB of daily 1 km grids; instead we use station SNOW
DEPTH (GHCN-Daily SNWD via RCC-ACIS) aggregated to counties as the accessible
SWE proxy. For each county-episode it adds:
  snowDepthPreIn - peak antecedent snow depth (max county-mean in the 10 days
                   before the episode) = "was there a snowpack to melt?"
  snowMeltIn     - largest 1-day drop in county snow depth during the episode
                   window = rapid-melt signal

Strategy mirrors build_precip.py: pull each state's cold-season (Dec–May) daily
station snow depth once per year (~108 calls), aggregate stations -> county mean,
slice per episode offline. Then re-run declared-vs-not on flood episodes.

Run from repo root (after build_panel.py + build_precip.py):
  python3 scripts/build_snow.py
"""
import os, json, time, datetime as dt, urllib.request, collections
HERE=os.path.dirname(os.path.abspath(__file__)); ROOT=os.path.dirname(HERE); DATA=os.path.join(ROOT,"data")
STATES=["IL","IN","MI","MN","OH","WI"]
SNOW_MONTHS={12,1,2,3,4,5}

def acis_snwd(state, sdate, edate, retries=4):
    body=json.dumps({"state":state,"sdate":sdate,"edate":edate,
        "elems":[{"name":"snwd"}],"meta":["county"]}).encode()
    for _ in range(retries):
        try:
            req=urllib.request.Request("https://data.rcc-acis.org/MultiStnData",data=body,
                headers={"Content-Type":"application/json"})
            with urllib.request.urlopen(req,timeout=120) as r: return json.load(r)
        except Exception: time.sleep(2)
    return None

def build_series(state, year):
    """county -> {date: mean_snow_depth_in} for [year-1 Dec 1 .. year May 31]."""
    sd=f"{year-1}-12-01"; ed=f"{year}-05-31"
    d=acis_snwd(state, sd, ed)
    sums=collections.defaultdict(lambda: collections.defaultdict(lambda:[0.0,0]))
    if not d: return {}
    start=dt.date.fromisoformat(sd)
    for stn in d.get("data",[]):
        fips=stn.get("meta",{}).get("county")
        if not fips: continue
        for i,day in enumerate(stn.get("data",[])):
            v=day[0] if isinstance(day,list) else day
            if v in ("M","S",None,""): continue
            if v=="T": v=0
            try: fv=float(v)
            except: continue
            date=(start+dt.timedelta(days=i)).isoformat()
            acc=sums[fips][date]; acc[0]+=fv; acc[1]+=1
    return {f:{d:(a[0]/a[1]) for d,a in days.items()} for f,days in sums.items()}

def main():
    panel=os.path.join(DATA,"county_panel.json")
    rows=json.load(open(panel))
    by=collections.defaultdict(list)
    for r in rows: by[(r["state"], int(r["begin"][:4]))].append(r)
    # default zeros for everything
    for r in rows: r["snowDepthPreIn"]=0.0; r["snowMeltIn"]=0.0
    todo=[(s,y) for (s,y) in by if any(int(r["begin"][5:7]) in SNOW_MONTHS for r in by[(s,y)])]
    done=0
    for (state,year) in sorted(todo):
        ser=build_series(state,year); time.sleep(0.4); done+=1
        for r in by[(state,year)]:
            if int(r["begin"][5:7]) not in SNOW_MONTHS: continue
            s=ser.get(r["fips"],{})
            b=dt.date.fromisoformat(r["begin"]); e=dt.date.fromisoformat(r["end"])
            if (e-b).days>30: e=b+dt.timedelta(days=30)
            pre=[s.get((b-dt.timedelta(days=i)).isoformat()) for i in range(1,11)]
            pre=[x for x in pre if x is not None]
            r["snowDepthPreIn"]=round(max(pre),1) if pre else 0.0
            melt=0.0
            for i in range((e-b).days+4):
                d0=(b-dt.timedelta(days=3)+dt.timedelta(days=i)); d1=d0+dt.timedelta(days=1)
                a=s.get(d0.isoformat()); c=s.get(d1.isoformat())
                if a is not None and c is not None and a-c>melt: melt=a-c
            r["snowMeltIn"]=round(melt,1)
        print(f"  [{done}/{len(todo)}] {state} {year}: peak antecedent snow "
              f"{max((r['snowDepthPreIn'] for r in by[(state,year)]),default=0)}\"")
    json.dump(rows,open(panel,"w"),separators=(",",":"))
    print(f"wrote snow onto {len(rows)} rows")
    analyze(rows)

def pct(vals,p):
    vals=[v for v in vals if v is not None]
    if not vals: return None
    vals=sorted(vals); k=(len(vals)-1)*p/100; f=int(k)
    return round(vals[f]+(vals[min(f+1,len(vals)-1)]-vals[f])*(k-f),1)

def analyze(rows):
    def desc(state,fn,title):
        sub=[r for r in rows if r["state"]==state and fn(r)]
        dec=[r for r in sub if r["declared"]]; nd=[r for r in sub if not r["declared"]]
        print(f"\n=== {state}: {title} — declared vs not ===")
        print(f"  episodes {len(sub)} (declared {len(dec)} / non {len(nd)})")
        for m,lab in [("snowDepthPreIn","antecedent snow in"),("snowMeltIn","1-day melt in"),
                      ("rainDayMaxIn","peak 1-day rain"),("rainEventIn","event rain"),("dmg","$ dmg")]:
            print(f"  {lab:<20}{f'{pct([r.get(m) for r in dec],50)} / {pct([r.get(m) for r in dec],90)}':>18}"
                  f"{f'{pct([r.get(m) for r in nd],50)} / {pct([r.get(m) for r in nd],90)}':>18}")
    spring=lambda r: r["flood"] and int(r["begin"][5:7]) in {3,4,5}
    desc("MN",spring,"SPRING flood episodes (Mar–May)")
    desc("WI",spring,"SPRING flood episodes (Mar–May)")
    # declared rate by antecedent snow depth for MN spring floods
    sub=[r for r in rows if r["state"]=="MN" and spring(r)]
    print("\n=== MN spring flood: declared rate by antecedent snow depth ===")
    for lab,fn in [('0"',lambda v:v==0),('0-3"',lambda v:0<v<3),('3-6"',lambda v:3<=v<6),
                   ('6-12"',lambda v:6<=v<12),('>=12"',lambda v:v>=12)]:
        b=[r for r in sub if fn(r["snowDepthPreIn"])]; d=sum(r["declared"] for r in b)
        if b: print(f"  {lab:<7} {100*d/len(b):>5.0f}% declared  ({d}/{len(b)})")

if __name__=="__main__":
    main()
