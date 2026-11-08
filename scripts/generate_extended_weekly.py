#!/usr/bin/env python3
"""Retrieve real ECMWF Extended weekly charts for KFS /tendance.

Only a complete, licensed, current set of week-3/week-4 T2m and
precipitation anomaly PNGs can mark the manifest verified. Missing
charts must never be replaced with fictional or historical images.
"""
from __future__ import annotations

import hashlib
import io
import json
import re
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from PIL import Image

BASE = "https://charts.ecmwf.int"
API = BASE + "/opencharts-api/v1/products/"
DEST = Path("forecast-maps/tendance")
PUBLIC = "https://almet27.github.io/kfs-meteo-cartes/forecast-maps/tendance/"
TYPES = {
    "charts": {
        "t2m": ("extended-anomaly-2t", "weekly ensemble mean anomaly"),
        "precip": ("extended-anomaly-tp", "weekly ensemble mean anomaly"),
    },
    "probability_charts": {
        "t2m": ("extended-prob-anom-2t", "ensemble probability of anomaly"),
        "precip": ("extended-prob-anom-tp", "ensemble probability of anomaly"),
    },
    "synoptic_charts": {
        "mslp": ("extended-anomaly-mslp", "weekly ensemble mean anomaly"),
        "z500": ("extended-anomaly-z500", "weekly ensemble mean anomaly"),
    },
}
SUFFIX = {"charts": "", "probability_charts": "prob-", "synoptic_charts": ""}


def utc_iso(t: datetime) -> str:
    return t.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def fetch(url: str, expect_json=False):
    last = None
    for attempt in range(3):
        try:
            req = Request(url, headers={
                "User-Agent": "KFS-Meteo/1.0 (ECMWF chart provenance)",
                "Accept": "application/json" if expect_json else "image/png",
            })
            with urlopen(req, timeout=50) as response:
                raw = response.read(7 * 1024 * 1024)
                if len(raw) > 6 * 1024 * 1024:
                    raise ValueError("ECMWF response too large")
                return json.loads(raw) if expect_json else raw
        except (HTTPError, URLError, TimeoutError) as error:
            last = error
            if isinstance(error, HTTPError) and error.code in (400, 401, 403, 404):
                break
            if attempt < 2:
                time.sleep(2 + attempt * 3)
    raise RuntimeError("ECMWF download unavailable: " + str(last))


def png_valid(blob: bytes):
    if not 15000 <= len(blob) <= 6 * 1024 * 1024:
        raise ValueError("PNG size outside validated bounds")
    if not blob.startswith(b"\x89PNG\r\n\x1a\n"):
        raise ValueError("Not a PNG")
    with Image.open(io.BytesIO(blob)) as im:
        if im.format != "PNG" or min(im.size) < 350:
            raise ValueError("Invalid ECMWF chart dimensions")
        im.verify()


def chart(base_time: datetime, start: datetime, end: datetime,
          week: int, section: str, metric: str, product: str, chart_type: str):
    query = urlencode({
        "base_time": utc_iso(base_time),
        "valid_time": utc_iso(end),
        "projection": "opencharts_europe",
    })
    api_url = API + product + "/?" + query
    payload = fetch(api_url, expect_json=True)
    if not isinstance(payload, dict):
        raise ValueError("ECMWF returned malformed chart metadata")
    meta = payload.get("meta") or {}
    attrs = (payload.get("data") or {}).get("attributes") or {}
    link = (payload.get("data") or {}).get("link") or {}
    license_name = str(meta.get("license") or "")
    if license_name not in ("CC-BY-4.0", "CC BY 4.0"):
        raise ValueError("ECMWF reuse licence missing or unexpected")
    image_url = str(link.get("href") or "")
    if link.get("type") != "image/png" or not re.fullmatch(
            r"https://charts\.ecmwf\.int/content/[a-zA-Z0-9_-]+\.png",
            image_url):
        raise ValueError("ECMWF did not provide a trusted PNG URL")
    description = str(attrs.get("description") or "")
    if "Area: Europe" not in description:
        raise ValueError("ECMWF returned the wrong map area (expected Europe): " + description[:150])
    # Validate both WEEK boundaries and the issuing cycle, not just a remote image.
    for label in (base_time.strftime("%d %b %Y"),
                  start.strftime("%d %b %Y"),
                  end.strftime("%d %b %Y")):
        if label not in description:
            raise ValueError("ECMWF chart dates differ from requested week: " + description[:140])
    image = fetch(image_url)
    png_valid(image)
    filename = "weekly-week" + str(week) + "-" + SUFFIX[section] + metric + ".png"
    path = DEST / filename
    result = {
        "product": product,
        "file_path": str(path),
        "image_url": PUBLIC + filename,
        "ecmwf_content_url": image_url,
        "ecmwf_product_url": api_url,
        "description": description[:400],
        "size_bytes": len(image),
        "sha256": hashlib.sha256(image).hexdigest(),
        "chart_type": chart_type,
        "projection": "opencharts_europe",
        "map_area": "Europe",
        "valid_start_utc": utc_iso(start),
        "valid_end_utc": utc_iso(end),
    }
    return filename, image, result


def main():
    now = datetime.now(timezone.utc)
    if now.weekday() != 6:
        raise RuntimeError("Extended /tendance generation is reserved for Sunday")
    base_time = (now - timedelta(days=(now.weekday() - 3) % 7)).replace(
        hour=0, minute=0, second=0, microsecond=0)
    next_monday = base_time + timedelta(days=4)
    files = {}
    manifest = {
        "schema_version": 1,
        "verified": False,
        "generated_utc": utc_iso(now),
        "source": "ECMWF OpenCharts — Sub-seasonal ensemble weekly anomalies",
        "base_time_utc": utc_iso(base_time),
        "weeks": [3, 4],
        "temperature_anomalies_verified": False,
        "precipitation_anomalies_verified": False,
        "charts": {},
        "probability_charts": {},
        "synoptic_charts": {},
        "note": "Authentic ECMWF weekly products. Images are not numerical anomaly values or ensemble spread.",
        "copyright": "© ECMWF, CC BY 4.0; original image and product links retained per chart.",
        "alerts": [],
    }
    for week in (3, 4):
        start = next_monday + timedelta(days=7 * (week - 1))
        end = start + timedelta(days=7)
        for section, definitions in TYPES.items():
            for metric, (product, chart_type) in definitions.items():
                try:
                    filename, blob, record = chart(
                        base_time, start, end, week, section, metric, product, chart_type)
                    files[filename] = blob
                    manifest[section].setdefault(str(week), {})[metric] = record
                    print("Verified", filename, len(blob), flush=True)
                except Exception as exc:
                    msg = "Week %s %s/%s unavailable: %s" % (
                        week, section, metric, str(exc)[:160])
                    manifest["alerts"].append(msg)
                    print("::warning::" + msg, flush=True)

    core = manifest["charts"]
    t2m_ok = all(core.get(str(w), {}).get("t2m") for w in (3, 4))
    rain_ok = all(core.get(str(w), {}).get("precip") for w in (3, 4))
    manifest["temperature_anomalies_verified"] = bool(t2m_ok)
    manifest["precipitation_anomalies_verified"] = bool(rain_ok)
    manifest["verified"] = bool(t2m_ok and rain_ok)
    DEST.mkdir(parents=True, exist_ok=True)
    if not manifest["verified"]:
        # Replace previous manifest with explicit UNVERIFIED state:
        # old images may remain in the repository but cannot be published.
        manifest["charts"] = {}
        manifest["probability_charts"] = {}
        manifest["synoptic_charts"] = {}
        (DEST / "extended-weekly.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8")
        raise RuntimeError("Required official ECMWF week-3/4 anomalies not verified")

    # Only verified files are written, and the manifest is written LAST.
    for filename, content in files.items():
        (DEST / filename).write_bytes(content)
    manifest["generated_utc"] = utc_iso(datetime.now(timezone.utc))
    (DEST / "extended-weekly.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8")
    print("ECMWF Extended 3/4 verified, %d licensed PNGs" % len(files), flush=True)


if __name__ == "__main__":
    main()
