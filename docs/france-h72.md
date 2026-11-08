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

Le workflow [KFS France - détection des nouveaux cycles](../actions/workflows/watch-france-cycles.yml) contrôle ECMWF / NOAA toutes les 20 minutes. Les cartes Europe peuvent être regénérées plus tôt lorsqu'un nouveau run est détecté. Les mises à jour France automatiques restent suspendues tant que la publication du site complet et le bot Discord ne sont pas validés.

## Hébergement GRATUIT prévu : GitHub Pages

Aucun abonnement Cloudflare R2 ni stockage o2switch ne sont nécessaires.

Le script `scripts/build_france_pages.py` construit un site temporaire **sans ajouter les images dans l'historique Git**. Il récupère les dernières archives GitHub Actions par modèle, les convertit en WebP et prépare `forecast-maps/france/metadata.json`. Le site conserve également les cartes Europe et les ressources existantes afin d'éviter de casser le site.

Sécurités de la publication finale :
- les 4 modèles IFS, AIFS, GFS et AIGFS doivent avoir tous leurs pas natifs jusqu'à +72 h ;
- aucun pas manquant n'est remplacé par une image artificielle ;
- le run de chaque modèle doit correspondre au dernier cycle confirmé ;
- la taille totale du site doit rester sous 450 Mo.

Le workflow [Préparer GitHub Pages](../actions/workflows/pages-france-snapshot.yml) est en mode validation uniquement par défaut. `publish=false` produit un rapport sans déploiement ; `publish=true` exige que l'administrateur ait choisi **Settings → Pages → Source : GitHub Actions**. Attention : Pages ne contient qu'un site par dépôt, donc son déploiement peut remplacer un site Pages existant ; ne pas activer sans vérification.

## Discord

La commande `/modele` de Cloudflare fonctionne actuellement avec les cartes Europe ; le choix `zone=france` ne sera activé qu'après validation des liens HTTPS publics du nouveau site Pages, pour éviter des liens cassés.

Ne pas considérer `/modele` France comme déployé tant que la migration des cartes et la commande Discord n'ont pas été testées de bout en bout.
