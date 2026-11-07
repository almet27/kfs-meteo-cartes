# Validation du géoréférencement radar — KFS MÉTÉO IA

**État : NON VALIDÉ.** Les images produites par `premier-decodage-radar.yml` sont des diagnostics, pas un radar exploitable pour informer le public. La commande Discord `/meteo` ne doit pas être modifiée.

## Ce qui est établi

- Le flux Météo-France DPRadar `METROPOLE/observations/REFLECTIVITE` est accessible.
- Le BUFR est décodé ; les valeurs de réflectivité sont représentées en dBZ.
- Le fichier `horodatage-observation-radar.json` sépare l'heure **d'observation** de l'heure **de capture**. Exemple vérifié : observation `2026-11-07T11:00:00+00:00`, capture `2026-11-07T11:03:53+00:00`.
- Les fonds de carte et limites administratives s'affichent, mais la correspondance exacte des pixels radar n'est pas établie.

## Prochaine validation, à faire sur une même observation UTC

1. Exécuter le workflow GitHub Actions `Premier decodage radar Meteo-France` et récupérer son artefact `premiere-carte-radar`.
2. Lire `horodatage-observation-radar.json` : utiliser **observation_utc**, jamais `capture_utc`, comme heure de référence.
3. Obtenir une **image de référence indépendante et horodatée** à cette même heure (idéalement même produit de réflectivité, même seuil dBZ). Une capture faite plusieurs minutes après n'est pas une comparaison valable si les échos se déplacent.
4. Choisir au moins trois structures d'échos **distinctes et reconnaissables**, éloignées géographiquement : par exemple une zone à l'ouest, une au nord et une au sud. Noter pour chacune les coordonnées géographiques du centre sur la référence, l'heure UTC et l'incertitude estimée.
5. Comparer ces structures sur les quatre panneaux de `diagnostic-quatre-ordres-pixels-fond-carte.png` ; vérifier les positions, pas seulement la ressemblance de la forme.
6. Si aucune orientation ne correspond, vérifier la projection Lambert, le point d'origine, le pas de grille, la convention de balayage BUFR et l'ordre de rangement du tableau ; **ne pas** translater manuellement les échos pour les faire coïncider.
7. Ne déclarer le placement `VALIDE` qu'après accord spatial reproductible sur plusieurs structures et **deux observations différentes**. Conserver les captures de référence et les écarts constatés.

## Résultat attendu avant mise en production

- Une image PNG montrant radar et départements correctement superposés autour de Bourth.
- Un audit avec heure UTC, méthode, écarts de position et sources des références.
- Ensuite seulement : collecte de plusieurs observations, GIF animé et intégration de `/radar ville:<ville>` dans le bot Discord, **sans toucher à `/meteo`**.

**Important :** une image sans échos près de Bourth ne démontre pas que le radar est mal placé ; elle ne permet pas non plus de le valider. Il faut comparer les échos là où il pleut à la même heure.


## Source de référence retrouvée le 7 novembre 2026

- Archives Météo60 : https://www.meteo60.fr/aller-plus-loin/archives-cartes — la page indique que les radars zoomables sont accessibles depuis les observations en direct et archivés pendant trois mois.
- Archives radar Météo-France : https://donneespubliques-int.meteofrance.fr/?fond=rubrique&id_rubrique=27 — référence officielle à privilégier si le créneau exact est accessible.
- Attention : une image de radar « en direct » n'est pas une preuve pour le 7 novembre 2026 à **11:05 UTC**. La référence doit afficher explicitement ce créneau.
- La mosaïque BUFR est une réflectivité en **dBZ** ; si la référence exprime une intensité en mm/h, ne pas comparer directement les valeurs numériques, mais seulement la position des structures d'échos avec prudence.
- Météo60 limite la réutilisation de ses images animées/zoomables ; utiliser l'archive pour une vérification visuelle, pas pour republier son contenu sans autorisation.

### Fichier de noyaux reçu

Le GeoJSON `noyaux-radar-hypotheses.geojson` contient des centres de noyaux **hypothétiques**, calculés pour quatre rangements possibles de la matrice. Ne pas transformer ces points en observations géolocalisées validées. La présence de 48 centres ne valide aucune orientation.

### Procédure de contrôle sur l'archive

1. Ouvrir l'archive Météo60, afficher le 07/11/2026 à 12:05 heure de Paris (11:05 UTC), et conserver une capture montrant clairement la date et l'heure.
2. Vérifier la carte de référence sur plusieurs zones de précipitations et relever au moins trois centres géographiques.
3. Comparer les centres relevés aux quatre groupes du GeoJSON ; une orientation qui place les noyaux en Manche et une autre qui les place dans le sud-est ne peuvent pas être considérées équivalentes.
4. Si la référence n'est pas disponible exactement à 11:05 UTC, laisser l'audit **NON_VALIDÉ** et refaire une acquisition synchronisée avec une autre source.
