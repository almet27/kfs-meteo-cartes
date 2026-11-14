#!/usr/bin/env python3
"""Validation prudente : un seul point EC46, sans publication ni Discord."""
import json
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from urllib.error import HTTPError

OUT = Path("meteo-mois-validation")
ENDPOINT = "https://seasonal-api.open-meteo.com/v1/seasonal"
VARS = [
    "pressure_msl_mean", "pressure_msl_anomaly",
    "wind_u_component_10m_mean", "wind_v_component_10m_mean",
    "temperature_2m_anomaly", "temperature_2m_mean",
    "precipitation_anomaly",
]
params = {
    "latitude": 48.85, "longitude": 2.35,
    "models": "ecmwf_seasonal_ensemble_mean_seamless",
    "timezone": "GMT", "forecast_days": 45,
    "weekly": ",".join(VARS),
}

def main():
    OUT.mkdir(parents=True, exist_ok=True)
    req = Request(ENDPOINT + "?" + urlencode(params), headers={
        "User-Agent": "KFS-Meteo-EC46-Validation/1.0",
        "Accept": "application/json",
    })
    try:
        with urlopen(req, timeout=75) as response:
            data = json.load(response)
    except HTTPError as exc:
        error_body = exc.read(700).decode("utf-8", errors="replace")
        raise RuntimeError(f"API HTTP {exc.code}: {error_body}") from exc

    if isinstance(data, list):
        assert len(data) == 1, "Nombre de points inattendu"
        data = data[0]
    if data.get("error"):
        raise RuntimeError(data.get("reason", "Erreur Open-Meteo"))
    weekly = data.get("weekly") or {}
    times = weekly.get("time") or []
    if len(times) < 4:
        raise RuntimeError(f"Semaines manquantes : {times!r}")
    lengths = {}
    for key in VARS:
        vals = weekly.get(key)
        if not isinstance(vals, list) or len(vals) != len(times):
            raise RuntimeError(f"Variable {key}: indisponible ou longueur incorrecte")
        lengths[key] = sum(isinstance(v, (int, float)) for v in vals)
    report = {
        "verified_utc": datetime.now(timezone.utc).isoformat(),
        "status": "sample_only_not_a_map",
        "source": "Open-Meteo seasonal ECMWF ensemble mean seamless",
        "point": {"latitude": 48.85, "longitude": 2.35},
        "weekly_units": data.get("weekly_units"),
        "weeks": times[:6],
        "variables_nonnull_counts": lengths,
        "first_week_values": {k: weekly[k][0] for k in VARS},
        "publication": False,
    }
    (OUT / "diagnostic.json").write_text(
        json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    print(json.dumps(report, ensure_ascii=False))
    if not all(n >= 4 for n in lengths.values()):
        raise RuntimeError("Données hebdomadaires trop incomplètes pour tracer les cartes.")

if __name__ == "__main__":
    main()
