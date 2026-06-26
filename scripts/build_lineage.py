#!/usr/bin/env python3
"""build_lineage.py — assemble data/lineage.json (the lineage manifest).

OFFLINE, no network. Phase 0 of docs/lineage-plan.md ("Provenance Atlas").

The manifest is the data behind the future Lineage view. Its STRUCTURE is partly
hand-authored (the parts a scanner can't reliably infer: which OpenFEMA dataset +
columns each transform consumes, human descriptions) and partly AUTO-DERIVED from
the repo (the parts that drift if hand-kept: the list of committed artifacts, their
freshness, producedBy edges, computed columnsUnused). The split is the whole point —
see docs/lineage-plan.md §3/§4.

Inputs
  data/lineage.seed.json    hand-authored truth: providers, sources(+columnsUsed),
                            transforms(reads/writes), surfaces(reads), plus optional
                            artifact prose overrides. Schema documented below.
  data/*.json               the committed artifacts (enumerated → artifact nodes)
  data/manifest.json        per-file freshness (bytes / dataAsOf / sourceCadence)
  docs/openfema-definitions/*.json   field dictionaries (→ columnsUnused per source)

Output
  data/lineage.json         the assembled manifest (a BUILD ARTIFACT — regenerate,
                            don't hand-edit; the Guardian checks it against reality).

Usage
  python3 scripts/build_lineage.py            # (re)build data/lineage.json
  python3 scripts/build_lineage.py --check    # exit 1 if committed lineage.json is stale

Seed schema (data/lineage.seed.json):
  {
    "providers":  [ {"id","name","links":[]} ],
    "sources":    [ {"id","providerId","name","endpoint"?,"binding":"live|snapshot|hybrid",
                     "cadence"?,"dictionary"? (path under repo),"columnsUsed":[]?,
                     "description"?,"links":[]?} ],
    "transforms": [ {"id","name" (script path or browser fn),"runtime":"offline|browser",
                     "schedule"?,"method"?,"reads":[id...],"writes":[artifactId...],
                     "description"?,"links":[]?} ],
    "surfaces":   [ {"id","name","location"?,"reads":[id...],"description"?,"links":[]?} ],
    "artifacts":  { "<file.json>": {"description"?,"deprecated"?:bool,"links":[]?} }   # prose only
  }
Artifact NODES are derived from data/*.json; the "artifacts" seed block only carries
optional prose/flags merged onto them (never the list itself).
"""
import json, os, sys, re

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, "data")
SEED = os.path.join(DATA, "lineage.seed.json")
OUT  = os.path.join(DATA, "lineage.json")
MANIFEST = os.path.join(DATA, "manifest.json")

# Artifacts that are NOT part of the lineage graph (the lineage feature's own files).
SELF_FILES = {"lineage.json", "lineage.seed.json"}


def load_json(path, default=None):
    if not os.path.exists(path):
        return default
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def list_artifacts():
    """Every committed data/*.json (except the lineage feature's own) is an artifact."""
    out = []
    for fn in sorted(os.listdir(DATA)):
        if fn.endswith(".json") and fn not in SELF_FILES:
            out.append(fn)
    return out


def dict_columns(rel_path):
    """Pull the available column/field names from an OpenFEMA dictionary file."""
    d = load_json(os.path.join(ROOT, rel_path))
    if not d:
        return []
    # OpenFEMA dictionaries vary in shape; collect any "name" fields one or two deep.
    names = set()

    def walk(o):
        if isinstance(o, dict):
            if isinstance(o.get("name"), str):
                names.add(o["name"])
            for v in o.values():
                walk(v)
        elif isinstance(o, list):
            for v in o:
                walk(v)
    walk(d)
    return sorted(names)


def build():
    seed = load_json(SEED)
    if seed is None:
        sys.exit(f"ERROR: missing seed file {os.path.relpath(SEED, ROOT)} — "
                 "author it (see schema in this script's docstring).")
    manifest = (load_json(MANIFEST) or {}).get("files", {})

    # --- artifacts: derived from data/*.json, prose merged from seed ---
    art_prose = seed.get("artifacts", {}) or {}
    artifacts = []
    for fn in list_artifacts():
        meta = manifest.get(fn, {})
        prose = art_prose.get(fn, {})
        artifacts.append({
            "id": fn,
            "name": f"data/{fn}",
            "bytes": meta.get("bytes"),
            "dataAsOf": meta.get("dataAsOf"),
            "sourceCadence": meta.get("sourceCadence"),
            "description": prose.get("description"),
            "deprecated": bool(prose.get("deprecated", False)),
            "links": prose.get("links", [f"data/{fn}"]),
            "producedBy": [],   # filled from transforms.writes below
        })
    art_by_id = {a["id"]: a for a in artifacts}

    # --- transforms: from seed; back-fill producedBy onto artifacts ---
    transforms = []
    for t in seed.get("transforms", []):
        node = {
            "id": t["id"],
            "name": t["name"],
            "runtime": t.get("runtime", "offline"),
            "schedule": t.get("schedule"),
            "method": t.get("method"),
            "reads": list(t.get("reads", [])),
            "writes": list(t.get("writes", [])),
            "description": t.get("description"),
            "links": t.get("links", []),
        }
        transforms.append(node)
        for w in node["writes"]:
            if w in art_by_id:
                art_by_id[w]["producedBy"].append(t["id"])

    # --- sources: from seed; compute columnsUnused from the dictionary ---
    sources = []
    for s in seed.get("sources", []):
        used = list(s.get("columnsUsed", []))
        unused = []
        if s.get("dictionary"):
            avail = dict_columns(s["dictionary"])
            if avail:
                used_set = {c.lower() for c in used}
                unused = [c for c in avail if c.lower() not in used_set]
        sources.append({
            "id": s["id"],
            "providerId": s.get("providerId"),
            "name": s["name"],
            "endpoint": s.get("endpoint"),
            "binding": s.get("binding", "snapshot"),
            "cadence": s.get("cadence"),
            "dictionary": s.get("dictionary"),
            "columnsUsed": used,
            "columnsUnused": unused,
            "description": s.get("description"),
            "links": s.get("links", []),
        })

    surfaces = []
    for s in seed.get("surfaces", []):
        surfaces.append({
            "id": s["id"],
            "name": s["name"],
            "location": s.get("location"),
            "reads": list(s.get("reads", [])),
            "description": s.get("description"),
            "links": s.get("links", []),
        })

    return {
        "schema": "provenance-atlas/1",
        "note": "Lineage manifest for the Provenance Atlas view. BUILD ARTIFACT — "
                "regenerate with scripts/build_lineage.py; do not hand-edit. "
                "Verified by scripts/verify_lineage.py. Not endorsed by FEMA.",
        "providers": seed.get("providers", []),
        "sources": sources,
        "transforms": transforms,
        "artifacts": artifacts,
        "surfaces": surfaces,
    }


def dumps(obj):
    return json.dumps(obj, indent=2, ensure_ascii=False) + "\n"


def main():
    check = "--check" in sys.argv
    built = build()
    # Drop generatedAt-style volatile fields? We keep none, so output is deterministic
    # given the inputs — that makes --check a meaningful staleness gate.
    text = dumps(built)
    if check:
        cur = ""
        if os.path.exists(OUT):
            with open(OUT, encoding="utf-8") as f:
                cur = f.read()
        if cur != text:
            sys.exit("ERROR: data/lineage.json is stale — run "
                     "`python3 scripts/build_lineage.py` and commit the result.")
        print("OK: data/lineage.json is up to date.")
        return
    with open(OUT, "w", encoding="utf-8") as f:
        f.write(text)
    n = lambda k: len(built[k])
    print(f"Wrote {os.path.relpath(OUT, ROOT)}: "
          f"{n('providers')} providers, {n('sources')} sources, "
          f"{n('transforms')} transforms, {n('artifacts')} artifacts, "
          f"{n('surfaces')} surfaces.")


if __name__ == "__main__":
    main()
