#!/usr/bin/env python3
"""Official Météo-France ODIM ACRR 500 m / 5 min. Preserve quality and coverage.
Preview generation only until independent geolocation and gauge checks pass."""
import io,os,json,gzip,math
from pathlib import Path
from datetime import datetime,timezone,timedelta
from urllib.parse import urlparse,urljoin,parse_qs
import requests,h5py,numpy as np
from pyproj import CRS,Transformer
from PIL import Image
BASE='https://public-api.meteofrance.fr/public/DPRadar/v1/'
OUT=Path('mf-radar-preview')
LEVELS=[.1,.3,1,3,8,15,30]
COLORS=[(72,61,138,190),(33,28,201,210),(0,163,224,230),(0,130,185,235),(255,221,0,245),(255,129,0,250),(193,0,0,255)]
def txt(x):return x.decode() if isinstance(x,bytes) else str(x)
def time(a,d,t):return datetime.strptime(txt(a[d])+txt(a[t]),'%Y%m%d%H%M%S').replace(tzinfo=timezone.utc)
def get():
    h={'apikey':os.environ['METEOFRANCE_API_KEY']}
    r=requests.get(BASE+'mosaiques/METROPOLE/observations/LAME_D_EAU',headers=h,timeout=25);r.raise_for_status()
    links=[l for l in r.json()['links'] if l.get('rel','').endswith('/data') and parse_qs(urlparse(l['href']).query).get('maille')==['500']]
    if len(links)!=1:raise ValueError('Unexpected 500m catalog')
    l=links[0];url=urljoin(BASE,l['href']);p=urlparse(url)
    if p.scheme!='https' or p.hostname!='public-api.meteofrance.fr':raise ValueError('Unexpected upstream URL')
    b=bytearray()
    with requests.get(url,headers=h,timeout=(15,90),stream=True) as r:
        r.raise_for_status()
        for chunk in r.iter_content(1024*1024):
            b.extend(chunk)
            if len(b)>30_000_000:raise ValueError('Oversized HDF5')
    return bytes(b),datetime.fromisoformat(l['validity_time'].replace('Z','+00:00'))
def parse(b,expected):
    with h5py.File(io.BytesIO(b),'r') as f:
        w=f['where'].attrs;meta=f['what'].attrs;d=f['dataset1/what'].attrs
        a=f['dataset1/data1/what'].attrs;q=f['dataset1/data1/quality1/what'].attrs
        start=time(d,'startdate','starttime');end=time(d,'enddate','endtime')
        if end!=expected or end!=time(meta,'date','time') or end-start!=timedelta(minutes=5) or end.minute%5 or end.second:raise ValueError('Invalid timestamp/interval')
        if datetime.now(timezone.utc)-end>timedelta(minutes=25) or end>datetime.now(timezone.utc):raise ValueError('Stale radar')
        if txt(meta['object'])!='COMP' or txt(a['quantity'])!='ACRR' or txt(q['quantity'])!='QIND':raise ValueError('Invalid quantity')
        if tuple(float(a[k]) for k in ('gain','offset','nodata','undetect'))!=(.01,0,65535,65534) or tuple(float(q[k]) for k in ('gain','offset','nodata','undetect'))!=(.01,0,255,254):raise ValueError('Unexpected radar scale')
        nx,ny=int(w['xsize']),int(w['ysize']);dx,dy=float(w['xscale']),float(w['yscale'])
        if (nx,ny,dx,dy)!=(3472,3472,500.,500.):raise ValueError('Unexpected grid')
        proj=CRS.from_proj4(txt(w['projdef']))
        if not proj.is_projected:raise ValueError('Expected projected CRS')
        trans=Transformer.from_crs('EPSG:4326',proj,always_xy=True)
        corners={k:trans.transform(float(w[k+'_lon']),float(w[k+'_lat'])) for k in ('UL','UR','LL','LR')}
        x0,y0=corners['UL']
        for k,(ex,ey) in {'UR':(x0+nx*dx,y0),'LL':(x0,y0-ny*dy),'LR':(x0+nx*dx,y0-ny*dy)}.items():
            if math.hypot(corners[k][0]-ex,corners[k][1]-ey)>2:raise ValueError('ODIM corner consistency failed '+k)
        data=f['dataset1/data1/data'][...];quality=f['dataset1/data1/quality1/data'][...]
        if data.shape!=(ny,nx) or quality.shape!=data.shape or data.dtype!=np.uint16 or quality.dtype!=np.uint8:raise ValueError('Dataset shape/type')
        if np.any((quality>100)&(quality<254)):raise ValueError('Unknown quality value')
        # Undetect is zero accumulation; nodata and missing quality stay invalid.
        good=(data!=65535)&(quality<=100)
        mm=np.where(data==65534,0.,data*.01).astype(np.float32);mm[~good]=np.nan
        print('ODIM',start.isoformat(),end.isoformat(),'CORNERS',corners,'valid',int(good.sum()),'max mm',float(np.nanmax(mm)),flush=True)
        return mm,quality,trans,x0,y0,dx,dy,end
def sample(parsed,lon,lat):
    mm,q,tr,x0,y0,dx,dy,end=parsed
    x,y=tr.transform(lon,lat);ix=np.floor((x-x0)/dx).astype(int);iy=np.floor((y0-y)/dy).astype(int)
    inside=(ix>=0)&(iy>=0)&(ix<mm.shape[1])&(iy<mm.shape[0])
    val=np.full(lon.shape,np.nan,dtype=np.float32);qual=np.full(lon.shape,255,dtype=np.uint8)
    val[inside]=mm[iy[inside],ix[inside]];qual[inside]=q[iy[inside],ix[inside]]
    return val,qual
def render(parsed,width,height):
    # Exact KFS SVG mapping, evaluate pixel centers. High-resolution output
    # preserves source detail at department zoom; never extrapolate.
    lon,lat=np.meshgrid(-5.8+(np.arange(width)+.5)*730/width/46,51.6-(np.arange(height)+.5)*735/height/65)
    mm,q=sample(parsed,lon,lat)
    idx=np.searchsorted(LEVELS,np.nan_to_num(mm,nan=0)*12,side='right')
    pal=np.array([(0,0,0,0)]+COLORS,dtype=np.uint8)
    rgba=pal[idx];rgba[~np.isfinite(mm)]=(125,145,160,100)
    return Image.fromarray(rgba)
def main():
    OUT.mkdir(exist_ok=True);b,t=get();p=parse(b,t)
    name=t.strftime('%Y%m%d%H%M')
    for w,h in ((730,735),(1460,1470),(2920,2940)):
        image=render(p,w,h);image.save(OUT/f'radar-{name}-{w}.png',optimize=True)
    lon,lat=np.meshgrid(np.linspace(-6,10,401),np.linspace(52,41,276))
    mm,q=sample(p,lon,lat)
    np.savez_compressed(OUT/f'radar-{name}.npz',schema=np.array(1),source=np.array('Météo-France ACRR 500m'),unit=np.array('mm'),interval_minutes=np.array(5),valid_utc=np.array(t.isoformat()),lon=lon.astype(np.float32),lat=lat.astype(np.float32),values=mm,coverage=np.isfinite(mm),quality=q)
    print('SAMPLED COVERAGE',float(np.isfinite(mm).mean()),'QUALITY',float(np.mean(q[q<=100])),flush=True)
    (OUT/'manifest.json').write_text(json.dumps({'schema':1,'source':'Météo-France ACRR 500m','valid_utc':t.isoformat(),'interval_minutes':5,'unit':'mm','projection':'KFS-stations-730x735-v2','width':2920,'height':2940,'file':f'radar-{name}-2920.png','verified_geometry_corners':True,'independent_validation':False},indent=2))
if __name__=='__main__':main()
