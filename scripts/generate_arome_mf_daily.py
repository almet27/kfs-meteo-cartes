#!/usr/bin/env python3
"""Cartes ARÔME direct Météo-France, paquets SP1 0,025°, via data.gouv.fr.
Publication atomique uniquement après décodage et validation du cycle complet.
"""
from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from urllib.request import Request, urlopen
from urllib.parse import unquote
import json, os, re, shutil
import numpy as np
import matplotlib
matplotlib.use("Agg")
from eccodes import codes_grib_new_from_file, codes_get, codes_get_array, codes_release
from france_daily import render_daily, PARIS, iso
from kfs_zoom_detail import native as zoom_native, native_weather

CATALOG="https://www.data.gouv.fr/api/1/datasets/paquets-arome-resolution-0-025deg/"
OUT=Path("forecast-maps/france/shortterm-daily")
UA={"User-Agent":"KFS-Meteo-Arome/1.0","Accept":"*/*"}
GROUPS=[(0,6),(7,12),(13,18),(19,24),(25,30),(31,36),(37,42),(43,48)]
NAME=re.compile(r"arome__0025__SP1__(\d{2})H(\d{2})H__(\d{4}-\d{2}-\d{2}T\d{2}[:%]?(?:3A)?00[:%]?(?:3A)?00Z)\.grib2",re.I)

def get_catalog():
    with urlopen(Request(CATALOG,headers=UA),timeout=30) as r:
        doc=json.load(r)
    cycles={}
    for item in doc.get("resources",[]):
        raw=unquote(str(item.get("title",""))+" "+str(item.get("url","")))
        m=NAME.search(raw)
        if not m:continue
        a,b=int(m[1]),int(m[2])
        stamp=m[3]
        try:run=datetime.fromisoformat(stamp.replace("Z","+00:00"))
        except ValueError:continue
        uri=item.get("url")
        if isinstance(uri,str) and uri.startswith("https://"):
            cycles.setdefault(run,{})[(a,b)]=uri
    # The data.gouv catalog rotates each slot separately. The object store
    # keeps dated files; check missing slots by their exact cycle, never mix runs.
    from concurrent.futures import ThreadPoolExecutor
    now=datetime.now(timezone.utc)
    recent=sorted((r for r in cycles if timedelta(0)<=now-r<=timedelta(hours=20)),reverse=True)
    anchor=now.replace(hour=now.hour//3*3,minute=0,second=0,microsecond=0)
    recent=sorted(set(recent+[anchor-timedelta(hours=3*i) for i in range(1,6)]),reverse=True)
    def direct(run,bounds):
        stamp=run.strftime("%Y-%m-%dT%H:00:00Z")
        a,b=bounds
        return f"https://object.data.gouv.fr/meteofrance-pnt/pnt/{stamp}/arome/0025/SP1/arome__0025__SP1__{a:02d}H{b:02d}H__{stamp}.grib2"
    def probe(run,bounds):
        uri=cycles.get(run,{}).get(bounds) or direct(run,bounds)
        try:
            with urlopen(Request(uri,headers=UA,method="HEAD"),timeout=12) as r:
                if r.status==200 and int(r.headers.get("Content-Length","0"))>1000:return bounds,uri
        except Exception as exc:
            print("KFS_AROME_SLOT_PENDING",run.isoformat(),bounds,str(exc)[:110],flush=True)
        return bounds,None
    partial=[]
    for run in recent:
        with ThreadPoolExecutor(max_workers=4) as pool:
            files=dict(pool.map(lambda b:probe(run,b),GROUPS))
        contiguous={}
        for b in GROUPS:
            if not files.get(b):break
            contiguous[b]=files[b]
        if len(contiguous)==len(GROUPS):
            return run,contiguous
        if len(contiguous)>=3:partial.append((run,contiguous))
    if partial:
        run,files=max(partial,key=lambda x:x[0])
        print("KFS_AROME_PARTIAL_CYCLE",run.isoformat(),max(b for a,b in files),flush=True)
        return run,files
    print("KFS_AROME_CATALOG_CYCLES",[(r.isoformat(),sorted(g)) for r,g in cycles.items()],flush=True)
    raise RuntimeError("No recent coherent SP1 cycle available")

def key(g,k,default=None):
    try:return codes_get(g,k)
    except Exception:return default

def hours(v,unit=1):
    if isinstance(v,(int,float)):
        if int(unit) not in (0,1,2,10,11,12,13):raise ValueError("Unsupported step unit")
        return float(v)*{0:1/60,1:1,2:24,10:3,11:6,12:12,13:1/3600}[int(unit)]
    m=re.fullmatch(r"(\d+(?:\.\d+)?)([smhd]?)",str(v).strip())
    if not m:raise ValueError("Unknown GRIB step "+str(v))
    return float(m[1])*{"":1,"h":1,"m":1/60,"s":1/3600,"d":24}[m[2]]

def field(g):
    sn=str(key(g,"shortName","")).lower()
    param=(key(g,"discipline"),key(g,"parameterCategory"),key(g,"parameterNumber"))
    level=key(g,"level");typ=key(g,"typeOfLevel");step=key(g,"stepType")
    if typ=="heightAboveGround" and level==2 and step=="instant" and (sn in ("2t","t2m","t") or param==(0,0,0)):return "temp"
    if typ=="heightAboveGround" and level==10 and step=="max" and (sn in ("10fg","fg10","fg","gust","gust10m","10fg6") or param==(0,2,22)):return "gust"
    if step=="accum" and (sn in ("tp","apcp") or param==(0,1,8)):return "precip"
    if step=="accum" and (sn in ("sf","asnow","snowfall","tsnowp") or param==(0,1,13)):return "snow"
    if step in ("instant","avg") and (sn in ("tcc","tcdc") or param==(0,6,1)):return "cloud"
    return None

class Grid:
    def __init__(self,g):
        if key(g,"gridType")!="regular_ll":raise ValueError("Not a regular native grid")
        a=np.asarray(codes_get_array(g,"latitudes"));b=(np.asarray(codes_get_array(g,"longitudes"))+180)%360-180
        mask=(a>=40.5)&(a<=52)&(b>=-7)&(b<=11)
        self.indices=np.flatnonzero(mask);a=a[mask];b=b[mask]
        self.lon=np.unique(b);self.lat=np.unique(a)
        if len(a)!=len(self.lon)*len(self.lat) or min(len(self.lon),len(self.lat))<400:raise ValueError("Unexpected 0.025 degree French grid")
        if not np.allclose(np.diff(self.lon),.025,atol=1e-5) or not np.allclose(np.diff(self.lat),.025,atol=1e-5):raise ValueError("Unexpected native resolution")
        self.order=np.lexsort((b,a))
        self.signature=tuple(key(g,k) for k in ("Ni","Nj","latitudeOfFirstGridPoint","longitudeOfFirstGridPoint","latitudeOfLastGridPoint","longitudeOfLastGridPoint","scanningMode"))
    def values(self,g):
        sig=tuple(key(g,k) for k in ("Ni","Nj","latitudeOfFirstGridPoint","longitudeOfFirstGridPoint","latitudeOfLastGridPoint","longitudeOfLastGridPoint","scanningMode"))
        if sig!=self.signature:raise ValueError("Grid changed")
        a=np.asarray(codes_get_array(g,"values"))[self.indices][self.order].reshape(len(self.lat),len(self.lon))
        missing=key(g,"missingValue",9999)
        a=np.where((a==missing)|(~np.isfinite(a))|(np.abs(a)>1e6),np.nan,a)
        if np.isfinite(a).mean()<.8:raise ValueError("Incomplete France field")
        return a.astype(np.float32)

def read_group(uri,run,bounds,grid,rows,tmp):
    file=Path(tmp)/"packet.grib2"
    with urlopen(Request(uri,headers=UA),timeout=100) as r, file.open("wb") as out:
        shutil.copyfileobj(r,out,1024*1024)
    if file.stat().st_size<1000:raise ValueError("Empty GRIB")
    inventory=set()
    with file.open("rb") as f:
        while (g:=codes_grib_new_from_file(f)) is not None:
            try:
                inventory.add((str(key(g,"shortName")),str(key(g,"typeOfLevel")),str(key(g,"level")),str(key(g,"stepType")),str(key(g,"units"))))
                k=field(g)
                if k is None:continue
                if int(key(g,"dataDate",0))!=int(run.strftime("%Y%m%d")) or int(key(g,"dataTime",-1))!=run.hour*100:raise ValueError("Different run in packet")
                unit=key(g,"stepUnits",1)
                h=hours(key(g,"endStep"),unit);s=hours(key(g,"startStep"),unit)
                if h!=int(h) or not bounds[0]<=h<=bounds[1]:raise ValueError("Wrong lead")
                h=int(h)
                if h==0 and k in ("gust","precip","snow"):continue
                units=str(key(g,"units",""))
                if k=="temp" and units!="K":raise ValueError("Temperature unit "+units)
                if k=="gust" and units not in ("m s**-1","m s-1","m/s"):raise ValueError("Gust unit "+units)
                if k in ("precip","snow") and units not in ("kg m**-2","kg m-2","mm","m"):continue
                if k=="cloud" and units not in ("%","(0 - 1)","1","Proportion"):
                    if (key(g,"discipline"),key(g,"parameterCategory"),key(g,"parameterNumber"))!=(0,6,1) or units!="unknown":continue
                    # WMO 4.2: 0/6/1 = total cloud cover in percent, including ecCodes unknown shortName.
                    units="%"
                if grid is None:grid=Grid(g)
                a=grid.values(g)
                if k=="temp":a-=273.15
                elif k=="gust":a*=3.6
                elif k in ("precip","snow") and units=="m":a*=1000
                elif k=="cloud":
                    if units=="%":
                        if np.nanmin(a)<-.1 or np.nanmax(a)>100.1:raise ValueError("Cloud cover outside percent range")
                        a/=100
                    elif np.nanmin(a)<-.01 or np.nanmax(a)>1.01:raise ValueError("Cloud fraction outside range")
                if (k,h) in rows:raise ValueError("Duplicate field "+str((k,h)))
                rows[k,h]=(a,s)
            finally:codes_release(g)
    print("KFS_AROME_SP1_INVENTORY",bounds,sorted(inventory),flush=True)
    print("KFS_AROME_DECODED",bounds,{k:sum(1 for f,h in rows if f==k) for k in ("temp","cloud","snow","precip")},flush=True)
    file.unlink()
    return grid

def increments(rows,k,horizon):
    output={}
    for h in range(1,horizon+1):
        a,s=rows[k,h]
        if s==h-1 or (h==1 and s==0):v=a
        elif s==0 and rows[k,h-1][1]==0:v=a-rows[k,h-1][0]
        else:raise ValueError("Unknown accumulation interval "+str((k,h,s)))
        if np.nanmin(v)<-.15:raise ValueError("Negative accumulation")
        output[h]=np.maximum(v,0)
    return output

def main():
    OUT.mkdir(parents=True,exist_ok=True)
    catalog=OUT/"latest.json"
    doc=json.loads(catalog.read_text()) if catalog.exists() else {"schema":1,"models":{}}
    run,files=get_catalog()
    horizon=max(b for a,b in files)
    old=doc.get("models",{}).get("arome",{})
    if old.get("source")=="Météo-France Open Data" and old.get("run_utc")==run.isoformat() and old.get("horizon_hours",0)>=horizon and os.getenv("KFS_FORCE")!="1" and all((v.get("maps",{}).get("tmin",{}).get("detail",{}).get("weather") or {}).get("count",0)>0 for v in old.get("days",{}).values()):
        print("KFS_AROME_NO_NEW_RUN",run.isoformat());return
    rows={};grid=None
    with TemporaryDirectory() as tmp:
        for bounds in files:
            grid=read_group(files[bounds],run,bounds,grid,rows,tmp)
        for k in ("temp","gust","precip"):
            required=range(0 if k=="temp" else 1,horizon+1)
            missing=[h for h in required if (k,h) not in rows]
            if missing:raise RuntimeError("Incomplete "+k+" leads "+str(missing))
        for h in range(1,horizon+1):
            if rows["gust",h][1]!=h-1:raise RuntimeError("Gust is not an hourly maximum")
        precip=increments(rows,"precip",horizon)
        try:snow=increments(rows,"snow",horizon)
        except (KeyError,ValueError):snow=None
        today=datetime.now(PARIS).date();days={};staged=[]
        for d in range(3):
            day=today+timedelta(days=d);tomorrow=day+timedelta(days=1)
            left=datetime(day.year,day.month,day.day,tzinfo=PARIS).astimezone(timezone.utc)
            right=datetime(tomorrow.year,tomorrow.month,tomorrow.day,tzinfo=PARIS).astimezone(timezone.utc)
            begin,end=max(left,run),min(right,run+timedelta(hours=horizon))
            duration=int((end-begin).total_seconds()/3600)
            if duration<4:continue
            hs=[h for h in range(1,horizon+1) if begin<run+timedelta(hours=h)<=end]
            ts=[h for h in range(horizon+1) if begin<=run+timedelta(hours=h)<end]
            if len(hs)!=duration or len(ts)!=duration:raise ValueError("Incomplete calendar interval")
            coverage="complete" if begin==left and end==right else "partial"
            total=np.sum([precip[h] for h in hs],axis=0)
            metrics={"tmin":np.minimum.reduce([rows["temp",h][0] for h in ts]),"tmax":np.maximum.reduce([rows["temp",h][0] for h in ts]),"gust":np.maximum.reduce([rows["gust",h][0] for h in hs]),"precip":total}
            wx=None
            if snow is not None and all(("cloud",h) in rows for h in hs):
                cloud=np.mean([rows["cloud",h][0] for h in hs],axis=0)
                solid=np.sum([snow[h] for h in hs],axis=0)
                wx=np.where(cloud<.25,0,np.where(cloud<.75,2,3)).astype(float)
                wx=np.where(total>=.5,61,wx)
                wx=np.where((solid>=.2)&(solid>=total*.5),71,wx)
                wx=np.where((solid>=.2)&(total-solid>=.5)&(solid<total*.5),100,wx)
                wx=np.where(np.isfinite(cloud)&np.isfinite(total)&np.isfinite(solid),wx,np.nan)
            maps={}
            for metric,v in metrics.items():
                note="Source : Météo-France · ARÔME 0,025° · "+("journée civile complète" if coverage=="complete" else f"période partielle ({duration} h)")
                if metric in ("tmin","tmax"):
                    note+=" · extrema horaires"
                    if wx is not None:note+=" · pictogrammes diagnostiques"
                # Les pictogrammes sont échantillonnés à pas de 0,125° pour limiter les allocations du placement.
                weather=None
                if wx is not None and metric in ("tmin","tmax"):
                    weather=np.full_like(wx,np.nan);weather[::5,::5]=wx[::5,::5]
                detail=zoom_native(grid.lon,grid.lat,v) if metric in ("tmin","tmax") else None
                if detail is not None:
                    detail["weather"]=native_weather(grid.lon,grid.lat,wx)
                    if wx is not None and not detail["weather"]:raise RuntimeError("Weather detail unexpectedly empty")
                p=Path(render_daily(grid.lon,grid.lat,v,metric,"ARÔME 2,5 km",run,day,tmp,note,weather=weather,detail=detail))
                name=f"daily-arome-{metric}-d{d}.png"
                dest=Path(tmp)/name;p.rename(dest)
                if dest.stat().st_size<12000:raise ValueError("Invalid image")
                staged.append(dest)
                maps[metric]={"filename":name,"size_bytes":dest.stat().st_size,"date":day.isoformat(),"coverage":coverage,"url":"https://almet27.github.io/kfs-meteo-cartes/forecast-maps/france/shortterm-daily/"+name}
                if detail is not None:maps[metric]["detail"]=detail
            days[str(d)]={"date":day.isoformat(),"coverage":coverage,"start_utc":iso(begin),"end_utc":iso(end),"hours":duration,"maps":maps}
        if not days:raise RuntimeError("No valid current days")
        for p in staged:shutil.copy2(p,OUT/p.name)
    now=datetime.now(timezone.utc).isoformat()
    doc.setdefault("models",{})["arome"]={"name":"ARÔME","source":"Météo-France Open Data","native_grid":True,"resolution_degrees":.025,"horizon_hours":horizon,"run_utc":run.isoformat(),"generated_utc":now,"days":days}
    doc.update(generated_utc=now,source="Sources par modèle : Météo-France / DWD / Open-Meteo")
    catalog.write_text(json.dumps(doc,ensure_ascii=False,indent=2)+"\n")
    print("KFS_AROME_NATIVE_DAILY_OK",run.isoformat(),len(days),len(grid.lon),len(grid.lat),flush=True)

if __name__=="__main__":main()
