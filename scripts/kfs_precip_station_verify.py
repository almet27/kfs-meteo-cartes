#!/usr/bin/env python3
"""Prospective matched hourly verification against official MF RR1 gauges.
All three models must be present, same valid hour and same station subset.
Latest publicly archived forecast at a fixed decision cutoff; never use a
forecast published during or after the observed accumulation window.
"""
import argparse,json,math,subprocess,tempfile
from datetime import datetime,timedelta,timezone
from pathlib import Path
import numpy as np

TAGS={"arome":"arome-precip-archive","icon-d2":"icon-precip-archive","harmonie":"harmonie-precip-archive"}
LEADS=(1,3,6,12,24,48)
THRESHOLDS=(.1,1.,5.)
def stamp(v):return datetime.fromisoformat(str(v).replace("Z","+00:00")).astimezone(timezone.utc)
def gh(*args):return subprocess.check_output(["gh",*args],text=True)
def get_assets(tag):
    try:
        # Do not suppress errors other than not-yet-created release.
        p=subprocess.run(["gh","release","view",tag,"--json","assets"],capture_output=True,text=True)
        if p.returncode:
            if "release not found" in p.stderr.lower():return []
            raise RuntimeError("Cannot list archive "+tag)
        return [a for a in json.loads(p.stdout)["assets"] if a["name"].startswith("verify-") and a["name"].endswith(".npz")]
    except Exception as e:print("Archive unavailable",tag,str(e),flush=True);return []
def observations(doc):
    h=doc.get("web_history",{})
    if h.get("schema")!=1:raise ValueError("Station history unavailable")
    times=list(map(stamp,h["times"]));out={}
    for i,t in enumerate(times):
        rows={}
        for lon,lat,sid,name,series in h["stations"]:
            if not (-6<=lon<=10 and 41<=lat<=52 and i<len(series)):continue
            row=series[i]
            if not isinstance(row,list) or len(row)<3 or row[2] is None:continue
            v=row[2]
            if isinstance(v,(int,float)) and math.isfinite(v) and 0<=v<=400:rows[str(sid)]=(lon,lat,v)
        if rows:out[t]=rows
    return out
def sample(d,t,coords,model):
    if d["schema"].item()!=1 or d["model"].item()!=model or d["unit"].item()!="mm" or d["interval_minutes"].item()!=60:raise ValueError("Archive metadata")
    if d["values"].shape[1:]!=(276,401):raise ValueError("Archive shape")
    if not np.allclose(d["lon"],np.linspace(-6,10,401)[None,:],atol=1e-5,rtol=0) or not np.allclose(d["lat"],np.linspace(52,41,276)[:,None],atol=1e-5,rtol=0):raise ValueError("Archive coordinates")
    times=[stamp(x) for x in d["valid_utc"]]
    if t not in times:return None
    ix=np.rint((coords[:,0]+6)/.04).astype(int);iy=np.rint((52-coords[:,1])/.04).astype(int)
    return d["values"][times.index(t),iy,ix]
def counts(a,b,threshold):
    f=a>=threshold;o=b>=threshold
    return [int((f&o).sum()),int((~f&o).sum()),int((f&~o).sum())]
def paired(values,actual,coords):
    good=np.isfinite(actual)&(actual>=0)
    for v in values.values():good&=np.isfinite(v)&(v>=0)
    lon,lat=coords.T
    regions={"France":np.ones(len(actual),dtype=bool),"Nord-Ouest":(lon<2)&(lat>=46.5),"Nord-Est":(lon>=2)&(lat>=46.5),"Sud-Ouest":(lon<2)&(lat<46.5),"Sud-Est":(lon>=2)&(lat<46.5)}
    result={}
    for region,regionmask in regions.items():
        mask=good&regionmask;n=int(mask.sum())
        if n<20:continue
        b=actual[mask]
        result[region]={model:{"n":n,"absolute":float(np.abs(v[mask]-b).sum()),"squared":float(((v[mask]-b)**2).sum()),"forecast":float(v[mask].sum()),"observed":float(b.sum()),"thresholds":{str(q):counts(v[mask],b,q) for q in THRESHOLDS}} for model,v in values.items()}
    return result
def main(manifest,out):
    now=datetime.now(timezone.utc);obs=observations(json.loads(manifest.read_text()));out.mkdir(exist_ok=True,parents=True)
    path=out/"station-pairs.json"
    state=json.loads(path.read_text()) if path.exists() else {"schema":1,"pairs":{}}
    records={k:v for k,v in state["pairs"].items() if stamp(k.split("|")[0])>=now-timedelta(days=30)}
    assets={m:sorted(get_assets(tag),key=lambda a:stamp(a["createdAt"]),reverse=True) for m,tag in TAGS.items()}
    added=0
    with tempfile.TemporaryDirectory() as tmp:
        cache={}
        for t,rows in sorted(obs.items()):
            if t>now or t<now-timedelta(hours=25):continue
            coords=np.asarray([(x,y) for x,y,v in rows.values()]);actual=np.asarray([v for x,y,v in rows.values()])
            for lead in LEADS:
                cutoff=t-timedelta(hours=lead);k=t.isoformat()+"|"+str(lead)
                if k in records:continue
                values={};sources={}
                for model,tag in TAGS.items():
                    for asset in assets[model]:
                        issued=stamp(asset["createdAt"])
                        if issued>cutoff or cutoff-issued>timedelta(hours=8):continue
                        name=asset["name"];key=(tag,name)
                        if key not in cache:
                            dest=Path(tmp)/name
                            gh("release","download",tag,"--pattern",name,"--dir",tmp)
                            cache[key]=dest
                        with np.load(cache[key],allow_pickle=False) as d:
                            run=stamp(d["run_utc"].item())
                            if run>issued:raise ValueError("Forecast run after publication")
                            v=sample(d,t,coords,model)
                        if v is not None:
                            values[model]=v;sources[model]={"issued_utc":issued.isoformat(),"run_utc":run.isoformat(),"file":name};break
                if len(values)!=len(TAGS):continue
                result=paired(values,actual,coords)
                if result:
                    records[k]={"sources":sources,"regions":result};added+=1
    state["pairs"]=records
    path.write_text(json.dumps(state,separators=(",",":"),allow_nan=False))
    summary={}
    for k,record in records.items():
        lead=k.split("|")[1]
        for region,models in record["regions"].items():
            b=summary.setdefault(lead,{}).setdefault(region,{})
            for model,v in models.items():
                a=b.setdefault(model,{"n":0,"hours":0,"absolute":0.,"squared":0.,"forecast":0.,"observed":0.,"thresholds":{str(q):[0,0,0] for q in THRESHOLDS}})
                a["hours"]+=1
                for field in ("n","absolute","squared","forecast","observed"):a[field]+=v[field]
                for q,counts in v["thresholds"].items():a["thresholds"][q]=[x+y for x,y in zip(a["thresholds"][q],counts)]
    for regions in summary.values():
        for models in regions.values():
            for a in models.values():
                a["mae"]=a["absolute"]/a["n"];a["rmse"]=math.sqrt(a["squared"]/a["n"])
                a["eligible_for_review"]=a["hours"]>=100 and a["n"]>=5000 and a["thresholds"]["1.0"][0]+a["thresholds"]["1.0"][1]>=200
                a["scores"]={q:{"CSI":h/(h+m+f) if h+m+f else None,"POD":h/(h+m) if h+m else None,"FAR":f/(h+f) if h+f else None} for q,(h,m,f) in a["thresholds"].items()}
    (out/"station-skill.json").write_text(json.dumps({"schema":1,"source":"Météo-France RR1 stations","method":"Same station and valid-hour sample for ARÔME, ICON-D2 and HARMONIE; decision cutoff before accumulation; rolling 30 days. No spatial radar FSS.","updated_utc":now.isoformat(),"paired_hours":len(records),"added":added,"lead_hours":summary},indent=2,allow_nan=False))
    print("STATION VERIFICATION",added,"new matched hours",len(records),"retained",flush=True)
def test():
    coords=np.tile([0.,48.],(30,1));o=np.ones(30);a=o.copy();b=np.zeros(30);c=o.copy();c[0]=np.nan
    d=paired({"arome":a,"icon-d2":b,"harmonie":c},o,coords)["France"]
    assert all(x["n"]==29 for x in d.values()) and d["arome"]["absolute"]==0 and d["icon-d2"]["thresholds"]["1.0"]==[0,29,0]
    print("PASS common station sample and wet/dry counts")
if __name__=="__main__":
    p=argparse.ArgumentParser();p.add_argument("--test",action="store_true");p.add_argument("--manifest",type=Path);p.add_argument("--out",type=Path,default=Path("precip-skill"));a=p.parse_args()
    if a.test:test()
    else:main(a.manifest,a.out)
