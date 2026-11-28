#!/usr/bin/env python3
"""DMI HARMONIE DINI, hourly precipitation on a geographic 0.02-degree output grid.
Native Lambert grid ~2 km. No extrapolation; no simulated reflectivity inferred.
Fetch only indexed precipitation GRIB messages (HTTP range)."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime,timedelta,timezone
from pathlib import Path
from urllib.parse import urlparse
import io,json,re
import requests
import numpy as np
from scipy.spatial import cKDTree
from PIL import Image
from eccodes import codes_new_from_message,codes_get,codes_get_array,codes_set,codes_release

API="https://opendataapi.dmi.dk/v1/forecastdata/collections/harmonie_dini_sf/items"
OUT=Path("harmonie-precip")
BOUNDS=(-6.,10.,41.,52.)
LEVELS=[.1,.3,1,3,8,15,30]
COLORS=["#483d8a","#211cc9","#00a3e0","#0082b9","#ffdd00","#ff8100","#c10000"]
def key(g,k,default=None):
    try:return codes_get(g,k)
    except Exception:return default
def date(s):return datetime.fromisoformat(s.replace("Z","+00:00"))
def catalog(run):
    r=requests.get(API,params={"modelRun":run.strftime("%Y-%m-%dT%H:%M:%SZ"),"limit":100},timeout=30);r.raise_for_status()
    frames={}
    for f in r.json().get("features",[]):
        t=date(f["properties"]["datetime"])
        if date(f["properties"]["modelRun"])!=run:continue
        h=(t-run).total_seconds()/3600
        if h<0 or not h.is_integer():continue
        u=(f.get("assets") or f.get("asset"))["data"]["href"];p=urlparse(u)
        if p.scheme!="https" or p.hostname not in ("dmi-opendata.s3.eu-north-1.amazonaws.com","dmi-opendata.s3-eu-north-1.amazonaws.com") or not p.path.startswith("/forecastdata/HARMONIE_DINI_SF/"):continue
        frames[int(h)]=u
    return frames
def grib(url):
    r=requests.get(url+".index",timeout=30);r.raise_for_status()
    rows=[l.split(":") for l in r.text.splitlines() if l.strip()]
    offsets=[int(x[1]) for x in rows]
    if offsets!=sorted(set(offsets)):raise ValueError("Index offsets invalid")
    # DMI parameter table 0/1/52 is total precipitation. Verify GRIB metadata,
    # not merely its index label. Index aliases differ between decoder versions.
    ids=[i for i,x in enumerate(rows) if i+1<len(rows) and len(x)>=6 and x[3] in ("TPRATE","APCP","TP","TOTP","ACPCP","TOTAL_PRECIPITATION") and "surface" in x[4].lower()]
    if not ids:raise ValueError("Total precipitation absent from GRIB index")
    for i in ids:
        a,b=offsets[i],offsets[i+1]-1
        if not 0<b-a<40_000_000:raise ValueError("Unexpected GRIB size")
        with requests.get(url,headers={"Range":f"bytes={a}-{b}"},stream=True,timeout=(15,90)) as r:
            if r.status_code!=206 or not r.headers.get("Content-Range","").startswith(f"bytes {a}-{b}/"):raise ValueError("Range not honored")
            raw=r.content
        if len(raw)!=b-a+1 or raw[:4]!=b"GRIB" or raw[-4:]!=b"7777":raise ValueError("GRIB framing")
        g=codes_new_from_message(raw)
        if tuple(key(g,k) for k in ("discipline","parameterCategory","parameterNumber"))==(0,1,52):return g
        codes_release(g)
    raise ValueError("Total precipitation 0/1/52 absent")
def load(url,run,h,geometry=False,index=None,coverage=None,identity=None):
    g=grib(url)
    try:
        valid=run+timedelta(hours=h)
        if key(g,"dataDate")!=int(run.strftime("%Y%m%d")) or key(g,"dataTime")!=run.hour*100 or key(g,"validityDate")!=int(valid.strftime("%Y%m%d")) or key(g,"validityTime")!=valid.hour*100:raise ValueError("Run or valid time mismatch")
        if key(g,"units") not in ("kg m**-2","kg m-2","mm") or key(g,"stepType")!="accum":raise ValueError("Unexpected rainfall unit or step type")
        if key(g,"stepUnits")!=1 or int(key(g,"endStep"))!=h:raise ValueError("Unexpected accumulation end")
        begin=int(key(g,"startStep"))
        ident=tuple(key(g,k) for k in ("gridType","Nx","Ny","latitudeOfFirstGridPointInDegrees","longitudeOfFirstGridPointInDegrees","DxInMetres","DyInMetres","LoVInDegrees","Latin1InDegrees","Latin2InDegrees","scanningMode"))
        if ident[0]!="lambert" or not 1800<=float(ident[5])<=2200 or not 1800<=float(ident[6])<=2200:raise ValueError("Not native 2km Lambert")
        if identity is not None and ident!=identity:raise ValueError("Grid geometry changed")
        codes_set(g,"missingValue",1e30)
        v=np.asarray(codes_get_array(g,"values"),dtype=float)
        if geometry:
            lat=np.asarray(codes_get_array(g,"latitudes"));lon=(np.asarray(codes_get_array(g,"longitudes"))+180)%360-180
            if len(lat)!=len(v):raise ValueError("Grid size")
            # Geographic nearest-neighbor on a local metric; reject pixels farther
            # than 1.7 km from an actual native cell. No edge extrapolation.
            mask=(lat>=40.8)&(lat<=52.2)&(lon>=-6.2)&(lon<=10.2)
            subset=np.flatnonzero(mask)
            def xyz(lon,lat):
                p=np.deg2rad(lat);q=np.deg2rad(lon);return 6371.0088*np.column_stack((np.cos(p)*np.cos(q),np.cos(p)*np.sin(q),np.sin(p)))
            x,y=np.meshgrid(np.linspace(-6,10,801),np.linspace(52,41,551))
            dist,near=cKDTree(xyz(lon[mask],lat[mask])).query(xyz(x.ravel(),y.ravel()),workers=2)
            index=subset[near];coverage=dist<=1.7
            if coverage.mean()<.80:raise ValueError("Insufficient native coverage")
        a=v[index];a[~coverage|~np.isfinite(a)|(a<0)|(a>1e6)]=np.nan
        return a,begin,index,coverage,ident
    finally:codes_release(g)
def main():
    OUT.mkdir(exist_ok=True)
    now=datetime.now(timezone.utc);base=now.replace(minute=0,second=0,microsecond=0);anchor=base.replace(hour=base.hour//3*3)
    chosen=None
    for lag in range(1,6):
        run=anchor-timedelta(hours=lag*3);frames=catalog(run);start=max(1,int((base-run).total_seconds()/3600)+1);end=min(60,int((base+timedelta(hours=48)-run).total_seconds()/3600))
        if end-start>=23 and all(h in frames for h in range(start-1,end+1)):
            chosen=run,frames,start,end;break
    if not chosen:raise RuntimeError("No recent contiguous HARMONIE cycle")
    run,frames,start,end=chosen
    old=Path("previous-harmonie.json")
    if old.exists():
        prev=json.loads(old.read_text())
        if prev.get("run_utc")==run.isoformat() and len(prev.get("frames",[]))>=end-start+1:
            print("Already published",flush=True);return
    first=load(frames[start],run,start,geometry=True);index,coverage,identity=first[2:]
    def one(h):return h,load(frames[h],run,h,index=index,coverage=coverage,identity=identity)[:2]
    jobs=list(range(start-1,end+1))
    with ThreadPoolExecutor(max_workers=3) as pool:fields=dict(pool.map(one,jobs))
    output=[]
    for h in range(start,end+1):
        a,begin=fields[h]
        if begin==h-1:rate=a
        elif begin==0 and fields[h-1][1]==0:rate=a-fields[h-1][0]
        else:raise ValueError("Unknown accumulation interval")
        if np.any(rate[np.isfinite(rate)]<-.15):raise ValueError("Negative precipitation increment")
        rate=np.maximum(rate,0)
        if np.count_nonzero(np.isfinite(rate))<.95*coverage.sum():raise ValueError("Incomplete precipitation field")
        pixels=np.searchsorted(LEVELS,np.nan_to_num(rate,nan=0),side="right").astype(np.uint8)
        pixels[~np.isfinite(rate)]=len(COLORS)+1
        im=Image.fromarray(pixels.reshape(551,801),mode="P");palette=[0,0,0]+[int(c[i:i+2],16) for c in COLORS for i in (1,3,5)]+[125,145,160];im.putpalette(palette+[0]*(768-len(palette)));im.info["transparency"]=bytes([0]+[255]*len(COLORS)+[100])
        name=f"precip-{run:%Y%m%d%H}-h{h:02d}.png";im.save(OUT/name,optimize=True)
        output.append({"hour":h,"valid_utc":(run+timedelta(hours=h)).isoformat(),"file":name})
        print("HARMONIE",h,"max mm",float(np.nanmax(rate)),flush=True)
    doc={"schema":1,"model":"harmonie","source":"DMI HARMONIE DINI","run_utc":run.isoformat(),"generated_utc":now.isoformat(),"native_grid_km":2,"resolution_degrees":.02,"bounds":BOUNDS,"unit":"mm","interval_hours":1,"levels":LEVELS,"colors":COLORS,"coverage_fraction":float(coverage.mean()),"frames":output}
    (OUT/"manifest.json").write_text(json.dumps(doc,indent=2))
if __name__=="__main__":main()
