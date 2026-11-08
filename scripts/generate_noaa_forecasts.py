#!/usr/bin/env python3
"""KFS Météo: GFS and AIGFS Europe maps from operational NOAA GRIB2.
Uses indexed partial downloads via Herbie; never invents weather fields.
"""
import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import cartopy.crs as ccrs
import cartopy.feature as cf
from herbie import Herbie

OUT = Path("forecast-maps/europe")
OUT.mkdir(parents=True, exist_ok=True)
STEPS = [24, 48, 72, 120, 168, 240, 360]
RUN = (datetime.now(timezone.utc) - timedelta(hours=10)).replace(
    hour=((datetime.now(timezone.utc) - timedelta(hours=10)).hour // 6) * 6,
    minute=0, second=0, microsecond=0)
METADATA = {"generated_utc":datetime.now(timezone.utc).isoformat(),
            "run_utc":RUN.isoformat(),"source":"NOAA NCEP NOMADS",
            "maps":{}, "errors":{}}

def subset(dataset):
    names = list(dataset.data_vars)
    if len(names)!=1:
        raise ValueError(f"Expected one GRIB parameter, found {names}")
    da = dataset[names[0]].squeeze()
    lat = np.asarray(da.latitude.values)
    lon = ((np.asarray(da.longitude.values)+180)%360)-180
    if lat.ndim!=1 or lon.ndim!=1:
        raise ValueError("Expected regular latitude/longitude grid")
    iy = np.where((lat>=32)&(lat<=74))[0]
    ix = np.where((lon>=-15)&(lon<=36))[0]
    ix = ix[np.argsort(lon[ix])]
    data = da.values[np.ix_(iy,ix)]
    return lon[ix],lat[iy],data

def fetch_field(model, step, product, pattern):
    h = Herbie(RUN, model=model, product=product, fxx=step, verbose=False)
    ds = h.xarray(pattern, remove_grib=True)
    if ds is None:
        raise RuntimeError(f"No {pattern} in {model} +{step}h")
    return subset(ds)

for model, title in [("gfs","GFS"),("aigfs","AIGFS")]:
    for step in STEPS:
        key = f"{model}-h{step:03}"
        try:
            if model=="gfs":
                product_pressure = product_temperature = "pgrb2.0p25"
            else:
                product_pressure,product_temperature="sfc","pres"
            lon,lat,msl = fetch_field(model,step,product_pressure,":PRMSL:mean sea level:")
            xx,yy,t850 = fetch_field(model,step,product_temperature,":TMP:850 mb:")
            if not (np.array_equal(lon,xx) and np.array_equal(lat,yy)):
                raise ValueError("Temperature and pressure GRIB grids differ")
            if np.nanmedian(msl)<2000:
                raise ValueError("Pressure units are not Pa")
            if np.nanmedian(t850)<150:
                raise ValueError("Temperature units are not Kelvin")
            fig=plt.figure(figsize=(11.5,9),dpi=155)
            ax=fig.add_subplot(111,projection=ccrs.PlateCarree())
            ax.set_extent([-13,34,34,72],crs=ccrs.PlateCarree())
            ax.add_feature(cf.LAND,facecolor="#f0f0f0")
            ax.add_feature(cf.OCEAN,facecolor="#dceaf3")
            ax.coastlines("110m",linewidth=.7)
            ax.add_feature(cf.BORDERS,linewidth=.4)
            shaded=ax.contourf(lon,lat,t850-273.15,levels=np.arange(-32,34,2),
              cmap="RdYlBu_r",extend="both",alpha=.86,transform=ccrs.PlateCarree())
            c=ax.contour(lon,lat,msl/100,levels=np.arange(940,1061,4),
              colors="#232c40",linewidths=.7,transform=ccrs.PlateCarree())
            ax.clabel(c,inline=True,fontsize=7,fmt="%d")
            fig.colorbar(shaded,ax=ax,orientation="horizontal",pad=.04,shrink=.8,
              label="Température 850 hPa (°C)")
            ax.set_title(f"KFS MÉTÉO | {title} | Europe | +{step} h\\nPression hPa et température 850 hPa")
            filename=key+".png"
            fig.savefig(OUT/filename,bbox_inches="tight",facecolor="white")
            plt.close(fig)
            METADATA["maps"].setdefault(model,{})[str(step)]="forecast-maps/europe/"+filename
        except Exception as e:
            METADATA["errors"][key]=str(e)[:350]
(OUT/"noaa-metadata.json").write_text(json.dumps(METADATA,ensure_ascii=False,indent=2),encoding="utf-8")
if not METADATA["maps"]:
    raise RuntimeError("No genuine GFS/AIGFS fields retrieved; publication aborted")
print({k:len(v) for k,v in METADATA["maps"].items()})
