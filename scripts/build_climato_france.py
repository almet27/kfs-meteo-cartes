"""KFS month-to-date maps, Météo-France daily stations."""
import os, json, gzip, csv, logging, math, statistics
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo
from pathlib import Path
import requests
from climato_static_fusion import fetch_static, complete_static
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
                            tx=val(row,"TX")
                            vals={"temp":tm,"temp_mid":None if tn is None or tx is None or tx<tn else (tn+tx)/2,"rain":val(row,"RR"),"frost":None if tn is None else int(tn<=0)}
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
    coverage=set()
    for dep,entries in results.items():
        for sid,entry in entries.items():
            r=stat(entry,key,n)
            if r is None:continue
            if key in ("rain","sun") and r[1]<=0:continue
            selected[sid]=(catalog[sid],r)
            coverage.add(dep)
    return selected,len(coverage)

def render(points,boundaries,title,units,cmap,norm,metric,cutoff,filename,period_label=None,source_label="Météo-France",method_label=None):
    import numpy as np
    from matplotlib.path import Path as MplPath
    from matplotlib.colors import BoundaryNorm
    fig,ax=plt.subplots(figsize=(10,10),facecolor="#f5f7f8")
    ax.set_facecolor("#eaf1f4")
    # Interpolation IDW on a roughly 5 km mesh. Do not extrapolate beyond
    # 150 km of a station; require two stations within 200 km.
    gx=np.linspace(-5.7,9.9,310); gy=np.linspace(41.1,51.5,260)
    xx,yy=np.meshgrid(gx,gy)
    coords=np.column_stack((xx.ravel(),yy.ravel()))
    inside=np.zeros(len(coords),dtype=bool)
    outlines=[]
    for f in boundaries["features"]:
        geo=f.get("geometry",{}); p=geo.get("coordinates",[])
        polys=[p] if geo.get("type")=="Polygon" else p if geo.get("type")=="MultiPolygon" else []
        for poly in polys:
            if not poly or not any(-6.5<x<10.5 and 41<y<52 for x,y,*_ in poly[0]):continue
            outer=np.asarray(poly[0])[:,:2]
            mask=MplPath(outer).contains_points(coords)
            for hole in poly[1:]:
                mask &= ~MplPath(np.asarray(hole)[:,:2]).contains_points(coords)
            inside |= mask
            outlines.append(outer)
            ax.add_patch(Polygon(outer,closed=True,facecolor="#d9dee1",edgecolor="none",zorder=1))
    xs=np.array([p[0] for p,_ in points]);ys=np.array([p[1] for p,_ in points])
    values=np.array([v for _,v in points])
    if len(values)<2:raise ValueError("Insufficient stations")
    grid=np.full(len(coords),np.nan)
    covered=np.flatnonzero(inside)
    for block in np.array_split(covered,max(1,math.ceil(len(covered)/1000))):
        if not len(block):continue
        p=coords[block]
        dx=(p[:,0,None]-xs[None,:])*111.2*np.cos(np.radians((p[:,1,None]+ys[None,:])/2))
        dy=(p[:,1,None]-ys[None,:])*111.2
        dist=np.hypot(dx,dy)
        support=(dist<=200).sum(axis=1)>=2
        support &= dist.min(axis=1)<=150
        weights=np.where(dist<=200,1/np.maximum(dist,3)**2,0)
        denom=weights.sum(axis=1)
        grid[block[support]]= (weights[support]@values)/denom[support]
    if "anomalie" in filename:
        if metric=="temp": levels=[-5,-4,-3,-2,-1,-.5,.5,1,2,3,4,5]
        elif metric=="frost": levels=[-10,-7,-5,-3,-1,-.5,.5,1,3,5,7,10]
        else: levels=[-100,-75,-50,-25,-10,10,25,50,75,100]
    else:
        levels=np.linspace(norm.vmin,max(norm.vmin+1,norm.vmax),11)
    cm=plt.get_cmap(cmap,len(levels)-1)
    norm=BoundaryNorm(levels,cm.N,clip=True)
    ax.pcolormesh(xx,yy,np.ma.masked_invalid(grid.reshape(xx.shape)),cmap=cm,norm=norm,shading="nearest",zorder=2)
    for outer in outlines:
        ax.plot(outer[:,0],outer[:,1],color="#65727b",linewidth=.48,alpha=.8,zorder=3)
    # Label actual station anomalies, without overlapping nearby labels.
    # All eligible stations still enter the interpolation.
    from matplotlib import patheffects
    order=sorted(range(len(values)),key=lambda i:(-ys[i],xs[i]))
    plotted=[]
    for i in order:
        x,y,v=xs[i],ys[i],values[i]
        if any(math.hypot((x-px)*111.2*math.cos(math.radians((y+py)/2)),(y-py)*111.2)<65 for px,py in plotted):
            continue
        plotted.append((x,y))
        rgba=cm(norm(v))
        light=.2126*rgba[0]+.7152*rgba[1]+.0722*rgba[2]
        fg,bg=("#172029","white") if light>.52 else ("white","#20252b")
        label=(f"{v:+.1f}" if metric in ("temp","frost") else f"{v:+.0f}%") if "anomalie" in filename else (f"{v:.1f}" if metric=="temp" else f"{v:.0f}")
        ax.text(x,y,label,ha="center",va="center",fontsize=8.2,fontweight="bold",color=fg,zorder=4,
                path_effects=[patheffects.withStroke(linewidth=1.7,foreground=bg)])
    ax.set_xlim(-5.7,9.9);ax.set_ylim(41.1,51.5);ax.set_aspect(1/math.cos(math.radians(46.5)));ax.set_xticks([]);ax.set_yticks([])
    for spine in ax.spines.values():spine.set_visible(False)
    fig.suptitle("KFS MÉTÉO  |  CLIMATOLOGIE",x=.5,y=.975,fontsize=15,fontweight="bold",color="#385064")
    ax.set_title(title,fontsize=19,fontweight="bold",pad=14,color="#1c2a35")
    sm=ScalarMappable(norm=norm,cmap=cm);sm.set_array([])
    bar=fig.colorbar(sm,ax=ax,orientation="horizontal",fraction=.045,pad=.035,aspect=32,extend="both",ticks=levels)
    bar.set_label(units)
    fig.text(.5,.035,f"{period_label or cutoff.strftime('Du 1er au %d/%m/%Y')}  •  {len(points)} stations  •  {source_label}",ha="center",fontsize=11,fontweight="bold")
    fig.text(.5,.015,method_label or "Zonage interpolé (IDW) • valeurs aux stations • normales 1991–2020 • gris : données insuffisantes",ha="center",fontsize=9,color="#52606b")
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
    manifest={"schema":1,"month":TODAY.strftime("%Y-%m"),"generated_at":datetime.now(ZoneInfo("Europe/Paris")).isoformat(),"source":"Météo-France, observations quotidiennes","method":"IDW, 150 km max nearest station, 2 stations within 200 km","maps":[]}
    audit={}
    observed_cutoffs={}
    for key,minimum in [("temp",15),("rain",15),("sun",8),("frost",15)]:
        picks={}
        for n in range(END.day,0,-1):
            picks,coverage=select(results,key,n,catalog)
            if coverage>=minimum:break
        else:
            logging.warning("Insufficient coverage for %s",key);continue
        cutoff=TODAY.replace(day=n)
        observed_cutoffs[key]=cutoff
        audit[key]={"end":cutoff.isoformat(),"stations":[{"id":sid,"name":loc[2],"lon":loc[0],"lat":loc[1],"observed":round(r[0],4),"normal":round(r[1],4),"delta":round(r[0]-r[1],4),"reference_years":r[2]} for sid,(loc,r) in picks.items()]}
        if key=="temp":
            for row in audit[key]["stations"]:
                if abs(row["lon"]-3.10)<1.0 and abs(row["lat"]-50.57)<.65:
                    logging.info("LILLE AUDIT %s",json.dumps(row,ensure_ascii=False))
        specs={
            "temp":[("temperature-anomalie.png","Anomalie de température moyenne","Écart (°C)","RdBu_r",TwoSlopeNorm(vmin=-5,vcenter=0,vmax=5),lambda o,r:o-r)],
            "rain":[("pluie-anomalie.png","Anomalie de précipitations","Écart (%)","BrBG",TwoSlopeNorm(vmin=-100,vcenter=0,vmax=100),lambda o,r:(o/r-1)*100)],
            "sun":[("soleil-anomalie.png","Anomalie d’ensoleillement","Écart (%)","PuOr_r",TwoSlopeNorm(vmin=-100,vcenter=0,vmax=100),lambda o,r:(o/r-1)*100)],
            "frost":[("gel-anomalie.png","Anomalie du nombre de jours de gel","Écart (jours)","RdBu",TwoSlopeNorm(vmin=-10,vcenter=0,vmax=10),lambda o,r:o-r)]
        }[key]
        for filename,title,units,cmap,norm,fn in specs:
            points=[(loc,fn(r[0],r[1])) for loc,r in picks.values()]
            render(points,boundaries,title,units,cmap,norm,key,cutoff,filename)
            manifest["maps"].append({"file":filename,"title":title,"end":cutoff.isoformat(),"stations":len(points)})
    if not any(m["file"]=="temperature-anomalie.png" for m in manifest["maps"]) or not any(m["file"]=="pluie-anomalie.png" for m in manifest["maps"]):
        raise SystemExit("Couverture température/pluie insuffisante : ne pas publier de cartes incomplètes.")
    # Observed maps are additional, never a replacement for the anomaly maps.
    start=TODAY.replace(day=1)
    try:
        static=fetch_static(start,END,catalog)
    except Exception as exc:
        logging.warning("StatIC unavailable; observed maps MF only: %s",exc)
        static={}
    for key,filename,title,units,cmap in [
        ("temp","temperature-observee.png","Température moyenne observée","°C","RdYlBu_r"),
        ("rain","pluie-observee.png","Cumul de précipitations observé","mm","YlGnBu"),
        ("frost","gel-observe.png","Nombre de jours de gel observés","jours","Blues")
    ]:
        if key not in observed_cutoffs:continue
        cutoff=observed_cutoffs[key]
        def mf_points(until):
            points={}
            for entries in results.values():
                for sid,entry in entries.items():
                    vals=[entry["obs"].get(f"{TODAY.year}{TODAY.month:02d}{d:02d}",{}).get("temp_mid" if key=="temp" else key) for d in range(1,until.day+1)]
                    if vals and all(v is not None for v in vals):
                        points[sid]=(catalog[sid],statistics.mean(vals) if key=="temp" else sum(vals))
            return list(points.values())
        mf=mf_points(cutoff);ic=complete_static(static,key,start,cutoff)
        # Preserve freshness: only move back up to 7 days, and only if >= 3 StatIC
        # stations have complete data and the MF network still has sufficient coverage.
        if len(ic)<3:
            for back in range(1,8):
                older=cutoff-timedelta(days=back)
                if older<start:break
                trial=complete_static(static,key,start,older)
                if len(trial)>=3:
                    candidate=mf_points(older)
                    if len(candidate)>=30:
                        cutoff=older;mf=candidate;ic=trial;break
        if len(mf)<15:continue
        pts=mf+ic
        v=[p[1] for p in pts]
        lo=math.floor(min(v)) if key=="temp" else 0
        hi=max(lo+1,math.ceil(max(v)))
        if key=="temp":
            lo=math.floor(lo/2)*2;hi=math.ceil(hi/2)*2
        source=f"MF : {len(mf)}  •  StatIC : {len(ic)}"
        method="IDW • jours complets • "+("moyenne (Tn+Tx)/2" if key=="temp" else "cumul ; fenêtres journalières différentes selon réseau" if key=="rain" else "Tn ≤ 0 °C") 
        method+=" • données StatIC non certifiées" if ic else " • StatIC sans série complète"
        render(pts,boundaries,title,units,cmap,Normalize(vmin=lo,vmax=hi),key,cutoff,filename,source_label=source,method_label=method)
        manifest["maps"].append({"file":filename,"title":title,"end":cutoff.isoformat(),"stations":len(pts),"mf_stations":len(mf),"static_stations":len(ic),"kind":"observed_fusion","source":"Météo-France ; Infoclimat StatIC via chom.engineering (LO 2.0)"})
    (OUT/"station-audit.json").write_text(json.dumps(audit,ensure_ascii=False,separators=(",",":")))
    (OUT/"latest.json").write_text(json.dumps(manifest,ensure_ascii=False,indent=2))
if __name__=="__main__":main()
