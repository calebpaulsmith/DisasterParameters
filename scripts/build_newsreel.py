#!/usr/bin/env python3
"""
Build data/newsreel.json — a small "latest obligations" reel for the two FEMA
programs that publish a per-item obligation DATE you can sort on:

  - Public Assistance  (PublicAssistanceFundedProjectsDetails) -> lastObligationDate
  - Hazard Mitigation  (HazardMitigationAssistanceProjects v4) -> initialObligationDate
                        (HMGP + the non-disaster HMA programs: FMA/BRIC/PDM/…)

For each program, two strips, Region 5 only (IL/IN/MI/MN/OH/WI):
  - "latest"  : the most recent N obligation events (orderby <date> desc)
  - "biggest" : the largest single obligations in the last 6 months
                (orderby federalShareObligated desc within the date window)

WHY ONLY THESE TWO PROGRAMS
  IHP is individual/household-level and carries no obligation/approval date
  (only appliedDate); preparedness grants (AFG/EMPG) are annual (fiscalYear only,
  no obligation date). Neither supports a per-item "latest obligated" reel.

COVID-19 IS EXCLUDED
  The six R5 COVID-19 (incidentType "Biological") declarations dwarf weather PA
  (~7x a state's entire weather PA) and are kept in their own view. We drop them
  here too — by incidentType for PA and by disasterNumber for both programs — so
  the reel stays about weather/flood/storm obligations, consistent with the ledger.

NOTE ON DATES
  lastObligationDate reflects the latest obligation ACTIVITY, which includes
  downward adjustments (deobligations) — federalShareObligated can decrease and
  still bump the date. So "latest" means latest activity, not only new money.

CORS-open OpenFEMA; offline/regenerable. Re-run any time:
    python3 scripts/build_newsreel.py
"""
import os, json, urllib.request, urllib.parse, datetime as dt

DATA = os.path.join(os.path.dirname(__file__), "..", "data")
PA_URL = "https://www.fema.gov/api/open/v2/PublicAssistanceFundedProjectsDetails"
HM_URL = "https://www.fema.gov/api/open/v4/HazardMitigationAssistanceProjects"

R5_ABBR = ["IL", "IN", "MI", "MN", "OH", "WI"]
R5_NAME = ["Illinois", "Indiana", "Michigan", "Minnesota", "Ohio", "Wisconsin"]
ABBR = {"Illinois": "IL", "Indiana": "IN", "Michigan": "MI",
        "Minnesota": "MN", "Ohio": "OH", "Wisconsin": "WI"}
COVID_DNS = {4489, 4494, 4507, 4515, 4520, 4531}   # R5 COVID-19 (Biological)
N_LATEST = 5
N_BIGGEST = 5
WINDOW_DAYS = 183                                  # ~6 months


def get(url):
    req = urllib.request.Request(url, headers={"User-Agent": "DisasterParameters/newsreel"})
    with urllib.request.urlopen(req, timeout=90) as r:
        return json.loads(r.read().decode("utf-8", "replace"))


def q(base, flt, orderby, select, top=60):
    url = (f"{base}?$filter={urllib.parse.quote(flt)}"
           f"&$orderby={urllib.parse.quote(orderby)}"
           f"&$select={urllib.parse.quote(select)}"
           f"&$top={top}&$format=json")
    key = base.rstrip("/").split("/")[-1]
    return (get(url) or {}).get(key, [])


def n(x):
    try:
        return round(float(x))
    except Exception:
        return 0


def cutoff_iso():
    d = dt.date.today() - dt.timedelta(days=WINDOW_DAYS)
    return d.isoformat() + "T00:00:00.000Z"


# ---- Public Assistance --------------------------------------------------------
def pa_states_flt():
    return "(" + " or ".join(f"stateAbbreviation eq '{s}'" for s in R5_ABBR) + ")"


def pa_row(r):
    return {
        "program": "PA",
        "dn": r.get("disasterNumber"),
        "state": r.get("stateAbbreviation"),
        "title": (r.get("applicationTitle") or "").strip(),
        "category": r.get("damageCategoryDescrip"),
        "county": r.get("county"),
        "amount": n(r.get("federalShareObligated")),
        "date": (r.get("lastObligationDate") or "")[:10],
    }


def build_pa():
    # PA (v2) rejects 'ne null'; nulls already sort last under 'desc', so omit it.
    base = f"{pa_states_flt()} and incidentType ne 'Biological'"
    latest = q(PA_URL,
               base,
               "lastObligationDate desc",
               "disasterNumber,stateAbbreviation,applicationTitle,damageCategoryDescrip,county,federalShareObligated,lastObligationDate")
    latest = [pa_row(r) for r in latest if r.get("disasterNumber") not in COVID_DNS][:N_LATEST]

    biggest = q(PA_URL,
                f"lastObligationDate ge '{cutoff_iso()}' and {base}",
                "federalShareObligated desc",
                "disasterNumber,stateAbbreviation,applicationTitle,damageCategoryDescrip,county,federalShareObligated,lastObligationDate")
    biggest = [pa_row(r) for r in biggest if r.get("disasterNumber") not in COVID_DNS][:N_BIGGEST]
    return latest, biggest


# ---- Hazard Mitigation --------------------------------------------------------
def hm_states_flt():
    return "(" + " or ".join(f"state eq '{s}'" for s in R5_NAME) + ")"


def hm_row(r):
    return {
        "program": "HM",
        "programArea": r.get("programArea"),
        "dn": r.get("disasterNumber"),
        "state": ABBR.get(r.get("state"), r.get("state")),
        "title": (r.get("projectType") or "").strip(),
        "recipient": r.get("subrecipient") or r.get("recipient"),
        "county": r.get("county"),
        "amount": n(r.get("federalShareObligated")),
        "date": (r.get("initialObligationDate") or "")[:10],
    }


def build_hm():
    sel = "disasterNumber,state,programArea,projectType,subrecipient,recipient,county,federalShareObligated,initialObligationDate"
    latest = q(HM_URL,
               f"initialObligationDate ne null and {hm_states_flt()}",
               "initialObligationDate desc", sel)
    latest = [hm_row(r) for r in latest if r.get("disasterNumber") not in COVID_DNS][:N_LATEST]

    biggest = q(HM_URL,
                f"initialObligationDate ge '{cutoff_iso()}' and {hm_states_flt()}",
                "federalShareObligated desc", sel)
    biggest = [hm_row(r) for r in biggest
               if r.get("disasterNumber") not in COVID_DNS and n(r.get("federalShareObligated")) > 0][:N_BIGGEST]
    return latest, biggest


def main():
    pa_latest, pa_biggest = build_pa()
    hm_latest, hm_biggest = build_hm()
    out = {
        "generated": dt.date.today().isoformat(),
        "windowDays": WINDOW_DAYS,
        "source": "OpenFEMA PublicAssistanceFundedProjectsDetails (lastObligationDate) + "
                  "HazardMitigationAssistanceProjects v4 (initialObligationDate), Region 5, COVID-19 excluded",
        "note": "PA is obligated; 'latest' = latest obligation activity (includes downward "
                "adjustments). HM covers HMGP + non-disaster HMA (FMA/BRIC/PDM). Real OpenFEMA "
                "figures — not endorsed by FEMA.",
        "programs": {
            "PA": {"label": "Public Assistance", "latest": pa_latest, "biggest": pa_biggest},
            "HM": {"label": "Hazard Mitigation", "latest": hm_latest, "biggest": hm_biggest},
        },
    }
    json.dump(out, open(os.path.join(DATA, "newsreel.json"), "w"), separators=(",", ":"))
    print(f"wrote data/newsreel.json — PA: {len(pa_latest)} latest / {len(pa_biggest)} biggest; "
          f"HM: {len(hm_latest)} latest / {len(hm_biggest)} biggest")
    for tag, rows in (("PA latest", pa_latest), ("HM latest", hm_latest)):
        for r in rows:
            print(f"  {tag}: {r['date']} {r['state']} DR{r['dn']} ${r['amount']:,} {r.get('title','')[:40]}")


if __name__ == "__main__":
    main()
