# Scheduled data refresh — architecture & plan

How the committed data snapshots stay current across **both** origins this project deploys to
(GitHub Pages *and* Cloudflare Pages), and the plan for adding NFIP. Grounded in the OpenFEMA
facts we measured, not guesses.

## The core facts that drive the design

- **Refresh cadence is per-dataset, not global.** OpenFEMA publishes each set's reload cadence
  in `accrualPeriodicity`:
  - PA `PublicAssistanceFundedProjectsDetails` → **daily** (`R/P1D`), ~815k rows
  - HM `HazardMitigationAssistanceProjects` → **daily** (`R/P1D`), ~56k rows
  - **NFIP** `FimaNfipClaims` → **monthly** (`R/P1M`), **2.7M** rows
  - **NFIP** `FimaNfipPolicies` → **monthly** (`R/P1M`), **73.6M** rows
- **Content lag ≈ 2 days** for PA/HM (newest obligation date trails real time by ~2d); the
  reconciliation tail runs months/years (obligations keep adjusting). NFIP updates monthly.
- **Refreshing faster than the source reloads buys nothing.** Daily for PA/HM, monthly for NFIP.
- **GitHub Pages limits:** ~1 GB/site soft, **100 MB/file hard**. Current committed `data/` is
  ~2.3 MB. Small rollups have huge headroom; raw NFIP (73.6M policies) is categorically out.

## Two origins, clear division of labor

This repo deploys to GitHub Pages **and** Cloudflare Pages (project `disasterdata`). They are
complementary, not redundant:

| | GitHub Pages | Cloudflare (Pages + Workers/KV/R2/D1) |
|---|---|---|
| **Role** | Canonical app + small, git-tracked rollups | Freshness without redeploy + scale (big data) |
| **Refresh** | Scheduled GitHub Action → commit → redeploy | Worker Cron → KV/R2; no commit needed |
| **Strength** | Free, audit trail in git history, zero infra | Fresh between deploys, holds big data, dodges OpenFEMA cold-start |
| **Weakness** | Stale between commits; 100 MB/file ceiling | No git history; Worker CPU/subrequest limits |

**Rule of thumb:** small + traceable → Pages (committed). Big or needs-to-be-fresh-now →
Cloudflare. One **canonical writer per dataset**, everything else is a fallback.

## Refresh tiers

```
Tier 0  LIVE (no refresh)      NWS alerts, USGS gages, live short-window (7–90d) recent obligations → browser
Tier 1  SMALL + DAILY          recent.json, newsreel.json, manifest.json
                               → .github/workflows/refresh-daily.yml (cron) → commit → Pages redeploy   [BUILT]
Tier 1b SMALL + DAILY (heavy)  disasters.json, county_declarations.json (+ byYear/ihp/hmgp/mit/prep)
                               → weekly workflow (multi-step, slow, audited)                            [PLANNED]
Tier 2  FRESH FEED             recent.json → Cloudflare Worker Cron → KV (served CORS)                  [worker shipped, opt-in]
Tier 3  BIG + MONTHLY          NFIP county×year claims rollup (Pages)                                  [SHIPPED]
                               NFIP claim-level drill-down (Cloudflare R2/D1)                          [PLANNED, Phase 2]
```

### Tier 1 — daily (shipped)
`refresh-daily.yml` rebuilds `recent.json`, `newsreel.json`, `manifest.json` and commits to
`main` only when they change (auto-commit, per maintainer decision). The commit triggers
`pages.yml`, which redeploys. Cloudflare Pages auto-builds the same push. Best-effort builders:
an OpenFEMA hiccup keeps the prior snapshot rather than failing.

### Tier 1b — weekly heavy rebuild (planned)
`county_declarations.json` is built by a **multi-step, order-dependent** pipeline
(`build_county_map` → `dedup_applicants` → `build_county_ihp` → `build_county_hmgp` →
`build_county_mitigation` → `build_state_prep` → `build_county_byyear`) that takes many minutes
and hits the API hard. Run it **weekly**, not daily, and **gate the commit on the existing
dollar-conservation audits** (`cd["ihpAudit"]`, HMGP/mit conservation) — refuse to commit if
reconciliation breaks. (Obligations reconcile over months, so weekly is plenty.)

### Tier 2 — Cloudflare worker (shipped, opt-in)
`cloudflare/recent-worker.js` rebuilds `recent.json` daily into KV and serves it CORS-open. Set
`RECENT_WORKER_URL` in `index.html` to read the daily-fresh feed (esp. the 1-year window)
without waiting for a commit. Default `""` = committed file.

## NFIP — the plan (phased)

NFIP is why "scheduled refresh for all data" needs real architecture: it's **monthly** and
**huge**. Do it in two phases.

### Phase 1 — county×year rollup on Pages (SHIPPED)
`scripts/build_county_nfip.py` → `data/nfip.json` (~340 KB). Pulls the Region 5 subset of
**`FimaNfipClaims` v2** (the public redacted claims dataset; `FimaNfipRedactedClaims` 404s —
`FimaNfipClaims` is already redacted) per state, aggregates to **county × year**. Per
county/state: claims **count**, **total paid** (building + contents + ICC, with the split),
**claims/paid by `yearOfLoss`**, and an **SFHA in/out** summary (from `ratedFloodZone`). The
first build: 137k R5 claims, 512 counties, **$1.71B paid**, 1978–2026, outside-SFHA paid share
18–32% (tracks the ~25–30% national figure). Refreshed **monthly** via
`.github/workflows/refresh-monthly.yml`.

**Not in Phase 1: policies-in-force / coverage $.** `FimaNfipPolicies` is 73.6M rows and a
`propertyState` filter full-scans it (times out); even the R5 subset is millions of rows — it
belongs in the Phase 2 Cloudflare-backed layer, not a committed Pages file.

**Next step (not yet done):** surface `nfip.json` as a Geography **"Flood insurance"** program
lens (NFIP $ / claims / outside-SFHA measures). The data merges onto `DECL.counties`/`states`
by FIPS so it slots into the existing program-first machinery; claims-only counties (no FEMA
declaration) get a minimal synthetic county entry so the map still colors them.

### Phase 2 — claim-level drill-down (Cloudflare R2/D1)
What you specifically asked: *what does claim-level give me that a rollup doesn't?* A lot — but
it's why this phase needs the dynamic backend. `FimaNfipRedactedClaims` carries per-claim:

- **`dateOfLoss` (to the day)** → join individual claims to specific declared disasters; compare
  **insured (NFIP) losses vs PA/IHP** for the *same* event — a cross-program loss picture the
  rollup can't show.
- **Census-tract centroid lat/lon** → map **damage clusters within a county**, not just a county
  color; see exactly where flood losses concentrate.
- **`floodZone` / `ratedFloodZone`** → quantify the big policy story: the share of paid claims
  **outside** the mapped high-risk zone (SFHA) — nationally ~25–30%.
- **building vs contents vs ICC split**, **`waterDepth`**, **`causeOfDamage`** → loss
  composition and **severity distribution** (the insured analog of the project's hazard envelope).
- **repeated location/tract hits** → **repetitive-loss properties**, the prime mitigation target —
  ties NFIP directly to the HMGP / mitigation views.
- **`occupancyType`, pre/post-FIRM construction** → vulnerability by building type/age.

**Why it can't live on Pages or be fetched live:** even the R5 subset is ~hundreds of thousands
of claim rows — too big to commit (100 MB/file ceiling) and too big to filter in-browser. The
path: a **monthly cron** stages the R5 claim subset into **Cloudflare R2** (raw) and a queryable
layer (**D1** SQLite, or pre-built tract aggregates in **KV**); a **Worker API** serves
filtered/aggregated slices to the browser on demand. Budget the **paid CF plan (~$5/mo)** —
D1/R2 at this scale plus the Worker subrequest limits (50 free / 1000 paid per request; NFIP
paging needs many) make the free tier impractical. Ingestion must be the cron batch, never an
on-demand Worker fetch.

**Recommendation:** ship Phase 1 (rollup) first — it answers the map/exec questions cheaply and
stays traceable on Pages. Treat Phase 2 (claim-level drill-down) as a funded follow-up once the
rollup is live and the Cloudflare backend is provisioned.

## What this closes (gaps from the review)

1. **Orchestration** — daily Action shipped; weekly/monthly planned above.
2. **Staleness visibility** — `manifest.json` + footer "Data as of" stamp (per-file `dataAsOf`
   vs source cadence), so stale data can't look fresh.
3. **Audit-gated refresh** — Tier 1b commits only if conservation audits pass.
4. **Failure handling** — best-effort builders + commit-on-change; a failed pull keeps the prior
   snapshot. (Add Actions failure notification when you wire alerting.)
5. **Single-writer rule** — one canonical writer per dataset (e.g. recent.json: the daily Action
   writes the committed file; the Worker serves its own KV copy as the opt-in fast source).

## Open decisions

- **NFIP depth:** Phase 1 rollup now; Phase 2 claim-level drill-down is the funded follow-up
  (needs paid Cloudflare). *(Maintainer leaning toward wanting Phase 2 — parked here.)*
- **Daily delivery:** auto-commit to `main` (chosen) vs PR-for-review. Chosen: auto-commit.
