#!/usr/bin/env python3
"""KFS /diagramme backup: real ECMWF IFS ENS members, no Open-Meteo API.
8 fixed perturbed members, 12-hourly, 15-day, France 0.5° sample grid.
Temperature and MSL pressure only; no synthetic rain or members.
"""
import json, math, os, tempfile
from pathlib import Path
from datetime import datetime,timedelta,timezone
import numpy as np
from scipy.spatial import cKDTree
from ecmwf.opendata import Client
from eccodes import codes_get,codes_get_array,codes_get_elements,codes_grib_new_from_file,codes_release

ROOT=Path(__file__).resolve().parents[1]
OUTPUT=ROOT/"diagramme"/"ifs-ens-8m.json"
MEMBERS=[3,9,15,21,27,33,39,45]
STEPS=list(range(12,361,12))
PARAMS={"2t":"temperature","msl":"pression"}
LATS=[float(x) for x in np.arange(41.0,51.51,.5)]
LONS=[float(x) for x in np.arange(-5.5,10.01,.5)]
GRID=np.array([(a,b) for a in LATS for b in LONS],dtype=np.float64)

def index_grid(msg):
    lat=np.asarray(codes_get_array(msg,"latitudes"),dtype=np.float64)
    lon=np.asarray(codes_get_array(msg,"longitudes"),dtype=np.float64)
    lon=np.where(lon>180,lon-360,lon)
    candidates=np.flatnonzero((lat>=40)&(lat<=53)&(lon>=-7)&(lon<=12))
    fac=math.cos(math.radians(47))
    tree=cKDTree(np.column_stack([lat[candidates],lon[candidates]*fac]))
    dist,idx=tree.query(np.column_stack([GRID[:,0],GRID[:,1]*fac]))
    if np.max(dist)>.2: raise RuntimeError("Invalid French domain sampling")
    return candidates[idx].astype(int).tolist()

def parse_grib(path):
    data={};idx=None;run_dates=set()
    with path.open("rb") as fh:
        while (msg:=codes_grib_new_from_file(fh)) is not None:
            try:
                key=str(codes_get(msg,"shortName"))
                step=int(codes_get(msg,"endStep"))
                member=int(codes_get(msg,"number"))
                if key not in PARAMS or step not in STEPS or member not in MEMBERS:continue
                if idx is None:idx=index_grid(msg)
                vals=np.asarray(codes_get_elements(msg,"values",idx),dtype=float)
                if not np.all(np.isfinite(vals)):raise RuntimeError(f"Missing field values {key}/{step}/{member}")
                if key=="2t":
                    if np.min(vals)<180 or np.max(vals)>340:raise RuntimeError("Unexpected Kelvin field")
                    vals-=273.15
                if key=="msl":
                    if np.min(vals)<85000 or np.max(vals)>110000:raise RuntimeError("Unexpected pressure Pa field")
                    vals/=100
                field=(key,step,member)
                if field in data:raise RuntimeError("Duplicate GRIB field")
                data[field]=vals
                run_dates.add((int(codes_get(msg,"dataDate")),int(codes_get(msg,"dataTime"))))
            finally:codes_release(msg)
    if len(run_dates)!=1:raise RuntimeError("Mixed forecast runs in GRIB")
    expected={(k,t,m) for k in PARAMS for t in STEPS for m in MEMBERS}
    if missing:=expected-data.keys():raise RuntimeError(f"Incomplete ENS: {len(missing)} missing fields, e.g. {list(missing)[:5]}")
    return data,run_dates.pop()

def main():
    with tempfile.TemporaryDirectory() as d:
        target=Path(d)/"ens.grib2"
        client=Client(source=os.getenv("ECMWF_SOURCE","ecmwf"),model="ifs",resol="0p25")
        output=client.retrieve(time=0,stream="enfo",type="pf",param=list(PARAMS),number=MEMBERS,step=STEPS,target=str(target))
        run=output.datetime
        if run.tzinfo is None:run=run.replace(tzinfo=timezone.utc)
        run=run.astimezone(timezone.utc)
        if run.hour not in (0,12) or datetime.now(timezone.utc)-run>timedelta(hours=40):
            raise RuntimeError(f"Old/invalid ECMWF run {run}")
        fields,grib_date=parse_grib(target)
        if grib_date!=(int(run.strftime("%Y%m%d")),run.hour*100):
            raise RuntimeError("ECMWF GRIB forecast cycle mismatch")
        series={name:[] for name in PARAMS.values()}
        for step in STEPS:
            for short,name in PARAMS.items():
                matrix=np.vstack([fields[(short,step,m)] for m in MEMBERS])
                quantiles=np.percentile(matrix,[10,50,90],axis=0)
                row=np.stack([*quantiles,np.mean(matrix,axis=0)],axis=1)
                series[name].append([[round(float(z),1) for z in vals] for vals in row])
    payload={
        "schema":1,"provider":"ECMWF IFS ENS, 8 genuine perturbed members",
        "source":"https://www.ecmwf.int/en/forecasts/datasets/open-data","license":"CC BY 4.0",
        "run_utc":run.isoformat().replace("+00:00","Z"),
        "generated_at_utc":datetime.now(timezone.utc).isoformat().replace("+00:00","Z"),
        "members":MEMBERS,"model_resolution_degrees":.25,"grid_resolution_degrees":.5,
        "interval_hours":12,"step_hours":STEPS,"latitudes":LATS,"longitudes":LONS,
        "series":series,"notice":"8/50 perturbed members; not full ENS. Precipitation not available."}
    OUTPUT.parent.mkdir(parents=True,exist_ok=True)
    OUTPUT.write_text(json.dumps(payload,separators=(",",":"))+"\n",encoding="utf-8")
    print("KFS independent ECMWF fallback:",run,len(STEPS),"steps",len(GRID),"cells",OUTPUT.stat().st_size,"bytes")

if __name__=="__main__":main()
