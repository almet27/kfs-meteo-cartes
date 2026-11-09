#!/usr/bin/env python3
"""KFS ECMWF anticipé : cartes de surface IFS HRES 9 km, run exact Open-Meteo.

L'API gratuite est réservée à l'usage non commercial. Les données sont des
échantillons sur la France (~35–60 km), pas des cartes GRIB natives à 9 km.
La diffusion IFS Open Data originale reste indépendante et prioritaire.
"""
from __future__ import annotations
import argparse,json,math,sys
from collections import Counter
from concurrent.futures import ThreadPoolExecutor,as_completed
from datetime import datetime,timedelta,timezone
from io import BytesIO
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request,urlopen
from urllib.error import HTTPError,URLError
from zoneinfo import ZoneInfo

OUT=Path("forecast-maps/france/ifs-early9km")
OUT.mkdir(parents=True,exist_ok=True)
API="https://single-runs-api.open-meteo.com/v1/forecast"
VARS=("temperature_2m","precipitation","rain","snowfall",
      "wind_gusts_10m","weather_code","cloud_cover")
METRICS={
 "tmin":("Température minimale","temperature_2m","°C",-14,34,"RdYlBu_r"),
 "tmax":("Température maximale","temperature_2m","°C",-14,34,"RdYlBu_r"),
 "gust":("Rafales maximales","wind_gusts_10m","km/h",0,130,"turbo"),
 "precip":("Précipitations totales","precipitation","mm",0,50,"YlGnBu"),
 "rain":("Pluie liquide","rain","mm",0,50,"YlGnBu"),
 "neige_frais":("Chutes de neige (pas la tenue au sol)","snowfall","cm",0,28,"PuBu")}
PARIS=ZoneInfo("Europe/Paris")
CITIES=[(-4.49,48.38),(-1.55,47.22),(-.58,44.84),(1.44,43.60),
 (2.35,48.86),(3.06,50.63),(1.10,49.44),(4.84,45.76),
 (5.37,43.30),(7.75,48.58),(7.26,43.71)]

def valid(v):
 return isinstance(v,(int,float)) and not isinstance(v,bool) and math.isfinite(v)
def cycle_value(raw):
 if raw:
  dt=datetime.fromisoformat(raw.replace("Z","+00:00"))
  if dt.tzinfo is None:dt=dt.replace(tzinfo=timezone.utc)
  dt=dt.astimezone(timezone.utc)
  if dt.hour not in (0,12) or dt.minute or dt.second:
   raise ValueError("Sélectionner un run 00Z ou 12Z")
  return dt
 now=datetime.now(timezone.utc)
 dt=now.replace(hour=12,minute=0,second=0,microsecond=0)
 return dt if now.hour>=16 else dt-timedelta(days=1)

def get(cycle,locations):
 qs=urlencode({
  "latitude":",".join(str(p[0]) for p in locations),
  "longitude":",".join(str(p[1]) for p in locations),
  "run":cycle.strftime("%Y-%m-%dT%H:%M"),"models":"ecmwf_ifs",
  "hourly":",".join(VARS),"forecast_hours":"72","timezone":"UTC"})
 with urlopen(Request(API+"?"+qs,headers={"User-Agent":"KFS-Meteo-NonCommercial/1.0"}),
              timeout=40) as resp: payload=json.load(resp)
 if isinstance(payload,dict):payload=[payload]
 if not isinstance(payload,list) or len(payload)!=len(locations):
  raise ValueError("Le nombre de points retournés est incohérent")
 for rec in payload:
  h=rec.get("hourly",{});timestamps=h.get("time",[])
  if len(timestamps)<12:raise ValueError("Run non encore exploitable")
  parsed=[datetime.fromisoformat(x).replace(tzinfo=timezone.utc) for x in timestamps]
  if min(parsed)>cycle+timedelta(hours=1) or max(parsed)<cycle+timedelta(hours=12):
   raise ValueError("Les échéances ne correspondent pas au cycle demandé")
  for key in VARS:
   if len(h.get(key,[]))!=len(timestamps):
    raise ValueError("Variable absente du cycle "+key)
  if not any(valid(x) for x in h["temperature_2m"]):
   raise ValueError("Run sans températures valides")
 return payload

def gather(cycle,points):
 chunks=[points[i:i+16] for i in range(0,len(points),16)]
 values=[None]*len(chunks)
 with ThreadPoolExecutor(max_workers=3) as pool:
  futures={pool.submit(get,cycle,chunk):i for i,chunk in enumerate(chunks)}
  for future in as_completed(futures):values[futures[future]]=future.result()
 return [row for chunk in values for row in chunk]

def weather(codes,cloud_cover):
 from kfs_weather_symbols import kind
 categories=[kind(c) for c in codes if kind(c)]
 if not categories:return None
 c=Counter(categories);n=len(categories)
 if c["storm"]>=max(2,math.ceil(n*.15)):return 95
 if c["snow"]>=max(2,math.ceil(n*.20)):return 71
 if c["rain"]>=max(3,math.ceil(n*.35)):return 61
 if c["rain"]+c["snow"]+c["storm"]>=max(2,math.ceil(n*.12)):return 80
 if c["fog"]>=max(3,math.ceil(n*.35)):return 45
 cc=[x for x in cloud_cover if valid(x)]
 if cc:
  avg=sum(cc)/len(cc)
  return 0 if avg<25 else 2 if avg<70 else 3
 return {"sun":0,"partly":2,"cloud":3,"fog":45}.get(c.most_common(1)[0][0],2)

def collect(records,date,metric):
 key=METRICS[metric][1];out=[];codes=[];hours=[]
 for rec in records:
  h=rec["hourly"]
  indices=[i for i,t in enumerate(h["time"]) if
   datetime.fromisoformat(t).replace(tzinfo=timezone.utc).astimezone(PARIS).date().isoformat()==date]
  nums=[h[key][i] for i in indices]
  if len(nums)<3 or not all(valid(v) for v in nums):out.append(float("nan"))
  elif metric=="tmin":out.append(min(nums))
  elif metric in ("tmax","gust"):out.append(max(nums))
  else:out.append(sum(nums))
  daytime=[i for i in indices if 7<=datetime.fromisoformat(h["time"][i]).replace(
   tzinfo=timezone.utc).astimezone(PARIS).hour<20]
  if len(daytime)<3:daytime=indices
  codes.append(weather([h["weather_code"][i] for i in daytime],
                       [h["cloud_cover"][i] for i in daytime]))
  hours.append(len(indices))
 return out,codes,min(hours,default=0)

def draw(cycle,date,day,metric,coords,values,codes,hours):
 import matplotlib
 matplotlib.use("Agg")
 import matplotlib.pyplot as plt
 import matplotlib.patheffects as pe
 from matplotlib.colors import Normalize
 import cartopy.crs as ccrs
 import cartopy.feature as cf
 from PIL import Image
 from kfs_weather_symbols import overlay
 name,field,unit,vmin,vmax,cmap=METRICS[metric]
 good=[(lon,lat,v) for (lat,lon),v in zip(coords,values) if valid(v)]
 if len(good)<len(coords)*.9:raise RuntimeError("Données terrestres incomplètes")
 xx,yy,zz=zip(*good)
 fig=plt.figure(figsize=(11.2,9.4),dpi=115,facecolor="#081f35")
 ax=fig.add_axes((.065,.15,.87,.69),projection=ccrs.PlateCarree())
 ax.set_extent((-5.8,9.8,41.2,51.8))
 ax.add_feature(cf.LAND,facecolor="#e8ede3",zorder=0)
 ax.add_feature(cf.OCEAN,facecolor="#153c59",zorder=0)
 ax.coastlines("110m",linewidth=.75,color="#20364a")
 ax.add_feature(cf.BORDERS,linewidth=.6,edgecolor="#29485e")
 plot=ax.scatter(xx,yy,c=zz,cmap=cmap,norm=Normalize(vmin,vmax),
     s=92,edgecolors="none",transform=ccrs.PlateCarree(),zorder=2)
 protected=[]
 for lon,lat in CITIES:
  near=min(range(len(coords)),key=lambda i:
    (coords[i][0]-lat)**2+(coords[i][1]-lon)**2)
  v=values[near]
  if not valid(v):continue
  text=(f"{v:+.0f}°" if metric in ("tmin","tmax") else
        f"{v:.0f}" if metric=="gust" else f"{v:.1f}")
  a=ax.text(lon,lat,text,fontsize=9,color="#132f44",fontweight="bold",
     ha="center",va="center",transform=ccrs.PlateCarree(),zorder=11)
  a.set_path_effects([pe.withStroke(linewidth=2.5,foreground="white")])
  protected.append((lon,lat))
 overlay(ax,coords,codes,max_icons=7,protected=protected)
 cb=fig.colorbar(plot,ax=ax,orientation="horizontal",shrink=.8,pad=.04)
 cb.set_label(unit,color="white")
 cb.ax.tick_params(colors="white")
 fig.text(.055,.96,"KFS MÉTÉO /FRANCE  •  ECMWF IFS HRES 9 KM",
  fontsize=15,color="#f1f8ff",weight="bold")
 fig.text(.055,.918,f"{name} | {date} | J+{day}",fontsize=14,
  color="#71dcee",weight="bold")
 coverage="journée complète" if hours>=23 else f"journée partielle ({hours} h disponibles)"
 fig.text(.055,.879,f"RUN {cycle:%d/%m/%Y %HZ} UTC • {coverage}",
  fontsize=10,color="#d0e9f3")
 fig.text(.055,.064,"Source : ECMWF via Open-Meteo (CC BY 4.0) • usage non commercial",
  fontsize=9,color="#c4dbeb")
 fig.text(.055,.038,"Échantillons ~35-60 km ; ne pas confondre avec la grille native 9 km.",
  fontsize=9,color="#c4dbeb")
 filename=f"ifs9-{metric}-j{day}.webp";dest=OUT/filename
 b=BytesIO()
 fig.savefig(b,format="png",dpi=115,facecolor=fig.get_facecolor())
 plt.close(fig);b.seek(0)
 Image.open(b).convert("RGB").save(dest,"WEBP",quality=84,method=4)
 if dest.stat().st_size<12000:raise RuntimeError("WebP trop petit")
 return {"file":filename,"bytes":dest.stat().st_size,"coverage_hours":hours}

def main():
 p=argparse.ArgumentParser()
 p.add_argument("--run-utc",default="")
 p.add_argument("--probe-only",action="store_true")
 args=p.parse_args();cycle=cycle_value(args.run_utc)
 if cycle>datetime.now(timezone.utc)-timedelta(hours=3):
  print("KFS_IFS9_PENDING cycle trop récent");return 0
 latest=OUT/"latest.json"
 if latest.exists():
  try:
   old=json.loads(latest.read_text(encoding="utf-8"))
   if old.get("run_utc")==cycle.isoformat():
    print("KFS_IFS9_ALREADY_PUBLISHED",cycle.isoformat());return 0
  except (ValueError,OSError):pass
 try:get(cycle,[(49.03,1.15)])
 except (HTTPError,URLError,TimeoutError,ValueError,KeyError) as error:
  print("KFS_IFS9_PENDING",cycle.isoformat(),str(error)[:180]);return 0
 print("KFS_IFS9_CYCLE_CONFIRMED",cycle.isoformat(),flush=True)
 if args.probe_only:return 0
 from generate_france_shortterm_risks import points
 coords=points()[::2]
 records=gather(cycle,coords)
 first=cycle.astimezone(PARIS).date()
 manifest={"schema":1,"model":"ecmwf_ifs","run_utc":cycle.isoformat(),
   "generated_utc":datetime.now(timezone.utc).isoformat(),
   "source":"Open-Meteo Single Runs API / ECMWF IFS HRES",
   "resolution_native_km":9,"sample_spacing":"~35-60 km",
   "licence":"CC BY 4.0","usage":"Non-commercial only",
   "days":{},"note":"Premières cartes de surface, sans T850/Z500. Le GRIB officiel reste inchangé."}
 for day in (0,1,2):
  date=(first+timedelta(days=day)).isoformat();maps={}
  for metric in METRICS:
   values,codes,hours=collect(records,date,metric)
   if hours<6 or sum(valid(v) for v in values)<len(values)*.9:continue
   maps[metric]=draw(cycle,date,day,metric,coords,values,codes,hours)
  if maps:manifest["days"][str(day)]={"date":date,"maps":maps}
 if not manifest["days"]:raise RuntimeError("Pas de journées complètes ou partielles vérifiées")
 temp=latest.with_suffix(".tmp")
 temp.write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
 temp.replace(latest)
 print("KFS_IFS9_PUBLISHED",cycle.isoformat(),list(manifest["days"]))
 return 0

if __name__=="__main__":sys.exit(main())
