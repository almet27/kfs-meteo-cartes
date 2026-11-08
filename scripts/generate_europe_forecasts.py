#!/usr/bin/env python3
"""KFS: real ECMWF IFS/AIFS forecast maps for Europe. No mock data."""
import json
from pathlib import Path
from datetime import datetime, timezone
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import cartopy.crs as ccrs
import cartopy.feature as cf
import xarray as xr
from ecmwf.opendata import Client

OUT=Path("forecast-maps/europe")
OUT.mkdir(parents=True,exist_ok=True)
STEPS=[24,48,72,120,168,240,360]
MODELS={"ifs":"ECMWF IFS","aifs-single":"ECMWF AIFS"}
EXTENT=[-13,34,34,72]
result={"generated_utc":datetime.now(timezone.utc).isoformat(),"source":"ECMWF Open Data (CC BY 4.0)","maps":{},"errors":{}}
def read(path,var):
    ds=xr.open_dataset(path,engine="cfgrib",backend_kwargs={"indexpath":""})
    try:
        a=ds[var].squeeze().load()
        lat=a.latitude.values
        lon=((a.longitude.values+180)%360)-180
        iy=np.where((lat>=32)&(lat<=74))[0]
        ix=np.where((lon>=-15)&(lon<=36))[0]
        ix=ix[np.argsort(lon[ix])]
        return lon[ix],lat[iy],a.values[np.ix_(iy,ix)]
    finally:ds.close()
for model,label in MODELS.items():
    client=Client(source="ecmwf",model=model,resol="0p25")
    for step in STEPS:
        if model=="ifs" and step>240:continue
        key=f"{model}-h{step:03}"
        p=OUT/(key+"-msl.grib2")
        q=OUT/(key+"-t850.grib2")
        try:
            client.retrieve(stream="oper",type="fc",step=step,param="msl",target=str(p))
            client.retrieve(stream="oper",type="fc",step=step,param="t",levelist=850,target=str(q))
            x,y,msl=read(p,"msl")
            x2,y2,temp=read(q,"t")
            if not (np.array_equal(x,x2) and np.array_equal(y,y2)):raise ValueError("Incompatible grids")
            fig=plt.figure(figsize=(11.5,9),dpi=155)
            ax=fig.add_subplot(111,projection=ccrs.PlateCarree())
            ax.set_extent(EXTENT,crs=ccrs.PlateCarree())
            ax.add_feature(cf.LAND,facecolor="#f0f0f0")
            ax.add_feature(cf.OCEAN,facecolor="#dceaf3")
            ax.coastlines("110m",linewidth=.7)
            ax.add_feature(cf.BORDERS,linewidth=.4)
            colors=ax.contourf(x,y,temp-273.15,levels=np.arange(-32,34,2),cmap="RdYlBu_r",extend="both",alpha=.86,transform=ccrs.PlateCarree())
            lines=ax.contour(x,y,msl/100,levels=np.arange(940,1061,4),colors="#232c40",linewidths=.7,transform=ccrs.PlateCarree())
            ax.clabel(lines,inline=True,fmt="%d",fontsize=7)
            fig.colorbar(colors,ax=ax,orientation="horizontal",pad=.04,shrink=.8,label="Température 850 hPa (°C)")
            ax.set_title(f"KFS MÉTÉO | {label} | Europe | +{step} h\nPression hPa et température 850 hPa")
            name=key+".png"
            fig.savefig(OUT/name,bbox_inches="tight",facecolor="white")
            plt.close(fig)
            result["maps"].setdefault(model,{})[str(step)]="forecast-maps/europe/"+name
        except Exception as exc:
            result["errors"][key]=str(exc)[:300]
        finally:
            p.unlink(missing_ok=True)
            q.unlink(missing_ok=True)
(OUT/"metadata.json").write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding="utf-8")
if not result["maps"]:raise RuntimeError("No real forecast data: abort publication")
print({k:len(v) for k,v in result["maps"].items()})
