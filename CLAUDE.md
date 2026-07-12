# CLAUDE.md

Guidance for working in this repo. Read this before changing code or data.

## What this is

An independent, **single-file web tool** that helps an executive get a fast,
**traceable** read on FEMA **Public Assistance (PA)** and **Individual
Assistance (IA/IHP)** for upper-Midwest (**FEMA Region 5**: IL, IN, MI, MN, OH,
WI) disasters. Built entirely on public open data. **Not endorsed by FEMA** —
the non-endorsement disclaimer must stay in the UI.

Live site (GitHub Pages): https://calebpaulsmith.github.io/DisasterParameters/

Three views (in priority order — **facts first**):
1. **Disaster Ledger** (default) — every Region 5 disaster, sortable, with
   measured hazards + real PA (obligated) & IHP (approved) dollars. **Tap a row → detail modal** with that
   disaster's full sourced cost breakdown and parameter provenance + verify links.
2. **Disaster Watch** — live NWS alerts + live USGS gages; trips when a river
   approaches a past disaster's peak stage or warnings match an analog's hazards.
3. **Estimate (beta)** — a deliberately-downplayed comparables heuristic that
   scales similar past disasters' obligations by population. It is **not a
   forecast**; keep the prominent caveat.

## Project layout

```
index.html                  # the entire app (HTML+CSS+vanilla JS, no build step)
data/disasters.json         # 80 Region 5 disasters (FY2007–2026) — the source of truth (committed)
data/gages.json             # 19 key USGS river gages: AHPS + crest history + declaration ties (committed)
data/county_declarations.json # committed geo rollup: per-county declaration count + disaster list + PA obligated $ + projects, IHP approved $ with HA/ONA split (ihpApproved/ihpHousing/ihpOna) + iaRegistrations, and per-state totals (states carry the same IHP HA/ONA/registrations set). County IHP $ are registrant-level; state IHP $ are ledger-level (different datasets — see the cd["ihpAudit"] conservation block + scripts/build_county_ihp.py). PA applicants: counties[fips].applicants[] (Summaries v1, by applicant×county — note this differs from county paObligated which is Details v2) plus states[st].paStatewideApplicants[] for no-county/state-agency applicants; cd["paApplicantAudit"] conserves every applicant row (inCounty+statewide+undeclared+unmatched==totalSummaries) — see scripts/build_county_applicants.py. Powers the Watch "Declaration history" map and the Geography view. Also carries per-county+per-state *ByYear obligation buckets (paByYear/paProjectsByYear/hmgpByYear/mitByYear true obligation year, ihpByYear proxy incident year, empgByYear/afgByYear fiscal year) that drive the Geography per-view timeline + draggable year-range filter — see scripts/build_county_byyear.py. The Geography view is **program-first**: a PROGRAM row (Overview · PA · IA · HMGP · Non-disaster, #geoProgRow `data-prog`) picks the lens, then a program-scoped MEASURE row (#geoToggle `data-geom`) picks the figure — Overview→count; PA→paObligated/paProjects/paApplicants; IA→ihpApproved/ihpHousing(HA)/ihpOna(ONA)/iaRegistrations; HMGP→hmgpObligated/hmgpSubs; Non-disaster→mitObligated/empg/afg + the promoted preparedness-family lenses prepHomeland/prepTransit/prepNonprofit/prepOther (state-fill, via PREP_FAMILY→prepByFamily/prepFamilyYear/prepFamilyVendors). `geoProgram` derives `geoGroup`; `GEO_MEASURE_PROG`/`GEO_PROG_DEFAULT` map the two. The WITH PA/IA/HMGP filter (`#paiaToggle`) shows on **Overview only** and its IA branch uses the **ledger authorization** (`isIHP(d)||iaProgramDeclared`, see `geoProgKeep`); COVID fold-in stays on all disaster-side programs. New count/$-measures plug into the generic metric tables (GEO_META/geoColor/GEO_LEGEND/GEO_KEY/GEO_BAR); applicants/subrecipients get per-state sums in `geoComputeStatewide` (`_paAppl`/`_hmgpSubs`). The Geography timeline is **measure-driven**: ONE series for the active measure — Disasters(count) → # declarations by incident year honoring the WITH switcher + COVID toggle (counted live); dollar/projects → that measure's *ByYear; measures with no year series (HA/ONA/registrations/applicants/subrecipients) fall back to the program's representative $-series via `GEO_YEARFALLBACK` (relabeled "selected measure not year-bucketed"). Mobile mirrors the FULL program→measure pair via a program chip row (`.gm-progbar`/`data-gmprog`, GM_PROGS) that scopes the measure chips (GM_SORTS, `data-gmsort`) — gmProgОf()/gmProgMeasures()/gmLensControl() — so every desktop lens incl. the state-only Non-disaster set (EMPG/AFG/prep families), Recent (with mobile window chips, `data-gmrecwin`) and Flood-insurance is selectable on mobile; the chips double as the row sort, plus the `.gmpaia` IA-labeled switcher on the Disasters view. The per-disaster county drill uses a fixed PA/IA chip set (GM_DIS_SORTS). Under a Non-disaster lens the mobile state view drops the Disasters/Counties tabs + disaster list and shows a grant breakdown instead (gmNonDisStateBody: by-family/by-program split + top recipients; mit also lists counties-with-grants), mirroring the desktop state detail (prepBreakdownHTML/geoNonDisDetailHTML); the non-county PA applicant buckets render only on the PA lens (gated on gmProgram, matching desktop's geoSoleProgram()==="pa"). Same timeline component renders on desktop (#geoTimeline) and mobile (#gmTimeline). The earlier single stacked-dollar chart + the parked mobile/per-program-mit plan are archived in docs/timeline-archive.md
scripts/build_county_map.py # OFFLINE: builds county_declarations.json — designations from _disasters_raw + disasters.json; per-county PA $/projects pulled from OpenFEMA PublicAssistanceFundedProjectsDetails (needs network)
scripts/build_county_applicants.py # OFFLINE: adds per-county PA applicants[] (PublicAssistanceFundedProjectsSummaries v1, by applicant×county) AND conserves no-county applicants — county="Statewide"/blank (state agencies, e.g. Illinois Emergency Management Agency) go to states[st].paStatewideApplicants[] instead of being dropped. Emits cd["paApplicantAudit"] (mirrors ihpAudit): per state buckets every row inCounty/statewide/undeclared/unmatched with the identity inCounty+statewide+undeclared+unmatched==totalSummaries, and reports the cross-dataset gap vs ledger PA (FemaWebDisasterSummaries). undeclared=R5 county w/ no declaration record; unmatched=non-R5/unresolved (e.g. ND/SD border electric coops). Needs network; resumable cache (_paappl_cache.json). Run after build_county_map.py, then dedup_applicants.py.
scripts/dedup_applicants.py # OFFLINE, no network: collapses duplicate per-county PA applicant entries in county_declarations.json (case/punctuation/"X Township"↔"X (TOWNSHIP OF)"/abbreviation DEPT↔DEPARTMENT/repeated-segment/trailing "(1)" + exact "(DO NOT USE)" variants). ONLY merges order-preserving normalized-string matches (so "Forest Park"≠"Park Forest"); fuzzy/subset cases are reported for manual review, plus a small curated MANUAL map for confirmed-but-non-deterministic merges (e.g. "(DO NOT USE) DULUTH"→"Duluth, City of"). Dry-run prints the full previous→canonical report; --apply rewrites + sums pa/projects/dns + recomputes nApplicants + sets cd["_applicantsDeduped"]. Every merged applicant carries a `merged` provenance tag listing each source record's name + PA $ (no numeric FEMA applicant IDs in this dataset), surfaced in the UI as a small "merged N" badge (mergedTag() in index.html). Idempotent; re-run after build_county_map.py.
scripts/build_planner_applicants.py # OFFLINE: builds data/planner_applicants.json — PER-DISASTER PA applicant detail for the Operations Planner's applicant-history analysis (planner.html). Keeps PublicAssistanceFundedProjectsSummaries v1 at the applicant×county×DISASTER grain (county_declarations only carries all-time rollups) with the SAME conservation bucketing as build_county_applicants.py (c=county/s=statewide/u=undeclared/x=unmatched — every dollar lands somewhere, audited per state), PLUS per-(disaster,applicant) damage-CATEGORY rollups (A–G,Z) from PublicAssistanceFundedProjectsDetails v2 — Details carries NO applicant name, only applicantId, so categories are attributed via the PublicAssistanceApplicants v1 (dn,applicantId)→name bridge using dedup_applicants.normalize() (imported — single source of truth); unattributable category $ stay in the audit, never force-matched. Display names canonicalized against the deduped county_declarations lists so the planner reconciles with Geography. Category rollup is per disaster×applicant ACROSS counties (Details classifies county differently than Summaries — a per-county category split would be false precision). Needs network; resumable cache (_plannerappl_cache.json). Run AFTER build_county_applicants.py + dedup_applicants.py.
data/planner_applicants.json # committed (~1.4MB): {dnMeta, names (dictionary-encoded), rows [[dn,bucket,key,nameIdx,pa$,projects]…], cats {"dn|nameIdx":{cat:[nProj,$]}}, audit}. Fetched LAZILY by planner.html only (never index.html) — powers the "PA applicant history — counties in plan" card: aggregated + by-county drillable applicant lists (per-disaster $/projects/categories; statewide & non-county-aligned labeled), expectation stats (median/mean applicants+projects per prior disaster touching the selection, with/without statewide), 3 CSV exports. PDA↔historical applicant reconciliation is deferred (docs/operations-planner-plan.md §9 P-I). The planner is PROGRAM-FIRST + PA-DEFAULT (PA/IA/HMGP chip row scopes the map measures + a program-scoped Expectations card; IA is a distinct view, HMGP is tucked reference). The PA card is a 3-TIER declutter: (1) a ROLL-UP band (rollupHTML) = plan-total expected PA applicants/projects/$ + a "vs past events" line (typical prior disaster that hit these counties: median + range) + closest named analogs ranked by county-footprint overlap (perDn.nCty); (2) the TEAM DIVIDER promoted, with a per-team expected-PA-applicant LOAD BAR + balance meter (±% vs avg, busiest-vs-lightest spread); (3) a per-county expectations table. Applicant rosters, category mix, and the exclusion/per-disaster tables live behind <details> disclosures. COVID-19 is ALWAYS excluded from every planner calculation (COVID_DNS/isCovid() guard in paCountyHistory/iaCountyHistory/computeAppl/computeIa/buildDindex/buildCountySnapshot — belt-and-suspenders since the data files already omit them — and LABELED in the roll-up header). LIVE per-disaster exclusion (plan.excludedDns — ✕ chips, outliers auto-suggested via modified z-score) and a TEAM DIVIDER (plan.teams = TASK FORCES/TFL; assign counties by map click or dropdown; team-colored map; per-team applicant workload from PDA / basis disaster / historical medians). A CASELOAD BOARD (#caseWrap, renderCaseload) nests the FEMA PA delivery org: each Task Force (TFL, owns counties, auto-named "Task Force A/B/C") holds PDMGs (auto "PDMG 1/2/3", bulk-add-by-count + named, renameable, stored on team.pdmgs), and named applicants — from the historical roster (computeAppl agg) AND/or imported PDA (caseSrc toggle), each carrying prior PA $, # disasters + expected $/disaster (per-disaster avg) — are assigned to a PDMG (plan.caseload{applicantKey→pdmgId}, reassignable to any TFL; PDA↔history name-matched via normApplName for prior-PA display). Caseload CSV export. COVID excluded throughout. Exports: self-contained HTML (teams+expectations baked in), data CSV, PA applicant CSVs + IA expectations CSV, "Copy for SharePoint" (script-free inline-styled clipboard fragment + map PNG) — see docs/planner-sharepoint-export.md.
scripts/build_disaster_designations.py # OFFLINE: builds data/disaster_designations.json — per-DISASTER × per-COUNTY program designation bitmasks (1=PA, 2=IA-authorized ih|ia, 4=HM) from DisasterDeclarationsSummaries v2 (per-state bulk pull over the ledger's dn range; resumable cache data/_desig_cache.json; statewide/tribal non-county designations conserved per disaster in nonCounty, never dropped). NOTE: don't combine $select with $filter+$top against fema.gov — the edge WAF intermittently 503s that combination; the script pulls full rows instead. Needs network.
data/disaster_designations.json # committed (~50KB): {byDisaster[dn]={counties{fips:mask},nonCounty[[area,mask]]}, audit}. Fetched by planner.html only — powers the "Start from a declared disaster" seeding: pick disaster + program(s) and the plan loads exactly the counties designated for that program (PA and IA designation lists differ per incident, e.g. DR-4892 has IH counties but zero PA counties). The seeded disaster is auto-excluded from the planner's expectation math (restorable).
scripts/build_county_ihp.py # OFFLINE: adds per-county IHP approved $ + HA/ONA split + iaRegistrations to county_declarations.json from IndividualsAndHouseholdsProgramValidRegistrations (registrant-level), AND per-state ihpHousing/ihpOna/iaRegistrations rolled up from the disasters.json ledger (no network for the state part). Emits a dollar-conservation audit (cd["ihpAudit"]): county $ (registrant pull) vs state $ (ledger = FemaWebDisasterSummaries) are different datasets, so per state it buckets every registrant dollar into inSet/undeclared/unmatched and reports the cross-dataset residual + flags — money in non-declared counties or unresolvable names (e.g. tribal/reservation areas) is flagged, never dropped. Needs network (county part); resumable cache.
scripts/build_disaster_county_ihp.py # OFFLINE: builds data/disaster_county_ihp.json — per-DISASTER × per-COUNTY IHP (approved $ + HA/ONA split + valid-registration count) from IndividualsAndHouseholdsProgramValidRegistrations (registrant-level), so the Geography disaster drill-down can show each designated county's IHP for THAT disaster (not its all-time IHP). Committed (not live-fetched) because IHP is per-registrant — the biggest R5 disasters carry 70k–117k rows, too heavy for a mobile fetch (PA can be fetched live because Summaries is pre-aggregated). Same dataset+norm() as build_county_ihp.py so per-disaster buckets SUM to that script's all-time county ihpApproved; unresolved rows conserved in a per-disaster audit (inSet/undeclared/unmatched). Needs network; resumable cache (_ihp_dc_cache.json).
data/disaster_county_ihp.json # committed: {byDisaster[dn][fips]=[ihp,ha,ona,regs], audit}. Loaded as DCIHP in index.html; powers the per-disaster IHP $/HA/ONA/registrations figures on the MOBILE Geography disaster→county rows (PA $/projects/applicants on those rows come live from geoDisCountyCache; IHP comes from here).
scripts/build_disaster_drc.py # OFFLINE: builds data/disaster_drc.json — per-DISASTER list of FEMA Disaster Recovery Centers (walk-in survivor-assistance sites: DRC / Mobile DRC / Document Drop-Off Center) from FEMA's own ArcGIS Geospatial Resource Center FeatureServer (gis.fema.gov/arcgis/rest/services/FEMA/DRC/FeatureServer — layer 0 "Open DRC" + layer 1 "Archive - Closed DRC Locations"; NOT OpenFEMA, a separate FEMA GIS system updated hourly by FEMA's DRC Manager program). Filtered to Region 5 states at query time; each record's primary_disaster/secondary_disaster (a FEMA disaster number) is joined to disasters.json's disasterNumber — a DRC co-declared to two disasters is attached to both. Disaster-number refs that don't match anything in the ledger (pre-FY2007, mostly) are conserved in audit.offLedgerDisasters, never silently dropped. No PII (records are already de-identified to name/address/hours — no borrower/registrant data). Needs network; no cache (R5 record count is small, a full re-pull is cheap).
data/disaster_drc.json # committed (~100KB): {byDisaster[dn]=[{name,type,street,city,county,state,zip,lat,lon,status,open,plannedClose,close,hours}, …], audit}. Loaded as DRC in index.html; powers a small "🏢 N DRC" **badge** (not a measure/selector) — drcBadgeHTML() — surfaced next to the IA/IHP figures on the Geography disaster drill-down (desktop disasterDetailHTML + mobile gmRenderDisaster) and the Ledger detail modal's survivor-assistance card. Tapping the badge (data-drcdn → openDrc()) opens a dedicated modal (renderDrcDetail(), a new mStack entry type "drc") listing each site's address, open/close dates, and hours. `hours` is derived from the source's per-day open/close fields where present, else a truncated notes fallback.
scripts/build_county_hmgp.py # OFFLINE: adds per-county + per-state-statewide HMGP (§404) obligated $ + subrecipient lists to county_declarations.json from HazardMitigationAssistanceProjects v4 (programArea=HMGP; needs network). Dollars conserved: a project lands in its county or the state STATEWIDE bucket. Each subrecipient entry carries name/hmgp/projects/nDisasters/dns PLUS types[] (top project types, code prefix stripped in UI), props (numberOfProperties), d0/d1 (obligation date range from initialObligationDate/dateApproved), counties[] (for statewide rows). Powers the Geography HMGP state view (hmgpSubsForState/hmgpStateDetailHTML desktop + gmHmgpStateBody mobile) — the HMGP lens shows real subrecipients + what they got, NOT a disaster list (HMGP funds reconcile for years after the disaster, so figures + timeline key to obligation year via hmgpByYear).
scripts/build_county_mitigation.py # OFFLINE: adds per-county NON-DISASTER hazard-mitigation grant $ (FMA/PDM/BRIC/LPDM/RFC/SRL — all HMA projects except HMGP) to county_declarations.json as mitObligated/mitByProgram/mitApplicants + per-state mitStatewide AND mitStatewideApplicants (no-county grantees, browsable; mirrors hmgpStatewideApplicants). Separate non-disaster layer; needs network; dollars conserved.
scripts/build_state_prep.py # OFFLINE: adds per-STATE non-disaster PREPAREDNESS grant $ — EMPG (EmergencyManagementPerformanceGrants) + AFG (NonDisasterAssistanceFirefighterGrants) — to county_declarations.json states. IMPORTANT: the NonDisasterAssistanceFirefighterGrants dataset is a GRAB-BAG of ALL DHS non-disaster grants (Homeland Security, Transit/Port, Nonprofit, EMPG, plus actual firefighter grants). `afg`/afgByProgram/afgByYear/afgVendors are now FIREFIGHTER-ONLY (AFG/SAFER/Fire Prevention/Station — honest label); the full split is in prepByFamily (Firefighter/Homeland Security/Transit-Port-Rail Security/Nonprofit Security/Other preparedness) + prepByProgram + prepByYear + prepTotal, with EMPG EXCLUDED (it is the separate `empg` field — avoids double-count). Each non-firefighter family is ALSO a selectable Geography map lens (Non-disaster → Homeland $ / Transit-Port $ / Nonprofit $ / Other prep $; firefighter = the `afg` lens), backed by per-family detail: prepFamilyYear (year series → the measure-driven timeline), prepFamilyProgram (top sub-programs), prepFamilyVendors (top recipients → the state-detail board). In index.html these map via PREP_FAMILY{measure→family} + GEO_STATEONLY (state-fill, no county) reading prepFamVal()/prepFamYear(). Both state-level (no county); map fills each state. Needs network.
scripts/build_county_byyear.py # OFFLINE, ADDITIVE: adds per-county + per-state *ByYear obligation buckets to county_declarations.json — powers the Geography "Obligations by year" timeline + its draggable year-range filter. paByYear/hmgpByYear/mitByYear are TRUE obligation year (PublicAssistanceFundedProjectsDetails.lastObligationDate / HazardMitigationAssistanceProjects v4.initialObligationDate); ihpByYear is a PROXY by disaster incident year (IHP carries no obligation date) — state from ledger ihpTotal, county by allocating ihpApproved across its disasters' incident years. EMPG/AFG already carry empgByYear/afgByYear (fiscal year); COVID excluded. Bucketing mirrors build_county_map/hmgp/mitigation (dollars conserved); sum(*ByYear) reconciles with the all-time field minus null-date rows. Needs network.
scripts/build_timeline.py   # OFFLINE: builds data/timeline.json — one regional monthly series (rain/river/tornado[/snow]) + disaster markers for the Ledger "Hazard timeline" chart
data/timeline.json          # committed: monthly regional hazard series + per-month disaster list (powers the Ledger hazard timeline)
scripts/build_covid.py      # OFFLINE: builds data/covid.json — the 6 R5 COVID-19 (Biological) declarations' PA/IHP/projects (needs network)
data/covid.json             # committed: per-state COVID-19 PA obligated/IHP approved/projects (powers the standalone COVID-19 view; kept OUT of ledger/geography/analyses — ~7× weather PA)
scripts/build_newsreel.py   # OFFLINE: builds data/newsreel.json — "latest obligations" strips for the programs with a per-item obligation DATE: PA (PublicAssistanceFundedProjectsDetails.lastObligationDate) + Hazard Mitigation §404 (HazardMitigationAssistanceProjects v4.initialObligationDate) + Section 406 mitigation (the PA project's mitigationAmount — hardening built into a PA repair, a SUBSET of that PA obligation; row carries paShare = the parent repair total). NATIONAL scope (the Briefing's default; other scopes fetch the same queries live in-browser), COVID excluded via the briefing.json covid dn set (live Biological-dn fallback) — so run build_briefing.py FIRST. Latest N + biggest N in last 6mo per program. Needs network. (IHP/AFG/EMPG carry no per-item obligation date, so they can't feed strips.)
data/newsreel.json          # committed, small: per-program national latest+biggest obligation strips (the Briefing's baked "what's moving" chapter at national scope)
scripts/build_briefing.py   # OFFLINE: builds data/briefing.json — ONE canonical NATIONAL per-disaster ledger (~5.2K DR+EM+FM declarations, ALL history, all states/territories/COFA/tribal) joining FemaWebDisasterSummaries costs (PA total/A-B/C-G → Cat Z = remainder, IHP HA/ONA, HMGP, IA regs; FEDERAL SHARE ONLY) onto deduped DisasterDeclarationsSummaries identity (state/region/incidentType/declType/dates/tribal; pulled $select+$top/$skip WITHOUT $filter — the WAF 503 combo), PLUS a trailing-12-month per-state monthly PA obligation-activity series (lastObligationDate semantics, COVID split into its own bucket so the client toggle is pure arithmetic). FM is INCLUDED (1,643 FM rows carry real $ — mostly post-fire HMGP); declared-but-no-cost-rollup rows kept with null costs; conservation audit baked in (audit.check). Every rollup (state/region/national/by-year/COVID) is derived CLIENT-SIDE from the rows — units sum to wholes by construction. Needs network (~2 min).
data/briefing.json          # committed (~650KB), LAZILY fetched: powers the Briefing (Newsreel view) — scope selector (US / Region 1-10 / state+territory, hash-routed #newsreel/MI), lede tiles, monthly activity chart, declaration-history chart + ledger table, PA composition incl. Cat Z with the on-screen reconciliation line + the implied non-federal share line (pc/pf/pn columns from nonfed.json — an ESTIMATE, labeled; summary figure stays authoritative), COVID toggle (default excluded), and the third tier of the disaster modal chain (DATA → BRI → NATIONAL: any US disaster gets a cost-breakdown modal with A-B+C-G+Z=total + implied non-federal + verify links). Region/state "what's moving" strips are fetched LIVE per scope (briFetchStrips, ~1-2s, cached per session); national strips read baked newsreel.json.
scripts/build_nonfed.py     # OFFLINE (Briefing P2b): builds data/nonfed.json — per-disaster PROJECT-LEVEL sums (Σ projectAmount, Σ federalShareObligated, project count) from a FULL national PublicAssistanceFundedProjectsDetails sweep (~820K rows, dn-range chunks, resumable cache data/_nonfed_cache.json). impliedNonFederal = cost − federal (the state/local match, an ESTIMATE — project costs reconcile for years; project-level federal ≠ FemaWebDisasterSummaries federal, different datasets). Row-conservation audit vs $inlinecount. Run BEFORE build_briefing.py (which joins it as pc/pf/pn). Refreshed weekly (.github/workflows/refresh-weekly.yml).
data/nonfed.json            # committed (~150KB): {byDisaster[dn]=[projCost,fedOblig,nProjects], audit}. Not fetched by the browser — consumed by build_briefing.py.
scripts/build_county_recent.py # OFFLINE: builds data/recent.json — a trailing ~400-day feed of Region 5 PA (lastObligationDate) + Hazard Mitigation (initialObligationDate) obligations as lean dated rows ({f,s,dn,amt,date,…}; f = county FIPS, null = statewide). Powers the Geography "Recent activity" sub-filter (last 7/30/60/90 days + 1 year). National date-windowed pull (the indexed/fast path — a server-side state filter forces a 15–25s scan, so we filter R5 client-side) paginated past the 10,000-row cap; COVID excluded. Needs network.
data/recent.json            # committed, small (~100KB): raw dated R5 PA+HM obligation rows for the Geography "Recent activity" view. The browser fetches SHORT windows (7–90d) LIVE from OpenFEMA (national-then-filter-R5, ~1–2s); the 1-YEAR window can't be served live (a single national pull truncates at the 10k-row cap) so it reads THIS file, which is also the fallback when a live fetch fails or stalls (12s cap). Refreshed at deploy time (pages.yml) + optionally daily by the Cloudflare worker. Records are obligation ACTIVITY (incl. downward adjustments), not new declarations.
cloudflare/recent-worker.js # OPTIONAL: a Cloudflare Worker that rebuilds recent.json daily (cron → KV) and serves it CORS-open, mirroring build_county_recent.py. Set RECENT_WORKER_URL in index.html to use it; default ("") reads the committed data/recent.json. See cloudflare/README.md.
scripts/build_county_nfip.py # OFFLINE: builds data/nfip.json — Region 5 county×year NFIP CLAIMS rollup (Phase 1) from OpenFEMA FimaNfipClaims v2 (public redacted claims, 2.7M rows nationwide, reloaded MONTHLY R/P1M; pulled per-state for R5). Per county+state: claims count, total paid (building+contents+ICC) with split, claims/paid by year(yearOfLoss), and SFHA in/out share (ratedFloodZone). Policies-in-force/coverage $ are NOT included (Phase 2 — FimaNfipPolicies is 73.6M rows, needs Cloudflare R2/D1). Needs network. See docs/refresh-architecture.md.
data/nfip.json              # committed (~340KB): R5 county×year NFIP claims rollup (counts/paid/byYear/SFHA-in-out per county+state). Surfaced as the Geography "Flood insurance" program lens (measures nfipPaid/nfipClaims/nfipOutPaid): at load applyNfip() merges it onto DECL.counties/states by FIPS (claims-only counties with no FEMA declaration get a minimal synthetic county entry so the map colors them), so it reuses the standard GEO_KEY/GEO_YEARKEY metric machinery + the measure-driven timeline (spans NFIP's 1978– range). Refreshed MONTHLY by .github/workflows/refresh-monthly.yml.
scripts/build_manifest.py   # OFFLINE, no network: builds data/manifest.json — per-file freshness (bytes + internal dataAsOf + the source's OpenFEMA cadence) for every committed data/*.json. Powers the footer "Data as of …" stamp + a quick staleness read.
data/manifest.json          # committed, tiny: per-file freshness manifest (dataAsOf vs sourceCadence). Read by the footer stamp in index.html.
# Scheduled refresh (see docs/refresh-architecture.md): .github/workflows/refresh-daily.yml rebuilds the DAILY snapshots (recent/newsreel/manifest) and auto-commits to main → pages.yml redeploys; refresh-monthly.yml does the same for the MONTHLY NFIP rollup. Cadence is matched to each OpenFEMA source's accrualPeriodicity (PA/HM daily, NFIP monthly).
scripts/enrich.py           # OFFLINE: joins NOAA/USGS hazards onto _disasters_raw.json (NO costs)
scripts/add_history.py      # OFFLINE: pulls older R5 disasters (FEMA costs + hazards) and merges them in
scripts/build_gages.py      # OFFLINE: builds gages.json + per-disaster gage lists; ties crests↔declarations
scripts/build_declared.py   # OFFLINE, ADDITIVE: adds `declared` (original declaration date) to each disasters.json record from OpenFEMA DisasterDeclarationsSummaries (earliest declarationDate per disasterNumber). Touches ONLY `declared` — leaves costs/gages/hz alone. Powers the "Disaster Timelines" view (declaration-lag trend + distribution). Needs network.
scripts/build_national.py   # OFFLINE: builds data/disasters_national.json — a LIGHTWEIGHT nationwide companion (all DR declarations FY2007–2026, COVID/Biological excluded; one row per disaster with only the lag fields disasterNumber/state/title/incidentType/begin/end/declared — NO costs/hazards). Powers the Disaster Timelines "National" toggle. Needs network.
data/disasters_national.json # committed: ~1,196 nationwide disasters, lag fields only (NO costs/hazards/gages). Loaded lazily by the browser when the Disaster Timelines view is toggled to "National". Clicking a national disaster opens a minimal modal (dates + lag + links to fema.gov/OpenFEMA); the rich detail card stays Region-5-only. Rebuild with scripts/build_national.py.
scripts/build_denials.py    # OFFLINE: builds data/denials.json — Region-5 + nationwide DECLARATION DENIALS ("turndowns") from OpenFEMA DeclarationDenials v1. Every row's currentRequestStatus is "Turndown" (the dataset has NO appeal-outcome field). Unlike declarations, denials carry BOTH a request date and a decision date, so two lags exist: incident-start→denial (apples-to-apples with the approval lag charts) and request→denial (FEMA decision turnaround). Scoped to requestStatusDate year >= YEAR_MIN (2007 — matches the approval charts; widen YEAR_MIN to bring in the full ~1953– history). Needs network.
data/denials.json           # committed, small (~80KB): 258 nationwide / 32 R5 denial rows (FY2007+), lean fields (reqNum,region,state,tribal,reqDate,statusDate,begin,reqBegin,reqEnd,type DR/EM,incidentType,name,ia/pa/ih/hm,incidentId). Loaded lazily by the browser when the Disaster Timelines view is first shown; powers the **Declaration Denials** block at the bottom of that view (headline metrics incl. a denial-rate = denied÷(denied+declared) cross-cut vs disasters.json/disasters_national.json, a denial-lag distribution overlaid on the approval-lag distribution, turndowns-by-year with per-year denial rate, and a by-type/state/program breakdown). Honors the SAME Region 5 / National clicker (filters region==5 client-side; national set already includes R5). Clicking a turndown opens a minimal denial modal (request timeline + programs requested + OpenFEMA link). The denials dataset's incidentId/declarationRequestNumber do NOT join cleanly into DisasterDeclarationsSummaries (a successful appeal leaves this dataset), so there is no automatic "denial later overturned" link — the reliable cross-dataset signal is the denial rate. Rebuild with scripts/build_denials.py.
scripts/build_pending.py    # OFFLINE: builds data/pending.json — PENDING declarations (the "Declaration Requests in Process" table) parsed from the latest FEMA **Daily Operations Briefing** PDF. THIS IS THE ONE NON-OPENFEMA SOURCE: OpenFEMA has no feed of requests awaiting a decision; FEMA lists them only in the daily briefing (emailed, not on a stable URL). The govdelivery PDF link for each day's brief is taken from the **Data Liberation Project** archive (https://github.com/data-liberation-project/fema-daily-ops-email-to-rss — CC0, actively/daily maintained, history to Sept 2022). Parsing uses pdfplumber with COLUMN X-COORDINATES so the IA/PA/HM X-marks are attributed to the right program (a row with two X's is correctly PA+HM vs IA+PA). TRUST GATE: asserts IN-PROCESS rows == the header count ("…in Process – N") and EXITS NONZERO WITHOUT WRITING on mismatch (a layout change keeps the last good snapshot). The brief tags terminal states on the incident tail — "– Appeal" / "(Appeal)" (resubmission) and, on decision day, "– Approved"/"– Denied" (shown once, EXCLUDED from the header count); these are parsed into `appeal`/`decision` and decided rows are dropped from the pending list (and feed the Phase-2 harvest). The "Requested" date may be abbreviated ("Jun 3"), spelled out ("June 3"), or carry an explicit year ("Jul 3, 2023") — all handled. Best-effort detail-page parse: the per-request "Disaster Request – <State>" pages (present only for newly-filed requests) carry the INCIDENT PERIOD + COUNTIES REQUESTED (neither is in the summary table) and are merged onto matching rows. Needs network + `pip install pdfplumber`.
data/pending.json           # committed, small (~7KB): {briefDate,briefTitle,briefUrl,headerCount,parsedCount,crossCheckOk,source,rows[]}. Each row: entity(+entityName for tribes/territories),kind(state/tribal),state,region (tribes mapped via curated TRIBE_STATE→state→region, so e.g. Leech Lake Band of Ojibwe→MN→R5),incident,appeal(bool),type DR/EM,ia/pa/hm,requestedRaw("Mon Day"),requestDate(ISO, year INFERRED most-recent≤brief),requestYearInferred,daysWaiting, plus incidentPeriod/incidentPeriodStart/daysSinceIncident/countiesRequested (only when a detail page was present). Loaded lazily by the browser on the Disaster Timelines view; powers the **Declaration requests in process** (pending) block at the bottom of that view (table: entity·incident·type·programs·requested·waiting·incident-period; honors the SAME Region 5 / National clicker via region==5; "Waiting" is recomputed to today client-side; clearly labeled UNOFFICIAL parse with a "source brief ↗" link). CAVEAT: the summary table carries NO incident period — "Waiting" is request→today, not from incident start. Rebuild with scripts/build_pending.py.
.github/workflows/refresh-pending.yml # daily (14:23 + 16:23 UTC fallback) re-parse of the latest Daily Ops Brief → data/pending.json, commit-on-change to main (gated on the cross-check; commit is a no-op when no new brief). Timed just after the Data Liberation Project ingests the morning brief (~13:00–16:00 UTC; brief drops 8:30 a.m. ET).
scripts/build_request_dates.py # OFFLINE (Phase 2): builds data/request_dates.json — REQUEST DATES for DECLARED disasters NATIONWIDE (roadmap #2 widened this beyond R5; the UI filters by region for the Region 5 / National clicker), which OpenFEMA never publishes (it carries a request date only for denials). Harvests the FULL Daily Ops Brief archive (Data Liberation Project history.csv, ~1,330 briefs back to Sept 2022; threaded download + RESUMABLE cache data/_request_cache.json), dedups each request across the days it recurs (key = entity+incident+type+appeal+requested-date; recovers the request date from the first brief that showed it), and matches CONSERVATIVELY to OpenFEMA declarations — preferring the brief's own "Approved" tag near the declaration date, else a single-candidate post-request window; ambiguous → left unmatched. CROSS-CHECK (baked into the file): validates parsed request dates against OpenFEMA DeclarationDenials.declarationRequestDate (ground truth) — currently 63/70 denials found, 56 exact-date, mean 0.3d. COUNTIES (roadmap #3): the per-request "Disaster Request" detail pages (incident period + counties requested) are near-absent in the archive (1/1333 briefs), so counties come from the **Joint Preliminary Damage Assessment** table instead (parsed via pdfplumber extract_tables, in ~every brief): per disaster it attaches AUTHORITATIVE OpenFEMA designated county counts (distinct designated FIPS, split PA/IA — the correctness anchor) PLUS the JPDA "requested" county counts where a single JPDA event matches by state + event-date-within-60d-of-incident-begin (year pinned from the brief it appeared in) AND passes the sanity gate requested>=designated (countyCheck "ok"|"flag"); only "ok" JPDA counts are surfaced. Reuses scripts/build_pending.py's parser. Needs network + pdfplumber.
data/request_dates.json     # committed, small (~6KB): {coverage, denialCrosscheck{denialsInWindow,matchedInBriefs,exactDateAgree,within3dAgree,meanAbsDiffDays,examples}, r5DeclaredConsidered, withDesignatedCounties, withJpdaCounties, byDisaster{<dn>:{requestDate,requestedRaw,declared,reqToDeclLagDays,firstSeen,lastSeen,firstSeenUrl,briefDecision,briefDecisionDate,decisionUrl,confidence,basis,incident,source, designatedPaCounties,designatedIaCounties (OpenFEMA, authoritative), jpdaPaReqCounties,jpdaIaReqCounties,countyCheck (JPDA requested, surfaced only when countyCheck=="ok")}}, denialBriefs{<reqNum>:{firstSeen,firstSeenUrl,decisionDate,decisionUrl,briefRequestDate}}}. 180/293 FY2022+ NATIONAL declared disasters matched (12/16 in R5; 166 with designated counts, ~83 with reconciled JPDA counts). Honors the Region 5 / National clicker (region==5 filter; entries carry state+region). Loaded lazily as REQDATES on the Disaster Timelines view; powers the **Request → decision timing** card (cross-check badge + median request→declaration (approvals, briefs) vs request→denial (denials, OpenFEMA) + the matched-disaster list with designated county counts, clickable → the rich disaster modal, which shows the harvested request date with links to the ACTUAL request/approval briefs + designated counties + reconciled "under PDA" requested counties). The denial modal links each turndown's briefs via denialBriefs. All labeled an UNOFFICIAL Daily-Ops-Brief parse, not OpenFEMA. Rebuild with scripts/build_request_dates.py.
.github/workflows/refresh-request-dates.yml # WEEKLY (Mon 15:43 UTC) re-harvest → data/request_dates.json, commit-on-change to main. Weekly (not daily): a request date only changes the file when a pending request is DECIDED + matches a new declaration. Persists the brief parse cache via actions/cache so a warm run only fetches the week's new briefs (~1 min) vs a cold ~7-min re-harvest.
# --- state-incident declaration & cost model (see analysis/state-declaration-model.md) ---
scripts/build_panel.py      # OFFLINE: county×episode panel (now also ingests Z-type flood/winter via NWS zone→county xwalk)
scripts/build_precip.py …   # OFFLINE additive enrichers: build_precip, build_snow, augment_ari, augment_stage, augment_exposure
scripts/build_state_panel.py# OFFLINE: aggregates county panel → state_panel.json (the modeling table)
scripts/fit_model.py        # OFFLINE: fits declaration+cost models (scikit-learn optional) → data/model.json
scripts/build_predictor.py  # OFFLINE: distills panel+model → predictor.json + triggers.json
scripts/build_seed_artifacts.py # OFFLINE: SEED predictor/triggers/model from disasters.json + gages.json + PoC findings (no panel needed)
data/predictor.json         # committed, small: per-state base rates, triggers, analogs, cost summaries, county drill-down
data/triggers.json          # committed, small: per-disaster characterizing hazard params + how-often/declared-rate
data/model.json             # committed, small: feature importance, base-rate matrix, literature benchmarks
.github/workflows/pages.yml # deploys to Pages on push to main; stamps the build commit into the footer
data/StormEvents_*.csv.gz   # raw NOAA inputs (2008–2025) — GIT-IGNORED (large, regenerable)
data/_disasters_raw.json    # intermediate from the FEMA pull — GIT-IGNORED
data/county_panel.json · data/state_panel.json # GIT-IGNORED model intermediates (regenerable, large)
FEMA Obligation-... .md      # the original research blueprint (background/context)
```

**Pipeline gotcha (costs landmine):** `enrich.py` writes hazards but **not** `costs`.
The authoritative `costs`/`pa`/`ihp` fields come from the FEMA pull (FemaWebDisasterSummaries),
carried in by `add_history.py`. Re-running **`enrich.py` alone would overwrite
`disasters.json` and drop costs + the `gages` lists** — don't. To rebuild from
scratch you must re-pull FEMA costs too. To just add more disasters, use
`add_history.py START_FY END_FY` (additive; leaves existing rows untouched), then
`build_gages.py`.

`index.html` **fetches `data/*.json` at runtime** (same-origin). It therefore
must be served over http(s) — opening the file directly with `file://` will
fail to load data. Local dev: `python3 -m http.server 8000`.

## Data model (`data/disasters.json`, one object per disaster)

- Identity/meta: `disasterNumber, state, title, incidentType, begin, end, fy,
  paDeclared, iaDeclared, countyCount, tags[]` (Flooding/Tornado/Wind/Hail/
  Snow-Ice/Storms/Dam-Levee), `eventTypes[]`, `reportedDamage`.
- `declared`: original federal declaration date (`YYYY-MM-DD`), from
  `scripts/build_declared.py`. Declaration lag (powering the Disaster Timelines
  view) is computed in-browser as `declared − begin` in days — "how long FEMA
  took to declare after the disaster started." Measuring from the incident
  **start** (not end) keeps the comparison fair across short storms and
  long-running events (wildfire seasons, volcanic eruptions, prolonged
  flooding); from-end produced large misleading negatives for long incidents.
  Begin-based lag is essentially always ≥ 0.
- `hz` (measured hazards): `windMph, hailIn, torEF, peakStageFt, rainIn`
  (total incident rainfall, peak county), `rainMeanIn`, `rainDailyMaxIn`
  (highest single-day rainfall), `rainStations` (ACIS stations used),
  `floodReports, snowReports, hailReports, windReports, tornadoes,
  stormEvents, countyMatched`. Rainfall is refreshed/extended by
  `scripts/augment_rain.py` (RCC-ACIS, additive — does not touch costs).
- `costs` (the authoritative figures): `paTotal, paEmergencyAB, paPermanentCG,
  paProjects, hmgp, ihpTotal, ihpHousing, ihpOna, iaRegistrations`.
- `pa`/`ihp` mirror `costs.paTotal`/`costs.ihpTotal` (used by list views).

## Data sources & how the pipeline works

`scripts/enrich.py` runs **offline** (needs network + the Storm Events CSVs in
`data/`) and writes `data/disasters.json`. The browser does NOT build this — it
only reads the committed JSON and makes a few live calls (NWS, USGS).

| Layer | Source | Where |
|---|---|---|
| Declarations, counties, dates | OpenFEMA `DisasterDeclarationsSummaries v2` | offline → `_disasters_raw.json` |
| **Declaration date** (`declared`) | OpenFEMA `DisasterDeclarationsSummaries v2` (`declarationDate`, earliest per disaster) | offline → `declared` |
| **PA obligated / IHP approved + breakdown** | OpenFEMA `FemaWebDisasterSummaries` (+ `PublicAssistanceFundedProjectsDetails` for project counts) | offline → `costs` |
| Wind / hail / tornado, type tags, reported damage | **NOAA Storm Events** bulk CSV (county FIPS + incident-window join) | offline → `hz` |
| Peak river stage | **USGS Water Services** daily values | offline → `hz.peakStageFt` |
| Storm-total rainfall | **RCC-ACIS** (NOAA) daily precip, summed | offline → `hz.rainIn` |
| AHPS flood categories | **NWPS** `api.water.noaa.gov` (per-gauge by LID) | offline → `data/gages.json` |
| Live alerts | **NWS** `api.weather.gov` | runtime (browser) |
| Live gage heights | **USGS** instantaneous values | runtime (browser) |

To rebuild the dataset: download the `StormEvents_details-*.csv.gz` files (URL in
the script header) into `data/`, then `python3 scripts/enrich.py`. Cross-check a
few PA totals against the granular PA Funded Projects worksheets before shipping.

## Domain facts that MUST stay correct (an expert user checks these)

> **Terminology reference:** `docs/fema-assistance-glossary.md` is the canonical glossary
> (IA vs IHP vs HA/ONA vs PA vs HMGP, accounting stages, declaration flags, field→source map).
> Official OpenFEMA field dictionaries are committed under `docs/openfema-definitions/`
> (regenerate with `scripts/fetch_openfema_dictionaries.py`). Read it before touching $ labels.

- **IA ≠ IHP.** **IA** (Individual Assistance) is the umbrella *authorization*; **IHP**
  (Individuals & Households Program) is the only IA program with public per-disaster dollars
  (`ihpTotal` = HA + ONA). **UI labeling splits along the data's own grain: declarations = IA/PA/HM,
  dollars = IHP, registrations = IA.** So the *authorization* badge (ledger Programs column + detail
  modal) reads **IA** for any IA-authorized disaster; the *dollar* figures/sections are labeled
  **IHP** (the program that actually carries public $); the *registrations* count is labeled **IA**
  (source `totalNumberIaApproved`). Per OpenFEMA, "IA-authorized" =
  `ihProgramDeclared OR iaProgramDeclared`. Each `disasters.json` record stores the **raw flags
  distinctly**: `paDeclared`, `ihpDeclared` (raw IH = modern IHP), `iaProgramDeclared` (raw
  legacy IA), `hmProgramDeclared`, plus `iaDeclared` (= **iaAuthorized** = the OR). The IA
  authorization badge fires on the OR (`isIHP(d) || iaProgramDeclared`); the **IHP money section**
  keys off **`ihpDeclared`/`isIHP()`**, NOT the OR — so a legacy `iaProgramDeclared`-only record
  (pre-IHP, no IHP $ series) shows its IHP dollars as **"Not available"**, never **$0 IHP**.
  Classification lives in one place: `survivorState(d)` in `index.html`, mirrored + fixture-tested
  in `scripts/verify_assistance_model.py`. In the current FY2008+ Region 5 ledger
  `iaDeclared = ihpDeclared = (ihpTotal>0) = 34` and `iaProgramDeclared = 8` — but that
  reconciliation is an **observed property of current data, not a universal rule** (it breaks for
  legacy/pre-IHP records).
- **PA is "obligated"; IHP is "approved."** Different accounting stages — never
  conflate or relabel them.
- **PA breakdown must reconcile:** `paEmergencyAB + paPermanentCG + Category Z
  (management) = paTotal`. Category Z is computed as the remainder
  (`paTotal - AB - CG`); without it the breakdown looks wrong. IHP reconciles as
  `ihpHousing + ihpOna = ihpTotal`.
- **Obligations lag and reconcile over years** — recent disasters under-count;
  `paProjects` can be >0 while `paTotal` is still 0.
- **Hazards are a "peak envelope"**: each `hz` value is the max across all
  reports/gages in the affected counties during the incident window. This loses
  extent; the blueprint notes extent/exposure drive obligations more than peak
  intensity. `countyMatched=false` means hazards were aggregated at state level
  (designated areas didn't map to counties) and may overstate the local peak.
- FY2026 declaration indicators used in the UI: statewide **$1.89**/capita,
  countywide **$4.72**/capita, large-project **$1,062,900**, 75→90% cost-share
  **$189**/capita.

## Gotchas / conventions

- **No framework, no build.** Plain HTML/CSS/JS. Typeface is **Public Sans**
  (US Web Design System look); keep the DHS/FEMA navy+gold palette and the
  `.gov` banner.
- All external APIs used at runtime are **CORS-open** (OpenFEMA, USGS
  waterservices, NWS api.weather.gov). NWPS (`api.water.noaa.gov`) is flaky and
  rate-limits — only used offline; its `?usgsId=` filter is unreliable, so
  resolve gauges by LID or by name match in the full gauge list.
- **Storm Events wind magnitude is in knots** — multiply by 1.151 for mph.
- **USGS gage height** for stage: `parameterCd=00065`, `statCd=00003` (daily
  mean is what USGS stores; `00001` returns nothing for most sites). `countyCd`
  must be the **5-digit** state+county FIPS. Filter out values >75 ft — those are
  reservoir/lake-elevation gauges, not river stage.
- `gages.json` flood stages are **official NWS AHPS** for 10/13 gauges
  (`official:true`, with `cats` = action/minor/moderate/major); the other 3 are
  approximate (`official:false`).
- Tap-through is wired by event delegation on `[data-dn]` → `openDetail(dn)`.
  Any element representing a disaster should carry `data-dn="<disasterNumber>"`.
- **Data lineage manifest (the "Provenance Atlas").** `data/lineage.json` is a BUILD
  ARTIFACT — never hand-edit it. Hand-edit only `data/lineage.seed.json` (providers/
  sources/transforms/surfaces + prose), then regenerate with
  `python3 scripts/build_lineage.py` and check with `python3 scripts/verify_lineage.py`
  (the CI "Guardian"; also runs in `.github/workflows/verify-lineage.yml` + after every
  refresh workflow). Rules that keep it honest: (1) **whenever you add/remove a committed
  `data/*.json`, OR add a `fetch("data/…")` in `index.html`, you MUST update the seed +
  rebuild** — the Guardian fails on orphan artifacts and untracked fetches by design.
  (2) The artifact list is enumerated from `data/` but **skips `_`-prefixed files** (the
  gitignore convention for regenerable caches); never commit a `data/_*.json`, and the
  manifest stays deterministic regardless of local caches. (3) `lineage.json` is
  STRUCTURAL ONLY — no freshness baked in (that's joined live from `manifest.json` at
  render). **Multi-session safety (many parallel sessions edit data + the seed):** the
  Guardian is the BACKSTOP — it makes any wiring mistake a VISIBLE red CI check at PR
  time, never silent bad data, so parallel work is safe; the worst case is a resolvable
  conflict, not corruption. To keep conflicts rare and trivial: (a) **rebase on `main`
  right before** touching `lineage.seed.json`; (b) edit it **append-only** — add your
  node(s) at the END of the relevant array and DON'T reformat the file (a deterministic
  `build_lineage.py` writes `lineage.json`, so you only hand-edit the seed); (c) if two
  PRs do collide on the seed, it's a trivial JSON array merge — **keep both sides' nodes,
  then re-run `build_lineage.py && verify_lineage.py`** to reconcile. If seed collisions
  become frequent, split the seed into per-domain fragments (deferred item in
  `docs/lineage-plan.md` §9). Full design: `docs/lineage-plan.md`; portable spec for
  rebuilding the whole feature in other repos: `docs/lineage-spec.md`; the
  process-reproducing discovery prompt: `docs/lineage-discovery-prompt.md`.

## Deployment

Push to `main` → `.github/workflows/pages.yml` deploys to Pages automatically
(Pages was enabled once via Settings → Pages → Source: GitHub Actions; the repo
is public, which Pages requires on a free plan). After merging, the new build is
live in ~1 minute; hard-refresh to bypass cache.

## Workflow norms for this repo

- Develop on a topic branch, push, open a **draft PR**; the maintainer reviews
  and merges. Don't push to `main` directly.
- Keep the OpenFEMA/NOAA/NWS/USGS **non-endorsement disclaimers** in the UI and
  README. Don't add eligibility/rights-determination features.
- When changing numbers or labels, preserve traceability: every figure should be
  reconcilable and linkable back to its OpenFEMA/NOAA/USGS source.

## Roadmap / future options (not yet built)

Parked follow-ups, in rough priority order. None of these are required for the app to
work today — they're enhancements. See `docs/refresh-architecture.md` for the fuller
design rationale behind the NFIP and refresh items.

- ~~**Pending declarations → Phase 2 (request-date harvest).**~~ DONE — `data/pending.json`
  (Phase 1, `scripts/build_pending.py`) parses the latest Daily Ops Brief's "Requests in
  Process" table. `data/request_dates.json` (Phase 2, `scripts/build_request_dates.py`)
  harvests the historical brief archive (Data Liberation Project, back to Sept 2022),
  conservatively matches requests to OpenFEMA declarations/denials, and now covers
  declared disasters **nationwide** (not just R5), cross-checked against OpenFEMA's denial
  request dates (ground truth). Per-disaster designated + JPDA-reconciled county counts are
  also wired in (`countyCheck`). All shown under Disaster Timelines.
- **Capacity-judgment surface — PARKED, likely a separate product, not this app.** The
  owner's original ask (record it, don't lose it): for each pending request, **form a
  judgment on whether the event is likely to exceed state/local capacity** (the core
  Stafford-Act declaration question) by synthesizing **Watch** (live gages/alerts), the
  **Ledger** (analogous past disasters + obligations), and the **predictor/estimator** (base
  rates, triggers, comparables). On scoping this out (see chat log), the conclusion was that
  this is **too ambitious for a documentation tool** — it shades into an actual prediction
  product (ingest live conditions, score against historical analogs, output a
  judgment/likelihood) rather than a traceable-facts reference tool, which is this app's whole
  premise. **Decision: do not build this inside DisasterParameters.** If pursued, it should be
  a **separate, clearly-labeled product** built on top of the same public data (disasters.json,
  gages.json, predictor/triggers, request_dates.json), explicitly framed as a predictive/
  judgment tool rather than a facts ledger — with its own disclaimers about the weak
  predictive power of measured weather (extent/exposure drive obligations more than peak
  intensity — see the hazards note above) and about not being an eligibility determination.
  Logged here purely so the context + caveats aren't lost if it's picked up later.
- **Denials / requests page — analytics cross-cuts.** Built so far on the Disaster Timelines
  page (all scope-aware via the Region 5 / National clicker): **(1) Appeal-outcome tracking** —
  `request_dates.json` carries an `appeals` block (`scripts/build_request_dates.py`
  `extract_appeals()`) reconstructed from the brief archive: each resubmission tagged "– Appeal"
  followed to its "– Approved"/"– Denied" outcome (the only public appeal-outcome trail; OpenFEMA
  has none). Surfaced as the "Appeals & resubmissions" card. **(2) Queue-position percentile** —
  each pending row shows where its current wait sits in the historical request→decision spread
  (`decidedLagPool()`), purely descriptive. **(3) State league table** — denial rate + median
  appr/denial lag per state ("By state: turndown rate & decision speed"). **PARKED for a future
  version: an administration/era cross-cut** — denial rate + median lag sliced by presidential
  administration or by year (policy posture on declarations shifts over time). Easy slice of data
  already in hand (`reqDate`/`begin` → year → era); deferred only to avoid scope creep. Other
  logged-but-unbuilt ideas: brief-archive coverage meter (what % of FY2007+ the Sept-2022+ archive
  covers) and an incident-type denial-rate ranking.

- **NFIP Phase 2 — claim-level drill-down.** Phase 1 (committed `data/nfip.json`) is a
  county×year rollup. Claim-level (`FimaNfipClaims` per-record: `dateOfLoss`, census-tract
  centroid, `ratedFloodZone`, `waterDepth`, `causeOfDamage`, repeated locations) unlocks
  per-event joins to specific disasters, within-county damage clusters, outside-SFHA detail,
  and repetitive-loss identification. The R5 subset is hundreds of thousands of rows — too
  big for Pages/live-fetch, so it needs a **Cloudflare R2 (raw) + D1/KV (queryable) + Worker
  API** backend, refreshed monthly. Budget the **paid Cloudflare plan (~$5/mo)**; ingestion
  must be a cron batch, never an on-demand Worker fetch.
- **NFIP policies / coverage as an exposure denominator.** `FimaNfipPolicies` (73.6M rows,
  monthly) gives policies-in-force + total coverage $ per county — the denominator for
  "claims paid per dollar of coverage" / take-up rate. Too big for Pages; same Cloudflare
  path as Phase 2 (or cheap per-county `$inlinecount` COUNT-only queries for counts without
  coverage $).
- **Wire the Cloudflare worker for `recent.json`.** Deploy `cloudflare/recent-worker.js`
  (daily cron → KV) and set `RECENT_WORKER_URL` in `index.html` so the Geography Recent
  "1 year" window + fallbacks read the daily-fresh feed instead of the committed snapshot.
- **Tier 1b — weekly heavy rebuild.** `county_declarations.json` is rebuilt by a slow,
  order-dependent multi-step pipeline and is currently refreshed by hand. A **weekly**
  GitHub Action (not daily — obligations reconcile over months) should run it and
  **gate the commit on the dollar-conservation audits** (`ihpAudit`, HMGP/mit conservation) —
  refuse to commit if reconciliation breaks. See the Tier table in docs/refresh-architecture.md.
- ~~**Mobile parity for the Recent + Flood-insurance lenses.**~~ DONE — mobile Geography now
  has a program chip row (`.gm-progbar`/GM_PROGS) scoping the measure chips, so the Recent
  (with mobile window chips), Flood-insurance, and state-only Non-disaster lenses (EMPG/AFG/prep
  families) are all selectable on mobile, matching desktop's program→measure pair.
- **The Briefing — evolve the Newsreel into a scope-aware "charted news article" (P1+P2 BUILT,
  spec at `docs/briefing-plan.md`).** DONE: scope selector (US / Region 1–10 / all states+
  territories, hash-routed), lede tiles, monthly PA activity chart, nationalized what's-moving
  strips (baked national + live per-scope), declaration-history chart + ledger table, PA
  composition incl. Cat Z with on-screen reconciliation, COVID toggle (default excluded),
  briefing modal tier (any US disaster → cost breakdown + verify links). P2b BUILT: implied
  non-federal share (scripts/build_nonfed.py national PA Details sweep → nonfed.json →
  briefing pc/pf/pn columns; composition chapter "non-federal bill" line + per-disaster modal
  row, both labeled ESTIMATE with the summary figure authoritative; weekly refresh). P3 BUILT:
  recipients chapter ("Who is getting it" — largest PA applicants live per scope from
  PublicAssistanceFundedProjectsSummaries v1, applicant×disaster grouping with counties merged,
  obligated≠out-for-bid caveat, COVID always excluded) + watch chapter ("What to watch" —
  HMGP§404/PA + §406-share-of-project-cost posture tiles vs the national baseline (pm column =
  Σ mitigationAmount from the nonfed sweep) and a recent-disasters lifecycle list with the
  Cat A-B:C-G emergency-vs-rebuilding bar + "still counting" flag). See
  scripts/build_briefing.py + data/briefing.json in the layout above. P4 BUILT: "How it compares"
  chapter — per-capita distribution strip (all 59 jurisdictions as dots on a log scale,
  scope highlighted, per-state percentile line at state scope; populations baked into
  briefing.json states.p, Census Vintage-2024/Island-Areas-2020/UN-COFA, a labeled
  today's-population simplification), a league table ranked by all-time PA/capita
  (declarations · PA · PA/capita · HMGP/PA · §406 share · 12-mo activity, US baseline row,
  tap a row to RE-SCOPE the whole briefing), and shared-y-scale monthly-activity small
  multiples at region scope. All five plan phases complete.
- **Refresh failure alerting.** The daily/monthly refresh workflows are best-effort + commit-
  on-change; add an Actions failure notification so a silently-failing pull (stale data looking
  fresh) is surfaced.
- **SBA disaster loan data (IA section) — PARKED pending better data, research is CURSORY/INITIAL.**
  See `docs/sba-data-feasibility.md` for the full writeup — flagged here so it isn't lost. Short
  version: `data.sba.gov` publishes per-fiscal-year XLSX Home/Business loan files with a
  `FEMA Disaster Number` join column, but (1) the newest published year is FY2022 (stale by
  several years vs this ledger), and (2) only ~10-12% of a sampled Region 5 fiscal year's rows
  actually carry that FEMA number — the rest are SBA administrative/EIDL-only declarations with
  no clean tie into `disasters.json`. Only one fiscal year was checked; this was a first pass,
  not a survey. Untested but promising alternates worth checking before building anything:
  `api.usaspending.gov` (fresher award-level data, unclear if SBA disaster loans are queryable
  at county grain), `disasterloanassistance.sba.gov` (SBA's newer portal, possibly a live
  successor to the stale bulk export), and `recovery.fema.gov`'s Spending Explorer (tracks the
  SBA Disaster Loan Fund account alongside the FEMA Disaster Relief Fund since 2017). Do not
  build an SBA measure/layer off the data described in the doc without re-checking those first.
- **PA Second Appeals Tracker (OpenFEMA) — PARKED, belongs in Geography first.** FEMA publishes
  first/second-appeal outcomes on PA project determinations as its own dataset (the "FEMA Public
  Assistance Second Appeals Tracker," migrating to OpenFEMA CSV/JSON/Parquet) — this is distinct
  from the declaration-request appeals already surfaced on the Disaster Timelines view
  (`request_dates.json`'s `appeals` block, sourced from the Daily Ops Brief archive). Not yet
  pulled/committed here. Raised while scoping the Disaster Operations Planner's county
  drill-down (owner wants per-county PA appeal history there too), but the owner explicitly
  wants it built in the **Geography tab first** (a per-county/per-disaster appeal lens,
  mirroring the existing HMGP/mitigation county pattern), with the planner then reading the
  same data. Logged here so it isn't lost; not started.
