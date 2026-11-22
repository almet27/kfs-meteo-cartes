"""Probe official snow sources before using them in the public climato maps."""
import csv,gzip,io,json,os,re
from datetime import datetime,timedelta,timezone
import requests
from concurrent.futures import ThreadPoolExecutor
BASE="https://meteofrance.s3.sbg.io.cloud.ovh.net/data/"
YEAR=datetime.now(timezone.utc).year
TODAY=datetime.now(timezone.utc).date()
def sample(name,url,compressed=True):
    try:
        with requests.get(url,stream=True,timeout=(15,65)) as r:
            r.raise_for_status()
            r.raw.decode_content=True
            raw=gzip.GzipFile(fileobj=r.raw) if compressed else r.raw
            reader=csv.reader(io.TextIOWrapper(raw,encoding="utf-8-sig",errors="replace"),delimiter=";")
            header=next(reader)
            rows=[]
            for _ in range(3):
                row=next(reader,None)
                if row is not None: rows.append(row)
            return {"name":name,"ok":True,"columns":header,"sample":rows,"last_modified":r.headers.get("Last-Modified")}
    except Exception as e:return {"name":name,"ok":False,"error":str(e)}
def ims():
    url="https://mapservices.weather.noaa.gov/raster/rest/services/obs/usnic_ims_snow_ice_1km/ImageServer"
    try:
        r=requests.get(url,params={"f":"json"},timeout=35);r.raise_for_status()
        d=r.json()
        return {"name":"NOAA IMS current","ok":"error" not in d,"pixelSizeX":d.get("pixelSizeX"),"pixelSizeY":d.get("pixelSizeY"),"pixelType":d.get("pixelType"),"timeInfo":d.get("timeInfo"),"rasterFunctionInfos":d.get("rasterFunctionInfos"),"error":d.get("error")}
    except Exception as e:return {"name":"NOAA IMS current","ok":False,"error":str(e)}
def catalog():
    try:
        end=TODAY.isoformat()+"T00:00:00.000Z"
        start=(TODAY-timedelta(days=5)).isoformat()+"T00:00:00.000Z"
        # CLMS archive catalogue metadata only; no credentials or full imagery.
        r=requests.get("https://catalogue.dataspace.copernicus.eu/odata/v1/Products",params={"$filter":f"Collection/Name eq 'CLMS' and contains(Name,'GFSC') and ContentDate/Start ge {start} and ContentDate/Start lt {end} and OData.CSC.Intersects(area=geography'SRID=4326;POLYGON((-5 42,9 42,9 51,-5 51,-5 42))')","$top":3,"$select":"Id,Name,ContentDate,S3Path"},timeout=45)
        r.raise_for_status()
        return {"name":"Copernicus GFSC catalogue","ok":True,"products":r.json().get("value",[])}
    except Exception as e:return {"name":"Copernicus GFSC catalogue","ok":False,"error":str(e)}
jobs=[
 lambda:sample("SIM national",BASE+"REF_CC/SIM/QUOT_SIM2_latest.csv.gz"),
 lambda:sample("NIVO mountains",BASE+f"REF_CC/NIVO/donnees_nivologiques_{YEAR}.csv.gz"),
 lambda:sample("Station observations Nord",BASE+f"synchro_ftp/BASE/QUOT/Q_59_latest-{YEAR-1}-{YEAR}_autres-parametres.csv.gz"),
 ims,catalog]
with ThreadPoolExecutor(max_workers=5) as pool:
    results=list(pool.map(lambda f:f(),jobs))
for result in results:
    print(json.dumps(result,ensure_ascii=False,default=str),flush=True)
with open("snow-source-diagnostic.json","w") as f:json.dump(results,f,ensure_ascii=False,indent=2)
