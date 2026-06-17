# State-incident declaration & cost model — design + pipeline

**The one question:** *given a weather event (forecast, current, or historical), should we
expect a FEMA disaster declaration in this state, and what would PA and IA cost?*

## Unit of analysis (the core design decision)

**Predict at the STATE-INCIDENT level; build the prediction from COUNTY features
aggregated up.**

- The **outcome is a state-incident**: a governor requests for the *state*; the President
  designates a *set of counties*; OpenFEMA reports PA obligated / IHP approved **per
  disaster number**. The **statewide** per-capita indicator ($1.89/capita FY26) is assessed
  on the **state aggregate**; a county rides into a declaration on the statewide total
  clearing the bar. So the prediction target (declared y/n) and the cost targets
  (`paTotal`, `ihpTotal`) are **state × storm-system**.
- The **drivers are county-level and additive**: group county-episodes by
  `(state, episode_id)` → a **state-episode**; features are aggregations over member
  counties (`nCountiesOverFlood`, `sumPopExposed`, `sumDamageProxy`, `maxSnowMeltIn`,
  `maxFtAboveFlood`, `totTornadoes`, …). This is the catastrophe-model chain
  Hazard → Exposure → Vulnerability → Loss, with a declaration/threshold layer on top.
- **Counties stay as the evidence + the drill-down**, never the prediction unit — a
  county-only model misclassifies every county whose state never cleared the statewide bar.

## Findings encoded (don't relearn them)

From `analysis/county-driver-findings.md` (47,057 county-episodes, 2,890 declared, 6.1%):
declarations are **damage/exposure-mediated, not intensity-triggered** (IL tornado count
p50/p90 is identical declared vs not; declared rate climbs with *damage*). Drivers vary by
state × hazard (**MN flood 38%** dominates). **Rain splits floods in WI/IL but not MN** —
**MN floods are snowmelt** (Red/Minnesota River), so `snowMeltIn`/`snowDepthPreIn` is the
driver there, not rainfall.

## Pipeline (offline Python — browser only reads committed JSON)

```
StormEvents CSVs ─┐
  build_panel.py  │  county × episode panel (+ Z-type flood/winter via NWS zone→county xwalk)
        │         │      → data/county_panel.json   (git-ignored, ~10 MB)
        ▼         │
  build_precip.py · build_snow.py · augment_ari.py · augment_stage.py · augment_exposure.py
        │            (all ADDITIVE — rainfall, snowmelt/depth, Atlas-14 ARI, gage crest, ACS exposure)
        ▼
  build_state_panel.py   → data/state_panel.json    (git-ignored — the modeling table)
        ▼
  fit_model.py           → data/model.json          (committed, small — coefs/importance/CV/benchmarks)
        ▼
  build_predictor.py     → data/predictor.json + data/triggers.json  (committed, small)
```

`enrich.py`/`disasters.json` are **never** touched (the costs landmine). The browser fetches
only the small committed `predictor.json` / `triggers.json` / `model.json` (+ the existing
`disasters.json` / `gages.json` / `r5_counties.json`) — never the multi-MB panels.

## Seed vs fitted artifacts

The committed `predictor.json` / `triggers.json` / `model.json` currently ship as a **seed**
build from `scripts/build_seed_artifacts.py`, derived **entirely from data already in the
repo + the published PoC findings** so the tool ships real, traceable numbers without the
~10 MB git-ignored panel:

- declared base rates by state × hazard, rain-band declared rates, panel size → PoC findings;
- analog state-incidents, cost medians/P90, characterizing hazard values → `disasters.json`
  (real OpenFEMA PA/IA + NOAA/USGS `hz`);
- county flood thresholds → `gages.json` (official NWS AHPS categories);
- occurrence/cost benchmarks → Diaz & Joseph (2019), Ghaedi (2024).

`fit_model.py` + `build_predictor.py` **overwrite** these same files with the fitted GBM /
Firth-corrected logistic + leave-one-disaster-out & temporal CV once the county panel is
regenerated. Both builds emit the **identical schema**, so the front end is unchanged. The
seed `model.json` is flagged `"build":"seed"`; the displayed likelihoods are honest empirical
frequencies either way (the most transparent output, per the spec).

## Regenerate the fitted model

```bash
# 1. download StormEvents_details-*.csv.gz into data/ (URL in scripts/enrich.py header)
python3 scripts/build_panel.py          # + NWS zone→county crosswalk (auto-cached)
python3 scripts/build_precip.py
python3 scripts/build_snow.py
python3 scripts/augment_ari.py
python3 scripts/augment_stage.py
CENSUS_API_KEY=… python3 scripts/augment_exposure.py
python3 scripts/build_state_panel.py    # → data/state_panel.json
python3 scripts/fit_model.py            # → data/model.json  (needs scikit-learn; shap optional)
python3 scripts/build_predictor.py      # → data/predictor.json + data/triggers.json
```

## Front end

One new view — **"Will it be declared?"** — state-first, three modes (Predicted sliders /
Current live / Past analog) with a county drill-down choropleth showing which counties drive
the state number. Plus the **ledger detail modal** gains a **"Triggers & how often"** section
(per-disaster characterizing params → how-often-before + declared-rate + related drivers,
clickable to a distribution). Honest uncertainty throughout: calibrated/empirical
probabilities, wide cost intervals, obligation-lag caveat, deferred-work notes.

**Deferred (TODO):** live QPF/forecast ingestion, SVI vulnerability layer, true SNODAS SWE,
NLCD `developedFrac`; thin state×hazard cells fall back to the pooled state base rate.
