#!/usr/bin/env python3
"""Planche /strato : anomalies GH 10 hPa (ECMWF – NOAA 1991-2020) + vent zonal.

Ne produit JAMAIS d'anomalies synthétiques. Si la climatologie NOAA manque,
la planche est omise et les cartes /strato existantes restent disponibles.
"""
from datetime import datetime, timedelta
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.path as mpath
import numpy as np
from matplotlib.colors import BoundaryNorm
import cartopy.crs as ccrs
from netCDF4 import Dataset
from scipy.interpolate import RegularGridInterpolator

STEPS = (24, 72, 120, 168, 240, 360)
NCEP_HGT_URL = (
    "https://psl.noaa.gov/thredds/dodsC/Datasets/"
    "ncep.reanalysis.derived/pressure/hgt.day.ltm.1991-2020.nc"
)
CREDIT = "ECMWF IFS Open Data (CC BY 4.0) · NOAA NCEP/NCAR R1 1991–2020"


def climatology_day_index(valid):
    """365 jours sans 29 février; dates après le 28 février décalées en année bissextile."""
    if valid.month == 2 and valid.day == 29:
        return 58
    base = datetime(2001, valid.month, valid.day)
    return (base - datetime(2001, 1, 1)).days


def load_climatology(dates, lon, lat):
    """Lit seulement six tranches de 10 hPa NOAA, puis interpolation bilinéaire."""
    wanted = sorted(set(climatology_day_index(d) for d in dates))
    with Dataset(NCEP_HGT_URL) as ds:
        levels = np.asarray(ds.variables["level"][:], dtype=float)
        ilvl = int(np.argmin(np.abs(levels - 10.0)))
        if abs(levels[ilvl] - 10) > 0.1:
            raise ValueError("NOAA : niveau 10 hPa absent")
        lat0 = np.asarray(ds.variables["lat"][:], dtype=float)
        lon0 = np.asarray(ds.variables["lon"][:], dtype=float)
        if lat0.ndim != 1 or lon0.ndim != 1 or lon0.size < 100:
            raise ValueError("NOAA : grille climatologique invalide")
        if not np.all(np.diff(lon0) > 0):
            raise ValueError("NOAA : longitudes non ordonnées")
        source_lon = np.r_[lon0, 360.0]
        samples = {}
        xx, yy = np.meshgrid(np.mod(lon, 360), lat)
        queries = np.stack([yy.ravel(), xx.ravel()], axis=-1)
        ascending = bool(lat0[0] < lat0[-1])
        source_lat = lat0 if ascending else lat0[::-1]
        for idx in wanted:
            height = np.ma.filled(ds.variables["hgt"][idx, ilvl, :, :], np.nan)
            height = np.asarray(height, dtype=float)
            if height.shape != (lat0.size, lon0.size):
                raise ValueError("NOAA : climatologie 10 hPa incomplète")
            if not ascending:
                height = height[::-1, :]
            if not np.all(np.isfinite(height)) or not 25000 < np.nanmean(height) < 33000:
                raise ValueError("NOAA : valeurs géopotentielles invalides")
            periodic = np.column_stack([height, height[:, :1]])
            interpolate = RegularGridInterpolator(
                (source_lat, source_lon), periodic,
                method="linear", bounds_error=True)
            mapped = interpolate(queries).reshape(xx.shape)
            if not np.all(np.isfinite(mapped)):
                raise ValueError("NOAA : interpolation invalide")
            samples[idx] = mapped
    return samples


def build_overview(cycle, lon, lat, gh_fields, zonal, root=Path("strato")):
    """Produit une seule image Discord avec six cartes et la courbe IFS J+1–J+15.

    gh_fields: {forecast_hour: 10 hPa GH en mètres, même grille que lon/lat}.
    zonal: {forecast_hour: moyenne U à 60°N en m/s}.
    """
    if set(gh_fields) != set(STEPS):
        raise ValueError("Planche 10 hPa : six champs GH nécessaires")
    if len(zonal) < 12:
        raise ValueError("Planche 10 hPa : vents zonaux incomplets")
    lon = np.asarray(lon, dtype=float)
    lat = np.asarray(lat, dtype=float)
    valid_dates = [cycle + timedelta(hours=s) for s in STEPS]
    normal = load_climatology(valid_dates, lon, lat)
    anomalies = {}
    for step, valid in zip(STEPS, valid_dates):
        gh = np.asarray(gh_fields[step], dtype=float)
        if gh.shape != (lat.size, lon.size) or not np.all(np.isfinite(gh)):
            raise ValueError("ECMWF : GH 10 hPa incomplet à H+" + str(step))
        anomalies[step] = (gh - normal[climatology_day_index(valid)]) / 10.0
        if not np.all(np.isfinite(anomalies[step])):
            raise ValueError("Anomalie 10 hPa non finie")

    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    fig = plt.figure(figsize=(14.0, 17.5), dpi=145, facecolor="#0b1220")
    gs = fig.add_gridspec(
        3, 3, left=.06, right=.96, bottom=.105, top=.835,
        wspace=.12, hspace=.30, height_ratios=[1.0, 1.0, .76])
    fig.text(.06, .960, "KFS MÉTÉO  /  VORTEX POLAIRE", fontsize=25,
             color="white", fontweight="bold")
    fig.text(.06, .918, "ÉVOLUTION À 10 hPa · HÉMISPHÈRE NORD · J+1 À J+15",
             fontsize=15, color="#d2e1f5", weight="bold")
    fig.text(.06, .890, "RUN ECMWF IFS " + cycle.strftime("%d/%m/%Y · %HZ") +
             "   |   anomalies de hauteur géopotentielle vs normale quotidienne 1991–2020",
             fontsize=10.4, color="#b2bfd1")

    levels = np.arange(-120, 121, 20)
    norm = BoundaryNorm(levels, ncolors=256, clip=False)
    cmap = plt.get_cmap("RdBu_r")
    xx, yy = np.meshgrid(lon, lat)
    last_shade = None
    for i, step in enumerate(STEPS):
        ax = fig.add_subplot(gs[i // 3, i % 3],
                             projection=ccrs.NorthPolarStereo(central_longitude=0))
        ax.set_facecolor("#f4f6fa")
        ax.set_extent([-180, 180, 21, 90], ccrs.PlateCarree())
        angles = np.linspace(0, 2 * np.pi, 200)
        boundary = mpath.Path(np.column_stack([np.sin(angles), np.cos(angles)]) *
                              0.5 + 0.5)
        ax.set_boundary(boundary, transform=ax.transAxes)
        last_shade = ax.contourf(
            xx, yy, anomalies[step], levels=levels, cmap=cmap, norm=norm,
            extend="both", transform=ccrs.PlateCarree())
        gh = np.asarray(gh_fields[step], dtype=float)
        contour_values = np.arange(25000, 35001, 500)
        cs = ax.contour(xx, yy, gh, levels=contour_values,
                        colors="#202638", linewidths=.52, alpha=.75,
                        transform=ccrs.PlateCarree())
        if len(cs.levels):
            ax.clabel(cs, cs.levels[::2], fmt=lambda v: str(int(v / 10)),
                      inline=True, fontsize=6.1)
        ax.coastlines("110m", color="#222a3b", linewidth=.65)
        ax.plot(np.linspace(-180, 180, 361),
                np.full(361, 60.0), transform=ccrs.PlateCarree(),
                color="#f8f9fa", linewidth=.95, alpha=.8, linestyle="--")
        valid = valid_dates[i]
        ax.set_title("J+" + str(step // 24) + "  ·  " +
                     valid.strftime("%d/%m %HZ UTC"), fontsize=12.3,
                     fontweight="bold", loc="left", color="#f0f5fe", pad=9)
        ax.text(.50, -.042, "U 10 hPa / 60°N : " +
                (f"{zonal[step]:+.1f} m/s" if step in zonal else "n.d."),
                color="#9dc7f9", fontsize=9.0,
                ha="center", transform=ax.transAxes)

    cax = fig.add_axes([.20, .857, .60, .013])
    bar = fig.colorbar(last_shade, cax=cax, orientation="horizontal")
    bar.ax.tick_params(colors="#d7e4f5", labelsize=9)
    bar.outline.set_edgecolor("#d7e4f5")
    fig.text(.5, .876, "Anomalie de géopotentiel (dam) · bleu = négative / rouge = positive",
             color="#d7e4f5", fontsize=10, ha="center")

    ax = fig.add_subplot(gs[2, :])
    ax.set_facecolor("#111e32")
    xdays = np.array(sorted(zonal)) / 24.0
    values = np.array([float(zonal[h]) for h in sorted(zonal)])
    if len(xdays) < 12 or not np.all(np.isfinite(values)):
        plt.close(fig)
        raise ValueError("Vent zonal 10 hPa : série invalide")
    ymin = min(-10.0, float(np.floor(values.min() / 10) * 10 - 3))
    ymax = max(15.0, float(np.ceil(values.max() / 10) * 10 + 3))
    ax.set_xlim(1, 15)
    ax.set_ylim(ymin, ymax)
    ax.axhspan(ymin, 0, color="#a63d58", alpha=.16)
    ax.axhline(0, color="#ef7d8c", lw=1.5)
    ax.plot(xdays, values, color="#67c5ff", linewidth=2.9,
            marker="o", markersize=4.8)
    ax.set_xticks([1,3,5,7,10,12,15],
                  ["J+1","J+3","J+5","J+7","J+10","J+12","J+15"])
    ax.set_ylabel("Vent zonal moyen 10 hPa / 60°N (m/s)",
                  color="#dceafa", fontsize=11)
    ax.grid(color="#dceafa", alpha=.15)
    ax.tick_params(colors="#cbd9ec", labelsize=10)
    for spine in ax.spines.values():
        spine.set_color("#546b84")
    ax.set_title("VENTS ZONAUX · PRÉVISION J+1 À J+15",
                 loc="left", color="white", fontsize=14, weight="bold", pad=15)
    inverted = [h for h in sorted(zonal) if zonal[h] < 0]
    diagnostic = ("Inversion prévue dès J+" + str(inverted[0] // 24) +
                  " · signal à surveiller, SSW non confirmé"
                  if inverted else "Pas d'inversion prévue à 10 hPa / 60°N sur ces échéances")
    fig.text(.06, .068, "DIAGNOSTIC : " + diagnostic, fontsize=11,
             weight="bold", color="#f1cb97")
    fig.text(.06, .049, "Rouge/bleu = anomalies de hauteur, PAS température ni probabilité de froid.",
             fontsize=9.5, color="#d5e1ef")
    fig.text(.06, .032, "Un SSW prévu n'implique pas automatiquement une vague de froid en France.",
             fontsize=9.5, color="#d5e1ef")
    fig.text(.06, .014, CREDIT + " · 10 hPa ≈ 30 km",
             fontsize=8.6, color="#9aaec7")
    output = root / "ifs-10hpa-vortex-overview.png"
    fig.savefig(output, facecolor=fig.get_facecolor(), dpi=145)
    plt.close(fig)
    if output.stat().st_size > 7_500_000 or output.stat().st_size < 10_000:
        output.unlink(missing_ok=True)
        raise ValueError("Taille de la planche incompatible Discord")
    return {
        "image": "strato/" + output.name,
        "run_utc": cycle.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "level_hpa": 10,
        "forecast_hours": list(STEPS),
        "anomaly_variable": "geopotential height 10 hPa",
        "anomaly_unit": "dam",
        "reference": "NOAA NCEP/NCAR Reanalysis 1, daily mean 1991-2020",
        "reference_url": NCEP_HGT_URL,
        "diagnostic": diagnostic,
    }
