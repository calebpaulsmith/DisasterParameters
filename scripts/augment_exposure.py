#!/usr/bin/env python3
"""
Add the EXPOSURE layer to data/county_panel.json. For each county-episode it
stamps the county's people and housing stock, so hazard intensity can be read
against how much is actually in harm's way (extent/exposure drives obligations
more than peak intensity -- see the blueprint):

  population   - county total population        (Census Population Estimates,
                 latest vintage, no API key required; or ACS 5-year B01003_001E
                 when CENSUS_API_KEY is set)
  housingUnits - county total housing units     (ACS 5-year B25001_001E; only
                 populated when CENSUS_API_KEY is set -- housing has no key-free
                 county feed, so it is omitted in the default keyless path)

  developedFrac - DOCUMENTED STRETCH (NOT IMPLEMENTED). The intended value is the
                  fraction of the county that is "developed" land cover from
                  USGS NLCD (classes 21-24). NLCD ships as a 30 m CONUS raster
                  (multi-GB); the proper pull is a zonal-statistics step over the
                  county polygon (e.g. via the MRLC viewer / rasterio + the county
                  geometry in data/r5_counties.json). That raster work is out of
                  scope for this stdlib-only enricher and is left as a TODO; the
                  field is intentionally NOT written.

SOURCE / METHOD
  - U.S. Census Bureau American Community Survey 5-year, county tables, via the
    public Census API:
        https://api.census.gov/data/2022/acs/acs5?get=NAME,B01003_001E,B25001_001E&for=county:*&in=state:NN
    One call per Region-5 state (6 calls). Results are folded into a
    fips(5-digit) -> {population, housingUnits} map and stamped onto every panel
    row by `fips`.

API KEY
  - The ACS API now requires a key. We read it from the environment variable
    CENSUS_API_KEY; when set, we pull ACS population + housing. When it is UNSET
    we fall back to the key-free Census Population Estimates county CSV for
    population (housingUnits left unset) so exposure is still real and traceable
    without registration. Get a free key at
    https://api.census.gov/data/key_signup.html for the housing field.

ADDITIVE / IDEMPOTENT
  - Loads data/county_panel.json, stamps population/housingUnits onto matching
    rows in place, writes back compact. Never touches costs / disasters.json.
    Re-running just refreshes these two fields.

Run from repo root (after build_panel.py):  python3 scripts/augment_exposure.py
"""
import os, sys, json, time, csv, io, urllib.request, urllib.parse
HERE=os.path.dirname(os.path.abspath(__file__)); ROOT=os.path.dirname(HERE); DATA=os.path.join(ROOT,"data")

# Region 5 state FIPS -> abbreviation (for reporting).
R5_STATE_FIPS={"17":"IL","18":"IN","26":"MI","27":"MN","39":"OH","55":"WI"}
ACS_YEAR=2022   # latest stable ACS 5-year vintage
VARS=["B01003_001E","B25001_001E"]   # total population, total housing units
# Key-free fallback: Census Population Estimates county totals (latest vintage).
POPEST_URL=("https://www2.census.gov/programs-surveys/popest/datasets/"
            "2020-2024/counties/totals/co-est2024-alldata.csv")
POPEST_COL="POPESTIMATE2024"

def fetch_state(state_fips, key, retries=4):
    """Return list of [NAME, pop, housing, state, county] rows for a state, or None."""
    params={"get":"NAME,"+",".join(VARS),"for":"county:*","in":f"state:{state_fips}","key":key}
    url="https://api.census.gov/data/%d/acs/acs5?%s"%(ACS_YEAR,urllib.parse.urlencode(params))
    for _ in range(retries):
        try:
            req=urllib.request.Request(url,headers={"User-Agent":"DisasterParameters/exposure (public open data)"})
            with urllib.request.urlopen(req,timeout=90) as r: return json.load(r)
        except Exception: time.sleep(2)
    return None

def to_int(v):
    try: return int(float(v))
    except: return None

def fetch_popest(retries=4):
    """Key-free fallback: {fips5 -> population} from the Census Population Estimates CSV."""
    for _ in range(retries):
        try:
            req=urllib.request.Request(POPEST_URL,
                headers={"User-Agent":"DisasterParameters/exposure (public open data)"})
            with urllib.request.urlopen(req,timeout=120) as r:
                txt=r.read().decode("latin-1")
            break
        except Exception: time.sleep(2)
    else:
        return {}
    out={}
    for rec in csv.DictReader(io.StringIO(txt)):
        sf=str(rec.get("STATE","")).zfill(2); cc=str(rec.get("COUNTY","")).zfill(3)
        if sf in R5_STATE_FIPS and cc!="000":
            out[sf+cc]={"population":to_int(rec.get(POPEST_COL)),"housingUnits":None}
    return out

def acs_exposure(key):
    """{fips5 -> {population, housingUnits}} from ACS 5-year (needs a key)."""
    fmap={}
    for sf,abbr in sorted(R5_STATE_FIPS.items()):
        data=fetch_state(sf, key); time.sleep(0.3)
        if not data or len(data)<2:
            print(f"  WARNING: no ACS data returned for {abbr} (state {sf})"); continue
        header=data[0]
        ip=header.index("B01003_001E"); ih=header.index("B25001_001E")
        ist=header.index("state"); ico=header.index("county")
        n=0
        for rec in data[1:]:
            fips=str(rec[ist]).zfill(2)+str(rec[ico]).zfill(3)
            fmap[fips]={"population":to_int(rec[ip]),"housingUnits":to_int(rec[ih])}
            n+=1
        print(f"  {abbr}: {n} counties")
    return fmap

def main():
    key=os.environ.get("CENSUS_API_KEY")
    if key:
        print(f"CENSUS_API_KEY set; pulling ACS {ACS_YEAR} population + housing.")
        fmap=acs_exposure(key); src=f"ACS {ACS_YEAR}"
    else:
        print("CENSUS_API_KEY unset; using key-free Census Population Estimates "
              f"({POPEST_COL}) for population (housingUnits omitted).")
        fmap=fetch_popest(); src=POPEST_COL

    if not fmap:
        print("No exposure data fetched; panel left unchanged."); sys.exit(0)

    panel=os.path.join(DATA,"county_panel.json")
    rows=json.load(open(panel))
    stamped=0
    for r in rows:
        ex=fmap.get(r["fips"])
        if ex:
            r["population"]=ex["population"]
            if ex.get("housingUnits") is not None: r["housingUnits"]=ex["housingUnits"]
            stamped+=1
        # developedFrac: intentionally not written -- see module docstring (NLCD stretch).

    json.dump(rows,open(panel,"w"),separators=(",",":"))
    print(f"stamped exposure (population{'+housingUnits' if key else ''}) onto "
          f"{stamped}/{len(rows)} rows from {len(fmap)} counties ({src}) -> data/county_panel.json")

if __name__=="__main__":
    main()
