#!/usr/bin/env python3
"""
Correct/refresh the DECLARATION FLAGS in the committed data/disasters.json, IN PLACE,
touching ONLY flag fields per record (never costs/gages/hz/declared):

  paDeclared        = paProgramDeclared                         (raw OpenFEMA flag)
  iaDeclared        = ihProgramDeclared OR iaProgramDeclared    (= iaAuthorized; FEMA's official
                                                                 "authorized for Individual
                                                                 Assistance" rule, per the
                                                                 OpenFEMA dictionary)
  ihpDeclared       = ihProgramDeclared                         (raw — the modern IHP program)
  iaProgramDeclared = iaProgramDeclared                         (raw — the legacy IA flag)
  hmProgramDeclared = hmProgramDeclared                         (raw — Hazard Mitigation)

Why distinct raw flags? IA (Individual Assistance) is the umbrella authorization; IHP
(Individuals & Households Program) is the modern program that actually carries public
per-disaster dollars. `iaProgramDeclared` without `ihProgramDeclared` is generally a LEGACY
pre-IHP declaration (no comparable IHP dollar series). Keeping the raw flags lets the UI key
"IHP" off `ihpDeclared` rather than the OR, so a legacy/no-IHP record never renders "$0 IHP".

WHY THIS SCRIPT (not a full pipeline re-run): re-running enrich.py / the full add_history path
recomputes and can DROP the authoritative `costs`/`gages` blocks (CLAUDE.md "costs landmine").
This script mutates ONLY the flag fields on the loaded records and re-dumps, so every other key
is preserved byte-for-byte.

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
    """Return {pa,hm,ih,ia} booleans for a disaster, OR-accumulated across its rows."""
    flt = urllib.parse.quote(f"disasterNumber eq {dn}")
    sel = "disasterNumber,paProgramDeclared,hmProgramDeclared,ihProgramDeclared,iaProgramDeclared"
    d = get(f"{BASE}?$filter={flt}&$select={sel}&$top=1000&$format=json")
    rows = (d or {}).get("DisasterDeclarationsSummaries", [])
    flags = {
        "pa": any(bool(r.get("paProgramDeclared")) for r in rows),
        "hm": any(bool(r.get("hmProgramDeclared")) for r in rows),
        "ih": any(bool(r.get("ihProgramDeclared")) for r in rows),
        "ia": any(bool(r.get("iaProgramDeclared")) for r in rows),
    }
    return flags, len(rows)


# canonical declaration-flag block, in the order we want them serialized
FLAG_ORDER = ["paDeclared", "iaDeclared", "ihpDeclared", "iaProgramDeclared", "hmProgramDeclared"]


def reordered(rec, flags):
    """Rebuild the record so the declaration-flag block is grouped & ordered, preserving every
    other key/value byte-for-byte. `flags` is {pa,hm,ih,ia} (raw, OR-accumulated)."""
    derived = {
        "paDeclared": bool(flags["pa"]),
        "iaDeclared": bool(flags["ih"] or flags["ia"]),   # = iaAuthorized
        "ihpDeclared": bool(flags["ih"]),
        "iaProgramDeclared": bool(flags["ia"]),
        "hmProgramDeclared": bool(flags["hm"]),
    }
    out = {}
    for k, v in rec.items():
        if k in FLAG_ORDER:
            continue  # drop existing copies; reinsert as a grouped block after `fy`
        out[k] = v
        if k == "fy":
            for fk in FLAG_ORDER:
                out[fk] = derived[fk]
    # safety: if `fy` wasn't present, append the block
    for fk in FLAG_ORDER:
        if fk not in out:
            out[fk] = derived[fk]
    return out


def main():
    records = json.load(open(DISASTERS))
    cache = json.load(open(CACHE)) if os.path.exists(CACHE) else {}

    before = sum(1 for r in records if r.get("iaDeclared"))
    new_records = []
    for rec in records:
        dn = rec["disasterNumber"]
        key = str(dn)
        entry = cache.get(key)
        if not entry or not all(k in entry for k in ("pa", "hm", "ih", "ia")):  # re-fetch on miss / old schema
            flags, nrows = fetch_flags(dn)
            cache[key] = flags
            json.dump(cache, open(CACHE, "w"))
            print(f"  DR-{dn}: pa={int(flags['pa'])} hm={int(flags['hm'])} "
                  f"ih={int(flags['ih'])} ia={int(flags['ia'])} ({nrows} rows)")
        new_records.append(reordered(rec, cache[key]))

    # --- reconciliation guard (abort before writing if anything is off) ---
    bad_or = [r["disasterNumber"] for r in new_records
              if r["iaDeclared"] != bool(r["ihpDeclared"] or r["iaProgramDeclared"])]
    flagged = {r["disasterNumber"] for r in new_records if r["iaDeclared"]}
    ihp_decl = {r["disasterNumber"] for r in new_records if r["ihpDeclared"]}
    ihp_money = {r["disasterNumber"] for r in new_records
                 if (r.get("costs") or {}).get("ihpTotal", 0) > 0}
    n_flag = len(flagged); n_ia = sum(1 for r in new_records if r["iaProgramDeclared"])
    n_hm = sum(1 for r in new_records if r["hmProgramDeclared"])

    print(f"\n  iaDeclared(=iaAuthorized): {before} -> {n_flag} (target {EXPECT_IH}); "
          f"ihpDeclared={len(ihp_decl)}; iaProgramDeclared={n_ia} (target {EXPECT_IA}); "
          f"hmProgramDeclared={n_hm}; ihpTotal>0={len(ihp_money)}")
    problems = []
    if bad_or:
        problems.append(f"iaDeclared != (ihpDeclared OR iaProgramDeclared) for {bad_or}")
    if n_flag != EXPECT_IH:
        problems.append(f"iaDeclared={n_flag}, expected {EXPECT_IH}")
    if ihp_decl != ihp_money:
        problems.append(f"ihpDeclared set != ihpTotal>0 set "
                        f"(decl-only={sorted(ihp_decl-ihp_money)}, money-only={sorted(ihp_money-ihp_decl)})")
    if n_ia != EXPECT_IA:
        problems.append(f"iaProgramDeclared={n_ia}, expected {EXPECT_IA}")
    if problems:
        print("\n  ABORT — not writing. Reconciliation failed:")
        for p in problems:
            print("   -", p)
        print("  (If OpenFEMA legitimately changed, update EXPECT_* and re-run.)")
        return

    json.dump(new_records, open(DISASTERS, "w"), separators=(",", ":"))
    print(f"  wrote data/disasters.json — iaDeclared={n_flag}, ihpDeclared={len(ihp_decl)}, "
          f"iaProgramDeclared={n_ia}, hmProgramDeclared={n_hm}; ihpDeclared reconciles with ihpTotal>0.")


if __name__ == "__main__":
    main()
