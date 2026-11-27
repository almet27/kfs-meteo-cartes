#!/usr/bin/env python3
"""NOAA/CIRA AI reforecasts: only publish scores on the full reproduced KFS sample.
Radford et al. 2025, doi:10.1175/BAMS-D-24-0057.1.
"""
import argparse,json
from datetime import datetime,timedelta,timezone
from pathlib import Path
import numpy as np
import xarray as xr
import fsspec
from build_model_skill import SITES,VARIABLES,truth,forecast,numeric

BUCKET="https://noaa-oar-mlwp-data.s3.amazonaws.com"
MODELS={"pangu":"PANG_v100_IFS","graphcast":"GRAP_v100_IFS","fourcastnet":"FOUR_v200_IFS"}
ALIASES={"temperature_2m":("t2","t2m","2t","temperature_2m","2m_temperature"),
         "pressure_msl":("mslp","msl","prmsl","mean_sea_level_pressure","pressure_msl")}
def select_name(ds,names):
    for n in names:
        if n in ds: return n
    raise ValueError("Missing "+str(names)+"; available "+str(list(ds.variables)))
def convert(arr,var):
    u=str(arr.attrs.get("units","")).strip().lower().replace(" ","").replace("°","")
    if var=="temperature_2m":
        if u in ("k","kelvin","degk"): return arr-273.15
        if u in ("c","degc","celsius","degree_celsius","degrees_celsius"): return arr
    if var=="pressure_msl":
        if u in ("pa","pascal","pascals"): return arr/100
        if u in ("hpa","mb","mbar","millibar"): return arr
    raise ValueError("Unknown unit "+var+" "+u)
def load(run,model):
    code=MODELS[model]
    url=f"{BUCKET}/{code}/{run:%Y/%m%d}/{code}_{run:%Y%m%d%H}_f000_f240_06.nc"
    with fsspec.open(url,"rb",block_size=1024*1024,cache_type="readahead") as handle:
        with xr.open_dataset(handle,engine="h5netcdf",decode_times=True) as ds:
            lat=select_name(ds,("latitude","lat"))
            lon=select_name(ds,("longitude","lon"))
            t=select_name(ds,("time","valid_time","forecast_time"))
            times=ds[t].values
            if not np.issubdtype(times.dtype,np.datetime64): raise ValueError("Non-datetime axis")
            actual=times.astype("datetime64[m]")
            expected=np.datetime64(run.replace(tzinfo=None),"m")+np.arange(0,241,6).astype("timedelta64[h]")
            if not np.array_equal(actual,expected): raise ValueError("Run/lead mismatch")
            lats,lons=ds[lat].values,ds[lon].values
            result={name:{} for name,_,_ in SITES}
            for var in VARIABLES:
                field=ds[select_name(ds,ALIASES[var])]
                for name,y,x in SITES:
                    iy=int(np.argmin(abs(lats-y)))
                    ix=int(np.argmin(abs((lons-x+180)%360-180)))
                    values=convert(field.isel({lat:iy,lon:ix}),var).transpose(t).values
                    result[name][var]={str(d):float(p) for d,p in zip(actual,values) if np.isfinite(p)}
            return result
def build(month):
    path=Path("data/model-skill")/(month+".json")
    baseline=json.loads(path.read_text())
    obs=truth(month,datetime.now(timezone.utc).date())
    base={k:v for k,v in baseline["models"].items() if k in ("ifs","aifs","aigfs","gfs")}
    if not {"ifs","aifs","gfs"}<=set(base): raise ValueError("Incomplete baseline")
    counts={v:[0]*15 for v in VARIABLES}
    sums={v:{m:[0.0]*15 for m in base} for v in VARIABLES}
    ns={v:{m:[0]*15 for m in MODELS} for v in VARIABLES}
    es={v:{m:[0.0]*15 for m in MODELS} for v in VARIABLES}
    errors=[]
    for day in baseline["run_dates"]:
        run=datetime.fromisoformat(day).replace(tzinfo=timezone.utc)
        bundle={m:forecast(run,api) for m,api in base.items()}
        extras={}
        for m in MODELS:
            try: extras[m]=load(run,m)
            except Exception as exc:
                errors.append(f"{day} {m}: {str(exc)[:350]}")
                print(errors[-1],flush=True)
        for i in range(10):
            valid=(run+timedelta(days=i+1)).strftime("%Y-%m-%dT%H:%M")
            for name,_,_ in SITES:
                for v in VARIABLES:
                    actual=numeric(obs[name][v].get(valid))
                    vals={m:numeric(d[name][v].get(valid)) for m,d in bundle.items()}
                    if actual is None or any(p is None for p in vals.values()): continue
                    counts[v][i]+=1
                    for m,p in vals.items(): sums[v][m][i]+=abs(p-actual)
                    for m,d in extras.items():
                        p=numeric(d[name][v].get(valid))
                        if p is None or not ((-100<=p<=70) if v=="temperature_2m" else (850<=p<=1100)): continue
                        ns[v][m][i]+=1
                        es[v][m][i]+=abs(p-actual)
        print("RUN",day,"NOAA",list(extras),flush=True)
    report={"schema":1,"period":month,"baseline_generated_utc":baseline["generated_utc"],"run_dates":baseline["run_dates"],"models":MODELS,"source":"NOAA/CIRA AIWP IFS initialization; doi:10.1175/BAMS-D-24-0057.1","method":"Identical KFS dates, sites, valid times, ERA5 and fully reproduced baseline MAE/counts; NOAA nearest native grid; J+10 max","metrics":{},"errors":errors}
    for v in VARIABLES:
        ref=baseline["metrics"][v]
        out={"unit":ref["unit"],"series":{},"n_by_model":{}}
        for m in MODELS:
            values=[]; nvalues=[]
            for i in range(15):
                n=counts[v][i]
                ok=n>0 and n==ref["n"][i] and ns[v][m][i]==n and all(ref["series"][b][i] is not None and abs(sums[v][b][i]/n-ref["series"][b][i])<=0.000501 for b in base)
                values.append(round(es[v][m][i]/n,3) if ok else None)
                nvalues.append(n if ok else 0)
            out["series"][m]=values
            out["n_by_model"][m]=nvalues
        report["metrics"][v]=out
    print(json.dumps({"coverage":{v:{m:sum(x is not None for x in a) for m,a in r["series"].items()} for v,r in report["metrics"].items()},"errors":errors[:10]}),flush=True)
    if not any(x is not None for r in report["metrics"].values() for a in r["series"].values() for x in a):
        raise RuntimeError("No fully matched scores; old archive preserved")
    target=path.with_name(month+"-ai.json")
    if target.exists():
        old=json.loads(target.read_text())
        if old.get("baseline_generated_utc")==report["baseline_generated_utc"]:
            for v,r in report["metrics"].items():
                for m,a in r["series"].items():
                    if any(p is not None and q is None for p,q in zip(old["metrics"][v]["series"][m],a)):
                        raise RuntimeError("Coverage decreased; old archive preserved")
    target.write_text(json.dumps(report,indent=2,ensure_ascii=False)+"\n")
if __name__=="__main__":
    parser=argparse.ArgumentParser()
    parser.add_argument("--month",required=True)
    build(parser.parse_args().month)
