#!/usr/bin/env python3
"""KFS: skill des configurations synoptiques de surface, J+1 a J+15.

Ne prétend PAS calculer un indice formel de blocage Z500 : Open-Meteo
ERA5 historique fournit ici la pression au sol, pas les champs Z500.
Le signal "blocage nord-atlantique" est un proxy de configuration
de pression, sans critère de persistence ni de gradients à 500 hPa.

Échantillon commun aux quatre modèles, prévisions 00Z datées,
mêmes points, même échéance et même heure que ERA5.
Les scores de détection de régimes demandent occurrences ET absences
suffisamment représentées : sinon null, sans faux pourcentage.
"""
from __future__ import annotations
import argparse
from datetime import datetime, date, timedelta, timezone
import json
import math
from pathlib import Path
import sys
from collections import defaultdict

from build_model_skill import MODELS, RUN_DAYS, request_json

# Noeuds d'une grille multi-points stable, sur l'Atlantique Nord et l'Europe.
# Indices construits à partir de gradients de pression au niveau marin (hPa).
POINTS = {
    "greenland": (63.0, -42.0),
    "iceland": (65.0, -20.0),
    "azores": (38.0, -28.0),
    "atlantic": (52.0, -26.0),
    "scandi": (62.0, 16.0),
    "east": (61.0, 34.0),
    "uk": (55.0, -5.0),
    "iberia": (42.0, -10.0),
}
VAR = "pressure_msl"
REGIMES = {
    "blocage_atlantique": {
        "title": "Configuration de hautes pressions nord-atlantiques",
        "short": "Blocage Atlantique (proxy SLP)",
        "definition": "Pression groenlandaise >= 1017 hPa, ecart Groenland-Açores >= -5 hPa, Groenland >= Atlantique central",
        "disclaimer": "Proxy de blocage / NAO négative : PAS un indice météorologique de blocage à 500 hPa",
        "unit": "hPa",
        "thresholds": {"greenland_min": 1017, "greenland_minus_azores_min": -5, "greenland_minus_atlantic_min": 0}
    },
    "anticyclone_scandinave": {
        "title": "Anticyclone centré sur la Scandinavie",
        "short": "Anticyclone scandinave (proxy SLP)",
        "definition": "Pression scandinave >= 1022 hPa, >= 5 hPa au-dessus du Royaume-Uni et >= 3 hPa au-dessus du nord-ouest de la Russie",
        "disclaimer": "Indicateur d'anticyclone de surface; ne certifie pas un blocage persistant",
        "unit": "hPa",
        "thresholds": {"scandi_min": 1022, "scandi_minus_uk_min": 5, "scandi_minus_east_min": 3}
    },
    "flux_zonal": {
        "title": "Flux d'ouest dominant sur le proche Atlantique et l'Europe",
        "short": "Circulation zonale (proxy SLP)",
        "definition": "Gradient de pression Ibérie-Islande >= 18 hPa, signe favorable aux vents d'ouest sur le proche Atlantique",
        "disclaimer": "Proxy barométrique du flux zonal, et NON mesure du courant-jet à 300 hPa",
        "unit": "hPa",
        "thresholds": {"iberia_minus_iceland_min": 18}
    },
}


def locate():
    entries = list(POINTS.values())
    return {
        "latitude": ",".join(str(x[0]) for x in entries),
        "longitude": ",".join(str(x[1]) for x in entries),
        "hourly": VAR,
        "timezone": "GMT",
        "cell_selection": "land",
    }


def normalize(payload):
    sequence = payload if isinstance(payload, list) else [payload]
    if len(sequence) != len(POINTS):
        raise ValueError(f"Coordonnées attendues {len(POINTS)}, reçues {len(sequence)}")
    result = {}
    for key, record in zip(POINTS, sequence):
        hourly = record.get("hourly", {})
        result[key] = dict(zip(hourly.get("time", []), hourly.get(VAR, [])))
    return result


def read_pressure(dataset, valid):
    out = {}
    for place in POINTS:
        v = dataset.get(place, {}).get(valid)
        if v is None:
            return None
        try:
            v = float(v)
        except (TypeError, ValueError):
            return None
        if not math.isfinite(v) or not 850 <= v <= 1100:
            return None
        out[place] = v
    return out


def features(p):
    # Valeur continue = gradient qui est comparé à ERA5 par MAE (hPa).
    # Un régime est évalué en binaire seulement si toutes conditions tenues.
    atlantic_index = p["greenland"] - p["azores"]
    scandi_index = p["scandi"] - p["uk"]
    zonal_index = p["iberia"] - p["iceland"]
    return {
        "blocage_atlantique": (
            atlantic_index,
            p["greenland"] >= 1017 and atlantic_index >= -5 and
            p["greenland"] >= p["atlantic"],
        ),
        "anticyclone_scandinave": (
            scandi_index,
            p["scandi"] >= 1022 and scandi_index >= 5 and
            p["scandi"] - p["east"] >= 3,
        ),
        "flux_zonal": (
            zonal_index, zonal_index >= 18,
        ),
    }


def retrieve_truth(month, today):
    first = date.fromisoformat(month + "-01")
    end = date(first.year + (first.month == 12), first.month % 12 + 1, 1) + timedelta(days=15)
    end = min(end, today - timedelta(days=5))
    if end < first:
        raise ValueError("Référence ERA5 du mois indisponible")
    params = {**locate(), "models": "era5", "start_date": first.isoformat(), "end_date": end.isoformat()}
    return normalize(request_json("https://archive-api.open-meteo.com/v1/archive", params))


def retrieve_run(run, model):
    params = {**locate(), "models": model, "run": run.strftime("%Y-%m-%dT%H:%M"), "forecast_days": 16}
    return normalize(request_json("https://single-runs-api.open-meteo.com/v1/forecast", params))


def empty_results():
    return {
        regime: [
            {"n": 0, "observed_event_n": 0, "observed_nonevent_n": 0,
             "event_runs": set(), "nonevent_runs": set(),
             "errors": {model: 0.0 for model in MODELS},
             "confusion": {model: {"tp": 0, "tn": 0, "fp": 0, "fn": 0} for model in MODELS}}
            for _ in range(15)
        ] for regime in REGIMES
    }


def build(month, today):
    first = date.fromisoformat(month + "-01")
    if first > today:
        raise ValueError("Mois futur")
    reference = retrieve_truth(month, today)
    scores = empty_results()
    runs = []
    failures = []
    for day in RUN_DAYS:
        try:
            run = datetime(first.year, first.month, day, 0, tzinfo=timezone.utc)
        except ValueError:
            continue
        if (run + timedelta(days=15)).date() > today - timedelta(days=5):
            continue
        models = {}
        for model, api in MODELS.items():
            try:
                models[model] = retrieve_run(run, api)
            except Exception as exc:
                failures.append(f"{run.date()} {model}: {str(exc)[:150]}")
        if len(models) != 4:
            continue
        runs.append(run.date().isoformat())
        for lead in range(1, 16):
            for hour in (0, 6, 12, 18):
                valid = (run + timedelta(days=lead, hours=hour)).strftime("%Y-%m-%dT%H:%M")
                truth_pressure = read_pressure(reference, valid)
                if truth_pressure is None:
                    continue
                predictions = {model: read_pressure(dataset, valid) for model, dataset in models.items()}
                if any(value is None for value in predictions.values()):
                    continue
                truth_features = features(truth_pressure)
                predicted_features = {model: features(values) for model, values in predictions.items()}
                for regime in REGIMES:
                    cell = scores[regime][lead - 1]
                    true_grad, true_event = truth_features[regime]
                    cell["n"] += 1
                    if true_event:
                        cell["observed_event_n"] += 1
                        cell["event_runs"].add(run.date().isoformat())
                    else:
                        cell["observed_nonevent_n"] += 1
                        cell["nonevent_runs"].add(run.date().isoformat())
                    for model in MODELS:
                        grad, event = predicted_features[model][regime]
                        cell["errors"][model] += abs(grad - true_grad)
                        category = "tp" if event and true_event else "fp" if event else "fn" if true_event else "tn"
                        cell["confusion"][model][category] += 1
        print("REGIME_RUN_VERIFIE", run.date(), flush=True)

    report = {
        "schema": 1,
        "period": month,
        "generated_utc": datetime.now(timezone.utc).isoformat(),
        "territory": "Europe occidentale et Atlantique Nord, 8 centres de pression",
        "reference": "Réanalyse ERA5 pression au niveau marin (pas Z500)",
        "source": "Open-Meteo Single Runs et Historical Weather",
        "method": "Prévisions 00 UTC vs ERA5, J+1 à J+15, échéance 00/06/12/18 UTC, mêmes 8 positions pour 4 modèles; balanced accuracy seulement si classes suffisamment représentées",
        "notes": [
            "Scores de régimes de surface indicatifs, pas des indices scientifiques officiels de blocage 500 hPa ou jet 300 hPa.",
            "La balanced accuracy exige au minimum 4 occurrences, 4 absences et 2 dates de runs distinctes pour chaque classe. Les autres résultats sont null (non évaluables).",
            "MAE hPa des gradients barométriques diffusée même quand les événements sont trop rares pour produire un score.",
            "Échantillons horaires issus des mêmes runs : ils ne sont pas statistiquement indépendants.",
        ],
        "models": MODELS,
        "points": POINTS,
        "run_dates": runs,
        "regimes": {},
        "errors": failures[:30],
    }
    for regime, definition in REGIMES.items():
        parts = scores[regime]
        score = {model: [] for model in MODELS}
        mae = {model: [] for model in MODELS}
        matrices = {model: [] for model in MODELS}
        for cell in parts:
            enough = (
                cell["n"] >= 10 and cell["observed_event_n"] >= 4 and
                cell["observed_nonevent_n"] >= 4 and
                len(cell["event_runs"]) >= 2 and len(cell["nonevent_runs"]) >= 2
            )
            for model in MODELS:
                matrix = cell["confusion"][model]
                matrices[model].append(matrix)
                mae[model].append(round(cell["errors"][model] / cell["n"], 3) if cell["n"] else None)
                if enough:
                    sensitivity = matrix["tp"] / (matrix["tp"] + matrix["fn"])
                    specificity = matrix["tn"] / (matrix["tn"] + matrix["fp"])
                    score[model].append(round(50.0 * (sensitivity + specificity), 1))
                else:
                    score[model].append(None)
        report["regimes"][regime] = {
            **definition,
            "scores_pct": score,
            "index_mae_hpa": mae,
            "confusion": matrices,
            "n": [cell["n"] for cell in parts],
            "event_n": [cell["observed_event_n"] for cell in parts],
            "nonevent_n": [cell["observed_nonevent_n"] for cell in parts],
            "event_run_n": [len(cell["event_runs"]) for cell in parts],
            "nonevent_run_n": [len(cell["nonevent_runs"]) for cell in parts],
        }
    return report


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--month", help="YYYY-MM, defaut mois civil precedent")
    parser.add_argument("--today")
    args = parser.parse_args()
    today = date.fromisoformat(args.today) if args.today else datetime.now(timezone.utc).date()
    prior = date(today.year, today.month, 1) - timedelta(days=1)
    month = args.month or prior.strftime("%Y-%m")
    output = build(month, today)
    target = Path("data/model-skill") / f"{month}-regimes.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(output, indent=2, ensure_ascii=False)+"\n", encoding="utf-8")
    summary = {
        k: {"max_n": max(v["n"]), "score_days": sum(s is not None for s in v["scores_pct"]["ifs"])}
        for k,v in output["regimes"].items()
    }
    print(json.dumps({"file": str(target), "runs":len(output["run_dates"]), "regimes":summary, "errors":output["errors"][:4]}, ensure_ascii=False))
    if not output["run_dates"] or not any(v["n"][0] for v in output["regimes"].values()):
        raise SystemExit("Aucun run synoptique vérifié : ne pas publier de scores")


if __name__ == "__main__":
    main()
