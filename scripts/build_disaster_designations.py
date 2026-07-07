#!/usr/bin/env python3
"""Build data/disaster_designations.json — per-DISASTER × per-COUNTY program designations.

OFFLINE (needs network). Pulls OpenFEMA DisasterDeclarationsSummaries v2 for every
disaster in data/disasters.json and records, for each designated area, which programs
were declared THERE (designations are per-area, not per-disaster — e.g. DR-4892 has
IH-designated counties but zero PA-designated counties, and on many disasters the PA
county list differs from the IA county list).

Powers the Operations Planner's "start from a declared disaster" flow: pick a disaster
+ program and the planner seeds the plan with exactly the counties designated for that
program.

Output shape (compact):
{
  "generated": "...", "source": "...",
  "byDisaster": {
    "<dn>": {
      "counties": { "<fips5>": <mask> },   # 1=PA, 2=IA-authorized (ih OR ia), 4=HM
      "nonCounty": [ ["<designatedArea>", <mask>], ... ]  # statewide / tribal / reservation rows — conserved, never dropped
    }
  },
  "audit": { "<dn>": {"rows": N, "county": N, "nonCounty": N}, "_meta": {...} }
}

IA bit follows the glossary: IA-authorized = ihProgramDeclared OR iaProgramDeclared
(see docs/fema-assistance-glossary.md). The planner's IA county filter keys on that OR,
matching the ledger's authorization badge (isIHP(d) || iaProgramDeclared).

Run: python3 scripts/build_disaster_designations.py
"""
import json, os, ssl, sys, time, urllib.parse, urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
API = "https://www.fema.gov/api/open/v2/DisasterDeclarationsSummaries"
# NOTE: no $select — combining $filter+$select+$top intermittently 503s at the
# fema.gov edge (observed 2026-07); full rows per disaster are small anyway.

def fetch(url, tries=8):
    # fema.gov intermittently 503s in bursts — retry patiently.
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "DisasterParameters/designations (public open data)"})
            ctx = ssl.create_default_context(cafile=os.environ.get("SSL_CERT_FILE") or None)
            with urllib.request.urlopen(req, timeout=60, context=ctx) as r:
                return json.load(r)
        except Exception as e:
            if i == tries - 1:
                raise
            time.sleep(min(60, 3 * (i + 1)))

def main():
    disasters = json.loads((DATA / "disasters.json").read_text())
    dns = sorted({d["disasterNumber"] for d in disasters})
    print(f"{len(dns)} ledger disasters (DR-{dns[0]}..DR-{dns[-1]})")

    dn_set = set(dns)
    states = sorted({d["state"] for d in disasters})
    cache_path = DATA / "_desig_cache.json"   # resumable; _-prefixed = gitignored
    cache = json.loads(cache_path.read_text()) if cache_path.exists() else {}

    # One bulk pull per state (paginated), filtered to the ledger's dn range —
    # far fewer requests than per-disaster queries (fema.gov edge throttles bursts).
    for st in states:
        if st in cache:
            continue
        rows, skip = [], 0
        while True:
            q = urllib.parse.quote(f"state eq '{st}' and disasterNumber ge {dns[0]}")
            url = f"{API}?$filter={q}&$top=1000&$skip={skip}"
            batch = fetch(url).get("DisasterDeclarationsSummaries", [])
            rows.extend(batch)
            if len(batch) < 1000:
                break
            skip += 1000
            time.sleep(2)
        cache[st] = rows
        cache_path.write_text(json.dumps(cache))
        print(f"  {st}: {len(rows)} designation rows pulled")
        time.sleep(2)

    by_disaster, audit = {}, {}
    for st in states:
        for r in cache[st]:
            dn = r.get("disasterNumber")
            if dn not in dn_set:
                continue
            mask = (1 if r.get("paProgramDeclared") else 0) \
                 | (2 if (r.get("ihProgramDeclared") or r.get("iaProgramDeclared")) else 0) \
                 | (4 if r.get("hmProgramDeclared") else 0)
            b = by_disaster.setdefault(str(dn), {"counties": {}, "nonCounty": []})
            a = audit.setdefault(str(dn), {"rows": 0, "county": 0, "nonCounty": 0})
            a["rows"] += 1
            stc, cty = (r.get("fipsStateCode") or ""), (r.get("fipsCountyCode") or "")
            if cty and cty != "000" and len(stc) == 2:
                fips = stc + cty
                b["counties"][fips] = b["counties"].get(fips, 0) | mask
            else:
                b["nonCounty"].append([r.get("designatedArea") or "(unnamed area)", mask])
        for dn, b in by_disaster.items():
            audit[dn]["county"] = len(b["counties"])
            audit[dn]["nonCounty"] = len(b["nonCounty"])

    n_rows = sum(a["rows"] for a in audit.values())
    zero = [dn for dn in map(str, dns) if dn not in by_disaster]
    if zero:
        print(f"WARNING: {len(zero)} disasters returned no designation rows: {zero}", file=sys.stderr)
    audit["_meta"] = {"totalRows": n_rows, "disastersWithNoRows": zero}

    out = {
        "generated": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "source": "OpenFEMA DisasterDeclarationsSummaries v2 (per-area program flags; IA bit = ihProgramDeclared OR iaProgramDeclared)",
        "maskLegend": {"1": "PA", "2": "IA-authorized (IH or legacy IA)", "4": "HM"},
        "byDisaster": by_disaster,
        "audit": audit,
    }
    dest = DATA / "disaster_designations.json"
    dest.write_text(json.dumps(out, separators=(",", ":")) + "\n")
    print(f"wrote {dest} ({dest.stat().st_size:,} bytes; {n_rows} designation rows across {len(dns)} disasters)")

if __name__ == "__main__":
    main()
