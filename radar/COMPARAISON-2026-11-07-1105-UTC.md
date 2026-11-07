# Comparaison radar du 7 novembre 2026 — 11:05 UTC

## Référence reçue

Capture fournie par l'utilisateur : `meteo60-radar-261107-1105.gif`, carte de France portant le libellé **07/11/26 11h05 - meteo60.fr (données MF)**. Elle montre de nombreux échos dans la Manche, vers la mer du Nord et au large de la Belgique/Pays-Bas, ainsi que des échos au Pays basque, à proximité de la frontière franco-espagnole. **Attention** : cette carte utilise une légende en **mm/h**, et le BUFR analysé une réflectivité en **dBZ**. La comparaison porte uniquement sur les emplacements et les grandes structures, pas les intensités.

## Confrontation aux noyaux BUFR

Source : fichier `noyaux-radar-hypotheses.geojson` reçu pour cette observation. Les coordonnées ci-dessous sont des centres de composantes connectées de réflectivité >=20 dBZ, **hypothétiques**.

| Hypothèse | Gros noyaux au nord | Autre noyau distinct | Concordance qualitative |
|---|---|---|---|
| Lignes adjacentes, sans retournement | (-2.15961, 49.64263), (-3.60348, 50.02563), (-0.54039, 50.59348) | (-1.35472, 43.37377), Pays basque | **Meilleure concordance visuelle** : Manche et Pays basque |
| Colonnes adjacentes, sans retournement | (-2.40412, 49.47435), (-3.09631, 50.37925) | (7.13370, 48.87230), Alsace | Concordance partielle Manche, mais distribution méridionale peu convaincante |
| Lignes adjacentes, retournement 180 | (4.56692, 44.57730), (5.81436, 44.10116) | (3.03268, 43.69004) | **Incompatible visuellement** avec la concentration d'échos en Manche |
| Colonnes adjacentes, retournement 180 | (4.81018, 44.73193), (5.31023, 43.78376) | (6.23691, 45.72765) | **Incompatible visuellement** avec la concentration d'échos en Manche |

## Conclusion provisoire

**Orientation privilégiée : lignes adjacentes / sans retournement.** La concordance de deux zones géographiquement éloignées (Manche et Pays basque) est un indice fort, mais **ce n'est pas une validation quantitative**. La capture Météo60 est une image cartographique raster ; nous n'avons pas encore calculé les écarts géodésiques des structures appariées. De plus, la carte de référence peut appliquer ses propres filtres/seuils.

**Statut : VALIDATION VISUELLE PROVISOIRE ; GÉORÉFÉRENCEMENT NON VALIDÉ POUR LA DIFFUSION.**

## Prochaines étapes

1. Reproduire la comparaison sur une **deuxième observation UTC distincte**.
2. Contrôler le placement des noyaux au nord et au Pays basque avec une référence géographique mesurable (fond de carte ou coordonnées d'au moins trois structures).
3. Ne pas annoncer une précision kilométrique ni activer `/radar` publiquement avant ces contrôles.
4. Préserver `/meteo` et l'ensemble du bot existant.
