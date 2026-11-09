#!/usr/bin/env python3
"""KFS /diagramme GEFS backup, 100% NOAA NOMADS (no Open-Meteo).
8 genuine perturbed members; temperature, MSL pressure, 12-h precipitation,
and snow-cover probabilities at 1, 3, 5, 10 cm.
Forecasts every 12 h through 15 days; original 0.5-degree grid, sampled
at 0.5-degree French gridpoints. Never invent missing members/steps.
"""
from __future__ import annotations
import io
import json
import math
import os
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

import numpy as np
from scipy.spatial import cKDTree
from eccodes import codes_get, codes_get_array, codes_get_elements, codes_grib_new_from_file, codes_release

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "diagramme" / "gefs-noaa-8m.json"
MEMBERS = [3, 7, 11, 15, 19, 23, 27, 30]
STEPS = list(range(12, 361, 12))
LATS = [round(float(v), 2) for v in np.arange(41.0, 51.51, .5)]
LONS = [round(float(v), 2) for v in np.arange(-5.5, 10.01, .5)]
POINTS = np.array([(lat, lon) for lat in LATS for lon in LONS], dtype=np.float64)
NOMADS = "https://nomads.ncep.noaa.gov/cgi-bin/filter_gefs_atmos_0p50a.pl"
RETRY_HTTP = {429, 500, 502, 503, 504}
WORKERS = 3
FIELDS = ("temperature", "pression", "pluie_part", "neige_cm")
SNOW_THRESHOLDS_CM = (1, 3, 5, 10)
SAMPLE_INDEX = None

def cycle_candidates():
    now = datetime.now(timezone.utc)
    candidates = []
    for days in range(3):
        for hour in (0, 6, 12, 18):
            dt = (now - timedelta(days=days)).replace(hour=hour, minute=0, second=0, microsecond=0)
            # No fixed 9-hour delay: verify the actual +360 h GRIB product instead.
            if dt <= now - timedelta(hours=3) and now - dt < timedelta(hours=45):
                candidates.append(dt)
    return sorted(set(candidates), reverse=True)

def make_url(run, member, step, precip_only=False):
    filename = f"gep{member:02d}.t{run.hour:02d}z.pgrb2a.0p50.f{step:03d}"
    params = [
        ("file", filename),
        ("var_APCP", "on"), ("lev_surface", "on"),
    ]
    if not precip_only:
        params += [
            ("var_TMP", "on"), ("lev_2_m_above_ground", "on"),
            ("var_PRMSL", "on"), ("lev_mean_sea_level", "on"),
            ("var_SNOD", "on"),
        ]
    params += [
        ("subregion", ""), ("leftlon", "-6"), ("rightlon", "11"),
        ("toplat", "52"), ("bottomlat", "40"),
        ("dir", f"/gefs.{run:%Y%m%d}/{run.hour:02d}/atmos/pgrb2ap5"),
    ]
    return NOMADS + "?" + urlencode(params)

def download(run, member, step, precip_only=False):
    url = make_url(run, member, step, precip_only)
    for attempt in range(5):
        try:
            req = Request(url, headers={"User-Agent": "KFS-METEO/1.0 (gefs ensemble open data)"})
            with urlopen(req, timeout=50) as response:
                body = response.read(8_000_000)
            if body[:4] == b"GRIB" and b"7777" in body[-16:]:
                return body
            raise RuntimeError(f"NOAA non-GRIB response for GEFS member={member}, step={step}: {body[:85]!r}")
        except HTTPError as exc:
            if exc.code not in RETRY_HTTP or attempt >= 4:
                raise RuntimeError(f"NOAA HTTP {exc.code} GEFS {run:%Y%m%d} {run:%HZ} p{member:02d} +{step}") from exc
        except (TimeoutError, URLError):
            if attempt >= 4:
                raise
        time.sleep(min(3 * (attempt + 1) ** 2, 40))
    raise RuntimeError(f"NOAA unavailable p{member:02d} +{step}")

def get_index(msg):
    lats = np.asarray(codes_get_array(msg, "latitudes"), dtype=np.float64)
    lons = np.asarray(codes_get_array(msg, "longitudes"), dtype=np.float64)
    lons = np.where(lons > 180, lons-360, lons)
    fac = math.cos(math.radians(47))
    tree = cKDTree(np.column_stack((lats, lons*fac)))
    dist, indexes = tree.query(np.column_stack((POINTS[:, 0], POINTS[:, 1]*fac)))
    if np.max(dist) > .20:
        raise RuntimeError(f"Unexpected GEFS grid alignment, max {np.max(dist):.3f} degrees")
    return indexes.astype(int).tolist()

def decode(raw, run, member, step, grid_index, precip_only=False):
    import tempfile
    result = {}
    with tempfile.TemporaryFile() as f:
        f.write(raw)
        f.seek(0)
        while (h := codes_grib_new_from_file(f)) is not None:
            try:
                if int(codes_get(h, "dataDate")) != int(run.strftime("%Y%m%d")):
                    raise RuntimeError("Inconsistent GEFS GRIB initialization date")
                if int(codes_get(h, "dataTime")) != run.hour*100 or int(codes_get(h, "endStep")) != step:
                    raise RuntimeError("Inconsistent GEFS GRIB cycle or lead time")
                try:
                    actual_member = int(codes_get(h, "number"))
                    if actual_member != member:
                        raise RuntimeError("Unexpected GEFS ensemble member number")
                except (KeyError, ValueError):
                    pass
                kind = str(codes_get(h, "typeOfLevel"))
                level = int(codes_get(h, "level"))
                short = str(codes_get(h, "shortName")).lower()
                name = str(codes_get(h, "name")).lower()
                field = None
                if kind == "heightAboveGround" and level == 2 and (
                    short in ("2t", "t", "t2m") or "temperature" in name):
                    field = "temperature"
                elif kind.lower() in ("meansea", "meansealevel") and (
                    short in ("prmsl", "msl", "mslet") or "pressure" in name):
                    field = "pression"
                elif kind == "surface" and level == 0 and (
                    short in ("tp", "apcp") or name == "total precipitation"):
                    field = "pluie_part"
                elif kind == "surface" and level == 0 and (
                    short in ("sde", "snod") or name == "snow depth"):
                    field = "neige_cm"
                if field is None:
                    continue
                if precip_only and field != "pluie_part":
                    continue
                if field in result:
                    raise RuntimeError(f"Duplicate GEFS GRIB field {field} for +{step}")
                if grid_index[0] is None:
                    grid_index[0] = get_index(h)
                values = np.asarray(codes_get_elements(h, "values", grid_index[0]), dtype=float)
                if not np.all(np.isfinite(values)):
                    raise RuntimeError(f"GEFS GRIB contains missing values {field} p{member} +{step}")
                if field == "temperature":
                    if np.min(values) < 180 or np.max(values) > 340:
                        raise RuntimeError("GEFS invalid temperature units")
                    values -= 273.15
                elif field == "pression":
                    if np.min(values) < 85000 or np.max(values) > 110000:
                        raise RuntimeError("GEFS invalid pressure units")
                    values /= 100.0
                elif field == "pluie_part":
                    # NOAA APCP is an interval accumulation in kg m^-2 == mm.
                    if str(codes_get(h, "stepType")) != "accum" or                        int(codes_get(h, "startStep")) != step - 6:
                        raise RuntimeError(f"Not a 6h NOAA precipitation accumulation at +{step}")
                    if str(codes_get(h, "units")) != "kg m**-2":
                        raise RuntimeError("Unexpected NOAA APCP unit")
                    if np.min(values) < -0.001 or np.max(values) > 500:
                        raise RuntimeError("GEFS invalid six-hour precipitation")
                    values = np.maximum(values, 0)
                elif field == "neige_cm":
                    if str(codes_get(h, "units")) != "m" or                        str(codes_get(h, "stepType")) != "instant":
                        raise RuntimeError("Unexpected NOAA snow depth units or interval")
                    if np.min(values) < -0.00001 or np.max(values) > 10:
                        raise RuntimeError(f"GEFS invalid snow depth min={np.min(values)} max={np.max(values)} at +{step} p{member:02d}")
                    values = np.maximum(values, 0) * 100.0
                result[field] = values
            finally:
                codes_release(h)
    expected = {"pluie_part"} if precip_only else set(FIELDS)
    if set(result) != expected:
        raise RuntimeError(f"GEFS incomplete fields p{member:02d} +{step}: {sorted(result)}")
    return result

def main():
    run = None
    for candidate in cycle_candidates():
        try:
            # Probe both end-of-range and short-range fields; avoid incomplete runs.
            index = [None]
            decode(download(candidate, MEMBERS[0], 360), candidate, MEMBERS[0], 360, index)
            decode(download(candidate, MEMBERS[0], 12), candidate, MEMBERS[0], 12, index)
            run = candidate
            break
        except Exception as exc:
            print("GEFS run candidate unavailable:", candidate.isoformat(), str(exc)[:240], flush=True)
    if run is None:
        raise RuntimeError("No recent NOAA GEFS run with +12h and +360h available")

    print("GEFS selected run", run.isoformat(), flush=True)
    jobs = [(m,step,False) for step in STEPS for m in MEMBERS] + \
           [(m,step-6,True) for step in STEPS for m in MEMBERS]
    values = {}
    grid_index = [None]
    # Establish a stable grid index before running the fetch pool.
    first = decode(download(run, MEMBERS[0], STEPS[0]), run, MEMBERS[0], STEPS[0], grid_index)
    values[(MEMBERS[0], STEPS[0])] = first
    remaining = [item for item in jobs if item != (MEMBERS[0], STEPS[0], False)]
    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        pending = {pool.submit(download, run, m, step, only):(m,step,only)
                   for m,step,only in remaining}
        for k, future in enumerate(as_completed(pending), start=1):
            member,step,only=pending[future]
            values[(member,step)] = decode(future.result(), run, member, step,
                                           grid_index, precip_only=only)
            if k % 30 == 0:
                print(f"GEFS progress {k+1}/{len(jobs)}", flush=True)

    if len(values)!=len(jobs):
        raise RuntimeError("Missing member/lead-time pairs in NOAA GEFS")
    series = {name:[] for name in ("temperature", "pression", "pluie", "neige")}
    for step in STEPS:
        for name in ("temperature", "pression", "pluie"):
            if name == "pluie":
                # Two verified consecutive 6h accumulations -> real 12h total.
                matrix = np.vstack([
                    values[(m,step-6)]["pluie_part"] + values[(m,step)]["pluie_part"]
                    for m in MEMBERS
                ])
            else:
                matrix = np.vstack([values[(m,step)][name] for m in MEMBERS])
            q = np.percentile(matrix, [10,50,90], axis=0)
            merged = np.stack([q[0],q[1],q[2],np.mean(matrix,axis=0)],axis=1)
            series[name].append([[round(float(v),1) for v in x] for x in merged])
        snow = np.vstack([values[(m,step)]["neige_cm"] for m in MEMBERS])
        # Probability of actual GEFS-modelled snow cover at this valid time.
        # Not a probability of fresh snowfall in the preceding 12h.
        snow_probs = np.stack([np.mean(snow >= level, axis=0) * 100
                               for level in SNOW_THRESHOLDS_CM],axis=1)
        series["neige"].append([[round(float(p),1) for p in row]
                               for row in snow_probs])
    payload = {
        "schema":1, "provider":"NOAA NCEP GEFS, 8 genuine perturbed members",
        "source":"https://nomads.ncep.noaa.gov/", "run_utc":run.isoformat().replace("+00:00","Z"),
        "generated_at_utc":datetime.now(timezone.utc).isoformat().replace("+00:00","Z"),
        "members":MEMBERS, "model_resolution_degrees":.5, "grid_resolution_degrees":.5,
        "interval_hours":12, "precipitation_period_hours":12,
        "snow_threshold_cm":list(SNOW_THRESHOLDS_CM),
        "snow_probability_definition":"P(SNOD model snow depth >= threshold at forecast valid time)",
        "step_hours":STEPS, "latitudes":LATS, "longitudes":LONS,
        "series":series,
        "notice":"8 out of 30 perturbed members, not the full GEFS. Rain is total precipitation (liquid water equivalent including snow) over 12h. Snow probabilities describe depth on ground, not new snowfall."
    }
    OUTPUT.parent.mkdir(parents=True,exist_ok=True)
    OUTPUT.write_text(json.dumps(payload,separators=(",",":"))+"\n",encoding="utf-8")
    print("KFS GEFS independent backup published",run,len(STEPS),"steps",len(POINTS),"points",OUTPUT.stat().st_size,"bytes",flush=True)

if __name__=="__main__":
    main()
