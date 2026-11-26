#!/usr/bin/env python3
"""KFS — pilotage historique EUMETSAT LFL, comptage station 15 km.
Un jour sans éclair n'est valide que si toute la fenêtre est couverte.
Les coordonnées sont des centres optiques, pas des impacts au sol.
"""
import argparse
import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo
import numpy as np
import requests
import eumdac
from collect import COLLECTION, PRODUCT_TIME, download_one, decode_product, Parallax, LUT, METHOD

def main():
    p=argparse.ArgumentParser()
    p.add_argument("--date",required=True)
    p.add_argument("--pilot",action="store_true")
    a=p.parse_args()
    day=datetime.strptime(a.date,"%Y-%m-%d").replace(tzinfo=ZoneInfo("Europe/Paris"))
    start=day.astimezone(timezone.utc)
    if a.pilot: start+=timedelta(hours=16)
    end=start+timedelta(hours=1) if a.pilot else (day+timedelta(days=1)).astimezone(timezone.utc)
    if start<datetime(2024,7,4,tzinfo=timezone.utc) or end>datetime.now(timezone.utc)-timedelta(hours=2):
        raise ValueError("Période non disponible ou trop récente")
    token=eumdac.AccessToken((os.environ["EUMETSAT_CONSUMER_KEY"],os.environ["EUMETSAT_CONSUMER_SECRET"]))
    collection=eumdac.DataStore(token).get_collection(COLLECTION)
    products=list(collection.search(dtstart=(start-timedelta(minutes=15)).replace(tzinfo=None),dtend=(end+timedelta(minutes=15)).replace(tzinfo=None)))
    if not products or len(products)>170: raise RuntimeError("Nombre de produits inattendu")
    geo=requests.get("https://meteofrance.s3.sbg.io.cloud.ovh.net/data/synchro_ftp/REF_STATION/liste_fiches_clim.geojson",timeout=60)
    geo.raise_for_status()
    stations=[]
    for f in geo.json()["features"]:
        sid=str(f["properties"].get("num",""))
        lon,lat=map(float,f["geometry"]["coordinates"][:2])
        if len(sid)==8 and sid.isdigit() and 40.5<=lat<=52 and -7.5<=lon<=10:
            stations.append((sid,lat,lon))
    if len(stations)<100: raise RuntimeError("Catalogue station incomplet")
    # Exiger la même correction de parallaxe que la carte live.
    table=Parallax(LUT)
    def xyz(lat,lon):
        lat,lon=np.radians(lat),np.radians(lon)
        return np.stack([np.cos(lat)*np.cos(lon),np.cos(lat)*np.sin(lon),np.sin(lat)],axis=-1)
    from scipy.spatial import cKDTree
    tree=cKDTree(xyz([s[1] for s in stations],[s[2] for s in stations]))
    hits=np.zeros(len(stations),dtype=np.int64)
    intervals=[]; decoded=0; seen=set()
    # Étendre le filtrage du décodeur de production pour tenir compte
    # du rayon et du décalage de parallaxe aux frontières du domaine.
    import collect
    collect.WEST,collect.SOUTH,collect.EAST,collect.NORTH=-8.0,40.0,10.5,52.5
    for product in sorted(products,key=str):
        name=str(product)
        m=PRODUCT_TIME.search(name)
        if not m: continue
        begin,finish=[datetime.strptime(s,"%Y%m%d%H%M%S").replace(tzinfo=timezone.utc) for s in m.groups()]
        if finish<=start or begin>=end or name in seen: continue
        pts=decode_product(download_one(product),name)
        seen.add(name); intervals.append((max(start,begin),min(end,finish))); decoded+=1
        lat=[];lon=[]
        for v in pts:
            if start.timestamp()<=v["ts"]<end.timestamp():
                y,x=table.correct(v["lat"],v["lon"],v["ts"])
                lat.append(y);lon.append(x)
        if lat:
            for indexes in tree.query_ball_point(xyz(lat,lon),2*np.sin(15/(2*6371.0088))):
                hits[indexes]+=1
        print("Produit décodé",decoded,"points France élargie",len(lat),flush=True)
    cursor=start; coverage=0.; largest_gap=0.
    for x,y in sorted(intervals):
        if x>cursor: largest_gap=max(largest_gap,(x-cursor).total_seconds())
        if y>cursor: coverage+=(y-max(x,cursor)).total_seconds();cursor=y
    largest_gap=max(largest_gap,(end-cursor).total_seconds())
    seconds=(end-start).total_seconds()
    # Les petites discontinuités de chronométrage sont tolérées, pas un cycle manquant.
    complete=coverage/seconds>=.995 and largest_gap<=30
    data={"schema":1,"source":"EUMETSAT MTG LI LFL EO:EUM:DAT:0691","date":a.date,
          "pilot":a.pilot,"start_utc":start.isoformat(),"end_utc":end.isoformat(),
          "radius_km":15,"parallax":METHOD,"products":decoded,"coverage_fraction":round(coverage/seconds,6),
          "max_gap_seconds":largest_gap,"complete":complete,"station_count":len(stations),
          "stations_with_flashes":{s[0]:int(h) for s,h in zip(stations,hits) if h>0},
          "station_ids":[s[0] for s in stations]}
    out=Path("data/eumetsat-li/pilot.json" if a.pilot else f"data/eumetsat-li/daily/{a.date}.json")
    out.parent.mkdir(parents=True,exist_ok=True)
    out.write_text(json.dumps(data,separators=(",",":"))+"\n")
    print("Bilan",json.dumps({k:v for k,v in data.items() if k not in ("station_ids","stations_with_flashes")}),flush=True)
    if not complete: raise RuntimeError("Couverture insuffisante ; aucune publication")
if __name__=="__main__":
    try: main()
    except Exception as exc:
        # Ne jamais consigner d'URL signée ni de jeton.
        print("Echec archive:",type(exc).__name__,flush=True)
        raise SystemExit(1)
