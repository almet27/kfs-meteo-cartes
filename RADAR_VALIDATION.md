# Validation du géoréférencement radar — KFS MÉTÉO

## État au 7 novembre 2026

La mosaïque de réflectivité Météo-France est décodée en BUFR et les limites
administratives (pays, départements) sont tracées sur le fond de carte autour de Bourth.

**Le géoréférencement des précipitations n'est pas validé.**
Les quatre dispositions des pixels comparées dans
`diagnostic-quatre-ordres-pixels-fond-carte.png` ne constituent pas une preuve
de localisation correcte. En particulier, l'apparence plausible de la variante
« Lignes adjacentes / sans retournement » n'est pas une validation.

## Contrôles indispensables avant publication

1. Lire les unités, le type de projection, le point d'origine, les dimensions,
   les pas et les indicateurs de balayage dans le message BUFR **réel**.
   Ne pas supposer qu'un point de station radar est un coin de grille.
2. Vérifier les conventions de projection du produit local Météo-France.
   La projection Lambert utilisée dans le workflow est **provisoire**.
3. Comparer une même observation horodatée à une référence radar
   géoréférencée indépendante et autorisée, avec au moins trois points
   de contrôle répartis sur la France. Une ressemblance visuelle ne suffit pas.
4. Vérifier le sens des lignes et colonnes, la résolution et l'étendue ;
   conserver les valeurs manquantes masquées.
5. Tester une superposition sur les limites de départements et les côtes,
   notamment dans le secteur de Bourth, et consigner les écarts constatés.
6. Ne créer une carte opérationnelle puis un GIF qu'après réussite
   documentée de ces contrôles.

## Séparation des commandes

- `/meteo` : ne pas modifier.
- `/radar ville:<commune>` : projet futur, à activer seulement lorsque
  le calage est validé et que plusieurs observations datées sont disponibles.
- Les cartes actuelles sont des **diagnostics non validés**, pas un radar
  opérationnel ni une prévision.

## Fichiers utiles

Workflow d'analyse : `.github/workflows/premier-decodage-radar.yml`.

Les sorties PNG sont accessibles dans les artefacts de l'exécution GitHub Actions
du workflow « Premier decodage radar Meteo-France ».
