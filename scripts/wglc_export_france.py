#!/usr/bin/env python3
"""Extrait WGLC v2026, données WWLLN (CC BY-SA 4.0), pour France métropolitaine.
Usage: python scripts/wglc_export_france.py /tmp/wglc.nc
Ne prétend jamais fournir des coups individuels ni des éclairs nuage-sol confirmés.
"""
import calendar
import gzip
import json
import math
import sys
from pathlib import Path

import numpy as np
from netCDF4 import Dataset, num2date

ROOT = Path(__file__).resolve().parent.parent
DEST = ROOT / "data" / "wglc"
DEST.mkdir(parents=True, exist_ok=True)

def variable(ds, keys):
    for k in ds.variables:
        if k.lower() in keys:
            return ds.variables[k]
    raise RuntimeError(f"Missing coordinate {keys}")

with Dataset(sys.argv[1], "r") as ds:
    latvar = variable(ds, {"lat", "latitude"})
    lonvar = variable(ds, {"lon", "longitude"})
    timevar = variable(ds, {"time"})
    density = variable(ds, {"density"})
    lat = np.asarray(latvar[:], dtype=float)
    lonorig = np.asarray(lonvar[:], dtype=float)
    lon = ((lonorig + 180) % 360) - 180
    years = num2date(timevar[:], timevar.units,
                    calendar=getattr(timevar, "calendar", "standard"))
    yinds = np.where((lat >= 40.5) & (lat <= 52.0))[0]
    xinds = np.where((lon >= -6.5) & (lon <= 11.0))[0]
    if not len(yinds) or not len(xinds):
        raise RuntimeError("No France grid coordinates")
    yinds = yinds[np.argsort(lat[yinds])]
    xinds = xinds[np.argsort(lon[xinds])]
    yi0, yi1 = int(yinds.min()), int(yinds.max())+1
    yrel = yinds-yi0
    la = [round(float(x), 6) for x in lat[yinds]]
    lo = [round(float(x), 6) for x in lon[xinds]]
    print("DIMENSIONS", density.dimensions, density.shape,
          "UNITS", getattr(density, "units", None), flush=True)
    print("CROP",len(la),len(lo),min(la),max(la),min(lo),max(lo),flush=True)
    vars_ = list(density.dimensions)
    if len(vars_) != 3 or timevar.dimensions[0] not in vars_ or latvar.dimensions[0] not in vars_ or lonvar.dimensions[0] not in vars_:
        raise RuntimeError(f"Unexpected density axes {vars_}")
    ti = vars_.index(timevar.dimensions[0])
    yi = vars_.index(latvar.dimensions[0])
    xi = vars_.index(lonvar.dimensions[0])
    years_avail=sorted(set(int(t.year) for t in years))
    print("YEARS",years_avail,flush=True)
    # 12 months of a single year on a 5-arcmin grid, one gzip file per year.
    for year in years_avail:
        mo = {}
        for idx,t in enumerate(years):
            if int(t.year)!=year:
                continue
            month=int(t.month)
            slab=[slice(None)]*3
            slab[ti]=idx
            slab[yi]=slice(yi0,yi1)
            sample=density[tuple(slab)]
            # After removing time, the array either has (lat,lon) or (lon,lat).
            dim2=[name for i,name in enumerate(vars_) if i!=ti]
            a=np.ma.filled(sample,np.nan)
            a=np.asarray(a,dtype=np.float64)
            if dim2.index(latvar.dimensions[0])==1:
                a=a.T
            # Remap selected 5' cells in ascending latitude, longitude.
            a=a[yrel,:][:,xinds]
            if a.shape!=(len(la),len(lo)):
                raise RuntimeError(f"Unexpected selected shape {a.shape}")
            # Monthly WGLC density field is aggregated from daily samples;
            # store RAW WGLC monthly values without multiplying days.
            vals=np.round(a,6)
            vals[~np.isfinite(vals)]=np.nan
            mo[month]=[None if not math.isfinite(float(v)) else float(v)
                       for v in vals.ravel()]
        if not mo:
            continue
        if set(mo)!=set(range(1,13)):
            print("WARN incomplete year",year,"months",sorted(mo),flush=True)
        payload={"version":1,"year":year,"source":"WWLLN WGLC v2026",
                 "doi":"10.5281/zenodo.20277101","license":"CC BY-SA 4.0",
                 "units":getattr(density,"units","strokes/km2/day"),
                 "definition":"Monthly gridded, detection-efficiency-corrected lightning stroke density; not distinct ground flash counts",
                 "lat":la,"lon":lo,"monthly":[mo.get(i) for i in range(1,13)]}
        path=DEST/f"wglc_france_{year}.json.gz"
        contents=json.dumps(payload,separators=(",",":"),ensure_ascii=False,allow_nan=False).encode()
        with gzip.open(path,"wb",compresslevel=8,mtime=None) as f: f.write(contents)
        print("OUTPUT",year,path.relative_to(ROOT),path.stat().st_size,"bytes",
              "L'Aigle sample",next((mo[m][(min(range(len(la)),key=lambda i:abs(la[i]-48.765))*len(lo)+
                  min(range(len(lo)),key=lambda i:abs(lo[i]-0.626)))] for m in range(1,13) if m in mo),None),flush=True)
