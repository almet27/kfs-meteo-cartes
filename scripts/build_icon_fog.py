#!/usr/bin/env python3
"""Sample direct ICON-EU WW (45/48) for the public KFS hourly map.
Prefer the new DWD native-grid API; support legacy regular grids during migration.
If native data cannot be obtained, publish explicitly labelled ICON-EU Open-Meteo codes.
"""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryFile
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen
import bz2, json, math
import numpy as np
from scipy.spatial import cKDTree
from eccodes import codes_grib_new_from_file, codes_get, codes_get_array, codes_release
from build_hourly_web import points, get, inside
from kfs_weather_cache import check_quota, record_quota
from urllib.error import HTTPError

OUT=Path("forecast-maps/france/hourly-web/icon-fog.json")
BASE="https://opendata.dwd.de/weather/nwp/"
HORIZON=60
UA={"User-Agent":"KFS-Meteo-ICON-WW/1.0"}

def key(g,k,default=None):
    try:return codes_get(g,k)
    except Exception:return default

def native_url(run,field,h):
    return BASE+"v1/m/icon-eu/p/"+field+"/r/"+quote(run.strftime("%Y-%m-%dT%H:00"),safe="")+"/s/PT%03dH00M.grib2"%h

def legacy_url(run,h):
    return BASE+f"icon-eu/grib/{run:%H}/ww/icon-eu_europe_regular-lat-lon_single-level_{run:%Y%m%d%H}_{h:03d}_WW.grib2.bz2"

def read(url,run,h,coords=False):
    with urlopen(Request(url,headers=UA),timeout=35) as r:
        data=r.read(35_000_001)
    if len(data)>35_000_000:raise ValueError("Oversized GRIB")
    with TemporaryFile() as f:
        f.write(bz2.decompress(data) if data.startswith(b"BZh") else data);f.seek(0)
        g=codes_grib_new_from_file(f)
        if g is None:raise ValueError("Missing GRIB")
        try:
            v=np.asarray(codes_get_array(g,"values"))
            grid=(key(g,"gridType"),key(g,"numberOfDataPoints"),key(g,"uuidOfHGrid"))
            if not coords:
                t=run+timedelta(hours=h)
                if (key(g,"dataDate")!=int(run.strftime("%Y%m%d")) or key(g,"dataTime")!=run.hour*100 or
                    key(g,"validityDate")!=int(t.strftime("%Y%m%d")) or key(g,"validityTime")!=t.hour*100):
                    raise ValueError("Wrong WW run/valid hour")
            if coords:
                units=str(key(g,"units","")).lower()
                if units in ("rad","radian","radians"):v=np.degrees(v)
                elif not (units.startswith("degree") or units=="deg"):raise ValueError("Coordinate units")
                return v,grid
            if grid[0]=="regular_ll":
                return v,grid,np.asarray(codes_get_array(g,"longitudes")),np.asarray(codes_get_array(g,"latitudes"))
            return v,grid,None,None
        finally:codes_release(g)

def dense_points():
    geo=get("https://raw.githubusercontent.com/gregoiredavid/france-geojson/master/regions-version-simplifiee.geojson")
    polys=[]
    for f in geo["features"]:
        if str(f["properties"]["code"]) not in {"11","24","27","28","32","44","52","53","75","76","84","93","94"}:continue
        g=f["geometry"]
        polys.extend([g["coordinates"]] if g["type"]=="Polygon" else g["coordinates"])
    boxes=[(p,min(x[0] for x in p[0]),max(x[0] for x in p[0]),min(x[1] for x in p[0]),max(x[1] for x in p[0])) for p in polys]
    return [[x,y] for y in (round(41.5+j*.29,3) for j in range(34)) for x in (round(-5.2+i*.29,3) for i in range(54))
            if any(l<=x<=r and b<=y<=t and inside(x,y,p[0]) and not any(inside(x,y,h) for h in p[1:]) for p,l,r,b,t in boxes)]

def publish(provider,run,pts,times,frames,spacing):
    doc={"schema":1,"model":"icon_eu","provider":provider,"run_utc":run.isoformat() if run else None,
         "fetched_utc":datetime.now(timezone.utc).isoformat(),"grid_degrees":spacing,
         "points_count":len(pts),"times":[t.isoformat() for t in times],"frames":frames}
    OUT.parent.mkdir(parents=True,exist_ok=True)
    tmp=OUT.with_suffix(".tmp");tmp.write_text(json.dumps(doc,separators=(",",":"),allow_nan=False));tmp.replace(OUT)
    print("ICON fog",provider,len(pts),len(times),"hours",sum(map(len,frames)),"fog samples",flush=True)

def direct(now):
    pts=dense_points()
    if len(pts)<500:raise ValueError("Incomplete sampling grid")
    base=now.replace(hour=now.hour//6*6,minute=0,second=0,microsecond=0)
    for lag in range(3):
        run=base-timedelta(hours=6*lag)
        start=max(1,int((now-run).total_seconds()//3600))
        leads=list(range(start,HORIZON+1))
        if len(leads)<25:continue
        for native in (True,False):
            try:
                url=lambda h:native_url(run,"WW",h) if native else legacy_url(run,h)
                first=read(url(leads[0]),run,leads[0])
                last=read(url(leads[-1]),run,leads[-1])
                v,meta,lon,lat=first
                if lon is None:
                    lat,lm=read(native_url(run,"CLAT",0),run,0,True)
                    lon,om=read(native_url(run,"CLON",0),run,0,True)
                    if lm!=om or lm!=meta or not lm[2]:raise ValueError("Native grid identity mismatch")
                lon=(lon+180)%360-180
                if len(lon)!=len(v) or len(lat)!=len(v) or not np.isfinite(lon).all() or not np.isfinite(lat).all():raise ValueError("Bad grid")
                mask=(lon>=-7)&(lon<=11)&(lat>=40)&(lat<=53)
                ids=np.flatnonzero(mask)
                if len(ids)<1000:raise ValueError("French grid missing")
                q=np.array(pts)
                distance,index=cKDTree(np.column_stack((lon[mask]*.67,lat[mask]))).query(np.column_stack((q[:,0]*.67,q[:,1])))
                if np.any(distance>.13):raise ValueError("Insufficient native coverage")
                ids=ids[index]
                def frame(h):
                    a,m,_,_=first if h==leads[0] else last if h==leads[-1] else read(url(h),run,h)
                    if m!=meta or len(a)!=len(v):raise ValueError("Grid changed")
                    vals=a[ids]
                    if np.count_nonzero(np.isfinite(vals)&(vals>=0)&(vals<=99))<len(pts)*.95:raise ValueError("Incomplete WW")
                    return [[*p,int(c)] for p,c in zip(pts,vals) if c in (45,48)]
                with ThreadPoolExecutor(max_workers=4) as pool:frames=list(pool.map(frame,leads))
                publish("DWD Open Data WW",run,pts,[run+timedelta(hours=h) for h in leads],frames,.29)
                return
            except Exception as e:print("WW unavailable",run.isoformat(),native,str(e)[:160],flush=True)
    raise RuntimeError("No complete recent native WW cycle")

def fallback(now):
    check_quota()
    pts=points();start=now.replace(minute=0,second=0,microsecond=0)
    times=[start+timedelta(hours=i) for i in range(49)]
    keys=[t.strftime("%Y-%m-%dT%H:%M") for t in times]
    frames=[[] for _ in times];coverage=[0]*len(times)
    for k in range(0,len(pts),25):
        part=pts[k:k+25]
        q=urlencode({"latitude":",".join(str(p[1]) for p in part),"longitude":",".join(str(p[0]) for p in part),
                     "models":"icon_eu","hourly":"weather_code","forecast_hours":49,"timezone":"GMT","cell_selection":"land"})
        try:rows=get("https://api.open-meteo.com/v1/forecast?"+q)
        except HTTPError as e:record_quota(e);raise
        if isinstance(rows,dict):rows=[rows]
        if len(rows)!=len(part):raise ValueError("Wrong location count")
        for p,r in zip(part,rows):
            h=r.get("hourly",{});by=dict(zip(h.get("time",[]),h.get("weather_code",[])))
            for i,t in enumerate(keys):
                c=by.get(t)
                if isinstance(c,(int,float)) and math.isfinite(c):coverage[i]+=1
                if c in (45,48):frames[i].append([*p,int(c)])
    if min(coverage)<len(pts)*.8:raise ValueError("Incomplete ICON fallback")
    publish("Open-Meteo ICON-EU",None,pts,times,frames,.58)

if __name__=="__main__":
    now=datetime.now(timezone.utc)
    try:direct(now)
    except Exception as e:
        print("Native WW unavailable; trying explicit ICON-EU WMO codes:",e,flush=True)
        fallback(now)
