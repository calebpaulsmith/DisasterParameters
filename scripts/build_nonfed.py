#!/usr/bin/env python3
"""
Build data/nonfed.json — per-disaster IMPLIED NON-FEDERAL SHARE aggregates
(phase 2b of docs/briefing-plan.md), from a full national sweep of OpenFEMA
PublicAssistanceFundedProjectsDetails (~820K project rows).

WHAT / WHY
  FemaWebDisasterSummaries (the briefing ledger's cost source) is FEDERAL SHARE
  ONLY — a state's own bill (the 10-25% cost-share match) appears nowhere in it.
  PA Details carries both figures per project:
    projectAmount         = estimated TOTAL eligible cost of the project
    federalShareObligated = the federal share obligated on it
  so per disaster:  impliedNonFederal = Σ projectAmount − Σ federalShareObligated.

  This is an ESTIMATE, and the UI must say so: projectAmount is an estimated
  total (it moves as projects reconcile), the difference is not an invoice, and
  the project-level federal sum will NOT exactly equal the FemaWebDisasterSummaries
  federal total (different datasets, refreshed on different days). The briefing
  keeps the summary figure authoritative and shows the project-level pair as the
  basis of the estimate — deltas footnoted, never hidden.

METHOD
  Sweeps PA Details in disasterNumber-range chunks (dn 0-7000, step 200), each
  chunk paginated $top=10000 with $select of just the three needed fields.
  ~90-120 requests total. RESUMABLE: each completed chunk's aggregates are
  cached in data/_nonfed_cache.json (gitignored), so a killed run re-fetches
  only unfinished chunks. Conservation audit: fetched row count is compared to
  the dataset's $inlinecount total; rows with a null disasterNumber are counted,
  never silently dropped.

Output: data/nonfed.json
  {generated, source, note, byDisaster:{dn:[projCostSum, fedObligSum, nProjects]},
   audit:{expectedRows, fetchedRows, nullDnRows, coverageDisasters, check}}
  Consumed by scripts/build_briefing.py (joined into briefing.json as the
  pc/pf/pn row columns) — run this FIRST, then build_briefing.py.

Refresh cadence: weekly (.github/workflows/refresh-weekly.yml) — obligations
reconcile over months; the daily briefing rebuild joins the committed snapshot.

Re-run any time:  python3 scripts/build_nonfed.py
"""
import os, json, time, urllib.request, urllib.parse, datetime as dt

DATA = os.path.join(os.path.dirname(__file__), "..", "data")
URL = "https://www.fema.gov/api/open/v2/PublicAssistanceFundedProjectsDetails"
CACHE = os.path.join(DATA, "_nonfed_cache.json")
DN_MAX, STEP = 7000, 200
SEL = urllib.parse.quote("disasterNumber,projectAmount,federalShareObligated")


def get(url, retries=5):
    req = urllib.request.Request(url, headers={"User-Agent": "DisasterParameters/nonfed"})
    for i in range(retries):
        try:
            with urllib.request.urlopen(req, timeout=180) as r:
                return json.loads(r.read().decode("utf-8", "replace"))
        except Exception:
            if i == retries - 1:
                raise
            time.sleep(2 ** i)


def expected_total():
    j = get(f"{URL}?$top=1&$inlinecount=allpages&$format=json")
    return int(j["metadata"]["count"])


def sweep_chunk(lo, hi):
    """Aggregate one dn range [lo, hi): {dn: [projSum, fedSum, n]}, plus row count."""
    agg, rows, skip = {}, 0, 0
    flt = urllib.parse.quote(f"disasterNumber ge {lo} and disasterNumber lt {hi}")
    while True:
        u = f"{URL}?$filter={flt}&$select={SEL}&$top=10000&$skip={skip}&$format=json&$metadata=off"
        chunk = (get(u) or {}).get("PublicAssistanceFundedProjectsDetails", [])
        for r in chunk:
            dn = r.get("disasterNumber")
            rows += 1
            if dn is None:
                agg.setdefault("_null", [0, 0, 0])
                dn = "_null"
            a = agg.setdefault(str(dn), [0.0, 0.0, 0])
            a[0] += float(r.get("projectAmount") or 0)
            a[1] += float(r.get("federalShareObligated") or 0)
            a[2] += 1
        if len(chunk) < 10000:
            return agg, rows
        skip += len(chunk)


def main():
    cache = {}
    if os.path.exists(CACHE):
        cache = json.load(open(CACHE))
        print(f"resuming: {len(cache)} of {DN_MAX//STEP} chunks cached")
    expected = expected_total()
    print(f"dataset reports {expected:,} rows")

    for lo in range(0, DN_MAX, STEP):
        key = str(lo)
        if key in cache:
            continue
        agg, rows = sweep_chunk(lo, lo + STEP)
        cache[key] = {"agg": agg, "rows": rows}
        json.dump(cache, open(CACHE, "w"))
        print(f"  dn {lo:>5}-{lo+STEP:<5} {rows:>8,} rows · {len(agg)} disasters")

    by, fetched, null_rows = {}, 0, 0
    for c in cache.values():
        fetched += c["rows"]
        for dn, a in c["agg"].items():
            if dn == "_null":
                null_rows += a[2]
                continue
            e = by.setdefault(dn, [0.0, 0.0, 0])
            e[0] += a[0]; e[1] += a[1]; e[2] += a[2]
    by = {dn: [round(a[0]), round(a[1]), a[2]] for dn, a in sorted(by.items(), key=lambda x: int(x[0]))}

    nonfed_total = sum(a[0] - a[1] for a in by.values())
    out = {
        "generated": dt.date.today().isoformat(),
        "source": "OpenFEMA PublicAssistanceFundedProjectsDetails (projectAmount, federalShareObligated), full national sweep",
        "note": "Per-disaster project-level sums. impliedNonFederal = projCostSum − fedObligSum "
                "(the state/local cost-share match, ESTIMATED — projectAmount is an estimated total "
                "that reconciles over the project's life). Project-level federal sums will not exactly "
                "match FemaWebDisasterSummaries federal totals (different datasets/refresh days); the "
                "summary figure stays authoritative. Not endorsed by FEMA.",
        "byDisaster": by,
        "audit": {
            "expectedRows": expected, "fetchedRows": fetched, "nullDnRows": null_rows,
            "coverageDisasters": len(by),
            "identity": "fetchedRows == sum(byDisaster n) + nullDnRows; expected vs fetched may drift by the day's reload",
            "rowsConserved": fetched == sum(a[2] for a in by.values()) + null_rows,
            "check": abs(fetched - expected) <= max(2000, expected // 100),
        },
    }
    path = os.path.join(DATA, "nonfed.json")
    json.dump(out, open(path, "w"), separators=(",", ":"))
    kb = os.path.getsize(path) // 1024
    print(f"wrote data/nonfed.json ({kb} KB) — {len(by):,} disasters · {fetched:,} rows "
          f"(expected {expected:,}) · implied non-federal ${round(nonfed_total):,} · "
          f"conserved: {out['audit']['rowsConserved']} · check: {out['audit']['check']}")


if __name__ == "__main__":
    main()
