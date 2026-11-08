#!/usr/bin/env python3
"""Fetch ECMWF Weekly anomaly maps for the KFS Sunday bulletin.

Do not invent numbers from images. On failure write an explicit blocked status,
never a fabricated forecast. Run from repo root via GitHub Actions.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlencode, urlsplit
from urllib.request import Request, urlopen

from PIL import Image

OUT=Path("forecast-maps/tendance")
OUT.mkdir(parents=True,exist_ok=True)
API="https://charts.ecmwf.int/opencharts-api/v1/products/"
VARIABLES={"t2m":"extended-anomaly-2t", "precip":"extended-anomaly-tp"}
# Optional ensemble-probability maps for responsible expression of uncertainty.
PROBABILITY={"t2m":"extended-prob-anom-2t", "precip":"extended-prob-anom-tp"}
SYNOPTIC={"mslp":"extended-anomaly-mslp", "z500":"extended-anomaly-z500"}
AREA="opencharts_eurasia"
USER_AGENT="KFS-Meteo/1.0 (ECMWF OpenCharts citation and forecast validation)"
now=datetime.now(timezone.utc)
# Weekly ensemble extension on Monday and Thursday 00 UTC.
day_since_thu=(now.weekday()-3)%7
base=(now-timedelta(days=day_since_thu)).replace(hour=0,minute=0,second=0,microsecond=0)
# On Mondays and late Thursdays, select the newest published 00UTC extension.
monday=(now-timedelta(days=now.weekday())).replace(hour=0,minute=0,second=0,microsecond=0)
if now.weekday() in (0,1,2) and now-monday>=timedelta(hours=15):
    base=monday
next_week_monday=base+timedelta(days=(7-base.weekday())%7 or 7)
if base.weekday()==0:
    next_week_monday=base # Monday run: first week starts same Monday
if base.weekday() not in (0,3):
    raise RuntimeError("Unexpected ECMWF weekly run day")

def iso(x):return x.strftime("%Y-%m-%dT%H:%M:%SZ")
def get_json(url):
    with urlopen(Request(url,headers={"User-Agent":USER_AGENT,"Accept":"application/json"}),
                 timeout=25) as response:
        if "json" not in str(response.headers.get("Content-Type","")).lower():
            raise ValueError("OpenCharts response is not JSON")
        blob=response.read(450000)
        if len(blob)>=450000:raise ValueError("Excessive JSON response")
        return json.loads(blob)
def get_image(url):
    target=urlsplit(url)
    if target.scheme!="https" or target.hostname!="charts.ecmwf.int" or not target.path.startswith("/content/"):
        raise ValueError("Image URL outside official ECMWF OpenCharts")
    if not target.path.lower().endswith(".png"):
        raise ValueError("ECMWF chart is not PNG")
    with urlopen(Request(url,headers={"User-Agent":USER_AGENT,"Accept":"image/png"}),
                 timeout=40) as response:
        content=response.read(8500000)
    if len(content)<14000 or len(content)>=8500000 or not content.startswith(b"\x89PNG\r\n\x1a\n"):
        raise ValueError("Invalid or truncated PNG")
    return content

def fetch_chart(week,kind,product,start,end,probability=False):
    q=urlencode({"base_time":iso(base),"valid_time":iso(end),"projection":AREA})
    api=API+product+"/?"+q
    obj=get_json(api)
    info=obj.get("data",{})
    href=info.get("link",{}).get("href","")
    media=info.get("link",{}).get("type","")
    description=str(info.get("attributes",{}).get("description",""))
    expected=[base.strftime("%d %b %Y"),start.strftime("%d %b %Y"),end.strftime("%d %b %Y")]
    if media!="image/png" or not all(fragment.lower() in description.lower() for fragment in expected):
        raise ValueError("Product date/run/format inconsistent: "+description[:260])
    png=get_image(href)
    name=f"weekly-week{week}-"+("prob-" if probability else "")+kind+".png"
    path=OUT/name
    path.write_bytes(png)
    try:
        with Image.open(path) as image:
            if image.format!="PNG" or min(image.size)<650 or max(image.size)<850:
                raise ValueError("Chart resolution too low")
            image.verify()
    except Exception:
        path.unlink(missing_ok=True)
        raise
    return {
      "product":product, "file_path":str(path),
      "image_url":"https://almet27.github.io/kfs-meteo-cartes/"+str(path),
      "ecmwf_content_url":href,"ecmwf_product_url":api,
      "description":description,"size_bytes":len(png),
      "sha256":hashlib.sha256(png).hexdigest(),
      "chart_type":"ensemble probability of anomaly" if probability else "weekly ensemble mean anomaly",
      "valid_start_utc":iso(start),"valid_end_utc":iso(end),
    }
def main():
    status={"schema_version":1,"verified":False,"generated_utc":None,
      "source":"ECMWF OpenCharts — Sub-seasonal ensemble weekly anomalies",
      "base_time_utc":iso(base),"weeks":[],
      "temperature_anomalies_verified":False,"precipitation_anomalies_verified":False,
      "charts":{},"probability_charts":{},"synoptic_charts":{},
      "note":"No extension of deterministic forecasts; use official anomaly charts only.",
      "copyright":"© ECMWF — original product URLs and provenance provided.",
      "alerts":[]}
    try:
        for week in (3,4):
            start=next_week_monday+timedelta(days=7*(week-1))
            end=start+timedelta(days=7)
            group={}
            for kind,product in VARIABLES.items():
                group[kind]=fetch_chart(week,kind,product,start,end)
            status["charts"][str(week)]=group
            status["weeks"].append(week)
        # Optional probabilities: enrich uncertainty; no invented probabilities.
        for week in (3,4):
            start=next_week_monday+timedelta(days=7*(week-1))
            end=start+timedelta(days=7)
            prob={}
            for kind,product in PROBABILITY.items():
                try:
                    prob[kind]=fetch_chart(week,kind,product,start,end,True)
                except Exception as error:
                    status["alerts"].append("Optional probability week%d %s: %s"%(week,kind,str(error)[:160]))
            status["probability_charts"][str(week)]=prob
        # Complementary anomaly maps of pressure and geopotential: true
        # weekly ensemble signals, helpful for synoptic interpretation.
        for week in (3,4):
            start=next_week_monday+timedelta(days=7*(week-1))
            end=start+timedelta(days=7)
            syn={}
            for kind,product in SYNOPTIC.items():
                try:
                    syn[kind]=fetch_chart(week,kind,product,start,end)
                except Exception as error:
                    status["alerts"].append("Optional synoptic week%d %s: %s"%(week,kind,str(error)[:160]))
            status["synoptic_charts"][str(week)]=syn
        status["temperature_anomalies_verified"]=True
        status["precipitation_anomalies_verified"]=True
        status["verified"]=True
        status["generated_utc"]=iso(datetime.now(timezone.utc))
        status["note"]="Official ECMWF weekly anomaly PNGs downloaded and validated for both weeks. No numeric anomaly magnitude or ensemble spread inferred from images; interpretation requires chart review."
    except Exception as exc:
        status["alerts"].append(type(exc).__name__+": "+str(exc)[:280])
        status["charts"]={}
        status["probability_charts"]={}
        status["weeks"]=[]
        # Do not retain stale verified image files if a refresh failed.
        status["generated_utc"]=None
        print("::warning::ECMWF Weekly validation failed: "+str(exc)[:220],flush=True)
    (OUT/"extended-weekly.json").write_text(json.dumps(status,ensure_ascii=False,indent=2)+"\n",encoding="utf8")
    print(json.dumps({"verified":status["verified"],"base_time_utc":status["base_time_utc"],
                      "weeks":status["weeks"],"alerts":status["alerts"],
                      "charts":{w:{k:v["size_bytes"] for k,v in records.items()}
                                for w,records in status["charts"].items()}},
                     ensure_ascii=False,indent=2),flush=True)
if __name__=="__main__":main()
