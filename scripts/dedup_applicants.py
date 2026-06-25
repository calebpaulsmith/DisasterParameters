#!/usr/bin/env python3
"""
Dedupe per-county PA applicant entries in data/county_declarations.json.

OpenFEMA PublicAssistanceFundedProjectsDetails carries the same real applicant under
several name strings — case/punctuation variants, "(DO NOT USE)" markers, abbreviation
differences (DEPT vs DEPARTMENT), "X Township" vs "X (TOWNSHIP OF)", duplicated segments,
trailing record suffixes "(1)/(2)". This collapses those WITHOUT fuzzy guessing.

SAFE rule (auto-applied): within a county, entries whose ORDER-PRESERVING normalized name
string is identical are merged (pa/projects summed, dns unioned, nDisasters recomputed).
Order is preserved so "Forest Park" and "Park Forest" never collide. The canonical display
name is the cleanest variant (non-marked, mixed-case, most projects).

REVIEW rule (reported, NOT applied): "(DO NOT USE)" entries that don't exact-match a sibling,
plus non-marked near-duplicates — these need a human because similarity merges misattribute
money (e.g. "Houston County DOT" vs "Houston" city). Printed for manual adjudication.

Usage:
  python3 scripts/dedup_applicants.py            # dry-run: print the full merge + review report
  python3 scripts/dedup_applicants.py --apply     # apply SAFE merges, rewrite county_declarations.json
Offline, idempotent, no network.
"""
import os, json, re, sys, collections
DATA=os.path.join(os.path.dirname(__file__),"..","data")
CDP=os.path.join(DATA,"county_declarations.json")

MARK=re.compile(r'\(?\s*do\s*not\s*use\s*\)?(\s*-\s*)?|\bduplicate\b|\bobsolete\b|\bdelete\b', re.I)
ABBR=[(r'\bdept\b','department'),(r'\bdepts\b','departments'),(r'\bhwy\b','highway'),
      (r'\btwp\b','township'),(r'\bassn\b','association'),(r'\bassoc\b','association'),
      (r'\bcoop\b','cooperative'),(r'\bco op\b','cooperative'),(r'\bcomm\b','commission'),
      (r'\bdist\b','district'),(r'\butil\b','utility'),(r'\bsvc\b','service'),(r'\bsvcs\b','services')]
TYPEWORD=("city","county","township","town","village","borough")

def is_marked(n): return bool(MARK.search(n))

# Curated merges that aren't deterministic but are confirmed the same entity by inspection
# (and word-order / typo near-duplicates). (county, state, exact source name) -> canonical target
# name (must be an existing applicant entry in that county). EXCLUDES genuinely-distinct lookalikes
# like "Forest Park" vs "Park Forest". See the REVIEW report for entries deliberately left alone.
MANUAL={
  # confirmed "(DO NOT USE)"/defunct records folded into their real entity
  ("St. Louis","MN","(DO NOT USE) DULUTH"):"Duluth, City of",
  ("Meigs","OH","DO NOT USE - MEIGS COUNTY ENGINEER (2)"):"Meigs County Engineer (Meigs County Highway Department)",
  ("Houston","MN","DO NOT USE - HOUSTON COUNTY DEPT OF TRANSPORTATION /"):"HOUSTON (COUNTY) / HIGHWAY DEPARTMENT",
  ("Blue Earth","MN","(DO NOT USE) BLUE EARTH COUNTY/ HIGHWAY DEPARTMENT"):"Blue Earth County / Public Works",
  ("Jackson","MN","JACKSON (COUNTY) / PUBLIC WORKS (DO NOT USE)"):"Jackson County Highway",
  ("Jackson","MN","JACKSON (COUNTY) DO NOT USE"):"Jackson County Highway",
  ("Big Stone","MN","DO NOT USE - Big Stone County"):"Big Stone County / Highway Department",
  ("Yellow Medicine","MN","DO NOT USE (YELLOW MEDICINE (COUNTY) / DITCH DEPARTMENT)"):"Yellow Medicine County / Drainage",
  ("Stearns","MN","DO NOT USE ROCORI AREA SUPERINTENDENT OFC"):"Rocori Independent School District #750",
  ("Kenosha","WI","DO NOT USE - KENOSHA COUNTY DIVISION OF HIGHWAYS"):"Kenosha County",
  ("Sauk","WI","DO NOT USE - LA VALLE TELEPHONE COOPERATIVE"):"LaValle Telephone Cooperative, Inc.",
  # non-marked word-order / typo / repeated-segment near-duplicates (same entity)
  ("St. Louis","MN","St. Louis County / Public Work Department"):"ST. LOUIS (COUNTY) / PUBLIC WORKS DEPARTMENT",
  ("Steele","MN","OWATONNA / OWATONNA PUBLIC UTILITIES / OWATONNA PUBLIC UTILITIES"):"Owatonna Public Utilities",
  ("Perry","IN","TOWN OF TROY/UTILITIES"):"Town of Troy/Troy Utilities",
  ("Winnebago","WI","Winnebago County Housing Authority (Oshkosh / Winnebago County Housing Authority)"):"Oshkosh / Winnebago County Housing Authority",
  ("Sangamon","IL","AUBURN, CITY OF"):"City of Auburn (Auburn, City of)",
  ("Aitkin","MN","HILL CITY"):"HILL CITY CITY OF",
  ("White","IN","MONON, TOWN OF"):"Town of Monon (Monon, Town of)",
}

def normalize(n):
    s=MARK.sub(' ', n.lower())
    s=re.sub(r'\(\d+\)\s*$',' ',s)             # trailing record suffix "(1)" "(2)"
    s=re.sub(r'[.,/()\'\"&]', ' ', s)          # punctuation -> space
    s=re.sub(r'\s+',' ',s).strip()
    for pat,rep in ABBR: s=re.sub(pat,rep,s)
    # collapse an immediately-repeated trailing segment: "highway department highway department"
    parts=s.split()
    for seglen in (3,2,1):
        if len(parts)>=2*seglen and parts[-seglen:]==parts[-2*seglen:-seglen]:
            parts=parts[:-seglen]
    s=' '.join(parts)
    # canonicalize a trailing/leading type-word into "type of CORE" (order-preserving on CORE)
    m=re.match(r'(.*?)\s+'+ '('+ '|'.join(TYPEWORD) +')'+r'(\s+of)?$', s)
    if m and m.group(1):
        s=f"{m.group(2)} of {m.group(1).strip()}"
    else:
        m=re.match(r'('+'|'.join(TYPEWORD)+r')\s+of\s+(.*)$', s)
        if m: s=f"{m.group(1)} of {m.group(2).strip()}"
    return re.sub(r'\s+',' ',s).strip()

def core_tokens(n):
    s=normalize(n)
    return set(t for t in s.split() if t not in ('of','the'))

def canonical(members):
    """pick the cleanest display name among merged variants."""
    def score(a):
        marked=is_marked(a['name'])
        mixed=any(c.islower() for c in a['name']) and any(c.isupper() for c in a['name'])
        return (0 if marked else 1, 1 if mixed else 0, a.get('projects',0), a.get('pa',0), -len(a['name']))
    return max(members, key=score)['name']

def main():
    apply="--apply" in sys.argv
    cd=json.load(open(CDP)); co=cd["counties"]
    merges=[]   # (county,state,canonical,[variant names])
    review=[]   # (county,state,marked_name,$,best_target_or_None)
    n_before=0; n_after=0; merged_groups=0
    for f,o in co.items():
        ap=o.get("applicants") or []
        if not ap: continue
        n_before+=len(ap)
        groups=collections.defaultdict(list)
        for a in ap:
            tgt=MANUAL.get((o["name"],o["state"],a["name"]))   # curated → group with the target
            groups[normalize(tgt) if tgt else normalize(a["name"])].append(a)
        new=[]
        for k,mem in groups.items():
            if len(mem)==1: new.append(mem[0]); continue
            merged_groups+=1
            forced=[MANUAL[(o["name"],o["state"],m["name"])] for m in mem
                    if (o["name"],o["state"],m["name"]) in MANUAL]
            canon=forced[0] if forced else canonical(mem)   # curated target wins over heuristic
            dns=sorted(set(d for m in mem for d in (m.get("dns") or [])))
            new.append({"name":canon,
                        "pa":sum(m.get("pa",0) for m in mem),
                        "projects":sum(m.get("projects",0) for m in mem),
                        "nDisasters":len(dns) or max(m.get("nDisasters",0) for m in mem),
                        "dns":dns,
                        # provenance: every source record folded in (name + PA $). OpenFEMA per-applicant
                        # numeric IDs aren't carried in this dataset, so name+pa are the identifiers.
                        "merged":[{"name":m["name"],"pa":m.get("pa",0)} for m in sorted(mem,key=lambda x:-x.get("pa",0))]})
            merges.append((o["name"],o["state"],canon,[m["name"] for m in mem]))
        # REVIEW: marked entries that stayed singletons (no exact sibling)
        kept_norm={normalize(x["name"]) for x in new}
        for a in new:
            if is_marked(a["name"]):
                mt=core_tokens(a["name"]); best=None;bj=0
                for b in new:
                    if b is a or is_marked(b["name"]): continue
                    tb=core_tokens(b["name"])
                    if mt and tb and mt<=tb:                 # marked is a strict subset → safe direction only
                        j=len(mt&tb)/len(mt|tb)
                        if j>bj: bj=j; best=b["name"]
                review.append((o["name"],o["state"],a["name"],a.get("pa",0),best))
        new.sort(key=lambda x:-x.get("pa",0))
        o["applicants"]=new; o["nApplicants"]=len(new)
        n_after+=len(new)

    # --- also dedup each state's statewide (no-county) PA applicant list (same rules, no MANUAL) ---
    for st,sd in cd.get("states",{}).items():
        ap=sd.get("paStatewideApplicants") or []
        if not ap: continue
        n_before+=len(ap)
        groups=collections.defaultdict(list)
        for a in ap: groups[normalize(a["name"])].append(a)
        new=[]
        for k,mem in groups.items():
            if len(mem)==1: new.append(mem[0]); continue
            merged_groups+=1
            canon=canonical(mem)
            dns=sorted(set(d for m in mem for d in (m.get("dns") or [])))
            new.append({"name":canon,"pa":sum(m.get("pa",0) for m in mem),
                        "projects":sum(m.get("projects",0) for m in mem),
                        "nDisasters":len(dns) or max(m.get("nDisasters",0) for m in mem),
                        "dns":dns,
                        "merged":[{"name":m["name"],"pa":m.get("pa",0)} for m in sorted(mem,key=lambda x:-x.get("pa",0))]})
            merges.append((f"{st} · statewide","",canon,[m["name"] for m in mem]))
        new.sort(key=lambda x:-x.get("pa",0))
        sd["paStatewideApplicants"]=new
        n_after+=len(new)

    print(f"{'APPLY' if apply else 'DRY-RUN'} · applicant entries {n_before} -> {n_after} "
          f"({n_before-n_after} merged away across {merged_groups} groups)")
    print(f"\n=== SAFE MERGES ({len(merges)}) — canonical  <=  [variants] ===")
    for cnty,st,canon,vs in sorted(merges,key=lambda x:x[0]):
        print(f"  [{cnty},{st}] {canon!r}  <=  {vs}")
    print(f"\n=== REVIEW — '(DO NOT USE)'/marked entries NOT auto-merged ({len(review)}) ===")
    for cnty,st,nm,pa,best in sorted(review,key=lambda x:-x[3]):
        print(f"  [{cnty},{st}] ${pa:,}  {nm!r}  -> suggest {best!r}" if best
              else f"  [{cnty},{st}] ${pa:,}  {nm!r}  -> no safe target (left as-is)")
    if apply:
        cd["_applicantsDeduped"]=True
        json.dump(cd,open(CDP,"w"),separators=(",",":"))
        print("\nwrote",CDP)
    else:
        print("\n(dry-run — re-run with --apply to write)")

if __name__=="__main__": main()
