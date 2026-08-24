"""Build data/history_in.json — the per-county PRIOR FEMA HISTORY snapshot.

Pulls TODAY's data straight from OpenFEMA and freezes it as a static file the
board embeds (the board itself makes NO network requests). Re-run whenever a
fresh snapshot is wanted; the file carries `fetchedAt` and the UI shows it as
"Last updated".

    python build_history.py                # writes data/history_in.json
    python build_history.py --state IN --state-name Indiana

============================ THE EXACT QUERIES =============================
Reproduce these dynamically (Databricks v2) — plain HTTPS GET, JSON out,
paginate with $skip until a page returns fewer than $top rows. Both are also
embedded verbatim in the output JSON under "queries".

1. PA applicant history — one row per APPLICANT x COUNTY x DISASTER with
   federal PA dollars obligated + project count (this is the applicant list):

   https://www.fema.gov/api/open/v1/PublicAssistanceFundedProjectsSummaries
     ?$filter=state eq 'Indiana'
     &$orderby=id&$top=1000&$skip={skip}&$inlinecount=allpages

   Fields used: disasterNumber, county, applicantName, educationApplicant,
   numberOfProjects, federalObligatedAmount.

2. Disaster declarations — one row per DISASTER x DESIGNATED AREA with the
   declaration title/dates/programs (this is the county timeline):

   https://www.fema.gov/api/open/v2/DisasterDeclarationsSummaries
     ?$filter=state eq 'IN'
     &$orderby=id&$top=1000&$skip={skip}&$inlinecount=allpages

   Fields used: disasterNumber, declarationType, declarationTitle,
   incidentType, declarationDate, incidentBeginDate, incidentEndDate,
   fipsStateCode, fipsCountyCode, designatedArea, ia/pa/hm program flags.

Gotchas that MUST carry over to any port:
  - Do NOT combine $select with $filter+$top — fema.gov's edge WAF
    intermittently 503s that combination. Pull full rows.
  - PA dollars are FEDERAL SHARE OBLIGATED (not project cost, not paid).
  - COVID-19 (incidentType == 'Biological') is EXCLUDED from both pulls.
  - Summaries `county` is a NAME ("Marion", "Statewide", sometimes blank);
    declarations carry real FIPS. Rows that don't resolve to a county land in
    the `statewide` bucket or the audit — dollars are conserved, never dropped.
============================================================================
"""
from __future__ import annotations

import argparse
import json
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent

API = "https://www.fema.gov/api/open"
PAGE = 1000
UA = {"User-Agent": "pdaboard-history/1.0 (offline snapshot builder)"}

Q_SUMMARIES = (API + "/v1/PublicAssistanceFundedProjectsSummaries"
               "?$filter=state eq '{state_name}'"
               "&$orderby=id&$top=1000&$skip={skip}&$inlinecount=allpages")
Q_DECLARATIONS = (API + "/v2/DisasterDeclarationsSummaries"
                  "?$filter=state eq '{state}'"
                  "&$orderby=id&$top=1000&$skip={skip}&$inlinecount=allpages")


def log(msg):
    print(f"[history] {msg}")


def fetch_all(url_tpl: str, record_key: str, **fmt) -> list[dict]:
    """Paginate an OpenFEMA endpoint to completion. Returns every row."""
    rows, skip = [], 0
    while True:
        url = url_tpl.format(skip=skip, **fmt)
        # spaces/quotes must be %-encoded for urllib; keep the tpl human-readable
        safe = urllib.parse.quote(url, safe=":/?&=$'")
        for attempt in range(5):
            try:
                with urllib.request.urlopen(
                        urllib.request.Request(safe, headers=UA), timeout=90) as r:
                    page = json.loads(r.read().decode("utf-8"))
                break
            except Exception as e:                     # noqa: BLE001 — retry then raise
                if attempt == 4:
                    raise
                wait = 2 ** attempt
                log(f"  retry {attempt + 1} in {wait}s ({e})")
                time.sleep(wait)
        recs = page.get(record_key) or []
        rows.extend(recs)
        total = (page.get("metadata") or {}).get("count")
        log(f"  {record_key}: {len(rows)}" + (f"/{total}" if total else "") + " rows")
        if len(recs) < PAGE:
            return rows
        skip += PAGE


def load_dim(path: Path) -> dict:
    """name.lower() -> {fips,name} from the county dim CSV."""
    import csv
    out = {}
    with open(path, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            out[row["name"].lower()] = {"fips": row["fips"], "name": row["name"]}
    return out


def norm_county(name: str) -> str:
    n = (name or "").strip().lower()
    for suf in (" (county)", " county"):
        if n.endswith(suf):
            n = n[: -len(suf)].strip()
    return n


def build(state: str, state_name: str, out_path: Path):
    fetched_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    dim = load_dim(HERE / "data" / f"dim_county_{state.lower()}.csv")

    log(f"pull 1/2: PA applicant summaries ({state_name})")
    summaries = fetch_all(Q_SUMMARIES, "PublicAssistanceFundedProjectsSummaries",
                          state_name=state_name)
    log(f"pull 2/2: disaster declarations ({state})")
    decls = fetch_all(Q_DECLARATIONS, "DisasterDeclarationsSummaries", state=state)

    # ---- disaster meta + COVID exclusion (Biological) --------------------
    covid_dns = {d["disasterNumber"] for d in decls
                 if (d.get("incidentType") or "").lower() == "biological"}
    dis_meta: dict[int, dict] = {}
    for d in decls:
        dn = d["disasterNumber"]
        if dn in covid_dns:
            continue
        m = dis_meta.setdefault(dn, {
            "dn": dn, "type": d.get("declarationType"),
            "title": (d.get("declarationTitle") or "").title(),
            "incidentType": d.get("incidentType"),
            "declared": (d.get("declarationDate") or "")[:10],
            "began": (d.get("incidentBeginDate") or "")[:10] or None,
            "ended": (d.get("incidentEndDate") or "")[:10] or None,
        })
        # earliest declarationDate wins (amendments repeat rows)
        dd = (d.get("declarationDate") or "")[:10]
        if dd and (not m["declared"] or dd < m["declared"]):
            m["declared"] = dd

    # ---- per-county designations (timeline spine) ------------------------
    # one entry per (disaster, county); program flags OR'd across rows
    desig: dict[tuple[int, str], dict] = {}
    statewide_desig: dict[int, dict] = {}
    n_cty_rows = n_sw_rows = 0
    for d in decls:
        dn = d["disasterNumber"]
        if dn in covid_dns:
            continue
        cc = (d.get("fipsCountyCode") or "").zfill(3)
        flags = {"ia": bool(d.get("iaProgramDeclared") or d.get("ihProgramDeclared")),
                 "pa": bool(d.get("paProgramDeclared")),
                 "hm": bool(d.get("hmProgramDeclared"))}
        if cc == "000":
            n_sw_rows += 1
            e = statewide_desig.setdefault(dn, {"dn": dn, "area": d.get("designatedArea"),
                                                "ia": False, "pa": False, "hm": False})
        else:
            n_cty_rows += 1
            fips = (d.get("fipsStateCode") or "").zfill(2) + cc
            e = desig.setdefault((dn, fips), {"ia": False, "pa": False, "hm": False})
        for k in ("ia", "pa", "hm"):
            e[k] = e[k] or flags[k]

    # ---- applicant rollup (applicant x county x disaster) -----------------
    per_cty_apps: dict[str, dict] = {}    # fips -> applicant name -> agg
    per_cty_dn: dict[tuple[str, int], dict] = {}  # (fips,dn) -> {apps:set,pa,projects}
    sw_apps: dict[str, dict] = {}
    unmatched: dict[str, dict] = {}
    tot = {"rows": 0, "pa": 0.0, "matched": 0.0, "statewide": 0.0,
           "unmatched": 0.0, "covid": 0.0}
    for r in summaries:
        dn = r.get("disasterNumber")
        pa = float(r.get("federalObligatedAmount") or 0)
        projects = int(r.get("numberOfProjects") or 0)
        name = (r.get("applicantName") or "").strip() or "(unnamed applicant)"
        tot["rows"] += 1
        tot["pa"] += pa
        if dn in covid_dns:
            tot["covid"] += pa
            continue
        cty = norm_county(r.get("county"))
        hit = dim.get(cty)
        if hit:
            tot["matched"] += pa
            fips = hit["fips"]
            a = per_cty_apps.setdefault(fips, {}).setdefault(
                name, {"name": name, "pa": 0.0, "projects": 0,
                       "edu": bool(r.get("educationApplicant")), "disasters": {}})
            a["pa"] += pa
            a["projects"] += projects
            ad = a["disasters"].setdefault(dn, {"dn": dn, "pa": 0.0, "projects": 0})
            ad["pa"] += pa
            ad["projects"] += projects
            g = per_cty_dn.setdefault((fips, dn),
                                      {"apps": set(), "pa": 0.0, "projects": 0})
            g["apps"].add(name)
            g["pa"] += pa
            g["projects"] += projects
        else:
            bucket = sw_apps if cty in ("statewide", "") else unmatched
            tot["statewide" if bucket is sw_apps else "unmatched"] += pa
            a = bucket.setdefault(name, {"name": name, "pa": 0.0, "projects": 0,
                                         "county": r.get("county"), "disasters": {}})
            a["pa"] += pa
            a["projects"] += projects
            ad = a["disasters"].setdefault(dn, {"dn": dn, "pa": 0.0, "projects": 0})
            ad["pa"] += pa
            ad["projects"] += projects

    def _apps_out(d: dict) -> list[dict]:
        out = []
        for a in d.values():
            a = dict(a)
            a["pa"] = round(a["pa"], 2)
            a["disasters"] = sorted(
                ({**v, "pa": round(v["pa"], 2)} for v in a["disasters"].values()),
                key=lambda x: x["dn"])
            out.append(a)
        return sorted(out, key=lambda x: -x["pa"])

    # ---- assemble per county ---------------------------------------------
    counties = {}
    for key in dim.values():
        fips, cname = key["fips"], key["name"]
        dlist = []
        for (dn, f), flags in desig.items():
            if f != fips:
                continue
            m = dis_meta.get(dn)
            if not m:
                continue
            g = per_cty_dn.get((fips, dn)) or {}
            dlist.append({**m, **{k: flags[k] for k in ("ia", "pa", "hm")},
                          "applicants": len(g.get("apps") or ()),
                          "paObligated": round(g.get("pa") or 0.0, 2),
                          "projects": g.get("projects") or 0})
        # PA dollars in a county for a disaster that never designated it
        # (possible when Summaries' county attribution differs) — keep them
        for (f, dn), g in per_cty_dn.items():
            if f == fips and (dn, fips) not in desig and dn in dis_meta:
                dlist.append({**dis_meta[dn], "ia": False, "pa": True, "hm": False,
                              "applicants": len(g["apps"]), "undesignated": True,
                              "paObligated": round(g["pa"], 2),
                              "projects": g["projects"]})
        dlist.sort(key=lambda d: d["declared"] or "", reverse=True)
        if not dlist and fips not in per_cty_apps:
            continue
        counties[fips] = {"name": cname, "disasters": dlist,
                          "applicants": _apps_out(per_cty_apps.get(fips, {}))}

    check = round(tot["matched"] + tot["statewide"] + tot["unmatched"]
                  + tot["covid"] - tot["pa"], 2)
    out = {
        "state": state, "stateName": state_name,
        "fetchedAt": fetched_at,
        "source": "OpenFEMA (api.fema.gov aliases www.fema.gov/api/open) — snapshot, not live",
        "covidExcluded": True,
        "queries": [
            {"name": "pa_applicants",
             "dataset": "PublicAssistanceFundedProjectsSummaries", "version": "v1",
             "grain": "applicant x county x disaster",
             "url": Q_SUMMARIES.format(state_name=state_name, skip="{skip}"),
             "notes": "Paginate $skip by 1000 until a page returns <1000 rows. "
                      "federalObligatedAmount = FEDERAL share obligated. county is a "
                      "NAME ('Marion', 'Statewide', or blank). Do NOT add $select "
                      "(WAF 503s $select+$filter+$top)."},
            {"name": "declarations",
             "dataset": "DisasterDeclarationsSummaries", "version": "v2",
             "grain": "disaster x designated area",
             "url": Q_DECLARATIONS.format(state=state, skip="{skip}"),
             "notes": "Same pagination. fipsCountyCode '000' = statewide designation. "
                      "Multiple rows per (disaster,county) possible — OR the program "
                      "flags, take the earliest declarationDate. Exclude "
                      "incidentType 'Biological' (COVID-19)."},
        ],
        "counties": counties,
        "statewide": {"designations": sorted(statewide_desig.values(),
                                             key=lambda d: d["dn"]),
                      "applicants": _apps_out(sw_apps)},
        "audit": {
            "summaries": {"rows": tot["rows"], "paTotal": round(tot["pa"], 2),
                          "paMatchedToCounty": round(tot["matched"], 2),
                          "paStatewide": round(tot["statewide"], 2),
                          "paUnmatched": round(tot["unmatched"], 2),
                          "paCovidExcluded": round(tot["covid"], 2),
                          "conservationResidual": check,
                          "unmatchedCounties": sorted({a["county"] or ""
                                                       for a in unmatched.values()})},
            "declarations": {"rows": len(decls), "disasters": len(dis_meta),
                             "covidDisastersExcluded": sorted(covid_dns),
                             "countyDesignationRows": n_cty_rows,
                             "statewideDesignationRows": n_sw_rows},
        },
    }
    if unmatched:
        out["unmatchedApplicants"] = _apps_out(unmatched)

    out_path.write_text(json.dumps(out), encoding="utf-8")
    log(f"wrote {out_path} ({out_path.stat().st_size // 1024} KB) — "
        f"{len(counties)} counties, PA conserved: "
        f"matched {tot['matched']:,.0f} + statewide {tot['statewide']:,.0f} + "
        f"unmatched {tot['unmatched']:,.0f} + covid {tot['covid']:,.0f} "
        f"== total {tot['pa']:,.0f} (residual {check})")
    if check != 0:
        raise SystemExit("DOLLAR CONSERVATION FAILED — not shipping this snapshot")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--state", default="IN", help="2-letter state code (default IN)")
    ap.add_argument("--state-name", default="Indiana",
                    help="full state name as OpenFEMA spells it (default Indiana)")
    ap.add_argument("--out", default=None,
                    help="output path (default data/history_<state>.json)")
    a = ap.parse_args()
    dest = Path(a.out) if a.out else HERE / "data" / f"history_{a.state.lower()}.json"
    build(a.state.upper(), a.state_name, dest)
