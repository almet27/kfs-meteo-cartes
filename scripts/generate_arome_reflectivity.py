#!/usr/bin/env python3
"""Native ARÔME HD maximum simulated reflectivity (SP2, local GRIB 0/16/193)."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from urllib.request import Request, urlopen
import json, shutil, sys
import numpy as np
from PIL import Image
from eccodes import codes_grib_new_from_file, codes_get, codes_get_array, codes_release, codes_set

BASE = "https://meteofrance-pnt.s3.rbx.io.cloud.ovh.net/pnt/"
OUT = Path("arome-reflectivity")
BOUNDS = (-6., 10., 41., 52.)
LEVELS = [5,10,15,20,25,30,35,40,45,50,55,60,65]
COLORS = ["#263f80","#2869b1","#42a9e0","#3cbd9b","#28a34d","#a6d739","#f2df32","#ffae22","#f57b20","#e73b38","#b9184b","#be38ba","#f0c8ff"]
def url(run,h):
    t=run.strftime("%Y-%m-%dT%H:00:00Z")
    return f"{BASE}{t}/arome/001/SP2/arome__001__SP2__{h:02d}H__{t}.grib2"
def exists(run,h):
    try:
        with urlopen(Request(url(run,h),method="HEAD"),timeout=12) as r:
            return r.status==200 and int(r.headers.get("Content-Length","0"))>1000
    except Exception:return False
def key(g,k,default=None):
    try:return codes_get(g,k)
    except Exception:return default
def image_for(run,h,tmp):
    with TemporaryDirectory(dir=tmp) as folder:
        f=Path(folder)/"frame.grib2"
        with urlopen(Request(url(run,h),headers={"User-Agent":"KFS-Meteo/1.0"}),timeout=90) as r, f.open("wb") as out:
            shutil.copyfileobj(r,out,1024*1024)
        with f.open("rb") as stream:
            while (g:=codes_grib_new_from_file(stream)) is not None:
                try:
                    if tuple(key(g,k) for k in ("discipline","parameterCategory","parameterNumber"))!=(0,16,193):continue
                    if key(g,"dataDate")!=int(run.strftime("%Y%m%d")) or key(g,"dataTime")!=run.hour*100 or key(g,"endStep")!=h or key(g,"stepType")!="instant":
                        raise ValueError("Unexpected run or step")
                    if key(g,"gridType")!="regular_ll" or not np.isclose(key(g,"iDirectionIncrementInDegrees"),.01) or not np.isclose(key(g,"jDirectionIncrementInDegrees"),.01):raise ValueError("Not native HD grid")
                    codes_set(g,"missingValue",1e30)
                    lat=np.asarray(codes_get_array(g,"latitudes"));lon=(np.asarray(codes_get_array(g,"longitudes"))+180)%360-180
                    w,e,s,n=BOUNDS
                    mask=(lon>=w-.00001)&(lon<=e+.00001)&(lat>=s-.00001)&(lat<=n+.00001)
                    x=np.rint((lon[mask]-w)*100).astype(int);y=np.rint((n-lat[mask])*100).astype(int)
                    raw=np.asarray(codes_get_array(g,"values"))[mask]
                    if len(raw)!=1601*1101:raise ValueError("Unexpected crop")
                    good=np.isfinite(raw)&(raw>=0)&(raw<1e20)&(raw!=9999)
                    if good.mean()<.8:raise ValueError("Incomplete reflectivity field")
                    units=str(key(g,"units","unknown")).lower()
                    if units in ("dbz","db"):raise ValueError("Unexpected logarithmic units for linear parameter")
                    db=np.full(raw.shape,-np.inf)
                    positive=good&(raw>0);db[positive]=10*np.log10(raw[positive])
                    idx=np.searchsorted(LEVELS,db,side="right").astype(np.uint8)
                    idx[~good]=len(COLORS)+1
                    raster=np.zeros((1101,1601),dtype=np.uint8);raster[y,x]=idx
                    palette=[0,0,0]+[int(c[i:i+2],16) for c in COLORS for i in (1,3,5)]+[107,112,120]
                    im=Image.fromarray(raster,mode="P");im.putpalette(palette+[0]*(768-len(palette)))
                    name=f"reflect-{run:%Y%m%d%H}-h{h:02d}.png"
                    im.save(OUT/name,transparency=0,optimize=True)
                    print("AROME HD",h,"valid",round(float(good.mean()),3),"max dBZ",float(np.max(db)),flush=True)
                    return {"hour":h,"valid_utc":(run+timedelta(hours=h)).isoformat(),"file":name}
                finally:codes_release(g)
        raise ValueError("SP2 reflectivity field missing")
def main():
    OUT.mkdir(exist_ok=True)
    now=datetime.now(timezone.utc);anchor=now.replace(hour=now.hour//3*3,minute=0,second=0,microsecond=0)
    run=next((r for r in (anchor-timedelta(hours=i*3) for i in range(1,7)) if exists(r,48) and exists(r,1)),None)
    if run is None:raise RuntimeError("No coherent recent HD cycle")
    old=Path("previous-reflectivity.json")
    if old.exists():
        try:
            prev=json.loads(old.read_text())
            if prev["run_utc"]==run.isoformat() and len(prev["frames"])>=48:
                print("Already published");return
        except (ValueError,KeyError):pass
    horizon=51 if exists(run,51) else 48
    with TemporaryDirectory() as tmp,ThreadPoolExecutor(max_workers=3) as pool:
        frames=list(pool.map(lambda h:image_for(run,h,tmp),range(1,horizon+1)))
    doc={"schema":1,"run_utc":run.isoformat(),"generated_utc":now.isoformat(),"resolution_degrees":.01,"source":"Météo-France ARÔME HD SP2","unit":"dBZ","bounds":BOUNDS,"levels":LEVELS,"colors":COLORS,"frames":frames}
    (OUT/"manifest.json").write_text(json.dumps(doc,indent=2))
if __name__=="__main__":main()
