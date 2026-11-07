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
