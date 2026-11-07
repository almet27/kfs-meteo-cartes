#!/usr/bin/env python3
"""Creer un atlas GIF radar georeference recadrable par ville (DIAGNOSTIC).

La projection stéréographique polaire WGS84 provient du descriptif officiel
Météo-France IMFR27 (16/01/2024), latitude de référence 45°.
Une validation de positionnement indépendante est encore nécessaire.
"""
import argparse
import json
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np
from PIL import Image, ImageDraw, ImageFont
from pyproj import CRS, Transformer
try:
    from radar.zoom_ville import radar_grid
except ModuleNotFoundError:
    from zoom_ville import radar_grid

# Emprise LCC assez large pour un zoom de 180 km autour des villes metropolitaines.
# Emprise de l'atlas dans la projection stereographique polaire WGS84,
# latitude vraie 45 N / meridien central 0, en metres.
# Limites fixes pour rendre les recadrages reproductibles entre observations.
XMIN, XMAX = -900_000.0, 1_100_000.0
YMIN, YMAX = -5_400_000.0, -3_400_000.0
WIDTH = HEIGHT = 1600
RADIUS_KM = 180
LAYERS = [
    'https://raw.githubusercontent.com/gregoiredavid/france-geojson/master/departements.geojson',
    'https://raw.githubusercontent.com/datasets/geo-countries/master/data/countries.geojson',
]

def font(size):
    try:
        return ImageFont.load_default(size=size)
    except (TypeError, OSError):
        return ImageFont.load_default()

def get_contours(transformer):
    lines = []
    for url in LAYERS:
        try:
            req = urllib.request.Request(url, headers={'User-Agent': 'KFS-radar-diagnostic/1.0'})
            with urllib.request.urlopen(req, timeout=18) as response:
                raw = response.read(10_000_001)
            if len(raw) > 10_000_000:
                raise ValueError('Fond de carte trop volumineux')
            features = json.loads(raw)['features']
            for feature in features:
                g = feature.get('geometry') or {}
                kind = g.get('type')
                coords = g.get('coordinates') or []
                polygons = [coords] if kind == 'Polygon' else coords if kind == 'MultiPolygon' else []
                for polygon in polygons:
                    for ring in polygon:
                        if len(ring) < 2:
                            continue
                        xy = np.asarray(ring, dtype=float)
                        xx, yy = transformer.transform(xy[:, 0], xy[:, 1])
                        if max(xx) < XMIN or min(xx) > XMAX or max(yy) < YMIN or min(yy) > YMAX:
                            continue
                        points = [
                            ((x-XMIN) * WIDTH/(XMAX-XMIN),
                             (YMAX-y) * HEIGHT/(YMAX-YMIN))
                            for x,y in zip(xx,yy)]
                        lines.append(points)
        except (OSError, ValueError, KeyError) as exc:
            print('Fond indisponible (radar quand meme produit):', url, str(exc)[:150], flush=True)
    print('Contours geographiques retenus :', len(lines), flush=True)
    return lines

def make_city_marker(path):
    """Petit repere geographique transparent pour le centre du zoom Discord."""
    marker = Image.new('RGBA', (56, 56), (0, 0, 0, 0))
    d = ImageDraw.Draw(marker)
    # Bord blanc pour rester lisible sur des echos radar jaunes ou violets.
    d.ellipse((16, 16, 40, 40), fill=(255, 255, 255, 225),
              outline=(255, 255, 255, 255), width=5)
    d.ellipse((18, 18, 38, 38), fill=(242, 55, 79, 235),
              outline=(133, 19, 39, 255), width=2)
    d.ellipse((25, 25, 31, 31), fill=(255, 255, 255, 255))
    for x0, y0, x1, y1 in ((28, 2, 28, 14), (28, 42, 28, 54),
                           (2, 28, 14, 28), (42, 28, 54, 28)):
        d.line((x0,y0,x1,y1),fill=(255,255,255,255),width=5)
        d.line((x0,y0,x1,y1),fill=(181,24,53,255),width=2)
    marker.save(path)


def select_data(directory, times):
    chosen = []
    for value in times:
        when = datetime.fromisoformat(value.replace('Z', '+00:00')).astimezone(timezone.utc)
        path = directory / ('radar-grid-'+when.strftime('%Y-%m-%dT%H-%M-%SZ')+'.npz')
        if not path.is_file():
            continue
        try:
            observed, values, geo = radar_grid(path)
        except ValueError as error:
            if 'Projection radar non conforme' in str(error):
                print('ANCIENNE GRILLE LAMBERT EXCLUE:',path.name,flush=True)
                continue
            raise
        if observed != when:
            raise ValueError('Horodatage incorrect : '+path.name)
        if chosen and geo != chosen[0][2]:
            raise ValueError('Projection ou origine modifiee entre grilles')
        if chosen and (when-chosen[-1][0]).total_seconds() > 1500:
            chosen = []
        chosen.append((when, values, geo))
    return chosen[-8:]

def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--dossier-grilles', type=Path, required=True)
    p.add_argument('--horodatages', type=Path, required=True)
    p.add_argument('--sortie', type=Path, required=True)
    p.add_argument('--manifest', type=Path, required=True)
    args = p.parse_args()
    times = json.loads(args.horodatages.read_text(encoding='utf-8'))
    if not isinstance(times, list) or len(times) > 8:
        p.error('Liste des heures invalide')
    data = select_data(args.dossier_grilles, times)
    if len(data) < 2:
        print('ATLAS NON GENERE : moins de 2 grilles recentes compatibles', flush=True)
        return
    latest = data[-1][0]
    age = (datetime.now(timezone.utc)-latest).total_seconds()/60
    if age > 45 or age < -5:
        print(f'ATLAS NON GENERE : observation agee de {age:.1f} minutes', flush=True)
        return
    _, _, (x0, y0, dx, dy, proj4) = data[0]
    transformer = Transformer.from_crs('EPSG:4326', CRS.from_proj4(proj4), always_xy=True)
    outlines = get_contours(transformer)
    # Grille de destination strictement en metres Lambert. Aucun axe Matplotlib
    # ni marge de figure : le recadrage Discord peut calculer des pixels exacts.
    xx = XMIN + (np.arange(WIDTH) + 0.5) * (XMAX-XMIN)/WIDTH
    yy = YMAX - (np.arange(HEIGHT) + 0.5) * (YMAX-YMIN)/HEIGHT
    cols = np.floor((xx-x0)/dx).astype(int)
    rows = np.floor((y0-yy)/dy).astype(int)
    xvalid = (cols>=0)&(cols<1536)
    yvalid = (rows>=0)&(rows<1536)
    cols = np.clip(cols, 0, 1535)
    rows = np.clip(rows, 0, 1535)
    within = yvalid[:, None] & xvalid[None, :]
    color_map = plt.get_cmap('turbo')
    colors = np.asarray([
        [int(round(c*255)) for c in color_map(i/255)[:3]]
        for i in range(256)], dtype=np.uint8)
    bg = np.array([235,241,245], dtype=np.uint8)
    # Petit tampon discret, lisible apres zoom Discord sans masquer les precipitations.
    # Les alertes de non-validation restent explicites dans le message Discord.
    warning_font = font(11)
    frames = []
    gaps = [
        (data[i+1][0]-data[i][0]).total_seconds()/60
        for i in range(len(data)-1)]
    for index,(stamp,grid,_) in enumerate(data):
        sampled = grid[np.ix_(rows,cols)]
        valid = within & np.isfinite(sampled) & (sampled>=5) & (sampled<=70)
        scaled = np.nan_to_num((sampled-5)*255/50, nan=0, posinf=255, neginf=0)
        indices = np.clip(scaled,0,255).astype(np.uint8)
        pixels = np.empty((HEIGHT,WIDTH,3),dtype=np.uint8)
        pixels[:]=bg
        pixels[valid] = colors[indices[valid]]
        im = Image.fromarray(pixels,'RGB')
        draw = ImageDraw.Draw(im)
        for outline in outlines:
            draw.line(outline,fill='#748a9b',width=1)
        # Un repere par zone, sans large bandeau qui masque la carte.
        # L'heure UTC varie avec chaque image du GIF.
        stamp_label = stamp.strftime('%H:%M')
        label = 'DIAG ' + stamp_label + 'Z'
        overlay = Image.new('RGBA', (WIDTH, HEIGHT), (0, 0, 0, 0))
        tag = ImageDraw.Draw(overlay)
        for y in range(50, HEIGHT, 215):
            for x in range(50, WIDTH, 215):
                tag.rounded_rectangle((x-5, y-3, x+91, y+15),
                                      radius=4, fill=(255, 248, 248, 135))
                tag.text((x, y), label, font=warning_font,
                         fill=(124, 25, 39, 205))
        im = Image.alpha_composite(im.convert('RGBA'), overlay).convert('RGB')
        frames.append(im)
    args.sortie.parent.mkdir(parents=True, exist_ok=True)
    durations = [max(150,min(3000,round(g*65))) for g in gaps]+[650]
    frames[0].save(args.sortie,save_all=True,append_images=frames[1:],
                   duration=durations,loop=0,optimize=True)
    # Conserver un manifeste explicite, sans jamais annoncer de validation.
    manifest = {
        'schema': 2,
        'mode': 'diagnostic',
        'projection_kind': 'stereographique_polaire_WGS84',
        'latitude_reference_deg': 45.0,
        'longitude_centrale_deg': 0.0,
        'georeferencement_valide': False,
        'diffusion_meteorologique_validee': False,
        'projection_proj4': proj4,
        'xmin': XMIN, 'xmax': XMAX, 'ymin': YMIN, 'ymax': YMAX,
        'width': WIDTH, 'height': HEIGHT,
        'rayon_km': RADIUS_KM,
        'observations_utc': [t.isoformat() for t,_,_ in data],
        'derniere_observation_utc': latest.isoformat(),
        'nombre_images': len(data),
        'intervalles_minutes': gaps,
        'gif': 'radar-atlas-diagnostic.gif',
        'centre_projection_lat_1':45.0,
        'centre_projection_lat_0':45.0,
        'centre_projection_lon_0':0.0,
    }
    args.manifest.write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8')
    make_city_marker(args.sortie.parent/'radar-marker.png')
    print('ATLAS DIAGNOSTIC:',args.sortie,'frames=',len(frames),
          'size=',WIDTH,'x',HEIGHT,'derniere=',latest.isoformat(),flush=True)

if __name__=='__main__':
    main()
