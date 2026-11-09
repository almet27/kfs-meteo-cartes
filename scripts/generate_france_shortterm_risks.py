#!/usr/bin/env python3
"""KFS /france - cartes de risque indicatif ARÔME / ICON jusqu'à 48 h.

Échantillonnage géographique explicite (ne pas confondre avec la grille native).
Le potentiel d'orage ne constitue PAS une probabilité d'orage ou une vigilance.
La neige qui tombe n'est pas assimilée à une neige qui tient au sol : pour
ARÔME, seule une susceptibilité est estimée ; ICON utilise snow_depth natif.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen
import json, math, time

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.patheffects as pe
import numpy as np
import cartopy.crs as ccrs
import cartopy.feature as cfeature
from cartopy.io import shapereader
from shapely.geometry import Point
from shapely.prepared import prep

OUT=Path("forecast-maps/france/risques")
OUT.mkdir(parents=True,exist_ok=True)
PERIODS=((0,6),(6,12),(12,24),(24,36),(36,48))
COMMON=("temperature_2m","wet_bulb_temperature_2m","cape","snowfall",
  "precipitation","wind_speed_850hPa","wind_direction_850hPa",
  "wind_speed_500hPa","wind_direction_500hPa","wind_gusts_10m")
EXTRA={"arome":(),"icon_eu":("showers","snow_depth",
  "soil_temperature_0cm","snowfall_height")}
CODES={"arome":"meteofrance_arome_france","icon_eu":"icon_eu"}
LEVELS=("non_evalue","faible","possible","marque")
COLORS=["#8196aa","#86d8bd","#f8c666","#df4058"]
LABELS={"orage":"Potentiel orageux","neige_sol":"Neige au sol / tenue possible"}

def isnum(x):
    return isinstance(x,(float,int)) and not isinstance(x,bool) and math.isfinite(x)

def wind_vector(speed,direction):
    if not isnum(speed) or not isnum(direction):return None
    rad=math.radians(direction)
    return -speed*math.sin(rad),-speed*math.cos(rad)

def shear_kmh(h,i):
    a=wind_vector(at(h,"wind_speed_850hPa",i),at(h,"wind_direction_850hPa",i))
    b=wind_vector(at(h,"wind_speed_500hPa",i),at(h,"wind_direction_500hPa",i))
    return math.hypot(b[0]-a[0],b[1]-a[1]) if a and b else None

def at(h,key,i):
    x=h.get(key,[])
    return x[i] if i<len(x) else None

def thunder_potential(h,i,model):
    cape=at(h,"cape",i)
    precip=at(h,"showers",i) if model=="icon_eu" else at(h,"precipitation",i)
    sh=shear_kmh(h,i)
    if not all(isnum(x) for x in (cape,precip,sh)):
        return 0
    # Indice qualitatif multi-critères : CAPE, cisaillement 850-500 hPa,
    # précipitations convectives ICON ou totales AROME (substitut imparfait).
    if cape>=1200 and sh>=45 and precip>=0.3:
        return 3
    if cape>=500 and sh>=25 and precip>=0.1:
        return 2
    if cape>=150 and (precip>=0.1 or sh>=40):
        return 1
    return 1 if cape>=500 else 0

def snow_ground_potential(h,i,model,previous_depth):
    snow=at(h,"snowfall",i)
    twb=at(h,"wet_bulb_temperature_2m",i)
    t2m=at(h,"temperature_2m",i)
    if not all(isnum(x) for x in (snow,twb,t2m)):
        return 0
    if model=="arome":
        # ARÔME ne fournit pas ici de neige AU SOL : ne pas la confirmer.
        if snow>=0.6 and twb<=0.0 and t2m<=1.0:return 3
        if snow>=0.2 and twb<=0.8 and t2m<=2.5:return 2
        return 1 if snow>0.05 and twb<=1.8 else 0
    depth=at(h,"snow_depth",i)
    soil=at(h,"soil_temperature_0cm",i)
    if not isnum(depth) or not isnum(soil):
        return 0
    increment=depth-previous_depth if isnum(previous_depth) else 0.0
    if depth>=0.015 and soil<=1.5 and twb<=0.8 and
       increment>=0.005:
        return 3
    if depth>=0.005 and soil<=2.5 and twb<=1.5:
        return 2
    if snow>0.05 and twb<=1.8 and soil<=3.0:
        return 1
    return 0

def points():
    path=shapereader.natural_earth(resolution="110m",category="cultural",
                                  name="admin_0_countries")
    france=[]
    for item in shapereader.Reader(path).records():
        if item.attributes.get("ADMIN")=="France":
            france.append(item.geometry)
    if not france:raise RuntimeError("Polygone terrestre français introuvable")
    geom=prep(france[0])
    pts=[]
    # Espacement 25-35 km : ce N'EST PAS une sortie native à 2.5 km.
    for lat in np.arange(42.0,51.75,.32):
        for lon in np.arange(-5.45,9.75,.38):
            if geom.intersects(Point(float(lon),float(lat))):
                pts.append((round(float(lat),3),round(float(lon),3)))
    if len(pts)<150 or len(pts)>1200:
        raise RuntimeError("Maillage suspect : "+str(len(pts)))
    return pts

def get_batch(model,records,tries=3):
    lat=",".join(str(x[0]) for x in records)
    lon=",".join(str(x[1]) for x in records)
    names=COMMON+EXTRA[model]
    url="https://api.open-meteo.com/v1/forecast?"+urlencode({
        "latitude":lat,"longitude":lon,"models":CODES[model],
        "hourly":",".join(names),"forecast_hours":48,"timezone":"UTC"})
    err=None
    for attempt in range(tries):
        try:
            with urlopen(Request(url,headers={"User-Agent":"KFS-Meteo-OpenData/1.0"}),
                         timeout=45) as response:
                data=json.load(response)
            if isinstance(data,dict):data=[data]
            if len(data)!=len(records):raise ValueError("Nombre de localisations incorrect")
            for d in data:
                if not isinstance(d,dict) or not isinstance(d.get("hourly"),dict):
                    raise ValueError("Champs météo absents")
                h=d["hourly"]
                if len(h.get("time",[]))<42:raise ValueError("Prévision trop courte")
                for n in names:
                    if n not in h or sum(isnum(x) for x in h[n])<35:
                        raise ValueError("Champ incomplet "+n+" "+model)
            return data
        except (HTTPError,URLError,TimeoutError,ValueError) as exc:
            err=exc
            if isinstance(exc,HTTPError) and exc.code in (400,401,403):
                raise
            time.sleep(2+3*attempt)
    raise RuntimeError("Source "+model+" temporairement indisponible: "+str(err)[:120])

def fetch_model(model,coords):
    chunk=18
    batches=[coords[i:i+chunk] for i in range(0,len(coords),chunk)]
    out=[None]*len(coords)
    with ThreadPoolExecutor(max_workers=3) as pool:
        tasks={pool.submit(get_batch,model,part):j for j,part in
               enumerate(batches)}
        for fut in as_completed(tasks):
            j=tasks[fut]
            rows=fut.result()
            out[j*chunk:j*chunk+len(rows)]=rows
    if any(v is None for v in out):
        raise RuntimeError(model+" : données manquantes au maillage")
    return out

def compute(model,data,period):
    left,right=period
    output={"orage":[],"neige_sol":[]}
    for d in data:
        h=d["hourly"]
        rows=min(len(h["time"]),48)
        a,b=max(0,left),min(rows,right)
        if b-a<4:
            raise RuntimeError("Période trop peu couverte : "+str(period))
        prev=at(h,"snow_depth",max(0,a-1))
        o=max(thunder_potential(h,i,model) for i in range(a,b))
        sn=max(snow_ground_potential(h,i,model,prev) for i in range(a,b))
        output["orage"].append(o)
        output["neige_sol"].append(sn)
    return output

def plot(model,variable,period,coords,values,issued):
    label=LABELS[variable]
    lo,hi=period
    fig=plt.figure(figsize=(11.4,10.2),dpi=120,facecolor="#092340")
    ax=fig.add_axes([.06,.14,.88,.70],projection=ccrs.PlateCarree())
    ax.set_extent([-5.8,9.8,41.2,51.8])
    ax.set_facecolor("#0c3054")
    ax.add_feature(cfeature.OCEAN,facecolor="#0d3558",zorder=0)
    ax.add_feature(cfeature.LAND,facecolor="#d9e5dd",zorder=0)
    ax.coastlines("110m",linewidth=.65,color="#283f4d")
    ax.add_feature(cfeature.BORDERS,linewidth=.7,edgecolor="#354d58")
    for grade in (0,1,2,3):
        xs=[coords[i][1] for i,x in enumerate(values) if x==grade]
        ys=[coords[i][0] for i,x in enumerate(values) if x==grade]
        if xs:
            ax.scatter(xs,ys,c=COLORS[grade],s=64 if grade==3 else 34,
                       marker="o",edgecolors="#21384b",linewidths=.35,
                       transform=ccrs.PlateCarree(),zorder=4+grade)
    fig.text(.05,.952,"KFS MÉTÉO  |  FRANCE COURT TERME",color="#edfaff",
             fontsize=16,weight="bold")
    fig.text(.05,.909,label+" • "+model.upper()+" • H+"+str(lo)+" à H+"+str(hi),
             color="#62d5f0",fontsize=15,weight="bold")
    fig.text(.05,.873,"Échantillon de "+str(len(coords))+" points sur le territoire",
             color="#bbdaee",fontsize=10)
    legend="     ".join(["● "+name for name in ("Non évalué","Faible","Possible","Marqué")])
    fig.text(.07,.091,legend,color="#f1f8ff",fontsize=11)
    fig.text(.06,.056,"Cartographie indicative, maillage ~25–35 km : cellules convectives plus fines possibles.",
             color="#c4d3e6",fontsize=9.7)
    footer=("ARÔME : tenue de neige estimée, non confirmée (pas de hauteur de neige au sol)."
            if model=="arome" and variable=="neige_sol"
            else "ICON : neige au sol modélisée, non constatée sur le terrain."
            if variable=="neige_sol" else
            "CAPE + cisaillement 850–500 hPa + précipitations ; pas de probabilité chiffrée.")
    fig.text(.06,.031,footer+" Aucune vigilance officielle.",
             color="#c4d3e6",fontsize=8.6)
    fname=f"risk-{model}-{variable}-h{hi:03d}.png"
    path=OUT/fname
    fig.savefig(path,dpi=120,facecolor=fig.get_facecolor())
    plt.close(fig)
    if path.stat().st_size<15000:raise RuntimeError("Image vide "+fname)
    return {"filename":fname,"url":"https://almet27.github.io/kfs-meteo-cartes/forecast-maps/france/risques/"+fname,
            "size_bytes":path.stat().st_size,
            "classes":{"non_evalue":values.count(0),"faible":values.count(1),
                       "possible":values.count(2),"marque":values.count(3)},
            "start_h":lo,"end_h":hi}

def main():
    timestamp=datetime.now(timezone.utc)
    coords=points()
    document={"schema":1,"generated_utc":timestamp.isoformat(),
      "source":"Open-Meteo, modèles natifs ARÔME France et DWD ICON Europe",
      "spatial_sampling":"Points terrestres esp. 0.38° lon / 0.32° lat ; pas une grille native",
      "not_official_warning":True,"not_thunderstorm_probability":True,
      "horizons":[6,12,24,36,48],"models":{}}
    for model in CODES:
        data=fetch_model(model,coords)
        views={}
        for period in PERIODS:
            values=compute(model,data,period)
            for kind in ("orage","neige_sol"):
                key=kind+"_h"+str(period[1])
                views[key]=plot(model,kind,period,coords,values[kind],timestamp)
        document["models"][model]={"name":CODES[model],"fields":list(COMMON+EXTRA[model]),
                                   "maps":views}
        print("KFS_FRANCE_RISK_MODEL_OK",model,len(coords),"points",flush=True)
    (OUT/"latest.json").write_text(
        json.dumps(document,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print("KFS_FRANCE_SHORTTERM_RISKS_OK",timestamp.isoformat(),flush=True)

if __name__=="__main__":
    main()
