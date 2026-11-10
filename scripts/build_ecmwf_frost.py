#!/usr/bin/env python3
"""KFS /proba frost: ECMWF IFS ENS 8 members, 6-hour minimum 2 m temperature.

A frost event is a UTC day's lowest 2 m temperature <= a threshold. Every
member must have four *consecutive* native mn2t6 windows. Missing input is
never silently replaced with zero or a warmer 2 m instantaneous sample.
"""
from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
from eccodes import codes_get, codes_get_array, codes_grib_new_from_file, codes_release
from ecmwf.opendata import Client
from build_ecmwf_snow_storm import MEMBERS, indexed_points, nearest

ROOT = Path(__file__).resolve().parents[1]
POINTS = ROOT / "proba" / "points-ecmwf.json"
OUT = ROOT / "proba" / "ecmwf-frost-probabilities.json"
STEPS = list(range(6, 97, 6))
THRESHOLDS = (0, -2, -5, -10)
MIN_MEMBERS = 5


def load_minimum_fields(path, points):
    """Read native minimum of previous 6 hours, converted from kelvin to °C."""
    fields, index, grid_size = {}, None, 0
    with open(path, "rb") as stream:
        while (msg := codes_grib_new_from_file(stream)) is not None:
            try:
                short = str(codes_get(msg, "shortName"))
                if short != "mn2t6":
                    continue
                end = int(codes_get(msg, "endStep"))
                start = int(codes_get(msg, "startStep"))
                member = int(codes_get(msg, "number"))
                if end not in STEPS or member not in MEMBERS or start != end - 6:
                    continue
                if (end, member) in fields:
                    raise RuntimeError("Duplicate ECMWF frost field")
                raw = np.asarray(codes_get_array(msg, "values"), dtype=np.float64)
                if index is None:
                    index, grid_size = nearest(msg, points)
                if len(raw) != grid_size:
                    raise RuntimeError("Inconsistent ECMWF frost grid")
                celsius = raw[index] - 273.15
                fields[(end, member)] = np.where(
                    np.isfinite(celsius) & (celsius >= -90) & (celsius <= 60),
                    celsius, np.nan)
            finally:
                codes_release(msg)
    if not fields:
        raise RuntimeError("No ECMWF mn2t6 fields available")
    return fields


def daily_minima(fields, lead, npoints):
    """One Tmin per ensemble member over exactly four 6h periods (UTC)."""
    result = []
    for member in MEMBERS:
        periods = [fields.get((lead * 24 + hour, member))
                   for hour in (6, 12, 18, 24)]
        if any(v is None for v in periods):
            result.append(np.full(npoints, np.nan))
            continue
        matrix = np.stack(periods)
        if matrix.shape != (4, npoints):
            raise RuntimeError("Frost point count mismatch")
        good = np.all(np.isfinite(matrix), axis=0)
        result.append(np.where(good, np.min(matrix, axis=0), np.nan))
    return np.stack(result)


def frost_fields(member_minima):
    """Return real member fractions, or fail closed on incomplete coverage."""
    a = np.asarray(member_minima, dtype=np.float64)
    if a.ndim != 2 or a.shape[0] != len(MEMBERS):
        raise RuntimeError("Frost member count mismatch")
    valid = np.sum(np.isfinite(a), axis=0)
    if np.any(valid < MIN_MEMBERS):
        raise RuntimeError("Fewer than five valid ECMWF members at some points")
    fields = {}
    for threshold in THRESHOLDS:
        slug = "frost" + str(abs(threshold))
        fields[slug] = np.sum(np.isfinite(a) & (a <= threshold), axis=0) / valid * 100
    fields["frost_mean_c"] = np.nansum(a, axis=0) / valid
    return fields


def main():
    cfg = json.loads(POINTS.read_text(encoding="utf-8"))
    coords, zones = indexed_points(cfg["zones"])
    with tempfile.TemporaryDirectory() as tmp:
        client = Client(source=os.getenv("ECMWF_SOURCE", "ecmwf"),
                        model="ifs", resol="0p25")
        path = Path(tmp) / "ecmwf-ens-frost.grib2"
        response = client.retrieve(time=0, stream="enfo", type="pf",
                                   number=MEMBERS, step=STEPS, param="mn2t6",
                                   target=str(path))
        run = response.datetime
        if run.tzinfo is None:
            run = run.replace(tzinfo=timezone.utc)
        run = run.astimezone(timezone.utc)
        if run.hour != 0 or not (timedelta(0) <= datetime.now(timezone.utc) - run <= timedelta(hours=40)):
            raise RuntimeError("ECMWF frost run not fresh 00Z")
        fields = load_minimum_fields(path, coords)

    days = {}
    for lead in range(4):
        start = run + timedelta(days=lead)
        forecast = frost_fields(daily_minima(fields, lead, len(coords)))
        days[start.date().isoformat()] = {
            "valid_from_utc": start.isoformat().replace("+00:00", "Z"),
            "valid_to_utc": (start + timedelta(days=1)).isoformat().replace("+00:00", "Z"),
            "fields": {field: {zone: [round(float(x), 1) for x in values[a:b]]
                               for zone, (a, b) in zones.items()}
                       for field, values in forecast.items()}
        }
    result = {
        "schema": 1,
        "provider": "ECMWF IFS ENS 8-member frost subset",
        "source": "https://www.ecmwf.int/en/forecasts/datasets/open-data",
        "license": "CC BY 4.0",
        "run_utc": run.isoformat().replace("+00:00", "Z"),
        "generated_at_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "ensemble_members": MEMBERS,
        "sampling_interval_hours": 6,
        "method": "Native ECMWF mn2t6: 4 non-overlapping 6h windows per UTC day; minimum over each 24h member; fraction <= threshold",
        "warning": "Indicative 8-member, 0.25 degree ensemble fraction; UTC days (not local calendar days), not ground frost or official warning",
        "zone_point_counts": {zone: b - a for zone, (a, b) in zones.items()},
        "days": days,
    }
    OUT.write_text(json.dumps(result, ensure_ascii=False, separators=(",", ":")) + "\n", encoding="utf-8")
    print("Saved", OUT, OUT.stat().st_size, "bytes; run", run)


if __name__ == "__main__":
    main()
