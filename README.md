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

## Three views

**1. Estimator** — set a current event's **measured** hazard parameters (peak
wind, max hail, peak river stage, rainfall, tornado EF) plus state and affected
population, and get:
- estimated PA, IA, and total federal obligations with honest low–high intervals
- a major-disaster **declaration likelihood** gauge
- a **threshold panel** flagging exactly what a request trips against FY2026 FEMA
  indicators — statewide ($1.89/capita), countywide ($4.72/capita), the
  $1,062,900 large-project threshold, and the $189/capita 75%→90% cost-share line
  — with the dollar gap to each
- the **5 closest analog disasters** ranked by *measured-hazard* similarity, each
  showing real obligations, incident dates, multi-type tags, and PA/IA badges

**2. Disaster Watch** — live regional monitoring that **trips when current
conditions approach a past disaster's threshold**:
- active **NWS alerts** across Region 5 (live from `api.weather.gov`)
- **live USGS river gages** with stage vs. flood stage
- **trigger cards**: e.g. "River X is at 88% of the 27 ft peak during DR-4461,
  which obligated $67M" — and warning-mix matches to analog disasters
- an overall threat level, auto-refreshing every 5 minutes

**3. Region 5 History** — a **seasonality timeline** (declarations by month) with
type filters (Flooding / Tornado / Wind / Hail / Snow-Ice / Storms), and a
sortable **ledger** of every disaster: number (desc), incident period, state,
type tags, PA/IA, and measured wind / hail / stage / tornado.

## Data — real, measured, mostly live

| Layer | Source | How |
|---|---|---|
| **Obligations** (PA obligated / IHP approved $) | OpenFEMA `FemaWebDisasterSummaries`, `DisasterDeclarationsSummaries v2` | Baked + refreshed **live** in-browser |
| **Hazards** (wind, hail, tornado EF) | **NOAA Storm Events Database** | Joined **offline** by county FIPS + incident window |
| **River stage** (peak ft) | **USGS Water Services** (daily values) | Joined **offline** per disaster's counties |
| **Live alerts** | **NWS** `api.weather.gov` | Fetched **live** in-browser |
| **Live gages** | **USGS** instantaneous values | Fetched **live** in-browser |

**Terminology:** PA is *obligated*, IHP is *approved*, and **IA (Individual Assistance) is the
umbrella, IHP (Individuals & Households Program) is the program with public dollars** — see
[`docs/fema-assistance-glossary.md`](docs/fema-assistance-glossary.md) (with committed OpenFEMA
field dictionaries in [`docs/openfema-definitions/`](docs/openfema-definitions/)).

The hazard metrics are **measured observations, not proxies.** Because NOAA
Storm Events has no live browser API, the historical hazard join is done offline
by `scripts/enrich.py`, which writes `data/disasters.json` (baked into the page
so it works offline too). The live OpenFEMA / NWS / USGS calls run in the browser.

### Rebuilding the dataset

```bash
# download NOAA Storm Events CSVs into data/ (see script header for URL), then:
python3 scripts/enrich.py        # -> data/disasters.json
python3 -c "import json,re; h=open('index.html').read(); ..."   # re-inject if templating
```

`data/disasters.json` and `data/gages.json` are committed; the raw Storm Events
CSVs are git-ignored (large, regenerable).

## Run it

No build step, no dependencies. Open `index.html`, or serve it:

```bash
python3 -m http.server 8000   # then visit http://localhost:8000
```

Deploys as-is to GitHub Pages (already wired via `.github/workflows/pages.yml`).

## Method (analog / nearest-neighbor)

Your measured hazard inputs are normalized and compared to each historical event
with a Gaussian similarity kernel (plus an incident-type bonus). The closest
events form the analog set; their real obligations are converted to per-capita
rates using their impacted-county footprint, similarity-weighted, and re-scaled
to your affected population. Intervals span the spread of the nearest analogs —
deliberately wide, because disaster cost is zero-inflated and long-tailed.

## Limitations

- Storm Events hazard reports are NWS "best estimates"; USGS gage height is
  daily-mean (understates instantaneous crest); some events join at state level
  where county detail is missing. River flood-stage thresholds are approximate.
- Obligations lag and reconcile over years — recent disasters under-count.
- Only *declared* events are modeled; declaration is partly bureaucratic.
- The live watch is informational only — for official warnings consult
  weather.gov and water.noaa.gov.

## Key gages (the predictors)

`scripts/build_gages.py` builds `data/gages.json`: ~19 major Region 5 river
gages, each with USGS site metadata, **NWS AHPS** flood categories, its full
**USGS annual peak-crest history** (90–150 years), and the Region 5 disasters
**tied to it** — a past crest counts as a *declaration crest* when it falls in a
disaster's incident window and that disaster's designated counties include the
gage. That yields a **stage → cost** relationship per gage (the lowest crest
that has triggered a declaration = the gage's `minDeclStage`).

In the app: tap a disaster to see the specific gages that rose; tap a gage for
its crest timeline with declaration markers, AHPS flood-stage lines, and the
**live** USGS level plotted against the declaration threshold. The Disaster
Watch surfaces every key gage's live level as a share of its threshold — the
live→prediction nexus.

Rebuild: `python3 scripts/build_gages.py` (run after `enrich.py`; uses the live
USGS site/peak/IV services, NWPS for AHPS, and `data/_disasters_raw.json`).
