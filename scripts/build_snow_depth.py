#!/usr/bin/env python3
"""KFS snow depth: native ICON-EU, optional ICON-D2, hourly model depth.
Quarter-hour linear interpolation of the model state, not radar assimilation.
"""
import datetime as dt
import json
from pathlib import Path
from tempfile import TemporaryFile
from concurrent.futures import ThreadPoolExecutor
import numpy as np
from PIL import Image
from scipy.spatial import cKDTree
from eccodes import codes_grib_new_from_file,codes_get_array,codes_set,codes_release
from generate_hourly_precip_phase import payload, available, key, hours, grid_identity
from urllib.parse import quote
UTC=dt.timezone.utc
W,H=730,735
BOUNDS=(-5.8,51.6-735/65,-5.8+730/46,51.6)
X,Y=np.meshgrid(-5.8+(np.arange(W)+.5)/46,51.6-(np.arange(H)+.5)/65)
XY=np.column_stack((X.ravel()*.68,Y.ravel()))
LEVELS=np.array([.2,1,2,5,10,20,50,100])
COLORS=["#e2f5ff","#a8ddff","#60b7f5","#3877db","#6450ba","#a23da1","#e64794","#f9a2c9"]
def url(model,run,field,h):
    cycle=quote(run.strftime("%Y-%m-%dT%H:00"),safe="")
    return f"https://opendata.dwd.de/weather/nwp/v1/m/{model}/p/{field}/r/{cycle}/s/PT{h:03d}H00M.grib2"
def read(model,run,field,h):
    with TemporaryFile() as f:
        f.write(payload(url(model,run,field,h)));f.seek(0)
        g=codes_grib_new_from_file(f)
        if g is None:raise ValueError("Invalid GRIB "+field)
        try:
            codes_set(g,"missingValue",1e30)
            vals=np.asarray(codes_get_array(g,"values"))
            meta=grid_identity(g);units=str(key(g,"units","")).lower().strip()
            if field=="H_SNOW":
                valid=run+dt.timedelta(hours=h)
                if key(g,"dataDate")!=int(run.strftime("%Y%m%d")) or key(g,"dataTime")!=run.hour*100 or key(g,"validityDate")!=int(valid.strftime("%Y%m%d")) or key(g,"validityTime")!=valid.hour*100 or key(g,"stepType")!="instant" or hours(key(g,"endStep"))!=h or units!="m":raise ValueError("Snow depth metadata mismatch")
                if tuple(key(g,k) for k in ("discipline","parameterCategory","parameterNumber"))!=(0,1,11):raise ValueError("Unexpected GRIB parameter")
                vals=np.where(np.isfinite(vals)&(vals>=0)&(vals<=30),100*vals,np.nan)
            elif field in ("CLAT","CLON"):
                if units in ("rad","radian","radians"):vals=np.degrees(vals)
                elif not (units.startswith("degree") or units=="deg"):raise ValueError("Coordinate units")
                if not np.isfinite(vals).all() or np.max(np.abs(vals))>360:raise ValueError("Invalid coordinates")
            return vals,meta
        finally:codes_release(g)
def model_frames(model,start,end):
    now=dt.datetime.now(UTC)
    anchor=now.replace(hour=now.hour//3*3,minute=0,second=0,microsecond=0)
    for lag in range(1,6):
        run=anchor-dt.timedelta(hours=3*lag)
        h0=int((start-run).total_seconds()/3600);h1=int((end-run).total_seconds()/3600)
        if h0<0 or h1>48:continue
        if not all(available(url(model,run,f,h)) for f,h in [("CLAT",0),("CLON",0),("H_SNOW",h0),("H_SNOW",h1)]):continue
        try:
            with ThreadPoolExecutor(max_workers=3) as pool:
                lat,lon=pool.map(lambda f:read(model,run,f,0),["CLAT","CLON"])
                if lat[1]!=lon[1] or not lat[1][2]:raise ValueError("Native grid UUID missing")
                yy,xx=lat[0],(lon[0]+180)%360-180
                if len(xx)!=len(yy):raise ValueError("Coordinate length mismatch")
                w,s,e,n=BOUNDS
                mask=(xx>=w-.15)&(xx<=e+.15)&(yy>=s-.15)&(yy<=n+.15)
                if mask.sum()<10000:raise ValueError("Too few French grid points")
                dist,idx=cKDTree(np.column_stack((xx[mask]*.68,yy[mask]))).query(XY,workers=2)
                covered=dist<(.035 if model=="icon-d2" else .085)
                rows=[]
                for vals,meta in pool.map(lambda h:read(model,run,"H_SNOW",h),range(h0,h1+1)):
                    if meta!=lat[1] or len(vals)!=len(mask):raise ValueError("Snow depth grid differs")
                    out=vals[mask][idx];out[~covered]=np.nan
                    rows.append(out.reshape(H,W).astype("float32"))
            return run,rows
        except Exception as e:
            print(model,run.isoformat(),str(e)[:220],flush=True)
    raise RuntimeError("No complete recent "+model+" depth cycle")
def interpolate(a,b,f):
    if f==0:return a
    if f==1:return b
    return a*(1-f)+b*f
def classify(v):
    idx=np.zeros(v.shape,dtype=np.uint8)
    good=np.isfinite(v)
    idx[~good]=len(COLORS)+1
    snow=good&(v>=LEVELS[0])
    idx[snow]=np.searchsorted(LEVELS,v[snow],side="right")
    return idx
def render(v,path):
    idx=classify(v)
    im=Image.fromarray(idx,mode="P")
    palette=[0,0,0]+[int(c[i:i+2],16) for c in COLORS for i in (1,3,5)]+[125,145,160]
    im.putpalette(palette+[0]*(768-len(palette)))
    im.save(path,transparency=bytes([0]+[230]*len(COLORS)+[150]),optimize=True)
def main():
    start=dt.datetime.now(UTC).replace(minute=0,second=0,microsecond=0)
    end=start+dt.timedelta(hours=2)
    eu,base=model_frames("icon-eu",start,end)
    if min(np.isfinite(v).mean() for v in base)<.85:raise RuntimeError("ICON-EU insufficient national coverage")
    models={"icon-eu":eu.isoformat()}
    try:
        d2,detail=model_frames("icon-d2",start,end)
        if abs((d2-eu).total_seconds())<=6*3600:
            base=[np.where(np.isfinite(d),d,b) for b,d in zip(base,detail)]
            models["icon-d2"]=d2.isoformat()
    except Exception as e:print("ICON-D2 fallback to national ICON-EU:",str(e)[:200],flush=True)
    out=Path("data/snow-depth");out.mkdir(parents=True,exist_ok=True)
    frames=[]
    stamp=eu.strftime("%Y%m%d%H")
    for k in range(9):
        h=k//4;f=(k%4)/4
        vals=base[h] if f==0 else interpolate(base[h],base[h+1],f)
        valid=start+dt.timedelta(minutes=15*k)
        file=f"depth-{stamp}-{valid:%Y%m%d%H%M}.png"
        render(vals,out/file)
        frames.append({"valid_utc":valid.isoformat(),"file":file,"valid_pixels":int(np.isfinite(vals).sum()),"snow_pixels":int((vals>=.2).sum())})
    manifest={"schema":1,"projection":"KFS-730x735-v1","width":W,"height":H,"method":"native_model_depth_linear_15min","models":models,"units":"cm","levels":LEVELS.tolist(),"colors":COLORS,"frames":frames,"published_utc":dt.datetime.now(UTC).isoformat()}
    (out/"latest.json").write_text(json.dumps(manifest,separators=(",",":"))+"\n")
    # Retain the previous day's images so cached manifests do not break.
    keep={f["file"] for f in frames}
    for p in out.glob("depth-*.png"):
        try:valid=dt.datetime.strptime(p.stem.split("-")[-1],"%Y%m%d%H%M").replace(tzinfo=UTC)
        except ValueError:continue
        if p.name not in keep and valid<start-dt.timedelta(hours=4):p.unlink()
    print(json.dumps(manifest),flush=True)
if __name__=="__main__":main()
