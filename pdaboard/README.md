# PDA Board

A live operations board for an **ongoing FEMA Preliminary Damage Assessment**:
an interactive county map you watch like a game overview — hover a county for
the critical rollup, click it for the full drill-down (applicants, Cat A–G,
threshold math, validation comments) and links to that county's SharePoint
files. Built for the **IN PDA July 2026**; multi-PDA by design.

This folder is the **local development harness** for the Databricks product
described in [`../docs/pda-databricks-dashboard-plan.md`](../docs/pda-databricks-dashboard-plan.md).
The parser and pipeline are pure Python (openpyxl only — no pandas/Spark), so
the same modules run unchanged inside a Databricks job; `templates/board.html`
is the reference UI for the Databricks App port.

> **Only the tool code is public; PDA data never is.** This repo is public. The
> root `.gitignore` allowlists the code under `pdaboard/` (parsers, pipeline,
> template, notebooks, VBA source, public county/history reference data, scrubbed
> manifests, this README, `setup.html`) and ignores everything that carries live
> content — `PDAExamples/` (real workbooks), `out*/` (built boards with baked
> figures), `tests/` (hardcoded totals + an inspector name), `excel/*.xlsm`,
> `query.xlsx`, and `docs/pda-databricks-dashboard-plan.md`. Never commit those,
> and never set a real `sharepoint_base`/`master_folder` in a committed manifest.
> New to the tool? See **[`setup.html`](setup.html)** for the full local walkthrough.

## Quickstart

```bash
cd pdaboard
python pipeline.py                 # parses PDAExamples/ -> out/board.html + gold CSVs
python -m http.server 8137 --directory out   # then open http://localhost:8137/board.html
python -m pytest tests -q          # golden tests (~4 min, needs PDAExamples)
python rehtml.py                   # re-render board.html after template-only edits
```

## What it does

1. **`sp_filetree.py`** parses `query.xlsx` (SharePoint "Export to Excel" of the
   PDA library) and owns the **four-stage validation model** — a Chart A's
   stage is *where it sits* in the folder workflow:

   | # | Stage | Folder |
   |---|---|---|
   | 1 | Working | `Damage Data/Counties/<County>/` (field copies) |
   | 2 | For PDA Lead Review | `Chart A's/1. For PDA Lead Review/` (+ loose Chart A's root) |
   | 3 | Ready for Table A | `Chart A's/2. Ready for Table A/` (a local `Validated/` ranks the same) |
   | 4 | Entered in Table A | `.../2. Ready for Table A/Entered in Table A/` |

   (0 = Not started: county in scope, no Chart A anywhere.) Dropped files lose
   their SharePoint folder context, so each is **matched back to the export**
   by filename (size as tiebreaker) to recover stage / modified / author / URL.

2. **`chart_a_parser.py`** parses Chart A workbooks (county, population,
   threshold, inspector, applicant rows with Cat A–G + status + comments) and
   the Table A master (Input Sheet, Summary, Reductions). Trust rules: county
   identity from the cell (filenames lie), every total **recomputed** from the
   Cat A–G inputs and reconciled against the workbook's own cells — mismatches
   are flagged, never silently resolved.

3. **`pipeline.py`** joins it all into gold rows (county × event), applies the
   canonical rule for duplicate copies (highest stage wins; tie → latest
   modified), evaluates the per-capita indicators (read from Table A, never
   hardcoded), computes the **statewide inclusion math** from the PDA Guide
   (July 2025, "Per Capita Impact Calculations": counties ≥100% of the county
   PCI always count toward the statewide PCI; 50–99% counties count only once
   the ≥100% counties alone cover 75% of the statewide PCI; <50% counties are
   excluded; un-allocated REMC $ reported separately), reconciles
   Chart A ↔ Table A, appends an immutable snapshot (→ the ticker + "movers
   since last refresh"), and renders `out/board.html`.

   Each county's pane renders its SharePoint folder as a **file tree** (every
   subfolder + document, all links; from the export when live, from the drop
   layout when completed) plus a direct **Chart A workbook** link. Completed
   boards drop the Chart-A-pipeline list and the prior-history timeline chart.

4. **`templates/board.html`** — the board itself: single self-contained file,
   vanilla JS, dark ops-room theme + light theme, event switcher
   (per-incident-period thresholds), stage/%-of-indicator map modes, click
   panel with SharePoint file links, sortable county table, data-health drawer.

## Config

- **SharePoint links come from `query.iqy`** — the little web-query file
  SharePoint saves *with* the Export to Excel. `query.xlsx` carries only
  server-relative paths; the `.iqy` carries the **site host** and this PDA's
  **root folder**, which is everything the links need. Drop it in the PDA
  folder (any `*.iqy`) or pass `--iqy <file>`; `pipeline.resolve_links()`
  resolves each field manifest → `query.xlsx` → `.iqy` and bakes working file +
  county-folder links. No `.iqy` and no manifest base → a
  `NO_SHAREPOINT_LINKS` health note and inert links, never a guessed URL.
  **Swappable in the board**: Admin → *SharePoint links* (on a COMPLETE board
  the Admin surface is a discreet gear) loads another PDA's `.iqy` in the
  browser — same parse, no network — and re-points every link, or takes the two
  URLs typed by hand; *Reset* returns to the baked values. Stored per PDA in
  `localStorage`.
- **A master (library-wide) query works too.** An export or `.iqy` rooted at
  `Ongoing PDA's` covers every PDA, so it is narrowed to this one: the export's
  PDA folders are enumerated and picked by `sp_folder` (manifest / `--sp-folder`)
  or by a name match on state + month + year, and the filetree is filtered to
  that subtree (`MULTI_PDA_EXPORT` in Data health; `AMBIGUOUS_PDA_EXPORT` when
  nothing matches — never a guess). A master `.iqy` has no listing, so it can
  only name the parent; the board's **PDA folder** picker (or `sp_folder`)
  supplies the rest.
- `manifest.json` — per-PDA: events + optional `sharepoint_base` /
  `master_folder` overrides (normally left empty — the `.iqy` supplies them). **Indicators are never configured here** — the state/county
  PCIs and state population are read from the Table A workbook, and each county
  threshold from that county's own Chart A, so the board tracks whatever fiscal
  year the source workbooks carry. (`state_pci`/`county_pci`/`state_population`
  keys are honored only as an emergency override; a drop with no Table A gets a
  `NO_STATE_INDICATOR` health flag instead of silently guessed numbers.)
- `data/dim_county_in.csv` + `data/in_counties_geo.json` — built by
  `build_dim_county.py` (populations from the Chart A's own hidden lookup;
  FIPS derived + anchor-asserted; geometry from Census 20m via plotly mirror).

## Prior FEMA history (static OpenFEMA snapshot)

Each county's Chart A explorer ends with a **Prior FEMA history** card
(all-time; chart/list filtered to declarations WITH PA applicants or
obligations): a roll-up (`From <first> to <last>:` / `N Requests for Public
Assistance` / `$X PA obligated` / `N declarations (with PA
applicants/obligations)`), a categorical **double bar chart** (one slot per
active declaration, DR number + year stacked beneath; navy = PA applicants,
green = PA obligated on its own scale), the declaration list with dates, then
every prior PA applicant with its disasters comma-concatenated and the PA
dollars obligated **per disaster**, and a **Last updated** stamp.

The data is pulled **as of the run date** straight from OpenFEMA and frozen in
`data/history_in.json` — the board itself makes zero network calls, so the
exported `board.html` carries the history with it. Refresh the snapshot with:

```bash
python build_history.py            # -> data/history_in.json, then: python pipeline.py
```

### The exact queries (for the Databricks v2 dynamic version)

Plain HTTPS GET, JSON out; paginate `$skip` by 1000 until a page returns fewer
than 1000 rows. Both URLs are also embedded verbatim in `history_in.json`
under `queries`, alongside `fetchedAt`.

1. **Applicant history** — one row per *applicant × county × disaster* with
   federal PA dollars obligated + project count:

   ```
   https://www.fema.gov/api/open/v1/PublicAssistanceFundedProjectsSummaries?$filter=state eq 'Indiana'&$orderby=id&$top=1000&$skip={skip}&$inlinecount=allpages
   ```

2. **Declarations** — one row per *disaster × designated area* with title,
   dates, program flags, county FIPS (the timeline spine):

   ```
   https://www.fema.gov/api/open/v2/DisasterDeclarationsSummaries?$filter=state eq 'IN'&$orderby=id&$top=1000&$skip={skip}&$inlinecount=allpages
   ```

Rules that must carry over to any port: never combine `$select` with
`$filter`+`$top` (FEMA's edge WAF intermittently 503s it — pull full rows);
dollars are **federal share obligated**; COVID-19 (`incidentType eq
'Biological'`) is excluded; Summaries' `county` is a *name* ("Marion",
"Statewide", or blank) while declarations carry real FIPS — unresolvable rows
land in a statewide/audit bucket, never dropped (`build_history.py` exits
nonzero if the dollars don't conserve).

## Refresh SOP (during a live PDA)

1. SharePoint library → flat view → **Export to Excel** → save over `query.xlsx`.
2. Copy the current Chart A's (+ Table A workbook) into the drop folder.
3. `python pipeline.py` → refresh the browser. Each run is a ticker point;
   changes since the previous run appear under "Movers".

## Port to Databricks (next)

Volume = the drop folder; job steps = `load_filetree` → parse → `build()`;
gold dicts → Delta tables; board = Databricks App (or serve this HTML as-is).
See the plan doc §4–§7 for the full mapping.
