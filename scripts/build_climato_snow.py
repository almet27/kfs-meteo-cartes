"""Monthly maximum snow depth: native SIM 8 km + station measurements + IMS snow extent."""
import argparse,calendar,csv,gzip,io,json,logging,math,shutil,tempfile
from collections import Counter,defaultdict
from concurrent.futures import ThreadPoolExecutor
from datetime import date,datetime,timedelta
from pathlib import Path
from zoneinfo import ZoneInfo
import requests
from climato_zones import ZONES, zone_filename, zone_files
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.colors import ListedColormap,BoundaryNorm
from matplotlib.patheffects import withStroke
from matplotlib.lines import Line2D
from pyproj import Transformer
import rasterio
from rasterio.transform import from_origin
from rasterio.warp import reproject,Resampling
from rasterio.features import geometry_mask
from rasterio.warp import transform_geom

logging.basicConfig(level=logging.INFO,format="%(levelname)s %(message)s")
BASE="https://meteofrance.s3.sbg.io.cloud.ovh.net/data/"
IMS="https://noaadata.apps.nsidc.org/NOAA/G02156/GIS/"
OUT=Path("climato/france")
CACHE=Path(".climato-cache/ims-fr-v2")
CACHE.mkdir(parents=True,exist_ok=True)
TODAY=datetime.now(ZoneInfo("Europe/Paris")).date()
START=TODAY.replace(day=1)
END=TODAY-timedelta(days=1)
CRS="EPSG:27572"
TRANS=Transformer.from_crs("EPSG:4326",CRS,always_xy=True)
def dates(a,b):
    return [a+timedelta(days=i) for i in range((b-a).days+1)]
def rows(url):
    with requests.get(url,stream=True,timeout=(15,100)) as r:
        r.raise_for_status();r.raw.decode_content=True
        with gzip.GzipFile(fileobj=r.raw) as g:
            yield from csv.DictReader(io.TextIOWrapper(g,encoding="utf-8-sig"),delimiter=";")
def sim():
    daycells=defaultdict(dict)
    url=BASE+("REF_CC/SIM/QUOT_SIM2_latest.csv.gz" if OUT==Path("climato/france") else f"REF_CC/SIM/QUOT_SIM2_{START.year}.csv.gz")
    for row in rows(url):
        d=row["DATE"]
        if not START.strftime("%Y%m%d")<=d<=END.strftime("%Y%m%d"):continue
        try:
            x=int(float(row["LAMBX"])*100); y=int(float(row["LAMBY"])*100)
            v=float(row["HTEURNEIGEX"])*100
            if math.isfinite(v) and 0<=v<=3000:daycells[d][(x,y)]=v
        except (KeyError,ValueError,TypeError):continue
    good=[]
    for d in dates(START,END):
        key=d.strftime("%Y%m%d")
        if len(daycells.get(key,{}))<8500:break
        good.append(key)
    if not good:raise RuntimeError("Pas de journée SIM France complète pour cette période")
    if OUT!=Path("climato/france") and len(good)!=(END-START).days+1:raise RuntimeError("Archive SIM incomplète ; carte historique non remplacée")
    cells=set().union(*(daycells[d] for d in good))
    maxs={p:max(daycells[d][p] for d in good) for p in cells if all(p in daycells[d] for d in good)}
    if len(maxs)<8500:raise RuntimeError("Couverture SIM insuffisante")
    return maxs,datetime.strptime(good[-1],"%Y%m%d").date()
def station_dep(dep,cutoff):
    result={}
    try:
        period="previous-1950-2024" if START.year<=2024 else "latest-2025-2026"
        url=BASE+f"synchro_ftp/BASE/QUOT/Q_{dep}_{period}_autres-parametres.csv.gz"
        for r in rows(url):
            d=r.get("AAAAMMJJ","")
            if not START.strftime("%Y%m%d")<=d<=cutoff.strftime("%Y%m%d"):continue
            try:
                vals=[]
                for key in ("NEIGETOTX","HTN"):
                    try:
                        v=float(r[key]);q=r.get("Q"+key,"").strip()
                        if q in ("0","1","9") and math.isfinite(v) and 0<=v<=3000:vals.append((v,key))
                    except (ValueError,KeyError,TypeError):continue
                if not vals:continue
                v,key=next((p for p in vals if p[1]=="NEIGETOTX"),vals[0])
                x,y=TRANS.transform(float(r["LON"]),float(r["LAT"]))
                sid=r["NUM_POSTE"]
                rec=result.setdefault(sid,{"x":x,"y":y,"name":r.get("NOM_USUEL",sid),"days":{}})
                rec["days"][d]=v
                if key!="NEIGETOTX":rec["snapshot_only"]=True
            except (ValueError,KeyError,TypeError):continue
    except Exception as e:logging.warning("Stations %s: %s",dep,e)
    return result
def stations(cutoff):
    deps=[f"{d:02d}" for d in range(1,96) if d!=20]+["2A","2B","20"]
    out={}
    with ThreadPoolExecutor(max_workers=8) as pool:
        for result in pool.map(lambda d:station_dep(d,cutoff),deps):out.update(result)
    n=(cutoff-START).days+1
    # A full-period zero requires all days; partial readings can only establish
    # a lower bound on the maximum and are excluded from the numeric overlay.
    return [dict(x=r["x"],y=r["y"],name=r["name"],max=max(r["days"].values()),days=len(r["days"]),complete=len(r["days"])==n and not r.get("snapshot_only",False)) for r in out.values() if len(r["days"])==n or max(r["days"].values())>0]
def ims_day(day,shape,transform):
    # GeoTIFF archives use production date (one day before 00 UTC validity).
    # Unlike ASCII files, the documented GeoTIFF filename omits 00UTC.
    if day<date(2014,12,3):return day,None
    produced=day-timedelta(days=1)
    name=f"ims{produced:%Y%j}_1km_GIS_v1.3.tif.gz"
    urls=[IMS+sub+name for sub in (f"1km/{produced.year}/",f"{produced.year}/",f"{produced.year}/1km/") ]
    cache=CACHE/f"{day.isoformat()}-{shape[0]}-{shape[1]}.npz"
    if cache.exists():
        try:
            a=np.load(cache)["classes"]
            if a.shape==shape:return day,a
        except Exception:pass
    try:
        with tempfile.TemporaryDirectory() as td:
            raw=Path(td)/"ims.tif"
            fetched=False
            for url in urls:
                with requests.get(url,stream=True,timeout=(8,35)) as r:
                    if r.status_code==404:continue
                    r.raise_for_status();r.raw.decode_content=True
                    with gzip.GzipFile(fileobj=r.raw) as gz,raw.open("wb") as f:
                        shutil.copyfileobj(gz,f,1024*1024)
                    fetched=True
                    logging.info("IMS %s archive %s",day,url)
                    break
            if not fetched:raise FileNotFoundError("Archive IMS GeoTIFF non trouvée (3 chemins testés)")
            dest=np.zeros(shape,dtype=np.uint8)
            with rasterio.open(raw) as ds:
                if ds.crs is None:raise ValueError("IMS sans projection")
                reproject(rasterio.band(ds,1),dest,src_transform=ds.transform,src_crs=ds.crs,
                          dst_transform=transform,dst_crs=CRS,src_nodata=0,dst_nodata=0,resampling=Resampling.nearest)
            if not np.isin(dest,[0,1,2,3,4]).all() or np.isin(dest,[2,4]).sum()<10000:raise ValueError("Classes ou couverture IMS non conformes")
            np.savez_compressed(cache,classes=dest)
            return day,dest
    except Exception as e:
        logging.warning("IMS %s: %s",day,str(e)[:200])
        return day,None
def main():
    if END<START:return
    manifest_path=OUT/"latest.json"
    manifest=json.loads(manifest_path.read_text())
    expected=TODAY.strftime("%Y-%m") if OUT==Path("climato/france") else f"{START.year}-{OUT.name}"
    if manifest.get("month")!=expected:raise RuntimeError("Manifeste climatologique périmé")
    cells,cutoff=sim()
    x0=min(x for x,y in cells);x1=max(x for x,y in cells)
    y0=min(y for x,y in cells);y1=max(y for x,y in cells)
    # SIM is a regular 8 km grid; reject unexpected projection/spacing.
    if any((x-x0)%8000 or (y-y0)%8000 for x,y in cells):raise ValueError("Grille SIM non conforme")
    nx=(x1-x0)//8000+1;ny=(y1-y0)//8000+1
    z=np.full((ny,nx),np.nan)
    for (x,y),v in cells.items():z[(y-y0)//8000,(x-x0)//8000]=v
    xmin,xmax=x0-4000,x1+4000;ymin,ymax=y0-4000,y1+4000
    bounds=requests.get("https://raw.githubusercontent.com/gregoiredavid/france-geojson/master/departements-version-simplifiee.geojson",timeout=60)
    bounds.raise_for_status()
    geoms=[]
    for f in bounds.json()["features"]:
        code=str(f.get("properties",{}).get("code",""))
        if code.startswith(("97","98")):continue
        g=f.get("geometry")
        if g and g["type"] in ("Polygon","MultiPolygon"):geoms.append(transform_geom("EPSG:4326",CRS,g))
    if not geoms:raise RuntimeError("Frontières absentes")
    shape=(ny*8,nx*8);transform=from_origin(xmin,ymax,1000,1000)
    land=geometry_mask(geoms,out_shape=shape,transform=transform,invert=True)
    # All available dated IMS analyses in the same period: union of snow
    # presence, not a depth estimate. Missing days never count as no snow.
    confirmed=np.zeros(shape,dtype=bool);valid=[]
    with ThreadPoolExecutor(max_workers=2) as pool:
        for d,a in pool.map(lambda d:ims_day(d,shape,transform),dates(START,cutoff)):
            if a is not None:
                confirmed|=(a==4)&land
                valid.append(d.isoformat())
    obs=stations(cutoff)
    logging.info("SIM cells=%d cutoff=%s; IMS days=%d/%d; stations with usable readings=%d",len(cells),cutoff,len(valid),(cutoff-START).days+1,len(obs))
    fig,ax=plt.subplots(figsize=(10,10),facecolor="#f5f7f8")
    ax.set_facecolor("#eaf1f4")
    for geom in geoms:
        polys=[geom["coordinates"]] if geom["type"]=="Polygon" else geom["coordinates"]
        for poly in polys:
            p=np.asarray(poly[0]);ax.fill(p[:,0],p[:,1],color="#bac4cc",zorder=1)
    # Clip the 8 km raster to land without inventing fine-scale depths.
    fine=np.repeat(np.repeat(z[::-1],8,axis=0),8,axis=1)
    fine[~land]=np.nan
    colors=["#f6f7f8","#dceef9","#a9d5f5","#519bd8","#2359ab","#7842b5","#b82b91","#791238"]
    levels=[0,.01,1,5,10,20,50,100,3001]
    cm=ListedColormap(colors);norm=BoundaryNorm(levels,cm.N)
    img=ax.imshow(np.ma.masked_invalid(fine),extent=(xmin,xmax,ymin,ymax),origin="upper",cmap=cm,norm=norm,interpolation="nearest",zorder=2)
    if confirmed.any():
        # A green outline marks observed snow extent at least once, independently
        # of the maximum depth estimated by SIM.
        xx=xmin+500+np.arange(shape[1])*1000;yy=ymax-500-np.arange(shape[0])*1000
        ax.contour(xx,yy,confirmed.astype(np.uint8),levels=[.5],colors=["#16866d"],linewidths=.55,zorder=3)
    for geom in geoms:
        polys=[geom["coordinates"]] if geom["type"]=="Polygon" else geom["coordinates"]
        for poly in polys:
            p=np.asarray(poly[0]);ax.plot(p[:,0],p[:,1],color="#65727b",linewidth=.45,zorder=4)
    ax.set_aspect("equal");ax.axis("off")
    fig.suptitle("KFS MÉTÉO  |  CLIMATOLOGIE",y=.98,fontsize=15,fontweight="bold",color="#385064")
    ax.set_title("Hauteur maximale de neige au sol",fontsize=19,fontweight="bold",pad=12,color="#1c2a35")
    bar=fig.colorbar(img,ax=ax,orientation="horizontal",fraction=.045,pad=.03,aspect=32,spacing="uniform",ticks=[.005,.5,3,7.5,15,35,75,1550])
    bar.set_ticklabels(["0","<1","1–5","5–10","10–20","20–50","50–100",">100"])
    bar.set_label("Épaisseur maximale estimée (cm) — grille SIM 8 km")
    if valid:ax.legend(handles=[Line2D([0],[0],color="#16866d",label="Neige détectée (IMS, au moins un jour)")],loc="lower left",fontsize=8,framealpha=.96)
    fig.text(.5,.035,f"{START:%d/%m/%Y} – {cutoff:%d/%m/%Y} • mesures MF (cm), ≥ : série partielle ou relevé à 6 h • {len(valid)}/{(cutoff-START).days+1} jours IMS",ha="center",fontsize=10,fontweight="bold")
    fig.text(.5,.015,"SIM : estimation, pas une mesure locale • gris foncé : données manquantes • en montagne, forte variabilité",ha="center",fontsize=8.5,color="#52606b")
    filename="neige-sol-max.png"
    viewports={"france":("France",(xmin,ymin,xmax,ymax))}
    for zone,(label,(west,east,south,north)) in ZONES.items():
        viewports[zone]=(label,TRANS.transform_bounds(west,south,east,north,densify_pts=21))
    for zone,(label,(left,bottom,right,top)) in viewports.items():
        ax.set_xlim(left,right);ax.set_ylim(bottom,top)
        ax.set_title("Hauteur maximale de neige au sol"+("" if zone=="france" else " — "+label),fontsize=17 if zone!="france" else 19,fontweight="bold",pad=12,color="#1c2a35")
        spacing=42000 if zone=="france" else max(8000,42000*max((right-left)/(xmax-xmin),(top-bottom)/(ymax-ymin)))
        shown=[];artists=[]
        for r in sorted(obs,key=lambda r:-r["max"]):
            x,y=r["x"],r["y"]
            if not (left<=x<=right and bottom<=y<=top):continue
            if any(math.hypot(x-a,y-b)<spacing for a,b in shown):continue
            shown.append((x,y))
            artists.append(ax.text(x,y,f'{r["max"]:g}' if r["complete"] else f'≥{r["max"]:g}',color="#172029",fontsize=8,ha="center",va="center",fontweight="bold",zorder=5,path_effects=[withStroke(linewidth=2,foreground="white")],clip_on=True))
        fig.savefig(OUT/(filename if zone=="france" else zone_filename(filename,zone)),dpi=150,bbox_inches="tight",pad_inches=.2)
        for artist in artists:artist.remove()
    plt.close(fig)
    manifest["maps"]=[m for m in manifest["maps"] if m["file"]!=filename]
    manifest["maps"].append({"file":filename,"title":"Hauteur maximale de neige au sol estimée","end":cutoff.isoformat(),"stations":len(obs),"grid_cells":len(cells),"ims_days":len(valid),"ims_dates":valid,"kind":"snow_depth","zones":zone_files(OUT,filename),"source":"Météo-France SIM 8 km + stations; IMS 1 km si disponible"})
    manifest_path.write_text(json.dumps(manifest,ensure_ascii=False,indent=2))
if __name__=="__main__":
    parser=argparse.ArgumentParser()
    parser.add_argument("--year",type=int)
    parser.add_argument("--month",choices=["annee"]+[str(i) for i in range(1,13)])
    args=parser.parse_args()
    if args.year is not None:
        if args.month is None or not 1958<=args.year<=TODAY.year:raise SystemExit("Archive SIM : année ≥ 1958 et mois requis")
        year=args.year
        if args.month=="annee":
            START=date(year,1,1);END=date(year,12,31);tag="annee"
        else:
            month=int(args.month);START=date(year,month,1);END=date(year,month,calendar.monthrange(year,month)[1]);tag=f"{month:02d}"
        if END>=TODAY:raise SystemExit("Période historique non terminée")
        OUT=Path(f"climato/archive/{year}/{tag}")
    main()
