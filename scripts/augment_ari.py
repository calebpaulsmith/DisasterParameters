#!/usr/bin/env python3
"""
Add the RAINFALL-RARITY layer to data/county_panel.json. For each county-episode
it converts the already-measured rainfall depths (from build_precip.py) into a
NOAA Atlas-14 average recurrence interval (ARI) in YEARS, so that "3 inches" is
read against each county's own climatology instead of in absolute inches:

  rainDayMaxARIyr - ARI (years) of the episode's peak 1-day rainfall (rainDayMaxIn)
  rainEventARIyr  - ARI (years) of the episode's event-total rainfall (rainEventIn),
                    evaluated at the duration closest to the episode length.

WHY
  A 3-inch day is a routine summer event in southern Illinois but a rare one in
  northern Minnesota. The ARI normalizes intensity onto the local precipitation-
  frequency curve, which is far more comparable across counties (and closer to the
  exposure/return-period logic that actually drives disaster declarations).

SOURCE / METHOD
  - NOAA Atlas-14 precipitation-frequency depth-duration-frequency (DDF) estimates,
    queried at each county CENTROID via the HDSC PFDS point service:
        https://hdsc.nws.noaa.gov/cgi-bin/hdsc/new/cgi_readH5.py
    with params: lat, lon, type=pf, data=depth, units=english, series=pds.
    The service returns partial-duration-series depths (inches) on a grid of
    durations (1-day, 2-day, ...) x ARIs (1,2,5,10,25,50,100,200,500,1000 yr).
    (If you prefer to avoid the live service, NOAA also publishes the Atlas-14
    volume grids as downloadable GIS rasters per state/volume from
    https://hdsc.nws.noaa.gov/pfds/ -- document/swap that path here if the CGI
    endpoint is retired. NOTE Atlas-14 is being superseded by Atlas-15; the same
    interpolation approach applies to its point estimates.)
  - County centroids are computed from data/r5_counties.json (each {f,n,s,g} where
    g is a multipolygon of [lon,lat] rings) by averaging all polygon vertices.
  - For a row depth D we locate it on the relevant DDF row (1-day for rainDayMaxIn;
    the duration nearest the episode length for rainEventIn) and LOG-LOG interpolate
    between bracketing (ARI, depth) points to get the recurrence interval. Depths
    below the 1-yr value -> ARI < 1 (reported as the 1-yr floor); depths above the
    1000-yr value are capped at 1000.

CACHING
  - Per-county DDF tables are cached to data/_atlas14_cache.json (git-ignored) so
    re-runs and additional episodes don't re-hit the service. Keyed by FIPS.

ROBUSTNESS
  - If Atlas-14 cannot be reached AND nothing is cached for a county, the two ARI
    fields are simply left ABSENT on that row (never written as bogus values) and
    a clear per-county message is printed. The script always exits cleanly and
    never touches costs / disasters.json or any other field.

ADDITIVE / IDEMPOTENT
  - Loads the panel, stamps fields in place, writes back compact.

Run from repo root (after build_precip.py):  python3 scripts/augment_ari.py
"""
import os, json, time, math, datetime as dt, urllib.request, urllib.parse, collections
HERE=os.path.dirname(os.path.abspath(__file__)); ROOT=os.path.dirname(HERE); DATA=os.path.join(ROOT,"data")
CACHE=os.path.join(DATA,"_atlas14_cache.json")
PFDS_URL="https://hdsc.nws.noaa.gov/cgi-bin/hdsc/new/cgi_readH5.py"

# ARI columns (years) returned by the PFDS point service, in order.
ARIS=[1,2,5,10,25,50,100,200,500,1000]
# Duration row labels we care about (days). PFDS also returns sub-daily rows; we
# only consume daily+ durations here, mapped by index after the sub-daily rows.
DAY_DURATIONS=[1,2,3,4,7,10,20,30,45,60]

def load_centroids():
    """fips -> (lat, lon) centroid from r5_counties.json multipolygons."""
    cos=json.load(open(os.path.join(DATA,"r5_counties.json")))
    out={}
    for c in cos:
        xs=[]; ys=[]
        # g is a list of polygons; each polygon is a list of rings; each ring a list of [lon,lat]
        for poly in c.get("g",[]):
            for ring in poly:
                for pt in ring:
                    if len(pt)>=2:
                        xs.append(pt[0]); ys.append(pt[1])
        if xs and ys:
            out[c["f"]]=(round(sum(ys)/len(ys),5), round(sum(xs)/len(xs),5))
    return out

def fetch_ddf(lat, lon, retries=3):
    """Return {duration_days: [depths per ARI]} parsed from the PFDS point service,
    or None on failure. The service returns a JS-ish payload; we parse the
    'quantiles' depth matrix and the duration labels defensively."""
    q=urllib.parse.urlencode({"lat":lat,"lon":lon,"type":"pf","data":"depth",
                              "units":"english","series":"pds"})
    url=f"{PFDS_URL}?{q}"
    for _ in range(retries):
        try:
            req=urllib.request.Request(url,headers={"User-Agent":"DisasterParameters/ari (public open data)"})
            with urllib.request.urlopen(req,timeout=90) as r:
                txt=r.read().decode("utf-8","replace")
            return parse_pfds(txt)
        except Exception:
            time.sleep(2)
    return None

def parse_pfds(txt):
    """The PFDS CGI returns lines like:
         quantiles = [[d11,d12,...],[d21,...],...];
         durations = ['5-min',...,'1-day','2-day',...];
    Extract the depth matrix and the duration labels, keep only day+ durations,
    return {duration_days: [depth_per_ARI...]}.  Returns None if unparseable."""
    def grab(name):
        i=txt.find(name)
        if i<0: return None
        i=txt.find("[",i)
        if i<0: return None
        depth=0; j=i
        while j<len(txt):
            ch=txt[j]
            if ch=="[": depth+=1
            elif ch=="]":
                depth-=1
                if depth==0: break
            j+=1
        frag=txt[i:j+1]
        try: return json.loads(frag.replace("'",'"'))
        except Exception: return None
    quant=grab("quantiles")
    durs=grab("durations")
    if not quant or not durs or len(quant)!=len(durs): return None
    out={}
    for label,row in zip(durs,quant):
        days=duration_to_days(label)
        if days is None: continue
        try: out[days]=[float(x) for x in row]
        except Exception: continue
    return out or None

def duration_to_days(label):
    """'1-day'->1, '2-day'->2, '60-day'->60; ignore sub-daily ('5-min','1-hr')."""
    label=str(label).strip().lower()
    if label.endswith("-day") or label.endswith("day"):
        n=label.replace("-day","").replace("day","").strip()
        try: return int(float(n))
        except: return None
    return None

def loglog_ari(depth, depths_by_ari):
    """Interpolate ARI (years) for a measured depth on a (ARI->depth) curve, log-log.
    depths_by_ari: list aligned with ARIS. Returns float years (1..1000 capped)."""
    pairs=[(a,d) for a,d in zip(ARIS,depths_by_ari) if d and d>0]
    if not pairs: return None
    if depth<=pairs[0][1]: return float(ARIS[0])           # below 1-yr -> floor
    if depth>=pairs[-1][1]: return float(ARIS[-1])         # above 1000-yr -> cap
    for (a0,d0),(a1,d1) in zip(pairs,pairs[1:]):
        if d0<=depth<=d1:
            # linear in log-space on both axes
            if d1==d0: return float(a0)
            f=(math.log(depth)-math.log(d0))/(math.log(d1)-math.log(d0))
            ly=math.log(a0)+f*(math.log(a1)-math.log(a0))
            return round(math.exp(ly),1)
    return float(ARIS[-1])

def nearest_duration(ddf, target_days):
    """Pick the available DDF duration row closest to the episode length (>=1 day)."""
    if not ddf: return None
    keys=sorted(ddf.keys())
    return min(keys, key=lambda k: abs(k-max(1,target_days)))

def main():
    panel=os.path.join(DATA,"county_panel.json")
    rows=json.load(open(panel))
    cache=json.load(open(CACHE)) if os.path.exists(CACHE) else {}
    centroids=load_centroids()

    fips_list=sorted({r["fips"] for r in rows})
    misses=[]
    for fips in fips_list:
        if fips in cache: continue
        ll=centroids.get(fips)
        if not ll:
            misses.append((fips,"no centroid")); continue
        ddf=fetch_ddf(ll[0], ll[1]); time.sleep(0.5)
        if ddf:
            # store as {str(duration_days): [depths...]} for JSON
            cache[fips]={str(k):v for k,v in ddf.items()}
            json.dump(cache,open(CACHE,"w"))   # checkpoint as we go
        else:
            misses.append((fips,"atlas14 unreachable"))
            print(f"  Atlas-14 unavailable for {fips} ({centroids.get(fips)}) -- ARI left absent for its rows")

    stamped=0
    for r in rows:
        c=cache.get(r["fips"])
        if not c: continue
        ddf={int(k):v for k,v in c.items()}
        # 1-day ARI from rainDayMaxIn
        if "rainDayMaxIn" in r and 1 in ddf:
            a=loglog_ari(r["rainDayMaxIn"], ddf[1])
            if a is not None: r["rainDayMaxARIyr"]=a
        # event ARI from rainEventIn at the duration nearest the episode length
        if "rainEventIn" in r:
            try:
                b=dt.date.fromisoformat(r["begin"]); e=dt.date.fromisoformat(r["end"])
                dur=(e-b).days+1
            except Exception:
                dur=1
            dkey=nearest_duration(ddf, dur)
            if dkey is not None:
                a=loglog_ari(r["rainEventIn"], ddf[dkey])
                if a is not None: r["rainEventARIyr"]=a
        if "rainDayMaxARIyr" in r or "rainEventARIyr" in r: stamped+=1

    json.dump(rows,open(panel,"w"),separators=(",",":"))
    print(f"cached Atlas-14 DDF for {len(cache)} counties ({len(misses)} misses)")
    print(f"stamped ARI (rainDayMaxARIyr / rainEventARIyr) onto {stamped}/{len(rows)} rows -> data/county_panel.json")

if __name__=="__main__":
    main()
