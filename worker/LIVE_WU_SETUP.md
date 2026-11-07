# /live Weather Underground — KFS MÉTÉO

## Version préparée

Fichier complet : `worker/kfs-meteo-worker-foudre-live-wunderground.js`.

Conserve `/meteo`, `/radar`, `/foudre` et `/live`. Ne modifie PAS le Worker actuellement en production. Ajout d'une source PWS Weather Underground prioritaire pour `/live ville` et repli vers Open-Meteo (explicitement identifié comme modèle) si les stations ne répondent pas.

Station personnelle du propriétaire du Discord : `IBOURTH5`, **Bourth – la Morière**, dans le secteur de Bourth. La commande `/live Bourth` vérifie directement cette station.

Pour les autres communes, l'API `v3/location/near` recherche les PWS proches et les données `v2/pws/observations/current` fournissent les mesures. Les stations au-delà de 40 km, les relevés de plus de 25 minutes et les données ayant échoué au contrôle qualité sont écartés.

## Conditions d'utilisation

**Important :** la gratuité du Discord et le fait de contribuer au réseau WU ne suffisent pas à garantir l'autorisation de republier des données de stations tierces dans un serveur communautaire. La licence personnelle Weather Underground autorise un usage personnel non commercial et exige d'attribuer la source, tout en limitant la redistribution. Demander une confirmation écrite à Weather Underground avant une publication publique systématique.

Conditions : https://wx-next-privacy.vercel.weather.com/privacy/terms-of-use (section 18 « Personal Weather Station (PWS) Data Feed Terms »).

Documentation officielle :
- https://www.wunderground.com/pws-api/utility/search/near
- https://www.wunderground.com/pws-api/observations/current-conditions

## Activer seulement après confirmation de la licence

1. Ouvrir le compte Weather Underground lié à `IBOURTH5` : https://www.wunderground.com/member/api-keys ; récupérer sa clé API PWS.
2. Dans Cloudflare Workers > KFS Worker > Settings > Variables and Secrets, créer le **Secret** `WEATHER_UNDERGROUND_API_KEY` (jamais dans le code ou le chat).
3. Une fois l'autorisation de diffusion confirmée, ajouter la variable `WEATHER_UNDERGROUND_DISCORD_ENABLED` avec valeur `true` (type texte non secret). **Sans cette variable, la source Weather Underground reste désactivée** et `/live` utilise les estimations Open-Meteo.
4. Après sauvegarde du Worker actif, copier toute la version `kfs-meteo-worker-foudre-live-wunderground.js` dans Cloudflare `Edit code` puis `Deploy`.
5. Si `/live` était déjà enregistré, aucune réinscription n'est nécessaire. Sinon utiliser le cron du Worker ou son endpoint protégé `/register-live`, jamais publier `SETUP_KEY`.
6. Tester `/live Bourth`, puis `/live Rouen` : une station physique n'est affichée que si elle est accessible, suffisamment proche et à jour. Le message indique le type de données et l'identifiant de station.

## Quotas et cache

Le programme PWS a historiquement annoncé 1 500 appels/jour et 30 appels/minute. **Ces chiffres proviennent d'une annonce ancienne et peuvent avoir changé**. Les conditions propres au compte prévalent.

Le cache Cloudflare est de 5 minutes par commune ; il réduit la consommation sans garantir un plafond global. Une recherche d'une autre commune peut nécessiter un appel de découverte et jusqu'à quatre lectures PWS. Le rafraîchissement ne doit pas être automatisé à grande fréquence.

## Vérifications techniques

- Compilation JavaScript de la variante : réussie.
- Génération d'un message PWS simulé : réussie.
- Simulation d'un appel de recherche PWS proche et d'une observation actuelle, avec rejet des stations non conformes : réussie.
- Pas de véritable appel Weather Underground (la clé du compte n'est pas disponible ici).
- Pas de test Discord ni de déploiement Cloudflare en production.

Ne jamais afficher ou enregistrer la clé API dans un fichier GitHub public. Les requêtes WU sont authentifiées dans le Worker via ses secrets et le message Discord ne comprend que les valeurs publiques.
