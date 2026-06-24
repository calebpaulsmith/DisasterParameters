# Timeline — Archive & Parked Specs

This file preserves work that was paused on 2026-06-24 when the Geography timeline was
pivoted to a **per-view, metric-driven** design (see the disasters-first rework). Nothing
here is live; it's kept so the prior direction and the original implementation can be
referenced or restored without spelunking git history.

---

## A. Current stacked-dollar timeline — as-built spec (PR #46, commit 25394ed)

The first timeline rendered ONE stacked chart combining every program's dollars per year.
It was replaced by the per-view design. Spec of what it did, for reference:

### Data
- Per-county + per-state `*ByYear` buckets in `data/county_declarations.json`, built by
  `scripts/build_county_byyear.py`:
  - `paByYear`, `paProjectsByYear` — true obligation year (`lastObligationDate`)
  - `hmgpByYear`, `mitByYear` — true obligation year (`initialObligationDate`)
  - `ihpByYear` — proxy by disaster incident year
  - `empgByYear`, `afgByYear` — grant fiscal year (state-level)

### State variables
```
GEO_YR0, GEO_YR1        full data span (from DECL on load)
geoYearLo, geoYearHi    selected inclusive range
geoTlDomLo, geoTlDomHi  visible animated domain (expand/contract)
geoTlAnim               rAF handle
GEO_YEARKEY             metric -> *ByYear field map
geoYrFiltering()        true when a sub-range is selected
yrSum(map,lo,hi)        sum a byYear map over [lo,hi]
inYr(rec)               record (by date/begin year) in range?
```

### Series (the thing being removed)
```
const GEO_TL_PROGS=[
  {yk:"paByYear",  lab:"PA",         c:GEO_BAR.paObligated},
  {yk:"ihpByYear", lab:"IHP",        c:GEO_BAR.ihpApproved, proxy:true},
  {yk:"hmgpByYear",lab:"HMGP",       c:GEO_BAR.hmgpObligated},
  {yk:"mitByYear", lab:"Mitigation", c:GEO_BAR.mitObligated}];
```

### Functions
- `geoSetYearBounds()` — derive `GEO_YR0/1` from the union of `GEO_TL_PROGS` year keys.
- `geoScopeByYear(yk)` — scope-aware byYear map for region/state/county.
- `geoScopeLabel()` — "Region 5" / state name / "X County, ST".
- `renderGeoTimeline()` — builds the SVG: stacked rects per year, in-range bars opaque,
  out-of-range context bars at 0.26, selection highlight, two draggable handles, legend,
  "all years ✕" reset, basis caption.
- `geoTlYearAtX(clientX)`, `geoTlAnimateDomain(tLo,tHi)`, `geoTlFocus()` (expand/contract),
  `geoTlCommit()` (focus + re-render all + detail), `geoTlSetRange(lo,hi)`.
- `geoTlBind()` — pointer events on the stable `#geoTimeline` container (drag handles,
  click a bar to isolate a year, swallow synthetic post-drag click).
- Propagation: `geoCountyVal`/`geoStateVal` window via `GEO_YEARKEY`+`yrSum`; detail panes
  use `geoYrCap()` + `inYr()`.

### Behavior
Drag handles → range filters every figure on the tab; the visible domain animates to focus
on the selection (expand when widening, contract when narrowing). Click a bar → 1-year range.
PA/HMGP/Mit = true obligation year; IHP* = proxy incident year; EMPG/AFG & COVID excluded
from the chart.

---

## B. Parked plan — mobile timeline + per-program mitigation (NOT being built now)

This was the approved-then-paused direction. Parked because it grouped timeline concerns
prematurely. Revisit only after the per-view redesign settles.

### B1. Mobile port of the (then-single) timeline
- Extract the timeline SVG builder into a shared helper; render into desktop `#geoTimeline`
  and a new mobile `#gmTimeline` at the top of `renderGeoMobile()`.
- Make `gmVal()` year-aware (mirror `geoCountyVal`/`geoStateVal`: `yrSum(o[GEO_YEARKEY[m]],…)`).
- Window mobile header pills + add a `(YYYY–YYYY)` label when filtering.
- Touch: reuse `geoTlBind` pointer events, ≥44px hit zones, tap-a-year fallback.
- Route `geoTlCommit()` through `geoRenderAll()`; unhide mobile timeline in the ≤760px CSS.

### B2. Per-program mitigation (year-sliced)
- **Data gap**: `mitByProgram` (all-time per program FMA/PDM/BRIC/LPDM/RFC/SRL) and
  `mitByYear` (per year, all programs) exist, but there is **no `mitByProgramByYear`** — so
  the program chips are ignored once a year range is active
  (`geoCountyVal` comment: "per-program mit isn't year-sliced (v1)").
- **Fix**: add `mitByProgramByYear` (`{prog:{year:$}}`) per county + state in
  `scripts/build_county_byyear.py` (add `programArea` to the MIT `$select`; accumulate
  `miPC[fips][prog][y]` / `miPSW[ab][prog][y]`; roll up county+statewide per program-year;
  re-run with OpenFEMA network). Reconcile `Σ_y mitByProgramByYear[p] ≈ mitByProgram[p]` and
  `Σ_p mitByProgramByYear ≈ mitByYear`.
- **UI**: in `geoCountyVal`/`geoStateVal` mit branch, when filtering AND `geoMitProg!=="ALL"`
  → `yrSum(mitByProgramByYear[prog], lo, hi)`. Window `geoMitProgRows` by range. Optionally
  split the mitigation timeline segment into per-program colors (gated to the mit metric) via
  a `GEO_MIT_COLORS` ramp.
