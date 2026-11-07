#!/usr/bin/env python3
"""Prototype EC46 : deux cartes hebdomadaires sur l'Atlantique et l'Europe.

Aucune diffusion Discord / aucune publication GitHub Pages.
Maille volontairement grossière : NE PAS UTILISER EN PRÉVISION OPÉRATIONNELLE.
"""
from __future__ import annotations
import json
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from analysis_ec46 import build as build_bulletin
import cartopy.crs as ccrs
import cartopy.feature as cfeature

OUTPUT = Path("meteo-mois-preview")
SOURCE = "https://seasonal-api.open-meteo.com/v1/seasonal"
FIELDS = [
    "pressure_msl_mean", "pressure_msl_anomaly",
    "temperature_2m_anomaly", "precipitation_anomaly",
    "wind_u_component_10m_mean", "wind_v_component_10m_mean",
]
# Grille du TEST uniquement. Ne constitue pas une résolution cartographique opérationnelle.
LONS = np.array([-60, -45, -30, -15, -5, 0, 5, 10, 15, 30, 40], dtype=float)
LATS = np.array([30, 38, 42, 46, 50, 54, 62, 70, 75], dtype=float)
N = len(LONS) * len(LATS)
ALL_POINTS = [(float(lat), float(lon)) for lat in LATS for lon in LONS]

def api():
    p = {
        "latitude": ",".join(str(lat) for lat, lon in ALL_POINTS),
        "longitude": ",".join(str(lon) for lat, lon in ALL_POINTS),
        "models": "ecmwf_seasonal_ensemble_mean_seamless",
        "forecast_days": 45, "timezone": "GMT",
        "weekly": ",".join(FIELDS),
    }
    req = Request(SOURCE + "?" + urlencode(p), headers={
        "Accept": "application/json",
        "User-Agent": "KFS-Meteo-EC46-Synoptic-Prototype/0.1",
    })
    try:
        with urlopen(req, timeout=110) as res:
            result = json.load(res)
    except HTTPError as exc:
        raise RuntimeError(f"EC46 HTTP {exc.code}: {exc.read(500)!r}") from exc
    if not isinstance(result, list) or len(result) != N:
        raise RuntimeError(f"Réponse multi-points inattendue (attendus {N}, obtenus {len(result) if isinstance(result,list) else type(result).__name__}).")
    weeks = result[0].get("weekly", {}).get("time", [])
    if len(weeks) < 5:
        raise RuntimeError("Moins de 5 semaines disponibles pour sélectionner quatre semaines complètes")
    # Écarter la première semaine car elle peut déjà être en cours.
    chosen = list(range(1, 5))
    today = datetime.now(timezone.utc).date()
    for i in chosen:
        d = date.fromisoformat(weeks[i])
        if d + timedelta(days=6) < today:
            raise RuntimeError("Période EC46 entièrement passée : source obsolète")
    for idx, item in enumerate(result):
        if item.get("weekly", {}).get("time") != weeks:
            raise RuntimeError("Semaines incohérentes entre points de grille")
        for field in FIELDS:
            values = item["weekly"].get(field)
            if not isinstance(values, list) or len(values) != len(weeks):
                raise RuntimeError(f"Champ manquant : {field} au point {idx}")
            for i in chosen:
                if not isinstance(values[i], (float, int)) or not np.isfinite(values[i]):
                    raise RuntimeError(f"Donnée invalide : {field}, point {idx}, semaine {i}")
    units = result[0].get("weekly_units", {})
    assert units.get("pressure_msl_mean") == "hPa"
    assert units.get("pressure_msl_anomaly") == "hPa"
    assert units.get("temperature_2m_anomaly") in ("K", "°C")
    assert units.get("wind_u_component_10m_mean") in ("km/h", "m/s")
    assert units.get("wind_v_component_10m_mean") in ("km/h", "m/s")
    return result, weeks, chosen, units

def grid(data, key, index):
    return np.array([x["weekly"][key][index] for x in data], dtype=float).reshape(len(LATS), len(LONS))

def decorate(ax, week):
    """Fond Natural Earth précis, en lon/lat WGS84 (données projetées en PlateCarree)."""
    d = date.fromisoformat(week)
    end = d + timedelta(days=6)
    ax.set_title(f"{d:%d/%m} – {end:%d/%m/%Y}", fontsize=11, weight="bold")
    ax.set_extent([float(LONS[0]), float(LONS[-1]),
                   float(LATS[0]), float(LATS[-1])],
                  crs=ccrs.PlateCarree())

    # Terre et mer SOUS les champs ECMWF ; frontières et côtes AU-DESSUS.
    ax.add_feature(cfeature.OCEAN.with_scale("50m"),
                   facecolor="#dcebf5", edgecolor="none", zorder=0)
    ax.add_feature(cfeature.LAND.with_scale("50m"),
                   facecolor="#f1ede4", edgecolor="none", zorder=0.1)
    ax.coastlines(resolution="50m", linewidth=0.75,
                  color="#2e3942", zorder=7)
    ax.add_feature(cfeature.BORDERS.with_scale("50m"),
                   linewidth=0.45, edgecolor="#505b63", zorder=7)

    gl = ax.gridlines(crs=ccrs.PlateCarree(), draw_labels=True,
                      linewidth=0.45, alpha=0.25, linestyle="--",
                      color="#3e515e", zorder=6)
    gl.top_labels = False
    gl.right_labels = False
    gl.xlabel_style = {"size": 7}
    gl.ylabel_style = {"size": 7}

    # Petit repère lisible, sans cacher la France sous un symbole imposant.
    ax.plot([2.2], [46.5], marker="o", markersize=2.5, color="#333333",
            transform=ccrs.PlateCarree(), zorder=8)
    ax.text(3.6, 46.6, "France", fontsize=7, weight="bold",
            color="#26323a", transform=ccrs.PlateCarree(), zorder=8,
            bbox={"facecolor": "white", "alpha": 0.62, "edgecolor": "none",
                  "pad": 0.4})
    ax.text(0.025, 0.027, "GRILLE EXPÉRIMENTALE",
            transform=ax.transAxes, fontsize=8, color="#121820",
            bbox={"facecolor": "white", "alpha": .86,
                  "edgecolor": "none", "pad": 1.2}, zorder=9)

def draw_vectors(ax, data, idx):
    u = grid(data, "wind_u_component_10m_mean", idx)
    v = grid(data, "wind_v_component_10m_mean", idx)
    xx, yy = np.meshgrid(LONS, LATS)
    ax.quiver(xx, yy, u, v, color="#202b38", angles="uv", scale_units="width",
              scale=140, width=0.003, headwidth=3, alpha=0.8, zorder=5,
              transform=ccrs.PlateCarree())

def render(data, weeks, chosen, mode):
    fig, axes = plt.subplots(2, 2, figsize=(14, 11),
                             constrained_layout=True,
                             subplot_kw={"projection": ccrs.PlateCarree()})
    xx, yy = np.meshgrid(LONS, LATS)
    contour = None
    for ax, idx in zip(axes.flat, chosen):
        if mode == "pressure":
            anomaly = grid(data, "pressure_msl_anomaly", idx)
            pressure = grid(data, "pressure_msl_mean", idx)
            contour = ax.contourf(xx, yy, anomaly, levels=np.arange(-24, 25, 3),
                                  cmap="RdBu_r", extend="both", alpha=0.88,
                                  zorder=2, transform=ccrs.PlateCarree())
            pmin, pmax = float(np.min(pressure)), float(np.max(pressure))
            levels = np.arange(np.floor(pmin/5)*5, np.ceil(pmax/5)*5+1, 5)
            if len(levels) >= 2:
                lines = ax.contour(xx, yy, pressure, levels=levels, colors="#161e2b",
                                   linewidths=.8, alpha=.85, zorder=3,
                                   transform=ccrs.PlateCarree())
                ax.clabel(lines, inline=True, fontsize=7, fmt="%d")
        else:
            thermal = grid(data, "temperature_2m_anomaly", idx)
            contour = ax.contourf(xx, yy, thermal, levels=np.arange(-9, 10, 1),
                                  cmap="RdBu_r", extend="both", alpha=0.88,
                                  zorder=2, transform=ccrs.PlateCarree())
        draw_vectors(ax, data, idx)
        decorate(ax, weeks[idx])
    if mode == "pressure":
        title="KFS MÉTÉO | EC46 — Pressions et centres d'action MOYENS"
        label="Anomalie de pression (hPa) · isolignes pression moyenne (hPa)"
        file="centres-action-4semaines-TEST.png"
    else:
        title="KFS MÉTÉO | EC46 — Anomalie thermique près du sol"
        label="Anomalie température 2 m (K, écart équivalent à °C)"
        file="anomalies-thermiques-4semaines-TEST.png"
    fig.suptitle(title + f"\nAtlantique Nord oriental – Europe | ÉCHANTILLONNAGE {N} POINTS, NON OPÉRATIONNEL",
                 fontsize=15, weight="bold")
    fig.colorbar(contour, ax=axes.ravel().tolist(), shrink=.8, label=label, pad=.02)
    OUTPUT.mkdir(parents=True, exist_ok=True)
    fig.savefig(OUTPUT / file, dpi=140, facecolor="white")
    plt.close(fig)
    return file

def main():
    data, weeks, chosen, units = api()
    products = [render(data, weeks, chosen, "pressure"),
                render(data, weeks, chosen, "thermal")]
    generated = datetime.now(timezone.utc).isoformat()
    analysis = build_bulletin(data, weeks, chosen, generated)
    (OUTPUT / "bulletin-TEST.txt").write_text(analysis["text"]+"\n", encoding="utf-8")
    (OUTPUT / "analysis-TEST.json").write_text(
        json.dumps(analysis, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    meta = {
        "status": "prototype_ne_pas_diffuser",
        "generated_utc": generated,
        "product": "ECMWF seamless weekly ensemble mean via Open-Meteo",
        "region": "Atlantique nord oriental / Europe",
        "points": N, "grid": "coarse_experimental",
        "analysis": "analysis-TEST.json",
        "analysis_text": "bulletin-TEST.txt",
        "source_run_utc": None,
        "basemap": "Natural Earth 50m via Cartopy (coasts, land/ocean, borders)",
        "periods": [
            {"start": weeks[i], "end": str(date.fromisoformat(weeks[i]) + timedelta(days=6))}
            for i in chosen
        ],
        "units": units, "files": products,
        "warnings": [
            "Source avec données non corrigées des biais, résolution grossière.",
            "4 semaines moyennes ; ne prédit pas la position exacte des centres d'action.",
            "Aucune donnée T850 ou Z500 ; les flèches représentent vent à 10m.",
            "Pas de vérification de dispersion des membres de l'ensemble.",
            "Aucune donnée importée dans le bot Discord.",
        ],
    }
    (OUTPUT / "manifest-TEST.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "status": meta["status"], "periods": meta["periods"], "files": products,
        "points": N,
    }, ensure_ascii=False))

if __name__ == "__main__":
    main()
