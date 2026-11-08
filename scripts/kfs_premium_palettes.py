#!/usr/bin/env python3
"""Palette operationnelle KFS METEO pour les cartes /modeles.

Les quatre modeles IFS, AIFS, GFS et AIGFS utilisent la MEME echelle.
Le Z500 est une hauteur geometrique en dam, non une anomalie ;
la T850 est une temperature a 850 hPa, non une temperature au sol.
Les couleurs seules changent, jamais les donnees des modeles.
"""

from matplotlib.colors import BoundaryNorm, LinearSegmentedColormap, ListedColormap

# Hauteur 500 hPa (dam) : conforme a l'esprit des cartes meteorologiques
# classiques, du violet/bleu profond au cyan, vert, jaune, orange et rouge.
# Pas de plage automatique selon les echeances, pour une comparaison objective.
KFS_Z500_LEVELS = tuple(range(452, 617, 4))
KFS_Z500_CMAP = LinearSegmentedColormap.from_list(
    "kfs_z500_meteo_contraste",
    [
        (0.00, "#5C005B"),  # violet, creux tres prononces
        (0.11, "#22206C"),  # indigo
        (0.22, "#0633CE"),  # bleu franc
        (0.32, "#007DF4"),  # bleu azur
        (0.43, "#25C9FF"),  # cyan
        (0.50, "#65ECDB"),  # turquoise
        (0.59, "#4CE845"),  # vert vif
        (0.67, "#B0F21C"),  # vert jaune
        (0.75, "#FFF136"),  # jaune
        (0.83, "#FFAA16"),  # orange dore
        (0.90, "#FF6A1A"),  # orange soutenu
        (0.96, "#F23B38"),  # rouge
        (1.00, "#A70B4B"),  # magenta
    ],
    N=256,
)
KFS_Z500_NORM = BoundaryNorm(KFS_Z500_LEVELS, KFS_Z500_CMAP.N)
KFS_Z500_TICKS = (460, 480, 500, 520, 540, 560, 580, 600)

# Temperature a 850 hPa : palette fixe proche des cartes meteorologiques
# classiques fournies en reference par KFS METEO.
# -34/-24 : prune et violet ; -22/-10 : bleu profond ; -8/-2 : cyan ;
# 0/+4 : vert ; +6/+12 : jaune et creme ; +14/+34 : orange et rouge.
# Les 34 couleurs correspondent exactement aux 34 intervalles de 2 degres.
KFS_T850_LEVELS = tuple(range(-34, 35, 2))
KFS_T850_COLORS = [
    "#4c003f", "#6a1766", "#7f3b8c", "#9a63b0", "#b99ad0",
    "#5a4f87", "#2e3f8f", "#1d33c7", "#0b2fff", "#173dff",
    "#1558ff", "#0e73ff", "#1c97ff", "#46bfff", "#78dbff",
    "#a8ecff", "#7ff2d8", "#66ee88", "#7eed39", "#b9f41d",
    "#f0f51f", "#fff34d", "#fff799", "#fff3cf", "#f6e4a6",
    "#f1cd66", "#efb033", "#eb9220", "#e67a15", "#dd6314",
    "#d4511b", "#c44528", "#b73d36", "#a83a45",
]
KFS_T850_CMAP = ListedColormap(KFS_T850_COLORS, name="kfs_t850_classique")
KFS_T850_CMAP.set_under("#33323d")
KFS_T850_CMAP.set_over("#8f263f")
KFS_T850_NORM = BoundaryNorm(KFS_T850_LEVELS, KFS_T850_CMAP.N)
KFS_T850_TICKS = (-32, -24, -16, -8, -4, 0, 4, 8, 12, 16, 20, 24, 28, 32)
KFS_T850_ISOTHERMS = tuple(range(-32, 33, 4))

assert len(KFS_T850_COLORS) == len(KFS_T850_LEVELS) - 1
