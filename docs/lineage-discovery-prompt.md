# Portable prompt — "Build me a data-lineage view for this repo"

Copy everything in the fenced block below into a fresh session **in any repo** that
has grown a tangled web of data sources → transforms → outputs → UI/reports. It
reproduces the discovery + research + planning process that produced this project's
`docs/lineage-plan.md`, **including the branch where the right answer is "adopt an
existing tool" rather than build a bespoke one.**

It is deliberately tool-agnostic and stack-agnostic. It tells the assistant to
*chat first*, research honestly, and only then plan.

---

```
You are helping me build a DATA LINEAGE view for this repository: a graph that maps
every data SOURCE to all of its downstream PRODUCTS (dashboards, charts, reports,
APIs, exported files), through every transform/join in between — so that anyone can
trace any figure on screen back to its origin, and so that staleness/outages can be
traced FORWARD to everything they impact.

Do NOT write a plan yet. First investigate, research, and have a conversation with me.

== STEP 1: Map the actual data web in THIS repo (don't guess) ==
Explore the codebase and inventory, as concretely as you can:
- External data providers/origins (APIs, vendors, public datasets, files received).
- Specific source datasets/endpoints/tables actually used, and ideally which COLUMNS
  /fields are used vs available-but-unused.
- Transform steps: scripts, notebooks, SQL models, in-app joins, ETL jobs — anything
  that reads data and writes data. Note for each whether it runs offline (batch/CI/
  scheduled) or at request/render time (in the app/browser).
- Built/intermediate artifacts (files, tables, caches) produced by those transforms.
- The consumer "surfaces": the dashboards, charts, views, pages, reports, or API
  responses that end users actually see.
- Refresh mechanics: how/when each source updates (cadence), and how the repo pulls it.
Report what you found and where you're UNCERTAIN. Cite files.

== STEP 2: Research prior art and decide BUILD vs ADOPT (be honest) ==
This is a mature software category. Investigate and tell me whether THIS repo should
adopt an existing tool instead of building bespoke:
- dbt (sources → models → exposures lineage DAG; "exposures" = the downstream-consumer
  concept) — fits if the repo is already SQL/warehouse + dbt-shaped.
- OpenLineage (open JSON standard: datasets + jobs/runs) + Marquez (its reference UI).
- Data catalogs with column-level lineage + impact analysis: DataHub, OpenMetadata,
  Atlan, Amundsen.
- Platform-native lineage: Power BI lineage view, Databricks Unity Catalog, Snowflake,
  Microsoft Purview, dbt Cloud.
Decision rule you must apply and JUSTIFY against this repo's actual stack:
- If the repo already runs on a warehouse + an orchestrator (SQL/Spark/Airflow/dbt)
  that EMITS lineage events, strongly prefer ADOPTING one of the above — don't rebuild
  what the platform gives for free. Tell me exactly which one and why.
- If the repo is bespoke/no-build/static/hand-rolled (e.g. scripts producing files,
  served by a custom app) and those tools would require rearchitecting it, recommend
  BUILDING a lightweight in-repo view that BORROWS THE MODEL (datasets/jobs nodes,
  source→transform→artifact→surface tiers, the dbt "exposures" idea) but renders itself.
- It's legitimate to recommend a HYBRID (e.g. emit OpenLineage-shaped metadata even if
  we render it ourselves, so it stays a standard).
Give me a clear recommendation, not a survey.

== STEP 3: Propose terminology ==
Adopt the two-node-kind model (DATA nodes hold data; PROCESS nodes transform it; edges
flow data→process→data). Propose crisp names for each tier in THIS repo's vocabulary
(e.g. Provider / Source / Transform / Artifact / Surface) and a name for the view.

== STEP 4: Surface the hard challenges BEFORE planning ==
Raise (at least) these, mapped to this repo's specifics:
1. THE DRIFT PARADOX (most important): a hand-maintained lineage doc is itself prone to
   rot and to the very sloppiness it's meant to catch — so it must be MACHINE-DERIVED
   and/or CI-VERIFIED against the real code, or it will lie. A lineage tool that lies is
   worse than none. Identify what can be auto-derived here (greppable imports, fetch/
   read calls, output filenames) vs what must be hand-authored (prose, column intent).
2. Column-level lineage is a HARDER class than dataset-level (needs annotation or
   fragile static analysis). Recommend dataset-level first, column-level later.
3. It's a DAG, not a tree (many-to-many). Dense graphs are unreadable if you render
   everything — require focus/impact mode, filtering, collapse/expand.
4. "Stale" vs "down" are different signals. Staleness is often computable from existing
   freshness metadata; live "the API is down right now" is only knowable where the app
   actually fetches live; offline pull failures are only knowable from the job/CI status.
   Also distinguish ACTIVE (what's shown live right now) vs LAST-PULL (snapshot recency).
5. Export/reproduce-elsewhere (e.g. into Power BI) is a SEMANTIC-MISMATCH trap: bespoke
   transform logic doesn't port to DAX/SQL/M. What ports is the source QUERY + a visual
   SPEC, not the middle logic. Set that expectation.
6. The trust paradox: the VERIFIER that keeps the manifest honest is the real product;
   the pretty graph is the demo. Build the verifier first.
7. Weight/placement: don't bloat the hot path; consider a separate lazily-loaded view.
8. Duplication: lineage knowledge may already live in READMEs/docstrings/manifests —
   derive from those rather than adding a 4th hand-maintained copy.

== STEP 5: Converse, THEN plan ==
Ask me the key forks (truth source: auto-derived+CI-checked vs hybrid vs hand-authored;
granularity: dataset-level vs column-level for v1; placement; rendering approach). Give
your recommendation for each. WAIT for my answers.

Then write a PLAN as a committed living spec (a markdown doc) with:
- The preserved statement of intent/goals (so scope can't quietly drift).
- The terminology + node model + a concrete manifest SCHEMA.
- An auto-derivation step and a CI VERIFIER ("Guardian") built FIRST, with a concrete
  acceptance test: deliberately break one edge → CI goes red.
- A health/status model covering staleness, last-pull/job status, and active-vs-cached.
- A phased roadmap where each phase has a HARD acceptance check (no "mostly done").
- A "DEFERRED BUT DO NOT DROP" registry capturing every later feature (export, manual
  refresh, change-diff, column-level, history) with a build trigger and its landmine,
  so the product does not dwindle toward the middle/end.

Anti-pattern to actively guard against: scoping the project down over time until the
deliverable shrinks. Keep the full ambition recorded even when sequencing it later.
```

---

## Notes for the human using this prompt

- The prompt is intentionally **honest about adopt-vs-build**. In a repo that's already
  a dbt/warehouse/Airflow shop, the correct output is "adopt dbt exposures / DataHub /
  Unity Catalog," not a bespoke build. This repo got a bespoke build only because it's a
  no-build single-file static app where those tools don't fit.
- If you want the assistant to go straight to a specific tool, append: *"Skip the build-
  vs-adopt analysis; we are a <dbt / Databricks / Power BI> shop — wire lineage using
  that platform's native capability."*
- The output you want from a good run is a committed `*-lineage-plan.md` plus a first
  Guardian/verifier — same shape as this repo's `docs/lineage-plan.md`.
