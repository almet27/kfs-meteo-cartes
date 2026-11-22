"""Monthly/yearly archived station anomaly maps. Read each departmental archive once per year."""
import calendar,csv,gzip,io,json,logging,math,os,statistics,sys
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor,as_completed
from datetime import date,datetime,timedelta
from pathlib import Path
from zoneinfo import ZoneInfo
import requests
from matplotlib.colors import TwoSlopeNorm
import build_climato_france as core
from climato_zones import zone_files

YEAR=int(sys.argv[1])
NOW=datetime.now(ZoneInfo("Europe/Paris")).date()
if not 1950<=YEAR<=NOW.year:raise SystemExit("Year must be 1950 to current year")
LAST=12 if YEAR<NOW.year else NOW.month-1
ROOT=Path(f"climato/archive/{YEAR}")
ROOT.mkdir(parents=True,exist_ok=True)
KEYS=("temp","rain","sun","frost")
DEPS=core.DEPS
SPECS={
 "temp":("temperature-anomalie.png","Anomalie de température moyenne","Écart (°C)","RdBu_r",5),
 "rain":("pluie-anomalie.png","Anomalie de précipitations","Écart (%)","BrBG",100),
 "sun":("soleil-anomalie.png","Anomalie d’ensoleillement","Écart (%)","PuOr_r",100),
 "frost":("gel-anomalie.png","Anomalie du nombre de jours de gel","Écart (jours)","RdBu",10)}
def download(dep,typ,period,ids,years):
    result={ }
    url=core.BASE+f"BASE/QUOT/Q_{dep}_{period}_{typ}.csv.gz"
    for attempt in range(2):
        try:
            result={ }
            with requests.get(url,stream=True,timeout=(20,150)) as r:
                r.raise_for_status();r.raw.decode_content=True
                with gzip.GzipFile(fileobj=r.raw) as gz:
                    reader=csv.DictReader(io.TextIOWrapper(gz,encoding="utf-8-sig"),delimiter=";")
                    for row in reader:
                        sid=row.get("NUM_POSTE","");d=row.get("AAAAMMJJ","")
                        if sid not in ids or len(d)!=8:continue
                        y=int(d[:4])
                        if y not in years:continue
                        m=int(d[4:6]);day=int(d[6:]);v=core.val
                        if typ=="RR-T-Vent":
                            t=v(row,"TM")
                            if t is None:t=v(row,"TNTXM")
                            tn=v(row,"TN")
                            data={"temp":t,"rain":v(row,"RR"),"frost":None if tn is None else int(tn<=0)}
                        else:
                            sun=v(row,"INST");data={"sun":None if sun is None else sun/60,"snow":v(row,"NEIGETOTX")}
                        for k,value in data.items():
                            if value is None or k=="snow" and not 0<=value<=3000:continue
                            # Unique date per station; aggregate after reading.
                            key=(sid,y,m,k); bit=1<<(day-1)
                            total,mask=result.get(key,(0,0))
                            if mask&bit:continue
                            result[key]=(max(total,value) if k=="snow" else total+value,mask|bit)
            aggregates={}
            for key,(total,mask) in result.items():
                sid,y,m,k=key
                if mask!=(1<<calendar.monthrange(y,m)[1])-1:continue
                aggregates[key]=total
            return aggregates
        except Exception as e:logging.warning("%s %s %s: %s",dep,typ,period,e)
    return {}
def dept(dep,catalog):
    ids={s for s in catalog if s[:2]==dep or dep in ("2A","2B") and s[:2]=="20"}
    out={}
    for typ in ("RR-T-Vent","autres-parametres"):
        out.update(download(dep,typ,"previous-1950-2024",ids,set(range(1991,2021))|({YEAR} if YEAR<=2024 else set())))
        if YEAR>=2025:
            out.update(download(dep,typ,"latest-2025-2026",ids,{YEAR}))
    logging.info("%s : %d agrégats",dep,len(out))
    return out
def metric(ag,sid,y,months,key):
    seq=[ag.get((sid,y,m,key)) for m in months]
    if any(v is None for v in seq):return None
    if key=="snow":return max(seq)
    total=sum(seq)
    return total/sum(calendar.monthrange(y,m)[1] for m in months) if key=="temp" else total

def snow_station_map(points,bounds,filename,period):
    import matplotlib.pyplot as plt
    from matplotlib.colors import ListedColormap,BoundaryNorm
    from matplotlib.patheffects import withStroke
    from matplotlib.cm import ScalarMappable
    from matplotlib.patches import Polygon
    fig,ax=plt.subplots(figsize=(10,10),facecolor="#f5f7f8");ax.set_facecolor("#eaf1f4")
    for f in bounds["features"]:
        g=f.get("geometry",{});p=g.get("coordinates",[])
        for poly in ([p] if g.get("type")=="Polygon" else p if g.get("type")=="MultiPolygon" else []):
            if poly and any(-6.5<x<10.5 and 41<y<52 for x,y,*_ in poly[0]):
                ax.add_patch(Polygon(poly[0],closed=True,facecolor="#d9dee1",edgecolor="#a4afb6",linewidth=.55))
    cm=ListedColormap(["#ffffff","#a9d5f5","#519bd8","#2359ab","#7842b5","#b82b91","#791238"])
    norm=BoundaryNorm([0,.01,5,10,20,50,100,3001],cm.N)
    shown=[]
    for (x,y,name),v in sorted(points,key=lambda p:-p[1]):
        if any(math.hypot((x-a)*76,(y-b)*111)<65 for a,b in shown):continue
        shown.append((x,y))
        ax.scatter([x],[y],c=[v],cmap=cm,norm=norm,s=170,edgecolor="#64748b",linewidth=.5,zorder=3)
        ax.text(x,y,f"{v:g}",ha="center",va="center",fontsize=8,fontweight="bold",color="#18242d",zorder=4,path_effects=[withStroke(linewidth=2,foreground="white")])
    ax.set(xlim=(-5.7,9.9),ylim=(41.1,51.5));ax.set_aspect(1/math.cos(math.radians(46.5)));ax.axis("off")
    fig.suptitle("KFS MÉTÉO | CLIMATOLOGIE",y=.97,fontsize=15,fontweight="bold")
    ax.set_title("Hauteur maximale de neige au sol — mesures",fontsize=18,fontweight="bold")
    sm=ScalarMappable(cmap=cm,norm=norm);sm.set_array([])
    bar=fig.colorbar(sm,ax=ax,orientation="horizontal",fraction=.045,pad=.04,ticks=[.005,2.5,7.5,15,35,75,1550])
    bar.set_ticklabels(["0","<5","5–10","10–20","20–50","50–100",">100"])
    bar.set_label("Maximum observé (cm)")
    fig.text(.5,.035,f"{period} • {len(points)} stations avec période complète • Météo-France",ha="center",fontsize=11)
    fig.text(.5,.015,"Mesures ponctuelles uniquement • pas de zonage estimé ni de validation satellite historique",ha="center",fontsize=9)
    fig.savefig(filename,dpi=150,bbox_inches="tight",pad_inches=.2);plt.close(fig)

def main():
    if LAST<1:return
    catalog=core.station_catalog()
    ag={}
    with ThreadPoolExecutor(max_workers=6) as pool:
        for job in as_completed([pool.submit(dept,d,catalog) for d in DEPS]):
            ag.update(job.result())
    bounds=core.fetch_json("https://raw.githubusercontent.com/gregoiredavid/france-geojson/master/departements-version-simplifiee.geojson")
    valid_sids={k[0] for k in ag if k[1]==YEAR}
    for tag,months in [(f"{m:02d}",[m]) for m in range(1,LAST+1)]+([("annee",list(range(1,13)))] if LAST==12 else []):
        folder=ROOT/tag;folder.mkdir(parents=True,exist_ok=True)
        start=date(YEAR,months[0],1);end=date(YEAR,months[-1],calendar.monthrange(YEAR,months[-1])[1])
        period=f"{start:%d/%m/%Y} – {end:%d/%m/%Y}"
        manifest={"schema":1,"month":f"{YEAR}-{tag}","period":period,"start":start.isoformat(),"generated_at":datetime.now(ZoneInfo("Europe/Paris")).isoformat(),"source":"Météo-France, archives quotidiennes","maps":[]}
        core.OUT=folder
        # Keep the established national map style but display the full date range.
        for key,(filename,title,units,cmap,span) in SPECS.items():
            pts=[]
            for sid in valid_sids:
                obs=metric(ag,sid,YEAR,months,key)
                if obs is None:continue
                ref=[metric(ag,sid,y,months,key) for y in range(1991,2021)]
                ref=[v for v in ref if v is not None]
                if len(ref)<24:continue
                normal=statistics.mean(ref)
                if key in ("rain","sun") and normal<=0:continue
                v=(obs/normal-1)*100 if key in ("rain","sun") else obs-normal
                pts.append((catalog[sid],v))
            if len(pts)<(15 if key=="sun" else 30) or len({(round(p[0][0]),round(p[0][1])) for p in pts})<8:continue
            core.render(pts,bounds,title,units,cmap,TwoSlopeNorm(vmin=-span,vcenter=0,vmax=span),key,end,filename,period_label=period)
            manifest["maps"].append({"file":filename,"title":title,"end":end.isoformat(),"stations":len(pts)})
        snow=[]
        for sid in valid_sids:
            v=metric(ag,sid,YEAR,months,"snow")
            if v is not None:snow.append((catalog[sid],v))
        # Preserve the richer SIM/IMS map generated by the dedicated snow workflow.
        enhanced=None
        try:
            previous=json.loads((folder/"latest.json").read_text())
            enhanced=next((m for m in previous.get("maps",[]) if m.get("file")=="neige-sol-max.png" and m.get("kind")=="snow_depth" and m.get("end")==end.isoformat() and (folder/"neige-sol-max.png").is_file()),None)
        except (OSError,ValueError):pass
        if enhanced:
            manifest["maps"].append(enhanced)
        elif len(snow)>=8:
            filename="neige-sol-max.png"
            snow_station_map(snow,bounds,folder/filename,period)
            manifest["maps"].append({"file":filename,"title":"Hauteur maximale de neige au sol mesurée","end":end.isoformat(),"stations":len(snow),"kind":"snow_observed"})
        if not any(m["file"]=="temperature-anomalie.png" for m in manifest["maps"]) or not any(m["file"]=="pluie-anomalie.png" for m in manifest["maps"]):
            logging.warning("Période %s insuffisante, non publiée",period);continue
        for m in manifest["maps"]:
            # Never label a point-only legacy snow map as an enhanced regional view.
            if m.get("kind")!="snow_observed":m["zones"]=zone_files(folder,m["file"])
        (folder/"latest.json").write_text(json.dumps(manifest,ensure_ascii=False,indent=2))
        logging.info("Archive %s publiée localement",period)
if __name__=="__main__":main()
