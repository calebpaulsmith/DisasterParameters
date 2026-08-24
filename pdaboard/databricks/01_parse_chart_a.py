# Databricks notebook source
# MAGIC %md
# MAGIC # 01 — Parse Chart A drops → Unity Catalog tables
# MAGIC
# MAGIC Reads every Chart A / Table A workbook dropped into the PDA inbox **volume**,
# MAGIC parses them with the SAME `chart_a_parser.py` used by the local pdaboard
# MAGIC harness (upload it next to this notebook, or to `<drop>/_code/`), and writes
# MAGIC Delta tables the board app and Power BI both read.
# MAGIC
# MAGIC **Drop convention** (matches the SharePoint `Chart A's/` pipeline — drag the
# MAGIC folder, or the zip SharePoint's Download gives you, into the volume):
# MAGIC
# MAGIC ```
# MAGIC /Volumes/<catalog>/<schema>/<volume>/<pda_id>/
# MAGIC ├── (root .xlsx or .zip)                ← triage / lead review (default stage)
# MAGIC ├── 1. For PDA Lead Review/…            ← stage 2
# MAGIC ├── 2. Ready for Table A/…              ← stage 3
# MAGIC │   └── Entered in Table A/…            ← stage 4
# MAGIC ├── IN PDA - July 2026.xlsx             ← Table A master (indicators), if present
# MAGIC ├── _code/chart_a_parser.py             ← (optional) parser fallback location
# MAGIC └── _ref/dim_county_in.csv              ← (optional) name→FIPS dim
# MAGIC ```
# MAGIC
# MAGIC **Stage comes from the folder each file sits in** (the SharePoint convention:
# MAGIC the folder move IS the status change). `.zip` files are expanded in place —
# MAGIC inner folder paths count for stage too. Files with no stage folder get the
# MAGIC `default_stage` widget value (2 = For PDA Lead Review, since everything in the
# MAGIC Chart A's pipeline folder has at least been submitted).
# MAGIC
# MAGIC **Tables written** (all Delta, `<catalog>.<schema>.*`):
# MAGIC
# MAGIC | table | grain | notes |
# MAGIC |---|---|---|
# MAGIC | `bronze_chart_files` | file copy | registry: every file seen, parse status, stage |
# MAGIC | `silver_chart_a_county` | workbook copy | header + recomputed totals + `wb_*` reconciliation + `is_canonical` |
# MAGIC | `silver_chart_a_applicant` | applicant row | Cat A–G, status, **comment** (plain, real line breaks) + **comment_html** (bold/italic/underline + `<br>`) |
# MAGIC | `silver_chart_a_flags` | anomaly | nothing silently dropped |
# MAGIC | `silver_table_a_meta/county/subrecipient/reductions` | Table A | indicators + entered rows, when a Table A is in the drop |
# MAGIC | `gold_county_status` | county × event (canonical) | the map/table row: stage, validated $, % of county target, money tier |
# MAGIC | `gold_pda_summary` | event (+ ALL) | validated (stage≥3 only), PDA-Guide inclusion math, pending buckets |
# MAGIC | `gold_data_health` | anomaly | the Data Health page |
# MAGIC | `gold_snapshot_county` / `gold_snapshot_summary` | append-only | THE TICKER — one batch per run, skipped when nothing changed |
# MAGIC
# MAGIC **Rich text / Power BI:** `comment` keeps the workbook's alt-Enter line breaks
# MAGIC as real `\n` characters — a Power BI table visual with *word wrap* on shows
# MAGIC them. `comment_html` preserves bold/italic/underline runs as minimal HTML
# MAGIC (`<b>`, `<i>`, `<u>`, `<br>`) — render it with the free **HTML Content**
# MAGIC custom visual (native visuals show the tags literally). Both columns always
# MAGIC carry the same text.
# MAGIC
# MAGIC **Domain rules honored** (same as the local harness — see pdaboard/CLAUDE.md):
# MAGIC indicators come from the source workbooks, never hardcoded (widgets are an
# MAGIC emergency override only); county identity from `County Summary!B3`, not the
# MAGIC filename; every total recomputed from Cat A–G and reconciled; only stage ≥ 3
# MAGIC (through Lead Review) counts as validated; REMC charts parse but are parked;
# MAGIC dollar conservation is asserted before anything is written.

# COMMAND ----------

# MAGIC %pip install "openpyxl>=3.1" --quiet
# MAGIC # openpyxl >= 3.1 is required for rich_text=True (the comments' bold runs)

# COMMAND ----------

dbutils.widgets.text("catalog", "recovery", "Catalog")
dbutils.widgets.text("schema", "pda_ops", "Schema")
dbutils.widgets.text("drop_path", "/Volumes/recovery/pda_ops/pda_inbox/IN_PDA_July_2026",
                     "Drop path (volume folder for this PDA)")
dbutils.widgets.text("pda_id", "IN_PDA_July_2026", "PDA id")
dbutils.widgets.text("state", "IN", "State (2-letter)")
dbutils.widgets.text("default_stage", "2", "Stage when no folder matches (2=Lead Review)")
# --- pa_pdas_charta identity: FILL IN / VERIFY for each PDA run. These name
# the PDA the way the existing pa_pdas table does (its natural key is
# Year+Month+State — e.g. 2026 / May / MI). Leave year/month blank to derive
# them from the Table A's PDA-start date (verify the printed values!).
dbutils.widgets.text("pda_year", "", "PDA year (pa_pdas Year, e.g. 2026; blank=from Table A)")
dbutils.widgets.text("pda_month", "", "PDA month (pa_pdas Month, e.g. May; blank=from Table A)")
dbutils.widgets.text("declaration_number", "", "Declaration number if known (pa_pdas Declaration_Number)")
dbutils.widgets.text("pa_pdas_table", "", "Existing pa_pdas table (read-only, for the row link; blank=skip)")
# Emergency overrides ONLY — normally blank; indicators come from the Table A workbook.
dbutils.widgets.text("state_pci_override", "", "State PCI override (emergency only)")
dbutils.widgets.text("county_pci_override", "", "County PCI override (emergency only)")
dbutils.widgets.text("state_population_override", "", "State population override (emergency only)")

CATALOG = dbutils.widgets.get("catalog").strip()
SCHEMA = dbutils.widgets.get("schema").strip()
DROP = dbutils.widgets.get("drop_path").rstrip("/")
PDA_ID = dbutils.widgets.get("pda_id").strip()
STATE = dbutils.widgets.get("state").strip().upper()
DEFAULT_STAGE = int(dbutils.widgets.get("default_stage") or 2)

def _optf(name):
    v = dbutils.widgets.get(name).strip()
    return float(v.replace(",", "")) if v else None

OVR_STATE_PCI = _optf("state_pci_override")
OVR_COUNTY_PCI = _optf("county_pci_override")
OVR_STATE_POP = _optf("state_population_override")
PDA_YEAR = dbutils.widgets.get("pda_year").strip()
PDA_MONTH = dbutils.widgets.get("pda_month").strip()
DECL_NUMBER = dbutils.widgets.get("declaration_number").strip() or None
PA_PDAS_TABLE = dbutils.widgets.get("pa_pdas_table").strip() or None

spark.sql(f"CREATE SCHEMA IF NOT EXISTS {CATALOG}.{SCHEMA}")
print(f"drop: {DROP}\ntables: {CATALOG}.{SCHEMA}.*")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Import the parser (single source of truth — do not fork it)
# MAGIC `chart_a_parser.py` is the exact module the local harness runs and tests.
# MAGIC Upload it (Workspace → this notebook's folder, or `<drop>/_code/`).

# COMMAND ----------

import os, sys, importlib.util

def _load_module(name):
    """chart_a_parser.py / pa_pdas_charta.py: workspace file next to this
    notebook, else <drop>/_code/. Same modules the local harness tests."""
    # 1) workspace file next to this notebook
    try:
        nb = dbutils.notebook.entry_point.getDbutils().notebook().getContext() \
                    .notebookPath().get()
        wsdir = "/Workspace" + os.path.dirname(nb)
        if os.path.exists(os.path.join(wsdir, f"{name}.py")):
            if wsdir not in sys.path:
                sys.path.insert(0, wsdir)
            mod = importlib.import_module(name)
            return mod, os.path.join(wsdir, f"{name}.py")
    except Exception:
        pass
    # 2) volume fallback
    vp = os.path.join(DROP, "_code", f"{name}.py")
    if os.path.exists(vp):
        spec = importlib.util.spec_from_file_location(name, vp)
        mod = importlib.util.module_from_spec(spec)
        sys.modules[name] = mod   # must precede exec_module (dataclasses)
        spec.loader.exec_module(mod)
        return mod, vp
    raise FileNotFoundError(
        f"{name}.py not found. Upload pdaboard/{name}.py either next to this "
        f"notebook (Workspace) or to <drop>/_code/{name}.py.")

cap, parser_path = _load_module("chart_a_parser")
parse_chart_a, parse_table_a, sniff_workbook = cap.parse_chart_a, cap.parse_table_a, cap.sniff_workbook
event_key, CATS = cap.event_key, cap.CATS
# charta builder imports chart_a_parser — load it AFTER the parser is in sys.modules
chb, charta_path = _load_module("pa_pdas_charta")
print(f"parser: {parser_path}\ncharta builder: {charta_path}")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Discover files (expand zips, derive stage from folder path)

# COMMAND ----------

import hashlib, re, shutil, tempfile, zipfile
from datetime import datetime, timezone

RUN_TS = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")

STAGE_LABELS = {0: "Not started", 1: "Working", 2: "For PDA Lead Review",
                3: "Ready for Table A", 4: "Entered in Table A"}
# (lowercased folder-segment, rank). MAX rank among matching segments wins —
# 'Entered in Table A' paths also contain '2. Ready for Table A'.
FOLDER_STAGES = [
    ("entered in table a", 4),
    ("2. ready for table a", 3),
    ("ready for table a", 3),
    ("validated", 3),
    ("1. for pda lead review", 2),
    ("for pda lead review", 2),
    ("chart a's", 2),
    ("chart as", 2),
    ("counties", 1),
]

def stage_from_segments(segments):
    low = [s.lower() for s in segments]
    best, basis = 0, None
    for seg, rank in FOLDER_STAGES:
        if seg in low and rank > best:
            best, basis = rank, seg
    if best == 0:
        return DEFAULT_STAGE, "default (no stage folder in path)"
    return best, basis

def sha256_of(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()

work = tempfile.mkdtemp(prefix="pda_drop_")
found = []   # {local_path, display_path, rel_segments, filename, size, mtime, from_zip}

for root, _dirs, files in os.walk(DROP):
    for fn in sorted(files):
        full = os.path.join(root, fn)
        rel = os.path.relpath(full, DROP).replace("\\", "/")
        segs = rel.split("/")[:-1]
        if fn.startswith("~$") or any(s.startswith("_") for s in segs):
            continue  # _-prefixed folders (_code, _ref, _<aside>) never parse
        if fn.lower().endswith(".zip"):
            # SharePoint "Download" hands you a zip — expand it; inner folder
            # paths (e.g. "2. Ready for Table A/…") count for stage.
            zdir = os.path.join(work, re.sub(r"[^A-Za-z0-9]+", "_", rel))
            try:
                with zipfile.ZipFile(full) as z:
                    for zi in z.infolist():
                        if zi.is_dir() or not zi.filename.lower().endswith(".xlsx"):
                            continue
                        if os.path.basename(zi.filename).startswith("~$"):
                            continue
                        target = os.path.join(zdir, zi.filename)
                        os.makedirs(os.path.dirname(target), exist_ok=True)
                        with z.open(zi) as src, open(target, "wb") as dst:
                            shutil.copyfileobj(src, dst)
                        found.append({
                            "local_path": target,
                            "display_path": f"{rel}!{zi.filename}",
                            "rel_segments": segs + zi.filename.split("/")[:-1],
                            "filename": os.path.basename(zi.filename),
                            "size": zi.file_size,
                            "mtime": datetime(*zi.date_time).strftime("%Y-%m-%dT%H:%M:%S"),
                            "from_zip": True,
                        })
            except zipfile.BadZipFile:
                found.append({"local_path": full, "display_path": rel,
                              "rel_segments": segs, "filename": fn,
                              "size": os.path.getsize(full), "mtime": None,
                              "from_zip": False, "bad_zip": True})
        elif fn.lower().endswith(".xlsx"):
            found.append({
                "local_path": full, "display_path": rel, "rel_segments": segs,
                "filename": fn, "size": os.path.getsize(full),
                "mtime": datetime.fromtimestamp(os.path.getmtime(full), timezone.utc)
                                 .strftime("%Y-%m-%dT%H:%M:%S"),
                "from_zip": False,
            })

print(f"{len(found)} candidate files under {DROP}")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Parse every workbook (Chart A + Table A), collect flags

# COMMAND ----------

registry, charts, table_as, health = [], [], [], []

for f in found:
    stage, basis = stage_from_segments(f["rel_segments"])
    reg = {"pda_id": PDA_ID, "run_ts": RUN_TS,
           "volume_path": f["display_path"], "filename": f["filename"],
           "size_bytes": int(f["size"]), "modified_ts": f["mtime"],
           "from_zip": bool(f["from_zip"]), "stage": stage,
           "stage_basis": str(basis), "sha256": None,
           "kind": None, "parse_status": None, "parse_error": None}
    if f.get("bad_zip"):
        reg.update(kind="zip", parse_status="error", parse_error="bad zip file")
        registry.append(reg)
        health.append({"code": "BAD_ZIP", "detail": f["display_path"]})
        continue
    try:
        reg["sha256"] = sha256_of(f["local_path"])
        kind = sniff_workbook(f["local_path"])
        reg["kind"] = kind
        if kind == "chart_a":
            ca = parse_chart_a(f["local_path"]).to_dict()
            ca.update(volume_path=f["display_path"], filename=f["filename"],
                      stage=stage, stage_basis=str(basis),
                      modified_ts=f["mtime"])
            charts.append(ca)
            reg["parse_status"] = "ok"
        elif kind == "table_a":
            table_as.append((f, parse_table_a(f["local_path"])))
            reg["parse_status"] = "ok"
        else:
            reg["parse_status"] = "skipped"
            health.append({"code": "OTHER_XLSX",
                           "detail": f"{f['display_path']}: not a Chart A or Table A"})
    except Exception as e:  # noqa: BLE001 — a bad file must never sink the run
        reg["parse_status"] = "error"
        reg["parse_error"] = f"{type(e).__name__}: {e}"[:500]
        health.append({"code": "PARSE_FAIL", "detail": f"{f['display_path']}: {e}"})
    registry.append(reg)

n_ok = sum(1 for r in registry if r["parse_status"] == "ok")
n_err = sum(1 for r in registry if r["parse_status"] == "error")
print(f"parsed: {len(charts)} Chart A, {len(table_as)} Table A, {n_err} errors")

# Trust gate: a template drift shows as a loud red run, never a half-parsed board.
if registry and n_err > 0.25 * max(n_ok + n_err, 1):
    raise RuntimeError(f"DEGRADED RUN: {n_err} of {n_ok + n_err} workbooks failed to "
                       "parse — refusing to overwrite tables. See `health` above.")
if not charts and not table_as:
    raise RuntimeError(f"No Chart A or Table A workbooks found under {DROP} — "
                       "nothing to build.")
if not charts:
    # Table A-only drop (e.g. a prior-PDA import where only the master was
    # kept): the board tables will be empty but pa_pdas_charta still builds.
    health.append({"code": "NO_CHART_A",
                   "detail": "drop carries a Table A but no Chart A workbooks — "
                             "board tables empty; pa_pdas_charta from Table A only "
                             "(no comments/types/inspectors)"})

# COMMAND ----------

# MAGIC %md
# MAGIC ## Indicators (from the Table A workbook — widgets are an emergency override)

# COMMAND ----------

ta = None
if table_as:
    table_as.sort(key=lambda t: t[0]["mtime"] or "", reverse=True)
    ta = table_as[0][1]
    for extra, _ in table_as[1:]:
        health.append({"code": "MULTIPLE_TABLE_A",
                       "detail": f"ignored older {extra['filename']}"})

state_pci = (ta.meta.get("state_pci") if ta else None) or OVR_STATE_PCI
county_pci = (ta.meta.get("county_pci") if ta else None) or OVR_COUNTY_PCI
state_pop = (ta.meta.get("state_population") if ta else None) or OVR_STATE_POP
state_threshold = round(state_pop * state_pci, 2) if state_pop and state_pci else None

if ta is None:
    health.append({"code": "NO_TABLE_A",
                   "detail": "no Table A workbook in drop — indicators unavailable "
                             "unless overridden by widget"})
if state_threshold is None:
    health.append({"code": "NO_STATE_INDICATOR",
                   "detail": "state PCI / population not found — statewide threshold "
                             "and inclusion math unavailable"})
if county_pci is None:
    health.append({"code": "NO_COUNTY_INDICATOR",
                   "detail": "county PCI not found — county targets only where the "
                             "Chart A carries its own threshold cell"})
print(f"state PCI={state_pci}  county PCI={county_pci}  pop={state_pop}  "
      f"state threshold={state_threshold}")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Events, canonical selection, county FIPS

# COMMAND ----------

MONTHS = {m: i + 1 for i, m in enumerate(
    ["january", "february", "march", "april", "may", "june", "july",
     "august", "september", "october", "november", "december"])}

def event_sort_key(label):
    m = re.match(r"([A-Za-z]+)\s*(\d{1,2}).*?,\s*(\d{4})", label or "")
    if m:
        return (int(m.group(3)), MONTHS.get(m.group(1).lower(), 0), int(m.group(2)))
    return (9999, 0, 0)

labels = sorted({c["event_label"] for c in charts if c["event_label"]},
                key=event_sort_key)
events = [{"event_id": f"E{i+1}", "label": lb, "key": event_key(lb)}
          for i, lb in enumerate(labels)]
ekey_to_id = {e["key"]: e["event_id"] for e in events}
if charts and not events:
    # Legacy-era filenames carry no incident-period parenthetical (e.g.
    # "Alcona County - Chart A - Michigan (2026).xlsx") — synthesize ONE event
    # for the whole drop, labeled from the Table A incident period when we
    # have it. event_key None matches the charts' parsed (absent) key.
    _lbl = "PDA"
    if ta is not None and ta.meta.get("incident_start"):
        _lbl = f"{ta.meta['incident_start']} - {ta.meta.get('incident_end') or '?'}"
    events = [{"event_id": "E1", "label": _lbl, "key": None}]
    ekey_to_id = {None: "E1"}
    health.append({"code": "NO_EVENT_LABELS",
                   "detail": f"no incident period in any Chart A filename — "
                             f"single synthesized event '{_lbl}'"})
print("events:", [(e["event_id"], e["label"]) for e in events])

# canonical per (entity, event): highest stage wins, tie -> latest modified
groups = {}
for d in charts:
    if d["is_template"]:
        health.append({"code": "TEMPLATE_IN_DROP", "detail": d["filename"]})
        continue
    gk = ((d["county_key"] or d["filename"]).lower(), d["event_key"])
    groups.setdefault(gk, []).append(d)
for gk, ds in groups.items():
    ds.sort(key=lambda d: (d["stage"], d["modified_ts"] or ""), reverse=True)
    for i, d in enumerate(ds):
        d["is_canonical"] = i == 0
        if i:
            health.append({"code": "DUPLICATE_COPY",
                           "detail": f"{d['filename']}: superseded by "
                                     "higher-stage/newer copy"})
canonical = {gk: ds[0] for gk, ds in groups.items()}
for d in canonical.values():
    if d["entity_type"] == "remc":
        health.append({"code": "REMC_PARKED",
                       "detail": f"{d['filename']}: REMC chart parsed but not "
                                 "counted — REMC damage arrives via county Chart A's"})

# name -> fips: dim_county table if it exists, else _ref CSV, else none
dim = {}
dim_tbl = f"{CATALOG}.{SCHEMA}.dim_county"
try:
    for r in spark.table(dim_tbl).collect():
        d = r.asDict()
        dim[str(d.get("name", "")).lower()] = str(d.get("fips") or "")
    print(f"dim_county: {len(dim)} rows from {dim_tbl}")
except Exception:
    csvp = os.path.join(DROP, "_ref", f"dim_county_{STATE.lower()}.csv")
    if os.path.exists(csvp):
        import csv as _csv
        with open(csvp, newline="", encoding="utf-8") as fh:
            for row in _csv.DictReader(fh):
                dim[row["name"].lower()] = row["fips"]
        print(f"dim_county: {len(dim)} rows from {csvp}")
    else:
        health.append({"code": "NO_DIM_COUNTY",
                       "detail": f"no {dim_tbl} table and no {csvp} — FIPS left null "
                                 "(map join unavailable)"})

# COMMAND ----------

# MAGIC %md
# MAGIC ## Gold model — county × event rows, PDA-Guide math, summaries
# MAGIC Ports of `pipeline.py`'s `_money_tier` / `_guide_math` / summary loop.
# MAGIC Only stage ≥ 3 (through Lead Review) counts as validated anywhere.

# COMMAND ----------

def money_tier(pct):
    if pct is None:
        return "unknown"
    if pct >= 100:
        return "met_100"
    if pct >= 50:
        return "met_50"
    if pct > 0:
        return "under"
    return "zero"

def guide_math(per_cty, state_threshold):
    """PDA Guide (July 2025, p.56, 'Per Capita Impact Calculations'):
    >=100% of county PCI always counts; 50-99% counts ONLY if the >=100%
    counties alone cover 75% of the statewide PCI; <50% never counts."""
    full = half = below = 0.0
    n_full = n_half = n_below = 0
    for a in per_cty.values():
        t, th = a["total"], a["threshold"]
        if not t:
            continue
        if not th:
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
    return {"full": round(full, 2), "n_full": n_full,
            "half": round(half, 2), "n_half": n_half, "half_counts": gate75_ok,
            "below": round(below, 2), "n_below": n_below,
            "gate_need": gate_need, "gate75_ok": gate75_ok,
            "countable": countable,
            "pct_countable": round(100 * countable / state_threshold, 1)
                             if state_threshold else None}

# scope = counties observed among canonical county-type charts (there is no
# query.xlsx/Counties folder in this drop mode; the SharePoint sync phase will
# restore the authoritative scope list)
scope = sorted({d["county_key"] for d in canonical.values()
                if d["entity_type"] == "county" and d["county_key"]})

county_rows, applicant_rows = [], []
_applicants_added = set()   # id() of charts whose applicants landed below
for cname in scope:
    for ev in events:
        d = canonical.get((cname.lower(), ev["key"]))
        if d is None:
            county_rows.append({
                "pda_id": PDA_ID, "run_ts": RUN_TS, "county": cname,
                "fips": dim.get(cname.lower()), "event_id": ev["event_id"],
                "event_label": ev["label"], "stage": 0,
                "stage_label": STAGE_LABELS[0], "is_validated": False,
                "population": None, "county_threshold": None,
                "validated_total": None, "pct_of_target": None,
                "money_tier": "unknown", "emergency": None, "permanent": None,
                **{f"cat_{c.lower()}": None for c in CATS},
                "applicants_n": None, "applicants_complete": None,
                "inspector": None, "content_status": None,
                "source_file": None, "volume_path": None, "n_flags": 0})
            continue
        pop = d.get("population")
        threshold = d.get("county_threshold") or (
            round(pop * county_pci, 2) if pop and county_pci else None)
        total = d["total_calc"]
        pct = round(100 * total / threshold, 1) if threshold else None
        cats_sum = {c: round(sum(a[f"cat_{c.lower()}"] for a in d["applicants"]), 2)
                    for c in CATS}
        county_rows.append({
            "pda_id": PDA_ID, "run_ts": RUN_TS, "county": cname,
            "fips": dim.get(cname.lower()), "event_id": ev["event_id"],
            "event_label": ev["label"], "stage": d["stage"],
            "stage_label": STAGE_LABELS[d["stage"]],
            "is_validated": d["stage"] >= 3,
            "population": int(pop) if pop else None,
            "county_threshold": threshold,
            "validated_total": total, "pct_of_target": pct,
            "money_tier": money_tier(pct),
            "emergency": d["emergency_calc"], "permanent": d["permanent_calc"],
            **{f"cat_{c.lower()}": cats_sum[c] for c in CATS},
            "applicants_n": len(d["applicants"]),
            "applicants_complete": sum(1 for a in d["applicants"]
                                       if a["status_norm"] == "complete"),
            "inspector": d.get("inspector"),
            "content_status": d.get("content_status"),
            "source_file": d["filename"], "volume_path": d["volume_path"],
            "n_flags": len(d["flags"])})
        _applicants_added.add(id(d))
        for a in d["applicants"]:
            applicant_rows.append({
                "pda_id": PDA_ID, "run_ts": RUN_TS, "county": cname,
                "fips": dim.get(cname.lower()),
                "event_id": ev["event_id"], "event_label": ev["label"],
                "stage": d["stage"], "is_validated": d["stage"] >= 3,
                "is_canonical": True, **a})

# every other chart's applicants still land in silver (nothing dropped):
# non-canonical copies AND canonical REMC charts (parked, never validated-counted)
for d in charts:
    if d["is_template"] or id(d) in _applicants_added:
        continue
    for a in d["applicants"]:
        applicant_rows.append({
            "pda_id": PDA_ID, "run_ts": RUN_TS,
            "county": d["county_key"] or d["filename"],
            "fips": dim.get((d["county_key"] or "").lower()),
            "event_id": ekey_to_id.get(d["event_key"]),
            "event_label": d["event_label"], "stage": d["stage"],
            "is_validated": False,
            "is_canonical": bool(d.get("is_canonical")), **a})

# per-event + Combined summaries (validated = stage >= 3 ONLY)
summary_rows = []
for scope_ev in events + [{"event_id": "ALL", "label": "Combined", "key": None}]:
    eid = scope_ev["event_id"]
    crs = [r for r in county_rows if eid == "ALL" or r["event_id"] == eid]
    vrs = [r for r in crs if r["stage"] >= 3]
    tot = round(sum(r["validated_total"] or 0 for r in vrs), 2)
    per_cty = {}
    for r in vrs:
        a = per_cty.setdefault(r["county"], {"total": 0.0,
                                             "threshold": r["county_threshold"]})
        a["total"] += r["validated_total"] or 0
        a["threshold"] = a["threshold"] or r["county_threshold"]
    gm = guide_math(per_cty, state_threshold)
    pend = {}
    for r in crs:
        if r["stage"] >= 3:
            continue
        e = pend.setdefault(r["county"], {"total": 0.0, "measured": False,
                                          "maxstage": 0})
        e["maxstage"] = max(e["maxstage"], r["stage"])
        if r["validated_total"] is not None:
            e["total"] += r["validated_total"]
            e["measured"] = True
    if eid == "ALL":
        for k in [k for k in pend
                  if any(x["county"] == k and x["stage"] >= 3 for x in crs)]:
            del pend[k]
    summary_rows.append({
        "pda_id": PDA_ID, "run_ts": RUN_TS, "event_id": eid,
        "event_label": scope_ev["label"],
        "validated_total": tot, "state_threshold": state_threshold,
        "pct_of_state": round(100 * tot / state_threshold, 1)
                        if state_threshold else None,
        "counties_total": len(scope),
        "counties_ready": sum(1 for r in crs if r["stage"] >= 3),
        "counties_met_100": sum(1 for a in per_cty.values()
                                if a["threshold"] and a["total"] >= a["threshold"]),
        "counties_met_50": sum(1 for a in per_cty.values() if a["threshold"] and
                               0.5 * a["threshold"] <= a["total"] < a["threshold"]),
        "applicants_n": sum(r["applicants_n"] or 0 for r in crs),
        "gm_full": gm["full"], "gm_n_full": gm["n_full"],
        "gm_half": gm["half"], "gm_n_half": gm["n_half"],
        "gm_half_counts": gm["half_counts"],
        "gm_below": gm["below"], "gm_n_below": gm["n_below"],
        "gm_gate_need": gm["gate_need"], "gm_gate75_ok": gm["gate75_ok"],
        "gm_countable": gm["countable"], "gm_pct_countable": gm["pct_countable"],
        "pending_review_total": round(sum(e["total"] for e in pend.values()
                                          if e["maxstage"] == 2), 2),
        "pending_review_n": sum(1 for e in pend.values() if e["maxstage"] == 2),
        "pending_pre_total": round(sum(e["total"] for e in pend.values()
                                       if e["maxstage"] < 2), 2),
        "pending_pre_n": sum(1 for e in pend.values() if e["maxstage"] < 2),
        "pending_unmeasured_n": sum(1 for e in pend.values() if not e["measured"]),
    })

# dollar conservation: sum of county rows == recomputed workbook totals
for eid in [e["event_id"] for e in events]:
    lhs = round(sum(r["validated_total"] or 0 for r in county_rows
                    if r["event_id"] == eid), 2)
    rhs = round(sum(d["total_calc"] for d in canonical.values()
                    if d["entity_type"] == "county"
                    and ekey_to_id.get(d["event_key"]) == eid), 2)
    if abs(lhs - rhs) > 0.005:
        raise RuntimeError(f"DOLLAR CONSERVATION FAILED for {eid}: "
                           f"county rows {lhs} != canonical charts {rhs}")
print("summaries:", [(s["event_id"], s["validated_total"], s["gm_countable"])
                     for s in summary_rows])

# COMMAND ----------

# MAGIC %md
# MAGIC ## pa_pdas_charta — the pa_pdas-compatible applicant table for THIS PDA
# MAGIC
# MAGIC One row per Table A subrecipient x county, in the EXISTING `pa_pdas`
# MAGIC table's column vocabulary (Year/Month/State/County/Applicant_Name/
# MAGIC Cat_A..G/Total + thresholds), enriched from the Chart A's (Comment,
# MAGIC Applicant_Type, Inspector) when they're in the drop. `pa_pdas` itself is
# MAGIC NEVER touched — the link is the shared natural key, exposed as
# MAGIC `Pda_Id = Year-Month-State` (build the same calculated column on the
# MAGIC pa_pdas side in Power BI and relate the two). **Verify the printed
# MAGIC Year/Month/State before trusting the run** — they come from the widgets,
# MAGIC falling back to the Table A's PDA-start date.

# COMMAND ----------

charta_rows, charta_audit = [], None
if ta is None:
    print("no Table A in drop — pa_pdas_charta skipped")
    health.append({"code": "CHARTA_SKIPPED",
                   "detail": "no Table A workbook — pa_pdas_charta not built"})
else:
    from datetime import date as _date
    _pda_date = ta.meta.get("pda_start") or ta.meta.get("incident_start") or ""
    _yr = PDA_YEAR or (_pda_date[:4] if _pda_date else "")
    _mo = PDA_MONTH or (
        ["January", "February", "March", "April", "May", "June", "July",
         "August", "September", "October", "November", "December"]
        [int(_pda_date[5:7]) - 1] if len(_pda_date) >= 7 else "")
    if not _yr or not _mo:
        raise RuntimeError("pda_year/pda_month widgets are blank and the Table A "
                           "carries no PDA-start date — fill the widgets in.")
    pa_pdas_ref = None
    if PA_PDAS_TABLE:
        pa_pdas_ref = [r.asDict() for r in spark.table(PA_PDAS_TABLE).collect()]
        print(f"pa_pdas link source: {PA_PDAS_TABLE} ({len(pa_pdas_ref)} rows)")
    # canonical county charts only (REMCs parked, duplicates superseded)
    _link_charts = [d for d in canonical.values() if d["entity_type"] == "county"]
    charta_rows, charta_audit = chb.build_charta_rows(
        ta, _link_charts,
        year=int(_yr), month=_mo,
        state=(ta.meta.get("state_code") or STATE),
        declaration_number=DECL_NUMBER,
        pa_pdas_rows=pa_pdas_ref)
    print(f"pa_pdas_charta: Pda_Id={charta_audit['pda_id']}  "
          f"rows={charta_audit['n_rows']}  ${charta_audit['row_total']:,.2f}  "
          f"counties={charta_audit['n_counties']} (met {charta_audit['n_met']})  "
          f"comments={charta_audit['n_comment']}"
          + (f"  linked={charta_audit['n_linked']}" if charta_audit["linkable"] else ""))
    for u in charta_audit["unmatched_chart_applicants"]:
        health.append({"code": "CHARTA_CHART_ONLY_APPLICANT",
                       "detail": f"{u['county']}: {u['applicant']} "
                                 f"(${u['total']:,.2f}) — {u['detail']}"})

# COMMAND ----------

# MAGIC %md
# MAGIC ## Write Delta tables

# COMMAND ----------

def write_table(name, rows, ddl, mode="overwrite", comment=None):
    full = f"{CATALOG}.{SCHEMA}.{name}"
    df = spark.createDataFrame(rows, schema=ddl)
    w = df.write.format("delta").mode(mode)
    if mode == "overwrite":
        w = w.option("overwriteSchema", "true")
    w.saveAsTable(full)
    if comment:
        c = comment.replace("'", "''")
        spark.sql(f"COMMENT ON TABLE {full} IS '{c}'")
    print(f"  {full}: {len(rows)} rows ({mode})")

CAT_DDL = ", ".join(f"cat_{c.lower()} double" for c in CATS)

write_table("bronze_chart_files", registry,
    "pda_id string, run_ts string, volume_path string, filename string, "
    "size_bytes long, modified_ts string, from_zip boolean, stage int, "
    "stage_basis string, sha256 string, kind string, parse_status string, "
    "parse_error string",
    comment="PDA Board file registry: every file found in the drop volume, with "
            "stage derived from its folder path. One row per file per run.")

silver_county = [{
    "pda_id": PDA_ID, "run_ts": RUN_TS,
    "county": d["county"], "county_key": d["county_key"],
    "county_source": d["county_source"], "entity_type": d["entity_type"],
    "event_id": ekey_to_id.get(d["event_key"]), "event_label": d["event_label"],
    "population": int(d["population"]) if d["population"] else None,
    "county_threshold": d["county_threshold"], "inspector": d["inspector"],
    "emergency_calc": d["emergency_calc"], "permanent_calc": d["permanent_calc"],
    "total_calc": d["total_calc"], "wb_emergency": d["wb_emergency"],
    "wb_permanent": d["wb_permanent"], "wb_total": d["wb_total"],
    "content_status": d["content_status"], "stage": d["stage"],
    "stage_label": STAGE_LABELS[d["stage"]], "stage_basis": d["stage_basis"],
    "is_canonical": bool(d.get("is_canonical")), "is_template": d["is_template"],
    "is_empty": d["is_empty"], "n_applicants": len(d["applicants"]),
    "n_flags": len(d["flags"]), "filename": d["filename"],
    "volume_path": d["volume_path"], "modified_ts": d["modified_ts"],
} for d in charts]
write_table("silver_chart_a_county", silver_county,
    "pda_id string, run_ts string, county string, county_key string, "
    "county_source string, entity_type string, event_id string, "
    "event_label string, population long, county_threshold double, "
    "inspector string, emergency_calc double, permanent_calc double, "
    "total_calc double, wb_emergency double, wb_permanent double, "
    "wb_total double, content_status string, stage int, stage_label string, "
    "stage_basis string, is_canonical boolean, is_template boolean, "
    "is_empty boolean, n_applicants int, n_flags int, filename string, "
    "volume_path string, modified_ts string",
    comment="One row per parsed Chart A workbook copy. Totals are RECOMPUTED "
            "from Cat A-G; wb_* are the workbook's own cells, kept for "
            "reconciliation only. is_canonical: highest stage wins, tie -> "
            "latest modified.")

write_table("silver_chart_a_applicant", applicant_rows,
    "pda_id string, run_ts string, county string, fips string, "
    "event_id string, event_label string, stage int, is_validated boolean, "
    "is_canonical boolean, applicant string, applicant_type string, "
    "status_raw string, status_norm string, " + CAT_DDL + ", "
    "total_calc double, wb_row_total double, comment string, comment_html string",
    comment="Applicant rows from every Chart A. comment = plain text with real "
            "line breaks (Power BI table + word wrap shows them); comment_html "
            "= same text with the workbook's bold/italic/underline runs and "
            "alt-Enter breaks as <b>/<i>/<u>/<br> (render with the HTML Content "
            "custom visual). Filter is_canonical for board figures.")

flag_rows = [{"pda_id": PDA_ID, "run_ts": RUN_TS, "filename": d["filename"],
              "county": d["county_key"], "event_id": ekey_to_id.get(d["event_key"]),
              "code": f["code"], "detail": f["detail"]}
             for d in charts for f in d["flags"]]
write_table("silver_chart_a_flags", flag_rows,
    "pda_id string, run_ts string, filename string, county string, "
    "event_id string, code string, detail string",
    comment="Per-workbook parser anomalies — nothing is silently dropped.")

if ta is not None:
    write_table("silver_table_a_meta",
        [{"pda_id": PDA_ID, "run_ts": RUN_TS, **ta.meta}],
        "pda_id string, run_ts string, format string, state_code string, "
        "region string, state_population long, state_pci double, "
        "county_pci double, event_type string, pda_start string, "
        "incident_start string, incident_end string, incident_name string, "
        "state_name string",
        comment="Table A Input Sheet indicators — the year's PCIs and state "
                "population come from HERE, never hardcoded. format: v2 = the "
                "RVAR-era template (IN 2026), legacy = the SummaryPage/PCI "
                "Indicator template (MI/WI 2026) — both parse by label.")
    write_table("silver_table_a_county",
        [{"pda_id": PDA_ID, "run_ts": RUN_TS, **c} for c in ta.counties],
        "pda_id string, run_ts string, county string, population long, "
        + CAT_DDL + ", total_entered double, wb_total double, "
        "county_pci_target double, target_label string")
    write_table("silver_table_a_subrecipient",
        [{"pda_id": PDA_ID, "run_ts": RUN_TS, **s} for s in ta.subrecipients],
        "pda_id string, run_ts string, subrecipient string, county string, "
        "status string, " + CAT_DDL + ", total_calc double")
    write_table("silver_reductions",
        [{"pda_id": PDA_ID, "run_ts": RUN_TS, **r} for r in ta.reductions],
        "pda_id string, run_ts string, county string, applicant string, "
        "cat string, original double, eligible double, reduction double, "
        "reduction_category string, notes string")

COUNTY_DDL = ("pda_id string, run_ts string, county string, fips string, "
    "event_id string, event_label string, stage int, stage_label string, "
    "is_validated boolean, population long, county_threshold double, "
    "validated_total double, pct_of_target double, money_tier string, "
    "emergency double, permanent double, " + CAT_DDL + ", "
    "applicants_n int, applicants_complete int, inspector string, "
    "content_status string, source_file string, volume_path string, n_flags int")
write_table("gold_county_status", county_rows, COUNTY_DDL,
    comment="Canonical county x event rows — the board's map/table. Figures "
            "count toward rollups ONLY where is_validated (stage >= 3, through "
            "Lead Review); below that they are pending.")

SUMMARY_DDL = ("pda_id string, run_ts string, event_id string, "
    "event_label string, validated_total double, state_threshold double, "
    "pct_of_state double, counties_total int, counties_ready int, "
    "counties_met_100 int, counties_met_50 int, applicants_n int, "
    "gm_full double, gm_n_full int, gm_half double, gm_n_half int, "
    "gm_half_counts boolean, gm_below double, gm_n_below int, "
    "gm_gate_need double, gm_gate75_ok boolean, gm_countable double, "
    "gm_pct_countable double, pending_review_total double, "
    "pending_review_n int, pending_pre_total double, pending_pre_n int, "
    "pending_unmeasured_n int")
write_table("gold_pda_summary", summary_rows, SUMMARY_DDL,
    comment="Per-event (+ ALL) rollup. gm_* = PDA Guide (July 2025, p.56) "
            "statewide inclusion math: >=100% counties always count; 50-99% "
            "only if >=100% counties alone cover 75% of the statewide PCI; "
            "<50% never counts.")

health_rows = [{"pda_id": PDA_ID, "run_ts": RUN_TS, **h} for h in health]
write_table("gold_data_health", health_rows,
    "pda_id string, run_ts string, code string, detail string",
    comment="Data Health page: every anomaly this run, nothing silent.")

# pa_pdas_charta accumulates ACROSS PDAs (like pa_pdas itself): delete this
# PDA's rows, append the fresh ones — other PDAs' rows are never touched.
if charta_rows:
    CHARTA_DDL = ("Charta_Id string, Pda_Id string, Year int, Month string, "
        "State string, State_Pop long, State_Threshold double, "
        "Declaration_Number string, County string, Met_Threshold boolean, "
        "County_Pop long, County_Threshold double, Applicant_Id string, "
        "SLTT_Organization_Id string, Applicant_Name string, "
        + ", ".join(f"Cat_{c} double" for c in CATS) + ", Total double, "
        "Status string, Applicant_Type string, Comment string, "
        "Comment_Html string, Inspector string, Source_File string, "
        "In_Pa_Pdas boolean, Pa_Pdas_Applicant_Name string")
    _full = f"{CATALOG}.{SCHEMA}.gold_pa_pdas_charta"
    _df = spark.createDataFrame(charta_rows, schema=CHARTA_DDL)
    if spark.catalog.tableExists(_full):
        spark.sql(f"DELETE FROM {_full} WHERE Pda_Id = '{charta_audit['pda_id']}'")
        _df.write.format("delta").mode("append").saveAsTable(_full)
    else:
        _df.write.format("delta").mode("overwrite").saveAsTable(_full)
        spark.sql(f"COMMENT ON TABLE {_full} IS 'Applicant x county rows per "
                  "PDA in the pa_pdas column vocabulary (pa_pdas is never "
                  "modified; join on Pda_Id = Year-Month-State). Sourced from "
                  "the Table A Input Sheet; Comment/Applicant_Type/Inspector "
                  "enriched from Chart A workbooks when present. Blank "
                  "categories are null (pa_pdas convention); Total = sum of "
                  "non-null categories.'")
    print(f"  {_full}: {len(charta_rows)} rows (Pda_Id {charta_audit['pda_id']} replaced)")
    # CSV copy on the volume for the by-hand Power BI import path
    _csvp = os.path.join(DROP, f"pa_pdas_charta_{charta_audit['pda_id']}.csv")
    chb.write_charta_csv(charta_rows, _csvp)
    print(f"  csv: {_csvp}")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Snapshot append (THE TICKER) — skipped when nothing changed

# COMMAND ----------

snap_c, snap_s = "gold_snapshot_county", "gold_snapshot_summary"
changed = True
try:
    last = spark.sql(f"""
        SELECT county, event_id, stage, validated_total
        FROM {CATALOG}.{SCHEMA}.{snap_c}
        WHERE pda_id = '{PDA_ID}'
          AND run_ts = (SELECT max(run_ts) FROM {CATALOG}.{SCHEMA}.{snap_c}
                        WHERE pda_id = '{PDA_ID}')
        """).collect()
    prev = sorted((r.county, r.event_id, r.stage, r.validated_total) for r in last)
    cur = sorted((r["county"], r["event_id"], r["stage"], r["validated_total"])
                 for r in county_rows)
    changed = prev != cur
except Exception:
    pass  # first run: table doesn't exist yet

if changed:
    write_table(snap_c, county_rows, COUNTY_DDL, mode="append",
                comment="Append-only per-run county snapshots — the ticker/movers "
                        "source. One batch per run_ts; unchanged runs skipped.")
    write_table(snap_s, summary_rows, SUMMARY_DDL, mode="append",
                comment="Append-only per-run summary snapshots — validated $ and "
                        "guide-math countable $ over time vs the state threshold.")
else:
    print("no county changed since last snapshot — ticker append skipped")

shutil.rmtree(work, ignore_errors=True)
gm_all = next(s for s in summary_rows if s["event_id"] == "ALL")
print(f"\nDONE {RUN_TS}: {len(scope)} counties, {len(events)} events; "
      f"validated ${gm_all['validated_total']:,.2f}, "
      f"countable ${gm_all['gm_countable']:,.2f}"
      + (f" of ${state_threshold:,.2f}" if state_threshold else " (no state threshold)"))

# COMMAND ----------

# MAGIC %md
# MAGIC ### Movers since the previous snapshot (ad-hoc check / Power BI source)
# MAGIC ```sql
# MAGIC WITH runs AS (SELECT DISTINCT run_ts FROM <cat>.<schema>.gold_snapshot_county
# MAGIC               WHERE pda_id = '<pda>' ORDER BY run_ts DESC LIMIT 2)
# MAGIC SELECT c.county, c.event_id,
# MAGIC        c.validated_total - p.validated_total AS delta_total,
# MAGIC        p.stage AS from_stage, c.stage AS to_stage
# MAGIC FROM   <cat>.<schema>.gold_snapshot_county c
# MAGIC JOIN   <cat>.<schema>.gold_snapshot_county p
# MAGIC        ON p.county = c.county AND p.event_id = c.event_id
# MAGIC       AND p.run_ts = (SELECT min(run_ts) FROM runs)
# MAGIC WHERE  c.run_ts = (SELECT max(run_ts) FROM runs)
# MAGIC   AND (abs(coalesce(c.validated_total,0) - coalesce(p.validated_total,0)) > 0.005
# MAGIC        OR c.stage <> p.stage);
# MAGIC ```
