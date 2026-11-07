# KFS MÉTÉO — /foudre : 5 min, 30 min, 1 h, 6 h, 24 h

## Fichier complet prêt à copier

`worker/kfs-meteo-worker-foudre-periodes.js` est une version intégrale du Worker Cloudflare. Elle conserve sans changement la logique des commandes `/meteo`, `/radar` et `/live` **Infoclimat**, en partant de la version complète préparée dans `feature/live-infoclimat-only-20261107`. Elle améliore uniquement `/foudre`.

## Paramètres Discord

`/foudre ville [periode]` :

- `ville` obligatoire : exemple `Bourth`, `Rouen, 76` ; même géocodage que `/radar`.
- `periode` facultative (type nombre entier, choix Discord) : `5` = 5 minutes, `30` = 30 minutes, `60` = 1 heure, `360` = 6 heures, `1440` = 24 heures.
- **30 minutes est la valeur par défaut**, même si Discord n'a pas encore mis à jour la définition de slash command.
- Cercle de recherche **100 km autour de la ville**, toutes périodes confondues.

## Source et interprétation

Pour la carte des impacts **nuage-sol CG uniquement** des cinq dernières minutes, conserve l'API Xweather `/lightning/closest` actuelle ; couleur et taille selon la polarité et le courant de crête. Les valeurs affichées sur la carte sont en kiloampères (kA). Les 5 minutes sur la carte NE représentent PAS la durée sélectionnée au-delà de 5 minutes.

Pour les périodes **30 min, 1 h, 6 h et 24 h**, une deuxième requête distincte utilise `https://data.api.xweather.com/lightning/summary/closest` avec `radius=100km`, `from=-30minutes` / `-1hour` / `-6hours` / `-24hours` et `to=now`.

Le bilan affiche le total CG + IC, le nombre CG et IC, les polarités positives/négatives **toutes décharges confondues (CG et IC)** et les crêtes maximales agrégées en kA lorsque disponibles. Il ne donne pas les coordonnées des impacts de la période longue. Ne pas appeler les polarités du bilan « CG+ / CG− » : l'API Summary inclut IC.

Le Worker vérifie `summary.range.fromTimestamp` et `toTimestamp` pour empêcher qu'un résultat de 5 minutes soit présenté comme un bilan de 30 minutes. En cas de fenêtre inconnue / invalide, un message indique que les statistiques sont indisponibles. Aucun chiffre n'est fabriqué.

Si Lightning Summary est indisponible ou refusé pour le compte, la carte des cinq dernières minutes peut toujours s'afficher ; si la carte échoue, les statistiques réelles déjà récupérées sont présentées sous forme de texte. Si aucun CG n'est détecté, aucune image vide n'est générée.

## Quotas, tarifs et conditions

Xweather propose 15 000 accès mensuels gratuits (https://www.xweather.com/products/weather-api). Un « appel » n'équivaut pas forcément à un accès facturé. Le système de coût dépend du multiplicateur de l'endpoint, de la zone géographique et de la durée temporelle, et est exposé dans `X-Cost-Tokens`.

Une commande avec période de 30 minutes ou plus peut engendrer **deux requêtes API** (Lightning + Lightning Summary) avant l'utilisation du cache. La carte garde un cache de 90 s par zone ; Summary utilise 120 s par zone et période. Le cache limite les appels mais n'impose pas un plafond strict de crédits mensuels.

La documentation Lightning Summary indique une fenêtre disponible jusqu'à 24 h. Il reste à confirmer **sur ton compte** que l'endpoint et les périodes demandées sont accessibles sans supplément. L'accès aux impacts individuels au-delà des 5 minutes nécessite l'extension Lightning Enterprise : la carte reste donc limitée aux cinq dernières minutes.

Sources de référence :
- https://www.xweather.com/docs/weather-api/endpoints/lightning-summary
- https://www.xweather.com/docs/weather-api/endpoints/lightning
- https://www.xweather.com/docs/weather-api/getting-started/responses

## Déploiement (non effectué)

1. Sauvegarder le code actuel du Worker dans Cloudflare.
2. Sur GitHub, ouvrir `worker/kfs-meteo-worker-foudre-periodes.js` depuis la branche `feature/foudre-periodes-summary-20261107`, puis `Raw`, sélectionner tout, copier.
3. Dans Cloudflare Worker > Edit code, coller le fichier complet puis déployer. Aucun nouveau secret : `XWEATHER_CLIENT_ID` et `XWEATHER_CLIENT_SECRET` sont ceux déjà présents.
4. Mettre à jour l'enregistrement du slash command `/foudre` : le cron du Worker réenregistre les commandes lorsqu'il est actif ; ou envoyer un `POST /register-foudre` avec l'en-tête `Authorization: Bearer <SETUP_KEY>` existant. **Ne jamais partager le SETUP_KEY ni les identifiants API.** Sans réenregistrement, la commande existante continuera d'utiliser automatiquement 30 minutes, mais n'affichera pas le menu de périodes.
5. Dans Discord, vérifier `/foudre Bourth` (30 minutes), puis choisir `5 minutes`, `1 heure`, `6 heures`, `24 heures` dans le menu, et contrôler les résultats.
6. Sur Cloudflare > Observabilité, consulter les journaux uniquement si une requête renvoie une erreur. Les causes d'échec sont distinguées : accès Summary refusé, quota, fenêtre invalide, carte PNG indisponible.

## Tests réalisés

- Analyse syntaxique du Worker JavaScript : OK.
- Vérification que le corps des commandes `/meteo`, `/radar`, `/live` Infoclimat et leurs enregistrements est identique au fichier de base : OK.
- Validation de toutes les durées, avec défaut à 30 min ; refus des durées invalides : OK.
- Réponses JSON Lightning Summary simulées pour 30 min / 1 h / 6 h / 24 h : OK.
- Rejet d'un résumé renvoyant une période incorrecte : OK.
- Test de refus d'accès `insufficient_scope` et du cache Summary : OK.
- **Non testé sur l'API Xweather avec tes véritables identifiants**, non testé sur Discord Cloudflare en production et aucun déploiement effectué.
