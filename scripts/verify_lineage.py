#!/usr/bin/env python3
"""verify_lineage.py — the "Guardian" for the lineage manifest.

OFFLINE, no network. Phase 0 of docs/lineage-plan.md ("Provenance Atlas").

A lineage tool that lies is worse than none. This script is the anti-AI-slop
guardrail: it checks the BUILT manifest (data/lineage.json) against the real repo
and EXITS NONZERO on any mismatch, so CI goes red the moment the documented data
web and the actual code disagree. It is the real product; the eventual graph is the
demo. See docs/lineage-plan.md §6.

Run
  python3 scripts/verify_lineage.py            # check; exit 1 on any error
  python3 scripts/verify_lineage.py --strict   # also treat WARNINGS as failures

What it enforces (errors unless noted):
  Artifacts
    - every artifact node's file exists in data/
    - NO ORPHAN ARTIFACTS: every committed data/*.json has an artifact node
    - every artifact has >=1 producedBy transform (forces the web to stay documented)
  Transforms
    - a script-path transform's file exists; a browser-fn transform's name appears in index.html
    - every writes/reads id resolves (no dangling edges)
    - an offline transform's written filenames literally appear in its script
    - (warning) a read OpenFEMA source's dataset name appears in the script
  Surfaces
    - every reads id resolves
    - every artifact a surface reads is actually fetch()-ed in index.html
    - NO UNTRACKED CONSUMPTION: every fetch("data/*.json") in index.html is covered by a surface
  Sources
    - providerId resolves
    - columnsUsed is a subset of the dictionary's columns (catches typo'd/hallucinated fields)
"""
import json, os, re, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, "data")
LINEAGE = os.path.join(DATA, "lineage.json")
INDEX = os.path.join(ROOT, "index.html")
SELF_FILES = {"lineage.json", "lineage.seed.json"}

errors, warnings = [], []
def err(m): errors.append(m)
def warn(m): warnings.append(m)


def load_json(path, default=None):
    if not os.path.exists(path):
        return default
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def dict_columns(rel_path):
    d = load_json(os.path.join(ROOT, rel_path))
    if not d:
        return None
    names = set()
    def walk(o):
        if isinstance(o, dict):
            if isinstance(o.get("name"), str):
                names.add(o["name"].lower())
            for v in o.values():
                walk(v)
        elif isinstance(o, list):
            for v in o:
                walk(v)
    walk(d)
    return names


def main():
    strict = "--strict" in sys.argv
    man = load_json(LINEAGE)
    if man is None:
        sys.exit("ERROR: data/lineage.json not found — run scripts/build_lineage.py first.")

    index_txt = ""
    if os.path.exists(INDEX):
        with open(INDEX, encoding="utf-8") as f:
            index_txt = f.read()
    else:
        warn("index.html not found — surface/fetch checks skipped.")

    providers   = {p["id"]: p for p in man.get("providers", [])}
    sources     = {s["id"]: s for s in man.get("sources", [])}
    artifacts   = {a["id"]: a for a in man.get("artifacts", [])}
    transforms  = {t["id"]: t for t in man.get("transforms", [])}
    surfaces    = {s["id"]: s for s in man.get("surfaces", [])}
    data_ids    = set(artifacts) | set(sources)   # valid edge endpoints

    # --- artifacts ---
    # Skip `_`-prefixed files: the .gitignore convention for regenerable caches/
    # intermediates (data/_request_cache.json, …). They are not committed, so they must
    # not count as orphan artifacts when a build script left one in data/ locally. This
    # mirrors list_artifacts() in build_lineage.py — keep the two in sync.
    committed = {fn for fn in os.listdir(DATA)
                 if fn.endswith(".json") and fn not in SELF_FILES and not fn.startswith("_")}
    for fn in sorted(committed - set(artifacts)):
        err(f"ORPHAN ARTIFACT: data/{fn} is committed but has no artifact node "
            f"in lineage.json (add it to the seed / rebuild).")
    for a in artifacts.values():
        p = os.path.join(ROOT, a.get("name", f"data/{a['id']}"))
        if not os.path.exists(p):
            err(f"artifact '{a['id']}': file {a.get('name')} does not exist.")
        if not a.get("producedBy") and not a.get("deprecated"):
            err(f"artifact '{a['id']}': no producedBy transform — every artifact "
                f"must name the transform that builds it.")

    # --- transforms ---
    for t in transforms.values():
        name = t.get("name", "")
        runtime = t.get("runtime", "offline")
        script_txt = None
        if "/" in name:  # a file path, e.g. scripts/build_county_map.py
            sp = os.path.join(ROOT, name)
            if not os.path.exists(sp):
                err(f"transform '{t['id']}': script {name} not found.")
            else:
                with open(sp, encoding="utf-8") as f:
                    script_txt = f.read()
        else:            # a browser function, e.g. applyNfip()
            ident = re.sub(r"\(.*\)$", "", name).strip()
            if ident and index_txt and ident not in index_txt:
                err(f"transform '{t['id']}': browser fn '{ident}' not found in index.html.")
        for w in t.get("writes", []):
            if w not in artifacts:
                err(f"transform '{t['id']}': writes unknown artifact '{w}'.")
            elif script_txt is not None and runtime == "offline" and w not in script_txt:
                err(f"transform '{t['id']}': declares it writes '{w}' but the filename "
                    f"never appears in {name}.")
        for r in t.get("reads", []):
            if r not in data_ids:
                err(f"transform '{t['id']}': reads unknown id '{r}' "
                    f"(not a source or artifact).")
            elif script_txt is not None and r in sources:
                # A script "uses" a source if its dataset name OR its endpoint host
                # appears in the script (some scripts hit the source by URL, not label).
                src = sources[r]
                ds = src.get("name", "")
                tokens = [ds] if ds else []
                m = re.match(r"https?://([^/]+)", src.get("endpoint") or "")
                if m:
                    tokens.append(m.group(1))
                if tokens and not any(tok and tok in script_txt for tok in tokens):
                    warn(f"transform '{t['id']}': reads source '{ds}' but neither its "
                         f"name nor endpoint host appears in {name} (check the mapping, "
                         f"or it's reached indirectly via a cached intermediate).")

    # --- surfaces ---
    # Each surface's fetches are checked against ITS OWN location HTML (planner.html,
    # lineage.html, …), falling back to index.html — a standalone page's artifact reads
    # must not pass merely because index.html happens to fetch the same file.
    FETCH_RE = r"""fetch\(\s*["'`]data/([\w.]+\.json)"""
    page_txt = {"index.html": index_txt}
    def txt_for(loc):
        loc = loc if loc and loc.endswith(".html") else "index.html"
        if loc not in page_txt:
            p = os.path.join(ROOT, loc)
            page_txt[loc] = open(p, encoding="utf-8").read() if os.path.exists(p) else ""
        return loc, page_txt[loc]
    for s in surfaces.values():
        loc, txt = txt_for(s.get("location", "index.html"))
        fetched_here = set(re.findall(FETCH_RE, txt))
        for r in s.get("reads", []):
            if r not in data_ids:
                err(f"surface '{s['id']}': reads unknown id '{r}'.")
            elif r in artifacts and txt and r not in fetched_here:
                err(f"surface '{s['id']}': declares it reads '{r}' but {loc} "
                    f"never fetch()es data/{r}.")
    # no untracked consumption: every fetch on every surface page is declared by a
    # surface that lives on that page
    for loc, txt in page_txt.items():
        reads_here = {r for s in surfaces.values()
                      if txt_for(s.get("location", "index.html"))[0] == loc
                      for r in s.get("reads", [])}
        for fn in sorted(set(re.findall(FETCH_RE, txt)) - SELF_FILES):
            if fn not in reads_here:
                err(f"UNTRACKED CONSUMPTION: {loc} fetches data/{fn} but no surface "
                    f"on that page declares it as a source.")

    # --- sources ---
    for s in sources.values():
        if s.get("providerId") and s["providerId"] not in providers:
            err(f"source '{s['id']}': unknown providerId '{s['providerId']}'.")
        if s.get("dictionary"):
            avail = dict_columns(s["dictionary"])
            if avail is None:
                warn(f"source '{s['id']}': dictionary {s['dictionary']} not found.")
            else:
                for c in s.get("columnsUsed", []):
                    if c.lower() not in avail:
                        err(f"source '{s['id']}': columnsUsed '{c}' is not in the "
                            f"dictionary {s['dictionary']} (typo or wrong field?).")

    # --- report ---
    for w in warnings:
        print(f"  WARN  {w}")
    for e in errors:
        print(f"  FAIL  {e}")
    n_art = len(artifacts); n_tr = len(transforms); n_su = len(surfaces); n_so = len(sources)
    print(f"\nlineage.json: {len(providers)} providers · {n_so} sources · "
          f"{n_tr} transforms · {n_art} artifacts · {n_su} surfaces")
    fail = bool(errors) or (strict and bool(warnings))
    if fail:
        print(f"GUARDIAN: FAIL — {len(errors)} error(s)"
              + (f", {len(warnings)} warning(s)" if strict else "") + ".")
        sys.exit(1)
    print(f"GUARDIAN: PASS"
          + (f" ({len(warnings)} warning(s))" if warnings else "") + ".")


if __name__ == "__main__":
    main()
