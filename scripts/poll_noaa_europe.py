#!/usr/bin/env python3
"""KFS /modele: small NOAA readiness probe without GRIB downloads.

GFS/AIGFS Europe cards have a minimum lead time of +24h. This checks
the source's actual GRIB indices before triggering expensive generation.
If source is newer than the corresponding published map, return 'true'.
"""
import concurrent.futures
import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from check_france_cycles import noaa_index

ROOT=Path("forecast-maps/europe/noaa-metadata.json")
STEPS=(24,48,72,120,168,240,360)
MODELS=("gfs","aigfs")

def utc(value):
    try:
        d=datetime.fromisoformat(str(value).replace("Z","+00:00"))
        return d.replace(tzinfo=timezone.utc) if d.tzinfo is None else d.astimezone(timezone.utc)
    except (ValueError,TypeError):
        return datetime(1970,1,1,tzinfo=timezone.utc)

def main():
    try:
        stored=json.loads(ROOT.read_text(encoding="utf-8"))
    except (OSError,ValueError):
        stored={}
    now=datetime.now(timezone.utc).replace(minute=0,second=0,microsecond=0)
    base=now.replace(hour=now.hour//6*6)
    cycles=(base,base-timedelta(hours=6))
    checks=[(model,step,cycle) for model in MODELS for step in STEPS for cycle in cycles]
    def probe(x):
        model,step,cycle=x
        try:
            return (model,step,cycle,bool(noaa_index(model,cycle,step)))
        except Exception as exc:
            print("NOAA_PROBE_ERROR",model,step,str(exc)[:120],flush=True)
            return (model,step,cycle,False)
    with concurrent.futures.ThreadPoolExecutor(max_workers=14) as pool:
        found=list(pool.map(probe,checks))
    missing=[]
    for model in MODELS:
        for step in STEPS:
            newer=[c for m,s,c,ok in found if m==model and s==step and ok]
            if not newer:
                continue
            latest=max(newer)
            published=utc(stored.get("runs_utc",{}).get(model,{}).get(str(step)))
            if latest>published:
                missing.append((model,step,latest.isoformat(),published.isoformat()))
    needs=bool(missing)
    for model,step,new,old in missing:
        print("NOAA_EUROPE_PENDING",model,"+"+str(step),new,"published",old,flush=True)
    print("NOAA_EUROPE_NEEDS_REFRESH",str(needs).lower(),"count",len(missing),flush=True)
    if os.environ.get("GITHUB_OUTPUT"):
        with open(os.environ["GITHUB_OUTPUT"],"a",encoding="utf-8") as stream:
            stream.write("generate="+str(needs).lower()+"\n")
    return 0

if __name__=="__main__":
    raise SystemExit(main())
