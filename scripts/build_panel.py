#!/usr/bin/env python3
"""
PoC: build a COUNTY x STORM-EPISODE panel for FEMA Region 5 from the NOAA Storm
Events CSVs, labeled declared / not-declared, to study which measured metrics
separate declared county-events from non-declared ones — by hazard and by state.

Unit of analysis: one row per (county, storm episode). Storm Events natively
carries non-declared events, so the panel has both the positives (county-events
inside a FEMA disaster window) and the negatives (everything else).

Outputs:
  data/county_panel.json   - the panel (compact)
  prints a descriptive declared-vs-not analysis for IL (tornado/wind/hail) and
  MN (flood), plus per-county frequencies.

Run from repo root:  python3 scripts/build_panel.py
Needs the StormEvents_details-*.csv.gz in data/ + data/disasters.json +
data/_disasters_raw.json.
"""
import os, json, gzip, csv, glob, datetime as dt, collections, statistics as st, urllib.request, time
HERE=os.path.dirname(os.path.abspath(__file__)); ROOT=os.path.dirname(HERE); DATA=os.path.join(ROOT,"data")
R5={"17":"IL","18":"IN","26":"MI","27":"MN","39":"OH","55":"WI"}
KT2MPH=1.151
WIND={"Thunderstorm Wind","High Wind","Strong Wind","Marine Thunderstorm Wind","Marine High Wind"}
FLOOD={"Flood","Flash Flood","Coastal Flood","Lakeshore Flood"}
# Z-type (forecast-zone-collected) events that build_panel previously DROPPED. Riverine
# "Flood" and the winter family are reported by ZONE, not county, so they never matched
# the CZ_TYPE=="C" filter — yet they are exactly the flood/snowmelt declarations the model
# needs. We ingest them by expanding each zone to its member counties via the NWS
# zone->county correlation file (baked offline; see load_zone_county).
WINTER={"Winter Storm","Heavy Snow","Blizzard","Ice Storm","Winter Weather","Lake-Effect Snow","Sleet"}
ZONE_EVENTS=FLOOD|WINTER

# NWS public forecast-zone <-> county correlation file (pipe-delimited "bp" file).
# Columns: STATE|ZONE|CWA|NAME|STATE_ZONE|COUNTY|FIPS|TIME_ZONE|FE_AREA|LAT|LON
ZONE_URL="https://www.weather.gov/source/gis/Shapefiles/County/bp05de24.dbx"
def load_zone_county():
    """Return {STATE_ZONE -> [county FIPS5,...]} e.g. 'ILZ001'->['17001',...].
    Cached to data/_zone_county.json (git-ignored). Drop the file in manually if the
    NWS URL rotates (the correlation file is renamed by date)."""
    cache=os.path.join(DATA,"_zone_county.json")
    if os.path.exists(cache):
        return json.load(open(cache))
    txt=None
    for _ in range(4):
        try:
            with urllib.request.urlopen(ZONE_URL,timeout=60) as r: txt=r.read().decode("latin-1"); break
        except Exception: time.sleep(2)
    z2f=collections.defaultdict(list)
    if not txt:
        print("  WARN: could not fetch NWS zone-county file; Z-type events will be skipped.\n"
              f"        Download {ZONE_URL} (or the current bp*.dbx) to data/_zone_county.json as\n"
              "        a {STATE_ZONE:[fips,...]} map, or re-run with network access.")
        return z2f
    for line in txt.splitlines():
        f=line.split("|")
        if len(f)<7: continue
        sz=f[4].strip(); fips=f[6].strip()
        if len(sz)==6 and len(fips)==5 and fips[:2] in R5:
            z2f[sz].append(fips)
    json.dump({k:v for k,v in z2f.items()},open(cache,"w"))
    print(f"  zone->county crosswalk: {len(z2f)} R5 zones cached -> data/_zone_county.json")
    return z2f

def dmg(s):
    if not s: return 0.0
    s=s.strip().upper(); m=1.0
    if s and s[-1] in "KMBT": m={"K":1e3,"M":1e6,"B":1e9,"T":1e12}[s[-1]]; s=s[:-1]
    try: return float(s)*m
    except: return 0.0

def ym_day(ym,day):
    try: return dt.date(int(ym)//100,int(ym)%100,int(day))
    except: return None

def build_panel():
    z2f=load_zone_county()
    agg={}  # (fips5,episode) -> dict
    for fp in sorted(glob.glob(os.path.join(DATA,"StormEvents_details-*.csv.gz"))):
        with gzip.open(fp,"rt",encoding="latin-1") as fh:
            for r in csv.DictReader(fh):
                ct=r.get("CZ_TYPE")
                sf=str(r.get("STATE_FIPS","")).zfill(2)
                if sf not in R5: continue
                et=r.get("EVENT_TYPE","")
                # county-collected (C) rows map 1:1; zone-collected (Z) flood/winter rows
                # expand to every member county via the NWS zone->county crosswalk.
                if ct=="C":
                    fips_list=[sf+str(r.get("CZ_FIPS","")).zfill(3)]; zone=False
                elif ct=="Z" and et in ZONE_EVENTS:
                    sz=R5[sf]+"Z"+str(r.get("CZ_FIPS","")).zfill(3)
                    fips_list=z2f.get(sz,[]); zone=True
                    if not fips_list: continue
                else:
                    continue
                ep=r.get("EPISODE_ID","")
                d=ym_day(r.get("BEGIN_YEARMONTH"),r.get("BEGIN_DAY"))
                dmgv=dmg(r.get("DAMAGE_PROPERTY"))
                mag=r.get("MAGNITUDE")
                try: mag=float(mag) if mag not in (None,"") else None
                except: mag=None
                mt=r.get("MAGNITUDE_TYPE","")
                fscale=r.get("TOR_F_SCALE","") or ""
                # a Z-type record's damage is split evenly across member counties so we
                # don't multiply a single zone's reported loss by its county count.
                dshare=dmgv/len(fips_list) if (zone and fips_list) else dmgv
                for fips5 in fips_list:
                    key=(fips5,ep); o=agg.get(key)
                    if o is None:
                        o=agg[key]=dict(fips=fips5,state=R5[sf],name=r.get("CZ_NAME","").title(),ep=ep,
                                        begin=d,end=d,ets=set(),gust=0.0,sustained=0.0,hail=0.0,tor=0,ef=-1,
                                        flood=False,winter=False,zoneSourced=False,dmg=0.0)
                    if d:
                        if o["begin"] is None or d<o["begin"]: o["begin"]=d
                        if o["end"] is None or d>o["end"]: o["end"]=d
                    o["ets"].add(et)
                    if zone: o["zoneSourced"]=True
                    if et in WINTER: o["winter"]=True
                    o["dmg"]+=dshare
                    if et in WIND and mag:
                        mph=mag*KT2MPH
                        if mt in ("ES","MS"): o["sustained"]=max(o["sustained"],mph)
                        else: o["gust"]=max(o["gust"],mph)   # EG/MG/blank -> treat as gust
                    if et=="Hail" and mag: o["hail"]=max(o["hail"],mag)
                    if et=="Tornado":
                        o["tor"]+=1
                        if fscale.startswith("EF"):
                            try: o["ef"]=max(o["ef"],int(fscale[2:]))
                            except: pass
                    if et in FLOOD: o["flood"]=True
    return agg

def label(agg):
    disasters=json.load(open(os.path.join(DATA,"disasters.json")))
    raw={d["disasterNumber"]:d for d in json.load(open(os.path.join(DATA,"_disasters_raw.json")))}
    by_county=collections.defaultdict(list)
    for d in disasters:
        r=raw.get(d["disasterNumber"]);
        if not r: continue
        sf=r.get("stateFips","")
        b=dt.date.fromisoformat(d["begin"]); e=dt.date.fromisoformat(d["end"])
        for c in (r.get("counties") or {}):
            by_county[sf+c].append((b,e,d["disasterNumber"],d["pa"]+d["ihp"]))
    rows=[]
    for (fips,ep),o in agg.items():
        if o["begin"] is None: continue
        decl=None
        for (b,e,dn,cost) in by_county.get(fips,[]):
            if o["begin"]<=e+dt.timedelta(days=10) and o["end"]>=b-dt.timedelta(days=4):
                decl=(dn,cost); break
        rows.append(dict(fips=fips,state=o["state"],name=o["name"],
            begin=o["begin"].isoformat(),end=o["end"].isoformat(),month=o["begin"].month,
            ets=sorted(o["ets"]),gust=round(o["gust"]),sustained=round(o["sustained"]),
            hail=round(o["hail"],2),tor=o["tor"],ef=o["ef"],flood=o["flood"],
            winter=o.get("winter",False),zoneSourced=o.get("zoneSourced",False),dmg=round(o["dmg"]),
            declared=1 if decl else 0,dn=decl[0] if decl else None,cost=decl[1] if decl else None))
    return rows

def pct(vals,p):
    if not vals: return None
    vals=sorted(vals); k=(len(vals)-1)*p/100; f=int(k)
    return round(vals[f]+(vals[min(f+1,len(vals)-1)]-vals[f])*(k-f),1)

def describe(rows,state,subset_fn,metrics,title):
    sub=[r for r in rows if r["state"]==state and subset_fn(r)]
    dec=[r for r in sub if r["declared"]]; nd=[r for r in sub if not r["declared"]]
    print(f"\n=== {state}: {title} ===")
    print(f"  episodes: {len(sub)}  (declared {len(dec)} / non-declared {len(nd)})")
    print(f"  {'metric':<18}{'declared p50/p90':>22}{'non-decl p50/p90':>22}")
    for m,lab in metrics:
        dv=[r[m] for r in dec if r[m] is not None]; nv=[r[m] for r in nd if r[m] is not None]
        print(f"  {lab:<18}{f'{pct(dv,50)} / {pct(dv,90)}':>22}{f'{pct(nv,50)} / {pct(nv,90)}':>22}")
    # per-county frequency for the headline metric
    return sub

def main():
    print("parsing Storm Events (county-level, R5)…")
    agg=build_panel(); print(f"  county-episodes: {len(agg)}")
    rows=label(agg)
    nd=sum(1 for r in rows if r["declared"])
    print(f"  labeled rows: {len(rows)}  declared county-episodes: {nd} ({100*nd/len(rows):.1f}%)")
    json.dump(rows,open(os.path.join(DATA,"county_panel.json"),"w"),separators=(",",":"))
    sz=os.path.getsize(os.path.join(DATA,"county_panel.json"))
    print(f"  wrote data/county_panel.json ({sz//1024} KB)")

    # ---- descriptive declared-vs-not, by hazard & state ----
    describe(rows,"IL",lambda r:r["tor"]>=1,
             [("tor","# tornadoes"),("ef","max EF"),("gust","max gust mph"),("dmg","$ property dmg")],
             "tornado episodes — what separates declared from not")
    describe(rows,"IL",lambda r:r["gust"]>=50 or "Thunderstorm Wind" in r["ets"],
             [("gust","max gust mph"),("sustained","max sustained"),("dmg","$ property dmg")],
             "wind episodes")
    describe(rows,"IL",lambda r:r["hail"]>=1.0,
             [("hail","max hail in"),("dmg","$ property dmg")],
             "large-hail episodes")
    describe(rows,"MN",lambda r:r["flood"],
             [("dmg","$ property dmg")],
             "flood episodes (note: rain/stage/SWE not yet in panel)")

    # ---- base declaration rate by state x hazard (where each hazard drives decs) ----
    haz={"tornado":lambda r:r["tor"]>=1,"wind>=60mph":lambda r:r["gust"]>=60,
         "hail>=1in":lambda r:r["hail"]>=1.0,"flood":lambda r:r["flood"]}
    print("\n=== declared base rate by state x hazard (declared / episodes) ===")
    print(f"  {'state':<7}"+"".join(f"{h:>16}" for h in haz))
    for sfa in ("IL","IN","MI","MN","OH","WI"):
        sr=[r for r in rows if r["state"]==sfa]
        cells=[]
        for h,fn in haz.items():
            sub=[r for r in sr if fn(r)]; d=sum(x["declared"] for x in sub)
            cells.append(f"{(100*d/len(sub) if sub else 0):.0f}% ({d}/{len(sub)})")
        print(f"  {sfa:<7}"+"".join(f"{c:>16}" for c in cells))

    # ---- damage is the real driver: declared rate by damage band ----
    def band_rates(state,fn,title):
        sub=[r for r in rows if r["state"]==state and fn(r)]
        bands=[("$0",lambda d:d==0),("<$100K",lambda d:0<d<1e5),("$100K-1M",lambda d:1e5<=d<1e6),
               ("$1M-10M",lambda d:1e6<=d<1e7),(">=$10M",lambda d:d>=1e7)]
        print(f"\n=== {state} {title}: declared rate by property-damage band ===")
        for lab,bf in bands:
            b=[r for r in sub if bf(r["dmg"])]; d=sum(r["declared"] for r in b)
            if b: print(f"  {lab:<10} {100*d/len(b):>5.0f}% declared  ({d}/{len(b)})")
    band_rates("IL",lambda r:r["tor"]>=1,"tornado episodes")
    band_rates("MN",lambda r:r["flood"],"flood episodes")

    # per-county frequency example: IL counties, tornado episodes, declared rate
    il=[r for r in rows if r["state"]=="IL" and r["tor"]>=2]
    cc=collections.Counter(r["name"] for r in il)
    dcc=collections.Counter(r["name"] for r in il if r["declared"])
    print("\n=== IL: counties with the most multi-tornado episodes (>=2 tornadoes) ===")
    for name,n in cc.most_common(8):
        print(f"  {name:<16} {n} episodes, {dcc.get(name,0)} declared")

if __name__=="__main__":
    main()
