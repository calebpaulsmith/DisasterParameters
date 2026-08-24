# CLAUDE.md — PA PDA Operations Dashboard (pdaboard/)

Instructions for working on **PDA Board** — the internal dashboard for ongoing FEMA
Preliminary Damage Assessments. Read this before touching anything in `pdaboard/`.

## What this is (and is not)

A **single-file, fully-offline operations dashboard** for a live PA PDA: the PDA Lead
watches validated damage fill toward the statewide per-capita indicator, and reviews
each county's Chart A. Built for the IN PDA (July 2026); multi-PDA by design (per-PDA
`manifest.json`). This is the **local development harness** for a future Databricks
port (volume drop → job → Delta → App) — see `../docs/pda-databricks-dashboard-plan.md`.

- **Only the tool CODE is committed; all PDA DATA stays git-ignored.** The parent
  repo (DisasterParameters) is PUBLIC. As of 2026-07-21 the root `.gitignore` uses an
  **allowlist** for `pdaboard/`: the parsers/pipeline/template/databricks notebooks/
  VBA source/public reference data (`data/dim_county_*`, `data/*_counties_geo.json`,
  `data/history_*.json`) + `manifest.json`/`manifests/*` (scrubbed — empty
  `sharepoint_base`/`master_folder`) + `setup.html`/`README.md`/`CLAUDE.md` are
  committed; **everything else under `pdaboard/` is ignored** — `PDAExamples/`,
  `out*/`, `tests/`, `excel/*.xlsm`, `query.xlsx`, `*.iqy`, caches. The reason the
  ignored set MUST stay ignored: it holds **live damage figures, applicant details,
  and staff names** (e.g. `out/board.html` bakes the built data; `tests/` hardcode
  cent-level totals and an inspector name; `PDAExamples/` are the real workbooks).
  NEVER commit any of those, never add a live `sharepoint_base`/`master_folder` to a
  committed manifest, and never quote ignored contents into a committed file. When you
  add a new committed code file under `pdaboard/`, add it to the allowlist explicitly.
- Not a declaration determination; the "Unofficial working tool" footer stays.

## Commands

```bash
cd pdaboard
python pipeline.py            # full rebuild: parse PDAExamples/ -> out/board.html (~90s)
python wizard.py [folder]     # POINT-AT-A-FOLDER build: give it the downloaded PDA folder
                              # (or a flat pile of Chart A's) -> reads it IN PLACE (filename
                              # classify, stage from folder location, Table A meta = identity
                              # defaults), writes _manifest.json beside the files -> one
                              # board.html. The guided workflow behind setup.html §5b.
python build_history.py       # refresh the static OpenFEMA prior-history snapshot (network)
python rehtml.py              # re-render out/board.html after TEMPLATE-ONLY edits (instant)
python -m pytest tests -q     # golden tests (~4 min, needs PDAExamples/)
python pa_pdas_charta.py "PDAExamples/_17-19 import" --year 2026 --month May \
    --state MI --dn 4925 --pa-pdas "PDAExamples/_17-19 import/pa_pdas.csv"
                              # Table A (+Chart A's) -> pa_pdas_charta CSV (see below)
python -m http.server 8137 --directory out    # or just open out/board.html via file://
```

After template edits, syntax-check the script block before rendering:
`node -e "...new Function(js)..."` (see git history of this session) — the template is
one big JS file and a typo bricks the whole board.

## Architecture (one file each)

| File | Role |
|---|---|
| `chart_a_parser.py` | Parses Chart A workbooks (county/pop/threshold from `County Summary!B3`, applicant rows B6:L, comments sheet **with rich text** → `comment_html`; sheet is `Comments` (v2) or `Deduction Comments` (legacy)) and the Table A master. **Two Table A template generations parse — by LABEL, never fixed cells**: v2 = RVAR-era (IN 2026; Input Sheet D1 state code/D2 population, per-county table on `Summary`), legacy = SummaryPage-era (MI/WI May 2026; NO RVAR sheet, D1 Region/D2 state code, state population + PCIs + incident block from `PCI Indicator`, per-county table on `SummaryPage` under `County|Subrecipient` with per-subrecipient detail rows interleaved — skip blank-A rows, stop at `Grand Total`). v2 must NOT read `PCI Indicator` (stale template leftovers). `meta["format"]` records which. openpyxl only — no pandas — so it ports to Databricks unchanged. |
| `pa_pdas_charta.py` | Builds **pa_pdas_charta** rows: Table A subrecipient×county grain in the EXISTING `pa_pdas` table's column vocabulary + `Charta_Id`/`Pda_Id = Year-Month-State` + charta extras (Status/Applicant_Type/Comment/Comment_Html/Inspector). **`pa_pdas` is NEVER modified** (it has no id column — the link is the shared natural key; Power BI relates on a `Pda_Id` calculated column both sides). Chart A's are OPTIONAL enrichment (comments/types/inspectors — dollars always from the Table A); chart-only applicants are never added as rows (double-count risk), they land in the audit. Blank cats = null (pa_pdas convention). Dollar-conservation gate. Optional best-effort row link vs a pa_pdas extract (normalized names, `X, City of`↔`City of X`, County="Multiple" fallback) — validated 2026-07-19: MI 67/73, WI 137/137 pa_pdas rows hit, zero field disagreements. CLI: `python pa_pdas_charta.py <folder> --year 2026 --month May [--state MI --dn 4925 --pa-pdas pa_pdas.csv]`. Used by notebook 01 (gold_pa_pdas_charta + volume CSV) and mirrored in `excel/modChartA.bas`. |
| `excel/` | **PA PDAs ChartA Builder.xlsm** + `modChartA.bas` (the source of truth for its VBA — reimport after edits): the no-Databricks twin of the charta build. Browse to a PDA folder → sniffs+parses the Table A (both generations, label-driven), verify Year/Month/State/DN prompts (defaults from the workbook), optional Chart A comment enrichment, writes the `pa_pdas_charta` sheet as a ListObject (Power BI: Get Data → Excel workbook). Sheet `pa_pdas` (optional paste of the existing table) enables the row-level link; sheet `openfema` is reserved for OpenFEMA reference data — the macro never writes it. `BuildChartaAuto()` is the headless entry point for testing. Runs with manual calculation (the source workbooks recalc slowly). |
| `sp_filetree.py` | Parses `query.xlsx` (SharePoint "Export to Excel") and owns the **stage model**; matches dropped files back to SharePoint rows by filename (+size tiebreak). ALSO parses **`query*.iqy`** (`parse_iqy`/`load_iqy`/`find_query_iqy`) — the web-query file saved with that export, and the ONLY artifact carrying the SharePoint **host** + the PDA's **root folder** (query.xlsx's `Path` column is server-relative). `root_path_from_rows`/`counties_path_from_rows` recover the same two paths from an export when there is one. |
| `pipeline.py` | Joins everything into `out/board_data.json` + renders `templates/board.html` → `out/board.html`. Canonical rule: highest stage wins, tie → latest modified. Snapshots append to `out/snapshots.jsonl` (ticker/movers). History layer reads `data/history_<state>.json` (scope counties only embedded → keeps board.html lean; `history_meta` carries fetchedAt + the queries). |
| `build_history.py` | OFFLINE (network): pulls TODAY's prior-FEMA-history direct from OpenFEMA and freezes it as `data/history_in.json` — PublicAssistanceFundedProjectsSummaries v1 (applicant × county × disaster, FEDERAL share obligated) + DisasterDeclarationsSummaries v2 (per-county designations/titles/dates). COVID (Biological) excluded; dollars conserved (exits nonzero on residual); the EXACT reproducible query URLs (for the Databricks v2 dynamic version) are in the module docstring, README, and embedded in the JSON under `queries` with `fetchedAt`. WAF gotcha: never `$select` with `$filter`+`$top`. |
| `templates/board.html` | The entire UI (vanilla JS, ~90KB). Placeholder `/*__BOARD_DATA__*/null` is replaced at build. |
| `wizard.py` | **Point-at-a-folder build workflow** (setup.html §5b; REWRITTEN 2026-07-27 — the old add-sources-one-at-a-time staging loop is gone, owner found it annoying): `python wizard.py [folder]` — point it at ONE folder (the whole downloaded PDA/Final Products folder, or a flat pile of Chart A's) and it reads everything IN PLACE, no staging copies. Classifies by FILENAME first ("table a"→Table A, `looks_like_chart_a`→Chart A, query*.xlsx/.iqy), content-sniffs only name-ambiguous workbooks; prints a found-summary with per-stage chart counts (`stage_from_segments` — an "Entered in Table A" folder anywhere in the path keeps its meaning); identity defaults (state, month/year) are READ FROM THE TABLE A meta so prompts are Enter-Enter — the month/year is the **PDA's month** (`meta["pda_start"]`, what PDAs are named for; incident-start month only as fallback — owner caught "April 2026" on a May PDA), and the readout also prints the incident period numerically (MM.DD.YYYY - MM.DD.YYYY); on a LIVE build with loose (no-stage-folder) charts it asks ONE stage for all of them → `manifest["default_stage"]` (pipeline applies it when `stage_from_segments`==0 and no sp match; `stage_basis:"default_stage"`; mirrors notebook 01's widget); with MULTIPLE Table A's (drops carry variants, e.g. MI's full + "Counties That Met Threshold Only") it LISTS them (newest marked) and the user picks the master → `manifest["table_a"]` (filename or drop-relative path; pipeline honors it, falls back newest + `TABLE_A_NOT_FOUND` health flag if it names a missing file; without the key: newest wins, others flagged `MULTIPLE_TABLE_A`). If the pointed folder has NO `query*.iqy` but the PARENT folder does (user pointed at a Chart A subfolder while the query files sit beside it), the wizard OFFERS the parent's .iqy and passes it via `pipeline.build(..., iqy_path=)` (+ `--iqy` in the printed re-run line). The folder question opens a **Windows folder-picker by default** (tkinter `askdirectory`, guarded — falls back to paste if tk is unavailable/cancelled); pasting still works. After the identity questions it OFFERS a **prior-FEMA-history refresh** (default No; runs build_history.py as a subprocess with timeout, any failure prints a note and is SKIPPED — never fatal; `STATE_NAMES` maps R5 codes to OpenFEMA spellings, other states prompt). Writes only `_manifest.json` beside the files (falls back to `drops/<id>_manifest.json` if unwritable), builds, prints the re-run `pipeline.py` line. ASCII-only console (cp1252). |
| `manifest.json` | Per-PDA: `pda_id`, `title`, `state`, events, `sharepoint_base`, `stale_hours`, plus **`complete`** (COMPLETE mode, below) and **`master_folder`** (county-folder link base). **No indicator values here** — see rules. `manifests/` holds the per-PDA manifests for the imported completed PDAs (mi_may_2026.json, wi_may_2026.json → `python pipeline.py --drop "PDAExamples/_17-19 import/MI May 2026" --manifest manifests/mi_may_2026.json --out out_mi`). |
| `build_dim_county.py` | Per-STATE county dims + geojson (`data/dim_county_<st>.csv`, `data/<st>_counties_geo.json`; built for ALL SIX Region 5 states in/il/mi/mn/oh/wi). Populations from the hidden 'County Population and Threshold' sheet in any Chart A of that state (both template layouts sniffed), OR — for states with no chart on hand — from any Table A master's NATIONAL 'County Populations' sheet (IL/MN/OH were built this way from the MI Table A; non-county rows like 'Grand Total' and MN tribal entries are skipped with a printed note — tribal damage reaches the board via county Chart A rows). FIPS/geometry NAME-MATCHED against a US counties GeoJSON (Census 20m via plotly mirror — download to repo root as counties_us.json or pass a path). NAME_ALIASES fixes typos baked into the workbooks (WI's "Fond Du Loc", "La Cross"). `python build_dim_county.py mn <table-a-or-chart>.xlsx <counties_us.json>`. pipeline.py loads the dim/geo for `manifest.state`. |
| `databricks/01_parse_chart_a.py` | Databricks notebook (import via Workspace → Import; upload `chart_a_parser.py` beside it — it IMPORTS the local parser, never forks it): volume drop → bronze/silver/gold Delta tables. Stage from the folder each file sits in (SharePoint pipeline subfolders; zips expanded, inner paths count; no-folder files get the `default_stage` widget = 2). Indicators from the dropped Table A (widgets = emergency override only). Rich-text comments land as `comment` (plain, real `\n` — Power BI word wrap) + `comment_html` (`<b>/<i>/<u>/<br>` — HTML Content visual). Appends ticker snapshots (`gold_snapshot_*`, skipped when unchanged); fails the run on >25% parse errors or broken dollar conservation. See `databricks/README.md`. |
| `databricks/03_render_board.py` | **The no-tables path**: Databricks notebook that turns a volume drop (one subfolder per PDA: Chart A's + Table A + optional query.xlsx + optional `pda.json` identity file) into **one self-contained `board_<pda_id>.html` per PDA** — rendered inline via displayHTML AND written back to the PDA's folder for download/email. Pure python (no Spark unless `write_tables=yes`, which adds the two board-level Delta tables `gold_*_boards`; the full medallion stays notebook 01's job). Code resolves from the Workspace beside the notebook (upload pipeline.py + parsers + templates/ + data/ dims, folder shape preserved) else `<drop>/_code/`. Identity: `pda.json` else derived (state from the Table A, pda_id from the folder name, complete from the `complete_default` widget). Prior-history: reads `history_<st>.json` from data/ or `<drop>/_ref/`; with `auto_history=yes` it resolves the two OpenFEMA CATALOG tables via the workspace's **OpenFEMA columns** table (`openfema_columns_table` widget, tolerant scanner + name-guess fallback + direct-table override widgets) and runs notebook 02 to build the JSON — **never the public API**. Every volume write has a /tmp fallback (locked-down workspaces); header cells are a step-by-step SharePoint download/upload guide. Smoke-tested locally with stubbed dbutils/spark over the MI+WI imports. |
| `databricks/02_openfema_history.py` | Databricks port of `build_history.py`: reads the workspace's CATALOG copies of PublicAssistanceFundedProjectsSummaries v1 + DisasterDeclarationsSummaries v2 (widgets point at the tables; no public-API calls), same math (COVID excluded, flags OR'd, earliest declared, conservation gate fails the run) → `hist_*` Delta tables + `history_<state>.json` on the volume in the exact `pipeline.load_history()` shape. Original API URLs kept in the output `queries` block for provenance. |
| `tests/` | Golden tests against `PDAExamples/` (skip if absent). Keep them green; they pin every displayed number. |

## Domain rules that MUST stay correct

- **Indicators come from the source workbooks, never hardcoded**: state PCI, county
  PCI, state population from the Table A Input Sheet; each county's threshold from its
  own Chart A header cell. Manifest keys are an emergency override only. A drop with
  no Table A raises `NO_TABLE_A`/`NO_STATE_INDICATOR` health flags — never guess.
- **Statewide inclusion math** (PDA Guide, July 2025, "Per Capita Impact
  Calculations", printed p. 56 + fn. 12; `_guide_math()` in pipeline.py):
  counties ≥100% of county PCI always count; 50–99% count ONLY if ≥100% counties
  alone cover 75% of the statewide PCI; <50% never counts. Guide is quoted VERBATIM
  in the UI and linked: https://www.fema.gov/sites/default/files/documents/fema_rd_pda-guide_07012025.pdf
  (local copy: `PDAExamples/fema_rd_pda-guide_07012025.pdf`).
- **Stage model** (folder-location-encoded in SharePoint). Internally 0–4; the UI
  surfaces only three statuses: **For PDA Lead Review (2) → Ready for Table A (3) →
  Entered in Table A (4)**. Stages 0–1 display as one "Not yet submitted" bucket
  (still fully ingested and drillable).
- **Only counties THROUGH Lead Review count**: rollups (validated_total, guide math,
  map outcome fills, county-table figures) include ONLY stage ≥ 3 rows. Everything
  below is **pending** — pipeline emits `summaries[eid].pending` = {total (ingested
  pending $), n_counties, n_unmeasured}. The default UI shows NO figures for
  pending counties. The header **"Pending $" admin toggle** (`S.admin`, persisted
  `pdaboard-admin`) surfaces them: stage-2 = YELLOW "For PDA Lead Review" pill with
  its $, unsubmitted = grey pill with any working-chart $, values styled `.pendval`
  (italic); it also fills the clock's TBD cells (per bucket: review + not-submitted)
  with pending $ + "N TBD" for unmeasured counties. Pending NEVER mixes into
  countable/validated totals. The header **Admin ▾ menu** (`.admwrap`) holds the
  Pending $ checkbox PLUS opt-in panels — Validated $ over time / Movers / Data
  health (`S.panels`, persisted `pdaboard-panels`, ALL UNCHECKED by default; the
  rail folds render only when checked; renderTicker/renderMovers/renderHealth are
  null-guarded).
- **SharePoint links: `query.iqy` is the source, and they are swappable in the
  board.** `pipeline.resolve_links()` resolves each field manifest -> `query.xlsx`
  -> the drop's `query*.iqy` (CLI `--iqy` pins one): `sharepoint_base` = the
  site host (only the .iqy has it), `master_folder` = the counties folder —
  taken from the export when it's visible there, else the Region 5 convention
  `<root>/Damage Data/Counties` with `master_folder_assumed:true` so the UI says
  so. Nothing is invented: no source -> empty links + a `NO_SHAREPOINT_LINKS`
  health note. File rows carry their server-relative `path`, and the board
  composes hrefs live (`fileUrl()`), so changing the base re-points every link
  without a rebuild.
- **One MASTER query can serve every PDA.** An Export to Excel / .iqy taken at
  the library level ("Ongoing PDA's") is rooted ABOVE the PDAs, so it must be
  narrowed to THIS one before anything reads it — otherwise scope, stages and
  links silently mix PDAs. `sp.pda_root_candidates()` lists every PDA folder in
  an export (the folder above the first `Damage Data`/`Chart A's`/`Counties`
  segment); `choose_pda_root()` picks: explicit `sp_folder` (manifest key or
  `--sp-folder`) -> the only candidate -> a token match on the PDA's identity
  (state + month + year, `sp.match_pda_folder`). A match narrows the filetree
  (`filter_rows_under`) and logs `MULTI_PDA_EXPORT`; no match is
  `AMBIGUOUS_PDA_EXPORT` and nothing is guessed. A master **.iqy** carries no
  listing at all, so it can only ever name the parent — `master_root_path` is
  set, `root_path`/`master_folder` stay empty, and `PDA_FOLDER_UNKNOWN` says to
  set `sp_folder` or pick in the board. The board's **PDA folder** field
  (`#rowPdaFolder`, datalist of `pda_candidates` + generated spellings) is that
  picker: choosing a folder recomputes the county base
  (`recomputeCountyBase()`) and persists as `pdaboard-pdafolder-<id>`.
  Parent-vs-PDA is decided by NAME (`looks_like_pda_folder` /
  `looksLikeThisPda`); with no identity tokens to judge by, a root is taken at
  face value. In the board: **Admin -> SharePoint links** (site base +
  county folder base + "Load query.iqy…" + Reset + "Open PDA folder"),
  `parseIqy()` mirroring the python parser in-browser (FileReader, no network),
  persisted per PDA as `pdaboard-spbase-<id>` / `pdaboard-master-<id>`. In
  COMPLETE mode the Admin button is a **discreet gear** (`.admbtn.quiet`,
  gear SVG) and the whole panels/pending group (`#grpPanels`) is hidden — the
  links section is the only admin surface a finished board keeps.
- **County pane shows ONE unified mirror of the county's SharePoint files (tree).**
  `board_data` `files[county]` = `{prefix_path, prefix_rel, nodes[]}`; each node is a
  folder or a document with `disp` (path relative to `prefix_path`). Per county the
  pipeline collects EVERY file the query knows about it — its `Counties/<County>/`
  working docs AND its Chart A(s) sitting in the pipeline folders
  (`Chart A's/…/Entered in Table A/`, attributed by `county_from_filename`) — then
  roots the tree at the **common ancestor** of those files (`_common_prefix`). So a
  county whose files are all in its own folder stays shallow (prefix
  `…/Counties/Harrison`, `disp` = "County Highway/invoice.pdf"), while a county whose
  Chart A lives in the pipeline roots higher (prefix `…/Damage Data`, `disp` =
  "Chart A's/2. Ready for Table A/Floyd…xlsx" alongside "Counties/Floyd/…"). This
  FIXED the "County folder — Damage Data/Counties · 0" bug: pipeline-only counties
  used to show 0 because the old code mirrored `Counties/<County>/` only and put
  pipeline charts in a SEPARATE "Chart A pipeline" section — now it is ONE tree, no
  empty section. `chart_files` is emitted empty (kept for back-compat). Completed PDA
  with no export: the drop's own layout, links composed off the PDA root
  (`prefix_rel`, labeled "read from the data drop"). Template `nestNodes` +
  `fileTreeHTML()` — every folder and file is a link `<base>/<prefix>/<disp>`, so
  re-pointing the site base re-points the whole tree. Each county row also carries
  `source_path`/`source_rel`/`source_file` → the **"Chart A workbook ↗"** button
  (`chartAUrl()`) linking that county's canonical Chart A. The tree renders FULLY
  EXPANDED — every folder level open (owner ask 2026-07-27; was one level).
  The **Prior FEMA history histogram (`histChart`) STAYS on COMPLETE** — the owner
  wants the declaration bar chart on finished boards; what a completed board drops
  is the live OPERATIONS/stage status (Under Review / Ready / pending), which the
  COMPLETE const already removes elsewhere. Since 2026-07-27 the whole history card
  is a **collapsed `<details>` on COMPLETE** (`histCard(cty,hist,true)`) — click
  "Prior FEMA history" to expand; content unchanged. Live boards keep it open.
- **County identity comes from the workbook cell, not the filename** (filenames lie —
  "Blank Chart A" files carry real data). Every total is recomputed from Cat A–G and
  reconciled against the workbook's own cells; mismatches are flagged, never fixed.
- **County joins are FUZZY (2026-07-27).** Every county↔county join in the pipeline
  goes through `sp_filetree.norm_county_name()` (aliased `ckey` in pipeline.py):
  lowercased, punctuation/space-insensitive, `Saint`→`St`, trailing `County` dropped —
  so a hand-typed `Counties/St Joseph` folder attaches to the workbook's `St. Joseph`.
  Applied to: canonical group keys, Table A county map, ft_charts, dim lookups
  (`load_dim_county` keys by it), scope dedupe, file-tree attribution
  (`scope_by_norm`), `_last_touch`. Unmatched folder names (REMCs) still pass through
  as-is. Never reintroduce bare `.lower()` county joins.
- **REMCs are not displayed** — their damage arrives via county Chart A's. REMC charts
  still parse → `REMC_PARKED` health note (nothing silently dropped).
- **Dollar conservation**: sum of county rows == summary total; guide-math tiers sum
  to total validated. Tests enforce this.
- **pa_pdas is read-only, forever.** The owner's pre-existing `pa_pdas` table
  (applicant×county×PDA; extract at `PDAExamples/_17-19 import/pa_pdas.csv`) must never
  be altered by anything here. `pa_pdas_charta` shares its column names/meanings and
  links via `Pda_Id = Year-Month-State`; a missing row-level link is NORMAL (pa_pdas
  names are hand-curated; multi-county applicants sit under County="Multiple"; a charta
  import usually lands before the pa_pdas row exists).
- **Underscore folders are aside material.** `_`-prefixed folders under a drop
  (`_code`, `_ref`, `PDAExamples/_17-19 import`) are never parsed as part of that PDA —
  both pipeline.py and notebook 01 skip them. The MI/WI May 2026 prior-PDA workbooks
  live in `_17-19 import` so the IN board/tests don't ingest them.
- **Chart A's are optional for the charta table.** Table A alone carries applicant,
  county, status, and Cat A–G (the full pa_pdas grain). Only comments, applicant type,
  and inspector REQUIRE Chart A's — they exist nowhere in a Table A.

## Content switches (external-share stripping — owner 2026-07-27)

Three manifest booleans (the wizard asks them as include-Yes/No questions —
never labeled "clean"), applied in `pipeline.build()` AFTER the board dict is
assembled — the data is **STRIPPED from the emitted file**, not CSS-hidden:

- **`no_links`**: every SharePoint link/path removed (`links` emptied,
  `files`={}, `master_folder`/`sp_url`/`source_path`/`source_rel`/
  `table_a.rel_path` nulled). Template (`NOLINKS`): Folder column dropped,
  selected-row link bar + Files cards gone, Table A ↗ gone, Admin
  SharePoint-links section (`#grpLinks`) hidden. Verified: no URL/path
  values survive in DATA (only empty key names).
- **`history_no_dollars`**: prior-FEMA-history OBLIGATION dollars stripped
  (`paObligated`/`pa` popped at every level) — **prior applicants and
  declarations stay visible** (owner: the lists surface, just not the $).
  Template (`HSCRUB`): applicants-only single-bar histChart, no $ lines/
  columns, footer notes "obligation dollars omitted".
- **`no_inspectors`**: inspector names nulled on county + applicant rows
  (plus last_touch_by/sp_modified_by) — the Inspector line disappears
  everywhere (template renders it only when present).

## COMPLETE mode (finished PDAs — owner-specified 2026-07-19)

`manifest["complete"] = true` (or `pda.json` in the Databricks drop). For a PDA
whose numbers are FINAL — the live-tracking chrome comes off:

- **Pipeline**: every parsed chart is stage 4 (`stage_basis:"complete"`); scope
  falls back to Table A counties ∪ charts when there's no query.xlsx
  (`SCOPE_FROM_WORKBOOKS`); a single event is synthesized from the Table A
  incident period when filenames carry no period (`NO_EVENT_LABELS`); counties
  with no Chart A in the drop take their FINAL figures from the Table A county
  row (`FROM_TABLE_A` flag + per-subrecipient pseudo-applicants) — so a
  Table A-only drop renders a full board. board_data carries `complete` +
  `master_folder`.
- **met_only** (manifest key, DEFAULT TRUE when complete; notebook widget
  `met_only_default`): counties whose validated total never reached their
  county indicator are EXCLUDED from every figure AND from the map — they
  render as plain nonscope (owner 2026-07-28, REVERSING the short-lived
  translucent-red excluded-county map treatment: "don't include" means the
  map too). Disclosure stays: the top card's red "N did not meet · $X" line,
  the health note, and the counties CSV export rows (`met_only_excluded`
  carries `{n, total, counties:[{county,fips,total,threshold,pct}]}`).
  Boards that INCLUDE their non-met counties (met_only:false) are where
  did-not-meet is surfaced visually: red map fills (they're real rows),
  red row tints, MET/NOT MET tier badges. Non-excluded under-100% rows also
  keep a red map outline under the metric choropleth.
  `MET_ONLY_EXCLUDED` health note unchanged; empty 50–99/<50 tier rows hide.
  Set `"met_only": false` for the full-fidelity board (hero then matches the
  workbook's own Validated Total incl. the 75%-rule holdings).
- **Template — the COMPLETE layout (owner spec 2026-07-27, REVISED same day —
  the county-table-in-rail experiment was REVERTED on owner feedback).**
  The left rail is a 2-card stack; the county list lives in the RIGHT panel:
  1. **Top card** (NO "Thresholds" title — owner 2026-07-27 round 4): the
     **PDA title** (`.pdatitle`, e.g. "WI PA PDA - May 2026") with the
     **incident period in smaller text under it** (`.pdaper`) — this lockup
     is THE home of title+period (the header band stays a plain title). Then
     a **LINEAR vertical bar** (`vbar()` — NOT meterGeom: the track spans
     max(validated, indicator); at/under 100% the 100% line sits at the top,
     over it the line moves DOWN in proportion, so 300% puts it a third of
     the way up — commensurate, never "just a little over". NAVY gradient
     fill below the line, GOLD gradient overage above it, soft glows, **NO
     stripes, NO green** — owner killed the striped r/y/g treatment. %
     callout chip rides the fill) beside **BIG-number stats** (`.vstat.big2`,
     21px: Counties · applicants · validated $; the statewide indicator
     stays small) + a **red "N did not meet · $X" line** whenever ANY county
     is under its indicator — met_only-excluded AND/OR visible under-100%
     rows (owner round 5: the tooltip-only disclosure was right only for
     boards where every county met) + the gold **"Table A ↗" link** (rendered
     even when inert). The same linear vbar serves the county morph card.
  2. **"Categories of Work" card** (retitled from "Table A"). Contents in
     order: a **`.cwscope` TITLE LINE naming the charted level** (PDA title
     statewide → "<County> County" → "<Applicant> · <County>" — owner wants
     the level unmistakable) → the **$ Validated / Applicants metric
     TOGGLES** (`.catmode` chips, `data-mapmetric` — moved here FROM the map
     overlay, `#mapChips` deleted; radio-off; they drive the chart METRIC,
     the map choropleth + per-county values, AND the county-row bars) →
     compact tier rows (`.tam`, click-filter) → the **category chart with
     FOUR flippable visualizations** (`S.catViz`, ‹ › arrows bottom-right,
     `.viznav`; **DEFAULT = 3 "Rows"** — per-category horizontal bars A–G,
     owner: better than the column bars): 0 column bars (scope-colored muted
     teal #40796a / slate #4f7fae / gold #c8a04d), 1 PIE, 2 STACKED bar,
     3 ROWS. `CAT_COLORS` is a **MUTED palette** (owner: bright primaries
     read grade-school; hues kept, saturation down). **Every viz: hover-peek
     + click-slice** (delegated `.catpeek [data-cat]`, svg wedges included);
     **tooltips carry ONLY that category's facts** (no "hover to preview"
     boilerplate — and the hint line under the chart was removed entirely).
     Metric: `chartMetric` = dollars, or "applicants with $ in that
     category" under the Applicants toggle (applicant scope is ALWAYS
     dollars). Scope + animation (`CAT_ANIM` → `.cgrow`); click an APPLICANT
     row → its A–G (`S.selApp`, name-keyed; re-click deselects; auto-OPENED
     comment rows do NOT set the scope). **The statewide aggregation honors
     the ACTIVE FILTERS** (`baseRows = rows.filter(rowPass)`) — clicking a
     tier row (≥100% / 50–99 / <50) re-scopes the chart's numbers to that
     tier, same for the stage/category filters (owner 2026-07-27 round 7).
     **Category ↔ Type grouping (BOTH board types, owner 2026-07-28):** the
     word in "Dollars by category|type" is a BUTTON (`.catgroupbtn`,
     `data-catgroup`) toggling `S.catGroup` — "type" collapses every chart
     (all 4 vizzes + the live rail chart) to TWO groups, Emergency Work
     (A–B, --m2) and Permanent Work (C–G, --accent-dim; the E/P split-bar
     colors). `groupDefs()`/`TYPE_GROUPS` drive rendering + BOTH A–G filter
     menus (county + applicant Validated columns become two group
     checkboxes; option values are comma lists, handlers split on ","); bar/
     wedge `data-cat` carries the comma list, `paintCatPeek` sums it;
     `sliceLab()` renders "A–B"/"C–G" in headers and "Emergency A–B"/
     "Permanent C–G" in the map totals lead. Applicants metric per group =
     DISTINCT applicants with $ in any group cat (never a sum — would
     double-count).
  **Right panel** = the **county table** (columns County | Applicants |
  Validated $ | Folder — the Folder column is DROPPED on no_links boards;
  the scope band is HIDDEN on COMPLETE — its county/applicant counts
  duplicated the Thresholds card). **County rows and applicant rows carry
  TRANSLUCENT BACKGROUND BARS** (`--rowbar` rgba, a row-level
  linear-gradient behind the text): county rows sized by validated $ or
  applicant count per the metric toggle, applicant rows always by (sliced)
  validated $; both respect the filters + category slice; hover/selected
  backgrounds paint over them. **On a MIXED board (met + did-not-meet
  counties both visible, e.g. met_only:false) the county rows switch to a
  full-width GREEN/RED row tint with the proportional bar in a stronger
  shade** (module const `MIXED` — small counties' proportional bars alone
  were invisible); all-met boards keep the quiet blue bar, red only where a
  non-met row exists. **MIXED-board extras (owner 2026-07-28, exclusive to
  boards showing both):** `:root[data-mixed="1"]` darkens the reds —
  50–99% ≈ the old <50% shade, <50% a notch darker (map fills + tier-row
  tints; labels stay readable); tier rows carry **MET / NOT MET pills** +
  explicit notes ("counts toward statewide" / "counted (75% rule met)" /
  "held" / "excluded"); the **top card becomes an EXEC SUMMARY** (PDA title
  + period, then ONLY: N met · $, N did not meet · $, validated total,
  statewide indicator — no county/applicant totals); and the **$ Validated/
  Applicants toggle switches the 3 tier-row values** between dollars and
  per-tier applicant counts (`tierApps`, slice-aware). Clicking a county **SLIDES the
  drill-down over it**
  (`slideInR` on `.chartexp`; ‹ Back top-left / Esc slides the table back in
  via `#rpTable.slideback` slideInL; `.rightpanel{overflow:hidden}` clips).
  The drill-down shows: **Applicants** (columns Applicant | Validated ONLY —
  the **Status column was REMOVED** (owner 2026-07-27); both headers
  **click-sort**, `S.appSort`; the Validated header carries its own
  **"A–G ▾" category-filter menu** (`data-afm`/`data-afv`, `S.openMenu==
  "appcat"`) operating on the SAME shared `S.catSel` slice as the county
  table — narrowed → only applicants with $ in the selected cats,
  "Validated · C" header, sliced sums; the ACTIVE applicant row carries a
  gold `.appmark` + inset bar; the Back-bar county row shows **NO stage
  badge on COMPLETE** — "Entered" is meaningless there, and the map TOOLTIP
  likewise drops its stage chip on COMPLETE), the **"Chart A
  workbook ↗"** link + **Files rooted at the county's folder**, and **Prior
  FEMA history as a COLLAPSED `<details>`**.
  **Clicking a county**: the map **ZOOMS onto it** (`mapZoom` — CSS-transitioned
  transform on the `.zoomg` wrapper, county fills ~55% of the short axis capped
  at 4.5×, seams stay screen-width via vector-effect) and the Thresholds card
  **MORPHS into the county's version** (`.morph` slide-in): its vertical bar +
  stats (validated / county indicator / % / applicants) + Inspector line + the
  **Emergency/Permanent split bar** (the middle horizontal indicator meter
  with 50/100 ticks was REMOVED 2026-07-27 — redundant with the vertical bar;
  NO incident-period line here either).
  **Incident period appears ONCE — on the TOP RAIL CARD** under the PDA
  title (`.pdaper`; owner round 4 — the header-parenthetical version was
  rejected as ugly; the header band shows the plain title only).
  **The footer band is HIDDEN on COMPLETE** — the "Unofficial working tool"
  disclaimer + the COMPLETE/build stamp move INTO the Admin gear menu
  (appended in `stamps()`; the non-endorsement disclaimer thus STAYS in the
  UI, just under Admin). Live boards keep the visible footer + staleness.
  The Admin menu also carries **"Export — CSV for Power BI"** (all modes):
  three buttons (`csvCounties`/`csvApplicants`/`csvSummary` → `pbiCsv()`/
  `dlCsv()`) that download flat, Power-BI-ready CSVs built client-side from
  board_data — UTF-8 BOM, CRLF, quoted text, plain numbers, ISO dates, Cat
  A–G split into columns; counties.csv = county × incident period with
  met_only-EXCLUDED counties appended and flagged (`excluded_met_only`);
  applicants.csv = applicant × county incl. plain-text comment; summary.csv
  = one row (indicators, totals, incident period). Exports are the FULL
  data, never the current view filters.
  **The Admin gear is a CLEARLY VISIBLE header icon button** (same weight as
  the theme toggle; 2026-07-27 — supersedes the 07-24 "discreet gear") —
  pending/panels stay baked and hidden; the gear opens ONLY the
  SharePoint-links section (site base · county folder base · Load query.iqy ·
  Reset · Open PDA folder). Bake `master_folder`, or just drop the PDA's
  `query.iqy` in the folder, so emailed recipients get working county-folder
  links out of the box. NOTE (owner asked): a dropped `.iqy` re-points every
  link but CANNOT rebuild the file TREE — an .iqy carries no listing, only
  `query.xlsx` does, and the board can't parse xlsx in-browser.
- **Header**: single-event PDAs (every completed import) show a PLAIN title —
  no dropdown, no period, and the word "Combined" never appears; only
  multi-event PDAs (IN) keep the event selector with Combined. **This
  includes `rowFor`'s ALL row** (fixed 2026-07-27 — the drill-down used to
  say "Combined" on MI): with one event, `event_label` is the incident
  period (`PERIOD`), never "Combined".
- **Incident period** (owner ask 2026-07-27): pipeline emits `incident`
  {start,end,name} from the Table A meta + `table_a` {filename, rel_path};
  the template's `PERIOD` renders it **ONLY on the top rail card** under the
  PDA title (`.pdaper` — the header-parenthetical and the per-card copies
  were both rejected as redundant/ugly). **Date gotcha — do not reintroduce:**
  bare `YYYY-MM-DD` strings must be parsed as LOCAL dates (`fmtD`) —
  `new Date("2026-04-10")` is UTC midnight and renders Apr 9 in every US
  timezone (bit both the incident period and the history card's declared
  dates).
- **Map**: camera FITS THE SCOPE counties (+4% margin), not the whole state.
  **Click-to-zoom (2026-07-27):** opening a county flies the camera onto it
  (`mapZoom`, `.zoomg` transform, ~55% of the short axis, cap 4.5×); labels are
  NEVER hidden while zoomed — `MAP.renderLabels(sc)` re-draws every label at
  screen-font/sc svg units, so names stay readable and counties too small to
  label at 1× gain labels zoomed in. paintMap must run AFTER renderLabels (it
  re-applies the `.on` classes) — every mapZoom caller already does.
  The COMPLETE grid is minmax(290px,27fr)/37fr/36fr (`body[data-complete]`
  override; the 340px/31fr wider-rail variant died with the county-in-rail
  layout).
  **Seams are WHITE** (light theme; page-navy in dark) at 1.2px — classic
  clean choropleth separation; non-scope counties share the same seam so the
  state reads as one quiet surface. **Labels are inline-only and
  size-adaptive** (no leader lines, no margin stacks — owner rejected both
  crowded 13px labels AND leader lines): font shrinks to fit the county's
  on-screen bbox (12.5px down to 8px, ~0.62px/char), multi-word names wrap
  to two balanced tspan lines when one line won't go, and only truly tiny
  slivers stay unlabeled (tooltip covers them). Works for any state's
  geometry. Under **met_only the met fill switches to BLUE**
  (`--fill-metblue` #5e93cc light / #4f97d1 dark, tier row tinted to match)
  — a wall of green says nothing when every county met; mixed-tier boards
  keep green/red. Theme toggle is a 22px sun/moon in a 38px button.
- **Clock card title is "Thresholds"** (all modes — not "Threshold clock").
- **Category-of-work SLICE** (all modes): the Validated $ column header
  carries a ▾ multi-select of Cat A–G (`S.catSel`); the rail "Dollars by
  category of work" bars are CLICKABLE (solo-toggle, same slice). When
  narrowed: county rows filter to counties WITH those categories, the $
  column (header "Validated $ · CDE") and its sort show only those
  categories' dollars, Applicants counts only applicants with dollars in
  them, and the map dims non-passing counties. Hover on a bar stays the
  temporary blue peek. Thresholds card math is NEVER sliced (indicators
  are all-category by definition).
- **COMPLETE metric toggle** ($ Validated / Applicants — lives in the
  Categories of Work card, `data-mapmetric`; the old map-overlay `#mapChips`
  is GONE): while active it renders a blue heat choropleth of the hottest
  counties by sliced dollars or sliced applicant count (catBlue ramp; honors
  the category slice + filters) and **each county shows its VALUE on the map**
  (`g.gv` layer, `.ctyval` — $ compact or applicant count, under the county
  name, zoom-compensated via `MAP.sc`). A **totals strip sits UNDER the map**
  (`#mapTotals`, normal flow so it can't overlap anything): "$ Validated $X ·
  Applicants N", always visible on COMPLETE, honoring filters + the slice —
  when sliced it leads with a BOLD "**Cat D** —" prefix (`.mt-cat`) that
  governs BOTH figures (never "$ Validated · D"). No COMPLETE pill in the
  scope band.
- **Category-slice button is LABELED** — the Validated $ header's filter
  button reads "A–G ▾" (a bare 9px ▾ read as an empty box); COMPLETE column
  widths are 27/17/36/20 so eight-digit dollars + the button never clip
  (Applicants is a small count — its width went to Validated $).
- **Hero line wraps** (`.heroline flex-wrap`) and runs 25px/17px so
  "$16,732,747 / $11,433,813"-scale figures never clip the Thresholds card.
- **Chart A pane applicants expand/collapse**: each applicant row is exactly
  as before but its comment block toggles on click (▸/▾ caret); with ≤3
  applicants all comments start OPEN, with more they start collapsed
  (`S.appOpen`, reset per county via `openCounty`).
- The board stays ONE self-contained file — zero network requests — so a
  completed-PDA board is emailable as-is (~400KB). Baked examples:
  `out_mi/board.html`, `out_wi/board.html`.

## UI design decisions (owner-set; don't regress)

- **Full-screen app, no page scroll** (100vh; columns scroll internally).
  Gotcha: any element with an author `display:` needs the global
  `[hidden]{display:none!important}` rule to stay hideable.
- **One screen, three columns**: rail (Threshold Clock hero → category-of-work chart →
  collapsed ticker/movers/health folds) | map | right panel. The right panel swaps
  between the **spreadsheet county table** (scope band above it: inline stage bar +
  clickable bucket-filter chips; sortable column headers) and the **Chart A explorer**,
  which DROPS DOWN in place when a county is clicked anywhere: the scope band stays
  visible, the other county rows hide, and a sticky bar at the top shows a "‹ Back"
  button plus the county's own table row — clicking either (or Esc) rolls it back up.
  Map column is wider than the county column. **Columns are PROPORTIONAL, never
  fixed px** — `minmax(250px,26fr) | minmax(0,37fr) | minmax(300px,37fr)` — so
  browser zoom / different monitors scale the whole board uniformly instead of the
  map absorbing all the change (fixed-px columns caused the map to shrink on
  zoom-in and balloon on zoom-out; don't reintroduce them). The county table is
  `table-layout:fixed` with %-width `<colgroup>` + ellipsis cells so it can NEVER
  scroll horizontally; `.rpbody`/`.rail` are `overflow-x:hidden`. Bigger text =
  browser zoom, which now scales everything proportionally.
  There is NO header view switcher — navigation is click-county / Back only.
- **Filtering lives in the column headers, not chips**: Stage and % of indicator
  headers carry a ▾ menu with multi-select checkboxes (stage: Entered/Ready/Review/
  Not yet submitted; %: ≥100 met / 50–99 / under 50 / For PDA Lead Review /
  not submitted–no figure — bucket ids met/half/under/review/none) + "select all";
  County and Validated $ are sort-only. State: `S.stageSel`/`S.pctSel` Sets +
  `rowPass()` — the map dims counties that fail the same predicate. The scope band
  is display-only: stacked Entered/Ready/Review readiness bar + applicant rows.
- **Thermometer**: striped-gradient fill colored by progress — RED under 75%,
  AMBER at ≥75%, GREEN at ≥100% (`.segc.r/.y/.g`); the current % rides the fill
  edge as a `.thermocall` chip (position clamped so it never clips); past 100% the
  whole bar GROWS (`.thermo.over`, 30→40px + glow). 75%-rule tick stays.
- **Meter geometry (2026-07-24): FULL bar at 100%, then a distinct OVERFLOW
  segment extends past.** `meterGeom(pct)` (shared by the statewide thermometer
  AND the per-county meter) returns `{goal, baseW, overW, fill, over}`: the 100%
  line sits near the END of the track (`METER_GOAL=82`) so the MAIN bar reads as
  ~full at 100%; `baseW = min(100,pct)/100*goal`; going over fills a SEPARATE,
  darker/striped `.segover` (county `i.over`) segment from the goal line into the
  remaining lane, `overW = (100-goal)*over/(over+45)` — saturating so 120% shows
  a clear chunk over and 6808% just maxes the lane without running off. A hatched
  `.overlane` marks the reserved overflow zone; a bold `.tgoal` line marks 100%;
  75% tick at `goal*0.75`, county 50% tick at `goal*0.5`; scale/`.mscale` labels
  positioned to match, over-% label at the right edge. First attempt (a single
  saturating fill with the goal at 68%) was WRONG — a 120% bar looked two-thirds
  empty with the label floating in the gap; the two-segment base+overflow model
  is what "full bar, then overfilled" means. Replaced the original
  `Math.min(100,pct)` cap (statewide only grew taller; county showed no overflow).
- **Fill-up animation (`@keyframes growX`, scaleX 0→1):** the bars fill on
  reveal — base first (`.grow`, .8s), then the overflow/held segments extend past
  (`.grow2`, delayed .78s) — so it reads "fill to 100%, then overfill." Gated to
  fire ONCE, not on every re-render: `RAIL_ANIM` (module flag, consumed in the
  first `renderRail` = page load) for the statewide bar; `CTY_ANIM` (set in
  `openCounty`, consumed in `renderChartPane`) for the per-county meter on open.
  Theme/filter re-renders drop the class so nothing re-animates. `prefers-reduced-
  motion` disables it via the global `animation:none!important` rule (bars show
  full immediately — no stuck-at-0, since scaleX is only applied by the animation).
- **The Thresholds card `?` popover is HIDDEN in COMPLETE mode** (owner: not
  needed on a finished board); the live board keeps it. The per-county pane `?`
  is unchanged.
- **Threshold Clock layout**: hero = "$countable / $EXACT-statewide-threshold"
  (full digits, e.g. $13,163,924), then the thermometer, then a **3-row × 4-column
  tier table** (aligned grid, each row clickable → filters the list/map to that
  %-bucket): (1) `≥ 100%` | MET/NOT-MET pill (statewide indicator) | plain $full
  (NO fraction/percent here — the % lives as a chip CALLOUT riding the thermometer
  fill edge) | "N County/ies";
  (2) `50 – 99%` | "75% MET/NOT MET" pill | plain $held — but when the 75% rule is
  met it renders as a green video-game BUFF: `+$X · +Y%` (the boost those dollars add
  to the statewide %) | counties; (3) `< 50%` | red EXCLUDED pill | $excluded |
  counties; (4) `TBD` | YELLOW "LEAD REVIEW" pill | TBD / pending-$ | stage-2
  counties; (5) `TBD` | grey NOT SUBMITTED pill | TBD / pending-$ | unsubmitted
  counties (pipeline `summaries[].pending` = {review:{…}, pre:{…}}). Rows are
  TINTED to match the map fill buckets (`.tcrow.t-met/.t-half/.t-under/.t-rev/
  .t-pre`) — the 5 rows double as the MAP LEGEND — and every row click-filters
  the county list + map (tiers met/half/under/review/none). Footer line:
  "Validated total $X · not counted $Y". Pills: `.pill.ok/.no/.rev/.pre`.
- **Ready vs Entered must stay visually distinct**: light s3 #4292c6 / s4 #162e51
  (brand navy); dark s3 #4f97d1 / s4 #c9e2f8.
- **Map borders**: WHITE seams (light theme; page-navy dark) at 1.2px;
  hover/selected = bold navy outline and the path is re-appended (raised) in
  its <g> so neighbors don't clip the outline. Paths live in `<g class="gp">`,
  labels in `<g class="gl">`. **CRITICAL hover gotcha (bug fixed 2026-07-19,
  do not reintroduce):** the mouseover handler MUST bail when the target
  already has `.hover` — re-appending the node under the cursor re-fires
  mouseover endlessly, and that churn re-targets the subsequent click to the
  parent `<g>`, silently killing click-to-open (the core feature). The click
  handler also carries an `elementFromPoint` fallback for the same reason.
- **File rows carry stage badges**: pipeline files get colored Entered/Ready/Lead
  Review chips; county-folder Chart A's get a gray "Not submitted" chip (`is_chart`
  from the pipeline); SOURCE badge unchanged.
- **Threshold Clock**: countable-$ thermometer toward the statewide indicator, 75%-rule
  tick, faded amber extension segment = held 50–99% dollars when the gate isn't met.
  Total validated is a detail line, not the hero. Rule text lives in a **hover ? popover**.
- **Map**: FIVE fill buckets, and the Threshold-clock tier rows ARE the map legend
  (there is NO separate legend under the map): met (green) / 50–99% (LIGHT red) /
  under 50% (darker red) / **For PDA Lead Review (YELLOW, --fill-rev)** / not
  submitted (soft blue-gray). Non-PDA counties melt into the page background.
  Labels only on stage≥3 counties, paint-order halo. No stage outlines, no gold
  rings. **Category hover peek**: hovering a bar in "Dollars by category of work"
  repaints the map as a BLUE choropleth of that category's $ share by county
  (sqrt-eased pale→deep blue, `catBlue()`), with each county's normal bucket color
  moved to a 2px OUTLINE; mouseout restores `paintMap()` (which must keep clearing
  inline stroke/fill styles).
- **Files (Chart A explorer)**: one "Files" card with two headed dropdowns —
  "Chart A pipeline" (lead review / ready / entered; OPEN by default) and
  "County folder — Damage Data/Counties" (all working files; collapsed). The
  canonical workbook per (county, event) — the one the board's numbers come from —
  carries a gold **SOURCE** badge + row highlight wherever it appears (pipeline or,
  for working-only counties, the county folder); on Combined both events' source
  charts are badged. Data: pipeline emits `chart_files` + `source_events` per file
  (`_is_source()` matches canonical sp_path/filename). County-folder files feed the
  rollup only when no higher-stage copy exists (canonical rule) — future "Combined
  Chart A's" will make the pipeline copy always canonical.
- **Chart A explorer**: everything straight from the workbook — applicants with
  always-visible comments (rich text preserved: bold/italic/line breaks), Files as
  collapsed `<details>`, then the **Prior FEMA history card** (owner-specified,
  refined twice 2026-07-19) at the BOTTOM under Files, always visible, ALL-TIME.
  The chart + declarations list show ONLY declarations with PA activity
  (`applicants>0 || paObligated>0` — the `active` filter); zero-activity
  declarations are excluded everywhere except the roll-up date range. Exact
  order: (1) roll-up stanza — `From <first declared> to <last declared>:` /
  `N Requests for Public Assistance` (spelled out, NOT "RPAs") / `$X PA
  obligated` / `N declarations (with PA applicants/obligations)` — counts the
  ACTIVE set — each on its own line, numbers bold; (2) a READABLE categorical
  DOUBLE bar chart (`histChart`) — dynamic viewBox width (`n*76 + pads`, svg
  `max-width:W*1.5px` so few slots stay large, columns close together), one slot
  per active declaration, x-axis labels stacked horizontally UNDER each slot:
  `DR-####` then the 4-digit YEAR beneath (no rotation); bars: PA applicants
  (navy `--blue-dark`) + PA obligated (green `--m3`, own scale) with per-bar
  value labels (count above navy, compact $ above green; when both bars are
  near-equal height the labels MERGE into one centered `N · $X` to avoid
  touching), tooltips, tiny legend. NOT a time axis (owner rejected the
  time-positioned version as "too crunched" and the full-width tiny version as
  unreadable); (3) the declarations list with DATES (number · declared date ·
  title · applicants · $, newest first, active only); (4) the full
  prior-applicant list (grid: name | disasters comma-concatenated with
  per-disaster PA $ | total; wraps within columns, NO inner scroll — the panel
  is the only scroller); (5) footer with the OpenFEMA source line and **Last
  updated <fetchedAt>**. Data comes from the static snapshot (`build_history.py`),
  NEVER live. **No parser flags in the pane** (Data health only). No "last touch"
  anywhere in the UI.
- **Header**: thin navy band — "PA PDA Summary Dashboard" (retitled from
  "Operations" 2026-07-27, owner) + PDA/event dropdown
  (options like `IN PA PDA - July 2026 (Combined)`, Combined default) + Table A/Chart A
  pills + sun/moon theme icon. SharePoint-export stamp lives in the footer.
- **No emoji anywhere** (color-emoji tofu/compositing bugs on the owner's machine);
  file icons are CSS letter chips. **No external requests** — Public Sans is embedded
  as a data-URI variable font; the board must work from file:// and inside a
  locked-down Databricks App.
- Owner explicitly does NOT want: validation-quality rollups (orig/eligible/reduced),
  decision-context cards, applicant complete/in-progress metrics. "Daily movement"
  band is a v2 idea — movers stay in the collapsed fold until there are ≥2 snapshots.

## Refresh SOP (live PDA)

1. SharePoint library → flat view → Export to Excel → save over `PDAExamples/query.xlsx`
   (or the real drop folder).
2. Copy current Chart A's + Table A workbook into the drop.
3. `python pipeline.py` → open/refresh `out/board.html`. Each run appends a snapshot
   (skipped when nothing changed); movers populate from the second snapshot.

## Session memory

Cross-session context lives in the user memory file `pda-board-databricks.md`
(auto-recalled). Keep it updated when the design moves.
