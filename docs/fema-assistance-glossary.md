# FEMA disaster-assistance glossary (IA · IHP · HA · ONA · PA · HMGP)

The canonical terminology reference for this project. It exists because it is easy to
**conflate Individual Assistance (IA) with the Individuals & Households Program (IHP)** — they
are not the same thing, they are reported by different OpenFEMA flags, and only one of them has
public dollar figures. Every number this app shows should be reconcilable back to a term
defined here and a field listed in [`openfema-definitions/`](openfema-definitions/INDEX.md).

> **Not endorsed by FEMA.** Built on public OpenFEMA/NOAA/USGS/NWS open data.

---

## 1. The program hierarchy

A presidential **major disaster declaration** can authorize three independent assistance
streams. Each is a separate flag in OpenFEMA `DisasterDeclarationsSummaries`:

```
Major Disaster Declaration
├─ PA  — Public Assistance ....................... paProgramDeclared   (to governments/nonprofits)
├─ IA  — Individual Assistance (umbrella) ........ iaProgramDeclared + ihProgramDeclared (to people)
│       ├─ IHP — Individuals & Households Program . ihProgramDeclared  ← the ONLY IA program with public $
│       │        ├─ HA  — Housing Assistance
│       │        └─ ONA — Other Needs Assistance
│       ├─ Crisis Counseling Program (CCP)
│       ├─ Disaster Unemployment Assistance (DUA)
│       ├─ Disaster Legal Services (DLS)
│       ├─ Disaster Case Management (DCM)
│       └─ Disaster SNAP (D-SNAP)
└─ HM  — Hazard Mitigation ....................... hmProgramDeclared   (HMGP / §404, post-disaster)
```

The non-disaster grant layers this app also tracks (separate from any single declaration):
**non-disaster HMA** (FMA/BRIC/PDM/LPDM/RFC/SRL), **EMPG**, and **AFG** — see §6.

---

## 2. Accounting stages — never conflate these

Different programs are reported at different points in the funding lifecycle. The words are
**not interchangeable**, and mixing them misstates the data.

| Term | Meaning | Applies to |
|---|---|---|
| **Obligated** | FEMA has legally committed the funds (a later, firmer stage). Lags for years; recent disasters under-count. | **PA, HMGP** |
| **Approved** | FEMA approved the amount for award (an earlier stage). | **IHP (incl. HA, ONA)** |
| **Registrations** | Count of applications approved — people, not dollars. | **IA / IHP** (`iaRegistrations`) |

Reconciliation identities the data must satisfy:
- `paEmergencyAB + paPermanentCG + Category Z (management) = paTotal`
- `ihpHousing (HA) + ihpOna (ONA) = ihpTotal`

---

## 3. Individual Assistance (IA) vs. Individuals & Households Program (IHP)

This is the distinction the project most often gets wrong, so it is spelled out in full.

### IA — Individual Assistance (the umbrella)
The **broad declaration category** that authorizes FEMA to help disaster survivors directly.
It is an *authorization*, not a single pot of money: it umbrellas IHP **plus** Crisis
Counseling, Disaster Unemployment Assistance, Disaster Legal Services, Disaster Case
Management, and D-SNAP. Of these, **only IHP publishes per-disaster dollar figures** in
OpenFEMA; the others have no per-disaster dollar field, so an "IA total dollars" distinct from
IHP **cannot be computed from public data**.

- OpenFEMA flag: **`iaProgramDeclared`** — *"Denotes whether the Individual Assistance program
  was declared for this disaster."*
- Source: [Individual Assistance](https://www.fema.gov/assistance/individual) ·
  [Individual Assistance Program & Policy Guide (IAPPG)](https://www.fema.gov/sites/default/files/documents/fema_iappg-1.1.pdf)

### IHP — Individuals & Households Program (the direct-$ program)
The specific program within IA that provides **financial assistance and direct services to
eligible individuals and households** with uninsured/underinsured disaster losses. Reported as
**approved** dollars, split into HA + ONA. **This is the number this app shows for the
individual side.**

- OpenFEMA flag: **`ihProgramDeclared`** — *"Denotes whether the Individuals and Households
  program was declared for this disaster."*
- Dollars: `totalAmountIhpApproved` (= `ihpTotal`).
- Source: [Individuals & Households Program](https://www.fema.gov/assistance/individual/program) ·
  [IHP fact sheet](https://www.fema.gov/fact-sheet/fema-individuals-and-households-program) ·
  [IHP Unified Guidance (PDF)](https://www.fema.gov/sites/default/files/2020-05/IHP_Unified_Guidance_FINAL_09272016_0.pdf)

### FEMA's official rule for "was IA authorized?"
The OpenFEMA dictionary states verbatim, on **both** flag fields:

> *"To determine which FEMA events have been authorized to receive Individual Assistance, use
> **both** ihProgramDeclared and iaProgramDeclared."*

So: **IA-authorized = `ihProgramDeclared` OR `iaProgramDeclared`.**

#### What that means for this project's Region 5 dataset (FY2007–2026, 80 disasters)
- `ihProgramDeclared` (IHP) = **34** — the modern, consistently-populated flag; **reconciles
  exactly** with `costs.ihpTotal > 0` (both 34).
- `iaProgramDeclared` (IA) = **8** — all FY2008–09 "Severe Storm" declarations; a **legacy**
  flag, every one of which is *also* IH. After FY2009 no Region 5 disaster sets it.
- Because IA ⊆ IHP here, **IA-authorized = the union = 34**. We therefore store the declared
  flag as the OR of both and surface the program as **IHP** in the UI.

> **Historical data bug (fixed):** earlier builds set `iaDeclared = bool(ihProgramDeclared)`
> *and never pulled `iaProgramDeclared`*, and the committed value had gone stale at **21**
> (13 disasters with IHP dollars were missing the flag). The flag is now corrected to **34** =
> `ihProgramDeclared OR iaProgramDeclared`, with `iaProgramDeclared` kept as a provenance field.
> See `scripts/patch_ia_flag.py`.

### Legacy IA-only declarations (pre-IHP) — and why they're not "$0 IHP"
A declaration flagged with **only** the legacy `iaProgramDeclared` (no `ihProgramDeclared`)
generally **predates the modern IHP program** and carries **no comparable IHP dollar series**
(`totalAmountIhpApproved` is null) — predecessor individual aid (e.g. the former Individual &
Family Grant program) is not recorded in the modern field. Evidence (live OpenFEMA):

- **Region 5:** 152 such IA-only declarations, **all FY1953–2002**; none in the current
  FY2008+ ledger.
- **National:** ~1,199, all **≤FY2007**, dropping off a cliff after FY2002 (IHP was created by
  the Disaster Mitigation Act of 2000, effective ~2003).
- **Rare anomaly:** a few records have `iaProgramDeclared=true`, `ihProgramDeclared=false`, *and*
  positive IHP dollars (e.g. **DR-1582**, American Samoa, Typhoon Olaf, FY2005 — a
  historical/territorial transition). Real dollars are preserved and shown; the flag mismatch is
  surfaced in analyst metadata, not hidden.

Therefore the UI keys "IHP" off **`ihpDeclared`** (the modern program), **not** the
`iaDeclared` OR — so a legacy/IA-only record is shown as **Legacy Individual Assistance
(not available)**, never as **$0 IHP**.

> **Current-data note:** in the FY2008+ Region 5 ledger every IA-authorized disaster is *also*
> IHP-declared with positive IHP $, so `iaDeclared`, `ihpDeclared`, and `ihpTotal>0` all = 34.
> That reconciliation is an **observed property of the current data, not a universal rule** — it
> breaks for legacy/pre-IHP records, which is exactly what the guard handles.

#### Survivor-assistance display states
`survivorState(d)` (in `index.html`, mirrored in `scripts/verify_assistance_model.py`) maps each
disaster to one of:

| State | Condition | Card shows |
|---|---|---|
| `IHP_WITH_AWARDS` | `ihpDeclared` & IHP `$>0` | IHP approved + HA/ONA + registrations |
| `IHP_NO_AWARDS` | `ihpDeclared` & IHP `$=0` | "IHP authorized · no approved assistance reported" (not $0) |
| `IA_ONLY` | `iaProgramDeclared` & not `ihpDeclared` & IHP `$=0` | "Legacy Individual Assistance · Not available" + era note |
| `IA_ONLY_ANOMALY` | `iaProgramDeclared` & not `ihpDeclared` & IHP `$>0` | real IHP $ + a source-flag note |
| `NONE` | no IA/IHP authorization | compact "no IA/IHP authorization recorded" |

(`isIHP(d)` = the first, second, and fourth states — i.e. show an IHP money section. The ledger
"IHP" badge fires only on `isIHP`; otherwise a muted **IA** badge marks legacy authorization.)

---

## 4. Inside IHP: HA vs. ONA

| | **HA — Housing Assistance** | **ONA — Other Needs Assistance** |
|---|---|---|
| Field | `totalAmountHaApproved` → `ihpHousing` | `totalAmountOnaApproved` → `ihpOna` |
| Covers | Temporary housing (financial + direct), lodging-expense reimbursement, home-repair and home-replacement assistance | Other disaster-caused necessary expenses & serious needs: personal property, medical/dental, funeral, childcare, transportation, moving & storage, misc. |
| Cost share | Federally funded | Some categories cost-shared 75% federal / 25% state |

Source: [Assistance for Housing and Other Needs](https://www.fema.gov/assistance/individual/housing) ·
[IHP Unified Guidance (PDF)](https://www.fema.gov/sites/default/files/2020-05/IHP_Unified_Guidance_FINAL_09272016_0.pdf).

**Availability caveat for this app:** the HA/ONA split is only carried **per disaster** (in
`data/disasters.json` `costs.ihpHousing`/`ihpOna`, shown in the Ledger detail modal). It is
**not** aggregated geographically — county/state objects in `data/county_declarations.json`
carry only `ihpApproved` (and `iaRegistrations` at county level), so the Geography views lead
with **IHP approved**, not an HA/ONA breakdown.

---

## 5. Public Assistance (PA)

Reimburses **state/local governments and certain nonprofits** for emergency response and
rebuilding. Reported as **obligated**.

- Flag: `paProgramDeclared`. Dollars: `totalObligatedAmountPa` (= `paTotal`).
- Category groups: **Emergency** (A debris, B emergency protective measures) →
  `totalObligatedAmountCatAb` (`paEmergencyAB`); **Permanent** (C roads/bridges, D water
  control, E buildings/equipment, F utilities, G parks/other) →
  `totalObligatedAmountCatC2g` (`paPermanentCG`); **Category Z** = management costs, computed
  as the remainder `paTotal − AB − CG`.
- Source: [PA Program Overview](https://www.fema.gov/assistance/public/program-overview) ·
  [PA Program & Policy Guide](https://www.fema.gov/assistance/public/policy-guidance-fact-sheets).

---

## 6. Mitigation & preparedness layers

| Layer | What | Stage | Field(s) → our keys |
|---|---|---|---|
| **HMGP (§404)** | Post-disaster hazard-mitigation grants tied to a declaration | obligated | `HazardMitigationAssistanceProjects` (programArea=HMGP) → `hmgp` / `hmgpObligated` |
| **Non-disaster HMA** | FMA, BRIC, PDM, LPDM, RFC, SRL — mitigation *not* tied to a single disaster | obligated | `HazardMitigationAssistanceProjects` (all except HMGP) → `mitObligated` |
| **EMPG** | Emergency Management Performance Grants (state preparedness) | fiscal year | `EmergencyManagementPerformanceGrants` → `empg` |
| **AFG** | Assistance to Firefighters Grants (non-disaster) | fiscal year | `NonDisasterAssistanceFirefighterGrants` → `afg` |

Source: [Hazard Mitigation Assistance](https://www.fema.gov/grants/mitigation) ·
[Hazard Mitigation Grant Program](https://www.fema.gov/grants/mitigation/hazard-mitigation).

---

## 7. Field → source map (quick reference)

| Our key (`disasters.json` / `county_declarations.json`) | OpenFEMA dataset · field | Stage |
|---|---|---|
| `paDeclared` | DisasterDeclarationsSummaries · `paProgramDeclared` | flag |
| `iaDeclared` | DisasterDeclarationsSummaries · `ihProgramDeclared` **OR** `iaProgramDeclared` | flag |
| `iaProgramDeclared` (provenance) | DisasterDeclarationsSummaries · `iaProgramDeclared` | flag |
| `costs.paTotal` / `pa` · `paObligated` | FemaWebDisasterSummaries · `totalObligatedAmountPa` | obligated |
| `costs.paEmergencyAB` | FemaWebDisasterSummaries · `totalObligatedAmountCatAb` | obligated |
| `costs.paPermanentCG` | FemaWebDisasterSummaries · `totalObligatedAmountCatC2g` | obligated |
| `costs.paProjects` · `paProjects` | PublicAssistanceFundedProjectsDetails (count) | obligated |
| `costs.ihpTotal` / `ihp` · `ihpApproved` | FemaWebDisasterSummaries · `totalAmountIhpApproved` | approved |
| `costs.ihpHousing` (HA) | FemaWebDisasterSummaries · `totalAmountHaApproved` | approved |
| `costs.ihpOna` (ONA) | FemaWebDisasterSummaries · `totalAmountOnaApproved` | approved |
| `costs.iaRegistrations` · `iaRegistrations` | FemaWebDisasterSummaries · `totalNumberIaApproved` | count |
| `costs.hmgp` · `hmgpObligated` | HazardMitigationAssistanceProjects (HMGP) | obligated |
| `mitObligated` | HazardMitigationAssistanceProjects (non-HMGP) | obligated |
| `empg` / `afg` | EmergencyManagementPerformanceGrants / NonDisasterAssistanceFirefighterGrants | fiscal yr |

Full field dictionaries: [`openfema-definitions/`](openfema-definitions/INDEX.md)
(regenerate with `python3 scripts/fetch_openfema_dictionaries.py`).

---

## 8. One-line reminders

- **PA is obligated; IHP is approved.** Different stages — never relabel one as the other.
- **IA is the umbrella; IHP is the program.** The UI labels the program **IHP** because that
  is what the dollars are. "IA-authorized" = `ihProgramDeclared OR iaProgramDeclared`.
- **Only IHP has public per-disaster dollars** on the individual side. There is no separable
  "IA dollars."
- **HA + ONA = IHP**, but the split is per-disaster only (Ledger modal), not geographic.
- **Obligations lag**; recent disasters under-count and reconcile upward over years.
