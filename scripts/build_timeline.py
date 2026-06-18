#!/usr/bin/env python3
"""
Build data/timeline.json — ONE combined monthly timeline for the whole region that
overlays the hazard signals against the federal declarations, so you can see what was
happening when each disaster hit. Per calendar month (FY2007→present):

  rain    - peak 1-day rainfall anywhere in Region 5    (in)   county_panel.rainDayMaxIn
  river   - peak river crest above flood stage          (ft)   _stage_cache.json − gage flood stage
  tornado - tornado reports across the region           (#)    county_panel.tor
  snow    - peak storm snowfall / melt                  (in)   county_panel snow fields (when enriched)
  + disasters: every declaration that began that month (dn, state, type, title, PA, IHP) for markers

Series carry their own max for normalization; the UI overlays them on one chart with the
real values in tooltips. Reads committed/intermediate JSON only — no network.
"""
import os, json, collections, datetime as dt
DATA=os.path.join(os.path.dirname(__file__),"..","data")
def load(n): return json.load(open(os.path.join(DATA,n)))

def main():
    panel=load("county_panel.json")
    disasters=load("disasters.json")
    gages={g["id"]:g for g in load("gages.json") if g.get("id")}
    stage=load("_stage_cache.json") if os.path.exists(os.path.join(DATA,"_stage_cache.json")) else {}

    rain=collections.defaultdict(float); torn=collections.defaultdict(int)
    snow=collections.defaultdict(float); snow_any=False
    for r in panel:
        m=(r.get("begin") or "")[:7]
        if len(m)!=7: continue
        rd=r.get("rainDayMaxIn") or 0
        if rd: rain[m]=max(rain[m],rd)
        torn[m]+=int(r.get("tor") or 0)
        sv=r.get("snowDepthPreIn") or 0   # peak antecedent snowpack depth (intuitive "snow on the ground")
        if sv: snow[m]=max(snow[m],sv); snow_any=True

    # river: peak (daily stage − flood stage) across gages, by month
    river=collections.defaultdict(lambda:-1e9)
    for site,hist in stage.items():
        fs=gages.get(site,{}).get("floodStage")
        if fs is None: continue
        for d,v in hist.items():
            m=d[:7]; over=v-fs
            if over>river[m]: river[m]=over
    river={m:round(v,2) for m,v in river.items() if v>-1e8}

    # disasters by month
    dmonth=collections.defaultdict(list)
    for d in disasters:
        m=(d.get("begin") or "")[:7]
        if len(m)!=7: continue
        c=d.get("costs") or {}
        dmonth[m].append({"dn":d["disasterNumber"],"state":d.get("state"),"it":d.get("incidentType"),
                          "title":d.get("title"),"tags":d.get("tags",[]),
                          "pa":c.get("paTotal",0),"ihp":c.get("ihpTotal",0)})

    # continuous month axis from first to last
    allm=set(rain)|set(torn)|set(river)|set(dmonth)|set(snow)
    if not allm: allm={dt.date.today().isoformat()[:7]}
    lo=min(allm); hi=max(allm)
    months=[]; y,mo=int(lo[:4]),int(lo[5:7])
    while True:
        months.append(f"{y:04d}-{mo:02d}")
        if f"{y:04d}-{mo:02d}"==hi: break
        mo+=1
        if mo>12: mo=1;y+=1
        if y>2100: break

    series={"rain":[round(rain.get(m,0),2) for m in months],
            "river":[river.get(m,None) for m in months],
            "tornado":[torn.get(m,0) for m in months]}
    if snow_any: series["snow"]=[round(snow.get(m,0),2) for m in months]
    rv=[v for v in series["river"] if v is not None]
    out={"generated":dt.date.today().isoformat()[:7],
         "source":"NOAA Storm Events (rain/tornado) + USGS daily stage − NWS flood stage (river) + OpenFEMA (disasters)",
         "months":months,"series":series,
         "max":{"rain":round(max(series["rain"] or [0]),2),
                "river":round(max(rv) if rv else 0,2),
                "tornado":max(series["tornado"] or [0]),
                "snow":round(max(series.get("snow") or [0]),2)},
         "snowPending":not snow_any,"nGagesRiver":len([s for s in stage if stage[s]]),
         "disasters":{m:dmonth[m] for m in dmonth}}
    p=os.path.join(DATA,"timeline.json")
    json.dump(out,open(p,"w"),separators=(",",":"))
    nd=sum(len(v) for v in dmonth.values())
    print(f"wrote {p}: {len(months)} months · rain max {out['max']['rain']}in · "
          f"river max {out['max']['river']}ft ({out['nGagesRiver']} gages) · "
          f"{nd} disasters · snow {'pending' if not snow_any else 'present'}")

if __name__=="__main__":
    main()
