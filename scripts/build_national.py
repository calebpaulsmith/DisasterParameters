#!/usr/bin/env python3
"""
Build data/disasters_national.json — a LIGHTWEIGHT, nationwide companion to
disasters.json used only by the Disaster Timelines view's "National" toggle.

One row per disaster with just the declaration-lag fields (NO costs / hazards /
gages — those stay curated for Region 5 only):
  disasterNumber, state, title, incidentType, begin, end, declared

Scope: all major-disaster declarations (declarationType DR), fyDeclared 2007-2026
(the same window as the Region 5 set), EXCLUDING incidentType "Biological"
(COVID-19) — the pandemic declarations are carved out of the lag analysis just
as they are for Region 5, since their open-ended incident windows distort lag.

Source: OpenFEMA DisasterDeclarationsSummaries v2 (one county-area row per
designation; deduped here to one row per disasterNumber). `declared` is the
EARLIEST declarationDate; `begin`/`end` are the min/max incident dates across
the disaster's rows (end falls back to begin when incidentEndDate is null).

Run from repo root (needs network; OpenFEMA is CORS/proxy-open):
  python3 scripts/build_national.py
"""
import os, json, urllib.request, urllib.parse

HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.dirname(HERE)
DATA = os.path.join(ROOT, "data")
BASE = "https://www.fema.gov/api/open/v2/DisasterDeclarationsSummaries"
FLT = ("declarationType eq 'DR' and fyDeclared ge 2007 and fyDeclared le 2026 "
       "and incidentType ne 'Biological'")
SEL = "disasterNumber,state,declarationDate,incidentBeginDate,incidentEndDate,declarationTitle,incidentType"

def main():
    by = {}
    skip, page = 0, 1000
    while True:
        qs = urllib.parse.urlencode({"$filter": FLT, "$select": SEL,
                                     "$top": str(page), "$skip": str(skip),
                                     "$format": "json"})
        with urllib.request.urlopen(f"{BASE}?{qs}", timeout=120) as r:
            rows = json.load(r).get("DisasterDeclarationsSummaries", [])
        if not rows:
            break
        for row in rows:
            dn = row["disasterNumber"]
            decl = (row.get("declarationDate") or "")[:10]
            begin = (row.get("incidentBeginDate") or "")[:10]
            end = (row.get("incidentEndDate") or begin)[:10]
            if not (decl and begin):
                continue
            rec = by.get(dn)
            if not rec:
                by[dn] = dict(disasterNumber=dn, state=row["state"],
                              title=row.get("declarationTitle", ""),
                              incidentType=row.get("incidentType", ""),
                              begin=begin, end=end, declared=decl)
            else:
                if decl < rec["declared"]: rec["declared"] = decl
                if begin < rec["begin"]: rec["begin"] = begin
                if end > rec["end"]: rec["end"] = end
        print(f"  fetched {len(rows)} rows (skip={skip}); {len(by)} disasters so far")
        skip += page

    out = sorted(by.values(), key=lambda d: -d["disasterNumber"])
    path = os.path.join(DATA, "disasters_national.json")
    json.dump(out, open(path, "w"), separators=(",", ":"))
    size = os.path.getsize(path)
    print(f"\nwrote {len(out)} national disasters → disasters_national.json ({size//1024} KB)")

if __name__ == "__main__":
    main()
