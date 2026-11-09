#!/usr/bin/env python3
"""KFS France: surveiller les runs ARÔME/ICON disponibles chez Open-Meteo.

Une nouvelle initialisation *disponible* implique la régénération des cartes
nationales. Les fichiers GRIB bruts n'ont pas à être téléchargés par le watcher.
"""
from __future__ import annotations
from datetime import datetime,timezone,timedelta
from pathlib import Path
from urllib.request import Request,urlopen
from urllib.error import URLError,HTTPError
import json,os,time

META={
 "arome":"meteofrance_arome_france0025",
 "icon_eu":"dwd_icon_eu"
}
BASE="https://api.open-meteo.com/data/"
OUT=Path("forecast-maps/france/risques/latest.json")

def stamp(unix):
    t=float(unix)
    return datetime.fromtimestamp(t,tz=timezone.utc)

def get_run(model,code):
    url=BASE+code+"/static/meta.json"
    request=Request(url,headers={"User-Agent":"KFS-Meteo-Run-Watcher/1.0"})
    error=None
    for attempt in range(4):
        try:
            with urlopen(request,timeout=20) as r:
                j=json.load(r)
            error=None
            break
        except (URLError,HTTPError,TimeoutError,OSError,ValueError) as exc:
            error=exc
            if isinstance(exc,HTTPError) and exc.code in (400,401,403,404):
                raise
            print("KFS_RUN_META_RETRY",model,attempt+1,str(exc)[:130],flush=True)
            if attempt<3:time.sleep(2*(attempt+1))
    if error is not None:
        raise RuntimeError("Métadonnées Open-Meteo momentanément indisponibles : "+str(error)[:150])
    init=stamp(j["last_run_initialisation_time"])
    available=stamp(j["last_run_availability_time"])
    now=datetime.now(timezone.utc)
    if init>now+timedelta(minutes=10) or now-init>timedelta(hours=20):
        raise RuntimeError("Run "+model+" absent, trop ancien ou futur")
    if available<init or available>now+timedelta(minutes=10):
        raise RuntimeError("Disponibilité incohérente "+model)
    return {"run_utc":init.isoformat(),
            "available_utc":available.isoformat(),
            "model_code":code}

def run_info():
    return {model:get_run(model,code) for model,code in META.items()}

def main():
    fresh=run_info()
    try:
        previous=json.loads(OUT.read_text(encoding="utf-8"))
    except (OSError,ValueError):
        previous={}
    old=previous.get("model_runs",{})
    changes=[model for model,data in fresh.items()
             if data["run_utc"]!=old.get(model,{}).get("run_utc")]
    print("KFS_FRANCE_RUN_CHECK",json.dumps({"current":fresh,
        "published":old,"new_models":changes},ensure_ascii=False),flush=True)
    desired=bool(changes)
    if os.environ.get("GITHUB_OUTPUT"):
        with open(os.environ["GITHUB_OUTPUT"],"a",encoding="utf-8") as f:
            f.write("generate="+str(desired).lower()+"\n")
    print("KFS_FRANCE_GENERATE",str(desired).lower(),flush=True)

if __name__=="__main__":
    main()
