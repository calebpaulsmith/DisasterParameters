# Event Hazard Overlay — Plan & Living Spec

**Status:** proposed, not built. Source of truth for the feature. Update as phases land.

**Owner's ask (2026-07-02, recorded verbatim in intent):** put the pre-declaration pipeline
(PDAs underway → requests in process) **on maps**, and show **the actual disaster as an
overlay** — river gauges, rain, wind — as a **timelapse with a timeline**. Target the
**live upcoming events first: Wisconsin and Michigan (requests in process) and Indiana
(upcoming, pre-request)** — then generalize.

---

## 0. Why this feature (and why now)

The app's value is concentrated in the weeks around an event (see chat log): "a disaster
just happened here — will it be declared, what will it become?" Today the app answers that
with *tables* (pending requests, lags, denial rates) and *history* (ledger, Geography).
This feature answers it with the **event itself**: what actually fell / blew / rose, where,
and when — on the same county map the Geography view already uses — while the declaration
decision is still pending. It is also the app's first honest **recurring** surface: a live
event's overlay changes daily until FEMA decides.

**Stays on the facts side of the line.** Everything rendered is a measured observation
(gage stage, station rainfall, storm reports) or a public status (PDA underway, request
pending). No likelihood, no judgment — the parked capacity-judgment product (CLAUDE.md
roadmap) remains parked. The analog context we attach (Phase 4) is the same
descriptive-history framing already shipped in `event_nexus.json` / `context.json`.

## 1. The live targets (as of the 2026-07-01 Daily Ops Brief)

From `data/pending.json` (all Region 5, all type DR):

| Entity | Incident | Requested | Programs | Status |
|---|---|---|---|---|
| **WI** | Severe Storms, Tornadoes, and Flooding | 2026-05-22 | IA+PA+HM | in process (40d waiting) |
| **MI** | Severe Storms, Tornadoes, and Flooding | 2026-06-04 | IA+PA+HM | in process (27d) |
| **MI** | Severe Storms and Tornadoes | 2026-06-23 | IA+HM | **appeal** (8d) |
| **IN** | *(not yet in the requests table — expected; watch the JPDA table)* | — | — | pre-request |

The pending summary table carries **no incident period and no county list** (known
limitation, see `build_pending.py` header) — so the tracked-event seed (§3) must carry a
curated incident window until OpenFEMA supplies the authoritative one at declaration time.
Indiana is the reason Phase 0 exists: the earliest public signal for a not-yet-requested
event is the brief's **Joint PDA table**, which we already know how to parse but only use
retrospectively.

## 2. What exists already (reuse, don't rebuild)

- **Map**: `data/r5_counties.json` (524 simplified county polygons) + the `MAPPROJ` SVG
  map in `index.html` with animated pan/zoom (`geoVB` machinery) and a mobile variant.
- **Timeline UI**: the Geography "Obligations by year" component with a draggable range
  handle — the interaction pattern (a stable container owning pointer events, inner SVG
  rebuilt per frame) is exactly what a time-slider/scrubber needs.
- **JPDA parser**: `parse_jpda()` in `scripts/build_request_dates.py:76` — per state-event
  IA/PA counties requested/complete from the Daily Ops Brief. Currently historical-only.
- **Funnel data**: `pending.json` (requests in process, refreshed daily),
  `request_dates.json` (request→decision history), `denials.json`, `disasters.json`.
- **Gage plumbing**: `gages.json` (19 curated gages with AHPS flood categories + crest
  history), live USGS IV fetches in the Watch view, `build_gages.py` patterns.
- **Rain plumbing**: `augment_rain.py` (RCC-ACIS daily precip, station→county).
- **Analog context**: `event_nexus.json` / `context.json` (per-disaster driver values
  placed in the historical distribution — `build_context.py`).

## 3. Data design

### 3.1 Sources per overlay layer — and the one hard constraint

| Layer | Historical disasters | **Live (pre-declaration) events** |
|---|---|---|
| River stage | USGS daily values (already in `hz`) | **same USGS API** — full series for the window, works live ✓ |
| Rainfall | RCC-ACIS daily precip (already used) | **same ACIS API** — works live ✓ |
| Wind / hail / tornado | NOAA Storm Events bulk CSV | ✗ **lags ~2–4 months — unusable for a current event.** Use **NWS Local Storm Reports** via the IEM archive (`mesonet.agron.iastate.edu` GeoJSON services): point reports with lat/lon, timestamp, magnitude, type. Preliminary/unvetted — label as such. |
| Declared counties (once decided) | OpenFEMA DisasterDeclarationsSummaries | same, at decision time |
| PDA / request status | — | `pending.json` + Phase-0 JPDA block |

LSR vs Storm Events is the one place live and historical packages differ, and the labels
must say so: Storm Events values are quality-controlled; LSRs are raw spotter/observer
reports. When a tracked event later lands in Storm Events, the backfill (Phase 5) replaces
the LSR layer.

**Gage coverage gap:** the 19 curated gages are thin exactly where the live events are
(WI 4, IN 3, MI 7 — mostly not in the affected basins). The builder must therefore query
the **USGS Site Service** for all stage-reporting sites (`parameterCd=00065`) in the
event's counties, pull their series, and carry NWS flood categories from NWPS where
resolvable (offline, per the CLAUDE.md NWPS caveats) — `official:false` approximations
otherwise, same convention as `gages.json`.

### 3.2 Artifacts (all committed; lineage seed updated with each)

- **`data/event_watch.json`** (small index): one entry per tracked event —
  `id, state, label, incidentWindow {start,end,basis}, status` (funnel:
  `pda → requested → appeal → declared|denied`, each stage with date + source link),
  `jpda {iaReq,iaComplete,paReq,paComplete}`, `requestDate`, `disasterNumber` (once
  declared), `overlayFile`.
- **`data/event_overlay_<id>.json`** (one per tracked event, loaded lazily, target
  ≤300KB): the hazard package —
  - `days[]`: the incident window plus padding (a few days each side);
  - `rain`: per county FIPS per day (in), station-derived like `augment_rain.py`, with
    `rainStations` provenance;
  - `gages[]`: site id/name/latlon/county, flood `cats` (+`official` flag), and the
    stage series aligned to `days`;
  - `reports[]`: LSR points `{t, lat, lon, kind (wind|hail|tornado|flood), mag, src}`;
  - `counties`: the event's county set and how it was derived (`basis`:
    seed | LSR-cluster | JPDA | designated);
  - `audit`: pull windows, row counts, dropped/out-of-window counts (conservation
    convention — nothing silently dropped).
- **`scripts/event_watch.seed.json`** (hand-curated, like `lineage.seed.json`): the
  tracked-event list — state, label, curated incident window + a `basis` note (governor's
  request press release, LSR cluster, JPDA event label date), optional explicit county
  list. The builder refuses to guess a window: no seed window and no confident
  LSR-cluster → the event builds status-only (no overlay) rather than a wrong one.

### 3.3 Builder + refresh

- **`scripts/build_event_overlay.py`** (OFFLINE, needs network): reads the seed +
  `pending.json`, pulls USGS/ACIS/IEM per event, writes the index + per-event overlays.
  Resumable cache under `data/_eventoverlay_cache.json` (gitignored `_` convention).
- **Refresh**: fold into the existing daily `refresh-pending.yml` run (after the pending
  parse, so status is current) — commit-on-change, gated on each overlay's audit
  reconciling. A tracked event stops refreshing 30 days after its decision; the committed
  package then stands as the historical record until Phase-5 backfill.
- **Lineage Guardian**: every new `data/*.json` + every new `fetch("data/…")` requires a
  `lineage.seed.json` append + `build_lineage.py && verify_lineage.py` — non-negotiable
  per CLAUDE.md; the seed edit is append-only.

## 4. UI design

### 4.1 Where it lives

A **per-event overlay page** reached from (a) the Disaster Timelines pending block —
each pending/PDA row for a tracked event gains a "🗺 event map" affordance — and (b) the
Watch view when a tracked event's state has active alerts. Implemented **inside
`index.html`** as a new detail surface (it reuses `COUNTIES`/`MAPPROJ`/the timeline
component directly), not a standalone page — unlike the Operations Planner, which is
standalone because its export artifact *is* the page. The two features stay distinct:
the planner is **user-authored and prospective**; the overlay is **measured and factual**.
(The planner's county drill-down should eventually link to an event's overlay and vice
versa — deferred, noted in §7.)

### 4.2 The event map

- County map zoomed to the event's state(s), event counties emphasized; the rest dimmed.
- **Funnel header** — the event's status strip: PDA (counties req/complete) → requested
  (date, programs, days waiting, queue percentile — already computed for pending rows) →
  appeal → declared/denied (with the decision brief link, per `request_dates.json`
  conventions). This is the "explorer" spine from the PDA-explorer discussion, folded in.
- **Layer toggles**: ☑ rainfall (county choropleth), ☑ gages (dots colored by stage vs
  flood category: below-action → major, the AHPS color ramp), ☑ reports (wind/hail/
  tornado/flood glyphs), ☐ designated counties (appears at declaration — **"the actual
  disaster as an overlay"**: the official FEMA designation drawn over the measured
  hazard footprint, the single most communicative frame this app can produce).
- **Time scrubber + play** (the timelapse): daily steps across `days[]`. Scrub → the map
  shows that day (daily rain, that day's peak stage per gage, that day's reports); play
  animates. A cumulative/daily toggle for rain (cumulative is the "storm total" story;
  daily is the "when it fell" story). Report dots accumulate during play with a fade so
  the swath reads as a track.
- Every layer's legend links to its source (USGS site page, IEM LSR archive, ACIS) —
  standard traceability rule.
- Mobile: same surface, chip-row layer toggles, scrubber full-width (the `gm*` patterns).

### 4.3 Labeling (must-keep)

- Pre-decision surfaces carry the same UNOFFICIAL framing as the pending block: statuses
  are parsed from the Daily Ops Brief (source link on every stage), not an OpenFEMA feed.
- LSR layer labeled **"preliminary local storm reports (unvetted)"**; replaced by Storm
  Events on backfill.
- Incident window labeled with its `basis` when curated ("window per governor's request
  letter", etc.) until the authoritative OpenFEMA period replaces it at declaration.
- No estimate/likelihood anywhere on this surface.

## 5. Phases

- **Phase 0 — PDAs underway (prerequisite; small).** Run `parse_jpda()` in the daily
  pending refresh, write a `pdas` block into `pending.json`, render a "PDAs underway"
  table on Disaster Timelines (state · event · IA/PA counties requested vs complete,
  R5/National clicker, unofficial-parse label). **This is how Indiana gets picked up the
  day it surfaces.** Also gives every tracked event its earliest funnel stage.
- **Phase 1 — data.** Seed with WI + MI(×2); `build_event_overlay.py`; commit
  `event_watch.json` + per-event overlays; wire the daily refresh; lineage.
- **Phase 2 — map + timelapse UI.** The event page: map, funnel header, three hazard
  layers, scrubber/play. Desktop + mobile.
- **Phase 3 — decision join.** On declaration: designated-counties overlay, ledger
  cross-link (detail modal ↔ event overlay), funnel completes. On denial: denial-modal
  link, overlay stands as the record of a turned-down event — which the ledger has never
  been able to show before.
- **Phase 4 — analog context.** Attach the `context.json` distribution framing to the
  funnel header (e.g. "peak gust 82 mph — of 34 prior WI wind events at ≥80 mph, 21 were
  declared"): descriptive counts only, reusing `build_context.py` machinery.
- **Phase 5 — historical backfill (the generalization).** The same package built from
  Storm Events + ACIS + USGS for any ledger disaster → a "hazard timelapse" button in the
  ledger detail modal. Start with the analogs of the tracked events, not all 80.

## 6. Open decisions (owner input wanted, none block Phase 0/1)

1. **Incident windows for WI/MI**: I'll draft seed windows from LSR clustering + the
   states' request press releases and mark `basis` — owner should eyeball them.
2. **Warning polygons** (NWS watch/warning shapes from the IEM SBW archive) as a fourth
   layer: high narrative value, moderate size cost. Proposed: defer to Phase 4+.
3. **Step resolution**: daily now; hourly is possible later (USGS IV + LSR timestamps
   support it; ACIS daily rain does not) — daily first, revisit after Phase 2.

## 7. Deferred / do-not-drop

- Planner ↔ overlay cross-links (`operations-planner-plan.md` county drill-down).
- Hourly timelapse steps; warning-polygon layer.
- Backfill sweep of all 80 ledger disasters (after Phase 5 proves the frame).
- Auto-promotion: a JPDA row in an R5 state auto-creates a status-only tracked event
  (still needs a curated window before an overlay builds).
