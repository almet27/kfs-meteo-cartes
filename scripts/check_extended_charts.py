#!/usr/bin/env python3
"""Audit public ECMWF sub-seasonal chart products before using them in /tendance.

This does not infer weather from product availability and does not publish to Discord.
"""
import json
from datetime import datetime, timezone
from pathlib import Path
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError

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
except HTTPError as exc:
    report["endpoint_status"] = int(exc.code)
    report["access_state"] = "unavailable_http"
    report["alerts"].append(
        f"ECMWF OpenCharts API inaccessible depuis GitHub (HTTP {exc.code}). "
        "Cela ne prouve pas l'absence du produit meteorologique."
    )
except URLError as exc:
    report["access_state"] = "network_error"
    report["alerts"].append(f"ECMWF OpenCharts API inaccessible: {exc.reason}")
except Exception as exc:
    report["access_state"] = "unexpected_response"
    report["alerts"].append(f"Catalogue indisponible: {type(exc).__name__}: {exc}")

# Autre vérification indépendante : tentatives ciblées des produits
# hebdomadaires sur le dernier cycle sub-saisonnier disponible (jeudi 00 UTC).
# Ne déclare jamais "verified" sans graphique réellement obtenu, licence
# et horodatages validés. Les HTTP 404/403 restent un diagnostic d'accès.
from datetime import timedelta
from urllib.parse import urlencode
now=datetime.now(timezone.utc)
days_since_thu=(now.weekday()-3)%7
recent_thu=(now-timedelta(days=days_since_thu)).replace(hour=0,minute=0,second=0,microsecond=0)
next_monday=recent_thu+timedelta(days=4)
dates={
    3:(next_monday+timedelta(days=21)).strftime("%Y-%m-%dT%H:%M:%SZ"),
    4:(next_monday+timedelta(days=28)).strftime("%Y-%m-%dT%H:%M:%SZ"),
}
base_time=recent_thu.strftime("%Y-%m-%dT%H:%M:%SZ")
report["weekly_probe"]={"base_time":base_time,
                        "valid_time_by_week":dates,
                        "responses":{}}
for week in (3,4):
    for var,product in (("t2m","extended-anomaly-2t"),("precip","extended-anomaly-tp")):
        qs=urlencode({"base_time":base_time,
                      "valid_time":dates[week],
                      "projection":"opencharts_eurasia"})
        endpoint=API+"products/"+product+"/?"+qs
        entry={"product":product,"base_time":base_time,"valid_time":dates[week],
               "url":endpoint,"image_verified":False}
        try:
            response=json_get(endpoint)
            meta=response.get("meta",{})
            link=response.get("data",{}).get("link",{})
            attributes=response.get("data",{}).get("attributes",{})
            entry.update({"license":meta.get("license"),
                          "chart_url":link.get("href"),
                          "description":attributes.get("description","")[:350],
                          "returned_type":link.get("type")})
            if (link.get("type")=="image/png" and
                link.get("href","").startswith("https://charts.ecmwf.int/content/") and
                meta.get("license") in ("CC-BY-4.0","CC BY 4.0")):
                entry["metadata_validated"]=True
        except HTTPError as exc:
            entry["http_status"]=int(exc.code)
        except Exception as exc:
            entry["error"]=f"{type(exc).__name__}: {str(exc)[:200]}"
        report["weekly_probe"]["responses"][f"week{week}_{var}"]=entry

report["catalogue_ready"] = all(p.get("listed") for p in report["products"].values()) if report["products"] else False
if not report["catalogue_ready"]:
    report["alerts"].append("Temperature / precipitation product discovery incomplete.")
report["alerts"].append("No current forecast charts or ensemble fields retrieved; /tendance remains disabled.")
OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
print(json.dumps(report, ensure_ascii=False, indent=2))
if not report["catalogue_ready"]:
    print("::warning::ECMWF Extended non disponible via API; aucune tendance a 4 semaines ne sera publiee.")
