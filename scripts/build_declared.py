#!/usr/bin/env python3
"""
Augment data/disasters.json IN PLACE with the federal declaration date (does NOT
touch costs, gages, hz, or any other field):
  declared  - "YYYY-MM-DD", the ORIGINAL major-disaster declaration date

This powers the "Disaster Timelines" view, which plots incident date against
declaration date to show how long each disaster took to be declared. Declaration
lag is computed in the browser as (declared - end) in days.

Source: OpenFEMA DisasterDeclarationsSummaries v2, field `declarationDate`. A
disaster has one row per designated area (and later amendments share the same
disasterNumber); we take the EARLIEST declarationDate = the original declaration.

Run from repo root (needs network; OpenFEMA is CORS/proxy-open):
  python3 scripts/build_declared.py
"""
import os, json, urllib.request, urllib.parse

HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.dirname(HERE)
DATA = os.path.join(ROOT, "data")
BASE = "https://www.fema.gov/api/open/v2/DisasterDeclarationsSummaries"

def fetch_decl_dates(numbers):
    """Returns {disasterNumber: earliest 'YYYY-MM-DD' declarationDate}."""
    out = {}
    for i in range(0, len(numbers), 45):
        chunk = numbers[i:i + 45]
        flt = " or ".join(f"disasterNumber eq {n}" for n in chunk)
        qs = urllib.parse.urlencode({
            "$filter": flt,
            "$select": "disasterNumber,declarationDate",
            "$top": "1000", "$format": "json",
        })
        url = f"{BASE}?{qs}"
        with urllib.request.urlopen(url, timeout=60) as r:
            j = json.load(r)
        for row in j.get("DisasterDeclarationsSummaries", []):
            dn = row["disasterNumber"]
            d = (row.get("declarationDate") or "")[:10]
            if not d:
                continue
            if dn not in out or d < out[dn]:
                out[dn] = d
    return out

def main():
    path = os.path.join(DATA, "disasters.json")
    disasters = json.load(open(path))
    numbers = [d["disasterNumber"] for d in disasters]
    dates = fetch_decl_dates(numbers)

    n, missing = 0, []
    print(f"{'DR':>8}  {'state':<5} {'incident end':<12} {'declared':<12} lag(days)")
    for d in disasters:
        decl = dates.get(d["disasterNumber"])
        if not decl:
            missing.append(d["disasterNumber"]); continue
        d["declared"] = decl
        # report-only lag from incident end (browser computes the real thing)
        import datetime as dt
        end = dt.date.fromisoformat(d["end"])
        lag = (dt.date.fromisoformat(decl) - end).days
        n += 1
        print(f"DR-{d['disasterNumber']:<5} {d['state']:<5} {d['end']:<12} {decl:<12} {lag}")

    json.dump(disasters, open(path, "w"), separators=(",", ":"))
    print(f"\nadded `declared` to {n} disasters; wrote disasters.json")
    if missing:
        print(f"WARNING: no declarationDate for {len(missing)} disasters: {missing}")

if __name__ == "__main__":
    main()
