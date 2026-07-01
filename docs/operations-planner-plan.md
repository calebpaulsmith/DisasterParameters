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
- **P1 — Layers + overlays + county cards.** Full background-metric picker (§4), per-county
  detail popover, measure switcher, **+ the optional DRC point overlay (§4b) once its data
  lands**.
- **P2 — PDA CSV import** (firm; after owner's example) — map columns → per-county PDA fields,
  distinct PDA layer, unmatched-row report.
- **P3 — Export = self-contained HTML file** (§6A) + CSV/JSON. Everything inlined (geometry,
  active layers, DRC overlay), read-only, no network. Deeper Geography/nav entry point.
- **P4 — Polish.** Multiple saved plans, mobile, PNG/SVG, a short "embed in SharePoint" doc,
  optional "when declared, auto-fill counties from OpenFEMA designated areas."

---

## 9. Deferred — DO NOT DROP

| # | Item | Trigger | Note |
|---|---|---|---|
| P-A | **Auto-fill counties from OpenFEMA** once the disaster is declared | after P3 | designated areas → FIPS; plan flips from "requested" to "declared". |
| P-B | **Pre-fill requested counties from JPDA/brief** where available | after P2 | sparse coverage; a convenience seed for the picker. |
| P-C | **National scope** (beyond R5) | when needed | needs national county geometry + rollups. |
| P-D | **Estimate/analog auto-suggest** — predicted $ from comparables | later | crosses into prediction; keep clearly separated + labeled if ever built. |
| P-E | **Shareable-URL / live embed hosting** (Cloudflare) — plan encoded in URL | after P3 | secondary to the confirmed self-contained-file export; deferred by owner. |
| P-F | **Wire the DRC overlay** (§4b) to the real dataset | when DRC data merges to `main` | not on `main` yet; layer is stubbed until then. Reconcile fields. |
| P-G | **More overlays** (gages, shelters, PODs) | as needed | same marker-layer machinery as DRCs. |

---

## 10. Open questions / needs from owner

**Resolved (owner):**
- **Export = a downloadable self-contained HTML file** (not iframe-to-hosted-URL). §6A.
- **Standalone `planner.html`**, reachable from the app (shipped in P0). §1.
- **DRC support** is required, as an **optional layer** (§4b). Owner reports merging DRC work,
  but it is **not on `main`** here yet — wire on arrival (P-F).

**Still open:**
- **The PDA CSV example** (blocks P2) — columns, county key (name vs FIPS), PA vs IA fields.
  Owner can't provide yet; feature stays firmly in the plan.
- The **DRC dataset's exact fields/location** (once it lands) — to bind the overlay.
- Scope: R5 only for v1 (assumed) or national?
