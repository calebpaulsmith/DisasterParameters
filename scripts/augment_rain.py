#!/usr/bin/env python3
"""
Augment data/disasters.json IN PLACE with rainfall detail (does NOT touch costs,
gages, or any other field):
  hz.rainIn          - total incident-period rainfall (peak across counties)  [refreshed]
  hz.rainMeanIn      - area-mean incident-period total                         [refreshed]
  hz.rainDailyMaxIn  - highest SINGLE-DAY rainfall during the incident period  [new]
  hz.rainStations    - number of ACIS stations used (traceability)             [new]

Source: RCC-ACIS (NOAA) daily precipitation, summed/maxed across the disaster's
designated counties during [begin-1, end+1]. Run from repo root:
  python3 scripts/augment_rain.py
Needs data/_disasters_raw.json (county lists) + network.
"""
import os, json, datetime as dt, urllib.request, time
HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.dirname(HERE)
DATA = os.path.join(ROOT, "data")
RAIN_TAGS = ("Flooding", "Storms", "Wind")

def acis_rain(county_fips_list, start, end):
    """Returns (total_peak, mean, daily_max_peak, n_stations) across counties."""
    if not county_fips_list: return (None, None, None, 0)
    peak_total, daily_max, means, nst = None, None, [], 0
    for fips5 in sorted(set(county_fips_list))[:18]:
        payload = {"county": fips5, "sdate": start.isoformat(), "edate": end.isoformat(),
                   "elems": [{"name": "pcpn"}]}
        try:
            req = urllib.request.Request("https://data.rcc-acis.org/MultiStnData",
                data=json.dumps(payload).encode(), headers={"Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=40) as r:
                d = json.load(r)
        except Exception:
            continue
        totals = []
        for st in d.get("data", []):
            tot, dmax, ok = 0.0, 0.0, False
            for day in st.get("data", []):
                v = day[0] if isinstance(day, list) else day
                if v in ("M", "S", None, ""): continue
                if v == "T": v = 0
                try: fv = float(v)
                except Exception: continue
                tot += fv; ok = True
                if fv > dmax: dmax = fv
            if ok:
                totals.append(tot); nst += 1
                if daily_max is None or dmax > daily_max: daily_max = dmax
        if totals:
            cmax = max(totals)
            if peak_total is None or cmax > peak_total: peak_total = cmax
            means.append(sum(totals) / len(totals))
    return (round(peak_total, 1) if peak_total is not None else None,
            round(sum(means) / len(means), 1) if means else None,
            round(daily_max, 1) if daily_max is not None else None, nst)

def main():
    disasters = json.load(open(os.path.join(DATA, "disasters.json")))
    raw = {d["disasterNumber"]: d for d in json.load(open(os.path.join(DATA, "_disasters_raw.json")))}
    n = 0
    for d in disasters:
        r = raw.get(d["disasterNumber"])
        if not r: continue
        if not any(t in d.get("tags", []) for t in RAIN_TAGS): continue
        counties = r.get("counties") or {}
        if not counties: continue
        sf = r.get("stateFips", "")
        county5 = [sf + c for c in counties]
        b = dt.date.fromisoformat(d["begin"]); e = dt.date.fromisoformat(d["end"])
        tot, mean, dmax, nst = acis_rain(county5, b - dt.timedelta(days=1), e + dt.timedelta(days=1))
        hz = d["hz"]
        if tot is not None: hz["rainIn"] = tot
        if mean is not None: hz["rainMeanIn"] = mean
        hz["rainDailyMaxIn"] = dmax
        hz["rainStations"] = nst
        n += 1
        print(f"  DR-{d['disasterNumber']}-{d['state']} total={tot}\" daily-max={dmax}\" mean={mean}\" stations={nst}")
    json.dump(disasters, open(os.path.join(DATA, "disasters.json"), "w"), separators=(",", ":"))
    print(f"\naugmented {n} rain-relevant disasters; wrote disasters.json")

if __name__ == "__main__":
    main()
