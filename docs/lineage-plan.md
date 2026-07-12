# Data Lineage ("Provenance Atlas") — Plan & Living Spec

**Status:** Phase 0 (manifest + builder + CI Guardian) **merged**. Phase 2 (the
`lineage.html` visual — tiered DAG, cards, focus/impact, live freshness) **merged**, plus
a polish pass (barycenter crossing-reduction, program filters, isolate/trace, responsive).
Phase 3 (column-level: click a field → consuming transforms → surfaces, with a
"declared-used-but-unfound-in-any-script" slop flag) **v1 shipped**. Outage / red-line
mode **shipped** — a "Pipeline health" toggle fetches each refresh workflow's last run
from the public GitHub Actions API (CORS-open) and red-lines the impacted downstream
cone (transforms → artifacts → at-risk surfaces), plus a "✓ manifest verified" badge
from the Guardian's own run. Live-source column tracing **shipped** — NWS/USGS live
sources are now wired to the Watch surface (no longer orphan nodes), carry their real
fields, and a field click traces them "read live" to the surface via an `index.html`
scan (`build_lineage.py` now attributes columns to surface consumers, not just
transform scripts). Freshness coverage **shipped** — `build_manifest.py` now stamps a
"covers-through" `dataAsOf` (explicit build/coverage field, else newest dated record) +
an honest `sourceCadence` on every committed file, and the manifest describes itself.
**Staleness semantics corrected:** only **automated-pipeline** files (recent/newsreel/
manifest/nfip/pending/request_dates) carry a staleness clock — for them `dataAsOf` is the
last successful pull, so amber/red means the **pull is failing**. Manually-built files
(the ledger, national, gages, county rollups) and static geometry render as a neutral
**snapshot/reference** state showing "covers through …" — record age is NOT treated as
staleness (a quiet disaster season must not turn the ledger red). `isAutoArtifact()` in
`lineage.html` derives this from each artifact's producing-transform schedule. Phase 1
(health) folded into render-time per §5. Next: live API up/down probes + a live
behind-source check (our latest record vs the source's). This doc is the source of truth;
update it as phases land; do **not** let scope quietly shrink
— see [§9 Scope guard](#9-scope-guard--deferred-but-do-not-drop).

**Branch:** `claude/data-lineage-chart-odfw2b`

---

## 0. Why this exists (the owner's intent, preserved verbatim-in-spirit)

This repo has grown a dense web of data sources → build scripts → committed JSON
→ UI views, developed fast (often AI-assisted, not always triple-checked). We want
a **data lineage graph + lightweight data catalog** that:

1. Lets the owner *and other users* understand where every figure on the site is
   derived from — traceable, end to end, source → screen.
2. **Surfaces and tracks staleness and outages**: if a source pull fails or a
   snapshot goes stale, the graph visually traces the blast radius downstream
   (a "red line" through every impacted transform and UI element). Make it
   graphical and cool — a Star-Trek status board.
3. (Later) lets users **reproduce** these connections/visuals in their own products
   (Power BI is the priority target; also website, SharePoint, Databricks).
4. (Later) yields a **generalized spec** the owner can paste into *other* convoluted
   repos so their session builds the same kind of lineage view.
5. (Later) supports **manual refresh** (whole or per-source), with each refresh's
   timing/method/ramifications shown, and eventually a diff of what changed.

The owner's explicit anti-pattern to guard against: *"Claude sometimes scopes down
on big projects and the product dwindles toward the middle and end."* This spec
exists to prevent that. Every deferred item is recorded in §9, not dropped.

---

## 1. This already exists (don't reinvent the model — reinvent only the rendering)

This is a mature software category. We deliberately **borrow the data model and
vocabulary** from these and **render it ourselves**, because none of them fit a
no-build, single-file, vanilla-JS, GitHub-Pages app fed by hand-rolled Python:

- **dbt** — `sources → models → exposures` DAG, upstream-left / downstream-right.
  dbt's **"exposures"** are *exactly* our UI layer ("this dashboard depends on these
  models"). We copy this three-tier shape.
- **OpenLineage** — open JSON standard modeling the world as **datasets** (data
  nodes) + **jobs/runs** (process nodes). This is the structural spine we adopt
  (see §3). Aligning to it is also what makes Goal #4 (a portable spec) generalize.
- **Marquez** — OpenLineage's reference UI. **DataHub / Atlan / OpenMetadata** —
  full catalogs that already do column-level lineage, click-a-column→downstream,
  and red-line impact propagation. These are our *feature* north stars.
- **Power BI lineage view / Databricks Unity Catalog lineage** — same idea inside
  walled gardens; the Power BI one is our eventual export target (Goal #3).

**Why we still build our own:** every tool above assumes a warehouse + an
orchestrator (SQL/Spark/Airflow) *emitting events as it runs*. We have pandas
scripts producing committed JSON, served statically. Adopting dbt/DataHub would
mean rearchitecting the whole project. So: **steal the model, render in-app.**

---

## 2. Terminology (canonical — use these names everywhere)

The whole feature: **the Lineage view** (sober) / **"Provenance Atlas"** (branded).
The data file: the **lineage manifest** (`data/lineage.json`).

**Core insight (from OpenLineage): there are only two kinds of nodes.**
**Data nodes** hold data; **process nodes** transform it. Edges always flow
`data → process → data`. This dissolves most of the confusion about "the middle."

Tiers, upstream → downstream (rendered left → right):

| Tier | Name | What it is here | Node kind |
|---|---|---|---|
| 5 | **Provider** | OpenFEMA, USGS, NWS, NOAA, Data Liberation Project | data (origin) |
| 4 | **Source** | a specific dataset/endpoint + its columns (e.g. `FemaWebDisasterSummaries`, `DisasterDeclarationsSummaries`, USGS gage IV) | data |
| 3a | **Transform** | a build script or in-browser join (`build_county_map.py`, `enrich.py`, `applyNfip()`) | **process** |
| 3b | **Artifact** | a committed output (`disasters.json`, `county_declarations.json`) | data |
| 1 | **Surface** | a UI view/widget (Ledger, Geography, Watch, Timelines, Newsreel, Estimate) | data (consumer) |

Tier 3 is **two alternating node types**: a Transform *writes* an Artifact, which a
Surface (or another Transform) *reads*. Transforms carry a `runtime` flag:
**`offline`** (runs in GitHub Actions / by hand) vs **`browser`** (runs at page load,
e.g. `applyNfip()`). This flag is load-bearing for health and refresh (§5, §6).

---

## 3. The manifest (`data/lineage.json`) — OpenLineage-shaped, but ours

Structure is **auto-derived** from code where possible (§4); prose is hand-authored;
the whole thing is **CI-verified against reality** (§5). Decision rationale in §8.

```jsonc
{
  "generatedAt": "ISO8601",
  "providers": [
    { "id": "openfema", "name": "OpenFEMA", "links": ["https://www.fema.gov/about/openfema/api"] }
  ],
  "sources": [
    {
      "id": "femaWebDisasterSummaries",
      "providerId": "openfema",
      "name": "FemaWebDisasterSummaries",
      "endpoint": "https://www.fema.gov/api/open/v1/FemaWebDisasterSummaries",
      "binding": "snapshot",            // live | snapshot | hybrid  (see §5 active-vs-last-pull)
      "cadence": "daily",               // from the source's accrualPeriodicity
      "columnsUsed": ["disasterNumber","totalAmountIhpApproved", "..."],
      "dictionary": "docs/openfema-definitions/FemaWebDisasterSummaries.json", // → columnsUnused computed
      "links": ["..."]
    }
  ],
  "transforms": [
    {
      "id": "build_county_map",
      "name": "scripts/build_county_map.py",
      "runtime": "offline",
      "schedule": ".github/workflows/refresh-... (or 'manual')",
      "method": "OpenFEMA pull + county FIPS join (pandas)",
      "reads": ["publicAssistanceFundedProjectsDetails", "..."],
      "writes": ["county_declarations.json"],
      "links": ["scripts/build_county_map.py"]
    }
  ],
  "artifacts": [
    {
      "id": "county_declarations.json",
      "name": "data/county_declarations.json",
      "producedBy": "build_county_map",     // + downstream enrichers (multi-producer ok)
      "freshnessFrom": "manifest.json:county_declarations.json", // dataAsOf + sourceCadence
      "links": ["data/county_declarations.json"]
    }
  ],
  "surfaces": [
    {
      "id": "geography",
      "name": "Geography view",
      "location": "index.html#view-geography",   // deep-link/anchor back into the app
      "reads": ["county_declarations.json","nfip.json","disaster_county_ihp.json"],
      "description": "Program-first county/state choropleth + measure-driven timeline.",
      "links": ["index.html"]
    }
  ]
}
```

Edges are *implicit*: `provider⊃source`; `transform.reads/writes`; `surface.reads`.
The renderer derives the DAG from these. Multi-producer / multi-consumer is
first-class (it's a DAG, not a tree — §7).

---

## 4. Auto-derivation (`scripts/build_lineage.py`) — keep hands off the structure

Hand-maintaining the structure is the thing we're trying to *kill*, so most of it is
machine-derived and only the prose is hand-written:

- **Artifacts** ← `ls data/*.json`. Freshness (bytes/`dataAsOf`/`sourceCadence`) is
  **NOT** baked into the committed manifest — it's volatile (changes every refresh) and
  is joined live from `data/manifest.json` at render time (§5a). Keeping `lineage.json`
  structural-only makes it deterministic, so the `--check` staleness gate is stable even
  on a PR merged against a freshly-refreshed `main`.
- **Transforms `writes`** ← scan `scripts/*.py` for the output filename(s) they write.
- **Transforms `reads`** ← scan scripts for known OpenFEMA dataset names (regex over
  the endpoint catalog) and for input filenames they open.
- **Surfaces `reads`** ← scan `index.html` for `fetch("data/<file>.json")` and the
  enclosing render function (= which Surface consumes it).
- **Sources `columnsUsed`** ← (best-effort) fields referenced near each dataset call;
  **`columnsUnused`** = dictionary columns (`docs/openfema-definitions/`) − used.
- **Browser transforms** (e.g. `applyNfip()`) ← curated list of in-page join fns +
  the artifacts they merge.

Hand-authored, never auto-clobbered: `description`, `method`, human `links`, and any
column mapping the scanner can't infer. The build step **merges** new auto-structure
with retained prose (keyed by node id).

---

## 5. Health & status model — including **active vs last pull**

Health is **computed at render time**, never hand-stored. Three independent signals,
because "is it healthy?" means different things at different tiers:

### 5a. Snapshot freshness (we already have the inputs)
For every **Artifact**: compare `data/manifest.json` `dataAsOf` vs `sourceCadence`.
→ `fresh` (within cadence) · `aging` (1–2× cadence) · `stale` (≫ cadence) ·
`unknown` (no `dataAsOf`). This is nearly free today.

### 5b. Last-pull / refresh-job status (the "offline outage" signal)
For **offline Transforms**: the **last GitHub Actions refresh run result**
(success / fail / last-run time) is the honest "is the source down" signal, because
OpenFEMA pulls fail *in CI*, not in the user's browser. A failed last run → red.

### 5c. Active (live) pull status — **the owner's explicit requirement**
Every **data node** carries a **`provenanceMode`** describing *what the user is
actually looking at right now*:

- **`LIVE`** — value fetched live this session (NWS alerts, USGS gage heights).
  Health = *this session's fetch result*. Card shows "LIVE · fetched 8s ago · OK".
- **`SNAPSHOT`** — value from the committed pull. Health = 5a freshness + 5b last-run.
  Card shows "SNAPSHOT from 2026-06-25 · cadence monthly · fresh · last CI pull OK".
- **`HYBRID`** — snapshot by default, live-refreshable (e.g. `recent.json` short
  windows; live PA county Summaries). Card shows **both**: which is *currently
  active*, the snapshot's freshness, **and** the last live fetch's outcome.

So a node answers two questions distinctly: **"is the underlying data current?"
(last pull)** and **"is what I'm showing live or cached right now?" (active)**. That
distinction is a first-class field, surfaced on every card and color-codeable.

### 5d. Propagation (the red line)
A node's *effective* status = worst of (its own status, its inputs' effective
status), with **partial** states preserved: a Surface reading 3 artifacts where 1 is
stale renders **"partially stale"** (amber, with the culprit edge highlighted), not
fully red. Clicking any degraded node lights its **downstream cone** (impact) and
**upstream cone** (root cause).

Color legend (draft): `fresh` green · `aging` yellow · `partial` amber ·
`stale`/`failed` red · `deprecated` grey · `unknown` hatched.

---

## 6. The Guardian (`scripts/verify_lineage.py`) — **built first, the real product**

A lineage tool that lies is worse than none. The verifier is what keeps the manifest
matched to reality and is therefore Phase 0. Offline, no network. It **exits nonzero
(fails CI)** on any mismatch:

- Every Artifact node → file exists in `data/`; `producedBy` Transform exists.
- Every committed `data/*.json` → has an Artifact node (**no orphan artifacts**).
- Every Transform node → script exists in `scripts/` (or is a named browser fn in
  `index.html`); its declared `writes` filename actually appears in the script; its
  declared OpenFEMA `reads` datasets appear in the script.
- Every Surface `reads` → that JSON is actually `fetch()`-ed in `index.html`.
- Every `fetch("data/*.json")` in `index.html` → covered by some Surface edge
  (**no untracked consumption**).
- Every Source `columnsUsed` ⊆ dictionary columns; emit `columnsUnused`.

**Placement (decided):** the Guardian is **bolted onto the existing refresh workflows
— it runs *after* a refresh finishes** (a refresh that changes the data web must be
re-verified immediately), **and** it is **independently runnable** as its own
standalone workflow / `python3 scripts/verify_lineage.py` for local + on-demand checks.
**Both results surface in the Lineage view** (a "manifest verified · <date>" badge,
red if the last Guardian run failed). **Acceptance proof: deliberately break one edge →
CI goes red.** This is the anti-AI-slop guardrail.

---

## 7. Rendering — hand-rolled tiered SVG, separate lazy page

- **Lives in its own file `lineage.html`** reading `data/lineage.json` — keeps the
  mobile hot path (`index.html`) light; room to grow into a big graph. Links back
  into the app via Surface `location` anchors.
- **Tiered columns left→right:** Provider · Source · Transform · Artifact · Surface
  (upstream-left / downstream-right, matching dbt and the owner's mental model).
- **No graph library** (honors the no-build, zero-dependency ethos). Hand-drawn
  SVG/Canvas; our own focus logic.
- **It's a DAG, not a tree** (many-to-many). Therefore: **never render everything at
  once.** Default to a readable overview; **focus mode** on click (dim everything
  except the selected node's up/down cone); filters by tier and by program
  (PA/IA/HMGP/Non-disaster/NFIP); collapse/expand groups.
- **Cards** on each node: summary, link to actual location, data sources, last
  updated, update schedule, update method, health (5a–5c), and — for Sources —
  columns used vs **unused** (§ Phase 3).
- Star-Trek polish (glow, animated impact lines) is a *finish*, applied after the
  data and focus logic are correct.

---

## 8. Decisions log (the four forks)

1. **Manifest truth source → auto-derived structure + hand-authored prose, CI-verified.**
   Pure hand-authoring drifts (the exact failure we're preventing); pure auto can't
   write good descriptions. So: scanner derives edges, humans write prose, Guardian
   forbids contradictions. (Owner endorsed "boring guardian first.")
2. **v1 granularity → dataset/file-level.** Column-level is a harder class (manual
   annotation + fragile static analysis); it's Phase 3, not v1.
3. **Placement → separate lazy-loaded `lineage.html` + `data/lineage.json`.** Keeps
   the mobile hot path clean.
4. **Rendering → hand-rolled tiered SVG, zero dependencies.**

---

## 9. Scope guard — "deferred but DO NOT DROP"

These are **not cut**. They are sequenced after v1 and recorded here so they get
built, not forgotten. When a phase lands, revisit this list.

| # | Deferred feature | Trigger to build | Notes / landmines |
|---|---|---|---|
| D1 | ~~**Column-level lineage UI**~~ **v1 SHIPPED (Phase 3)** — click a source field → consuming transforms → surfaces it reaches; "available but unused" list; "declared-used-but-not-found-in-any-script" slop flag. Derived by grounded script-scan (`column_in` in `build_lineage.py`), deterministic. | — | Remaining: column tracing through *live* sources (index.html scan), and per-output-field propagation past a transform (currently column→transform→all that transform's outputs). |
| D2 | **Code/visual export** — emit a portable bundle so a user can reproduce a Surface in **Power BI** (priority), a website, SharePoint, Databricks | after Phases 2–3 | **Semantic-mismatch trap:** pandas→JSON does NOT port to DAX/M. Realistically exportable = the **source query (OpenFEMA REST URL + columns)** + a **visual spec**, NOT the transform logic. Label honestly. |
| D3 | **Manual refresh from the UI** — whole or per-source, showing timing/method/ramifications | after Phase 4 | **Backend-shaped:** a public static page can only re-pull the *live-fetchable* sources; committed-JSON refresh needs a GitHub Action trigger (token — can't be a public button) or the Cloudflare worker path. |
| D4 | **Change diff** — "what changed since last refresh" | after D3 | Requires storing snapshots/history (data-retention design). |
| D5 | **Time-travel / lineage history** | later | Versioned manifests. |
| D6 | ~~**Generalized spec / skill**~~ **SHIPPED** — `docs/lineage-spec.md` is the portable spec (what it does, full feature inventory, the Guardian's complete check list, health model, porting guide + build order); `docs/lineage-discovery-prompt.md` remains the process-reproducing prompt (Goal #4) | — | OpenLineage-shaped model is what makes it generalize. |
| D7 | **Live API health probes everywhere** | Phase 4 | Only the browser-fetched sources (NWS/USGS/short recent) can be truly probed client-side. |
| D8 | **Refresh-failure alerting** | with D3 | Ties into the existing best-effort refresh workflows (see `docs/refresh-architecture.md`). |
| D9 | **Split the seed into per-domain fragments** (`data/lineage.seed.d/*.json`, merged by `build_lineage.py`) | when seed collisions between parallel sessions become frequent | Lets sessions on different features (denials vs PA vs NFIP) edit DIFFERENT files → no merge conflict. Until then: the append-only + rebase protocol (CLAUDE.md) + the Guardian backstop keep parallel work safe; collisions are trivial JSON-array merges. |

---

## 10. Phased roadmap (each phase ships something verifiable)

> Anti-dwindle rule: a phase is **done** only when its acceptance check passes. No
> phase is "mostly done." Deferred work goes to §9, never silently dropped.

- **Phase 0 — Schema + scaffold + Guardian (no UI).**
  Deliver: `data/lineage.json` schema (§3), `scripts/build_lineage.py` (§4),
  `scripts/verify_lineage.py` (§6), CI wiring.
  **Accept:** deliberately break one edge → CI red; fix → green.

- **Phase 1 — Health model (data only).**
  Deliver: freshness (5a) + last-CI-run (5b) + `provenanceMode` active-vs-snapshot
  (5c) computed into `lineage.json`.
  **Accept:** an artificially-staled file reports `stale`; a `HYBRID` node shows both
  states.

- **Phase 2 — The visual.**
  Deliver: `lineage.html` tiered SVG DAG, node cards, focus mode, impact propagation
  (§5d, §7).
  **Accept:** click a degraded Source → its downstream cone lights red/amber;
  unrelated nodes dim.

- **Phase 3 — Column layer (D1).** used vs unused per Source; (stretch) column→Surface
  highlight.

- **Phase 4 — Live health probes (D7) + true active/last-pull display.**

- **Phase 5+ — Deferred registry (§9): D2 export, D3 manual refresh, D4 diff, D6 spec.**

---

## 11. Open questions

**Resolved (owner, 2026-06-26):**
- **In-browser joins (`applyNfip()` etc.) DO get their own Transform nodes**
  (`runtime: browser`). "Show them; we can always hide later."
- **Guardian placement:** bolted onto the refresh workflows (runs *after* a refresh)
  **and** independently runnable; both run results surface in the Lineage view. (§6)

**Still open (resolve as we go):**
- Exact color thresholds for `aging` vs `stale` (multiple of cadence?).
- How aggressively to deep-link Surface `location` back into `index.html` (anchors
  exist per view; per-widget anchors may need adding).
```
