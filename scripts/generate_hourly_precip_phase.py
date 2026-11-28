#!/usr/bin/env python3
"""Native hourly surface precipitation phase maps (mm liquid equivalent).
AROME SP2 and DWD ICON-D2 native triangular grid. Publish only complete validated hours."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryFile
from urllib.request import Request, urlopen
from urllib.parse import quote
import bz2, json, re, sys
import numpy as np
from PIL import Image
from kfs_precip_archive import PrecipArchive
from scipy.spatial import cKDTree
from eccodes import codes_grib_new_from_file, codes_get, codes_get_array, codes_set, codes_release

BOUNDS=(-6.,10.,41.,52.)
LEVELS=[.05,.1,.2,.5,1,2,4,8,15,25]
COLORS={
 "rain":["#245c88","#277bb5","#30a5d6","#36c4c9","#41c88a","#a4d83b","#f2df32","#ff9c30","#e94542"],
 "snow":["#625ca9","#7971c3","#9d89df","#b19ced","#c4b0fb","#ded1ff","#e9e5ff","#f6f2ff","#ffffff"],
 "graupel":["#83476d","#a94b87","#c54d9c","#df63b2","#ef80c2","#f4a0d4","#f9bce4","#ffd4eb","#ffe8f6"],
 "mixed":["#477c8e","#598eae","#699dc6","#82addc","#a3bce9","#c5c8f1","#e7c5e9","#ffc9df","#ffecf8"]}
for phase, first in zip(("rain","snow","graupel","mixed"),("#344a67","#4b4b85","#633956","#415a70")):
    COLORS[phase].insert(0,first)
UA={"User-Agent":"KFS-Meteo-Phase/2.0"}
AROME_BASE="https://meteofrance-pnt.s3.rbx.io.cloud.ovh.net/pnt/"
DWD_BASE="https://opendata.dwd.de/weather/nwp/v1/m/icon-d2/p/"
DWD_FIELDS=("RAIN_GSP","RAIN_CON","SNOW_GSP","SNOW_CON","GRAU_GSP")
AROME_NAMES={"tirf":"rain","tsnowp":"snow","tgrp":"graupel"}

def key(g,k,default=None):
    try:return codes_get(g,k)
    except Exception:return default

def hours(v):
    if isinstance(v,(int,float)):return float(v)
    m=re.fullmatch(r"([0-9]+(?:\.[0-9]+)?)([smhd]?)",str(v))
    if not m:raise ValueError("Unknown step "+str(v))
    return float(m[1])*{"":1,"h":1,"m":1/60,"s":1/3600,"d":24}[m[2]]

def arome_url(run,h):
    t=run.strftime("%Y-%m-%dT%H:00:00Z")
    return f"{AROME_BASE}{t}/arome/001/SP2/arome__001__SP2__{h:02d}H__{t}.grib2"

def icon_url(run,h,field):
    cycle=quote(run.strftime("%Y-%m-%dT%H:00"),safe="")
    return f"{DWD_BASE}{field}/r/{cycle}/s/PT{h:03d}H00M.grib2"

def available(url):
    try:
        with urlopen(Request(url,headers=UA,method="HEAD"),timeout=12) as r:return r.status==200
    except Exception:return False

def payload(url):
    with urlopen(Request(url,headers=UA),timeout=90) as r:b=r.read(100_000_001)
    if len(b)>100_000_000:raise ValueError("Oversized GRIB")
    return bz2.decompress(b) if b.startswith(b"BZh") else b

def grid_identity(g):
    return (key(g,"gridType"),key(g,"numberOfDataPoints"),key(g,"uuidOfHGrid"))

def icon_coordinate(run,field):
    with TemporaryFile() as f:
        f.write(payload(icon_url(run,0,field)));f.seek(0)
        g=codes_grib_new_from_file(f)
        if g is None:raise ValueError("Missing "+field)
        try:
            codes_set(g,"missingValue",1e30)
            v=np.asarray(codes_get_array(g,"values"))
            units=str(key(g,"units","")).lower().strip()
            if units in ("rad","radian","radians"):v=np.degrees(v)
            elif not (units.startswith("degree") or units=="deg"):raise ValueError("Unexpected coordinate units "+units)
            if not np.isfinite(v).all() or np.max(np.abs(v))>360:raise ValueError("Invalid coordinate grid")
            if field=="CLAT" and not (35<np.min(v)<55 and 45<np.max(v)<65):raise ValueError("Unexpected ICON latitude range")
            return v,grid_identity(g)
        finally:codes_release(g)

def icon_grid(run):
    lat,lm=icon_coordinate(run,"CLAT");lon,om=icon_coordinate(run,"CLON")
    if lm!=om or not lm[2] or len(lat)!=len(lon):raise ValueError("Coordinate grid mismatch")
    lon=(lon+180)%360-180
    w,e,s,n=BOUNDS
    mask=(lon>=w-.08)&(lon<=e+.08)&(lat>=s-.08)&(lat<=n+.08)
    return lon[mask],lat[mask],mask,lm

def extract(url,run,h,model,field=None,grid=None):
    out={}
    with TemporaryFile() as f:
        f.write(payload(url));f.seek(0)
        while (g:=codes_grib_new_from_file(f)) is not None:
            try:
                name=AROME_NAMES.get(str(key(g,"shortName","")).lower()) if model=="arome" else field
                if not name:continue
                if key(g,"dataDate")!=int(run.strftime("%Y%m%d")) or key(g,"dataTime")!=run.hour*100:continue
                valid=run+timedelta(hours=h)
                if key(g,"validityDate")!=int(valid.strftime("%Y%m%d")) or key(g,"validityTime")!=valid.hour*100:continue
                if key(g,"stepType")!="accum" or hours(key(g,"endStep"))!=h:continue
                unit=str(key(g,"units","")).replace(" ","")
                # DWD ICON-D2 output table explicitly defines RAIN_GSP/RAIN_CON
                # as accumulated kg/m² for GRIB 0/1/77 and 0/1/76 with accum.
                # ecCodes generic names/units describe the rate form of these IDs.
                dwd_accum=(model=="icon" and key(g,"centre")=="edzw" and key(g,"stepType")=="accum"
                    and (key(g,"discipline"),key(g,"parameterCategory"),key(g,"parameterNumber"))==(0,1,{"RAIN_GSP":77,"RAIN_CON":76}.get(field,-1))
                    and unit=="kgm**-2s**-1")
                if not dwd_accum and unit not in ("kgm**-2","kgm-2","kg/m^2","kg/m2","mm"):raise ValueError("Unexpected unit "+repr(key(g,"units",""))+" for "+model+" "+str(field)+" "+str(key(g,"shortName"))+" at "+str(h))
                if dwd_accum:print("DWD documented accumulated rainfall unit",field,h,flush=True)
                codes_set(g,"missingValue",1e30)
                v=np.asarray(codes_get_array(g,"values"))
                if model=="icon":
                    lon,lat,mask,meta=grid
                    if grid_identity(g)!=meta or len(v)!=len(mask):raise ValueError("Native ICON grid mismatch")
                    v=v[mask]
                else:
                    if key(g,"gridType")!="regular_ll":raise ValueError("Unexpected AROME grid")
                    lat=np.asarray(codes_get_array(g,"latitudes"));lon=(np.asarray(codes_get_array(g,"longitudes"))+180)%360-180
                    w,e,s,n=BOUNDS
                    mask=(lon>=w-.08)&(lon<=e+.08)&(lat>=s-.08)&(lat<=n+.08)
                    lon,lat,v=lon[mask],lat[mask],v[mask]
                v=np.where(np.isfinite(v)&(v>=-.05)&(v<1e5),np.maximum(v,0),np.nan)
                if len(v)<10000:raise ValueError("Insufficient coverage")
                out[name]=(hours(key(g,"startStep")),lon,lat,v.astype(np.float32))
            finally:codes_release(g)
    expected=set(AROME_NAMES.values()) if model=="arome" else {field}
    if set(out)!=expected:raise ValueError("Missing exact accumulation fields: "+str(expected-set(out)))
    return out

def fetch(model,run,h,grid=None):
    if model=="arome":return extract(arome_url(run,h),run,h,model)
    result={}
    with ThreadPoolExecutor(max_workers=3) as pool:
        for row in pool.map(lambda field:extract(icon_url(run,h,field),run,h,model,field,grid),DWD_FIELDS):result.update(row)
    return result

def delta(a,b,h):
    start,x,y,v=b
    if start==h-1:return v
    if start!=0 or h<=1:raise ValueError("Unsupported accumulation interval")
    if a is None or a[0]!=0 or not np.array_equal(x,a[1]) or not np.array_equal(y,a[2]):raise ValueError("Previous accumulation grid/interval mismatch")
    d=v-a[3]
    if np.any(d[np.isfinite(d)]<-.15):raise ValueError("Negative accumulation increment")
    return np.maximum(d,0)

def raster_index(x,y,step):
    w,e,s,n=BOUNDS
    W,H=round((e-w)/step)+1,round((n-s)/step)+1
    xx,yy=np.meshgrid(np.linspace(w,e,W),np.linspace(n,s,H))
    def xy(a,b):return np.column_stack((a*.68,b))
    d,j=cKDTree(xy(x,y)).query(xy(xx.ravel(),yy.ravel()),workers=2)
    return W,H,j,d<=step*1.15

def render(model,run,h,previous,current,out,mapping,archive=None):
    step=.01 if model=="arome" else .02
    first=next(iter(current.values()))
    x,y=first[1:3]
    values={}
    for k,row in current.items():
        if not np.array_equal(x,row[1]) or not np.array_equal(y,row[2]):raise ValueError("Phase grids differ")
        values[k]=delta(previous.get(k),row,h)
    if model=="arome":rain,snow,graupel=(values[k] for k in ("rain","snow","graupel"))
    else:rain=values["RAIN_GSP"]+values["RAIN_CON"];snow=values["SNOW_GSP"]+values["SNOW_CON"];graupel=values["GRAU_GSP"]
    gx,gy,(W,H,j,covered)=mapping
    if not np.array_equal(x,gx) or not np.array_equal(y,gy):raise ValueError("Source grid changed")
    p=np.stack([rain[j],snow[j],graupel[j]])
    good=covered&np.isfinite(p).all(axis=0)
    if good.sum()<10000:raise ValueError("Insufficient valid phase pixels")
    total=p.sum(axis=0)
    if archive is not None:archive.add(run+timedelta(hours=h),total,good,W,H,step)
    strongest=np.argmax(np.nan_to_num(p,nan=-1),axis=0)
    mixed=good&(p[0]>=.1)&((p[1]+p[2])>=.1)&(np.maximum(p[0],p[1]+p[2])<.8*total)
    phase=np.where(mixed,3,strongest)
    idx=np.zeros(W*H,dtype=np.uint8)
    wet=good&(total>=LEVELS[0])
    level=np.searchsorted(LEVELS,total[wet],side="right")-1
    idx[wet]=1+phase[wet]*len(LEVELS)+level
    idx[~good]=1+4*len(LEVELS)
    im=Image.fromarray(idx.reshape(H,W),mode="P")
    palette=[0,0,0]+[int(c[i:i+2],16) for kind in ("rain","snow","graupel","mixed") for c in COLORS[kind] for i in (1,3,5)]+[107,112,120]
    im.putpalette(palette+[0]*(768-len(palette)))
    name=f"phase-v2-{run:%Y%m%d%H}-h{h:02d}.png"
    im.save(out/name,transparency=0,optimize=True)
    return {"hour":h,"valid_utc":(run+timedelta(hours=h)).isoformat(),"file":name}

def main(model):
    out=Path(model+"-phase");out.mkdir(exist_ok=True)
    now=datetime.now(timezone.utc);base=now.replace(minute=0,second=0,microsecond=0)
    anchor=base.replace(hour=base.hour//3*3)
    old=Path("previous-"+model+"-phase.json")
    previous=json.loads(old.read_text()) if old.exists() else {}
    candidates=[]
    for run in (anchor-timedelta(hours=3*i) for i in range(1,6)):
        start=max(1,int((base-run).total_seconds()/3600))
        ends=sorted({h for h in (48,42,36,start+24) if start+24<=h<=48},reverse=True) if model=="arome" else [start+24]
        for end in ends:
            if end>48:continue
            if model=="arome":urls=[arome_url(run,h) for h in (start-1,end)]
            else:urls=[icon_url(run,h,f) for h in (start-1,end) for f in DWD_FIELDS]+[icon_url(run,0,f) for f in ("CLAT","CLON")]
            if all(available(u) for u in urls):
                candidates.append((run,start,end))
                break
            print("Incomplete",model,run,start,end,flush=True)
        if candidates and model=="icon":break
        if candidates and candidates[-1][2]==48:break
    if not candidates:raise RuntimeError("No complete recent cycle")
    # Prefer the freshest usable cycle (at least 24 hours ahead). A longer older cycle must not override it.
    run,start,end=max(candidates,key=lambda c:(c[0],c[2]))
    if previous.get("render_version")==2 and previous.get("run_utc")==run.isoformat() and previous.get("numeric_archive") and previous.get("frames") and max(datetime.fromisoformat(f["valid_utc"]) for f in previous["frames"])>=run+timedelta(hours=end):
        print("Already published");return
    grid=icon_grid(run) if model=="icon" else None
    # One shared predecessor, no duplicate downloads, and bounded memory.
    prev=fetch(model,run,start-1,grid);frames=[];archive=PrecipArchive('icon-d2' if model=='icon' else model,run)
    x,y=next(iter(prev.values()))[1:3]
    mapping=(x,y,raster_index(x,y,.01 if model=="arome" else .02))
    for h in range(start,end+1):
        curr=fetch(model,run,h,grid)
        frames.append(render(model,run,h,prev,curr,out,mapping,archive));prev=curr
        print(model,run,h,flush=True)
    doc={"schema":1,"render_version":2,"unit":"mm","interval_hours":1,"model":model,"source":"Météo-France ARÔME HD SP2" if model=="arome" else "DWD ICON-D2",
         "run_utc":run.isoformat(),"generated_utc":now.isoformat(),"resolution_degrees":.01 if model=="arome" else .02,"bounds":BOUNDS,
         "levels":LEVELS,"colors":COLORS,"frames":frames}
    doc["numeric_archive"]=archive.save(out)
    (out/"manifest.json").write_text(json.dumps(doc,indent=2))
if __name__=="__main__":
    if len(sys.argv)!=2 or sys.argv[1] not in ("arome","icon"):raise SystemExit("Specify arome or icon")
    main(sys.argv[1])
