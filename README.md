# Disaster Obligation Estimator — FEMA Region 5 (PA/IA)

A single-file, FEMA/DHS-styled web tool that turns **current event conditions
— wind, hail, flooding, rainfall —** into an estimate of likely **FEMA Public
Assistance (PA)** and **Individual Assistance (IA/IHP)** *obligated dollars*,
benchmarked against the **actual obligations of analog historical disasters**.

It answers the question HAZUS, the National Risk Index, and commercial cat
models do *not*: **given this event, roughly how many federal dollars get
obligated — and which funding thresholds does it trip?**

> **Not endorsed by FEMA.** This product uses the Federal Emergency Management
> Agency's OpenFEMA API but is an independent demonstration tool. It must not be
> used to make individual eligibility or rights determinations. Estimates are
> illustrative, not financial or legal advice.

## What it does

- **Executive-friendly headline:** estimated PA, IA, and total federal
  obligations with honest low–high intervals, plus a major-disaster
  **declaration likelihood** gauge.
- **Threshold panel:** flags exactly what a request would trigger against
  FY2026 FEMA indicators — statewide ($1.89/capita) and countywide
  ($4.72/capita) impact indicators, the $1,062,900 large-project threshold,
  and the $189/capita 75%→90% cost-share line — with the dollar gap to each.
- **Closest analog disasters:** the 5 most similar past Region 5 events ranked
  by hazard similarity, showing their **real OpenFEMA obligations** and a
  side-by-side comparison bar.
- **Load a real event:** pick an actual Region 5 disaster to see how the tool
  would have estimated it.

## Data

- **Live from OpenFEMA** (public domain, CORS-enabled, no key required):
  - `FemaWebDisasterSummaries` (v1) — PA obligated and IHP approved totals.
  - `DisasterDeclarationsSummaries` (v2) — state, incident type, dates, county
    footprint; filtered to Region 5 major (DR) declarations, excluding
    Biological/COVID.
- A 36-event **embedded snapshot** is used automatically if the live API is
  unreachable, so the tool always works offline.
- **Hazard metrics are modeled proxies.** OpenFEMA records the dollars but not
  the measured wind/hail/flood/rainfall of each event; those signatures are
  derived here from incident type, narrative title, and obligation scale. A
  production model joins NOAA Storm Events, USGS streamgages, and hazard swaths.

## Run it

No build step, no dependencies. Open `index.html` in a browser, or serve it:

```bash
python3 -m http.server 8000   # then visit http://localhost:8000
```

Deploys as-is to GitHub Pages or any static host.

## Method (analog / nearest-neighbor)

Your hazard inputs are normalized and compared to each historical event with a
Gaussian similarity kernel (plus an incident-type bonus). The closest events
form the analog set; their real obligations are converted to per-capita rates
using their impacted-county footprint, similarity-weighted, and re-scaled to
your affected population. Intervals span the spread of the nearest analogs —
deliberately wide, because disaster cost is zero-inflated and long-tailed.

See the in-app **"How this estimate is built"** and **"Important limitations"**
panels for the full methodology and caveats.
