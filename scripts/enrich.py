#!/usr/bin/env python3
"""
Build data/disasters.json: real Region 5 FEMA disasters enriched with
measured hazard metrics from NOAA Storm Events (offline CSV join) and
peak river stage from USGS Water Services (daily values).

Run from repo root:  python3 scripts/enrich.py
Requires the StormEvents_details-*.csv.gz files in data/ (downloaded
from https://www.ncei.noaa.gov/pub/data/swdi/stormevents/csvfiles/).
"""
import gzip, csv, glob, json, datetime as dt, urllib.request, urllib.parse, time, sys, os, collections

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
DATA = os.path.join(ROOT, "data")

R5_FIPS = {"17", "18", "26", "27", "39", "55"}
KT2MPH = 1.151
WIND_TYPES = {"Thunderstorm Wind", "High Wind", "Strong Wind", "Marine Thunderstorm Wind", "Marine High Wind"}
SNOW_TYPES = {"Heavy Snow", "Winter Storm", "Winter Weather", "Ice Storm", "Blizzard",
              "Lake-Effect Snow", "Sleet", "Frost/Freeze", "Cold/Wind Chill"}
FLOOD_TYPES = {"Flood", "Flash Flood", "Coastal Flood", "Lakeshore Flood"}

def parse_dt(ym, day):
    try:
        ym = int(ym); day = int(day)
        return dt.date(ym // 100, ym % 100, day)
    except Exception:
        return None

def load_storm_events():
    """Return list of Region 5 events: dict(date, stateFips, czType, czFips, eventType, magnitude, torEF, dmg)."""
    out = []
    for f in sorted(glob.glob(os.path.join(DATA, "StormEvents_details-ftp_v1.0_d20*.csv.gz"))):
        with gzip.open(f, "rt", encoding="latin-1") as fh:
            r = csv.reader(fh); hdr = next(r); ix = {h: i for i, h in enumerate(hdr)}
            for row in r:
                if row[ix["STATE_FIPS"]] not in R5_FIPS:
                    continue
                d = parse_dt(row[ix["BEGIN_YEARMONTH"]], row[ix["BEGIN_DAY"]])
                if not d:
                    continue
                mag = row[ix["MAGNITUDE"]]
                try: mag = float(mag) if mag else None
                except Exception: mag = None
                ef = row[ix["TOR_F_SCALE"]] or ""
                ef_n = int(ef[2]) if ef.startswith("EF") and ef[2:3].isdigit() else (
                        int(ef[1]) if ef.startswith("F") and ef[1:2].isdigit() else None)
                out.append(dict(
                    date=d, sf=row[ix["STATE_FIPS"]], czt=row[ix["CZ_TYPE"]],
                    czf=(row[ix["CZ_FIPS"]] or "").zfill(3), et=row[ix["EVENT_TYPE"]],
                    mag=mag, ef=ef_n))
    return out

def usgs_peak_stage(state_abbr, county_fips_list, start, end):
    """Peak daily gage height (ft) across affected counties during the window, from USGS DV."""
    if not county_fips_list:
        return None
    sf = STATE_FIPS_OF.get(state_abbr, "")
    counties = ",".join(sf + c for c in sorted(set(county_fips_list))[:20])  # 5-digit FIPS
    qs = urllib.parse.urlencode({
        "format": "json", "countyCd": counties,
        "parameterCd": "00065", "statCd": "00003",  # gage height, daily mean (the stat USGS stores)
        "startDT": start.isoformat(), "endDT": end.isoformat(), "siteStatus": "all"})
    url = "https://waterservices.usgs.gov/nwis/dv/?" + qs
    for _ in range(3):
        try:
            with urllib.request.urlopen(url, timeout=45) as resp:
                j = json.load(resp)
            peak = None
            for ts in j.get("value", {}).get("timeSeries", []):
                for blk in ts.get("values", []):
                    for v in blk.get("value", []):
                        try: x = float(v["value"])
                        except Exception: continue
                        # Real river gage height above datum is < ~75 ft; larger values are
                        # reservoir/lake elevation gauges (ft above sea level) — exclude them.
                        if 0 <= x <= 75 and (peak is None or x > peak):
                            peak = x
            return round(peak, 1) if peak is not None else None
        except Exception:
            time.sleep(1.5)
    return None

def type_tags(event_types, title):
    t = title.upper(); tags = []
    add = lambda x: tags.append(x) if x not in tags else None
    if any(e in FLOOD_TYPES for e in event_types) or "FLOOD" in t: add("Flooding")
    if "Tornado" in event_types or "TORNADO" in t: add("Tornado")
    if "Hail" in event_types or "HAIL" in t: add("Hail")
    if any(e in WIND_TYPES for e in event_types) or "WIND" in t: add("Wind")
    if any(e in SNOW_TYPES for e in event_types) or any(k in t for k in ("WINTER", "SNOW", "ICE", "BLIZZARD")): add("Snow/Ice")
    if "DAM" in t or "LEVEE" in t: add("Dam/Levee")
    if "STORM" in t and "Flooding" not in tags: add("Storms")
    if not tags: add("Storms")
    return tags

STATE_ABBR = {"17": "IL", "18": "IN", "26": "MI", "27": "MN", "39": "OH", "55": "WI"}
STATE_FIPS_OF = {v: k for k, v in STATE_ABBR.items()}

def main():
    disasters = json.load(open(os.path.join(DATA, "_disasters_raw.json")))
    print(f"disasters: {len(disasters)}")
    events = load_storm_events()
    print(f"Region 5 storm events loaded: {len(events)}")

    # index events by state for speed
    by_state = collections.defaultdict(list)
    for e in events:
        by_state[e["sf"]].append(e)

    out = []
    for i, d in enumerate(disasters):
        begin = dt.date.fromisoformat(d["begin"][:10])
        end = dt.date.fromisoformat((d["end"] or d["begin"])[:10])
        w0, w1 = begin - dt.timedelta(days=1), end + dt.timedelta(days=1)
        sf = d["stateFips"]
        counties = set(d["counties"].keys())

        win = [e for e in by_state.get(sf, []) if w0 <= e["date"] <= w1]
        cty = [e for e in win if e["czt"] == "C" and e["czf"] in counties] if counties else []
        use = cty if cty else win  # prefer county-matched, fall back to state-window

        ets = set(e["et"] for e in use)
        winds = [e["mag"] for e in use if e["et"] in WIND_TYPES and e["mag"]]
        hails = [e["mag"] for e in use if e["et"] == "Hail" and e["mag"]]
        efs = [e["ef"] for e in use if e["ef"] is not None]
        floods = [e for e in use if e["et"] in FLOOD_TYPES]
        snows = [e for e in use if e["et"] in SNOW_TYPES]

        wind_mph = round(max(winds) * KT2MPH) if winds else 0
        hail_in = round(max(hails), 2) if hails else 0
        tor_ef = max(efs) if efs else None

        peak_stage = None
        if ("Flooding" in type_tags(ets, d["title"])) and counties:
            peak_stage = usgs_peak_stage(STATE_ABBR.get(sf, d["state"]), list(counties), w0, w1)

        rec = dict(
            disasterNumber=d["disasterNumber"], state=d["state"], title=d["title"],
            incidentType=d["incidentType"], begin=d["begin"][:10], end=(d["end"] or d["begin"])[:10],
            fy=d["fy"], paDeclared=d["paDeclared"], iaDeclared=d["iaDeclared"],
            countyCount=len(counties),
            tags=type_tags(ets, d["title"]),
            hz=dict(
                windMph=wind_mph, hailIn=hail_in, torEF=tor_ef,
                peakStageFt=peak_stage,
                floodReports=len(floods), snowReports=len(snows),
                stormEvents=len(use), countyMatched=bool(cty)),
            eventTypes=sorted(ets),
        )
        out.append(rec)
        print(f"  DR-{rec['disasterNumber']}-{rec['state']} {rec['begin']}..{rec['end']} "
              f"wind={wind_mph}mph hail={hail_in}in EF={tor_ef} stage={peak_stage}ft "
              f"events={len(use)} tags={rec['tags']}")

    out.sort(key=lambda x: -x["disasterNumber"])
    json.dump(out, open(os.path.join(DATA, "disasters.json"), "w"), separators=(",", ":"))
    print(f"\nwrote data/disasters.json ({len(out)} disasters)")

if __name__ == "__main__":
    main()
