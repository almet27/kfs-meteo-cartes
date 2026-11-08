#!/usr/bin/env python3
"""Package real KFS France forecast charts into immutable-size release assets.

GitHub release tags are per model (france-ifs, france-gfs, etc.).
Only the last complete +72h run is published, overwriting assets from that tag.
No Europe file, GitHub Pages site or Git history image is changed.
"""
from __future__ import annotations
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
from PIL import Image

STEPS={"ifs":3,"gfs":3,"aifs-single":6,"aigfs":6}
FIELDS={"t2m","t850","wind10m","mslp","precip_total"}
ECMWF_FIELDS=FIELDS|{"rain","snow"}

def validate(raw:dict,source:Path):
    model=raw.get("model")
    if model not in STEPS or raw.get("area")!="France":
        raise ValueError("Not a supported France model atlas")
    expected=list(range(STEPS[model],73,STEPS[model]))
    if raw.get("requested_steps_h") != expected:
        raise ValueError("Source does not cover every native step through +72h")
    maps=raw.get("maps")
    if not isinstance(maps,dict):
        raise ValueError("Missing maps")
    essential=ECMWF_FIELDS if model in ("ifs","aifs-single") else FIELDS
    for step in expected:
        fields=maps.get(str(step))
        if not isinstance(fields,dict) or not essential.issubset(fields):
            raise ValueError("Missing required fields at +%s h for %s: %s" %
                             (step,model,sorted(essential-set(fields or {}))))
        for field, entry in fields.items():
            if field not in ECMWF_FIELDS:
                continue
            if not isinstance(entry,dict):
                raise ValueError("Invalid map entry")
            path=source / Path(str(entry.get("path",""))).name
            if path.suffix.lower()!=".png" or not path.is_file():
                raise ValueError("Source image is missing: "+str(path))
    return model

def main():
    p=argparse.ArgumentParser()
    p.add_argument("--source",type=Path,required=True,
                   help="Directory with metadata.json and source PNGs")
    p.add_argument("--output",type=Path,required=True,
                   help="Temporary output directory for WebP release assets")
    p.add_argument("--max-mb",type=int,default=40)
    args=p.parse_args()
    raw=json.loads((args.source/"metadata.json").read_text(encoding="utf-8"))
    model=validate(raw,args.source)
    args.output.mkdir(parents=True,exist_ok=True)
    manifest={"schema":2,"model":model,"run_utc":raw["run_utc"],
              "native_step_h":STEPS[model],"area":"France",
              "source_generated_utc":raw["generated_utc"],
              "published_utc":datetime.now(timezone.utc).isoformat(),
              "maps":{},"errors":raw.get("errors",{}),
              "notes":["Previsions generees depuis les champs GRIB reels.",
                       "Pas de donnees interpolees pour combler des echeances absentes.",
                       "Neige ECMWF en equivalent-eau, pas en centimetres au sol.",
                       "Phase pluie/neige GFS estimee seulement si disponible."]}
    n=0
    for step,fields in sorted(raw["maps"].items(),key=lambda kv:int(kv[0])):
        entry={}
        for field,data in sorted(fields.items()):
            if field not in ECMWF_FIELDS:
                continue
            origin=args.source/Path(data["path"]).name
            target=args.output/(field+"-h"+int(step).__format__("03d")+".webp")
            with Image.open(origin) as im:
                if im.width<300 or im.height<200:
                    raise ValueError("Map image too small: "+str(origin))
                im.convert("RGB").save(target,format="WEBP",quality=87,method=6)
            entry[field]={"file":target.name,"note":data.get("note","")}
            n+=1
        manifest["maps"][step]=entry
    (args.output/"metadata.json").write_text(
        json.dumps(manifest,ensure_ascii=False,indent=2)+"\n",encoding="utf-8"
    )
    size=sum(x.stat().st_size for x in args.output.iterdir() if x.is_file())
    if size>args.max_mb*1_000_000:
        raise ValueError("Release too large (%s MB), aborting" % round(size/1e6,1))
    print(json.dumps({"model":model,"run":raw["run_utc"],
                      "assets":n,"megabytes":round(size/1e6,2),
                      "release_tag":"france-"+model},ensure_ascii=False))
    return 0

if __name__=="__main__":
    sys.exit(main())
