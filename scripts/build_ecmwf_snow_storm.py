#!/usr/bin/env python3
"""KFS /proba free ECMWF IFS ENS: indicative snow cover and convective potential.

NOT official event probabilities. Uses 8 fixed, dispersed ensemble members and
two snapshots per UTC day (12-hourly); lower-resolution sampling than full ENS.
Snow height comes from ECMWF SD water equivalent and RSN density:
  snow_depth_cm = 100000 * sd_m_water_equivalent / rsn_kg_m3.
Convective tiers use CAPE + convective-precip increment + gusts on each member.
Do not infer thunderstorm severity or road snow cover from this output.
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
PARAMS = ["sd", "rsn", "mucape", "cp", "10fg"]


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
                count += 1
            finally:
                codes_release(msg)
    expected = len(STEPS) * len(MEMBERS) * len(PARAMS)
    missing = [(k, s, n) for k in PARAMS for s in STEPS for n in MEMBERS
               if (k, s, n) not in values]
    # Some runs omit the +96h gust field; this must not block snow or imply
    # zero wind. Other missing products are a hard failure.
    optional = {( "10fg", 96, member) for member in MEMBERS}
    required_missing = [k for k in missing if k not in optional]
    if required_missing:
        raise RuntimeError(f"ECMWF PF incomplete: {count}/{expected}; missing {required_missing[:5]}")
    if missing:
        print("Warn: optional ECMWF gust fields missing (not treated as zero):", missing)
    return values


def convective_tier(cape, precipitation_mm, gust_kmh):
    if not np.isfinite(cape) or not np.isfinite(precipitation_mm) or not np.isfinite(gust_kmh):
        return None
    if cape >= 3000 and precipitation_mm >= 5 and gust_kmh >= 90:
        return 5
    if cape >= 1600 and precipitation_mm >= 2.5 and gust_kmh >= 60:
        return 4
    if cape >= 900 and precipitation_mm >= 1 and gust_kmh >= 40:
        return 3
    if cape >= 400 and precipitation_mm >= 0.5:
        return 2
    if cape >= 150 and precipitation_mm >= 0.2:
        return 1
    return 0


def produce(fields, npoints, run):
    by_day = {}
    for lead in range(4):
        day = (run + timedelta(days=lead)).strftime("%Y-%m-%d")
        steps = [lead * 24 + 12, lead * 24 + 24]
        snow_by_member, storm_by_member = [], []
        for member in MEMBERS:
            snow_at_steps, storm_at_steps = [], []
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
                idx = np.fromiter(
                    (convective_tier(cape[i], accum[i], gusts[i]) or 0
                     for i in range(npoints)),
                    dtype=np.float64,
                    count=npoints
                )
                # Unknown values are never treated as zero.
                missing = ~np.isfinite(cape) | ~np.isfinite(accum) | ~np.isfinite(gusts)
                idx[missing] = np.nan
                storm_at_steps.append(idx)
                previous_cp = cp
            with np.errstate(all="ignore"):
                snow_max = np.where(np.all(np.isnan(snow_at_steps), axis=0), np.nan,
                                    np.nanmax(snow_at_steps, axis=0))
                storm_max = np.where(np.all(np.isnan(storm_at_steps), axis=0), np.nan,
                                     np.nanmax(storm_at_steps, axis=0))
            snow_by_member.append(snow_max)
            storm_by_member.append(storm_max)

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
        fields = load_fields(file, coords)
    products = produce(fields,len(coords),run)
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
        "method":"Indicative 8-member ensemble risk: SD+RSN snow depth; MU-CAPE+CP+gust convective potential",
        "warning":"Approximate subset and 12h sampling; not official thunderstorm or snow risk; grid 0.25 degrees",
        "zone_point_counts":{z:b-a for z,(a,b) in zones.items()},
        "days":data
    }
    OUT.write_text(json.dumps(result,ensure_ascii=False,separators=(",",":"))+"\n",encoding="utf-8")
    print("Saved",OUT,OUT.stat().st_size,"bytes",run,"run")


if __name__=="__main__":
    main()
