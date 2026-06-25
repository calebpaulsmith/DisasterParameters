#!/usr/bin/env python3
"""OFFLINE: build data/recent.json — a trailing-window feed of the only two FEMA
programs that publish a per-item obligation DATE you can sort to the day:

  - Public Assistance  (PublicAssistanceFundedProjectsDetails) -> lastObligationDate
  - Hazard Mitigation  (HazardMitigationAssistanceProjects v4) -> initialObligationDate
                        (HMGP + non-disaster HMA: FMA/BRIC/PDM/…)

This powers the Geography view's "Recent activity" sub-filter (last 7 / 30 / 60 /
90 days + 1 year), and is the BAKED BACKUP for the live in-browser fetch:
  - short windows (7–90d) are fetched LIVE in the browser (national date-windowed
    query, filtered to Region 5 client-side — fast because the date column is
    indexed; the state filter is NOT, which is why we never filter by state
    server-side);
  - the 1-year window can't be served live (a single national pull truncates at
    OpenFEMA's 10,000-row cap), so the browser reads THIS committed file for it,
    and falls back to it for any window if a live fetch fails.

WHY NATIONAL-THEN-FILTER
  A server-side `stateAbbreviation eq 'IL' or …` forces a full table scan
  (15–25 s cold). Filtering only by `lastObligationDate ge <cutoff>` uses the
  indexed date column (~1–2 s) and paginates cleanly; we keep just the Region 5
  rows. Same trick the browser uses live.

OUTPUT (data/recent.json) — Region 5 only, COVID-19 excluded, lean per-record:
  pa: [{f,s,dn,amt,date,cat,cty}]   f = 5-digit county FIPS (null = statewide)
  hm: [{f,s,dn,amt,date,prog,cty,sub}]
  plus generated/windowDays/asOf (newest obligation date seen per program).
The browser buckets these by FIPS for any chosen window, so the file holds raw
dated rows (not pre-bucketed) — one file serves every window.

CORS-open OpenFEMA; offline/regenerable. Re-run any time:
    python3 scripts/build_county_recent.py [WINDOW_DAYS]
The Cloudflare worker in cloudflare/recent-worker.js mirrors this logic to
refresh the same payload daily — see cloudflare/README.md.
"""
import os, sys, json, time, urllib.request, urllib.parse, datetime as dt

DATA = os.path.join(os.path.dirname(__file__), "..", "data")
PA_URL = "https://www.fema.gov/api/open/v2/PublicAssistanceFundedProjectsDetails"
HM_URL = "https://www.fema.gov/api/open/v4/HazardMitigationAssistanceProjects"

R5_ABBR = {"IL", "IN", "MI", "MN", "OH", "WI"}
FIPS2AB = {"17": "IL", "18": "IN", "26": "MI", "27": "MN", "39": "OH", "55": "WI"}
ABBR = {"Illinois": "IL", "Indiana": "IN", "Michigan": "MI",
        "Minnesota": "MN", "Ohio": "OH", "Wisconsin": "WI"}
COVID_DNS = {4489, 4494, 4507, 4515, 4520, 4531}   # R5 COVID-19 (Biological)
WINDOW_DAYS = int(sys.argv[1]) if len(sys.argv) > 1 else 400   # 1yr + buffer for the baked file
PAGE = 1000


def get(url, retries=4, timeout=120):
    for i in range(retries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "DisasterParameters/recent (public open data)"})
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return json.loads(r.read().decode("utf-8", "replace"))
        except Exception as e:
            if i == retries - 1:
                print(f"  ! {e}")
            time.sleep(1.5 * (i + 1))
    return None


def n(x):
    try:
        return round(float(x))
    except Exception:
        return 0


def cutoff_iso(days):
    d = dt.date.today() - dt.timedelta(days=days)
    return d.isoformat() + "T00:00:00.000Z"


def paginate(base, flt, orderby, select, key):
    """National date-windowed pull, paginated by $skip until exhausted."""
    out, skip = [], 0
    while True:
        url = (f"{base}?$filter={urllib.parse.quote(flt)}"
               f"&$orderby={urllib.parse.quote(orderby)}"
               f"&$select={urllib.parse.quote(select)}"
               f"&$top={PAGE}&$skip={skip}&$format=json")
        d = get(url)
        recs = (d or {}).get(key, []) if d else []
        if not recs:
            break
        out += recs
        skip += len(recs)
        if len(recs) < PAGE:
            break
        time.sleep(0.05)
    return out


def fips_of(sc, cc):
    sc = str(sc or "").zfill(2)
    if cc in (None, "") or str(cc).strip() in ("", "000"):
        return None
    return sc + str(cc).zfill(3)


def build_pa():
    cut = cutoff_iso(WINDOW_DAYS)
    sel = ("disasterNumber,stateAbbreviation,stateNumberCode,countyCode,county,"
           "damageCategoryDescrip,federalShareObligated,lastObligationDate")
    print(f"PA: national pull lastObligationDate ge {cut[:10]} …")
    recs = paginate(PA_URL, f"lastObligationDate ge '{cut}'", "lastObligationDate desc", sel,
                    "PublicAssistanceFundedProjectsDetails")
    print(f"  PA national rows: {len(recs)}")
    rows, newest = [], ""
    for r in recs:
        if r.get("stateAbbreviation") not in R5_ABBR:
            continue
        if r.get("disasterNumber") in COVID_DNS:
            continue
        d = (r.get("lastObligationDate") or "")[:10]
        if d > newest:
            newest = d
        rows.append({
            "f": fips_of(r.get("stateNumberCode"), r.get("countyCode")),
            "s": r.get("stateAbbreviation"),
            "dn": r.get("disasterNumber"),
            "amt": n(r.get("federalShareObligated")),
            "date": d,
            "cat": r.get("damageCategoryDescrip"),
            "cty": r.get("county"),
        })
    print(f"  PA Region 5 rows: {len(rows)} · newest {newest or '—'}")
    return rows, newest


def build_hm():
    cut = cutoff_iso(WINDOW_DAYS)
    sel = ("disasterNumber,state,stateNumberCode,countyCode,county,programArea,"
           "projectType,subrecipient,federalShareObligated,initialObligationDate")
    print(f"HM: national pull initialObligationDate ge {cut[:10]} …")
    recs = paginate(HM_URL, f"initialObligationDate ne null and initialObligationDate ge '{cut}'",
                    "initialObligationDate desc", sel, "HazardMitigationAssistanceProjects")
    print(f"  HM national rows: {len(recs)}")
    rows, newest = [], ""
    for r in recs:
        ab = ABBR.get(r.get("state"))
        if ab is None:
            sc = str(r.get("stateNumberCode") or "").zfill(2)
            ab = FIPS2AB.get(sc)
        if ab not in R5_ABBR:
            continue
        if r.get("disasterNumber") in COVID_DNS:
            continue
        fed = n(r.get("federalShareObligated"))
        if not fed:
            continue
        d = (r.get("initialObligationDate") or "")[:10]
        if d > newest:
            newest = d
        sub = (r.get("subrecipient") or "").strip()
        f = None if sub.lower() == "statewide" else fips_of(r.get("stateNumberCode"), r.get("countyCode"))
        rows.append({
            "f": f,
            "s": ab,
            "dn": r.get("disasterNumber"),
            "amt": fed,
            "date": d,
            "prog": r.get("programArea"),
            "cty": r.get("county"),
            "sub": sub or None,
        })
    print(f"  HM Region 5 rows: {len(rows)} · newest {newest or '—'}")
    return rows, newest


def main():
    pa, pa_new = build_pa()
    hm, hm_new = build_hm()
    pa.sort(key=lambda r: r["date"], reverse=True)
    hm.sort(key=lambda r: r["date"], reverse=True)
    out = {
        "generated": dt.date.today().isoformat(),
        "generatedAt": dt.datetime.utcnow().replace(microsecond=0).isoformat() + "Z",
        "windowDays": WINDOW_DAYS,
        "asOf": {"PA": pa_new, "HM": hm_new},
        "source": ("OpenFEMA PublicAssistanceFundedProjectsDetails (lastObligationDate) + "
                   "HazardMitigationAssistanceProjects v4 (initialObligationDate); Region 5, "
                   "COVID-19 excluded. Real OpenFEMA figures — not endorsed by FEMA."),
        "note": ("Raw dated obligation rows (federal share). PA is obligated; 'date' = latest "
                 "obligation activity (includes downward adjustments). Bucket by 'f' (county FIPS; "
                 "null = statewide) for any window. Counts are obligation ACTIVITY, not new declarations."),
        "pa": pa,
        "hm": hm,
    }
    path = os.path.join(DATA, "recent.json")
    json.dump(out, open(path, "w"), separators=(",", ":"))
    print(f"wrote data/recent.json — PA {len(pa)} rows / HM {len(hm)} rows · "
          f"window {WINDOW_DAYS}d · asOf PA {pa_new or '—'} HM {hm_new or '—'}")


if __name__ == "__main__":
    main()
