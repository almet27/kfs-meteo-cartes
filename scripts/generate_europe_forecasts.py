#!/usr/bin/env python3
"""KFS Europe: separate 850 hPa temperature and 500 hPa heights / sea-level pressure."""
import json
from datetime import datetime, timezone
from pathlib import Path
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import cartopy.crs as ccrs
import cartopy.feature as cf
import xarray as xr
from ecmwf.opendata import Client

OUT = Path("forecast-maps/europe")
OUT.mkdir(parents=True, exist_ok=True)
STEPS = [24, 48, 72, 120, 168, 240, 360]
MODELS = {"ifs": "ECMWF IFS", "aifs-single": "ECMWF AIFS"}
EXTENT = [-13, 34, 34, 72]
result = {"generated_utc": datetime.now(timezone.utc).isoformat(),
          "source": "ECMWF Open Data (CC BY 4.0)", "maps": {}, "errors": {}}

def read(path, name):
    ds = xr.open_dataset(path, engine="cfgrib", backend_kwargs={"indexpath": ""})
    try:
        a = ds[name].squeeze().load()
        lat = np.asarray(a.latitude.values)
        lon = ((np.asarray(a.longitude.values)+180)%360)-180
        iy = np.where((lat>=32)&(lat<=74))[0]
        ix = np.where((lon>=-15)&(lon<=36))[0]
        ix = ix[np.argsort(lon[ix])]
        return lon[ix], lat[iy], a.values[np.ix_(iy,ix)], str(a.attrs.get("units", ""))
    finally:
        ds.close()

def canvas():
    fig = plt.figure(figsize=(11.5,9), dpi=155)
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
            x,y,temp,units=read(temp_path,"t")
            if np.nanmedian(temp)<150: raise ValueError("Unexpected 850 hPa temperature units: "+units)
            fig,ax=canvas()
            shade=ax.contourf(x,y,temp-273.15,levels=np.arange(-36,38,2),
                cmap="RdYlBu_r",extend="both",transform=ccrs.PlateCarree())
            fig.colorbar(shade,ax=ax,orientation="horizontal",pad=.04,shrink=.8,label="Température à 850 hPa (°C)")
            ax.set_title(f"KFS MÉTÉO | {title} | Europe | +{step} h\nTempérature 850 hPa")
            save_map(fig,model,step,"t850")
        except Exception as exc:
            result["errors"][key+"-t850"]=str(exc)[:350]
        try:
            # Real 500 hPa geopotential height (not 500 hPa temperature).
            client.retrieve(stream="oper",type="fc",step=step,param="msl",target=str(pres_path))
            client.retrieve(stream="oper",type="fc",step=step,param="gh",levelist=500,target=str(height_path))
            x,y,msl,_=read(pres_path,"msl")
            x2,y2,gh,units=read(height_path,"gh")
            if not (np.array_equal(x,x2) and np.array_equal(y,y2)):
                raise ValueError("500 hPa and MSLP grids differ")
            # ECMWF 'gh' is geopotential height, in metres (convert to decametres).
            if not 4000 < np.nanmedian(gh) < 6500:
                raise ValueError("Unexpected geopotential height values/units: "+units)
            if not 90000 < np.nanmedian(msl) < 110000:
                raise ValueError("Unexpected MSL pressure values")
            fig,ax=canvas()
            shade=ax.contourf(x,y,gh/10,levels=np.arange(460,625,4),
                cmap="Spectral_r",extend="both",transform=ccrs.PlateCarree())
            heights=ax.contour(x,y,gh/10,levels=np.arange(460,625,8),
                colors="#322f41",linewidths=.8,transform=ccrs.PlateCarree())
            ax.clabel(heights,inline=True,fontsize=7,fmt="%d")
            lines=ax.contour(x,y,msl/100,levels=np.arange(940,1061,4),
                colors="#1b547b",linewidths=.8,linestyles="dashed",transform=ccrs.PlateCarree())
            ax.clabel(lines,inline=True,fontsize=7,fmt="%d")
            fig.colorbar(shade,ax=ax,orientation="horizontal",pad=.04,shrink=.8,label="Géopotentiel 500 hPa (dam)")
            ax.set_title(f"KFS MÉTÉO | {title} | Europe | +{step} h\nZ500 (dam) et pression au niveau de la mer (hPa, pointillés)")
            save_map(fig,model,step,"z500_msl")
        except Exception as exc:
            result["errors"][key+"-z500_msl"]=str(exc)[:350]
        finally:
            for p in (temp_path,pres_path,height_path):
                p.unlink(missing_ok=True)
(OUT/"metadata.json").write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding="utf-8")
print("ECMWF summary",json.dumps({"maps":result["maps"],"errors":result["errors"]},ensure_ascii=False),flush=True)
if not result["maps"]: raise RuntimeError("No real ECMWF fields; publication aborted")
