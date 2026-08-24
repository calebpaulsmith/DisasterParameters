"""Build **pa_pdas_charta** rows — the Chart A / Table A-sourced companion to
the pre-existing `pa_pdas` table.

`pa_pdas` (EXISTING, NEVER MODIFIED HERE) is applicant x county x PDA grain:
  Year, Month, State, State_Pop, State_Threshold, Declaration_Number, County,
  Met_Threshold, County_Pop, County_Threshold, Applicant_Id,
  SLTT_Organization_Id, Applicant_Name, Cat_A..Cat_G, Total

`pa_pdas` has NO primary-key column, so the link between the two tables rides
on the SHARED natural-key columns, which this module emits with the exact same
names and meanings. Every charta row also carries:

  * ``Pda_Id``    = ``"{Year}-{Month}-{State}"`` (plain concatenation — build
                    the identical calculated column on the pa_pdas side in
                    Power BI: ``[Year] & "-" & [Month] & "-" & [State]`` — and
                    relate the tables 1-column). PDA grain, always present.
  * ``Charta_Id`` = ``"{Pda_Id}-{NNNN}"`` — unique per row (rows sorted by
                    county + applicant before numbering, so re-runs over the
                    same workbook are stable).
  * ``In_Pa_Pdas`` / ``Pa_Pdas_Applicant_Name`` — OPTIONAL row-level link,
                    filled only when a pa_pdas extract is supplied: pa_pdas
                    names were hand-curated (trailing spaces, "City of X" vs
                    "X, City of", multi-county applicants consolidated under
                    County="Multiple"), so this is a best-effort normalized
                    match, never forced. No match is fine — a charta import
                    typically lands BEFORE the pa_pdas row exists.

Dollars come from the **Table A Input Sheet** (the same grain pa_pdas was
built from). Chart A workbooks are OPTIONAL enrichment only — they add the
per-applicant narrative comments, applicant type, and the county's FEMA
inspector, none of which exist anywhere in a Table A. Chart-only applicants
(present in a Chart A but not entered in Table A) are NEVER added as rows
(they may be the same applicant under a different name — adding them could
double-count); they land in the audit instead.

Null convention: pa_pdas stores blank categories as null, not 0 — this module
mirrors that (a 0.0 category cell becomes None; Total is the sum of non-null
categories, itself None when every category is null).

Pure python + the sibling ``chart_a_parser`` module — runs unchanged locally
and inside the Databricks notebook (upload next to ``chart_a_parser.py``).
"""
from __future__ import annotations

import csv
import re
from pathlib import Path
from typing import Any, Iterable, Optional

from chart_a_parser import CATS, ChartA, TableA, county_short

MONTHS = ("January", "February", "March", "April", "May", "June", "July",
          "August", "September", "October", "November", "December")

# pa_pdas-compatible columns first (same names), then the charta-only columns.
COLUMNS = [
    "Charta_Id", "Pda_Id",
    "Year", "Month", "State", "State_Pop", "State_Threshold",
    "Declaration_Number", "County", "Met_Threshold", "County_Pop",
    "County_Threshold", "Applicant_Id", "SLTT_Organization_Id",
    "Applicant_Name",
    "Cat_A", "Cat_B", "Cat_C", "Cat_D", "Cat_E", "Cat_F", "Cat_G", "Total",
    # charta extras (not in pa_pdas)
    "Status", "Applicant_Type", "Comment", "Comment_Html", "Inspector",
    "Source_File", "In_Pa_Pdas", "Pa_Pdas_Applicant_Name",
]

_CIV_RE = re.compile(
    r"^(?P<name>.+?),\s*(?P<kind>city|village|town|township|county|charter township)\s+of\s*$",
    re.I)


def norm_appl_name(s: Any) -> str:
    """Normalized applicant-name join key. Handles the differences observed
    between Table A entries and the hand-curated pa_pdas names: case,
    stray/trailing whitespace, punctuation, and the 'X, City of' <-> 'City of
    X' inversion. Conservative on purpose — order-preserving otherwise."""
    t = " ".join(str(s or "").split()).strip().rstrip(".")
    m = _CIV_RE.match(t)
    if m:
        t = f"{m.group('kind')} of {m.group('name')}"
    t = re.sub(r"[^a-z0-9 &]+", " ", t.lower())
    return " ".join(t.split())


def _strip_county_suffix(name: str, county: str) -> str:
    """Table A disambiguates multi-county applicants as 'X - <County>'
    ('PIE&G - Alcona'); the Chart A row is just 'X'. Strip for matching."""
    n, c = name.strip(), county.strip()
    for suffix in (f" - {c}", f" - {c} County", f" - {c} Co.", f" - {c} Co",
                   f"- {c}", f" – {c}"):
        if c and n.lower().endswith(suffix.lower()):
            return n[: -len(suffix)].strip(" -–")
    return n


def _null_if_zero(v: float) -> Optional[float]:
    return None if not v else round(v, 2)


class _Obj:
    """Attribute view over a dict (the Databricks notebook passes charts as
    to_dict() output; locally they're ChartA/Applicant dataclasses)."""
    def __init__(self, d):
        self.__dict__.update(d)


def _as_chart(ca):
    if isinstance(ca, dict):
        o = _Obj(ca)
        o.applicants = [a if not isinstance(a, dict) else _Obj(a)
                        for a in ca.get("applicants", [])]
        return o
    return ca


def build_charta_rows(ta: TableA,
                      charts: Iterable[ChartA] = (),
                      *,
                      year: int,
                      month: str,
                      state: str,
                      declaration_number: Optional[str] = None,
                      pa_pdas_rows: Optional[list] = None) -> tuple[list, dict]:
    """-> (rows, audit). ``rows`` are dicts keyed by COLUMNS. ``ta`` is the
    parsed Table A (either template generation); ``charts`` optional parsed
    Chart A's for comment/type/inspector enrichment; ``pa_pdas_rows`` an
    optional list of dicts from the existing pa_pdas table/CSV for the
    best-effort row-level link."""
    meta = ta.meta
    state = (state or meta.get("state_code") or "").strip().upper()
    month = str(month).strip()
    year = int(year)
    pda_id = f"{year}-{month}-{state}"

    state_pop = meta.get("state_population")
    state_pci = meta.get("state_pci")
    county_pci = meta.get("county_pci")
    state_threshold = round(state_pop * state_pci, 2) if state_pop and state_pci else None

    # county name -> {population, threshold, entered total} from the Table A
    # per-county table (both formats parse into ta.counties)
    cinfo = {}
    for c in ta.counties:
        pop = c.get("population")
        thr = c.get("county_pci_target") or (
            round(pop * county_pci, 2) if pop and county_pci else None)
        total = c.get("wb_total")
        if total is None:
            total = c.get("total_entered")
        cinfo[county_short(c["county"]).lower()] = {
            "pop": pop, "threshold": thr, "total": total}

    # chart lookup: county -> {normalized applicant -> Applicant}, + inspector
    chart_apps, chart_meta, chart_seen = {}, {}, {}
    for ca in map(_as_chart, charts):
        if ca.entity_type != "county" or not ca.county_key:
            continue
        ck = ca.county_key.lower()
        m = chart_apps.setdefault(ck, {})
        for a in ca.applicants:
            m.setdefault(norm_appl_name(a.applicant), a)
        chart_meta.setdefault(ck, {"inspector": ca.inspector,
                                   "pop": ca.population,
                                   "threshold": ca.county_threshold,
                                   "file": ca.filename})
        chart_seen.setdefault(ck, set())
        # county gap check data (chart county not in Table A handled in audit)
        if ck not in cinfo and ca.population:
            thr = ca.county_threshold or (
                round(ca.population * county_pci, 2) if county_pci else None)
            cinfo[ck] = {"pop": ca.population, "threshold": thr, "total": None}

    # pa_pdas link index (optional): (county-lower OR 'multiple', norm name)
    link = {}
    for r in (pa_pdas_rows or []):
        if (str(r.get("Year", "")).strip() != str(year)
                or str(r.get("Month", "")).strip().lower() != month.lower()
                or str(r.get("State", "")).strip().upper() != state):
            continue
        cty = str(r.get("County", "")).strip().lower()
        link[(cty, norm_appl_name(r.get("Applicant_Name")))] = r["Applicant_Name"]

    def find_link(county: str, names: list) -> Optional[str]:
        cl = county.strip().lower()
        for nm in names:
            k = norm_appl_name(nm)
            for cc in (cl, "multiple"):
                if (cc, k) in link:
                    return link[(cc, k)]
        return None

    rows = []
    subs = sorted(ta.subrecipients,
                  key=lambda s: (s["county"].lower(), s["subrecipient"].lower()))
    for s in subs:
        county = county_short(s["county"]) or s["county"]
        ck = county.lower()
        ci = cinfo.get(ck, {})
        thr, ctot = ci.get("threshold"), ci.get("total")
        met = (ctot >= thr) if (thr and ctot is not None) else None
        cats = {c: _null_if_zero(s[f"cat_{c.lower()}"]) for c in CATS}
        nonnull = [v for v in cats.values() if v is not None]
        stripped = _strip_county_suffix(s["subrecipient"], county)
        capp = chart_apps.get(ck, {}).get(norm_appl_name(s["subrecipient"])) \
            or chart_apps.get(ck, {}).get(norm_appl_name(stripped))
        if capp is not None:
            chart_seen.setdefault(ck, set()).add(norm_appl_name(capp.applicant))
        rows.append({
            "Charta_Id": None,  # numbered below
            "Pda_Id": pda_id,
            "Year": year, "Month": month, "State": state,
            "State_Pop": state_pop, "State_Threshold": state_threshold,
            "Declaration_Number": (str(declaration_number).strip() or None)
                                  if declaration_number else None,
            "County": county, "Met_Threshold": met,
            "County_Pop": ci.get("pop"), "County_Threshold": thr,
            "Applicant_Id": None, "SLTT_Organization_Id": None,
            "Applicant_Name": s["subrecipient"],
            **{f"Cat_{c}": cats[c] for c in CATS},
            "Total": round(sum(nonnull), 2) if nonnull else None,
            "Status": s.get("status") or None,
            "Applicant_Type": (capp.applicant_type or None) if capp else None,
            "Comment": (capp.comment or None) if capp else None,
            "Comment_Html": (capp.comment_html or None) if capp else None,
            "Inspector": chart_meta.get(ck, {}).get("inspector"),
            "Source_File": ta.filename,
            "In_Pa_Pdas": None, "Pa_Pdas_Applicant_Name": None,
        })

    for i, r in enumerate(rows, 1):
        r["Charta_Id"] = f"{pda_id}-{i:04d}"
        if pa_pdas_rows is not None:
            hit = find_link(r["County"], [r["Applicant_Name"],
                            _strip_county_suffix(r["Applicant_Name"], r["County"])])
            r["In_Pa_Pdas"] = hit is not None
            r["Pa_Pdas_Applicant_Name"] = hit

    # ---- audit: dollars conserved + nothing silently dropped
    row_total = round(sum(r["Total"] or 0 for r in rows), 2)
    sub_total = round(sum(s["total_calc"] for s in ta.subrecipients), 2)
    cty_total = round(sum(ci["total"] or 0 for ci in cinfo.values()), 2)
    unmatched_chart = []
    for ck, m in chart_apps.items():
        seen = chart_seen.get(ck, set())
        for k, a in m.items():
            if k not in seen and a.total_calc:
                unmatched_chart.append(
                    {"county": ck, "applicant": a.applicant,
                     "total": a.total_calc,
                     "detail": "in Chart A but no Table A row matched "
                               "(NOT added as a row — could double-count)"})
    audit = {
        "pda_id": pda_id, "n_rows": len(rows),
        "row_total": row_total, "subrecipient_total": sub_total,
        "conserved": abs(row_total - sub_total) < 0.01,
        "county_table_total": cty_total,
        "n_counties": len({r["County"] for r in rows}),
        "n_met": len({r["County"] for r in rows if r["Met_Threshold"]}),
        "n_comment": sum(1 for r in rows if r["Comment"]),
        "n_linked": sum(1 for r in rows if r["In_Pa_Pdas"]),
        "linkable": pa_pdas_rows is not None,
        "unmatched_chart_applicants": unmatched_chart,
    }
    # tolerance: category cells are rounded to cents per row before summing,
    # so allow up to half a cent of drift per row
    audit["conserved"] = abs(row_total - sub_total) <= max(0.01, 0.005 * len(rows))
    if not audit["conserved"]:
        raise RuntimeError(
            f"DOLLAR CONSERVATION FAILED: charta rows ${row_total:,.2f} != "
            f"Table A subrecipients ${sub_total:,.2f}")
    return rows, audit


def read_pa_pdas_csv(path) -> list:
    """Existing pa_pdas extract -> list of dicts (headers stripped — the CSV
    export carries stray spaces like ' State_Threshold')."""
    with open(path, newline="", encoding="utf-8-sig") as fh:
        rdr = csv.reader(fh)
        hdr = [h.strip() for h in next(rdr)]
        return [dict(zip(hdr, row)) for row in rdr]


def write_charta_csv(rows: list, path) -> None:
    """Power BI-ready CSV: header row = COLUMNS, empty cell for null (typed
    columns import clean — no 'null' literals)."""
    with open(path, "w", newline="", encoding="utf-8-sig") as fh:
        w = csv.writer(fh)
        w.writerow(COLUMNS)
        for r in rows:
            w.writerow(["" if r[c] is None else r[c] for c in COLUMNS])


# ---------------------------------------------------------------- CLI
if __name__ == "__main__":
    import argparse
    import glob as _glob
    import warnings

    from chart_a_parser import parse_chart_a, parse_table_a, sniff_workbook

    warnings.filterwarnings("ignore", module="openpyxl")
    ap = argparse.ArgumentParser(description="Table A (+ optional Chart A's) -> pa_pdas_charta CSV")
    ap.add_argument("folder", help="folder holding the Table A (and optionally Chart A's)")
    ap.add_argument("--year", required=True, type=int)
    ap.add_argument("--month", required=True, help='e.g. "May" (as pa_pdas spells it)')
    ap.add_argument("--state", default=None, help="2-letter; default from Table A")
    ap.add_argument("--dn", default=None, help="Declaration_Number if known")
    ap.add_argument("--pa-pdas", default=None, help="pa_pdas CSV extract for the row-level link")
    ap.add_argument("--out", default=None, help="output CSV (default pa_pdas_charta_<Pda_Id>.csv)")
    args = ap.parse_args()

    tables, charts = [], []
    for f in _glob.glob(str(Path(args.folder) / "**" / "*.xlsx"), recursive=True):
        if Path(f).name.startswith("~$"):
            continue
        kind = sniff_workbook(f)
        if kind == "table_a":
            tables.append(f)
        elif kind == "chart_a":
            charts.append(parse_chart_a(f))
    if not tables:
        raise SystemExit(f"no Table A workbook found under {args.folder}")
    if len(tables) > 1:
        print("multiple Table A workbooks found — using the largest "
              "(pass a tighter folder to override):")
        for t in tables:
            print("  ", t)
        tables.sort(key=lambda p: Path(p).stat().st_size, reverse=True)
    ta = parse_table_a(tables[0])

    pa_rows = read_pa_pdas_csv(args.pa_pdas) if args.pa_pdas else None
    rows, audit = build_charta_rows(
        ta, charts, year=args.year, month=args.month,
        state=args.state or ta.meta.get("state_code"),
        declaration_number=args.dn, pa_pdas_rows=pa_rows)
    out = args.out or f"pa_pdas_charta_{audit['pda_id']}.csv"
    write_charta_csv(rows, out)
    print(f"wrote {out}: {audit['n_rows']} rows, ${audit['row_total']:,.2f} "
          f"({audit['n_counties']} counties, {audit['n_met']} met threshold, "
          f"{audit['n_comment']} with comments"
          + (f", {audit['n_linked']} linked to pa_pdas" if audit["linkable"] else "")
          + ")")
    for u in audit["unmatched_chart_applicants"]:
        print(f"  NOTE chart-only applicant not in Table A: {u['county']}: "
              f"{u['applicant']} (${u['total']:,.2f})")
