#!/usr/bin/env python3
"""DWD ICON-D2 DBZ_CMAX (instantaneous column max reflectivity in dBZ).
Prefer the v1 native grid feed; legacy regular grid is a temporary fallback.
No extrapolation outside the ICON-D2 domain."""
import bz2
import json
import math
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from urllib.request import Request, urlopen
from urllib.parse import quote
import numpy as np
from scipy.spatial import cKDTree
from PIL import Image
from eccodes import codes_grib_new_from_file, codes_get, codes_get_array, codes_release, codes_set

ROOT = "https://opendata.dwd.de/weather/nwp/"
OUT = Path("icon-reflectivity")
BOUNDS = (-6., 10., 41., 52.)
STEP = .02
LEVELS = [5,10,15,20,25,30,35,40,45,50,55,60,65]
COLORS = ["#263f80","#2869b1","#42a9e0","#3cbd9b","#28a34d","#a6d739","#f2df32","#ffae22","#f57b20","#e73b38","#b9184b","#be38ba","#f0c8ff"]
W,H = 801,551

def url(run, h, field, native):
    if native:
        cycle = quote(run.strftime("%Y-%m-%dT%H:00"), safe="")
        return f"{ROOT}v1/m/icon-d2/p/{field}/r/{cycle}/s/PT{h:03d}H00M.grib2"
    return f"{ROOT}icon-d2/grib/{run:%H}/{field.lower()}/icon-d2_germany_regular-lat-lon_single-level_{run:%Y%m%d%H}_{h:03d}_{field}_2d.grib2.bz2"

def read_bytes(url):
    with urlopen(Request(url, headers={"User-Agent":"KFS-Meteo/1.0"}), timeout=55) as r:
        b=r.read(40_000_001)
    if len(b)>40_000_000: raise ValueError("Oversized field")
    return bz2.decompress(b) if b.startswith(b"BZh") else b

def key(g,k,default=None):
    try: return codes_get(g,k)
    except Exception: return default

def decode(run,h,field,native,coordinates=False):
    b=read_bytes(url(run,h,field,native))
    with TemporaryDirectory() as tmp:
        path=Path(tmp)/"field.grib2";path.write_bytes(b)
        with path.open("rb") as f:
            while (g:=codes_grib_new_from_file(f)) is not None:
                try:
                    if key(g,"dataDate")!=int(run.strftime("%Y%m%d")) or key(g,"dataTime")!=run.hour*100: continue
                    if field=="DBZ_CMAX":
                        if tuple(key(g,k) for k in ("discipline","parameterCategory","parameterNumber"))!=(0,15,1): continue
                        # Legacy files may contain sub-hourly fields; select exact validity, never first message blindly.
                        valid=run+timedelta(hours=h)
                        if key(g,"validityDate")!=int(valid.strftime("%Y%m%d")) or key(g,"validityTime")!=valid.hour*100: continue
                        if key(g,"stepType")!="instant":continue
                    codes_set(g,"missingValue",1e30)
                    v=np.asarray(codes_get_array(g,"values"),dtype=float)
                    unit=str(key(g,"units","")).lower()
                    meta=(key(g,"gridType"),key(g,"numberOfDataPoints"),key(g,"uuidOfHGrid"))
                    if coordinates:
                        return v,unit,meta
                    if field=="DBZ_CMAX" and unit not in ("dbz","db"):raise ValueError("Expected logarithmic reflectivity units")
                    if not native:
                        lat=np.asarray(codes_get_array(g,"latitudes"))
                        lon=np.asarray(codes_get_array(g,"longitudes"))
                        return v,meta,lat,lon
                    return v,meta,None,None
                finally: codes_release(g)
    raise ValueError(f"Missing exact {field} at H+{h}")

def coord(v,units,lat):
    if units in ("rad","radian","radians"):v=np.degrees(v)
    elif units not in ("deg","degree","degrees","degrees_north","degrees_east","degree_north","degree_east"):raise ValueError("Unknown coordinate units "+units)
    if not np.isfinite(v).all() or (lat and not (35<np.min(v)<55 and 45<np.max(v)<65)):raise ValueError("Invalid native coordinates")
    return v

def grid_index(lat,lon):
    lon=(lon+180)%360-180
    w,e,s,n=BOUNDS
    inside=np.isfinite(lat)&np.isfinite(lon)&(lat>=s-.1)&(lat<=n+.1)&(lon>=w-.1)&(lon<=e+.1)
    ids=np.flatnonzero(inside)
    if len(ids)<10000:raise ValueError("Insufficient France coverage")
    # Approximate local distances, with strict nearest-cell range to avoid extrapolation.
    x,y=np.meshgrid(np.linspace(w,e,W),np.linspace(n,s,H))
    def xy(a,b):return np.column_stack((a*111.195*math.cos(math.radians(47)),b*111.195))
    d,j=cKDTree(xy(lon[ids],lat[ids])).query(xy(x.ravel(),y.ravel()),workers=2)
    return ids[j],d<=2.8

def main():
    OUT.mkdir(exist_ok=True)
    now=datetime.now(timezone.utc)
    anchor=now.replace(hour=now.hour//3*3,minute=0,second=0,microsecond=0)
    prev=Path("previous-icon-reflectivity.json")
    previous=json.loads(prev.read_text()) if prev.exists() else {}
    selection=None
    for run in (anchor-timedelta(hours=i*3) for i in range(1,5)):
        start=max(0,int((now.replace(minute=0,second=0,microsecond=0)-run).total_seconds()//3600))
        end=start+24
        if end>48:continue
        if previous.get("run_utc")==run.isoformat() and len(previous.get("frames",[]))>=24 and max(datetime.fromisoformat(f["valid_utc"]) for f in previous["frames"])>=now.replace(minute=0,second=0,microsecond=0)+timedelta(hours=24):
            print("Already published");return
        for native in (True,False):
            try:
                first,meta,lat,lon=decode(run,start,"DBZ_CMAX",native)
                if native:
                    lat,lu,lm=decode(run,0,"CLAT",True,True)
                    lon,ou,om=decode(run,0,"CLON",True,True)
                    if lm!=meta or om!=meta or len(first)!=len(lat) or len(first)!=len(lon) or meta[2] is None:raise ValueError("Grid identity mismatch")
                    lat,lon=coord(lat,lu,True),coord(lon,ou,False)
                index,covered=grid_index(lat,lon)
                decode(run,end,"DBZ_CMAX",native)
                selection=run,start,end,native,meta,index,covered,first
                break
            except Exception as exc:print("ICON candidate",run,native,str(exc)[:160],flush=True)
        if selection:break
    if not selection:raise RuntimeError("No complete recent ICON-D2 cycle")
    run,start,end,native,meta,index,covered,first=selection
    def frame(h):
        if h==start:v=first
        else:
            v,m,_,_=decode(run,h,"DBZ_CMAX",native)
            if m!=meta:raise ValueError("Grid changed")
        sample=v[index]
        good=covered&np.isfinite(sample)&(sample>-1000)&(sample<100)
        if good.sum()<10000:raise ValueError("Insufficient valid field")
        idx=np.zeros(W*H,dtype=np.uint8)
        idx[good]=np.searchsorted(LEVELS,sample[good],side="right")
        idx[~good]=len(COLORS)+1
        im=Image.fromarray(idx.reshape(H,W),mode="P")
        palette=[0,0,0]+[int(c[i:i+2],16) for c in COLORS for i in (1,3,5)]+[107,112,120]
        im.putpalette(palette+[0]*(768-len(palette)))
        name=f"reflect-{run:%Y%m%d%H}-h{h:02d}.png"
        im.save(OUT/name,transparency=0,optimize=True)
        return {"hour":h,"valid_utc":(run+timedelta(hours=h)).isoformat(),"file":name}
    with ThreadPoolExecutor(max_workers=3) as pool:frames=list(pool.map(frame,range(start,end+1)))
    doc={"schema":1,"source":"DWD ICON-D2 DBZ_CMAX","unit":"dBZ","run_utc":run.isoformat(),"generated_utc":now.isoformat(),"resolution_degrees":STEP,"bounds":BOUNDS,"levels":LEVELS,"colors":COLORS,"frames":frames,"grid":"native-nearest" if native else "regular-nearest"}
    (OUT/"manifest.json").write_text(json.dumps(doc,indent=2))
if __name__=="__main__":main()
