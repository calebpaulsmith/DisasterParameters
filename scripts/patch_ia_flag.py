#!/usr/bin/env python3
"""
Correct the individual-assistance declaration flag in the committed data/disasters.json,
IN PLACE, touching ONLY two fields per record:

  iaDeclared        = ihProgramDeclared OR iaProgramDeclared   (FEMA's official "IA-authorized"
                                                                rule, per the OpenFEMA dictionary)
  iaProgramDeclared = iaProgramDeclared                        (provenance only; the legacy flag)

WHY THIS SCRIPT (and not a full pipeline re-run): re-running enrich.py / the full add_history
path recomputes and can DROP the authoritative `costs` and `gages` blocks (CLAUDE.md "costs
landmine"). This script never recomputes costs/hz/gages — it mutates the two flag fields on the
loaded records and re-dumps, so every other key is preserved byte-for-byte.

Background: earlier builds set `iaDeclared = bool(ihProgramDeclared)` and never pulled
`iaProgramDeclared`; the committed value had also gone stale (21 instead of the true 34). For
Region 5 the corrected count is 34 and reconciles exactly with `costs.ihpTotal > 0`.

NEEDS NETWORK (CORS-open OpenFEMA). Resumable via a git-ignored cache. Idempotent.
Run from repo root:  python3 scripts/patch_ia_flag.py
"""
import os, json, time, urllib.request, urllib.parse

HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.dirname(HERE)
DATA = os.path.join(ROOT, "data")
DISASTERS = os.path.join(DATA, "disasters.json")
CACHE = os.path.join(DATA, "_ia_flag_cache.json")
BASE = "https://www.fema.gov/api/open/v2/DisasterDeclarationsSummaries"
EXPECT_IH = 34   # Region 5 FY2007-2026 sanity targets (abort if upstream disagrees)
EXPECT_IA = 8


def get(url, tries=4):
    for _ in range(tries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "DisasterParameters/patch-ia-flag"})
            with urllib.request.urlopen(req, timeout=60) as r:
                return json.load(r)
        except Exception:
            time.sleep(1.5)
    return None


def fetch_flags(dn):
    """Return (ih, ia) booleans for a disaster, OR-accumulated across its rows."""
    flt = urllib.parse.quote(f"disasterNumber eq {dn}")
    sel = "disasterNumber,ihProgramDeclared,iaProgramDeclared"
    d = get(f"{BASE}?$filter={flt}&$select={sel}&$top=1000&$format=json")
    rows = (d or {}).get("DisasterDeclarationsSummaries", [])
    ih = any(bool(r.get("ihProgramDeclared")) for r in rows)
    ia = any(bool(r.get("iaProgramDeclared")) for r in rows)
    return ih, ia, len(rows)


def reordered(rec, ia_declared, ia_program):
    """Rebuild the record dict so `iaProgramDeclared` sits right after `iaDeclared`
    (minimal, readable diff), preserving all other keys/values byte-for-byte."""
    out = {}
    for k, v in rec.items():
        if k == "iaProgramDeclared":
            continue  # drop any existing copy; we reinsert in the canonical slot
        out[k] = ia_declared if k == "iaDeclared" else v
        if k == "iaDeclared":
            out["iaProgramDeclared"] = ia_program
    return out


def main():
    records = json.load(open(DISASTERS))
    cache = json.load(open(CACHE)) if os.path.exists(CACHE) else {}

    before = sum(1 for r in records if r.get("iaDeclared"))
    new_records = []
    for rec in records:
        dn = rec["disasterNumber"]
        key = str(dn)
        if key not in cache:
            ih, ia, nrows = fetch_flags(dn)
            cache[key] = {"ih": ih, "ia": ia}
            json.dump(cache, open(CACHE, "w"))
            print(f"  DR-{dn}: ih={int(ih)} ia={int(ia)} ({nrows} rows)")
        c = cache[key]
        new_records.append(reordered(rec, bool(c["ih"] or c["ia"]), bool(c["ia"])))

    # --- reconciliation guard (abort before writing if anything is off) ---
    flagged = {r["disasterNumber"] for r in new_records if r["iaDeclared"]}
    ihp_money = {r["disasterNumber"] for r in new_records
                 if (r.get("costs") or {}).get("ihpTotal", 0) > 0}
    n_flag = len(flagged); n_ia = sum(1 for r in new_records if r.get("iaProgramDeclared"))
    only_flag = sorted(flagged - ihp_money); only_money = sorted(ihp_money - flagged)

    print(f"\n  iaDeclared: {before} -> {n_flag} (target {EXPECT_IH}); "
          f"iaProgramDeclared={n_ia} (target {EXPECT_IA}); ihpTotal>0={len(ihp_money)}")
    problems = []
    if n_flag != EXPECT_IH:
        problems.append(f"iaDeclared={n_flag}, expected {EXPECT_IH}")
    if flagged != ihp_money:
        problems.append(f"flagged set != ihpTotal>0 set "
                        f"(flagged-only={only_flag}, money-only={only_money})")
    if n_ia != EXPECT_IA:
        problems.append(f"iaProgramDeclared={n_ia}, expected {EXPECT_IA}")
    if problems:
        print("\n  ABORT — not writing. Reconciliation failed:")
        for p in problems:
            print("   -", p)
        print("  (If OpenFEMA legitimately changed, update EXPECT_* and re-run.)")
        return

    json.dump(new_records, open(DISASTERS, "w"), separators=(",", ":"))
    print(f"  wrote data/disasters.json — iaDeclared={n_flag}, iaProgramDeclared={n_ia}, "
          f"reconciles with ihpTotal>0 ({len(ihp_money)}).")


if __name__ == "__main__":
    main()
