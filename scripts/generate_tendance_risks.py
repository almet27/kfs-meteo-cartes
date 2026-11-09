#!/usr/bin/env python3
"""KFS — analyse géoréférencée des signaux météo aux échéances /tendance.

Les seuils sont des repères graphiques, PAS une vigilance ni une prévision de crue.
La carte synoptique et les marqueurs sont produits avec les mêmes coordonnées
géographiques et les mêmes runs ECMWF vérifiés.
"""
from __future__ import annotations
import json
import math
import time
from urllib.parse import urlencode
from urllib.request import urlopen
from pathlib import Path
from datetime import datetime, timezone, timedelta
import numpy as np
import xarray as xr
from ecmwf.opendata import Client
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.patheffects as pe
import cartopy.crs as ccrs
import cartopy.feature as cfeature
from kfs_synoptic_overlays import (
    premium_pictogram, t850_celsius, air_masses, frontal_candidates,
    draw_air_masses, draw_frontal_candidates,
)
from cartopy.io import shapereader
from shapely.geometry import Point
from shapely.ops import unary_union
from shapely.prepared import prep
from matplotlib.colors import LinearSegmentedColormap, Normalize
from matplotlib.cm import ScalarMappable
from matplotlib.offsetbox import AnnotationBbox, DrawingArea
from matplotlib.patches import Circle, FancyBboxPatch, PathPatch
from matplotlib.lines import Line2D
from matplotlib.path import Path as MplPath

OUT=Path("forecast-maps/tendance")
EU=Path("forecast-maps/europe")
OUT.mkdir(parents=True,exist_ok=True)
STAGES=[("j3",72,"ifs"),("j7",168,"ifs"),("j10",240,"ifs"),("j15",360,"aifs-single")]
GEOGRAPHY=(-45,35,31,75)
FOCUS=(-10,12,41,53)
CATEGORIES=("neige","verglas","orage","tempete","gel","canicule","inondation","pluie_forte")
COLORS={"vent_fort":"#FFCE66","tempete":"#FB765A","pluie_forte":"#37CFFF","neige":"#BCEBFF"}
SNOW_ALT_MAX_M=800
ELEVATION_ENDPOINT="https://api.open-meteo.com/v1/elevation"
_TERRAIN_CACHE={}
_LAND_GEOMETRY=None

def when(value):
    return datetime.fromisoformat(value.replace("Z","+00:00")).astimezone(timezone.utc)

def load(path,name):
    ds=xr.open_dataset(path,engine="cfgrib",backend_kwargs={"indexpath":""})
    try:
        z=ds[name].squeeze().load()
        lon=((np.asarray(z.longitude.values,dtype=float)+180)%360)-180
        lat=np.asarray(z.latitude.values,dtype=float)
        field=np.asarray(z.values,dtype=float)
        run=np.datetime_as_string(np.asarray(z.time.values),unit="m")+"Z"
        if lon.ndim!=1 or lat.ndim!=1 or field.ndim!=2:raise ValueError("GRIB grid not regular lat-lon")
        ix=np.argsort(lon)
        iy=np.argsort(lat)
        return lon[ix],lat[iy],field[np.ix_(iy,ix)],run,str(z.attrs.get("units",""))
    finally:ds.close()

def acquire(client,model,step,run,parameters,variables,name):
    dest=OUT/("temp-risk-"+model+"-"+str(step)+"-"+name+".grib2")
    try:
        client.retrieve(date=run.strftime("%Y-%m-%d"),time=run.hour,
                        stream="oper",type="fc",step=step,
                        param=parameters,target=str(dest),**variables)
        return [load(dest,var) for var in (parameters if False else name.split(","))]
    finally:dest.unlink(missing_ok=True)

def single(client,model,step,run,parameter,variable,level=None):
    dest=OUT/("temp-risk-"+model+"-"+str(step)+"-"+variable+".grib2")
    try:
        options={"levelist":level} if level else {}
        client.retrieve(date=run.strftime("%Y-%m-%d"),time=run.hour,
                        stream="oper",type="fc",step=step,param=parameter,
                        target=str(dest),**options)
        return load(dest,variable)
    finally:dest.unlink(missing_ok=True)

def mm_factor(unit):
    v=unit.lower().replace(" ","").replace("**","^")
    if v in {"m","metre","meter","mofwaterequivalent"}:return 1000
    if v in {"kgm^-2","kg/m^2","kgm-2","mm","kgm^(-2)"}:return 1
    raise ValueError("Unité de cumul non reconnue : "+unit)

def verify(ref,fields):
    for v in fields:
        if not (np.array_equal(ref[0],v[0]) and np.array_equal(ref[1],v[1])):
            raise RuntimeError("Grilles incompatibles")
        if when(ref[3])!=when(v[3]):raise RuntimeError("Runs GRIB non synchronisés")

def peaks(lon,lat,field,threshold,kind,limit=3,km=210):
    ys,xs=np.where(np.isfinite(field) & (field>=threshold))
    points=[]
    for j,i in zip(ys,xs):
        x,y=float(lon[i]),float(lat[j])
        if not (FOCUS[0]<=x<=FOCUS[1] and FOCUS[2]<=y<=FOCUS[3]):continue
        points.append((float(field[j,i]),x,y))
    points.sort(reverse=True)
    chosen=[]
    for value,x,y in points:
        if all(distance_km(x,y,p["lon"],p["lat"])>=km for p in chosen):
            chosen.append({"lon":round(x,2),"lat":round(y,2),"value":round(value,1),"kind":kind})
        if len(chosen)>=limit:break
    return chosen

def distance_km(lon1,lat1,lon2,lat2):
    y1,y2=math.radians(lat1),math.radians(lat2)
    a=math.sin((y2-y1)/2)**2+math.cos(y1)*math.cos(y2)*math.sin(math.radians(lon2-lon1)/2)**2
    return 12742*math.asin(min(1,math.sqrt(a)))

def status(v,low,high):
    if v is None:return "indisponible"
    return "marque" if v>=high else "possible" if v>=low else "absent"



def land_geometry():
    """Coastline filter: the ocean must not count as lowland snowfall."""
    global _LAND_GEOMETRY
    if _LAND_GEOMETRY is None:
        _LAND_GEOMETRY=prep(unary_union(list(cfeature.LAND.geometries())))
    return _LAND_GEOMETRY

def fetch_elevations(coords):
    """Copernicus DEM GLO-90 from Open-Meteo; at most 100 positions/request.

    Querying candidate grid cells (not a whole continent) keeps requests light.
    An API failure never silently classifies unverified mountain snow as lowland.
    """
    missing=[(lon,lat) for lon,lat in coords if (lon,lat) not in _TERRAIN_CACHE]
    for start in range(0,len(missing),95):
        batch=missing[start:start+95]
        params=urlencode({
            "latitude":",".join(f"{lat:.3f}" for lon,lat in batch),
            "longitude":",".join(f"{lon:.3f}" for lon,lat in batch)
        })
        error=None
        for trial in range(3):
            try:
                with urlopen(ELEVATION_ENDPOINT+"?"+params,timeout=24) as resp:
                    values=json.load(resp).get("elevation")
                if not isinstance(values,list) or len(values)!=len(batch):
                    raise RuntimeError("Nombre d'altitudes incohérent")
                for key,elev in zip(batch,values):
                    if not isinstance(elev,(float,int)) or not math.isfinite(elev):
                        raise RuntimeError("Altitude absente ou invalide")
                    _TERRAIN_CACHE[key]=float(elev)
                error=None
                break
            except Exception as exc:
                error=exc
                time.sleep(1+trial*2)
        if error is not None:
            raise RuntimeError("Altitude Copernicus non accessible : "+str(error)[:140])
    return {key:_TERRAIN_CACHE[key] for key in coords}

def snow_off_mountain(lon,lat,snow):
    """Evaluate snow on sampled grid maxima with independent 90-m terrain data.

    Samples at most one model-grid maximum per 0.5-degree cell, over land.
    A maximum from mountains cannot drive the 'lowland' risk label.
    """
    ys,xs=np.where(np.isfinite(snow)&(snow>=0.5))
    land=land_geometry()
    selected_cells={}
    for j,i in zip(ys,xs):
        x,y=float(lon[i]),float(lat[j])
        if not (FOCUS[0]<=x<=FOCUS[1] and FOCUS[2]<=y<=FOCUS[3]):
            continue
        if not land.intersects(Point(x,y)):
            continue
        key=(int(math.floor(x*2)),int(math.floor(y*2)))
        value=float(snow[j,i])
        if key not in selected_cells or value>selected_cells[key][0]:
            selected_cells[key]=(value,x,y)
    candidates=sorted(selected_cells.values(),reverse=True)
    if not candidates:
        return [],{"status":"absent","max":0.0,"unit":"mm équiv. eau/6h",
                   "reason":"Pas de neige ≥ 0,5 mm/6h sur le domaine terrestre"}
    # Keep a geographically broad sample, including potential weak snowfall in plains.
    # Avoid declaring all snow relief-only if lowlands have not been evaluated.
    if len(candidates)>500:
        return [],{"status":"indisponible","reason":"Échantillon terrain trop vaste : vérification incomplète"}
    elevations=fetch_elevations([(x,y) for value,x,y in candidates])
    low=[]
    high=[]
    for value,x,y in candidates:
        elev=elevations[(x,y)]
        record={"lon":round(x,2),"lat":round(y,2),"value":round(value,1),
                "kind":"neige","altitude_m":round(elev)}
        if elev<=SNOW_ALT_MAX_M:
            low.append(record)
        else:
            high.append(record)
    # A valley below 800 m can still lie in the Alps/Pyrenees.
    # Exclude snowfall on the mountainous surroundings, not only high peaks.
    if low:
        neighbours=[]
        around={}
        for p in low:
            key=(p["lon"],p["lat"])
            offsets=((0.25,0),(-0.25,0),(0,0.20),(0,-0.20),
                     (0.18,0.15),(-0.18,0.15),(0.18,-0.15),(-0.18,-0.15))
            pts=[(round(p["lon"]+dx,3),round(p["lat"]+dy,3)) for dx,dy in offsets]
            around[key]=pts
            neighbours.extend(pts)
        # Elevations must be verifiable; don't count an unknown mountain valley as plain.
        adjacent=fetch_elevations(list(dict.fromkeys(neighbours)))
        plains=[]
        for p in low:
            nearby=max(adjacent[c] for c in around[(p["lon"],p["lat"])])
            if nearby>=1200 and nearby-p["altitude_m"]>=400:
                p["terrain_context"]="zone montagneuse (relief voisin élevé)"
                high.append(p)
            else:
                p["terrain_context"]="hors relief marqué"
                plains.append(p)
        low=plains
    highest=max((p["value"] for p in low),default=0)
    if highest>=2:st="marque"
    elif highest>=0.5:st="possible"
    elif high:st="relief_uniquement"
    else:st="absent"
    markers=[]
    for p in sorted(low,key=lambda p:p["value"],reverse=True):
        if all(distance_km(p["lon"],p["lat"],q["lon"],q["lat"])>=180 for q in markers):
            markers.append(p)
        if len(markers)>=3:break
    return markers,{"status":st,"max":round(highest,1),"unit":"mm équiv. eau/6h",
        "reason":f"Neige hors relief ≤ {SNOW_ALT_MAX_M} m, hors vallée de montagne (Copernicus GLO-90) ; relief : "+str(len(high))+" zones échantillonnées",
        "mountain_signal":bool(high), "mountain_max":round(max((p["value"] for p in high),default=0),1),
        "lowland_sample_count":len(low),"highland_sample_count":len(high),
        "terrain_source":"Copernicus DEM GLO-90 via Open-Meteo"}

def weather_pictogram(kind):
    """Premium independent icon, no background circle."""
    return premium_pictogram(kind)

def render(id,run,fields,marks,masses,fronts):
    lon,lat=fields["msl"][0],fields["msl"][1]
    msl=fields["msl"][2]/100.0
    gh=fields["gh"][2]/10.0
    ix=np.flatnonzero((lon>=GEOGRAPHY[0])&(lon<=GEOGRAPHY[1]))
    iy=np.flatnonzero((lat>=GEOGRAPHY[2])&(lat<=GEOGRAPHY[3]))
    xx,yy=lon[ix],lat[iy]
    pres=msl[np.ix_(iy,ix)]
    geop=gh[np.ix_(iy,ix)]
    fig=plt.figure(figsize=(15.44,5.65),dpi=100,facecolor="#082D53")
    ax=fig.add_axes([0,0,1,1],projection=ccrs.PlateCarree())
    ax.set_extent(GEOGRAPHY,crs=ccrs.PlateCarree())
    ax.set_aspect("auto")
    # Premium cartographic styling inspired by the supplied TV-weather reference:
    # authentic natural-earth relief under genuine geopotential/isobars.
    ax.set_facecolor("#06315A")
    try:
        ax.stock_img()
    except Exception:
        ax.add_feature(cfeature.OCEAN,facecolor="#06406B")
        ax.add_feature(cfeature.LAND,facecolor="#73A56C")
    # The filled palette now encodes REAL 850-hPa air temperature in Celsius.
    # A fixed scale is used for J+3/J+7/J+10/J+15: equal colours = equal temperatures.
    # 850-hPa temperature describes air aloft, not 2-m temperature or heatwave risk.
    temp850=t850_celsius(fields["t850"][2],fields["t850"][4])
    tc=temp850[np.ix_(iy,ix)]
    palette=LinearSegmentedColormap.from_list("kfs_t850_masses_d_air",[
        (0.00,"#142A82"), (0.20,"#2452BA"), (0.325,"#4B99D7"),
        (0.425,"#91D8E8"), (0.50,"#75BEA5"), (0.625,"#F5DC85"),
        (0.750,"#F1A05C"), (0.875,"#E9674A"), (1.00,"#B93451")])
    temp_norm=Normalize(vmin=-20,vmax=20)
    ax.contourf(xx,yy,tc,levels=np.arange(-30,32,2),
                cmap=palette,norm=temp_norm,alpha=.70,
                extend="both",transform=ccrs.PlateCarree(),zorder=2)
    # Keep subtle 500-hPa height contours but do NOT use them as heat colours.
    ax.contour(xx,yy,geop,levels=np.arange(470,610,10),
               colors="#EDF6FF",linewidths=.42,linestyles="dashed",
               alpha=.22,transform=ccrs.PlateCarree(),zorder=3)
    # Compact fixed Celsius legend, positioned above map annotations.
    cax=fig.add_axes([.685,.793,.272,.029])
    cb=fig.colorbar(ScalarMappable(norm=temp_norm,cmap=palette),
                    cax=cax,orientation="horizontal",
                    ticks=[-20,-10,0,10,20],extend="both")
    cb.ax.set_xticklabels(["-20","-10","0","+10","+20"])
    cb.ax.tick_params(axis="x",colors="#F7FAFF",labelsize=10,length=3,pad=2)
    cb.outline.set_edgecolor("#EAF6FF")
    cb.outline.set_linewidth(1)
    fig.text(.684,.851,"MASSES D'AIR  •  TEMPÉRATURE 850 hPa (°C)",
             fontsize=10.5,color="white",weight="bold",
             bbox=dict(boxstyle="round,pad=0.35",facecolor="#082A51",
                       edgecolor="#99CBEA",alpha=.9))
    # Cyan precipitation veils are derived only from the 6-hour model field.
    if "rain6h" in fields:
        rr=fields["rain6h"][2][np.ix_(iy,ix)]
        shade=np.ma.masked_where(~np.isfinite(rr)|(rr<2),rr)
        if np.ma.count(shade):
            ax.contourf(xx,yy,shade,levels=[2,5,10,20,40,80,160],
                        colors=["#42BDF2","#22B8ED","#009BC9","#1579BA","#2869AD","#4458AB"],
                        alpha=.25,extend="max",transform=ccrs.PlateCarree(),zorder=5)
    cs=ax.contour(xx,yy,pres,levels=np.arange(940,1061,5),
                  colors="white",linewidths=1.05,transform=ccrs.PlateCarree())
    labels=ax.clabel(cs,fmt="%d",inline=True,fontsize=8,colors="white")
    for a in labels:a.set_path_effects([pe.Stroke(linewidth=2.5,foreground="#173147"),pe.Normal()])
    ax.coastlines("110m",linewidth=.85,color="#EFF6F9",zorder=10)
    ax.add_feature(cfeature.BORDERS,linewidth=.56,edgecolor="#E2EFF5",alpha=.82,zorder=10)
    # Derived from numerical temperature gradients + 6-hour tendency + precipitation.
    # Not official analysed fronts; long-range maps intentionally omit individual fronts.
    draw_frontal_candidates(ax,fronts)
    draw_air_masses(ax,masses)
    for mark in marks:
        x,y=mark["lon"],mark["lat"]
        icon=weather_pictogram(mark["kind"])
        pin=AnnotationBbox(icon,(x,y),
                           xycoords=ccrs.PlateCarree()._as_mpl_transform(ax),
                           box_alignment=(0.5,0.5),frameon=False,pad=0,zorder=18)
        ax.add_artist(pin)
    fn=OUT/("tendance-risques-fond-"+id+".png")
    fig.savefig(fn,dpi=100,facecolor=fig.get_facecolor(),pad_inches=0)
    plt.close(fig)
    return fn

def calculate(id,step,model,atlas,now):
    recorded=atlas["runs_utc"][model][str(step)]
    run=when(recorded)
    if run>now+timedelta(hours=1) or now-run>timedelta(hours=48):
        raise RuntimeError("Run de carte trop ancien")
    client=Client(source="ecmwf",model=model,resol="0p25")
    # Fully aligned synoptic data, 10m WIND, six-hour precipitation and snow-water.
    f={}
    for key,param,var,lev in (("gh","gh","gh",500),("msl","msl","msl",None),
                               ("u","10u","u10",None),("v","10v","v10",None),
                               ("tp","tp","tp",None),("sf","sf","sf",None),
                               ("t850","t","t",850)):
        f[key]=single(client,model,step,run,param,var,lev)
    for key,param,var in (("tp_prev","tp","tp"),("sf_prev","sf","sf")):
        f[key]=single(client,model,step-6,run,param,var)
    if step<=168:
        f["t850_prev"]=single(client,model,step-6,run,"t","t",850)
    verify(f["msl"],list(f.values()))
    x,y=f["msl"][0],f["msl"][1]
    wind=np.hypot(f["u"][2],f["v"][2])*3.6
    if np.nanmax(wind)>400:raise RuntimeError("Vent 10 m physiquement aberrant")
    rainnow=f["tp"][2]*mm_factor(f["tp"][4])
    rainprev=f["tp_prev"][2]*mm_factor(f["tp_prev"][4])
    snownow=f["sf"][2]*mm_factor(f["sf"][4])
    snowprev=f["sf_prev"][2]*mm_factor(f["sf_prev"][4])
    total=np.maximum(0,rainnow-rainprev)
    snow=np.maximum(0,snownow-snowprev)
    rain=np.maximum(0,total-snow)
    if not np.all(np.isfinite(wind)) or not np.all(np.isfinite(rain)) or not np.all(np.isfinite(snow)):
        raise RuntimeError("Données de risques non finies")
    box=(x>=FOCUS[0])&(x<=FOCUS[1])
    by=(y>=FOCUS[2])&(y<=FOCUS[3])
    region=np.ix_(by,box)
    vw=float(np.max(wind[region]))
    vr=float(np.max(rain[region]))
    vs=float(np.max(snow[region]))
    # 10m average speed != gust. Do not claim official storm warning from it.
    risks={k:{"status":"indisponible","reason":"Champs spécifiques non disponibles"} for k in CATEGORIES}
    risks["tempete"]={"status":status(vw,50,70),"max":round(vw,1),"unit":"km/h (vent moyen 10 m)",
                      "reason":"Signal de vent soutenu, pas une vigilance tempête"}
    risks["pluie_forte"]={"status":status(vr,10,20),"max":round(vr,1),"unit":"mm/6h",
                          "reason":"Cumul des 6 heures précédant l'échéance"}
    try:
        snow_markers,snow_info=snow_off_mountain(x,y,snow)
    except Exception as exc:
        # Never assume an altitude from model T850 or from approximate polygons.
        snow_markers=[]
        snow_info={"status":"indisponible","reason":"Filtre altitude indisponible : "+str(exc)[:155]}
    risks["neige"]=snow_info
    risks["inondation"]={"status":"indisponible",
                         "reason":"Crue non déductible d'un seul cumul de pluie de 6 h"}
    markers=(peaks(x,y,wind,50,"vent_fort",3) +
             peaks(x,y,rain,10,"pluie_forte",4) +
             snow_markers)
    # Adjacent pin collision is undesirable even across different phenomena.
    selected=[]
    for p in sorted(markers,key=lambda p:p["value"],reverse=True):
        if all(distance_km(p["lon"],p["lat"],q["lon"],q["lat"])>=125 for q in selected):
            selected.append(p)
    t850=t850_celsius(f["t850"][2],f["t850"][4])
    masses=air_masses(x,y,t850)
    fronts=[]
    if step<=168:
        previous=t850_celsius(f["t850_prev"][2],f["t850_prev"][4])
        fronts=frontal_candidates(x,y,t850,previous,rain,step)
    f["rain6h"]=(x,y,rain,recorded,"mm")
    background=render(id,recorded,f,selected,masses,fronts)
    return {"id":id,"step_h":step,"model":model,"run_utc":recorded,
            "valid_utc":(run+timedelta(hours=step)).isoformat(),
            "background_path":str(background),"risks":risks,"markers":selected,
            "air_masses":masses,"frontal_zones":fronts,
            "t850_shading":{"enabled":True,"level_hpa":850,"unit":"°C",
                            "fixed_scale_c":[-20,20],
                            "description":"Température à 850 hPa modélisée, pas température au sol"},
            "frontal_method":"Thermal gradient / 6h tendency / rain (experimental), only J+3/J+7",
            "risk_scope":"France et secteurs proches, domaine rectangulaire terre + mer",
            "method":"Vent moyen 10m, pluie/neige 6h ; neige hors relief selon altitudes GLO-90 ; pas une vigilance officielle."}

def main():
    now=datetime.now(timezone.utc)
    atlas=json.loads((EU/"metadata.json").read_text(encoding="utf-8"))
    records=[]
    for id,step,model in STAGES:
        records.append(calculate(id,step,model,atlas,now))
    output={"schema_version":1,"generated_utc":now.isoformat(),
            "atlas_generated_utc":atlas["generated_utc"],
            "reference":"ECMWF Open Data, Copernicus DEM GLO-90 via Open-Meteo — champs géoréférencés",
            "stages":records}
    (OUT/"tendance-risques.json").write_text(json.dumps(output,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print(json.dumps({"generated_utc":output["generated_utc"],
                      "stages":[{"id":r["id"],"risks":{k:v["status"] for k,v in r["risks"].items()},
                                 "markers":len(r["markers"])} for r in records]},ensure_ascii=False))
if __name__=="__main__":main()
