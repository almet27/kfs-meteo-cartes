#!/usr/bin/env python3
"""KFS Europe: separate 850 hPa temperature and 500 hPa heights / sea-level pressure."""
import json
from datetime import datetime, timezone, timedelta
from pathlib import Path
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.colors import ListedColormap, BoundaryNorm
from kfs_premium_palettes import KFS_Z500_CMAP, KFS_Z500_NORM, KFS_T850_CMAP, KFS_T850_NORM
import numpy as np
import cartopy.crs as ccrs
import cartopy.feature as cf
import xarray as xr
from ecmwf.opendata import Client

OUT = Path("forecast-maps/europe")
OUT.mkdir(parents=True, exist_ok=True)
STEPS = [24, 48, 72, 120, 168, 240, 360]
MODELS = {"ifs": "ECMWF IFS", "aifs-single": "ECMWF AIFS"}
EXTENT = [-65, 40, 30, 85]  # Atlantique Nord, Groenland et Europe
result = {"generated_utc": datetime.now(timezone.utc).isoformat(),
          "source": "ECMWF Open Data (CC BY 4.0)", "maps": {}, "runs_utc": {}, "errors": {}}

def read(path, name):
    ds = xr.open_dataset(path, engine="cfgrib", backend_kwargs={"indexpath": ""})
    try:
        a = ds[name].squeeze().load()
        lat = np.asarray(a.latitude.values)
        lon = ((np.asarray(a.longitude.values)+180)%360)-180
        iy = np.where((lat>=28)&(lat<=87))[0]
        ix = np.where((lon>=-67)&(lon<=42))[0]
        ix = ix[np.argsort(lon[ix])]
        return lon[ix], lat[iy], a.values[np.ix_(iy,ix)], str(a.attrs.get("units", "")), np.datetime_as_string(np.asarray(a.time.values),unit="m")+"Z"
    finally:
        ds.close()

def canvas():
    fig = plt.figure(figsize=(14,9), dpi=155)
    ax = fig.add_subplot(111, projection=ccrs.PlateCarree())
    ax.set_extent(EXTENT, crs=ccrs.PlateCarree())
    ax.add_feature(cf.LAND, facecolor="#f0f0f0")
    ax.add_feature(cf.OCEAN, facecolor="#dceaf3")
    ax.coastlines("110m", linewidth=.7)
    ax.add_feature(cf.BORDERS, linewidth=.4)
    return fig, ax

def save_map(fig, model, step, field):
    filename=f"{model}-h{step:03}-{field}.png"
    fig.savefig(OUT/filename, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    result["maps"].setdefault(model, {}).setdefault(str(step), {})[field] = "forecast-maps/europe/"+filename


# Palette contraste : pas de couleur sur les cellules seches (<0.1 mm).
# Seuils communs rain/snow ; couleurs specifiques a chaque hydrometeore.
PRECIP_LEVELS = [0.1,0.25,0.5,1,2,3,5,8,12,20,30,45,65,90]
RAIN_COLORS = ["#91e0ff","#55c5ff","#1b95ed","#1164cb","#143ba6","#167e91",
               "#23b85a","#85d232","#e0df23","#f6b12e","#ef772a","#da3740",
               "#a72564","#6e155b"]
SNOW_COLORS = ["#a7f0ff","#6fdcff","#3db7fb","#1e81ed","#2659cc","#5338bd",
               "#7744cd","#9950e1","#b44ede","#c73bb5","#d21a84","#a60c77",
               "#7b0c71","#500557"]

def render_precip(x,y,data,model,title,step,run_utc,kind,filename):
    cmap=ListedColormap(RAIN_COLORS if kind in ("rain","total") else SNOW_COLORS)
    norm=BoundaryNorm(PRECIP_LEVELS,cmap.N,extend="max")
    fig,ax=canvas()
    display=np.ma.masked_where(~np.isfinite(data)|(data<0.1),data)
    shade=ax.pcolormesh(x,y,display,cmap=cmap,norm=norm,shading="auto",
                        transform=ccrs.PlateCarree(),rasterized=True)
    labels={"rain":"Pluie (neige déduite du cumul total)",
            "snow":"Neige (équivalent-eau, PAS une épaisseur au sol)",
            "total":"Pluie + neige (cumul total)"}
    fig.colorbar(shade,ax=ax,orientation="horizontal",pad=.04,shrink=.8,
                 extend="max",ticks=[.1,.5,1,2,5,12,30,65],
                 label=labels[kind]+" — mm / 6 h")
    if kind=="snow":
        note="La carte indique les mm d'équivalent-eau, pas des cm de neige."
    elif kind=="rain":
        note="Cumul liquide estimé = précipitations totales - équivalent-eau neige."
    else:
        note="Cumul total, incluant pluie et neige."
    ax.set_title(f"KFS MÉTÉO | {title} | Atlantique Nord · Groenland · Europe | +{step} h\n"
                 f"{labels[kind]} | période +{step-6} à +{step} h\n"
                 f"Run : {run_utc[:16].replace('T',' ')} UTC · {note}")
    save_map(fig,model,step,filename)

for model, title in MODELS.items():
    client=Client(source="ecmwf",model=model,resol="0p25")
    for step in STEPS:
        if model=="ifs" and step>240:
            continue
        key=f"{model}-h{step:03}"
        temp_path=OUT/(key+"-t850.grib2")
        pres_path=OUT/(key+"-msl.grib2")
        height_path=OUT/(key+"-gh500.grib2")
        try:
            # Temperature at 850 hPa alone, no MSLP overlay.
            client.retrieve(stream="oper",type="fc",step=step,param="t",levelist=850,target=str(temp_path))
            x,y,temp,units,run_utc=read(temp_path,"t")
            result["runs_utc"].setdefault(model,{})[str(step)] = run_utc
            if np.nanmedian(temp)<150: raise ValueError("Unexpected 850 hPa temperature units: "+units)
            fig,ax=canvas()
            shade=ax.contourf(x,y,temp-273.15,levels=np.arange(-36,38,2),
                cmap=KFS_T850_CMAP,norm=KFS_T850_NORM,
                              extend="both",transform=ccrs.PlateCarree())
            fig.colorbar(shade,ax=ax,orientation="horizontal",pad=.04,shrink=.8,ticks=[-24,-16,-8,0,8,16,24],
                         label="Température à 850 hPa (°C) · Palette KFS premium")
            ax.set_title(f"KFS MÉTÉO | {title} | Atlantique Nord · Groenland · Europe | +{step} h\nTempérature 850 hPa · Run : {run_utc[:16].replace('T', ' ')} UTC · Validité : {(datetime.fromisoformat(run_utc.replace('Z','+00:00'))+timedelta(hours=step)).strftime('%d/%m %H:%M')} UTC")
            save_map(fig,model,step,"t850")
        except Exception as exc:
            result["errors"][key+"-t850"]=str(exc)[:350]
        try:
            # Real 500 hPa geopotential height (not 500 hPa temperature).
            client.retrieve(stream="oper",type="fc",step=step,param="msl",target=str(pres_path))
            client.retrieve(stream="oper",type="fc",step=step,param="gh",levelist=500,target=str(height_path))
            x,y,msl,_,run_utc=read(pres_path,"msl")
            result["runs_utc"].setdefault(model,{})[str(step)] = run_utc
            x2,y2,gh,units,_=read(height_path,"gh")
            if not (np.array_equal(x,x2) and np.array_equal(y,y2)):
                raise ValueError("500 hPa and MSLP grids differ")
            # ECMWF 'gh' is geopotential height, in metres (convert to decametres).
            if not 4000 < np.nanmedian(gh) < 6500:
                raise ValueError("Unexpected geopotential height values/units: "+units)
            if not 90000 < np.nanmedian(msl) < 110000:
                raise ValueError("Unexpected MSL pressure values")
            fig,ax=canvas()
            shade=ax.contourf(x,y,gh/10,levels=np.arange(460,625,4),
                cmap=KFS_Z500_CMAP,norm=KFS_Z500_NORM,
                              extend="both",transform=ccrs.PlateCarree())
            heights=ax.contour(x,y,gh/10,levels=np.arange(460,625,8),
                colors="#322f41",linewidths=.8,transform=ccrs.PlateCarree())
            ax.clabel(heights,inline=True,fontsize=7,fmt="%d")
            lines=ax.contour(x,y,msl/100,levels=np.arange(940,1061,4),
                colors="#1b547b",linewidths=.8,linestyles="dashed",transform=ccrs.PlateCarree())
            ax.clabel(lines,inline=True,fontsize=7,fmt="%d")
            fig.colorbar(shade,ax=ax,orientation="horizontal",pad=.04,shrink=.8,ticks=[500,520,540,560,580,600],
                         label="Hauteur géopotentielle Z500 (dam) · Palette KFS premium")
            ax.set_title(f"KFS MÉTÉO | {title} | Atlantique Nord · Groenland · Europe | +{step} h\nZ500 (dam) et pression au sol (hPa) · Run : {run_utc[:16].replace('T', ' ')} UTC · Validité : {(datetime.fromisoformat(run_utc.replace('Z','+00:00'))+timedelta(hours=step)).strftime('%d/%m %H:%M')} UTC")
            save_map(fig,model,step,"z500_msl")
        except Exception as exc:
            result["errors"][key+"-z500_msl"]=str(exc)[:350]
        finally:
            for p in (temp_path,pres_path,height_path):
                p.unlink(missing_ok=True)

        # Vent moyen à 10 m : norme des composantes U/V, convertie de m/s en km/h.
        wind_path=OUT/(key+"-wind10m.grib2")
        try:
            client.retrieve(stream="oper",type="fc",step=step,param=["10u","10v"],target=str(wind_path))
            x,y,u,uu,run_u=read(wind_path,"u10")
            x2,y2,v,uv,run_v=read(wind_path,"v10")
            if not (np.array_equal(x,x2) and np.array_equal(y,y2) and run_u==run_v):
                raise ValueError("Incoherence des champs de vent U/V")
            if np.nanmax(np.abs(u))>180 or np.nanmax(np.abs(v))>180:
                raise ValueError("Vent 10 m hors limites physiques")
            kmh=np.hypot(u,v)*3.6
            fig,ax=canvas()
            shade=ax.contourf(x,y,kmh,levels=[0,10,20,30,40,50,60,75,90,110,130,160,200],
                              cmap="turbo",extend="max",transform=ccrs.PlateCarree())
            xx,yy=np.meshgrid(x,y)
            skip=(slice(None,None,max(1,len(y)//22)),slice(None,None,max(1,len(x)//26)))
            ax.quiver(xx[skip],yy[skip],u[skip],v[skip],color="#233245",alpha=.78,
                      scale=680,width=.0016,transform=ccrs.PlateCarree())
            fig.colorbar(shade,ax=ax,orientation="horizontal",pad=.04,shrink=.8,
                         label="Vitesse du vent à 10 m (km/h) — flèches : direction")
            ax.set_title(f"KFS MÉTÉO | {title} | Atlantique Nord · Groenland · Europe | +{step} h\nVent 10 m · Run : {run_u[:16].replace('T',' ')} UTC · Validité : {(datetime.fromisoformat(run_u.replace('Z','+00:00'))+timedelta(hours=step)).strftime('%d/%m %H:%M')} UTC")
            save_map(fig,model,step,"wind10m")
        except Exception as exc:
            result["errors"][key+"-wind10m"]=str(exc)[:350]
        finally:
            wind_path.unlink(missing_ok=True)

        # Cumuls EXACTS des 6 h precedentes : differences tp/sf au sein du meme run.
        # L'unite ECMWF est le metre d'eau equivalent; 1 mm = 1 kg/m2.
        wet_now=OUT/(key+"-wet6h-now.grib2")
        wet_prev=OUT/(key+"-wet6h-prev.grib2")
        try:
            client.retrieve(stream="oper",type="fc",step=step,param=["tp","sf"],target=str(wet_now))
            client.retrieve(stream="oper",type="fc",step=step-6,param=["tp","sf"],target=str(wet_prev))
            x,y,tp_now,tp_units,run_now=read(wet_now,"tp")
            x2,y2,sf_now,sf_units,run_sf=read(wet_now,"sf")
            x3,y3,tp_prev,_,run_prev=read(wet_prev,"tp")
            x4,y4,sf_prev,_,run_prev_sf=read(wet_prev,"sf")
            if not (np.array_equal(x,x2) and np.array_equal(x,x3) and np.array_equal(x,x4)
                    and np.array_equal(y,y2) and np.array_equal(y,y3) and np.array_equal(y,y4)
                    and run_now==run_sf==run_prev==run_prev_sf):
                raise ValueError("Runs / grilles differents : cumul 6 h impossible")
            # Selon le flux GRIB, cfgrib peut exposer m ou kg/m2 (equiv. mm).
            def to_mm(units):
                u=units.lower().replace(" ","").replace("**","^").replace("−","-")
                if u in ("m","metre","meter","mofwaterequivalent","mofwaterequivalent(s)"): return 1000.0
                if u in ("kgm^-2","kg/m^2","kgm-2","mm","kgm^(-2)"): return 1.0
                raise ValueError("Unité GRIB non reconnue : "+repr(units))
            tp_factor=to_mm(tp_units)
            sf_factor=to_mm(sf_units)
            result.setdefault("precip_units",{}).setdefault(model,{})[str(step)]={"tp":tp_units,"sf":sf_units}
            total=np.maximum(0,(tp_now-tp_prev)*tp_factor)
            neige=np.minimum(total,np.maximum(0,(sf_now-sf_prev)*sf_factor))
            pluie=np.maximum(0,total-neige)
            # Trois sorties. Rain/snow sont DISTINCTES, seule la carte total conserve tout.
            render_precip(x,y,pluie,model,title,step,run_now,"rain","rain6h")
            render_precip(x,y,neige,model,title,step,run_now,"snow","snow6h")
            render_precip(x,y,total,model,title,step,run_now,"total","precip6h")
        except Exception as exc:
            result["errors"][key+"-precip6h"]=str(exc)[:350]
        finally:
            for file in (wet_now,wet_prev):
                file.unlink(missing_ok=True)
(OUT/"metadata.json").write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding="utf-8")
print("ECMWF summary",json.dumps({"maps":result["maps"],"errors":result["errors"]},ensure_ascii=False),flush=True)
if not result["maps"]: raise RuntimeError("No real ECMWF fields; publication aborted")
