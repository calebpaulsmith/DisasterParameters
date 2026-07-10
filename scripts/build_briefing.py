#!/usr/bin/env python3
"""
Build data/briefing.json — the NATIONAL disaster ledger + trailing obligation
activity that powers the Briefing (the scope-aware Newsreel: National / FEMA
Region 1-10 / state+territory).

DESIGN PRINCIPLE (reconciliation by construction)
  ONE canonical per-disaster ledger is baked; every rollup (state, region,
  national, by-year, COVID split) is derived CLIENT-SIDE from it. Wholes are
  computed from the units, so units always sum to wholes — no drift between a
  baked rollup and the rows behind it.

SOURCES (all CORS-open OpenFEMA; needs network)
  - FemaWebDisasterSummaries v1 (~4K rows, one per disaster): PA obligated
    total + Cat A-B + Cat C-G (=> Cat Z derived as the remainder client-side),
    IHP approved + HA/ONA split, HMGP, IA registrations. FEDERAL SHARE ONLY —
    the non-federal match is NOT in this dataset (phase 2b of the plan).
  - DisasterDeclarationsSummaries v2 (~70K county rows -> deduped per
    disasterNumber): identity/state/region/incidentType/declarationType/
    title/dates/tribal. Pulled with $select + $top/$skip and NO $filter
    (the fema.gov WAF intermittently 503s $select+$filter+$top).
  - PublicAssistanceFundedProjectsDetails v2, trailing ~12 months national
    (date-windowed like build_county_recent.py): monthly per-state obligation
    ACTIVITY ($ on projects whose latest obligation landed that month —
    lastObligationDate semantics, same convention as paByYear; includes
    downward adjustments).

SCOPE OF THE LEDGER
  DR + EM + FM declarations, all history, all states/territories/COFA + tribal
  (tribal declarations carry their state's code + a tribal flag). FM (Fire
  Management Assistance) is INCLUDED — probing FemaWebDisasterSummaries showed
  1,600+ FM rows carrying real dollars (mostly post-fire HMGP, some PA);
  excluding FM would silently drop that money from national totals. The
  declaration type (DR/EM/FM) rides on every row so the UI can slice by it.
  Declarations with no FemaWebDisasterSummaries row are KEPT with null costs
  (declared but no public cost rollup — counts stay honest); FWDS rows with no
  declaration identity are conserved in the audit, never silently dropped.
  COVID flag = incidentType "Biological" (all COVID-19 declarations).

Re-run any time:  python3 scripts/build_briefing.py
"""
import os, json, time, urllib.request, urllib.parse, datetime as dt

DATA = os.path.join(os.path.dirname(__file__), "..", "data")
FWDS = "https://www.fema.gov/api/open/v1/FemaWebDisasterSummaries"
DDS = "https://www.fema.gov/api/open/v2/DisasterDeclarationsSummaries"
PA_URL = "https://www.fema.gov/api/open/v2/PublicAssistanceFundedProjectsDetails"
ACTIVITY_DAYS = 366

STATE_NAMES = {
    "AL":"Alabama","AK":"Alaska","AZ":"Arizona","AR":"Arkansas","CA":"California",
    "CO":"Colorado","CT":"Connecticut","DE":"Delaware","DC":"District of Columbia",
    "FL":"Florida","GA":"Georgia","HI":"Hawaii","ID":"Idaho","IL":"Illinois",
    "IN":"Indiana","IA":"Iowa","KS":"Kansas","KY":"Kentucky","LA":"Louisiana",
    "ME":"Maine","MD":"Maryland","MA":"Massachusetts","MI":"Michigan","MN":"Minnesota",
    "MS":"Mississippi","MO":"Missouri","MT":"Montana","NE":"Nebraska","NV":"Nevada",
    "NH":"New Hampshire","NJ":"New Jersey","NM":"New Mexico","NY":"New York",
    "NC":"North Carolina","ND":"North Dakota","OH":"Ohio","OK":"Oklahoma","OR":"Oregon",
    "PA":"Pennsylvania","RI":"Rhode Island","SC":"South Carolina","SD":"South Dakota",
    "TN":"Tennessee","TX":"Texas","UT":"Utah","VT":"Vermont","VA":"Virginia",
    "WA":"Washington","WV":"West Virginia","WI":"Wisconsin","WY":"Wyoming",
    "PR":"Puerto Rico","VI":"U.S. Virgin Islands","GU":"Guam","AS":"American Samoa",
    "MP":"Northern Mariana Islands","FM":"Micronesia (COFA)","MH":"Marshall Islands (COFA)",
    "PW":"Palau (COFA)",
}


def get(url, retries=4):
    req = urllib.request.Request(url, headers={"User-Agent": "DisasterParameters/briefing"})
    for i in range(retries):
        try:
            with urllib.request.urlopen(req, timeout=120) as r:
                return json.loads(r.read().decode("utf-8", "replace"))
        except Exception:
            if i == retries - 1:
                raise
            time.sleep(2 ** i)


def paginate(base, key, params, page=10000):
    rows, skip = [], 0
    while True:
        u = f"{base}?{params}&$top={page}&$skip={skip}&$format=json&$metadata=off"
        chunk = (get(u) or {}).get(key, [])
        rows.extend(chunk)
        if len(chunk) < page:
            return rows
        skip += len(chunk)


def n(x):
    try:
        return round(float(x))
    except Exception:
        return 0


def main():
    # ---- 1. identity: dedup DisasterDeclarationsSummaries per disasterNumber ----
    sel = ("$select=" + urllib.parse.quote(
        "disasterNumber,state,region,incidentType,declarationType,"
        "declarationTitle,incidentBeginDate,declarationDate,tribalRequest"))
    print("pulling DisasterDeclarationsSummaries…")
    dds = paginate(DDS, "DisasterDeclarationsSummaries", sel)
    print(f"  {len(dds)} county-level rows")
    ident = {}
    for r in dds:
        dn = r.get("disasterNumber")
        if dn is None:
            continue
        e = ident.setdefault(dn, {"st": r.get("state"), "rg": r.get("region"),
                                  "it": r.get("incidentType"), "dt": r.get("declarationType"),
                                  "ti": "", "bg": None, "dc": None, "tr": False})
        t = (r.get("declarationTitle") or "").strip()
        if len(t) > len(e["ti"]):
            e["ti"] = t
        for k, f in (("bg", "incidentBeginDate"), ("dc", "declarationDate")):
            v = (r.get(f) or "")[:10] or None
            if v and (e[k] is None or v < e[k]):
                e[k] = v
        if r.get("tribalRequest"):
            e["tr"] = True
    n_dr = sum(1 for e in ident.values() if e["dt"] == "DR")
    n_em = sum(1 for e in ident.values() if e["dt"] == "EM")
    n_fm = sum(1 for e in ident.values() if e["dt"] not in ("DR", "EM"))
    print(f"  {len(ident)} distinct disasters — DR {n_dr} · EM {n_em} · FM/other {n_fm} (all in ledger)")

    # ---- 2. costs: FemaWebDisasterSummaries (v1 caps pages at 1000) ----
    print("pulling FemaWebDisasterSummaries…")
    fwds = {r["disasterNumber"]: r for r in
            paginate(FWDS, "FemaWebDisasterSummaries", "$select=" + urllib.parse.quote(
                "disasterNumber,totalObligatedAmountPa,totalObligatedAmountCatAb,"
                "totalObligatedAmountCatC2g,totalAmountIhpApproved,totalAmountHaApproved,"
                "totalAmountOnaApproved,totalObligatedAmountHmgp,totalNumberIaApproved"), page=1000)}
    print(f"  {len(fwds)} cost rows")

    # ---- 3. join into the ledger (DR+EM only; conserve everything else) ----
    it_dict, dt_dict = [], []

    def idx(d, v):
        if v not in d:
            d.append(v)
        return d.index(v)

    rows, neg_z = [], 0
    withCosts = 0
    for dn in sorted(ident):
        e = ident[dn]
        s = fwds.get(dn)
        covid = 1 if e["it"] == "Biological" else 0
        if s:
            paT, ab, cg = n(s.get("totalObligatedAmountPa")), n(s.get("totalObligatedAmountCatAb")), n(s.get("totalObligatedAmountCatC2g"))
            costs = [paT, ab, cg, n(s.get("totalAmountIhpApproved")), n(s.get("totalAmountHaApproved")),
                     n(s.get("totalAmountOnaApproved")), n(s.get("totalObligatedAmountHmgp")),
                     int(s.get("totalNumberIaApproved") or 0)]
            withCosts += 1
            if paT and paT - ab - cg < 0:
                neg_z += 1
        else:
            costs = [None] * 8
        rows.append([dn, e["st"], e["rg"], idx(it_dict, e["it"] or "—"), idx(dt_dict, e["dt"]),
                     e["ti"][:90], e["bg"], e["dc"], *costs, covid, 1 if e["tr"] else 0])

    orphans = [dn for dn in fwds if dn not in ident]
    print(f"  ledger {len(rows)} rows ({withCosts} with costs, {len(rows)-withCosts} declared/no public cost rollup)")
    print(f"  conservation: {len(orphans)} FWDS rows w/o identity (audited, out of ledger)")
    if neg_z:
        print(f"  NOTE: {neg_z} rows have AB+CG > PA total (Cat Z clamps to 0 client-side; audited)")

    # ---- 4. states map (name + region, region = mode across that state's rows) ----
    from collections import Counter
    st_reg = {}
    for r in rows:
        if r[1]:
            st_reg.setdefault(r[1], Counter())[r[2]] += 1
    states = {st: {"n": STATE_NAMES.get(st, st), "r": (c.most_common(1)[0][0] if c else None)}
              for st, c in sorted(st_reg.items())}

    # ---- 5. trailing-12-month obligation activity, monthly per state ----
    cutoff = (dt.date.today() - dt.timedelta(days=ACTIVITY_DAYS)).isoformat()
    print(f"pulling PA obligation activity since {cutoff}…")
    flt = urllib.parse.quote(f"lastObligationDate ge '{cutoff}T00:00:00.000Z'")
    asel = urllib.parse.quote("stateAbbreviation,federalShareObligated,lastObligationDate,incidentType")
    act_rows = paginate(PA_URL, "PublicAssistanceFundedProjectsDetails",
                        f"$filter={flt}&$select={asel}")
    print(f"  {len(act_rows)} activity rows")
    months = sorted({(r.get("lastObligationDate") or "")[:7] for r in act_rows if r.get("lastObligationDate")})
    act = {}
    for r in act_rows:
        ym, st = (r.get("lastObligationDate") or "")[:7], r.get("stateAbbreviation")
        if not ym or not st:
            continue
        mi = months.index(ym)
        a = act.setdefault(st, [[0, 0] for _ in months])
        a[mi][1 if r.get("incidentType") == "Biological" else 0] += n(r.get("federalShareObligated"))

    out = {
        "generated": dt.date.today().isoformat(),
        "source": "OpenFEMA FemaWebDisasterSummaries (costs; federal share only) + "
                  "DisasterDeclarationsSummaries v2 (identity/region) + "
                  "PublicAssistanceFundedProjectsDetails (trailing obligation activity)",
        "note": "DR + EM + FM declarations, all history, all states/territories. "
                "PA is obligated, IHP is approved. Cat Z = PA total − Cat A-B − Cat C-G, derived "
                "client-side. Null costs = declared but no public cost rollup in "
                "FemaWebDisasterSummaries. Activity $ keys to lastObligationDate (latest "
                "obligation activity incl. downward adjustments). Not endorsed by FEMA.",
        "cols": ["dn", "st", "rg", "it", "dt", "title", "begin", "declared",
                 "paTotal", "paAB", "paCG", "ihpTotal", "ihpHA", "ihpONA", "hmgp", "iaRegs",
                 "covid", "tribal"],
        "it": it_dict, "dt": dt_dict, "states": states, "d": rows,
        "activity": {"cutoff": cutoff, "months": months, "byState": act},
        "audit": {
            "ddsCountyRows": len(dds), "distinctDisasters": len(ident),
            "dr": n_dr, "em": n_em, "fm": n_fm,
            "ledgerRows": len(rows), "withCosts": withCosts,
            "fwdsRows": len(fwds), "fwdsNoIdentity": sorted(orphans),
            "negativeCatZ": neg_z,
            "identity": "ledgerRows == distinctDisasters; every FWDS row is inLedger or noIdentity",
            "check": len(rows) == len(ident) and
                     withCosts + len(orphans) == len(fwds),
        },
    }
    path = os.path.join(DATA, "briefing.json")
    json.dump(out, open(path, "w"), separators=(",", ":"))
    kb = os.path.getsize(path) // 1024
    paTotal = sum(r[8] or 0 for r in rows)
    covidPa = sum(r[8] or 0 for r in rows if r[16])
    print(f"wrote data/briefing.json ({kb} KB) — {len(rows)} disasters · "
          f"PA ${paTotal:,} (COVID ${covidPa:,}) · audit check: {out['audit']['check']}")


if __name__ == "__main__":
    main()
