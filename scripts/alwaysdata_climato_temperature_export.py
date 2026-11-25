"""KFS Infoclimat: bounded export of sampled daily temperatures.
No public endpoint, arbitrary commands, paths or URLs. Owner-authenticated MCP only.
Meteo-France TN: J-1 18 UTC to J 18 UTC; TX: J 06 UTC to J+1 06 UTC.
Sampled extrema are estimates, not certified daily extremes.
"""
import collections
import datetime as dt
import fcntl
import json
import math
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import time
from urllib.parse import urlencode

BASE=Path.home()/"kfs-infoclimat"
LOCK=BASE/".climato_temperature_export.lock"
OUT=BASE/"climato_temperature_export.json"
START=dt.date(2026,11,1)
END=dt.date(2026,11,23)
CATALOG="https://www.infoclimat.fr/opendata/stations_xhr.php?format=geojson"
API="https://www.infoclimat.fr/opendata/?"

def fetch(url):
    return json.loads(subprocess.check_output(
        ["curl","-4","-fsS","--max-time","90","--config","-"],
        input=('url = "'+url+'"\n').encode(),stderr=subprocess.DEVNULL))

def temperature(row):
    v=row.get("temperature")
    if isinstance(v,bool):return None
    try:v=float(v)
    except (ValueError,TypeError):return None
    return v if math.isfinite(v) and -45<=v<=55 else None

def add(series,sid,stamp,row):
    v=temperature(row)
    if v is None:return
    try:t=dt.datetime.strptime(stamp,"%Y-%m-%d %H:%M:%S")
    except (ValueError,TypeError):return
    hour=t.replace(minute=0,second=0)
    mins=series[sid].setdefault(hour,[v,v,t,t])
    mins[0]=min(mins[0],v);mins[1]=max(mins[1],v)
    mins[2]=min(mins[2],t);mins[3]=max(mins[3],t)

def lock():
    f=LOCK.open("a")
    try:fcntl.flock(f,fcntl.LOCK_EX|fcntl.LOCK_NB)
    except BlockingIOError:
        f.close();return None
    return f

def main():
    # Only explicitly open French Infoclimat stations in mainland geographical bounds.
    raw=fetch(CATALOG)
    catalog={}
    for f in raw["features"]:
        p=f["properties"];lic=p.get("license") or {}
        if not (p.get("country")=="FR" and lic.get("source")=="infoclimat.fr"
            and str(lic.get("code")) in ("0","1") and p.get("id")):continue
        try:lon,lat=map(float,f["geometry"]["coordinates"][:2])
        except (ValueError,TypeError,KeyError):continue
        if not (-5.8<=lon<=10.1 and 41<=lat<=51.6):continue
        sid=str(p["id"])
        catalog[sid]={"id":sid,"lon":round(lon,5),"lat":round(lat,5),
                      "license":str(lic["code"])}
    series=collections.defaultdict(dict)
    with sqlite3.connect((BASE/"climatologie.sqlite").as_uri()+"?mode=ro",uri=True,timeout=30) as db:
        for sid,stamp,data in db.execute("SELECT station,dh_utc,data FROM observations WHERE dh_utc>=? AND dh_utc<?",("2026-10-31 18:00:00","2026-11-25 00:00:00")):
            if sid not in catalog:continue
            try:row=json.loads(data)
            except (ValueError,TypeError):continue
            if isinstance(row,dict):add(series,sid,stamp,row)
    # Retrieve only the missing boundary preceding November, not the full archive.
    boundary=dt.datetime(2026,10,31,18)
    pending=[sid for sid in sorted(series) if any(boundary+dt.timedelta(hours=h) not in series[sid] for h in range(6))]
    token=(BASE/".token").read_text().strip()
    for i in range(0,len(pending),20):
        batch=pending[i:i+20]
        params=[("method","get"),("format","json"),("token",token),("start","2026-10-31"),("end","2026-11-01")]
        params.extend(("stations[]",sid) for sid in batch)
        with (BASE/".collect.lock").open("a") as f:
            fcntl.flock(f,fcntl.LOCK_EX)
            data=fetch(API+urlencode(params))
        if str(data.get("status")).lower()!="ok" or not isinstance(data.get("hourly"),dict):
            raise ValueError("Boundary API response invalid")
        for sid in batch:
            for row in data["hourly"].get(sid,[]):
                if not isinstance(row,dict):continue
                stamp=row.get("dh_utc","")
                if isinstance(stamp,str) and "2026-10-31 18:00:00"<=stamp<"2026-11-01 00:00:00":
                    add(series,sid,stamp,row)
        time.sleep(2)
    records=[]
    for sid,hours in sorted(series.items()):
        def extrema(begin,minimum):
            blocks=[hours.get(begin+dt.timedelta(hours=h)) for h in range(24)]
            if any(x is None for x in blocks):return None
            # Reject gaps > 60 min between successive hourly groups.
            if any(b[2]-a[3]>dt.timedelta(hours=1) for a,b in zip(blocks,blocks[1:])):return None
            return (min(x[0] for x in blocks) if minimum else max(x[1] for x in blocks))
        days=[]
        for i in range((END-START).days+1):
            day=START+dt.timedelta(days=i);mid=dt.datetime.combine(day,dt.time())
            tn=extrema(mid-dt.timedelta(hours=6),True)
            tx=extrema(mid+dt.timedelta(hours=6),False)
            if tn is None or tx is None or tx<tn:break
            days.append([round(tn,2),round(tx,2)])
        if days:records.append({**catalog[sid],"days":days})
    report={"schema":1,"source":"Infoclimat - stations ouvertes","start":str(START),"end":str(END),
            "method":"sampled extrema; TN 18-18 UTC, TX 06-06 UTC; 24 hourly bins, gaps between bins <=60 min; non certified",
            "stations":records}
    tmp=OUT.with_suffix(".tmp")
    tmp.write_text(json.dumps(report,separators=(",",":")))
    tmp.replace(OUT)
    print("Export:",len(records),"stations;",sum(len(r["days"])==23 for r in records),"through Nov 23",flush=True)

def preparer_export_temperature() -> dict:
    """Prepare un export climatologique borne du 1 au 23 novembre 2026."""
    f=lock()
    if f is None:return {"statut":"Export en cours"}
    with f:
        env={"HOME":str(Path.home()),"PATH":"/usr/bin:/bin","LANG":"C.UTF-8"}
        with (BASE/"climato_temperature_export.log").open("w") as log:
            p=subprocess.Popen([sys.executable,str(Path(__file__).resolve())],cwd=BASE,env=env,
                  stdout=log,stderr=log,start_new_session=True,pass_fds=(f.fileno(),))
        return {"statut":"Export lance","pid":p.pid}

def lire_export_temperature(jour_fin:int=23,offset:int=0,limite:int=80) -> dict:
    """Exporte seulement les agregats temperature/gel publics a date fixe; aucun secret."""
    if not 1<=jour_fin<=23 or not 0<=offset<=1000 or not 1<=limite<=100:
        return {"statut":"Parametres hors limites"}
    f=lock()
    if f is None:return {"statut":"Export en cours"}
    with f:
        if not OUT.exists():return {"statut":"Export indisponible"}
        report=json.loads(OUT.read_text())
        rows=[]
        for r in report["stations"]:
            if len(r["days"])<jour_fin:continue
            days=r["days"][:jour_fin]
            rows.append({k:r[k] for k in ("id","lon","lat","license")}|{
                "temp":round(sum((tn+tx)/2 for tn,tx in days)/jour_fin,3),
                "frost":sum(tn<=0 for tn,tx in days)})
        return {"statut":"Export disponible","start":report["start"],
                "end":str(START+dt.timedelta(days=jour_fin-1)),
                "method":report["method"],"total":len(rows),
                "offset":offset,"next_offset":offset+limite if offset+limite<len(rows) else None,
                "stations":rows[offset:offset+limite]}

if __name__=="__main__":
    try:main()
    except Exception as exc:
        print("Export interrompu:",type(exc).__name__,file=sys.stderr)
        sys.exit(1)
