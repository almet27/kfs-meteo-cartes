"""Verify precipitation, snowfall and wind for archived 00 UTC runs."""
from datetime import date, datetime, timedelta, timezone
import json
from pathlib import Path
from build_model_skill import MODELS, RUN_DAYS, SITES, locations, request_json

FIELDS = {"precipitation": "mm", "snowfall": "cm", "wind_speed_10m": "km/h"}
ARCHIVE = Path("data/model-skill")


def fetch(url, params):
    query = dict(locations(), hourly=",".join(FIELDS), wind_speed_unit="kmh", precipitation_unit="mm")
    payload = request_json(url, {**query, **params})
    if not isinstance(payload, list) or len(payload) != len(SITES):
        raise ValueError("Réponse multi-sites incomplète")
    rows = []
    for item in payload:
        hours = item["hourly"]
        fields = {}
        for field, unit in FIELDS.items():
            if item["hourly_units"].get(field) == unit:
                fields[field] = dict(zip(hours["time"], hours.get(field, [])))
        rows.append(fields)
    return rows


def value(row, field, hours):
    values = row.get(field, {})
    if field == "wind_speed_10m":
        return values.get(hours[-1])
    sample = [values.get(hour) for hour in hours]
    return sum(sample) if all(isinstance(v, (float, int)) and v >= 0 for v in sample) else None


def build(month):
    base = json.loads((ARCHIVE / (month + ".json")).read_text())
    dates = sorted(base["run_dates"])
    if not dates:
        raise ValueError("Aucun run vérifié")
    truth = fetch("https://archive-api.open-meteo.com/v1/archive", {
        "models": "era5", "start_date": dates[0],
        "end_date": (date.fromisoformat(dates[-1]) + timedelta(days=15)).isoformat()})
    metrics = {f: {"unit": unit, "series": {m: [None]*15 for m in MODELS},
                   "n_by_model": {m: [0]*15 for m in MODELS}} for f, unit in FIELDS.items()}
    used = set()
    for day in dates:
        run = datetime.fromisoformat(day)
        forecasts = {}
        for model, api_id in MODELS.items():
            try:
                forecasts[model] = fetch("https://single-runs-api.open-meteo.com/v1/forecast", {
                    "models": api_id, "run": day + "T00:00", "forecast_days": 16})
            except (RuntimeError, ValueError, KeyError) as error:
                print(day, model, error, flush=True)
        # Use the same cases for all four models at each lead.
        if len(forecasts) != len(MODELS):
            continue
        for lead in range(1, 16):
            hours = [(run+timedelta(hours=24*(lead-1)+h)).strftime("%Y-%m-%dT%H:%M") for h in range(1,25)]
            for i, obs in enumerate(truth):
                for field, metric in metrics.items():
                    actual = value(obs, field, hours)
                    pred = {m: value(rows[i], field, hours) for m, rows in forecasts.items()}
                    if actual is None or None in pred.values():
                        continue
                    used.add(day)
                    for m, v in pred.items():
                        k = lead-1
                        metric["series"][m][k] = (metric["series"][m][k] or 0) + abs(v-actual)
                        metric["n_by_model"][m][k] += 1
        print("Run traité", day, flush=True)
    for metric in metrics.values():
        for m, totals in metric["series"].items():
            metric["series"][m] = [round(t/n,3) if n else None for t,n in zip(totals,metric["n_by_model"][m])]
    if not any(metrics["precipitation"]["n_by_model"]["ifs"]):
        raise ValueError("Aucune comparaison de précipitations vérifiée")
    path = ARCHIVE / (month+"-surface.json")
    if path.exists():
        previous = json.loads(path.read_text())
        if any(n < old for f, metric in metrics.items() for m, counts in metric["n_by_model"].items()
               for n, old in zip(counts, previous["metrics"][f]["n_by_model"][m])):
            raise ValueError("Couverture en recul : archive précédente conservée")
    report = {"schema":1, "period":month, "metrics":metrics, "run_dates":sorted(used),
              "sites":[s[0] for s in SITES], "reference":"Réanalyse ERA5",
              "method":"MAE sur un échantillon commun. Précipitations et neige : cumul des 24 h finissant à l’échéance. Vent à 10 m : valeur à 00 UTC."}
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2)+"\n")


if __name__ == "__main__":
    import sys
    build(sys.argv[1])
