#!/usr/bin/env python3
"""
Validate the IA / IHP / HA / ONA assistance model — no browser/build required.

Checks (exits non-zero on any failure):

  1. DATA CONSISTENCY (data/disasters.json)
     - iaDeclared === bool(ihpDeclared OR iaProgramDeclared)   (= iaAuthorized)
     - where IHP cost data exists: |ihpTotal - (ihpHousing + ihpOna)| <= 1
  2. UI-LANGUAGE GUARDRAILS
     - no prohibited displayed labels ("IA dollars", "IA obligated", "PA/IA obligated",
       "IA/IHP obligated", "IA/IHP dollars") in index.html / README.md / CLAUDE.md.
       Explanatory lines that explicitly say such a total is unavailable are allowed.
  3. SURVIVOR-ASSISTANCE STATE FIXTURES
     - a Python mirror of index.html `survivorState(d)` is exercised against 6 synthetic
       records (the logic, NOT live counts — OpenFEMA data may change).

Run from repo root:  python3 scripts/verify_assistance_model.py
"""
import os, re, sys, json

HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.dirname(HERE)
DATA = os.path.join(ROOT, "data")
fails = []


def b(x):
    """Normalize an OpenFEMA-ish flag to a bool."""
    if isinstance(x, str):
        return x.strip().lower() in ("1", "true", "t", "yes", "y")
    return bool(x)


# --- mirror of index.html survivorState(d) (keep in sync) -----------------------------------
def survivor_state(d):
    costs = d.get("costs") or {}
    ihp = costs.get("ihpTotal") or d.get("ihp") or 0
    ih = b(d.get("ihpDeclared"))
    ia_only = b(d.get("iaProgramDeclared")) and not ih
    if ih:
        return "IHP_WITH_AWARDS" if ihp > 0 else "IHP_NO_AWARDS"
    if ia_only:
        return "IA_ONLY_ANOMALY" if ihp > 0 else "IA_ONLY"
    return "NONE"


def check_data():
    recs = json.load(open(os.path.join(DATA, "disasters.json")))
    bad_or, bad_recon = [], []
    for r in recs:
        dn = r.get("disasterNumber")
        ia_auth = b(r.get("ihpDeclared")) or b(r.get("iaProgramDeclared"))
        if b(r.get("iaDeclared")) != ia_auth:
            bad_or.append(dn)
        c = r.get("costs") or {}
        ihp, ha, ona = c.get("ihpTotal"), c.get("ihpHousing"), c.get("ihpOna")
        if ihp and (ha is not None or ona is not None):
            if abs((ihp or 0) - ((ha or 0) + (ona or 0))) > 1:
                bad_recon.append((dn, ihp, ha, ona))
    if bad_or:
        fails.append(f"iaDeclared != (ihpDeclared OR iaProgramDeclared) for {bad_or}")
    if bad_recon:
        fails.append(f"ihpTotal != ihpHousing+ihpOna for {bad_recon}")
    print(f"  [data] {len(recs)} records · iaDeclared OR-invariant: "
          f"{'OK' if not bad_or else 'FAIL'} · HA+ONA reconcile: "
          f"{'OK' if not bad_recon else 'FAIL'}")


PROHIBITED = ["IA dollars", "IA obligated", "PA/IA obligated", "IA/IHP obligated", "IA/IHP dollars"]
# a line is allowed (explanatory) if it negates / contrasts rather than labels
ALLOW = ["no separable", "not available", "unavailable", "there is no", "no public",
         "rather than", "instead of", "≠", " vs ", "distinct from", "do not exist", "don't"]


def check_labels():
    viol = []
    for fn in ("index.html", "README.md", "CLAUDE.md"):
        path = os.path.join(ROOT, fn)
        if not os.path.exists(path):
            continue
        for i, line in enumerate(open(path, encoding="utf-8"), 1):
            low = line.lower()
            for phrase in PROHIBITED:
                if phrase.lower() in low and not any(a in low for a in ALLOW):
                    viol.append(f"{fn}:{i}: {phrase!r} -> {line.strip()[:90]}")
    if viol:
        fails.append("prohibited UI labels:\n    " + "\n    ".join(viol))
    print(f"  [labels] scanned index.html/README.md/CLAUDE.md · "
          f"{'OK' if not viol else str(len(viol)) + ' violation(s)'}")


FIXTURES = [
    ({"ihpDeclared": True,  "iaProgramDeclared": False, "costs": {"ihpTotal": 100}}, "IHP_WITH_AWARDS"),
    ({"ihpDeclared": True,  "iaProgramDeclared": False, "costs": {"ihpTotal": 0}},   "IHP_NO_AWARDS"),
    ({"ihpDeclared": False, "iaProgramDeclared": True,  "costs": {"ihpTotal": 0}, "declared": "1999-06-01"}, "IA_ONLY"),
    ({"ihpDeclared": False, "iaProgramDeclared": True,  "costs": {"ihpTotal": 0}, "declared": "2005-09-01"}, "IA_ONLY"),
    ({"ihpDeclared": False, "iaProgramDeclared": True,  "costs": {"ihpTotal": 2500000}}, "IA_ONLY_ANOMALY"),
    ({"ihpDeclared": False, "iaProgramDeclared": False, "costs": {"ihpTotal": 0}}, "NONE"),
]


def check_fixtures():
    bad = []
    for d, expect in FIXTURES:
        got = survivor_state(d)
        if got != expect:
            bad.append(f"expected {expect}, got {got} for {d}")
    if bad:
        fails.append("survivorState fixtures:\n    " + "\n    ".join(bad))
    print(f"  [fixtures] {len(FIXTURES)} survivor-assistance states · "
          f"{'OK' if not bad else 'FAIL'}")


def main():
    print("Verifying IA/IHP assistance model…")
    check_data()
    check_labels()
    check_fixtures()
    if fails:
        print("\nFAILED:")
        for f in fails:
            print(" -", f)
        sys.exit(1)
    print("\nAll assistance-model checks passed.")


if __name__ == "__main__":
    main()
