# Building the Denominator: An Empirical-Modeling and Data-Acquisition Plan for DisasterParameters (FEMA Region 5)

## TL;DR

- **Build a committed county-event panel of ALL qualifying severe-weather/flood events in Region 5 (declared AND non-declared), label each by joining to OpenFEMA at the county+date level, and fit two transparent, interpretable models — a regularized/penalized logistic classifier for P(declaration) and a hurdle/Tweedie cost model for E(obligation | declared) — with feature-importance (SHAP + permutation + L1) reporting baked in so the tool reports which parameters actually drive declarations rather than assuming tornado count matters.** This is feasible entirely within the existing offline-Python-writes-committed-JSON / browser-reads-JSON architecture; no live backend is needed.
- **The denominator is the heart of the work.** The NOAA Storm Events Database (episode→event structure, county FIPS, magnitudes in knots) is the spine for assembling candidate events; USGS daily/instantaneous gage data and RCC-ACIS daily precipitation supply hydrology and rainfall; NOAA Atlas 14 converts raw rainfall/stage into recurrence intervals (ARI) so events are comparable across counties. Inclusion thresholds (a Storm Events report of damaging magnitude, OR a gage at/above NWS action/flood stage, OR daily rainfall above a percentile/ARI cut) keep the negative set from being swamped by trivia.
- **Be honest about scope and uncertainty.** Region 5 has only dozens of declared disasters since FY2007 (the current tool covers ~80), so per-state declared counts are small. The closest peer-reviewed precedent — Ghaedi, Best, Reilly & Niemeier (2024), *Natural Hazards* 120:10559–10582 — modeled upper-Midwest flood Public Assistance and found that the four most important variables were “whether the flood occurred in North Dakota, the number of fire departments in the county, average soil moisture in the past 5 days, and the fraction of the county that is developed land,” with flood-intensity metrics failing to crack the top ten for applicants. A tornado-cost benchmark (Diaz & Joseph 2019) explained under half the variance of damage (conditional R² = 0.432). Report wide intervals, calibrated probabilities, and always show the prior analog county-events behind every prediction.

-----

## Key Findings

1. **A denominator can be built purely from measured data.** The NOAA Storm Events Database is published as bulk CSV (“details”, “locations”, “fatalities”) on the NCEI FTP/HTTP server, covering 1950–present,  with an `episode_id` linking many event records to one storm system, county FIPS for county-collected event types (tornado, thunderstorm wind, hail, flash flood), and forecast-zone collection for larger-scale types (flood, winter weather, heat). Wind magnitude is in knots (×1.151 → mph). This is the natural candidate-event generator: every county that recorded a qualifying Storm Events entry becomes a row, declared or not.
1. **Make events comparable with recurrence intervals, not raw magnitudes.** NOAA Atlas 14 (the Precipitation Frequency Data Server, PFDS) gives point precipitation-frequency estimates  / Average Recurrence Intervals; USGS WaterWatch/peak-flow analysis gives flood recurrence intervals and “days above flood stage.” Converting a county’s storm-total or daily-max rainfall and its peak gage stage into an ARI/return period puts an Illinois flood and a Minnesota flood on the same probabilistic footing — far more defensible than comparing raw inches or feet.
1. **The right statistical toolkit is rare-event classification + a hurdle/Tweedie cost model, with explicit feature-importance reporting.** For the declaration yes/no stage, use L1/L2-penalized logistic regression — applying the King & Zeng (2001, *Political Analysis* 9(2):137–163) rare-events correction, which warns that “popular statistical procedures, such as logistic regression, can sharply underestimate the probability of rare events,” or Firth penalization for small per-state samples — as a transparent baseline, and gradient-boosted trees (XGBoost/LightGBM/CatBoost) for nonlinear feature discovery, ranked by permutation importance and TreeSHAP. For cost, use a two-part hurdle (already done) or a single Tweedie-loss GBM.
1. **The closest published precedent validates the approach AND warns about it.** Ghaedi, Best, Reilly & Niemeier (2024, *Natural Hazards* 120:10559–10582, DOI 10.1007/s11069-024-06620-2) modeled county-level PA applicants/projects for upper-Midwest floods — “In total, there are 566 PDD-county observations in our dataset” across “the 270 counties that we consider in our study,” covering North Dakota, South Dakota, Iowa, Wisconsin, and Minnesota over 2003–2018 (note: only Wisconsin and Minnesota overlap FEMA Region 5). They compared eight learners (BART, CART, GLM, GBM, MARS, NN, RF, SVR), selected Random Forest (which beat the null model by 49% on MAE for applicants and 33% for projects), and pruned features with VSURF (retaining 18 variables for applicants, 13 for projects). Their finding: non-hazard features dominated, and “the flood hazard intensity metrics did not rank among the top ten important variables in the model of the number of applicants, and the maximum flood gauge ratio was only the tenth most important variable for the model of the number of projects.” Crucially, that paper did NOT build a non-declared denominator — it modeled *counts given a declaration*. The DisasterParameters owner’s denominator-building goal is therefore a genuine extension, not a replication.
1. **Everything fits the existing architecture and licensing.** OpenFEMA, USGS Water Services, and NWS api.weather.gov are CORS-open and already wired in; Census ACS/Decennial APIs are CORS-open (now require a free key). NOAA Storm Events (bulk CSV), RCC-ACIS, NOAA Atlas 14 grids, PRISM, NLDAS, and SHELDUS are offline/bulk sources — consistent with the repo’s “Python precomputes, browser reads committed JSON” pattern. SHELDUS is the one notable licensed source (free for academic/registered use under an EULA; not redistributable as raw data).

-----

## Details

### 1. Unit of analysis

**Recommendation: the county × storm-episode is the primary modeling unit, with a county × incident-window “event” as the operational definition, and a county-month panel as a secondary aggregation for base-rate frequency tables.**

Three candidate units, with tradeoffs:

- **County × NOAA Storm Events episode.** An episode is “an entire storm system” that can contain many event types across many counties; an event is an individual occurrence (one tornado segment, one hail report, one county’s flood). This is the best primary unit because (a) it is the native grain at which weather is measured and reported, (b) it naturally bounds an “event” in time and space the same way for declared and non-declared cases, and (c) it maps cleanly onto how FEMA declares — a declaration cites an incident period and a set of designated counties, which is essentially a set of county-episodes. The cost: episode boundaries are NWS artifacts, and a multi-day flood may span several episodes; you must merge episodes within a rolling incident window per county.
- **County × time-window (county-month or county-season).** Cleaner panel structure, no episode-merging headaches, and ideal for **base-rate frequency tables** (“in Illinois, how often does a county-month with ≥X tornadoes lead to a declaration?”). But it dilutes hazard signal (a violent 6-hour derecho and a quiet month look like one row) and creates many empty rows. Use it as a *secondary* aggregation layer for frequencies, not as the model’s primary training grain.
- **NOAA Storm Events “episode” × county (the recommended hybrid).** Define an **event** as: all Storm Events records sharing a county FIPS within a rolling incident window (e.g., merge records ≤72 h apart into one event), plus any USGS gage exceedance and any daily-rainfall exceedance in that county within that window. This yields one row per county-event with a “peak envelope” of parameters — exactly the envelope the current tool already computes per disaster, now extended to non-declared events.

**Consistency rule (critical for comparability):** the SAME event-construction algorithm must run over the entire Storm Events + gage + rainfall record, *before* any declaration label is attached. The declaration label is then joined on. This guarantees declared and non-declared events are defined identically and avoids the selection bias the README and CLAUDE.md flag (“only declared events are modeled; declaration is partly bureaucratic”).

### 2. Building the denominator (negative cases) — the core of the plan

**Goal: a committed `data/county_events.json` panel of every qualifying county-event in IL/IN/MI/MN/OH/WI from FY2007 (matching the current dataset floor) — declared and not — with measured parameters and a declaration label.**

**Step A — Candidate-event generation from NOAA Storm Events.** Download the `StormEvents_details-*.csv.gz`, `*_locations-*`, and `*_fatalities-*` files for 2007–present from the NCEI bulk server. Filter to the six Region 5 state FIPS (17 IL, 18 IN, 26 MI, 27 MN, 39 OH, 55 WI). Key handling rules from NCEI documentation and the repo’s own CLAUDE.md:

- **Wind is in knots** — multiply by 1.151 for mph (the tool already does this).
- **`cz_type`**: `C` = county-collected (tornado, hail, thunderstorm wind, flash flood — has a real county FIPS); `Z` = zone-collected (flood, winter storm, heat — must be cross-walked from forecast zone to county FIPS, e.g., via the IEM or NWS zone-county correlation file). Keep a `countyMatched` flag exactly as the current schema does.
- **`episode_id`** groups events into storm systems; carry it so multi-type episodes (the realistic declaration trigger) can be reconstructed.
- **Tornado segments**: a tornado crossing a county/state line is a separate segment; for “tornado count per event” document the logic and note that NCEI advises using SPC monthly counts for official state tornado totals.

**Step B — Attach hydrology and rainfall.** For each candidate county-event window:

- **USGS daily/instantaneous gage stage** (`parameterCd=00065`, `statCd=00003` daily mean; filter values >75 ft as reservoir/lake gauges) for gages in/near the county; compute peak stage, stage relative to AHPS action/minor/moderate/major categories, and **duration above each threshold**. The current `build_gages.py` already does this per declared disaster — generalize it to all events.
- **RCC-ACIS daily precipitation** (open JSON web service at data.rcc-acis.org; supports station `StnData`/`MultiStnData` and gridded county-average “area” queries) summed over the window for storm-total and daily-max rainfall, as `augment_rain.py` already does.

**Step C — Set inclusion thresholds so negatives aren’t trivial.** A county logs many minor Storm Events records; without a floor the negative class is all noise. Recommended multi-criteria inclusion (a county-event enters the panel if it meets ANY):

- a Storm Events report with damaging magnitude: wind ≥ 50 kt (~58 mph severe criterion), hail ≥ 1.0 in, any tornado, or any flash-flood/flood event with property damage > 0; OR
- a USGS gage in the county reached **NWS action stage or higher**; OR
- county storm-total or daily-max rainfall exceeded a **recurrence threshold** (e.g., ≥ 2-year ARI from NOAA Atlas 14, or ≥ 95th-percentile daily precip).

This mirrors the logic of the Ghaedi flood study (which restricted to flood PDDs to keep hazard intensity measurable) and the Diaz–Joseph tornado paper (which kept all tornado events and let a zero/occurrence stage absorb the no-damage cases). Document the thresholds as tunable constants; report panel size and the declared:non-declared ratio.

**Step D — Label declared vs. not.** Join to OpenFEMA `DisasterDeclarationsSummaries v2` at **county FIPS + incident-window overlap**. A county-event is `declared=1` if its county is a designated area of a DR/EM declaration whose incident period overlaps the event window; else `declared=0`. Attach `disasterNumber`, `paDeclared`, `iaDeclared`, and (from `FemaWebDisasterSummaries` + `PublicAssistanceFundedProjectsDetails`) the obligated dollars for declared rows. This is exactly the join the tool already performs for declared events; the new work is running it across the full candidate set and recording the 0s. (OpenFEMA returns 1,000 records per page by default, max 10,000 per call; page with `$skip`/`$top`; no API key required.)

**Expected class imbalance:** declarations are rare relative to qualifying weather, so expect a low positive rate (single-digit to low-tens percent depending on thresholds). This is a feature, not a bug — it is precisely the base rate the owner wants to surface — but it dictates the rare-event modeling choices in §5.

### 3. Candidate predictor parameters

Enumerate at county-event grain. “Wired” = derivable from sources already in the pipeline; “New” = needs a new source (all offline-friendly).

**Hazard intensity (mostly wired):**

- Peak wind (mph, from knots) — *wired (Storm Events)*
- Max hail size (in) and hail-report count — *wired*
- Tornado count per event and max EF — *wired*
- Storm-total rainfall and daily-max rainfall (in) — *wired (RCC-ACIS)*
- **Rainfall ARI / recurrence interval** (e.g., is the daily-max a 10-yr/25-yr/100-yr event?) — *New: NOAA Atlas 14 PFDS point/grid*
- Peak river stage (ft) and **feet above flood stage**; exceedance flags for action/minor/moderate/major AHPS categories; **duration (hours/days) above each category** — *wired (USGS + gages.json AHPS cats)*
- **Flood/stage recurrence interval** (peak-flow return period) — *New: USGS peak-streamflow / WaterWatch-successor flood-frequency*
- Count of NWS storm-event reports by type (flood, wind, hail, tornado, snow) — *wired (already in `hz`)*

**Spatial extent / footprint (partly new):**

- Number of counties in the episode (contiguous footprint), max single-county intensity vs. episode-wide — *wired (derivable by grouping on `episode_id`)*
- Spatial extent of gage exceedance / rainfall footprint — *New (grid overlay)*

**Antecedent conditions (new):**

- Antecedent precipitation (prior 5–30 day cumulative) — *wired-ish (RCC-ACIS multi-day sums) or New (PRISM/NLDAS grids)*
- Soil moisture (top and root-zone) — *New: NLDAS-2 (0.125°, hourly, 1979–present, ~4-day latency) or NASA Giovanni (the source Ghaedi used; “average soil moisture in the past 5 days” was a top-four predictor there)*

**Exposure / scaling covariates (new but CORS-friendly):**

- County population and housing units — *New: Census ACS 5-yr / Decennial API (CORS-open, free key)*
- Developed-land fraction, structure counts — *New: NLCD land cover (offline) or USA Structures/NSI (offline)* — note Ghaedi found “the fraction of the county that is developed land” and “the number of fire departments in the county” among the top four predictors
- Social vulnerability (optional secondary layer, not backbone) — *New: CDC/ATSDR SVI*

**Per-capita indicators (secondary layer only, per owner’s instruction):** statewide/countywide per-capita impact can be surfaced as a derived display value against the FY2026 indicators ($1.89 statewide, $4.72 countywide, $1,062,900 large-project), but must NOT be the modeling backbone.

**On feature discovery:** the explicit requirement is that the model DISCOVER which parameters matter. Do not hard-code tornado count as the driver. Feed the full set above and let permutation importance + SHAP rank them. The Ghaedi precedent strongly suggests exposure and “experience/bureaucratic” covariates will rival or beat peak intensity — surface that finding honestly rather than suppressing it.

### 4. Additional data sources to consider

|Source                               |What it adds                                                                                                                                |Granularity                      |Access                                                                                                             |CORS-open for live browser?                                                            |
|-------------------------------------|--------------------------------------------------------------------------------------------------------------------------------------------|---------------------------------|-------------------------------------------------------------------------------------------------------------------|---------------------------------------------------------------------------------------|
|**NOAA Atlas 14 PFDS**               |Precipitation frequency / ARI to normalize rainfall                                                                                         |Point + gridded (ascii/GIS)      |Web/PFDS + grid download; a point CSV endpoint exists (used by USGS `pfdf` library)                                |No — offline; bake ARI lookups into JSON                                               |
|**USGS peak-streamflow / WaterWatch**|Flood recurrence interval, days above flood stage                                                                                           |Per gage                         |WaterWatch was scheduled for decommission end-2025; migrate to USGS Water Data APIs / `hyswap` for exceedance stats|Water Services daily/IV are CORS-open; peak-flow analysis offline                      |
|**NWS AHPS / NWPS**                  |Official flood categories (action/minor/moderate/major)                                                                                     |Per gauge (LID)                  |`api.water.noaa.gov`                                                                                               |Flaky/rate-limited — offline only (as repo already notes); resolve by LID, not `usgsId`|
|**PRISM**                            |Gridded daily precip (4 km, free) for gap-filling/antecedent                                                                                |4 km daily, 1981–present         |Web service (COG/BIL); free with attribution; 800 m is paid                                                        |No — offline                                                                           |
|**NLDAS-2**                          |Soil moisture, antecedent precip                                                                                                            |0.125°, hourly, 1979–present     |NASA GES DISC (may need Earthdata login)                                                                           |No — offline                                                                           |
|**Iowa Environmental Mesonet (IEM)** |Archived NWS Local Storm Reports (LSRs) back to 2003, zone→county crosswalks, MRMS precip                                                   |Point LSRs; shapefile/CSV/GeoJSON|Open HTTP/JSON APIs (`mesonet.agron.iastate.edu`)                                                                  |Largely open — but use offline for bulk archive pulls                                  |
|**SPC storm reports**                |Tornado/wind/hail reports, official tornado counts                                                                                          |Point/day                        |Bulk CSV                                                                                                           |Offline                                                                                |
|**Census ACS / Decennial**           |Population, housing, exposure scaling                                                                                                       |County                           |api.census.gov (free key required)                                                                                 |Yes — CORS-open                                                                        |
|**NRI (National Risk Index)**        |Expected annual loss, SVI, resilience — secondary context                                                                                   |County/tract                     |OpenFEMA (CSV/GDB; v1.20 Dec 2025)                                                                                 |OpenFEMA is CORS-open; NRI is bulk                                                     |
|**SHELDUS**                          |County-level historical property/crop loss, casualties (1960–present)                                                                       |County × event                   |Registered/licensed (EULA; free for academic/registered use; v24.0 released Feb 16, 2026)                          |No — offline, not redistributable raw                                                  |
|**OpenFEMA additional endpoints**    |`PublicAssistanceFundedProjectsDetails` (project-level obligations), `IndividualsAndHouseholdsProgramValidRegistrations`, PA Applicants, HMA|County/applicant/project         |OpenFEMA API                                                                                                       |Yes — CORS-open                                                                        |

Note the data-quality caveat carried from the blueprint: `PublicAssistanceFundedProjectsDetails` is raw FAC-Trax/Grants Manager data subject to human error, excludes open/pre-obligation projects, and reconciles over years — recent disasters under-count. v1 was retired October 6, 2025; build against v2.

### 5. Statistical / modeling approach

**Two linked models, both interpretable, both traceable to analogs.**

**Stage 1 — P(declaration | parameters), a rare-event classifier.**

- **Transparent baseline:** L1- (lasso) and L2-penalized logistic regression. With small per-state positive counts, apply the **King & Zeng (2001) rare-events correction**  (which warns that logistic regression “can sharply underestimate the probability of rare events”) or **Firth penalized likelihood** to reduce small-sample bias and handle quasi-separation. Firth gives finite estimates even under perfect separation, but biases predicted probabilities toward 0.5 — correct the intercept post-hoc when reporting probabilities. L1 doubles as variable selection.
- **Nonlinear discovery model:** gradient-boosted trees (XGBoost / LightGBM / CatBoost) with class weighting (`scale_pos_weight [![](claude-citation:/icon.png?validation=57FD6C67-12B1-413F-81D3-0856B044C99B&citation=eyJlbmRJbmRleCI6MTkzNTUsIm1ldGFkYXRhIjp7Imljb25VcmwiOiJodHRwczpcL1wvd3d3Lmdvb2dsZS5jb21cL3MyXC9mYXZpY29ucz9zej02NCZkb21haW49cmVzZWFyY2hnYXRlLm5ldCIsInByZXZpZXdUaXRsZSI6IkxvZ2lzdGljIFJlZ3Jlc3Npb24gaW4gUmFyZSBFdmVudHMgRGF0YSB8IFJlcXVlc3QgUERGIiwic291cmNlIjoiUmVzZWFyY2hHYXRlIiwidHlwZSI6ImdlbmVyaWNfbWV0YWRhdGEifSwic291cmNlcyI6W3siaWNvblVybCI6Imh0dHBzOlwvXC93d3cuZ29vZ2xlLmNvbVwvczJcL2Zhdmljb25zP3N6PTY0JmRvbWFpbj1yZXNlYXJjaGdhdGUubmV0Iiwic291cmNlIjoiUmVzZWFyY2hHYXRlIiwidGl0bGUiOiJMb2dpc3RpYyBSZWdyZXNzaW9uIGluIFJhcmUgRXZlbnRzIERhdGEgfCBSZXF1ZXN0IFBERiIsInVybCI6Imh0dHBzOlwvXC93d3cucmVzZWFyY2hnYXRlLm5ldFwvcHVibGljYXRpb25cLzI4NTIwMjZfTG9naXN0aWNfUmVncmVzc2lvbl9pbl9SYXJlX0V2ZW50c19EYXRhIn1dLCJzdGFydEluZGV4IjoxOTMzOSwidGl0bGUiOiJSZXNlYXJjaEdhdGUiLCJ1cmwiOiJodHRwczpcL1wvd3d3LnJlc2VhcmNoZ2F0ZS5uZXRcL3B1YmxpY2F0aW9uXC8yODUyMDI2X0xvZ2lzdGljX1JlZ3Jlc3Npb25faW5fUmFyZV9FdmVudHNfRGF0YSIsInV1aWQiOiJlNGEyOWRiZC04NzI0LTQ5NzQtOGM0ZS03M2NhMWZkZjc4YzIifQ%3D%3D "ResearchGate")](https://www.researchgate.net/publication/2852026_Logistic_Regression_in_Rare_Events_Data)`) for imbalance. This is where feature *discovery* happens.
- **Feature importance / variable selection (the explicit requirement):** report (a) **permutation importance** (model-agnostic, global, computed on held-out data to detect overfitting),  (b) **TreeSHAP** (fast exact Shapley values for tree ensembles — reduces complexity from exponential KernelSHAP to polynomial — giving both global ranking and per-prediction attributions), and (c) **L1 coefficients** for the linear view. Optionally use **VSURF** as Ghaedi did. Present a single honest ranking with the caveat (from the SHAP literature) that importance ≠ causation — correlated covariates can rank highly without causal effect.
- **Base-rate frequency tables (the most transparent, most trusted output):** independent of any model, compute empirical frequencies: for each state (and county where N permits), bin each parameter (e.g., tornado count 0, 1–4, 5–9, 10–19, 20+; peak wind bands; stage-above-flood bands; rainfall ARI bands) and report how often events in that bin were declared. This directly answers “how often did that level occur historically and how often did a declaration follow,” and it degrades gracefully when samples are tiny (just show the counts).

**Stage 2 — E(obligation | declared), a cost model (see §6).**

**Confidence / uncertainty (be honest given small N):**

- **Calibration:** reliability/calibration plots for the probability stage; isotonic or Platt scaling if needed; recall Firth biases probabilities and must be intercept-corrected.
- **Cross-validation:** do NOT use random row splits (they leak within-episode correlation). Use **leave-one-disaster-out** and **temporal hold-out** (train on older events, test on recent).
- **Intervals:** wide by design. For probabilities, report confidence bands; for cost, report low–high spanning the analog spread. State explicitly that for rare severe events the model extrapolates.
- **Interpretability/traceability:** every prediction must render the **k nearest analog county-events** (k-NN on standardized parameters) with their actual parameters, declaration outcome, and (if declared) obligations — preserving the tool’s existing “facts-first, traceable” design and giving users a sanity anchor independent of the model.

**Sparse-data mitigations:** pool across all six states and hazard types; consider **hierarchical/partial-pooling** (a data-poor county borrows strength from the regional distribution); and label the model with the policy regime it was trained on (pre-reform).

### 6. Cost model

Predict obligated dollars (PA obligated; IHP approved) **conditional on declaration**, addressing the long-tailed, zero-inflated distribution and the multi-year obligation lag.

- **Distribution/transform:** disaster cost is right-skewed and zero-inflated. Two equivalent routes: (a) a **two-part hurdle** — the Stage-1 classifier supplies P(any obligation), then a **log-link gamma GLM** or **log-dollar regression** for magnitude conditional on >0; or (b) a single **Tweedie-loss GBM** (compound Poisson-gamma, power p∈(1,2)), which natively handles the zero mass plus right skew in one interpretable model and is standard in actuarial loss modeling (XGBoost, LightGBM, CatBoost, and scikit-learn all expose a Tweedie objective). Recommend offering both; the Tweedie GBM is more parsimonious, the hurdle is more transparent and avoids the “low frequency → zero predicted loss” pitfall of pure-frequency models.
- **Honest accuracy expectation:** the Diaz & Joseph (2019, *Weather and Climate Extremes*) tornado benchmark reports — verbatim — “a neural network that predicts whether a tornado will cause property damage (out-of-sample accuracy = 0.821 and area under the receiver operating characteristic curve, AUROC, = 0.872). Conditional on a tornado causing damage, another neural network predicts the amount of damage (out-of-sample mean squared error = 0.0918 and R² = 0.432).” That is, even a good model explains under half the variance, and log-scale fitting produces large natural-scale residuals. Set expectations and intervals accordingly.
- **Obligation lag (under-counting recent events):** PA obligations reconcile over years; `paProjects` can be >0 while `paTotal` is still 0. Mitigations: (a) add **disaster age** (years since declaration) as a covariate and/or model a maturation curve; (b) down-weight or flag immature disasters in training; (c) for display, show a “still maturing — figures will rise” badge for recent DRs, consistent with the current README/CLAUDE caveats.
- **Per-capita normalization (optional, not mandatory):** offer obligations per impacted-county capita as a secondary normalization for cross-event comparability, but keep raw dollars as the primary figure and do NOT make per-capita indicators the modeling backbone (owner’s instruction).
- **Uncertainty:** report low–high intervals spanning analog spread; aggregate-sanity-check county predictions against known totals.

### 7. Data model / schema

Propose a new committed file `data/county_events.json` (one object per county-event), plus a committed `data/model.json` holding fitted outputs so the static front-end renders predictions with no backend.

```jsonc
// data/county_events.json — one object per county-event (declared OR not)
{
  "eventId": "17031-2023-0710",      // FIPS-date key
  "state": "IL",
  "countyFips": "17031",
  "countyName": "Cook",
  "episodeId": 184562,                // NOAA Storm Events episode link
  "begin": "2023-07-10",
  "end": "2023-07-12",
  "fy": 2023,
  "hz": {                             // measured parameters (peak envelope)
    "windMph": 71, "hailIn": 1.75, "torEF": 2, "tornadoes": 3,
    "rainTotalIn": 6.2, "rainDailyMaxIn": 4.1, "rainARIyears": 25,
    "peakStageFt": 18.4, "ftAboveFlood": 4.4,
    "stageCat": "moderate", "hoursAboveAction": 36, "hoursAboveFlood": 18,
    "stageARIyears": 15,
    "windReports": 4, "hailReports": 2, "floodReports": 6,
    "stormEvents": 14, "countyMatched": true
  },
  "footprint": { "episodeCountyCount": 9, "contiguous": true },
  "antecedent": { "precip30dIn": 7.1, "soilMoisturePct": 88 },
  "exposure": { "population": 5109000, "housingUnits": 2095000, "developedFrac": 0.61 },
  "declared": 1,                      // the LABEL
  "disasterNumber": 4728,
  "paDeclared": true, "iaDeclared": true,
  "costs": { "paTotal": 67000000, "ihpTotal": 12000000, "disasterAgeYears": 2.9, "mature": false },
  "sources": { "stormEvents": "...", "usgs": [], "acis": [], "openFema": "..." }
}
```

```jsonc
// data/model.json — fitted outputs the browser uses to predict
{
  "trainedThrough": "2026-02",
  "policyRegime": "pre-reform",
  "logistic": { "coef": { "windMph": 0.41, "rainARIyears": 0.77 }, "intercept": -3.2,
                "rareEventCorrection": "king-zeng", "scaleNote": "standardized" },
  "gbm": { "featureImportance": { "rainARIyears": 0.22, "ftAboveFlood": 0.18,
            "population": 0.15, "windMph": 0.11, "tornadoes": 0.07 },
           "shapTop": [] },
  "baseRates": { "IL": { "tornadoes": { "0":{"n":420,"declared":3},
            "5-9":{"n":18,"declared":7}, "20+":{"n":4,"declared":4} },
            "ftAboveFlood": {} } },
  "cost": { "type": "tweedie", "power": 1.6, "coef": {},
            "logResidualSd": 1.1, "condR2": 0.43 },
  "calibration": [ {"binP":0.1,"obs":0.08} ],
  "cv": { "scheme": "leave-one-disaster-out", "auroc": 0.0, "brier": 0.0 }
}
```

**Offline pipeline scripts (new/modified):**

- `scripts/build_events.py` (NEW) — generates candidate county-events from Storm Events + USGS + ACIS, applies inclusion thresholds, writes `county_events.json` (the denominator). Reuses the knots→mph, `00065`/`00003`, >75 ft filters and zone→county logic.
- `scripts/augment_ari.py` (NEW) — attaches NOAA Atlas 14 rainfall ARI and USGS peak-flow recurrence to each event (offline lookups baked in).
- `scripts/label_declarations.py` (NEW) — joins OpenFEMA declarations + costs onto events at county+window.
- `scripts/fit_model.py` (NEW) — fits logistic + GBM + Tweedie/hurdle, computes SHAP/permutation importance, base-rate tables, calibration, CV; writes `model.json`. (Python/scikit-learn/xgboost/shap, offline.)
- Existing `enrich.py`, `add_history.py`, `build_gages.py`, `augment_rain.py` remain for the declared-disaster ledger; the new panel is additive and must NOT overwrite `disasters.json` (respect the “costs landmine” gotcha in CLAUDE.md — `enrich.py` alone would drop `costs` and the `gages` lists).

### 8. Front-end integration

Add a **Parameter Predictor** view to the existing single-file `index.html` (vanilla JS, Public Sans, DHS navy+gold, `.gov` banner, non-endorsement disclaimer preserved). It reads `county_events.json` + `model.json` at runtime (same-origin fetch — must be served over http(s), not `file://`) and, given **state + parameter sliders** (the existing wind/hail/stage/rainfall controls, plus tornado count and rainfall-ARI/stage-ARI), returns:

- **Declaration likelihood** (calibrated probability with a confidence band), computed in-browser from `model.json` coefficients/importance.
- **Predicted cost** (PA obligated, IHP approved) with low–high interval, from the Tweedie/hurdle outputs.
- **Most-predictive parameters** for that state/event — a small SHAP/importance bar showing which parameters drove this prediction (so the user sees, e.g., that river-stage exceedance mattered more than tornado count).
- **Historical frequency of that parameter level** — pulled from the `baseRates` table: “events at this tornado-count level occurred N times in IL; M were declared.”
- **Prior analog county-events** — the k nearest events from `county_events.json` listed with their parameters, declared/not badge, and (if declared) real obligations and a tap-through to the existing disaster detail modal via `data-dn`.

Keep the prominent “rough projection, not a forecast” caveat, the facts-first ordering (ledger remains default), and full traceability/verify links. Reuse event delegation on `[data-dn]`.

The target user statement — “For a severe storm event in Illinois, when there are ~17 tornadoes in the event, a wind/storm declaration is likely, with obligations totaling roughly $X, at confidence XX% — here are the prior analog events and their parameters” — is produced directly from these four outputs, with the SHAP panel correcting the user if tornado count is *not* in fact the dominant driver.

### 9. Step-by-step build roadmap

1. **Freeze the event definition.** Implement and document the rolling-window county-event merge over Storm Events (≤72 h), the inclusion thresholds (§2C), and the zone→county crosswalk. Validate that re-running it reproduces the existing ~80 declared disasters’ counties when intersected with OpenFEMA.
1. **Build the candidate panel** (`build_events.py`) for FY2007–present across the six states. Sanity-check counts; inspect the declared:non-declared ratio.
1. **Attach hydrology + rainfall + ARI** (`augment_ari.py`): USGS stage and duration-above-category, RCC-ACIS rainfall, NOAA Atlas 14 ARI, USGS peak-flow recurrence. Handle the **daily-mean-understates-instantaneous-crest** caveat: where instantaneous IV exists, prefer it for peak stage; flag daily-mean rows.
1. **Attach exposure** (Census ACS county population/housing; NLCD developed fraction) and **antecedent** (NLDAS/PRISM soil moisture and prior-precip). Optional: SHELDUS loss history (offline, licensed).
1. **Label declarations + costs** (`label_declarations.py`) from OpenFEMA at county+window; carry `disasterAgeYears`/`mature` flag for the obligation-lag problem.
1. **Reconciliation checks:** confirm every known declared county-event is labeled `declared=1`; confirm PA breakdown reconciles (`paEmergencyAB + paPermanentCG + Cat Z = paTotal`; `ihpHousing + ihpOna = ihpTotal`); spot-check a few PA totals against PA Funded Projects worksheets (per CLAUDE.md). Verify knots→mph and the >75 ft reservoir filter didn’t drop real river gages.
1. **Fit models** (`fit_model.py`): penalized/rare-event logistic + GBM for P(declaration); Tweedie/hurdle for cost. Run leave-one-disaster-out and temporal CV. Compute permutation + SHAP importance, base-rate tables, calibration. Write `model.json`.
1. **Validate honestly:** report AUROC/Brier/calibration for the probability stage and log- and natural-scale error for cost; benchmark against the published anchors (occurrence AUROC ~0.87, conditional cost R² ~0.43) so reviewers can judge. Flag that Storm Events damage/hazard are NWS “best estimates,” that some events join at state level (`countyMatched=false`), and that recent disasters under-count.
1. **Wire the front-end** Parameter Predictor view; keep ledger default and all disclaimers.
1. **Document + re-train cadence:** version the model, label the policy regime, and re-train as obligations mature and (if it advances) as FEMA reform changes the regime.

-----

## Recommendations

**Stage 1 — Prove the denominator (1–2 weeks).** Build `build_events.py` and the labeling join first; produce `county_events.json` and inspect the declared:non-declared ratio and per-state positive counts. **Threshold that changes the plan:** if a state has fewer than ~10 declared county-events, do NOT fit a per-state model there — fall back to pooled regional models + base-rate tables for that state, and say so in the UI. (For perspective on how thin per-state data can be: the Ghaedi study had 566 PDD-county observations across 270 counties and five states over 15 years, and still found hazard intensity hard to separate from confounders.)

**Stage 2 — Frequencies before fancy models.** Ship the **base-rate frequency tables** first; they are the most transparent, most defensible output and require no model. They alone satisfy “how often did that level occur and how often did a declaration follow.”

**Stage 3 — Add the two models with importance reporting.** Fit penalized/rare-event logistic + GBM (P declaration) and Tweedie/hurdle (cost). Lead with SHAP/permutation importance so the tool reports *discovered* drivers. **Benchmark to beat:** occurrence AUROC in the mid-0.8s and conditional cost R² ~0.4–0.5 would match published precedent and is a credible “ship it” bar.

**Stage 4 — Integrate + caveat.** Add the Parameter Predictor view; preserve facts-first ordering, analog traceability, and the non-endorsement disclaimer. **Threshold that escalates scope:** if FEMA’s RAPID parametric-PA reform advances, the discovered parameter→declaration→dollar mapping becomes a trigger-calibration asset — version and document accordingly.

**Guardrails throughout:** never overwrite `disasters.json` (costs landmine); keep all heavy computation offline in Python; commit only JSON; keep all runtime calls to the CORS-open set (OpenFEMA, USGS Water Services, NWS, Census).

## Caveats

- **Selection-bias is reduced, not eliminated.** Building a denominator from measured weather fixes the “only declared events” problem, but the declaration label still encodes bureaucratic/political choices — the Ghaedi precedent found “whether the flood occurred in North Dakota” and “the length of time between the end of the disaster and the date when a disaster is declared” out-ranked hazard intensity. Frame predictions as “how often a declaration *historically followed* these conditions,” not “whether one *should* occur.” Note also that the Ghaedi states only partially overlap Region 5 (only Wisconsin and Minnesota), so its specific coefficients are indicative, not transferable.
- **Storm Events is noisy.** NCEI/NWS damage and magnitude figures are “best estimates” with documented inconsistency across offices and missingness; use them as features, not ground truth.
- **Hydrology pitfalls:** USGS daily-mean understates instantaneous crest; prefer IV where available; the >75 ft filter and zone→county crosswalk can drop or misassign records — validate. NWPS/AHPS is rate-limited and offline-only.
- **Small samples + long tails mean wide intervals.** Per-state declared events number in the low tens at most; cost variance is large (precedent conditional R²≈0.43). Report uncertainty prominently.
- **SHELDUS licensing:** free for registered/academic use under an EULA  but not redistributable as raw data — use it offline to derive features, don’t commit raw SHELDUS to the public repo.
- **Obligation lag** means recent-disaster cost labels are incomplete; the model will under-predict immature disasters unless age is modeled and flagged.
- **FEMA reform risk:** if PA becomes a parametric block grant (RAPID) and IA a single payment (FAIR), the historical relationship the model learns may partly break — label the trained policy regime and re-train.