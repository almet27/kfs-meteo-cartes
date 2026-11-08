#!/usr/bin/env python3
"""Build three modern KFS synoptic comparison cards from real ECMWF forecast PNGs.

Each image is tied to the exact run(s) and generated timestamp of the numerical
bulletin. It must never be treated as a climatological anomaly or a weekly mean.
"""
from __future__ import annotations
import json
import math
from datetime import datetime, timedelta, timezone
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont, ImageOps

ROOT=Path("forecast-maps")
EU=ROOT/"europe"
OUT=ROOT/"tendance"
OUT.mkdir(parents=True,exist_ok=True)
W,H=1600,1120
C={
 "bg":(9,21,40),"deep":(13,32,55),"panel":(22,44,67),"border":(65,102,125),
 "white":(242,250,255),"muted":(158,186,211),"cyan":(85,220,236),
 "gold":(255,199,91),"green":(106,233,172),"blue":(98,151,255)}
STAGES=[
 {"id":"j3","step":"72","stage":"PERIODE 01  /  ENVIRON J+3","name":"Circulation de debut de periode","caption":"Flux et structures de pression : scenarii IFS et AIFS"},
 {"id":"j7","step":"168","stage":"PERIODE 02  /  ENVIRON J+7","name":"Evolution a moyen terme","caption":"Centres d'action et divergences possibles"},
 {"id":"j10","step":"240","stage":"PERIODE 03  /  ENVIRON J+10","name":"Scenario de fin de periode","caption":"Echeance fragile : plusieurs configurations possibles"},
]

def f(sz,bold=False):
  p="/usr/share/fonts/truetype/dejavu/DejaVuSans"+("-Bold.ttf" if bold else ".ttf")
  return ImageFont.truetype(p,sz)
def label(d,x,y,t,size=22,col="white",bold=False):
  d.text((x,y),str(t),font=f(size,bold),fill=C.get(col,col))
def rect(d,box,r=22,fill="panel",stroke=None):
  d.rounded_rectangle(box,radius=r,fill=C.get(fill,fill),
                      outline=C.get(stroke,stroke) if stroke else None,width=2)
def valid_date(value):
  x=datetime.fromisoformat(value.replace("Z","+00:00"))
  if x.tzinfo is None:raise ValueError("Horodatage UTC obligatoire")
  return x.astimezone(timezone.utc)
def iso(v):return valid_date(v).strftime("%d/%m/%Y %H:%M UTC")
def choose(meta,data,stage,model):
  h=stage["step"]
  info=data["models"].get(model,{}).get(h)
  if not info:raise RuntimeError("Absence donnees "+model+" +"+h)
  actual=meta["runs_utc"].get(model,{}).get(h)
  if not actual or valid_date(actual)!=valid_date(info["run_utc"]):
    raise RuntimeError("Run carte != run bulletin : "+model+" +"+h+" carte="+str(actual)+" analyse="+str(info["run_utc"]))
  p=EU/Path(meta["maps"][model][h]["z500_msl"]).name
  if not p.is_file():raise FileNotFoundError(str(p))
  if p.stat().st_size<10000:raise RuntimeError("Carte trop petite: "+str(p))
  return p,info

def card(stage,meta,data,now):
  h=stage["step"]
  entries={}
  for model in ("ifs","aifs-single"):
    entries[model]=choose(meta,data,stage,model)
  canvas=Image.new("RGB",(W,H),C["bg"])
  d=ImageDraw.Draw(canvas)
  for y in range(H):
    t=y/(H-1)
    rgb=tuple(int(C["bg"][k]*(1-t)+C["deep"][k]*t) for k in range(3))
    d.line((0,y,W,y),fill=rgb,width=1)
  d.rectangle((0,0,13,H),fill=C["cyan"])
  label(d,52,31,"KFS METEO",39,"white",True)
  label(d,54,89,stage["stage"],24,"cyan",True)
  label(d,53,129,stage["name"],39,"white",True)
  label(d,55,181,"COMPARAISON DES SORTIES DETERMINISTES  |  EUROPE & ATLANTIQUE NORD",19,"muted")
  labels=[("ifs","IFS",56),("aifs-single","AIFS",814)]
  for model,title,left in labels:
    src,info=entries[model]
    rect(d,(left,237,left+730,868),25,"panel","border")
    rect(d,(left+14,251,left+716,315),13,"deep")
    label(d,left+36,262,title,30,"white",True)
    label(d,left+163,266,"Z500 + pression au sol",21,"muted")
    with Image.open(src) as im:
      fitted=ImageOps.contain(im.convert("RGB"),(704,488),Image.Resampling.LANCZOS)
    x=left+13+(704-fitted.width)//2
    y=left*0+331+(488-fitted.height)//2
    canvas.paste(fitted,(x,y))
    label(d,left+26,826,"Run "+iso(info["run_utc"]),18,"muted")
  rect(d,(56,889,W-56,1062),26,"deep","border")
  label(d,80,905,"MASSES D'AIR & COURANTS A 850 hPa  |  DOMAINE FRANCE",21,"cyan",True)
  for model,title,left in labels:
    _,info=entries[model]
    flow=info.get("flow_850",{}).get("france",{})
    t850=info.get("fields",{}).get("t850",{}).get("france",{}).get("mean")
    if not flow or t850 is None:raise RuntimeError("Champ flux/T850 manquant "+model)
    dr=flow.get("from_deg")
    winds="direction indisponible" if dr is None else "de %03d degres" % dr
    label(d,left+24,951,"%s   |   T850 %+0.1f C" %(title,t850),26,"white",True)
    label(d,left+24,990,"Flux %s   |   %.1f m/s" %(winds,flow["vector_speed_ms"]),20,"gold")
  label(d,60,1070,"ECMWF Open Data (CC BY 4.0)  |  Champs ponctuels, pas de moyenne hebdomadaire",15,"muted")
  label(d,1315,1070,"Genere "+now.strftime("%d/%m %H:%M UTC"),14,"muted")
  file=OUT/("tendance-carte-"+stage["id"]+".png")
  canvas.save(file,format="PNG",optimize=True)
  return {
    "id":stage["id"],"step_h":int(h),"path":str(file),
    "image_url":"https://almet27.github.io/kfs-meteo-cartes/"+str(file),
    "size_bytes":file.stat().st_size,
    "run_utc":{m:entries[m][1]["run_utc"] for m in entries},
    "valid_utc":{m:entries[m][1]["valid_utc"] for m in entries},
    "title":stage["name"],
    "model_comparison":"IFS / AIFS · champs synoptiques de meme echeance, mais horaires de validite parfois differents",
  }
def main():
  now=datetime.now(timezone.utc)
  data=json.loads((OUT/"tendance-analyse-donnees.json").read_text(encoding="utf-8"))
  meta=json.loads((EU/"metadata.json").read_text(encoding="utf-8"))
  source_time=valid_date(data["generated_utc"])
  map_time=valid_date(meta["generated_utc"])
  if not (timedelta(hours=-1)<now-source_time<timedelta(hours=48)):
    raise RuntimeError("Diagnostic synoptique trop ancien")
  if not (timedelta(hours=-1)<now-map_time<timedelta(hours=48)):
    raise RuntimeError("Cartes de prevision perimees")
  generated=[card(stage,meta,data,now) for stage in STAGES]
  manifest={
   "schema_version":1,"status":"illustrative_model_maps","generated_utc":now.isoformat(),
   "source_generated_utc":data["generated_utc"],"charts_generated_utc":meta["generated_utc"],
   "source":"ECMWF Open Data (CC BY 4.0)","not_weekly_anomalies":True,
   "period_maps":generated,"public":True,
   "note":"Cartes de modeles pour trois echeances precises. Ne pas extrapoler aux semaines 3 et 4."}
  (OUT/"tendance-cartes.json").write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
  print(json.dumps({k:manifest[k] for k in ("generated_utc","source_generated_utc","period_maps")},ensure_ascii=False))
if __name__=="__main__":main()
