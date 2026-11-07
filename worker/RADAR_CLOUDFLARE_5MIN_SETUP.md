# Radar KFS MÉTÉO : publication Cloudflare toutes les 5 minutes

## Pourquoi cette solution ?

GitHub Actions ne lance pas à l'heure les exécutions programmées du workflow RainViewer. Les derniers runs réussis ont été provoqués par des modifications du dépôt, pas par le cron automatique. GitHub documente des déclenchements programmés retardés ou supprimés.

Pour ne pas remplacer le bot Discord, un second Worker Cloudflare, indépendant, déclenche le workflow GitHub via son API toutes les cinq minutes. GitHub vérifie ensuite s'il existe une observation RainViewer plus récente avant de reconstruire le GIF.

**La vérification peut être toutes les 5 minutes, mais RainViewer fournit généralement de nouvelles observations toutes les ~10 minutes.** Une vérification n'est pas une nouvelle image garantie.

## Installation (sans modifier le Worker Discord)

1. Ouvrir https://github.com/settings/personal-access-tokens/new et créer un **fine-grained personal access token**.
2. Limiter le jeton à **Only select repositories : almet27/kfs-meteo-cartes** et lui donner seulement **Actions: Read and write**. Noter sa date d'expiration. Ne jamais transmettre ce jeton dans le chat, Discord ou GitHub.
3. Cloudflare > Workers & Pages : créer un Worker distinct, nommé **kfs-radar-scheduler**.
4. Ouvrir https://github.com/almet27/kfs-meteo-cartes/blob/main/worker/kfs-radar-cloudflare-scheduler.js, cliquer **Raw**, copier tout le JavaScript dans l'éditeur Cloudflare du nouveau Worker, puis **Deploy**.
5. Dans **Settings > Variables and Secrets**, créer un **Secret** nommé GITHUB_RADAR_DISPATCH_TOKEN avec la valeur du jeton GitHub. Ne pas choisir une variable publique.
6. Dans **Settings > Triggers > Cron Triggers**, ajouter la programmation suivante (cinq champs, UTC) :

       */5 * * * *

7. Consulter https://<adresse-du-nouveau-worker>.workers.dev/status. La réponse doit contenir enabled: true. Ce statut n'indique que la présence d'un secret, pas le succès des publications.
8. Ouvrir https://github.com/almet27/kfs-meteo-cartes/actions/workflows/rainviewer-discord.yml et chercher les nouvelles exécutions ayant l'événement **workflow_dispatch**.
9. Quand le workflow a publié une nouvelle image, relancer **/radar Le Havre** dans Discord. Une image déjà envoyée dans un ancien message Discord reste ancienne jusqu'à une nouvelle commande.
10. Si le radar est encore périmé, consulter **/radar-status** sur le Worker Discord pour voir l'âge de l'observation (refus au-delà de 50 minutes).

## Diagnostic

- HTTP 204 dans les logs du nouveau Worker : GitHub a accepté le déclenchement, mais l'Action peut être encore en cours.
- HTTP 401 : jeton expiré, absent ou refusé.
- HTTP 403 : permissions insuffisantes, restrictions ou limite API.
- HTTP 404 : dépôt inaccessible au jeton ou workflow introuvable.
- HTTP 422 : workflow non disponible, ref incorrecte ou erreur de requête.
- Aucun workflow_dispatch : vérifier les **Cron Events** du nouveau Worker et la valeur du secret.
- Workflow_dispatch présent mais GIF ancien : examiner les logs GitHub et l'horodatage RainViewer. Le fournisseur ou GitHub Pages peut présenter un retard.

Le GitHub workflow garde son cron automatique d'origine en secours. Cloudflare Cron Triggers peut lui aussi mettre quelques minutes à devenir actif. Le bouton public /status est en lecture seule et ne déclenche aucune Action.

## Liens officiels

- API GitHub workflow_dispatch : https://docs.github.com/en/rest/actions/workflows#create-a-workflow-dispatch-event
- Scheduling GitHub : https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows#schedule
- Cloudflare Cron : https://developers.cloudflare.com/workers/configuration/cron-triggers/

## État

Le JavaScript du nouveau Worker a été ajouté au dépôt et testé avec des réponses API simulées. Aucun jeton GitHub réel n'a été créé, aucun nouveau Worker Cloudflare n'a été déployé, et aucun Cron supplémentaire n'est actif tant que les étapes d'installation ne sont pas exécutées.
