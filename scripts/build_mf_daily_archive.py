"""Public Météo-France daily station archive, compact monthly coverage index."""
import csv, gzip, io, json, math, time, urllib.request, urllib.error
from pathlib import Path
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from concurrent.futures import ThreadPoolExecutor

BASE="https://meteofrance.s3.sbg.io.cloud.ovh.net/data/synchro_ftp/"
OUT=Path("climato/mf-daily")
DEPS=[f"{i:02d}" for i in range(1,96) if i!=20]+["2A","2B"]
TODAY=datetime.now(ZoneInfo("Europe/Paris")).date()
YEAR=TODAY.year
LIMIT=(TODAY-timedelta(days=1)).strftime("%Y%m%d")
FIELDS=["tn","tx","tm","rr","gust","wind","gustUtc"]
def fetch(url):
    return urllib.request.urlopen(urllib.request.Request(url,headers={"User-Agent":"KFS-Meteo climatologie quotidienne"}),timeout=90)
def val(row,k):
    try:
        v=float(row.get(k,"").replace(",","."))
        q=row.get("Q"+k,"").strip()
        return v if math.isfinite(v) and (not q or float(q) in (0,1,9)) else None
    except (ValueError,TypeError,AttributeError):return None
def put(path,data):
    path.parent.mkdir(parents=True,exist_ok=True)
    tmp=path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data,ensure_ascii=False,separators=(",",":"),allow_nan=False))
    tmp.replace(path)
def collect(dep):
    url=BASE+f"BASE/QUOT/Q_{dep}_latest-2025-2026_RR-T-Vent.csv.gz"
    for attempt in range(2):
        try:
            stations={}
            with fetch(url) as f:
                for r in csv.DictReader(io.TextIOWrapper(gzip.GzipFile(fileobj=f),encoding="utf-8-sig"),delimiter=";"):
                    sid=r.get("NUM_POSTE","");day=r.get("AAAAMMJJ","")
                    if len(sid)!=8 or not sid.isdigit() or len(day)!=8 or not day.startswith(str(YEAR)) or day>LIMIT:continue
                    tn,tx,tm,rr=map(lambda k:val(r,k),("TN","TX","TM","RR"))
                    if tm is None:tm=val(r,"TNTXM")
                    gust=val(r,"FXI");gh=val(r,"HXI")
                    if gust is None:gust=val(r,"FXI3S");gh=val(r,"HXI3S")
                    wind=val(r,"FFM")
                    vals=[tn,tx,tm,rr if rr is not None and rr>=0 else None,gust*3.6 if gust is not None and 0<=gust<=150 else None,wind*3.6 if wind is not None and 0<=wind<=100 else None,str(int(gh)).zfill(4) if gh is not None and 0<=gh<=2359 and int(gh)%100<60 else None]
                    if any(v is not None for v in vals[:6]):stations.setdefault(sid,{})[day]=[round(v,2) if isinstance(v,float) else v for v in vals]
            if not stations:raise ValueError("No valid current year rows")
            return dep,stations,None
        except Exception as e:
            err=str(e);time.sleep(1)
    return dep,{},err
def main():
    if YEAR!=2026:raise SystemExit("Update source period for new year")
    with fetch(BASE+"REF_STATION/liste_fiches_clim.geojson") as f:geo=json.load(f)
    catalog={}
    for f in geo["features"]:
        try:
            sid=str(f["properties"]["num"]).zfill(8);lon,lat=f["geometry"]["coordinates"][:2]
            if -6<=lon<=10 and 41<=lat<=52:catalog[sid]=[f["properties"].get("nom",sid),lon,lat]
        except (KeyError,TypeError,ValueError):pass
    records={};failed=[]
    with ThreadPoolExecutor(max_workers=6) as ex:
        for dep,stations,err in ex.map(collect,DEPS):
            if err:failed.append(dep);print(dep,err,flush=True);continue
            records.update(stations);print(dep,len(stations),flush=True)
    if len(failed)>8 or len(records)<400:raise SystemExit("Coverage insufficient; previous edition retained")
    stamp=datetime.now(ZoneInfo("Europe/Paris")).isoformat()
    index=[]
    for sid,days in sorted(records.items()):
        if sid not in catalog:continue
        months=[[0]*6 for _ in range(12)]
        rows=[]
        for day,v in sorted(days.items()):
            for i,x in enumerate(v[:6]):
                if x is not None:months[int(day[4:6])-1][i]+=1
            rows.append([day[:4]+"-"+day[4:6]+"-"+day[6:],*v])
        if not rows:continue
        name,lon,lat=catalog[sid]
        put(OUT/str(YEAR)/(sid+".json"),dict(schema=1,station=sid,year=YEAR,fields=FIELDS,generated_at=stamp,rows=rows))
        index.append(dict(id=sid,name=name,lon=lon,lat=lat,months=months,first=rows[0][0],last=rows[-1][0]))
    put(OUT/str(YEAR)/"index.json",dict(schema=1,year=YEAR,generated_at=stamp,fields=FIELDS[:6],failed_departments=failed,stations=index))
    print("ARCHIVE",len(index),"stations",sum(len(records[s["id"]]) for s in index),"station-days",flush=True)
if __name__=="__main__":main()
