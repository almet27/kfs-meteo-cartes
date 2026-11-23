#!/usr/bin/env python3
"""KFS: vérification de quatre modèles, plus AIFS ENS Control quand archivé.

Archives des runs 00 UTC (8 dates/mois), vérifiées par ERA5.
Les quatre modèles de référence gardent un échantillon commun.
AIFS ENS Control est vérifié sur un sous-échantillon propre, sans biaiser les quatre.
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

AIFS_CONTROL_ID = "ecmwf-aifs-ens-forecast"  # AIFS ENS membre 0, pas AIFS Single

HISTORICAL_MODELS = {
    "ifs": "ecmwf_ifs",
    "aifs": "ecmwf-aifs-single-forecast",
    "gfs": "noaa-gfs-forecast",
}

def models_for_month(month):
    return HISTORICAL_MODELS if month < "2026-04" else MODELS


def optional_models_for_month(month):
    # AIFS ENS v1 opérationnel à partir du 1er juillet 2025 ; archive Dynamical dès le 2.
    return {"aifs_control": AIFS_CONTROL_ID} if month >= "2025-07" else {}

def historical_payload(run, model, points, variables):
    """Return Open-Meteo-shaped arrays without interpolating missing leads."""
    if model == "ecmwf_ifs":
        return request_json("https://single-runs-api.open-meteo.com/v1/forecast", {
            "latitude": ",".join(str(p[0]) for p in points),
            "longitude": ",".join(str(p[1]) for p in points),
            "timezone": "GMT", "cell_selection": "land",
            "hourly": ",".join(variables), "models": model,
            "run": run.strftime("%Y-%m-%dT%H:%M"), "forecast_days": 16,
        })
    mapping = {"temperature_2m": "temperature_2m",
               "pressure_msl": "pressure_reduced_to_mean_sea_level"}
    timestamp = run.strftime("%Y-%m-%dT%H:%M:%SZ")
    output = []
    # Keep each request small to limit archive API work units.
    for i, (lat, lon) in enumerate(points):
        query = {"dataProductId": model, "location": {"latitude": lat, "longitude": lon},
                 "variables": [mapping[v] for v in variables],
                 "initTime": timestamp, "maxLeadTimeHours": 360}
        last = None
        for attempt in range(4):
            try:
                req = Request("https://api.dynamical.org/v1/forecasts",
                              data=json.dumps({"queries": [query]}).encode(),
                              headers={"User-Agent": "KFS-Meteo-Verification/1.0",
                                       "Content-Type": "application/json", "Accept": "application/json"})
                with urlopen(req, timeout=80) as response:
                    raw = json.load(response)
                f = raw["results"][0]["forecasts"][0]
                if f["initTime"][:16] != timestamp[:16]:
                    raise ValueError("Run different de celui demande")
                times = [t[:16] for t in f["validTimes"]]
                hourly = {"time": times}
                if model == AIFS_CONTROL_ID:
                    controls = [entry for entry in f.get("ensembleMembers", [])
                                if entry.get("member") == 0]
                    if len(controls) != 1:
                        raise ValueError("Membre 0 AIFS ENS Control absent ou ambigu")
                    fields = controls[0]["data"]
                else:
                    fields = f["data"]
                for var in variables:
                    vals = fields[mapping[var]]
                    if len(vals) != len(times):
                        raise ValueError("Axe temporel incoherent")
                    # Dynamical catalogue: Celsius and Pa; ERA5 via Open-Meteo: Celsius and hPa.
                    factor = 0.01 if var == "pressure_msl" else 1.0
                    hourly[var] = [float(v) * factor if isinstance(v, (float, int)) and math.isfinite(v) else None for v in vals]
                output.append({"hourly": hourly})
                break
            except (HTTPError, URLError, TimeoutError, ValueError, KeyError, IndexError, TypeError) as exc:
                last = exc
                if attempt == 3 or getattr(exc, "code", None) in (400, 401, 403, 404, 422):
                    raise RuntimeError(f"{model} point {i}: {last}") from exc
                time.sleep(min(30, 3 * 2 ** attempt))
        time.sleep(0.4)
    return output

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
    if model == AIFS_CONTROL_ID or model in HISTORICAL_MODELS.values():
        return normalize(historical_payload(run, model, [(s[1], s[2]) for s in SITES], VARIABLES))
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
    active_models = models_for_month(month)
    optional_models = optional_models_for_month(month)
    totals = {var: {m: [0.0] * 15 for m in active_models} for var in VARIABLES}
    counts = {var: [0] * 15 for var in VARIABLES}
    extra_totals = {var: {m: [0.0] * 15 for m in optional_models} for var in VARIABLES}
    extra_counts = {var: {m: [0] * 15 for m in optional_models} for var in VARIABLES}
    extra_run_dates = set()
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
        for key, api_id in active_models.items():
            try:
                bundle[key] = forecast(run, api_id)
            except Exception as exc:
                rejected.append(f"{run.date()} {key}: {str(exc)[:160]}")
        if len(bundle) != len(active_models):
            continue
        # L'absence du contrôle AIFS ne doit jamais invalider les modèles historiques.
        extras = {}
        for key, api_id in optional_models.items():
            try:
                extras[key] = forecast(run, api_id)
                extra_run_dates.add(run.date().isoformat())
            except Exception as exc:
                rejected.append(f"{run.date()} {key}: {str(exc)[:160]}")
        accepted_runs.append(run.date().isoformat())
        for lead in range(1, 16):
            valid = (run + timedelta(days=lead)).strftime("%Y-%m-%dT%H:%M")
            for name, _, _ in SITES:
                for var in VARIABLES:
                    actual = numeric(observations[name][var].get(valid))
                    if actual is None:
                        continue
                    values = {model: numeric(bundle[model][name][var].get(valid)) for model in active_models}
                    if any(v is None for v in values.values()):
                        continue
                    for model, predicted in values.items():
                        totals[var][model][lead - 1] += abs(predicted - actual)
                    counts[var][lead - 1] += 1
                    for model, dataset in extras.items():
                        predicted = numeric(dataset[name][var].get(valid))
                        if predicted is not None:
                            extra_totals[var][model][lead - 1] += abs(predicted - actual)
                            extra_counts[var][model][lead - 1] += 1
        print(f"RUN_VERIFIE {run.date()} : {len(bundle)} modèles", flush=True)
    result = {
        "schema": 1,
        "period": month,
        "generated_utc": datetime.now(timezone.utc).isoformat(),
        "territory": "France métropolitaine, Corse comprise",
        "reference": "Réanalyse ERA5 (référence modélisée, pas relevés de stations)",
        "method": "MAE, 12 lieux; runs 00 UTC des jours 1, 5, 9, 13, 17, 21, 25, 29 du mois; validité 00 UTC à J+1..J+15; échantillon commun aux modèles disponibles",
        "sites": [x[0] for x in SITES],
        "run_dates": accepted_runs,
        "requested_run_days": list(RUN_DAYS),
        "models": {**active_models, **{m: api for m, api in optional_models.items()
                                       if any(max(extra_counts[v][m]) for v in VARIABLES)}},
        "source": ("Open-Meteo Single Runs, Dynamical.org AIFS ENS membre 0, ERA5"
                   if month >= "2026-04" else "Open-Meteo IFS, Dynamical.org AIFS/GFS/AIFS ENS, ERA5"),
        "notes": ((["AIGFS exclu avant avril 2026; résolution IFS historique différente"]
                   if month < "2026-04" else []) +
                  ["AIFS ENS Control (membre 0) distinct d'AIFS Single ; échantillon optionnel, n par modèle."]),
        "aifs_control_run_dates": sorted(extra_run_dates),
        "metrics": {},
        "errors": rejected[:35],
    }
    for var in VARIABLES:
        unit = "°C" if var == "temperature_2m" else "hPa"
        result["metrics"][var] = {
            "unit": unit,
            "n": counts[var],
            "series": {
                **{model: [
                    round(totals[var][model][i] / counts[var][i], 3) if counts[var][i] else None
                    for i in range(15)
                ] for model in active_models},
                **{model: [
                    round(extra_totals[var][model][i] / extra_counts[var][model][i], 3)
                    if extra_counts[var][model][i] else None
                    for i in range(15)
                ] for model in optional_models},
            },
            "n_by_model": {
                **{model: counts[var] for model in active_models},
                **extra_counts[var],
            },
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
