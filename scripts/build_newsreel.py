#!/usr/bin/env python3
"""
Build data/newsreel.json — a small "latest obligations" reel for the two FEMA
programs that publish a per-item obligation DATE you can sort on:

  - Public Assistance  (PublicAssistanceFundedProjectsDetails) -> lastObligationDate
  - Hazard Mitigation  (HazardMitigationAssistanceProjects v4) -> initialObligationDate
                        (§404 HMGP + the non-disaster HMA programs: FMA/BRIC/PDM/…)
  - Section 406 mitigation -> the `mitigationAmount` carried on each PA project
                        (hardening built into a PA permanent-work repair; a SUBSET
                        of that project's PA obligation, dated by lastObligationDate)

For each program, two strips, NATIONAL scope (the Briefing's default; region/
state scopes run the same queries live in-browser with scope filters):
  - "latest"  : the most recent N obligation events (orderby <date> desc)
  - "biggest" : the largest single obligations in the last 6 months
                (orderby federalShareObligated desc within the date window)

WHY ONLY THESE TWO PROGRAMS
  IHP is individual/household-level and carries no obligation/approval date
  (only appliedDate); preparedness grants (AFG/EMPG) are annual (fiscalYear only,
  no obligation date). Neither supports a per-item "latest obligated" reel.

COVID-19 IS EXCLUDED
  COVID PA (~$98B national) dwarfs weather obligations. Dropped by incidentType
  ('Biological') for PA/§406 server-side, and for HM (no incidentType field) by
  disasterNumber against the COVID dn set from data/briefing.json (falls back to
  a live Biological-dn pull if briefing.json is absent). Run build_briefing.py
  first when rebuilding both.

NOTE ON DATES
  lastObligationDate reflects the latest obligation ACTIVITY, which includes
  downward adjustments (deobligations) — federalShareObligated can decrease and
  still bump the date. So "latest" means latest activity, not only new money.

CORS-open OpenFEMA; offline/regenerable. Re-run any time:
    python3 scripts/build_newsreel.py
"""
import os, json, time, urllib.request, urllib.parse, datetime as dt
from build_briefing import STATE_NAMES   # single source of truth for state names

DATA = os.path.join(os.path.dirname(__file__), "..", "data")
PA_URL = "https://www.fema.gov/api/open/v2/PublicAssistanceFundedProjectsDetails"
HM_URL = "https://www.fema.gov/api/open/v4/HazardMitigationAssistanceProjects"
# HM carries full state names; map back to abbreviations (unknown names pass through)
ABBR = {v: k for k, v in STATE_NAMES.items()}

N_LATEST = 5
N_BIGGEST = 5
WINDOW_DAYS = 183                                  # ~6 months


def get(url, retries=4):
    req = urllib.request.Request(url, headers={"User-Agent": "DisasterParameters/newsreel"})
    for i in range(retries):
        try:
            with urllib.request.urlopen(req, timeout=90) as r:
                return json.loads(r.read().decode("utf-8", "replace"))
        except Exception:
            if i == retries - 1:
                raise
            time.sleep(2 ** i)   # OpenFEMA 503s are transient; back off and retry


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


# ---- COVID disaster-number set (for HM, which has no incidentType) ------------
def covid_dns():
    try:
        b = json.load(open(os.path.join(DATA, "briefing.json")))
        c = b["cols"]
        i_dn, i_cv = c.index("dn"), c.index("covid")
        return {r[i_dn] for r in b["d"] if r[i_cv]}
    except Exception:
        rows = []
        skip = 0
        while True:
            u = ("https://www.fema.gov/api/open/v2/DisasterDeclarationsSummaries"
                 f"?$filter={urllib.parse.quote(chr(39).join(['incidentType eq ','Biological','']))}"
                 f"&$top=10000&$skip={skip}&$format=json&$metadata=off")
            chunk = (get(u) or {}).get("DisasterDeclarationsSummaries", [])
            rows.extend(chunk)
            if len(chunk) < 10000:
                break
            skip += len(chunk)
        return {r.get("disasterNumber") for r in rows}


# ---- Public Assistance --------------------------------------------------------


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
    base = "incidentType ne 'Biological'"
    latest = q(PA_URL,
               base,
               "lastObligationDate desc",
               "disasterNumber,stateAbbreviation,applicationTitle,damageCategoryDescrip,county,federalShareObligated,lastObligationDate")
    latest = [pa_row(r) for r in latest][:N_LATEST]

    biggest = q(PA_URL,
                f"lastObligationDate ge '{cutoff_iso()}' and {base}",
                "federalShareObligated desc",
                "disasterNumber,stateAbbreviation,applicationTitle,damageCategoryDescrip,county,federalShareObligated,lastObligationDate")
    biggest = [pa_row(r) for r in biggest][:N_BIGGEST]
    return latest, biggest


# ---- Section 406 mitigation (baked into PA permanent-work repairs) ------------
# Not a separate program: it's the `mitigationAmount` carried on each PA project.
# Distinct from §404 HMGP (the standalone Hazard Mitigation card above).
M406_SEL = ("disasterNumber,stateAbbreviation,applicationTitle,damageCategoryDescrip,"
            "county,mitigationAmount,federalShareObligated,lastObligationDate")


def m406_row(r):
    return {
        "program": "M406",
        "dn": r.get("disasterNumber"),
        "state": r.get("stateAbbreviation"),
        "title": (r.get("applicationTitle") or "").strip(),
        "category": r.get("damageCategoryDescrip"),
        "county": r.get("county"),
        "amount": n(r.get("mitigationAmount")),      # the §406 mitigation portion
        "paShare": n(r.get("federalShareObligated")),  # total obligated on the repair
        "date": (r.get("lastObligationDate") or "")[:10],
    }


def build_m406():
    base = "mitigationAmount gt 0 and incidentType ne 'Biological'"
    latest = q(PA_URL, base, "lastObligationDate desc", M406_SEL)
    latest = [m406_row(r) for r in latest][:N_LATEST]

    biggest = q(PA_URL,
                f"lastObligationDate ge '{cutoff_iso()}' and {base}",
                "mitigationAmount desc", M406_SEL)
    biggest = [m406_row(r) for r in biggest][:N_BIGGEST]
    return latest, biggest


# ---- Hazard Mitigation --------------------------------------------------------


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


def build_hm(cv):
    sel = "disasterNumber,state,programArea,projectType,subrecipient,recipient,county,federalShareObligated,initialObligationDate"
    latest = q(HM_URL, "initialObligationDate ne null", "initialObligationDate desc", sel)
    latest = [hm_row(r) for r in latest if r.get("disasterNumber") not in cv][:N_LATEST]

    biggest = q(HM_URL, f"initialObligationDate ge '{cutoff_iso()}'",
                "federalShareObligated desc", sel)
    biggest = [hm_row(r) for r in biggest
               if r.get("disasterNumber") not in cv and n(r.get("federalShareObligated")) > 0][:N_BIGGEST]
    return latest, biggest


def main():
    cv = covid_dns()
    print(f"covid dn set: {len(cv)}")
    pa_latest, pa_biggest = build_pa()
    hm_latest, hm_biggest = build_hm(cv)
    m4_latest, m4_biggest = build_m406()
    out = {
        "generated": dt.date.today().isoformat(),
        "windowDays": WINDOW_DAYS,
        "scope": "national",
        "source": "OpenFEMA PublicAssistanceFundedProjectsDetails (lastObligationDate; "
                  "mitigationAmount for §406) + HazardMitigationAssistanceProjects v4 "
                  "(initialObligationDate), NATIONAL, COVID-19 excluded",
        "note": "PA is obligated; 'latest' = latest obligation activity (includes downward "
                "adjustments). HM is §404 HMGP + non-disaster HMA (FMA/BRIC/PDM). §406 is the "
                "mitigation portion built into PA permanent-work repairs (the mitigationAmount "
                "on each PA project — a subset of the PA obligation, not new money). Real OpenFEMA "
                "figures — not endorsed by FEMA.",
        "programs": {
            "PA": {"label": "Public Assistance", "latest": pa_latest, "biggest": pa_biggest},
            "HM": {"label": "Hazard Mitigation", "latest": hm_latest, "biggest": hm_biggest},
            "M406": {"label": "Section 406 mitigation",
                     "sub": "hardening built into PA repairs",
                     "latest": m4_latest, "biggest": m4_biggest},
        },
    }
    json.dump(out, open(os.path.join(DATA, "newsreel.json"), "w"), separators=(",", ":"))
    print(f"wrote data/newsreel.json — PA: {len(pa_latest)}/{len(pa_biggest)}; "
          f"HM: {len(hm_latest)}/{len(hm_biggest)}; §406: {len(m4_latest)}/{len(m4_biggest)} (latest/biggest)")
    for tag, rows in (("PA latest", pa_latest), ("HM latest", hm_latest), ("406 biggest", m4_biggest)):
        for r in rows:
            print(f"  {tag}: {r['date']} {r['state']} DR{r['dn']} ${r['amount']:,} {r.get('title','')[:40]}")


if __name__ == "__main__":
    main()
