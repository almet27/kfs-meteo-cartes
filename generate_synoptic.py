#!/usr/bin/env python3
"""Generate North Atlantic/Europe synoptic maps from ECMWF open IFS pressure fields.
Uses deterministic IFS (not ensemble mean). Fails closed on unavailable data.
"""
import json
import os
from datetime import datetime, timezone
from pathlib import Path
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import cartopy.crs as ccrs
import cartopy.feature as cfeature
import xarray as xr
from ecmwf.opendata import Client

OUT = Path("synoptic-output")
OUT.mkdir(exist_ok=True)
# ECMWF open data is a rolling archive; retrieve latest available run.
client = Client(source="ecmwf", model="ifs", resol="0p25")
steps = list(range(144, 241, 24)) + list(range(264, 361, 24))
fields = {}
t850_fields = {}
for step in steps:
    target = OUT / f"msl_{step}.grib2"
    client.retrieve(type="fc", step=step, param="msl", target=str(target))
    ds = xr.open_dataset(target, engine="cfgrib", backend_kwargs={"indexpath": ""})
    fields[step] = ds["msl"].squeeze().load()
    ds.close()
    temp_target = OUT / f"t850_{step}.grib2"
    client.retrieve(type="fc", step=step, param="t", levelist=850, target=str(temp_target))
    temp_ds = xr.open_dataset(temp_target, engine="cfgrib", backend_kwargs={"indexpath": ""})
    t850_fields[step] = temp_ds["t"].squeeze().load()
    temp_ds.close()
periods = {"j6-j10": [s for s in steps if 144 <= s <= 240],
           "j11-j15": [s for s in steps if 264 <= s <= 360]}
metadata = {"source": "ECMWF Open Data IFS deterministic", "generated_utc": datetime.now(timezone.utc).isoformat(), "maps": {}}
for label, selected in periods.items():
    da = xr.concat([fields[s] for s in selected], dim="step").mean("step") / 100.0
    temp = xr.concat([t850_fields[s] for s in selected], dim="step").mean("step") - 273.15
    lat = da.latitude.values
    lon = ((da.longitude.values + 180) % 360) - 180
    ix = np.argsort(lon)
    data = da.values[:, ix]
    temperature = temp.values[:, ix]
    lon = lon[ix]
    fig = plt.figure(figsize=(12, 7), dpi=150)
    ax = plt.axes(projection=ccrs.PlateCarree())
    ax.set_extent([-65, 40, 30, 75], crs=ccrs.PlateCarree())
    ax.add_feature(cfeature.LAND, facecolor="#eef1ed", zorder=0)
    ax.add_feature(cfeature.OCEAN, facecolor="#e3edf4", zorder=0)
    ax.coastlines(resolution="110m", linewidth=0.7)
    temp_levels = np.arange(-24, 25, 2)
    shaded = ax.contourf(lon, lat, temperature, levels=temp_levels, cmap="RdBu_r",
                         extend="both", transform=ccrs.PlateCarree(), alpha=0.78)
    cbar = fig.colorbar(shaded, ax=ax, orientation="horizontal", pad=0.06, shrink=0.75)
    cbar.set_label("Température moyenne à 850 hPa (°C) — indicateur de masse d'air")
    ax.contour(lon, lat, temperature, levels=[0], colors="#555555",
               linewidths=1.0, linestyles="dashed", transform=ccrs.PlateCarree())
    levels = np.arange(940, 1061, 4)
    cs = ax.contour(lon, lat, data, levels=levels, colors="#263e63", linewidths=0.8,
                    transform=ccrs.PlateCarree())
    ax.clabel(cs, inline=True, fontsize=7, fmt="%d")
    ax.set_title(f"KFS MÉTÉO IA | Pression et masses d’air {label.upper()}\nECMWF IFS déterministe • moyenne temporelle, pas ensemble")
    filename = f"pression-{label}.png"
    fig.savefig(OUT / filename, bbox_inches="tight")
    plt.close(fig)
    metadata["maps"][label] = filename
    metadata.setdefault("variables", ["Pression moyenne au niveau de la mer (hPa)", "Température moyenne 850 hPa (°C)"])
(OUT / "metadata.json").write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
print(json.dumps(metadata, ensure_ascii=False))
