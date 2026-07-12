# The Provenance Atlas — a portable specification

**A data-lineage chart + CI Guardian for any repo with a tangled data web.**

This is the generalized spec promised by `docs/lineage-plan.md` §9-D6: a complete,
self-contained description of the data lineage feature built in this repo
(DisasterParameters), written so it can be handed to a session in **any other
repository** and rebuilt there. It covers what the feature does, **every feature
it ships**, and the **Guardian** — the CI verifier that is the real product.

Companion documents in this repo:
- `docs/lineage-plan.md` — the living plan/decision log for *this* repo's instance.
- `docs/lineage-discovery-prompt.md` — a paste-into-a-fresh-session prompt that
  reproduces the *discovery + build-vs-adopt + planning conversation*. Use that when
  you want the process; use **this** spec when you want the finished design.

Reference implementation (all in this repo, ~1,000 lines total, zero dependencies
beyond Python 3 + a browser):

| Piece | File | Role |
|---|---|---|
| Seed | `data/lineage.seed.json` | hand-authored truth (the only file humans edit) |
| Builder | `scripts/build_lineage.py` | derives + assembles the manifest |
| Manifest | `data/lineage.json` | build artifact — the data behind the chart |
| **Guardian** | `scripts/verify_lineage.py` | CI verifier; fails red on any lie |
| Renderer | `lineage.html` | the chart — single-file, no framework, hand-rolled SVG |
| Freshness | `data/manifest.json` (via `scripts/build_manifest.py`) | per-file `dataAsOf` + cadence, joined at render time |
| CI | `.github/workflows/verify-lineage.yml` + a step at the end of every refresh workflow | the gate |

---

## 1. What it does (product statement)

The Provenance Atlas is an interactive chart that maps a repository's **entire data
web** — every external source → every transform/build step → every committed/built
artifact → every UI surface or report that end users actually see — so that:

1. **Anyone can trace any figure on screen back to its origin** (source → screen),
   end to end, with links to the real endpoint, script, file, and view at every hop.
2. **Staleness and outages trace FORWARD to everything they impact**: a failing
   pull or stale snapshot red-lines its whole downstream cone — every affected
   transform, artifact, and surface — the "blast radius" view.
3. **The chart cannot lie.** Its structure is machine-derived from the code where
   possible and CI-verified against the code everywhere (the Guardian). If the
   documented data web and the actual code disagree, CI goes red — the mismatch is
   never silently shipped.

It is deliberately buildable in a **no-framework, no-build, statically-served**
repo: plain JSON + plain Python + one self-contained HTML page. It borrows its
data model from the mature lineage ecosystem (OpenLineage's datasets-vs-jobs node
model, dbt's sources → models → **exposures** tiering, DataHub/Marquez-style
column-level tracing and impact propagation) without adopting any of those
platforms — see §12 for when you should adopt one instead.

## 2. Design principles (the parts that make it work)

These are load-bearing. A port that drops any of them will produce a lineage chart
that rots.

1. **The drift paradox — the central problem.** A hand-maintained lineage doc is
   itself prone to rot and to the very sloppiness it's meant to catch. Therefore:
   **structure is machine-derived and/or CI-verified; only prose is hand-written.**
   A lineage tool that lies is worse than none.
2. **The trust paradox — the Guardian is the real product.** The pretty graph is
   the demo. Build the verifier *first* (Phase 0), and prove it with an acceptance
   test: *deliberately break one edge → CI goes red; fix it → green.*
3. **Two node kinds only** (from OpenLineage): **data nodes** hold data, **process
   nodes** transform it. Edges always flow `data → process → data`. This dissolves
   most confusion about "the middle" of a pipeline.
4. **It's a DAG, not a tree.** Many-to-many everywhere (one artifact feeds many
   surfaces; one surface reads many artifacts). Never render everything at full
   emphasis — require focus/isolate/filter interactions.
5. **"Stale" and "down" are different signals**, knowable in different places:
   snapshot freshness is computable from committed metadata; offline pull failure
   is only knowable from CI/job status; live-API health is only knowable where the
   app actually fetches live. Model all three separately (§7).
6. **Structural manifest, volatile freshness.** Freshness (bytes, data-as-of,
   cadence) is NOT baked into the committed lineage manifest — it changes on every
   refresh and would churn the file and break the staleness gate. It lives in a
   separate freshness manifest and is **joined live at render time**. The lineage
   manifest is therefore **deterministic** given the seed + the file list, which is
   what makes `--check` a stable CI gate.
7. **Keep the hot path light.** The chart lives on its own lazily-loaded page, not
   in the main app bundle.
8. **Record age ≠ staleness.** Only files refreshed by an *automated pipeline*
   carry a staleness clock (for them, data-as-of = last successful pull, so lagging
   means the pull is failing). Manually-built snapshots and reference data render
   as a neutral "covers through …" state — a quiet news/disaster/data season must
   not turn the ledger red.
9. **Anti-dwindle.** Every deferred feature is recorded in a "deferred but do NOT
   drop" registry with a build trigger and its landmine (§11). Scope never quietly
   shrinks.

## 3. Terminology and the node model

Name the whole feature something sober ("the Lineage view") with an optional brand
("Provenance Atlas"). The five tiers, upstream → downstream, rendered left → right:

| Tier | Name | What it is | Node kind |
|---|---|---|---|
| 1 | **Provider** | an external organization/origin (OpenFEMA, USGS, NWS, a vendor) | data (origin) |
| 2 | **Source** | a specific dataset/endpoint/table + its columns | data |
| 3 | **Transform** | a build script, SQL model, ETL job, or in-app join function | **process** |
| 4 | **Artifact** | a committed/built output (a JSON file, a table, a cache) | data |
| 5 | **Surface** | a UI view/widget/report/API response end users actually see | data (consumer) |

Notes:
- Transforms carry a **`runtime`** flag: `offline` (batch/CI/scheduled/by hand) vs
  `browser` (runs at request/render time, e.g. an in-page join function). This flag
  is load-bearing for the health model — offline transforms are healthy/unhealthy
  per their **last CI run**; browser transforms per **this session's fetch**.
- Transforms can read Sources *or* Artifacts (chained pipelines), and Artifacts can
  have **multiple producers** (a base builder plus additive enrichers) — model
  `producedBy` as a list.
- Surfaces read Artifacts (committed snapshots) and/or Sources directly (live
  fetches). A live Source wired straight to a Surface is a first-class edge, not an
  orphan.
- Edges are **implicit** in the node fields (`provider⊃source`, `transform.reads/
  writes`, `surface.reads`); the renderer derives the DAG. There is no separate
  edge list to hand-maintain.

## 4. The manifest (`lineage.json`) — schema

The committed build artifact the renderer reads. Schema-stamped
(`"schema": "provenance-atlas/1"`), with a note declaring it a build artifact.

```jsonc
{
  "schema": "provenance-atlas/1",
  "note": "BUILD ARTIFACT — regenerate with build_lineage.py; do not hand-edit. Verified by verify_lineage.py.",
  "providers": [
    { "id": "openfema", "name": "OpenFEMA", "links": ["https://…"] }
  ],
  "sources": [
    {
      "id": "femaWebDisasterSummaries",
      "providerId": "openfema",
      "name": "FemaWebDisasterSummaries",          // the real dataset name (greppable in scripts)
      "endpoint": "https://…/FemaWebDisasterSummaries",
      "binding": "snapshot",                        // live | snapshot | hybrid  (§7c)
      "cadence": "daily",                           // the SOURCE's own update cadence
      "dictionary": "docs/…/FemaWebDisasterSummaries.json",  // optional field dictionary
      "columnsUsed": ["disasterNumber", "totalAmountIhpApproved"],
      "columnsUnused": ["…"],                       // COMPUTED: dictionary − used
      "columnUsage": { "disasterNumber": ["build_x", "watch"] },  // COMPUTED: col → consumer ids
      "columnsDeclaredUnfound": ["…"],              // COMPUTED: claimed used, found nowhere (slop flag)
      "description": "…", "links": ["…"]
    }
  ],
  "transforms": [
    {
      "id": "build_county_map",
      "name": "scripts/build_county_map.py",        // a file path, OR a browser fn name like "applyNfip()"
      "runtime": "offline",                         // offline | browser
      "schedule": ".github/workflows/refresh-daily.yml",  // or "manual"
      "method": "OpenFEMA pull + county FIPS join (pandas)",
      "reads":  ["publicAssistanceFundedProjectsDetails", "disasters.json"],  // source AND/OR artifact ids
      "writes": ["county_declarations.json"],
      "description": "…", "links": ["…"]
    }
  ],
  "artifacts": [
    {
      "id": "county_declarations.json",
      "name": "data/county_declarations.json",
      "freshnessFrom": "data/manifest.json",        // pointer only — freshness joined at render time
      "producedBy": ["build_county_map", "build_county_ihp"],  // COMPUTED from transforms.writes
      "deprecated": false,
      "description": "…", "links": ["…"]
    }
  ],
  "surfaces": [
    {
      "id": "geography",
      "name": "Geography view",
      "location": "index.html#view-geography",      // deep link back into the app; page part drives verification
      "reads": ["county_declarations.json", "nfip.json", "nwsAlerts"],  // artifact AND/OR live-source ids
      "description": "…", "links": ["…"]
    }
  ]
}
```

Hard rules:
- **Never hand-edit the manifest.** It is deterministic output of the builder.
- **No volatile fields** (no `generatedAt`, no freshness, no byte counts). Same
  inputs → byte-identical output → `--check` works.

## 5. The seed — the only hand-edited file

`lineage.seed.json` carries what a scanner can't reliably infer: the provider list,
source→provider mapping, endpoints, binding/cadence, `columnsUsed` intent, each
transform's reads/writes declaration, surface reads, and all human prose
(`description`, `method`, curated `links`). Same shape as the manifest minus every
COMPUTED field, plus one difference:

- **`artifacts` in the seed is a map of prose overrides only**
  (`{"<file>": {"description", "deprecated", "links"}}`). The artifact *list* is
  never hand-authored — it is enumerated from the real files on disk, so a new
  committed data file automatically becomes a node (and, unseeded, a Guardian
  error, which forces documentation).

**Multi-session / multi-author safety** (many parallel branches edit data + seed):
1. Rebase on the default branch right before touching the seed.
2. Edit **append-only** — add new nodes at the END of the relevant array; never
   reformat the file. (The builder owns all formatting of the output.)
3. If two branches collide on the seed anyway, it's a trivial JSON-array merge:
   keep both sides' nodes, re-run the builder, re-run the Guardian.
4. The Guardian is the backstop: any wiring mistake becomes a visible red CI check
   at PR time, never silently-bad data. Worst case is a resolvable conflict, not
   corruption.
5. If seed collisions become frequent, split the seed into per-domain fragments
   (`lineage.seed.d/*.json`, merged by the builder) — deferred until needed.

## 6. The builder (`build_lineage.py`) — auto-derivation

Offline, no network, deterministic. Responsibilities:

1. **Enumerate artifacts** from the real data directory (`data/*.json` here).
   Exclusions that keep the output deterministic:
   - the lineage feature's own files (`lineage.json`, `lineage.seed.json`);
   - **uncommitted regenerable caches/intermediates** — this repo uses a
     `_`-prefix filename convention (`data/_*.json` is gitignored); a port can
     instead enumerate `git ls-files` so the manifest never depends on whatever
     caches a build script happened to leave locally. Without this, a clean CI
     checkout regenerates a *different* manifest and `--check` fails though
     nothing real drifted.
2. **Merge seed prose onto derived structure**, keyed by node id. Auto-derived
   structure never clobbers hand prose; hand prose never invents structure.
3. **Back-fill `producedBy`** on each artifact from every transform whose `writes`
   names it (multi-producer aware).
4. **Compute `columnsUnused`** per source: parse the committed field dictionary
   (tolerant walk collecting `name` fields at any depth — dictionary shapes vary),
   subtract `columnsUsed` (case-insensitive).
5. **Compute `columnUsage` (column-level lineage, grounded in code).** For each
   declared-used column of a source, grep every *consuming* transform's script for
   a **grounded** reference — the column as a quoted string, attribute access, or
   bracket access (`re.search(r'''["'.\[]''' + escape(col) + r"\b")`), not
   incidental prose. For **live/direct sources** (surface reads the source with no
   offline transform in between), scan the surface's page (`index.html`) the same
   way and attribute the column to the surface itself.
6. **Flag `columnsDeclaredUnfound`**: a column claimed used but found in *no*
   consuming script/page — only flagged when at least one consumer exists to scan.
   This is the "slop / stale mapping" signal, surfaced in the UI in orange.
7. **`--check` mode**: rebuild in memory, byte-compare against the committed
   manifest, exit nonzero with a "run the builder and commit" message on drift.
   This is CI step 1; the Guardian is step 2.

## 7. Health & freshness model — computed at render time, never stored

Three independent signals, because "is it healthy?" means different things at
different tiers. All computed in the renderer from live joins; nothing is baked in.

### 7a. Snapshot freshness (artifacts)
Join each artifact to the freshness manifest (`manifest.json`: per-file `bytes`,
`dataAsOf` = covers-through date, `sourceCadence`). Then — the critical split:

- **Automated-pipeline artifacts** (some producing transform's `schedule` is one of
  the known refresh workflows): `dataAsOf` is the **last successful pull**, so it
  carries a real staleness clock:
  - `fresh` — age ≤ cadence + max(cadence, 7 days) of slack;
  - `aging` — age ≤ 5× cadence ("pipeline behind schedule");
  - `stale` — beyond that ("pipeline not refreshing — pull may be failing").
- **Everything else** (manually-built snapshots, reference/geometry data):
  **`static`** — rendered as a neutral cyan "snapshot / covers through … (no
  automated pull)" state, *never* amber/red on age alone.
- **`unknown`** — no freshness metadata at all (hatched in the legend).

### 7b. Last-pull / refresh-job status (offline transforms) — "Pipeline health"
For offline transforms scheduled by CI, the honest "is the source down" signal is
the **last CI run result**, because pulls fail in CI, not in the user's browser.
The renderer fetches each refresh workflow's most recent run from the public
GitHub Actions REST API (CORS-open, no token for public repos):
`GET /repos/{owner}/{repo}/actions/workflows/{file}/runs?branch=main&per_page=1`,
cached in `sessionStorage` for 5 minutes. Any conclusion other than
`success`/`skipped` marks that pipeline failed.

### 7c. Active vs last-pull (`binding` / provenance mode) — data nodes
Every source declares what the user is *actually looking at right now*:
- **`live`** — fetched in-browser this session (alerts, gage heights). Health =
  this session's fetch result.
- **`snapshot`** — a committed pull. Health = 7a freshness + 7b last run.
- **`hybrid`** — snapshot by default, live-refreshable. Shows **both**: which is
  currently active, the snapshot's freshness, and the last live fetch's outcome.

A node thereby answers two questions distinctly: *"is the underlying data
current?"* (last pull) and *"is what I'm seeing live or cached right now?"*
(active).

### 7d. Propagation — the red line
- A **surface's** effective health = **worst of its inputs'** health
  (rank: fresh/static < unknown < aging < stale), labeled "(worst of inputs)".
  Partial degradation stays partial — one stale input of three renders the surface
  amber/degraded with the culprit edge highlightable, not fully red.
- In **Pipeline-health mode**, each failed pipeline's transform node and its whole
  **downstream cone** (artifacts → surfaces) get the outage treatment: red node
  outline + red **animated dashed** edges (`stroke-dasharray` + keyframed
  `stroke-dashoffset` — the marching-ants "red line"), and every surface in the
  cone is listed as "at risk" in a banner.
- Clicking any node lights its **upstream cone (root cause)** and **downstream
  cone (impact)** simultaneously.

Color legend: `fresh` green · `aging` gold · `stale`/failed red · `static`
(snapshot) cyan · `unknown` hatched grey · node-kind colors on the border,
health color on a left stripe.

## 8. The Guardian (`verify_lineage.py`) — the real product

Offline, no network. Checks the **built manifest against the real repo** and exits
nonzero on any mismatch, so CI goes red the moment the documented data web and the
actual code disagree. Two severities: **errors** (always fail) and **warnings**
(fail only under `--strict`). The full check inventory:

**Artifacts**
- Every artifact node's file exists on disk.
- **NO ORPHAN ARTIFACTS**: every committed data file has an artifact node. (Skips
  the same uncommitted-cache convention as the builder — keep the two exclusion
  rules in sync.) Adding a data file without documenting it = red CI, by design.
- Every artifact has ≥ 1 `producedBy` transform (unless marked `deprecated`) —
  forces the producing edge to stay documented.

**Transforms**
- A script-path transform's file exists; a **browser-function** transform's
  identifier (name minus the `()`) actually appears in the app page.
- Every `writes`/`reads` id resolves to a real node (no dangling edges).
- An offline transform's declared output **filename literally appears in its
  script** — the cheapest possible "does this script really write that file" check,
  and remarkably effective.
- *(warning)* A declared source-read is corroborated: the source's dataset name
  **or its endpoint host** appears in the script (some scripts hit sources by URL,
  and some reach them indirectly via a cached intermediate — hence warning, not
  error).

**Surfaces**
- Every `reads` id resolves.
- Every artifact a surface declares is **actually fetched in that surface's own
  page**. The check resolves the page from the surface's `location` (`planner.html`,
  `lineage.html`, … falling back to the main page) — a standalone page's reads must
  not pass merely because the main page happens to fetch the same file.
- **NO UNTRACKED CONSUMPTION**: every `fetch("data/*.json")` found in every
  surface-bearing page is declared by some surface *on that page*. Adding a data
  fetch to the app without wiring the lineage = red CI, by design. (The fetch
  regex — `fetch\(\s*["'`]data/([\w.]+\.json)` here — is the main thing a port
  adapts: point it at your data-access idiom.)

**Sources**
- `providerId` resolves.
- **`columnsUsed` ⊆ the field dictionary's columns** — catches typo'd or
  hallucinated field names against the source's own published schema.
  *(warning)* dictionary file missing.

**Report format:** prints every `WARN`/`FAIL` line, then a one-line census
(`N providers · N sources · N transforms · N artifacts · N surfaces`), then
`GUARDIAN: PASS/FAIL`. Human-scannable in a CI log.

**Placement (both, deliberately):**
1. A **standalone workflow** triggered on push/PR touching anything that could
   desync the web (data files, scripts, the app pages, the dictionaries, the
   workflow itself) + manual dispatch. Two steps: `build_lineage.py --check` (the
   committed manifest is current), then `verify_lineage.py` (the manifest matches
   reality).
2. **Bolted onto the end of every scheduled refresh workflow**, before the
   auto-commit — a refresh that changes the data web is re-verified immediately,
   and a refresh that would produce an undocumented file never lands.

Both results surface **in the chart itself**: the Pipeline-health check also
fetches the Guardian workflow's last run and renders a "✓ manifest verified" /
"✗ guardian failed" badge in the masthead.

**Acceptance proof (non-negotiable for a port):** deliberately break one edge —
rename a fetch, delete a seed node, typo a column — and watch CI go red; fix it
and watch it go green. If that test doesn't pass, you have a diagram, not a
lineage tool.

## 9. The renderer (`lineage.html`) — complete feature inventory

One self-contained HTML page (inline CSS + vanilla JS, no libraries, no build),
lazily loaded, linking back to the app. Fetches the lineage manifest + the
freshness manifest in parallel and joins them in memory. Everything below ships in
the reference implementation:

### Graph
- **Tiered columns left→right** (Provider · Source · Transform · Artifact ·
  Surface), each with a column header; upstream-left/downstream-right.
- **Hand-rolled SVG**: nodes are rounded rects with the node-kind color as border,
  a 5px **health stripe** (health color if the node has health, else kind color),
  and a truncated label (basename for transforms/artifacts). Bézier-curved edges.
- **Barycenter crossing-reduction layout**: 6 alternating down/up sweeps ordering
  each column by the mean position of its neighbors in the adjacent column,
  computed over the **currently visible subgraph** (so filtering re-untangles).
- **Responsive**: column/node widths shrink below 760px; re-layout on resize
  (debounced); the page falls to a single column on narrow screens; the graph pane
  scrolls independently.

### Interaction
- **Click a node → focus mode**: its upstream cone (root cause) + downstream cone
  (impact) stay lit; everything else dims to near-invisible; on-path edges turn
  gold ("hot"), and — if the selected node is stale — its *downstream* hot edges
  turn red. Click empty canvas to clear.
- **Detail card** (sticky side panel) for the selected node — see below.
- **Isolate**: hides everything outside the selected node's dependency cone
  (up + down), and the layout recomputes for just that subgraph.
- **Trace a UI surface…** dropdown: pick any surface → auto-select + isolate its
  full dependency chain (the "where does this screen come from" one-gesture answer).
- **Search** box: incremental find by label/id; first hit is selected, focused,
  and scrolled into view.
- **Program/domain filter chips**: display-only grouping of nodes into domains
  (here: PA / IA-IHP / Mitigation / NFIP / Preparedness / Declarations / Hazards /
  Core) by a prioritized regex heuristic over `id + name + description`. Toggling
  chips hides whole domains; providers always stay. Each node's card shows its
  group. *Explicitly labeled a display heuristic — never used for verification.*
- **Reset** restores all filters, selection, isolation, and the URL hash.
- **Deep links**: `lineage.html#<kind>:<id>` (e.g. `#artifact:nfip.json`)
  pre-selects and focuses that node on load; chips/banners update selection and
  scroll the node into view.
- **Node count readout** ("34 of 78 nodes · isolated").

### Detail cards (per node kind)
Every card: kind tag, name, hand-written description, program chip, and
**Upstream/Downstream cone sizes**. All references are clickable **chips that
navigate the graph** (select + focus + scroll). Plus per kind:
- **Provider**: links; chips of its datasets (sources).
- **Source**: provider chip; **binding** (live / snapshot / hybrid, explained);
  cadence; endpoint link; **columns-used chips** (see column tracing below);
  **"Unverified" row** listing `columnsDeclaredUnfound` in orange;
  **"Not used" disclosure** — the computed available-but-unused column list
  (two-column layout); dictionary link.
- **Transform**: runtime (offline/CI vs browser/page-load); schedule (workflow
  basename); **live pipeline status row** when Pipeline-health data is loaded
  (conclusion + link to the actual run); method (one-line "how"); reads/writes
  chips; link to the script source.
- **Artifact**: **freshness status line** (FRESH/AGING/STALE/STATIC/UNKNOWN with
  the human-readable basis string, e.g. "refreshed 2026-07-11 · daily" or "covers
  through 2026-06-25 — manual snapshot"); file size from the freshness manifest;
  **Built by** chips (multi-producer); **Read by** chips (consuming surfaces);
  link to the file.
- **Surface**: health (worst-of-inputs, labeled as such); **location deep link
  back into the app**; reads chips.

### Column-level tracing (Phase 3)
- Each source's used columns render as chips; columns in
  `columnsDeclaredUnfound` render **orange** ("declared used but not found in any
  consuming script — click to verify").
- **Click a column chip** → the graph highlights exactly that field's path:
  the source + the transforms whose scripts actually reference it (+ the surfaces
  those transforms' outputs reach), or — for live sources — straight to the
  surfaces that read the field in-page ("read live"). A field-trace readout under
  the chips summarizes "*col* → N transform(s) → M surface(s)" with clickable
  chips; clicking the active chip again clears the trace.
- A column with **no** consumer found shows a "candidate slop / stale mapping"
  callout instead of a trace.
- Known limitation (recorded, not hidden): propagation past a transform is
  transform-granular (column → transform → *all* that transform's outputs), not
  per-output-field.

### Pipeline health / outage mode ("⚡ Pipeline health")
- On toggle: fetches the last run of **every scheduled refresh workflow** + the
  Guardian workflow from the public GitHub Actions API (per-file, parallel,
  5-minute sessionStorage cache; graceful "couldn't reach the API" warning banner
  when rate-limited/offline).
- Failures compute the outage set: the failed pipelines' transforms + their full
  downstream cones. Those nodes get red outlines; in-cone edges become **red
  animated dashed lines** (the marching red line); at-risk surfaces are collected.
- **Banner**: red — "⚠ N pipeline(s) failing → M surface(s) at risk" with
  clickable surface chips + a link to each failing run; green — "✓ All N automated
  pipelines healthy," with the honest caveat that manual/weekly builders aren't
  auto-checked, and a note if any status fetch itself failed.
- **Guardian badge** in the masthead: "✓ manifest verified" green pill (or
  "✗ guardian <conclusion>" red) from the Guardian workflow's last run.
- Transform cards gain the live last-run row while mode is on. Toggle off restores
  the normal view.

### Chrome
- Masthead (title, schema stamp, verified badge, back-link into the app), sticky
  toolbar (health legend · search · trace dropdown · Isolate · Reset · Pipeline
  health · node count), program-chip row, footer with the provenance of the
  lineage itself (built by the builder, verified by the Guardian, freshness joined
  live) and any required non-endorsement disclaimers.
- **Overview panel** (no selection): usage hints + an artifact-health census
  (N fresh · N aging · N stale · N snapshot · N no-date) + a plain-language
  explanation of the staleness semantics (only automated pipelines alarm).
- **Failure state**: if the manifest can't load (opened as `file://`), the panel
  explains the same-origin requirement and how to serve locally.

## 10. Rules that keep it honest (workflow norms for the host repo)

Write these into the host repo's contributor docs (this repo's `CLAUDE.md` carries
them verbatim):

1. `lineage.json` is a **build artifact — never hand-edit it**. Hand-edit only the
   seed, then rebuild + verify.
2. **Whenever you add/remove a committed data file, or add a data fetch to a
   surface page, you MUST update the seed + rebuild.** The Guardian fails on
   orphan artifacts and untracked fetches *by design* — that friction is the
   feature.
3. Never commit regenerable caches into the enumerated data directory (or keep the
   exclusion convention in sync between builder and Guardian).
4. Seed edits are **append-only + rebase-first** (multi-session protocol, §5).
5. The manifest stays **structural-only**; freshness lives in the freshness
   manifest and is joined at render.

## 11. Deferred-but-do-NOT-drop registry (carry this into any port)

The anti-dwindle device: every later feature gets a row with a build trigger and
its landmine, so the product doesn't shrink toward the middle/end of the project.
State of the reference implementation:

| # | Feature | Status here | Landmine to record |
|---|---|---|---|
| D1 | Column-level lineage UI | **shipped** (v1) | per-output-field propagation past a transform still transform-granular; live-source columns need a page-scan |
| D2 | Code/visual export (Power BI, SharePoint, …) | deferred | **semantic-mismatch trap**: bespoke transform logic doesn't port to DAX/M/SQL. What honestly exports = the source *query* (endpoint + columns) + a *visual spec*, never the middle logic |
| D3 | Manual refresh from the UI | deferred | backend-shaped: a static page can only re-pull live-fetchable sources; committed-artifact refresh needs a CI dispatch token or a worker |
| D4 | Change diff ("what changed since last refresh") | deferred | needs snapshot retention design |
| D5 | Time-travel / lineage history | deferred | versioned manifests |
| D6 | Generalized spec | **this document** | abstract only after the real thing works |
| D7 | Live API health probes everywhere | partial (browser-fetched sources only) | only live-bound sources are probeable client-side |
| D8 | Refresh-failure alerting | deferred | ties into the host repo's refresh workflows |
| D9 | Seed split into per-domain fragments | deferred | trigger: frequent parallel-edit collisions on the seed |

## 12. Porting guide

### First: build vs adopt (be honest)
This design is for repos where the mainstream lineage stack doesn't fit. **If the
host repo already runs a warehouse + orchestrator that emits lineage events**
(dbt, Airflow+OpenLineage/Marquez, Databricks Unity Catalog, Snowflake, Power BI
datasets, DataHub/OpenMetadata/Atlan), **adopt that instead** — don't rebuild what
the platform gives for free. Build this when the repo is bespoke/no-build/static/
hand-rolled (scripts producing files, served by a custom app) and those platforms
would mean rearchitecting. Emitting an OpenLineage-shaped manifest while rendering
it yourself is a legitimate hybrid.

### What generalizes unchanged
The node model and tiers (§3); the seed/builder/manifest/Guardian split and
determinism rules (§4–6); the health model's three signals + propagation (§7);
every Guardian check *pattern* (§8); the full renderer feature set (§9); the norms
(§10) and the deferred registry (§11).

### What you adapt per repo (the complete list)
1. **Artifact enumeration**: your data directory/globs + your uncommitted-cache
   convention (or `git ls-files`).
2. **The consumption regex**: how surfaces read data in your stack
   (`fetch("data/…")` here; maybe `read_csv(`, `requests.get(`, an import graph,
   or SQL `FROM` clauses elsewhere). This powers both the no-untracked-consumption
   check and live-column attribution.
3. **The "script really writes it" check**: literal filename in script here;
   yours might be a table name in a SQL model.
4. **Surface pages**: the set of HTML/report entry points and the
   `location → page` resolution.
5. **Field dictionaries**: wherever your sources publish schemas (OpenFEMA
   dictionary JSONs here; OpenAPI specs, `information_schema`, dbt catalogs
   elsewhere). Without dictionaries you lose `columnsUnused` + the typo check but
   keep everything else.
6. **The workflow map** (`WF` in the renderer): your scheduled refresh jobs +
   your CI API (GitHub Actions here; adapt for GitLab/Buildkite — you need
   "last run conclusion per pipeline," CORS-reachable or proxied).
7. **Program/domain groups**: the display-only regex heuristic — retag for your
   domain vocabulary.
8. **Freshness manifest**: any per-artifact `{dataAsOf, sourceCadence, bytes}`
   builder; the covers-through semantics and the automated-vs-manual split matter
   more than the format.
9. **Branding/palette/disclaimers** and the back-link into your app.

### Build order (phased, each with a hard acceptance check)
1. **Phase 0 — seed + builder + Guardian + CI.** *Accept: break one edge → CI red;
   fix → green.* No UI yet. This is deliberately first.
2. **Phase 1 — health data.** *Accept: an artificially-staled file reports stale;
   a hybrid source shows both states.*
3. **Phase 2 — the chart** (tiers, cards, focus/isolate/trace, filters).
   *Accept: click a degraded source → its downstream cone lights; unrelated nodes
   dim.*
4. **Phase 3 — column layer.** *Accept: click a column → only its real consumers
   light; a fabricated column shows the unfound flag.*
5. **Phase 4 — pipeline health + guardian badge.** *Accept: a failing refresh
   workflow red-lines its cone and lists at-risk surfaces.*
6. **Phase 5+ — the deferred registry, in order, on their triggers.**

Anti-pattern to actively guard against, verbatim from the owner: *"scoping the
project down over time until the deliverable shrinks."* Keep the full ambition
recorded (§11) even when sequencing it later.
