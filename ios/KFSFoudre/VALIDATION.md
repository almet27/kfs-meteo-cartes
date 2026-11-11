# Vérifications — 11 novembre 2026

- Compilation iPhone Simulator avec Xcode : **réussie**.
- Tests Swift du choix des alertes : **réussis** (signes, valeur absolue, rayon, fraîcheur, kA absents, doublons, CG/IC).
- Tests Node du service mobile : **réussis** (authentification, GPS récent, domaine géographique, valeurs kA, limitation des appels).
- Service Cloudflare en production : requête sans code refusée (**401**), requête personnelle acceptée (**200**) et format de données valide. Le test réel a fourni une liste vide pour les cinq minutes interrogées ; aucune décharge fictive n'a été créée.
- Le test de diagnostic temporaire a été retiré après vérification.

Compilation : https://github.com/almet27/kfs-meteo-cartes/actions/runs/42940476447

## Ce qui reste à vérifier sur l'appareil

Le projet n'a pas encore été signé avec le compte Apple d'Alain ni installé sur son iPhone. La compilation ne valide pas le GPS réel, le réseau de l'iPhone, les autorisations, l'affichage d'une notification réelle ni le maintien de l'exécution pendant un déplacement écran verrouillé. Ces points demandent le premier essai sur l'iPhone après installation.

Le service météo personnel est déjà raccordé ; les requêtes n'ont lieu que pendant une séance lancée depuis l'app. Aucun cron de surveillance n'a été ajouté.


## Mise à jour Europe du 11 novembre 2026

- API : périmètre Europe latitude 30–72°, longitude −25–45°, validation des
  coordonnées et du corps JSON, authentification et cadence inchangées.
- Tests backend : France, Italie, Grèce, Allemagne, Islande, Istanbul ; rejet
  hors limites, ancien horodatage et corps null, conservation des kA signés.
- Test source réel à 16:02 UTC : une décharge IC +2 kA (44.1699, 10.2751),
  horodatée 16:00:53 UTC, source Xweather ; route de diagnostic retirée aussitôt.
- Essai distant isolé : affichage des données réelles sans filtre d’alerte,
  aucun appel au GPS et aucune notification, consultation ponctuelle au premier plan.
