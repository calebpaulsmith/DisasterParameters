# Databricks notebook source
# MAGIC %md
# MAGIC # 03 — Render the board: workbooks → one self-contained `board.html` per PDA
# MAGIC
# MAGIC **What you get:** one portable HTML dashboard per PDA — threshold clock,
# MAGIC county map, county table, Chart A drill-downs — rendered inline in the
# MAGIC last cell AND written back to the volume for download/email. The file
# MAGIC makes **zero network requests** (font + data baked in), so it opens on
# MAGIC any work laptop from a double-click. **No Delta tables or Spark are used
# MAGIC unless you opt in** via the widgets below.
# MAGIC
# MAGIC ---
# MAGIC ## How much do I have to upload? (three tiers)
# MAGIC
# MAGIC A cloud notebook cannot read your C: drive, so *something* must land in
# MAGIC the volume — but it can be as little as one file per PDA:
# MAGIC
# MAGIC | Tier | You upload | You get |
# MAGIC |---|---|---|
# MAGIC | **Minimal** | ONLY the Table A master workbook (one ~1MB file) | The full board — clock, map, county table with per-county totals and applicant counts straight from the Table A. No Chart A's needed. What you lose: per-applicant narrative comments, applicant types, inspector names (those exist only in Chart A's). Counties show a `FROM_TABLE_A` health note. |
# MAGIC | **Full** | Table A + the Chart A's folder/zip (SharePoint → Download) | Everything above PLUS the applicant drill-downs with validated-comment narratives, types, inspectors. |
# MAGIC | **No Databricks at all** | Nothing | On any machine with python + openpyxl: `python pipeline.py --drop "<folder>" --manifest manifests/<pda>.json --out out_x` produces the identical HTML from a local directory. Use Databricks only when you want the board built/stored where colleagues can run it too. |
# MAGIC
# MAGIC Upload shortcut from your PC (instead of drag-and-drop):
# MAGIC `databricks fs cp -r "C:\...\MI May 2026" dbfs:/Volumes/<catalog>/<schema>/<volume>/MI May 2026`
# MAGIC
# MAGIC ---
# MAGIC ## Volume layout (one folder per PDA under `drop_root`)
# MAGIC
# MAGIC ```
# MAGIC <drop_root>/
# MAGIC ├── MI May 2026/            ← one folder per PDA (any name)
# MAGIC │   ├── Table A - ….xlsx     REQUIRED (indicators come from it, never code)
# MAGIC │   ├── <Chart A's>          optional — zip or folders, comments/types/inspectors
# MAGIC │   ├── query.xlsx           live PDAs only (SharePoint flat view → Export to Excel)
# MAGIC │   ├── query.iqy            the web-query file saved WITH that export — it carries
# MAGIC │   │                        the site host + this PDA's root folder, so every file
# MAGIC │   │                        and county-folder link resolves (drop it for ANY PDA,
# MAGIC │   │                        live or complete; it is also loadable in the board
# MAGIC │   │                        itself under Admin → SharePoint links)
# MAGIC │   └── pda.json             optional identity (below)
# MAGIC ├── _ref/history_mi.json    optional prior-FEMA-history (notebook 02 writes it)
# MAGIC └── _code/…                 fallback code location (next cell)
# MAGIC ```
# MAGIC
# MAGIC **`pda.json`** pins identity; anything missing is derived (state from the
# MAGIC Table A, id/title from the folder name, mode from the widgets):
# MAGIC `{"pda_id":"MI_PDA_May_2026","title":"MI PA PDA - May 2026","state":"MI",
# MAGIC   "complete":true,"met_only":true,
# MAGIC   "master_folder":"https://…/Damage Data/Counties",
# MAGIC   "sp_folder":"MI PDA May 2026"}`
# MAGIC
# MAGIC **`sp_folder`** is only needed when the dropped `query.xlsx`/`query.iqy` is a
# MAGIC LIBRARY-WIDE query covering several PDAs: it names this PDA's folder under that
# MAGIC root. A single-PDA query, or a name the build can match (state + month + year),
# MAGIC needs nothing.
# MAGIC
# MAGIC ---
# MAGIC ## What each widget does (the options, in plain terms)
# MAGIC
# MAGIC | Widget | What it controls | What you get |
# MAGIC |---|---|---|
# MAGIC | `drop_root` | The volume folder holding one subfolder per PDA | Everything under it that doesn't start with `_` is treated as a PDA |
# MAGIC | `pda_folders` | `*` = build every PDA folder; or a comma list (`MI May 2026,WI May 2026`) | One board per folder — build one PDA or the whole shelf in a single run |
# MAGIC | `complete_default` | COMPLETE mode for folders whose pda.json doesn't say | **yes** = finished-PDA board: clock trimmed to the outcome tiers, county table = County / Applicants / Validated $ / Folder-link, no admin chrome, blue map. **no** = live-tracking board with stages and pending buckets |
# MAGIC | `met_only_default` | Exclude counties that never reached their county indicator | **yes** = only qualifying counties on the map/table; the excluded count + $ is disclosed on the clock footer ("under-threshold excluded N · $X"). **no** = every county, hero matches the workbook's all-county Validated Total |
# MAGIC | `master_folder_default` | Base URL for the county Folder links (COMPLETE table) | Set it to the SharePoint `…/Damage Data/Counties` URL and every county row links to its folder; blank = **derived from the PDA folder's `query.iqy`** (host + root folder + `Damage Data/Counties`), and only if there is no .iqy either does the Folder column show "—". Either way the board's Admin panel can load another `.iqy` and re-point the links without a rebuild |
# MAGIC | `write_tables` | OPT-IN Delta tables | **no** (default) = pure HTML, zero tables. **yes** = also writes `gold_county_status_boards` + `gold_pda_summary_boards` for Power BI (each run replaces only its own PDA's rows). The full medallion incl. `gold_pa_pdas_charta` stays notebook 01's job |
# MAGIC | `auto_history` | Prior-FEMA-history card in the drill-downs | **no** = use `history_<state>.json` if present, else the card is simply absent. **yes** = when missing, resolve the OpenFEMA CATALOG tables via `openfema_columns_table` and run notebook 02 to build it — never the public API |
# MAGIC | `openfema_columns_table` / `pa_summaries_table` / `declarations_table` | Where OpenFEMA lives in your catalog | The columns table is scanned to find the two source tables; the two overrides pin them directly if the scan guesses wrong |
# MAGIC | `catalog` / `schema` | Only used when `write_tables=yes` or `auto_history=yes` | Where the optional tables / history land |
# MAGIC
# MAGIC ---
# MAGIC ## Code + reference files (one-time)
# MAGIC Put the pdaboard files next to this notebook in the Workspace (keep the
# MAGIC folder shape), **or** — usually easier — drag the whole set into
# MAGIC `<drop_root>/_code/` in Catalog Explorer:
# MAGIC `chart_a_parser.py`, `sp_filetree.py`, `pipeline.py`, `pa_pdas_charta.py`,
# MAGIC `templates/board.html`, `data/dim_county_<st>.csv`,
# MAGIC `data/<st>_counties_geo.json` (dims committed for in/mi/wi — other states:
# MAGIC `python build_dim_county.py <st> <any chart>.xlsx <counties_us.json>`).

# COMMAND ----------

# MAGIC %pip install "openpyxl>=3.1" --quiet

# COMMAND ----------

dbutils.widgets.text("drop_root", "/Volumes/recovery/pda_ops/pda_inbox",
                     "Drop root (one subfolder per PDA)")
dbutils.widgets.text("pda_folders", "*",
                     "PDA folders to build: * = all, or comma-separated names")
dbutils.widgets.dropdown("complete_default", "yes", ["yes", "no"],
                         "Treat PDAs as COMPLETE when pda.json doesn't say")
dbutils.widgets.dropdown("met_only_default", "yes", ["yes", "no"],
                         "Exclude counties under their county indicator (COMPLETE boards)")
dbutils.widgets.text("master_folder_default", "",
                     "Master folder URL default (county links, COMPLETE mode)")
dbutils.widgets.dropdown("write_tables", "no", ["no", "yes"],
                         "Also write gold_county_status/gold_pda_summary Delta tables")
dbutils.widgets.text("catalog", "recovery", "Catalog (only if write_tables)")
dbutils.widgets.text("schema", "pda_ops", "Schema (only if write_tables)")
dbutils.widgets.dropdown("auto_history", "no", ["no", "yes"],
                         "Build missing history_<state>.json via notebook 02")
dbutils.widgets.text("openfema_columns_table", "openfema.odp.openfema_columns",
                     "OpenFEMA columns table (dataset -> table resolver)")
dbutils.widgets.text("pa_summaries_table", "",
                     "Override: PA FundedProjectsSummaries table ('' = resolve)")
dbutils.widgets.text("declarations_table", "",
                     "Override: DisasterDeclarationsSummaries table ('' = resolve)")
dbutils.widgets.text("history_notebook", "02_openfema_history",
                     "Notebook 02 path (relative to this folder)")

DROP_ROOT = dbutils.widgets.get("drop_root").rstrip("/")
PDA_FOLDERS = dbutils.widgets.get("pda_folders").strip()
COMPLETE_DEFAULT = dbutils.widgets.get("complete_default") == "yes"
MET_ONLY_DEFAULT = dbutils.widgets.get("met_only_default") == "yes"
MASTER_DEFAULT = dbutils.widgets.get("master_folder_default").strip()
WRITE_TABLES = dbutils.widgets.get("write_tables") == "yes"
CATALOG = dbutils.widgets.get("catalog").strip()
SCHEMA = dbutils.widgets.get("schema").strip()
AUTO_HISTORY = dbutils.widgets.get("auto_history") == "yes"
COLS_TABLE = dbutils.widgets.get("openfema_columns_table").strip()
OVR_PA_TBL = dbutils.widgets.get("pa_summaries_table").strip()
OVR_DECL_TBL = dbutils.widgets.get("declarations_table").strip()
HIST_NB = dbutils.widgets.get("history_notebook").strip()

# COMMAND ----------

# MAGIC %md
# MAGIC ## Locate the code (workspace beside this notebook, else `<drop>/_code`)

# COMMAND ----------

import json, os, re, shutil, sys, tempfile, traceback
from pathlib import Path

def _code_base():
    try:
        nb = dbutils.notebook.entry_point.getDbutils().notebook().getContext() \
                    .notebookPath().get()
        wsdir = "/Workspace" + os.path.dirname(nb)
        if os.path.exists(os.path.join(wsdir, "pipeline.py")):
            return wsdir
        # also allow the files one level up (notebook inside pdaboard/databricks/)
        parent = os.path.dirname(wsdir)
        if os.path.exists(os.path.join(parent, "pipeline.py")):
            return parent
    except Exception:
        pass
    vp = os.path.join(DROP_ROOT, "_code")
    if os.path.exists(os.path.join(vp, "pipeline.py")):
        return vp
    raise FileNotFoundError(
        "pipeline.py not found next to this notebook (or one folder up) nor in "
        f"{DROP_ROOT}/_code — upload the pdaboard files per the header cell.")

BASE = _code_base()
if BASE not in sys.path:
    sys.path.insert(0, BASE)
import chart_a_parser  # noqa: F401  (must import first — pipeline depends on it)
import pipeline as pl
from chart_a_parser import event_key, parse_table_a, sniff_workbook
print(f"code: {BASE}")
for req in ("templates/board.html",):
    if not os.path.exists(os.path.join(BASE, req)):
        raise FileNotFoundError(f"{req} missing under {BASE}")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Discover PDA folders + identity

# COMMAND ----------

def detect_state(folder: Path):
    """Cheap pre-scan: find a Table A, read its state code."""
    for p in sorted(folder.rglob("*.xlsx")):
        if p.name.startswith("~$"):
            continue
        if any(seg.startswith("_") for seg in p.relative_to(folder).parts[:-1]):
            continue
        if sniff_workbook(p) == "table_a":
            ta = parse_table_a(p)
            return (ta.meta.get("state_code") or "").upper() or None
    return None

root = Path(DROP_ROOT)
if not root.is_dir():
    raise FileNotFoundError(f"drop_root {DROP_ROOT} does not exist")
wanted = None if PDA_FOLDERS in ("", "*") else \
    {w.strip().lower() for w in PDA_FOLDERS.split(",") if w.strip()}
pdas = []
for f in sorted(p for p in root.iterdir()
                if p.is_dir() and not p.name.startswith("_")):
    if wanted is not None and f.name.lower() not in wanted:
        continue
    cfg = {}
    pj = f / "pda.json"
    if pj.exists():
        cfg = json.loads(pj.read_text(encoding="utf-8"))
    state = (cfg.get("state") or detect_state(f) or "").upper()
    if not state:
        print(f"SKIP {f.name}: no state (no Table A found and no pda.json)")
        continue
    slug = re.sub(r"[^A-Za-z0-9]+", "_", f.name).strip("_")
    manifest = {
        "pda_id": cfg.get("pda_id", slug),
        "title": cfg.get("title", f.name),
        "state": state,
        "complete": bool(cfg.get("complete", COMPLETE_DEFAULT)),
        "met_only": bool(cfg.get("met_only", MET_ONLY_DEFAULT)),
        "master_folder": cfg.get("master_folder", MASTER_DEFAULT),
        "sharepoint_base": cfg.get("sharepoint_base", ""),
        "stale_hours": cfg.get("stale_hours", 876000),
        "events": cfg.get("events", []),
    }
    for ev in manifest["events"]:
        ev["key"] = event_key(ev["label"])
    pdas.append((f, manifest))
    print(f"PDA {manifest['pda_id']}: state={state} complete={manifest['complete']} "
          f"({f.name})")
if not pdas:
    raise RuntimeError("no PDA folders matched — check drop_root/pda_folders")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Prior-history JSON per state (existing file, else notebook 02 via the
# MAGIC ## OpenFEMA columns table — catalog only, never the public API)

# COMMAND ----------

STATE_NAMES = {"IL": "Illinois", "IN": "Indiana", "MI": "Michigan",
               "MN": "Minnesota", "OH": "Ohio", "WI": "Wisconsin"}

def _resolve_openfema_tables():
    """Find the two source tables via the OpenFEMA columns table. Tolerant of
    schema: scans string columns for the dataset names; prefers any value that
    looks like a catalog.schema.table reference on the same row."""
    if OVR_PA_TBL and OVR_DECL_TBL:
        return OVR_PA_TBL, OVR_DECL_TBL
    want = {"publicassistancefundedprojectssummaries": None,
            "disasterdeclarationssummaries": None}
    try:
        rows = [r.asDict() for r in spark.table(COLS_TABLE).collect()]
    except Exception as e:
        print(f"openfema columns table unreadable ({COLS_TABLE}): {e}")
        rows = []
    norm = lambda s: re.sub(r"[^a-z0-9]", "", str(s).lower())
    for r in rows:
        vals = {k: v for k, v in r.items() if isinstance(v, str)}
        hit = next((w for w in want
                    if any(norm(v) == w or w in norm(v) for v in vals.values())), None)
        if hit and want[hit] is None:
            ref = next((v for v in vals.values()
                        if isinstance(v, str) and v.count(".") == 2), None)
            want[hit] = ref or f"openfema.odp.{hit}"
    pa = OVR_PA_TBL or want["publicassistancefundedprojectssummaries"]
    de = OVR_DECL_TBL or want["disasterdeclarationssummaries"]
    # last resort: guess common namings and test
    def _try(cands):
        for c in cands:
            try:
                if spark.catalog.tableExists(c):
                    return c
            except Exception:
                pass
        return None
    pa = pa or _try(["openfema.odp.publicassistancefundedprojectssummaries",
                     "openfema.odp.public_assistance_funded_projects_summaries"])
    de = de or _try(["openfema.odp.disasterdeclarationssummaries",
                     "openfema.odp.disaster_declarations_summaries"])
    return pa, de

def history_path_for(state: str):
    st = state.lower()
    cands = [Path(BASE) / "data" / f"history_{st}.json",
             root / "_ref" / f"history_{st}.json"]
    for c in cands:
        if c.exists():
            return c
    if not AUTO_HISTORY:
        print(f"history_{st}.json not found — board renders without the "
              "prior-history card (auto_history=no)")
        return None
    pa_tbl, de_tbl = _resolve_openfema_tables()
    if not (pa_tbl and de_tbl):
        print(f"could not resolve OpenFEMA tables for {state} — set the "
              "pa_summaries_table/declarations_table widgets")
        return None
    out_dir = root / "_ref"
    try:
        out_dir.mkdir(exist_ok=True)
        print(f"running {HIST_NB} for {state} (pa={pa_tbl}, decl={de_tbl}) …")
        dbutils.notebook.run(HIST_NB, 3600, {
            "catalog": CATALOG, "schema": SCHEMA,
            "pa_summaries_table": pa_tbl, "declarations_table": de_tbl,
            "state": state, "state_name": STATE_NAMES.get(state, state),
            "history_out": str(out_dir)})
        p = out_dir / f"history_{st}.json"
        return p if p.exists() else None
    except Exception as e:
        print(f"notebook 02 failed for {state}: {e} — continuing without history")
        return None

# COMMAND ----------

# MAGIC %md
# MAGIC ## Build each board (writes `board_<pda_id>.html` back to the PDA folder;
# MAGIC ## falls back to /tmp if the volume denies writes)

# COMMAND ----------

built = []      # (manifest, board dict, html string, html path or None)
hist_cache = {}
for folder, manifest in pdas:
    print(f"\n=== {manifest['pda_id']} ===")
    try:
        st = manifest["state"]
        if st not in hist_cache:
            hist_cache[st] = history_path_for(st)
        # out dir on the volume keeps snapshots.jsonl (the ticker) across runs
        out_dir = folder / "out"
        try:
            out_dir.mkdir(exist_ok=True)
            probe = out_dir / ".w"
            probe.write_text("x"); probe.unlink()
        except Exception:
            out_dir = Path(tempfile.mkdtemp(prefix=f"pda_{manifest['pda_id']}_"))
            print(f"volume not writable — outputs to {out_dir}")
        board = pl.build(folder, manifest, out_dir, history_path=hist_cache[st])
        html = (out_dir / "board.html").read_text(encoding="utf-8")
        dest = None
        try:
            dest = folder / f"board_{manifest['pda_id']}.html"
            dest.write_text(html, encoding="utf-8")
            print(f"wrote {dest}")
        except Exception as e:
            dest = Path(tempfile.gettempdir()) / f"board_{manifest['pda_id']}.html"
            dest.write_text(html, encoding="utf-8")
            print(f"volume write failed ({e}) — saved {dest}; download via the "
                  "last cell's inline view or copy the file out")
        built.append((manifest, board, html, str(dest)))
    except Exception:
        print(f"BUILD FAILED for {manifest['pda_id']}:\n{traceback.format_exc()}")
if not built:
    raise RuntimeError("no board built — see errors above")
print(f"\n{len(built)} board(s) built")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Optional Delta tables (Power BI) — `write_tables=yes` only

# COMMAND ----------

if WRITE_TABLES:
    from chart_a_parser import CATS
    CAT_DDL = ", ".join(f"cat_{c.lower()} double" for c in CATS)
    spark.sql(f"CREATE SCHEMA IF NOT EXISTS {CATALOG}.{SCHEMA}")
    for manifest, board, _html, _p in built:
        pid = manifest["pda_id"]
        crows = [{"pda_id": pid, "run_ts": board["generated"],
                  **{k: v for k, v in r.items() if k not in ("cats", "flags")},
                  **{f"cat_{c.lower()}": (r["cats"] or {}).get(c) for c in CATS}}
                 for r in board["counties"]]
        srows = [{"pda_id": pid, "run_ts": board["generated"], "event_id": eid,
                  "validated_total": s["validated_total"],
                  "state_threshold": s["state_threshold"],
                  "pct_of_state": s["pct_of_state"],
                  "counties_total": s["counties_total"],
                  "counties_ready": s["counties_ready"],
                  "counties_met_100": s["counties_met_100"],
                  "counties_met_50": s["counties_met_50"],
                  "applicants_n": s["applicants_n"],
                  "gm_countable": s["guide_math"]["countable"],
                  "gm_gate75_ok": s["guide_math"]["gate75_ok"]}
                 for eid, s in board["summaries"].items()]
        for name, rows, ddl in (
            ("gold_county_status_boards", crows,
             "pda_id string, run_ts string, county string, fips string, "
             "event_id string, event_label string, stage int, stage_label string, "
             "ingested boolean, population long, county_threshold double, "
             "validated_total double, pct_of_target double, money_tier string, "
             "emergency double, permanent double, applicants_n int, "
             "applicants_complete int, inspector string, content_status string, "
             "source_file string, sp_url string, last_touch string, "
             "last_touch_by string, " + CAT_DDL),
            ("gold_pda_summary_boards", srows,
             "pda_id string, run_ts string, event_id string, "
             "validated_total double, state_threshold double, pct_of_state double, "
             "counties_total int, counties_ready int, counties_met_100 int, "
             "counties_met_50 int, applicants_n int, gm_countable double, "
             "gm_gate75_ok boolean")):
            full = f"{CATALOG}.{SCHEMA}.{name}"
            df = spark.createDataFrame(rows, schema=ddl)
            if spark.catalog.tableExists(full):
                spark.sql(f"DELETE FROM {full} WHERE pda_id = '{pid}'")
                df.write.format("delta").mode("append").saveAsTable(full)
            else:
                df.write.format("delta").mode("overwrite").saveAsTable(full)
            print(f"  {full}: {len(rows)} rows (pda {pid} replaced)")
    print("For the full medallion set (silver applicants/flags, snapshots, "
          "pa_pdas_charta) run notebook 01 — this cell writes the two "
          "board-level dashboard tables only.")
else:
    print("write_tables=no — skipped (the board.html files are the product)")

# COMMAND ----------

# MAGIC %md
# MAGIC ## View the board(s) — this IS the shareable file, rendered inline

# COMMAND ----------

for manifest, board, html, dest in built:
    s = board["summaries"]["ALL"]
    print(f"{manifest['pda_id']}: validated ${s['validated_total']:,.2f} · "
          f"countable ${s['guide_math']['countable']:,.2f} of "
          f"${s['state_threshold']:,.2f} · file: {dest}")
displayHTML(built[-1][2])
