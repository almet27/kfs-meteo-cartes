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
