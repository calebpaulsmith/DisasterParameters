#!/usr/bin/env python3
"""
Build data/pending.json — the "Declaration Requests in Process" (PENDING
declarations) table parsed from the latest FEMA Daily Operations Briefing.

WHY THIS EXISTS (and what it is NOT):
  OpenFEMA publishes declared disasters and declaration *denials*, but it has NO
  public feed of requests that are still PENDING a decision. FEMA only surfaces
  those in its Daily Operations Briefing — a PDF emailed each morning, not posted
  to a stable URL. So this is an UNOFFICIAL community parse of that PDF, NOT an
  OpenFEMA dataset. Every figure must be labeled as such in the UI.

SOURCE / SUSTAINABILITY:
  The Data Liberation Project archives the govdelivery PDF link for every daily
  brief (CC0 / public domain), actively + daily:
    https://github.com/data-liberation-project/fema-daily-ops-email-to-rss
  We read its output/history.csv, take the most recent entry's PDF URL, download
  that PDF, and parse the "Declaration Requests in Process – N" table (pp ~11-13).
  A daily GitHub Action can re-run this; the commit is GATED on the cross-check
  below so a layout change that breaks parsing refuses to ship stale/garbage data.

CROSS-CHECK (trust):
  The table header literally states the count ("Declaration Requests in Process
  – 20"). We assert parsed rows == that header count and record both in the
  output `audit`. Program flags (IA/PA/HM) are read by COLUMN X-COORDINATE (not
  whitespace), so a row with two X's is correctly attributed (e.g. PA+HM vs IA+PA).

CAVEATS (surfaced honestly):
  * Incident PERIOD is NOT in this table — only request date. "Days waiting" is
    therefore request-date -> brief-date, NOT from incident start.
  * The request date is "Mon Day" with NO year; we infer the most-recent year
    <= brief date and set requestYearInferred=true. Long-pending appeals may be a
    year older than inferred (Phase 2 history-harvest would pin this exactly).

Run from repo root (needs network; pip install pdfplumber):
  python3 scripts/build_pending.py
"""
import os, csv, io, json, re, sys, urllib.request, datetime

HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.dirname(HERE)
DATA = os.path.join(ROOT, "data")
HISTORY_CSV = ("https://raw.githubusercontent.com/data-liberation-project/"
               "fema-daily-ops-email-to-rss/main/output/history.csv")

# FEMA region by state/territory (R5 = IL IN MI MN OH WI)
STATE_REGION = {}
for reg, sts in {
    1: "CT ME MA NH RI VT", 2: "NJ NY PR VI", 3: "DE DC MD PA VA WV",
    4: "AL FL GA KY MS NC SC TN", 5: "IL IN MI MN OH WI",
    6: "AR LA NM OK TX", 7: "IA KS MO NE", 8: "CO MT ND SD UT WY",
    9: "AZ CA HI NV GU AS MP FM MH PW", 10: "AK ID OR WA",
}.items():
    for s in sts.split():
        STATE_REGION[s] = reg

# Tribe / territory footnote name -> home state (so tribal requests get a region;
# e.g. Leech Lake Band of Ojibwe -> MN -> Region 5). Extend as new tribes appear.
TRIBE_STATE = {
    "san carlos apache": "AZ", "native village of kipnuk": "AK",
    "fort peck": "MT", "crow tribe": "MT", "fort belknap": "MT",
    "chickasaw nation": "OK", "native village of ambler": "AK",
    "mashpee wampanoag": "MA", "pueblo of acoma": "NM",
    "leech lake band of ojibwe": "MN",
}
MONTHS = {m: i for i, m in enumerate(
    ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"], 1)}

ROW_RE = re.compile(
    r"^(?P<ent>.+?)\s+(?P<type>DR|EM)\s+(?:X\s*){1,3}(?P<date>[A-Z][a-z]{2}\s+\d{1,2})\s*$")

MONTH_FULL = {m: i for i, m in enumerate(
    ["January", "February", "March", "April", "May", "June", "July", "August",
     "September", "October", "November", "December"], 1)}


def latest_brief():
    with urllib.request.urlopen(HISTORY_CSV, timeout=120) as r:
        rows = list(csv.DictReader(io.TextIOWrapper(r, "utf-8")))
    rows = [x for x in rows if x.get("entry_link", "").startswith("http")]
    rows.sort(key=lambda x: x["entry_dt"])
    last = rows[-1]
    url = last["entry_link"].strip()
    if not url.lower().endswith(".pdf"):
        url += ".pdf"
    return url, last["entry_title"]


def brief_date(text):
    m = re.search(r"(January|February|March|April|May|June|July|August|September|"
                  r"October|November|December)\s+(\d{1,2}),\s+(\d{4})", text)
    if not m:
        return None
    return datetime.date(int(m.group(3)),
                         ["January", "February", "March", "April", "May", "June",
                          "July", "August", "September", "October", "November",
                          "December"].index(m.group(1)) + 1, int(m.group(2)))


def infer_date(raw, bdate):
    """'Oct 24' + brief date -> most-recent ISO date <= brief date."""
    mon, day = raw.split()
    mo, dy = MONTHS[mon], int(day)
    for yr in (bdate.year, bdate.year - 1, bdate.year - 2):
        try:
            d = datetime.date(yr, mo, dy)
        except ValueError:
            continue
        if d <= bdate:
            return d
    return None


def resolve_entity(ent_raw, footnotes):
    """Return (kind, code, name, state, region)."""
    ent_raw = ent_raw.strip()
    code = re.sub(r"\d+$", "", ent_raw).strip()        # strip footnote superscript
    sup = re.search(r"(\d+)$", ent_raw)
    if len(code) == 2 and code.upper() in STATE_REGION:
        st = code.upper()
        return "state", st, None, st, STATE_REGION[st]
    # tribal / territory -> footnote name -> curated state map
    name = footnotes.get(sup.group(1)) if sup else None
    st = region = None
    if name:
        low = name.lower()
        for key, s in TRIBE_STATE.items():
            if key in low:
                st, region = s, STATE_REGION.get(s); break
        if region is None:                              # name might end in a state
            for s, r in STATE_REGION.items():
                if low.endswith(s.lower()):
                    st, region = s, r; break
    return "tribal", code, name, st, region


def infer_full_date(mon_full, day, bdate):
    """'April' 23 + brief date -> most-recent ISO date <= brief date."""
    mo = MONTH_FULL[mon_full]
    for yr in (bdate.year, bdate.year - 1, bdate.year - 2):
        try:
            d = datetime.date(yr, mo, int(day))
        except ValueError:
            continue
        if d <= bdate:
            return d
    return None


def parse_detail_pages(pdf, bdate):
    """Best-effort: the 'Disaster Request - <State>' detail pages (present only
    for newly-filed requests) carry the INCIDENT PERIOD and COUNTIES REQUESTED,
    neither of which is in the summary table. Returns a list of detail dicts to
    merge onto matching pending rows by state + requested date."""
    details = []
    for page in pdf.pages:
        t = page.extract_text() or ""
        if not re.search(r"Disaster Request\s*[–-]", t):
            continue
        st = None
        ms = re.search(r"Declaration Type:.*?[–-]\s*([A-Z]{2})\b", t)
        if ms:
            st = ms.group(1)
        mreq = re.search(r"Date Requested:\s*([A-Z][a-z]{2}\s+\d{1,2})", t)
        mper = re.search(r"Incident Period:\s*([^\n]+)", t)
        period = mper.group(1).strip() if mper else None
        pstart = None
        if period:
            pm = re.match(r"([A-Z][a-z]+)\s+(\d{1,2})", period)
            if pm:
                pstart = infer_full_date(pm.group(1), pm.group(2), bdate)
        counties = {}
        for cm in re.finditer(r"[▪•]\s*([A-Za-z/ ]+?):\s*(\d+)\s*count", t):
            counties[cm.group(1).strip()] = int(cm.group(2))
        for cm in re.finditer(r"[▪•]\s*([A-Za-z/ ]+?):\s*(Statewide)", t):
            counties[cm.group(1).strip()] = "Statewide"
        details.append({
            "state": st,
            "requestedRaw": mreq.group(1) if mreq else None,
            "incidentPeriod": period,
            "incidentPeriodStart": pstart.isoformat() if pstart else None,
            "countiesRequested": counties or None,
        })
    return details


def parse_pending(pdf_path):
    import pdfplumber
    pdf = pdfplumber.open(pdf_path)
    full = "\n".join((p.extract_text() or "") for p in pdf.pages)
    bdate = brief_date(full)
    details = parse_detail_pages(pdf, bdate) if bdate else []
    header = re.search(r"Declaration Requests in Process\s*[–-]\s*(\d+)", full)
    header_count = int(header.group(1)) if header else None

    rows = []
    for page in pdf.pages:
        ptext = page.extract_text() or ""
        if "Declaration Requests in Process" not in ptext:
            continue
        words = page.extract_words()
        cols = {w["text"]: w["x0"] for w in words if w["text"] in ("IA", "PA", "HM")}
        if not all(k in cols for k in ("IA", "PA", "HM")):
            continue
        # footnotes on this page: "1Native Village of Ambler / 2Mashpee ..."
        footnotes = {}
        for fm in re.finditer(r"(\d+)([A-Z][^/]+?)(?=\s*/\s*\d|\s*$)", ptext):
            footnotes[fm.group(1)] = fm.group(2).strip()
        # group words into visual lines by their vertical position
        lines = {}
        for w in words:
            lines.setdefault(round(w["top"]), []).append(w)
        for top in sorted(lines):
            toks = sorted(lines[top], key=lambda w: w["x0"])
            text = " ".join(t["text"] for t in toks)
            m = ROW_RE.match(text)
            if not m:
                continue
            xs = [w["x0"] for w in toks if w["text"] == "X"]

            def hit(col):  # an X within +/-12pt of the column header
                return any(abs(x - cols[col]) < 12 for x in xs)
            ent = m.group("ent")
            appeal = bool(re.search(r"[–-]\s*Appeal\s*$", ent))
            ent = re.sub(r"\s*[–-]\s*Appeal\s*$", "", ent)
            parts = re.split(r"\s*[–-]\s*", ent, maxsplit=1)
            ent_code = parts[0]
            incident = parts[1].strip() if len(parts) > 1 else ""
            kind, code, name, st, region = resolve_entity(ent_code, footnotes)
            rd = infer_date(m.group("date"), bdate) if bdate else None
            row = {
                "entity": code, "entityName": name, "kind": kind,
                "state": st, "region": region,
                "incident": incident, "appeal": appeal, "type": m.group("type"),
                "ia": hit("IA"), "pa": hit("PA"), "hm": hit("HM"),
                "requestedRaw": m.group("date"),
                "requestDate": rd.isoformat() if rd else None,
                "requestYearInferred": rd is not None,
                "daysWaiting": (bdate - rd).days if (rd and bdate) else None,
                # incident period / counties — filled from a detail page when present
                "incidentPeriod": None, "incidentPeriodStart": None,
                "daysSinceIncident": None, "countiesRequested": None,
            }
            # best-effort merge: match a detail page by state + requested date
            for d in details:
                if d["state"] == st and d["requestedRaw"] == m.group("date"):
                    row["incidentPeriod"] = d["incidentPeriod"]
                    row["incidentPeriodStart"] = d["incidentPeriodStart"]
                    row["countiesRequested"] = d["countiesRequested"]
                    if d["incidentPeriodStart"]:
                        ps = datetime.date.fromisoformat(d["incidentPeriodStart"])
                        row["daysSinceIncident"] = (bdate - ps).days
                    break
            rows.append(row)
    return bdate, header_count, rows


def main():
    url, title = latest_brief()
    print(f"latest brief: {title}\n  {url}")
    tmp = os.path.join(DATA, "_pending_brief.pdf")
    urllib.request.urlretrieve(url, tmp)
    bdate, header_count, rows = parse_pending(tmp)
    os.remove(tmp)

    parsed = len(rows)
    ok = header_count is not None and parsed == header_count
    print(f"  brief date: {bdate}")
    print(f"  CROSS-CHECK: header says {header_count}, parsed {parsed} -> {'OK' if ok else 'MISMATCH'}")
    r5 = [r for r in rows if r["region"] == 5]
    print(f"  Region 5 pending: {len(r5)} -> " +
          ", ".join(f"{r['entity']}({'A' if r['appeal'] else ''}{r['requestedRaw']})" for r in r5))

    if not ok:
        print("REFUSING to write: parsed count != header count (layout may have changed).",
              file=sys.stderr)
        sys.exit(2)

    out = {
        "briefDate": bdate.isoformat() if bdate else None,
        "briefTitle": title, "briefUrl": url,
        "headerCount": header_count, "parsedCount": parsed, "crossCheckOk": ok,
        "source": "FEMA Daily Operations Briefing (unofficial parse) via Data Liberation Project",
        "rows": rows,
    }
    path = os.path.join(DATA, "pending.json")
    json.dump(out, open(path, "w"), separators=(",", ":"))
    print(f"\nwrote {parsed} pending requests -> pending.json ({os.path.getsize(path)//1024} KB)")


if __name__ == "__main__":
    main()
