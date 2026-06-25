# CLAUDE.md

Guidance for working in this repo. Read this before changing code or data.

## What this is

An independent, **single-file web tool** that helps an executive get a fast,
**traceable** read on FEMA **Public Assistance (PA)** and **Individual
Assistance (IA/IHP)** for upper-Midwest (**FEMA Region 5**: IL, IN, MI, MN, OH,
WI) disasters. Built entirely on public open data. **Not endorsed by FEMA** —
the non-endorsement disclaimer must stay in the UI.

Live site (GitHub Pages): https://calebpaulsmith.github.io/DisasterParameters/

Three views (in priority order — **facts first**):
1. **Disaster Ledger** (default) — every Region 5 disaster, sortable, with
   measured hazards + real PA (obligated) & IHP (approved) dollars. **Tap a row → detail modal** with that
   disaster's full sourced cost breakdown and parameter provenance + verify links.
2. **Disaster Watch** — live NWS alerts + live USGS gages; trips when a river
   approaches a past disaster's peak stage or warnings match an analog's hazards.
3. **Estimate (beta)** — a deliberately-downplayed comparables heuristic that
   scales similar past disasters' obligations by population. It is **not a
   forecast**; keep the prominent caveat.

## Project layout

```
index.html                  # the entire app (HTML+CSS+vanilla JS, no build step)
data/disasters.json         # 80 Region 5 disasters (FY2007–2026) — the source of truth (committed)
data/gages.json             # 19 key USGS river gages: AHPS + crest history + declaration ties (committed)
data/county_declarations.json # committed geo rollup: per-county declaration count + disaster list + PA obligated $ + projects, IHP approved $ with HA/ONA split (ihpApproved/ihpHousing/ihpOna) + iaRegistrations, and per-state totals (states carry the same IHP HA/ONA/registrations set). County IHP $ are registrant-level; state IHP $ are ledger-level (different datasets — see the cd["ihpAudit"] conservation block + scripts/build_county_ihp.py). Powers the Watch "Declaration history" map and the Geography view. Also carries per-county+per-state *ByYear obligation buckets (paByYear/paProjectsByYear/hmgpByYear/mitByYear true obligation year, ihpByYear proxy incident year, empgByYear/afgByYear fiscal year) that drive the Geography per-view timeline + draggable year-range filter — see scripts/build_county_byyear.py. The Geography view is **program-first**: a PROGRAM row (Overview · PA · IA · HMGP · Non-disaster, #geoProgRow `data-prog`) picks the lens, then a program-scoped MEASURE row (#geoToggle `data-geom`) picks the figure — Overview→count; PA→paObligated/paProjects/paApplicants; IA→ihpApproved/ihpHousing(HA)/ihpOna(ONA)/iaRegistrations; HMGP→hmgpObligated/hmgpSubs; Non-disaster→mitObligated/empg/afg. `geoProgram` derives `geoGroup`; `GEO_MEASURE_PROG`/`GEO_PROG_DEFAULT` map the two. The WITH PA/IA/HMGP filter (`#paiaToggle`) shows on **Overview only** and its IA branch uses the **ledger authorization** (`isIHP(d)||iaProgramDeclared`, see `geoProgKeep`); COVID fold-in stays on all disaster-side programs. New count/$-measures plug into the generic metric tables (GEO_META/geoColor/GEO_LEGEND/GEO_KEY/GEO_BAR); applicants/subrecipients get per-state sums in `geoComputeStatewide` (`_paAppl`/`_hmgpSubs`). The Geography timeline is **measure-driven**: ONE series for the active measure — Disasters(count) → # declarations by incident year honoring the WITH switcher + COVID toggle (counted live); dollar/projects → that measure's *ByYear; measures with no year series (HA/ONA/registrations/applicants/subrecipients) fall back to the program's representative $-series via `GEO_YEARFALLBACK` (relabeled "selected measure not year-bucketed"). Mobile mirrors this via its sort-chip paradigm (GM_SORTS + the `.gmpaia` IA-labeled switcher). Same timeline component renders on desktop (#geoTimeline) and mobile (#gmTimeline). The earlier single stacked-dollar chart + the parked mobile/per-program-mit plan are archived in docs/timeline-archive.md
scripts/build_county_map.py # OFFLINE: builds county_declarations.json — designations from _disasters_raw + disasters.json; per-county PA $/projects pulled from OpenFEMA PublicAssistanceFundedProjectsDetails (needs network)
scripts/dedup_applicants.py # OFFLINE, no network: collapses duplicate per-county PA applicant entries in county_declarations.json (case/punctuation/"X Township"↔"X (TOWNSHIP OF)"/abbreviation DEPT↔DEPARTMENT/repeated-segment/trailing "(1)" + exact "(DO NOT USE)" variants). ONLY merges order-preserving normalized-string matches (so "Forest Park"≠"Park Forest"); fuzzy/subset cases are reported for manual review, plus a small curated MANUAL map for confirmed-but-non-deterministic merges (e.g. "(DO NOT USE) DULUTH"→"Duluth, City of"). Dry-run prints the full previous→canonical report; --apply rewrites + sums pa/projects/dns + recomputes nApplicants + sets cd["_applicantsDeduped"]. Every merged applicant carries a `merged` provenance tag listing each source record's name + PA $ (no numeric FEMA applicant IDs in this dataset), surfaced in the UI as a small "merged N" badge (mergedTag() in index.html). Idempotent; re-run after build_county_map.py.
scripts/build_county_ihp.py # OFFLINE: adds per-county IHP approved $ + HA/ONA split + iaRegistrations to county_declarations.json from IndividualsAndHouseholdsProgramValidRegistrations (registrant-level), AND per-state ihpHousing/ihpOna/iaRegistrations rolled up from the disasters.json ledger (no network for the state part). Emits a dollar-conservation audit (cd["ihpAudit"]): county $ (registrant pull) vs state $ (ledger = FemaWebDisasterSummaries) are different datasets, so per state it buckets every registrant dollar into inSet/undeclared/unmatched and reports the cross-dataset residual + flags — money in non-declared counties or unresolvable names (e.g. tribal/reservation areas) is flagged, never dropped. Needs network (county part); resumable cache.
scripts/build_county_hmgp.py # OFFLINE: adds per-county + per-state-statewide HMGP (§404) obligated $ + subrecipient lists to county_declarations.json from HazardMitigationAssistanceProjects v4 (programArea=HMGP; needs network). Dollars conserved: a project lands in its county or the state STATEWIDE bucket.
scripts/build_county_mitigation.py # OFFLINE: adds per-county NON-DISASTER hazard-mitigation grant $ (FMA/PDM/BRIC/LPDM/RFC/SRL — all HMA projects except HMGP) to county_declarations.json as mitObligated/mitByProgram/mitApplicants + per-state mitStatewide (separate non-disaster layer; needs network; dollars conserved).
scripts/build_state_prep.py # OFFLINE: adds per-STATE non-disaster PREPAREDNESS grant $ — EMPG (EmergencyManagementPerformanceGrants) + AFG (NonDisasterAssistanceFirefighterGrants, with top fire-dept recipients) — to county_declarations.json states. Both are state-level (no county); the Geography map fills each state. Needs network.
scripts/build_county_byyear.py # OFFLINE, ADDITIVE: adds per-county + per-state *ByYear obligation buckets to county_declarations.json — powers the Geography "Obligations by year" timeline + its draggable year-range filter. paByYear/hmgpByYear/mitByYear are TRUE obligation year (PublicAssistanceFundedProjectsDetails.lastObligationDate / HazardMitigationAssistanceProjects v4.initialObligationDate); ihpByYear is a PROXY by disaster incident year (IHP carries no obligation date) — state from ledger ihpTotal, county by allocating ihpApproved across its disasters' incident years. EMPG/AFG already carry empgByYear/afgByYear (fiscal year); COVID excluded. Bucketing mirrors build_county_map/hmgp/mitigation (dollars conserved); sum(*ByYear) reconciles with the all-time field minus null-date rows. Needs network.
scripts/build_timeline.py   # OFFLINE: builds data/timeline.json — one regional monthly series (rain/river/tornado[/snow]) + disaster markers for the Ledger "Hazard timeline" chart
data/timeline.json          # committed: monthly regional hazard series + per-month disaster list (powers the Ledger hazard timeline)
scripts/build_covid.py      # OFFLINE: builds data/covid.json — the 6 R5 COVID-19 (Biological) declarations' PA/IHP/projects (needs network)
data/covid.json             # committed: per-state COVID-19 PA obligated/IHP approved/projects (powers the standalone COVID-19 view; kept OUT of ledger/geography/analyses — ~7× weather PA)
scripts/build_newsreel.py   # OFFLINE: builds data/newsreel.json — "latest obligations" reel for the 2 programs with a per-item obligation DATE: PA (PublicAssistanceFundedProjectsDetails.lastObligationDate) + Hazard Mitigation (HazardMitigationAssistanceProjects v4.initialObligationDate). R5 only, COVID excluded. Each program: latest N obligated + biggest N in last 6mo. Needs network. (IHP/AFG/EMPG carry no per-item obligation date, so they can't feed this reel.)
data/newsreel.json          # committed, small: per-program latest+biggest obligations (powers the Newsreel view)
scripts/enrich.py           # OFFLINE: joins NOAA/USGS hazards onto _disasters_raw.json (NO costs)
scripts/add_history.py      # OFFLINE: pulls older R5 disasters (FEMA costs + hazards) and merges them in
scripts/build_gages.py      # OFFLINE: builds gages.json + per-disaster gage lists; ties crests↔declarations
scripts/build_declared.py   # OFFLINE, ADDITIVE: adds `declared` (original declaration date) to each disasters.json record from OpenFEMA DisasterDeclarationsSummaries (earliest declarationDate per disasterNumber). Touches ONLY `declared` — leaves costs/gages/hz alone. Powers the "Disaster Timelines" view (declaration-lag trend + distribution). Needs network.
scripts/build_national.py   # OFFLINE: builds data/disasters_national.json — a LIGHTWEIGHT nationwide companion (all DR declarations FY2007–2026, COVID/Biological excluded; one row per disaster with only the lag fields disasterNumber/state/title/incidentType/begin/end/declared — NO costs/hazards). Powers the Disaster Timelines "National" toggle. Needs network.
data/disasters_national.json # committed: ~1,196 nationwide disasters, lag fields only (NO costs/hazards/gages). Loaded lazily by the browser when the Disaster Timelines view is toggled to "National". Clicking a national disaster opens a minimal modal (dates + lag + links to fema.gov/OpenFEMA); the rich detail card stays Region-5-only. Rebuild with scripts/build_national.py.
# --- state-incident declaration & cost model (see analysis/state-declaration-model.md) ---
scripts/build_panel.py      # OFFLINE: county×episode panel (now also ingests Z-type flood/winter via NWS zone→county xwalk)
scripts/build_precip.py …   # OFFLINE additive enrichers: build_precip, build_snow, augment_ari, augment_stage, augment_exposure
scripts/build_state_panel.py# OFFLINE: aggregates county panel → state_panel.json (the modeling table)
scripts/fit_model.py        # OFFLINE: fits declaration+cost models (scikit-learn optional) → data/model.json
scripts/build_predictor.py  # OFFLINE: distills panel+model → predictor.json + triggers.json
scripts/build_seed_artifacts.py # OFFLINE: SEED predictor/triggers/model from disasters.json + gages.json + PoC findings (no panel needed)
data/predictor.json         # committed, small: per-state base rates, triggers, analogs, cost summaries, county drill-down
data/triggers.json          # committed, small: per-disaster characterizing hazard params + how-often/declared-rate
data/model.json             # committed, small: feature importance, base-rate matrix, literature benchmarks
.github/workflows/pages.yml # deploys to Pages on push to main; stamps the build commit into the footer
data/StormEvents_*.csv.gz   # raw NOAA inputs (2008–2025) — GIT-IGNORED (large, regenerable)
data/_disasters_raw.json    # intermediate from the FEMA pull — GIT-IGNORED
data/county_panel.json · data/state_panel.json # GIT-IGNORED model intermediates (regenerable, large)
FEMA Obligation-... .md      # the original research blueprint (background/context)
```

**Pipeline gotcha (costs landmine):** `enrich.py` writes hazards but **not** `costs`.
The authoritative `costs`/`pa`/`ihp` fields come from the FEMA pull (FemaWebDisasterSummaries),
carried in by `add_history.py`. Re-running **`enrich.py` alone would overwrite
`disasters.json` and drop costs + the `gages` lists** — don't. To rebuild from
scratch you must re-pull FEMA costs too. To just add more disasters, use
`add_history.py START_FY END_FY` (additive; leaves existing rows untouched), then
`build_gages.py`.

`index.html` **fetches `data/*.json` at runtime** (same-origin). It therefore
must be served over http(s) — opening the file directly with `file://` will
fail to load data. Local dev: `python3 -m http.server 8000`.

## Data model (`data/disasters.json`, one object per disaster)

- Identity/meta: `disasterNumber, state, title, incidentType, begin, end, fy,
  paDeclared, iaDeclared, countyCount, tags[]` (Flooding/Tornado/Wind/Hail/
  Snow-Ice/Storms/Dam-Levee), `eventTypes[]`, `reportedDamage`.
- `declared`: original federal declaration date (`YYYY-MM-DD`), from
  `scripts/build_declared.py`. Declaration lag (powering the Disaster Timelines
  view) is computed in-browser as `declared − begin` in days — "how long FEMA
  took to declare after the disaster started." Measuring from the incident
  **start** (not end) keeps the comparison fair across short storms and
  long-running events (wildfire seasons, volcanic eruptions, prolonged
  flooding); from-end produced large misleading negatives for long incidents.
  Begin-based lag is essentially always ≥ 0.
- `hz` (measured hazards): `windMph, hailIn, torEF, peakStageFt, rainIn`
  (total incident rainfall, peak county), `rainMeanIn`, `rainDailyMaxIn`
  (highest single-day rainfall), `rainStations` (ACIS stations used),
  `floodReports, snowReports, hailReports, windReports, tornadoes,
  stormEvents, countyMatched`. Rainfall is refreshed/extended by
  `scripts/augment_rain.py` (RCC-ACIS, additive — does not touch costs).
- `costs` (the authoritative figures): `paTotal, paEmergencyAB, paPermanentCG,
  paProjects, hmgp, ihpTotal, ihpHousing, ihpOna, iaRegistrations`.
- `pa`/`ihp` mirror `costs.paTotal`/`costs.ihpTotal` (used by list views).

## Data sources & how the pipeline works

`scripts/enrich.py` runs **offline** (needs network + the Storm Events CSVs in
`data/`) and writes `data/disasters.json`. The browser does NOT build this — it
only reads the committed JSON and makes a few live calls (NWS, USGS).

| Layer | Source | Where |
|---|---|---|
| Declarations, counties, dates | OpenFEMA `DisasterDeclarationsSummaries v2` | offline → `_disasters_raw.json` |
| **Declaration date** (`declared`) | OpenFEMA `DisasterDeclarationsSummaries v2` (`declarationDate`, earliest per disaster) | offline → `declared` |
| **PA obligated / IHP approved + breakdown** | OpenFEMA `FemaWebDisasterSummaries` (+ `PublicAssistanceFundedProjectsDetails` for project counts) | offline → `costs` |
| Wind / hail / tornado, type tags, reported damage | **NOAA Storm Events** bulk CSV (county FIPS + incident-window join) | offline → `hz` |
| Peak river stage | **USGS Water Services** daily values | offline → `hz.peakStageFt` |
| Storm-total rainfall | **RCC-ACIS** (NOAA) daily precip, summed | offline → `hz.rainIn` |
| AHPS flood categories | **NWPS** `api.water.noaa.gov` (per-gauge by LID) | offline → `data/gages.json` |
| Live alerts | **NWS** `api.weather.gov` | runtime (browser) |
| Live gage heights | **USGS** instantaneous values | runtime (browser) |

To rebuild the dataset: download the `StormEvents_details-*.csv.gz` files (URL in
the script header) into `data/`, then `python3 scripts/enrich.py`. Cross-check a
few PA totals against the granular PA Funded Projects worksheets before shipping.

## Domain facts that MUST stay correct (an expert user checks these)

> **Terminology reference:** `docs/fema-assistance-glossary.md` is the canonical glossary
> (IA vs IHP vs HA/ONA vs PA vs HMGP, accounting stages, declaration flags, field→source map).
> Official OpenFEMA field dictionaries are committed under `docs/openfema-definitions/`
> (regenerate with `scripts/fetch_openfema_dictionaries.py`). Read it before touching $ labels.

- **IA ≠ IHP.** **IA** (Individual Assistance) is the umbrella *authorization*; **IHP**
  (Individuals & Households Program) is the only IA program with public per-disaster dollars
  (`ihpTotal` = HA + ONA). **UI labeling splits along the data's own grain: declarations = IA/PA/HM,
  dollars = IHP, registrations = IA.** So the *authorization* badge (ledger Programs column + detail
  modal) reads **IA** for any IA-authorized disaster; the *dollar* figures/sections are labeled
  **IHP** (the program that actually carries public $); the *registrations* count is labeled **IA**
  (source `totalNumberIaApproved`). Per OpenFEMA, "IA-authorized" =
  `ihProgramDeclared OR iaProgramDeclared`. Each `disasters.json` record stores the **raw flags
  distinctly**: `paDeclared`, `ihpDeclared` (raw IH = modern IHP), `iaProgramDeclared` (raw
  legacy IA), `hmProgramDeclared`, plus `iaDeclared` (= **iaAuthorized** = the OR). The IA
  authorization badge fires on the OR (`isIHP(d) || iaProgramDeclared`); the **IHP money section**
  keys off **`ihpDeclared`/`isIHP()`**, NOT the OR — so a legacy `iaProgramDeclared`-only record
  (pre-IHP, no IHP $ series) shows its IHP dollars as **"Not available"**, never **$0 IHP**.
  Classification lives in one place: `survivorState(d)` in `index.html`, mirrored + fixture-tested
  in `scripts/verify_assistance_model.py`. In the current FY2008+ Region 5 ledger
  `iaDeclared = ihpDeclared = (ihpTotal>0) = 34` and `iaProgramDeclared = 8` — but that
  reconciliation is an **observed property of current data, not a universal rule** (it breaks for
  legacy/pre-IHP records).
- **PA is "obligated"; IHP is "approved."** Different accounting stages — never
  conflate or relabel them.
- **PA breakdown must reconcile:** `paEmergencyAB + paPermanentCG + Category Z
  (management) = paTotal`. Category Z is computed as the remainder
  (`paTotal - AB - CG`); without it the breakdown looks wrong. IHP reconciles as
  `ihpHousing + ihpOna = ihpTotal`.
- **Obligations lag and reconcile over years** — recent disasters under-count;
  `paProjects` can be >0 while `paTotal` is still 0.
- **Hazards are a "peak envelope"**: each `hz` value is the max across all
  reports/gages in the affected counties during the incident window. This loses
  extent; the blueprint notes extent/exposure drive obligations more than peak
  intensity. `countyMatched=false` means hazards were aggregated at state level
  (designated areas didn't map to counties) and may overstate the local peak.
- FY2026 declaration indicators used in the UI: statewide **$1.89**/capita,
  countywide **$4.72**/capita, large-project **$1,062,900**, 75→90% cost-share
  **$189**/capita.

## Gotchas / conventions

- **No framework, no build.** Plain HTML/CSS/JS. Typeface is **Public Sans**
  (US Web Design System look); keep the DHS/FEMA navy+gold palette and the
  `.gov` banner.
- All external APIs used at runtime are **CORS-open** (OpenFEMA, USGS
  waterservices, NWS api.weather.gov). NWPS (`api.water.noaa.gov`) is flaky and
  rate-limits — only used offline; its `?usgsId=` filter is unreliable, so
  resolve gauges by LID or by name match in the full gauge list.
- **Storm Events wind magnitude is in knots** — multiply by 1.151 for mph.
- **USGS gage height** for stage: `parameterCd=00065`, `statCd=00003` (daily
  mean is what USGS stores; `00001` returns nothing for most sites). `countyCd`
  must be the **5-digit** state+county FIPS. Filter out values >75 ft — those are
  reservoir/lake-elevation gauges, not river stage.
- `gages.json` flood stages are **official NWS AHPS** for 10/13 gauges
  (`official:true`, with `cats` = action/minor/moderate/major); the other 3 are
  approximate (`official:false`).
- Tap-through is wired by event delegation on `[data-dn]` → `openDetail(dn)`.
  Any element representing a disaster should carry `data-dn="<disasterNumber>"`.

## Deployment

Push to `main` → `.github/workflows/pages.yml` deploys to Pages automatically
(Pages was enabled once via Settings → Pages → Source: GitHub Actions; the repo
is public, which Pages requires on a free plan). After merging, the new build is
live in ~1 minute; hard-refresh to bypass cache.

## Workflow norms for this repo

- Develop on a topic branch, push, open a **draft PR**; the maintainer reviews
  and merges. Don't push to `main` directly.
- Keep the OpenFEMA/NOAA/NWS/USGS **non-endorsement disclaimers** in the UI and
  README. Don't add eligibility/rights-determination features.
- When changing numbers or labels, preserve traceability: every figure should be
  reconcilable and linkable back to its OpenFEMA/NOAA/USGS source.
