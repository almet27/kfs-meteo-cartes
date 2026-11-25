"""Créer une petite LUT France à partir des 12 NetCDF officiels SSP_0_LUT.
Usage: python foudre-li/build_parallax_lut.py /chemin/SSP_0_LUT.tar.gz
Source officielle: https://sftp.eumetsat.int/public/folder/UsCVknVOOkSyCdgpMimJNQ/User-Materials/MTGUP/LI_parallax_correction/
Interpolation spatiale par voisin le plus proche sur la sphère, grille .125 degré.
Aucune donnée synthétique ne peut remplacer les tables.
"""
import argparse
import calendar
import shutil
import tarfile
import tempfile
from pathlib import Path
import numpy as np
from netCDF4 import Dataset
from scipy.spatial import cKDTree
from parallax import METHOD, LUT, Parallax

def xyz(lat, lon):
    a,b=np.deg2rad(lat),np.deg2rad(lon)
    return np.column_stack((np.cos(a)*np.cos(b),np.cos(a)*np.sin(b),np.sin(a)))

def build(archive, output):
    lat=np.arange(40.,52.501,.125)
    lon=np.arange(-8.,10.501,.125)
    gx,gy=np.meshgrid(lon,lat)
    target=xyz(gy.ravel(),gx.ravel())
    shifts=[[],[]]
    with tarfile.open(archive,"r:*") as tar, tempfile.TemporaryDirectory() as tmp:
        members=tar.getmembers()
        for m in range(1,13):
            prefix="PX_"+calendar.month_abbr[m]+"_2005_2018_MK_res1"
            files=[f for f in members if f.isfile() and Path(f.name).name.startswith(prefix) and f.name.lower().endswith(".nc")]
            if len(files)!=1 or files[0].size>600_000_000:
                raise ValueError("Table mensuelle manquante ou inattendue: "+prefix)
            path=Path(tmp)/"month.nc"
            with tar.extractfile(files[0]) as src, path.open("wb") as dst:
                shutil.copyfileobj(src,dst)
            with Dataset(path) as ds:
                values=[np.ma.asarray(ds.variables[v][:],dtype=np.float64).filled(np.nan).ravel()
                        for v in ("lat","lon","new_lat_ice","new_lon_ice")]
            path.unlink()
            a,b,c,d=values
            keep=np.isfinite(a)&np.isfinite(b)&np.isfinite(c)&np.isfinite(d)&(a>=39)&(a<=54)&(b>=-10)&(b<=13)
            if not np.any(keep):
                raise ValueError("Aucune donnée régionale dans "+prefix)
            a,b,c,d=[v[keep] for v in values]
            dist,idx=cKDTree(xyz(a,b)).query(target)
            if np.max(dist)>2*np.sin(50/6371/2):
                raise ValueError("Couverture spatiale incomplète: "+prefix)
            shifts[0].append((c-a)[idx].reshape(gx.shape))
            shifts[1].append((d-b)[idx].reshape(gx.shape))
            print("Table validée:",prefix,flush=True)
    output=Path(output)
    temp=output.with_name(output.stem+".tmp.npz")
    np.savez_compressed(temp,lat=lat,lon=lon,dlat=np.asarray(shifts[0],dtype=np.float32),
                        dlon=np.asarray(shifts[1],dtype=np.float32),method=METHOD)
    Parallax(temp)
    temp.replace(output)

if __name__=="__main__":
    p=argparse.ArgumentParser()
    p.add_argument("archive",type=Path)
    p.add_argument("--out",type=Path,default=LUT)
    a=p.parse_args()
    build(a.archive,a.out)
