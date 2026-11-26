"""Precompute 1991-2020 references for daily prefixes, and complete months.
Historical extremes limited to the explicitly stated reference period.
No request-time decompression; preserve prior output on department failure.
"""
import csv,gzip,io,json,math,calendar,statistics,urllib.request,datetime as dt
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
from collections import defaultdict

BASE="https://meteofrance.s3.sbg.io.cloud.ovh.net/data/synchro_ftp/"
ROOT=Path("climato/mf-daily")
OUT=Path("climato/mf-reference")
FIELDS=("tn","tx","tm","rr","wind","frost","wet1")
def val(r,k):
    try:
        v=float(r.get(k,"").replace(",","."))
        q=r.get("Q"+k,"").strip()
        return v if math.isfinite(v) and (not q or float(q) in (0,1,9)) else None
    except (ValueError,TypeError,AttributeError):return None
def save(p,d):
    p.parent.mkdir(parents=True,exist_ok=True)
    t=p.with_suffix(".tmp");t.write_text(json.dumps(d,ensure_ascii=False,separators=(",",":"),allow_nan=False));t.replace(p)
def read(dep,ids):
    rows=defaultdict(lambda:defaultdict(dict))
    url=BASE+f"BASE/QUOT/Q_{dep}_previous-1950-2024_RR-T-Vent.csv.gz"
    with urllib.request.urlopen(url,timeout=180) as f:
        with gzip.GzipFile(fileobj=f) as z:
            for r in csv.DictReader(io.TextIOWrapper(z,encoding="utf-8-sig"),delimiter=";"):
                sid=r.get("NUM_POSTE","");day=r.get("AAAAMMJJ","")
                if sid not in ids or len(day)!=8 or not "19910101"<=day<="20201231":continue
                y,m,d=int(day[:4]),int(day[4:6]),int(day[6:])
                tn,tx,tm,rr,w=map(lambda k:val(r,k),("TN","TX","TM","RR","FFM"))
                if tm is None:tm=val(r,"TNTXM")
                if rr is not None and rr<0:rr=None
                rows[sid][(y,m)][d]=(tn,tx,tm,rr,w*3.6 if w is not None and w>=0 else None,int(tn<=0) if tn is not None else None,int(rr>=1) if rr is not None else None)
    return rows
def station(sid,rows):
    months=[]
    for m in range(1,13):
        nmax=calendar.monthrange(2024,m)[1]
        # one entry per prefix length, each variable independently validated.
        accum=[[[] for _ in FIELDS] for _ in range(nmax)]
        for y in range(1991,2021):
            daily=rows.get((y,m),{})
            sums=[0.]*len(FIELDS);ok=[True]*len(FIELDS)
            for day in range(1,calendar.monthrange(y,m)[1]+1):
                row=daily.get(day,(None,)*len(FIELDS))
                for i,v in enumerate(row):
                    if v is None:ok[i]=False
                    if ok[i]:
                        sums[i]+=v
                        accum[day-1][i].append(sums[i]/day if i in (0,1,2,4) else sums[i])
        months.append([[{"n":len(v),"v":round(statistics.mean(v),3) if len(v)>=(6 if m==2 and day==29 else 24) else None} for v in a] for day,a in enumerate(accum,1)])
    return {"schema":1,"station":sid,"reference":"1991-2020","fields":FIELDS,"months":months}
def task(item):
    dep,ids=item
    try:
        rows=read(dep,ids)
        if not rows:raise ValueError("No historical rows")
        for sid,r in rows.items():save(OUT/(sid+".json"),station(sid,r))
        return dep,len(rows),None
    except Exception as e:return dep,0,str(e)
def main():
    idx=json.loads((ROOT/"2026"/"index.json").read_text())
    deps=defaultdict(set)
    for st in idx["stations"]:
        sid=st["id"];deps[sid[:2]].add(sid)
    results=[]
    with ThreadPoolExecutor(max_workers=4) as pool:
        for result in pool.map(task,sorted(deps.items())):
            results.append(result);print(result,flush=True)
    n=sum(r[1] for r in results)
    if n<400:raise SystemExit("Coverage insufficient; do not publish")
    save(OUT/"index.json",{"schema":1,"reference":"1991-2020","generated_at":dt.datetime.now(dt.timezone.utc).isoformat(),"stations":n,"departments_failed":[r[0] for r in results if r[2]]})
if __name__=="__main__":main()
