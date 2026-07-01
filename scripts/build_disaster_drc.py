#!/usr/bin/env python3
"""
Build data/disaster_drc.json — per-DISASTER list of FEMA Disaster Recovery Centers
(walk-in survivor assistance sites: DRC / Mobile DRC / Document Drop-Off Center), so the
Geography IA section + Ledger detail modal can show a small "N DRCs" badge per disaster
that expands into each site's name, address, open/close dates, hours, and status.

Source: FEMA's public ArcGIS Geospatial Resource Center FeatureServer (no key, CORS-open):
  https://gis.fema.gov/arcgis/rest/services/FEMA/DRC/FeatureServer
    layer 0 = "Open DRC"                     (currently active, nationwide)
    layer 1 = "Archive - Closed DRC Locations" (historical, nationwide)
Both share one schema. Filtered here to Region 5 states at query time.

Join: each record's primary_disaster / secondary_disaster is a FEMA disaster number —
matched directly against disasters.json's disasterNumber. A DRC can serve two co-declared
disasters (primary + secondary), in which case it's attached to both. Records whose
disaster number(s) don't match anything in the ledger (pre-FY2007, not-yet-added, or a
disaster this app doesn't track) are conserved in the audit, never silently dropped.

Needs network. No resumable cache — the R5 record count is small (a few hundred), so a
full re-pull is cheap. Run any time:
  python3 scripts/build_disaster_drc.py
"""
import json, os, time, urllib.request, urllib.parse
from datetime import datetime, timezone

DATA = os.path.join(os.path.dirname(__file__), "..", "data")
BASE = "https://gis.fema.gov/arcgis/rest/services/FEMA/DRC/FeatureServer"
R5 = ["IL", "IN", "MI", "MN", "OH", "WI"]
FIELDS = ["objectid", "primary_disaster", "secondary_disaster", "drc_name", "drc_type_desc",
          "street_1", "city", "county_parish", "state", "zip", "status",
          "actual_open_date", "planned_close_date", "close_date", "latitude", "longitude", "notes"] + \
         [f"{d}_{t}_tm" for d in ["sunday", "monday", "tuesday", "wednesday", "thursday", "friday", "saturday"] for t in ["open", "close"]]
DAYS = ["sunday", "monday", "tuesday", "wednesday", "thursday", "friday", "saturday"]
DAY_ABBR = {"sunday": "Sun", "monday": "Mon", "tuesday": "Tue", "wednesday": "Wed", "thursday": "Thu", "friday": "Fri", "saturday": "Sat"}

def get(u, retries=5):
    for i in range(retries):
        try:
            with urllib.request.urlopen(urllib.request.Request(u, headers={"User-Agent": "DisasterParameters/drc"}), timeout=60) as r:
                return json.loads(r.read().decode("utf-8", "replace"))
        except Exception:
            time.sleep(2 * (i + 1))
    return None

def pull_layer(layer_id):
    """→ list of raw attribute dicts for R5 states, paginated past any transfer limit."""
    where = "state IN (" + ",".join(f"'{s}'" for s in R5) + ")"
    out, offset = [], 0
    while True:
        q = urllib.parse.urlencode({"where": where, "outFields": ",".join(FIELDS), "f": "json",
                                     "resultOffset": offset, "resultRecordCount": 1000})
        d = get(f"{BASE}/{layer_id}/query?{q}")
        feats = (d or {}).get("features", [])
        if not feats: break
        out.extend(f["attributes"] for f in feats)
        offset += len(feats)
        if not d.get("exceededTransferLimit"): break
    return out

def iso(ms):
    if not ms: return None
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).date().isoformat()

def fmt_tm(hhmm):
    h, m = hhmm.split(":")
    h, m = int(h), int(m)
    ap = "AM" if h < 12 else "PM"
    h12 = h % 12 or 12
    return f"{h12}:{m:02d} {ap}" if m else f"{h12} {ap}"

def hours_summary(a):
    """Group consecutive open days sharing the same open/close time into ranges, e.g. 'Mon-Fri 9 AM-7 PM · Sat 9 AM-5 PM'."""
    slots = []
    for d in DAYS:
        o, c = a.get(f"{d}_open_tm"), a.get(f"{d}_close_tm")
        slots.append((o, c) if o and c else None)
    groups, i = [], 0
    while i < len(slots):
        if slots[i] is None:
            i += 1; continue
        j = i
        while j + 1 < len(slots) and slots[j + 1] == slots[i]:
            j += 1
        groups.append((i, j, slots[i]))
        i = j + 1
    if not groups:
        note = (a.get("notes") or "").strip()
        return note[:160] if note else None
    parts = []
    for i, j, (o, c) in groups:
        label = DAY_ABBR[DAYS[i]] if i == j else f"{DAY_ABBR[DAYS[i]]}-{DAY_ABBR[DAYS[j]]}"
        parts.append(f"{label} {fmt_tm(o)}-{fmt_tm(c)}")
    return " · ".join(parts)

def clean(a):
    return {
        "name": a.get("drc_name") or "",
        "type": a.get("drc_type_desc") or "Disaster Recovery Center",
        "street": a.get("street_1") or None,
        "city": (a.get("city") or "").title() or None,
        "county": (a.get("county_parish") or "").title() or None,
        "state": a.get("state"),
        "zip": a.get("zip"),
        "lat": a.get("latitude"), "lon": a.get("longitude"),
        "status": a.get("status") or None,
        "open": iso(a.get("actual_open_date")),
        "plannedClose": iso(a.get("planned_close_date")),
        "close": iso(a.get("close_date")),
        "hours": hours_summary(a),
    }

def main():
    disasters = json.load(open(os.path.join(DATA, "disasters.json")))
    dn_set = {d["disasterNumber"] for d in disasters}

    raw = pull_layer(0) + pull_layer(1)   # open + closed archive
    print(f"Pulled {len(raw)} R5 DRC records (open + archive)")

    by_disaster, seen = {}, set()
    matched = no_number = off_ledger = dupes = 0
    off_ledger_dns = set()
    for a in raw:
        key = a.get("objectid")
        if key in seen: continue
        seen.add(key)
        dns = [n for n in (a.get("primary_disaster"), a.get("secondary_disaster")) if n]
        if not dns:
            no_number += 1
            continue
        rec = clean(a)
        hit = False
        for dn in dns:
            if dn in dn_set:
                by_disaster.setdefault(str(int(dn)), []).append(rec)
                hit = True
            else:
                off_ledger += 1
                off_ledger_dns.add(int(dn))
        if hit: matched += 1

    for dn, recs in by_disaster.items():
        recs.sort(key=lambda r: r.get("open") or "")

    out = {
        "meta": {
            "source": "FEMA Geospatial Resource Center ArcGIS FeatureServer — "
                       "gis.fema.gov/arcgis/rest/services/FEMA/DRC/FeatureServer (layers 0=Open, 1=Archive-Closed). "
                       "Not OpenFEMA; a separate FEMA GIS system, updated hourly by FEMA's DRC Manager program.",
            "fields": "byDisaster[dn] = [{name,type,street,city,county,state,zip,lat,lon,status,open,plannedClose,close,hours}, ...]. "
                      "'type' is one of: Disaster Recovery Center, Mobile Disaster Recovery Center, Document Drop-Off Center. "
                      "'hours' is derived from per-day open/close fields where present, else a truncated notes fallback, else null.",
            "note": "A DRC can be co-declared to two disasters (primary+secondary) and appears under both. "
                    "Records whose disaster number(s) aren't in this ledger are conserved in audit.offLedgerDisasters, never dropped silently.",
            "disasters": len(by_disaster),
            "generatedFrom": "R5 states only (state IN IL,IN,MI,MN,OH,WI) at query time.",
        },
        "byDisaster": by_disaster,
        "audit": {
            "recordsPulled": len(raw),
            "recordsMatchedToLedger": matched,
            "recordsNoDisasterNumber": no_number,
            "disasterNumberRefsOffLedger": off_ledger,
            "offLedgerDisasters": sorted(off_ledger_dns),
        },
    }
    json.dump(out, open(os.path.join(DATA, "disaster_drc.json"), "w"), separators=(",", ":"))
    print(f"Wrote data/disaster_drc.json — {len(by_disaster)} disasters, {matched} matched records, "
          f"{no_number} with no disaster number, {off_ledger} disaster-number refs off-ledger {sorted(off_ledger_dns)[:10]}")

if __name__ == "__main__":
    main()
