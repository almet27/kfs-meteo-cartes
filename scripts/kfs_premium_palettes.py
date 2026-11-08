#!/usr/bin/env python3
"""Palette operationnelle KFS METEO pour les cartes /modeles.

Les quatre modeles IFS, AIFS, GFS et AIGFS utilisent la MEME echelle.
Le Z500 est une hauteur geometrique en dam, non une anomalie ;
la T850 est une temperature a 850 hPa, non une temperature au sol.
Les couleurs seules changent, jamais les donnees des modeles.
"""

from matplotlib.colors import BoundaryNorm, LinearSegmentedColormap

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

# Masse d'air T850 : froid bleu/violet, proche de zero cyan/vert clair,
# doux jaune/orange et chaud rouge. Zero degre represente une valeur
# a 850 hPa, jamais un seuil automatique de gel en surface.
KFS_T850_LEVELS = tuple(range(-30, 31, 2))
KFS_T850_CMAP = LinearSegmentedColormap.from_list(
    "kfs_t850_meteo_contraste",
    [
        (0.00, "#4C006F"),  # tres froid
        (0.16, "#2244BD"),
        (0.30, "#078BEA"),
        (0.42, "#65D9FF"),
        (0.50, "#6FE1B1"),  # proche de 0 degre a 850 hPa
        (0.60, "#8EE642"),
        (0.70, "#F4E948"),
        (0.81, "#FFB137"),
        (0.90, "#FB7528"),
        (1.00, "#CB2F3D"),
    ],
    N=256,
)
KFS_T850_NORM = BoundaryNorm(KFS_T850_LEVELS, KFS_T850_CMAP.N)
KFS_T850_TICKS = (-24, -16, -8, 0, 8, 16, 24)
