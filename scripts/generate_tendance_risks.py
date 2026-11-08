#!/usr/bin/env python3
"""KFS — analyse géoréférencée des signaux météo aux échéances /tendance.

Les seuils sont des repères graphiques, PAS une vigilance ni une prévision de crue.
La carte synoptique et les marqueurs sont produits avec les mêmes coordonnées
géographiques et les mêmes runs ECMWF vérifiés.
"""
from __future__ import annotations
import json
import math
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
COLORS={"vent_fort":"#FFD06B","tempete":"#F46C55","pluie_forte":"#39CAFF","neige":"#E9F7FF"}

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


def weather_pictogram(kind):
    """Vector pictograms (no letter glyphs or system emoji fonts).

    White pictogram on a risk-coloured circular pin:
    wind swirls, rainy cloud and snowflake.
    """
    area=DrawingArea(46,46,0,0)
    bg=COLORS[kind]
    area.add_artist(Circle((23,23),21,facecolor=bg,edgecolor="white",linewidth=2.2))
    ink="#092B49"
    if kind in ("vent_fort","tempete"):
        # Three curved air-stream lines, with trailing gust curls.
        for y,delta in ((31,2),(23,0),(15,-2)):
            verts=[(9,y),(16,y+3),(25,y+3),(30,y),
                   (35,y-3),(38,y-1),(37,y+3)]
            codes=[MplPath.MOVETO]+[MplPath.CURVE4]*6
            area.add_artist(PathPatch(MplPath(verts,codes),fill=False,
                        edgecolor=ink,linewidth=2.6,capstyle="round"))
        area.add_artist(Circle((12,13),2.2,facecolor=ink,edgecolor="none"))
    elif kind=="pluie_forte":
        # Stylised cloud with three rain streaks.
        area.add_artist(Circle((17,28),7.2,facecolor="white",edgecolor="none"))
        area.add_artist(Circle((25,32),9,facecolor="white",edgecolor="none"))
        area.add_artist(Circle((33,27),6.8,facecolor="white",edgecolor="none"))
        area.add_artist(FancyBboxPatch((12,24),25,8,boxstyle="round,pad=0,rounding_size=4",
                                       facecolor="white",edgecolor="none"))
        for x in (17,24,31):
            area.add_artist(Line2D([x+1,x-2],[19,12],linewidth=2.7,
                          color=ink,solid_capstyle="round"))
    elif kind=="neige":
        for angle in (0,60,120):
            a=math.radians(angle)
            dx,dy=13*math.cos(a),13*math.sin(a)
            area.add_artist(Line2D([23-dx,23+dx],[23-dy,23+dy],
                         color="white",linewidth=2.7,solid_capstyle="round"))
            # Two barbs at both ends of each snowflake arm.
            for sign in (-1,1):
                ex,ey=23+sign*dx,23+sign*dy
                ax0,ay0=-sign*math.cos(a),-sign*math.sin(a)
                px,py=-math.sin(a),math.cos(a)
                for side in (-1,1):
                    area.add_artist(Line2D([ex,ex+ax0*4+side*px*3],
                              [ey,ey+ay0*4+side*py*3],color="white",linewidth=1.7,
                              solid_capstyle="round"))
    return area

def render(id,run,fields,marks):
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
    cmap=plt.get_cmap("turbo")
    ax.contourf(xx,yy,geop,levels=np.arange(470,605,5),cmap=cmap,
                extend="both",transform=ccrs.PlateCarree())
    cs=ax.contour(xx,yy,pres,levels=np.arange(940,1061,5),
                  colors="white",linewidths=1.05,transform=ccrs.PlateCarree())
    labels=ax.clabel(cs,fmt="%d",inline=True,fontsize=8,colors="white")
    for a in labels:a.set_path_effects([pe.Stroke(linewidth=2.5,foreground="#173147"),pe.Normal()])
    ax.coastlines("110m",linewidth=.65,color="#10283C")
    ax.add_feature(cfeature.BORDERS,linewidth=.48,edgecolor="#122A43")
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
                               ("tp","tp","tp",None),("sf","sf","sf",None)):
        f[key]=single(client,model,step,run,param,var,lev)
    for key,param,var in (("tp_prev","tp","tp"),("sf_prev","sf","sf")):
        f[key]=single(client,model,step-6,run,param,var)
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
    risks["neige"]={"status":status(vs,0.5,2),"max":round(vs,1),"unit":"mm équivalent-eau/6h",
                    "reason":"Neige modélisée : pas une hauteur de neige au sol"}
    risks["inondation"]={"status":"indisponible",
                         "reason":"Crue non déductible d'un seul cumul de pluie de 6 h"}
    markers=(peaks(x,y,wind,50,"vent_fort",3) +
             peaks(x,y,rain,10,"pluie_forte",4) +
             peaks(x,y,snow,0.5,"neige",3))
    # Adjacent pin collision is undesirable even across different phenomena.
    selected=[]
    for p in sorted(markers,key=lambda p:p["value"],reverse=True):
        if all(distance_km(p["lon"],p["lat"],q["lon"],q["lat"])>=125 for q in selected):
            selected.append(p)
    background=render(id,recorded,f,selected)
    return {"id":id,"step_h":step,"model":model,"run_utc":recorded,
            "valid_utc":(run+timedelta(hours=step)).isoformat(),
            "background_path":str(background),"risks":risks,"markers":selected,
            "risk_scope":"France et secteurs proches, domaine rectangulaire terre + mer",
            "method":"Seuils indicatifs vent moyen 10m, pluie/neige 6h. Aucun diagnostic de vigilance."}

def main():
    now=datetime.now(timezone.utc)
    atlas=json.loads((EU/"metadata.json").read_text(encoding="utf-8"))
    records=[]
    for id,step,model in STAGES:
        records.append(calculate(id,step,model,atlas,now))
    output={"schema_version":1,"generated_utc":now.isoformat(),
            "atlas_generated_utc":atlas["generated_utc"],
            "reference":"ECMWF Open Data — champs bruts géoréférencés",
            "stages":records}
    (OUT/"tendance-risques.json").write_text(json.dumps(output,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print(json.dumps({"generated_utc":output["generated_utc"],
                      "stages":[{"id":r["id"],"risks":{k:v["status"] for k,v in r["risks"].items()},
                                 "markers":len(r["markers"])} for r in records]},ensure_ascii=False))
if __name__=="__main__":main()
