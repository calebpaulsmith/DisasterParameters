#!/usr/bin/env python3
"""
Add the RIVER-STAGE layer to data/county_panel.json by joining data/gages.json
onto county-episodes and pulling USGS observed stage for the episode window.

For every panel row whose `fips` matches a gage's `countyFips`, we pull that
gage's stage (gage height) over the episode window from USGS Water Services and
add, per row:

  ftAboveFlood   - peak stage minus the gage's NWS flood stage (feet ABOVE flood;
                   negative => stayed below flood stage). If a county has several
                   gages we keep the MAX ftAboveFlood (the worst gage).
  stageCat       - flood category at the peak from the gage's `cats`
                   (action/minor/moderate/major), else null if cats absent / below action.
  hoursAboveFlood- approximate hours the gage was at/above flood stage during the
                   window. From instantaneous (IV) data this is counted directly;
                   from daily-mean (DV) data it is days-above x 24 (coarse) -- see flag.
  stageDailyMean - True when only USGS daily-mean values were available (so
                   ftAboveFlood/hoursAboveFlood are daily-derived and conservative);
                   False when instantaneous values were used.
  stageGage      - the USGS site id that produced the kept (max) reading (traceability).

SOURCE / METHOD (matches CLAUDE.md conventions)
  - Stage parameter is parameterCd=00065 (gage height, ft). We PREFER instantaneous
    values (USGS IV service) for sub-daily peaks and dwell-time; if IV returns
    nothing for the window we fall back to daily mean (DV, statCd=00003) and set
    stageDailyMean=True.
  - Readings > 75 ft are DROPPED (those are reservoir/lake-elevation gauges, not
    river stage) -- same guard the project uses elsewhere.
  - Episodes are matched by county; we run for any episode that touches a gaged
    county (flood episodes are the obvious target, but a high river can matter for
    non-flood-tagged episodes too, so we don't gate on r["flood"]).

ADDITIVE / IDEMPOTENT
  - Loads data/county_panel.json, stamps fields in place for matched rows, writes
    back compact. Rows in counties with no gage are left untouched. Never touches
    costs / disasters.json. Re-running overwrites only these stage fields.

Run from repo root (after build_panel.py):  python3 scripts/augment_stage.py
Network-only (USGS waterservices, CORS/public); needs data/gages.json.
"""
import os, json, time, datetime as dt, urllib.request, urllib.parse, collections
HERE=os.path.dirname(os.path.abspath(__file__)); ROOT=os.path.dirname(HERE); DATA=os.path.join(ROOT,"data")
MAX_STAGE_FT=75.0   # above this => reservoir/lake elevation gauge, not river stage
IV_URL="https://waterservices.usgs.gov/nwis/iv/"
DV_URL="https://waterservices.usgs.gov/nwis/dv/"

def usgs(url, params, retries=4):
    q=urllib.parse.urlencode(params)
    for _ in range(retries):
        try:
            req=urllib.request.Request(f"{url}?{q}",
                headers={"User-Agent":"DisasterParameters/stage (public open data)"})
            with urllib.request.urlopen(req,timeout=120) as r: return json.load(r)
        except Exception: time.sleep(2)
    return None

def parse_ts(doc):
    """USGS WaterML-JSON -> list of (datetime_str, value_float), stage only, <=75 ft."""
    out=[]
    try:
        for ts in doc["value"]["timeSeries"]:
            for blk in ts.get("values",[]):
                for v in blk.get("value",[]):
                    try: f=float(v["value"])
                    except: continue
                    if f<=-999999: continue          # USGS no-data sentinel
                    if f>MAX_STAGE_FT: continue       # reservoir/lake gauge guard
                    out.append((v.get("dateTime",""), f))
    except Exception:
        return []
    return out

def pull_stage(site, sdate, edate):
    """Return (readings, daily_mean_flag). readings = list of (time, ft). Prefers IV."""
    iv=usgs(IV_URL, {"format":"json","sites":site,"parameterCd":"00065",
                     "startDT":sdate,"endDT":edate})
    pts=parse_ts(iv) if iv else []
    if pts: return pts, False
    dv=usgs(DV_URL, {"format":"json","sites":site,"parameterCd":"00065",
                     "statCd":"00003","startDT":sdate,"endDT":edate})
    pts=parse_ts(dv) if dv else []
    return pts, True

def category(peak, cats):
    """Highest NWS flood category at/below peak stage; None if below action or no cats."""
    if not cats: return None
    order=[("major","major"),("moderate","moderate"),("minor","minor"),("action","action")]
    hit=None
    for key,name in order:
        th=cats.get(key)
        if th is not None and peak>=th: return name
    return hit

def hours_above(readings, flood_stage, daily_mean):
    """Approx hours at/above flood stage. IV: count distinct hours touched; DV:
    days-above x 24 (coarse). Returns int hours."""
    if flood_stage is None: return 0
    above=[(t,v) for (t,v) in readings if v>=flood_stage]
    if not above: return 0
    if daily_mean:
        return len(above)*24
    # IV: approximate by number of distinct calendar hours with an above reading.
    hrs=set()
    for t,_ in above:
        # dateTime like 2019-03-15T13:30:00.000-05:00 ; take 'YYYY-MM-DDTHH'
        hrs.add(t[:13])
    return len(hrs)

def main():
    panel=os.path.join(DATA,"county_panel.json")
    rows=json.load(open(panel))
    gages=json.load(open(os.path.join(DATA,"gages.json")))

    # county FIPS -> list of gages
    by_county=collections.defaultdict(list)
    for g in gages:
        cf=g.get("countyFips")
        if cf: by_county[cf].append(g)

    # group rows needing a lookup by (gage_site, window) to reuse pulls within a county
    targets=[r for r in rows if r["fips"] in by_county]
    print(f"{len(targets)} rows fall in {len(by_county)} gaged counties; pulling USGS stage…")

    done=0
    for r in targets:
        b=dt.date.fromisoformat(r["begin"]); e=dt.date.fromisoformat(r["end"])
        if (e-b).days>30: e=b+dt.timedelta(days=30)
        sd=b.isoformat(); ed=(e+dt.timedelta(days=1)).isoformat()
        best=None  # (ftAbove, cat, hours, daily_flag, site)
        for g in by_county[r["fips"]]:
            site=g.get("id"); fs=g.get("floodStage")
            if not site: continue
            readings,daily=pull_stage(site, sd, ed); time.sleep(0.3)
            if not readings: continue
            peak=max(v for _,v in readings)
            ftabove=round(peak-fs,2) if fs is not None else None
            cat=category(peak, g.get("cats"))
            hrs=hours_above(readings, fs, daily)
            cand=(ftabove if ftabove is not None else -9999, cat, hrs, daily, site, ftabove)
            if best is None or cand[0]>best[0]: best=cand
        if best is not None:
            r["ftAboveFlood"]=best[5]      # may be None if gage had no floodStage
            r["stageCat"]=best[1]
            r["hoursAboveFlood"]=best[2]
            r["stageDailyMean"]=best[3]
            r["stageGage"]=best[4]
        done+=1
        if done%50==0: print(f"  …{done}/{len(targets)} rows")

    json.dump(rows,open(panel,"w"),separators=(",",":"))
    stamped=sum(1 for r in rows if "ftAboveFlood" in r)
    print(f"stamped stage onto {stamped} rows -> data/county_panel.json")

if __name__=="__main__":
    main()
