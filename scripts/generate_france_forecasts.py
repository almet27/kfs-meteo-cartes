#!/usr/bin/env python3
"""KFS Meteo: truthful France-focused 0-72 h forecast atlas.

Models:
 - ECMWF IFS, native 3-hour steps;
 - ECMWF AIFS Single, native 6-hour steps (never interpolate fake steps);
 - NOAA GFS, native 3-hour steps.
Data is taken from actual GRIB fields. In particular snowfall is *water
equivalent*, not centimetres of snow on the ground. For NOAA, GFS rain and snow are shown only as labelled, diagnostic
phase ESTIMATES derived from categorical NOAA rain/snow fields; mixed phase
is never silently classified as snow. Missing fields stay missing.

Writes temporary Actions artifacts for independent GitHub Releases. No Europe
forecast output is modified.
"""
from __future__ import annotations
import argparse
from datetime import datetime, timedelta, timezone
from pathlib import Path
import json
import math
import sys
import time

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.patheffects as pe
import numpy as np
import cartopy.crs as ccrs
import cartopy.feature as cf
import xarray as xr
from kfs_premium_palettes import (
    KFS_T850_CMAP, KFS_T850_NORM, KFS_T850_LEVELS,
    KFS_T850_TICKS, KFS_T850_ISOTHERMS, KFS_T850_COLD_ISOTHERMS,
)

EXTENT = (-6.6, 10.3, 41.0, 51.7)
STEP_BY_MODEL = {"ifs": 3, "aifs-single": 6, "gfs": 3, "aigfs": 6}
MODEL_LABELS = {"ifs": "ECMWF IFS", "aifs-single": "ECMWF AIFS", "gfs": "NOAA GFS", "aigfs": "NOAA AIGFS"}
VARS = ("t2m", "t850", "wind10m", "mslp", "precip_total", "rain", "snow")
RAIN_LEVELS = (0.1, .3, .6, 1, 2, 3, 5, 8, 12, 18, 25, 40, 60)
RAIN_COLORS = (
    "#C0EAF9", "#79CFFF", "#339DE8", "#276CCA",
    "#3249A8", "#289990", "#46BD50", "#A5DE32",
    "#F6E042", "#F4AE39", "#E86933", "#D72F51",
)
SNOW_COLORS = (
    "#D5F5FF", "#A6E5FF", "#73C9FF", "#499DF4",
    "#326ED2", "#4F4DC5", "#754ACB", "#984EDA",
    "#BF56C7", "#D4419A", "#AD267C", "#7D1C62",
)


def parse_datetime(v):
    if isinstance(v, datetime):
        return v.replace(tzinfo=timezone.utc) if v.tzinfo is None else v.astimezone(timezone.utc)
    parsed = datetime.fromisoformat(str(v).replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def iso(dt):
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def native_model(model):
    if model in ("ifs", "aifs-single"):
        from ecmwf.opendata import Client
        client = Client(source="ecmwf", model=model, resol="0p25")
        step = STEP_BY_MODEL[model]
        current = parse_datetime(client.latest(stream="oper", type="fc", step=step, param="2t"))
        return {"kind": "ecmwf", "client": client, "cycle": current}
    from herbie import Herbie
    now = datetime.now(timezone.utc)
    for lag in (4, 7, 10, 13, 16, 19, 22):
        candidate = (now - timedelta(hours=lag)).replace(
            hour=((now - timedelta(hours=lag)).hour // 6) * 6,
            minute=0, second=0, microsecond=0)
        try:
            h = Herbie(candidate.replace(tzinfo=None), model=model,
                       product="pgrb2.0p25" if model == "gfs" else "sfc",
                       fxx=72, verbose=False)
            if h.grib is not None:
                return {"kind": "noaa", "cycle": candidate}
        except Exception:
            continue
    raise RuntimeError("GFS : aucun run +72 h disponible via NOAA")


def area(da):
    a = da.squeeze().load()
    lats = np.asarray(a.latitude.values, dtype=float)
    lons = ((np.asarray(a.longitude.values, dtype=float) + 180) % 360) - 180
    yy = np.where((lats >= EXTENT[2] - .65) & (lats <= EXTENT[3] + .65))[0]
    xx = np.where((lons >= EXTENT[0] - .65) & (lons <= EXTENT[1] + .65))[0]
    xx = xx[np.argsort(lons[xx])]
    if len(xx) < 12 or len(yy) < 12:
        raise ValueError("France: insufficient GRIB grid coverage")
    v = np.asarray(a.values)[np.ix_(yy, xx)]
    if not np.isfinite(v).any():
        raise ValueError("Field has no finite values over France")
    return lons[xx], lats[yy], v, str(a.attrs.get("units", "")), dict(a.attrs)


def ecmwf_field(state, step, key, out):
    param = "t" if key == "t850" else key
    name = {"2t": "t2m", "10u": "u10", "10v": "v10",
            "t850": "t", "sf": "sf", "tp": "tp", "msl": "msl"}[key]
    file = out / f"{param}-{step:03}-{key}.grib2"
    kwargs = dict(stream="oper", type="fc", date=state["cycle"].strftime("%Y-%m-%d"),
                  time=state["cycle"].hour, step=step, param=param,
                  target=str(file))
    if key == "t850":
        kwargs["levelist"] = 850
    try:
        state["client"].retrieve(**kwargs)
        ds = xr.open_dataset(file, engine="cfgrib", backend_kwargs={"indexpath": ""})
        try:
            if name not in ds:
                raise ValueError("Missing GRIB variable: " + name)
            return area(ds[name])
        finally:
            ds.close()
    finally:
        file.unlink(missing_ok=True)


def gfs_field(state, step, key):
    from herbie import Herbie
    model=state["model"]
    product=("pgrb2.0p25" if model=="gfs" else
             ("pres" if key=="t850" else "sfc"))
    patt = {
        "2t": r":TMP:2 m above ground:",
        "t850": r":TMP:850 mb:",
        "10u": r":UGRD:10 m above ground:",
        "10v": r":VGRD:10 m above ground:",
        "msl": r":PRMSL:mean sea level:",
        "tp": r":APCP:surface:",
        "crain": r":CRAIN:surface:[0-9]+ hour fcst:",
        "csnow": r":CSNOW:surface:[0-9]+ hour fcst:",
        "cicep": r":CICEP:surface:[0-9]+ hour fcst:",
        "cfrzr": r":CFRZR:surface:[0-9]+ hour fcst:",
    }[key]
    # NOAA AIGFS can briefly publish a GRIB index before a subset becomes
    # reachable from every mirror. Retry the SAME cycle and SAME field only.
    retries = 3 if model == "aigfs" else 1
    for attempt in range(retries):
        try:
            h = Herbie(state["cycle"].replace(tzinfo=None), model=model,
                       product=product, fxx=step, verbose=False)
            ds = h.xarray(patt, remove_grib=True)
            if ds is None or len(ds.data_vars) != 1:
                raise ValueError("GFS field unavailable/ambiguous: " + key)
            try:
                return area(ds[list(ds.data_vars)[0]])
            finally:
                ds.close()
        except (OSError, FileNotFoundError) as exc:
            if attempt == retries - 1:
                raise
            print("NOAA mirror retry", model, step, key, attempt + 1,
                  str(exc)[:140], flush=True)
            time.sleep(2 + attempt * 2)


def field(state, step, key, tmp):
    if state["kind"] == "ecmwf":
        return ecmwf_field(state, step, key, tmp)
    return gfs_field(state, step, key)


def common_grid(*xs):
    ref = xs[0]
    for item in xs[1:]:
        if not (np.array_equal(ref[0], item[0]) and np.array_equal(ref[1], item[1])):
            raise ValueError("Fields use different grids; no interpolation")
    return ref[0], ref[1]


def ecmwf_precip_mm(curr, prev, step, earlier):
    """Respect GRIB stepRange. Never subtract a native single-interval field."""
    value = np.asarray(curr[2], dtype=float)
    units = curr[3].strip()
    if units in ("m", "m of water equivalent"):
        value = value * 1000
    elif units in ("kg m**-2", "kg m-2", "kg m^-2", "mm"):
        pass
    else:
        raise ValueError("Unknown ECMWF precipitation unit: " + units)
    if not np.isfinite(value).all() or np.nanmin(value) < -1e-3:
        raise ValueError("Invalid ECMWF precipitation field")
    grib = curr[4]
    range_text = str(grib.get("GRIB_stepRange", ""))
    # For a native single interval e.g. 3-6, do not difference.
    if "-" in range_text:
        begin = int(range_text.split("-")[0])
        end = int(range_text.split("-")[-1])
        if end != step:
            raise ValueError("GRIB stepRange does not match target")
        if begin == earlier:
            return np.clip(value, 0, None), "native_interval"
        if begin != 0:
            raise ValueError("Unsupported GRIB accumulation interval: " + range_text)
    # First native step begins at +0; accumulated precipitation is already the
    # 0..step total. At later steps, cumulative fields need differencing.
    if prev is None:
        if earlier == 0:
            return np.maximum(0, value), "first_interval_since_run"
        raise ValueError("Previous accumulation missing; refusing to invent interval")
    common_grid(curr, prev)
    old = np.asarray(prev[2], dtype=float)
    old_units = prev[3].strip()
    if old_units in ("m", "m of water equivalent"):
        old = old * 1000
    elif old_units not in ("kg m**-2", "kg m-2", "kg m^-2", "mm"):
        raise ValueError("Previous ECMWF precipitation unit unexpected: " + old_units)
    diff = value - old
    if np.nanmin(diff) < -0.15:
        raise ValueError("Accumulation decreased unexpectedly")
    return np.maximum(0, diff), "cumulative_difference"


def palette():
    from matplotlib.colors import ListedColormap, BoundaryNorm
    from matplotlib import colormaps
    rain = ListedColormap(RAIN_COLORS)
    snow = ListedColormap(SNOW_COLORS)
    return {
        "t2m": (colormaps["turbo"], None, np.arange(-25, 41, 2), "Température 2 m (°C)"),
        "t850": (KFS_T850_CMAP, KFS_T850_NORM, KFS_T850_LEVELS, "Température 850 hPa (°C)"),
        "wind10m": (colormaps["turbo"], None, (0, 5, 10, 15, 20, 30, 40, 55, 70, 90, 110, 140),
                    "Vent à 10 m (km/h)"),
        "mslp": (colormaps["GnBu"], None, np.arange(960, 1061, 4),
                 "Pression réduite à la mer (hPa)"),
        "precip_total": (rain, BoundaryNorm(RAIN_LEVELS, rain.N),
                 RAIN_LEVELS, "Précipitations totales (mm sur la période)"),
        "rain": (rain, BoundaryNorm(RAIN_LEVELS, rain.N),
                 RAIN_LEVELS, "Pluie estimée (mm sur la période)"),
        "snow": (snow, BoundaryNorm(RAIN_LEVELS, snow.N),
                 RAIN_LEVELS, "Neige : équivalent-eau (mm sur la période)"),
    }


def render(lon, lat, values, model, run, step, metric, folder, note=""):
    spec = palette()
    cmap, norm, levels, label = spec[metric]
    fig = plt.figure(figsize=(9.8, 7.8), dpi=115)
    ax = fig.add_subplot(111, projection=ccrs.PlateCarree())
    ax.set_extent(EXTENT, crs=ccrs.PlateCarree())
    ax.add_feature(cf.LAND, facecolor="#EDF0EC", zorder=0)
    ax.add_feature(cf.OCEAN, facecolor="#D7E8F3", zorder=0)
    if metric in ("rain", "snow", "precip_total"):
        values=np.ma.masked_invalid(values)
        values=np.ma.masked_less(values,0.1)
    kw = {"cmap": cmap, "extend": "both", "transform": ccrs.PlateCarree()}
    if norm is not None:
        kw["norm"] = norm
    shade = ax.contourf(lon, lat, values, levels=levels, **kw)
    if metric in ("t850", "t2m"):
        # Display the actual scalar field values at weather map anchor points.
        # Values come from the nearest native GRIB cell: no made-up interpolation.
        locations = [
            (-4.49,48.38,"Brest"),(-1.55,47.22,"Nantes"),
            (-0.58,44.84,"Bordeaux"),(1.44,43.60,"Toulouse"),
            (2.35,48.86,"Paris"),(3.06,50.63,"Lille"),
            (1.10,49.44,"Rouen"),(1.26,45.83,"Limoges"),
            (3.09,45.78,"Clermont"),(4.84,45.76,"Lyon"),
            (5.37,43.30,"Marseille"),(3.88,43.61,"Montpellier"),
            (5.39,43.94,"Avignon"),(7.75,48.58,"Strasbourg"),
            (5.04,47.32,"Dijon"),(7.26,43.71,"Nice"),
        ]
        a=np.asarray(values,dtype=float)
        ix=np.asarray(lon,dtype=float);iy=np.asarray(lat,dtype=float)
        for xpoint,ypoint,city in locations:
            col=int(np.abs(ix-xpoint).argmin())
            row=int(np.abs(iy-ypoint).argmin())
            measured=a[row,col]
            if not np.isfinite(measured):
                continue
            txt=ax.text(xpoint,ypoint,f"{measured:+.0f}°",fontsize=8.3,
                        ha="center",va="center",weight="bold",color="#1D2431",
                        transform=ccrs.PlateCarree(),zorder=8)
            txt.set_path_effects([pe.Stroke(linewidth=2.35,foreground="white"),
                                  pe.Normal()])
    if metric == "t2m":
        lines=tuple(range(-25,41,5))
        cc=ax.contour(lon,lat,values,levels=lines,
                      colors="#263442",linewidths=[1.1 if v in (-10,-5,0) else .48 for v in lines],
                      alpha=.72,transform=ccrs.PlateCarree(),zorder=4)
        ll=ax.clabel(cc,inline=True,fontsize=7,fmt="%d",colors="#192636")
        for label in ll:
            label.set_path_effects([pe.Stroke(linewidth=1.8,foreground="white"),pe.Normal()])
    if metric == "t850":
        isotherm_contours = ax.contour(lon, lat, values, levels=KFS_T850_ISOTHERMS,
                         colors="#17202A",
                         linewidths=[1.18 if n in KFS_T850_COLD_ISOTHERMS else .45
                                     for n in KFS_T850_ISOTHERMS],
                         transform=ccrs.PlateCarree(), zorder=4)
        labels = ax.clabel(isotherm_contours, levels=KFS_T850_ISOTHERMS,
                          inline=True, inline_spacing=3, fontsize=8,
                          fmt="%d", colors="#17202A")
        boldlabels = ax.clabel(isotherm_contours, levels=KFS_T850_COLD_ISOTHERMS,
                          inline=True, fontsize=10.5, fmt="%d", colors="#17202A")
        for l in labels + boldlabels:
            l.set_path_effects([pe.Stroke(linewidth=2.1, foreground="white"), pe.Normal()])
    if metric == "mslp":
        contour = ax.contour(lon, lat, values,
                             levels=np.arange(960, 1056, 5), colors="white",
                             linewidths=1.2, transform=ccrs.PlateCarree(), zorder=4)
        labels = ax.clabel(contour, inline=True, fontsize=8, fmt="%d", colors="white")
        for l in labels:
            l.set_path_effects([pe.Stroke(linewidth=2, foreground="#142238"), pe.Normal()])
    ax.coastlines("10m", linewidth=.7, color="#182A3E", zorder=5)
    ax.add_feature(cf.BORDERS, linewidth=.6, edgecolor="#172A3B", zorder=5)
    ax.set_title("KFS MÉTÉO  •  FRANCE  •  " + MODEL_LABELS[model] +
                 f"\n{label}  |  +{step} h  |  validité {iso(run + timedelta(hours=step))}",
                 fontsize=12, weight="bold", pad=11)
    cb = fig.colorbar(shade, ax=ax, orientation="horizontal", shrink=.82, pad=.04)
    cb.set_label(label, fontsize=9)
    footer = "Run " + iso(run) + " UTC  •  " + ("ECMWF Open Data CC BY 4.0" if model != "gfs" else "NOAA NCEP")
    if note:
        footer += "  •  " + note
    fig.text(.04, .024, footer, fontsize=7.8)
    path = folder / f"{metric}-h{step:03}.png"
    fig.savefig(path, dpi=115, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    return str(path)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", required=True, choices=sorted(STEP_BY_MODEL))
    parser.add_argument("--steps", help="Comma-separated subset for smoke tests")
    parser.add_argument("--max-hour", type=int, default=72)
    parser.add_argument("--output", default="forecast-maps/france")
    args = parser.parse_args()
    stride = STEP_BY_MODEL[args.model]
    steps = list(range(stride, min(72, args.max_hour) + 1, stride))
    if args.steps:
        selected = [int(n) for n in args.steps.split(",")]
        if any(n not in steps for n in selected):
            raise ValueError("Requested step not available natively")
        steps = sorted(set(selected))
    state = native_model(args.model)
    state["model"] = args.model
    run = state["cycle"]
    folder = Path(args.output) / args.model
    folder.mkdir(parents=True, exist_ok=True)
    tmp = folder / "_tmp"
    tmp.mkdir(exist_ok=True)
    manifests = {}
    errors = {}
    cache = {}
    for step in steps:
        print("KFS FRANCE", args.model, iso(run), step, flush=True)
        fields = {}
        requested = (("2t", "t850", "10u", "10v", "msl", "tp", "sf")
                     if state["kind"] == "ecmwf" else
                     ("2t","t850","10u","10v","msl","tp",
                      "crain","csnow","cfrzr","cicep") if args.model=="gfs" else
                     ("2t","t850","10u","10v","msl","tp"))
        for param in requested:
            try:
                fields[param] = field(state, step, param, tmp)
            except Exception as exc:
                errors[f"{step}-{param}"] = str(exc)[:200]
        maps = {}
        candidates = {}
        try:
            t2 = fields["2t"]
            candidates["t2m"] = (t2[0], t2[1], t2[2] - 273.15, "")
        except KeyError:
            pass
        try:
            t = fields["t850"]
            candidates["t850"] = (t[0], t[1], t[2] - 273.15, "")
        except KeyError:
            pass
        try:
            u, v = fields["10u"], fields["10v"]
            lon, lat = common_grid(u, v)
            candidates["wind10m"] = (lon, lat, np.hypot(u[2], v[2]) * 3.6, "")
        except KeyError:
            pass
        try:
            p = fields["msl"]
            candidates["mslp"] = (p[0], p[1], p[2] / 100, "")
        except KeyError:
            pass
        if state["kind"] == "ecmwf":
            for param, name in (("tp", "tp"), ("sf", "sf")):
                if param in fields:
                    curr = fields[param]
                    prev = cache.get(param)
                    try:
                        mm, method = ecmwf_precip_mm(curr, prev, step, step-stride)
                        candidates["total_precip" if param == "tp" else "snow"] = (
                            curr[0], curr[1], mm, method)
                    except Exception as exc:
                        errors[f"{step}-{param}-window"] = str(exc)[:180]
                    cache[param] = curr
            if "total_precip" in candidates:
                candidates["precip_total"] = candidates["total_precip"]
            if "total_precip" in candidates and "snow" in candidates:
                a, b = candidates["total_precip"], candidates["snow"]
                lon, lat = common_grid((a[0],a[1]), (b[0],b[1]))
                candidates["rain"] = (lon, lat, np.maximum(0, a[2] - b[2]),
                                       "pluie = total - neige, équivalent-eau")
        else:
            if "tp" in fields:
                tp=fields["tp"]
                # NOAA APCP is normally already a window accumulation.
                units=tp[3].strip()
                if units not in ("kg m**-2", "kg m-2", "kg m^-2", "mm"):
                    errors[f"{step}-tp-units"] = "Unité NOAA inconnue: " + units
                else:
                    candidates["precip_total"] = (tp[0], tp[1], np.maximum(0,tp[2]),
                                                   "cumul total; ne distingue pas pluie et neige")
                    # GFS: use NOAA native categorical precipitation *at the
                    # valid instant*. This is a diagnostic phase classification,
                    # not a native 3-hour rain/snow accumulation.
                    # Do not classify mixed/freezing/ice-pellet cells as snow.
                    required=("crain","csnow","cfrzr","cicep")
                    if all(x in fields for x in required):
                        try:
                            masks=[fields[k] for k in required]
                            common_grid(tp,*masks)
                            raw=[np.asarray(m[2],dtype=float) for m in masks]
                            valid=np.logical_and.reduce([
                                np.isfinite(v)&(v>=0)&(v<=1) for v in raw])
                            rainflag,snowflag,freeze,ice=raw
                            wet=np.asarray(tp[2],dtype=float)>0.1
                            onlyrain=(rainflag>.5)&(snowflag<.5)&(freeze<.5)&(ice<.5)
                            onlysnow=(snowflag>.5)&(rainflag<.5)&(freeze<.5)&(ice<.5)
                            known=(onlyrain|onlysnow)&valid
                            # Even if rare, ambiguous precip cells stay unclassified.
                            # Dry cells are zero, unknown *wet* cells are NaN.
                            quality=float(np.count_nonzero(known&wet))/max(1,int(np.count_nonzero(wet)))
                            rain=np.where(~wet,0,np.where(valid&onlyrain,tp[2],
                                          np.where(valid&onlysnow,0,np.nan)))
                            snow=np.where(~wet,0,np.where(valid&onlysnow,tp[2],
                                          np.where(valid&onlyrain,0,np.nan)))
                            if quality>=.5 or not np.any(wet):
                                note=("PHASE ESTIMÉE: pluie/neige NOAA au temps de validité;"
                                      " cellules mixtes/non déterminées grisées")
                                candidates["rain"]=(tp[0],tp[1],rain,note)
                                candidates["snow"]=(tp[0],tp[1],snow,note)
                            else:
                                errors[f"{step}-phase"]="Categorical GFS phase too ambiguous: "+str(round(quality*100))+" % classified wet cells"
                        except Exception as exc:
                            errors[f"{step}-phase"]="GFS phase fields invalid: "+str(exc)[:150]
                    else:
                        errors[f"{step}-phase"]="No four categorical NOAA fields; no artificial rain/snow classification"
        for metric, (lon, lat, values, note) in candidates.items():
            if metric not in VARS:
                continue
            try:
                if metric not in ("rain","snow","precip_total") and not np.isfinite(values).all():
                    raise ValueError("Non-finite field")
                if metric in ("rain","snow","precip_total") and np.isfinite(values).mean()<0.2:
                    raise ValueError("Insufficient valid precipitation cells")
                path = render(lon, lat, values, args.model, run, step, metric, folder, note)
                maps[metric] = {"path":path, "note":note}
            except Exception as exc:
                errors[f"{step}-{metric}-draw"] = str(exc)[:200]
        manifests[str(step)] = maps
    manifest = {
        "schema": 1,
        "generated_utc": iso(datetime.now(timezone.utc)),
        "run_utc": iso(run), "model": args.model,
        "model_name": MODEL_LABELS[args.model],
        "area": "France", "extent_lonlat": list(EXTENT),
        "native_step_h": stride, "requested_steps_h": steps,
        "maps": manifests, "errors": errors,
        "note": "No model field or missing forecast timestep is invented",
    }
    (folder/"metadata.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2)+"\n", encoding="utf-8")
    print("Done, maps:", sum(len(x) for x in manifests.values()),
          "errors:",len(errors),flush=True)
    # Success requires at least one fully verifiable step for prototype testing.
    if not any("t850" in x and "t2m" in x and "mslp" in x for x in manifests.values()):
        raise RuntimeError("No complete temperature/pressure triplet generated")
    return 0


if __name__=="__main__":
    sys.exit(main())
