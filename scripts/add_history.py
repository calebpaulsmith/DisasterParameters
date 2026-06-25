#!/usr/bin/env python3
"""
Add older Region 5 disasters to data/disasters.json (and data/_disasters_raw.json).

Pulls OpenFEMA DisasterDeclarationsSummaries for the R5 states for a historical
FY range (DR = major disaster declarations), reconstructs each disaster's
designated counties, pulls real obligations/approvals from
FemaWebDisasterSummaries + a project count from PublicAssistanceFundedProjectsDetails,
and enriches hazards from the NOAA Storm Events CSVs in data/ using the helpers
in enrich.py. New disasters are merged in; existing ones are left untouched.

Run from repo root:  python3 scripts/add_history.py [START_FY END_FY]
Requires the StormEvents_details-*.csv.gz for the covered years in data/.
"""
import sys, os, json, time, datetime as dt, urllib.request, urllib.parse, collections
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE)
import enrich
DATA = enrich.DATA
R5 = ["IL", "IN", "MI", "MN", "OH", "WI"]
START_FY = int(sys.argv[1]) if len(sys.argv) > 1 else 2008
END_FY   = int(sys.argv[2]) if len(sys.argv) > 2 else 2015

def get(url, tries=4):
    for _ in range(tries):
        try:
            with urllib.request.urlopen(url, timeout=60) as r: return json.load(r)
        except Exception: time.sleep(1.5)
    return None

def pull_declarations():
    """R5 DR disasters in [START_FY,END_FY] -> dict dn -> raw disaster (with counties)."""
    base = "https://www.fema.gov/api/open/v2/DisasterDeclarationsSummaries"
    sel = "disasterNumber,state,declarationType,declarationTitle,incidentType,incidentBeginDate,incidentEndDate,fyDeclared,ihProgramDeclared,iaProgramDeclared,paProgramDeclared,hmProgramDeclared,fipsStateCode,fipsCountyCode,designatedArea"
    out = {}
    for st in R5:
        skip = 0
        while True:
            flt = (f"state eq '{st}' and declarationType eq 'DR' "
                   f"and fyDeclared ge {START_FY} and fyDeclared le {END_FY}")
            url = f"{base}?$filter={urllib.parse.quote(flt)}&$select={sel}&$top=1000&$skip={skip}&$format=json"
            d = get(url)
            rows = (d or {}).get("DisasterDeclarationsSummaries", [])
            if not rows: break
            for r in rows:
                dn = r["disasterNumber"]
                o = out.get(dn)
                if o is None:
                    o = out[dn] = dict(
                        disasterNumber=dn, state=r["state"], title=r["declarationTitle"],
                        incidentType=r["incidentType"], begin=r["incidentBeginDate"][:10],
                        end=(r.get("incidentEndDate") or r["incidentBeginDate"])[:10],
                        fy=r["fyDeclared"], paDeclared=False, iaDeclared=False,
                        ihpDeclared=False, iaProgramDeclared=False, hmProgramDeclared=False,
                        stateFips=r["fipsStateCode"], counties={})
                # Raw OpenFEMA flags, OR-accumulated across rows. iaDeclared = iaAuthorized =
                # ihProgramDeclared OR iaProgramDeclared (per OpenFEMA). ihpDeclared (modern IHP)
                # and iaProgramDeclared (legacy IA) kept distinct; iaProgramDeclared is not a $ field.
                ih = bool(r.get("ihProgramDeclared")); ia = bool(r.get("iaProgramDeclared"))
                o["paDeclared"] = o["paDeclared"] or bool(r.get("paProgramDeclared"))
                o["hmProgramDeclared"] = o["hmProgramDeclared"] or bool(r.get("hmProgramDeclared"))
                o["ihpDeclared"] = o["ihpDeclared"] or ih
                o["iaProgramDeclared"] = o["iaProgramDeclared"] or ia
                o["iaDeclared"] = o["iaDeclared"] or ih or ia
                cc = r.get("fipsCountyCode")
                if cc and cc != "000":
                    o["counties"][cc] = (r.get("designatedArea") or "").replace(" (County)", "")
            skip += 1000
            if len(rows) < 1000: break
        print(f"  {st}: {sum(1 for v in out.values() if v['state']==st)} disasters")
    return out

def pull_costs(dn):
    u = ("https://www.fema.gov/api/open/v1/FemaWebDisasterSummaries"
         f"?$filter=disasterNumber%20eq%20{dn}&$format=json")
    d = get(u); arr = (d or {}).get("FemaWebDisasterSummaries", [])
    s = arr[0] if arr else {}
    def n(x):
        try: return round(float(x))
        except Exception: return 0
    pc = get("https://www.fema.gov/api/open/v2/PublicAssistanceFundedProjectsDetails"
             f"?$filter=disasterNumber%20eq%20{dn}&$top=1&$inlinecount=allpages&$format=json")
    proj = ((pc or {}).get("metadata") or {}).get("count", 0) or 0
    return dict(
        paTotal=n(s.get("totalObligatedAmountPa")), paEmergencyAB=n(s.get("totalObligatedAmountCatAb")),
        paPermanentCG=n(s.get("totalObligatedAmountCatC2g")), paProjects=int(proj),
        hmgp=n(s.get("totalObligatedAmountHmgp")), ihpTotal=n(s.get("totalAmountIhpApproved")),
        ihpHousing=n(s.get("totalAmountHaApproved")), ihpOna=n(s.get("totalAmountOnaApproved")),
        iaRegistrations=int(s.get("totalNumberIaApproved") or 0))

def enrich_record(d, by_state, costs):
    begin = dt.date.fromisoformat(d["begin"]); end = dt.date.fromisoformat(d["end"])
    w0, w1 = begin - dt.timedelta(days=1), end + dt.timedelta(days=1)
    sf = d["stateFips"]; counties = set(d["counties"].keys())
    win = [e for e in by_state.get(sf, []) if w0 <= e["date"] <= w1]
    cty = [e for e in win if e["czt"] == "C" and e["czf"] in counties] if counties else []
    use = cty if cty else win
    ets = set(e["et"] for e in use)
    winds = [e["mag"] for e in use if e["et"] in enrich.WIND_TYPES and e["mag"]]
    hails = [e["mag"] for e in use if e["et"] == "Hail" and e["mag"]]
    efs = [e["ef"] for e in use if e["ef"] is not None]
    floods = [e for e in use if e["et"] in enrich.FLOOD_TYPES]
    snows = [e for e in use if e["et"] in enrich.SNOW_TYPES]
    tags = enrich.type_tags(ets, d["title"]); county5 = [sf + c for c in counties]
    peak_stage = enrich.usgs_peak_stage(enrich.STATE_ABBR.get(sf, d["state"]), list(counties), w0, w1) if ("Flooding" in tags and counties) else None
    rain_peak, rain_mean = (None, None)
    if any(t in tags for t in ("Flooding", "Storms", "Wind")) and county5:
        rain_peak, rain_mean = enrich.acis_rain(county5, w0, w1)
    rec = dict(
        disasterNumber=d["disasterNumber"], state=d["state"], title=d["title"],
        incidentType=d["incidentType"], begin=d["begin"], end=d["end"], fy=d["fy"],
        paDeclared=d["paDeclared"], iaDeclared=d["iaDeclared"],
        ihpDeclared=d.get("ihpDeclared", False), iaProgramDeclared=d.get("iaProgramDeclared", False),
        hmProgramDeclared=d.get("hmProgramDeclared", False), countyCount=len(counties),
        tags=tags, reportedDamage=round(sum(e["dmg"] for e in use)),
        hz=dict(windMph=round(max(winds) * enrich.KT2MPH) if winds else 0,
                hailIn=round(max(hails), 2) if hails else 0, torEF=max(efs) if efs else None,
                peakStageFt=peak_stage, rainIn=rain_peak, rainMeanIn=rain_mean,
                floodReports=len(floods), snowReports=len(snows),
                hailReports=sum(1 for e in use if e["et"] == "Hail"),
                windReports=sum(1 for e in use if e["et"] in enrich.WIND_TYPES),
                tornadoes=sum(1 for e in use if e["et"] == "Tornado"),
                stormEvents=len(use), countyMatched=bool(cty)),
        eventTypes=sorted(ets), costs=costs,
        pa=costs["paTotal"], ihp=costs["ihpTotal"])
    return rec

def main():
    existing = json.load(open(os.path.join(DATA, "disasters.json")))
    have = {x["disasterNumber"] for x in existing}
    raw_existing = json.load(open(os.path.join(DATA, "_disasters_raw.json")))
    print(f"existing: {len(existing)} disasters; pulling FY{START_FY}-{END_FY} R5 DR…")
    pulled = pull_declarations()
    new = {dn: d for dn, d in pulled.items() if dn not in have}
    print(f"pulled {len(pulled)}; {len(new)} new (not already present)")
    events = enrich.load_storm_events(); print(f"storm events loaded: {len(events)}")
    by_state = collections.defaultdict(list)
    for e in events: by_state[e["sf"]].append(e)

    added = []
    for i, (dn, d) in enumerate(sorted(new.items()), 1):
        costs = pull_costs(dn)
        rec = enrich_record(d, by_state, costs)
        added.append(rec); raw_existing.append(d)
        print(f"  [{i}/{len(new)}] DR-{dn}-{rec['state']} {rec['begin']} {rec['tags']} "
              f"PA=${costs['paTotal']/1e6:.1f}M IHP=${costs['ihpTotal']/1e6:.1f}M stage={rec['hz']['peakStageFt']}")

    merged = existing + added
    merged.sort(key=lambda x: -x["disasterNumber"])
    json.dump(merged, open(os.path.join(DATA, "disasters.json"), "w"), separators=(",", ":"))
    json.dump(raw_existing, open(os.path.join(DATA, "_disasters_raw.json"), "w"), separators=(",", ":"))
    print(f"\nwrote disasters.json: {len(existing)} -> {len(merged)} disasters (+{len(added)})")
    print("now run: python3 scripts/build_gages.py")

if __name__ == "__main__":
    main()
