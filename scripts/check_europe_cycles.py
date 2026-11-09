#!/usr/bin/env python3
"""KFS Europe /modele — detect published source cycles vs committed map cycles.

Reuse the native NOAA .idx and ECMWF availability probes already used for /france.
A probe is not proof that all meteorological fields are ready; generation validates them.
"""
from __future__ import annotations
from datetime import datetime, timezone
from pathlib import Path
import json
import os
from check_france_cycles import noaa_latest, ecmwf_latest

ROOT=Path("forecast-maps/europe")
SPECS={"ifs":("ecmwf",240),"aifs-single":("ecmwf",360),
       "gfs":("noaa",360),"aigfs":("noaa",360)}
def parse(value):
    try:
        d=datetime.fromisoformat(str(value).replace("Z","+00:00"))
        return d.replace(tzinfo=timezone.utc) if d.tzinfo is None else d.astimezone(timezone.utc)
    except (TypeError,ValueError):
        return datetime(1970,1,1,tzinfo=timezone.utc)

def latest(model,step):
    if model in ("ifs","aifs-single"): return ecmwf_latest(model,step)
    return noaa_latest(model,step)

def published(model,step):
    path=ROOT/("metadata.json" if model in ("ifs","aifs-single") else "noaa-metadata.json")
    try: manifest=json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError,ValueError): return None
    return manifest.get("runs_utc",{}).get(model,{}).get(str(step))

def main():
    models={}
    pending=[]
    for model,(provider,limit) in SPECS.items():
        info={"source":provider,"earliest_step_h":24,"maximum_step_h":limit}
        update=False
        # Chaque échéance est publiée au plus tôt : ne pas attendre +360 h
        # pour mettre à jour +48, +72, +120 ou +168 h.
        for step in [24,48,72,120,168,240,360]:
            if step>limit:
                continue
            try:
                available=latest(model,step)
            except Exception as error:
                available=None
                info[f"error_{step}h"]=str(error)[:140]
            stored=published(model,step)
            is_new=bool(available and parse(available)>parse(stored))
            info[f"source_{step}h_utc"]=available
            info[f"published_{step}h_utc"]=stored
            info[f"new_{step}h"]=is_new
            update=update or is_new
        info["update_pending"]=update
        if update:pending.append(model)
        models[model]=info
    groups={
       "europe_noaa":"true" if any(x in pending for x in ("gfs","aigfs")) else "false",
       "europe_ecmwf":"true" if any(x in pending for x in ("ifs","aifs-single")) else "false",
    }
    out={"generated_utc":datetime.now(timezone.utc).isoformat(),
         "models":models,"pending":pending,"dispatch_groups":groups,
         "note":"Availability of a GRIB file/index is not a verified complete map."}
    print(json.dumps(out,ensure_ascii=False,indent=2),flush=True)
    output=os.getenv("GITHUB_OUTPUT")
    if output:
        with open(output,"a",encoding="utf-8") as f:
            for key,value in groups.items(): f.write(f"{key}={value}\n")
    return 0

if __name__=="__main__":
    raise SystemExit(main())
