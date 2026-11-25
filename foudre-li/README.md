# KFS MÉTÉO — carte foudre satellitaire EUMETSAT / MTG Lightning Imager

Cette version utilise des **positions réelles d'éclairs optiques détectés par satellite**, et non des impacts nuage-sol confirmés. Produit **EUMETSAT MTG LI L2-LFL**, collection **`EO:EUM:DAT:0691`** (policy `NoConditions`).

## Fichiers

- `foudre-li/collect.py` : interroge EUMETSAT Data Store, décompresse les produits ZIP, lit les NetCDF BODY et retient uniquement les observations dans et autour de la France.
- `foudre-li/flash-points.json` : archive courte rendue publique sur GitHub ; la version initiale est explicitement `not_configured`, sans faux points.
- `.github/workflows/eumetsat-li-foudre.yml` : lance les tests et la collecte toutes les 10 minutes environ, sous réserve des délais de GitHub Actions.
- `foudre-li/test_collect.py` : tests avec NetCDF synthétique, sans requêtes réelles.
- `worker/kfs-meteo-worker-foudre-eumetsat-li.js` : Worker complet qui conserve `/meteo`, `/radar`, `/live Weather Underground` et les statistiques Xweather de `/foudre`.

## Activation (à faire une fois)

1. **Fusionner la PR** sur la branche `main` du dépôt `almet27/kfs-meteo-cartes` après vérification. Les déclenchements programmés GitHub ne fonctionnent que depuis la branche par défaut.
2. Créer un compte gratuit sur [EUMETSAT User Portal](https://user.eumetsat.int/) ; dans le portail accéder à [API key](https://api.eumetsat.int/api-key/) et générer les identifiants du **Data Store**.
3. Sur GitHub : `Settings > Secrets and variables > Actions > New repository secret`. Créer **deux** secrets : `EUMETSAT_CONSUMER_KEY` et `EUMETSAT_CONSUMER_SECRET`. **Ne jamais les inscrire dans le code, dans Discord ou dans un message public.**
4. Sur GitHub : `Actions > EUMETSAT LI — carte des éclairs optiques KFS > Run workflow` sur `main` pour effectuer une première acquisition réelle. Les tests s'exécutent même sans secrets ; la collecte est alors ignorée.
5. Si la collecte réussit, ouvrir [`foudre-li/flash-points.json`](https://github.com/almet27/kfs-meteo-cartes/blob/main/foudre-li/flash-points.json) et contrôler : `state=ready`, `updated_utc`, `latest_product_end_utc`, nombre de points. **Zéro point** peut être réel dans le rectangle géographique, mais les produits doivent d'abord avoir été réellement acquis.
6. Sauvegarder le Worker Cloudflare actuellement en production. Sur GitHub, ouvrir `worker/kfs-meteo-worker-foudre-eumetsat-li.js` en mode `Raw`, copier le code entier et remplacer le Worker, puis **Deploy**. Aucun secret EUMETSAT n'est à configurer dans Cloudflare ; les secrets sont uniquement sur GitHub.
7. Dans Discord, tester `/foudre Caen` puis `/foudre Cherbourg` avec 30 minutes. Le texte doit annoncer distinctement : points **LI satellite**, statistiques Xweather et heure de la dernière observation EUMETSAT.

## Fonctionnement et limites

- Les fichiers EUMETSAT Data Store LFL livrés par l'API couvrent habituellement des tranches d'environ **10 minutes**. Le workflow vérifie les nouveautés toutes les **10 minutes**, avec des retards possibles à la diffusion et dans GitHub Actions.
- Le collecteur cherche sur les **3 dernières heures** pour récupérer les produits livrés en retard, puis conserve **2 heures** d'éclairs en France. Il mémorise les produits déjà traités pour éviter les doublons.
- Pour 5 minutes, la carte affiche les 5 dernières minutes demandées **uniquement parmi les produits déjà reçus**, et peut donc sembler vide même si un orage se produit. Préférer **30 minutes**.
- Pour 30 minutes / 1 heure, carte sur la période demandée. Pour 6 heures / 24 heures, les statistiques Xweather couvrent la période sélectionnée, mais la carte satellitaire affiche au maximum **2 heures** (mention explicite).
- Dans Discord, chaque requête `/foudre ville` filtre avec un **vrai rayon géodésique de 100 km**.
- Le collecteur conserve uniquement un rectangle autour de la France et les zones maritimes proches : longitude **−7,5° à +10°**, latitude **40,5° à 52°**.
- **Statistiques au sol Xweather et carte EUMETSAT ne sont pas des mesures directement comparables.** La carte satellitaire ne connaît ni polarité ni intensité électrique en kA et ne distingue pas CG/IC. N'interprétez pas les points comme impacts au sol.
- Si le dernier produit a plus de 50 minutes, ou si l'acquisition/lecture échoue, le bot marque la carte **non alimentée/périmée**, sans annoncer zéro activité.
- La source attribuée est [EUMETSAT MTG LI](https://data.eumetsat.int/) (collection `EO:EUM:DAT:0691`, NoConditions). La source Xweather conserve son lien d'attribution dans la partie statistiques.
- Le script ne publie jamais des observations fictives. Les tests de NetCDF sont synthétiques mais servent uniquement à valider le décodeur, **jamais** à remplir la carte en production.

## Diagnostics

- `state=not_configured` : secrets absents ou collecte pas encore exécutée sur `main`.
- Échec 401/403 au Data Store : compte, clé, expiration de jeton, ou licence NRT selon produit. Vérifier `My Data Licenses` sur le portail EUMETSAT.
- Aucun produit trouvé : le collecteur sort en erreur et garde la publication précédente. Vérifier les délais Data Store, puis relancer le workflow.
- Erreur de décodage ZIP/NetCDF : le workflow échoue et **ne remplace pas** le dernier relevé valide. Examiner les logs GitHub Actions, sans publier de secrets.
- La page de statut du dépôt ne garantit pas une exécution GitHub exactement toutes les 10 minutes : la programmation `schedule` peut subir des retards.
- `/foudre` n'utilise pas le prototype Xweather D1 à appels multiples. **Aucune base D1 et aucun Cron Cloudflare 2 minutes ne sont nécessaires** pour cette solution.

## Références

- https://api.eumetsat.int/data/browse/collections/EO%3AEUM%3ADAT%3A0691?format=html
- https://user.eumetsat.int/data-access
- https://user.eumetsat.int/resources/user-guides/frequently-asked-questions-for-data-store
- https://satellite-resources.readthedocs.io/en/latest/MTG%20Lightning%20Imager%20data%20visualization.html

**État actuel :** le collecteur et le Worker sont préparés sur une branche, les tests GitHub passent sans clés. Aucun compte EUMETSAT connecté, aucune collecte satellitaire réelle validée et aucun déploiement Cloudflare réalisés.
