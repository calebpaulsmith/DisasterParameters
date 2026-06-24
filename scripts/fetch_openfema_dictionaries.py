#!/usr/bin/env python3
"""
Fetch the official OpenFEMA field dictionaries for every dataset this app relies on and
commit them to docs/openfema-definitions/ so the field meanings (e.g. iaProgramDeclared vs
ihProgramDeclared, totalAmountHaApproved vs totalAmountOnaApproved) are reviewable offline,
at any time, without hitting the network.

SOURCE / METHOD
  - OpenFEMA `OpenFemaDataSetFields` endpoint is itself a dataset describing every field of
    every OpenFEMA dataset (name, title, description, datatype, version). We pull the rows
    for each dataset we use and write one JSON per dataset plus a generated INDEX.md table.
  - CORS-open, no auth. NEEDS NETWORK. Idempotent — re-run any time to refresh:
        python3 scripts/fetch_openfema_dictionaries.py

These files are documentation/provenance only; the app does NOT read them at runtime.
"""
import os, json, urllib.request, urllib.parse, datetime as dt

OUT = os.path.join(os.path.dirname(__file__), "..", "docs", "openfema-definitions")
API = "https://www.fema.gov/api/open/v1/OpenFemaDataSetFields"

# The datasets this project sources numbers from (see CLAUDE.md "Data sources").
DATASETS = [
    ("DisasterDeclarationsSummaries", "Declarations, counties, dates, and the program-declared flags (pa/ia/ih/hm)."),
    ("FemaWebDisasterSummaries", "PA obligated + Cat A-B/C-G, HMGP, IHP approved + HA/ONA, IA registrations."),
    ("PublicAssistanceFundedProjectsDetails", "Per-project PA obligated $ + project counts (and lastObligationDate)."),
    ("IndividualsAndHouseholdsProgramValidRegistrations", "Per-registration IHP (HA/ONA) detail used for county IHP rollups."),
    ("HazardMitigationAssistanceProjects", "HMGP (§404) + non-disaster HMA project obligations (initialObligationDate)."),
    ("EmergencyManagementPerformanceGrants", "EMPG non-disaster preparedness grants (state-level)."),
    ("NonDisasterAssistanceFirefighterGrants", "AFG non-disaster firefighter grants (with recipient fire departments)."),
]


def get(url):
    req = urllib.request.Request(url, headers={"User-Agent": "DisasterParameters/openfema-dictionaries"})
    with urllib.request.urlopen(req, timeout=90) as r:
        return json.loads(r.read().decode("utf-8", "replace"))


def fetch_fields(dataset):
    """Return the field rows for one dataset, sorted by field name."""
    flt = urllib.parse.quote(f"openFemaDataSet eq '{dataset}'")
    rows, skip = [], 0
    while True:
        data = get(f"{API}?$filter={flt}&$top=1000&$skip={skip}&$format=json")
        recs = data.get("OpenFemaDataSetFields", [])
        if not recs:
            break
        rows.extend(recs)
        skip += len(recs)
        if len(recs) < 1000:
            break
    # keep the latest version row per field name (dedupe across dataset versions)
    by_name = {}
    for r in rows:
        n = r.get("name")
        if n not in by_name or (r.get("datasetVersion") or 0) >= (by_name[n].get("datasetVersion") or 0):
            by_name[n] = r
    out = []
    for n in sorted(by_name):
        r = by_name[n]
        out.append({
            "name": r.get("name"),
            "title": r.get("title"),
            "type": r.get("type"),
            "description": (r.get("description") or "").strip(),
        })
    return out


def main():
    os.makedirs(OUT, exist_ok=True)
    today = dt.date.today().isoformat()
    index_rows = []
    for dataset, blurb in DATASETS:
        fields = fetch_fields(dataset)
        doc = {
            "dataset": dataset,
            "purpose": blurb,
            "fetched": today,
            "source": f"{API}?$filter=openFemaDataSet eq '{dataset}'",
            "fieldCount": len(fields),
            "fields": fields,
        }
        path = os.path.join(OUT, f"{dataset}.json")
        json.dump(doc, open(path, "w"), indent=2)
        print(f"  wrote docs/openfema-definitions/{dataset}.json — {len(fields)} fields")
        index_rows.append((dataset, len(fields), blurb))

    # generated index table
    lines = [
        "# OpenFEMA field dictionaries (committed reference)",
        "",
        "Official field definitions for every OpenFEMA dataset this project sources numbers",
        "from, pulled from the `OpenFemaDataSetFields` endpoint. These are documentation only —",
        "the app does not read them at runtime. Regenerate with",
        "`python3 scripts/fetch_openfema_dictionaries.py`.",
        "",
        f"_Last fetched: {today}._",
        "",
        "| Dataset | Fields | What we use it for |",
        "|---|---:|---|",
    ]
    for dataset, count, blurb in index_rows:
        lines.append(f"| [`{dataset}`]({dataset}.json) | {count} | {blurb} |")
    lines += [
        "",
        "See [`../fema-assistance-glossary.md`](../fema-assistance-glossary.md) for the plain-",
        "language program glossary (IA, IHP, HA, ONA, PA, HMGP) and how these fields map to the",
        "keys in `data/disasters.json` and `data/county_declarations.json`.",
        "",
    ]
    open(os.path.join(OUT, "INDEX.md"), "w").write("\n".join(lines))
    print(f"  wrote docs/openfema-definitions/INDEX.md — {len(index_rows)} datasets")


if __name__ == "__main__":
    main()
