# KFS MÉTÉO — diagnostic multiparamètre `/proba` orages

## Séparer les trois questions

1. **Potentiel convectif** : catégories 0–5 calculées par membre à partir de MU-CAPE, pluie convective, point de rosée et rafales. Le niveau « moyen » peut être atteint avec MU-CAPE ≥ 500 J/kg et point de rosée ≥ 8 °C même si le modèle ne déclenche pas encore de précipitations. Ce n'est pas une probabilité calibrée d'orage.
2. **Environnement favorable à l'organisation** : diagnostic séparé, membre positif lorsque, **à une même échéance**, le potentiel convectif est au moins moyen (niveau ≥ 2) **et** le cisaillement vectoriel entre 850 et 500 hPa atteint **15 m/s**. Ce cisaillement entre niveaux de pression n'est **pas** le cisaillement 0–6 km ; il est moins représentatif dans les régions d'altitude.
3. **Soutien par ascendance de grande échelle** : diagnostic séparé, membre positif lorsque l'indice convectif est ≥ 1 et la vitesse verticale à **700 hPa ≤ −0,05 Pa/s** à une même échéance (valeurs négatives = ascendance). Ce diagnostic ne mesure pas les courants ascendants des cellules et n'exclut pas les déclenchements par convergence locale.

## Sources et méthode

- Données ECMWF IFS ENS open data, **8 membres choisis**, grille 0,25°, deux échéances / 24 h, J+0 à J+3.
- Champs optionnels : U/V 850 et 500 hPa et ω à 700 hPa, téléchargés séparément sur **le même run**.
- Cisaillement en m/s = racine carrée de `(U500 − U850)^2 + (V500 − V850)^2`. Il est résumé, par membre, par le maximum quotidien des deux échantillons.
- `storm_organized_pct` : fraction de membres présentant au moins une échéance favorable à une organisation possible.
- `storm_ascent_support_pct` : fraction de membres présentant un signal convectif accompagné d'ascendance à 700 hPa.
- `shear_850_500_mean_ms` : moyenne d'ensemble des maxima quotidiens par membre.
- Un diagnostic optionnel n'est publié que si au moins **5 membres sur 8** sont valides à un point ; une donnée absente reste absente, jamais forcée à 0.
- Si les champs de pression ne sont pas accessibles, les cartes existantes (orage, pluie, neige et neige tombante) continuent avec leurs données validées, sans ces indicateurs additionnels.
- Dans Discord, les chiffres de la carte orage restent les **fractions de membres atteignant le niveau demandé**. Les indicateurs d'organisation et d'ascendance sont affichés **séparément sous forme de texte**, sans prétendre évaluer la violence d'un orage.

## Limitations

**Aucune équivalence avec les vigilances Météo-France, la grêle, les tornades, les dommages ou une probabilité officielle d'orage violent.** Ces seuils sont des heuristiques expérimentales : ils doivent être calibrés et vérifiés rétrospectivement face aux observations (foudre, radar, stations) avant de prétendre mesurer une probabilité d'occurrence ou de sévérité.

Sources : [ECMWF Open Data](https://www.ecmwf.int/en/forecasts/datasets/open-data) et [ecmwf-opendata](https://github.com/ecmwf/ecmwf-opendata).
