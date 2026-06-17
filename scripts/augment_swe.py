#!/usr/bin/env python3
"""
Add an estimated SNOWPACK WATER-EQUIVALENT (SWE) layer to data/county_panel.json.
SWE — the inches of liquid water held in the snowpack — is the physically-correct
"flood fuel" for the Upper-Midwest spring-snowmelt floods (Red / Minnesota River)
that rainfall cannot explain (per analysis/county-driver-findings.md: 42% of MN
flood episodes with <1" rain are still declared).

  sweAntecedentIn - estimated SWE in the antecedent snowpack    (the standing water)
  sweMeltIn       - estimated SWE RELEASED by the largest 1-day melt (the runoff pulse)

HONEST PROVENANCE — this is an ESTIMATE, not a measurement
  True gridded SWE comes from NOHRSC SNODAS, whose daily archive is ~90 GB and is
  not backfillable in this environment; and GHCN water-equivalent (WESD) is not
  served by RCC-ACIS. So we derive SWE from the OBSERVED snow DEPTH that
  build_snow.py already measured (GHCN SNWD, real), using a settled late-winter
  snowpack bulk density:

      SWE_inches  ~=  snow_depth_inches  x  SNOWPACK_DENSITY

  SNOWPACK_DENSITY = 0.30 (water:snow), a standard value for a settled, ripe
  late-winter Upper-Midwest snowpack at the onset of melt (fresh snow is ~0.10;
  ripe melting snow runs 0.30-0.40). This is a coarse but transparent stand-in;
  swapping in real SNODAS SWE later only changes these two fields.

  The fields are flagged downstream as estimated (build_state_panel / build_context
  carry the basis), so the UI never presents them as observed SWE.

ADDITIVE / IDEMPOTENT / LOCAL
  - Reads the two snow-depth fields written by build_snow.py (snowDepthPreIn,
    snowMeltIn), writes the two SWE fields, saves compact. No network, no costs,
    no disasters.json. Safe to re-run. Run build_snow.py first.

Run from repo root (after build_snow.py):  python3 scripts/augment_swe.py
"""
import os, json
HERE=os.path.dirname(os.path.abspath(__file__)); ROOT=os.path.dirname(HERE); DATA=os.path.join(ROOT,"data")

SNOWPACK_DENSITY=0.30   # water:snow bulk density of a settled, melt-ready snowpack

def main():
    panel=os.path.join(DATA,"county_panel.json")
    rows=json.load(open(panel))
    missing=0; stamped=0
    for r in rows:
        depth=r.get("snowDepthPreIn"); melt=r.get("snowMeltIn")
        if depth is None or melt is None:
            missing+=1
            r["sweAntecedentIn"]=0.0; r["sweMeltIn"]=0.0
            continue
        r["sweAntecedentIn"]=round(depth*SNOWPACK_DENSITY,2)
        r["sweMeltIn"]=round(melt*SNOWPACK_DENSITY,2)
        stamped+=1
    json.dump(rows,open(panel,"w"),separators=(",",":"))
    mx=max((r.get("sweAntecedentIn",0) for r in rows),default=0)
    if missing:
        print(f"  note: {missing} rows lacked snow-depth fields (run build_snow.py first) -> SWE set 0")
    print(f"wrote estimated SWE (sweAntecedentIn, sweMeltIn @ density {SNOWPACK_DENSITY}) "
          f"onto {stamped} rows; maxAntecedentSWE={mx}\" -> data/county_panel.json")

if __name__=="__main__":
    main()
