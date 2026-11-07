#!/usr/bin/env python3
"""Test non déployé : superposition EUMETView WMS GeoColour FCI et foudre LI AFA.

Les éclairs détectés par LI sont optiques, pas nécessairement des impacts au sol.
Sans horodatage confirmé, ne jamais présenter le résultat comme du temps réel.
"""
from datetime import datetime, timezone
from io import BytesIO
import json
from pathlib import Path
import urllib.error
import urllib.parse
import urllib.request
from PIL import Image, ImageDraw

BASE = "https://view.eumetsat.int/geoserver/wms"
LAYERS = ("mtg_fd:rgb_geocolour", "mtg_fd:li_afa")
WIDTH, HEIGHT = 840, 720
# WMS 1.3.0 EPSG:4326 => ordre lat_sud, lon_ouest, lat_nord, lon_est.
BBOX = "41,-6,52,10"
OUT = Path("mtg-li-preview")

def get_layer(layer):
    query = {
        "SERVICE": "WMS", "VERSION": "1.3.0", "REQUEST": "GetMap",
        "LAYERS": layer, "STYLES": "", "CRS": "EPSG:4326",
        "BBOX": BBOX, "WIDTH": str(WIDTH), "HEIGHT": str(HEIGHT),
        "FORMAT": "image/png", "TRANSPARENT": "TRUE",
    }
    url = BASE + "?" + urllib.parse.urlencode(query)
    request = urllib.request.Request(url, headers={
        "User-Agent": "KFS-Meteo-LI-WMS-Research/0.1", "Accept": "image/png"})
    try:
        with urllib.request.urlopen(request, timeout=65) as response:
            content_type = response.headers.get("Content-Type", "")
            data = response.read(9_000_001)
    except urllib.error.HTTPError as exc:
        raise RuntimeError("WMS " + layer + ": HTTP " + str(exc.code) +
                           " " + repr(exc.read(500))) from exc
    if not data.startswith(bytes.fromhex("89504e470d0a1a0a")):
        raise RuntimeError("WMS " + layer + ": réponse non PNG " +
                           content_type + " " + repr(data[:500]))
    if len(data) > 9_000_000:
        raise RuntimeError("Réponse WMS trop volumineuse")
    img = Image.open(BytesIO(data))
    img.load()
    if img.size != (WIDTH, HEIGHT):
        raise RuntimeError("Dimensions WMS inattendues: " + repr(img.size))
    return img.convert("RGBA")

def main():
    OUT.mkdir(parents=True, exist_ok=True)
    clouds = get_layer(LAYERS[0])
    lightning = get_layer(LAYERS[1])
    composite = Image.alpha_composite(clouds, lightning).convert("RGB")
    draw = ImageDraw.Draw(composite)
    draw.rectangle((0, 0, WIDTH, 45), fill=(10, 19, 32))
    draw.text((12, 12), "KFS METEO | Meteosat FCI + LI (test satellite + eclairs)", fill="white")
    draw.rectangle((0, HEIGHT-37, WIDTH, HEIGHT), fill=(10, 19, 32))
    draw.text((12, HEIGHT-26), "Images EUMETSAT / fond GeoColour NASA | TEST NON VALIDE", fill="white")
    composite.save(OUT / "satellite_foudre_test.png", optimize=True)
    meta = {
        "service": "EUMETView WMS", "created_utc": datetime.now(timezone.utc).isoformat(),
        "layers": list(LAYERS), "bbox_wms": BBOX, "crs": "EPSG:4326",
        "wms_layer_requests_ok": True, "actual_acquisition_time_verified": False,
        "not_for_publication": True,
        "note": "LI détecte des émissions optiques dans les nuages ; pas seulement des impacts au sol."
    }
    (OUT / "test_meta.json").write_text(
        json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(meta, ensure_ascii=False))

if __name__ == "__main__":
    main()
