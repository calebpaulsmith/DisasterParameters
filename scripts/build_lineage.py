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
  docs/openfema-definitions/*.json   field dictionaries (→ columnsUnused per source)

Freshness (bytes / dataAsOf / sourceCadence) is intentionally NOT embedded — it is
volatile (changes every refresh) and is joined live from data/manifest.json at render
time (see docs/lineage-plan.md §5). The output is therefore DETERMINISTIC given the
seed + the set of data files, which is what makes --check a stable gate.

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

# Artifacts that are NOT part of the lineage graph (the lineage feature's own files).
SELF_FILES = {"lineage.json", "lineage.seed.json"}


def load_json(path, default=None):
    if not os.path.exists(path):
        return default
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def list_artifacts():
    """Every COMMITTED data/*.json (except the lineage feature's own) is an artifact.

    Skips `_`-prefixed files: that is the repo's .gitignore convention for regenerable
    intermediates/caches (data/_request_cache.json, data/_ihp_dc_cache.json, …). Those
    are NOT committed, so they must never become artifact nodes — otherwise the manifest
    would depend on whatever caches happen to sit in data/ locally (the build scripts
    create them), and a clean CI checkout (no caches) would regenerate a different
    manifest and fail --check though nothing real drifted. Keeping the enumeration to
    committed files makes the output deterministic. (Equivalent, convention-free option:
    enumerate `git ls-files data/*.json`.)
    """
    out = []
    for fn in sorted(os.listdir(DATA)):
        if fn.endswith(".json") and fn not in SELF_FILES and not fn.startswith("_"):
            out.append(fn)
    return out


_script_cache = {}
def script_text(rel_name):
    """Read a transform's script once (cached). Empty string for browser fns / missing."""
    if rel_name in _script_cache:
        return _script_cache[rel_name]
    p = os.path.join(ROOT, rel_name)
    txt = ""
    if "/" in rel_name and os.path.exists(p):
        with open(p, encoding="utf-8", errors="ignore") as f:
            txt = f.read()
    _script_cache[rel_name] = txt
    return txt


def column_in(col, txt):
    """True if a column is referenced in a GROUNDED way (quoted string or attribute/
    bracket access) — e.g. "disasterNumber", 'ratedFloodZone', .state, [col] — rather
    than as incidental prose. Reduces coincidental matches; still a heuristic."""
    if not txt:
        return False
    return re.search(r'''["'.\[]''' + re.escape(col) + r"\b", txt, re.IGNORECASE) is not None


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

    # --- artifacts: derived from data/*.json, prose merged from seed ---
    # NOTE: freshness (bytes / dataAsOf / sourceCadence) is deliberately NOT baked in
    # here. That data lives in data/manifest.json and changes on every refresh; baking
    # it would make this committed manifest churn and break the --check staleness gate
    # on any branch whose data differs (e.g. a PR merged against a freshly-refreshed
    # main). Per docs/lineage-plan.md §5, health/freshness is joined at RENDER time:
    # the view looks up manifest.files[<artifact id>]. We only record the pointer.
    art_prose = seed.get("artifacts", {}) or {}
    artifacts = []
    for fn in list_artifacts():
        prose = art_prose.get(fn, {})
        artifacts.append({
            "id": fn,
            "name": f"data/{fn}",
            "freshnessFrom": "data/manifest.json",   # join by id at render time
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

    # index.html text — for attributing live-source columns to the surfaces that read
    # them directly (no offline transform in between, e.g. NWS alerts / USGS gages).
    index_txt = ""
    _ip = os.path.join(ROOT, "index.html")
    if os.path.exists(_ip):
        with open(_ip, encoding="utf-8", errors="ignore") as f:
            index_txt = f.read()
    seed_surfaces = seed.get("surfaces", [])

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
        # --- column-level usage (Phase 3): for each used column, which CONSUMING
        # transform scripts actually reference it? Grounded in the real code (column_in),
        # so it's deterministic + regenerable. Columns claimed used but found in NO
        # consuming script are flagged (columnsDeclaredUnfound) — a slop/staleness signal.
        consumers = [t for t in transforms if s["id"] in t["reads"] and "/" in t["name"]]
        surf_consumers = [su for su in seed_surfaces if s["id"] in (su.get("reads") or [])]
        col_usage, col_unfound = {}, []
        for col in used:
            hits = [t["id"] for t in consumers if column_in(col, script_text(t["name"]))]
            # live / direct sources: a surface reads the source straight from index.html
            if surf_consumers and column_in(col, index_txt):
                hits += [su["id"] for su in surf_consumers]
            if hits:
                col_usage[col] = hits
            elif consumers or surf_consumers:   # flag only when SOMETHING could consume it
                col_unfound.append(col)
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
            "columnUsage": col_usage,                  # column -> [transform ids that reference it]
            "columnsDeclaredUnfound": col_unfound,     # used but not found in any consuming script
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
