"""Analyse EC46 hebdomadaire à partir des POINTS de prévision effectivement reçus.

Toutes les phrases utilisent des moyennes régionales calculées; les étiquettes
ne présument ni NAO, ni Z500/T850, ni scénarios d'ensemble probabilistes.
"""
from __future__ import annotations
from datetime import date, timedelta
import math
import numpy as np

REGIONS = {
    "Atlantique Nord oriental": (-60, -15, 30, 70),
    "Europe occidentale": (-15, 15, 38, 70),
    "Europe orientale": (15, 40, 38, 70),
    "France (secteur, pas une maille locale)": (-5, 10, 42, 52),
}

def aggregate(points, index, region):
    west, east, south, north = region
    subset = [
        p for p in points
        if west <= float(p["longitude"]) <= east
        and south <= float(p["latitude"]) <= north
    ]
    if not subset:
        raise ValueError(f"Aucun point dans {region}")
    weights = np.array([math.cos(math.radians(p["latitude"])) for p in subset])
    def avg(field):
        values = np.array([p["weekly"][field][index] for p in subset], dtype=float)
        if not np.all(np.isfinite(values)):
            raise ValueError("Données invalides " + field)
        return float(np.average(values, weights=weights))
    return {
        "points": len(subset),
        "msl": avg("pressure_msl_mean"),
        "msl_anomaly": avg("pressure_msl_anomaly"),
        "t2m_anomaly": avg("temperature_2m_anomaly"),
        "precip_anomaly": avg("precipitation_anomaly"),
        "u": avg("wind_u_component_10m_mean"),
        "v": avg("wind_v_component_10m_mean"),
    }

def category(x, threshold, negative, neutral, positive):
    return positive if x >= threshold else negative if x <= -threshold else neutral

def sentence(place, value):
    pressure = category(
        value["msl_anomaly"], 4,
        "signal dépressionnaire relatif aux normales du modèle",
        "anomalie de pression peu marquée",
        "signal anticyclonique relatif aux normales du modèle",
    )
    thermal = category(
        value["t2m_anomaly"], 1.0,
        "plus frais que la climatologie du modèle",
        "proche de la climatologie thermique du modèle",
        "plus doux que la climatologie du modèle",
    )
    rains = category(
        value["precip_anomaly"], 5.0,
        "précipitations sous les normales du modèle",
        "écart pluviométrique faible",
        "précipitations au-dessus des normales du modèle",
    )
    wind = category(
        value["u"], 5.0,
        "composante moyenne vers l'ouest",
        "composante zonale faible",
        "composante moyenne vers l'est (flux d'ouest)",
    )
    # L'anomalie de MSL n'est PAS un diagnostic suffisant d'anticyclone.
    return (
        f"**{place} :** {pressure} ({value['msl_anomaly']:+.1f} hPa), "
        f"pression moyenne {value['msl']:.0f} hPa. "
        f"Situation thermique : {thermal} ({value['t2m_anomaly']:+.1f} °C) ; "
        f"{rains} ({value['precip_anomaly']:+.0f} mm/semaine). "
        f"À 10 m, {wind} (u = {value['u']:+.0f} km/h)."
    )

def build(points, weeks, chosen, generated_utc):
    if not points or len(chosen) != 4:
        raise ValueError("Quatre semaines EC46 nécessaires")
    week_items = []
    paragraphs = [
        "🧭 **KFS MÉTÉO — Tendance Atlantique / Europe / France, 4 semaines**",
        "**ECMWF EC46 / Open-Meteo · moyennes hebdomadaires**",
        f"🕒 Génération UTC : {generated_utc}. Run exact ECMWF non communiqué par l'API.",
        "",
    ]
    for n, i in enumerate(chosen, start=1):
        start = date.fromisoformat(weeks[i])
        end = start + timedelta(days=6)
        regions = {name: aggregate(points, i, bounds)
                   for name, bounds in REGIONS.items()}
        paragraphs.append(
            f"**Semaine {n} — {start:%d/%m} au {end:%d/%m/%Y}**"
        )
        paragraphs.append(sentence("Atlantique Nord", regions["Atlantique Nord oriental"]))
        paragraphs.append(sentence("Europe occidentale", regions["Europe occidentale"]))
        paragraphs.append(sentence("Europe orientale", regions["Europe orientale"]))
        paragraphs.append(sentence("France", regions["France (secteur, pas une maille locale)"]))
        paragraphs.append("")
        week_items.append({
            "number": n, "start": start.isoformat(), "end": end.isoformat(),
            "regions": regions
        })
    paragraphs.extend([
        "⚠️ **Lecture :** anomalies relatives à la climatologie du modèle, pas aux observations."
        " Les noyaux de pression sont des structures moyennes, pas des positions à une date donnée.",
        "Les vents sont à 10 m ; ce produit ne décrit pas la température à 850 hPa ni le géopotentiel à 500 hPa.",
        "La France est représentée par un petit nombre de mailles ; aucune prévision départementale fiable à J+30.",
        "**Confiance : dispersion d'ensemble non calculée** ; aucune probabilité fiable ne peut être avancée.",
        "_Données : ECMWF via Open-Meteo ; traitement KFS MÉTÉO. CC BY 4.0._",
    ])
    body = "\n\n".join(paragraphs)
    return {
        "text": body,
        "weeks": week_items,
        "provenance": {
            "model": "ecmwf_seasonal_ensemble_mean_seamless",
            "run_time": None,
            "generated_utc": generated_utc,
            "source": "ECMWF via Open-Meteo",
            "method": "Moyenne pondérée cos(latitude) des points EC46",
            "ensemble_spread_verified": False,
            "operational": False
        }
    }
