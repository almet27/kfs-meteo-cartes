#!/usr/bin/env python3
"""Assemble actual forecast PNGs into side-by-side comparisons, no fabricated model fields."""
from pathlib import Path
from datetime import datetime, timezone
import json
from PIL import Image, ImageOps, ImageDraw, ImageFont

ROOT=Path("forecast-maps/europe")
STEPS=[24,48,72,120,168,240,360]
FIELDS={"t850":"Température à 850 hPa","z500_msl":"Géopotentiel 500 hPa + pression au sol",
        "wind10m":"Vent à 10 m (km/h)","precip6h":"Précipitations totales sur 6 h (pluie + neige)",
        "rain6h":"Pluie 6 h (GFS estimation, ECMWF données séparées)",
        "snow6h":"Neige / précipitations gelées 6 h (GFS estimation, ECMWF données séparées)"}
MODELS=[("gfs","GFS"),("aigfs","AIGFS"),("ifs","ECMWF IFS"),("aifs-single","ECMWF AIFS")]
SOURCES={"gfs":"noaa-metadata.json","aigfs":"noaa-metadata.json","ifs":"metadata.json","aifs-single":"metadata.json"}
manifest={f:json.loads((ROOT/f).read_text(encoding="utf-8")) for f in set(SOURCES.values())}
result={"generated_utc":datetime.now(timezone.utc).isoformat(),"maps":{},"models":[key for key,_ in MODELS],"runs_by_map":{},"errors":{}}
TILE_W,TILE_H=875,660
TITLE_H=54
fontfile="/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
font=ImageFont.truetype(fontfile,19) if Path(fontfile).exists() else ImageFont.load_default()
header=ImageFont.truetype(fontfile,24) if Path(fontfile).exists() else ImageFont.load_default()
for step in STEPS:
    for field,label in FIELDS.items():
        panels=[]
        successes=0
        used_runs={}
        for model,name in MODELS:
            source=manifest[SOURCES[model]]
            path=source.get("maps",{}).get(model,{}).get(str(step),{})
            path=path.get(field) if isinstance(path,dict) else None
            tile=Image.new("RGB",(TILE_W,TILE_H),"white")
            d=ImageDraw.Draw(tile)
            run=source.get("runs_utc",{}).get(model,{}).get(str(step),source.get("run_utc",""))
            try:
                when=datetime.fromisoformat(run.replace("Z","+00:00"))
                cycle="RUN "+when.strftime("%HZ du %d/%m/%Y")
            except (ValueError,TypeError):
                cycle="RUN indisponible"
            d.rectangle((0,0,TILE_W,TITLE_H),fill="#172c48")
            d.text((15,10),f"{name} • +{step} h",font=header,fill="white")
            d.text((TILE_W-340,16),cycle,font=font,fill="#d9e2ed")
            if path and (ROOT/Path(path).name).is_file():
                try:
                    with Image.open(ROOT/Path(path).name) as im:
                        im=im.convert("RGB")
                        fit=ImageOps.contain(im,(TILE_W-12,TILE_H-TITLE_H-12),Image.Resampling.LANCZOS)
                        tile.paste(fit,((TILE_W-fit.width)//2,TITLE_H+6+(TILE_H-TITLE_H-fit.height-12)//2))
                        successes+=1
                        if run: used_runs[model]=run
                except Exception as e:
                    d.text((34,110),"Image non exploitable : "+str(e)[:70],font=font,fill="#a32323")
            else:
                d.text((35,105),("Séparation pluie / neige non disponible pour AIGFS" if field in ("rain6h","snow6h") and model=="aigfs" else "Carte indisponible pour cette échéance"),font=font,fill="#a32323")
                if model=="ifs" and step==360:d.text((35,145),"IFS ouvert : pas de +360 h",font=font,fill="#6b6b6b")
            panels.append(tile)
        if not successes:continue
        comparison=Image.new("RGB",(TILE_W*2,TILE_H*2+84),"white")
        d=ImageDraw.Draw(comparison)
        d.rectangle((0,0,TILE_W*2,84),fill="#f4f7fa")
        d.text((25,12),f"KFS MÉTÉO | Atlantique Nord · Groenland · Europe | +{step} h | {label}",font=header,fill="#182f4b")
        d.text((25,47),("GFS/AIGFS : cumuls pluie + neige indifférenciés. Choisir Pluie ou Neige pour IFS/AIFS." if field=="precip6h" else "GFS : répartition indicative via CPOFP instantané. IFS/AIFS : cumuls séparés. AIGFS : non disponible." if field in ("rain6h","snow6h") else "RUN 00Z / 06Z / 12Z / 18Z indiqué pour chaque modèle — cycles parfois différents."),font=font,fill="#37506c")
        for i,tile in enumerate(panels):
            comparison.paste(tile,((i%2)*TILE_W,84+(i//2)*TILE_H))
        filename=f"compare-h{step:03}-{field}.png"
        comparison.save(ROOT/filename,optimize=True)
        result["maps"].setdefault(str(step),{})[field]={"path":"forecast-maps/europe/"+filename,"available":successes,"total":4}
        result["runs_by_map"].setdefault(str(step),{})[field]=used_runs
(ROOT/"compare-metadata.json").write_text(json.dumps(result,indent=2,ensure_ascii=False),encoding="utf-8")
print(json.dumps({"maps":len(result["maps"]),"available_models_per_step":{k:{a:v["available"] for a,v in x.items()} for k,x in result["maps"].items()}},ensure_ascii=False))
