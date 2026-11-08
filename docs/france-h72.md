# KFS MÉTÉO — Cartes France 0–72 h (prototype)

## Ce qui fonctionne

Le moteur `scripts/generate_france_forecasts.py` produit des cartes centrées sur la France, avec un horaire de validité et le run source dans chaque image. Les cartes proviennent des champs GRIB des modèles, pas d'images extrapolées.

| Modèle | Pas de temps natif | Échéances |
| --- | --- | --- |
| ECMWF IFS | 3 heures | +3, +6, …, +72 h |
| NOAA GFS | 3 heures | +3, +6, …, +72 h |
| ECMWF AIFS | 6 heures | +6, +12, …, +72 h |
| NOAA AIGFS | 6 heures | +6, +12, …, +72 h |

Les paramètres pris en charge sont : température à 2 m, température à 850 hPa, vent à 10 m, pression réduite au niveau de la mer, précipitations totales, pluie et neige lorsqu'une séparation est étayée.

**Neige** : pour ECMWF, il s'agit d'un équivalent-eau, pas de centimètres au sol. Pour GFS, le découpage pluie / précipitations gelées utilise la fraction instantanée CPOFP si cette fraction est valide et indique explicitement une estimation. Pour AIGFS, la phase n'est pas déduite arbitrairement : la carte de précipitations **totales** reste disponible même sans séparation pluie/neige.

## Tester maintenant

Dans GitHub Actions, ouvrir [KFS France - cartes haute fréquence 0-72 h](../actions/workflows/france-h72.yml), choisir **Run workflow**, le modèle et un horizon 12, 24 ou 72 heures. Les cartes et `metadata.json` sont disponibles via l'artefact ZIP de l'exécution pendant trois jours.

Sur chaque `push` de modification du moteur, le workflow lance un test réduit sur les quatre modèles, pas la génération complète, pour ne pas mobiliser inutilement les serveurs météorologiques.

## Détection des nouveaux runs

Le workflow [KFS France - détection des nouveaux cycles](../actions/workflows/watch-france-cycles.yml) interroge les sources toutes les 20 minutes et sauvegarde seulement les changements dans `forecast-maps/france/latest-cycles.json`. Un nouveau cycle confirmé à l'échéance +72 h peut déclencher une génération complète en artefact GitHub avec le `GITHUB_TOKEN` du dépôt. Cela ne garantit **pas** une disponibilité immédiate : les produits ECMWF / NOAA sont mis en ligne progressivement, et GitHub Actions peut retarder les événements planifiés.

## Diffusion Discord : étape encore non opérationnelle

Les images France sont **dans les artefacts de GitHub Actions**, pas encore sur un hébergement public stable. La commande `/modele` du bot Cloudflare reste orientée vers les cartes Europe existantes.

Pour activer la diffusion France sans accumuler des centaines d'images dans l'historique Git, il faut brancher un cache de cartes (Cloudflare R2 conseillé) avec une politique d'expiration, puis ajouter l'option `zone=france` aux commandes Discord. La connexion Cloudflare actuelle ne possède pas les droits R2 lecture/écriture ; ne pas intégrer le bot avant que ce blocage soit levé.

Les workflows actuels et les anciennes cartes Europe ne sont pas remplacés.
