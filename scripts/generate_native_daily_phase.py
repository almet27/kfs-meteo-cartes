#!/usr/bin/env python3
"""Daily native snow/freezing rain maps; millimetres water equivalent, never snow depth."""
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
from pathlib import Path
import json, sys
import numpy as np
from PIL import Image
from generate_hourly_precip_phase import (
    BOUNDS, available, arome_url, icon_url, icon_grid, extract, raster_index
)

LEVELS = [0.05, 0.1, 0.5, 1, 2, 5, 10, 20, 30]
COLORS = {
    "snow": ["#514075","#655291","#8069b1","#9b80d5","#b69aef","#cbb0ff","#a26be2","#833dc4","#602399"],
    "freezing": ["#254d36","#326747","#3c8b53","#54b566","#80de83","#b5efa0","#50bc64","#29914d","#126a35"],
}
PARIS=ZoneInfo("Europe/Paris")

def boundaries(now):
    for offset in range(3):
        date=now.astimezone(PARIS).date()+timedelta(days=offset)
        start=datetime.combine(date,datetime.min.time(),PARIS).astimezone(timezone.utc)
        end=datetime.combine(date+timedelta(days=1),datetime.min.time(),PARIS).astimezone(timezone.utc)
        if offset==0:start=max(start,now.replace(minute=0,second=0,microsecond=0))
        if end>start:yield date.isoformat(),start,end

def cumulative(row,h):
    if row[0]!=0:raise ValueError("Expected run-start accumulation")
    return row[3]

def difference(a,b,h0,h1):
    if not np.array_equal(a[1],b[1]) or not np.array_equal(a[2],b[2]):raise ValueError("Grid mismatch")
    v=cumulative(b,h1)-cumulative(a,h0)
    good=np.isfinite(v)
    if not good.any() or np.any(v[good]<-.15):raise ValueError("Invalid accumulation")
    return np.maximum(v,0)

def read_field(model,run,h,field,grid):
    if model=="arome":
        return extract(arome_url(run,h),run,h,model)["snow"]
    return extract(icon_url(run,h,field),run,h,model,field,grid)[field]

def render(out,model,run,date,kind,x,y,values):
    step=.01 if model=="arome" else .02
    W,H,j,covered=raster_index(x,y,step)
    v=values[j];good=covered&np.isfinite(v)
    if good.sum()<10000:raise ValueError("Insufficient raster coverage")
    idx=np.zeros(W*H,dtype=np.uint8)
    wet=good&(v>=LEVELS[0])
    idx[wet]=1+np.searchsorted(LEVELS,v[wet],side="right")-1
    idx[~good]=len(LEVELS)+1
    im=Image.fromarray(idx.reshape(H,W),mode="P")
    palette=[0,0,0]+[int(c[i:i+2],16) for c in COLORS[kind] for i in (1,3,5)]+[107,112,120]
    im.putpalette(palette+[0]*(768-len(palette)))
    name=f"daily-{kind}-{run:%Y%m%d%H}-{date}.png"
    im.save(out/name,transparency=0,optimize=True)
    return name

def main(model):
    now=datetime.now(timezone.utc)
    anchor=now.replace(hour=now.hour//3*3,minute=0,second=0,microsecond=0)
    out=Path(model+"-native-daily");out.mkdir(exist_ok=True)
    fields={"snow":["snow"]} if model=="arome" else {"snow":["SNOW_GSP","SNOW_CON"],"freezing":["FRZ_RAIN"]}
    maps=[];grids={};cache={}
    for date,start,end in boundaries(now):
        for kind,keys in fields.items():
            for cycle in range(1,6):
                run=anchor-timedelta(hours=cycle*3)
                h0=int((start-run).total_seconds()/3600);h1=int((end-run).total_seconds()/3600)
                if not 0<=h0<h1<=48:continue
                urls=[arome_url(run,h) for h in (h0,h1)] if model=="arome" else [icon_url(run,h,k) for h in (h0,h1) for k in keys]
                try:
                    if not all(available(u) for u in urls):continue
                    if model=="icon" and run not in grids:grids[run]=icon_grid(run)
                    rows=[]
                    for k in keys:
                        pair=[]
                        for h in (h0,h1):
                            key=(run,h,k)
                            if key not in cache:cache[key]=read_field(model,run,h,k,grids.get(run))
                            pair.append(cache[key])
                        a,b=pair
                        rows.append((a[1],a[2],difference(a,b,h0,h1)))
                    x,y,v=rows[0]
                    for xx,yy,vv in rows[1:]:
                        if not np.array_equal(x,xx) or not np.array_equal(y,yy):raise ValueError("Grid mismatch")
                        v=v+vv
                    file=render(out,model,run,date,kind,x,y,v)
                    maps.append(dict(date=date,kind=kind,run_utc=run.isoformat(),start_utc=start.isoformat(),end_utc=end.isoformat(),file=file))
                    print(model,date,kind,file,flush=True)
                    cache.clear();break
                except Exception as e:
                    cache.clear();print(model,date,kind,run,str(e)[:180],flush=True)
    if not maps:raise RuntimeError("No validated native daily fields")
    doc=dict(schema=1,model=model,generated_utc=now.isoformat(),unit="mm",bounds=BOUNDS,resolution_degrees=.01 if model=="arome" else .02,levels=LEVELS,colors=COLORS,maps=maps)
    (out/"manifest.json").write_text(json.dumps(doc,indent=2))
if __name__=="__main__":
    if len(sys.argv)!=2 or sys.argv[1] not in ("arome","icon"):raise SystemExit("Specify arome or icon")
    main(sys.argv[1])
