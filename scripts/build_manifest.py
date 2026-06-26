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
import os, json, datetime as dt

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
DATA = os.path.join(ROOT, "data")

# Declared OpenFEMA refresh cadence (accrualPeriodicity) for the source each file leans on,
# so the UI can say "source updates daily/monthly; snapshot is N days old".
SOURCE_CADENCE = {
    "disasters.json": "daily",
    "county_declarations.json": "daily",
    "recent.json": "daily",
    "newsreel.json": "daily",
    "disasters_national.json": "daily",
    "timeline.json": "daily",
    "covid.json": "daily",
    "gages.json": "as-needed (NWS AHPS)",
    "nfip.json": "monthly",            # future: FimaNfipClaims/Policies are R/P1M
}


def freshness(obj):
    """Pull a representative freshness date from a file's own contents, if present."""
    if not isinstance(obj, dict):
        return None
    for k in ("generatedAt", "generated"):
        if obj.get(k):
            return str(obj[k])
    if isinstance(obj.get("asOf"), dict) and obj["asOf"]:
        # e.g. recent.json {"asOf":{"PA":"2026-06-23","HM":"2026-06-05"}}
        return max(str(v) for v in obj["asOf"].values() if v)
    return None


def main():
    files = {}
    for name in sorted(os.listdir(DATA)):
        if not name.endswith(".json") or name == "manifest.json":
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

    manifest = {
        "generatedAt": dt.datetime.utcnow().replace(microsecond=0).isoformat() + "Z",
        "note": "Per-file freshness for the committed data snapshots. 'dataAsOf' is the newest "
                "record/build time inside the file; 'sourceCadence' is how often OpenFEMA reloads "
                "the underlying dataset. Real OpenFEMA figures — not endorsed by FEMA.",
        "files": files,
    }
    out = os.path.join(DATA, "manifest.json")
    json.dump(manifest, open(out, "w"), separators=(",", ":"))
    print(f"wrote data/manifest.json — {len(files)} files")
    for n, e in files.items():
        print(f"  {n:32s} {e['bytes']:>9,}B  asOf={e.get('dataAsOf','—')}  src={e.get('sourceCadence','—')}")


if __name__ == "__main__":
    main()
