# Collecte Xweather /foudre toutes les 2 minutes — PROTOTYPE DÉSACTIVÉ

Ce prototype est préparé dans `worker/kfs-meteo-worker-foudre-archive-d1.js` et ne doit **pas** être activé avant validation des licences, de l'accès Xweather aux événements et du budget.

## Fonctionnement

- Un Cron Cloudflare `*/2 * * * *` déclenche la collecte à 0, 2, 4, etc. minutes (UTC) ; la ponctualité exacte n'est pas garantie à la seconde.
- Les zones de collecte configurables sont `cherbourg`, `caen`, `rouen`, `alencon`. Leur cercle de collecte est **100 km de rayon**. Les zones ne représentent pas un relevé exhaustif pour une ville arbitraire ; la carte le signale.
- À chaque déclenchement, **une requête /lightning/closest par zone activée** est tentée, dans la limite mensuelle fixée par l'utilisateur. L'API ne renvoie que les décharges des 5 dernières minutes.
- Le fichier D1 enregistre une photographie par zone et par créneau de deux minutes, avec identifiant de décharge, heure UTC, latitude/longitude, type CG/IC et amplitude quand fournie.
- Les événements dupliqués au fil des acquisitions sont supprimés à la lecture par ID stable. La carte `/foudre ville` utilise l'archive pour afficher **jusqu'à 30 minutes d'impacts**, seulement si la période demandée dépasse 5 minutes et que des captures existent dans la zone concernée.
- **Seuls les événements réellement transmis par Xweather** sont affichés. Si Xweather renvoie `warn_no_data`, le snapshot est noté comme sans résultat ; aucun impact n'est fabriqué.
- Les statistiques Lightning Summary de 30 min / 1 h / 6 h / 24 h restent inchangées. Une sélection de 24 h affiche les statistiques sur 24 h mais au maximum **30 min de points historiques**.
- L'archive est limitée à 36 min (30 min + courte marge), puis nettoyée automatiquement même si la collecte est interrompue mais que le cron continue.
- Un endpoint privé `GET /foudre-archive-status` permet de consulter la configuration, la consommation de requêtes et les dernières captures, **uniquement avec `Authorization: Bearer <SETUP_KEY>`**.
- La logique des autres commandes `/meteo`, `/radar` et `/live Weather Underground` n'est pas modifiée.

## Coût et limites réelles

**Attention : une collecte 24 h/24 toutes les 2 minutes ne rentre PAS dans l'offre gratuite Xweather.**

- 1 zone = 720 appels par jour, environ 21 600 appels par 30 jours.
- 4 zones = 2 880 appels par jour, environ 86 400 appels par 30 jours.
- L'endpoint `lightning` a un facteur de coût de **10x**, auquel peut s'ajouter le facteur spatial. Pour 1 zone, **216 000 crédits/mois au minimum** contre 15 000 accès gratuits mensuels. Pour 4 zones, au moins 864 000 crédits/mois. Les commandes `/foudre` ajoutent aussi leurs propres appels.
- La variable `FOUDRE_ARCHIVE_MONTHLY_CALL_LIMIT` bloque le nombre d'appels tentés dans le mois. Ce **n'est pas** une garantie exacte en crédits : lire les métriques `X-Cost-Tokens` et les quotas dans le tableau de bord Xweather. Si le compte facture des dépassements, le contrôle par appels ne protège pas totalement contre des frais.
- Cloudflare D1 est choisi plutôt que Workers KV pour ne pas dépasser rapidement les **1 000 écritures/jour** de KV gratuit avec plusieurs zones ; D1 autorise plus d'écritures sur le palier gratuit.
- La documentation de l'API `lightning` montre un droit d'accès technique de 5 minutes : **elle ne prouve pas que l'enregistrement durable puis la republication sur Discord sont autorisés**. Obtenir une confirmation écrite de Xweather pour ces deux usages.
- En cas d'orage visible sur Blitzortung mais de `warn_no_data` Xweather, l'historique local sera incomplet, quel que soit le Cron.

Sources :
- https://www.xweather.com/docs/weather-api/endpoints/lightning
- https://www.xweather.com/docs/weather-api/getting-started/responses
- https://www.xweather.com/products/weather-api
- https://developers.cloudflare.com/d1/platform/pricing/
- https://developers.cloudflare.com/workers/configuration/cron-triggers/

## Installation : quand les droits et les crédits sont confirmés

1. Faire une sauvegarde du Worker Cloudflare et de ses variables actuelles.
2. Dans Cloudflare **Storage & databases > D1**, créer une base (exemple : `kfs-foudre-archive`). Dans D1 > Console, exécuter le fichier SQL `worker/FOUDRE_ARCHIVE_D1_SCHEMA.sql`.
3. Dans Cloudflare **Worker > Settings > Bindings**, ajouter un binding **D1 Database** vers cette base sous le nom exact `FOUDRE_DB`.
4. Copier tout le code de `worker/kfs-meteo-worker-foudre-archive-d1.js` (bouton GitHub Raw) dans le Worker existant, et déployer.
5. Dans le Worker > Settings > Triggers, ajouter un Cron `*/2 * * * *` (le cron existant éventuel de réenregistrement Discord peut rester). Le code évite de réenregistrer les slash commands toutes les 2 minutes.
6. Ajouter les variables **texte** suivantes dans Cloudflare :
   - `FOUDRE_ARCHIVE_ZONES=caen` (un seul secteur pour le premier test ; `cherbourg,caen,rouen,alencon` si couverture élargie autorisée et financée)
   - `FOUDRE_ARCHIVE_MONTHLY_CALL_LIMIT=0` par défaut — **aucune requête de fond tant que la limite est 0**.
   - `FOUDRE_ARCHIVE_ENABLED=false` par défaut.
   - `FOUDRE_ARCHIVE_RIGHTS_CONFIRMED=false` par défaut.
7. Après autorisation écrite de la conservation/réutilisation et décision explicite sur le coût, fixer un plafond d'appels, puis mettre les deux indicateurs `FOUDRE_ARCHIVE_ENABLED` et `FOUDRE_ARCHIVE_RIGHTS_CONFIRMED` à `true`.
8. Contrôler l'état : appeler `/foudre-archive-status` avec le `SETUP_KEY` existant **sans divulguer sa valeur**. Chercher `monthlyUsed`, `latest` et `active`.
9. Lancer `/foudre Caen` sur 30 minutes. Au démarrage, la carte ne dispose que des quelques premières minutes ; le maximum de 30 minutes n'est atteint qu'après 30 minutes de collecte régulière avec données réelles.

## Tests effectués / restant à faire

- Syntaxe Worker JavaScript vérifiée.
- Prototypes de réponses Xweather, D1 et texte Discord testés sans credentials réels.
- Aucune requête Xweather réelle, aucune base D1 Cloudflare créée et aucun déploiement sur le Worker de production réalisés.
- Avant mise en production, confirmer la disponibilité et le coût réel de l'API Lightning pour les zones choisies, ainsi que les droits de conservation.

## Diagnostic possible si les valeurs restent vides

Si `/foudre` indique `warn_no_data` pour `/lightning/closest` sur un secteur alors que Lightning Summary indique une activité antérieure, c'est cohérent avec le fait que le Summary couvre la période longue et `/lightning/closest` seulement les 5 dernières minutes. Comparer les deux réseaux ou demander à Xweather de vérifier la couverture de la zone.
