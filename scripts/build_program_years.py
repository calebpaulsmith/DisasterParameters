#!/usr/bin/env python3
"""OFFLINE: build data/program_years.json — the "Programs by year" view's dataset.

ONE cube: year x state x PROGRAM -> obligated/approved $ + a within-year drill-down
(sub-program split, top recipients, the disasters behind it). Everything the Programs
tab shows for a clicked year comes from this file; nothing is fetched live.

Ten programs, in the SAME taxonomy the Geography view already uses (so the two tabs
reconcile), each with its own honest YEAR BASIS — the tab labels this per program:

  disaster side
    pa    Public Assistance, federal share OBLIGATED   basis: TRUE obligation year
          (PublicAssistanceFundedProjectsDetails v2 .lastObligationDate)
          sub = damage category A-G/Z · top = applicants · dis = per disaster
    ihp   Individuals & Households Program, APPROVED   basis: PROXY, incident year
          (ledger disasters.json costs; IHP carries no obligation date)
          sub = HA/ONA · dis = per disaster · n = IA registrations
    hmgp  Hazard Mitigation Grant Program (Sec. 404), OBLIGATED  basis: TRUE obligation year
          (HazardMitigationAssistanceProjects v4 .initialObligationDate, programArea=HMGP)
          sub = project type · top = subrecipients · dis = per disaster
  non-disaster side
    mit   HMA non-disaster (FMA/PDM/BRIC/LPDM/RFC/SRL)  basis: TRUE obligation year
          sub = program · top = subrecipients
    empg  Emergency Management Performance Grants       basis: reporting/fiscal year
          sub = project type · top = recipient agency
    prepFire / prepHomeland / prepTransit / prepNonprofit / prepOther
          the NonDisasterAssistanceFirefighterGrants grab-bag split into the same five
          families build_state_prep.py uses                basis: grant FISCAL year
          sub = sub-program · top = recipients

SCOPE: Region 5 (IL/IN/MI/MN/OH/WI). The disaster-side programs cover exactly the
disasters in data/disasters.json (FY2007+, COVID-19 excluded from that ledger), so the
totals reconcile with county_declarations.json's per-state *ByYear buckets — the audit
block at the end of the file checks that state by state and records any delta.

Needs network (CORS-open OpenFEMA). Resumable cache: data/_progyears_cache.json.
Run from repo root:  python3 scripts/build_program_years.py
"""
import json, os, re, sys, time, collections, urllib.request, urllib.parse

HERE=os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0,HERE)
from dedup_applicants import normalize        # ONE name-normalizer for the whole repo

HERE=os.path.dirname(os.path.abspath(__file__)); ROOT=os.path.dirname(HERE); DATA=os.path.join(ROOT,"data")
CACHE=os.path.join(DATA,"_progyears_cache.json")

FIPS2AB={"17":"IL","18":"IN","26":"MI","27":"MN","39":"OH","55":"WI"}
NAMES={"IL":"Illinois","IN":"Indiana","MI":"Michigan","MN":"Minnesota","OH":"Ohio","WI":"Wisconsin"}
PA_URL="https://www.fema.gov/api/open/v2/PublicAssistanceFundedProjectsDetails"
APP_URL="https://www.fema.gov/api/open/v1/PublicAssistanceApplicants"
HMA_URL="https://www.fema.gov/api/open/v4/HazardMitigationAssistanceProjects"
EMPG_URL="https://www.fema.gov/api/open/v2/EmergencyManagementPerformanceGrants"
AFG_URL="https://www.fema.gov/api/open/v1/NonDisasterAssistanceFirefighterGrants"

R5="R5"          # the region-wide pseudo-scope (exact, not a merge of per-state top lists)
TOP_RECIP=12      # top recipients kept per (year, state, program)
TOP_SUB=12        # sub-program buckets kept per cell
TOP_DIS=12        # disasters kept per cell

CAT={"A":"A · Debris removal","B":"B · Emergency protective measures","C":"C · Roads & bridges",
     "D":"D · Water control facilities","E":"E · Buildings & equipment","F":"F · Utilities",
     "G":"G · Parks, recreational & other","Z":"Z · Management costs"}

# ---------------------------------------------------------------- fetch helpers
def get(url,retries=4,timeout=90):
    for i in range(retries):
        try:
            req=urllib.request.Request(url,headers={"User-Agent":"DisasterParameters/programyears (public open data)"})
            with urllib.request.urlopen(req,timeout=timeout) as r:
                return json.loads(r.read().decode("utf-8","replace"))
        except Exception as e:
            if i==retries-1: print(f"    ! {type(e).__name__} {url[:110]}")
            time.sleep(1.5*(i+1))
    return None

class ShortPull(Exception):
    """A pull came back with fewer rows than the server says exist — refuse to write a
    silently-truncated file (the same trust-gate posture as scripts/build_pending.py)."""

def paged(base,entity,flt,sel,page=1000,maxpages=200):
    """Pull an OpenFEMA entity in full, and GATE on the server's own record count.

    OpenFEMA reports the matching row count in metadata.count when $inlinecount=allpages
    is set. A transient failure mid-pagination would otherwise end the loop early and
    quietly drop rows (that is how the committed county_declarations.json ended up with a
    short Illinois preparedness series — see the audit note). We compare and raise."""
    out=[]; skip=0; expected=None
    for _ in range(maxpages):
        u=(f"{base}?$filter={urllib.parse.quote(flt)}&$select={urllib.parse.quote(sel)}"
           f"&$top={page}&$skip={skip}&$format=json"+("&$inlinecount=allpages" if expected is None else ""))
        d=get(u)
        if d is None: raise ShortPull(f"{entity} [{flt}] page at skip={skip} failed after retries")
        if expected is None:
            try: expected=int((d.get("metadata") or {}).get("count"))
            except Exception: expected=-1
        recs=d.get(entity,[]) or []
        if not recs: break
        out+=recs; skip+=len(recs)
        if len(recs)<page: break
        time.sleep(0.05)
    if expected is not None and expected>=0 and len(out)!=expected:
        raise ShortPull(f"{entity} [{flt}]: pulled {len(out)} of {expected} rows")
    return out

def num(x):
    try: return float(x or 0)
    except Exception: return 0.0

def yr(s):
    """ISO date / free text -> 4-digit year string, or None."""
    if not s: return None
    m=re.search(r"(19|20)\d\d",str(s))
    return m.group(0) if m else None

def clean(s):
    s=re.sub(r"\s+"," ",str(s or "").strip())
    return s or "(unnamed)"

# Recipient names arrive in several casings and punctuations of the same entity ("CHICAGO" /
# "Chicago", "Monroe (County)" / "MONROE COUNTY"), and a handful carry FEMA's own
# "(DO NOT USE)" retirement marker. Group on dedup_applicants.normalize() — the same
# normalizer the Geography and planner applicant lists use, so the three reconcile — and
# display the most readable surviving variant.
RAW=collections.defaultdict(collections.Counter)
def recip_key(nm):
    k=normalize(nm) or nm.lower().strip()
    RAW[k][nm]+=1
    return k
def recip_display(k):
    v=RAW.get(k)
    if not v: return k
    good=[n for n in v if "do not use" not in n.lower()] or list(v)
    # prefer Title Case over SHOUTING, then the longer (more complete) form, then stable order
    good.sort(key=lambda n:(-sum(1 for ch in n if ch.islower()),-len(n),n))
    return good[0]

# ---------------------------------------------------------------- cube
class Cube:
    """(year, state, program) -> {a:$, n:count, sub:{}, top:{}, dis:{}}"""
    def __init__(self):
        self.c=collections.defaultdict(lambda:{"a":0.0,"n":0,"sub":collections.defaultdict(float),
                                               "top":collections.defaultdict(lambda:[0.0,0]),
                                               "dis":collections.defaultdict(lambda:[0.0,0])})
    def add(self,y,st,prog,amt=0.0,n=0,sub=None,recip=None,dn=None):
        # every row lands in BOTH its state and the "R5" region cell, so the region-wide
        # top-recipient / top-disaster lists are exact rather than a merge of truncated
        # per-state lists.
        if not y or not st or st not in NAMES: return
        for key in (st,R5):
            cell=self.c[(y,key,prog)]
            cell["a"]+=amt; cell["n"]+=n
            if sub: cell["sub"][sub]+=amt
            if recip:
                t=cell["top"][recip]; t[0]+=amt; t[1]+=max(n,1)
            if dn:
                t=cell["dis"][str(dn)]; t[0]+=amt; t[1]+=max(n,1)
    def addsub(self,y,st,prog,sub,amt):
        """add to a cell's sub-breakdown only (the $ are already in via add())."""
        if not y or not st or st not in NAMES or not amt: return
        for key in (st,R5): self.c[(y,key,prog)]["sub"][sub]+=amt

CACHE_V=2      # bump to invalidate a cache filled by an older/looser pull
def cache_load():
    if os.path.exists(CACHE):
        try:
            c=json.load(open(CACHE))
            if c.get("_v")==CACHE_V: return c
            print("cache from an older build — re-pulling")
        except Exception: pass
    return {"_v":CACHE_V}
def cache_save(c):
    json.dump(c,open(CACHE,"w"),separators=(",",":"))

# ---------------------------------------------------------------- pulls
def pull_pa(dns,cache):
    """PA project worksheets for the ledger disasters -> lean rows (cached per disaster)."""
    sel="disasterNumber,stateNumberCode,federalShareObligated,lastObligationDate,damageCategoryCode,applicantId,mitigationAmount"
    store=cache.setdefault("pa",{})
    for k,dn in enumerate(dns,1):
        key=str(dn)
        if key in store: continue
        rows=[]
        for r in paged(PA_URL,"PublicAssistanceFundedProjectsDetails",f"disasterNumber eq {dn}",sel):
            ab=FIPS2AB.get(str(r.get("stateNumberCode") or "").zfill(2))
            if not ab: continue
            rows.append([ab,yr(r.get("lastObligationDate")),round(num(r.get("federalShareObligated"))),
                         (r.get("damageCategoryCode") or "").strip()[:1],r.get("applicantId") or "",
                         round(num(r.get("mitigationAmount")))])
        store[key]=rows
        if k%10==0 or k==len(dns):
            print(f"  PA [{k}/{len(dns)}] DR-{dn}: {len(rows)} worksheets"); cache_save(cache)
    cache_save(cache)
    return store

def pull_applicant_names(dns,cache):
    """(disasterNumber, applicantId) -> applicantName, for the R5 ledger disasters."""
    store=cache.setdefault("appl",{})
    for k,dn in enumerate(dns,1):
        key=str(dn)
        if key in store: continue
        m={}
        for r in paged(APP_URL,"PublicAssistanceApplicants",f"disasterNumber eq {dn}","applicantId,applicantName"):
            if r.get("applicantId"): m[r["applicantId"]]=clean(r.get("applicantName"))
        store[key]=m
        if k%20==0 or k==len(dns):
            print(f"  PA names [{k}/{len(dns)}] DR-{dn}: {len(m)} applicants"); cache_save(cache)
    cache_save(cache)
    return store

def pull_hma(cache):
    """All HMA projects (HMGP + non-disaster mitigation) for R5, per state.

    Only federalShareObligated counts. A row with no obligated federal share is an
    APPLICATION, not an obligation — the dataset carries denied, pending and not-selected
    projects alongside the funded ones, and its projectAmount is the requested cost.
    Falling back to projectAmount (as county_declarations.json's mit series does) would put
    money on this chart that FEMA never obligated; those dollars are counted separately and
    reported in the audit instead."""
    sel=("programArea,subrecipient,recipient,stateNumberCode,federalShareObligated,projectAmount,"
         "initialObligationDate,dateApproved,projectType,disasterNumber,status")
    store=cache.setdefault("hma2",{})
    for sc,ab in FIPS2AB.items():
        if ab in store: continue
        rows=[]
        for r in paged(HMA_URL,"HazardMitigationAssistanceProjects",f"stateNumberCode eq '{sc}'",sel):
            rows.append([(r.get("programArea") or "").strip(),
                         yr(r.get("initialObligationDate")) or yr(r.get("dateApproved")),
                         round(num(r.get("federalShareObligated"))),clean(r.get("subrecipient")),
                         clean(r.get("projectType")),r.get("disasterNumber"),
                         round(num(r.get("projectAmount"))),clean(r.get("status"))])
        store[ab]=rows; print(f"  HMA {ab}: {len(rows)} projects"); cache_save(cache)
    cache_save(cache)
    return store

def pull_empg(cache):
    store=cache.setdefault("empg",{})
    for ab,full in NAMES.items():
        if ab in store: continue
        rows=[]
        for r in paged(EMPG_URL,"EmergencyManagementPerformanceGrants",f"state eq '{full}'",
                       "fundingAmount,reportingPeriod,projectType,legalAgencyName"):
            rows.append([yr(r.get("reportingPeriod")),round(num(r.get("fundingAmount"))),
                         clean(r.get("projectType")),clean(r.get("legalAgencyName"))])
        store[ab]=rows; print(f"  EMPG {ab}: {len(rows)} awards"); cache_save(cache)
    cache_save(cache)
    return store

def pull_prep(cache):
    store=cache.setdefault("prep",{})
    for ab in NAMES:
        if ab in store: continue
        rows=[]
        for r in paged(AFG_URL,"NonDisasterAssistanceFirefighterGrants",f"vendorState eq '{ab}'",
                       "awardAmount,vendorName,fiscalYear,programName"):
            rows.append([str(r.get("fiscalYear") or "")[:4] or None,round(num(r.get("awardAmount"))),
                         clean(r.get("programName")),clean(r.get("vendorName"))])
        store[ab]=rows; print(f"  PREP {ab}: {len(rows)} awards"); cache_save(cache)
    cache_save(cache)
    return store

# family split — mirrors scripts/build_state_prep.py exactly (single taxonomy, two files)
def prep_family(p):
    pl=(p or "").lower()
    if "emergency management performance" in pl: return None      # EMPG owns those dollars
    if "non-profit" in pl or "nonprofit" in pl: return "prepNonprofit"
    if any(k in pl for k in ("assistance to firefighters","staffing for adequate","fire prevention","station construction")): return "prepFire"
    if "homeland security grant" in pl: return "prepHomeland"
    if any(k in pl for k in ("transit security","port security","freight rail","intercity bus")): return "prepTransit"
    return "prepOther"

# ---------------------------------------------------------------- main
def main():
    cache=cache_load()
    disasters=json.load(open(os.path.join(DATA,"disasters.json")))
    cd=json.load(open(os.path.join(DATA,"county_declarations.json")))
    dns=sorted({d["disasterNumber"] for d in disasters})
    dmeta={str(d["disasterNumber"]):{"t":d.get("title") or "","s":d.get("state"),
                                     "b":d.get("begin"),"it":d.get("incidentType") or ""} for d in disasters}

    cube=Cube()
    undated=collections.defaultdict(float)     # program -> $ dropped for want of a year

    # ---- PA (true obligation year) ----
    print(f"PA: project detail for {len(dns)} ledger disasters…")
    pa=pull_pa(dns,cache)
    print("PA: applicant-name bridge…")
    appl=pull_applicant_names(dns,cache)
    mit406=collections.defaultdict(float)      # (year,state) -> Sec. 406 mitigation inside PA
    for dnk,rows in pa.items():
        names=appl.get(dnk,{})
        for ab,y,fed,cat,aid,m406 in rows:
            if not y:
                if fed: undated["pa"]+=fed
                continue
            nm=names.get(aid) or "(applicant not named in OpenFEMA)"
            cube.add(y,ab,"pa",amt=fed,n=1,sub=CAT.get(cat,"(uncategorized)"),recip=recip_key(nm),dn=dnk)
            if m406: mit406[(y,ab)]+=m406; mit406[(y,R5)]+=m406

    # ---- IHP (PROXY: disaster incident year, from the ledger) ----
    for d in disasters:
        c=d.get("costs") or {}; ab=d.get("state"); y=yr(d.get("begin"))
        tot=num(c.get("ihpTotal"))
        if not (ab and y and tot): continue
        cube.add(y,ab,"ihp",amt=tot,n=int(num(c.get("iaRegistrations"))),dn=d["disasterNumber"])
        cube.addsub(y,ab,"ihp","Housing Assistance (HA)",num(c.get("ihpHousing")))
        cube.addsub(y,ab,"ihp","Other Needs Assistance (ONA)",num(c.get("ihpOna")))

    # ---- HMGP + non-disaster mitigation (true obligation year) ----
    print("HMA: HMGP + non-disaster mitigation per state…")
    hma=pull_hma(cache)
    notObl=collections.defaultdict(lambda:collections.defaultdict(float))   # program -> status -> requested $
    for ab,rows in hma.items():
        for area,y,fed,sub,ptype,dn,pamt,status in rows:
            prog="hmgp" if area=="HMGP" else "mit"
            if not fed:
                if pamt: notObl[prog][status or "(status not stated)"]+=pamt
                continue
            if not y: undated[prog]+=fed; continue
            cube.add(y,ab,prog,amt=fed,n=1,
                     sub=(re.sub(r"^\d+(\.\d+)?:\s*","",ptype) if prog=="hmgp" else (area or "(program not stated)")),
                     recip=recip_key(sub),dn=(dn if prog=="hmgp" and dn else None))

    # ---- EMPG (reporting/fiscal year) ----
    print("EMPG per state…")
    for ab,rows in pull_empg(cache).items():
        for y,amt,ptype,agency in rows:
            if not amt: continue
            if not y: undated["empg"]+=amt; continue
            cube.add(y,ab,"empg",amt=amt,n=1,sub=ptype,recip=recip_key(agency))

    # ---- preparedness families (grant fiscal year) ----
    print("Preparedness (AFG grab-bag) per state…")
    for ab,rows in pull_prep(cache).items():
        for y,amt,pname,vendor in rows:
            fam=prep_family(pname)
            if fam is None or not amt: continue
            if not y: undated[fam]+=amt; continue
            cube.add(y,ab,fam,amt=amt,n=1,sub=pname,recip=recip_key(vendor))

    # ---------------------------------------------------------------- serialize
    names_idx={}; names=[]
    def ni(nm):
        if nm not in names_idx: names_idx[nm]=len(names); names.append(nm)
        return names_idx[nm]

    years={}
    for (y,st,prog),cell in sorted(cube.c.items()):
        amt=round(cell["a"])
        if not amt and not cell["n"]: continue
        o={"a":amt,"n":cell["n"]}
        subAll=[(k,v) for k,v in sorted(cell["sub"].items(),key=lambda x:-x[1]) if round(v)]
        sub={k:round(v) for k,v in subAll[:TOP_SUB]}
        if sub:
            o["sub"]=sub
            if len(subAll)>len(sub): o["ns"]=len(subAll)      # kept only the top slice — say so
        top=[[ni(recip_display(k)),round(v[0]),v[1]] for k,v in sorted(cell["top"].items(),key=lambda x:-x[1][0])[:TOP_RECIP] if round(v[0])]
        if top:
            o["top"]=top
            o["nr"]=len([1 for v in cell["top"].values() if round(v[0])])     # total distinct recipients
        disAll=[(k,v) for k,v in sorted(cell["dis"].items(),key=lambda x:-x[1][0]) if round(v[0])]
        dis=[[int(k),round(v[0]),v[1]] for k,v in disAll[:TOP_DIS]]
        if dis:
            o["dis"]=dis
            o["nd"]=len(disAll)
        if prog=="pa" and mit406.get((y,st)): o["m406"]=round(mit406[(y,st)])
        years.setdefault(y,{}).setdefault(st,{})[prog]=o

    # ---------------------------------------------------------------- audit
    # Nothing here is quietly reconciled — every known difference against the other
    # committed artifacts is measured and written into the file, with its cause.
    CDKEY={"pa":"paByYear","ihp":"ihpByYear","hmgp":"hmgpByYear","mit":"mitByYear",
           "empg":"empgByYear","prepFire":"afgByYear"}
    CDWHY={
      "pa":("county_declarations rolls a state up from its COUNTIES, so PA dollars on a worksheet whose "
            "county does not resolve to a declared R5 county are not in its state series; this cube keys "
            "on the worksheet's STATE, so it keeps them."),
      "ihp":"same source (the ledger) and same proxy year basis — expected to match exactly.",
      "hmgp":("scope: county_declarations' hmgpByYear covers only the disasters in the FY2007+ ledger, while "
              "this cube covers the whole HazardMitigationAssistanceProjects record for Region 5 (older "
              "disasters are still obligating HMGP), plus the county-resolution difference noted for PA."),
      "mit":("this cube counts federalShareObligated ONLY. county_declarations' mit series falls back to "
             "projectAmount when no federal share is recorded, which sweeps in denied / pending / not-selected "
             "APPLICATIONS — money FEMA never obligated (see applicationsNotObligated). That makes this cube's "
             "figure the smaller, stricter one. Rows carrying no obligation date are in undatedDropped."),
      "empg":"same source and basis — differences are rounding or a newer data refresh.",
      "prepFire":("same source and basis. A large positive delta means the committed county_declarations "
                  "series is SHORT: scripts/build_state_prep.py ends its pagination loop on a failed page, "
                  "so one dropped page silently truncates that state. This cube gates every pull on the "
                  "server's own $inlinecount, so it cannot truncate silently."),
    }
    rec={}
    for prog,key in CDKEY.items():
        rec[prog]={"why":CDWHY[prog],"states":{}}
        for ab in NAMES:
            mine=sum(years.get(y,{}).get(ab,{}).get(prog,{}).get("a",0) for y in years)
            theirs=sum((cd["states"].get(ab,{}).get(key) or {}).values())
            rec[prog]["states"][ab]={"programYears":round(mine),"countyDeclarations":round(theirs),
                                     "delta":round(mine-theirs),
                                     "pctDelta":(round((mine-theirs)/theirs*1000)/10 if theirs else None)}

    # PA cross-dataset check: this cube sums PROJECT WORKSHEETS (Details v2, which is the only PA
    # source carrying an obligation DATE) while the ledger's per-disaster paTotal comes from
    # FemaWebDisasterSummaries. The two reconcile over time; a very recent disaster can differ a lot
    # because the summary rollup lags the worksheets. Per-disaster gaps are listed so the difference
    # is attributable, not just acknowledged.
    led=collections.defaultdict(float)
    for d in disasters: led[d.get("state")]+=num((d.get("costs") or {}).get("paTotal"))
    paDet=collections.defaultdict(float); paByDn=collections.defaultdict(float)
    for dnk,rows in pa.items():
        for ab,y,fed,cat,aid,m406 in rows:
            paDet[ab]+=fed; paByDn[dnk]+=fed
    gaps=[]
    for d in disasters:
        dnk=str(d["disasterNumber"]); l=num((d.get("costs") or {}).get("paTotal")); det=paByDn.get(dnk,0.0)
        if abs(det-l)>1_000_000:
            gaps.append({"dn":d["disasterNumber"],"state":d.get("state"),"begin":d.get("begin"),
                         "title":(d.get("title") or "")[:60],"worksheetsDetails":round(det),
                         "ledgerSummaries":round(l),"delta":round(det-l)})
    gaps.sort(key=lambda g:-abs(g["delta"]))
    paLedger={"why":("PublicAssistanceFundedProjectsDetails v2 (worksheets, dated — what this cube sums) vs "
                     "FemaWebDisasterSummaries via data/disasters.json (the ledger's per-disaster PA total). "
                     "Different datasets and different refresh cadences; obligations reconcile over years, so "
                     "recent disasters differ most. Neither is 'wrong' — the ledger stays authoritative for a "
                     "disaster's PA total, this cube for when dollars were obligated."),
              "states":{ab:{"worksheetsDetails":round(paDet[ab]),"ledgerSummaries":round(led[ab]),
                            "delta":round(paDet[ab]-led[ab])} for ab in NAMES},
              "disastersOver1M":gaps[:20]}

    fam_total={}
    for ab in NAMES:
        pf=(cd["states"].get(ab,{}) or {}).get("prepFamilyYear") or {}
        fam_total[ab]={k:round(sum(v.values())) for k,v in pf.items()}

    yrs=sorted(years)
    out={"generated":time.strftime("%Y-%m-%d"),
         "dataAsOf":time.strftime("%Y-%m-%d"),
         "source":("OpenFEMA PublicAssistanceFundedProjectsDetails v2 + PublicAssistanceApplicants v1 (PA), "
                   "FemaWebDisasterSummaries via data/disasters.json (IHP), HazardMitigationAssistanceProjects v4 "
                   "(HMGP + non-disaster mitigation), EmergencyManagementPerformanceGrants v2 (EMPG), "
                   "NonDisasterAssistanceFirefighterGrants v1 (preparedness families)"),
         "note":("year x state x program cube for the Programs tab. PA/HMGP/mitigation are bucketed by TRUE "
                 "obligation year; EMPG/preparedness by grant fiscal year; IHP is a PROXY by disaster incident "
                 "year (IHP carries no obligation date). Region 5 only; the disaster-side programs cover the "
                 "data/disasters.json ledger (FY2007+, COVID-19 excluded). PA is OBLIGATED, IHP is APPROVED — "
                 "different accounting stages, never conflate them."),
         "states":{ab:{"name":NAMES[ab],"pop":(cd["states"].get(ab,{}) or {}).get("pop")} for ab in NAMES},
         "yearMin":(yrs[0] if yrs else None),"yearMax":(yrs[-1] if yrs else None),
         "names":names,"years":years,"disasters":dmeta,
         "ledgerYear0":2007,
         "audit":{"reconcile":rec,"paLedger":paLedger,
                  "undatedDropped":{k:round(v) for k,v in undated.items() if round(v)},
                  "applicationsNotObligated":{p:{k:round(v) for k,v in sorted(d.items(),key=lambda x:-x[1])}
                                              for p,d in notObl.items()},
                  "prepFamilyAllTime":fam_total,
                  "note":("reconcile compares this file's all-time sum per state against the same program's "
                          "*ByYear bucket in county_declarations.json (an independent build from the same "
                          "sources) and states the CAUSE of each difference. paLedger is the PA cross-dataset "
                          "check (worksheets vs the ledger's summary rollup). undatedDropped = dollars on rows "
                          "with no usable date — they cannot be placed in a year, so they are reported here "
                          "rather than silently binned into one. Every pull is gated on the server's own "
                          "$inlinecount record count, so a dropped page aborts the build instead of shortening "
                          "a series. applicationsNotObligated = hazard-mitigation project REQUESTS with no "
                          "federal share obligated (denied / pending / not selected); they are excluded from "
                          "every figure on the tab — this tab counts obligations, not applications.")}}
    path=os.path.join(DATA,"program_years.json")
    json.dump(out,open(path,"w"),separators=(",",":"))
    kb=os.path.getsize(path)/1024
    print(f"\nwrote {path} ({kb:.0f} KB) — {len(yrs)} years {yrs[0] if yrs else '?'}–{yrs[-1] if yrs else '?'}, {len(names)} recipient names")
    for prog in CDKEY:
        d=rec[prog]["states"]; bad=[f"{ab} {d[ab]['delta']:+,}" for ab in d if d[ab]["delta"]]
        print(f"  reconcile {prog:12s} " + ("exact" if not bad else "; ".join(bad)))
    if undated: print("  undated dropped:",{k:round(v) for k,v in undated.items()})
    pl=paLedger["states"]
    print("  PA worksheets(Details) vs ledger(Summaries): "+"; ".join(f"{ab} {pl[ab]['delta']:+,}" for ab in pl if pl[ab]["delta"]))

if __name__=="__main__":
    try:
        main()
    except ShortPull as e:
        print(f"\nABORTED — incomplete pull: {e}\n(nothing written; the cache is resumable, just re-run)")
        sys.exit(1)
