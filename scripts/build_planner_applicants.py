#!/usr/bin/env python3
"""
Build data/planner_applicants.json — the PER-DISASTER PA applicant detail that powers the
Disaster Operations Planner's "PA applicant history" analysis (planner.html).

WHY A SEPARATE FILE: county_declarations.json carries each county applicant only as an
ALL-TIME rollup ({name, pa, projects, dns}). The planner needs the per-disaster grain
("which disasters, how much for EACH") plus per-project damage CATEGORIES — too heavy to
bolt onto county_declarations (which every Geography load fetches), so it's a standalone
artifact fetched lazily by planner.html only.

SOURCES / METHOD (three OpenFEMA endpoints, ledger disasters only — same 80 as disasters.json):
  1. PublicAssistanceFundedProjectsSummaries v1 — one row per applicant × county × disaster
     (applicantName, federalObligatedAmount, numberOfProjects). THE ROW GRAIN of this file.
     Same dataset + bucketing as build_county_applicants.py: every row lands in exactly one of
       c = inCounty (declared R5 county)         u = undeclared (R5 county, no declaration)
       s = statewide/no-county (state agencies)  x = unmatched (non-R5 / unresolvable name)
     so dollars are conserved, never dropped. Buckets u/x surface in the UI labeled as such.
  2. PublicAssistanceFundedProjectsDetails v2 — per project worksheet: damageCategoryCode
     (A..G, Z) + federalShareObligated, but NO applicant name — only applicantId.
  3. PublicAssistanceApplicants v1 — the (disasterNumber, applicantId) → applicantName bridge
     that lets Details' categories be attributed to the same names Summaries uses.

NAME CANONICALIZATION: applicant name variants are grouped with dedup_applicants.normalize()
(imported — single source of truth), and each group's display name prefers the canonical name
already committed in county_declarations.json (post-dedup incl. its MANUAL map) so the planner
lists reconcile with the Geography applicant lists. Cross-dataset (Details/Applicants→Summaries)
attribution uses the same normalize().

CATEGORY JOIN CAVEAT (kept honest in the audit): Summaries v1 and Details v2 are different
endpoints; a Details applicant that never matches a Summaries name keeps its dollars in
audit.catUnmatched (per state, top offenders listed) rather than being force-attributed.
Categories are rolled up per (disaster, applicant) ACROSS counties — Details' county
classification differs from Summaries', so a per-county category split would be false precision.

OUTPUT (data/planner_applicants.json, minified, dictionary-encoded names):
  { generated, source, note,
    dnMeta: {dn: [state, fy, title, begin]},
    names: [ ...applicant display names... ],
    rows:  [ [dn, bucket, key, nameIdx, pa$, projects], ... ]
           bucket c: key = 5-digit FIPS      bucket s: key = state abbr
           bucket u: key = FIPS (undeclared) bucket x: key = "ST|raw county label"
    cats:  { "<dn>|<nameIdx>": {"A":[nProjects, fed$], ...}, ... }
    audit: per state {summaries$, c/s/u/x $, details$, catMatched$, catUnmatched$, flags,
                      topCatUnmatched} + _meta }

Needs network; resumable per-disaster cache data/_plannerappl_cache.json (gitignored `_`).
Re-run any time (idempotent). Run AFTER build_county_map.py + build_county_applicants.py +
dedup_applicants.py so canonical names are current.
"""
import os, sys, json, collections, urllib.request, urllib.parse, time, importlib.util

DATA=os.path.join(os.path.dirname(__file__),"..","data")
sys.path.insert(0,os.path.dirname(__file__))
# import normalize()/canonical-name scoring from the dedup script (single source of truth)
_spec=importlib.util.spec_from_file_location("dedup_applicants",os.path.join(os.path.dirname(__file__),"dedup_applicants.py"))
_dedup=importlib.util.module_from_spec(_spec); _spec.loader.exec_module(_dedup)
normalize=_dedup.normalize; is_marked=_dedup.is_marked

STATE_FULL={"Illinois":"IL","Indiana":"IN","Michigan":"MI","Minnesota":"MN","Ohio":"OH","Wisconsin":"WI"}
SUM_URL="https://www.fema.gov/api/open/v1/PublicAssistanceFundedProjectsSummaries"
DET_URL="https://www.fema.gov/api/open/v2/PublicAssistanceFundedProjectsDetails"
APP_URL="https://www.fema.gov/api/open/v1/PublicAssistanceApplicants"
CACHE=os.path.join(DATA,"_plannerappl_cache.json")
TOL=0.01

def load(n): return json.load(open(os.path.join(DATA,n)))
def num(x):
    try: return float(x or 0)
    except Exception: return 0.0
def get(u,retries=4):
    for i in range(retries):
        try:
            with urllib.request.urlopen(urllib.request.Request(u,headers={"User-Agent":"DisasterParameters/planner-appl"}),timeout=120) as r:
                return json.loads(r.read().decode("utf-8","replace"))
        except Exception:
            time.sleep(2*(i+1))
    return None

def paged(url,ent,filt,sel):
    out=[];skip=0
    while True:
        q=urllib.parse.urlencode({"$filter":filt,"$select":sel,"$top":1000,"$skip":skip,"$format":"json"})
        d=get(f"{url}?{q}"); recs=(d or {}).get(ent,[]) if d else []
        if not recs: break
        out.extend(recs); skip+=len(recs)
        if len(recs)<1000: break
    return out

def pull_summaries(dn):
    """→ [[state_full, county, applicantName, pa, projects]] aggregated for this disaster
    (identical grain to build_county_applicants.pull_disaster)."""
    agg=collections.defaultdict(lambda:[0.0,0])
    for r in paged(SUM_URL,"PublicAssistanceFundedProjectsSummaries",f"disasterNumber eq {dn}",
                   "applicantName,county,state,federalObligatedAmount,numberOfProjects"):
        k=(r.get("state") or "", r.get("county") or "", r.get("applicantName") or "(unnamed)")
        a=agg[k]; a[0]+=num(r.get("federalObligatedAmount")); a[1]+=int(num(r.get("numberOfProjects")))
    return [[k[0],k[1],k[2],round(v[0],2),v[1]] for k,v in agg.items()]

def pull_details(dn):
    """→ [[applicantId, damageCategoryCode, nProjects, fed$]] aggregated for this disaster."""
    agg=collections.defaultdict(lambda:[0,0.0])
    for r in paged(DET_URL,"PublicAssistanceFundedProjectsDetails",f"disasterNumber eq {dn}",
                   "applicantId,damageCategoryCode,federalShareObligated"):
        k=(r.get("applicantId") or "?", (r.get("damageCategoryCode") or "?").strip() or "?")
        a=agg[k]; a[0]+=1; a[1]+=num(r.get("federalShareObligated"))
    return [[k[0],k[1],v[0],round(v[1],2)] for k,v in agg.items()]

def pull_applicant_names(dn):
    """→ {applicantId: applicantName} for this disaster."""
    out={}
    for r in paged(APP_URL,"PublicAssistanceApplicants",f"disasterNumber eq {dn}",
                   "applicantId,applicantName"):
        if r.get("applicantId"): out[r["applicantId"]]=r.get("applicantName") or "(unnamed)"
    return out

def main():
    disasters=load("disasters.json")
    dns=[d["disasterNumber"] for d in disasters]
    dn_meta={str(d["disasterNumber"]):[d["state"],d.get("fy"),d.get("title") or "",d.get("begin") or ""] for d in disasters}
    cd=load("county_declarations.json")
    name2fips={(c["s"],normalize_county(c["n"])):c["f"] for c in load("r5_counties.json")}
    declared=set(cd["counties"].keys())

    # canonical display names already committed (post-dedup): normalized → canonical
    canon={}
    for f,c in cd["counties"].items():
        for a in c.get("applicants") or []: canon.setdefault(normalize(a["name"]),a["name"])
    for st,s in cd["states"].items():
        for key in ("paStatewideApplicants","paUnmatchedApplicants","paUndeclaredApplicants"):
            for a in s.get(key) or []: canon.setdefault(normalize(a["name"]),a["name"])

    cache=json.load(open(CACHE)) if os.path.exists(CACHE) else {}
    cache.setdefault("sum",{}); cache.setdefault("det",{}); cache.setdefault("app",{})
    for i,dn in enumerate(dns,1):
        k=str(dn); fresh=[]
        if k not in cache["sum"]: cache["sum"][k]=pull_summaries(dn); fresh.append(f"sum {len(cache['sum'][k])}")
        if k not in cache["det"]: cache["det"][k]=pull_details(dn); fresh.append(f"det {len(cache['det'][k])}")
        if k not in cache["app"]: cache["app"][k]=pull_applicant_names(dn); fresh.append(f"app {len(cache['app'][k])}")
        if fresh:
            json.dump(cache,open(CACHE,"w"),separators=(",",":"))
            print(f"  [{i}/{len(dns)}] DR-{dn}: {' · '.join(fresh)}")

    # ---- Summaries rows → (dn, bucket, key, normName) groups with $ conservation ----
    names=[]; name_idx={}
    def nid(display):
        if display not in name_idx: name_idx[display]=len(names); names.append(display)
        return name_idx[display]
    def display_for(group_names):
        nkey=normalize(group_names[0])
        if nkey in canon: return canon[nkey]
        # cleanest variant: non-marked, mixed-case, longest tiebreak (mirrors dedup canonical())
        def score(n): return (0 if is_marked(n) else 1, 1 if (any(c.islower() for c in n) and any(c.isupper() for c in n)) else 0, -len(n))
        return max(group_names,key=score)

    groups=collections.defaultdict(lambda:{"pa":0.0,"pr":0,"names":[]})   # (dn,bucket,key,norm) → agg
    st_audit=collections.defaultdict(lambda:collections.defaultdict(float))
    for dn,rows in cache["sum"].items():
        for st_full,cnty,name,pa,proj in rows:
            st=STATE_FULL.get(st_full)
            nrm=normalize(name)
            if not st:
                b,key,ast=("x",f"{st_full}|{cnty}","??")
            else:
                nc=normalize_county(cnty); ast=st
                if not nc or nc=="statewide": b,key=("s",st)
                else:
                    fips=name2fips.get((st,nc))
                    if fips and fips in declared: b,key=("c",fips)
                    elif fips: b,key=("u",fips)
                    else: b,key=("x",f"{st}|{cnty}")
            g=groups[(dn,b,key,nrm)]; g["pa"]+=pa; g["pr"]+=proj; g["names"].append(name)
            st_audit[ast]["sum"]+=pa; st_audit[ast][b]+=pa

    rows=[]
    dnname2idx={}                      # (dn, normName) → nameIdx (for the category join)
    for (dn,b,key,nrm),g in groups.items():
        ni=nid(display_for(g["names"]))
        dnname2idx.setdefault((dn,nrm),ni)
        rows.append([int(dn),b,key,ni,round(g["pa"]),g["pr"]])
    rows.sort(key=lambda r:(r[0],r[1],r[2],-r[4]))

    # ---- Details categories → attach to (dn, applicant) via the Applicants id→name bridge ----
    cats=collections.defaultdict(lambda:collections.defaultdict(lambda:[0,0.0]))   # "dn|ni" → cat → [n,$]
    cat_un=collections.defaultdict(float); top_un=collections.Counter()
    for dn,drs in cache["det"].items():
        id2name=cache["app"].get(dn,{})
        st=dn_meta.get(dn,["??"])[0]
        for aid,cat,npw,fed in drs:
            st_audit[st]["det"]+=fed
            nm=id2name.get(aid)
            ni=dnname2idx.get((dn,normalize(nm))) if nm else None
            if ni is None:
                st_audit[st]["catUn"]+=fed; cat_un[st]+=fed
                top_un[f"{st}|DR-{dn}|{nm or aid}"]+=round(fed)
                continue
            st_audit[st]["catOk"]+=fed
            c=cats[f"{dn}|{ni}"][cat]; c[0]+=npw; c[1]+=fed
    cats_out={k:{cat:[v[0],round(v[1])] for cat,v in d.items()} for k,d in cats.items()}

    audit={}
    for st in sorted(set(list(st_audit.keys()))):
        a=st_audit[st]
        flags=[]
        if a.get("u",0)>0: flags.append("UNDECLARED_$")
        if a.get("x",0)>0: flags.append("UNMATCHED_$")
        if a.get("det",0) and a.get("catUn",0)/a["det"]>TOL: flags.append(f"CAT_UNATTRIBUTED_{a['catUn']/a['det']*100:.1f}%")
        audit[st]={"summaries":round(a.get("sum",0)),"inCounty":round(a.get("c",0)),"statewide":round(a.get("s",0)),
                   "undeclared":round(a.get("u",0)),"unmatched":round(a.get("x",0)),
                   "details":round(a.get("det",0)),"catMatched":round(a.get("catOk",0)),"catUnmatched":round(a.get("catUn",0)),
                   "flags":flags}
    audit["_meta"]={"note":"rows = Summaries v1 per applicant×county×disaster; c+s+u+x == summaries per state "
                    "(every row bucketed, dollars conserved). cats = Details v2 per-PW damageCategoryCode joined via "
                    "PublicAssistanceApplicants id→name (normalize()); catMatched+catUnmatched == details. Unattributed "
                    "category $ stay in the audit, never force-matched. Category rollup is per disaster×applicant across "
                    "counties (Details classifies county differently than Summaries).",
                    "tolerance":TOL,
                    "topCatUnmatched":[{"key":k,"fed":v} for k,v in top_un.most_common(15)]}

    out={"generated":time.strftime("%Y-%m-%d"),
         "source":"OpenFEMA PublicAssistanceFundedProjectsSummaries v1 (rows) + PublicAssistanceFundedProjectsDetails v2 "
                  "(damage categories) + PublicAssistanceApplicants v1 (applicantId→name); ledger disasters only",
         "note":"Per-disaster PA applicant detail for the Operations Planner. bucket c=county (key=FIPS), "
                "s=statewide/no-county (key=state), u=R5 county without a declaration record (key=FIPS), "
                "x=unmatched (key='ST|raw county'). names dictionary-encoded; $ rounded to whole dollars.",
         "dnMeta":dn_meta,"names":names,"rows":rows,"cats":cats_out,"audit":audit}
    path=os.path.join(DATA,"planner_applicants.json")
    json.dump(out,open(path,"w"),separators=(",",":"))

    nz=lambda x:f"${x:,.0f}"
    print(f"\nwrote {path}: {len(rows)} rows · {len(names)} names · {len(cats_out)} (dn,applicant) category rollups "
          f"· {os.path.getsize(path)/1e6:.2f} MB")
    print(f"{'ST':3} {'summaries':>14} {'inCounty':>14} {'statewide':>12} {'undecl':>9} {'unmatch':>9} {'details':>14} {'cat ok':>14} {'cat un':>10}  flags")
    for st,A in audit.items():
        if st=="_meta": continue
        print(f"{st:3} {nz(A['summaries']):>14} {nz(A['inCounty']):>14} {nz(A['statewide']):>12} {nz(A['undeclared']):>9} "
              f"{nz(A['unmatched']):>9} {nz(A['details']):>14} {nz(A['catMatched']):>14} {nz(A['catUnmatched']):>10}  {','.join(A['flags']) or 'ok'}")

def normalize_county(s):
    return (s or "").lower().replace("(county)","").replace("county","").replace(".","").replace("'","").replace(" ","").replace("-","").strip()

if __name__=="__main__":
    main()
