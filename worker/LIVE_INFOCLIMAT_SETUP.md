# KFS MÉTÉO — /live Infoclimat uniquement

## Ce qui change

`worker/kfs-meteo-worker-foudre-infoclimat.js` reprend le Worker KFS complet. **Seule la commande `/live ville` est remplacée** : elle ne contacte que l'OpenData Infoclimat. Les commandes `/meteo`, `/radar`, `/foudre` restent présentes ; elles utilisent leurs sources respectives.

Le bot géocode la commune exactement comme `/radar`, récupère la liste GeoJSON des stations open data, trie les stations par distance géographique, demande un paquet de relevés récents pour **12 stations voisines au maximum**, puis choisit la **plus proche dont un relevé datant de moins de 100 minutes est disponible**. L'affichage précise station, distance, date et heure du relevé et mesures disponibles. Si aucune station ne répond, la commande affiche une indisponibilité claire. Aucune donnée de modèle et aucun relevé inventé.

## Important : clé API Infoclimat et adresse IP

Infoclimat impose une clé d'API pour l'accès automatisé : https://www.infoclimat.fr/opendata/index.php . L'API authentifie aussi l'**adresse IP sortante du serveur**, déclarée à la création de la clé. **Cloudflare Workers n'a pas d'IP sortante publique fixe dans la configuration standard**, donc l'accès direct peut renvoyer `Wrong ip address`, même si la clé est correcte.

**Conseillé** : utiliser un petit relais hébergé sur un serveur ayant une IP sortante fixe (par exemple hébergement web qui le garantit et a autorisé ce service), puis autoriser cette IP lors de la création du jeton Infoclimat.

Le fichier `worker/infoclimat-relay.php` est un exemple de relais privé en PHP 8+, sous réserve de conformité avec les règles de ton hébergeur. Ne pas l'utiliser sans configuration de sécurité.

## Variables Cloudflare (production)

- `INFOCLIMAT_RELAY_URL` : URL HTTPS du relais PHP hébergé sur serveur à IP sortante autorisée, ex. `https://ton-domaine.fr/chemin-protege/infoclimat-relay.php`.
- `INFOCLIMAT_RELAY_SECRET` : secret partagé fort entre le Worker et le relais. Configurer en **Secret Cloudflare**. Ne pas le coller dans GitHub.
- Variante d'essai sans relais : `INFOCLIMAT_API_TOKEN` (**Secret Cloudflare**) suffit à construire l'URL de l'API Infoclimat, mais **la restriction d'IP risque de l'empêcher de fonctionner en production**.

Sur le serveur PHP hébergeant le relais, configurer **hors du répertoire public** les variables d'environnement `INFOCLIMAT_API_TOKEN` et `INFOCLIMAT_RELAY_SECRET` ; elles ne doivent pas figurer dans le fichier PHP accessible publiquement. Le jeton sera transmis par le relais à Infoclimat exclusivement en HTTPS.

Ne déclare pas les anciennes variables Weather Underground et Open-Meteo pour `/live` : elles ne sont plus consultées par cette commande. Tu peux conserver les secrets Xweather et Discord car `/foudre` et `/meteo` en ont toujours besoin.

## Installer et activer

1. Sur Infoclimat OpenData, créer un compte et une clé API **non commerciale**, autorisée pour les stations que tu souhaites republier. Vérifier le respect des licences BY et BY-NC.
2. Identifier l'IP **sortante** du serveur qui interrogera Infoclimat. Celle-ci n'est pas forcément l'IP affichée dans les DNS du site. Confirmer une IP fixe avec l'hébergeur.
3. Si usage via relais : placer `infoclimat-relay.php` sur le serveur stable et configurer les variables d'environnement sur le serveur. Créer un secret de relais aléatoire suffisamment long et le copier dans Cloudflare.
4. Ajouter les secrets nécessaires dans Cloudflare Workers > Settings > Variables and Secrets.
5. Sauvegarder le code actuel, ouvrir `worker/kfs-meteo-worker-foudre-infoclimat.js` dans GitHub, cliquer `Raw`, copier l'ensemble et le déployer dans le Worker existant.
6. Si la commande `/live` est déjà enregistrée sur Discord, elle gardera le même nom et la même option `ville` ; le Worker la traitera immédiatement. Pour actualiser sa description, attendre le cron du Worker ou appeler le POST protégé `/register-live` avec le `SETUP_KEY` existant.
7. Essayer `/live Bourth`, `/live Rouen, 76`, et vérifier l'horodatage et la distance.

## Limitations et vérifications

- Le référentiel GeoJSON inclut seulement les stations publiées en OpenData. Il n'inclut pas toutes les stations privées d'Infoclimat.
- Les champs d'une station peuvent être absents : le message le signale au lieu d'inventer une mesure.
- Le vent est présenté en km/h, la pression en hPa, la pluie en mm selon les conventions usuelles de l'API : à vérifier à l'aide d'un vrai échantillon avant publication.
- Catalogue conservé en cache 24 h, mesures mises en cache 15 min. L'association recommande un *fair use* ; éviter les rafraîchissements en continu.
- En cas d'absence de données récentes parmi les 12 stations voisines, aucun retour de modèle n'est substitué.
- La liste des stations et la réponse réelle de l'API n'ont **pas pu être testées** ici à cause des accès bloqués et de l'absence de clé. Il faut valider les noms exacts des champs de la réponse réelle avant le déploiement en production.
- Les tests réalisés utilisent des réponses simulées et vérifient la syntaxe JavaScript, le tri par distance, le choix du relevé valide et la mise en forme du message.

## Sources

- Documentation et clé : https://www.infoclimat.fr/opendata/
- GeoJSON des stations : https://www.infoclimat.fr/opendata/stations_xhr.php?format=geojson
- Format d'appel API et IP : https://forums.infoclimat.fr/f/topic/56709-ouverture-dune-rubrique-open-data-sur-infoclimat/
- Exemples de champs `hourly` : https://forums.infoclimat.fr/f/topic/57089-cas-dusage-et-questions-api/
- Licence : https://www.data.gouv.fr/datasets/liste-des-stations-en-open-data-du-reseau-meteorologique-infoclimat-static-et-meteo-france-synop
