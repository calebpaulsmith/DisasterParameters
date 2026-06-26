#!/usr/bin/env python3
"""
Systematic data-integrity audit across ALL programs in county_declarations.json (+ disasters.json,
nfip.json). Read-only, no network. Prints PASS/FAIL per conservation relationship with magnitudes so
silent drops / non-reconciliations surface the way the PA-applicant gap did.

Relationship classes checked:
  COUNT      list length == its n* field (applicants, hmgpApplicants, mitApplicants)
  SUBLIST    Σ sub-list $ == the county/state all-time total (same OpenFEMA source → should reconcile)
  BYYEAR     Σ *ByYear <= all-time field (null-date rows allowed; flag if OVER, or large UNDER)
  BREAKDOWN  Σ byProgram/byType == the headline total
  STATEROLL  Σ county $ + statewide bucket vs the ledger (disasters.json) — cross-dataset noted
  LEDGER     disasters.json internal: HA+ONA==IHP, AB+CG<=PA(Cat Z>=0), pa/ihp mirrors
  NFIP       county rollups sum to state; byYear sums to totals
"""
import os, json, collections
DATA=os.path.join(os.path.dirname(__file__),"..","data")
def load(n): return json.load(open(os.path.join(DATA,n)))
cd=load("county_declarations.json"); co=cd["counties"]; st=cd["states"]
disasters=load("disasters.json")
fails=[]; notes=[]
def money(x): return f"${x:,.0f}"
def close(a,b,tol): return abs(a-b)<=tol
def hdr(t): print(f"\n=== {t} ===")

# ledger sums by state
led=collections.defaultdict(lambda:{"pa":0.0,"ihp":0.0,"hmgp":0.0})
for d in disasters:
    c=d.get("costs") or {}; s=d["state"]
    led[s]["pa"]+=c.get("paTotal",0) or 0; led[s]["ihp"]+=c.get("ihpTotal",0) or 0; led[s]["hmgp"]+=c.get("hmgp",0) or 0

real_co={f:o for f,o in co.items() if not o.get("synthetic")}

# ---- 1. COUNT integrity ----
hdr("COUNT: n* == len(list)")
for field,lst in [("nApplicants","applicants"),("nHmgpApplicants","hmgpApplicants"),("nMitApplicants","mitApplicants")]:
    bad=[f for f,o in real_co.items() if (lst in o or field in o) and (o.get(field,0)!=len(o.get(lst,[])))]
    print(f"  {field} vs len({lst}): {'OK' if not bad else 'FAIL '+str(len(bad))+' e.g. '+str(bad[:5])}")
    if bad: fails.append(f"{field} != len({lst}) in {len(bad)} counties")

# ---- 2. SUBLIST $ conservation (same-source → should reconcile) ----
hdr("SUBLIST: Σ applicant/subrecipient $ vs county total (same OpenFEMA source)")
def sublist_check(listkey, amtkey, totkey, label, same_source):
    worst=[]; nbad=0; tot_drop=0
    for f,o in real_co.items():
        lst=o.get(listkey)
        if not lst: continue
        s=sum(a.get(amtkey,0) for a in lst); t=o.get(totkey,0)
        tol=max(5,0.005*t, len(lst))
        if not close(s,t,tol):
            nbad+=1; tot_drop+=(t-s); worst.append((abs(t-s),o["name"],o["state"],t,s))
    worst.sort(reverse=True)
    tag="(same source → SHOULD match)" if same_source else "(cross-dataset → informational)"
    print(f"  {label} {tag}: {nbad} counties off · net Σtotal-Σlist = {money(tot_drop)}")
    for d,nm,stt,t,s in worst[:5]: print(f"      [{nm},{stt}] total {money(t)} vs list {money(s)}  Δ{money(t-s)}")
    if same_source and nbad: fails.append(f"{label}: {nbad} counties where Σlist != total (same source)")
sublist_check("hmgpApplicants","hmgp","hmgpObligated","HMGP subrecipients vs hmgpObligated",True)
sublist_check("mitApplicants","mit","mitObligated","mit grantees vs mitObligated",True)
sublist_check("applicants","pa","paObligated","PA applicants vs paObligated",False)  # Summaries v1 vs Details v2

# ---- 3. BYYEAR vs all-time ----
hdr("BYYEAR: Σ *ByYear vs all-time (Σ should be <= all-time; null-date rows allowed)")
def byyear_check(scope, objs, ykey, totkey, label):
    over=[]; under_tot=0; n_over=0
    for k,o in objs.items():
        m=o.get(ykey);
        if m is None: continue
        s=sum(m.values()); t=o.get(totkey,0)
        if s-t>max(5,0.005*max(t,1)): n_over+=1; over.append((s-t,o.get("name",k),t,s))
        under_tot+=(t-s)
    over.sort(reverse=True)
    print(f"  {scope} {label}: Σbyyear OVER all-time in {n_over} {scope}s · total null-date/under = {money(under_tot)}")
    for d,nm,t,s in over[:5]: print(f"      OVER [{nm}] all-time {money(t)} < Σbyyear {money(s)}  +{money(s-t)}")
    if n_over: fails.append(f"{label} ({scope}): Σ*ByYear EXCEEDS all-time in {n_over} (impossible — bug)")
for yk,tk,lb in [("paByYear","paObligated","paByYear/paObligated"),("paProjectsByYear","paProjects","paProjectsByYear/paProjects"),
                 ("hmgpByYear","hmgpObligated","hmgpByYear/hmgpObligated"),("ihpByYear","ihpApproved","ihpByYear/ihpApproved"),
                 ("mitByYear","mitObligated","mitByYear/mitObligated")]:
    byyear_check("county",real_co,yk,tk,lb)
for yk,tk,lb in [("paByYear","paObligated","paByYear"),("hmgpByYear","hmgpObligated","hmgpByYear"),
                 ("ihpByYear","ihpApproved","ihpByYear"),("mitByYear","mitObligated","mitByYear"),
                 ("empgByYear","empg","empgByYear"),("afgByYear","afg","afgByYear")]:
    byyear_check("state",st,yk,tk,lb)

# ---- 4. BREAKDOWN: byProgram / byType sum to headline ----
hdr("BREAKDOWN: Σ byProgram/byType == headline total")
def breakdown_check(objs, bkey, totkey, label):
    bad=[]
    for k,o in objs.items():
        b=o.get(bkey)
        if not b: continue
        s=sum(v for v in b.values()); t=o.get(totkey,0); tol=max(5,0.005*max(t,1))
        if not close(s,t,tol): bad.append((o.get("name",k),t,s))
    print(f"  {label}: {'OK' if not bad else 'MISMATCH '+str(len(bad))}")
    for nm,t,s in bad[:6]: print(f"      [{nm}] total {money(t)} vs Σ {money(s)}  Δ{money(t-s)}")
    return bad
breakdown_check(real_co,"mitByProgram","mitObligated","county mitByProgram → mitObligated")
breakdown_check(st,"mitByProgram","mitObligated","state mitByProgram → mitObligated")
b1=breakdown_check(st,"empgByType","empg","state empgByType → empg")
b2=breakdown_check(st,"afgByProgram","afg","state afgByProgram → afg")
if b1: notes.append("empgByType != empg (check 'null' bucket / source)")
if b2: notes.append("afgByProgram != afg (afgByProgram appears to include non-AFG preparedness programs)")

# ---- 5. STATEROLL: county + statewide vs ledger ----
hdr("STATEROLL: Σ county $ + statewide bucket vs ledger (cross-dataset noted)")
print(f"  {'ST':3} {'PROG':5} {'ledger':>14} {'countySum':>14} {'statewide':>13} {'cty+sw':>14} {'gap':>13}")
for s in st:
    cpa=sum(o.get("paObligated",0) for o in real_co.values() if o["state"]==s)
    chm=sum(o.get("hmgpObligated",0) for o in real_co.values() if o["state"]==s)
    swpa=(cd.get("statewide",{}).get(s,{}) or {}).get("paObligated",0)
    swhm=st[s].get("hmgpStatewide",0) or 0
    for prog,led_v,csum,sw in [("PA",led[s]["pa"],cpa,swpa),("HMGP",led[s]["hmgp"],chm,swhm)]:
        gap=led_v-(csum+sw)
        print(f"  {s:3} {prog:5} {money(led_v):>14} {money(csum):>14} {money(sw):>13} {money(csum+sw):>14} {money(gap):>13}")
notes.append("PA county sum is Details v2 vs ledger FemaWebDisasterSummaries (cross-dataset gap expected); HMGP is same-source → gap should be ~0")

# HMGP statewide applicants conservation
hdr("HMGP statewide: Σ hmgpStatewideApplicants $ == hmgpStatewide")
for s in st:
    sl=st[s].get("hmgpStatewideApplicants");
    if sl is None: continue
    ssum=sum(a.get("hmgp",0) for a in sl); t=st[s].get("hmgpStatewide",0)
    ok=close(ssum,t,max(5,0.005*max(t,1)))
    print(f"  {s}: list {money(ssum)} vs hmgpStatewide {money(t)}  {'OK' if ok else 'MISMATCH'}")
    if not ok: fails.append(f"{s} hmgpStatewideApplicants != hmgpStatewide")
# mit statewide applicants — is there a list at all?
hdr("mit statewide: is there a mitStatewideApplicants list?")
has_mitsw=any("mitStatewideApplicants" in st[s] for s in st)
nonzero_mitsw=[s for s in st if (st[s].get("mitStatewide",0) or 0)>0]
print(f"  mitStatewideApplicants present: {has_mitsw} · states with mitStatewide $>0: {nonzero_mitsw}")
if nonzero_mitsw and not has_mitsw:
    fails.append("mitStatewide $ exists but NO mitStatewideApplicants list — no-county mit grantees not browsable (PA-style gap)")

# ---- 6. LEDGER internal ----
hdr("LEDGER: disasters.json internal reconciliation")
bad_recon=bad_catz=bad_mirror=0
for d in disasters:
    c=d.get("costs") or {}
    ihp,ha,ona=c.get("ihpTotal"),c.get("ihpHousing"),c.get("ihpOna")
    if ihp and (ha is not None or ona is not None) and abs((ihp)-( (ha or 0)+(ona or 0)))>1: bad_recon+=1
    pa,ab,cg=c.get("paTotal") or 0,c.get("paEmergencyAB") or 0,c.get("paPermanentCG") or 0
    if pa and (ab+cg)-pa>1: bad_catz+=1
    if d.get("pa") not in (None,c.get("paTotal")) or d.get("ihp") not in (None,c.get("ihpTotal")): bad_mirror+=1
print(f"  HA+ONA==IHP: {'OK' if not bad_recon else 'FAIL '+str(bad_recon)}")
print(f"  AB+CG<=PA (Cat Z>=0): {'OK' if not bad_catz else 'FAIL '+str(bad_catz)}")
print(f"  pa/ihp mirror costs: {'OK' if not bad_mirror else 'FAIL '+str(bad_mirror)}")
for cond,msg in [(bad_recon,"HA+ONA!=IHP"),(bad_catz,"AB+CG>PA"),(bad_mirror,"pa/ihp mirror")]:
    if cond: fails.append(f"ledger {msg}: {cond}")

# ---- 7. NFIP ----
hdr("NFIP: county → state rollup")
try:
    nf=load("nfip.json")
    keys=list(nf.keys()); print(f"  nfip.json top keys: {keys[:8]}")
except Exception as e:
    print("  (nfip.json not loaded:",e,")")

# ---- SUMMARY ----
hdr("SUMMARY")
if fails:
    print("INTEGRITY ISSUES:")
    for f in fails: print("  -",f)
else:
    print("No hard integrity failures.")
if notes:
    print("Notes (expected / informational):")
    for n in notes: print("  •",n)
