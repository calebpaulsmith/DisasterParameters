# Conditions in Context — design + implementation plan

**Supersedes the front-end of `analysis/state-declaration-model.md`.** The offline
pipeline and the county/state panel it describes are **kept and reused**; what
changes is the *product*: we are scrapping the "Will it be declared?" predictor
view (probability gauge, sliders, feature-importance bars, choropleth) and
replacing it with an **information & comparison** tool.

## The one goal (in the maintainer's words)

> Surface relevant weather data and compare that data to previous events (or
> non-events) to give the viewer perspective on current disasters. **I don't need
> a predictor, I need GOOD INFORMATION which actually drives significant weather.**

So: **perspective, not probability.** For each hazard, surface the metric that
actually drives Region 5 disasters, and show where the current situation — or any
past event — sits against the full record of events that *were* and *weren't*
declared, with the real PA/IHP dollars attached. No "% chance," no gauge.

## What the data says we must build around (do not relitigate)

From `analysis/county-driver-findings.md` (47,057 county-episodes, 2,890 declared,
6.1%) and the hazard composition of `data/disasters.json` (80 R5 disasters, ~$10.76B):

1. **R5 majors are flood-dominated but compound.** Flooding tags 67/80 disasters
   ($3.9B); Wind 56 ($3.3B); Hail 54 ($2.6B); Tornado 36 ($2.2B); Snow/Ice 9. Most
   majors are Flooding+Wind+Hail compound events. **River stage is populated for
   only ~63% of floods** — gages are *one flood sub-signal, not the spine.*
2. **Declarations are damage/exposure-mediated, not intensity-triggered.** IL
   tornado *count* p50/p90 is identical for declared vs non-declared; declared rate
   climbs with **damage** and **footprint**, not inches/mph.
3. **Drivers vary by state × hazard.** MN flood declares 38% of episodes (dominant);
   rain splits floods in WI/IL but **not MN** — MN floods are **spring snowmelt**
   (42% of MN <1″-rain flood episodes are still declared).
4. **Each hazard has a real driver metric except winter.** flood→rain depth +
   Atlas-14 rarity (+ snowmelt/SWE in MN, + crest where gaged); tornado→EF;
   wind→peak gust; hail→max size. **Snow/Ice currently has only report counts —
   a real data gap we are closing in this plan (see Phase 1).**

The honest "nexus" is therefore **driver metric + footprint/exposure, placed
against the declared-vs-non-declared distribution** — never a single magic
threshold, and explicitly showing the cases where intensity does *not* separate.

## Product: "Conditions in Context"

A new view (replacing the scrapped predictor) plus an upgrade to the ledger detail
modal. Three lenses, one comparison engine:

- **Now** — live conditions per state/region; each hazard's live driver shown
  against history (recent/forecast rain → ARI; NWS warnings; live USGS stage).
- **Past event** — pick a real disaster; see its driver metrics in historical
  context (was its rain a 1-in-50? was its footprint large? did extent or
  intensity drive it?), with its real PA/IHP.
- **State × hazard drill** — the declared-vs-**non-declared** distribution of the
  driver metric for that state×hazard, with analog disasters and costs.

### Per-hazard nexus (the spine)

| Hazard family | Driver metric(s) we surface | Live signal | Honest caveat shown |
|---|---|---|---|
| **Flood — rain-driven** (WI/IL/IN/OH/MI) | peak 1-day + multi-day antecedent rain as **Atlas-14 ARI** + **footprint** (# counties over flood, pop exposed) | recent/forecast rain, NWS Flash-Flood Warnings | rain separates declared floods *here* |
| **Flood — snowmelt** (MN) | **snowpack/SWE + rapid melt** (+ river crest vs flood stage where gaged) | live USGS stage, snowmelt layer | **rain does NOT separate MN floods** |
| **Tornado / wind / hail** | EF / peak gust / max hail **plus footprint + damage proxy + pop exposed** | SPC reports, NWS warnings | **intensity alone barely separates** — extent/damage drives it |
| **Winter (snow/ice)** | **event snowfall accumulation + antecedent snowpack/SWE** (new, Phase 1) + NWS winter warnings | NWS winter warnings | thin sample (9 disasters) — wide intervals |

## Pipeline (regenerate the panel first)

Reuse the existing offline chain; **add two winter enrichers**; **skip model fit**
(an information tool needs empirical distributions, not fitted coefficients — and
the goal is explicitly *not* a predictor).

```
download StormEvents_details-*.csv.gz (FY2008–2025) into data/   [NCEI, reachable]
  build_panel.py            → data/county_panel.json  (git-ignored)
  build_precip.py           + rainDayMaxIn, rainEventIn, rainAnte7/14In
  build_snow.py             + snowDepthPreIn, snowMeltIn          (GHCN SNWD depth)
  build_snowfall.py  (NEW)  + snowfallEventIn                     (GHCN SNOW accumulation — winter-storm severity)
  augment_swe.py     (NEW)  + sweAntecedentIn / sweMeltIn         (snowpack: NOHRSC/SNODAS SWE; GHCN-depth fallback if SNODAS infeasible here)
  augment_ari.py            + rainDayMaxARIyr, rainEventARIyr      (NOAA Atlas-14)
  augment_stage.py          + ftAboveFlood, stageCat, hoursAboveFlood (USGS)
  augment_exposure.py       + population, housingUnits             (Census ACS — key obtained)
  build_state_panel.py      → data/state_panel.json  (git-ignored; add maxSnowfallEventIn, maxSweAntecedentIn)
  build_context.py   (NEW)  → data/context.json + data/event_nexus.json  (committed, small)
```

`enrich.py` / `disasters.json` are **never** touched by the modeling chain (the
costs landmine). A separate additive `augment_snow_hz.py` (mirrors the existing
`augment_rain.py` pattern — adds `hz` fields only, leaves `costs` untouched) stamps
per-disaster `hz.snowfallIn` / `hz.sweIn` so the **ledger detail modal** has real
winter numbers for the per-disaster nexus.

### Committed artifacts (reframed away from "prediction")

- **`data/context.json`** — per state × hazard: the **declared-vs-non-declared
  distribution** of each driver metric (histogram bins carrying *both* declared and
  non-declared counts — the denominator), analog disasters with PA/IHP, footprint
  stats. No probability headline; bins read as "of N comparable episodes, M were
  declared."
- **`data/event_nexus.json`** — per disaster: its characterizing driver values +
  where each sits in history (how-often-before, declared share at that level) +
  related drivers. (Reframes today's `triggers.json`.)

The old `predictor.json` / `model.json` are retired (probability framing); their
reusable content — bins with declared counts, analogs, cost summaries — migrates
into `context.json`. No fitted model, no `model.json`.

## Front-end work

**Phase 2 — teardown.** Delete the predictor view: `#view-forecast` section, all
`.fc-*` + `.impbar` CSS, all `fc*` JS, the `FC_DRIVERS` config, the probability
gauge, sliders, feature-importance bars, the choropleth map tied to it, and the
`predictor.json`/`model.json` fetches. (The section is isolated; Estimator, Watch,
Ledger are independent.)

**Phase 3 — build.** New "Conditions in Context" view (three lenses, multi-hazard)
+ upgrade `renderDisasterDetail()` to show the real per-disaster nexus from
`event_nexus.json`. Keep Public Sans / DHS navy+gold / .gov banner.

**Phase 4 — honesty/QA.** Keep all non-endorsement disclaimers; reconcile cost
figures (PA obligated vs IHP approved; AB+CG+Z=paTotal); wide intervals; obligation-
lag caveat; traceable source links on every number; thin-sample flags for winter.

## Decisions locked (2026-06-17)

- **Exposure:** obtain a Census API key (or keyless ACS) → real population/housing
  exposed in the panel.
- **Winter:** build the snowfall-accumulation enricher **and** snowpack/SWE now
  (not deferred); flag thin sample.
- **Model fit:** skipped — empirical distributions only.

## Regenerate (commands)

```bash
# 0. download StormEvents CSVs into data/ (URL in scripts/enrich.py header)
python3 scripts/build_panel.py
python3 scripts/build_precip.py
python3 scripts/build_snow.py
python3 scripts/build_snowfall.py          # NEW
python3 scripts/augment_swe.py             # NEW
python3 scripts/augment_ari.py
python3 scripts/augment_stage.py
CENSUS_API_KEY=… python3 scripts/augment_exposure.py
python3 scripts/build_state_panel.py
python3 scripts/build_context.py           # NEW → data/context.json + data/event_nexus.json
python3 scripts/augment_snow_hz.py         # NEW (additive hz only) → data/disasters.json
```
