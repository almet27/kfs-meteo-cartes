#!/usr/bin/env python3
"""KFS hourly sampled model maps. Provider hourly output, not native grids."""
import json, math, time
from datetime import datetime, timezone, timedelta
from pathlib import Path
from urllib.request import Request, urlopen
from urllib.parse import urlencode
from urllib.error import HTTPError
from kfs_weather_cache import check_quota, record_quota
OUT=Path("forecast-maps/france/hourly-web")
MODELS={"arome":"meteofrance_arome_france","gfs":"gfs_global","ifs":"ecmwf_ifs025"}
FIELDS=["temperature_2m","wind_speed_10m","wind_gusts_10m","precipitation","wind_direction_10m","weather_code"]
def get(url):
    with urlopen(Request(url,headers={"User-Agent":"KFS-Meteo-Hourly/1.0"}),timeout=40) as r:return json.load(r)
def inside(x,y,ring):
    flag=False
    for a,b in zip(ring,ring[1:]+ring[:1]):
        if (a[1]>y)!=(b[1]>y) and x<(b[0]-a[0])*(y-a[1])/(b[1]-a[1])+a[0]:flag=not flag
    return flag
def points():
    geo=get("https://raw.githubusercontent.com/gregoiredavid/france-geojson/master/regions-version-simplifiee.geojson")
    polygons=[]
    for f in geo["features"]:
        if str(f["properties"]["code"]) not in {"11","24","27","28","32","44","52","53","75","76","84","93","94"}:continue
        g=f["geometry"];polygons.extend([g["coordinates"]] if g["type"]=="Polygon" else g["coordinates"])
    boxes=[(p,min(x[0] for x in p[0]),max(x[0] for x in p[0]),min(x[1] for x in p[0]),max(x[1] for x in p[0])) for p in polygons]
    pts=[]
    for j in range(17):
        lat=round(41.5+j*.58,3)
        for i in range(27):
            lon=round(-5.2+i*.58,3)
            if any(l<=lon<=r and b<=lat<=t and inside(lon,lat,p[0]) and not any(inside(lon,lat,h) for h in p[1:]) for p,l,r,b,t in boxes):
                pts.append([lon,lat])
    if len(pts)<100:raise RuntimeError("Coverage grid incomplete")
    return pts
def parse(v):
    return datetime.fromisoformat(v.replace("Z","+00:00")).replace(tzinfo=timezone.utc)
def numeric(v):return isinstance(v,(float,int)) and not isinstance(v,bool) and math.isfinite(v)
def build(name,code,pts):
    check_quota()
    now=datetime.now(timezone.utc)
    start=now.replace(minute=0,second=0,microsecond=0)
    times=[(start+timedelta(hours=i)).strftime("%Y-%m-%dT%H:%M") for i in range(34)]
    rows=[]
    for k in range(0,len(pts),25):
        part=pts[k:k+25]
        q=urlencode({"latitude":",".join(str(p[1]) for p in part),"longitude":",".join(str(p[0]) for p in part),"models":code,"hourly":",".join(FIELDS),"forecast_hours":34,"timezone":"GMT","wind_speed_unit":"kmh","precipitation_unit":"mm","cell_selection":"land"})
        try:d=get("https://api.open-meteo.com/v1/forecast?"+q)
        except HTTPError as e:record_quota(e);raise
        if isinstance(d,dict):d=[d]
        if len(d)!=len(part):raise ValueError("Unexpected location count")
        for p,r in zip(part,d):
            h=r.get("hourly",{});index={t:i for i,t in enumerate(h.get("time",[]))}
            values=[]
            for t in times:
                idx=index.get(t)
                vals=[]
                for field in FIELDS:
                    a=h.get(field,[])
                    v=a[idx] if idx is not None and idx<len(a) else None
                    vals.append(round(v,1) if numeric(v) else None)
                values.append(vals)
            rows.append(values)
        time.sleep(.3)
    # Require broad temperature coverage for every advertised hour. Other fields remain null when missing.
    good=[i for i in range(len(times)) if sum(r[i][0] is not None for r in rows)>=len(pts)*.8]
    if len(good)<25 or not all(i in good for i in range(1,25)):raise ValueError("Insufficient hourly temperature coverage")
    doc={"schema":1,"model":name,"provider":"Open-Meteo","fetched_utc":now.isoformat(),"points":pts,"times":[t+"Z" for t in times],"rows":rows,"fields":FIELDS,"grid_degrees":.58}
    tmp=OUT/(name+".tmp");tmp.write_text(json.dumps(doc,separators=(",",":"),allow_nan=False));tmp.replace(OUT/(name+".json"))
    print(name,len(pts),len(good),"hours",flush=True)
def main():
    OUT.mkdir(parents=True,exist_ok=True);pts=points();ok=0
    for name,code in MODELS.items():
        try:build(name,code,pts);ok+=1
        except Exception as e:print(name,"unavailable:",str(e)[:180],flush=True)
    if not ok:raise RuntimeError("No fresh models; previous files retained")
if __name__=="__main__":main()
