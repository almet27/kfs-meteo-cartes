"""KFS month-to-date maps, Météo-France daily stations."""
import os, json, gzip, csv, logging, math, statistics
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo
from pathlib import Path
import requests
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.colors import TwoSlopeNorm, Normalize
from matplotlib.cm import ScalarMappable
from matplotlib.patches import Polygon

BASE="https://meteofrance.s3.sbg.io.cloud.ovh.net/data/synchro_ftp/"
DEPS="02 05 06 08 13 14 15 17 19 21 22 25 27 29 31 33 34 35 36 38 40 42 44 45 49 51 54 57 59 62 63 64 65 66 67 69 71 72 75 76 79 80 83 84 85 86 87 88 89 90 2A 2B".split()
TODAY=datetime.now(ZoneInfo("Europe/Paris")).date()
END=TODAY-timedelta(days=1)
OUT=Path("climato/france")
CACHE=Path(".climato-cache")
OUT.mkdir(parents=True,exist_ok=True); CACHE.mkdir(exist_ok=True)
logging.basicConfig(level=logging.INFO,format="%(levelname)s %(message)s")

def fetch_json(url):
    r=requests.get(url,timeout=90); r.raise_for_status(); return r.json()

def station_catalog():
    d=fetch_json(BASE+"REF_STATION/liste_fiches_clim.geojson")
    out={}
    for f in d["features"]:
        try:
            p=f["properties"]; sid=str(p["num"]).zfill(8); lon,lat=f["geometry"]["coordinates"][:2]
            if -6<=lon<=10 and 41<=lat<=52: out[sid]=(float(lon),float(lat),p.get("nom",sid))
        except (KeyError,ValueError,TypeError): continue
    return out

def val(row, key):
    try:
        v=float(row.get(key,"").replace(",","."))
        q=row.get("Q"+key,"").strip()
        if not math.isfinite(v) or (q and float(q) not in (0,1,9)): return None
        return v
    except (ValueError,TypeError,AttributeError): return None

def read_dep(dep, typ, historic, ids):
    month=TODAY.month
    cache=CACHE/f"{dep}-{typ}-{month:02d}-v1.json"
    if historic and cache.exists():
        try: return json.loads(cache.read_text())
        except Exception: pass
    period="previous-1950-2024" if historic else "latest-2025-2026"
    # The department filenames for Corsica can differ from numeric station prefixes.
    url=BASE+f"BASE/QUOT/Q_{dep}_{period}_{typ}.csv.gz"
    rows=defaultdict(dict)
    for attempt in range(2):
        try:
            rows=defaultdict(dict)
            with requests.get(url,stream=True,timeout=(20,120)) as r:
                r.raise_for_status()
                r.raw.decode_content=True
                with gzip.GzipFile(fileobj=r.raw) as g:
                    import io
                    reader=csv.DictReader(io.TextIOWrapper(g,encoding="utf-8-sig"),delimiter=";")
                    for row in reader:
                        sid=row.get("NUM_POSTE",""); day=row.get("AAAAMMJJ","")
                        if sid not in ids or len(day)!=8 or day[4:6]!=f"{month:02d}": continue
                        y=int(day[:4])
                        if historic and not 1991<=y<=2020: continue
                        if not historic and (y!=TODAY.year or day>END.strftime("%Y%m%d")): continue
                        if typ=="RR-T-Vent":
                            tm=val(row,"TM")
                            if tm is None: tm=val(row,"TNTXM")
                            tn=val(row,"TN")
                            vals={"temp":tm,"rain":val(row,"RR"),"frost":None if tn is None else int(tn<=0)}
                        else:
                            sun=val(row,"INST"); vals={"sun":None if sun is None else sun/60}
                        rows[sid][day]={k:v for k,v in vals.items() if v is not None}
            if historic:
                tmp=cache.with_suffix(".tmp");tmp.write_text(json.dumps(rows,separators=(",",":")));tmp.replace(cache)
            return rows
        except Exception as e:
            logging.warning("%s %s %s attempt %s: %s",dep,typ,historic,attempt+1,e)
    return {}

def task(dep,catalog):
    ids={s for s in catalog if s[:2]==dep}
    if dep in ("2A","2B"):
        ids={s for s in catalog if s[:2]=="20" or s[:2]==dep}
    out={}
    for typ in ("RR-T-Vent","autres-parametres"):
        hist=read_dep(dep,typ,True,ids); obs=read_dep(dep,typ,False,ids)
        for sid in set(hist)&set(obs):
            entry=out.setdefault(sid,{"hist":{},"obs":{}})
            for name,data in [("hist",hist[sid]),("obs",obs[sid])]:
                for day,values in data.items():entry[name].setdefault(day,{}).update(values)
    return dep,out

def stat(entry,key,n):
    if n<1:return None
    obs=[entry["obs"].get(f"{TODAY.year}{TODAY.month:02d}{d:02d}",{}).get(key) for d in range(1,n+1)]
    if any(v is None for v in obs):return None
    reducer=statistics.mean if key=="temp" else sum
    annual=[]
    for y in range(1991,2021):
        seq=[entry["hist"].get(f"{y}{TODAY.month:02d}{d:02d}",{}).get(key) for d in range(1,n+1)]
        if all(v is not None for v in seq):annual.append(reducer(seq))
    minimum=6 if TODAY.month==2 and n==29 else 24
    if len(annual)<minimum:return None
    return reducer(obs),statistics.mean(annual),len(annual)

def select(results,key,n,catalog):
    selected={}
    for dep,entries in results.items():
        candidates=[]
        for sid,entry in entries.items():
            r=stat(entry,key,n)
            if r is None:continue
            if key in ("rain","sun") and r[1]<=0:continue
            candidates.append((r[2],sid,r))
        if candidates:
            _,sid,r=max(candidates,key=lambda x:(x[0],x[1]))
            selected[sid]=(catalog[sid],r)
    return selected

def render(points,boundaries,title,units,cmap,norm,metric,cutoff,filename):
    fig,ax=plt.subplots(figsize=(10,10),facecolor="#f5f7f8")
    ax.set_facecolor("#eaf1f4")
    for f in boundaries["features"]:
        geo=f.get("geometry",{}); p=geo.get("coordinates",[])
        polys=[p] if geo.get("type")=="Polygon" else p if geo.get("type")=="MultiPolygon" else []
        for poly in polys:
            if not poly or not any(-6.5<x<10.5 and 41<y<52 for x,y,*_ in poly[0]):continue
            ax.add_patch(Polygon(poly[0],closed=True,facecolor="#fafafa",edgecolor="#a4afb6",linewidth=.55,zorder=1))
    values=[v for _,v in points]
    if not values:raise ValueError("No points")
    xs=[p[0] for p,_ in points];ys=[p[1] for p,_ in points]
    ax.scatter(xs,ys,c=values,s=225,cmap=cmap,norm=norm,edgecolor="#36434a",linewidth=.6,zorder=3)
    for (lon,lat,_),v in points:
        rgba=plt.get_cmap(cmap)(norm(v)); lum=.2126*rgba[0]+.7152*rgba[1]+.0722*rgba[2]
        label=f"{v:+.1f}" if metric=="temp" else f"{v:+.0f}" if "anomalie" in filename else f"{v:.0f}"
        ax.text(lon,lat,label,ha="center",va="center",fontsize=7.3,fontweight="bold",color="#101820" if lum>.58 else "white",zorder=4)
    ax.set_xlim(-5.7,9.9);ax.set_ylim(41.1,51.5);ax.set_aspect(1/math.cos(math.radians(46.5)));ax.set_xticks([]);ax.set_yticks([])
    for spine in ax.spines.values():spine.set_visible(False)
    fig.suptitle("KFS MÉTÉO  |  CLIMATOLOGIE",x=.5,y=.975,fontsize=15,fontweight="bold",color="#385064")
    ax.set_title(title,fontsize=19,fontweight="bold",pad=14,color="#1c2a35")
    sm=ScalarMappable(norm=norm,cmap=cmap);sm.set_array([])
    bar=fig.colorbar(sm,ax=ax,orientation="horizontal",fraction=.045,pad=.035,aspect=32,extend="both")
    bar.set_label(units)
    fig.text(.5,.035,f"Du 1er au {cutoff.strftime('%d/%m/%Y')}  •  {len(points)} stations  •  Météo-France",ha="center",fontsize=11,fontweight="bold")
    fig.text(.5,.015,"Observations ponctuelles • référence 1991–2020 sur les mêmes dates • aucune interpolation",ha="center",fontsize=9,color="#52606b")
    fig.savefig(OUT/filename,dpi=150,bbox_inches="tight",pad_inches=.2);plt.close(fig)

def main():
    if END.month!=TODAY.month:raise SystemExit("Pas encore de journée complète du mois.")
    catalog=station_catalog()
    results={}
    with ThreadPoolExecutor(max_workers=6) as pool:
        jobs={pool.submit(task,d,catalog):d for d in DEPS}
        for job in as_completed(jobs):
            try:
                dep,rows=job.result();results[dep]=rows;logging.info("%s %s stations",dep,len(rows))
            except Exception as e: logging.warning("%s: %s",jobs[job],e)
    boundaries=fetch_json("https://raw.githubusercontent.com/gregoiredavid/france-geojson/master/departements-version-simplifiee.geojson")
    manifest={"schema":1,"month":TODAY.strftime("%Y-%m"),"generated_at":datetime.now(ZoneInfo("Europe/Paris")).isoformat(),"source":"Météo-France, observations quotidiennes","maps":[]}
    for key,minimum in [("temp",15),("rain",15),("sun",8),("frost",15)]:
        picks={}
        for n in range(END.day,0,-1):
            picks=select(results,key,n,catalog)
            if len(picks)>=minimum:break
        else:
            logging.warning("Insufficient coverage for %s",key);continue
        cutoff=TODAY.replace(day=n)
        specs={
            "temp":[("temperature-anomalie.png","Anomalie de température moyenne","Écart (°C)","RdBu_r",TwoSlopeNorm(vmin=-5,vcenter=0,vmax=5),lambda o,r:o-r)],
            "rain":[("pluie-cumul.png","Cumul des précipitations","mm","Blues",Normalize(0,max(100,max(r[0] for _,r in picks.values()))),lambda o,r:o),("pluie-anomalie.png","Anomalie de précipitations","Écart (%)","BrBG",TwoSlopeNorm(vmin=-100,vcenter=0,vmax=100),lambda o,r:(o/r-1)*100)],
            "sun":[("soleil-cumul.png","Cumul d’ensoleillement","heures","YlOrBr",Normalize(0,max(100,max(r[0] for _,r in picks.values()))),lambda o,r:o),("soleil-anomalie.png","Anomalie d’ensoleillement","Écart (%)","PuOr_r",TwoSlopeNorm(vmin=-100,vcenter=0,vmax=100),lambda o,r:(o/r-1)*100)],
            "frost":[("gel-anomalie.png","Anomalie du nombre de jours de gel","Écart (jours)","RdBu",TwoSlopeNorm(vmin=-10,vcenter=0,vmax=10),lambda o,r:o-r)]
        }[key]
        for filename,title,units,cmap,norm,fn in specs:
            points=[(loc,fn(r[0],r[1])) for loc,r in picks.values()]
            render(points,boundaries,title,units,cmap,norm,key,cutoff,filename)
            manifest["maps"].append({"file":filename,"title":title,"end":cutoff.isoformat(),"stations":len(points)})
    if not any(m["file"]=="temperature-anomalie.png" for m in manifest["maps"]) or not any(m["file"]=="pluie-anomalie.png" for m in manifest["maps"]):
        raise SystemExit("Couverture température/pluie insuffisante : ne pas publier de cartes incomplètes.")
    (OUT/"latest.json").write_text(json.dumps(manifest,ensure_ascii=False,indent=2))
if __name__=="__main__":main()
