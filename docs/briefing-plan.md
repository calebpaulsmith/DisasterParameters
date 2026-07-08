# The Briefing — evolving the Newsreel into a scope-aware "charted news article"

Status: PLANNED (phase 1 not started). Owner decisions locked 2026-07-08:
evolve the existing **Newsreel** tab (no new tab), build the **State Briefing**
first, national scope includes **all states + territories + tribal declarations**.

## 1. What this is

A **scope-aware briefing engine**. The user picks an altitude — **Nation →
FEMA Region (1–10) → State/Territory**, with drill-downs to a disaster or a
recipient — and the page composes a *charted news article* for that scope:
the same editorial grammar every time, re-lensed per audience. The portfolio
thesis it demonstrates: **one information architecture that stays honest at
every altitude**, with each audience's key numbers promoted, not invented.

Every scope answers the same five questions, in order — the five "chapters":

1. **What's happening?** — the lede: obligation activity, last 6–12 months
2. **What has happened?** — history: declarations + dollars over time
3. **Where is the money going?** — composition: program → PA category **incl. Cat Z**
4. **Who is getting it?** — recipients/applicants
5. **What should I watch?** — open disasters, immature obligations, mitigation posture

What changes per audience is which chapter leads and which derived figures are
promoted — never the questions.

## 2. Audiences → promoted information

### Regional leadership (region scope) — portfolio management across states
| They ask | Surface |
|---|---|
| Which of my states is absorbing money right now? | Obligation velocity by state — last 90d vs trailing year, small multiples |
| Where is each disaster in its lifecycle? | **A-B : C-G ratio** per open disaster (A-B heavy = emergency phase; C-G ramping = rebuilding) |
| Are we leaving mitigation on the table? | **§406/PA ratio** + HMGP pace per state, comparable across the region |
| What's anomalous? | Biggest single obligations + **deobligations** (negative activity is signal) |
| How do we compare? | Per-capita PA vs the national distribution, COVID excluded by default |

### State leadership (state scope) — my history, my exposure, my open recoveries
| They ask | Surface |
|---|---|
| Our full record? | State-scoped disaster ledger — every declaration, PA + IHP $, timeline |
| What is each disaster costing, in what? | Per-disaster PA **A-B / C-G / Z reconciling on-screen to the total** |
| What's *our* bill? | **Implied non-federal share** (fed share is 75–90%; the remainder is the state/local match) — phase 2b, see §6 |
| COVID or weather? | COVID toggle, everywhere, default excluded, always labeled (~7× distortion) |
| How mature are the numbers? | "Still counting" flag: recent disasters with projects > 0 but low $ |

### Private sector (recipient lens) — working backwards from money to door-knock
| They ask | Surface |
|---|---|
| Who just got funded? | Latest obligations with **applicant name** leading — obligated = money to spend |
| What kind of work? | Damage category as trade signal (A=debris, C=roads/bridges, E=buildings/A-E, Z=grant-mgmt consulting) |
| Where's the concentration? | County clustering within the state |
| What's the pipeline? | HMGP/BRIC/FMA subrecipients (long procurement tails); §406 = hardening scope inside upcoming repairs |
| Honesty check | Standing caveat: **obligated ≠ out for bid** — this tells you who to call, not what's on the street |

## 3. Scope model & routing

- Scopes: `national` · `region/1..10` · state/territory two-letter code (50 states,
  DC, PR, VI, GU, AS, MP; tribal declarations are carried under their state's
  scope and tagged, mirroring the pending.json TRIBE_STATE approach).
- Hash routing extends the existing pattern: `#newsreel` (national default),
  `#newsreel/r/5`, `#newsreel/MI`, plus drills `#newsreel/MI/4757`.
- The scope bar is a single control row at the top of the view: a dropdown
  (National / Region 1–10 / states+territories A-Z) + the COVID toggle.

## 4. Data feasibility (probed 2026-07-08, live OpenFEMA)

| Fact | Number | Consequence |
|---|---|---|
| `FemaWebDisasterSummaries` (all history, national) | **3,972 rows**, has PA total + CatAB + CatC2G (+IHP HA/ONA, HMGP, IA regs) | **Cat Z = paTotal − AB − C2G is computable for every disaster in America.** The whole national cost ledger bakes to a few hundred KB |
| `DisasterDeclarationsSummaries` | 70,049 rows, carries `region` (1–10) | Region is a first-class join, not a hack. Dedup per disasterNumber for identity/dates/state/region/incidentType |
| `PublicAssistanceFundedProjectsSummaries` v1 | **195,503 rows** national, `applicantName` + `federalObligatedAmount` + `numberOfProjects` + county | Recipients exist nationally. Never baked whole — **fetched live per scope** (CORS-open), like Geography's applicant fetch |
| `PublicAssistanceFundedProjectsDetails` v2 | ~800K+ rows | Only touched offline (aggregations) or in narrow live windows (newsreel strips) — never bulk in-browser |

## 5. Data plan

### Baked (offline script → committed JSON)
`scripts/build_briefing.py` → `data/briefing.json` (+ `data/briefing_ledger.json`
if size warrants a split):

- **National disaster ledger** (~4K rows, lean): per disasterNumber —
  state, region, incidentType, title, begin/declared dates, tribal flag,
  `paTotal / paAB / paCG / paZ (derived) / ihpTotal / ihpHA / ihpONA / hmgp / iaRegs`,
  `covid` flag (incidentType Biological).
- **Rollups**: per state+territory and per region — all-time totals,
  by-declaration-year buckets (count + $), COVID split baked as separate
  buckets so the toggle is pure client-side arithmetic (no re-fetch).
- **Trailing-12-month obligation series** per state (monthly, from a national
  date-windowed PA Details pull à la `build_county_recent.py`, aggregated
  offline so the browser gets tiny series).

### Live (in-browser, scoped, on demand)
- **Latest/biggest strips** for the selected scope (the existing newsreel
  queries with scope filters; baked national snapshot = default + fallback).
- **Top recipients** for a state/region/disaster (Summaries v1, `$orderby
  federalObligatedAmount desc`, `$inlinecount` for the denominator).
- Per-disaster §406 and category detail on drill-in.

### Two timelines, deliberately distinct
1. **Declaration timeline** (history chapter): disasters as events by year —
   baked, all history.
2. **Obligation timeline** (activity chapter): dollars moving by month —
   trailing window only, baked per state.
Conflating these is the classic dashboard lie; keeping them separate and
labeled is a core design point.

## 6. Reconciliation discipline (non-negotiable)

- On-screen identities, everywhere they apply:
  `A-B + C-G + Z = PA total` · `HA + ONA = IHP` ·
  `Σ states = region` · `Σ disasters = state` (within the baked dataset).
- Where datasets disagree (project-level sums vs FemaWebDisasterSummaries —
  they refresh on different days), the **summary figure is authoritative**;
  the delta is footnoted, never hidden. Extends the repo's audit ethic
  (`ihpAudit`, `paApplicantAudit`) to the article surface.
- Every figure keeps a verify link to its raw OpenFEMA query.
- **Non-federal share** (the state's bill): NOT computable from
  FemaWebDisasterSummaries (federal-only). Phase 2b bakes per-disaster
  `nonFederal = Σ(projectAmount − federalShareObligated)` from an offline
  national PA Details aggregation (resumable cache). v1 ships **without** it,
  labeled "federal share only — state/local match not shown" rather than
  estimating from an assumed 75%.
- PA is **obligated**; IHP is **approved** — labels never conflate (glossary rule).

## 7. UI — the State Briefing article (first build)

Top to bottom, each chapter = one chart + one sentence + 3–5 rows, tap for depth:

- **Scope bar**: dropdown + COVID toggle (default excluded, labeled when on).
- **Lede**: stat tiles — PA obligated (all-time, scope), IHP approved,
  declarations count, "still counting" count; data-as-of stamp.
- **Ch 1 What's moving**: the three existing cards (PA / HM §404 / §406),
  scoped live, baked fallback.
- **Ch 2 History**: declaration timeline (count + $ per year, COVID tinted
  when included); ledger table (top by PA, expandable). R5 disasters open the
  existing rich modal; non-R5 open the minimal modal (dates + $ + links),
  reusing the `disasters_national.json` pattern.
- **Ch 3 Composition**: stacked PA bar A-B / C-G / **Z** with the identity
  line printed under it; IHP HA/ONA split beside it; per-disaster composition
  in the expanded table.
- **Ch 4 Recipients**: top applicants live (name, $, projects, county),
  private-sector caveat standing.
- **Ch 5 Watch**: recent disasters still counting; §406/PA + HMGP posture strip.
- **Region scope** re-lenses: Ch 2 → state small-multiples; Ch 3 → composition
  by state; lifecycle board (A-B:C-G per open disaster); recipients top-N regionwide.
- **National scope**: same grammar, states as the units.

## 8. Phasing (each phase shippable)

- **P1 — Foundation**: `build_briefing.py` + baked national ledger/rollups;
  scope bar + hash routing; lede + Ch 1 scoped (nationalized newsreel).
- **P2 — State Briefing**: Ch 2 + Ch 3 (+ COVID toggle, reconciliation lines,
  minimal national modal). ← the centerpiece.
- **P2b — Non-federal share**: offline PA Details aggregation → per-disaster
  state/local match.
- **P3 — Recipients + Watch** (Ch 4–5).
- **P4 — Region board + national board** (comparative lenses).
- Every phase: update `data/lineage.seed.json` (append-only) + rebuild/verify
  lineage (Guardian), update `data/manifest.json` build, and wire any new baked
  file into the pages.yml best-effort refresh if cheap (the rollup pull is one
  bulk FemaWebDisasterSummaries fetch — fast).

## 9. Out of scope / guardrails

- No eligibility or rights determinations; non-endorsement disclaimer stays.
- No forecasting here — the Briefing is facts; the Estimate view keeps that role.
- IHP stays disaster-level in the Briefing (registrant-level data is per-person
  and heavy; county IHP lives in Geography).
- COVID never silently mixed: excluded by default, tinted + labeled when included.
