#!/usr/bin/env python3
"""Discover public ECMWF Extended charts; do not infer or publish forecasts."""
import json
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

endpoint = "https://charts.ecmwf.int/opencharts-api/v1/products/"
out = Path("forecast-maps/tendance/extended-access.json")
out.parent.mkdir(parents=True, exist_ok=True)
report = {
    "checked_utc": datetime.now(timezone.utc).isoformat(),
    "api": endpoint,
    "matching_products": [],
    "verified_current_forecast": False,
    "note": "Product discovery only. Verify chart dates, licence, and data before publication."
}
try:
    req = urllib.request.Request(endpoint, headers={"User-Agent": "KFS-Meteo/1.0", "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=35) as r:
        products = json.load(r)
    if isinstance(products, dict):
        products = products.get("results", products.get("products", []))
    if not isinstance(products, list):
        raise ValueError("Unexpected response shape")
    for item in products:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name", item.get("title", "")))
        code = str(item.get("id", item.get("slug", "")))
        if any(s in (name + " " + code).lower() for s in ("extended", "sub-seasonal", "weekly", "anomaly")):
            report["matching_products"].append({
                "id": code,
                "name": name,
                "schema_url": item.get("schema-url"),
                "api_documentation": item.get("api-documentation")
            })
except Exception as exc:
    report["error"] = f"{type(exc).__name__}: {exc}"
out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
print(json.dumps(report, ensure_ascii=False, indent=2))
if not report["matching_products"]:
    raise SystemExit("No usable Extended product discovered; no forecast published")
