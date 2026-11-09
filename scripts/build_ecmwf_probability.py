#!/usr/bin/env python3
"""KFS MÉTÉO: ECMWF IFS-ENS open probabilistic products for Discord /proba.

Source: ECMWF Open Data, stream=enfo/type=ep. CC BY 4.0.
No Open-Meteo calls. Published percentages are used unchanged, no inferred
precipitation quantities or unsupported thresholds. Forecast periods 00-24,
24-48, 48-72, 72-96 hours after the 00Z analysis (UTC).
"""
from __future__ import annotations

import json
import math
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
import tempfile

import numpy as np
from scipy.spatial import cKDTree
from ecmwf.opendata import Client
from eccodes import codes_grib_new_from_file, codes_get, codes_get_array, codes_release

ROOT = Path(__file__).resolve().parents[1]
POINTS_FILE = ROOT / "proba" / "points-ecmwf.json"
OUTPUT_FILE = ROOT / "proba" / "ecmwf-probabilities.json"
PARAMS = ["tpg1", "tpg5", "tpg10", "tpg20", "10fgg15", "10fgg25"]
STEPS = ["0-24", "24-48", "48-72", "72-96"]
ECMWF_MIN_VALUES = 0.0
ECMWF_MAX_VALUES = 100.0


def collect_points(zones):
    rows = []
    ranges = {}
    for region, locations in zones.items():
        begin = len(rows)
        rows.extend((float(lat), float(lon)) for lat, lon in locations)
        ranges[region] = (begin, len(rows))
    return np.asarray(rows, dtype=np.float64), ranges


def nearest_grid_indices(grib, target_coords):
    lats = np.asarray(codes_get_array(grib, "latitudes"), dtype=np.float64)
    lons = np.asarray(codes_get_array(grib, "longitudes"), dtype=np.float64)
    lons = np.where(lons > 180, lons - 360, lons)
    mask = ((lats >= 40) & (lats <= 53) & (lons >= -7) & (lons <= 12))
    candidates = np.flatnonzero(mask)
    if len(candidates) < 100:
        raise RuntimeError("Grille ECMWF inattendue : aucune maille française")
    coslat = math.cos(math.radians(47))
    tree = cKDTree(np.column_stack((lats[candidates], lons[candidates] * coslat)))
    distance, positions = tree.query(
        np.column_stack((target_coords[:, 0], target_coords[:, 1] * coslat))
    )
    if np.max(distance) > 0.45:
        raise RuntimeError("Écart de localisation ECMWF supérieur à 0,45 degré")
    return candidates[positions], len(lats)


def read_products(grib_path: Path, coordinates: np.ndarray, slices):
    out = {}
    index = None
    expected_length = 0
    with grib_path.open("rb") as stream:
        while (message := codes_grib_new_from_file(stream)) is not None:
            try:
                key = str(codes_get(message, "shortName"))
                step = str(codes_get(message, "stepRange"))
                if key not in PARAMS or step not in STEPS:
                    continue
                values = np.asarray(codes_get_array(message, "values"), dtype=np.float64)
                if index is None:
                    index, expected_length = nearest_grid_indices(message, coordinates)
                if len(values) != expected_length:
                    raise RuntimeError(f"Grille incohérente sur {key}/{step}")
                samples = values[index]
                if not np.all(np.isfinite(samples)):
                    raise RuntimeError(f"Probabilités invalides pour {key}/{step}")
                if np.any(samples < ECMWF_MIN_VALUES - 0.01) or np.any(samples > ECMWF_MAX_VALUES + 0.01):
                    raise RuntimeError(f"Unité incohérente pour {key}/{step} : probabilités hors [0, 100]")
                out.setdefault(step, {})[key] = {
                    region: [round(float(x), 1) for x in samples[a:b]]
                    for region, (a, b) in slices.items()
                }
            finally:
                codes_release(message)
    return out


def main():
    config = json.loads(POINTS_FILE.read_text(encoding="utf-8"))
    coordinates, zones = collect_points(config["zones"])
    with tempfile.TemporaryDirectory() as folder:
        target = Path(folder) / "proba-ens.grib2"
        client = Client(source=os.getenv("ECMWF_SOURCE", "ecmwf"), model="ifs", resol="0p25")
        download = client.retrieve(
            time=0, stream="enfo", type="ep", step=STEPS,
            param=PARAMS, target=str(target)
        )
        run = download.datetime
        if run.tzinfo is None:
            run = run.replace(tzinfo=timezone.utc)
        run = run.astimezone(timezone.utc)
        if run.hour != 0:
            raise RuntimeError(f"Run ECMWF inattendu: {run}")
        if datetime.now(timezone.utc) - run > timedelta(hours=40):
            raise RuntimeError("Run ECMWF trop ancien (>40 h), ne pas publier")
        values = read_products(target, coordinates, zones)

    # Publier uniquement des journées complètes ; aucune probabilité inventée.
    expected = {(step, param) for step in STEPS for param in PARAMS}
    found = {(step, param) for step, data in values.items() for param in data}
    if missing := sorted(expected - found):
        raise RuntimeError(f"Paramètres ECMWF manquants ({len(missing)}): {missing[:10]}")

    product_days = {}
    for lead, step in enumerate(STEPS):
        day = (run + timedelta(days=lead)).strftime("%Y-%m-%d")
        product_days[day] = {
            "valid_from_utc": (run + timedelta(days=lead)).isoformat().replace("+00:00", "Z"),
            "valid_to_utc": (run + timedelta(days=lead + 1)).isoformat().replace("+00:00", "Z"),
            "fields": values[step],
        }

    out = {
        "schema": 1,
        "provider": "ECMWF IFS ENS Open Data",
        "source": "https://www.ecmwf.int/en/forecasts/datasets/open-data",
        "license": "CC BY 4.0",
        "generated_at_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "run_utc": run.isoformat().replace("+00:00", "Z"),
        "method": "Ensemble event probabilities (ECMWF native, type=ep); nearest 0.25 deg grid cell",
        "parameters": {
            "tpg1": {"phenomenon": "pluie", "threshold_mm": 1},
            "tpg5": {"phenomenon": "pluie", "threshold_mm": 5},
            "tpg10": {"phenomenon": "pluie", "threshold_mm": 10},
            "tpg20": {"phenomenon": "pluie", "threshold_mm": 20},
            "10fgg15": {"phenomenon": "vent", "threshold_kmh": 54},
            "10fgg25": {"phenomenon": "vent", "threshold_kmh": 90}
        },
        "zone_point_counts": {z: end - start for z, (start, end) in zones.items()},
        "days": product_days,
        "notice": "24-hour UTC forecast periods, not exact Paris-local calendar days. Rain events include total precipitation, which can include snow."
    }
    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_FILE.write_text(json.dumps(out, ensure_ascii=False, separators=(",", ":")) + "\n", encoding="utf-8")
    print(f"ECMWF ENS forecast {run.isoformat()} published: {len(product_days)} days, {len(zones)} zones, {OUTPUT_FILE.stat().st_size} bytes")


if __name__ == "__main__":
    main()
