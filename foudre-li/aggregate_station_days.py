#!/usr/bin/env python3
"""Aggregate validated daily EUMETSAT station coverage without treating absent days as zero."""
import json
from collections import defaultdict
from datetime import date
from pathlib import Path
from parallax import METHOD
root=Path("data/eumetsat-li")
months=defaultdict(dict)
for path in sorted((root/"daily").glob("????-??-??.json")):
    d=json.loads(path.read_text())
    day=date.fromisoformat(path.stem)
    if d.get("schema")!=1 or d.get("date")!=path.stem or d.get("pilot") is not False or d.get("complete") is not True or d.get("parallax")!=METHOD or d.get("radius_km")!=15:
        raise ValueError(f"Invalid daily source {path}")
    if d.get("coverage_fraction",0)<.995 or d.get("max_gap_seconds",999)>30:
        raise ValueError(f"Incomplete day {path}")
    ids=d["station_ids"]; hits=d["stations_with_flashes"]
    if len(ids)!=len(set(ids)) or not set(hits)<=set(ids) or len(ids)!=d["station_count"]:
        raise ValueError(f"Invalid stations {path}")
    months[path.stem[:7]][path.stem]=(ids,hits)
yearly=defaultdict(dict)
for month,days in months.items():
    stations=defaultdict(lambda: {"valid":[],"active":[]})
    for day,(ids,hits) in days.items():
        for sid in ids:
            stations[sid]["valid"].append(int(day[-2:]))
            if hits.get(sid,0)>0: stations[sid]["active"].append(int(day[-2:]))
    payload={"schema":1,"month":month,"source":"EUMETSAT MTG LI LFL","radius_km":15,"parallax":METHOD,"timezone":"Europe/Paris","stations":stations}
    yearly[month[:4]][month]=stations
    out=root/"monthly"/(month+".json")
    out.parent.mkdir(parents=True,exist_ok=True)
    out.write_text(json.dumps(payload,separators=(",",":"))+"\n")

for year, data in yearly.items():
    payload={"schema":1,"year":int(year),"source":"EUMETSAT MTG LI LFL","radius_km":15,"parallax":METHOD,"timezone":"Europe/Paris","months":data}
    out=root/"yearly"/(year+".json")
    out.parent.mkdir(parents=True,exist_ok=True)
    out.write_text(json.dumps(payload,separators=(",",":"))+"\n")

# National map: use only validated daily archives above. Coordinates from the
# latest Météo-France catalogue, with the KFS web station catalogue as fallback.
# Counts are per 15 km disk, not unique national flash totals.
# Map-only high-coverage partial days: keep strict station climatology untouched.
# Partial day counts are lower bounds, never imputed or scaled.
map_months=defaultdict(dict,{m:dict(v) for m,v in months.items()})
partial_meta={}
for path in sorted((root/"partial").glob("2026-??-??.json")):
    d=json.loads(path.read_text())
    day=date.fromisoformat(path.stem)
    if path.stem in map_months[path.stem[:7]]: continue
    if (d.get("schema")!=1 or d.get("date")!=path.stem or d.get("pilot") is not False
        or d.get("complete") is not False or d.get("parallax")!=METHOD or d.get("radius_km")!=15
        or not .99<=d.get("coverage_fraction",0)<=1 or not 0<=d.get("max_gap_seconds",9999)<=900):
        raise ValueError(f"Invalid partial source {path}")
    ids=d["station_ids"]; hits=d["stations_with_flashes"]
    if len(ids)!=len(set(ids)) or not set(hits)<=set(ids) or len(ids)!=d["station_count"] or any(type(v) is not int or v<=0 for v in hits.values()):
        raise ValueError(f"Invalid partial station counts {path}")
    map_months[path.stem[:7]][path.stem]=(ids,hits)
    partial_meta[path.stem]={"coverage_fraction":d["coverage_fraction"],"max_gap_seconds":d["max_gap_seconds"]}
for year in sorted({m[:4] for m in map_months}):
    if year != "2026":
        continue
    coords={}
    try:
        import requests
        r=requests.get("https://meteofrance.s3.sbg.io.cloud.ovh.net/data/synchro_ftp/REF_STATION/liste_fiches_clim.geojson",timeout=45)
        r.raise_for_status()
        for f in r.json()["features"]:
            p=f["properties"]; sid=str(p.get("num",""))
            lon,lat=map(float,f["geometry"]["coordinates"][:2])
            if len(sid)==8 and sid.isdigit() and -7.5<=lon<=10 and 40.5<=lat<=52:
                coords[sid]=[str(p.get("nom") or p.get("name") or sid),lon,lat]
    except Exception as e:
        print("Station catalogue unavailable:",type(e).__name__,flush=True)
    for f in sorted(Path("climato/mf-web").glob("????-??.json")):
        try:
            for s in json.loads(f.read_text()).get("stations",[]):
                if len(s)>=4: coords.setdefault(s[0],[s[1],s[2],s[3]])
        except (ValueError,OSError): pass
    selected={m[5:]:sorted(days.items()) for m,days in map_months.items() if m[:4]==year}
    selected["annee"]=sorted((day,value) for m,days in map_months.items() if m[:4]==year for day,value in days.items())
    periods={}
    for tag,entries in selected.items():
        agg=defaultdict(lambda:[0,0,0])
        for day,(ids,hits) in entries:
            for sid in ids:
                a=agg[sid]; h=hits.get(sid,0)
                a[0]+=1; a[1]+=int(h>0); a[2]+=h
        rows=[[sid,*coords[sid],*v] for sid,v in sorted(agg.items()) if sid in coords]
        if not rows: continue
        periods[tag]={"dates":[day for day,_ in entries],"partial_dates":{day:partial_meta[day] for day,_ in entries if day in partial_meta},"rows":rows}
    if periods:
        payload={"schema":1,"year":int(year),"source":"EUMETSAT MTG LI LFL","radius_km":15,"timezone":"Europe/Paris","coordinate_source":"Météo-France","periods":periods}
        out=root/"yearly"/(year+"-map.json")
        out.write_text(json.dumps(payload,separators=(",",":"),ensure_ascii=False)+"\n")
        print("Map periods",list(periods),flush=True)
