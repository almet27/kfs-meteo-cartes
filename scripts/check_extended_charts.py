#!/usr/bin/env python3
"""Audit public ECMWF sub-seasonal chart products before using them in /tendance.

This does not infer weather from product availability and does not publish to Discord.
"""
import json
from datetime import datetime, timezone
from pathlib import Path
from urllib.request import Request, urlopen

API = "https://charts.ecmwf.int/opencharts-api/v1/"
OUT = Path("forecast-maps/tendance/extended-access.json")
OUT.parent.mkdir(parents=True, exist_ok=True)
TARGETS = {
    "temperature_2m": "extended-anomaly-2t",
    "precipitations": "extended-anomaly-tp",
    "temperature_surface": "extended-anomaly-t",
}
report = {
    "checked_utc": datetime.now(timezone.utc).isoformat(),
    "api": API,
    "forecast_ready": False,
    "products": {},
    "alerts": [],
    "note": "Product availability and metadata are not weather forecasts. Verify current issue date, chart times and reuse rights before publication."
}

def json_get(url):
    req = Request(url, headers={"User-Agent": "KFS-Meteo/1.0 (public source check)", "Accept": "application/json"})
    with urlopen(req, timeout=35) as response:
        return json.load(response)

try:
    data = json_get(API + "products/")
    if isinstance(data, dict):
        data = data.get("results", data.get("products", []))
    if not isinstance(data, list):
        raise ValueError("Unexpected ECMWF product index structure")
    index = {str(p.get("name", p.get("id", ""))): p for p in data if isinstance(p, dict)}
    for variable, name in TARGETS.items():
        item = index.get(name)
        status = {"product": name, "listed": item is not None, "schema_checked": False}
        if item:
            status["title"] = item.get("title", name)
            status["product_url"] = item.get("product-url", API + "products/" + name + "/")
            schema_url = item.get("schema-url")
            if schema_url:
                try:
                    schema = json_get(schema_url)
                    status["schema_checked"] = True
                    status["schema_type"] = type(schema).__name__
                    # Limit log size; include param names but not bulk reference data.
                    if isinstance(schema, dict):
                        status["schema_keys"] = list(schema)[:30]
                except Exception as exc:
                    status["schema_error"] = f"{type(exc).__name__}: {exc}"
        report["products"][variable] = status
    report["catalogue_count"] = len(index)
except Exception as exc:
    report["alerts"].append(f"Catalogue unavailable: {type(exc).__name__}: {exc}")

report["catalogue_ready"] = all(p.get("listed") for p in report["products"].values()) if report["products"] else False
if not report["catalogue_ready"]:
    report["alerts"].append("Temperature / precipitation product discovery incomplete.")
report["alerts"].append("No current forecast charts or ensemble fields retrieved; /tendance remains disabled.")
OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
print(json.dumps(report, ensure_ascii=False, indent=2))
if not report["catalogue_ready"]:
    raise SystemExit(1)
