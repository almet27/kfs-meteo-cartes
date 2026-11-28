#!/usr/bin/env python3
"""Experimental ARÔME HD pre-convective environment; not a calibrated probability.
Native MUCAPE, 10 m horizontal wind convergence and 2 m humidity. Missing data
remain missing. A candidate does not assert that an electrical storm will form.
"""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from urllib.request import Request, urlopen
import json
import shutil
import numpy as np
from scipy.ndimage import uniform_filter
from eccodes import codes_grib_new_from_file, codes_get, codes_get_array, codes_release, codes_set

BASE = "https://meteofrance-pnt.s3.rbx.io.cloud.ovh.net/pnt/"
OUT = Path("arome-initiation")
W,E,S,N = -6.,10.,41.,52.
RES=.01
SHAPE=(1101,1601)
BLOCK=5

def url(run,h,pkg):
    t=run.strftime("%Y-%m-%dT%H:00:00Z")
    return f"{BASE}{t}/arome/001/{pkg}/arome__001__{pkg}__{h:02d}H__{t}.grib2"

def exists(run,h,pkg):
    try:
        with urlopen(Request(url(run,h,pkg),method="HEAD"),timeout=15) as r:
            return r.status==200 and int(r.headers.get("Content-Length","0"))>1000
    except Exception:
        return False

def key(g,k,default=None):
    try: return codes_get(g,k)
    except Exception: return default

def identify(g,pkg):
    code=tuple(key(g,k) for k in ("discipline","parameterCategory","parameterNumber"))
    sn=str(key(g,"shortName","")).lower()
    if pkg=="SP2":
        if code==(0,7,6) or sn in ("cape_ins","mucape","cape"): return "cape"
        if code==(0,7,7) or sn=="cin": return "cin"
    if pkg=="SP3" and (code==(0,3,7) or sn=="h") and key(g,"typeOfLevel")=="surface": return "terrain"
    if pkg=="HP1" and key(g,"typeOfLevel")=="heightAboveGround" and key(g,"level")==100:
        if code==(0,2,2): return "u100"
        if code==(0,2,3): return "v100"
    if pkg=="SP1" and key(g,"typeOfLevel")=="heightAboveGround":
        level=key(g,"level")
        if level==10 and code==(0,2,2): return "u"
        if level==10 and code==(0,2,3): return "v"
        if level==2 and code==(0,1,1): return "rh"
    return None

def fields(run,h,pkg,tmp):
    out={}
    with TemporaryDirectory(dir=tmp) as d:
        p=Path(d)/"data.grib2"
        with urlopen(Request(url(run,h,pkg),headers={"User-Agent":"KFS-Meteo/1.0"}),timeout=100) as r,p.open("wb") as f:
            shutil.copyfileobj(r,f,1024*1024)
        with p.open("rb") as f:
            while (g:=codes_grib_new_from_file(f)) is not None:
                try:
                    name=identify(g,pkg)
                    if not name: continue
                    if name in out: raise ValueError("Ambiguous field "+name)
                    if name!="terrain" and (key(g,"dataDate")!=int(run.strftime("%Y%m%d")) or key(g,"dataTime")!=run.hour*100 or key(g,"endStep")!=h or key(g,"stepType")!="instant"): raise ValueError("Run/step mismatch")
                    if key(g,"gridType")!="regular_ll" or not np.isclose(key(g,"iDirectionIncrementInDegrees"),RES) or not np.isclose(key(g,"jDirectionIncrementInDegrees"),RES): raise ValueError("Unexpected grid")
                    codes_set(g,"missingValue",1e30)
                    lon=(np.asarray(codes_get_array(g,"longitudes"))+180)%360-180
                    lat=np.asarray(codes_get_array(g,"latitudes"))
                    mask=(lon>=W-1e-5)&(lon<=E+1e-5)&(lat>=S-1e-5)&(lat<=N+1e-5)
                    x=np.rint((lon[mask]-W)/RES).astype(int)
                    y=np.rint((N-lat[mask])/RES).astype(int)
                    raw=np.asarray(codes_get_array(g,"values"))[mask]
                    if len(raw)!=np.prod(SHAPE): raise ValueError("Incomplete crop")
                    good=np.isfinite(raw)&(abs(raw)<1e20)&(raw!=9999)
                    if name=="cape": good&=(raw>=0)&(raw<=15000)
                    elif name=="rh": good&=(raw>=0)&(raw<=105)
                    elif name in ("u","v","u100","v100"): good&=(abs(raw)<=150)
                    elif name=="terrain": good&=(raw>=-500)&(raw<=9000)
                    elif name=="cin": good&=(abs(raw)<=3000)
                    if good.mean()<.8: raise ValueError("Incomplete "+name)
                    a=np.full(SHAPE,np.nan,dtype=np.float32)
                    a[y[good],x[good]]=raw[good]
                    out[name]=a
                    print(pkg,h,name,key(g,"shortName"),key(g,"units"),flush=True)
                finally: codes_release(g)
    return out

def smooth(a,n=5):
    valid=np.isfinite(a)
    weight=uniform_filter(valid.astype(np.float32),size=n,mode="constant")
    num=uniform_filter(np.where(valid,a,0).astype(np.float32),size=n,mode="constant")
    return np.divide(num,weight,out=np.full_like(num,np.nan),where=weight>=.8)

def forcing(u,v,terrain=None):
    us,vs=smooth(u),smooth(v)
    dx=(111195*RES*np.cos(np.deg2rad(N-np.arange(u.shape[0])*RES)))[:,None]
    dy=111195*RES
    conv=-(np.gradient(us,axis=1)/dx-np.gradient(vs,axis=0)/dy)
    lift=None
    if terrain is not None:
        z=smooth(terrain,9)
        lift=us*np.gradient(z,axis=1)/dx-vs*np.gradient(z,axis=0)/dy
    return conv,lift

def diagnose(cape,u,v,rh,cin=None,u100=None,v100=None,terrain=None):
    # 5-point smoothing then finite differences on latitude-dependent metric grid.
    us,vs=smooth(u),smooth(v)
    dx=(111195*RES*np.cos(np.deg2rad(N-np.arange(u.shape[0])*RES)))[:,None]
    dy=111195*RES
    conv=-(np.gradient(us,axis=1)/dx-np.gradient(vs,axis=0)/dy)
    valid=np.isfinite(cape)&np.isfinite(conv)&np.isfinite(rh)
    # Thresholds are experimental, not probabilities; CIN is only a veto when known.
    cap=np.zeros_like(valid) if cin is None else np.isfinite(cin)&(abs(cin)>=150)
    low=valid&~cap&(cape>=150)&(conv>=2e-4)&(rh>=55)
    high=low&(cape>=500)&(conv>=4e-4)&(rh>=65)
    if u100 is not None and v100 is not None:
        upper,lift=forcing(u100,v100,terrain)
        coherent=valid&~cap&(cape>=150)&(rh>=55)&(conv>=1e-4)&(upper>=2e-4)
        low |= coherent
        high |= coherent&(cape>=500)&(rh>=65)&(upper>=4e-4)&(conv>=2e-4)
        if lift is not None:
            slope=valid&~cap&(cape>=250)&(rh>=60)&(lift>=.25)&(upper>=0)&(conv>=-1e-4)
            low |= slope
            high |= slope&(cape>=700)&(rh>=65)&(lift>=.5)&(conv>=1e-4)
    return valid,conv,low,high

def optional_fields(run,h,pkg,tmp):
    try: return fields(run,h,pkg,tmp)
    except Exception as e:
        print("Optional",pkg,h,str(e),flush=True)
        return {}

def frame(run,h,tmp,terrain=None):
    a=fields(run,h,"SP1",tmp)
    b=fields(run,h,"SP2",tmp)
    if not {"u","v","rh"}<=a.keys() or "cape" not in b: raise ValueError("Required fields missing")
    upper=optional_fields(run,h,"HP1",tmp) if exists(run,h,"HP1") else {}
    upper_available={"u100","v100"}<=upper.keys()
    valid,conv,low,high=diagnose(b["cape"],a["u"],a["v"],a["rh"],b.get("cin"),upper.get("u100"),upper.get("v100"),terrain)
    sources={"convergence_100m":upper_available,"orographic_lift_proxy":upper_available and terrain is not None,"vertical_velocity":False}
    coverage=float(valid.mean())
    if coverage<.8: raise ValueError("Insufficient joint coverage")
    ny,nx=SHAPE[0]//BLOCK,SHAPE[1]//BLOCK
    def count(x): return x[:ny*BLOCK,:nx*BLOCK].reshape(ny,BLOCK,nx,BLOCK).sum(axis=(1,3))
    lc,hc,vc=count(low),count(high),count(valid)
    ys,xs=np.where((lc>=3)&(vc>=20))
    cells=[[int(x),int(y),2 if hc[y,x]>=3 else 1] for y,x in zip(ys,xs)]
    filename=f"init-{run:%Y%m%d%H}-h{h:02d}.json"
    doc={"schema":1,"run_utc":run.isoformat(),"valid_utc":(run+timedelta(hours=h)).isoformat(),"coverage":round(coverage,4),"cin_available": "cin" in b,"sources":sources,"cells":cells}
    (OUT/filename).write_text(json.dumps(doc,separators=(",",":")))
    print(h,"coverage",coverage,"candidates",len(cells),flush=True)
    return {"hour":h,"valid_utc":doc["valid_utc"],"file":filename,"coverage":doc["coverage"],"cin_available":doc["cin_available"],"sources":sources}

def main():
    OUT.mkdir(exist_ok=True)
    now=datetime.now(timezone.utc)
    anchor=now.replace(hour=now.hour//3*3,minute=0,second=0,microsecond=0)
    for age in range(0,7):
        run=anchor-timedelta(hours=age*3)
        start=max(1,int((now-run).total_seconds()//3600)+1)
        hours=list(range(start,start+7))
        if all(exists(run,h,p) for h in (hours[0],hours[-1]) for p in ("SP1","SP2")): break
    else: raise RuntimeError("No complete recent HD cycle for next six hours")
    previous=Path("previous-initiation.json")
    if previous.exists():
        try:
            old=json.loads(previous.read_text())
            if old.get("run_utc")==run.isoformat() and old.get("diagnostic_version")==2 and {f["hour"] for f in old["frames"]}.issuperset(hours): return
        except (ValueError,KeyError): pass
    with TemporaryDirectory() as tmp,ThreadPoolExecutor(max_workers=2) as pool:
        terrain=optional_fields(run,hours[0],"SP3",tmp).get("terrain")
        frames=list(pool.map(lambda h:frame(run,h,tmp,terrain),hours))
    doc={"schema":1,"diagnostic_version":2,"run_utc":run.isoformat(),"generated_utc":now.isoformat(),"source":"Météo-France ARÔME 0.01 SP1/SP2","bounds":[W,E,S,N],"resolution_degrees":RES*BLOCK,"origin":[W,N],"diagnostic":"experimental uncalibrated MUCAPE + 10m convergence + 2m RH + optional 100m convergence and terrain lift proxy","frames":frames}
    (OUT/"manifest.json").write_text(json.dumps(doc,indent=2))

if __name__=="__main__": main()
