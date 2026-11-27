#!/usr/bin/env python3
"""NOAA AI synoptic proxies, strictly matched to the published KFS sample."""
import argparse,json
from datetime import datetime,timedelta,timezone
from pathlib import Path
import numpy as np
import xarray as xr
import fsspec
from build_external_ai_skill import BUCKET,MODELS,ALIASES,select_name,convert
from build_model_regimes import POINTS,VAR,REGIMES,retrieve_truth,retrieve_run,read_pressure,features,empty_results

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
            result={name:{} for name in POINTS}
            for var in (VAR,):
                field=ds[select_name(ds,ALIASES[var])]
                for name,(y,x) in POINTS.items():
                    iy=int(np.argmin(abs(lats-y)))
                    ix=int(np.argmin(abs((lons-x+180)%360-180)))
                    values=convert(field.isel({lat:iy,lon:ix}),var).transpose(t).values
                    result[name]={str(d):float(p) for d,p in zip(actual,values) if np.isfinite(p)}
            return result

def record(cell, model, run, actual, predicted):
    grad,event=actual
    pgrad,pevent=predicted
    cell["errors"][model]+=abs(pgrad-grad)
    k="tp" if pevent and event else "fp" if pevent else "fn" if event else "tn"
    cell["confusion"][model][k]+=1

def build(month):
    path=Path("data/model-skill")/(month+"-regimes.json")
    baseline=json.loads(path.read_text())
    base={k:v for k,v in baseline["models"].items() if k in ("ifs","aifs","aigfs","gfs")}
    if not {"ifs","aifs","gfs"}<=set(base): raise ValueError("Incomplete baseline")
    if {k:tuple(v) for k,v in baseline["points"].items()}!=POINTS: raise ValueError("Point mismatch")
    ref=retrieve_truth(month,datetime.now(timezone.utc).date())
    common=empty_results(base)
    extra={m:empty_results([m]) for m in MODELS}
    errors=[]
    for day in baseline["run_dates"]:
        run=datetime.fromisoformat(day).replace(tzinfo=timezone.utc)
        bundle={m:retrieve_run(run,api) for m,api in base.items()}
        ext={}
        for m in MODELS:
            try: ext[m]=load(run,m)
            except Exception as e:
                errors.append(f"{day} {m}: {str(e)[:350]}")
                print(errors[-1],flush=True)
        # Full baseline day samples only. At J+10 archive has 00Z, not 06/12/18.
        for i in range(10):
            for hour in (0,6,12,18):
                valid=(run+timedelta(days=i+1,hours=hour)).strftime("%Y-%m-%dT%H:%M")
                obs=read_pressure(ref,valid)
                pred={m:read_pressure(d,valid) for m,d in bundle.items()}
                if obs is None or any(x is None for x in pred.values()): continue
                actual=features(obs)
                computed={m:features(x) for m,x in pred.items()}
                xpred={m:read_pressure(d,valid) for m,d in ext.items()}
                for key in REGIMES:
                    cell=common[key][i]
                    cell["n"]+=1
                    event=actual[key][1]
                    cell["observed_event_n" if event else "observed_nonevent_n"]+=1
                    cell["event_runs" if event else "nonevent_runs"].add(day)
                    for m in base: record(cell,m,day,actual[key],computed[m][key])
                    for m,x in xpred.items():
                        if x is None: continue
                        ec=extra[m][key][i]
                        ec["n"]+=1
                        record(ec,m,day,actual[key],features(x)[key])
        print("REGIME_RUN",day,list(ext),flush=True)
    report={"schema":1,"period":month,"baseline_generated_utc":baseline["generated_utc"],"models":MODELS,"run_dates":baseline["run_dates"],"method":"Same KFS dates, points, UTC hours, ERA5 and full reproduced confusion matrices / gradients. NOAA AI IFS initialization. Full 6-hourly day coverage through J+9; J+10 only if baseline has no later hours.","regimes":{},"errors":errors}
    for key in REGIMES:
        prior=baseline["regimes"][key]
        out={f:{m:[] for m in MODELS} for f in ("n_by_model","scores_pct","index_mae_hpa","confusion")}
        for i,cell in enumerate(common[key]):
            n=cell["n"]
            matched=n>0 and n==prior["n"][i] and cell["observed_event_n"]==prior["event_n"][i] and cell["observed_nonevent_n"]==prior["nonevent_n"][i] and len(cell["event_runs"])==prior["event_run_n"][i] and len(cell["nonevent_runs"])==prior["nonevent_run_n"][i] and all(cell["confusion"][m]==prior["confusion"][m][i] and prior["index_mae_hpa"][m][i] is not None and abs(cell["errors"][m]/n-prior["index_mae_hpa"][m][i])<=0.000501 for m in base)
            enough=n>=10 and cell["observed_event_n"]>=4 and cell["observed_nonevent_n"]>=4 and len(cell["event_runs"])>=2 and len(cell["nonevent_runs"])>=2
            for m in MODELS:
                ec=extra[m][key][i]
                ok=matched and ec["n"]==n
                matrix=ec["confusion"][m]
                out["n_by_model"][m].append(n if ok else 0)
                out["index_mae_hpa"][m].append(round(ec["errors"][m]/n,3) if ok else None)
                out["confusion"][m].append(matrix if ok else None)
                out["scores_pct"][m].append(round(50*(matrix["tp"]/(matrix["tp"]+matrix["fn"])+matrix["tn"]/(matrix["tn"]+matrix["fp"])),1) if ok and enough else None)
        report["regimes"][key]=out
    print("REGIME_COVERAGE",json.dumps({k:{m:sum(x is not None for x in v["index_mae_hpa"][m]) for m in MODELS} for k,v in report["regimes"].items()}),flush=True)
    if not any(x is not None for r in report["regimes"].values() for a in r["index_mae_hpa"].values() for x in a):
        raise RuntimeError("No fully matched regime scores")
    target=path.with_name(month+"-regimes-ai.json")
    if target.exists():
        old=json.loads(target.read_text())
        if old.get("baseline_generated_utc")==report["baseline_generated_utc"]:
            for key,r in report["regimes"].items():
                for m,a in r["index_mae_hpa"].items():
                    if any(p is not None and q is None for p,q in zip(old["regimes"][key]["index_mae_hpa"][m],a)): raise RuntimeError("Coverage decreased; prior archive preserved")
    target.write_text(json.dumps(report,indent=2,ensure_ascii=False)+"\n")
if __name__=="__main__":
    p=argparse.ArgumentParser()
    p.add_argument("--month",required=True)
    build(p.parse_args().month)
