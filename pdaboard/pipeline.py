"""PDA Board pipeline: drop folder -> gold tables -> board.html.

Local CLI today; the same steps become the Databricks job (01 register ->
02 parse -> 03 model) with the volume as the drop folder.

  python pipeline.py --drop PDAExamples --manifest manifest.json --out out

Stages (the four-type validation model — see sp_filetree.STAGE_LABELS):
  1 Working (county files) . 2 For PDA Lead Review . 3 Ready for Table A .
  4 Entered in Table A  (0 = Not started: county in scope, no Chart A found)

Canonical-record rule for a county x event with several Chart A copies:
highest stage wins; tie -> latest modified. Every non-canonical copy stays in
the output with is_canonical=False. SharePoint stage (via the query.xlsx
match) beats the local drop folder; local folders are the fallback.
"""
from __future__ import annotations

import argparse
import csv
import json
import time
from datetime import datetime
from pathlib import Path

from chart_a_parser import (
    parse_chart_a, parse_table_a, sniff_workbook, norm_status,
    county_from_filename, county_short, event_label_from_filename, event_key, CATS,
)
import sp_filetree as sp

HERE = Path(__file__).resolve().parent

# fuzzy county join key — every county↔county join in the build goes through
# this (folder names are hand-typed in SharePoint; workbook cells are the
# identity), so 'St Joseph' folders attach to the workbook's 'St. Joseph'
ckey = sp.norm_county_name


# ---------------------------------------------------------------- utilities

def log(msg):
    print(f"[pda] {msg}")


def load_manifest(path: Path) -> dict:
    m = json.loads(path.read_text(encoding="utf-8"))
    for ev in m.get("events", []):
        ev["key"] = event_key(ev["label"])
    return m


def load_dim_county(path: Path) -> dict:
    out = {}
    with open(path, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            row["population"] = int(row["population"])
            row["lat"], row["lon"] = float(row["lat"]), float(row["lon"])
            out[sp.norm_county_name(row["name"])] = row
    return out


def find_query_xlsx(drop: Path):
    hits = sorted(drop.rglob("query*.xlsx"), key=lambda p: p.stat().st_mtime, reverse=True)
    return hits[0] if hits else None


def choose_pda_root(ftree: list, manifest: dict, sp_folder: str = "") -> tuple:
    """Narrow a MASTER (library-wide) export to THIS PDA's folder.

    Returns ``(root_path|None, candidates)``. Order: an explicit ``sp_folder``
    (manifest key / ``--sp-folder``) -> the only candidate -> a token match on
    the PDA's own identity (state + month + year). Several plausible folders
    and no match -> ``None``, and the caller flags it instead of guessing.
    """
    cands = sp.pda_root_candidates(ftree)
    if not cands:
        return None, []
    want = (sp_folder or manifest.get("sp_folder") or "").strip("/ ").lower()
    if want:
        hit = [c for c in cands
               if c.rsplit("/", 1)[-1].lower() == want or c.lower().endswith("/" + want)]
        if hit:
            return hit[0], cands
    if len(cands) == 1:
        return cands[0], cands
    return sp.match_pda_folder(cands, manifest), cands


def resolve_links(drop: Path, manifest: dict, ftree: list, iqy_path: Path | None = None,
                  pda_root: str | None = None, sp_folder: str = "",
                  pda_candidates: list | None = None) -> dict:
    """The PDA's SharePoint links: site base + the county-folder base.

    Order of trust, per field: the manifest (an explicit override) -> the
    ``query.xlsx`` export (server-relative paths, so it fixes the FOLDERS but
    never the host) -> ``query*.iqy`` (the only file that carries the host).
    Nothing is invented: a field with no source stays empty and the board says
    so. ``master_folder_assumed`` marks the case where the counties folder was
    taken from the Region 5 convention rather than seen in an export.

    The board can re-derive all of this in the browser from a dropped .iqy —
    this is the same logic, run at build time so a baked board ships with
    working links.
    """
    iq = {}
    if iqy_path is None:
        iqy_path = sp.find_query_iqy(drop)
    if iqy_path is not None:
        iq = sp.load_iqy(iqy_path)
        log(f"links: {iqy_path.name} -> {iq.get('root_name') or iq.get('host')}")

    base = (manifest.get("sharepoint_base") or iq.get("sharepoint_base") or "").rstrip("/")

    # The .iqy may be a MASTER query rooted above the PDAs ("Ongoing PDA's").
    # Then its root is only useful once this PDA's folder is named — by the
    # export (pda_root), by sp_folder, or by the lead in the board's picker.
    want_folder = (sp_folder or manifest.get("sp_folder") or "").strip("/ ")
    iq_root, master_root = iq.get("root_path"), None
    if iq_root and not pda_root:
        if want_folder and not iq_root.lower().endswith("/" + want_folder.lower()):
            master_root, iq_root = iq_root, f"{iq_root}/{want_folder}"
        elif (sp.pda_identity_tokens(manifest)
              and not sp.looks_like_pda_folder(iq_root.rsplit("/", 1)[-1], manifest)):
            # the root names some other folder ("Ongoing PDA's") — a library-wide
            # query. With no identity to judge by, take the root at face value.
            master_root, iq_root = iq_root, None      # parent root, PDA unknown

    root_path = pda_root or sp.root_path_from_rows(ftree) or iq_root
    root_url = f"{base}{sp.sp_quote(root_path)}" if base and root_path else None

    counties_path = sp.counties_path_from_rows(ftree)
    if counties_path and root_path and not counties_path.lower().startswith(root_path.lower() + "/"):
        counties_path = None            # belongs to a different PDA in a master export
    assumed = False
    if manifest.get("master_folder"):
        master = manifest["master_folder"].rstrip("/")
    elif base and counties_path:
        master = f"{base}{sp.sp_quote(counties_path)}"
    elif root_url:
        master = f"{root_url}/{sp.sp_quote(sp.COUNTY_SUBPATH)}"
        assumed = True
    else:
        master = ""

    return {
        "sharepoint_base": base,
        "master_folder": master,
        "master_folder_assumed": assumed,
        "sp_root_url": root_url,
        # server-relative paths, so the board can recompose the links itself
        # when an admin swaps in another PDA's .iqy (different host or root)
        "root_path": root_path,
        "counties_path": counties_path,
        "county_subpath": sp.COUNTY_SUBPATH,
        "root_name": (root_path.rsplit("/", 1)[-1] if root_path else None),
        # a library-wide (master) query: the parent, plus the PDA folder names
        # seen under it — the board's "PDA folder" picker
        "master_root_path": master_root,
        "pda_folder": (root_path.rsplit("/", 1)[-1]
                       if (root_path and master_root) else (want_folder or None)),
        # every PDA the export saw — the board's picker offers these. Passed in
        # from build() PRE-filter, so a master export still lists its siblings.
        "pda_candidates": [c.rsplit("/", 1)[-1] for c in
                           (pda_candidates if pda_candidates is not None
                            else sp.pda_root_candidates(ftree))],
        "source": (iqy_path.name if iqy_path is not None and not manifest.get("sharepoint_base")
                   else ("manifest" if manifest.get("sharepoint_base") else None)),
    }


# ---------------------------------------------------------------- history (context layer)

def load_history(path: Path | None, scope_fips: set) -> tuple:
    """Prior FEMA history per county from the STATIC OpenFEMA snapshot
    (data/history_<state>.json, built by build_history.py — a direct OpenFEMA
    pull frozen on disk; the board itself makes no network calls). Only scope
    counties are embedded, keeping board.html lean. Context only — never the
    hero. Missing snapshot -> empty context, no failure."""
    if not path or not path.exists():
        return {}, None
    snap = json.loads(path.read_text(encoding="utf-8"))
    hist = {}
    for fips, c in (snap.get("counties") or {}).items():
        if scope_fips and fips not in scope_fips:
            continue
        apps = c.get("applicants") or []
        hist[fips] = {
            "declarations": len(c.get("disasters") or []),
            "paObligated": round(sum(a.get("pa") or 0 for a in apps), 2),
            "priorApplicants": len(apps),
            "disasters": c.get("disasters") or [],
            "applicants": apps,
        }
    meta = {"fetchedAt": snap.get("fetchedAt"), "source": snap.get("source"),
            "covidExcluded": bool(snap.get("covidExcluded")),
            "state": snap.get("state"), "queries": snap.get("queries") or []}
    return hist, meta


# ---------------------------------------------------------------- core build

def build(drop: Path, manifest: dict, out: Path, history_path: Path | None = None,
          iqy_path: Path | None = None, sp_folder: str = ""):
    t0 = time.time()
    out.mkdir(parents=True, exist_ok=True)
    run_ts = datetime.now().isoformat(timespec="seconds")

    # COMPLETE mode: a finished PDA — everything is final/Entered, the clock
    # shows only the outcome tiers, and the county table swaps Stage/% for
    # Applicants + a county-folder link (see templates/board.html).
    complete = bool(manifest.get("complete"))

    st = (manifest.get("state") or "in").lower()
    dim = load_dim_county(HERE / "data" / f"dim_county_{st}.csv")
    geo = json.loads((HERE / "data" / f"{st}_counties_geo.json").read_text(encoding="utf-8"))

    # -- filetree
    qx = find_query_xlsx(drop)
    ftree = sp.load_filetree(qx) if qx else []
    ftree_export_ts = (datetime.fromtimestamp(qx.stat().st_mtime).isoformat(timespec="seconds")
                       if qx else None)

    # A library-wide ("master") export covers every PDA — narrow it to this one
    # BEFORE anything reads it, or scope/stages/links silently mix PDAs.
    pda_root, pda_cands = choose_pda_root(ftree, manifest, sp_folder)
    multi_pda_note = None
    if len(pda_cands) > 1:
        names = ", ".join(c.rsplit("/", 1)[-1] for c in pda_cands)
        if pda_root:
            ftree = sp.filter_rows_under(ftree, pda_root)
            multi_pda_note = {"code": "MULTI_PDA_EXPORT",
                              "detail": f"master export of {len(pda_cands)} PDAs — narrowed to "
                                        f"'{pda_root.rsplit('/', 1)[-1]}' ({len(ftree)} rows). "
                                        f"Seen: {names}"}
            log(f"filetree: master export ({len(pda_cands)} PDAs) -> "
                f"{pda_root.rsplit('/', 1)[-1]}")
        else:
            multi_pda_note = {"code": "AMBIGUOUS_PDA_EXPORT",
                              "detail": f"master export of {len(pda_cands)} PDAs and none matches "
                                        f"this PDA's name — set \"sp_folder\" in the manifest (or "
                                        f"--sp-folder) to pick one. Seen: {names}"}

    scope = [c for c in sp.scope_counties(ftree) if c.lower() != "remcs"]
    has_remc_scope = any(c.lower() == "remcs" for c in sp.scope_counties(ftree))
    log(f"filetree: {len(ftree)} rows; scope: {len(scope)} counties"
        + (" + REMCs" if has_remc_scope else ""))

    # -- discover + parse workbooks in the drop
    charts, table_as, others, health = [], [], [], []

    # -- SharePoint links (manifest -> query.xlsx -> query*.iqy). Swappable in
    # the board itself via Admin -> SharePoint links, which re-runs this same
    # derivation on a dropped .iqy.
    links = resolve_links(drop, manifest, ftree, iqy_path, pda_root, sp_folder, pda_cands)
    sp_base = links["sharepoint_base"]
    if multi_pda_note:
        health.append(multi_pda_note)
    if not sp_base:
        health.append({"code": "NO_SHAREPOINT_LINKS",
                       "detail": "no sharepoint_base in the manifest and no query*.iqy in the "
                                 "drop — file/folder links are inert until one is loaded "
                                 "(board: Admin -> SharePoint links)"})
    elif links["master_root_path"] and not links["root_path"]:
        health.append({"code": "PDA_FOLDER_UNKNOWN",
                       "detail": f"the .iqy is a master query rooted at "
                                 f"'{links['master_root_path'].rsplit('/', 1)[-1]}' — which PDA "
                                 f"folder sits under it is not knowable from that file alone. Set "
                                 f"\"sp_folder\" in the manifest (or pick it in the board: Admin "
                                 f"-> SharePoint links -> PDA folder)."})

    for p in sorted(drop.rglob("*.xlsx")):
        if p.name.startswith("~$") or (qx and p.samefile(qx)):
            continue
        # underscore convention (same as the parent repo's data/): _-prefixed
        # folders hold aside material (e.g. _17-19 import — prior-PDA workbooks
        # for the pa_pdas_charta importer), never part of THIS PDA's drop
        if any(part.startswith("_") for part in p.relative_to(drop).parts[:-1]):
            continue
        kind = sniff_workbook(p)
        if kind == "chart_a":
            ca = parse_chart_a(p)
            m = sp.match_dropped_file(p.name, p.stat().st_size, ftree)
            rel = p.relative_to(drop).parts[:-1]
            local_stage, _ = sp.stage_from_segments(list(rel))
            local_basis = "local_folder"
            if local_stage == 0 and int(manifest.get("default_stage") or 0):
                # loose chart, no stage folder anywhere in its path: the
                # manifest's default_stage (wizard/notebook-set) speaks for it
                local_stage, local_basis = int(manifest["default_stage"]), "default_stage"
            row = m["row"]
            d = ca.to_dict()
            d.update({
                "sp_matched": row is not None,
                "sp_match_method": m["method"],
                "sp_path": row.full_path if row else None,
                "sp_modified": row.modified if row else None,
                "sp_modified_by": row.modified_by if row else None,
                "sp_url": row.url(sp_base) if row else None,
                "stage": row.stage if row else local_stage,
                "stage_basis": "sharepoint" if row else local_basis,
                "local_modified": datetime.fromtimestamp(p.stat().st_mtime)
                                          .isoformat(timespec="seconds"),
                # where the workbook sits in the drop, folder chain included —
                # a completed PDA has no export to link against, so its file
                # tree + Chart A link are built from this (see files_by_county)
                "rel_path": p.relative_to(drop).as_posix(),
            })
            for fl in m["flags"]:
                d["flags"].append({"code": fl, "detail": f"filetree match: {p.name}"})
            if complete:
                # a finished PDA: every workbook is final regardless of which
                # folder the copy came from
                d["stage"], d["stage_basis"] = 4, "complete"
            charts.append(d)
        elif kind == "table_a":
            table_as.append(p)
        else:
            others.append(p.name)
    log(f"drop: {len(charts)} Chart A, {len(table_as)} Table A, {len(others)} other xlsx")

    # -- Table A. With several, the manifest's `table_a` (filename or
    # drop-relative path; wizard-set when the user picked one) decides;
    # otherwise latest-modified wins and the rest are flagged.
    ta = None
    ta_rel = None
    if table_as:
        table_as.sort(key=lambda p: p.stat().st_mtime, reverse=True)
        pick = table_as[0]
        want = (manifest.get("table_a") or "").strip().lower()
        if want:
            hit = [p for p in table_as
                   if p.name.lower() == want
                   or p.relative_to(drop).as_posix().lower() == want]
            if hit:
                pick = hit[0]
            else:
                health.append({"code": "TABLE_A_NOT_FOUND",
                               "detail": f"manifest table_a {manifest['table_a']!r} not in "
                                         f"the drop — fell back to newest {pick.name}"})
        ta = parse_table_a(pick)
        # drop-relative path of the chosen Table A — the board composes its
        # SharePoint link from this (site base + PDA root + this path), same
        # trick as the completed-PDA Chart A links
        ta_rel = pick.relative_to(drop).as_posix()
        for extra in table_as:
            if extra is not pick:
                health.append({"code": "MULTIPLE_TABLE_A",
                               "detail": f"ignored {extra.name} (using {pick.name})"})

    # Indicators come from the SOURCE MATERIAL (Table A carries the year's PCIs
    # and the state population; each Chart A carries its own county threshold).
    # The manifest is only an emergency override — normally unset, so the board
    # keeps working year after year with whatever the workbooks say.
    state_pci = (ta.meta.get("state_pci") if ta else None) or manifest.get("state_pci")
    county_pci = (ta.meta.get("county_pci") if ta else None) or manifest.get("county_pci")
    state_pop = (ta.meta.get("state_population") if ta else None) or manifest.get("state_population")
    state_threshold = round(state_pop * state_pci, 2) if state_pop and state_pci else None
    if ta is None:
        health.append({"code": "NO_TABLE_A",
                       "detail": "no Table A workbook in drop — indicators unavailable "
                                 "unless overridden in manifest.json"})
    if state_threshold is None:
        health.append({"code": "NO_STATE_INDICATOR",
                       "detail": "state PCI / population not found — statewide threshold "
                                 "and inclusion math unavailable"})
    if county_pci is None:
        health.append({"code": "NO_COUNTY_INDICATOR",
                       "detail": "county PCI not found — county targets only where the "
                                 "Chart A carries its own threshold cell"})

    # -- events: manifest order, plus any discovered in filenames
    events = list(manifest.get("events", []))
    known = {e["key"] for e in events}
    for d in charts:
        if d["event_key"] and d["event_key"] not in known:
            events.append({"event_id": f"E{len(events) + 1}", "label": d["event_label"],
                           "key": d["event_key"]})
            known.add(d["event_key"])
            health.append({"code": "UNLISTED_EVENT",
                           "detail": f"event {d['event_label']!r} not in manifest"})
    if not events:
        # legacy-era filenames carry no incident-period parenthetical — one
        # synthesized event for the whole PDA, labeled from the Table A
        lbl = "PDA"
        if ta is not None and ta.meta.get("incident_start"):
            lbl = f"{ta.meta['incident_start']} - {ta.meta.get('incident_end') or '?'}"
        events = [{"event_id": "E1", "label": lbl, "key": None}]
        health.append({"code": "NO_EVENT_LABELS",
                       "detail": f"no incident period in manifest or filenames — "
                                 f"single synthesized event {lbl!r}"})
    ekey_to_id = {e["key"]: e["event_id"] for e in events}

    # -- canonical selection per (entity, event) among parsed charts
    def sort_key(d):
        return (d["stage"], d["sp_modified"] or d["local_modified"] or "")

    groups = {}
    for d in charts:
        if d["is_template"]:
            health.append({"code": "TEMPLATE_IN_DROP", "detail": d["filename"]})
            continue
        gk = (ckey(d["county_key"] or d["filename"]), d["event_key"])
        groups.setdefault(gk, []).append(d)
    for gk, ds in groups.items():
        ds.sort(key=sort_key, reverse=True)
        for i, d in enumerate(ds):
            d["is_canonical"] = (i == 0)
            if i:
                health.append({"code": "DUPLICATE_COPY",
                               "detail": f"{d['filename']}: superseded by higher-stage/newer copy"})

    canonical = {gk: ds[0] for gk, ds in groups.items()}

    # -- scope fallback (no query.xlsx in the drop — e.g. a completed-PDA
    # import): counties named by the Table A plus counties with a chart
    ta_by_cty = {ckey(county_short(c["county"])): c
                 for c in (ta.counties if ta else [])}
    if not scope:
        chart_ctys = [d["county_key"] for d in canonical.values()
                      if d["entity_type"] == "county" and d["county_key"]]
        seen_k, scope = set(), []
        for c in sorted({*(county_short(c["county"]) for c in (ta.counties if ta else [])),
                         *chart_ctys} - {None}, key=str.lower):
            if ckey(c) not in seen_k:      # dedupe spelling variants across sources
                seen_k.add(ckey(c))
                scope.append(c)
        if scope:
            health.append({"code": "SCOPE_FROM_WORKBOOKS",
                           "detail": f"no query.xlsx — scope = {len(scope)} counties "
                                     "from Table A + Chart A's"})

    # -- filetree-known Chart A's (stage escalation / not-yet-ingested)
    ft_charts = {}
    for r in ftree:
        if not (r.is_item and sp.looks_like_chart_a(r.name)):
            continue
        if r.county_folder and r.county_folder.lower() == "remcs":
            cty = county_from_filename(r.name)  # the REMC's name
            ent = "remc"
        elif r.county_folder:
            cty, ent = r.county_folder, "county"
        else:
            cty, ent = county_from_filename(r.name), "county"
        if not cty:
            continue  # blank templates parked in pipeline folders
        ek = event_key(event_label_from_filename(r.name))
        k = (ckey(cty), ek)
        cur = ft_charts.get(k)
        if cur is None or (r.stage, r.modified or "") > (cur.stage, cur.modified or ""):
            ft_charts[k] = r

    # -- gold county rows: scope x events
    county_rows, applicant_rows = [], []
    for cname in sorted(scope):
        dc = dim.get(ckey(cname))
        if dc is None:
            health.append({"code": "COUNTY_NOT_IN_DIM", "detail": cname})
        for ev in events:
            gk = (ckey(cname), ev["key"])
            d = canonical.get(gk)
            ftr = ft_charts.get(gk)
            if d is None and complete and ckey(cname) in ta_by_cty:
                # COMPLETE mode, county has no Chart A in the drop: the Table A
                # itself carries the final figures — use them (labeled), so a
                # Table A-only drop still renders a full board.
                tac = ta_by_cty[ckey(cname)]
                subs = [s for s in (ta.subrecipients if ta else [])
                        if ckey(county_short(s["county"])) == ckey(cname)]
                emerg = round(tac["cat_a"] + tac["cat_b"], 2)
                total = tac["wb_total"] if tac.get("wb_total") is not None \
                    else tac["total_entered"]
                d = {
                    "population": tac.get("population"),
                    "county_threshold": tac.get("county_pci_target"),
                    "total_calc": total, "emergency_calc": emerg,
                    "permanent_calc": round(total - emerg, 2),
                    "applicants": [{
                        "applicant": s["subrecipient"], "applicant_type": "",
                        "status_raw": s["status"],
                        "status_norm": norm_status(s["status"]),
                        **{f"cat_{c.lower()}": s[f"cat_{c.lower()}"] for c in CATS},
                        "total_calc": s["total_calc"], "wb_row_total": None,
                        "comment": "", "comment_html": "",
                    } for s in subs],
                    "stage": 4, "inspector": None, "content_status": "table_a",
                    "filename": ta.filename, "sp_url": None,
                    "flags": [{"code": "FROM_TABLE_A",
                               "detail": "no Chart A in drop — figures from the "
                                         "Table A county row"}],
                }
            stage = max(d["stage"] if d else 0, ftr.stage if ftr else 0)
            ingested = d is not None
            pop = (d and d.get("population")) or (dc and dc["population"]) or None
            threshold = (d and d.get("county_threshold")) or (
                round(pop * county_pci, 2) if pop and county_pci else None)
            total = d["total_calc"] if d else None
            pct = round(100 * total / threshold, 1) if (total is not None and threshold) else None
            napp = len(d["applicants"]) if d else None
            ncomp = (sum(1 for a in d["applicants"] if a["status_norm"] == "complete")
                     if d else None)
            touch_ts, touch_by = _last_touch(ftree, cname, d)
            row = {
                "county": cname, "fips": dc["fips"] if dc else None,
                "event_id": ev["event_id"], "event_label": ev["label"],
                "stage": stage, "stage_label": sp.STAGE_LABELS[stage],
                "ingested": ingested,
                "population": pop, "county_threshold": threshold,
                "validated_total": total, "pct_of_target": pct,
                "money_tier": _money_tier(pct),
                "emergency": d["emergency_calc"] if d else None,
                "permanent": d["permanent_calc"] if d else None,
                "cats": ({c: round(sum(a[f"cat_{c.lower()}"] for a in d["applicants"]), 2)
                          for c in CATS} if d else None),
                "applicants_n": napp, "applicants_complete": ncomp,
                "inspector": d.get("inspector") if d else None,
                "content_status": d.get("content_status") if d else None,
                "source_file": d["filename"] if d else (ftr.name if ftr else None),
                "source_rel": (d.get("rel_path") if d else None),
                "source_path": (d.get("sp_path") if d else (ftr.full_path if ftr else None)),
                "sp_url": d.get("sp_url") if d else (
                    ftr.url(sp_base) if ftr else None),
                "last_touch": touch_ts, "last_touch_by": touch_by,
                "flags": d["flags"] if d else
                         ([{"code": "NOT_INGESTED",
                            "detail": f"Chart A in SharePoint (stage {stage}) not in drop"}]
                          if ftr else []),
            }
            county_rows.append(row)
            if d:
                for a in d["applicants"]:
                    applicant_rows.append({
                        "county": cname, "event_id": ev["event_id"], **a})

    # -- met_only (COMPLETE-mode default): drop counties whose validated total
    # never reached their county indicator — the finished-PDA board shows the
    # counties that mattered. Nothing silent: the excluded set is summarized in
    # health + on the clock footer (board["met_only_excluded"]).
    met_only = bool(manifest.get("met_only", complete))
    met_only_excluded = {"n": 0, "total": 0.0}
    if met_only:
        per = {}
        for r in county_rows:
            a = per.setdefault(r["county"], {"t": 0.0, "th": r["county_threshold"]})
            a["t"] += r["validated_total"] or 0
            a["th"] = a["th"] or r["county_threshold"]
        drop = {c for c, a in per.items() if a["th"] and a["t"] < a["th"]}
        if drop:
            # per-county detail rides along so the board can still SHOW the
            # excluded counties (translucent red on the map, count + $ on the
            # top card) — excluded from every total, never from sight
            fips_of = {r["county"]: r["fips"] for r in county_rows}
            met_only_excluded = {"n": len(drop),
                                 "total": round(sum(per[c]["t"] for c in drop), 2),
                                 "counties": sorted(
                                     ({"county": c, "fips": fips_of.get(c),
                                       "total": round(per[c]["t"], 2),
                                       "threshold": per[c]["th"],
                                       "pct": round(100 * per[c]["t"] / per[c]["th"], 1)
                                               if per[c]["th"] else None}
                                      for c in drop), key=lambda x: -x["total"])}
            health.append({"code": "MET_ONLY_EXCLUDED",
                           "detail": f"{len(drop)} counties under their county "
                                     f"indicator excluded from the board "
                                     f"(${met_only_excluded['total']:,.2f}): "
                                     + ", ".join(sorted(drop))})
            county_rows = [r for r in county_rows if r["county"] not in drop]
            applicant_rows = [r for r in applicant_rows if r["county"] not in drop]
            scope = [c for c in scope if c not in drop]

    # -- REMC charts: parked, not displayed. REMC damage ultimately lands inside
    # county Chart A's, so their standalone charts are parsed (never silently
    # dropped) but excluded from the board and every total, with a health note.
    for gk, d in canonical.items():
        if d["entity_type"] == "remc":
            health.append({"code": "REMC_PARKED",
                           "detail": f"{d['filename']}: REMC chart parsed but not counted — "
                                     "REMC damage arrives via county Chart A's"})

    # -- per-event + combined summaries
    summaries = {}
    for scope_ev in events + [{"event_id": "ALL", "label": "Combined", "key": None}]:
        eid = scope_ev["event_id"]
        crs = [r for r in county_rows if eid == "ALL" or r["event_id"] == eid]
        # Only counties THROUGH lead review (Ready for Table A / Entered) carry
        # figures in the rollup; everything below is "pending" (surfaced only in
        # the admin/pending view + the clock's TBD row).
        vrs = [r for r in crs if r["stage"] >= 3]
        tot = round(sum(r["validated_total"] or 0 for r in vrs), 2)
        per_stage = {s: 0 for s in range(5)}
        seen = set()
        # per-county aggregate within this scope (ALL combines events per county)
        per_cty = {}
        for r in vrs:
            k = r["county"]
            a = per_cty.setdefault(k, {"total": 0.0, "threshold": r["county_threshold"]})
            a["total"] += r["validated_total"] or 0
            a["threshold"] = a["threshold"] or r["county_threshold"]
        for r in crs:
            k = r["county"]
            if eid != "ALL":
                per_stage[r["stage"]] += 1
            else:
                if k not in seen:
                    seen.add(k)
                    per_stage[max(x["stage"] for x in county_rows
                                  if x["county"] == k)] += 1
        # pending: counties not yet through lead review, split into
        # "review" (at PDA Lead Review) vs "pre" (not submitted at all)
        pend = {}
        for r in crs:
            if r["stage"] >= 3:
                continue
            e = pend.setdefault(r["county"], {"total": 0.0, "measured": False,
                                              "maxstage": 0})
            e["maxstage"] = max(e["maxstage"], r["stage"])
            if r["ingested"] and r["validated_total"] is not None:
                e["total"] += r["validated_total"]
                e["measured"] = True
        if eid == "ALL":
            for k in [k for k in pend
                      if any(x["county"] == k and x["stage"] >= 3 for x in crs)]:
                del pend[k]

        def _pbucket(pred):
            sel = [e for e in pend.values() if pred(e)]
            return {"total": round(sum(e["total"] for e in sel), 2),
                    "n_counties": len(sel),
                    "n_unmeasured": sum(1 for e in sel if not e["measured"])}
        n_scope = len(scope)
        summaries[eid] = {
            "validated_total": tot,
            "state_threshold": state_threshold,
            "pct_of_state": round(100 * tot / state_threshold, 1) if state_threshold else None,
            "counties_total": n_scope,
            "counties_by_stage": per_stage,
            "counties_ready": per_stage[3] + per_stage[4],
            "counties_met_100": sum(1 for a in per_cty.values()
                                    if a["threshold"] and a["total"] >= a["threshold"]),
            "counties_met_50": sum(1 for a in per_cty.values() if a["threshold"] and
                                   0.5 * a["threshold"] <= a["total"] < a["threshold"]),
            "applicants_n": sum(r["applicants_n"] or 0 for r in crs),
            "guide_math": _guide_math(per_cty, state_threshold),
            "pending": {"review": _pbucket(lambda e: e["maxstage"] == 2),
                        "pre": _pbucket(lambda e: e["maxstage"] < 2)},
        }

    # -- Chart A <-> Table A reconciliation (Table A is per county, all events)
    recon = []
    if ta:
        entered = {ckey(c["county"]): c for c in ta.counties}
        chart_by_cty = {}
        for r in county_rows:
            if r["validated_total"] is not None:
                chart_by_cty[r["county"].lower()] = \
                    round(chart_by_cty.get(r["county"].lower(), 0) + r["validated_total"], 2)
        for cty, chart_total in sorted(chart_by_cty.items()):
            e = entered.get(ckey(cty))
            t_total = e["total_entered"] if e else 0.0
            if abs(chart_total - t_total) > 0.005:
                recon.append({"county": cty.title(), "chart_a": chart_total,
                              "table_a": t_total,
                              "delta": round(chart_total - t_total, 2)})

    # -- files directories per county (for the Chart A explorer)
    # Source-document test: the canonical chart per (county, event) IS the file the
    # board's numbers come from — marked in every file list it appears in.
    def _is_source(row_path, row_name, cty_l, ekey):
        d = canonical.get((cty_l, ekey))
        if not d:
            return False
        if d.get("sp_path"):
            return d["sp_path"] == row_path
        return d.get("filename") == row_name

    def _source_events(row, cty_l):
        return [e["event_id"] for e in events
                if _is_source(row.full_path, row.name, cty_l, e["key"])]

    scope_by_norm = {ckey(c): c for c in scope}

    # -- per-county FILE TREE: ONE faithful mirror of everything the query knows
    # about a county — its Counties/<County>/ working docs AND its Chart A(s)
    # sitting in the pipeline folders (Chart A's/… /Entered in Table A/) — every
    # subfolder and document, each a link. Rooted at the COMMON ANCESTOR of the
    # county's files, so a county whose only file is a pipeline Chart A still
    # shows it (no empty "0" section); a county whose files are all in its own
    # folder stays rooted there (shallow). A node's URL is <prefix>/<disp>, so
    # re-pointing the site base in the board re-points the whole tree.
    #
    # Completed PDA with no export: the drop's own folder layout (links composed
    # off the PDA root, flagged `derived` since no export confirms them).
    files_by_county = {}

    def _row_county(r):
        if r.county_folder:
            # fuzzy-map the hand-typed Counties/<Folder> name onto the scope
            # county it corresponds to; unmatched folders (REMCs etc.) pass
            # through under their own name
            return scope_by_norm.get(ckey(r.county_folder), r.county_folder)
        if r.is_item and sp.looks_like_chart_a(r.name):
            return scope_by_norm.get(ckey(county_from_filename(r.name) or ""))
        return None

    def _common_prefix(seglists):
        if not seglists:
            return []
        out = []
        for i in range(min(len(s) for s in seglists)):
            seg = seglists[0][i]
            if all(s[i] == seg for s in seglists):
                out.append(seg)
            else:
                break
        return out

    county_ftree = {}
    for r in ftree:
        cty = _row_county(r)
        if cty:
            county_ftree.setdefault(cty, []).append(r)

    for cty, rows in county_ftree.items():
        prefix = _common_prefix([r.segments for r in rows])   # folder segments
        plen = len(prefix)
        nodes = []
        for r in rows:
            is_chart = r.is_item and sp.looks_like_chart_a(r.name)
            nodes.append({
                "disp": "/".join((r.segments + [r.name])[plen:]),
                "folder": not r.is_item,
                "modified": r.modified, "by": r.modified_by, "size": r.size,
                "is_chart": is_chart,
                "source_events": (_source_events(r, ckey(cty)) if is_chart else []),
            })
        files_by_county[cty] = {"prefix_path": "/".join(prefix),
                                "prefix_rel": None, "nodes": nodes}

    if not ftree:
        for d in charts:
            cty = scope_by_norm.get(ckey(d.get("county_key") or ""))
            if not cty or not d.get("rel_path"):
                continue
            e = files_by_county.setdefault(cty, {"prefix_path": None,
                                                 "prefix_rel": "", "nodes": []})
            e["nodes"].append({
                "disp": d["rel_path"], "folder": False, "derived": True,
                "modified": d.get("local_modified"), "by": None,
                "size": None, "is_chart": True,
                "source_events": [ev["event_id"] for ev in events
                                  if _is_source(d.get("sp_path") or "",
                                                d["filename"], ckey(cty), ev["key"])],
            })

    for e in files_by_county.values():
        e["nodes"].sort(key=lambda n: (not n["folder"], n["disp"].lower()))

    # kept for backward compatibility (the board now shows one unified tree; the
    # pipeline charts live inside files_by_county, not a separate section)
    chart_files = {}

    # -- data health rollup
    for d in charts:
        for f in d["flags"]:
            health.append({"code": f["code"],
                           "detail": f"{d['filename']}: {f['detail']}"})
    stale_h = manifest.get("stale_hours", 48)

    # -- snapshots (append-only ticker)
    snap_path = out / "snapshots.jsonl"
    snapshots = []
    if snap_path.exists():
        snapshots = [json.loads(l) for l in snap_path.read_text(encoding="utf-8").splitlines() if l.strip()]
    snap = {"run_ts": run_ts,
            "events": {eid: {"validated_total": s["validated_total"],
                             "counties_ready": s["counties_ready"],
                             "countable": s["guide_math"]["countable"]}
                       for eid, s in summaries.items()},
            "counties": [{"county": r["county"], "event_id": r["event_id"],
                          "stage": r["stage"], "total": r["validated_total"]}
                         for r in county_rows]}
    movers = _movers(snapshots[-1], snap) if snapshots else []
    if not snapshots or snapshots[-1]["counties"] != snap["counties"]:
        snapshots.append(snap)
        with open(snap_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(snap) + "\n")

    if history_path is None:
        history_path = HERE / "data" / f"history_{(manifest.get('state') or 'in').lower()}.json"
    hist, hist_meta = load_history(
        history_path, {r["fips"] for r in county_rows if r.get("fips")})
    if hist_meta:
        log(f"history: {len(hist)} scope counties from {history_path.name} "
            f"(OpenFEMA snapshot {hist_meta['fetchedAt']})")

    board = {
        "generated": run_ts,
        "complete": complete,
        "met_only": met_only,
        "met_only_excluded": met_only_excluded,
        "master_folder": links["master_folder"],
        "links": links,
        "pda": {"id": manifest["pda_id"], "title": manifest.get("title", manifest["pda_id"]),
                "state": manifest.get("state"), "sharepoint_base": sp_base,
                "sp_root_url": links["sp_root_url"]},
        "filetree_export_ts": ftree_export_ts,
        "indicators": {"state_pci": state_pci, "county_pci": county_pci,
                       "state_population": state_pop, "state_threshold": state_threshold},
        # incident period straight from the Table A meta (label-driven parse);
        # None fields simply don't render
        "incident": ({"start": ta.meta.get("incident_start"),
                      "end": ta.meta.get("incident_end"),
                      "name": ta.meta.get("incident_name")} if ta else None),
        # the Table A workbook itself — filename + drop-relative path so the
        # board can link it in SharePoint off the PDA root
        "table_a": {"present": ta is not None,
                    "filename": (ta.filename if ta else None),
                    "rel_path": ta_rel},
        "events": events, "summaries": summaries,
        "counties": county_rows,
        "applicants": applicant_rows,
        "reconciliation": recon,
        "table_a_present": ta is not None,
        "files": files_by_county,
        "chart_files": chart_files,
        "health": health, "stale_hours": stale_h,
        "snapshots": [{"run_ts": s["run_ts"], "events": s["events"]} for s in snapshots],
        "movers": movers,
        "history": hist,
        "history_meta": hist_meta,
        "geo": geo,
    }

    # -- content switches (wizard "clean" questions — for boards sent outside
    # the team, e.g. to the state). Data is STRIPPED at build, not hidden by
    # CSS: the emailed file genuinely does not carry it.
    if manifest.get("no_links"):
        board["no_links"] = True
        board["links"] = {"sharepoint_base": "", "master_folder": "",
                          "root_path": None, "master_root_path": None,
                          "pda_folder": "", "pda_candidates": [], "source": None,
                          "sp_root_url": None}
        board["master_folder"] = ""
        board["pda"]["sharepoint_base"] = ""
        board["pda"]["sp_root_url"] = None
        board["files"] = {}
        board["table_a"]["rel_path"] = None
        for r in board["counties"]:
            r["sp_url"] = None
            r["source_path"] = r["source_rel"] = None
        log("content switch: SharePoint links stripped (no_links)")
    if manifest.get("no_inspectors"):
        board["no_inspectors"] = True
        for r in board["counties"]:
            r["inspector"] = None
            r["last_touch_by"] = None
            if "sp_modified_by" in r:
                r["sp_modified_by"] = None
        for a in board["applicants"]:
            if "inspector" in a:
                a["inspector"] = None
        log("content switch: inspector names stripped (no_inspectors)")
    if manifest.get("history_no_dollars"):
        # prior applicants + declarations stay visible; every OBLIGATION
        # dollar is removed from the embedded history
        board["history_scrubbed"] = True
        for h in (board["history"] or {}).values():
            h.pop("paObligated", None)
            for d in h.get("disasters", []):
                d.pop("paObligated", None)
            for a in h.get("applicants", []):
                a.pop("pa", None)
                for x in a.get("disasters", []):
                    x.pop("pa", None)
        log("content switch: historical obligation dollars stripped (history_no_dollars)")

    # -- outputs
    _write_csv(out / "gold_county_status.csv", county_rows,
               drop_keys=("cats", "flags"))
    _write_csv(out / "gold_applicants.csv", applicant_rows, drop_keys=("cats",))
    _write_csv(out / "data_health.csv", health)
    (out / "board_data.json").write_text(json.dumps(board), encoding="utf-8")
    tpl = (HERE / "templates" / "board.html").read_text(encoding="utf-8")
    html = tpl.replace("/*__BOARD_DATA__*/null", json.dumps(board))
    (out / "board.html").write_text(html, encoding="utf-8")
    log(f"out: board.html ({len(html) // 1024} KB), gold CSVs, snapshot #{len(snapshots)} "
        f"in {time.time() - t0:.1f}s")
    return board


def _guide_math(per_cty, state_threshold):
    """Statewide per-capita inclusion math per the PDA Guide (July 2025, p.56,
    'Per Capita Impact Calculations'):
      - counties MEETING the countywide PCI always count toward the statewide PCI;
      - counties at 50-99% of countywide PCI count ONLY IF the meeting counties
        alone cover >= 75% of the statewide PCI;
      - counties below 50% of countywide PCI are never included.
    """
    full = half = below = 0.0
    n_full = n_half = n_below = 0
    for a in per_cty.values():
        t, th = a["total"], a["threshold"]
        if not t:
            continue
        if not th:                      # no threshold known -> can't tier; treat as below
            below += t; n_below += 1
        elif t >= th:
            full += t; n_full += 1
        elif t >= 0.5 * th:
            half += t; n_half += 1
        else:
            below += t; n_below += 1
    gate_need = round(0.75 * state_threshold, 2) if state_threshold else None
    gate75_ok = bool(gate_need is not None and full >= gate_need)
    countable = round(full + (half if gate75_ok else 0), 2)
    return {
        "full": round(full, 2), "n_full": n_full,
        "half": round(half, 2), "n_half": n_half,
        "half_counts": gate75_ok,
        "below": round(below, 2), "n_below": n_below,
        "gate_need": gate_need, "gate75_ok": gate75_ok,
        "countable": countable,
        "pct_countable": round(100 * countable / state_threshold, 1)
                         if state_threshold else None,
    }


def _money_tier(pct):
    if pct is None:
        return "unknown"
    if pct >= 100:
        return "met_100"
    if pct >= 50:
        return "met_50"
    if pct > 0:
        return "under"
    return "zero"


def _last_touch(ftree, county, d):
    best_ts, best_by = None, None
    for r in ftree:
        if r.is_item and r.county_folder and ckey(r.county_folder) == ckey(county):
            if r.modified and (best_ts is None or r.modified > best_ts):
                best_ts, best_by = r.modified, r.modified_by
    if d:
        for ts, by in ((d.get("sp_modified"), d.get("sp_modified_by")),):
            if ts and (best_ts is None or ts > best_ts):
                best_ts, best_by = ts, by
    return best_ts, best_by


def _movers(prev, cur):
    prev_ix = {(c["county"], c["event_id"]): c for c in prev["counties"]}
    out = []
    for c in cur["counties"]:
        p = prev_ix.get((c["county"], c["event_id"]))
        if p is None:
            if c["stage"] > 0 or c["total"]:
                out.append({"county": c["county"], "event_id": c["event_id"],
                            "kind": "new", "delta_total": c["total"], "to_stage": c["stage"]})
            continue
        dt = round((c["total"] or 0) - (p["total"] or 0), 2)
        if abs(dt) > 0.005:
            out.append({"county": c["county"], "event_id": c["event_id"],
                        "kind": "dollars", "delta_total": dt})
        if c["stage"] != p["stage"]:
            out.append({"county": c["county"], "event_id": c["event_id"],
                        "kind": "stage", "from_stage": p["stage"], "to_stage": c["stage"]})
    out.sort(key=lambda m: abs(m.get("delta_total") or 0), reverse=True)
    return out


def _write_csv(path, rows, drop_keys=()):
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    keys = [k for k in rows[0] if k not in drop_keys]
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=keys, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--drop", default=str(HERE / "PDAExamples"))
    ap.add_argument("--manifest", default=str(HERE / "manifest.json"))
    ap.add_argument("--out", default=str(HERE / "out"))
    ap.add_argument("--history", default="",
                    help="static OpenFEMA history snapshot (default "
                         "data/history_<state>.json; build with build_history.py)")
    ap.add_argument("--iqy", default="",
                    help="SharePoint web query (query*.iqy) for this PDA — supplies the "
                         "site host + root folder for file/county links. Default: the "
                         "newest *.iqy found in the drop.")
    ap.add_argument("--sp-folder", default="",
                    help="This PDA's folder name under a MASTER export/.iqy that covers the "
                         "whole library (e.g. 'MI PDA May 2026'). Same as the manifest's "
                         "\"sp_folder\" key; only needed when the name can't be matched.")
    a = ap.parse_args()
    build(Path(a.drop), load_manifest(Path(a.manifest)), Path(a.out),
          Path(a.history) if a.history else None,
          Path(a.iqy) if a.iqy else None, a.sp_folder)


if __name__ == "__main__":
    main()
