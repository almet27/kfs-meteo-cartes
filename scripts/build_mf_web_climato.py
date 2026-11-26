"""Interactive station maps: every eligible MF station, common comparison period.
Observations do not require historical references. No missing value is zero.
"""
import calendar,datetime as dt,json,math,statistics
from pathlib import Path
ROOT=Path("climato/mf-daily/2026")
REF=Path("climato/mf-reference")
OUT=Path("climato/mf-web")
METRICS=["temperature-observee.png","pluie-observee.png","gel-observe.png","rafales-max.png","temperature-anomalie.png","pluie-anomalie.png","gel-anomalie.png","tmin-observee.png","tmax-observee.png","vent-moyen.png"]
def read(p):return json.loads(p.read_text())
def save(p,d):
    p.parent.mkdir(parents=True,exist_ok=True);t=p.with_suffix(".tmp");t.write_text(json.dumps(d,ensure_ascii=False,separators=(",",":"),allow_nan=False));t.replace(p)
def main():
    idx=read(ROOT/"index.json");year=idx["year"]
    docs={s["id"]:read(ROOT/(s["id"]+".json")) for s in idx["stations"]}
    assert all(d["generated_at"]==idx["generated_at"] and d["fields"]==["tn","tx","tm","rr","gust","wind","gustUtc"] for d in docs.values())
    refs={}
    for sid in docs:
        try:
            r=read(REF/(sid+".json"))
            if r["station"]==sid and r["reference"]=="1991-2020" and r["fields"]==["tn","tx","tm","rr","wind","frost","wet1"]:refs[sid]=r
        except (OSError,ValueError,KeyError):pass
    # A uniform latest date with substantial coverage, not the longest isolated series.
    last=max(s["last"] for s in idx["stations"]);latest=dt.date.fromisoformat(last)
    for month in range(1,latest.month+1):
        n=latest.day if month==latest.month else calendar.monthrange(year,month)[1]
        prefix=f"{year}-{month:02d}"
        days=[f"{prefix}-{d:02d}" for d in range(1,n+1)]
        result=[]
        for st in idx["stations"]:
            sid=st["id"];rows={r[0]:r for r in docs[sid]["rows"] if r[0].startswith(prefix)}
            def series(i):
                a=[rows.get(d,[None]*8)[i] for d in days]
                return a if all(type(v) in (float,int) and math.isfinite(v) for v in a) else None
            tn,tx,tm,rr,gust,wind=[series(i) for i in range(1,7)]
            t=statistics.mean(tm) if tm else None
            rain=sum(rr) if rr else None
            frost=sum(x<=0 for x in tn) if tn else None
            g=max(gust) if gust else None
            ref=refs.get(sid,{}).get("months")
            vals=ref[month-1][n-1] if ref and len(ref[month-1])>=n else []
            def normal(i):
                if len(vals)<=i:return None
                a=vals[i];v=a.get("v");return v if a.get("n",0)>=24 and type(v) in (int,float) and math.isfinite(v) else None
            rt,rp,rf=normal(2),normal(3),normal(5)
            numbers=[t,rain,frost,g,t-rt if t is not None and rt is not None else None,100*(rain/rp-1) if rain is not None and rp is not None and rp>0 else None,frost-rf if frost is not None and rf is not None else None,statistics.mean(tn) if tn else None,statistics.mean(tx) if tx else None,statistics.mean(wind) if wind else None]
            if any(v is not None for v in numbers):result.append([sid,st["name"],st["lon"],st["lat"],*[round(v,2) if v is not None else None for v in numbers]])
        counts={key:sum(r[4+i] is not None for r in result) for i,key in enumerate(METRICS)}
        if counts[METRICS[0]]<400 or counts[METRICS[1]]<400:raise ValueError(f"Insufficient coverage: {prefix} {counts}")
        save(OUT/(prefix+".json"),{"schema":1,"month":prefix,"end":days[-1],"generated_at":idx["generated_at"],"source":"Météo-France Open Data","reference":"1991-2020","metrics":METRICS,"counts":counts,"stations":result})
        print(prefix,counts,flush=True)
    save(OUT/"latest.json",{"schema":1,"month":f"{year}-{latest.month:02d}","generated_at":idx["generated_at"]})
if __name__=="__main__":main()
