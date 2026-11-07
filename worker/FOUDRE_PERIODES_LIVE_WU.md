# KFS MÉTÉO — /foudre avec périodes, sans changement de /live Weather Underground

Ce dossier propose une version complète du Worker correspondant à la dernière version de production confirmée :

`worker/kfs-meteo-worker-foudre-periodes-live-wu.js`

Elle conserve les commandes `/meteo`, `/radar` et `/live` **Weather Underground avec repli Open-Meteo**, sans modifier leur logique ni leurs définitions. Seule la commande `/foudre` évolue.

## Utilisation

- `/foudre ville` : par défaut 30 minutes de statistiques + carte des impacts nuage-sol des cinq dernières minutes.
- `/foudre ville periode` : 5 min (5), 30 min (30), 1 heure (60), 6 h (360) ou 24 h (1440).
- `ville` est la même option obligatoire qu'avant. `periode` est une option entière facultative avec choix Discord prédéfinis.
- Rayon : 100 km autour du centre de la ville saisie.

### 5 minutes

Une seule API : `/lightning/closest`, qui renvoie les décharges individuelles CG localisables en temps quasi réel. Carte seulement sur cette période, avec intensités en kA et polarité +/-.

### 30 minutes à 24 heures

Statistiques issues de `/lightning/summary/closest`, avec `from=-30minutes`, `-1hour`, `-6hours` ou `-24hours`, `to=now`, `radius=100km`. Affichage des totaux CG + IC, des deux types CG/IC, des polarités agrégées (TOUTES DÉCHARGES, y compris IC) et des courants maximaux agrégés en kA. Le Worker vérifie les bornes temporelles de la réponse pour ne jamais présenter une fenêtre incorrecte comme un total sur la période demandée.

La carte reste **toujours limitée aux cinq dernières minutes**. Les statistiques longues n'ont pas les coordonnées nécessaires à une carte historique. Les impacts au-delà des cinq dernières minutes nécessitent l'extension Lightning Enterprise.

Si Summary n'est pas autorisé, refusé ou indisponible, les statistiques ne sont pas inventées et la carte cinq minutes demeure accessible. Si la carte ne peut être générée, les statistiques obtenues sont conservées dans le message.

## Coût

Xweather propose 15 000 accès API par mois au palier gratuit, mais le coût d'une requête dépend du multiplicateur d'endpoint, de la taille de la zone et de la fenêtre temporelle (`X-Cost-Tokens`). Une requête longue implique en principe deux appels distincts avant caches : Lightning et Lightning Summary. Caches : 90 s pour Lightning et 120 s pour Summary, par ville/période. Vérifier le quota et l'autorisation d'accès à Summary dans le tableau de bord Xweather avant usage intensif.

## Déploiement (pas encore effectué)

1. Sauvegarder le code du Worker actuellement déployé dans Cloudflare.
2. Ouvrir le fichier complet `kfs-meteo-worker-foudre-periodes-live-wu.js` depuis cette branche GitHub, cliquer Raw, copier tout le contenu, le coller dans Edit code de ton Worker Cloudflare et déployer.
3. Aucun nouveau secret à ajouter : les secrets Xweather existants sont utilisés. Les autres secrets Discord/WU restent inchangés.
4. Mettre à jour la commande Discord : le Worker la réenregistre via son déclencheur cron lorsqu'il est actif, ou par POST vers `/register-foudre` avec le header `Authorization: Bearer <SETUP_KEY>`. Garder la clé secrète hors du chat et de GitHub.
5. Tester `/foudre Bourth` (30 minutes par défaut) et chacune des autres périodes. Si le menu n'apparaît pas, la slash command Discord n'est pas encore réenregistrée.

## Vérifications

- Syntaxe JavaScript compilée sans erreur.
- Comparaison des corps des commandes météo, radar et live WU avant/après : identiques.
- Bilan Lightning Summary testé avec des réponses simulées couvrant 30m, 1h, 6h et 24h ; fenêtre incorrecte rejetée ; cache et refus d'accès validés.
- Aucune clé Xweather réelle n'a été utilisée dans les tests et aucun déploiement Cloudflare ou Discord en production n'a été effectué.

Docs Xweather : https://www.xweather.com/docs/weather-api/endpoints/lightning-summary

Variante alternative si `/live` Infoclimat a été déployé entre-temps : ouvrir le fichier de la branche `feature/foudre-periodes-summary-20261107` : `worker/kfs-meteo-worker-foudre-periodes.js`.


## Correction : activité orageuse visible mais carte vide (novembre 2026)

- `filter=all` est maintenant envoyé explicitement à Xweather pour recevoir CG et IC.
- La **carte affiche les CG** : jaune (positif), bleu (négatif), gris (courant non fourni) ; et les **IC en violet** (cercle creux), afin de distinguer les décharges dans le nuage des impacts au sol.
- Une décharge sans intensité connue reste visible (valeur `n/d`) au lieu d'être rejetée.
- Le message Discord donne le nombre total de décharges reçues, la répartition CG / IC et les exclusions pour données trop anciennes ou sans coordonnées.
- Si aucune décharge n'est renvoyée, la carte de repérage reste affichée ; si Xweather est inaccessible, le message le dit explicitement et ne présente pas le fond vide comme une observation d'absence de foudre.
- Les refus HTTP de Discord lors du dépôt du PNG ne sont plus silencieux : un message d'erreur apparaît et les journaux Cloudflare donnent le statut d'envoi.
- Le cache des impacts a été versionné pour éviter de réutiliser un ancien format CG seulement.
- Les statistiques de 30 minutes à 24 heures restent inchangées et indépendantes.
- Attribution : Xweather demande un lien « Powered by Vaisala Xweather » (https://www.xweather.com/docs/weather-api/resources/attribution). Le lien reste mais sous forme d'un crédit bref et discret en bas ; la suppression complète ne respecterait pas leur guide d'attribution.

**Tests** : syntaxe du Worker validée ; réponses Xweather simulées incluant CG, IC, absence de courant, données périmées, et zone sans décharge ; cache vérifié. **Aucun essai authentifié réel / aucun déploiement Cloudflare effectué.**
