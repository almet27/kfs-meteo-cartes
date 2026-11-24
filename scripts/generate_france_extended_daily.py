#!/usr/bin/env python3
"""J+0 à J+5 France: real daily IFS/GFS fields on a stated ~25–35 km grid.

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
import json,math,time,gzip,shutil
from tempfile import TemporaryDirectory
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.colors import Normalize
import cartopy.crs as ccrs
import cartopy.feature as cfeature
from PIL import Image
from generate_france_shortterm_risks import points
from kfs_surface_style import france_axes, surface as draw_surface, labels, symbols, TEMP_CMAP, TEMP_MIN, TEMP_MAX
from kfs_weather_cache import cached, validate_rows, record_quota, prune, utc_hour, cache_key

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
    # Un seul appel batch pour les valeurs + code WMO du jour.
    # Si le modèle ne produit pas weather_code, on conserve les cartes numériques.
    code_available=True
    error=None
    for attempt in range(4):
        qs=urlencode({"latitude":",".join(str(p[0]) for p in points_),
                      "longitude":",".join(str(p[1]) for p in points_),
                      "models":SOURCE[model],
                      "daily":",".join([x[0] for x in FIELDS.values()]+
                                       (["weather_code"] if code_available else [])),
                      "forecast_days":7,"timezone":"Europe/Paris"})
        url="https://api.open-meteo.com/v1/forecast?"+qs
        try:
            with urlopen(Request(url,headers={"User-Agent":"KFS-Meteo-Daily/1.0"}),
                         timeout=45) as response:
                value=json.load(response)
            if isinstance(value,dict):value=[value]
            if len(value)!=len(points_):raise ValueError("Nombre de points inattendu")
            return value
        except (HTTPError,URLError,TimeoutError,ValueError) as exc:
            record_quota(exc)
            error=exc
            if isinstance(exc,HTTPError) and exc.code==400 and code_available:
                code_available=False
                print("KFS_J5_WMO_UNSUPPORTED",model,flush=True)
                continue
            if isinstance(exc,HTTPError) and exc.code in (400,401,403):raise
            if attempt<3:time.sleep(2+2*min(attempt,2))
    raise RuntimeError("API "+model+" indisponible : "+str(error)[:180])

def fetch_all(model,coords,window,offline=False):
    rows=[]
    for i in range(0,len(coords),18):
        chunk=coords[i:i+18]
        ident={"model":SOURCE[model],"window":window,"coords":chunk,
               "fields":[x[0] for x in FIELDS.values()]+["weather_code"],"days":7}
        if offline:
            with gzip.open(cache_key("global-daily-v1",ident),"rt",encoding="utf-8") as fp:
                result=json.load(fp)
            validate_rows(result,len(chunk),"daily")
            rows.extend(result)
        else:
            rows.extend(cached("global-daily-v1",ident,lambda:fetch_batch(model,chunk),
                               lambda r:validate_rows(r,len(chunk),"daily")))
    times=rows[0]["daily"]["time"]
    if any(r["daily"]["time"]!=times for r in rows):
        raise RuntimeError("Fenêtres journalières différentes")
    return rows

def render(model,metric,offset,date,coords,vals,codes=None):
    variable,label,vmin,vmax,cmap=FIELDS[metric]
    fig=plt.figure(figsize=(11,10.2),dpi=120,facecolor="#082a4e")
    ax=france_axes(fig)
    ax.add_feature(cfeature.OCEAN,facecolor="#173e5d",zorder=0)
    ax.add_feature(cfeature.LAND,facecolor="#e8eadf",zorder=0)
    ax.coastlines("110m",linewidth=.72,color="#263b4b")
    ax.add_feature(cfeature.BORDERS,linewidth=.75,edgecolor="#263b4b")
    norm=Normalize(vmin=vmin,vmax=vmax)
    if metric in ("tmin","tmax"):
        cmap,norm=TEMP_CMAP,Normalize(TEMP_MIN,TEMP_MAX)
    numbers=[v if isinstance(v,(float,int)) and math.isfinite(v) else float("nan") for v in vals]
    zs=[v for v in numbers if math.isfinite(v)]
    if len(zs)<len(coords)*.92:
        raise RuntimeError("Pas assez de points complets "+model+" "+metric+" J+"+str(offset))
    shade=draw_surface(ax,coords,numbers,metric,cmap,norm)
    protected=labels(ax,coords,numbers,metric)
    if codes and metric in ("tmin","tmax"):
        try:
            icons=symbols(ax,coords,codes,protected)
            if icons:print("KFS_J5_WMO_ICONS",model,metric,offset,icons,flush=True)
        except Exception as exc:
            print("KFS_J5_WMO_ICON_SKIPPED",str(exc)[:130],flush=True)
    cb=fig.colorbar(shade,cax=fig.add_axes([.17,.105,.66,.023]),orientation="horizontal")
    cb.ax.tick_params(colors="#eef5fc")
    cb.outline.set_edgecolor("#e8f2ff")
    fig.text(.045,.96,"KFS MÉTÉO | FRANCE • PRÉVISION JOURNALIÈRE",
             color="#ffffff",fontsize=16,weight="bold")
    fig.text(.045,.912,"J+"+str(offset)+" • "+date+" • "+label,
             color="#7ae1ff",fontsize=15,weight="bold")
    fig.text(.045,.878,model.upper()+" • "+str(len(zs))+
             " points de grille échantillonnés",color="#c9dded",fontsize=10)
    fig.text(.06,.063,"Échantillonnage ~25–35 km • dégradé interpolé • valeurs issues du modèle.",
             color="#d4e3ed",fontsize=10)
    fig.text(.06,.034,"Données modèle via Open-Meteo ; heures exactes de rafales non indiquées. Non officiel.",
             color="#b5c6d9",fontsize=9)
    path=OUT/("daily-"+model+"-"+metric+"-d"+str(offset)+".webp")
    buf=BytesIO()
    detail=None
    if metric in ("tmin","tmax"):
        from kfs_zoom_detail import samples,geometry
        detail=samples(coords,numbers,.38);detail["geometry"]=geometry(ax)
    fig.savefig(buf,format="png",dpi=120,facecolor=fig.get_facecolor())
    plt.close(fig)
    buf.seek(0)
    im=Image.open(buf).convert("RGB")
    im.save(path,"WEBP",quality=86,method=5)
    if path.stat().st_size<10000:raise RuntimeError("Carte WebP vide")
    return {"filename":path.name,"bytes":path.stat().st_size,
            "url":"https://almet27.github.io/kfs-meteo-cartes/forecast-maps/france/daily-extended/"+path.name,
            "date":date,"valid_points":len(zs),**({"detail":detail} if detail is not None else {})}

def main():
    global OUT
    prune()
    now=datetime.now(timezone.utc)
    window=utc_hour()
    date=datetime.now(PARIS).date()
    coords=points()
    dest=OUT
    try:
        doc=json.loads((dest/"latest.json").read_text())
        all_models=doc["models"]
        for m in all_models.values():
            m.setdefault("generated_utc",doc.get("generated_utc"))
    except (OSError,ValueError,KeyError):
        all_models={}
    completed=[]
    for model in SOURCE:
        try:
            try:
                records=fetch_all(model,coords,window)
                data_window=window
                if utc_hour()!=window:raise RuntimeError("Fenêtre de collecte changée")
            except Exception as exc:
                print("KFS_J5_LIVE_DEFERRED",model,str(exc)[:200],flush=True)
                records=None
                # Reuse only a COMPLETE existing cache from the same day, without API calls.
                for n in range(1,4):
                    at=now-timedelta(hours=n)
                    if at.astimezone(PARIS).date()!=date:break
                    data_window=at.strftime("%Y-%m-%dT%H:00")
                    try:
                        records=fetch_all(model,coords,data_window,offline=True)
                        break
                    except (OSError,ValueError,RuntimeError):continue
                if records is None:raise RuntimeError("No complete recent cached model")
            with TemporaryDirectory() as tmp:
                OUT=Path(tmp)
                maps={}
                for day in range(6):
                    target=(date+timedelta(days=day)).isoformat()
                    fields={}
                    day_codes=[]
                    for record in records:
                        daily=record.get("daily",{})
                        try:
                            at_day=daily["time"].index(target)
                            code=daily.get("weather_code",[])[at_day]
                        except (ValueError,IndexError,KeyError,TypeError):
                            code=None
                        day_codes.append(code)
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
                        fields[metric]=render(model,metric,day,target,coords,values,day_codes)
                    maps[str(day)]={"date":target,"maps":fields}

                for p in OUT.glob("*.webp"):shutil.copy2(p,dest/p.name)
            all_models[model]={"source":SOURCE[model],"days":maps,
                "generated_utc":data_window+":00+00:00","rendered_utc":now.isoformat()}
            completed.append(model)
            print("KFS_FRANCE_J5_MODEL_OK",model,len(coords),flush=True)
        except Exception as exc:
            print("KFS_FRANCE_J5_MODEL_DEFERRED",model,str(exc)[:250],flush=True)
        finally:
            OUT=dest
    if completed:
        doc={"schema":1,"generated_utc":max(m.get("generated_utc") or "" for m in all_models.values()),
            "rendered_utc":now.isoformat(),
            "source":"Modèles ECMWF IFS et NOAA GFS via Open-Meteo",
            "sampling":"0.38° longitude, 0.32° latitude, points terrestres uniquement",
            "not_native_grib":True,"models":all_models}
        (OUT/"latest.json").write_text(json.dumps(doc,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print("KFS_FRANCE_J5_PUBLISHED",completed,flush=True)

if __name__=="__main__":
    main()
