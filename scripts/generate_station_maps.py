#!/usr/bin/env python3
"""Cartes KFS Météo : observations de stations Météo-France, sans images Météociel.

Variables : METEOFRANCE_BASIC_AUTH (valeur Base64 seule, sans le préfixe 'Basic ').
Une erreur d'API arrête la publication : aucune carte fictive n'est produite.
"""
from __future__ import annotations
import argparse
import json
import math
import os
import pathlib
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone

API = "https://public-api.meteofrance.fr/public/DPPaquetObs/v2/paquet/stations"
TOKEN_URL = "https://portail-api.meteofrance.fr/token"
BOUNDARIES_URL = ("https://raw.githubusercontent.com/gregoiredavid/"
                  "france-geojson/master/regions-version-simplifiee.geojson")
OUT = pathlib.Path("station-maps")
METRICS = {
    "temperature": ("Températures observées", "°C", "coolwarm"),
    "tmax": ("Températures maximales / 24 h", "°C", "coolwarm"),
    "tmin": ("Températures minimales / 24 h", "°C", "coolwarm"),
    "vent": ("Vent moyen observé", "km/h", "YlGnBu"),
    "rafales": ("Dernières rafales horaires", "km/h", "inferno"),
    "rafalesmax": ("Rafales maximales / 24 h", "km/h", "inferno"),
    "pluie": ("Cumul de pluie / 24 h", "mm", "turbo"),
}
# Zones historiques de la commande Discord. Coordonnées : ouest, est, sud, nord.
ZONES = {
    "fr": ("France entière", (-5.8, 10.0, 41.1, 51.6)),
    "no": ("Nord-Ouest", (-5.8, 3.0, 45.8, 51.6)),
    "ne": ("Nord-Est", (1.5, 8.5, 45.8, 51.6)),
    "so": ("Sud-Ouest", (-5.8, 3.3, 41.0, 47.8)),
    "se": ("Sud-Est", (2.5, 10.0, 41.0, 47.9)),
    "rp": ("Région parisienne", (1.2, 3.6, 47.8, 49.4)),
    "r14": ("Normandie", (-2.25, 1.95, 48.1, 50.2)),
    "r4": ("Bretagne", (-5.25, -0.8, 47.15, 49.3)),
    "r1": ("Hauts-de-France", (-0.05, 4.35, 48.95, 51.3)),
    "r3": ("Île-de-France", (1.3, 3.6, 47.9, 49.3)),
    "r5": ("Pays de la Loire", (-2.7, 0.95, 46.1, 48.9)),
    "r12": ("Centre-Val de Loire", (-0.3, 3.6, 46.2, 48.9)),
    "r2": ("Grand Est", (3.05, 8.45, 47.2, 50.4)),
    "r13": ("Bourgogne-Franche-Comté", (2.6, 7.3, 45.6, 48.6)),
    "r11": ("Auvergne-Rhône-Alpes", (2.35, 7.8, 43.8, 46.9)),
    "r6": ("Nouvelle-Aquitaine Nord", (-2.3, 2.0, 45.35, 47.7)),
    "r7": ("Nouvelle-Aquitaine Sud", (-2.4, 1.8, 42.55, 45.6)),
    "r8": ("Occitanie", (-0.8, 4.95, 42.2, 45.2)),
    "r9": ("Provence-Alpes-Côte d'Azur", (4.45, 7.9, 42.85, 45.25)),
    "r10": ("Corse", (8.45, 9.8, 41.3, 43.15)),
    # Le réseau de Météo-France ne couvre pas l'ensemble de l'Europe.
    "eur2": ("Europe (stations françaises uniquement)", (-11.0, 17.0, 36.0, 55.0)),
}


def http_json(url, headers=None, body=None, retries=3):
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, data=body, headers=headers or {})
            with urllib.request.urlopen(req, timeout=90) as response:
                data = response.read()
            return json.loads(data)
        except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError,
                json.JSONDecodeError) as exc:
            if attempt == retries - 1:
                raise RuntimeError(f"Accès impossible : {url.split('?')[0]} : {exc}") from exc
            time.sleep(2 * (attempt + 1))


def token():
    encoded = os.environ.get("METEOFRANCE_BASIC_AUTH", "").strip()
    if not encoded or encoded.lower().startswith("basic "):
        raise RuntimeError("Secret METEOFRANCE_BASIC_AUTH manquant ou incorrect")
    answer = http_json(TOKEN_URL, {
        "Authorization": "Basic " + encoded,
        "Content-Type": "application/x-www-form-urlencoded",
        "Accept": "application/json",
    }, b"grant_type=client_credentials")
    access = answer.get("access_token")
    if not access:
        raise RuntimeError("Réponse OAuth2 sans access_token")
    return access


def obs(token_value, period="infrahoraire-6m", date=None):
    query = {"format": "geojson"}
    if not date:
        # Version 2 : paramètre date obligatoire, pas de date future, pas de minute arbitraire.
        snapshot = datetime.now(timezone.utc) - timedelta(minutes=18)
        snapshot = snapshot.replace(minute=(snapshot.minute // 6) * 6,
                                    second=0, microsecond=0)
        date = snapshot.strftime("%Y-%m-%dT%H:%M:%SZ")
    query["date"] = date
    url = API + "/" + period + "?" + urllib.parse.urlencode(query)
    response = http_json(url, {"Authorization": "Bearer " + token_value,
                               "Accept": "application/json"})
    if isinstance(response, list):
        features = response
    elif isinstance(response, dict) and response.get("type") == "FeatureCollection":
        features = response.get("features", [])
    elif isinstance(response, dict) and "features" in response:
        features = response["features"]
    else:
        raise RuntimeError(f"Format de GeoJSON inconnu : {type(response)}")
    return [item for item in features
            if isinstance(item, dict) and item.get("geometry", {}).get("type") == "Point"]


def as_number(value):
    if value is None or isinstance(value, bool):
        return None
    try:
        v = float(value)
        return v if math.isfinite(v) else None
    except (TypeError, ValueError):
        return None


def kelvin(value):
    n = as_number(value)
    return round(n - 273.15, 1) if n is not None and 180 < n < 350 else None


def kmh(value):
    n = as_number(value)
    return round(n * 3.6, 1) if n is not None and 0 <= n < 150 else None


def station_id(feature):
    p = feature["properties"]
    coords = feature["geometry"]["coordinates"]
    return str(p.get("geo_id_insee") or (round(coords[0], 4), round(coords[1], 4)))


def stations(features):
    result = {}
    for feature in features:
        try:
            coords = feature["geometry"]["coordinates"]
            lon, lat = float(coords[0]), float(coords[1])
            if not (-6.5 <= lon <= 10.2 and 41 <= lat <= 52):
                continue  # Métropole uniquement ; zones régionales existantes.
            key = station_id(feature)
            result[key] = (lon, lat, feature["properties"])
        except (ValueError, TypeError, KeyError, IndexError):
            continue
    return result


def aggregate_hourly(samples):
    data = {}
    for snapshot in samples:
        for key, (_, _, props) in stations(snapshot).items():
            s = data.setdefault(key, {
                "tx": None, "tn": None, "gust": None,
                "rain": 0.0, "rain_count": 0, "temp_count": 0
            })
            t = kelvin(props.get("t"))
            if t is not None:
                s["tx"] = t if s["tx"] is None else max(t, s["tx"])
                s["tn"] = t if s["tn"] is None else min(t, s["tn"])
                s["temp_count"] += 1
            gust = kmh(props.get("fxi", props.get("fxy")))
            if gust is not None:
                s["gust"] = gust if s["gust"] is None else max(gust, s["gust"])
            rain = as_number(props.get("rr1"))
            if rain is not None and 0 <= rain <= 400:
                s["rain"] += rain
                s["rain_count"] += 1
    return data


def map_values(current, hourly, latest_hourly=None):
    values = {k: [] for k in METRICS}
    latest_hourly = latest_hourly or {}
    for sid, (lon, lat, p) in current.items():
        temp = kelvin(p.get("t"))
        wind = kmh(p.get("ff"))
        recent_hour = latest_hourly.get(sid, (None, None, {}))[2]
        # Le paquet 6 minutes n'offre pas toujours de rafale ; utilise la dernière heure mesurée.
        gust = kmh(p.get("fxi10"))
        if gust is None:
            gust = kmh(recent_hour.get("fxi", recent_hour.get("fxy")))
        day = hourly.get(sid, {})
        entries = {
            "temperature": temp, "vent": wind, "rafales": gust,
            "tmax": day.get("tx") if day.get("temp_count", 0) >= 16 else None,
            "tmin": day.get("tn") if day.get("temp_count", 0) >= 16 else None,
            "rafalesmax": day.get("gust") if day.get("temp_count", 0) >= 16 else None,
            "pluie": round(day["rain"], 1) if day.get("rain_count", 0) >= 20 else None,
        }
        for metric, val in entries.items():
            if val is not None:
                values[metric].append((lon, lat, val))
    return values


def polygons(geojson):
    for feature in geojson.get("features", []):
        geometry = feature.get("geometry", {})
        typ, coord = geometry.get("type"), geometry.get("coordinates", [])
        if typ == "Polygon":
            for ring in coord:
                yield ring
        elif typ == "MultiPolygon":
            for polygon in coord:
                for ring in polygon:
                    yield ring


def render(metric, zone, records, shapes, timestamp, hours):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.colors import Normalize
    from PIL import Image
    title, unit, palette = METRICS[metric]
    area, bounds = ZONES[zone]
    x0, x1, y0, y1 = bounds
    points = [p for p in records if x0 <= p[0] <= x1 and y0 <= p[1] <= y1]
    # France entiere : un format quasi carre exploite beaucoup mieux l'espace.
    # Les quatre secteurs conservent leur cadrage vertical specifique.
    # Les autres zones conservent leur format horizontal.
    france_zone = zone == "fr"
    quadrant_zone = zone in ("no", "ne", "so", "se")
    figure_size = ((11.5, 11.5) if france_zone else
                   (9.2, 12.8) if quadrant_zone else (12.8, 8.5))
    fig, ax = plt.subplots(figsize=figure_size, dpi=150)
    fig.patch.set_facecolor("#101927")
    ax.set_facecolor("#172538")
    for ring in shapes:
        xs, ys = zip(*ring)
        ax.plot(xs, ys, color="#4a6073", lw=.65, alpha=.72, zorder=1)
    # Les zones etroites profitent de valeurs plus lisibles ; sur la France entiere,
    # des etiquettes legerement reduites evitent la superposition.
    wide_zone = zone in ("fr", "no", "ne", "so", "se", "eur2")
    label_size = 11.0 if wide_zone else 13.5
    grid_cols, grid_rows = (27, 18) if wide_zone else (19, 13)
    if points:
        xs, ys, nums = list(zip(*points))
        low, high = min(nums), max(nums)
        if low == high:
            low -= 1
            high += 1
        colors = plt.get_cmap(palette)
        normalized = Normalize(vmin=low, vmax=high)
        ax.scatter(xs, ys, c=nums, s=24, cmap=colors,
                   norm=normalized, alpha=.76, linewidths=0, zorder=2)
        occupied = set()
        for lon, lat, val in sorted(points, key=lambda x: abs(x[2]), reverse=True):
            cell = (int((lon - x0) / (x1 - x0) * grid_cols),
                    int((lat - y0) / (y1 - y0) * grid_rows))
            if cell in occupied:
                continue
            occupied.add(cell)
            label = f"{val:.0f}" if metric != "pluie" else f"{val:.1f}"
            ax.text(lon, lat, label, color="white", fontsize=label_size, fontweight="bold",
                    ha="center", va="center", zorder=4,
                    bbox={"boxstyle":"round,pad=0.20",
                          "facecolor":"#0b1524","edgecolor":"#495b6c",
                          "linewidth":.5,"alpha":.96})
        cb = fig.colorbar(plt.cm.ScalarMappable(norm=normalized, cmap=colors),
                          ax=ax, orientation="horizontal", fraction=.047, pad=.07,
                          aspect=35)
        cb.set_label(unit, color="#dee7f5", fontsize=13)
        cb.ax.tick_params(colors="#bfc8d9", labelsize=11)
    else:
        ax.text(.5, .5, "Aucune mesure disponible sur cette zone",
                transform=ax.transAxes, ha="center", va="center",
                fontsize=16, color="white")
    ax.set_xlim(x0, x1)
    ax.set_ylim(y0, y1)
    ax.set_aspect(1 / max(.25, math.cos(math.radians((y0 + y1)/2))))
    ax.tick_params(labelbottom=False, labelleft=False, bottom=False, left=False)
    for side in ax.spines.values():
        side.set_color("#405168")
    fig.text(.055, .94, "KFS MÉTÉO  /  OBSERVATIONS", color="#65d8f7",
             weight="bold", fontsize=17)
    fig.text(.055, .89, title + " — " + area, color="white",
             weight="bold", fontsize=17)
    footer = (f"Stations : {len(points)} · mesure {timestamp} UTC"
              + (f" · {hours} relevés horaires reçus" if metric in ("tmax","tmin","rafalesmax","pluie") else ""))
    fig.text(.055, .04, footer, color="#cfdae9", fontsize=10.5)
    fig.text(.055, .016, "Source : Météo-France · Contours : IGN / Admin Express (Licence Ouverte)",
             color="#8da2b8", fontsize=9.5)
    if quadrant_zone or france_zone:
        # Maximiser la carte sans rogner le bandeau ni le pied.
        fig.subplots_adjust(left=.035, right=.975, top=.86, bottom=.105)
        if points:
            # La legende doit avoir la MEME largeur que la carte visible.
            # Par defaut Matplotlib lui laisse toute la largeur du canevas.
            fig.canvas.draw()
            map_box = ax.get_position()
            scale_box = cb.ax.get_position()
            cb.ax.set_axes_locator(None)
            cb.ax.set_position((map_box.x0, scale_box.y0,
                                map_box.width, scale_box.height))
    else:
        fig.subplots_adjust(left=.035, right=.975, top=.85, bottom=.13)
    OUT.mkdir(exist_ok=True)
    dest = OUT / f"{zone}-{metric}.png"
    fig.savefig(dest, facecolor=fig.get_facecolor(), dpi=150)
    plt.close(fig)
    # Palette PNG : alléger l'actualisation sans dégrader les valeurs textuelles.
    with Image.open(dest) as img:
        img.convert("RGB").quantize(colors=128).save(dest, format="PNG", optimize=True)
    return len(points)


def test():
    sample = [{
        "type": "Feature",
        "geometry": {"type":"Point","coordinates":[1.2,49.2]},
        "properties": {"geo_id_insee":"27000001","t":282.15,"ff":2.5,
                       "fxi10":7,"fxi":9,"rr1":1.5}
    }]
    s = stations(sample)
    assert len(s) == 1 and kelvin(282.15) == 9
    hourly = aggregate_hourly([sample] * 24)
    values = map_values(s, hourly, stations(sample))
    assert values["temperature"][0][2] == 9
    assert values["vent"][0][2] == 9
    assert values["pluie"][0][2] == 36
    assert values["tmax"][0][2] == 9
    assert values["rafales"][0][2] == 25.2
    assert values["rafalesmax"][0][2] == 32.4
    print("Self-test: conversions, cumul 24 h, maximum et 7 mesures OK")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--self-test", action="store_true")
    args = ap.parse_args()
    if args.self_test:
        test()
        return
    auth = token()
    current_features = obs(auth)
    current = stations(current_features)
    if len(current) < 100:
        raise RuntimeError(f"Trop peu de stations : {len(current)}. Aucune publication.")
    validities = [p.get("validity_time") for _, _, p in current.values()
                  if p.get("validity_time")]
    now = datetime.now(timezone.utc)
    latest = max(validities) if validities else now.isoformat()
    try:
        observation_time = datetime.fromisoformat(latest.replace("Z","+00:00"))
        if now - observation_time > timedelta(minutes=90):
            raise RuntimeError("Observations de plus de 90 minutes : publication annulée")
    except ValueError:
        observation_time = now
    # Échantillonnage 24 h : les relevés horaires sont disponibles vers H+10.
    end_hour = (now - timedelta(minutes=18)).replace(minute=0, second=0, microsecond=0)
    hourly_samples = []
    for i in range(24):
        date = (end_hour - timedelta(hours=i)).strftime("%Y-%m-%dT%H:%M:%SZ")
        try:
            hourly_samples.append(obs(auth, period="horaire", date=date))
        except RuntimeError as error:
            print(f"INFO observation horaire indisponible {date}: {error}", file=sys.stderr)
        time.sleep(.12)
    aggregated = aggregate_hourly(hourly_samples)
    last_hourly = stations(hourly_samples[0]) if hourly_samples else {}
    values = map_values(current, aggregated, last_hourly)
    if not values["temperature"]:
        raise RuntimeError("Aucune température valide : ne pas publier.")
    if not values["rafales"]:
        raise RuntimeError("Aucune rafale récente : ne pas publier une carte vide.")
    boundaries = http_json(BOUNDARIES_URL)
    rings = list(polygons(boundaries))
    if not rings:
        raise RuntimeError("Fond de carte absent")
    stations_count = {}
    for zone in ZONES:
        stations_count[zone] = {}
        for metric in METRICS:
            stations_count[zone][metric] = render(
                metric, zone, values[metric], rings,
                observation_time.strftime("%Y-%m-%d %H:%M"),
                len(hourly_samples))
    metadata = {
        "generated_utc": now.isoformat().replace("+00:00","Z"),
        "observation_utc": observation_time.isoformat().replace("+00:00","Z"),
        "source": "Météo-France / API Package Observations",
        "hourly_snapshots": len(hourly_samples),
        "metric_details": {k: v[0] for k, v in METRICS.items()},
        "stations": stations_count,
        "zones": {k:v[0] for k,v in ZONES.items()},
        "note": "Maximum/minimum/cumuls calculés sur les relevés disponibles. Une station peut être exclue si ses relevés sont incomplets."
    }
    (OUT/"manifest.json").write_text(json.dumps(metadata, ensure_ascii=False, indent=2),
                                       encoding="utf-8")
    print(f"Cartes créées : {len(ZONES)*len(METRICS)}; stations={len(current)}; "
          f"horaires={len(hourly_samples)}; mesure={latest}")

if __name__ == "__main__":
    main()
