#!/usr/bin/env python3
"""Check real 0-72h model output availability without downloading GRIB data.

This is a low-cost watcher, not a claim of zero-latency publication.
ECMWF may publish successive steps at different moments; the 72h probe only
becomes 'complete_72h' when its native file is advertised by the source.
NOAA is checked against original GRIB index files via HTTPS HEAD.
"""
from __future__ import annotations
from datetime import datetime, timedelta, timezone
from pathlib import Path
import json
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError

OUT=Path("forecast-maps/france/latest-cycles.json")
SPECS={
    "ifs":{"hour":3,"source":"ECMWF IFS Open Data"},
    "aifs-single":{"hour":6,"source":"ECMWF AIFS Open Data"},
    "gfs":{"hour":3,"source":"NOAA NCEP GFS"},
    "aigfs":{"hour":6,"source":"NOAA NCEP AIGFS"},
}


def iso(dt):
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def stamp(value):
    if isinstance(value,datetime):
        return iso(value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value)
    dt=datetime.fromisoformat(str(value).replace("Z","+00:00"))
    return iso(dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt)


def ecmwf_latest(model, step):
    from ecmwf.opendata import Client
    client=Client(source="ecmwf",model=model,resol="0p25")
    return stamp(client.latest(stream="oper",type="fc",step=step,param="2t"))


def noaa_index(model, cycle, step):
    date=cycle.strftime("%Y%m%d")
    hh=cycle.strftime("%H")
    if model=="gfs":
        path=f"gfs.{date}/{hh}/atmos/gfs.t{hh}z.pgrb2.0p25.f{step:03}.idx"
        url="https://nomads.ncep.noaa.gov/pub/data/nccf/com/gfs/prod/"+path
    else:
        path=f"aigfs.{date}/{hh}/model/atmos/grib2/aigfs.t{hh}z.sfc.f{step:03}.grib2.idx"
        url="https://nomads.ncep.noaa.gov/pub/data/nccf/com/aigfs/prod/"+path
    try:
        req=Request(url,method="HEAD",headers={"User-Agent":"KFS-Meteo/1.0"})
        with urlopen(req,timeout=12) as response:
            return response.status==200 and int(response.headers.get("Content-Length","0"))>0
    except (HTTPError,URLError,TimeoutError,ValueError):
        return False


def noaa_latest(model, step):
    now=datetime.now(timezone.utc)
    cycle=now.replace(minute=0,second=0,microsecond=0)
    cycle=cycle.replace(hour=(cycle.hour//6)*6)
    for n in range(8):
        choice=cycle-timedelta(hours=6*n)
        if noaa_index(model,choice,step):
            return iso(choice)
    return None


def main():
    old={}
    if OUT.is_file():
        try: old=json.loads(OUT.read_text(encoding="utf-8"))
        except (ValueError,OSError): pass
    models={}
    warnings={}
    for model,info in SPECS.items():
        interval=info["hour"]
        try:
            if model in ("ifs","aifs-single"):
                initial=ecmwf_latest(model,interval)
                complete=ecmwf_latest(model,72)
            else:
                initial=noaa_latest(model,interval)
                complete=noaa_latest(model,72)
            if initial is None:
                warnings[model]="Le nouveau run n'a pas ete confirme par la source NOAA"
            models[model]={
                "source":info["source"],"native_step_h":interval,
                "latest_first_step_utc":initial,
                "latest_72h_temperature_step_utc":complete,
                "temperature_72h_available_for_latest_run":bool(initial and complete and initial==complete),
                "all_required_fields_verified":False,  # must be checked by GRIB atlas generation
            }
        except Exception as exc:
            previous=old.get("models",{}).get(model,{})
            models[model]={**previous,"source":info["source"],
                           "native_step_h":interval,"check_error":str(exc)[:200]}
            warnings[model]="Echec de la verification : pas de nouveau run annonce"
    same=(models==old.get("models"))
    if same:
        print("No new verified source cycle; no repository commit")
        return
    output={"schema":1,"generated_utc":iso(datetime.now(timezone.utc)),
            "models":models,"warnings":warnings,
            "note":"Latest source availability, not a completed/posted forecast map. GitHub scheduled checks may be delayed."}
    OUT.parent.mkdir(parents=True,exist_ok=True)
    OUT.write_text(json.dumps(output,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print(json.dumps(output,ensure_ascii=False,indent=2))


if __name__=="__main__":
    main()
