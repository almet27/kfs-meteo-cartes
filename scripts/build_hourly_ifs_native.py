#!/usr/bin/env python3
"""Native IFS fallback for the sampled KFS timeline, with explicit temporal approximation."""
import json, math, tempfile
from datetime import datetime, timezone, timedelta
from pathlib import Path
import numpy as np
from ecmwf.opendata import Client
from eccodes import codes_grib_new_from_file, codes_get, codes_get_array, codes_release

ROOT=Path("forecast-maps/france/hourly-web")
STEPS=list(range(3,73,3))
FIELDS=["temperature_2m","wind_speed_10m","wind_gusts_10m","precipitation","wind_direction_10m","weather_code"]
def utc(x):
    d=x if isinstance(x,datetime) else datetime.fromisoformat(str(x).replace("Z","+00:00"))
    return d.replace(tzinfo=timezone.utc) if d.tzinfo is None else d.astimezone(timezone.utc)
def key(g,k,default=None):
    try:return codes_get(g,k)
    except Exception:return default
def extract(client,cycle,param,points,tmp,optional=False):
    p=tmp/(param+".grib2")
    result={}
    try:
        client.retrieve(stream="oper",type="fc",date=cycle.strftime("%Y-%m-%d"),time=cycle.hour,
                        step=STEPS,param=param,target=str(p))
        with p.open("rb") as fh:
            while (g:=codes_grib_new_from_file(fh)) is not None:
                try:
                    step=int(key(g,"endStep",-1))
                    if step not in STEPS or step in result:raise ValueError("Unexpected/duplicate forecast step")
                    if key(g,"dataDate")!=int(cycle.strftime("%Y%m%d")) or key(g,"dataTime")!=cycle.hour*100:
                        raise ValueError("GRIB cycle mismatch")
                    ni,nj=int(codes_get(g,"Ni")),int(codes_get(g,"Nj"))
                    lat=np.asarray(codes_get_array(g,"latitudes")).reshape(nj,ni)
                    lon=np.asarray(codes_get_array(g,"longitudes")).reshape(nj,ni)
                    if not np.allclose(lat,lat[:,0,None]) or not np.allclose(lon,lon[0,None,:]):
                        raise ValueError("Unsupported nonregular grid")
                    yy=np.abs(lat[:,0,None]-points[:,1]).argmin(axis=0)
                    delta=(lon[0,:,None]-points[:,0]+180)%360-180
                    xx=np.abs(delta).argmin(axis=0)
                    if np.max(np.abs(lat[yy,xx]-points[:,1]))>.16 or np.max(np.abs(delta[xx,np.arange(len(points))]))>.16:
                        raise ValueError("Insufficient grid coverage")
                    val=np.asarray(codes_get_array(g,"values"),dtype=float).reshape(nj,ni)[yy,xx]
                    missing=key(g,"missingValue",9999)
                    val[(val==missing)|~np.isfinite(val)]=np.nan
                    result[step]=(val,str(key(g,"units","")),int(key(g,"startStep",-1)))
                finally:codes_release(g)
        if set(result)!=set(STEPS):raise ValueError("Incomplete GRIB steps for "+param)
        return result
    except Exception as exc:
        if not optional:raise
        print("Optional field unavailable",param,str(exc)[:200],flush=True)
        return {}
    finally:p.unlink(missing_ok=True)
def convert(d,kind):
    out={}
    for step,(a,unit,start) in d.items():
        if kind=="temp" and unit=="K":a=a-273.15
        elif kind=="wind" and unit in ("m s**-1","m s-1","m/s"):a=a*3.6
        elif kind=="precip" and unit in ("m","m of water equivalent"):a=a*1000
        elif kind=="precip" and unit in ("kg m**-2","kg m-2","mm"):pass
        else:raise ValueError("Unexpected units "+kind+" "+unit)
        out[step]=(a,start)
    return out
def intervals(d):
    out={}
    for step in STEPS:
        a,start=d[step]
        if start==step-3:diff=a
        elif start==0:
            if step==3:diff=a
            elif d[step-3][1]==0:diff=a-d[step-3][0]
            else:raise ValueError("Previous accumulation not cumulative")
        else:raise ValueError("Unsupported accumulation interval")
        if np.nanmin(diff)<-.15:raise ValueError("Negative precipitation interval")
        out[step]=np.maximum(diff,0)/3
    return out
def main():
    old=json.loads((ROOT/"ifs.json").read_text())
    points=np.asarray(old["points"],dtype=float)
    if points.ndim!=2 or points.shape[1]!=2 or len(points)<100:raise ValueError("Invalid KFS sampling points")
    now=datetime.now(timezone.utc)
    client=Client(source="ecmwf",model="ifs",resol="0p25")
    cycle=utc(client.latest(stream="oper",type="fc",step=72,param="2t"))
    if not timedelta(0)<=now-cycle<timedelta(hours=24):raise ValueError("IFS cycle too old")
    dest=ROOT/"ifs-native.json"
    if dest.exists():
        prev=json.loads(dest.read_text())
        if utc(prev["run_utc"])>=cycle and now-utc(prev["fetched_utc"])<timedelta(hours=12):
            print("Native IFS cycle already available",cycle.isoformat());return
    with tempfile.TemporaryDirectory() as t:
        tmp=Path(t)
        T=convert(extract(client,cycle,"2t",points,tmp),"temp")
        U=convert(extract(client,cycle,"10u",points,tmp),"wind")
        V=convert(extract(client,cycle,"10v",points,tmp),"wind")
        P=intervals(convert(extract(client,cycle,"tp",points,tmp),"precip"))
        G=extract(client,cycle,"10fg",points,tmp,optional=True)
        if not G:G=extract(client,cycle,"10fg3",points,tmp,optional=True)
        try:G=convert(G,"wind")
        except ValueError:G={}
    def interp(d,h):
        lo=h//3*3;hi=((h+2)//3)*3
        if lo not in d or hi not in d:return np.full(len(points),np.nan)
        return d[lo][0] if lo==hi else d[lo][0]*(hi-h)/3+d[hi][0]*(h-lo)/3
    def clean(v):return round(float(v),3) if math.isfinite(v) else None
    hours=list(range(3,73))
    rows=[[] for _ in points]
    for h in hours:
        t,u,v=interp(T,h),interp(U,h),interp(V,h)
        speed=np.hypot(u,v);direction=(270-np.degrees(np.arctan2(v,u)))%360
        upper=((h+2)//3)*3
        precip=P[upper]
        # The native interval maximum is only a 3-hour diagnostic, not hourly gust.
        gust=G[upper][0] if h%3==0 and upper in G and G[upper][1] in (upper-3,upper) else np.full(len(points),np.nan)
        if np.isfinite(t).sum()<len(points)*.8:raise ValueError("Temperature coverage incomplete")
        for i in range(len(points)):
            rows[i].append([clean(t[i]),clean(speed[i]),clean(gust[i]),clean(precip[i]),clean(direction[i]),None])
    doc={"schema":1,"model":"ifs","provider":"ECMWF Open Data","run_utc":cycle.isoformat(),
         "fetched_utc":datetime.now(timezone.utc).isoformat(),"points":points.tolist(),
         "times":[(cycle+timedelta(hours=h)).isoformat() for h in hours],"rows":rows,
         "fields":FIELDS,"grid_degrees":.58,"native_grid_degrees":.25,
         "temporal_method":"temperature/wind linear interpolation; 3-hour total precipitation divided equally among hours; native gust at interval end only; no weather code"}
    temp=dest.with_suffix(".tmp");temp.write_text(json.dumps(doc,separators=(",",":"),allow_nan=False));temp.replace(dest)
    print("IFS native ready",cycle.isoformat(),len(points),len(hours),flush=True)
if __name__=="__main__":main()
