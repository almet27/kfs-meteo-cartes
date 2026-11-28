#!/usr/bin/env python3
"""Paired precipitation verification on the KFS grid. No cross-unit scoring.
Inputs are NPZ files with values (mm), lon/lat 2D arrays, valid_utc,
interval_minutes, unit, and explicit coverage mask (boolean). Forecast inputs
also carry run_utc and issued_utc, observation carries source.
Only archived forecasts issued before the verification interval are accepted.
"""
import argparse
import json
from datetime import datetime, timezone, timedelta
from pathlib import Path
import numpy as np
from scipy.ndimage import uniform_filter

def scalar(d,k):
    return d[k].item()
def stamp(v):
    x=datetime.fromisoformat(str(v).replace("Z","+00:00"))
    if x.tzinfo is None:raise ValueError("Explicit timezone required")
    return x.astimezone(timezone.utc)
def ratio(a,b):return float(a/b) if b>0 else None
def compare(fc,ob,thresholds=(.1,.5,2.,5.)):
    x=np.asarray(fc["values"],dtype=float);y=np.asarray(ob["values"],dtype=float)
    if x.ndim!=2 or x.shape!=y.shape:raise ValueError("Grid mismatch")
    if scalar(fc,"unit")!="mm" or scalar(ob,"unit")!="mm":raise ValueError("Same accumulated water-equivalent mm required")
    t=stamp(scalar(ob,"valid_utc"));interval=int(scalar(ob,"interval_minutes"))
    if interval not in (5,15,60) or interval!=int(scalar(fc,"interval_minutes")) or t!=stamp(scalar(fc,"valid_utc")):raise ValueError("Exact matching accumulation interval required")
    run=stamp(scalar(fc,"run_utc"));issue=stamp(scalar(fc,"issued_utc"))
    if not run<=issue<=t-timedelta(minutes=interval):raise ValueError("Forecast must be archived before the interval")
    lon=np.asarray(ob["lon"]);lat=np.asarray(ob["lat"])
    if lon.shape!=x.shape or lat.shape!=x.shape or not np.allclose(lon,fc["lon"],atol=1e-6,rtol=0) or not np.allclose(lat,fc["lat"],atol=1e-6,rtol=0):raise ValueError("Coordinates mismatch")
    ca=np.asarray(fc["coverage"]);cb=np.asarray(ob["coverage"])
    if ca.shape!=x.shape or cb.shape!=x.shape or ca.dtype!=bool or cb.dtype!=bool:raise ValueError("Explicit boolean coverage required")
    mask=ca&cb&np.isfinite(x)&np.isfinite(y)&(x>=0)&(y>=0)
    # Regions are explicit quadrants, not administrative boundaries.
    sectors={"France":np.ones(x.shape,dtype=bool),"Nord-Ouest":(lon<2)&(lat>=46.5),"Nord-Est":(lon>=2)&(lat>=46.5),"Sud-Ouest":(lon<2)&(lat<46.5),"Sud-Est":(lon>=2)&(lat<46.5)}
    out={"schema":1,"model":str(scalar(fc,"model")),"observation":str(scalar(ob,"source")),"run_utc":run.isoformat(),"issued_utc":issue.isoformat(),"valid_utc":t.isoformat(),"lead_minutes":int((t-run).total_seconds()/60),"interval_minutes":interval,"regions":{}}
    for name,region in sectors.items():
        valid=mask&region;n=int(valid.sum())
        if n<100 or n<.5*int(region.sum()):continue
        a=x[valid];b=y[valid];part={"n":n,"sum_absolute_error":float(np.abs(a-b).sum()),"sum_squared_error":float(((a-b)**2).sum()),"sum_forecast":float(a.sum()),"sum_observed":float(b.sum()),"mae":float(np.abs(a-b).mean()),"thresholds":{}}
        for threshold in thresholds:
            f=(x>=threshold)&valid;o=(y>=threshold)&valid;hit=int((f&o).sum());miss=int((~f&o&valid).sum());false=int((f&~o&valid).sum())
            item={"hits":hit,"misses":miss,"false_alarms":false,"csi":ratio(hit,hit+miss+false),"pod":ratio(hit,hit+miss),"far":ratio(false,hit+false),"frequency_bias":ratio(hit+false,hit+miss),"fss":{}}
            for size in (1,5,11,21):
                cov=uniform_filter(valid.astype(float),size=size,mode="constant")
                eligible=valid&(cov>=.95)
                af=np.divide(uniform_filter(f.astype(float),size=size,mode="constant"),cov,out=np.zeros_like(cov),where=cov>0)
                ao=np.divide(uniform_filter(o.astype(float),size=size,mode="constant"),cov,out=np.zeros_like(cov),where=cov>0)
                num=float(((af[eligible]-ao[eligible])**2).sum());den=float((af[eligible]**2+ao[eligible]**2).sum())
                item["fss"][str(size)]={"n":int(eligible.sum()),"numerator":num,"denominator":den,"score":1-num/den if den>0 else None}
            part["thresholds"][str(threshold)]=item
        out["regions"][name]=part
    return out
def test():
    shape=(80,80);lon,lat=np.meshgrid(np.linspace(-5,10,80),np.linspace(51,41,80));a=np.zeros(shape);a[20:40,20:40]=2.;base=dict(lon=lon,lat=lat,coverage=np.ones(shape,dtype=bool),unit=np.array("mm"),valid_utc=np.array("2026-01-01T03:00:00Z"),interval_minutes=np.array(60));obs={**base,"values":a,"source":np.array("synthetic")};fc={**base,"values":a.copy(),"model":np.array("test"),"run_utc":np.array("2026-01-01T00:00:00Z"),"issued_utc":np.array("2026-01-01T01:00:00Z")}
    r=compare(fc,obs)["regions"]["France"];assert r["mae"]==0 and r["thresholds"]["0.1"]["csi"]==1 and r["thresholds"]["0.1"]["fss"]["11"]["score"]==1
    moved={**fc,"values":np.roll(a,5,axis=1)};r=compare(moved,obs)["regions"]["France"]["thresholds"]["0.1"];assert 0<r["csi"]<1 and r["fss"]["11"]["score"]>r["fss"]["1"]["score"]
    dry={**fc,"values":np.zeros(shape)};r=compare(dry,obs)["regions"]["France"]["thresholds"]["0.1"];assert r["pod"]==0 and r["far"] is None
    try:compare({**fc,"unit":np.array("dBZ")},obs)
    except ValueError:pass
    else:raise AssertionError("Different physical units accepted")
    try:compare({**fc,"issued_utc":np.array("2026-01-01T02:50:00Z")},obs)
    except ValueError:pass
    else:raise AssertionError("Look-ahead accepted")
    print("PASS: identity, displacement, dry forecast, unit and temporal safeguards")
if __name__=="__main__":
    p=argparse.ArgumentParser();p.add_argument("--test",action="store_true");p.add_argument("--forecast",type=Path);p.add_argument("--observation",type=Path);p.add_argument("--output",type=Path);a=p.parse_args()
    if a.test:test()
    else:
        if not all((a.forecast,a.observation,a.output)):p.error("Forecast, observation and output required")
        with np.load(a.forecast,allow_pickle=False) as fc,np.load(a.observation,allow_pickle=False) as ob:r=compare(fc,ob)
        a.output.write_text(json.dumps(r,indent=2,allow_nan=False))
