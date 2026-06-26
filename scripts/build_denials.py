#!/usr/bin/env python3
"""
Build data/denials.json — Region-5 + nationwide FEMA DECLARATION DENIALS
("turndowns"), the analytic mirror of the declaration-lag dataset that powers
the Disaster Timelines view.

Source: OpenFEMA DeclarationDenials v1 (every row's currentRequestStatus is
"Turndown" — this dataset is ONLY denied requests; it carries no appeal-outcome
field). One row per denied declaration request. Unlike DisasterDeclarations,
denials carry BOTH a request date and a decision date, so we can measure two
lags:
  * incident-start -> denial   (statusDate - begin)   apples-to-apples with the
    approval charts' "incident-start -> declaration" lag
  * request -> denial          (statusDate - reqDate) FEMA's decision turnaround

Scope (matching the approval charts for now): requestStatusDate year >= 2007.
The full dataset reaches back to ~1953; widen YEAR_MIN to include it later.
National rows include Region 5 (R5 is filtered client-side via `region==5`),
so this single committed file feeds BOTH the existing Region 5 / National clicker.

Lean record (browser computes the lags):
  reqNum, region, state, tribal, reqDate, statusDate, begin, reqBegin, reqEnd,
  type ("DR"|"EM"), incidentType, name, ia, pa, ih, hm, incidentId

Run from repo root (needs network; OpenFEMA is CORS/proxy-open):
  python3 scripts/build_denials.py
"""
import os, json, urllib.request, urllib.parse, datetime, collections

HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.dirname(HERE)
DATA = os.path.join(ROOT, "data")
BASE = "https://www.fema.gov/api/open/v1/DeclarationDenials"
YEAR_MIN = 2007  # widen later to bring in the full ~1953- history
SEL = ("declarationRequestNumber,region,stateAbbreviation,tribalRequest,"
       "declarationRequestDate,requestStatusDate,incidentBeginDate,"
       "requestedIncidentBeginDate,requestedIncidentEndDate,declarationRequestType,"
       "requestedIncidentTypes,incidentName,ihProgramRequested,iaProgramRequested,"
       "paProgramRequested,hmProgramRequested,incidentId")

TYPE = {"Major Disaster": "DR", "Emergency": "EM"}

def d10(s):
    return (s or "")[:10] or None

def daynum(s):
    return datetime.date.fromisoformat(s).toordinal() if s else None

def main():
    rows, skip, page = [], 0, 1000
    while True:
        qs = urllib.parse.urlencode({"$select": SEL, "$top": str(page),
                                     "$skip": str(skip), "$format": "json"})
        with urllib.request.urlopen(f"{BASE}?{qs}", timeout=120) as r:
            batch = json.load(r).get("DeclarationDenials", [])
        if not batch:
            break
        rows.extend(batch)
        print(f"  fetched {len(batch)} (skip={skip}); {len(rows)} total")
        skip += page

    out, dropped_year, dropped_nodate = [], 0, 0
    for r in rows:
        status = d10(r.get("requestStatusDate"))
        if not status:
            dropped_nodate += 1; continue
        if int(status[:4]) < YEAR_MIN:
            dropped_year += 1; continue
        out.append({
            "reqNum": r.get("declarationRequestNumber"),
            "region": r.get("region"),
            "state": (r.get("stateAbbreviation") or "").strip(),
            "tribal": bool(r.get("tribalRequest")),
            "reqDate": d10(r.get("declarationRequestDate")),
            "statusDate": status,
            "begin": d10(r.get("incidentBeginDate")),
            "reqBegin": d10(r.get("requestedIncidentBeginDate")),
            "reqEnd": d10(r.get("requestedIncidentEndDate")),
            "type": TYPE.get(r.get("declarationRequestType"), r.get("declarationRequestType")),
            "incidentType": r.get("requestedIncidentTypes") or "Other",
            "name": r.get("incidentName") or "",
            "ia": bool(r.get("iaProgramRequested")),
            "pa": bool(r.get("paProgramRequested")),
            "ih": bool(r.get("ihProgramRequested")),
            "hm": bool(r.get("hmProgramRequested")),
            "incidentId": r.get("incidentId"),
        })
    out.sort(key=lambda d: d["statusDate"], reverse=True)

    # ---- diagnostics (printed, not written): lag sanity + scope ----
    def lags(key_a, key_b):
        v = []
        for d in out:
            a, b = daynum(d[key_b]), daynum(d[key_a])  # a - b
            if a is not None and b is not None:
                v.append(a - b)
        return v
    def med(v):
        s = sorted(v); n = len(s)
        return None if not n else (s[n//2] if n % 2 else (s[n//2-1]+s[n//2])//2)
    inc = lags("begin", "statusDate")      # incident-start -> denial
    req = lags("reqDate", "statusDate")    # request -> denial
    r5 = sum(1 for d in out if d["region"] == 5)
    print(f"\n  kept {len(out)} denials (statusDate year >= {YEAR_MIN})"
          f"  ·  dropped {dropped_year} pre-{YEAR_MIN}, {dropped_nodate} no-status-date")
    print(f"  Region 5: {r5}  ·  National: {len(out)}")
    print(f"  incident-start->denial lag  n={len(inc)} median={med(inc)} "
          f"min={min(inc) if inc else '-'} max={max(inc) if inc else '-'}")
    print(f"  request->denial lag         n={len(req)} median={med(req)} "
          f"min={min(req) if req else '-'} max={max(req) if req else '-'}")
    print("  by request type:", dict(collections.Counter(d["type"] for d in out)))
    print("  top incident types:", collections.Counter(d["incidentType"] for d in out).most_common(8))

    path = os.path.join(DATA, "denials.json")
    json.dump(out, open(path, "w"), separators=(",", ":"))
    print(f"\nwrote {len(out)} denials -> denials.json ({os.path.getsize(path)//1024} KB)")

if __name__ == "__main__":
    main()
