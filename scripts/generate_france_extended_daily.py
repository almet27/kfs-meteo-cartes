#!/usr/bin/env python3
"""J+4/J+5 France: real daily IFS/GFS fields on a stated ~25–35 km grid.

Deliberately separate from the 0–72 h native-GRIB maps. No false hourly
gust time or high-resolution detail is invented.
"""
from __future__ import annotations
from concurrent.futures import ThreadPoolExecutor,as_completed
from datetime import datetime,timedelta,timezone
from io import BytesIO
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request,urlopen
from urllib.error import HTTPError,URLError
from zoneinfo import ZoneInfo
import json,math,time
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.colors import Normalize
import cartopy.crs as ccrs
import cartopy.feature as cfeature
from PIL import Image
from generate_france_shortterm_risks import points

OUT=Path("forecast-maps/france/daily-extended")
OUT.mkdir(parents=True,exist_ok=True)
SOURCE={"ifs":"ecmwf_ifs025","gfs":"ncep_gfs_global"}
FIELDS={
  "tmin":("temperature_2m_min","Tmin (°C)",-20,35,"coolwarm"),
  "tmax":("temperature_2m_max","Tmax (°C)",-10,42,"turbo"),
  "gust":("wind_gusts_10m_max","Rafales maximales (km/h)",0,140,"turbo"),
  "precip":("precipitation_sum","Précipitations (mm / jour)",0,65,"YlGnBu"),
  "rain":("rain_sum","Pluie seule (mm / jour)",0,65,"YlGnBu")
}
PARIS=ZoneInfo("Europe/Paris")

def fetch_batch(model,points_):
    qs=urlencode({"latitude":",".join(str(p[0]) for p in points_),
                  "longitude":",".join(str(p[1]) for p in points_),
                  "models":SOURCE[model],
                  "daily":",".join(x[0] for x in FIELDS.values()),
                  "forecast_days":7,"timezone":"Europe/Paris"})
    url="https://api.open-meteo.com/v1/forecast?"+qs
    error=None
    for attempt in range(3):
        try:
            with urlopen(Request(url,headers={"User-Agent":"KFS-Meteo-Daily/1.0"}),
                         timeout=45) as response:
                value=json.load(response)
            if isinstance(value,dict):value=[value]
            if len(value)!=len(points_):raise ValueError("Nombre de points inattendu")
            return value
        except (HTTPError,URLError,TimeoutError,ValueError) as exc:
            error=exc
            if isinstance(exc,HTTPError) and exc.code in (400,401,403):raise
            time.sleep(2+2*attempt)
    raise RuntimeError("API "+model+" indisponible : "+str(error)[:180])

def fetch_all(model,coords):
    span=18
    chunks=[coords[i:i+span] for i in range(0,len(coords),span)]
    values=[None]*len(coords)
    with ThreadPoolExecutor(max_workers=3) as executor:
        jobs={executor.submit(fetch_batch,model,chunk):i
              for i,chunk in enumerate(chunks)}
        for job in as_completed(jobs):
            i=jobs[job];records=job.result()
            values[i*span:i*span+len(records)]=records
    if any(x is None for x in values):raise RuntimeError("Données incomplètes")
    return values

def render(model,metric,offset,date,coords,vals):
    variable,label,vmin,vmax,cmap=FIELDS[metric]
    fig=plt.figure(figsize=(11,10.2),dpi=120,facecolor="#082a4e")
    ax=fig.add_axes([.06,.16,.87,.68],projection=ccrs.PlateCarree())
    ax.set_extent([-5.8,9.8,41.2,51.8])
    ax.add_feature(cfeature.OCEAN,facecolor="#173e5d",zorder=0)
    ax.add_feature(cfeature.LAND,facecolor="#e8eadf",zorder=0)
    ax.coastlines("110m",linewidth=.72,color="#263b4b")
    ax.add_feature(cfeature.BORDERS,linewidth=.75,edgecolor="#263b4b")
    norm=Normalize(vmin=vmin,vmax=vmax)
    numbers=[v if isinstance(v,(float,int)) and math.isfinite(v) else float("nan") for v in vals]
    xs=[coords[i][1] for i,v in enumerate(numbers) if math.isfinite(v)]
    ys=[coords[i][0] for i,v in enumerate(numbers) if math.isfinite(v)]
    zs=[v for v in numbers if math.isfinite(v)]
    if len(zs)<len(coords)*.92:
        raise RuntimeError("Pas assez de points complets "+model+" "+metric+" J+"+str(offset))
    scatter=ax.scatter(xs,ys,c=zs,cmap=cmap,norm=norm,s=65,
                       edgecolors="#1a3551",linewidths=.14,
                       transform=ccrs.PlateCarree(),zorder=4)
    cb=fig.colorbar(scatter,ax=ax,orientation="horizontal",shrink=.82,pad=.055)
    cb.ax.tick_params(colors="#eef5fc")
    cb.outline.set_edgecolor("#e8f2ff")
    fig.text(.045,.96,"KFS MÉTÉO | FRANCE • PRÉVISION JOURNALIÈRE",
             color="#ffffff",fontsize=16,weight="bold")
    fig.text(.045,.912,"J+"+str(offset)+" • "+date+" • "+label,
             color="#7ae1ff",fontsize=15,weight="bold")
    fig.text(.045,.878,model.upper()+" • "+str(len(zs))+
             " points de grille échantillonnés",color="#c9dded",fontsize=10)
    fig.text(.06,.063,"Échantillonnage ~25–35 km • les événements locaux peuvent être manqués.",
             color="#d4e3ed",fontsize=10)
    fig.text(.06,.034,"Données modèle via Open-Meteo ; heures exactes de rafales non indiquées. Non officiel.",
             color="#b5c6d9",fontsize=9)
    path=OUT/("daily-"+model+"-"+metric+"-d"+str(offset)+".webp")
    buf=BytesIO()
    fig.savefig(buf,format="png",dpi=120,facecolor=fig.get_facecolor())
    plt.close(fig)
    buf.seek(0)
    im=Image.open(buf).convert("RGB")
    im.save(path,"WEBP",quality=86,method=5)
    if path.stat().st_size<10000:raise RuntimeError("Carte WebP vide")
    return {"filename":path.name,"bytes":path.stat().st_size,
            "url":"https://almet27.github.io/kfs-meteo-cartes/forecast-maps/france/daily-extended/"+path.name,
            "date":date,"valid_points":len(zs)}

def main():
    now=datetime.now(timezone.utc)
    date=datetime.now(PARIS).date()
    coords=points()
    all_models={}
    for model in SOURCE:
        records=fetch_all(model,coords)
        maps={}
        for day in (4,5):
            target=(date+timedelta(days=day)).isoformat()
            fields={}
            for metric,(name,_,_,_,_) in FIELDS.items():
                values=[]
                for record in records:
                    daily=record.get("daily",{})
                    try:
                        index=daily["time"].index(target)
                        value=daily[name][index]
                    except (ValueError,IndexError,KeyError,TypeError):
                        value=None
                    values.append(value)
                fields[metric]=render(model,metric,day,target,coords,values)
            maps[str(day)]={"date":target,"maps":fields}
        all_models[model]={"source":SOURCE[model],"days":maps}
        print("KFS_FRANCE_J5_MODEL_OK",model,len(coords),flush=True)
    doc={"schema":1,"generated_utc":now.isoformat(),
         "source":"Modèles ECMWF IFS et NOAA GFS via Open-Meteo",
         "sampling":"0.38° longitude, 0.32° latitude, points terrestres uniquement",
         "not_native_grib":True,"models":all_models}
    (OUT/"latest.json").write_text(json.dumps(doc,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print("KFS_FRANCE_J5_READY",now.isoformat(),flush=True)

if __name__=="__main__":
    main()
