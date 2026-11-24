#!/usr/bin/env python3
"""Independent ICON-EU daily maps from DWD native regular-grid GRIB2."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.request import Request, urlopen
from urllib.error import HTTPError
from tempfile import TemporaryFile, TemporaryDirectory
import bz2, json, os, shutil, re
import numpy as np
import matplotlib
matplotlib.use("Agg")
from eccodes import codes_grib_new_from_file, codes_get, codes_get_array, codes_release
from france_daily import render_daily, PARIS, iso
from kfs_zoom_detail import native as zoom_native
from probe_dwd_icon_eu import BASE
OUT=Path("forecast-maps/france/shortterm-daily")
FIELDS={"t_2m":"instant","vmax_10m":"max","tot_prec":"accum"}
HORIZON=48
UA={"User-Agent":"KFS-Meteo-DWD-Daily/1.0"}

def url(run,field,h):
    return BASE+run.strftime("%H")+"/"+field+"/icon-eu_europe_regular-lat-lon_single-level_"+run.strftime("%Y%m%d%H")+f"_{h:03d}_{field.upper()}.grib2.bz2"

def cycle():
    now=datetime.now(timezone.utc)
    start=now.replace(hour=now.hour//3*3,minute=0,second=0,microsecond=0)
    for lag in range(6):
        run=start-timedelta(hours=3*lag)
        stamp=run.strftime("%Y%m%d%H")
        try:
            for field in FIELDS:
                directory=BASE+run.strftime("%H")+"/"+field+"/"
                with urlopen(Request(directory,headers=UA),timeout=30) as r:
                    listing=r.read(2*1024*1024).decode("utf-8")
                required=range(0 if field=="t_2m" else 1,HORIZON+1)
                missing=[h for h in required if url(run,field,h).rsplit("/",1)[1] not in listing]
                if missing:
                    print("KFS_DWD_INCOMPLETE_CYCLE",stamp,field,missing,flush=True)
                    break
            else:
                print("KFS_DWD_COMPLETE_CYCLE",stamp,flush=True)
                return run
        except HTTPError as e:
            if e.code!=404:raise
    raise RuntimeError("No recent full hourly 48h ICON-EU cycle")

def step_hours(value):
    # ecCodes newer releases may return '0m', '60m' or '1h'.
    if isinstance(value,(int,float)):return float(value)
    match=re.fullmatch(r"([0-9]+(?:\.[0-9]+)?)([smhd]?)",str(value).strip())
    if not match:raise ValueError("Unknown GRIB step "+str(value))
    return float(match[1])*{"":1,"h":1,"m":1/60,"s":1/3600,"d":24}[match[2]]

def read_field(run,field,h):
    try:
        with urlopen(Request(url(run,field,h),headers=UA),timeout=60) as r:
            b=r.read(16*1024*1024+1)
    except HTTPError as exc:
        raise RuntimeError(f"DWD {run.isoformat()} {field} +{h}h: HTTP {exc.code}") from exc
    if len(b)>16*1024*1024:raise ValueError("Oversized GRIB")
    with TemporaryFile() as f:
        f.write(bz2.decompress(b));f.seek(0)
        g=codes_grib_new_from_file(f)
        if g is None:raise ValueError("Invalid GRIB")
        try:
            get=lambda k:codes_get(g,k)
            if (int(get("dataDate"))!=int(run.strftime("%Y%m%d")) or int(get("dataTime"))!=run.hour*100
                or step_hours(get("endStep"))!=h or get("stepType")!=(FIELDS.get(field,"instant")) or get("gridType")!="regular_ll"):
                raise ValueError("Unexpected run, lead, interval or grid")
            a=np.asarray(codes_get_array(g,"latitudes"))
            b=np.asarray(codes_get_array(g,"longitudes"))
            b=(b+180)%360-180
            mask=(a>=40.5)&(a<=52)&(b>=-7)&(b<=11)
            a,b=a[mask],b[mask]
            v=np.asarray(codes_get_array(g,"values"))[mask]
            ys,xs=np.unique(a),np.unique(b)
            if len(v)!=len(xs)*len(ys) or not np.isfinite(v).all() or np.max(np.abs(v))>1e6:
                raise ValueError("Incomplete French native grid")
            order=np.lexsort((b,a))
            return (xs,ys,v[order].reshape(len(ys),len(xs)),step_hours(get("startStep")),str(get("units")))
        finally:codes_release(g)

def optional_weather(run,h,lon,lat):
    try:
        x,y,v,_,_=read_field(run,"ww",h)
        if not np.array_equal(x,lon) or not np.array_equal(y,lat):
            raise ValueError("Weather grid differs")
        return h,v
    except Exception as exc:
        print("KFS_DWD_WW_MISSING",h,str(exc)[:120],flush=True)
        return h,None

def daily_codes(weather,hs,shape):
    from kfs_weather_symbols import PRIORITY,kind
    best=np.full(shape,np.nan)
    rank=np.full(shape,-1,dtype=int)
    for h in hs:
        values=weather.get(h)
        if values is None:continue
        for raw in np.unique(values):
            mode=kind(raw)
            if mode is None:continue
            p=PRIORITY[mode]
            mask=(values==raw)&(p>rank)
            best[mask]=raw;rank[mask]=p
    return best if np.isfinite(best).any() else None

def main():
    OUT.mkdir(parents=True,exist_ok=True)
    cat=OUT/"latest.json"
    doc=json.loads(cat.read_text()) if cat.exists() else {"schema":1,"models":{}}
    run=cycle()
    old=doc.get("models",{}).get("icon_eu",{})
    if old.get("source")=="DWD Open Data" and old.get("run_utc")==run.isoformat() and os.getenv("KFS_FORCE")!="1" and all(v.get("maps",{}).get("tmin",{}).get("detail") for v in old.get("days",{}).values()):
        print("KFS_DWD_DAILY_NO_NEW_RUN",run.isoformat());return
    jobs=[(f,h) for f in FIELDS for h in range(0 if f=="t_2m" else 1,HORIZON+1)]
    with ThreadPoolExecutor(max_workers=4) as pool:
        rows=dict(zip(jobs,pool.map(lambda p:read_field(run,*p),jobs)))
    lon,lat=rows[("t_2m",0)][:2]
    for (field,h),(x,y,v,s,unit) in rows.items():
        if not np.array_equal(x,lon) or not np.array_equal(y,lat):raise ValueError("Grid changed")
        if field=="t_2m" and unit!="K":raise ValueError("Temperature unit "+unit)
        if field=="vmax_10m" and (unit!="m s**-1" or s!=h-1):raise ValueError("Gust interval/unit")
        if field=="tot_prec" and unit!="kg m**-2":raise ValueError("Precipitation unit "+unit)
    with ThreadPoolExecutor(max_workers=4) as pool:
        weather=dict(pool.map(lambda h:optional_weather(run,h,lon,lat),range(1,HORIZON+1)))
    increments={}
    for h in range(1,HORIZON+1):
        _,_,v,s,_=rows[("tot_prec",h)]
        if s==h-1:delta=v
        elif s==0 and h>1 and rows[("tot_prec",h-1)][3]==0:delta=v-rows[("tot_prec",h-1)][2]
        else:raise ValueError("Unsupported precipitation interval")
        if np.min(delta)<-.15:raise ValueError("Unexpected precipitation reset")
        increments[h]=np.maximum(delta,0)
    today=datetime.now(PARIS).date()
    end=run+timedelta(hours=HORIZON)
    days={}
    with TemporaryDirectory() as tmp:
        staged=[]
        for d in range(3):
            day=today+timedelta(days=d)
            left=datetime(day.year,day.month,day.day,tzinfo=PARIS).astimezone(timezone.utc)
            right=(left.astimezone(PARIS)+timedelta(days=1)).astimezone(timezone.utc)
            begin,finish=max(left,run),min(right,end)
            hours=int((finish-begin).total_seconds()/3600)
            if hours<4:continue
            hs=[h for h in range(1,HORIZON+1) if begin<run+timedelta(hours=h)<=finish]
            ts=[h for h in range(HORIZON+1) if begin<=run+timedelta(hours=h)<finish]
            if len(hs)!=hours or len(ts)!=hours:raise ValueError("Missing hourly data")
            coverage="complete" if begin==left and finish==right else "partial"
            t=np.stack([rows[("t_2m",h)][2]-273.15 for h in ts])
            metrics={"tmin":t.min(0),"tmax":t.max(0),
                "gust":np.maximum.reduce([rows[("vmax_10m",h)][2]*3.6 for h in hs]),
                "precip":np.sum([increments[h] for h in hs],axis=0)}
            maps={}
            wx=daily_codes(weather,hs,t.shape[1:])
            for metric,v in metrics.items():
                note="DWD Open Data · grille native ICON-EU · "+("journée complète" if coverage=="complete" else "période partielle")
                if metric in ("tmin","tmax"):note+=" · extrema des températures horaires"
                if metric in ("tmin","tmax"):
                    note+=" · pictos WW DWD (heures disponibles)" if wx is not None else " · temps sensible indisponible"
                detail=zoom_native(lon,lat,v) if metric in ("tmin","tmax") else None
                p=Path(render_daily(lon,lat,v,metric,"ICON-EU",run,day,tmp,note,weather=wx,detail=detail))
                name=f"daily-icon_eu-{metric}-d{d}.png"
                dest=Path(tmp)/name;p.rename(dest)
                if dest.stat().st_size<12000:raise ValueError("Invalid render")
                staged.append(dest)
                maps[metric]={"filename":name,"size_bytes":dest.stat().st_size,"date":day.isoformat(),
                    "coverage":coverage,"weather_codes_available":bool(wx is not None) if metric in ("tmin","tmax") else False,"url":"https://almet27.github.io/kfs-meteo-cartes/forecast-maps/france/shortterm-daily/"+name}
                if detail is not None:maps[metric]["detail"]=detail
            days[str(d)]={"date":day.isoformat(),"coverage":coverage,"start_utc":iso(begin),"end_utc":iso(finish),"hours":hours,"maps":maps}
        if not days:raise RuntimeError("No valid calendar days")
        for p in staged:shutil.copy2(p,OUT/p.name)
    now=datetime.now(timezone.utc).isoformat()
    doc.setdefault("models",{})["icon_eu"]={"name":"icon_eu","source":"DWD Open Data","native_grid":True,
        "run_utc":run.isoformat(),"generated_utc":now,"days":days,
        "notes":"Temperature extrema from hourly native fields; gust hourly maxima; precipitation increments from native GRIB."}
    doc["generated_utc"]=now
    doc["source"]="ARÔME via Open-Meteo ; ICON-EU via DWD Open Data"
    cat.write_text(json.dumps(doc,ensure_ascii=False,indent=2)+"\n")
    print("KFS_DWD_DAILY_OK",run.isoformat(),len(days),"days",len(lon),len(lat),"native grid")

if __name__=="__main__":main()
