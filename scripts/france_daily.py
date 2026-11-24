#!/usr/bin/env python3
"""Cartes KFS France par jour civil (Europe/Paris), issues de champs GRIB natifs.

Les températures sont les extrema des échéances disponibles (3 ou 6 heures) :
ce ne sont pas des extrêmes sub-horaires. Les cumuls franchissant minuit
sont répartis au prorata du temps, donc approximatifs sur cette frontière.
Une journée partiellement couverte est explicitement signalée.
"""
from __future__ import annotations
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo
import numpy as np
import matplotlib.pyplot as plt
import matplotlib.patheffects as pe
from matplotlib.colors import BoundaryNorm, ListedColormap
from matplotlib import colormaps
import cartopy.crs as ccrs
import cartopy.feature as cf
from cartopy.mpl.path import shapely_to_path
from kfs_surface_style import france_axes, mainland, TEMP_CMAP, TEMP_MIN, TEMP_MAX, symbols
from shapely import contains_xy

PARIS=ZoneInfo("Europe/Paris")
EXTENT=(-6.6,10.3,41.0,51.7)
CITIES=[
 (-4.49,48.38,"Brest"),(-1.55,47.22,"Nantes"),(-0.58,44.84,"Bordeaux"),
 (1.44,43.60,"Toulouse"),(2.35,48.86,"Paris"),(3.06,50.63,"Lille"),
 (1.10,49.44,"Rouen"),(1.26,45.83,"Limoges"),(3.09,45.78,"Clermont"),
 (4.84,45.76,"Lyon"),(5.37,43.30,"Marseille"),(3.88,43.61,"Montpellier"),
 (7.75,48.58,"Strasbourg"),(5.04,47.32,"Dijon"),(7.26,43.71,"Nice"),
 (-2.76,48.51,"Saint-Brieuc"),(-1.09,49.12,"Saint-Lô"),(.10,47.99,"Le Mans"),
 (-.46,46.32,"Niort"),(-.37,43.30,"Pau"),(1.81,44.35,"Cahors"),
 (3.13,46.99,"Nevers"),(4.03,49.26,"Reims"),(6.18,48.69,"Nancy"),
 (6.15,45.9,"Annecy"),(2.89,42.70,"Perpignan"),(8.74,41.92,"Ajaccio")]
LABELS={
 "tmin":"Températures minimales (°C)",
 "tmax":"Températures maximales (°C)",
 "gust":"Rafales maximales (km/h)",
 "precip":"Précipitations totales (mm)",
 "rain":"Pluie seule (mm)"
}
RAIN_LEVELS=(.1,.3,.6,1,2,3,5,8,12,18,25,40,60)
RAIN_COLORS=("#C0EAF9","#79CFFF","#339DE8","#276CCA","#3249A8",
 "#289990","#46BD50","#A5DE32","#F6E042","#F4AE39","#E86933","#D72F51")
GUST_LEVELS=(0,10,20,30,40,50,65,80,95,110,130,155,185)
GUST_COLORS=("#d9effb","#a4d6f3","#69bce3","#4c9ac9","#4eaf9e",
 "#80c36f","#e8db64","#f5b752","#f18b45","#dc564d","#b63b7c","#7e2f76")

def iso(dt):
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

def render_daily(lon,lat,values,metric,model,run,day,folder,note,peaks=None,weather=None,detail=None):
    if metric in ("tmin","tmax"):
        levels=np.linspace(TEMP_MIN,TEMP_MAX,113); cmap=TEMP_CMAP; norm=None
    elif metric=="gust":
        levels=GUST_LEVELS;cmap=ListedColormap(GUST_COLORS);norm=BoundaryNorm(levels,cmap.N)
    else:
        levels=RAIN_LEVELS;cmap=ListedColormap(RAIN_COLORS);norm=BoundaryNorm(levels,cmap.N)
    fig=plt.figure(figsize=(10,10),dpi=115,facecolor="#09233e")
    ax=france_axes(fig)
    ax.add_feature(cf.LAND,facecolor="#EDF0EC",zorder=0)
    ax.add_feature(cf.OCEAN,facecolor="#173e5d",zorder=0)
    arr=np.asarray(values,dtype=float)
    invalid=np.isnan(arr) if metric=="rain" else None
    if metric in ("precip","rain"):
        arr=np.ma.masked_less(np.ma.masked_invalid(arr),.1)
    kwargs={"cmap":cmap,"extend":"both","transform":ccrs.PlateCarree()}
    if norm is not None: kwargs["norm"]=norm
    if invalid is not None and invalid.any():
        grey=np.ma.masked_where(~invalid,np.ones_like(invalid,dtype=float))
        ax.contourf(lon,lat,grey,levels=[.5,1.5],colors=["#8F949C"],
                    alpha=.74,transform=ccrs.PlateCarree(),zorder=1)
    shade=ax.contourf(lon,lat,arr,levels=levels,**kwargs)
    clip=shapely_to_path(ax.projection.project_geometry(mainland(),ccrs.PlateCarree()))
    if hasattr(shade,"set_clip_path"):
        shade.set_clip_path(clip,ax.transData)
    else:
        for collection in shade.collections: collection.set_clip_path(clip,ax.transData)
    ix=np.asarray(lon,dtype=float);iy=np.asarray(lat,dtype=float)
    ax.apply_aspect()
    used=[]
    for x,y,city in CITIES:
        xy=ax.projection.transform_point(x,y,ccrs.PlateCarree())
        px=ax.transData.transform(xy)
        if any(np.linalg.norm(px-q)<(45 if metric in ("tmin","tmax") else 58) for q in used): continue
        i=int(np.abs(ix-x).argmin());j=int(np.abs(iy-y).argmin())
        v=np.asarray(values)[j,i]
        if not np.isfinite(v) or metric in ("precip","rain") and v<.1:
            continue
        label=(f"{v:+.0f}°" if metric in ("tmin","tmax") else
               f"{v:.0f}" if metric=="gust" else f"{v:.1f}")
        if metric=="gust" and peaks is not None:
            instant=peaks[j,i]
            if instant is not None: label+="\n"+instant
        used.append(px)
        t=ax.text(x,y,label,fontsize=7.3 if metric=="gust" else 9,
            ha="center",va="center",weight="bold",color="#1D2431",
            transform=ccrs.PlateCarree(),zorder=8)
        t.set_path_effects([pe.Stroke(linewidth=2.5,foreground="white"),pe.Normal()])
    if metric in ("tmin","tmax") and weather is not None:
        gx,gy=np.meshgrid(ix,iy)
        mask=contains_xy(mainland(),gx,gy)&np.isfinite(weather)
        coords=list(zip(gy[mask].tolist(),gx[mask].tolist()))
        codes=weather[mask].astype(int).tolist()
        count=symbols(ax,coords,codes,used,max_icons=9) if coords else 0
        print("KFS_NATIVE_WEATHER_ICONS",model,day,metric,count,flush=True)
    ax.coastlines("10m",linewidth=.7,color="#182A3E",zorder=5)
    ax.add_feature(cf.BORDERS,linewidth=.6,edgecolor="#172A3B",zorder=5)
    ax.set_title("KFS MÉTÉO · FRANCE · "+model+
        " · RUN "+run.strftime("%HZ du %d/%m/%Y")+" (UTC)"+
        "\n"+LABELS[metric]+" · "+day.strftime("%A %d/%m/%Y").capitalize(),
        fontsize=12,weight="bold",pad=11,color="white")
    cb=fig.colorbar(shade,cax=fig.add_axes([.17,.105,.66,.022]),orientation="horizontal")
    cb.ax.tick_params(colors="white")
    cb.set_label(LABELS[metric],fontsize=9,color="white")
    fig.text(.04,.025,"RUN "+run.strftime("%HZ du %d/%m/%Y")+
             " · cycle à "+run.astimezone(PARIS).strftime("%Hh%M")+" en France · "+
             note,fontsize=7.1,color="white",wrap=True)
    path=Path(folder)/f"daily-{metric}-d{(day-run.astimezone(PARIS).date()).days}.png"
    if detail is not None:
        from kfs_zoom_detail import geometry
        detail['geometry']=geometry(ax)
    fig.savefig(path,dpi=115,facecolor=fig.get_facecolor())
    plt.close(fig)
    return str(path)

def daily_weather(selected,lon,lat,run,stride,begin,end):
    # Diagnostic, not a native WMO weather code. All fields must be from the same run.
    by_field={}
    for key in ("cloud","rain","snow"):
        arrays=[]
        for step,data in selected:
            f=data.get(key)
            if f is None or not np.array_equal(lon,f[0]) or not np.array_equal(lat,f[1]):
                return None
            a,b=run+timedelta(hours=step-stride),run+timedelta(hours=step)
            weight=max(0,(min(b,end)-max(a,begin)).total_seconds())/(stride*3600)
            arrays.append((np.asarray(f[2],dtype=float),weight))
        if not arrays:return None
        weight_sum=sum(w for v,w in arrays)
        if not weight_sum:return None
        total=sum(v*w for v,w in arrays)
        by_field[key]=total/weight_sum if key=="cloud" else total
    cloud,rain,snow=(by_field[k] for k in ("cloud","rain","snow"))
    valid=np.isfinite(cloud)&np.isfinite(rain)&np.isfinite(snow)
    code=np.where(cloud<.25,0,np.where(cloud<.75,2,3)).astype(float)
    code=np.where(rain>=.5,61,code)
    code=np.where((snow>=.2)&(snow>=rain),71,code)
    return np.where(valid,code,np.nan)

def make_daily(run,stride,steps,samples,model,folder):
    """Create maps for J0..J3. Never call a partial calendar day complete."""
    result={}
    start_local=run.astimezone(PARIS).date()
    final=run+timedelta(hours=max(steps))
    names={"ifs":"ECMWF IFS","gfs":"NOAA GFS",
           "aifs-single":"ECMWF AIFS","aigfs":"NOAA AIGFS"}
    for d in range(4):
        day=start_local+timedelta(days=d)
        left=datetime(day.year,day.month,day.day,tzinfo=PARIS).astimezone(timezone.utc)
        tomorrow=day+timedelta(days=1)
        right=datetime(tomorrow.year,tomorrow.month,tomorrow.day,tzinfo=PARIS).astimezone(timezone.utc)
        from_utc=max(left,run)
        until_utc=min(right,final)
        hours=(until_utc-from_utc).total_seconds()/3600
        if hours<12: continue
        coverage="complete" if from_utc==left and until_utc==right else "partial"
        selected=[(step,data) for step,data in samples
            if run+timedelta(hours=step)>from_utc and
               run+timedelta(hours=step-stride)<until_utc]
        if not selected: continue
        maps={}
        for metric,source in (("tmin","t2m"),("tmax","t2m"),
                              ("gust","gust"),("precip","precip_total"),
                              ("rain","rain")):
            relevant=[]
            complete=True
            for step,data in selected:
                field=data.get(source)
                if field is None: complete=False;break
                a=run+timedelta(hours=step-stride)
                b=run+timedelta(hours=step)
                overlap=max(0,(min(b,until_utc)-max(a,from_utc)).total_seconds())
                if overlap<=0:continue
                relevant.append((step,field,overlap/(stride*3600),a,b))
            if not complete or not relevant:continue
            grid0=relevant[0][1]
            lon,lat=grid0[0],grid0[1]
            if any(not(np.array_equal(lon,x[1][0]) and np.array_equal(lat,x[1][1]))
                   for x in relevant[1:]):continue
            vals=[np.asarray(x[1][2],dtype=float) for x in relevant]
            if any(v.shape!=vals[0].shape for v in vals):continue
            if metric=="tmin":
                values=np.minimum.reduce(vals)
            elif metric in ("tmax","gust"):
                values=np.maximum.reduce(vals)
            else:
                invalid=np.logical_or.reduce([~np.isfinite(x) for x in vals])
                values=sum(v*w for v,entry,w,a,b in
                    [(np.nan_to_num(x[1][2],nan=0),x[1],x[2],x[3],x[4]) for x in relevant])
                values=np.where(invalid,np.nan,values)
            if np.isfinite(values).mean()<.2:continue
            peak_labels=None
            if metric=="gust":
                peak_labels=np.empty(vals[0].shape,dtype=object)
                peak_labels[:]=None
                idx=np.argmax(np.asarray(vals),axis=0)
                for n,(step,_,weight,a,b) in enumerate(relevant):
                    mask=idx==n
                    at=b.astimezone(PARIS)
                    # Time of the native sample/interval ending at this hour.
                    peak_labels[mask]=at.strftime("%H h")
            note=("Période incomplète : "+from_utc.astimezone(PARIS).strftime("%d/%m %Hh")+
                  " à "+until_utc.astimezone(PARIS).strftime("%d/%m %Hh")
                  if coverage=="partial" else "Journée civile 00h–24h (heure française)")
            if metric in ("tmin","tmax"):
                note+=" · extrêmes calculés sur les pas du modèle"
            if metric in ("precip","rain"):
                note+=" · répartition approximative aux limites des pas GRIB"
            if metric=="gust":
                note+=" · heures de fin de créneau, pas heure exacte du pic"
            if metric=="rain" and model=="gfs":
                note+=" · phase pluie/neige estimée par GFS"
            weather=None
            if metric in ("tmin","tmax"):
                weather=daily_weather(selected,lon,lat,run,stride,from_utc,until_utc)
                if weather is not None:
                    note+=" · pictos indicatifs (nuages, pluie, neige du modèle)"
            try:
                from kfs_zoom_detail import native
                detail=native(lon,lat,values) if metric in ("tmin","tmax") else None
                path=render_daily(lon,lat,values,metric,names[model],run,day,
                                  folder,note,peak_labels,weather,detail=detail)
                maps[metric]={"path":path,"note":note,**({"detail":detail} if detail is not None else {})}
            except Exception as exc:
                print("DAILY_DRAW_ERROR",model,d,metric,str(exc),flush=True)
        if maps:
            result[str(d)]={"date":day.isoformat(),"coverage":coverage,
                "start_utc":iso(from_utc),"end_utc":iso(until_utc),
                "maps":maps}
    return result
