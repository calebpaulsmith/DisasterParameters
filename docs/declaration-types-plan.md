# Declaration-Type Toggle (DR / EM / COVID) — Plan & Living Spec

**Status:** proposed, not built. Source of truth for the feature; update as phases land;
do **not** let scope shrink — see [§9 Deferred registry](#9-deferred--do-not-drop).

---

## 0. Intent (owner's, preserved)

The app is currently **DR-only** (major disaster declarations). It silently excludes
**13 Region 5 emergency declarations** (EM, FY2007+; ~**$40.5M PA obligated**, **$0 IHP**;
biggest are 2006–2008 snow emergencies + the 2007 Minneapolis I-35W bridge collapse), and
treats **COVID** (incidentType Biological) as a separate carved-out view.

Goals:
1. **Ingest EMs into the data** so nothing is silently missing (traceability), **but keep
   them unsurfaced by default** — the app stays DR-first. EMs are **not equivalent to DRs**
   (lesser tier: PA Category B emergency-protective-measures mainly, rarely IA/IHP) and the
   UI must keep them **visibly distinct, never conflated**.
2. A consistent **DR / EM / COVID badge + toggle** that folds EM and/or COVID into **every
   surface**, with **DR on, EM + COVID off** by default.

---

## 1. Taxonomy — three mutually-exclusive classes

Every declaration is exactly one class:

- **COVID** = `incidentType == "Biological"` (pandemic; whether DR or EM). Kept apart — its
  PA is ~7× weather and distorts totals.
- **EM** = `declarationType == "EM"` and not Biological (emergency declarations).
- **DR** = `declarationType == "DR"` and not Biological (major disasters — today's ledger).

One helper: `declClass(d) → 'dr' | 'em' | 'covid'`. Default-visible set: `{dr}`.

---

## 2. Data model

- **`disasters.json` records gain `declarationType`** (`"DR"` | `"EM"`) — currently absent
  (the ledger stores no DR/EM marker). `declClass` is derived in-browser (Biological → covid).
- **Ingest EMs — additive + reversible.** New offline builder **`scripts/add_emergencies.py`**
  pulls R5 EM declarations (FY2007+, non-Biological), their costs (`FemaWebDisasterSummaries`),
  designated counties, and declared dates; tags `declarationType:"EM"`; **merges into
  `disasters.json` without touching DR rows** (mirrors `add_history.py`'s additive contract).
  Also backfills `declarationType:"DR"` on existing rows.
  - **Hazards gap:** EM `hz` needs the NOAA Storm Events CSVs (not in the cloud env). EM rows
    land with **costs + declaration meta, `hz` empty + `hazardsPending:true`**, flagged in UI;
    a local hazard pass backfills later (deferred).
- **COVID stays in `covid.json`** (separate). The COVID *toggle* folds `covid.json` into a
  surface (Geography already has a COVID fold-in); the dedicated COVID view remains.
- **Rollups** (`county_declarations.json` + `*ByYear`/applicants/ihp/hmgp) are DR-derived. To
  let Geography honor EM they must be rebuilt with **per-class buckets** (EM $ as its own
  layer). Heaviest change → Phase 3.
- **Lineage/Guardian:** a new committed file or `fetch()` ⇒ update `data/lineage.seed.json` +
  rebuild (our own rule; the Guardian will fail otherwise).

---

## 3. Architecture — one state, one predicate, one component (the linchpin)

The only way "every surface" stays consistent and maintainable:

- **Single global state:** `declView` = Set of visible classes, default `{dr}`, **persisted
  to `localStorage`**, exposed app-wide.
- **One predicate:** `isDeclVisible(d) = declView.has(declClass(d))`. **Every surface funnels
  its disaster iteration through this** (or a shared `visibleDisasters()`), so one toggle
  change is universal. Today surfaces filter ad-hoc; introducing this shared predicate IS the
  core refactor.
- **One reusable control:** a chip row `[ DR ] [ EM ] [ COVID ]` with per-class counts. DR
  solid by default; EM/COVID muted/outlined when off. Clicking a chip flips its class and
  re-renders the active surface via a single `onDeclViewChange()` (mirrors the existing
  view-switch machinery).
- **Distinct styling everywhere:** DR = primary navy; **EM = a distinct "emergency" badge**
  (e.g. amber/outline); COVID = existing COVID styling. Every row/marker/detail carries its
  class badge so EM/COVID can never be read as a major disaster.
- **Aggregates recompute from the toggled set (the core requirement).** Toggling a class on
  folds its dollars **and** counts **into every aggregate** — per-state totals, per-county
  totals, map coloring, timelines, headline sums — not just extra rows. Each location holds
  **per-class buckets** and the displayed total = **sum of only the toggled-on classes**
  (default `{dr}` = today's DR-only totals, byte-for-byte). This is exactly why the Geography
  rollups (`county_declarations.json` + `*ByYear`) must be rebuilt per-class (Phase 3): today
  they bake in DR-only sums, so EM/COVID can't be folded in/out without the split buckets.

---

## 4. Per-surface integration matrix

| Surface | Reads | How the filter applies | Effort |
|---|---|---|---|
| **Ledger** | `disasters.json` | filter rows by `isDeclVisible`; class badge per row + in detail modal | low |
| **Disaster Timelines** | `disasters.json` (+national, denials, pending, request_dates) | lag charts include EM when on; National-EM set deferred | med |
| **Estimate** | `disasters.json` | comparables filtered by class; **keep DR-only for scaling even when EM shown** (note) | low |
| **Watch** | `disasters.json` analogs + live | analog pool honors the filter (EM analogs when on) | low–med |
| **Newsreel** | `newsreel.json` | rebuild to tag class; filter the reel | low (+build) |
| **Geography** | `county_declarations.json` (+nfip, dcihp, recent) | **needs per-class rollup buckets** to fold EM/COVID into map + timeline; COVID fold-in exists | **HIGH** |
| **Analyses** | `context.json` / `event_nexus.json` | analytical/modeling — keep DR-only; respect toggle only if cheap | low / defer |
| **COVID (standalone)** | `covid.json` | unchanged; the COVID toggle elsewhere folds COVID in | n/a |
| **Lineage (Atlas)** | `lineage.json` | gains the new EM builder + `declarationType` field as nodes | low |

---

## 5. Phases (each with a hard acceptance check)

> Anti-dwindle rule: every phase's acceptance includes **"the DR-only default view is
> byte-identical to today"** — turning the feature on must be opt-in, off changes nothing.

- **P0 — Data.** `add_emergencies.py` (additive) → 13 EM rows in `disasters.json` w/
  `declarationType` + costs (`hz` pending); backfill `declarationType:"DR"`; update lineage
  seed; Guardian green. **Accept:** 13 EMs present + tagged EM, DR rows unchanged, `declClass`
  correct; `verify_assistance_model.py` still passes.
- **P1 — Filter infrastructure.** Global `declView` + `isDeclVisible` + `declClass` + the
  reusable badge component + persistence; DR-only default. **Accept:** control renders on a
  surface, toggling re-renders, EM/COVID still hidden by default (no visible change yet).
- **P2 — Direct-read surfaces.** Ledger, Timelines, Estimate, Watch, Newsreel honor the filter
  + show class badges. **Accept:** toggling EM reveals the 13 EMs in the Ledger with EM badges;
  DR-only default identical to today.
- **P3 — Geography.** Per-class rollup rebuild (`county_declarations` + byYear) so EM/COVID
  fold into the map + measure timeline via the toggle. **Accept:** EM toggle shows EM county $;
  DR-only default identical; conservation audits pass.
- **P4 — Polish.** COVID-toggle unification, Analyses, `hazardsPending` affordance, mobile
  parity, detail-modal badges.

---

## 6. Risks / landmines

- **Source-of-truth ledger:** EM ingest must be additive + reversible; DR rows untouched; the
  `survivorState`/assistance fixtures (`verify_assistance_model.py`) must still pass.
- **Rollup rebuilds** are heavy + order-dependent; Phase 3 is gated on the dollar-conservation
  audits (`ihpAudit`, HMGP/mit) — refuse to ship if reconciliation breaks.
- **Hazards gap for EM** (no Storm Events CSVs in cloud) — ship costs-first, flag `hz` pending;
  don't invent hazard numbers.
- **COVID distortion** — COVID stays off by default; never auto-fold into headline totals.
- **"Every surface" scope** — the shared predicate is what makes it tractable; resist bespoke
  per-surface filters (they drift). One state, one predicate, one component.
- **Don't break DR-only default** — it's an acceptance gate on every phase.

---

## 7. Decisions needed (recommendation first)

1. **Toggle scope:** one **global** selection app-wide (badges shown per surface) vs
   independent per-surface toggles. → **Rec: global** (a river approaching flood shouldn't need
   re-toggling per view; matches "across every surface").
2. **EM ingest:** a dedicated additive **`add_emergencies.py`** vs flipping the DR-only filter
   in `build_raw.py`. → **Rec: dedicated additive builder** (safer, reversible, leaves the DR
   pipeline untouched).
3. **COVID:** keep the standalone COVID view **and** add COVID as a fold-in toggle vs fully
   merge COVID into `disasters.json`. → **Rec: keep standalone + add fold-in toggle**
   (least disruption; COVID's magnitude still warrants its own deep-dive).
4. **Geography EM depth in v1:** full per-class rollup (map + timeline + drilldowns) now vs EM
   visible only in the list/timeline surfaces first, Geography in P3. → **Rec: stage it**
   (P2 = list/timeline surfaces; P3 = the Geography rollup).

---

## 8. Open questions

- Where the badge control lives: a per-surface chip row vs one global control in the
  masthead/nav (global control = truest to "app-wide," but each surface may want its own
  placement).
- Estimate comparables: keep DR-only for scaling even when EM is toggled on? (Rec: yes.)
- A National-EM set for the Timelines "National" toggle (an EM variant of `build_national.py`)?

---

## 9. Deferred — DO NOT DROP

| # | Item | Trigger | Note |
|---|---|---|---|
| E1 | **EM hazards** (`hz`) via NOAA Storm Events CSVs | local run w/ CSVs | EM rows ship costs-first; hazards backfilled. |
| E2 | **National-EM set** for Timelines "National" toggle | after P2 | `build_national.py` EM variant. |
| E3 | **EM in the predictor / Estimate model** | after P3 | different tier — may stay DR-only by design. |
| E4 | **EM in denials / request-date cross-cuts** | after P2 | those pulls are DR-only too. |
| E5 | **FM (Fire Management) declarations** | later | 1 R5 FM exists; a 4th class if ever wanted. |
```
