# KFS Météo — commande /live ville

Le fichier `worker/kfs-meteo-worker-foudre-live.js` est une version **complète** du Worker Discord qui conserve `/meteo`, `/radar` et `/foudre` et ajoute `/live ville`.

## Données et limites

- `Open-Meteo /v1/forecast` (champs `current`) : température, ressenti, humidité, point de rosée, pluie, averses, neige, nuages, visibilité, vent, rafales, pression, CAPE, code météo et heure de validité.
- `Open-Meteo air-quality` (`current`), données CAMS : AQI européen, PM2,5, PM10, ozone et UV. Si ce fournisseur échoue, le bulletin météo reste disponible.
- Source locale : mêmes communes françaises et même service de géocodage que `/radar` (ex. `/live Bourth`, `/live Rouen, 76`).
- IMPORTANT : ces données proviennent de **modèles météorologiques**, pas d'une station observant réellement les conditions au centre de la commune. Ne pas les présenter comme des mesures instrumentales en direct.
- Horodatages `timezone=GMT` restitués dans le fuseau `Europe/Paris`. Si la donnée météo a plus de trois heures, un avertissement le précise.
- Il n'existe pas de vraie promesse de fonctionnement en temps réel sans délai : les modèles sont réactualisés par cycles.

## Installer

1. Ouvrir `worker/kfs-meteo-worker-foudre-live.js` depuis cette branche, cliquer `Raw` et copier tout le code.
2. Dans Cloudflare Workers > le Worker Discord KFS actif > Edit code, conserver une sauvegarde du code déployé, puis remplacer par le nouveau fichier et déployer.
3. Les secrets existants `DISCORD_BOT_TOKEN`, `SETUP_KEY`, `XWEATHER_CLIENT_ID`, `XWEATHER_CLIENT_SECRET` restent ceux du Worker existant. `/live` n'a **pas besoin d'une nouvelle clé API**.
4. L'enregistrement Discord est effectué par le déclencheur programmé du Worker, **s'il existe et s'il s'exécute**. Sinon envoyer un `POST /register-live` sur l'adresse du Worker avec `Authorization: Bearer <SETUP_KEY>` (identique au dispositif pour `/foudre`). Il n'est pas nécessaire de mettre la clé dans le code ou de la publier.
5. Sur Discord, taper `/live Bourth` ou `/live Rouen, 76`.

## Tests effectués

- Analyse syntaxique du Worker JavaScript : OK.
- Test de génération d'un bulletin avec des données simulées : OK (sans inventer de valeurs en production).
- **Non testé** avec les API Open-Meteo en ligne ni avec l'application Discord en production.
- Le Worker Cloudflare actif n'a pas été modifié automatiquement.

## Usage

Vérifier les conditions d'utilisation de l'API gratuite Open-Meteo : https://open-meteo.com/en/terms ; usage non commercial gratuit sous limites, licence commerciale nécessaire dans d'autres cas.

Sources : https://open-meteo.com/en/docs et https://open-meteo.com/en/docs/air-quality-api
