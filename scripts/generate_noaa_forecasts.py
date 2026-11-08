#!/usr/bin/env python3
"""KFS NOAA: split T850 and Z500+MSLP, using real GFS/AIGFS GRIB fields."""
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import cartopy.crs as ccrs
import cartopy.feature as cf
from herbie import Herbie

OUT=Path("forecast-maps/europe")
OUT.mkdir(parents=True,exist_ok=True)
STEPS=[24,48,72,120,168,240,360]
# Attendre environ 5 h après le cycle pour disposer des champs longue échéance GFS/AIGFS.
now=datetime.now(timezone.utc)-timedelta(hours=5)
RUN=now.replace(hour=(now.hour//6)*6,minute=0,second=0,microsecond=0)
metadata={"generated_utc":datetime.now(timezone.utc).isoformat(),"run_utc":RUN.isoformat(),"runs_utc":{"gfs":{},"aigfs":{}},
          "source":"NOAA NCEP NOMADS","maps":{},"errors":{}}

def subset(dataset):
    names=list(dataset.data_vars)
    if len(names)!=1: raise ValueError("Expected one parameter, found "+str(names))
    da=dataset[names[0]].squeeze()
    lat=np.asarray(da.latitude.values)
    lon=(np.asarray(da.longitude.values)+180)%360-180
    if lat.ndim!=1 or lon.ndim!=1: raise ValueError("Non regular latitude/longitude grid")
    iy=np.where((lat>=28)&(lat<=87))[0]
    ix=np.where((lon>=-67)&(lon<=42))[0]
    ix=ix[np.argsort(lon[ix])]
    return lon[ix],lat[iy],da.values[np.ix_(iy,ix)],str(da.attrs.get("units",""))

def field(model,step,product,pattern):
    h=Herbie(RUN.replace(tzinfo=None),model=model,product=product,fxx=step,verbose=False)
    ds=h.xarray(pattern,remove_grib=True)
    if ds is None: raise RuntimeError("No NOAA field "+pattern)
    return subset(ds)

def canvas():
    fig=plt.figure(figsize=(14,9),dpi=155)
    ax=fig.add_subplot(111,projection=ccrs.PlateCarree())
    ax.set_extent([-65,40,30,85],crs=ccrs.PlateCarree())
    ax.add_feature(cf.LAND,facecolor="#f0f0f0")
    ax.add_feature(cf.OCEAN,facecolor="#dceaf3")
    ax.coastlines("110m",linewidth=.7)
    ax.add_feature(cf.BORDERS,linewidth=.4)
    return fig,ax

def save(fig,model,step,param):
    filename=f"{model}-h{step:03}-{param}.png"
    fig.savefig(OUT/filename,bbox_inches="tight",facecolor="white")
    plt.close(fig)
    metadata["maps"].setdefault(model,{}).setdefault(str(step),{})[param]="forecast-maps/europe/"+filename

for model,title in [("gfs","GFS"),("aigfs","AIGFS")]:
    for step in STEPS:
        key=f"{model}-h{step:03}"
        metadata["runs_utc"][model][str(step)]=RUN.isoformat()
        pressure_product="pgrb2.0p25" if model=="gfs" else "sfc"
        upper_product="pgrb2.0p25" if model=="gfs" else "pres"
        try:
            lon,lat,t850,u=field(model,step,upper_product,":TMP:850 mb:")
            if not 150<np.nanmedian(t850)<330:raise ValueError("T850 values not Kelvin: "+u)
            fig,ax=canvas()
            shade=ax.contourf(lon,lat,t850-273.15,levels=np.arange(-36,38,2),
                              cmap="RdYlBu_r",extend="both",transform=ccrs.PlateCarree())
            fig.colorbar(shade,ax=ax,orientation="horizontal",pad=.04,shrink=.8,label="Température à 850 hPa (°C)")
            ax.set_title(f"KFS MÉTÉO | {title} | Atlantique Nord · Groenland · Europe | +{step} h\nTempérature 850 hPa · Run : {RUN.strftime('%d/%m %H:%M')} UTC · Validité : {(RUN+timedelta(hours=step)).strftime('%d/%m %H:%M')} UTC")
            save(fig,model,step,"t850")
        except Exception as e:
            metadata["errors"][key+"-t850"]=str(e)[:350]
        try:
            lon,lat,msl,u=field(model,step,pressure_product,":PRMSL:mean sea level:")
            x,y,z500,zunits=field(model,step,upper_product,":HGT:500 mb:")
            if not (np.array_equal(lon,x) and np.array_equal(lat,y)):
                raise ValueError("Z500 and MSLP grids differ")
            if not 90000<np.nanmedian(msl)<110000: raise ValueError("MSLP invalid: "+u)
            if not 4000<np.nanmedian(z500)<6500: raise ValueError("Z500 invalid: "+zunits)
            fig,ax=canvas()
            shade=ax.contourf(lon,lat,z500/10,levels=np.arange(460,625,4),
                              cmap="Spectral_r",extend="both",transform=ccrs.PlateCarree())
            heights=ax.contour(lon,lat,z500/10,levels=np.arange(460,625,8),
                               colors="#322f41",linewidths=.8,transform=ccrs.PlateCarree())
            ax.clabel(heights,inline=True,fmt="%d",fontsize=7)
            lines=ax.contour(lon,lat,msl/100,levels=np.arange(940,1061,4),
                             colors="#1b547b",linestyles="dashed",linewidths=.8,transform=ccrs.PlateCarree())
            ax.clabel(lines,inline=True,fmt="%d",fontsize=7)
            fig.colorbar(shade,ax=ax,orientation="horizontal",pad=.04,shrink=.8,label="Géopotentiel 500 hPa (dam)")
            ax.set_title(f"KFS MÉTÉO | {title} | Atlantique Nord · Groenland · Europe | +{step} h\nZ500 (dam) et pression au sol (hPa) · Run : {RUN.strftime('%d/%m %H:%M')} UTC · Validité : {(RUN+timedelta(hours=step)).strftime('%d/%m %H:%M')} UTC")
            save(fig,model,step,"z500_msl")
        except Exception as e:
            metadata["errors"][key+"-z500_msl"]=str(e)[:350]

        # Vent a 10 m : U/V instantanes, vitesse en km/h.
        try:
            lon,lat,uw,_=field(model,step,pressure_product,":UGRD:10 m above ground:")
            x,y,vw,_=field(model,step,pressure_product,":VGRD:10 m above ground:")
            if not (np.array_equal(lon,x) and np.array_equal(lat,y)):
                raise ValueError("Grilles U/V incompatibles")
            if np.nanmax(np.abs(uw))>180 or np.nanmax(np.abs(vw))>180:
                raise ValueError("Valeurs de vent hors limites")
            speed=np.hypot(uw,vw)*3.6
            fig,ax=canvas()
            shade=ax.contourf(lon,lat,speed,levels=[0,10,20,30,40,50,60,75,90,110,130,160,200],
                              cmap="turbo",extend="max",transform=ccrs.PlateCarree())
            xx,yy=np.meshgrid(lon,lat)
            skip=(slice(None,None,max(1,len(lat)//22)),slice(None,None,max(1,len(lon)//26)))
            ax.quiver(xx[skip],yy[skip],uw[skip],vw[skip],color="#233245",alpha=.78,
                      scale=680,width=.0016,transform=ccrs.PlateCarree())
            fig.colorbar(shade,ax=ax,orientation="horizontal",pad=.04,shrink=.8,
                         label="Vitesse du vent à 10 m (km/h) — flèches : direction")
            ax.set_title(f"KFS MÉTÉO | {title} | Atlantique Nord · Groenland · Europe | +{step} h\nVent à 10 m · Run : {RUN.strftime('%d/%m %H:%M')} UTC · Validité : {(RUN+timedelta(hours=step)).strftime('%d/%m %H:%M')} UTC")
            save(fig,model,step,"wind10m")
        except Exception as e:
            metadata["errors"][key+"-wind10m"]=str(e)[:350]

        # Precipitations totales des 6 h precedentes en mm d'eau.
        # Le produit AIGFS ne distingue pas la pluie et la neige ; ne pas inventer une partition.
        try:
            accumulation=f":APCP:surface:{step-6}-{step} hour acc:"
            lon,lat,total,units=field(model,step,pressure_product,accumulation)
            if np.nanmin(total)<-1 or np.nanmax(total)>1500:
                raise ValueError("Cumuls de précipitation inattendus : "+units)
            total=np.maximum(0,total)
            fig,ax=canvas()
            shade=ax.contourf(lon,lat,total,levels=[0,.1,.5,1,2,5,10,15,20,30,40,60,80],
                              cmap="Blues",extend="max",transform=ccrs.PlateCarree())
            fig.colorbar(shade,ax=ax,orientation="horizontal",pad=.04,shrink=.8,
                         label="Précipitations totales (pluie + neige, mm équivalent-eau / 6 h)")
            ax.set_title(f"KFS MÉTÉO | {title} | Atlantique Nord · Groenland · Europe | +{step} h\nPrécipitations totales 6 h (pluie/neige non séparables)\nRun : {RUN.strftime('%d/%m %H:%M')} UTC · Période : +{step-6} à +{step} h")
            save(fig,model,step,"precip6h")
        except Exception as e:
            metadata["errors"][key+"-precip6h"]=str(e)[:350]
(OUT/"noaa-metadata.json").write_text(json.dumps(metadata,ensure_ascii=False,indent=2),encoding="utf-8")
print("NOAA summary",json.dumps({"maps":metadata["maps"],"errors":metadata["errors"]},ensure_ascii=False),flush=True)
if not metadata["maps"]:raise RuntimeError("No genuine GFS/AIGFS fields, publication aborted")
