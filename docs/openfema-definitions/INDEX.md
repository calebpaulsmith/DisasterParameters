# OpenFEMA field dictionaries (committed reference)

Official field definitions for every OpenFEMA dataset this project sources numbers
from, pulled from the `OpenFemaDataSetFields` endpoint. These are documentation only —
the app does not read them at runtime. Regenerate with
`python3 scripts/fetch_openfema_dictionaries.py`.

_Last fetched: 2026-06-24._

| Dataset | Fields | What we use it for |
|---|---:|---|
| [`DisasterDeclarationsSummaries`](DisasterDeclarationsSummaries.json) | 28 | Declarations, counties, dates, and the program-declared flags (pa/ia/ih/hm). |
| [`FemaWebDisasterSummaries`](FemaWebDisasterSummaries.json) | 14 | PA obligated + Cat A-B/C-G, HMGP, IHP approved + HA/ONA, IA registrations. |
| [`PublicAssistanceFundedProjectsDetails`](PublicAssistanceFundedProjectsDetails.json) | 31 | Per-project PA obligated $ + project counts (and lastObligationDate). |
| [`IndividualsAndHouseholdsProgramValidRegistrations`](IndividualsAndHouseholdsProgramValidRegistrations.json) | 100 | Per-registration IHP (HA/ONA) detail used for county IHP rollups. |
| [`HazardMitigationAssistanceProjects`](HazardMitigationAssistanceProjects.json) | 33 | HMGP (§404) + non-disaster HMA project obligations (initialObligationDate). |
| [`EmergencyManagementPerformanceGrants`](EmergencyManagementPerformanceGrants.json) | 9 | EMPG non-disaster preparedness grants (state-level). |
| [`NonDisasterAssistanceFirefighterGrants`](NonDisasterAssistanceFirefighterGrants.json) | 9 | AFG non-disaster firefighter grants (with recipient fire departments). |

See [`../fema-assistance-glossary.md`](../fema-assistance-glossary.md) for the plain-
language program glossary (IA, IHP, HA, ONA, PA, HMGP) and how these fields map to the
keys in `data/disasters.json` and `data/county_declarations.json`.
