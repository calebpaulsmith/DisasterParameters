#!/usr/bin/env python3
"""Build data/r5_counties.json: simplified county polygons for FEMA Region 5
(IL, IN, MI, MN, OH, WI), keyed by 5-digit FIPS, for the live alerts choropleth.
Source: US Census county boundaries (plotly mirror). OFFLINE, run once."""
import json, os, urllib.request
HERE=os.path.dirname(os.path.abspath(__file__)); DATA=os.path.join(os.path.dirname(HERE),"data")
R5={"17":"IL","18":"IN","26":"MI","27":"MN","39":"OH","55":"WI"}
SRC="https://raw.githubusercontent.com/plotly/datasets/master/geojson-counties-fips.json"
raw=json.load(urllib.request.urlopen(SRC,timeout=60))

def simplify_ring(ring):
    out=[]; last=None
    for x,y in ring:
        p=[round(x,2),round(y,2)]
        if p!=last: out.append(p); last=p
    return out if len(out)>=4 else None

def polys(geom):
    t=geom["type"]; cs=geom["coordinates"]
    raw_polys = cs if t=="MultiPolygon" else [cs]
    out=[]
    for poly in raw_polys:
        rings=[]
        for ri,ring in enumerate(poly):
            sr=simplify_ring(ring)
            if sr: rings.append(sr)
        if rings: out.append(rings)
    return out

feats=[]
for f in raw["features"]:
    st=f["properties"].get("STATE")
    if st not in R5: continue
    g=polys(f["geometry"])
    if not g: continue
    feats.append({"f":f["id"],"n":f["properties"]["NAME"],"s":R5[st],"g":g})
feats.sort(key=lambda x:x["f"])
json.dump(feats, open(os.path.join(DATA,"r5_counties.json"),"w"), separators=(",",":"))
pts=sum(len(r) for x in feats for poly in x["g"] for r in poly)
print(f"wrote {len(feats)} R5 counties, {pts} points -> data/r5_counties.json")
