#!/usr/bin/env python3
"""
Build data/gages.json (rich, predictive) and add per-disaster gage lists to
data/disasters.json.

For a curated set of KEY Region 5 river gages, fetch:
  - USGS site metadata (location, county FIPS, drainage area)
  - NWS AHPS flood categories (action/minor/moderate/major) via NWPS  [cached]
  - USGS historical ANNUAL PEAK crests (decades of stage/discharge)
Then tie each gage to the Region 5 disasters whose designated counties include
that gage and whose incident window contains one of its peak crests -> that
crest becomes a "declaration crest" carrying the disaster's PA/IA cost. This is
the stage->cost nexus used for prediction.

Run from repo root:  python3 scripts/build_gages.py
"""
import json, os, urllib.request, urllib.parse, time, io, csv, datetime as dt

HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.dirname(HERE)
DATA = os.path.join(ROOT, "data")

# Curated KEY gages — major flood-prone rivers near population across Region 5.
KEY = [
  ("05331000","Mississippi River","St. Paul","MN"),
  ("05378500","Mississippi River","Winona","MN"),
  ("05288500","Mississippi River","Brooklyn Park","MN"),
  ("05325000","Minnesota River","Mankato","MN"),
  ("05355200","Cannon River","Welch","MN"),
  ("05407000","Wisconsin River","Muscoda","WI"),
  ("04087000","Milwaukee River","Milwaukee","WI"),
  ("05543500","Illinois River","Marseilles","IL"),
  ("05586100","Illinois River","Valley City","IL"),
  ("05532500","Des Plaines River","Riverside","IL"),
  ("05420500","Mississippi River","Clinton","IL"),
  ("04119000","Grand River","Grand Rapids","MI"),
  ("04156000","Tittabawassee River","Midland","MI"),
  ("04165500","Clinton River","Mt Clemens","MI"),
  ("04193500","Maumee River","Waterville","OH"),
  ("04208000","Cuyahoga River","Independence","OH"),
  ("03270500","Great Miami River","Dayton","OH"),
  ("03335500","Wabash River","Lafayette","IN"),
  ("03353000","White River","Indianapolis","IN"),
]

def fetch(url, timeout=40, retries=3, post=None, headers=None):
    for _ in range(retries):
        try:
            req = urllib.request.Request(url, data=post, headers=headers or {})
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.read().decode("utf-8", "replace")
        except Exception:
            time.sleep(1.2)
    return None

def site_meta(sid):
    txt = fetch(f"https://waterservices.usgs.gov/nwis/site/?format=rdb&sites={sid}&siteOutput=expanded&siteStatus=all")
    if not txt: return {}
    rows = [l for l in txt.splitlines() if l and not l.startswith("#")]
    if len(rows) < 3: return {}
    hdr = rows[0].split("\t"); vals = rows[2].split("\t")
    d = dict(zip(hdr, vals))
    try: lat, lon = float(d.get("dec_lat_va")), float(d.get("dec_long_va"))
    except Exception: lat = lon = None
    st, co = d.get("state_cd", ""), (d.get("county_cd", "") or "")
    return dict(name=d.get("station_nm", ""), lat=lat, lon=lon,
                countyFips=(st + co.zfill(3)) if st and co else None,
                drainage=d.get("drain_area_va") or None)

def annual_peaks(sid):
    txt = fetch(f"https://nwis.waterdata.usgs.gov/nwis/peak?site_no={sid}&agency_cd=USGS&format=rdb")
    if not txt: return []
    out = []
    for l in txt.splitlines():
        if not l.startswith("USGS"): continue
        c = l.split("\t")
        if len(c) < 8: continue
        date = c[2].strip()
        if not date or len(date) < 4: continue
        def num(x):
            try: return float(x)
            except Exception: return None
        stage, q = num(c[6]), num(c[4])
        if stage is None and q is None: continue
        out.append(dict(date=date, year=int(date[:4]), stage=stage, q=q))
    out.sort(key=lambda x: x["date"])
    return out

# ---- AHPS via NWPS, reusing committed cache where available ----
def load_ahps_cache():
    try:
        cache = {g["id"]: g.get("cats") for g in json.load(open(os.path.join(DATA, "gages.json"))) if g.get("cats")}
    except Exception: cache = {}
    return cache

def nwps_categories(want_ids, names):
    """Resolve action/minor/moderate/major by matching gauge name in the NWPS list, then detail by LID."""
    res = {}
    listing = fetch("https://api.water.noaa.gov/nwps/v1/gauges?state.abbreviation=MN", timeout=75, retries=4,
                    headers={"User-Agent": "build"})
    if not listing: return res
    try: gauges = json.loads(listing).get("gauges", [])
    except Exception: return res
    for sid in want_ids:
        town, river = names[sid]
        cands = [x for x in gauges if town.lower() in x.get("name", "").lower()
                 and river.split()[0].lower() in x.get("name", "").lower()]
        for c in cands[:5]:
            dtl = fetch(f"https://api.water.noaa.gov/nwps/v1/gauges/{c['lid']}", timeout=18, retries=2)
            time.sleep(0.15)
            if not dtl: continue
            try: j = json.loads(dtl)
            except Exception: continue
            if j.get("usgsId") != sid: continue
            fl = (j.get("flood") or {}).get("categories", {})
            cats = {k: fl[k]["stage"] for k in fl if isinstance(fl[k].get("stage"), (int, float)) and fl[k]["stage"] > 0}
            if cats: res[sid] = cats
            break
    return res

def main():
    disasters = json.load(open(os.path.join(DATA, "disasters.json")))
    raw = {d["disasterNumber"]: d for d in json.load(open(os.path.join(DATA, "_disasters_raw.json")))}
    # disaster -> set of 5-digit county FIPS + cost meta
    dmeta = {}
    for d in disasters:
        r = raw.get(d["disasterNumber"], {})
        sf = r.get("stateFips", "")
        counties = {sf + c for c in (r.get("counties") or {}).keys()}
        dmeta[d["disasterNumber"]] = dict(
            counties=counties, begin=d["begin"], end=d["end"], state=d["state"], title=d["title"],
            pa=d["pa"], ihp=d["ihp"], total=d["pa"] + d["ihp"], tags=d.get("tags", []))

    names = {sid: (town, river) for sid, river, town, st in KEY}
    cache = load_ahps_cache()
    need = [sid for sid, *_ in KEY if sid not in cache]
    print(f"AHPS cache has {len(cache)}; resolving {len(need)} via NWPS…")
    cache.update(nwps_categories(need, names))

    gages = []
    for sid, river, town, st in KEY:
        meta = site_meta(sid); time.sleep(0.2)
        peaks = annual_peaks(sid); time.sleep(0.2)
        cats = cache.get(sid)
        g = dict(id=sid, name=f"{river} at {town}", river=river, town=town, state=st,
                 countyFips=meta.get("countyFips"), lat=meta.get("lat"), lon=meta.get("lon"),
                 drainage=meta.get("drainage"),
                 cats=cats, official=bool(cats),
                 floodStage=(cats or {}).get("minor"),
                 peaks=[{"y": p["year"], "d": p["date"], "s": p["stage"], "q": p["q"]} for p in peaks],
                 disasters=[])
        gages.append(g)
        print(f"  {sid} {g['name'][:34]:36} co={meta.get('countyFips')} peaks={len(peaks)} "
              f"AHPS={'Y' if cats else '-'} record={max([p['stage'] for p in peaks if p['stage']], default=None)}")

    # ---- tie gages <-> disasters via peak-in-window + county match ----
    perDisaster = {d["disasterNumber"]: [] for d in disasters}
    for g in gages:
        cf = g["countyFips"]
        if not cf: continue
        record = max([p["s"] for p in g["peaks"] if p["s"] is not None], default=None)
        # a crest only counts as a declaration crest if the river was actually elevated:
        # >= AHPS action stage, else >= 60% of the gage's record crest.
        thr = (g["cats"] or {}).get("action") if g["cats"] else None
        if thr is None and record is not None: thr = 0.6 * record
        for dn, m in dmeta.items():
            if "Flooding" not in m["tags"]: continue
            if cf not in m["counties"]: continue
            b = dt.date.fromisoformat(m["begin"]); e = dt.date.fromisoformat(m["end"])
            w0, w1 = b - dt.timedelta(days=4), e + dt.timedelta(days=14)
            best = None
            for p in g["peaks"]:
                try: pd = dt.date.fromisoformat(p["d"])
                except Exception: continue
                if w0 <= pd <= w1 and p["s"] is not None:
                    if best is None or p["s"] > best["s"]: best = p
            if best and (thr is None or best["s"] >= thr):
                tie = dict(dn=dn, date=best["d"], stage=best["s"], pa=m["pa"], ihp=m["ihp"], total=m["total"], title=m["title"])
                g["disasters"].append(tie)
                # category at that stage
                cat = stage_cat(best["s"], g["cats"])
                perDisaster[dn].append(dict(id=g["id"], name=g["name"], stage=best["s"], cat=cat))
        g["disasters"].sort(key=lambda t: -t["stage"])
        decl = [t["stage"] for t in g["disasters"]]
        g["minDeclStage"] = round(min(decl), 1) if decl else None

    for d in disasters:
        d["gages"] = sorted(perDisaster[d["disasterNumber"]], key=lambda x: -(x["stage"] or 0))

    json.dump(gages, open(os.path.join(DATA, "gages.json"), "w"), separators=(",", ":"))
    json.dump(disasters, open(os.path.join(DATA, "disasters.json"), "w"), separators=(",", ":"))
    tied = sum(1 for g in gages if g["disasters"])
    print(f"\nwrote gages.json ({len(gages)} key gages, {tied} tied to >=1 disaster)")
    print(f"updated disasters.json with per-disaster gage lists")
    for g in gages:
        if g["disasters"]:
            print(f"  {g['name'][:34]:36} minDecl={g['minDeclStage']}ft  decls: " +
                  ", ".join(f"DR-{t['dn']}@{t['stage']}ft(${(t['total'])/1e6:.0f}M)" for t in g["disasters"][:4]))

def stage_cat(s, cats):
    if not cats or s is None: return None
    if cats.get("major") and s >= cats["major"]: return "major"
    if cats.get("moderate") and s >= cats["moderate"]: return "moderate"
    if cats.get("minor") and s >= cats["minor"]: return "minor"
    if cats.get("action") and s >= cats["action"]: return "action"
    return "below"

if __name__ == "__main__":
    main()
