#!/usr/bin/env python3
"""Produce the KFS ground snow overlay from NOAA/USNIC IMS 1 km.
Keep categorical classes; never infer absence of snow from missing data.
"""
import datetime as dt
import io
import json
from pathlib import Path
import numpy as np
import requests
import rasterio
from rasterio.io import MemoryFile
from rasterio.transform import from_bounds
from rasterio.warp import reproject, Resampling
from PIL import Image

BASE="https://mapservices.weather.noaa.gov/raster/rest/services/obs/usnic_ims_snow_ice_1km/ImageServer"
BBOX=(-5.8,51.6-735/65,-5.8+730/46,51.6)
W,H=1460,1470
def main():
    s=requests.Session()
    s.headers["User-Agent"]="KFS Meteo snow cover map / NOAA IMS"
    r=s.get(BASE+"/query",params={"where":"1=1","outFields":"objectid,name,idp_filedate","returnGeometry":"false","f":"json"},timeout=60)
    r.raise_for_status()
    features=r.json().get("features",[])
    rows=[f["attributes"] for f in features if isinstance(f.get("attributes",{}).get("idp_filedate"),(int,float))]
    if not rows: raise RuntimeError("IMS metadata has no dated raster")
    row=max(rows,key=lambda x:x["idp_filedate"])
    stamp=dt.datetime.fromtimestamp(row["idp_filedate"]/1000,dt.timezone.utc)
    age=dt.datetime.now(dt.timezone.utc)-stamp
    if not dt.timedelta(hours=-3)<=age<=dt.timedelta(days=3): raise RuntimeError("IMS raster date stale")
    q={"bbox":",".join(map(str,BBOX)),"bboxSR":4326,"imageSR":4326,"size":f"{W},{H}","format":"tiff","pixelType":"U8","interpolation":"RSP_NearestNeighbor","mosaicRule":json.dumps({"mosaicMethod":"esriMosaicLockRaster","lockRasterIds":[row["objectid"]]}),"renderingRule":json.dumps({"rasterFunction":"None"}),"f":"image"}
    r=s.get(BASE+"/exportImage",params=q,timeout=120)
    r.raise_for_status()
    if len(r.content)>25_000_000 or r.content[:4] not in (b"II*\x00",b"MM\x00*"): raise RuntimeError("Expected raw GeoTIFF")
    with MemoryFile(r.content) as f, f.open() as ds:
        if ds.count!=1 or not ds.crs: raise RuntimeError("Expected categorical georeferenced raster")
        src=ds.read(1,masked=True)
        if not set(np.unique(src.compressed())).issubset({0,1,2,3,4}): raise RuntimeError("Invalid IMS classes")
        dest=np.zeros((H,W),dtype=np.uint8)
        reproject(src.filled(0),dest,src_transform=ds.transform,src_crs=ds.crs,src_nodata=0,dst_transform=from_bounds(*BBOX,W,H),dst_crs="EPSG:4326",dst_nodata=0,resampling=Resampling.nearest)
    known=int(np.count_nonzero(dest))
    if known<dest.size*.5: raise RuntimeError("Insufficient IMS map coverage")
    rgba=np.zeros((H,W,4),dtype=np.uint8)
    rgba[dest==4]=(70,195,255,220)
    rgba[dest==0]=(145,155,165,150)
    out=Path("data/snow-cover")
    out.mkdir(parents=True,exist_ok=True)
    file="ims-"+stamp.strftime("%Y%m%dT%H%M%SZ")+".png"
    Image.fromarray(rgba).save(out/file,optimize=True)
    manifest={"schema":1,"source":"NOAA / US National Ice Center IMS 1 km","date":stamp.isoformat(),"date_type":"source_file_date","projection":"KFS-730x735-v1","width":W,"height":H,"image":file,"snow_pixels":int(np.count_nonzero(dest==4)),"valid_pixels":known,"total_pixels":dest.size}
    (out/"latest.json").write_text(json.dumps(manifest,separators=(",",":"))+"\n")
    for p in out.glob("ims-*.png"):
        if p.name!=file: p.unlink()
    print(json.dumps(manifest),flush=True)
if __name__=="__main__": main()
