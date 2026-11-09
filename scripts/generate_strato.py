#!/usr/bin/env python3
"""KFS MÉTÉO /strato : cartes ECMWF IFS des niveaux 10, 50 et 100 hPa.

Champs réels (t, u, v, gh) du même run ECMWF Open Data, sans Open-Meteo.
La présence d'un vent zonal négatif à une échéance ne constitue pas, à elle seule,
la confirmation d'un réchauffement stratosphérique majeur.
"""
import json
import math
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.path as mpath
import matplotlib.patheffects as pe
import numpy as np
import xarray as xr
import cartopy.crs as ccrs
import cartopy.feature as cfeature
from ecmwf.opendata import Client

ROOT = Path("strato")
ROOT.mkdir(exist_ok=True)
LEVELS = (10, 50, 100)
STEPS = (24, 72, 120, 168, 240, 360)
PARAMS = ("t", "u", "v", "gh")
MODEL = "ifs"
SOURCE = "ECMWF IFS Open Data · CC BY 4.0"
METADATA = ROOT / "metadata.json"
UTC = timezone.utc
now = datetime.now(UTC)
client = Client(source="ecmwf", model=MODEL, resol="0p25")
try:
    previous = json.loads(METADATA.read_text("utf-8"))
except (ValueError, OSError):
    previous = {}

def date_utc(value):
    dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    return dt.replace(tzinfo=UTC) if dt.tzinfo is None else dt.astimezone(UTC)

def find_cycle():
    # 00Z et 12Z ont les champs ouverts jusqu'à +360 h.
    # La disponibilité à +360 h évite de mélanger un 06/18Z court.
    cycle = client.latest(
        stream="oper", type="fc", step=360, param="t", levelist=10
    )
    dt = date_utc(cycle)
    if dt.hour not in (0, 12):
        raise ValueError("Dernier cycle long ECMWF inattendu : " + dt.isoformat())
    if now - dt > timedelta(days=3):
        raise RuntimeError("Cycle ECMWF trop ancien")
    return dt

def read_grib(path):
    # Les quatre paramètres ont les mêmes niveaux, échéance et grille.
    ds = xr.open_dataset(path, engine="cfgrib", backend_kwargs={"indexpath": ""})
    try:
        if not set(PARAMS).issubset(ds.data_vars):
            raise RuntimeError("Champs GRIB incomplets : " + repr(list(ds.data_vars)))
        if "isobaricInhPa" not in ds.coords:
            raise RuntimeError("Coordonnée isobare manquante")
        lon = np.asarray(ds.longitude.values, dtype=float)
        lat = np.asarray(ds.latitude.values, dtype=float)
        ilon = np.argsort((lon + 180.0) % 360.0)
        ilat = np.flatnonzero(lat >= 15)
        x = ((lon[ilon] + 180.0) % 360.0) - 180.0
        y = lat[ilat]
        data = {}
        for level in LEVELS:
            data[level] = {}
            for p in PARAMS:
                da = ds[p].sel(isobaricInhPa=level)
                a = np.asarray(da.values[np.ix_(ilat, ilon)], dtype=float)
                if a.shape != (len(y), len(x)) or not np.all(np.isfinite(a)):
                    raise ValueError("Grille invalide pour " + str((level, p)))
                data[level][p] = a
        if np.nanmedian(data[10]["t"]) < 150:
            raise ValueError("Températures non exprimées en Kelvin")
        if not 25000 < np.nanmedian(data[10]["gh"]) < 35000:
            raise ValueError("Geopotentiel GH 10 hPa hors plage physique")
        if not 17000 < np.nanmedian(data[50]["gh"]) < 24000:
            raise ValueError("Geopotentiel GH 50 hPa hors plage physique")
        if not 13000 < np.nanmedian(data[100]["gh"]) < 19000:
            raise ValueError("Geopotentiel GH 100 hPa hors plage physique")
        return x, y, data
    finally:
        ds.close()

def polar_canvas(title, subtitle):
    fig = plt.figure(figsize=(9.5, 10.4), dpi=125, facecolor="#09172b")
    ax = fig.add_axes((0.075, 0.115, 0.85, 0.75),
                      projection=ccrs.NorthPolarStereo(central_longitude=0))
    ax.set_facecolor("#102743")
    ax.set_extent([-180, 180, 19, 90], crs=ccrs.PlateCarree())
    theta = np.linspace(0, 2 * np.pi, 121)
    boundary = mpath.Path(np.stack([np.sin(theta), np.cos(theta)], axis=1)
                          * 0.5 + 0.5)
    ax.set_boundary(boundary, transform=ax.transAxes)
    ax.coastlines("110m", color="#dae5ee", linewidth=0.55, alpha=0.83)
    ax.add_feature(cfeature.BORDERS, edgecolor="#9baec4", linewidth=0.30)
    ax.gridlines(color="#8297b2", linewidth=0.4, alpha=0.42)
    for latitude in (30, 60):
        angles = np.linspace(-180, 180, 361)
        ax.plot(angles, np.full_like(angles, latitude),
                color="#e1edf7" if latitude == 60 else "#91abc7",
                linewidth=1.25 if latitude == 60 else .6,
                linestyle="--", alpha=.82, transform=ccrs.PlateCarree())
    fig.text(.5, .958, title, ha="center", color="#ffffff",
             fontsize=18, weight="bold")
    fig.text(.5, .921, subtitle, ha="center", color="#b5cadd", fontsize=10)
    fig.text(.5, .042, SOURCE + " | 60°N : cercle tireté",
             ha="center", color="#b8cbdc", fontsize=9)
    return fig, ax

def render(x, y, fields, level, step, cycle, kind):
    valid = cycle + timedelta(hours=step)
    title = "KFS MÉTÉO | STRATOSPHÈRE | " + str(level) + " hPa"
    subtitle = ("IFS " + cycle.strftime("%d/%m/%Y %HZ") + " · +"
                + str(step) + " h · " + valid.strftime("%d/%m %H:%M UTC"))
    fig, ax = polar_canvas(title, subtitle)
    temp = fields["t"] - 273.15
    u, v, gh = fields["u"], fields["v"], fields["gh"]
    w = np.hypot(u, v)
    x2, y2 = np.meshgrid(x, y)
    if kind == "temperature":
        levels = np.arange(-100, 61, 5)
        shade = ax.contourf(x2, y2, temp, levels=levels,
                            cmap="coolwarm", extend="both",
                            transform=ccrs.PlateCarree())
        isolines = np.arange(-100, 61, 10)
        contour = ax.contour(x2, y2, temp, levels=isolines,
                             colors="#122b47", alpha=.68, linewidths=.55,
                             transform=ccrs.PlateCarree())
        ax.clabel(contour, contour.levels[::2], fmt="%d°",
                  fontsize=7.5, inline=True)
        label = "Température stratosphérique (°C)"
    else:
        shade = ax.contourf(x2, y2, w, levels=np.arange(0, 121, 5),
                            cmap="turbo", extend="max",
                            transform=ccrs.PlateCarree())
        minimum = float(np.nanmin(gh))
        maximum = float(np.nanmax(gh))
        contour_levels = np.arange(math.floor(minimum / 300) * 300,
                                   math.ceil(maximum / 300) * 300 + 1, 300)
        if len(contour_levels) > 1:
            contours = ax.contour(x2, y2, gh, levels=contour_levels,
                                  colors="#ffffff", alpha=.85,
                                  linewidths=.68,
                                  transform=ccrs.PlateCarree())
            ax.clabel(contours, contours.levels[::2], fmt="%d",
                      inline=True, fontsize=7)
        label = "Vitesse du vent (m/s) · isohypses blanches : mètres"
    bar = fig.colorbar(shade, ax=ax, orientation="horizontal",
                       pad=.055, shrink=.81, aspect=32)
    bar.set_label(label, color="#eef4fd", fontsize=10)
    bar.ax.tick_params(colors="#eef4fd", labelsize=8)
    bar.outline.set_edgecolor("#a8b9cb")
    if level == 10:
        i60 = int(np.argmin(np.abs(y - 60.0)))
        u60 = float(np.nanmean(u[i60, :]))
        state = ("vents d'est à 60°N" if u60 < 0 else "vents d'ouest à 60°N")
        fig.text(.5, .895,
                 "Vent zonal moyen 10 hPa / 60°N : "
                 + f"{u60:+.1f} m/s" + " · " + state,
                 ha="center", color="#f8d58f", fontsize=10.5,
                 weight="bold")
    out = ROOT / f"ifs-h{step:03}-{level}hpa-{kind}.png"
    fig.savefig(out, facecolor=fig.get_facecolor(), dpi=125)
    plt.close(fig)
    return out

def main():
    cycle = find_cycle()
    stamp = cycle.strftime("%Y-%m-%dT%H:%M:%SZ")
    ready = previous.get("run_utc") == stamp and all(
        (ROOT / f"ifs-h{step:03}-{level}hpa-{kind}.png").is_file()
        for step in STEPS for level in LEVELS
        for kind in ("temperature", "vortex")
    )
    if ready and not os.getenv("KFS_FORCE_STRATO"):
        print("STRATO : cartes déjà à jour pour", stamp, flush=True)
        return

    print("STRATO : nouveau cycle ECMWF", stamp, flush=True)
    current = {
        "schema": 1, "model": "ifs", "source": SOURCE,
        "generated_utc": now.isoformat(), "run_utc": stamp,
        "description": "Vortex et température. Vent U 10 hPa à 60°N diagnostique ; "
                       "valeur négative ponctuelle ≠ événement SSW confirmé.",
        "levels_hpa": list(LEVELS), "forecast_hours": list(STEPS),
        "maps": {}, "zonal_wind_10hpa_60n": {}, "errors": {},
    }
    for step in STEPS:
        target = ROOT / f".strato-h{step:03}.grib2"
        try:
            client.retrieve(
                date=cycle.strftime("%Y-%m-%d"), time=cycle.hour,
                stream="oper", type="fc", step=step,
                levtype="pl", param=list(PARAMS), levelist=list(LEVELS),
                target=str(target))
            x, y, all_levels = read_grib(target)
            for level in LEVELS:
                f = all_levels[level]
                results = {}
                for kind in ("temperature", "vortex"):
                    output = render(x, y, f, level, step, cycle, kind)
                    results[kind] = "strato/" + output.name
                current["maps"].setdefault(str(level), {})[str(step)] = results
                if level == 10:
                    idx = int(np.argmin(np.abs(y - 60)))
                    current["zonal_wind_10hpa_60n"][str(step)] = round(
                        float(np.nanmean(f["u"][idx, :])), 1)
                print("STRATO OK", step, level, flush=True)
        except Exception as error:
            current["errors"][str(step)] = str(error)[:350]
            print("STRATO ÉCHEC", step, str(error), flush=True)
        finally:
            target.unlink(missing_ok=True)

    # En cas de rupture du flux météo, garder le précédent catalogue valide.
    count = sum(len(slots) for slots in current["maps"].values())
    if count == 0:
        raise RuntimeError("Aucune carte générée ; ancien catalogue préservé. "
                           + str(current["errors"]))
    METADATA.write_text(
        json.dumps(current, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8")
    print(f"STRATO : {count} couples de cartes, run {stamp}", flush=True)
    if current["errors"]:
        print("STRATO : échéances indisponibles", current["errors"], flush=True)

if __name__ == "__main__":
    main()
