#!/usr/bin/env python3
"""OFFLINE: build data/nfip.json — a Region 5 county×year NFIP **claims** rollup
(Phase 1 of the NFIP plan, see docs/refresh-architecture.md).

Source: OpenFEMA FimaNfipClaims v2 (the public, redacted claims dataset; 2.7M rows
nationwide, reloaded MONTHLY = accrualPeriodicity R/P1M). We pull only the Region 5
states (IL/IN/MI/MN/OH/WI) with a server-side `state eq` filter (the claims table is
small enough that this is fine, unlike the 73.6M-row Policies table), select only the
fields we roll up, and aggregate to county + state.

Per county (and per state): claims count, total paid (building + contents + ICC) with
the split, claims/paid by year(yearOfLoss), and a flood-zone summary (inside vs outside
the Special Flood Hazard Area, from ratedFloodZone) — the share of paid claims OUTSIDE
the mapped high-risk zone is a key policy signal.

NOT in Phase 1: policies-in-force / coverage $ (FimaNfipPolicies is 73.6M rows; even the
R5 subset is millions — that's the Phase 2 Cloudflare-backed layer). Claims is the
executive story: where flood damage actually cost money, when, and in/out of the SFHA.

CORS-open OpenFEMA; offline/regenerable; meant for the MONTHLY refresh workflow. Re-run:
    python3 scripts/build_county_nfip.py
"""
import os, json, time, urllib.request, urllib.parse, datetime as dt, collections

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
DATA = os.path.join(ROOT, "data")
CLAIMS_URL = "https://www.fema.gov/api/open/v2/FimaNfipClaims"
R5 = ["IL", "IN", "MI", "MN", "OH", "WI"]
PAGE = 10000
SEL = ("state,countyCode,yearOfLoss,ratedFloodZone,amountPaidOnBuildingClaim,"
       "amountPaidOnContentsClaim,amountPaidOnIncreasedCostOfComplianceClaim,asOfDate")


def get(url, retries=4, timeout=120):
    for i in range(retries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "DisasterParameters/nfip (public open data)"})
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return json.loads(r.read().decode("utf-8", "replace"))
        except Exception as e:
            if i == retries - 1:
                print(f"  ! {e}")
            time.sleep(1.5 * (i + 1))
    return None


def num(x):
    try:
        return float(x or 0)
    except Exception:
        return 0.0


def yr(v):
    try:
        y = int(v)
        return str(y) if 1900 <= y <= 2099 else None
    except Exception:
        return None


def sfha_class(z):
    """ratedFloodZone → 'in' (SFHA high-risk A*/V*), 'out' (B/C/X moderate-minimal), 'unk'."""
    if not z:
        return "unk"
    c = str(z).strip().upper()[:1]
    if c in ("A", "V"):
        return "in"
    if c in ("B", "C", "X"):
        return "out"
    return "unk"


def names_map():
    try:
        cs = json.load(open(os.path.join(DATA, "r5_counties.json")))
        return {c["f"]: (c["n"], c["s"]) for c in cs}
    except Exception:
        return {}


def srt(d):
    return {k: round(v) for k, v in sorted(d.items()) if round(v)}


def new_bucket():
    return {"claims": 0, "paid": 0.0, "paidBuilding": 0.0, "paidContents": 0.0, "paidIcc": 0.0,
            "claimsByYear": collections.defaultdict(int), "paidByYear": collections.defaultdict(float),
            "sfha": {"in": {"c": 0, "p": 0.0}, "out": {"c": 0, "p": 0.0}, "unk": {"c": 0, "p": 0.0}}}


def add(b, county_paid_b, county_paid_c, county_paid_i, y, zone):
    paid = county_paid_b + county_paid_c + county_paid_i
    b["claims"] += 1
    b["paid"] += paid
    b["paidBuilding"] += county_paid_b
    b["paidContents"] += county_paid_c
    b["paidIcc"] += county_paid_i
    if y:
        b["claimsByYear"][y] += 1
        b["paidByYear"][y] += paid
    s = b["sfha"][sfha_class(zone)]
    s["c"] += 1
    s["p"] += paid


def finalize(b):
    return {
        "claims": b["claims"],
        "paid": round(b["paid"]),
        "paidBuilding": round(b["paidBuilding"]),
        "paidContents": round(b["paidContents"]),
        "paidIcc": round(b["paidIcc"]),
        "claimsByYear": dict(sorted((k, v) for k, v in b["claimsByYear"].items())),
        "paidByYear": srt(b["paidByYear"]),
        "sfha": {k: {"claims": v["c"], "paid": round(v["p"])} for k, v in b["sfha"].items()},
    }


def main():
    names = names_map()
    counties = collections.defaultdict(new_bucket)
    states = collections.defaultdict(new_bucket)
    as_of = ""
    total = 0
    for st in R5:
        skip, got = 0, 0
        while True:
            flt = urllib.parse.quote(f"state eq '{st}'")
            url = (f"{CLAIMS_URL}?$filter={flt}&$select={urllib.parse.quote(SEL)}"
                   f"&$top={PAGE}&$skip={skip}&$format=json")
            d = get(url)
            recs = (d or {}).get("FimaNfipClaims", []) if d else []
            if not recs:
                break
            for r in recs:
                pb = max(0.0, num(r.get("amountPaidOnBuildingClaim")))
                pc = max(0.0, num(r.get("amountPaidOnContentsClaim")))
                pi = max(0.0, num(r.get("amountPaidOnIncreasedCostOfComplianceClaim")))
                y = yr(r.get("yearOfLoss"))
                zone = r.get("ratedFloodZone")
                ao = (r.get("asOfDate") or "")[:10]
                if ao > as_of:
                    as_of = ao
                add(states[st], pb, pc, pi, y, zone)
                cc = r.get("countyCode")
                if cc and str(cc).strip():
                    add(counties[str(cc).strip()], pb, pc, pi, y, zone)
            got += len(recs)
            skip += len(recs)
            if len(recs) < PAGE:
                break
            time.sleep(0.05)
        total += got
        print(f"  {st}: {got:,} claims")

    out_counties = {}
    for fips, b in counties.items():
        o = finalize(b)
        nm = names.get(fips)
        o["name"] = nm[0] if nm else None
        o["state"] = nm[1] if nm else None
        o["fips"] = fips
        out_counties[fips] = o
    out_states = {st: finalize(b) for st, b in states.items()}

    out = {
        "generated": dt.date.today().isoformat(),
        "generatedAt": dt.datetime.utcnow().replace(microsecond=0).isoformat() + "Z",
        "asOf": as_of,
        "source": "OpenFEMA FimaNfipClaims v2 (public redacted claims), Region 5. "
                  "Reloaded monthly (R/P1M). Real OpenFEMA figures — not endorsed by FEMA.",
        "note": "Phase 1 county×year NFIP CLAIMS rollup: count, total paid (building+contents+ICC) "
                "with split, by year(yearOfLoss), and SFHA in/out share (ratedFloodZone). "
                "Policies-in-force / coverage $ are NOT included (Phase 2 — FimaNfipPolicies is 73.6M rows). "
                "'paid' is total claim payments; flood losses are cumulative since the program's start.",
        "counties": out_counties,
        "states": out_states,
    }
    path = os.path.join(DATA, "nfip.json")
    json.dump(out, open(path, "w"), separators=(",", ":"))
    kb = os.path.getsize(path) / 1024
    paid = sum(s["paid"] for s in out_states.values())
    print(f"wrote data/nfip.json — {total:,} R5 claims · {len(out_counties)} counties · "
          f"${paid:,.0f} paid · asOf {as_of or '—'} · {kb:.0f}KB")


if __name__ == "__main__":
    main()
