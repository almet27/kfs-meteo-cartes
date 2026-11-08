#!/usr/bin/env python3
"""Palettes KFS METEO premium pour les cartes /modeles.

Deux echelles fixes : IFS, AIFS, GFS et AIGFS restent comparables.
Z500 represente une HAUTEUR absolue en dam, et non une anomalie.
T850 represente la temperature en °C a 850 hPa, non la temperature au sol.
"""
from matplotlib.colors import LinearSegmentedColormap, TwoSlopeNorm

# Geopotentiel : basses hauteurs bleu marine / azur, hautes hauteurs
# ambre / orange cuivre. Centre doux mais non delave.
KFS_Z500_CMAP = LinearSegmentedColormap.from_list(
    "kfs_premium_z500",
    [
        (0.00, "#0B2C59"),
        (0.15, "#17558F"),
        (0.31, "#3189BD"),
        (0.43, "#99CBE2"),
        (0.50, "#E5E9E9"),
        (0.62, "#F6C788"),
        (0.75, "#F09A43"),
        (0.88, "#D66B29"),
        (1.00, "#93331E"),
    ],
    N=256,
)
KFS_Z500_NORM = TwoSlopeNorm(vmin=488, vcenter=558, vmax=610)

# Masse d'air a 850 hPa : bleu nuit -> cyan glacial -> ivoire proche
# de 0 °C -> or / orange / rouge brique. Evite le jaune fade.
KFS_T850_CMAP = LinearSegmentedColormap.from_list(
    "kfs_premium_t850",
    [
        (0.00, "#102C63"),
        (0.16, "#1C5EA4"),
        (0.32, "#46A5DD"),
        (0.44, "#B0E2F3"),
        (0.50, "#E7E9E5"),
        (0.62, "#F5D48D"),
        (0.75, "#F4A34D"),
        (0.88, "#E06C32"),
        (1.00, "#A93025"),
    ],
    N=256,
)
KFS_T850_NORM = TwoSlopeNorm(vmin=-26, vcenter=0, vmax=24)

# Uniquement la presentation change : champs GRIB, niveaux et cycles
# continuent d'etre lus sans transformation.
