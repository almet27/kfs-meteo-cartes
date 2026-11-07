# Commande /foudre — KFS MÉTÉO

La version **worker/kfs-meteo-worker-foudre.js** est une variante complète du Worker existant avec ajout de /foudre. Elle ne change pas les fonctions /meteo et /radar.

## Affichage

- Commande Discord : /foudre ville (par exemple /foudre Bourth ou /foudre Rouen, 76).
- Même recherche de communes que /radar, centre sur la ville choisie.
- Carte PNG de 600 × 600, rayon de 100 km (limite de l'offre Xweather standard).
- Impacts nuage-sol (CG), sur une fenêtre de cinq minutes précédant la collecte.
- Impacts positifs jaunes et négatifs bleus ; plus forts courants étiquetés sur la carte en kA, détails et attribution dans le message.
- Une carte sans impact en l'absence de détection ; jamais d'impacts simulés en cas d'erreur.

## Activer

1. Créer un compte gratuit sur https://www.xweather.com/products/weather-api.
2. Récupérer le Client ID et Client Secret de l'application Xweather.
3. Dans Cloudflare Workers, ouvrir le Worker qui sert les interactions Discord. Dans Settings > Variables and Secrets, ajouter deux secrets (pas des variables en clair) : XWEATHER_CLIENT_ID et XWEATHER_CLIENT_SECRET. Ne jamais les partager dans un salon, une capture ou GitHub.
4. Remplacer le code complet du Worker avec worker/kfs-meteo-worker-foudre.js, puis déployer. Le fichier original worker/kfs-meteo-worker-corrige.js n'a pas été modifié.
5. Enregistrer /foudre : exécution programmée du Worker, ou POST vers /register-foudre avec Authorization: Bearer <SETUP_KEY> comme pour /register-radar.
6. Taper /foudre Bourth dans Discord.

## Quota gratuit et limites

Xweather : 15 000 accès gratuits mensuels, coefficient 10 pour /lightning. Cela représente au maximum 1 500 recherches /lightning par mois si aucun autre appel n'est effectué avec ce compte. Cache de 90 secondes par ville pour réduire la consommation, mais aucune limite budgétaire globale stricte n'est garantie par le code : surveiller le tableau de bord Xweather.

L'API standard donne les observations des cinq dernières minutes, dans un rayon de 100 km, maximum 1 000 décharges par réponse. Il ne s'agit pas d'une carte historique et l'affichage n'est pas mis à jour automatiquement après l'exécution de la commande.

Des données Xweather sont soumises à des conditions de licence et à des règles d'attribution. Vérifier l'autorisation d'afficher ces données dans le salon Discord concerné avant toute diffusion large ou commerciale : https://www.xweather.com/terms. Dans le message, l'attribution est liée à Xweather.

Documentation : https://www.xweather.com/docs/weather-api/endpoints/lightning

## Tests et déploiement

La syntaxe JavaScript de la variante a été vérifiée. Un rendu simulé (sans requête réseau) de deux impacts dans la zone a été testé ; il n'a pas encore été vérifié de bout en bout avec une vraie clé Xweather ni avec Discord. Le déploiement sur Cloudflare reste à faire. En cas d'indisponibilité du fond GeoJSON, le Worker affiche tout de même la grille et les impacts.

Source du fond : https://github.com/gregoiredavid/france-geojson.
