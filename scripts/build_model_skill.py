#!/usr/bin/env python3
"""KFS: comparaison objective de quatre modèles sur 12 points français.

Archives des runs 00 UTC (8 dates/mois), vérifiées par ERA5.
Une comparaison est conservée seulement si les quatre prévisions et
la référence sont toutes disponibles au même point et à la même échéance.
Il n'est jamais créé de score de précision fictif ou de données interpolées.
"""
from __future__ import annotations
import argparse
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
import json
import math
import os
from pathlib import Path
import random
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

MODELS = {
    "ifs": "ecmwf_ifs025",
    "aifs": "ecmwf_aifs025_single",
    "aigfs": "ncep_aigfs025",
    "gfs": "ncep_gfs_global",
}
VARIABLES = ("temperature_2m", "pressure_msl")
SITES = (
    ("Brest", 48.3904, -4.4861),
    ("Lille", 50.6292, 3.0573),
    ("Paris", 48.8566, 2.3522),
    ("Strasbourg", 48.5734, 7.7521),
    ("Nantes", 47.2184, -1.5536),
    ("Dijon", 47.3220, 5.0415),
    ("Clermont-Ferrand", 45.7772, 3.0870),
    ("Lyon", 45.7640, 4.8357),
    ("Bordeaux", 44.8378, -0.5792),
    ("Toulouse", 43.6047, 1.4442),
    ("Marseille", 43.2965, 5.3698),
    ("Ajaccio", 41.9192, 8.7386),
)
RUN_DAYS = (1, 5, 9, 13, 17, 21, 25, 29)


def request_json(base, parameters, tries=4):
    url = base + "?" + urlencode(parameters)
    last = None
    for attempt in range(tries):
        try:
            req = Request(url, headers={"User-Agent": "KFS-Meteo-Verification/1.0", "Accept": "application/json"})
            with urlopen(req, timeout=80) as resp:
                content = json.load(resp)
            if not isinstance(content, (dict, list)) or (isinstance(content, dict) and content.get("error")):
                raise ValueError(str(content)[:350])
            return content
        except (HTTPError, URLError, TimeoutError, ValueError) as exc:
            last = exc
            status = getattr(exc, "code", None)
            if status in (400, 401, 403, 404, 422):
                break
            if attempt + 1 < tries:
                time.sleep(min(28, 2 ** attempt * 2 + random.random()))
    raise RuntimeError(f"{type(last).__name__}: {last}")


def locations():
    return {
        "latitude": ",".join(str(x[1]) for x in SITES),
        "longitude": ",".join(str(x[2]) for x in SITES),
        "timezone": "GMT",
        "cell_selection": "land",
        "hourly": ",".join(VARIABLES),
    }


def normalize(payload):
    arr = payload if isinstance(payload, list) else [payload]
    if len(arr) != len(SITES):
        raise ValueError(f"Nombre de lieux inattendu: {len(arr)} au lieu de {len(SITES)}")
    result = {}
    for site, item in zip(SITES, arr):
        hourly = item.get("hourly", {})
        ts = hourly.get("time", [])
        result[site[0]] = {
            variable: dict(zip(ts, hourly.get(variable, [])))
            for variable in VARIABLES
        }
    return result


def truth(month, current):
    first = date.fromisoformat(month + "-01")
    end = date(first.year + (first.month == 12), first.month % 12 + 1, 1) + timedelta(days=15)
    params = {
        **locations(),
        "start_date": first.isoformat(),
        "end_date": min(end, current - timedelta(days=5)).isoformat(),
        "models": "era5",
    }
    if params["end_date"] < params["start_date"]:
        raise ValueError("Réanalyse ERA5 non encore disponible pour le mois")
    return normalize(request_json("https://archive-api.open-meteo.com/v1/archive", params))


def forecast(run, model):
    params = {
        **locations(),
        "models": model,
        "run": run.strftime("%Y-%m-%dT%H:%M"),
        "forecast_days": 16,
    }
    # Les prévisions peuvent être archivées sur 15 jours calendaires pour
    # certains cycles : la valeur J+15 reste absente, jamais extrapolée.
    return normalize(request_json("https://single-runs-api.open-meteo.com/v1/forecast", params))


def numeric(value):
    try:
        v = float(value)
        return v if math.isfinite(v) else None
    except (ValueError, TypeError):
        return None


def build(month, today):
    first = date.fromisoformat(month + "-01")
    if first > today:
        raise ValueError("Mois futur")
    observations = truth(month, today)
    totals = {var: {m: [0.0] * 15 for m in MODELS} for var in VARIABLES}
    counts = {var: [0] * 15 for var in VARIABLES}
    accepted_runs = []
    rejected = []
    for day in RUN_DAYS:
        try:
            run = datetime(first.year, first.month, day, tzinfo=timezone.utc)
        except ValueError:
            continue
        if (run + timedelta(days=15)).date() > today - timedelta(days=5):
            # On ne publie pas les J+15 avant disponibilité fiable d'ERA5.
            continue
        bundle = {}
        for key, api_id in MODELS.items():
            try:
                bundle[key] = forecast(run, api_id)
            except Exception as exc:
                rejected.append(f"{run.date()} {key}: {str(exc)[:160]}")
        if len(bundle) != 4:
            continue
        accepted_runs.append(run.date().isoformat())
        for lead in range(1, 16):
            valid = (run + timedelta(days=lead)).strftime("%Y-%m-%dT%H:%M")
            for name, _, _ in SITES:
                for var in VARIABLES:
                    actual = numeric(observations[name][var].get(valid))
                    if actual is None:
                        continue
                    values = {model: numeric(bundle[model][name][var].get(valid)) for model in MODELS}
                    if any(v is None for v in values.values()):
                        continue
                    for model, predicted in values.items():
                        totals[var][model][lead - 1] += abs(predicted - actual)
                    counts[var][lead - 1] += 1
        print(f"RUN_VERIFIE {run.date()} : {len(bundle)} modèles", flush=True)
    result = {
        "schema": 1,
        "period": month,
        "generated_utc": datetime.now(timezone.utc).isoformat(),
        "territory": "France métropolitaine, Corse comprise",
        "reference": "Réanalyse ERA5 (référence modélisée, pas relevés de stations)",
        "method": "MAE, 12 lieux; runs 00 UTC des jours 1, 5, 9, 13, 17, 21, 25, 29 du mois; validité 00 UTC à J+1..J+15; échantillon commun aux 4 modèles",
        "sites": [x[0] for x in SITES],
        "run_dates": accepted_runs,
        "requested_run_days": list(RUN_DAYS),
        "models": MODELS,
        "metrics": {},
        "errors": rejected[:35],
    }
    for var in VARIABLES:
        unit = "°C" if var == "temperature_2m" else "hPa"
        result["metrics"][var] = {
            "unit": unit,
            "n": counts[var],
            "series": {
                model: [
                    round(totals[var][model][i] / counts[var][i], 3) if counts[var][i] else None
                    for i in range(15)
                ] for model in MODELS
            }
        }
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--month", help="YYYY-MM (par défaut, mois civil précédent)")
    parser.add_argument("--today", help="Date de vérification (tests)")
    args = parser.parse_args()
    today = date.fromisoformat(args.today) if args.today else datetime.now(timezone.utc).date()
    first = date(today.year, today.month, 1)
    previous = first - timedelta(days=1)
    month = args.month or previous.strftime("%Y-%m")
    report = build(month, today)
    out = Path("data/model-skill") / f"{month}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    summary = {m: max(report["metrics"][m]["n"], default=0) for m in VARIABLES}
    print(json.dumps({"file": str(out), "runs": len(report["run_dates"]), "samples_max": summary, "errors": report["errors"][:5]}, ensure_ascii=False))
    if not report["run_dates"] or not any(max(x["n"], default=0) > 0 for x in report["metrics"].values()):
        raise SystemExit("Aucun score vérifié — contrôle nécessaire des archives modèles et observations")


if __name__ == "__main__":
    main()
