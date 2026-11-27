#!/usr/bin/env python3
"""DWD ICON-D2 native surface fields sampled on the KFS common grid, without extrapolation."""
import json, math
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryFile
import numpy as np
from scipy.spatial import cKDTree
from eccodes import codes_grib_new_from_file, codes_get_array, codes_set, codes_release
from generate_hourly_precip_phase import icon_url, available, payload, icon_grid, key, hours, grid_identity
ROOT=Path("forecast-maps/france/hourly-web")
FIELDS=["temperature_2m","wind_speed_10m","wind_gusts_10m","precipitation","wind_direction_10m","weather_code"]
CORE=("T_2M","U_10M","V_10M","TOT_PREC")
WIND_UNITS=("m s**-1","m s-1","m/s")
PRECIP_UNITS=("kg m**-2","kg m-2","kg/m^2","kg/m2","mm")
WX={45,48,51,53,55,56,57,61,63,65,66,67,71,73,75,77,80,81,82,85,86,95,96,97,99}
def load(run,h,field,grid,index,covered):
    lon,lat,mask,meta=grid
    with TemporaryFile() as f:
        f.write(payload(icon_url(run,h,field)));f.seek(0)
        valid=run+timedelta(hours=h)
        while (g:=codes_grib_new_from_file(f)) is not None:
            try:
                if key(g,"dataDate")!=int(run.strftime("%Y%m%d")) or key(g,"dataTime")!=run.hour*100:continue
                if key(g,"validityDate")!=int(valid.strftime("%Y%m%d")) or key(g,"validityTime")!=valid.hour*100:continue
                if hours(key(g,"endStep"))!=h or grid_identity(g)!=meta:continue
                mode=key(g,"stepType")
                if field in ("T_2M","U_10M","V_10M","CLCT") and mode!="instant":continue
                if field=="TOT_PREC" and mode!="accum":continue
                if field=="VMAX_10M" and (mode!="max" or hours(key(g,"startStep"))!=h-1):continue
                codes_set(g,"missingValue",1e30)
                v=np.asarray(codes_get_array(g,"values"),dtype=float)
                if len(v)!=len(mask):raise ValueError("Grid size mismatch")
                a=v[mask][index];a[~covered|~np.isfinite(a)|(np.abs(a)>1e6)]=np.nan
                unit=str(key(g,"units",""))
                if field=="T_2M":
                    if unit!="K":raise ValueError("Temperature unit "+unit)
                    a-=273.15
                elif field in ("U_10M","V_10M","VMAX_10M"):
                    if unit not in WIND_UNITS:raise ValueError("Wind unit "+unit)
                    a*=3.6
                elif field=="TOT_PREC":
                    if unit not in PRECIP_UNITS:raise ValueError("Precipitation unit "+unit)
                elif field=="CLCT":
                    if unit in ("(0 - 1)","1","~","fraction","0-1"):a*=100
                    elif unit not in ("%","percent"):raise ValueError("Cloud unit "+unit)
                    a[(a<0)|(a>100)]=np.nan
                return a,hours(key(g,"startStep"))
            finally:codes_release(g)
    raise ValueError("Missing exact "+field+" +"+str(h))
def main():
    pts=json.loads((ROOT/"arome.json").read_text())["points"]
    p=np.asarray(pts,dtype=float)
    if p.ndim!=2 or p.shape[1]!=2 or len(p)<100:raise ValueError("Invalid common grid")
    now=datetime.now(timezone.utc);base=now.replace(minute=0,second=0,microsecond=0)
    anchor=base.replace(hour=base.hour//3*3)
    dest=ROOT/"icon-d2.json"
    old=json.loads(dest.read_text()) if dest.exists() else {}
    selection=None
    for lag in range(1,6):
        run=anchor-timedelta(hours=lag*3);start=max(1,int((base-run).total_seconds()/3600))
        if start+12>48:continue
        if all(available(icon_url(run,h,f)) for f in CORE for h in (start-1,48)):
            selection=(run,start);break
    if selection is None:raise RuntimeError("No complete recent D2 cycle")
    run,start=selection
    if old.get("run_utc")==run.isoformat() and old.get("schema")==1 and old.get("times") and datetime.fromisoformat(old["times"][-1])>=run+timedelta(hours=48):
        print("D2 already published");return
    grid=icon_grid(run);lon,lat,mask,meta=grid
    # Nearest actual native cell within 2.8 km; outside domain stays null.
    def xy(x,y):return np.column_stack((x*111.195*math.cos(math.radians(47)),y*111.195))
    d,index=cKDTree(xy(lon,lat)).query(xy(p[:,0],p[:,1]),workers=2)
    covered=d<=2.8
    if covered.sum()<12:raise ValueError("Insufficient French D2 coverage")
    optional=[f for f in ("VMAX_10M","WW","CLCT") if available(icon_url(run,48,f))]
    def one(job):
        h,field=job
        try:return job,load(run,h,field,grid,index,covered)
        except Exception as exc:
            if field in CORE:raise
            print("Optional D2 field missing",field,h,str(exc)[:120],flush=True)
            return job,(np.full(len(p),np.nan),-1)
    jobs=[(start-1,"TOT_PREC")]+[(h,f) for h in range(start,49) for f in CORE+tuple(optional)]
    with ThreadPoolExecutor(max_workers=5) as pool:values=dict(pool.map(one,jobs))
    missing=np.full(len(p),np.nan)
    rows=[[] for _ in p]
    for h in range(start,49):
        t=values[h,"T_2M"][0];u=values[h,"U_10M"][0];v=values[h,"V_10M"][0]
        gust=values.get((h,"VMAX_10M"),(missing,-1))[0]
        a,begin=values[h,"TOT_PREC"]
        if begin==h-1:precip=a
        elif begin==0 and values[h-1,"TOT_PREC"][1]==0:precip=a-values[h-1,"TOT_PREC"][0]
        else:raise ValueError("Unknown D2 precipitation interval")
        if np.any(precip[np.isfinite(precip)]<-.15):raise ValueError("Negative precipitation increment")
        precip=np.maximum(precip,0)
        speed=np.hypot(u,v);direction=(270-np.degrees(np.arctan2(v,u)))%360
        wx=values.get((h,"WW"),(missing,-1))[0];cloud=values.get((h,"CLCT"),(missing,-1))[0]
        if sum(np.isfinite(t)&covered)<.8*covered.sum():raise ValueError("D2 temperature coverage incomplete")
        def clean(x):return round(float(x),3) if math.isfinite(x) else None
        for i in range(len(p)):
            code=None
            if covered[i] and math.isfinite(precip[i]):
                if math.isfinite(wx[i]) and wx[i] in WX and (precip[i]>=.1 or wx[i] in (45,48,95,96,97,99)):code=int(wx[i])
                elif precip[i]<.1 and math.isfinite(cloud[i]):code=0 if cloud[i]<15 else 1 if cloud[i]<35 else 2 if cloud[i]<80 else 3
            rows[i].append([clean(t[i]),clean(speed[i]),clean(gust[i]),clean(precip[i]),clean(direction[i]),code])
    doc={"schema":1,"model":"icon-d2","provider":"DWD Open Data","run_utc":run.isoformat(),
         "fetched_utc":datetime.now(timezone.utc).isoformat(),"points":pts,"times":[(run+timedelta(hours=h)).isoformat() for h in range(start,49)],
         "rows":rows,"fields":FIELDS,"grid_degrees":.58,"native_grid_km":2.2,"covered_points":int(covered.sum()),
         "note":"Hourly native ICON-D2, nearest native cell <=2.8km; outside domain null. WW or cloud diagnostic; no synthetic precipitation phases."}
    tmp=dest.with_suffix(".tmp");tmp.write_text(json.dumps(doc,separators=(",",":"),allow_nan=False));tmp.replace(dest)
    print("D2 published",run.isoformat(),int(covered.sum()),"of",len(p),"points",len(doc["times"]),"hours",flush=True)
if __name__=="__main__":main()
