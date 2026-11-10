#!/usr/bin/env python3
"""KFS /proba free ECMWF IFS ENS: snow cover, falling snow and convective potential.

NOT official event probabilities. Uses 8 fixed, dispersed ensemble members and
two snapshots per UTC day (12-hourly); lower-resolution sampling than full ENS.
Snow height comes from ECMWF SD water equivalent and RSN density:
  snow_depth_cm = 100000 * sd_m_water_equivalent / rsn_kg_m3.
Convective tiers use MU-CAPE, convective rain, dewpoint and gusts; optional 850-500hPa shear and omega700 provide separate context.
Falling snow uses the *daily accumulation of SF snowfall water equivalent*,\nnot snow already present on the ground. Do not infer road snow cover.
"""
from __future__ import annotations
import json
import math
import os
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
from scipy.spatial import cKDTree
from ecmwf.opendata import Client
from eccodes import codes_get, codes_get_array, codes_grib_new_from_file, codes_release

ROOT = Path(__file__).resolve().parents[1]
POINTS = ROOT / "proba" / "points-ecmwf.json"
OUT = ROOT / "proba" / "ecmwf-subset-probabilities.json"
MEMBERS = [3, 9, 15, 21, 27, 33, 39, 45]
STEPS = list(range(12, 97, 12))
PARAMS = ["sd", "rsn", "mucape", "cp", "10fg", "tp", "2d"]
# Optional ECMWF open-data pressure levels; they cannot block the base forecasts.
SYNOPTIC_LEVELS = {("u", 850), ("v", 850), ("u", 500), ("v", 500), ("w", 700)}
ORGANIZATION_SHEAR_MS = 15.0
ASCENT_OMEGA_PA_S = -0.05


def indexed_points(zones):
    points, ranges = [], {}
    for zone, coordinates in zones.items():
        a = len(points)
        points.extend((float(lat), float(lon)) for lat, lon in coordinates)
        ranges[zone] = (a, len(points))
    return np.asarray(points, dtype=np.float64), ranges


def nearest(msg, points):
    lats = np.asarray(codes_get_array(msg, "latitudes"), dtype=np.float64)
    lons = np.asarray(codes_get_array(msg, "longitudes"), dtype=np.float64)
    lons = np.where(lons > 180, lons - 360, lons)
    inds = np.flatnonzero((lats > 40) & (lats < 53) & (lons > -7) & (lons < 12))
    if len(inds) < 100:
        raise RuntimeError("ECMWF grid not compatible with France")
    fac = math.cos(math.radians(47))
    tree = cKDTree(np.column_stack((lats[inds], lons[inds] * fac)))
    dist, pos = tree.query(np.column_stack((points[:, 0], points[:, 1] * fac)))
    if np.max(dist) > .45:
        raise RuntimeError("Nearest ECMWF grid cell farther than .45 deg")
    return inds[pos], len(lats)


def load_fields(path, points):
    values = {}
    tp_start_steps = {}
    index = None
    count = 0
    ngrid = 0
    with open(path, "rb") as stream:
        while (msg := codes_grib_new_from_file(stream)) is not None:
            try:
                short = str(codes_get(msg, "shortName"))
                step = int(codes_get(msg, "endStep"))
                number = int(codes_get(msg, "number"))
                if short not in PARAMS or step not in STEPS or number not in MEMBERS:
                    continue
                a = np.asarray(codes_get_array(msg, "values"), dtype=np.float64)
                if index is None:
                    index, ngrid = nearest(msg, points)
                if len(a) != ngrid:
                    raise RuntimeError(f"Inconsistent ECMWF grid {short} {step}")
                sampled = a[index]
                if np.any(~np.isfinite(sampled)):
                    # Keep NaNs as missing: never replace with zero.
                    sampled = np.where(np.isfinite(sampled), sampled, np.nan)
                values[(short, step, number)] = sampled
                if short == "tp":
                    tp_start_steps[(step, number)] = int(codes_get(msg, "startStep"))
                count += 1
            finally:
                codes_release(msg)
    expected = len(STEPS) * len(MEMBERS) * len(PARAMS)
    missing = [(k, s, n) for k in PARAMS for s in STEPS for n in MEMBERS
               if (k, s, n) not in values]
    # Some runs omit the +96h gust field; this must not block snow or imply
    # zero wind. Other missing products are a hard failure.
    optional = {( "10fg", 96, member) for member in MEMBERS}
    optional.update(( "tp", step, member) for step in STEPS for member in MEMBERS)
    required_missing = [k for k in missing if k not in optional]
    if required_missing:
        raise RuntimeError(f"ECMWF PF incomplete: {count}/{expected}; missing {required_missing[:5]}")
    if missing:
        print("Warn: optional ECMWF gust fields missing (not treated as zero):", missing)
    return values, tp_start_steps


def load_synoptic_fields(path, points):
    """Sample optional pressure-level GRIB; preserve absence as missing."""
    sampled, index, ngrid = {}, None, 0
    with open(path, "rb") as stream:
        while (msg := codes_grib_new_from_file(stream)) is not None:
            try:
                short = str(codes_get(msg, "shortName"))
                if short not in ("u", "v", "w"):
                    continue
                level = int(codes_get(msg, "level"))
                if (short, level) not in SYNOPTIC_LEVELS:
                    continue
                step = int(codes_get(msg, "endStep"))
                number = int(codes_get(msg, "number"))
                if step not in STEPS or number not in MEMBERS:
                    continue
                values = np.asarray(codes_get_array(msg, "values"), dtype=np.float64)
                if index is None:
                    index, ngrid = nearest(msg, points)
                if len(values) != ngrid:
                    raise RuntimeError("ECMWF synoptic pressure-level grid mismatch")
                sample = values[index]
                sampled[(short, level, step, number)] = np.where(
                    np.isfinite(sample), sample, np.nan)
            finally:
                codes_release(msg)
    if not sampled:
        raise RuntimeError("No usable pressure-level GRIB records")
    return sampled


def shear_850_500_ms(u850, v850, u500, v500):
    """Bulk vector shear between 850 and 500 hPa; NOT 0-6 km shear."""
    return np.hypot(np.asarray(u500) - np.asarray(u850),
                    np.asarray(v500) - np.asarray(v850))


def organization_and_ascent(level, shear_ms, omega700):
    """Separate environment diagnostics, with missing fields as NaN."""
    level, shear_ms, omega700 = (
        np.asarray(v, dtype=np.float64) for v in (level, shear_ms, omega700))
    org = np.where(
        np.isfinite(level) & np.isfinite(shear_ms),
        ((level >= 2) & (shear_ms >= ORGANIZATION_SHEAR_MS)).astype(float), np.nan)
    lift = np.where(
        np.isfinite(level) & np.isfinite(omega700),
        ((level >= 1) & (omega700 <= ASCENT_OMEGA_PA_S)).astype(float), np.nan)
    return org, lift


def max_available(values):
    """Max over daily samples without mistaking missing for zero."""
    arr = np.stack(values)
    m = np.max(np.where(np.isfinite(arr), arr, -np.inf), axis=0)
    return np.where(np.isfinite(m), m, np.nan)


def optional_ensemble_stat(members, probability=False):
    """Require five genuine members per grid point before publishing."""
    a = np.asarray(members, dtype=np.float64)
    n = np.sum(np.isfinite(a), axis=0)
    if not np.any(n >= 5):
        return None
    mean = np.nansum(a, axis=0) / np.maximum(n, 1)
    return np.where(n >= 5, mean * (100 if probability else 1), np.nan)


def convective_tier(cape, precipitation_mm, gust_kmh, dewpoint_c=math.nan):
    """Experimental convective potential (0-5), not a calibrated thunderstorm probability.

    CP supports diagnosed convection; most-unstable CAPE + 2m dewpoint detect
    pre-convective environments even if the forecast hasn't triggered showers.
    A moist unstable environment alone is capped at level 2 (no forcing known).
    Gusts are needed for levels 4-5, not to acknowledge weak convection.
    """
    if not np.isfinite(cape) or not np.isfinite(precipitation_mm):
        return None
    moist = np.isfinite(dewpoint_c) and dewpoint_c >= 8
    level = 0
    if (cape >= 100 and precipitation_mm >= 0.1) or (cape >= 225 and moist):
        level = 1
    if (cape >= 300 and precipitation_mm >= 0.25) or (cape >= 500 and moist):
        level = 2
    if cape >= 650 and precipitation_mm >= 0.7 and (moist or (np.isfinite(gust_kmh) and gust_kmh >= 30)):
        level = 3
    if cape >= 950 and precipitation_mm >= 1 and np.isfinite(gust_kmh) and gust_kmh >= 35:
        level = 3
    if cape >= 1500 and precipitation_mm >= 2 and np.isfinite(gust_kmh) and gust_kmh >= 55:
        level = 4
    if cape >= 2800 and precipitation_mm >= 4 and np.isfinite(gust_kmh) and gust_kmh >= 85:
        level = 5
    return level

def daily_rain_mm(values, tp_starts, member, day_start, npoints, param="tp"):
    """Extract actual 24h TP (m -> mm) using GRIB startStep, not probability thresholds.

    Supports cumulative 0..T forecasts, adjacent 12h increments, or a direct
    24h accumulation. No ambiguous or missing step is silently turned into 0.
    """
    day_end = day_start + 24
    middle = day_start + 12
    end = values.get((param, day_end, member))
    if end is None:
        return None
    end_start = tp_starts.get((day_end, member))
    if end_start == day_start:
        rainfall_m = end
    elif end_start == middle:
        first = values.get((param, middle, member))
        first_start = tp_starts.get((middle, member))
        if first is None:
            return None
        if first_start == day_start:
            rainfall_m = first + end
        elif first_start == 0 and day_start > 0:
            # The first interval is the difference between run-cumulative
            # middle and dayStart, then add the final 12-hour increment.
            previous = values.get((param, day_start, member))
            if previous is None or tp_starts.get((day_start, member)) != 0:
                return None
            rainfall_m = first - previous + end
        else:
            return None
    elif end_start == 0 and day_start > 0:
        previous = values.get((param, day_start, member))
        if previous is None or tp_starts.get((day_start, member)) != 0:
            return None
        rainfall_m = end - previous
    else:
        return None
    if not np.all(np.isfinite(rainfall_m)):
        return None
    # A difference of two forecast accumulations can be slightly negative
    # from packing; large negative results mean a broken interpretation.
    if np.min(rainfall_m) < -0.0002:
        return None
    mm = np.maximum(rainfall_m, 0) * 1000.0
    if np.max(mm) > 500:
        return None
    return mm

def load_optional_snowfall(path, points):
    """Sample native ECMWF SF (m water equivalent) and preserve GRIB startStep.

    Separate from the existing compulsory download: unavailability of SF must
    never interrupt the snow-cover or convective products.
    """
    values, starts, index, ngrid = {}, {}, None, 0
    with open(path, "rb") as stream:
        while (msg := codes_grib_new_from_file(stream)) is not None:
            try:
                if str(codes_get(msg, "shortName")) != "sf":
                    continue
                step, member = int(codes_get(msg, "endStep")), int(codes_get(msg, "number"))
                if step not in STEPS or member not in MEMBERS:
                    continue
                units = str(codes_get(msg, "units")).lower()
                if units not in ("m", "m of water equivalent", "m of water equivalent(s)"):
                    raise RuntimeError("Unexpected ECMWF SF units: "+units)
                field = np.asarray(codes_get_array(msg, "values"), dtype=np.float64)
                if index is None:
                    index, ngrid = nearest(msg, points)
                if len(field) != ngrid:
                    raise RuntimeError("Inconsistent ECMWF SF grid")
                values[("sf", step, member)] = field[index]
                starts[(step, member)] = int(codes_get(msg, "startStep"))
            finally:
                codes_release(msg)
    if not values:
        raise RuntimeError("No ECMWF ensemble SF fields found")
    print("ECMWF snowfall SF records", len(values), "of", len(MEMBERS)*len(STEPS))
    return values, starts


def produce(fields, tp_starts, npoints, run, sf_fields=None, sf_starts=None, synoptic=None):
    synoptic = synoptic or {}
    by_day = {}
    for lead in range(4):
        day = (run + timedelta(days=lead)).strftime("%Y-%m-%d")
        steps = [lead * 24 + 12, lead * 24 + 24]
        snow_by_member, storm_by_member = [], []
        org_by_member, lift_by_member, shear_by_member = [], [], []
        rain_by_member = []
        # Falling snow: daily new snowfall, not instantaneous snow depth.
        falling_by_member = []
        if sf_fields and sf_starts:
            for member in MEMBERS:
                daily_sf = daily_rain_mm(sf_fields, sf_starts, member,
                                         lead*24, npoints, param="sf")
                if daily_sf is not None:
                    falling_by_member.append(daily_sf)
        for member in MEMBERS:
            rainfall = daily_rain_mm(fields, tp_starts, member, lead*24, npoints)
            if rainfall is not None:
                rain_by_member.append(rainfall)
            snow_at_steps, storm_at_steps = [], []
            org_at_steps, lift_at_steps, shear_at_steps = [], [], []
            previous_cp = np.zeros(npoints, dtype=np.float64) if lead == 0 else fields.get(
                ("cp", lead * 24, member), np.full(npoints, np.nan))
            for step in steps:
                sd = fields[("sd", step, member)]
                rsn = fields[("rsn", step, member)]
                depth = np.where(
                    (sd <= 0) & np.isfinite(sd), 0.0,
                    np.divide(100000.0 * sd, rsn,
                              out=np.full_like(sd, np.nan),
                              where=(rsn > 20) & (rsn < 800))
                )
                depth = np.where((depth >= 0) & (depth < 3000), depth, np.nan)
                snow_at_steps.append(depth)

                cp = fields[("cp", step, member)]
                accum = np.maximum(0, (cp - previous_cp) * 1000.0)
                gust_raw = fields.get(("10fg", step, member))
                gusts = (gust_raw * 3.6 if gust_raw is not None
                         else np.full(npoints, np.nan))
                cape = fields[("mucape", step, member)]
                # Surface dewpoint in Kelvin; missing values stay unavailable.
                dewpoint = fields.get(("2d", step, member))
                dewpoint_c = (dewpoint - 273.15 if dewpoint is not None
                              else np.full(npoints, np.nan))
                idx = np.fromiter(
                    (convective_tier(cape[i], accum[i], gusts[i], dewpoint_c[i]) or 0
                     for i in range(npoints)),
                    dtype=np.float64,
                    count=npoints
                )
                # CAPE and convective rain must be known; gust and dewpoint
                # are not prerequisites to lower-level convective signals.
                missing = ~np.isfinite(cape) | ~np.isfinite(accum)
                idx[missing] = np.nan
                storm_at_steps.append(idx)
                # Pressure levels, not geometric 0-6 km: 850-500 hPa shear.
                winds = [synoptic.get((p, lev, step, member)) for p, lev in
                         (("u", 850), ("v", 850), ("u", 500), ("v", 500))]
                shear = (shear_850_500_ms(*winds) if all(w is not None for w in winds)
                         else np.full(npoints, np.nan))
                omega = synoptic.get(("w", 700, step, member))
                if omega is None:
                    omega = np.full(npoints, np.nan)
                organized, lifted = organization_and_ascent(idx, shear, omega)
                org_at_steps.append(organized)
                lift_at_steps.append(lifted)
                shear_at_steps.append(shear)
                previous_cp = cp
            with np.errstate(all="ignore"):
                snow_max = np.where(np.all(np.isnan(snow_at_steps), axis=0), np.nan,
                                    np.nanmax(snow_at_steps, axis=0))
                storm_max = np.where(np.all(np.isnan(storm_at_steps), axis=0), np.nan,
                                     np.nanmax(storm_at_steps, axis=0))
            snow_by_member.append(snow_max)
            storm_by_member.append(storm_max)
            org_by_member.append(max_available(org_at_steps))
            lift_by_member.append(max_available(lift_at_steps))
            shear_by_member.append(max_available(shear_at_steps))

        snow = np.vstack(snow_by_member)
        storm = np.vstack(storm_by_member)
        fields_out = {}
        for level in (1, 3, 5, 10):
            valid = np.sum(np.isfinite(snow), axis=0)
            pct = np.where(valid>=5,
                np.sum((snow>=level)&np.isfinite(snow), axis=0) / np.maximum(valid,1)*100,
                np.nan)
            fields_out[f"snow{level}"] = pct
        for level in (1, 2, 3, 4, 5):
            valid = np.sum(np.isfinite(storm), axis=0)
            pct = np.where(valid>=5,
                np.sum((storm>=level)&np.isfinite(storm), axis=0) / np.maximum(valid,1)*100,
                np.nan)
            fields_out[f"storm{level}"] = pct
        with np.errstate(invalid="ignore"):
            fields_out["snow_mean_cm"] = np.nanmean(snow,axis=0)
            fields_out["storm_mean_level"] = np.nanmean(storm,axis=0)
        # Do not publish optional diagnostics unless >=5 real members exist.
        for field, matrix, pct in (
            ("storm_organized_pct", org_by_member, True),
            ("storm_ascent_support_pct", lift_by_member, True),
            ("shear_850_500_mean_ms", shear_by_member, False),
        ):
            summary = optional_ensemble_stat(np.stack(matrix), probability=pct)
            if summary is not None:
                fields_out[field] = summary
        if len(falling_by_member) == len(MEMBERS):
            falling = np.vstack(falling_by_member)
            if np.all(np.isfinite(falling)):
                # mm of water-equivalent snowfall over 24h. No snow-depth conversion.
                fields_out["snowfall_mean_mmwe"] = np.mean(falling, axis=0)
                for threshold, slug in ((0.1, "0p1"), (1, "1"), (3, "3"), (5, "5")):
                    fields_out["snowfall"+slug] = np.mean(falling >= threshold, axis=0) * 100
                print("ECMWF falling snowfall SF", day, "8 members,",
                      f"mean {np.min(fields_out['snowfall_mean_mmwe']):.2f}–"
                      f"{np.max(fields_out['snowfall_mean_mmwe']):.2f} mm water eq")
        else:
            print("WARNING: falling snowfall unavailable",day,
                  len(falling_by_member),"/",len(MEMBERS))
        if len(rain_by_member) == len(MEMBERS):
            rain = np.vstack(rain_by_member)
            if np.all(np.isfinite(rain)):
                fields_out["rain_mean_mm"] = np.mean(rain,axis=0)
                print(f"ECMWF rain 24h {day}: mean subset 8 members, "
                      f"{np.min(fields_out['rain_mean_mm']):.1f}–"
                      f"{np.max(fields_out['rain_mean_mm']):.1f} mm")
        else:
            print(f"WARNING: rain_mean_mm unavailable {day}: "
                  f"{len(rain_by_member)}/{len(MEMBERS)} valid members")
        by_day[day] = fields_out
    return by_day


def main():
    cfg = json.loads(POINTS.read_text(encoding="utf-8"))
    coords, zones = indexed_points(cfg["zones"])
    with tempfile.TemporaryDirectory() as tmp:
        client = Client(source=os.getenv("ECMWF_SOURCE", "ecmwf"),model="ifs",resol="0p25")
        file = Path(tmp)/"enfo-pf.grib2"
        response = client.retrieve(
            time=0,stream="enfo",type="pf",step=STEPS,
            number=MEMBERS,param=PARAMS,target=str(file))
        run = response.datetime
        if run.tzinfo is None:run=run.replace(tzinfo=timezone.utc)
        run=run.astimezone(timezone.utc)
        if run.hour!=0 or datetime.now(timezone.utc)-run>timedelta(hours=40):
            raise RuntimeError("Ensemble run is stale or not 00Z")
        fields, tp_starts = load_fields(file, coords)
        sf_fields, sf_starts = {}, {}
        try:
            sf_file = Path(tmp)/"snowfall-pf.grib2"
            sf_result = client.retrieve(
                date=run.strftime("%Y-%m-%d"), time=run.hour, stream="enfo",
                type="pf", step=STEPS, number=MEMBERS, param="sf",
                target=str(sf_file))
            sf_run = sf_result.datetime
            if sf_run.tzinfo is None:
                sf_run = sf_run.replace(tzinfo=timezone.utc)
            if sf_run.astimezone(timezone.utc) != run:
                raise RuntimeError("SF snowfall and other ENS fields from different runs")
            sf_fields, sf_starts = load_optional_snowfall(sf_file, coords)
        except Exception as exc:
            print("WARNING: ECMWF SF unavailable; keep snow depth and storm:",str(exc)[:250])
        # The synoptic diagnostics are optional and pinned to the base 00Z.
        # If they fail, the existing snow/rain/storm forecast remains valid.
        synoptic = {}
        for label, params, levels in (
            ("wind-850-500", ["u", "v"], [850, 500]),
            ("omega-700", ["w"], [700]),
        ):
            try:
                aux_file = Path(tmp) / ("synoptic-" + label + ".grib2")
                diag = client.retrieve(
                    date=run.strftime("%Y-%m-%d"), time=run.hour,
                    stream="enfo", type="pf", levtype="pl", levelist=levels,
                    step=STEPS, number=MEMBERS, param=params, target=str(aux_file))
                diag_run = diag.datetime
                if diag_run.tzinfo is None:
                    diag_run = diag_run.replace(tzinfo=timezone.utc)
                if diag_run.astimezone(timezone.utc) != run:
                    raise RuntimeError("Pressure-level run does not match base ENS run")
                loaded = load_synoptic_fields(aux_file, coords)
                synoptic.update(loaded)
                aux_file.unlink(missing_ok=True)
                print("ECMWF synoptic", label, len(loaded), "fields")
            except Exception as exc:
                print("WARNING optional synoptic field unavailable", label, str(exc)[:220])
        print("ECMWF TP stepRange:", 
              [(step, member, tp_starts.get((step,member))) 
               for step in (12,24,36,48,72,96) for member in MEMBERS[:1]])
    products = produce(fields,tp_starts,len(coords),run,sf_fields,sf_starts,synoptic)
    data = {}
    for day, fields in products.items():
        data[day] = {
            "valid_from_utc":(datetime.fromisoformat(day).replace(tzinfo=timezone.utc)).isoformat().replace("+00:00","Z"),
            "valid_to_utc":(datetime.fromisoformat(day).replace(tzinfo=timezone.utc)+timedelta(days=1)).isoformat().replace("+00:00","Z"),
            "fields": {
                name: {
                    zone: ([round(float(v),1) if np.isfinite(v) else None
                            for v in vals[start:end]])
                    for zone,(start,end) in zones.items()
                } for name,vals in fields.items()
            }
        }
    result={
        "schema":1,
        "provider":"ECMWF IFS ENS 8-member subset",
        "source":"https://www.ecmwf.int/en/forecasts/datasets/open-data",
        "license":"CC BY 4.0",
        "run_utc":run.isoformat().replace("+00:00","Z"),
        "generated_at_utc":datetime.now(timezone.utc).isoformat().replace("+00:00","Z"),
        "ensemble_members":MEMBERS,
        "sampling_interval_hours":12,
        "method":"8-member storm CAPE+CP+dewpoint+gust; optional 850-500hPa wind shear and omega700; snow cover and native snowfall SF",
        "warning":"8-member 12h subset, 0.25 degree grid; shear is 850-500hPa (NOT 0-6km), omega is 700hPa; NOT calibrated storm-severity probabilities",
        "zone_point_counts":{z:b-a for z,(a,b) in zones.items()},
        "days":data
    }
    OUT.write_text(json.dumps(result,ensure_ascii=False,separators=(",",":"))+"\n",encoding="utf-8")
    print("Saved",OUT,OUT.stat().st_size,"bytes",run,"run")


if __name__=="__main__":
    main()
