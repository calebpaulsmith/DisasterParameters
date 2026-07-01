# SBA Disaster Loan Data — Feasibility Research (CURSORY / INITIAL)

**Status:** research only, nothing built. This is a first pass, done in one sitting by
pulling one sample year and eyeballing it — **not a full survey**. Treat every number
below as directional, not final. Better sources than the ones below may exist and
haven't been checked yet (see §5). Re-verify before building anything on top of this.

---

## 0. Why this exists

While scoping a DRC (Disaster Recovery Center) layer for the Geography IA section, SBA
disaster loans came up as "another area we gotta add to IA." SBA physical/EIDL disaster
loans are a real, distinct assistance program (separate from FEMA IHP) that survivors and
businesses use after a declaration, so it's a reasonable candidate for the IA section. This
doc captures what a first look at the actual public data found, so the decision to build
(or not) is informed — and so a later session doesn't have to re-discover the same gotchas.

## 1. What's public

**`data.sba.gov`** hosts a "Disaster Loan Data" dataset: one `.xlsx` file per fiscal year,
FY2000 through FY2022 (24 resource files; dataset last-updated stamp: **May 8, 2024**). No
newer fiscal year is currently published. There is **no REST/JSON API** behind this —
it's flat bulk spreadsheet downloads, not a CKAN datastore (confirmed: `datastore_search`
against a resource ID 404s).

Each file has two data sheets, **`FY{YY} Home`** and **`FY{YY} Business`**, both sharing
this schema (verified by downloading and parsing FY2020 with `openpyxl`):

| Column | Notes |
|---|---|
| `SBA Physical Declaration Number` | SBA's own declaration number |
| `SBA EIDL Declaration Number` | Economic Injury Disaster Loan declaration number |
| **`FEMA Disaster Number`** | **The join key to `disasters.json.disasterNumber` — but sparsely populated, see §2** |
| `SBA Disaster Number` | e.g. `IL-00058` — SBA's own state+sequence numbering, always present |
| `Damaged Property City/Zip/County/State` | Geography — county-name level, no street address, no PII |
| `Total Verified Loss` (+ split Real Estate / Content) | |
| `Total Approved Loan Amount` (+ split Real Estate / Content) | |
| `Approved Amount EIDL` | Business sheet only |

Rows are already aggregated to city+zip+county (not per-borrower — no names/addresses),
so this is inherently county-level rollup data, not point-facility data like DRC. That
makes it a natural fit for a **measure/choropleth**, not a badge — if it gets built, it
belongs alongside the existing IA measure chips (HA $ / ONA $ / Registrations), not as a
click-to-expand indicator.

## 2. The three problems found

1. **Stale.** Newest published fiscal year is **FY2022**; the dataset hasn't moved since
   May 2024. SBA itself has publicly acknowledged a data gap covering roughly mid-2020
   through late-2023 tied to a system migration (Disaster Credit Management System →
   whatever replaced it). Practically: any Region 5 disaster from the last several fiscal
   years would show **nothing** for SBA. This is a much bigger lag than anything else in
   this app (PA/IHP obligations lag by months; this lags by years).

2. **Most rows don't carry a FEMA number.** Downloaded FY2020 and filtered to the six
   Region 5 states directly:
   - Home sheet: **76 of 619** R5 rows (12%) had `FEMA Disaster Number` populated.
   - Business sheet: **39 of 384** R5 rows (10%) had it populated.

   The rest have an `SBA Disaster Number` (e.g. `IL-00058`) but a blank FEMA field —
   these are SBA's own **administrative** or **EIDL-only (economic injury)**
   declarations, which SBA can issue independently of a Presidential/FEMA declaration
   (the sheet header literally lists `Declaration Type(s): 'PRES_IA','PRES_PA',
   'ADMINISTRATIVE'`, but that breakdown isn't a per-row column — only inferable from
   whether the FEMA field is filled). Only ~10-12% of the sampled rows have that clean
   FEMA tie; the rest would need a separate SBA-declaration↔FEMA-DR crosswalk that
   doesn't ship with this data. Only one fiscal year (FY2020) was checked — this ratio
   is a single data point, not a validated trend across years.

3. **Bulk-file pipeline, not a live query.** Building this means downloading and parsing
   `.xlsx` per fiscal year offline (`openpyxl`), closer in shape to `build_pending.py`'s
   PDF parsing than to the ArcGIS `FeatureServer` JSON queries used for DRC. More upfront
   engineering than a live-query source, for a payoff that's currently capped at FY2022.

## 3. What this means, if built

- Keep only rows with a populated `FEMA Disaster Number`, matched against Region 5
  disasters FY2007+ — same "conserve, don't drop" audit pattern as `ihpAudit`/HMGP
  (bucket the FEMA-number-missing $ into an explicit `administrative`/`unmatched` audit
  total rather than silently discarding it).
- Surface a loud "SBA data current only through FY2022" caveat everywhere it's shown —
  this app already does per-source freshness callouts (`data/manifest.json`), so this
  would need to plug into that same mechanism, probably pinned rather than auto-derived
  since the source itself doesn't update on a knowable cadence.
- Given the freshness gap, an SBA measure would be **silently empty for most of the most
  recent, most-clicked disasters** in the ledger — worth weighing whether a mostly-blank
  new lens is worth shipping vs. waiting for a better/current source.

## 4. Explicitly NOT checked (scope of this pass)

- Only FY2020 was downloaded and parsed. FY2021/FY2022 (or older years) were not spot
  checked — the FEMA-number match rate and schema stability across years are assumed,
  not verified.
- No attempt was made to build an SBA-declaration-number ↔ FEMA-disaster-number
  crosswalk for the administrative/EIDL-only rows.
- The COVID-19 EIDL dataset (also on `data.sba.gov`) was noted but not investigated —
  this app already carves COVID out into its own view (`data/covid.json`), so COVID EIDL
  data would follow that same exclusion, not feed into the regular IA section.
- `disasterloanassistance.sba.gov` (SBA's newer public-facing declaration search portal,
  possibly the successor system post-migration) could not be reached from this
  environment (DNS resolution failed) — unchecked whether it exposes a current API or
  export that supersedes the stale bulk files.
- `recovery.fema.gov`'s "Spending Explorer" (cited in search results as tracking SBA
  Disaster Loan account appropriations alongside the FEMA Disaster Relief Fund since
  2017) could not be reached from this environment either (DNS resolution failed) —
  unchecked whether it has county-level, current, or API-accessible detail.
- `USAspending.gov` / `api.usaspending.gov` were not queried directly — they're a
  plausible **fresher alternative** worth checking next: USAspending tracks federal
  award-level spending (including SBA's Disaster Loan Fund account) and is generally
  updated far more frequently than a hand-published SBA spreadsheet. Whether SBA disaster
  *loans* (as opposed to grants/contracts) show up there at the loan-transaction grain,
  and whether they're taggable by county/disaster, is unknown and should be the first
  thing checked in a follow-up pass.

## 5. Where to look next (not yet done)

In rough order of promise, untested:

1. **`api.usaspending.gov`** — federal award search API, likely fresher than the SBA
   bulk files; unknown whether SBA disaster loans are queryable at county/disaster grain.
2. **`disasterloanassistance.sba.gov`** — SBA's current-generation public portal;
   possibly the live successor to the stale DCMS export, unchecked for an API.
3. **`recovery.fema.gov` Spending Explorer** — tracks SBA Disaster Loan account spending
   alongside FEMA's Disaster Relief Fund since 2017; unchecked for county-level detail
   or an API.
4. A direct ask to SBA's Office of Disaster Assistance data steward (contact listed in
   the dataset's own instructions sheet) about post-FY2022 data availability.

**Bottom line for now:** SBA disaster loan data is real and does carry a clean FEMA join
key for the ~10-12% of rows that have one, but between the FY2022 freshness ceiling and
the mostly-missing FEMA ties, it's not yet a slam dunk the way DRC was. Worth another,
deeper pass (especially on USAspending) before committing to a build.
