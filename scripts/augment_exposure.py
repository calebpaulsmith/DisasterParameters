#!/usr/bin/env python3
"""
Add the EXPOSURE layer to data/county_panel.json. For each county-episode it
stamps the county's people and housing stock, so hazard intensity can be read
against how much is actually in harm's way (extent/exposure drives obligations
more than peak intensity -- see the blueprint):

  population   - county total population        (ACS 5-year B01003_001E)
  housingUnits - county total housing units     (ACS 5-year B25001_001E)

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
  - The Census API requires a key for sustained use. We read it from the
    environment variable CENSUS_API_KEY. If it is unset, the script prints a
    clear instruction (where to request a free key:
    https://api.census.gov/data/key_signup.html) and EXITS 0 WITHOUT modifying
    the panel -- so it never half-writes.

ADDITIVE / IDEMPOTENT
  - Loads data/county_panel.json, stamps population/housingUnits onto matching
    rows in place, writes back compact. Never touches costs / disasters.json.
    Re-running just refreshes these two fields.

Run from repo root (after build_panel.py):  python3 scripts/augment_exposure.py
"""
import os, sys, json, time, urllib.request, urllib.parse
HERE=os.path.dirname(os.path.abspath(__file__)); ROOT=os.path.dirname(HERE); DATA=os.path.join(ROOT,"data")

# Region 5 state FIPS -> abbreviation (for reporting).
R5_STATE_FIPS={"17":"IL","18":"IN","26":"MI","27":"MN","39":"OH","55":"WI"}
ACS_YEAR=2022   # latest stable ACS 5-year vintage
VARS=["B01003_001E","B25001_001E"]   # total population, total housing units

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

def main():
    key=os.environ.get("CENSUS_API_KEY")
    if not key:
        print("CENSUS_API_KEY is not set; skipping exposure enrichment (panel unchanged).")
        print("Request a free key at https://api.census.gov/data/key_signup.html then:")
        print("  export CENSUS_API_KEY=<your_key>  &&  python3 scripts/augment_exposure.py")
        sys.exit(0)

    panel=os.path.join(DATA,"county_panel.json")
    rows=json.load(open(panel))

    fmap={}  # 5-digit fips -> {population, housingUnits}
    for sf,abbr in sorted(R5_STATE_FIPS.items()):
        data=fetch_state(sf, key); time.sleep(0.3)
        if not data or len(data)<2:
            print(f"  WARNING: no ACS data returned for {abbr} (state {sf}); its rows keep prior values")
            continue
        header=data[0]
        ip=header.index("B01003_001E"); ih=header.index("B25001_001E")
        ist=header.index("state"); ico=header.index("county")
        n=0
        for rec in data[1:]:
            fips=str(rec[ist]).zfill(2)+str(rec[ico]).zfill(3)
            fmap[fips]={"population":to_int(rec[ip]),"housingUnits":to_int(rec[ih])}
            n+=1
        print(f"  {abbr}: {n} counties")

    if not fmap:
        print("No ACS data fetched; panel left unchanged.")
        sys.exit(0)

    stamped=0
    for r in rows:
        ex=fmap.get(r["fips"])
        if ex:
            r["population"]=ex["population"]; r["housingUnits"]=ex["housingUnits"]
            stamped+=1
        # developedFrac: intentionally not written -- see module docstring (NLCD stretch).

    json.dump(rows,open(panel,"w"),separators=(",",":"))
    print(f"stamped exposure (population, housingUnits) onto {stamped}/{len(rows)} rows "
          f"from {len(fmap)} counties (ACS {ACS_YEAR}) -> data/county_panel.json")

if __name__=="__main__":
    main()
