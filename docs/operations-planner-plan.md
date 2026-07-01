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

## 5. PDA CSV import (awaiting owner's example)

The user imports the event's **Preliminary Damage Assessment** figures — per-county PA/IA
**estimates + applicants**. Exact columns TBD from the owner's sample; design to be tolerant:
- Match rows to counties by **county name + state** and/or **FIPS**; report unmatched rows.
- Map a configurable set of columns → `county.pda.{paEst,iaEst,applicants,homesAffected,…}`.
- PDA layer renders **distinctly** from historical reference (different legend/label).
- Round-trips into the plan JSON + export. **Blocked on the example CSV.**

---

## 6. Export (the point of the tool)

From a saved plan, produce:
- **(A) Self-contained embeddable HTML** — one file with the plan + county geometry + a
  minimal map renderer inlined; iframe-able into **SharePoint** (embed web part) or any
  **website**. Also a **shareable URL** with the plan encoded (hash) pointing at the hosted
  `planner.html` in view-only mode.
- **(B) Data export** — **CSV/JSON** of the plan's counties + chosen metrics, for
  **Databricks** dashboards / spreadsheets.
- **(C) Image** — PNG/SVG snapshot of the current map (stretch).
- Every export carries the **PLAN / not-an-official-declaration** disclaimer + source note.

v1 priority: **(A) embeddable HTML + (B) CSV/JSON**.

---

## 7. Guardrails / labeling

- Prominent banner: **"PLAN — counties selected by the user; not an official FEMA declaration,
  damage estimate, or forecast. Historical figures are reference from prior disasters."**
- Keep the OpenFEMA/NOAA/USGS non-endorsement disclaimer in the page + every export.
- PDA figures labeled as user-imported preliminary estimates, never as obligations.

---

## 8. Phases (each ships something usable)

- **P0 — Planner core.** `planner.html`: state + county selection on the R5 map, PA/IA per
  county, one historical reference layer, save/load plan (localStorage + JSON). **Accept:**
  select a handful of IN counties as PA+IA, save, reload → plan restored; map colors a
  historical metric.
- **P1 — Layers + county cards.** Full background-metric picker (§4) + per-county detail
  popover; measure switcher.
- **P2 — PDA CSV import** (after owner's example) — map columns → per-county PDA fields,
  distinct PDA layer, unmatched-row report.
- **P3 — Export.** Self-contained embeddable HTML + shareable URL + CSV/JSON. Link from
  Geography + nav.
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
| P-E | **Live embed hosting** (Cloudflare) for the shareable URL | with P3 | vs pure downloadable HTML. |

---

## 10. Open questions / needs from owner

- **The PDA CSV example** (blocks P2) — columns, county key (name vs FIPS), PA vs IA fields.
- Standalone `planner.html` (recommended) vs inlined into the Geography view — confirm.
- Export priority: embeddable HTML first (assumed) — confirm SharePoint embed mechanism
  (iframe web part vs file upload).
- Scope: R5 only for v1 (assumed) or national?
