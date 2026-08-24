# PDA Board — Databricks notebooks

The Databricks port of the local pdaboard pipeline (see `../CLAUDE.md` and
`../../docs/pda-databricks-dashboard-plan.md`). Three notebooks, all in
Databricks notebook-source format — import them via **Workspace → Import**
(they render as notebooks with markdown cells).

**Start with 03 if you just want the board.** `03_render_board` is the
no-tables path: drop each PDA's workbooks in a volume folder, run, get one
self-contained `board_<pda_id>.html` per PDA (rendered inline + written to the
volume — download and email it; it makes zero network requests). Its header
cells are the step-by-step SharePoint download/upload guide. Delta tables are
opt-in (`write_tables`); the full medallion (silver applicant rows, snapshots,
`gold_pa_pdas_charta`) remains notebook 01. Prior-history comes from
`history_<state>.json` (notebook 02) — with `auto_history=yes`, 03 resolves
the OpenFEMA catalog tables via the workspace's **OpenFEMA columns** table
and runs 02 itself. Completed PDAs: set `complete` in `pda.json` (or the
`complete_default` widget) → COMPLETE mode (see ../CLAUDE.md).

## Setup (once)

1. Create the catalog objects (or reuse your sandbox):
   `recovery.pda_ops` schema + volume `/Volumes/recovery/pda_ops/pda_inbox/`.
2. **Import both notebooks** into a Workspace folder, and **upload
   `../chart_a_parser.py` AND `../pa_pdas_charta.py` into the same folder**
   (notebook 01 imports both — single source of truth, do not fork them).
   Alternative: put them at `<drop>/_code/*.py` in the volume.
3. Optional but recommended: put `../data/dim_county_in.csv` at
   `<drop>/_ref/dim_county_in.csv` (or load it as a `dim_county` table) so
   county rows carry FIPS for the map join.

## The refresh loop

1. In SharePoint, open `Damage Data/Chart A's/` → Download (zip) — or copy
   from the synced OneDrive folder. **Chart A pipeline folder only**, not the
   `Counties/` working files.
2. Drop it (zip or folder — subfolders preserved) into
   `/Volumes/.../pda_inbox/<pda_id>/`. Drop the Table A master workbook too if
   you have it — that's where the state PCI / population indicators come from.
3. Run **01_parse_chart_a** (or wire it to a job with a file-arrival trigger
   on the volume). Each run overwrites the current tables and appends a
   ticker snapshot (skipped when nothing changed).

Stage is derived from the folder each file sits in (`1. For PDA Lead
Review` → 2, `2. Ready for Table A`/`Validated` → 3, `Entered in Table A` → 4);
files with no stage folder get the `default_stage` widget (2 — everything in
the pipeline folder has at least been submitted). Zips are expanded in place
and inner folder paths count for stage.

**02_openfema_history** reads the workspace's catalog copies of the two
OpenFEMA datasets (point the `pa_summaries_table` / `declarations_table`
widgets at them — no public-API calls) and writes the `hist_*` tables plus
`history_<state>.json` to the volume in the exact shape
`pipeline.load_history()` / the board template consumes. Re-run whenever a
fresh history snapshot is wanted (weekly is plenty — obligations reconcile
slowly). It FAILS (keeping the last good output) if dollar conservation
breaks.

## Tables

Notebook 01: `bronze_chart_files`, `silver_chart_a_county`,
`silver_chart_a_applicant`, `silver_chart_a_flags`, `silver_table_a_*`,
`silver_reductions`, `gold_county_status`, `gold_pda_summary`,
`gold_data_health`, `gold_snapshot_county` / `gold_snapshot_summary`
(append-only ticker), and `gold_pa_pdas_charta` (below).

## gold_pa_pdas_charta — the pa_pdas companion table

One row per Table A subrecipient x county per PDA, in the EXISTING `pa_pdas`
table's column vocabulary (`Year/Month/State/State_Pop/State_Threshold/
Declaration_Number/County/Met_Threshold/County_Pop/County_Threshold/
Applicant_Name/Cat_A..G/Total`) plus charta extras (`Status`,
`Applicant_Type`, `Comment`, `Comment_Html`, `Inspector`) and keys
(`Charta_Id` unique per row, `Pda_Id = Year-Month-State`). Built by
`../pa_pdas_charta.py` (same module locally and here).

- **`pa_pdas` is never modified.** It has no id column, so the link is the
  shared natural key: create the same `Pda_Id` calculated column on the
  pa_pdas side in Power BI (`[Year] & "-" & [Month] & "-" & [State]`) and
  relate the tables. Optionally point the `pa_pdas_table` widget at the
  existing table to also get a best-effort row-level link
  (`In_Pa_Pdas`/`Pa_Pdas_Applicant_Name`) — pa_pdas names were hand-curated
  (multi-county applicants live under County="Multiple"), so no match is
  normal, especially when the charta import lands BEFORE the pa_pdas row.
- **Run identity**: verify/fill the `pda_year` / `pda_month` /
  `declaration_number` widgets; blank year/month derive from the Table A's
  PDA-start date and are printed — check them.
- The table ACCUMULATES across PDAs: each run replaces only its own
  `Pda_Id` rows. A ready-to-import CSV copy also lands on the volume
  (`<drop>/pa_pdas_charta_<Pda_Id>.csv`).
- Dollars come from the Table A (the same grain pa_pdas was built from);
  Chart A's only enrich (comments/types/inspectors). A Table A-only drop
  still builds the table (`NO_CHART_A` health note). Blank categories are
  null, matching pa_pdas.

Both **Table A template generations** parse: the RVAR-era v2 (IN 2026) and
the legacy SummaryPage/PCI-Indicator era (MI/WI 2026) — labels, not fixed
cells. Chart A's comments sheet may be `Comments` or `Deduction Comments`.
Legacy-era filenames carry no incident-period parenthetical; the run
synthesizes one event from the Table A incident period (`NO_EVENT_LABELS`
health note).

Notebook 02: `hist_disasters`, `hist_county_declarations`,
`hist_statewide_designations`, `hist_applicant_disaster`, `hist_audit`,
plus `history_<state>.json` on the volume.

Every table carries a COMMENT (visible in Catalog Explorer) describing its
grain and rules.

## Power BI

All tables are flat and typed — connect with the Databricks connector and
read them directly; `gold_county_status` + `gold_pda_summary` +
`gold_snapshot_summary` are the dashboard set, `silver_chart_a_applicant`
the drill-down.

Comment formatting from the Chart A Comments sheet survives in two columns:

- `comment` — plain text with the workbook's alt-Enter line breaks as real
  newlines. A Power BI table visual with **word wrap** on renders them.
- `comment_html` — the same text with bold/italic/underline runs and breaks
  as `<b>/<i>/<u>/<br>`. Native visuals show the tags literally; render it
  with the free **HTML Content** custom visual (AppSource) for true bold.

## Rules that must stay true (mirrors ../CLAUDE.md)

- Indicators come from the source workbooks (Table A → state PCI/population,
  each Chart A → its county threshold); widgets are an emergency override only.
- County identity from `County Summary!B3`, never the filename.
- Totals recomputed from Cat A–G; the workbook's own cells kept as `wb_*`
  for reconciliation; mismatches flagged, never fixed.
- Only stage ≥ 3 (through Lead Review) counts as validated anywhere.
- REMC charts parse but are parked (never counted; damage arrives via county
  Chart A's).
- Dollar conservation asserted before writes; a degraded parse run (>25%
  failures) refuses to overwrite tables.
- Nothing here goes to the public repo — the whole `pdaboard/` tree is
  git-ignored.

## Not yet ported

`query.xlsx` / SharePoint filetree matching (modified-by, SharePoint deep
links, authoritative county scope from `Counties/`), the board.html render
step, and the Graph-API sync. County scope in this drop mode = counties
observed among the parsed charts. When the SharePoint connection lands,
feed the pipeline folder straight into the same volume layout — nothing
downstream changes.
