# What drives a county's FEMA declaration? — PoC findings

**Goal:** determine which measured metrics drive a county's disaster declaration,
by hazard and by geography, so the app can surface the *relevant* metrics per
county, flag when thresholds are met, and show how often that has happened.

**Method (PoC):** `scripts/build_panel.py` builds a **county × storm-episode
panel** from the NOAA Storm Events CSVs (FY2008–2025, Region 5, county-level
events). Storm Events natively contains non-declared events, so the panel has
both **positives** (county-episodes inside a FEMA disaster window for that
county) and **negatives** (everything else). Each row aggregates that county's
metrics for that storm episode: peak wind gust / sustained, max hail, # tornadoes
and max EF, flood flag, property damage, month. Rows are labeled declared / not
by joining to the FEMA incident windows + designated counties.

**Scale:** 47,057 county-episodes; **2,890 declared (6.1%)** — a workable base
rate for a "given a notable storm episode, was it declared?" framing.

## Finding 1 — declarations are damage-mediated, not threshold-triggered

Physical metrics *alone* barely separate declared from non-declared episodes;
**damage** is the separator (and the metrics matter mainly as damage proxies):

| IL tornado episodes | declared p50 / p90 | non-declared p50 / p90 |
|---|---|---|
| # tornadoes | 1.0 / 3.0 | **1.0 / 3.0** (identical) |
| max EF | 1.0 / 2.2 | 1.0 / 2.0 |
| max gust mph | 64 / 90 | 0 / 81 |
| **$ property damage** | **$160K / $11M** | **$0 / $303K** |

Declared rate climbs monotonically with damage — IL tornado episodes: **$0 → 4%
declared, $1–10M → 19%, ≥$10M → 47%.** This matches how FEMA actually works
(per-capita *damage/need*, not inches/mph), and tells us the panel must carry
damage + exposure, not just raw hazard intensity.

## Finding 2 — drivers vary sharply by state × hazard (the differentiation you wanted)

Declared base rate by state × hazard (declared / episodes):

| state | tornado | wind ≥60mph | hail ≥1in | flood |
|---|---|---|---|---|
| IL | 6% | 5% | 4% | 11% |
| IN | **15%** | 5% | 6% | 12% |
| MI | 6% | 2% | 2% | 11% |
| **MN** | 13% | 9% | 8% | **38%** |
| OH | 5% | 3% | 2% | 4% |
| WI | 10% | 7% | 3% | 15% |

**MN flooding (38%) dominates** every other cell — flooding is by far the most
declaration-prone hazard in Minnesota, exactly as expected. IL/IN/OH lean more
tornado/wind/hail. This matrix is the backbone of "surface the *relevant*
metrics for *this* county."

## Finding 3 — what each data source can and can't separate

- **Wind:** Storm Events records **gust** well but **sustained wind is essentially
  absent** (the MS/ES magnitude type is rarely populated for thunderstorm wind).
  Sustained-wind drivers would need ASOS/METAR, not Storm Events.
- **Flood:** Storm Events damage is a **poor proxy** for flood declarations — even
  **$0-recorded-damage MN flood episodes are 36% declared** (riverine/agricultural
  loss isn't in the Storm Events property-damage field). Flood states therefore
  **cannot** be separated on Storm Events alone; they need the physical flood
  drivers: **rainfall (daily + multi-day antecedent), river crest vs flood stage,
  and snowpack (SWE).**

## Precipitation layer results (added via `build_precip.py`)

We added per-county-episode rainfall from gridded PRISM (RCC-ACIS, county-reduced):
peak 1-day, event total, and 7/14-day **antecedent**. Rerunning declared-vs-not on
**flood** episodes shows rainfall is a strong driver in some states and a
**non-driver** in others — which is itself the key result.

Flood episodes, declared vs non-declared (p50 / p90):

| state | peak 1-day (dec / non) | 14-day antecedent (dec / non) | reads as |
|---|---|---|---|
| **WI** | **3.39 / 7.5** vs 0.84 / 4.41 | 2.98 / 7.36 vs 2.01 / 4.48 | strongly rain-driven |
| **IL** | 1.02 / 5.07 vs 0.72 / 3.49 | **3.33 / 8.08** vs 2.48 / 5.17 | rain + antecedent matter |
| **MN** | 0.56 / 5.54 vs **1.23** / 4.67 | 2.36 / 5.53 vs 1.98 / 4.05 | **rain does NOT separate** |

Declared rate by peak 1-day rainfall (flood episodes):
- **IL:** <1″ → 10%, ≥4″ → **24%** (heavy rain ~doubles declaration odds).
- **MN:** <1″ → **42%**, ≥4″ → 45% (flat — low-rain floods are *just as* likely declared).

**The MN result is the headline.** Minnesota flood declarations are largely **spring
snowmelt** (Red River / Minnesota River basins) — the water comes from melting
**snowpack**, not concurrent rain — so 42% of MN flood episodes with <1″ of rain are
still declared. Rainfall alone can't model MN floods; **snowpack (SWE) is the missing
driver** there, exactly as hypothesized. Meanwhile precip materially improves the
flood model for **WI / IL** (and flash-flood states generally).

Takeaway for surfacing: rainfall thresholds are meaningful drivers to show for
**IL/WI/IN/OH/MI flash-flood and rain-driven flooding**, but **MN (and Red River
WI/ND border) needs the snowpack layer** before its flood metrics are trustworthy.

## Recommended next steps

1. ~~Add the precipitation layer~~ ✅ **done** (`build_precip.py`) — rain + antecedent
   now separate declared flood episodes in WI/IL; revealed MN floods are *not*
   rain-driven.
2. **Add snowpack (SWE)** from SNODAS/NOHRSC for MN/WI/MI Dec–Apr episodes — now the
   clear top priority: it's the missing driver for the MN spring-snowmelt floods
   that rainfall can't explain (42% of MN <1″-rain flood episodes are declared).
3. **Join river crest-over-flood** (we already have `gages.json`) onto flood
   episodes by county.
4. **Fit a model** — logistic regression / gradient boosting for P(declaration |
   metrics, state, season), with state×hazard interactions (or per-state models).
   Outputs calibrated probabilities + feature importances = *which metric drives
   each county's declarations*.
5. **Surface in the app** — per county, derive its hazard profile from the panel,
   show only the relevant metrics with their empirical declared-vs-not thresholds,
   flag when a live/incident value crosses them, and show the historical hit count
   (and how often hits became declarations).

## Reproduce

```bash
python3 scripts/build_panel.py   # -> data/county_panel.json (git-ignored) + this analysis
```

Storm Events CSVs must be in `data/` (the same files `enrich.py` uses).
`data/county_panel.json` (~10 MB) is **git-ignored** — it's a regenerable
intermediate; only the script and these findings are committed.
