"""Bounded, fail-closed StatIC supplement for monthly observed France maps.
No effect on 1991–2020 anomalies. API is experimental; do not infer missing days.
"""
import datetime as dt
import logging, math, statistics, time
from collections import defaultdict
import requests

BASE="https://climato.chom.engineering"
MAX_STATIONS=64
def get(path,params):
    r=requests.get(BASE+path,params=params,timeout=(8,15),headers={"User-Agent":"KFS-METEO-monthly-climatology/1.0"})
    r.raise_for_status()
    return r.json()

def number(v,lo,hi):
    return isinstance(v,(float,int)) and not isinstance(v,bool) and math.isfinite(v) and lo<=v<=hi

def eligible(s):
    return (s.get("genre")=="static" and s.get("pays")=="FR" and s.get("ouverte") is True
        and s.get("publiable") is True and "mfid" in s and not s["mfid"] and not s.get("type_poste")
        and s.get("ic_id") and "air_temperature" in (s.get("parametres_mesures") or [])
        and number(s.get("latitude"),41,52) and number(s.get("longitude"),-6,10)
        and not str(s.get("libelle_source") or "").upper().startswith("TEST MF CSV"))

def km(a,b):
    return math.hypot((a[0]-b[0])*111.2*math.cos(math.radians((a[1]+b[1])/2)),(a[1]-b[1])*111.2)

def fetch_static(start,end,mf_catalog):
    # The reference activity and catalogue may be stale; direct series determine dates.
    ref=get("/ref/stations",{"genre":"static","actif_depuis":"1900-01-01"})
    features=ref.get("features")
    if not isinstance(features,list): raise ValueError("Unexpected StatIC reference")
    rows=[f.get("properties",{}) for f in features]
    groups=defaultdict(list)
    ids=set()
    for s in rows:
        if not eligible(s) or s["ic_id"] in ids:continue
        ids.add(s["ic_id"])
        loc=(s["longitude"],s["latitude"],s.get("libelle") or s["ic_id"])
        if s["ic_id"] in mf_catalog or any(km(loc,m)<1 for m in mf_catalog.values()):continue
        # Spread requests over France; prioritize temperature + rain stations.
        cell=(math.floor(loc[0]/1.2),math.floor(loc[1]/.8))
        groups[cell].append((s,loc))
    for g in groups.values():
        g.sort(key=lambda pair:("precipitation_amount_24h" not in pair[0].get("parametres_mesures",[]),pair[0]["ic_id"]))
    # Deterministic geographic round robin, at most 64 HTTP series per daily run.
    order=[]
    for i in range(2):
        for cell in sorted(groups):
            if len(groups[cell])>i:order.append(groups[cell][i])
    selected=[]
    for s,loc in order:
        if any(km(loc,p[1])<4 for p in selected):continue
        selected.append((s,loc))
        if len(selected)>=MAX_STATIONS:break
    output={}
    stop=end+dt.timedelta(days=1)
    for s,loc in selected:
        sid=str(s["ic_id"])
        try:
            data=get("/statIC/journaliere",{"station":sid,"from":start.isoformat(),"to":stop.isoformat()})
            if data.get("tronque") or not isinstance(data.get("mesures"),list):continue
            days={}
            for row in data["mesures"]:
                if str(row.get("ic_id"))!=sid:continue
                try:d=dt.date.fromisoformat(row["date"])
                except (KeyError,TypeError,ValueError):continue
                if not start<=d<=end:continue
                n=row.get("n_obs");rej=row.get("n_obs_rejetees") or 0
                if not number(n,24,100000) or not number(rej,0,n) or n-rej<24 or not number(row.get("taux_qc_valide"),.99,1):continue
                tn,tx=row.get("tn"),row.get("tx")
                if not number(tn,-45,50) or not number(tx,tn,55):continue
                # Use the same midrange convention as the observed MF maps.
                days[d]={"temp":(tn+tx)/2,"frost":int(tn<=0)}
                if number(row.get("rr"),0,500):days[d]["rain"]=row["rr"]
            if days:output[sid]=(loc,days)
        except requests.RequestException as e:
            logging.warning("StatIC %s: %s",sid,e)
            if getattr(e.response,"status_code",None)==429:break
        except (ValueError,TypeError) as e:logging.warning("StatIC %s: %s",sid,e)
        finally:time.sleep(.25)
    logging.info("StatIC: %s stations requested, %s with usable days",len(selected),len(output))
    return output

def complete_static(records,key,start,end):
    dates=[start+dt.timedelta(days=i) for i in range((end-start).days+1)]
    out=[]
    for sid,(loc,days) in records.items():
        vals=[days.get(d,{}).get(key) for d in dates]
        if vals and all(v is not None for v in vals):
            out.append((loc,statistics.mean(vals) if key=="temp" else sum(vals)))
    return out
