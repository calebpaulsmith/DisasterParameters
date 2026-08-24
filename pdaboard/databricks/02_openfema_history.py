# Databricks notebook source
# MAGIC %md
# MAGIC # 02 — OpenFEMA prior-history → catalog tables + `history_<state>.json`
# MAGIC
# MAGIC The Databricks port of `pdaboard/build_history.py`. Same math, different
# MAGIC source: instead of hitting the public OpenFEMA API, this reads the
# MAGIC workspace's **catalog copies** of the two OpenFEMA datasets and produces
# MAGIC
# MAGIC 1. flat Delta tables (`hist_*`) for the board app / Power BI, and
# MAGIC 2. `history_<state>.json` written to the volume — the EXACT structure the
# MAGIC    board template already consumes (`pipeline.load_history()`), so the
# MAGIC    Chart A explorer's Prior FEMA history card works unchanged.
# MAGIC
# MAGIC **Source datasets** (point the widgets at your catalog's copies):
# MAGIC
# MAGIC | logical dataset | OpenFEMA original (provenance) | grain |
# MAGIC |---|---|---|
# MAGIC | PA applicant history | `PublicAssistanceFundedProjectsSummaries` v1 | applicant × county × disaster, **federal share obligated** |
# MAGIC | Declarations | `DisasterDeclarationsSummaries` v2 | disaster × designated area |
# MAGIC
# MAGIC **Rules that MUST hold** (identical to the local builder — do not relax):
# MAGIC - PA dollars are FEDERAL SHARE OBLIGATED — not project cost, not paid.
# MAGIC - COVID-19 (`incidentType = 'Biological'`) is EXCLUDED from both pulls.
# MAGIC - Summaries' `county` is a NAME ("Marion", "Statewide", sometimes blank);
# MAGIC   declarations carry real FIPS. Rows that don't resolve land in the
# MAGIC   `statewide` or `unmatched` bucket — **dollars are conserved, never
# MAGIC   dropped**, and the run FAILS (keeping the last good output) if
# MAGIC   matched + statewide + unmatched + covid ≠ total.
# MAGIC - Multiple declaration rows per (disaster, county): OR the program flags,
# MAGIC   take the earliest declarationDate.
# MAGIC - Context only, never the hero — the board labels it as a snapshot.

# COMMAND ----------

dbutils.widgets.text("catalog", "recovery", "Output catalog")
dbutils.widgets.text("schema", "pda_ops", "Output schema")
dbutils.widgets.text("pa_summaries_table",
                     "openfema.public.public_assistance_funded_projects_summaries",
                     "Catalog table: PublicAssistanceFundedProjectsSummaries")
dbutils.widgets.text("declarations_table",
                     "openfema.public.disaster_declarations_summaries",
                     "Catalog table: DisasterDeclarationsSummaries")
dbutils.widgets.text("state", "IN", "State (2-letter)")
dbutils.widgets.text("state_name", "Indiana", "State name as OpenFEMA spells it")
dbutils.widgets.text("history_out",
                     "/Volumes/recovery/pda_ops/pda_inbox/IN_PDA_July_2026/_ref",
                     "Volume folder for history_<state>.json ('' = skip JSON)")

CATALOG = dbutils.widgets.get("catalog").strip()
SCHEMA = dbutils.widgets.get("schema").strip()
T_SUMMARIES = dbutils.widgets.get("pa_summaries_table").strip()
T_DECLS = dbutils.widgets.get("declarations_table").strip()
STATE = dbutils.widgets.get("state").strip().upper()
STATE_NAME = dbutils.widgets.get("state_name").strip()
HISTORY_OUT = dbutils.widgets.get("history_out").strip().rstrip("/")

spark.sql(f"CREATE SCHEMA IF NOT EXISTS {CATALOG}.{SCHEMA}")

# Provenance: the public API queries this catalog data mirrors (kept in the
# output so every figure stays traceable back to OpenFEMA).
API_QUERIES = [
    {"name": "pa_applicants",
     "dataset": "PublicAssistanceFundedProjectsSummaries", "version": "v1",
     "grain": "applicant x county x disaster",
     "url": ("https://www.fema.gov/api/open/v1/PublicAssistanceFundedProjectsSummaries"
             f"?$filter=state eq '{STATE_NAME}'"
             "&$orderby=id&$top=1000&$skip={skip}&$inlinecount=allpages"),
     "notes": "Served from the workspace catalog copy (table below), not the "
              "public API. federalObligatedAmount = FEDERAL share obligated. "
              "county is a NAME ('Marion', 'Statewide', or blank).",
     "table": T_SUMMARIES},
    {"name": "declarations",
     "dataset": "DisasterDeclarationsSummaries", "version": "v2",
     "grain": "disaster x designated area",
     "url": ("https://www.fema.gov/api/open/v2/DisasterDeclarationsSummaries"
             f"?$filter=state eq '{STATE}'"
             "&$orderby=id&$top=1000&$skip={skip}&$inlinecount=allpages"),
     "notes": "Served from the workspace catalog copy (table below). "
              "fipsCountyCode '000' = statewide designation. Program flags OR'd "
              "across rows; earliest declarationDate wins. incidentType "
              "'Biological' (COVID-19) excluded.",
     "table": T_DECLS},
]

# COMMAND ----------

# MAGIC %md
# MAGIC ## Read the catalog copies (schema-tolerant: camelCase or snake_case)

# COMMAND ----------

from datetime import datetime, timezone

FETCHED_AT = datetime.now(timezone.utc).isoformat(timespec="seconds")

def resolve_cols(df, wanted):
    """Map OpenFEMA field names onto whatever this catalog copy calls them
    (disasterNumber == disaster_number == disasternumber). Fails loudly on a
    missing REQUIRED column instead of silently miscounting."""
    have = {c.lower().replace("_", ""): c for c in df.columns}
    out, missing = {}, []
    for w, required in wanted:
        c = have.get(w.lower().replace("_", ""))
        if c is None and required:
            missing.append(w)
        out[w] = c
    if missing:
        raise KeyError(f"{missing} not found in columns {sorted(df.columns)}")
    return out

def rows_as_dicts(df, colmap):
    sel = [c for c in colmap.values() if c]
    inv = {v: k for k, v in colmap.items() if v}
    return [{inv[k]: v for k, v in r.asDict().items()} for r in df.select(*sel).collect()]

def _s(v):
    return str(v).strip() if v not in (None, "") else ""

def _date10(v):
    """datetime/date/ISO-string -> 'YYYY-MM-DD' (or None)."""
    if v in (None, ""):
        return None
    if hasattr(v, "strftime"):
        return v.strftime("%Y-%m-%d")
    return _s(v)[:10] or None

def _b(v):
    if isinstance(v, bool):
        return v
    if v in (None, ""):
        return False
    return _s(v).lower() in ("true", "1", "t", "yes", "y")

# declarations
ddf = spark.table(T_DECLS)
dcols = resolve_cols(ddf, [
    ("disasterNumber", True), ("state", True), ("declarationType", True),
    ("declarationTitle", True), ("incidentType", True), ("declarationDate", True),
    ("incidentBeginDate", False), ("incidentEndDate", False),
    ("fipsStateCode", True), ("fipsCountyCode", True), ("designatedArea", True),
    ("iaProgramDeclared", False), ("ihProgramDeclared", False),
    ("paProgramDeclared", False), ("hmProgramDeclared", False),
])
decls = rows_as_dicts(ddf.where(ddf[dcols["state"]] == STATE), dcols)

# PA summaries — OpenFEMA spells state as the FULL NAME in this dataset
sdf = spark.table(T_SUMMARIES)
scols = resolve_cols(sdf, [
    ("disasterNumber", True), ("state", True), ("county", True),
    ("applicantName", True), ("educationApplicant", False),
    ("numberOfProjects", False), ("federalObligatedAmount", True),
])
summaries = rows_as_dicts(sdf.where(sdf[scols["state"]] == STATE_NAME), scols)

print(f"{len(decls)} declaration rows ({STATE}), {len(summaries)} PA summary "
      f"rows ({STATE_NAME})")
if not decls or not summaries:
    raise RuntimeError("A source pull came back empty — check the table widgets "
                       "and the state / state_name spellings.")

# COMMAND ----------

# MAGIC %md
# MAGIC ## County dim (name → FIPS)
# MAGIC Prefers `<catalog>.<schema>.dim_county`; else derives it from the
# MAGIC declarations' own `designatedArea` + FIPS columns (covers every county the
# MAGIC state has ever had designated — for IN that is all 92).

# COMMAND ----------

def norm_county(name):
    n = _s(name).lower()
    for suf in (" (county)", " county"):
        if n.endswith(suf):
            n = n[: -len(suf)].strip()
    return n

dim = {}   # norm name -> {"fips","name"}
try:
    for r in spark.table(f"{CATALOG}.{SCHEMA}.dim_county").collect():
        d = r.asDict()
        dim[norm_county(d.get("name"))] = {"fips": _s(d.get("fips")),
                                           "name": _s(d.get("name"))}
    dim_source = f"{CATALOG}.{SCHEMA}.dim_county"
except Exception:
    for d in decls:
        cc = _s(d.get("fipsCountyCode")).zfill(3)
        area = _s(d.get("designatedArea"))
        if cc == "000" or not area or "(county)" not in area.lower():
            continue  # statewide rows + reservations/parishes stay out of the dim
        name = norm_county(area).title()
        fips = _s(d.get("fipsStateCode")).zfill(2) + cc
        dim.setdefault(norm_county(area), {"fips": fips, "name": name})
    dim_source = f"derived from {T_DECLS} designatedArea"
print(f"dim: {len(dim)} counties ({dim_source})")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Build the history model (straight port of `build_history.py`)

# COMMAND ----------

# ---- disaster meta + COVID exclusion (Biological) ------------------------
covid_dns = {d["disasterNumber"] for d in decls
             if _s(d.get("incidentType")).lower() == "biological"}
dis_meta = {}
for d in decls:
    dn = d["disasterNumber"]
    if dn in covid_dns:
        continue
    m = dis_meta.setdefault(dn, {
        "dn": dn, "type": _s(d.get("declarationType")) or None,
        "title": _s(d.get("declarationTitle")).title(),
        "incidentType": _s(d.get("incidentType")) or None,
        "declared": _date10(d.get("declarationDate")) or "",
        "began": _date10(d.get("incidentBeginDate")),
        "ended": _date10(d.get("incidentEndDate")),
    })
    dd = _date10(d.get("declarationDate"))
    if dd and (not m["declared"] or dd < m["declared"]):
        m["declared"] = dd     # earliest wins (amendments repeat rows)

# ---- per-county designations (timeline spine) ----------------------------
desig, statewide_desig = {}, {}
n_cty_rows = n_sw_rows = 0
for d in decls:
    dn = d["disasterNumber"]
    if dn in covid_dns:
        continue
    cc = _s(d.get("fipsCountyCode")).zfill(3)
    flags = {"ia": _b(d.get("iaProgramDeclared")) or _b(d.get("ihProgramDeclared")),
             "pa": _b(d.get("paProgramDeclared")),
             "hm": _b(d.get("hmProgramDeclared"))}
    if cc == "000":
        n_sw_rows += 1
        e = statewide_desig.setdefault(dn, {"dn": dn,
                                            "area": _s(d.get("designatedArea")) or None,
                                            "ia": False, "pa": False, "hm": False})
    else:
        n_cty_rows += 1
        fips = _s(d.get("fipsStateCode")).zfill(2) + cc
        e = desig.setdefault((dn, fips), {"ia": False, "pa": False, "hm": False})
    for k in ("ia", "pa", "hm"):
        e[k] = e[k] or flags[k]

# ---- applicant rollup (applicant x county x disaster) --------------------
per_cty_apps, per_cty_dn = {}, {}
sw_apps, unmatched = {}, {}
applicant_disaster_rows = []   # flat grain for the hist_applicant_disaster table
tot = {"rows": 0, "pa": 0.0, "matched": 0.0, "statewide": 0.0,
       "unmatched": 0.0, "covid": 0.0}
for r in summaries:
    dn = r.get("disasterNumber")
    pa = float(r.get("federalObligatedAmount") or 0)
    projects = int(r.get("numberOfProjects") or 0)
    name = _s(r.get("applicantName")) or "(unnamed applicant)"
    tot["rows"] += 1
    tot["pa"] += pa
    if dn in covid_dns:
        tot["covid"] += pa
        continue
    cty = norm_county(r.get("county"))
    hit = dim.get(cty)
    if hit:
        tot["matched"] += pa
        bucket_name, fips = "county", hit["fips"]
        a = per_cty_apps.setdefault(fips, {}).setdefault(
            name, {"name": name, "pa": 0.0, "projects": 0,
                   "edu": _b(r.get("educationApplicant")), "disasters": {}})
        g = per_cty_dn.setdefault((fips, dn), {"apps": set(), "pa": 0.0, "projects": 0})
        g["apps"].add(name)
        g["pa"] += pa
        g["projects"] += projects
    else:
        b = sw_apps if cty in ("statewide", "") else unmatched
        bucket_name = "statewide" if b is sw_apps else "unmatched"
        fips = None
        tot[bucket_name] += pa
        a = b.setdefault(name, {"name": name, "pa": 0.0, "projects": 0,
                                "county": r.get("county"), "disasters": {}})
    a["pa"] += pa
    a["projects"] += projects
    ad = a["disasters"].setdefault(dn, {"dn": dn, "pa": 0.0, "projects": 0})
    ad["pa"] += pa
    ad["projects"] += projects
    applicant_disaster_rows.append({
        "state": STATE, "bucket": bucket_name, "fips": fips,
        "county_raw": _s(r.get("county")) or None, "applicant": name,
        "education_applicant": _b(r.get("educationApplicant")),
        "disaster_number": int(dn), "pa_obligated": round(pa, 2),
        "projects": projects, "fetched_at": FETCHED_AT})

# ---- CONSERVATION GATE: fail before writing anything ---------------------
check = round(tot["matched"] + tot["statewide"] + tot["unmatched"]
              + tot["covid"] - tot["pa"], 2)
print(f"PA conserved: matched {tot['matched']:,.0f} + statewide "
      f"{tot['statewide']:,.0f} + unmatched {tot['unmatched']:,.0f} + covid "
      f"{tot['covid']:,.0f} == total {tot['pa']:,.0f} (residual {check})")
if check != 0:
    raise RuntimeError("DOLLAR CONSERVATION FAILED — refusing to write; the "
                       "last good tables/JSON stay in place")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Assemble the board JSON (same shape as `build_history.py`)

# COMMAND ----------

def _apps_out(d):
    out = []
    for a in d.values():
        a = dict(a)
        a["pa"] = round(a["pa"], 2)
        a["disasters"] = sorted(
            ({**v, "pa": round(v["pa"], 2)} for v in a["disasters"].values()),
            key=lambda x: x["dn"])
        out.append(a)
    return sorted(out, key=lambda x: -x["pa"])

counties = {}
county_decl_rows = []   # flat grain for the hist_county_declarations table
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
    # (Summaries' county attribution can differ) — keep them, flagged
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
    for dd in dlist:
        county_decl_rows.append({
            "state": STATE, "fips": fips, "county": cname,
            "disaster_number": int(dd["dn"]), "declaration_type": dd["type"],
            "title": dd["title"], "incident_type": dd["incidentType"],
            "declared": dd["declared"] or None, "began": dd["began"],
            "ended": dd["ended"], "ia": dd["ia"], "pa": dd["pa"], "hm": dd["hm"],
            "undesignated": bool(dd.get("undesignated")),
            "applicants": dd["applicants"], "pa_obligated": dd["paObligated"],
            "projects": dd["projects"], "fetched_at": FETCHED_AT})

history = {
    "state": STATE, "stateName": STATE_NAME,
    "fetchedAt": FETCHED_AT,
    "source": ("OpenFEMA via the workspace catalog "
               f"({T_SUMMARIES}; {T_DECLS}) — snapshot, not live"),
    "covidExcluded": True,
    "queries": API_QUERIES,
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
                      "unmatchedCounties": sorted({_s(a.get("county"))
                                                   for a in unmatched.values()})},
        "declarations": {"rows": len(decls), "disasters": len(dis_meta),
                         "covidDisastersExcluded": sorted(covid_dns),
                         "countyDesignationRows": n_cty_rows,
                         "statewideDesignationRows": n_sw_rows},
    },
}
if unmatched:
    history["unmatchedApplicants"] = _apps_out(unmatched)
print(f"{len(counties)} counties, {len(dis_meta)} disasters, "
      f"{len(covid_dns)} COVID disasters excluded")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Write outputs — Delta tables + the board JSON

# COMMAND ----------

import json

def write_table(name, rows, ddl, comment=None):
    full = f"{CATALOG}.{SCHEMA}.{name}"
    df = spark.createDataFrame(rows, schema=ddl)
    (df.write.format("delta").mode("overwrite")
       .option("overwriteSchema", "true").saveAsTable(full))
    if comment:
        spark.sql(f"COMMENT ON TABLE {full} IS '{comment.replace(chr(39), chr(39)*2)}'")
    print(f"  {full}: {len(rows)} rows")

write_table("hist_disasters",
    [{"state": STATE, **m, "covid_excluded_set": False, "fetched_at": FETCHED_AT}
     for m in dis_meta.values()],
    "state string, dn int, type string, title string, incidentType string, "
    "declared string, began string, ended string, covid_excluded_set boolean, "
    "fetched_at string",
    comment="One row per non-COVID disaster declared in the state "
            "(DisasterDeclarationsSummaries v2; earliest declarationDate).")

write_table("hist_county_declarations", county_decl_rows,
    "state string, fips string, county string, disaster_number int, "
    "declaration_type string, title string, incident_type string, "
    "declared string, began string, ended string, ia boolean, pa boolean, "
    "hm boolean, undesignated boolean, applicants int, pa_obligated double, "
    "projects int, fetched_at string",
    comment="County x disaster timeline: designation flags (IA/PA/HM OR'd "
            "across rows) + that county's PA applicants/federal obligated/"
            "projects. undesignated = PA dollars attributed to a county the "
            "disaster never designated (kept, never dropped). COVID excluded.")

write_table("hist_statewide_designations",
    [{"state": STATE, **d, "fetched_at": FETCHED_AT}
     for d in statewide_desig.values()],
    "state string, dn int, area string, ia boolean, pa boolean, hm boolean, "
    "fetched_at string",
    comment="Statewide (fipsCountyCode 000) designation rows.")

write_table("hist_applicant_disaster", applicant_disaster_rows,
    "state string, bucket string, fips string, county_raw string, "
    "applicant string, education_applicant boolean, disaster_number int, "
    "pa_obligated double, projects int, fetched_at string",
    comment="Applicant x county x disaster PA history (federal share "
            "obligated), bucketed county/statewide/unmatched so every dollar "
            "lands somewhere — sum(pa_obligated) + the audit covid figure "
            "reconciles to the source total. COVID excluded from buckets.")

audit_s, audit_d = history["audit"]["summaries"], history["audit"]["declarations"]
write_table("hist_audit", [{
    "state": STATE, "fetched_at": FETCHED_AT,
    "summary_rows": audit_s["rows"], "pa_total": audit_s["paTotal"],
    "pa_matched": audit_s["paMatchedToCounty"],
    "pa_statewide": audit_s["paStatewide"],
    "pa_unmatched": audit_s["paUnmatched"],
    "pa_covid_excluded": audit_s["paCovidExcluded"],
    "conservation_residual": audit_s["conservationResidual"],
    "unmatched_counties": ", ".join(audit_s["unmatchedCounties"]),
    "declaration_rows": audit_d["rows"], "disasters": audit_d["disasters"],
    "covid_disasters_excluded": ", ".join(str(x) for x in
                                          audit_d["covidDisastersExcluded"]),
    "county_designation_rows": audit_d["countyDesignationRows"],
    "statewide_designation_rows": audit_d["statewideDesignationRows"],
    "dim_source": dim_source,
    "source_tables": f"{T_SUMMARIES}; {T_DECLS}"}],
    "state string, fetched_at string, summary_rows long, pa_total double, "
    "pa_matched double, pa_statewide double, pa_unmatched double, "
    "pa_covid_excluded double, conservation_residual double, "
    "unmatched_counties string, declaration_rows long, disasters long, "
    "covid_disasters_excluded string, county_designation_rows long, "
    "statewide_designation_rows long, dim_source string, source_tables string",
    comment="Dollar-conservation audit for the hist_* refresh: matched + "
            "statewide + unmatched + covid must equal pa_total (residual 0, "
            "enforced — the notebook fails rather than write a broken snapshot).")

if HISTORY_OUT:
    import os
    os.makedirs(HISTORY_OUT, exist_ok=True)
    jpath = f"{HISTORY_OUT}/history_{STATE.lower()}.json"
    with open(jpath, "w", encoding="utf-8") as f:
        json.dump(history, f)
    print(f"  {jpath}: {os.path.getsize(jpath) // 1024} KB "
          "(board-ready — pipeline.load_history() reads this unchanged)")
else:
    print("  history JSON skipped (history_out widget is blank)")

print(f"\nDONE {FETCHED_AT}")
