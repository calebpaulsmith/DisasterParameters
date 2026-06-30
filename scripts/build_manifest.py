#!/usr/bin/env python3
"""OFFLINE, no network: build data/manifest.json — a small freshness manifest for every
committed data/*.json file. Powers the UI "data as of" stamp and a quick health read so
stale data can't masquerade as fresh.

For each data file it records: size (bytes), the file's own internal freshness field if it
has one (generated / generatedAt / asOf), and the declared OpenFEMA refresh cadence for the
datasets that one is built from (so a reviewer can see "source updates daily, our snapshot is
N days old"). Pure stdlib; re-run any time (and from the daily refresh workflow):

    python3 scripts/build_manifest.py
"""
import os, re, json, datetime as dt

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
DATA = os.path.join(ROOT, "data")

# Declared refresh cadence for the source each file leans on, so the UI can say "source
# updates daily/monthly; snapshot is N days old". "static"/"as-needed" files have no
# periodic clock — the lineage view renders those as a calm "reference" state, not stale.
SOURCE_CADENCE = {
    "disasters.json": "daily",
    "county_declarations.json": "daily",
    "recent.json": "daily",
    "newsreel.json": "daily",
    "disasters_national.json": "daily",
    "timeline.json": "daily",
    "covid.json": "daily",
    "gages.json": "as-needed (NWS AHPS)",
    "nfip.json": "monthly",            # FimaNfipClaims/Policies are R/P1M
    "denials.json": "as-needed (declaration denials)",
    "pending.json": "daily (Daily Ops Brief)",
    "request_dates.json": "weekly (Daily Ops Brief harvest)",
    "disaster_county_ihp.json": "as-needed (IHP rollup)",
    "event_nexus.json": "as-needed",
    "context.json": "as-needed",
    "r5_counties.json": "static (county geometry)",
}

ISO_DATE = re.compile(r"\b(20\d{2}-\d{2}-\d{2})\b")


def _max_iso_date(obj):
    """Latest YYYY-MM-DD found anywhere in the file, capped at today — a "data covers
    through" proxy for files that carry dated records but no explicit build stamp."""
    today = dt.date.today().isoformat()
    best = None
    stack = [obj]
    while stack:
        x = stack.pop()
        if isinstance(x, str):
            for m in ISO_DATE.findall(x):
                if m <= today and (best is None or m > best):
                    best = m
        elif isinstance(x, dict):
            stack.extend(x.values())
        elif isinstance(x, list):
            stack.extend(x)
    return best


def freshness(obj):
    """A representative freshness date for a file: an explicit build/coverage stamp if it
    has one (top level or under meta/coverage), else the newest dated record in it."""
    def pick(d):
        if not isinstance(d, dict):
            return None
        for k in ("dataAsOf", "generatedAt", "generated", "builtAt", "briefDate"):
            if d.get(k):
                return str(d[k])
        if isinstance(d.get("asOf"), dict) and d["asOf"]:
            vs = [str(v) for v in d["asOf"].values() if v]
            if vs:
                return max(vs)
        return None

    if isinstance(obj, dict):
        v = pick(obj)
        if v:
            return v
        for sub in ("meta", "coverage"):
            s = obj.get(sub)
            if isinstance(s, dict):
                v = pick(s)
                if v:
                    return v
                if s.get("to"):              # coverage.to (e.g. request_dates.json)
                    return str(s["to"])
    return _max_iso_date(obj)               # list files + anything with dated records


def main():
    files = {}
    for name in sorted(os.listdir(DATA)):
        if not name.endswith(".json") or name == "manifest.json":
            continue
        if name in ("lineage.json", "lineage.seed.json"):  # lineage feature's own files, not data snapshots
            continue
        if name.startswith("_"):   # skip git-ignored intermediate/cache files (e.g. _ihp_dc_cache.json)
            continue
        path = os.path.join(DATA, name)
        entry = {"bytes": os.path.getsize(path)}
        try:
            obj = json.load(open(path))
            f = freshness(obj)
            if f:
                entry["dataAsOf"] = f
        except Exception:
            pass
        if name in SOURCE_CADENCE:
            entry["sourceCadence"] = SOURCE_CADENCE[name]
        files[name] = entry

    gen = dt.datetime.utcnow().replace(microsecond=0).isoformat() + "Z"
    # the manifest describes itself too (rebuilt daily by refresh-daily.yml), so it isn't
    # the one "no-date" node in the lineage view.
    files["manifest.json"] = {"dataAsOf": gen, "sourceCadence": "daily"}

    manifest = {
        "generatedAt": gen,
        "note": "Per-file freshness for the committed data snapshots. 'dataAsOf' is the newest "
                "record/build time inside the file; 'sourceCadence' is how often OpenFEMA reloads "
                "the underlying dataset. Real OpenFEMA figures — not endorsed by FEMA.",
        "files": files,
    }
    out = os.path.join(DATA, "manifest.json")
    json.dump(manifest, open(out, "w"), separators=(",", ":"))
    print(f"wrote data/manifest.json — {len(files)} files")
    for n, e in files.items():
        print(f"  {n:32s} {e.get('bytes',0):>9,}B  asOf={e.get('dataAsOf','—')}  src={e.get('sourceCadence','—')}")


if __name__ == "__main__":
    main()
