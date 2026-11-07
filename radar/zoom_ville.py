#!/usr/bin/env python3
"""GIF radar local construit depuis les grilles BUFR, sans recadrage de PNG.
Georeferencement encore PROVISOIRE : diagnostic uniquement, pas de diffusion.
"""
import argparse
import io
import json
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np
from PIL import Image, ImageDraw
from pyproj import CRS, Transformer

FONDS = [
    ('departements', 'https://raw.githubusercontent.com/gregoiredavid/france-geojson/master/departements.geojson', '#a9b9c5', 0.55),
    ('pays', 'https://raw.githubusercontent.com/datasets/geo-countries/master/data/countries.geojson', '#455a6c', 1.0),
]

def radar_grid(path):
    with np.load(path, allow_pickle=False) as z:
        arr = np.asarray(z['reflectivite'], dtype=np.float32)
        x0, y0 = float(z['x0_m']), float(z['y0_m'])
        dx, dy = float(z['dx_m']), float(z['dy_m'])
        proj4 = str(z['proj4'].item())
        stamp = str(z['observation_utc'].item())
    if arr.ndim != 2 or arr.shape != (1536, 1536):
        raise ValueError(f'Grille invalide : {path}: {arr.shape}')
    if not all(np.isfinite((x0, y0, dx, dy))) or not (500 <= dx <= 2000 and 500 <= dy <= 2000):
        raise ValueError(f'Coordonnees ou resolution invalides : {path}')
    observation = datetime.fromisoformat(stamp.replace('Z', '+00:00'))
    if observation.tzinfo is None:
        raise ValueError(f'Observation sans fuseau : {path}')
    expected_name = 'radar-grid-' + observation.astimezone(timezone.utc).strftime('%Y-%m-%dT%H-%M-%SZ') + '.npz'
    if path.name != expected_name:
        raise ValueError(f'Horodatage incoherent : {path.name} vs {expected_name}')
    if not np.isfinite(arr).any():
        raise ValueError(f'Grille vide : {path}')
    return observation, arr, (x0, y0, dx, dy, proj4)

def add_outlines(ax, transformer, bounds):
    xmin, xmax, ymin, ymax = bounds
    loaded = []
    for title, url, color, width in FONDS:
        try:
            req = urllib.request.Request(url, headers={'User-Agent': 'KFS-radar-diagnostic/1.0'})
            with urllib.request.urlopen(req, timeout=16) as resp:
                payload = resp.read(9_000_001)
            if len(payload) > 9_000_000:
                raise ValueError('fond trop volumineux')
            features = json.loads(payload)['features']
        except (OSError, ValueError, KeyError) as exc:
            print(f'AVERTISSEMENT: fond {title} indisponible : {exc}', flush=True)
            continue
        drawn = 0
        for feature in features:
            g = feature.get('geometry') or {}
            parts = [g.get('coordinates') or []] if g.get('type') == 'Polygon' else (g.get('coordinates') or [] if g.get('type') == 'MultiPolygon' else [])
            for polygon in parts:
                for ring in polygon:
                    if len(ring) < 2:
                        continue
                    coordinates = np.asarray(ring, dtype=float)
                    if coordinates.ndim != 2 or coordinates.shape[1] < 2:
                        continue
                    xx, yy = transformer.transform(coordinates[:, 0], coordinates[:, 1])
                    if max(xx) < xmin or min(xx) > xmax or max(yy) < ymin or min(yy) > ymax:
                        continue
                    ax.plot(xx, yy, linewidth=width, color=color, alpha=0.87, zorder=3)
                    drawn += 1
        loaded.append(title)
        print(f'Fond {title} : {drawn} contours sur le cadrage', flush=True)
    return loaded

def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--dossier-grilles', required=True, type=Path)
    p.add_argument('--horodatages', required=True, type=Path)
    p.add_argument('--sortie', required=True, type=Path)
    p.add_argument('--ville', required=True)
    p.add_argument('--latitude', required=True, type=float)
    p.add_argument('--longitude', required=True, type=float)
    p.add_argument('--rayon-km', default=180, type=float)
    a = p.parse_args()
    if not (41 <= a.latitude <= 52 and -6 <= a.longitude <= 10 and 30 <= a.rayon_km <= 350):
        p.error('Coordonnees ou rayon hors limites')
    selected_times = json.loads(a.horodatages.read_text(encoding='utf-8'))
    if not isinstance(selected_times, list) or not 2 <= len(selected_times) <= 8:
        p.error('Horodatages invalides (2 a 8 attendus)')
    wanted = [datetime.fromisoformat(t.replace('Z', '+00:00')).astimezone(timezone.utc) for t in selected_times]
    if wanted != sorted(set(wanted)):
        p.error('Horodatages non tries ou dupliques')
    data = []
    for time in wanted:
        name = 'radar-grid-' + time.strftime('%Y-%m-%dT%H-%M-%SZ') + '.npz'
        path = a.dossier_grilles / name
        if not path.is_file():
            print(f'GRILLE ABSENTE : {name} (ancienne acquisition sans export des donnees)', flush=True)
            continue
        observation, arr, geo = radar_grid(path)
        if observation != time:
            raise ValueError(f'Observation et horodatage divergent : {name}')
        if data and geo != data[0][2]:
            raise ValueError(f'Geometrie incoherente entre acquisitions : {name}')
        if data and (time - data[-1][0]).total_seconds() > 1500:
            data = []  # Pas de zoom a partir de grilles discontinues.
        data.append((time, arr, geo))
    if len(data) < 2:
        print('ZOOM NON GENERE : moins de 2 grilles continues. Le GIF national reste disponible.', flush=True)
        return
    time, arr, (x0, y0, dx, dy, proj4) = data[0]
    transform = Transformer.from_crs('EPSG:4326', CRS.from_proj4(proj4), always_xy=True)
    xc, yc = transform.transform(a.longitude, a.latitude)
    if not (x0 <= xc <= x0 + arr.shape[1]*dx and y0 - arr.shape[0]*dy <= yc <= y0):
        raise ValueError('Commune hors grille radar')
    radius = a.rayon_km * 1000
    bounds = (xc-radius, xc+radius, yc-radius, yc+radius)
    fig, ax = plt.subplots(figsize=(6, 6), dpi=120)
    fig.subplots_adjust(left=0, right=1, top=1, bottom=0)
    ax.set_facecolor('#eaf0f4')
    cmap = plt.get_cmap('turbo').copy()
    cmap.set_bad((0, 0, 0, 0))
    def masked(v):
        return np.ma.masked_where(~(np.isfinite(v) & (v >= 5) & (v <= 70)), v)
    artist = ax.imshow(masked(arr), origin='upper',
                       extent=(x0, x0+arr.shape[1]*dx, y0-arr.shape[0]*dy, y0),
                       vmin=5, vmax=55, cmap=cmap, interpolation='nearest', alpha=0.83, zorder=2)
    fond = add_outlines(ax, transform, bounds)
    ax.plot([xc], [yc], marker='+', color='white', markeredgewidth=2.2, markersize=17, zorder=6)
    ax.plot([xc], [yc], marker='+', color='#e11d48', markeredgewidth=1.1, markersize=17, zorder=7)
    ax.set_xlim(bounds[0], bounds[1]); ax.set_ylim(bounds[2], bounds[3])
    ax.set_aspect('equal'); ax.axis('off')
    frames = []
    gaps = [(data[i+1][0]-data[i][0]).total_seconds()/60 for i in range(len(data)-1)]
    for index, (stamp, values, _) in enumerate(data):
        artist.set_data(masked(values))
        stream = io.BytesIO()
        fig.savefig(stream, format='png', dpi=120)
        stream.seek(0)
        with Image.open(stream) as png:
            frame = png.convert('RGB')
        draw = ImageDraw.Draw(frame)
        draw.rectangle((0, 0, 720, 65), fill='#152536')
        draw.text((17, 11), f'Radar {a.ville[:65]} - rayon {a.rayon_km:g} km', fill='white')
        draw.text((17, 37), stamp.strftime('%d/%m/%Y %H:%M UTC'), fill='#f1f5f9')
        if index < len(gaps) and gaps[index] > 15:
            draw.rectangle((0, 650, 720, 690), fill='#9a3412')
            draw.text((15, 663), f'TROU : prochaine observation dans {gaps[index]:g} min', fill='white')
        draw.rectangle((0, 690, 720, 720), fill='#8b1723')
        draw.text((15, 699), 'GEOGRAPHIE NON VALIDEE - DIAGNOSTIC UNIQUEMENT', fill='white')
        frames.append(frame)
    plt.close(fig)
    a.sortie.parent.mkdir(parents=True, exist_ok=True)
    durations = [max(150, min(3000, round(650 * gap / 10))) for gap in gaps] + [650]
    frames[0].save(a.sortie, save_all=True, append_images=frames[1:],
                   duration=durations, loop=0, optimize=True)
    metadata = {
        'ville': a.ville, 'latitude': a.latitude, 'longitude': a.longitude,
        'rayon_km': a.rayon_km, 'observations_utc': [d[0].isoformat() for d in data],
        'fonds_charges': fond, 'geo_source': 'BUFR hypothese Lambert non validee',
        'intervalles_minutes': gaps, 'lacunes_signalees': [g for g in gaps if g > 15],
        'diffusion_discord_autorisee': False,
    }
    a.sortie.with_suffix('.json').write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding='utf-8')
    print(f'ZOOM DIAGNOSTIC : {a.sortie}, {len(frames)} images', flush=True)

if __name__ == '__main__':
    main()
