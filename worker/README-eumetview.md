# /foudre : activité électrique EUMETSAT sans clé API

La carte du Worker utilise désormais le WMS public EUMETView, couche officielle `mtg_fd:li_afa` (LI Accumulated Flash Area). Elle montre les zones d'émission lumineuse détectées au sommet des nuages. Ces zones ne sont pas des positions individuelles d'impacts au sol. Aucun comptage d'éclairs n'est déduit des pixels.

## Fonctionnement

- La date de la dernière image vient du `GetCapabilities` officiel. Le produit WMS est accumulé par tranches de cinq minutes. Une tranche nommée 00:25 couvre 00:25–00:30 UTC.
- Pour 30 minutes, six images successives sont composées. Chaque pixel garde l'âge de sa dernière apparition : bleu ancien, jaune récent. Les coordonnées WMS sont alignées sur la projection locale du fond de carte et limitées au disque de 100 km.
- La fenêtre est ancrée sur le dernier produit disponible, et ses deux horaires ainsi que le retard de diffusion sont affichés. Elle peut donc être décalée par rapport aux statistiques Xweather, qui sont des requêtes distinctes.
- Les choix 5 / 30 / 60 minutes sont conservés. Pour 6 h et 24 h, la carte satellite est limitée à 2 h et le bilan Xweather conserve la période choisie.
- Pas de requêtes programmées : les images sont chargées lors de `/foudre` et réutilisées en cache. Catalogue : 60 secondes ; images historiques : 1 heure. Aucun secret EUMETSAT nécessaire.
- Une source âgée de plus de 30 minutes est refusée. Une acquisition partielle est explicitement marquée. Une panne de la source satellite laisse la carte locale et les éventuels points Xweather disponibles.
- Les zones satellite ne distinguent ni CG/IC, ni polarité, ni intensité en kA. Ces informations restent exclusivement dans le bilan Xweather. Les points Xweather 5 min réellement reçus peuvent se superposer à la couche satellite.

## Validation du 11 novembre 2026

- Six images PNG officielles couvrant 00:25–00:55 UTC autour de Châteauroux ont été téléchargées. Le décodeur JavaScript a été comparé octet par octet (SHA-256 RGBA) à un décodage indépendant Pillow.
- Le rendu d'archive montre une zone lumineuse au sud-ouest de Châteauroux. Ce test n'alimente jamais la carte en production.
- Un test dans Cloudflare a reçu 6 images sur 6, fenêtre 00:40–01:10 UTC, retard de diffusion de 9 minutes au moment du contrôle, et a rendu la zone réelle sur le fond départemental.
- Tests : les cinq filtres PNG, fichiers incomplets, fraîcheur des produits, fenêtre 30 minutes, ordre des couches, source partielle, source en panne, informations de source et conservation du rendu Xweather.

## Fichiers et tests

Le Worker complet est `worker/kfs-meteo-ia-eumetview-2026-11-11.js`. Le module `worker/foudre-eumetview.js` est une copie du bloc intégré, pour faciliter les évolutions. Ne pas ajouter une deuxième fois ce module au Worker complet.

```sh
KFS_WORKER_SOURCE=worker/kfs-meteo-ia-eumetview-2026-11-11.js node worker/tests/test-eumetview.cjs
node worker/tests/test-foudre-2026-11-11.cjs worker/kfs-meteo-ia-eumetview-2026-11-11.js
```

Références :

- https://view.eumetsat.int/productviewer/productDetails/mtg_fd:li_afa
- https://view.eumetsat.int/geoserver/wms?service=WMS&request=GetCapabilities&version=1.3.0
- https://user.eumetsat.int/data-access

Les positions LFL individuelles restent une autre voie d'accès, nécessitant les clés Data Store du compte EUMETSAT. Le prototype ancien de la branche `feature/eumetsat-li-foudre-20261107` n'est pas utilisé par ce module.
