"""Verify precipitation, snowfall and wind for archived 00 UTC runs."""
from calendar import monthrange
from collections import Counter
from datetime import date, datetime, timedelta, timezone
import math
import json
from pathlib import Path
from build_model_skill import MODELS, SITES, locations, request_json

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


def valid_number(v):
    return isinstance(v, (float, int)) and math.isfinite(v)


def candidate_dates(month, today):
    first = date.fromisoformat(month + "-01")
    cutoff = today - timedelta(days=20)  # 15-day horizon + ERA5 publication lag
    return [first.replace(day=d).isoformat()
            for d in range(1, monthrange(first.year, first.month)[1] + 1)
            if first.replace(day=d) <= cutoff]


def value(row, field, hours):
    values = row.get(field, {})
    if field == "wind_speed_10m":
        v = values.get(hours[-1])
        return v if valid_number(v) and v >= 0 else None
    sample = [values.get(hour) for hour in hours]
    return sum(sample) if all(valid_number(v) and v >= 0 for v in sample) else None


def build(month):
    dates = candidate_dates(month, datetime.now(timezone.utc).date())
    if not dates:
        raise ValueError("Aucun run vérifié")
    truth = fetch("https://archive-api.open-meteo.com/v1/archive", {
        "models": "era5", "start_date": dates[0],
        "end_date": (date.fromisoformat(dates[-1]) + timedelta(days=15)).isoformat()})
    metrics = {f: {"unit": unit, "series": {m: [None]*15 for m in MODELS},
                   "n_by_model": {m: [0]*15 for m in MODELS}} for f, unit in FIELDS.items()}
    used = set()
    missing_j1 = {f: {m: Counter() for m in ["era5", *MODELS]} for f in ("precipitation", "snowfall")}
    run_dates_by_metric = {f: [set() for _ in range(15)] for f in FIELDS}
    rejected = []
    for day in dates:
        run = datetime.fromisoformat(day)
        forecasts = {}
        for model, api_id in MODELS.items():
            try:
                forecasts[model] = fetch("https://single-runs-api.open-meteo.com/v1/forecast", {
                    "models": api_id, "run": day + "T00:00", "forecast_days": 16})
            except (RuntimeError, ValueError, KeyError) as error:
                rejected.append({"run": day, "model": model, "error": str(error)[:250]})
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
                    if lead == 1 and field in missing_j1:
                        for model, row in {"era5": obs, **{m: rows[i] for m, rows in forecasts.items()}}.items():
                            vals = row.get(field, {})
                            for hour_index, hour in enumerate(hours, 1):
                                v = vals.get(hour)
                                if not valid_number(v) or v < 0:
                                    missing_j1[field][model][str(hour_index)] += 1
                    if actual is None or None in pred.values():
                        continue
                    used.add(day)
                    run_dates_by_metric[field][lead-1].add(day)
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
    diagnostics = {f: {m: dict(counts) for m, counts in models.items()} for f, models in missing_j1.items()}
    print("Diagnostic heures manquantes J+1", json.dumps(diagnostics), flush=True)
    report = {"schema":1, "period":month, "metrics":metrics, "run_dates":sorted(used),
              "sampling":"daily_00z", "requested_run_dates":dates, "rejected_runs":rejected,
              "run_dates_by_metric":{f: [sorted(ds) for ds in leads] for f, leads in run_dates_by_metric.items()},
              "missing_j1_hours_by_model":diagnostics,
              "sites":[s[0] for s in SITES], "reference":"Réanalyse ERA5",
              "method":"MAE sur un échantillon commun aux quatre modèles; runs 00 UTC quotidiens disponibles. Précipitations et neige : cumul des 24 h finissant à l’échéance. Vent à 10 m : valeur à 00 UTC."}
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2)+"\n")


if __name__ == "__main__":
    import sys
    build(sys.argv[1])
