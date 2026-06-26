#!/usr/bin/env python3
"""
Build data/request_dates.json — REQUEST DATES for declared (and denied) disasters,
harvested from the historical FEMA Daily Operations Briefing archive.

WHY: OpenFEMA publishes a declaration *request* date ONLY for denials
(DeclarationDenials.declarationRequestDate); for APPROVED disasters it publishes
the declaration date but never the request date. The daily briefing's "Declaration
Requests in Process" table is the only public source of the request date for
disasters that ended up declared. Harvesting the archive and matching requests to
OpenFEMA declarations yields a true REQUEST -> DECLARATION lag that OpenFEMA can't
give — and makes the Denials chart's request-basis toggle an apples-to-apples
denial-vs-approval comparison.

THIS IS A DAILY-OPS-BRIEF PARSE, NOT OPENFEMA. Every derived figure must be
labeled as such in the UI.

TRUST / CROSS-CHECK (the whole point of Phase 2):
  We have GROUND TRUTH for the request date of DENIED requests (OpenFEMA). So we
  match harvested brief-requests to OpenFEMA denials by state+date and report how
  often the brief's parsed/inferred request date agrees with OpenFEMA's. High
  agreement validates the parser + the year-inference + the matching logic. We
  also sanity-check declared matches (request <= declared; one candidate only).

THE WRINKLE (handled conservatively):
  One incident often spawns MULTIPLE requests/declarations (program splits;
  denials -> appeals, which the brief tags "– Appeal"). We dedup each request
  across the days it recurs (key = entity+incident+type+appeal+requested-date) and
  match to a declaration ONLY when exactly one OpenFEMA candidate fits the
  state + post-request date window (CONSERVATIVE — high-confidence only). Anything
  ambiguous is left unmatched and counted, never guessed.

Run from repo root (needs network; pip install pdfplumber):
  python3 scripts/build_request_dates.py            # full archive (cached/resumable)
  python3 scripts/build_request_dates.py --limit 60 # quick test on the newest 60 briefs
"""
import os, sys, csv, io, json, re, time, datetime, urllib.request, urllib.parse
from concurrent.futures import ThreadPoolExecutor, as_completed

HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.dirname(HERE)
DATA = os.path.join(ROOT, "data")
sys.path.insert(0, HERE)
import build_pending as bp  # reuse the validated parser

HISTORY_CSV = ("https://raw.githubusercontent.com/data-liberation-project/"
               "fema-daily-ops-email-to-rss/main/output/history.csv")
CACHE = os.path.join(DATA, "_request_cache.json")
DDS = "https://www.fema.gov/api/open/v2/DisasterDeclarationsSummaries"
R5 = {"IL", "IN", "MI", "MN", "OH", "WI"}


def norm_inc(s):
    return re.sub(r"[^a-z]", "", (s or "").lower())


def load_history():
    with urllib.request.urlopen(HISTORY_CSV, timeout=120) as r:
        rows = list(csv.DictReader(io.TextIOWrapper(r, "utf-8")))
    out = []
    for x in rows:
        url = (x.get("entry_link") or "").strip()
        if not url.startswith("http"):
            continue
        if not url.lower().endswith(".pdf"):
            url += ".pdf"
        out.append((x["entry_dt"][:10], url))
    out.sort()
    return out


def fetch_one(date, url):
    import tempfile
    fd, tmp = tempfile.mkstemp(suffix=".pdf"); os.close(fd)
    try:
        urllib.request.urlretrieve(url, tmp)
        bdate, hc, rows = bp.parse_pending(tmp)
        lean = [{k: r[k] for k in ("entity", "entityName", "state", "region",
                "incident", "appeal", "decision", "type", "ia", "pa", "hm",
                "requestedRaw", "incidentPeriod", "incidentPeriodStart", "countiesRequested")} for r in rows]
        inproc = sum(1 for r in rows if not r.get("decision"))  # header counts only in-process
        return date, {"url": url, "briefDate": bdate.isoformat() if bdate else None,
                      "header": hc, "parsed": len(rows), "inproc": inproc,
                      "ok": hc == inproc, "rows": lean}
    except Exception as e:
        return date, {"url": url, "error": str(e)}
    finally:
        try: os.remove(tmp)
        except OSError: pass


def harvest(briefs, workers=8):
    cache = json.load(open(CACHE)) if os.path.exists(CACHE) else {}
    todo = [(d, u) for d, u in briefs if d not in cache]
    print(f"harvest: {len(briefs)} briefs, {len(cache)} cached, {len(todo)} to fetch")
    done = 0
    with ThreadPoolExecutor(max_workers=workers) as ex:
        futs = [ex.submit(fetch_one, d, u) for d, u in todo]
        for f in as_completed(futs):
            d, rec = f.result(); cache[d] = rec; done += 1
            if done % 50 == 0:
                json.dump(cache, open(CACHE, "w"))
                print(f"  {done}/{len(todo)} fetched…")
    json.dump(cache, open(CACHE, "w"))
    bad = [d for d, r in cache.items() if r.get("error")]
    mism = [d for d, r in cache.items() if not r.get("error") and not r.get("ok")]
    print(f"  cached {len(cache)} | fetch errors {len(bad)} | header mismatches {len(mism)}")
    return cache


def build_inventory(cache):
    """Collapse each request across the days it recurs. Key on the request's
    identity; recover the request date from the FIRST brief that showed it."""
    inv = {}
    for d in sorted(cache):
        rec = cache[d]
        if rec.get("error") or not rec.get("ok"):
            continue
        bdate = datetime.date.fromisoformat(rec["briefDate"])
        for r in rec["rows"]:
            key = (r["entity"], norm_inc(r["incident"]), r["type"], r["appeal"], r["requestedRaw"])
            e = inv.get(key)
            if not e:
                rd = bp.infer_date(r["requestedRaw"], bdate) if r.get("requestedRaw") else None
                e = inv[key] = {
                    "entity": r["entity"], "entityName": r["entityName"],
                    "state": r["state"], "region": r["region"],
                    "incident": r["incident"], "appeal": r["appeal"], "type": r["type"],
                    "ia": r["ia"], "pa": r["pa"], "hm": r["hm"],
                    "requestedRaw": r["requestedRaw"],
                    "requestDate": rd.isoformat() if rd else None,
                    "firstSeen": d, "lastSeen": d,
                    "decision": None, "decisionDate": None,
                    "incidentPeriod": r.get("incidentPeriod"),
                    "incidentPeriodStart": r.get("incidentPeriodStart"),
                    "countiesRequested": r.get("countiesRequested"),
                }
            else:
                e["lastSeen"] = d
                for f in ("ia", "pa", "hm"):
                    e[f] = e[f] or r[f]
                # incident period + counties come from the detail page in the brief
                # where the request was newly filed — backfill from whichever brief had it
                if not e.get("incidentPeriod") and r.get("incidentPeriod"):
                    e["incidentPeriod"] = r["incidentPeriod"]
                    e["incidentPeriodStart"] = r.get("incidentPeriodStart")
                if not e.get("countiesRequested") and r.get("countiesRequested"):
                    e["countiesRequested"] = r["countiesRequested"]
            # capture the brief's own decision tag + the date it first appeared
            if r.get("decision") and not e["decision"]:
                e["decision"] = r["decision"]
                e["decisionDate"] = d
    print(f"inventory: {len(inv)} distinct requests across the archive")
    return list(inv.values())


def daynum(s):
    return datetime.date.fromisoformat(s).toordinal() if s else None


def denial_crosscheck(inv, date2url):
    """Validate parsed request dates against OpenFEMA denial request dates
    (ground truth). Match a brief request to a denial by state + |reqDate diff|.
    Also record, per OpenFEMA denial reqNum, the ACTUAL brief(s) it appeared in
    (first-seen + the brief that tagged the turndown) so the UI can link them."""
    den = json.load(open(os.path.join(DATA, "denials.json")))
    # only denials whose request could fall inside the brief archive window
    archive_start = "2022-09-01"
    cand = [x for x in den if x.get("reqDate") and x["reqDate"] >= archive_start]
    by_state = {}
    for r in inv:
        if r["requestDate"]:
            by_state.setdefault(r["state"], []).append(r)
    matched, diffs, examples = 0, [], []
    denial_briefs = {}
    for x in cand:
        best, bestdiff = None, 99
        for r in by_state.get(x["state"], []):
            dd = abs(daynum(r["requestDate"]) - daynum(x["reqDate"]))
            if dd < bestdiff:
                best, bestdiff = r, dd
        if best is not None and bestdiff <= 10:
            matched += 1; diffs.append(bestdiff)
            if x.get("reqNum") is not None:
                denial_briefs[str(x["reqNum"])] = {
                    "firstSeen": best["firstSeen"], "firstSeenUrl": date2url.get(best["firstSeen"]),
                    "decisionDate": best.get("decisionDate") or best["lastSeen"],
                    "decisionUrl": date2url.get(best.get("decisionDate") or best["lastSeen"]),
                    "briefRequestDate": best["requestDate"],
                }
            if len(examples) < 8:
                examples.append({"state": x["state"], "openfema": x["reqDate"],
                                 "brief": best["requestDate"], "diffDays": bestdiff,
                                 "incident": best["incident"][:40],
                                 "firstSeenUrl": date2url.get(best["firstSeen"])})
    exact = sum(1 for d in diffs if d == 0)
    within3 = sum(1 for d in diffs if d <= 3)
    cc = {
        "denialsInWindow": len(cand), "matchedInBriefs": matched,
        "exactDateAgree": exact, "within3dAgree": within3,
        "meanAbsDiffDays": round(sum(diffs) / len(diffs), 2) if diffs else None,
        "examples": examples,
        "note": ("Brief request dates compared to OpenFEMA DeclarationDenials.declarationRequestDate "
                 "(ground truth). Matched by state + nearest request date (<=10d). 'exact' = the "
                 "parsed+year-inferred brief date equals OpenFEMA's to the day."),
    }
    print(f"\nDENIAL CROSS-CHECK: {matched}/{len(cand)} denials found in briefs; "
          f"exact-date agree {exact}/{matched}, within-3d {within3}/{matched}, "
          f"mean |diff| {cc['meanAbsDiffDays']}d")
    for e in examples:
        print(f"   {e['state']} OF={e['openfema']} brief={e['brief']} Δ{e['diffDays']}d  {e['incident']}")
    return cc, denial_briefs


def fetch_declarations():
    """R5 declared disasters since the archive start (one row per disasterNumber)."""
    flt = ("declarationType eq 'DR' and fyDeclared ge 2022 and incidentType ne 'Biological' "
           "and (" + " or ".join(f"state eq '{s}'" for s in sorted(R5)) + ")")
    sel = ("disasterNumber,state,declarationDate,incidentType,incidentBeginDate,"
           "declarationTitle,ihProgramDeclared,paProgramDeclared,hmProgramDeclared")
    by, skip = {}, 0
    while True:
        qs = urllib.parse.urlencode({"$filter": flt, "$select": sel, "$top": "1000",
                                     "$skip": str(skip), "$format": "json"})
        with urllib.request.urlopen(f"{DDS}?{qs}", timeout=120) as r:
            rows = json.load(r).get("DisasterDeclarationsSummaries", [])
        if not rows:
            break
        for x in rows:
            dn = x["disasterNumber"]
            decl = (x.get("declarationDate") or "")[:10]
            if dn not in by or decl < by[dn]["declared"]:
                by[dn] = {"dn": dn, "state": x["state"], "declared": decl,
                          "incidentType": x.get("incidentType", ""),
                          "begin": (x.get("incidentBeginDate") or "")[:10],
                          "title": x.get("declarationTitle", "")}
        skip += 1000
    return list(by.values())


def match_declarations(inv, date2url):
    """CONSERVATIVE: attach a request date to a declared R5 disaster only when
    exactly one brief request fits state + declared-in-(req, req+150d]."""
    decls = fetch_declarations()
    print(f"\nR5 declared disasters (FY2022+): {len(decls)}")
    reqs = [r for r in inv if r["state"] in R5 and r["requestDate"] and not r["appeal"]]
    by_disaster = {}
    for dcl in decls:
        dnum = daynum(dcl["declared"])
        if dnum is None:
            continue
        # STRONG: a request the brief itself tagged "Approved" near this declaration date
        strong = []
        window = []
        for r in reqs:
            if r["state"] != dcl["state"]:
                continue
            rq = daynum(r["requestDate"])
            if rq is None or not (0 <= dnum - rq <= 150):
                continue
            window.append((dnum - rq, r))
            if r["decision"] == "approved" and r["decisionDate"]:
                if abs(daynum(r["decisionDate"]) - dnum) <= 21:
                    strong.append((dnum - rq, r))
        pick, basis, conf = None, None, None
        if len(strong) == 1:
            pick, basis, conf = strong[0], "brief-tagged-approved-near-declaration", "high"
        elif len(window) == 1:
            pick, basis, conf = window[0], "state+single-candidate-in-window", "high"
        # >1 ambiguous candidate and no unique approved tag -> leave unmatched (conservative)
        if pick:
            lag, r = pick
            ips = r.get("incidentPeriodStart")
            inc_lag = (dnum - daynum(ips)) if ips else None
            by_disaster[str(dcl["dn"])] = {
                "requestDate": r["requestDate"], "requestedRaw": r["requestedRaw"],
                "declared": dcl["declared"], "reqToDeclLagDays": lag,
                "firstSeen": r["firstSeen"], "lastSeen": r["lastSeen"],
                # link the ACTUAL briefs: where the request first appeared, and where it was decided
                "firstSeenUrl": date2url.get(r["firstSeen"]),
                "briefDecision": r["decision"], "briefDecisionDate": r["decisionDate"],
                "decisionUrl": date2url.get(r["decisionDate"]) if r["decisionDate"] else None,
                # incident period + counties requested, backfilled from the brief detail page
                "incidentPeriod": r.get("incidentPeriod"),
                "incidentPeriodStart": ips,
                "incidentToDeclLagDays": inc_lag,
                "countiesRequested": r.get("countiesRequested"),
                "confidence": conf, "basis": basis, "incident": r["incident"],
                "source": "FEMA Daily Operations Briefing (unofficial parse)",
            }
    matched = len(by_disaster)
    lags = [v["reqToDeclLagDays"] for v in by_disaster.values()]
    lags.sort()
    med = lags[len(lags) // 2] if lags else None
    print(f"matched request dates -> {matched}/{len(decls)} R5 declared disasters "
          f"(conservative single-candidate); median request->declaration lag {med}d")
    return by_disaster, len(decls), len([r for r in inv if r["state"] in R5])


def main():
    limit = None
    if "--limit" in sys.argv:
        limit = int(sys.argv[sys.argv.index("--limit") + 1])
    briefs = load_history()
    total = len(briefs)
    if limit:
        briefs = briefs[-limit:]
    date2url = dict(briefs)  # brief date -> the actual govdelivery PDF URL
    cache = harvest(briefs)
    inv = build_inventory(cache)
    cc, denial_briefs = denial_crosscheck(inv, date2url)
    by_disaster, n_decl, n_r5_req = match_declarations(inv, date2url)

    parsed_ok = sum(1 for r in cache.values() if not r.get("error") and r.get("ok"))
    dates = sorted(r["briefDate"] for r in cache.values() if r.get("briefDate"))
    out = {
        "source": "FEMA Daily Operations Briefing (unofficial parse) via Data Liberation Project",
        "note": ("Request dates for DECLARED disasters are not in OpenFEMA; these are parsed from "
                 "the daily briefing archive and matched conservatively. Cross-checked against "
                 "OpenFEMA denial request dates (see denialCrosscheck)."),
        "coverage": {"briefsTotal": total, "briefsParsed": parsed_ok,
                     "from": dates[0] if dates else None, "to": dates[-1] if dates else None},
        "denialCrosscheck": cc,
        "r5DeclaredConsidered": n_decl, "r5RequestsHarvested": n_r5_req,
        "matchedDeclared": len(by_disaster),
        "withIncidentPeriod": sum(1 for v in by_disaster.values() if v.get("incidentPeriod")),
        "withCounties": sum(1 for v in by_disaster.values() if v.get("countiesRequested")),
        "byDisaster": by_disaster,
        "denialBriefs": denial_briefs,  # OpenFEMA denial reqNum -> the brief(s) it appeared in
    }
    path = os.path.join(DATA, "request_dates.json")
    json.dump(out, open(path, "w"), separators=(",", ":"))
    print(f"\nwrote request_dates.json ({os.path.getsize(path)//1024} KB): "
          f"{len(by_disaster)} declared disasters with a harvested request date; "
          f"{out['withIncidentPeriod']} w/ incident period, {out['withCounties']} w/ counties")


if __name__ == "__main__":
    main()
