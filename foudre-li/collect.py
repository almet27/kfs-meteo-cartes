#!/usr/bin/env python3
"""KFS MÉTÉO — véritables éclairs optiques EUMETSAT MTG LI L2-LFL.

Lit des produits officiels (ZIP contenant un ou plusieurs BODY NetCDF).
Ne crée jamais de points fictifs. Ne publie rien si le téléchargement
ou le décodage échoue. Chaque produit LFL du Data Store couvre ~10 min.
Source: EO:EUM:DAT:0691 (NoConditions). Pas d'intensité ni d'impact CG.
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import math
import os
import re
import sys
import time
import zipfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

COLLECTION = "EO:EUM:DAT:0691"
SOURCE = "https://api.eumetsat.int/data/browse/collections/EO%3AEUM%3ADAT%3A0691?format=html"
WEST, SOUTH, EAST, NORTH = -7.5, 40.5, 10.0, 52.0
RETENTION_MINUTES = 120
MAX_POINTS = 20000
MAX_PRODUCTS = 50
MAX_PRODUCT_BYTES = 80000000
PRODUCT_TIME = re.compile(r"_OPE_(\d{14})_(\d{14})_")


def iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def as_utc(value) -> datetime:
    if isinstance(value, datetime):
        return (value if value.tzinfo else value.replace(tzinfo=timezone.utc)).astimezone(timezone.utc)
    # Cftime dates are not always Python datetime instances.
    return datetime(int(value.year), int(value.month), int(value.day),
                    int(value.hour), int(value.minute), int(value.second),
                    int(getattr(value, "microsecond", 0)), tzinfo=timezone.utc)


def product_ends(name: str) -> datetime | None:
    match = PRODUCT_TIME.search(name)
    if not match:
        return None
    return datetime.strptime(match.group(2), "%Y%m%d%H%M%S").replace(tzinfo=timezone.utc)


def inside_france_view(lon: float, lat: float) -> bool:
    return math.isfinite(lon) and math.isfinite(lat) and WEST <= lon <= EAST and SOUTH <= lat <= NORTH


def decode_body(content: bytes, product_name: str, body_index: int = 0) -> list[dict]:
    from netCDF4 import Dataset, num2date
    import numpy as np

    result = []
    with Dataset("LI-BODY", memory=content) as ds:
        for name in ("latitude", "longitude", "flash_time"):
            if name not in ds.variables:
                raise ValueError("Produit LFL : champ NetCDF manquant " + name)
        latitudes = ds.variables["latitude"][:]
        longitudes = ds.variables["longitude"][:]
        time_var = ds.variables["flash_time"]
        measured_times = time_var[:]
        if len(latitudes) != len(longitudes) or len(latitudes) != len(measured_times):
            raise ValueError("Produit LFL : tailles des dimensions incompatibles")
        units = getattr(time_var, "units", "seconds since 2000-01-01 00:00:00")
        calendar = getattr(time_var, "calendar", "standard")
        times = num2date(measured_times, units=units, calendar=calendar)
        digest = hashlib.sha256(product_name.encode("utf-8")).hexdigest()[:16]
        for i in range(len(latitudes)):
            if any(np.ma.is_masked(v) for v in
                   (latitudes[i], longitudes[i], measured_times[i])):
                continue
            lon, lat = float(longitudes[i]), float(latitudes[i])
            if not inside_france_view(lon, lat):
                continue
            try:
                measured = as_utc(times[i])
            except (ValueError, TypeError, OverflowError):
                continue
            result.append({
                "id": digest + ":" + str(body_index) + ":" + str(i),
                "lat": round(lat, 5), "lon": round(lon, 5),
                "ts": int(measured.timestamp()),
            })
    return result


def decode_product(blob: bytes, name: str) -> list[dict]:
    if not zipfile.is_zipfile(io.BytesIO(blob)):
        raise ValueError("Données EUMETSAT : produit ZIP attendu")
    found, points = 0, []
    with zipfile.ZipFile(io.BytesIO(blob)) as package:
        for info in package.infolist():
            filename = Path(info.filename).name.upper()
            if not filename.endswith(".NC") or "BODY" not in filename:
                continue
            if info.file_size > MAX_PRODUCT_BYTES:
                raise ValueError("Corps NetCDF trop volumineux")
            points.extend(decode_body(package.read(info), name, found))
            found += 1
    if found == 0:
        raise ValueError("Données EUMETSAT : aucun BODY NetCDF présent")
    return points


def read_previous(path: Path) -> dict:
    if not path.exists():
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("schema") != 1 or data.get("provider") != "EUMETSAT-MTG-LI-LFL":
        raise ValueError("Manifeste précédent de format inattendu")
    return data


def combine(previous: dict, decoded: list[dict], names: list[str],
            now: datetime) -> dict:
    cutoff = int((now - timedelta(minutes=RETENTION_MINUTES)).timestamp())
    latest = int(now.timestamp())
    by_id = {}
    for item in previous.get("flashes", []) + decoded:
        try:
            lat, lon, ts = float(item["lat"]), float(item["lon"]), int(item["ts"])
            ident = str(item["id"])
            if (cutoff <= ts <= latest + 20 and inside_france_view(lon, lat)
                    and 0 < len(ident) < 120):
                by_id[ident] = {"id": ident, "lat": round(lat, 5),
                                "lon": round(lon, 5), "ts": ts}
        except (KeyError, ValueError, TypeError):
            continue
    points = sorted(by_id.values(), key=lambda x: (x["ts"], x["id"]))
    truncated = len(points) > MAX_POINTS
    if truncated:
        points = points[-MAX_POINTS:]
    # Only recent product names are needed for deduplication across scans.
    names = sorted(set(previous.get("products_seen", [])) | set(names))
    names = [n for n in names
             if (product_ends(n) is not None and
                 product_ends(n) >= now - timedelta(hours=4))]
    last_ends = [v for v in
                 [previous.get("latest_product_end_utc")] +
                 [iso(e) for n in names if (e := product_ends(n))]]
    last_ends = [v for v in last_ends if v]
    return {
        "schema": 1, "provider": "EUMETSAT-MTG-LI-LFL",
        "state": "ready", "source": SOURCE, "updated_utc": iso(now),
        "latest_product_end_utc": max(last_ends) if last_ends else None,
        "retained_minutes": RETENTION_MINUTES,
        "area_wsen": [WEST, SOUTH, EAST, NORTH],
        "kind": "optical_lightning_flash_not_ground_impact",
        "truncated": truncated,
        "products_seen": names,
        "flashes": points
    }


def select_new(products, previous: dict) -> list:
    seen = set(previous.get("products_seen", []))
    new = [p for p in products if str(p) not in seen]
    if len(new) > MAX_PRODUCTS:
        raise RuntimeError("Trop de produits en attente ; pas de publication partielle")
    return sorted(new, key=str)


def download_one(product) -> bytes:
    for attempt in range(3):
        try:
            with product.open() as stream:
                data = stream.read(MAX_PRODUCT_BYTES + 1)
            if len(data) > MAX_PRODUCT_BYTES:
                raise ValueError("Produit LFL trop volumineux")
            return data
        except (OSError, ConnectionError, TimeoutError) as exc:
            if attempt == 2:
                raise RuntimeError("Téléchargement LFL impossible") from exc
            time.sleep(2 * (attempt + 1))
    raise RuntimeError("Téléchargement LFL impossible")


def run(output: Path, now: datetime | None = None, datastore=None) -> dict:
    now = now or datetime.now(timezone.utc)
    now = now.astimezone(timezone.utc)
    previous = read_previous(output)
    if datastore is None:
        key = os.environ.get("EUMETSAT_CONSUMER_KEY", "").strip()
        secret = os.environ.get("EUMETSAT_CONSUMER_SECRET", "").strip()
        if not key or not secret:
            raise RuntimeError("Clés EUMETSAT absentes. Configurer les deux secrets GitHub.")
        import eumdac
        datastore = eumdac.DataStore(eumdac.AccessToken((key, secret)))
    # Overlap slightly more than one product cycle to catch late publication.
    start = now - timedelta(hours=3)
    products = list(datastore.get_collection(COLLECTION).search(
        dtstart=start.replace(tzinfo=None),
        dtend=now.replace(tzinfo=None)))
    if not products:
        raise RuntimeError("Aucun produit LFL renvoyé : ancien relevé conservé")
    newer = select_new(products, previous)
    if not newer:
        print("Aucun nouveau produit satellitaire ; conserver la publication existante")
        return previous
    incoming = []
    names = []
    for product in newer:
        name = str(product)
        incoming.extend(decode_product(download_one(product), name))
        names.append(name)
        print("Décodé :", name[:100], flush=True)
    feed = combine(previous, incoming, names, now)
    # Atomic write: never replace an existing valid feed with a half-file.
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_suffix(".tmp")
    temporary.write_text(json.dumps(feed, ensure_ascii=False, separators=(",", ":")),
                         encoding="utf-8")
    temporary.replace(output)
    print("Publication : ", len(feed["flashes"]), "éclairs optiques ;",
          len(names), "produit(s) nouveaux ; fin de cycle",
          feed["latest_product_end_utc"], flush=True)
    return feed


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", default="foudre-li/flash-points.json")
    args = parser.parse_args()
    run(Path(args.out))


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print("ÉCHEC collecte EUMETSAT : " + str(exc), file=sys.stderr)
        raise SystemExit(1)
