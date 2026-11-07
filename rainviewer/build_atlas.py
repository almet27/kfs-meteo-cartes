#!/usr/bin/env python3
"""Animation RainViewer Web Mercator, sans BUFR. Usage communautaire avec attribution."""
import argparse
import concurrent.futures
import datetime as dt
import io
import json
import math
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

API = 'https://api.rainviewer.com/public/weather-maps.json'
DEPARTMENTS = 'https://raw.githubusercontent.com/gregoiredavid/france-geojson/master/departements.geojson'
ZOOM, SIZE, X0, Y0, COLS, ROWS = 6, 512, 31, 21, 3, 3
MAX_FRAMES, MAX_AGE_MINUTES = 8, 35
CITIES = [
    ('Caen', -0.3707,49.1829),('Rouen',1.0993,49.4431),
    ('Paris',2.3522,48.8566),('Brest',-4.4861,48.3904),
    ('Rennes',-1.6778,48.1173),('Le Havre',0.1079,49.4944),
    ('Nantes',-1.5536,47.2184),('Lille',3.0573,50.6292),
    ('Orleans',1.9093,47.9029),('Bourth',0.81,48.77),
    ('Bordeaux',-0.5792,44.8378),('Lyon',4.8357,45.7640),
    ('Marseille',5.3698,43.2965),('Toulouse',1.4442,43.6047),
    ('Strasbourg',7.7521,48.5734),('Ajaccio',8.7386,41.9192),
]

def request_bytes(url, maximum=10000000, attempts=3):
    for attempt in range(attempts):
        try:
            req=urllib.request.Request(url,headers={
                'User-Agent':'KFS-Meteo-RainViewer/1.0 (petite communaute)'})
            with urllib.request.urlopen(req,timeout=25) as response:
                if response.status!=200:
                    raise RuntimeError('HTTP '+str(response.status))
                data=response.read(maximum+1)
                if len(data)>maximum:
                    raise RuntimeError('Reponse trop volumineuse')
                return data
        except (urllib.error.HTTPError,urllib.error.URLError,TimeoutError) as exc:
            if attempt+1==attempts:
                raise RuntimeError('Telechargement impossible: '+str(exc)) from exc
            time.sleep(1.5*(attempt+1))

def validate_catalog(meta,now):
    parsed=urllib.parse.urlparse(str(meta.get('host','')))
    if parsed.scheme!='https' or parsed.hostname not in ('tilecache.rainviewer.com','tilecache2.rainviewer.com'):
        raise RuntimeError('Hote RainViewer inattendu')
    frames=meta.get('radar',{}).get('past',[])
    if not isinstance(frames,list):
        raise RuntimeError('Historique RainViewer invalide')
    by_time={}
    for item in frames:
        timestamp,path=item.get('time'),item.get('path')
        if (type(timestamp)==int and isinstance(path,str)
            and re.fullmatch(r'/v2/radar/[a-zA-Z0-9_-]+',path)
            and 0<=now-timestamp<=10800):
            by_time[timestamp]=path
    result=sorted(by_time.items())[-MAX_FRAMES:]
    if len(result)<2:
        raise RuntimeError('Moins de deux observations distinctes')
    if now-result[-1][0]>MAX_AGE_MINUTES*60:
        raise RuntimeError('Derniere observation ancienne')
    if any(b[0]-a[0]>1200 for a,b in zip(result,result[1:])):
        raise RuntimeError('Historique radar discontinu')
    return parsed.geturl().rstrip('/'),result

def location_pixel(lon,lat):
    lat=max(-85,min(85,lat))
    x=(lon+180)/360*2**ZOOM
    y=(1-math.asinh(math.tan(math.radians(lat)))/math.pi)/2*2**ZOOM
    return (x-X0)*SIZE,(y-Y0)*SIZE

def font(size):
    for path in ('/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf',
                 '/usr/share/fonts/truetype/liberation2/LiberationSans-Regular.ttf'):
        try:
            return ImageFont.truetype(path,size=size)
        except OSError:
            continue
    return ImageFont.load_default()

def borders():
    try:
        data=json.loads(request_bytes(DEPARTMENTS,maximum=4000000,attempts=2))
        result=[]
        for feat in data.get('features',[]):
            geo=feat.get('geometry') or {}
            kind,coords=geo.get('type'),geo.get('coordinates',[])
            polys=[coords] if kind=='Polygon' else coords if kind=='MultiPolygon' else []
            for poly in polys:
                for ring in poly:
                    points=[location_pixel(lon,lat) for lon,lat in ring]
                    if len(points)<2:
                        continue
                    xs=[p[0] for p in points]
                    ys=[p[1] for p in points]
                    if (max(xs)<-30 or min(xs)>COLS*SIZE+30 or
                        max(ys)<-30 or min(ys)>ROWS*SIZE+30):
                        continue
                    result.append(points)
        print('Contours :',len(result),flush=True)
        return result
    except (RuntimeError,ValueError,KeyError,TypeError) as exc:
        print('AVERTISSEMENT : contours indisponibles :',exc,flush=True)
        return []

def make_base(lines):
    base=Image.new('RGBA',(COLS*SIZE,ROWS*SIZE),'#e8eff4')
    draw=ImageDraw.Draw(base,'RGBA')
    for line in lines:
        draw.line(line,fill=(91,112,130,190),width=2)
    return base

def decorate(im,ts):
    draw=ImageDraw.Draw(im)
    small,big=font(18),font(25)
    for label,lon,lat in CITIES:
        x,y=location_pixel(lon,lat)
        if not(4<x<COLS*SIZE-6 and 4<y<ROWS*SIZE-6):
            continue
        draw.ellipse((x-3,y-3,x+3,y+3),fill='#c74350',outline='white',width=1)
        if label in ('Rouen','Caen','Paris','Lille','Bordeaux','Lyon','Marseille',
                     'Brest','Nantes','Rennes','Bourth'):
            draw.text((x+7,y-8),label,font=small,fill='#243447',
                      stroke_width=2,stroke_fill='#f8fafc')
    draw.rounded_rectangle((12,12,540,78),radius=12,fill='#16324be8')
    draw.text((26,18),'KFS METEO  |  RADAR PLUIE',font=big,fill='white')
    draw.text((26,50),f'{ts:%d/%m/%Y %H:%M} UTC  -  RainViewer',font=small,fill='#d8edf9')
    draw.rounded_rectangle((12,ROWS*SIZE-50,570,ROWS*SIZE-10),
                           radius=10,fill='#16324be8')
    draw.text((25,ROWS*SIZE-42),'RainViewer.com  |  France GeoJSON',font=small,fill='white')

def obtain_tiles(host,path):
    jobs=[(x,y) for y in range(Y0,Y0+ROWS) for x in range(X0,X0+COLS)]
    def fetch_tile(pair):
        x,y=pair
        url=f'{host}{path}/{SIZE}/{ZOOM}/{x}/{y}/2/1_1.png'
        try:
            data=request_bytes(url,maximum=2000000)
            with Image.open(io.BytesIO(data)) as tile:
                if tile.size!=(SIZE,SIZE):
                    raise RuntimeError('Dimensions image incorrectes')
                return x,y,tile.convert('RGBA')
        except (RuntimeError,OSError,ValueError) as exc:
            print('Tuile indisponible:',x,y,str(exc)[:100],flush=True)
            return x,y,None
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as executor:
        return list(executor.map(fetch_tile,jobs))

def build_frames(host,entries,lines):
    base=make_base(lines)
    results=[]
    counts=[]
    for index,(ts,path) in enumerate(entries,1):
        tiles=obtain_tiles(host,path)
        valid=sum(tile is not None for x,y,tile in tiles)
        if valid<3:
            raise RuntimeError('Moins de 3 tuiles utilisables : radar non genere')
        image=base.copy()
        for x,y,tile in tiles:
            if tile is not None:
                image.alpha_composite(tile,((x-X0)*SIZE,(y-Y0)*SIZE))
        decorate(image,dt.datetime.fromtimestamp(ts,dt.timezone.utc))
        quant=image.convert('RGB').quantize(colors=128,
            method=Image.Quantize.FASTOCTREE,dither=Image.Dither.NONE)
        results.append(quant)
        counts.append(valid)
        print('Image',index,'/',len(entries),'UTC',ts,'tuiles',valid,flush=True)
    return results,counts

def run(output,now=None):
    now=int(time.time()) if now is None else int(now)
    meta=json.loads(request_bytes(API,maximum=1000000))
    host,entries=validate_catalog(meta,now)
    frames,counts=build_frames(host,entries,borders())
    output.mkdir(parents=True,exist_ok=True)
    gif=output/'radar-rainviewer.gif'
    durations=[max(200,min(1500,(b[0]-a[0])*1000//900))
               for a,b in zip(entries,entries[1:])]+[700]
    frames[0].save(gif,format='GIF',save_all=True,
                   append_images=frames[1:],duration=durations,
                   loop=0,optimize=True,disposal=2)
    stamp=lambda ts:dt.datetime.fromtimestamp(ts,dt.timezone.utc).isoformat()
    manifest={
        'schema':1,'provider':'RainViewer','source':'https://www.rainviewer.com/',
        'projection':'EPSG:3857','zoom':ZOOM,'tile_size':SIZE,
        'x0':X0,'y0':Y0,'width':COLS*SIZE,'height':ROWS*SIZE,
        'nombre_images':len(frames),
        'observations_utc':[stamp(t) for t,path in entries],
        'derniere_observation_utc':stamp(entries[-1][0]),
        'generation_utc':stamp(now),
        'tuiles_valides':counts,'gif':gif.name,
        'mode':'historique_radar','georeferencement':'Web Mercator XYZ'
    }
    (output/'radar-rainviewer.json').write_text(
        json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8')
    (output/'.nojekyll').touch()
    print('GIF RainViewer genere:',gif,
          'images:',len(frames),'octets:',gif.stat().st_size,flush=True)
    return manifest

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,default=Path('rainviewer-public'))
    args=parser.parse_args()
    run(args.output)
