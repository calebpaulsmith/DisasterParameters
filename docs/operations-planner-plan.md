# Disaster Operations Planner — Plan & Living Spec

**Status:** proposed, not built. Source of truth for the feature. Update as phases land;
don't let scope shrink — see [§9 Deferred](#9-deferred--do-not-drop).

---

## 0. Intent (owner's)

A **FEMA-facing planning tool**: for a disaster that is *pending or anticipated*, let the
user **build a plan** — select the states + counties they expect to request/declare for
**PA** and/or **IA** — attach **background reference data** (what those counties drew in
past disasters) and **import the event's PDA estimates + applicants** (CSV), then **save it
as their own named map** and **export it** to drop into the disaster's **SharePoint** page,
a **Databricks** dashboard, or their **own website**.

This is **"plan mode"**, replacing the earlier "Pending badge" idea. Key framing:
- A plan is **prospective + user-authored** — *not* an official declaration, damage estimate,
  or forecast. Counties are **selected by the user**. Every export must say so.
- Two data layers, always distinct: **PDA estimates** (this event, user-imported) vs
  **historical reference** (prior disasters in those counties, from our data).
- This is the concrete realization of the deferred "export a surface" item (lineage §9/D2).

**Not a badge.** The DR/EM/COVID declaration-type toggle (see `declaration-types-plan.md`)
stays a separate feature for *historical* completeness; Pending is removed from it.

---

## 1. Where it lives — standalone page, opened from Geography (decision)

Build as **`planner.html`** (self-contained, like `lineage.html`), reading
`data/r5_counties.json` (geometry) + `data/county_declarations.json` (reference metrics).
Linked from the Geography view (and nav) as **"Disaster Operations Planner"** so it reads as
a Geography special-feature, **but implemented standalone** because:
- The **export artifact is the same page** parameterized by a plan — export becomes nearly
  free instead of something we reverse-engineer out of Geography.
- No risky surgery into Geography's dense lens/measure machinery.
- Isolation: a broken planner can't break the ledger/Geography.

(Owner asked for "a mode in Geography." This honors the intent — reachable from Geography,
feels like a mode — while keeping it a clean, exportable unit. Flag if you'd rather it be
inlined into the Geography view proper.)

---

## 2. The plan object (data model, portable)

A plan is a small JSON, saved to `localStorage` and import/export-able:
```jsonc
{
  "id": "...", "name": "IN Winter Storm 2026 — PA/IA request",
  "createdAt": "…", "author": "…", "notes": "…",
  "scope": { "states": ["IN"] },
  "counties": [
    { "fips": "18001", "name": "Adams", "state": "IN",
      "pa": true, "ia": true,
      "pda": { "paEst": 1250000, "iaEst": 380000, "applicants": 42, "…": null }  // from CSV, optional
    }
  ],
  "layers": ["paObligatedHist", "paProjectsAvg", "iaRegistrationsHist"],  // which reference metrics to show
  "activeMeasure": "paEst",           // what the map colors by
  "disclaimer": "PLAN — user-selected, not an official declaration…"
}
```
Portable + versioned; the export embeds it.

---

## 3. Interaction flow

1. **Scope** — pick state(s) (R5 first; extensible).
2. **Select counties** — click counties on the map to add to the plan; per county toggle
   **PA** and **IA** (a county can be PA-only, IA-only, or both). Running tally.
3. **Background reference layers** — choose which historical metrics to attach/show per
   county (from `county_declarations.json`, §4). Always labeled "historical reference."
4. **Import PDA CSV** (optional) — upload the event's PDA estimates + applicants; map columns
   → per-county `pda` fields (format from owner's example — §5).
5. **Choose the map measure** — color the choropleth by any selected layer or PDA field, via
   a metric picker (mirrors Geography's measure row).
6. **Save** — name + store the plan (localStorage; multiple saved plans); download plan JSON.
7. **Export** — self-contained embeddable map + data (§6).

---

## 4. Background reference layers (existing data, no new pull)

Per county from `county_declarations.json` — **historical, clearly labeled not-this-event**:
- Historical **PA obligated** (all-time) and **per-declaration average**.
- Historical **IHP approved**, **HA/ONA**.
- **# PA applicants** (all-time) and **average per past disaster**.
- **# PA projects** (all-time) and **average**.
- **# prior declarations** + most-recent disaster.
- (These are the "average applicants/projects for a county for previous disasters" the owner
  asked for = all-time total ÷ that county's declaration count.)

Reuses the same choropleth/legend machinery pattern as Geography (GEO_KEY-style metric maps).

---

## 4b. Optional overlays — points on top of the choropleth

Beyond the county fill, the planner supports **toggleable marker overlays**, each independently
switched on and carried into the saved plan + export:

- **Disaster Recovery Centers (DRCs)** — plot open/planned DRC locations (lat/lon, name,
  address, hours, associated disaster) as map markers, so a briefing map shows both the
  **requested counties** and **where survivors get in-person help**. Toggle on/off; included
  in the export when on; own legend.
  - **Data dependency:** binds to the owner's DRC dataset (a committed `data/drc*.json`, or
    OpenFEMA's DRC locations). **As of this writing that data is NOT yet on `main`** (searched
    — no `drc`/"recovery center" file/feature landed here), so the layer is specced now and
    **wired once the DRC data merges**; until then the toggle is a stub. Reconcile the exact
    fields against the merged dataset.
- Future overlays plug in the same way (gages, shelters, PODs, etc.) — see §9.

---

## 5. PDA CSV import (firm requirement — awaiting owner's example)

The user imports the event's **Preliminary Damage Assessment** figures — per-county PA/IA
**estimates + applicants**. Exact columns TBD from the owner's sample; design to be tolerant:
- Match rows to counties by **county name + state** and/or **FIPS**; report unmatched rows.
- Map a configurable set of columns → `county.pda.{paEst,iaEst,applicants,homesAffected,…}`.
- PDA layer renders **distinctly** from historical reference (different legend/label).
- Round-trips into the plan JSON + export. **This is a committed feature, not optional** — it
  stays in the plan; build waits only on the owner's example CSV to pin column names.

---

## 6. Export (the point of the tool)

From a saved plan, produce:
- **(A) Self-contained HTML FILE (the confirmed primary export).** One downloadable `.html`
  with the plan + county geometry + active layers/overlays (incl. DRCs) + a minimal read-only
  map renderer **all inlined** — no network, no dependencies. The user drops the file straight
  into SharePoint (upload / file embed) or hosts it anywhere. **Owner decided: a downloadable
  self-contained file, not an iframe-to-a-hosted-URL** (the shareable-URL path is deferred,
  §9 P-E).
- **(B) Data export** — **CSV/JSON** of the plan's counties + chosen metrics + PDA fields, for
  **Databricks** dashboards / spreadsheets.
- **(C) Image** — PNG/SVG snapshot of the current map (stretch).
- Every export carries the **PLAN / not-an-official-declaration** disclaimer + source note.

v1 priority: **(A) self-contained HTML file + (B) CSV/JSON**.

---

## 7. Guardrails / labeling

- Prominent banner: **"PLAN — counties selected by the user; not an official FEMA declaration,
  damage estimate, or forecast. Historical figures are reference from prior disasters."**
- Keep the OpenFEMA/NOAA/USGS non-endorsement disclaimer in the page + every export.
- PDA figures labeled as user-imported preliminary estimates, never as obligations.

---

## 8. Phases (each ships something usable)

- **P0 — Planner core. ✅ SHIPPED (PR #98).** `planner.html`: state + county selection on the
  R5 map, PA/IA per county, historical reference layers, save/load/download/import plan
  (localStorage + JSON), masthead link.
- **P1 — Layers + county detail card. ✅ SHIPPED.** Reference-layer picker expanded to PA
  (obligated/avg, projects/avg, applicants), IA/IHP (approved, HA, ONA, registrations), and
  HMGP (obligated/avg, subrecipient count) — grouped `<optgroup>`s in the layer select.
  Clicking a county now opens a **detail modal** (replacing the old instant-toggle click) with:
  a full per-disaster breakdown (PA $, IHP $ split into HA/ONA via `disaster_county_ihp.json`
  where available, DRC count via `disaster_drc.json`), the PA-applicant table, the HMGP
  subrecipient table, and the Add-to-Plan PA/IA toggles + remove control. All of this reads
  from already-committed data — **no live per-disaster-county fetch needed** (unlike
  Geography's mobile drill-down, which fetches PA live); `county_declarations.json`'s
  `disasters[]` array already carries per-disaster PA $ + IHP $ per county.
- **P2 — PDA CSV import. ✅ SHIPPED (generic schema, pending owner's real example).** Tolerant
  header-matching importer (`County/State/FIPS/Applicant/Category/Estimated PA $/Estimated IA
  $/Notes`, with common synonyms recognized) matches rows to counties by FIPS or
  name+state, aggregates to `plan.counties[fips].pda` (`paEst`, `iaEst`, `applicants[]`,
  `byCategory`), and reports unmatched rows inline (never silently dropped). A
  **downloadable CSV template** button lets the owner copy their PDA numbers in without
  guessing the format. Rendered as its own distinctly-labeled "PDA — this event" section in
  the county modal, plus 3 dedicated map layers (`pdaPaEst`/`pdaIaEst`/`pdaApplicants`). **Once
  the owner's real PDA export is in hand, revisit the alias list / column order** — it was
  built from a best guess, not the real file.
- **P3 — Export = self-contained HTML file (§6A) + CSV/JSON. ✅ SHIPPED.** "Export
  self-contained HTML" builds one downloadable file with county geometry (states-in-scope,
  for regional context) + a **fully resolved snapshot** per plan county (historical figures +
  every prior disaster's PA/IHP HA-ONA split + DRC counts + PA/HMGP applicant tables + PDA)
  baked in as plain JSON — no fetch, no dependency on the live datasets, matching the "drop
  into SharePoint" requirement. DRC entries are exported as a **count badge only** (not full
  address/hours cards) to keep the export lean — full DRC detail stays in the live planner
  (`disaster_drc.json`) and in Geography. "Export data CSV" gives one row per plan county
  (historical + PDA fields) for Databricks/spreadsheets. Verified end-to-end with a headless
  Playwright smoke test (map render, modal open, CSV import incl. an unmatched row, both
  exports).
- **P3b — A–Z picker + PA applicant history analysis. ✅ SHIPPED (owner's 2026-07 asks).**
  (1) **A–Z county picker**: a searchable alphabetical list ("Add counties from A–Z list",
  filtered to states-in-scope) alongside the map click; the counties-in-plan list was already
  alphabetical. (2) **"PA applicant history — counties in plan" card** (below the map), backed
  by a NEW committed artifact `data/planner_applicants.json` (`scripts/
  build_planner_applicants.py`): PA Summaries kept at the applicant×county×**disaster** grain
  (county_declarations only carries all-time rollups), plus per-(disaster,applicant) **damage
  category** rollups from PA Details v2 joined via the `PublicAssistanceApplicants` id→name
  bridge (Details carries no applicant name), display names canonicalized against the deduped
  county lists, dollars conserved (c/s/u/x buckets + audit; unattributable category $ stay in
  the audit). The card answers the owner's questions: **which applicants** in the selected
  counties, **which disasters, how much each, which categories** — as **two drillable lists**
  (Aggregated across selection · By county), with **statewide/state-agency (no-county) and
  undeclared/unresolved applicants listed separately and labeled**, an **expectations block**
  (median/mean applicants + projects per prior disaster touching the selection, with and
  without statewide), and **three CSV exports** (aggregated applicant×disaster, by-county,
  expectations). Selection basis = PA-flagged plan counties (falls back to all, labeled).
  Guardian extended: surface fetch checks now resolve against each surface's own HTML file
  (planner.html), not just index.html.
- **P4 — Program-first redesign + teams + disaster seeding + SharePoint export. ✅ SHIPPED
  (owner's 2026-07 redesign ask).** Four pieces, all in `planner.html`:
  1. **Program-first lens (replaces raw layer-picking as the primary control).** A PA / IA·IHP /
     HMGP chip row drives everything: the map measure list is scoped to the program (with an
     "Auto" headline measure — expected PA applicants for PA, expected IA registrations for IA),
     and the bottom card becomes a program-scoped **Expectations** engine: top-level
     median/mean per-disaster figures (PA: applicants, projects, $ — incl./excl. statewide;
     IA: registrations, IHP $ with HA share; from registrant-level `disaster_county_ihp.json`,
     NOT the disaster-level `disasters[].ihp` field), an **expected categories-of-work** mix
     (share of historical PA $ by Category A–G/Z, whole-disaster grain — labeled, since a
     per-county category split would be false precision), a **per-county expectations table**
     (the "as granular as possible" ask), and the existing drillable applicant lists (PA).
     **Live disaster exclusion:** every prior disaster in the math renders as a chip with ✕ /
     ↩ — excluded DR numbers (`plan.excludedDns`) drop out of ALL expectation stats, map
     `exp*` measures, exports, and the modal, in real time. **Outlier suggestion:** modified
     z-score (median/MAD, >3.5 and >2× median, high side only) flags "outlier?" on chips.
     HMGP intentionally stays all-time reference (no per-event expectation is honest — HMGP
     reconciles for years; exclusions don't apply there and the card says so).
  2. **Start from a declared disaster.** New committed artifact `data/disaster_designations.json`
     (`scripts/build_disaster_designations.py`, from DisasterDeclarationsSummaries v2): per
     disaster × county a PA/IA/HM program bitmask (IA bit = ih OR ia, per the glossary), with
     statewide/tribal non-county designations conserved. The planner's "Start from a declared
     disaster" picker seeds the plan with exactly the counties designated for the chosen
     program(s) — the PA and IA designation lists genuinely differ (e.g. DR-4892: 3 IH counties,
     0 PA counties). Sets `plan.basis`, auto-names the plan, and **auto-excludes the seeded
     disaster from the expectation math** (it's the event being planned; restorable via chip).
     This closes deferred item **P-A** (and the P4 "auto-fill counties" idea).
  3. **Team divider.** `plan.teams` (name, members, auto-assigned color). Assign counties via
     an armed "assign" mode (click counties on the map) or per-county dropdowns (list + modal).
     "Color map by: Teams" fills counties by team color with a team legend; the Expectations
     card gets a **team board**: per team, its counties + applicant workload from all three
     sources, labeled — **PDA applicants** (imported), **applicants/registrations on the basis
     disaster so far** (from `planner_applicants.json` / `disaster_county_ihp.json` when the
     plan was seeded from a declaration), and **historical medians** summed across its counties.
  4. **Exports for SharePoint** (see `docs/planner-sharepoint-export.md` for the full plan +
     tenant constraints): **"Copy for SharePoint"** puts a script-free, inline-styled HTML
     fragment (map as PNG data-URI, expectations/categories/team/county tables, disclaimer)
     on the clipboard as `text/html` for direct paste into a Text web part (falls back to
     downloading the fragment); **"Download map PNG"** for an Image web part; the
     **self-contained HTML export** now bakes in program, expectation summary, exclusions,
     team assignments + team-colored map fill, and per-county expected figures — this also
     retires P3's "fold the applicant card into the export" note. Data CSV gained
     Team/expectation columns; a new **IA expectations CSV** joins the three PA applicant CSVs.
- **P5 — Declutter + PA-first + roll-up + COVID guard. ✅ SHIPPED (owner's 2026-07 follow-up).**
  The P4 expectations card stacked ~8 sections at once and read as a tangle. Restructured to a
  clear **3-tier PA-first** layout (owner: "divide & staff the work, but give me a roll-up + a
  comparison to previous events"; headline metric = **expected PA applicants per county**; IA
  becomes its own view later):
  1. **Roll-up band** (`rollupHTML`) — the answer at a glance: plan-total expected PA applicants
     / projects / $ (sum of per-county medians), a **vs-past-events** baseline (a typical prior
     disaster that hit these counties drew *median* applicants, *range* min–max, across N events),
     and **closest named analogs** ranked by county-footprint overlap (`perDn.nCty`). Covers the
     owner's "roll-up" + "comparison to previous events" asks (they picked **both** flavors).
  2. **Team divider promoted** — each team gets an expected-PA-applicant **load bar + balance
     meter** (±% vs the average, busiest-vs-lightest spread) so imbalance is obvious without
     auto-assigning (owner picked "show load + a balance meter", not auto-split).
  3. **Per-county expectations table** — the field-team-facing granular row (applicants / projects
     / $ / top categories per county).
  Applicant rosters, category mix, and the exclusion + per-disaster tables moved **behind
  `<details>` disclosures** (kept, just out of the main flow; the exclusion panel auto-opens when
  outliers or manual exclusions exist). **COVID-19 is now explicitly guarded out of every
  calculation** (`COVID_DNS`/`isCovid()` across `paCountyHistory`/`iaCountyHistory`/`computeAppl`/
  `computeIa`/`buildDindex`/`buildCountySnapshot`) and **labeled** in the roll-up header — the six
  R5 COVID declarations were already absent from the planner's data files, so this is
  belt-and-suspenders + honest labeling, not a data fix. Verified with the headless smoke test
  (now 38 checks, incl. roll-up render, vs-past-events, load bars, and a COVID-absence assertion).
- **P6 — Caseload board: Task Forces → PDMGs → applicants. ✅ SHIPPED (owner's 2026-07 ask).**
  A staffing UI implementing the FEMA PA delivery org (owner: "assign a number of PDMGs to
  specific TFLs, then assign applicants to PDMGs; show applicants' previous PA info + expected $").
  - **TFLs = the existing county-teams, renamed** (owner: "TFLs own counties — usually multiple").
    Auto-named "Task Force A/B/C" (renameable); the side-panel "Teams" control is relabeled
    "Task Forces (TFL)". The `members` field is the TFL lead's name.
  - **PDMGs** nest under each task force (`team.pdmgs[]`), auto-named "PDMG 1/2/3", created
    **by count** ("Add N PDMGs") *or* singly ("Add one"), renameable, deletable (owner: "both").
  - **Applicants** come from the **historical roster** (named past PA applicants for the plan's
    counties, from `computeAppl` — each already carries prior PA $, # disasters, and an expected
    $/disaster = per-disaster average) **and/or an imported PDA** (owner: "could be PDA, could be
    real"), switchable via a source toggle; PDA applicants are name-matched to history
    (`normApplName`) so their prior-PA figures show too. Each applicant is **assigned to a PDMG**
    (`plan.caseload{applicantKey→pdmgId}`), **reassignable to any task force** (a dropdown lists
    every TFL▸PDMG); the unassigned pool suggests the task force that owns most of the applicant's
    counties. Per-PDMG and per-TFL rollups (count + expected $), a name filter, and a **caseload
    CSV export**. COVID-19 excluded throughout (same guards). New smoke coverage (49 checks total).
- **P7 — Polish (not yet built).** The **IA "diff view"** (owner wants a separate by-county
  *registrations* view — data is ready via `disaster_county_ihp.json`), multiple saved plans,
  mobile layout pass, full-card (not just map) snapshot export, folding the roll-up + team load +
  caseload into the SharePoint/HTML exports, and PDA↔historical-applicant reconciliation (P-I) now
  that the caseload board already does light name-matching.

---

## 9. Deferred — DO NOT DROP

| # | Item | Trigger | Note |
|---|---|---|---|
| P-A | ~~**Auto-fill counties from OpenFEMA** once the disaster is declared~~ | ✅ DONE (P4) | `disaster_designations.json` + the "Start from a declared disaster" picker, program-filtered (PA vs IA designated counties differ). |
| P-B | **Pre-fill requested counties from JPDA/brief** where available | after P2 | sparse coverage; a convenience seed for the picker. |
| P-C | **National scope** (beyond R5) | when needed | needs national county geometry + rollups. |
| P-D | **Estimate/analog auto-suggest** — predicted $ from comparables | later | crosses into prediction; keep clearly separated + labeled if ever built. |
| P-E | **Shareable-URL / live embed hosting** (Cloudflare) — plan encoded in URL | after P3 | secondary to the confirmed self-contained-file export; deferred by owner. |
| P-F | **Wire the DRC overlay** (§4b) to the real dataset | when DRC data merges to `main` | not on `main` yet; layer is stubbed until then. Reconcile fields. |
| P-G | **More overlays** (gages, shelters, PODs) | as needed | same marker-layer machinery as DRCs. |
| P-I | **PDA ↔ historical-applicant reconciliation** ("that's for later" — owner, 2026-07) | after P3b + a real PDA import | Compare the imported PDA's applicant list against the historical applicant roster for the selected counties (planner_applicants.json): how many expected applicants are already accounted for in the PDA, who's historically active but missing, who's new. Name-match via the same normalize() logic (port to JS or precompute normalized keys into planner_applicants.json). |
| P-H | **PA Second Appeals Tracker** (OpenFEMA — FEMA's first/second-appeal outcomes for PA determinations, distinct from the declaration-request appeals already in `request_dates.json`) | when built | Owner's ask: county drill-down should eventually show PA appeal history. Scoped out of this revamp — **owner said this needs to land in the Geography tab first**, then the planner would read the same data. Not yet on `main`; dataset confirmed to exist (`fema-public-assistance-second-appeals-tracker`, migrating to OpenFEMA CSV/JSON/Parquet) but not yet pulled/committed here. |

---

## 10. Open questions / needs from owner

**Resolved (owner):**
- **Export = a downloadable self-contained HTML file** (not iframe-to-hosted-URL). §6A.
- **Standalone `planner.html`**, reachable from the app (shipped in P0). §1.
- **DRC support** is required, as an **optional layer** (§4b) — wired in the P1/P3 revamp via
  a per-disaster DRC count badge (`disaster_drc.json`, now on `main`). Full DRC address/hours
  detail is intentionally left out of the modal/export for now (available in Geography); could
  be added later if wanted (P-G-style).
- **County drill-down depth**: full per-disaster breakdown (not just aggregate totals) —
  shipped in P1.
- **PDA CSV**: build a generic importer now + a copy-paste-able template, refine once the
  owner's real PDA export arrives — shipped in P2.
- **"Appeals" in the county drill-down** = the **PA Second Appeals Tracker** (first/second
  appeal outcomes on PA determinations), not the declaration-request appeals already covered
  elsewhere. **Deferred** — logged as P-H above; owner wants it built in Geography first.

**Still open:**
- **Real PDA CSV example** — once in hand, reconcile column names/order against the generic
  importer's alias list (`PDA_ALIASES` in `planner.html`) and tighten it.
- Scope: R5 only for v1 (assumed) or national?
- P4 polish items (multiple saved plans, mobile pass, PNG/SVG, SharePoint embed doc) — not
  started.
