#!/usr/bin/env python3
"""Prospective verification of KFS initiation candidates vs MTG-LI optical flashes.
Keep first published forecast per actual lead-hour bin. No observation coverage,
no score. Candidate-cell precision and event recall are separate metrics.
"""
from datetime import datetime,timedelta,timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from urllib.request import Request,urlopen
import json,math,re,subprocess
import numpy as np
from scipy.spatial import cKDTree

REPO="almet27/kfs-meteo-cartes"
TAG="arome-initiation-verification"
BASE=f"https://github.com/{REPO}/releases/download/arome-initiation/"
OBS=f"https://raw.githubusercontent.com/{REPO}/main/foudre-li/flash-points.json"
UTC=timezone.utc
def dt(x): return datetime.fromisoformat(x.replace("Z","+00:00"))
def gh(*args): return subprocess.check_output(["gh",*args],text=True)
def get(url):
    with urlopen(Request(url,headers={"User-Agent":"KFS-Meteo/verification"}),timeout=30) as r:return json.load(r)
def assets():
    return {a["name"] for a in json.loads(gh("release","view",TAG,"--json","assets"))["assets"]}
def save(name,obj):
    with TemporaryDirectory() as tmp:
        p=Path(tmp)/name;p.write_text(json.dumps(obj,separators=(",",":"),allow_nan=False))
        gh("release","upload",TAG,str(p),"--clobber")
def load(name): return get(f"https://github.com/{REPO}/releases/download/{TAG}/{name}?v={int(datetime.now(UTC).timestamp())}")
def xyz(lon,lat):
    x,y=np.deg2rad(lon),np.deg2rad(lat)
    return np.stack((6371*np.cos(y)*np.cos(x),6371*np.cos(y)*np.sin(x),6371*np.sin(y)),axis=-1)
def covers(obs,start,end):
    if obs.get("state")!="ready" or obs.get("truncated") is not False or obs.get("provider")!="EUMETSAT-MTG-LI-LFL":return False
    latest=dt(obs["latest_product_end_utc"])
    if latest<end or latest-timedelta(minutes=obs["retained_minutes"])>start:return False
    if obs.get("area_wsen")!=[-7.5,40.5,10.,52.]:return False
    spans=[]
    for name in obs.get("products_seen",[]):
        m=re.search(r"_OPE_(\d{14})_(\d{14})_",name)
        if m:spans.append(tuple(datetime.strptime(x,"%Y%m%d%H%M%S").replace(tzinfo=UTC) for x in m.groups()))
    cursor=start
    for a,b in sorted(spans):
        if b<cursor:continue
        if a>cursor+timedelta(seconds=1):return False
        cursor=max(cursor,b)
        if cursor>=end:return True
    return False
def score(doc,obs):
    t=dt(doc["valid_utc"]);start=t-timedelta(minutes=30);end=t+timedelta(minutes=30)
    if not covers(obs,start,end):return None
    p=[];q=[]
    for f in obs.get("flashes",[]):
        try: ts=datetime.fromtimestamp(f["ts"],UTC);lon=float(f["lon"]);lat=float(f["lat"])
        except (KeyError,ValueError,TypeError,OverflowError):continue
        if not (-7.5<=lon<=10 and 40.5<=lat<=52):continue
        if start<=ts<t:p.append((lon,lat))
        elif t<=ts<end:q.append((ts,lon,lat))
    old=cKDTree(xyz(*np.array(p).T)) if p else None
    events=[]
    for _,lon,lat in sorted(q):
        if not (-5.7<=lon<=9.7 and 41.3<=lat<=51.7):continue
        point=xyz(lon,lat)
        if old is not None and old.query(point)[0]<=20:continue
        if any(np.linalg.norm(point-z)<=20 for z in events):continue
        events.append(point)
    scores={}
    for lead,d in doc["forecasts"].items():
        cells=[]
        for ix,iy,level in d["cells"]:
            lon=-6+(ix+.4)*.05;lat=52-(iy+.4)*.05
            if -5.7<=lon<=9.7 and 41.3<=lat<=51.7:
                cells.append((xyz(lon,lat),level))
        # Distinct observed initiation clusters and forecast cells: neighborhood radius 20 km.
        for lvl in (1,2):
            pts=[p for p,l in cells if l>=lvl]; tree=cKDTree(pts) if pts else None
            hit=sum(bool(tree is not None and tree.query(e)[0]<=20) for e in events)
            et=cKDTree(events) if events else None
            matched=sum(bool(et is not None and et.query(p)[0]<=20) for p in pts)
            scores[f"{lead}h_L{lvl}"]={"events":len(events),"events_detected":hit,"candidate_cells":len(pts),"cells_near_event":matched}
    return {"observed_utc":obs["latest_product_end_utc"],"window":[start.isoformat(),end.isoformat()],"radius_km":20,"scores":scores,"source":"MTG-LI LFL optical flashes; initiation proxy, not ground strikes"}

def main():
    now=datetime.now(UTC)
    try: names=assets()
    except subprocess.CalledProcessError:
        gh("release","create",TAG,"--title","KFS - Verification initiation convective","--notes","Prospective optical lightning verification; experimental.","--prerelease");names=assets()
    try: m=get(BASE+"manifest.json")
    except Exception as e: print("Forecast unavailable",e);m=None
    if m and m.get("schema")==1 and m.get("diagnostic_version")==2 and m.get("resolution_degrees")==.05:
        for f in m["frames"]:
            t=dt(f["valid_utc"]);lead=(t-now).total_seconds()/3600
            if not 0<lead<=6:continue
            if not re.fullmatch(r"init-\d{10}-h\d{2}\.json",f["file"]):continue
            name=f"forecast-{t:%Y%m%d%H}.json";bucket=str(math.ceil(lead))
            doc=load(name) if name in names else {"schema":1,"valid_utc":t.isoformat(),"forecasts":{}}
            if bucket in doc["forecasts"] or "verification" in doc:continue
            d=get(BASE+f["file"])
            if d.get("run_utc")!=m["run_utc"] or dt(d["valid_utc"])!=t or not .8<=d.get("coverage",0)<=1:continue
            if datetime.now(UTC)>=t:continue
            doc["forecasts"][bucket]={"issued_utc":now.isoformat(),"run_utc":d["run_utc"],"lead_hours":round(lead,3),"sources":d.get("sources",{}),"cells":d["cells"]}
            save(name,doc);names.add(name)
    try: obs=get(OBS)
    except Exception as e: print("Observations unavailable",e);return
    for name in sorted(names):
        if not re.fullmatch(r"forecast-\d{10}\.json",name):continue
        t=datetime.strptime(name[9:19],"%Y%m%d%H").replace(tzinfo=UTC)
        if not t+timedelta(minutes=30)<=now<=t+timedelta(minutes=90):continue
        doc=load(name)
        if "verification" in doc:continue
        result=score(doc,obs)
        if result is not None:doc["verification"]=result;save(name,doc)
    # Preserve daily aggregate counts before expiring raw snapshots after 14 days.
    cutoff=now.date()-timedelta(days=14)
    groups={}
    for name in names:
        if not re.fullmatch(r"forecast-\d{10}\.json",name):continue
        day=datetime.strptime(name[9:17],"%Y%m%d").date()
        if day<cutoff:groups.setdefault(day,[]).append(name)
    for day,files in groups.items():
        total={};verified=0
        for name in files:
            doc=load(name)
            if "verification" not in doc:continue
            verified+=1
            for k,v in doc["verification"]["scores"].items():
                a=total.setdefault(k,{x:0 for x in v})
                for x,n in v.items():a[x]+=n
        daily=f"daily-{day.isoformat()}.json"
        if daily not in names:save(daily,{"date":day.isoformat(),"forecast_hours":len(files),"verified_hours":verified,"scores":total})
        for name in files:gh("release","delete-asset",TAG,name,"--yes")
if __name__=="__main__":main()
