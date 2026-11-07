# Satellite Meteosat + foudre Lightning Imager : essai WMS

**Statut : test isolé, non déployé sur Discord ou GitHub Pages.**

Ce prototype combine deux couches EUMETView :

- Nuages : GeoColour RGB du capteur FCI, couche WMS mtg_fd:rgb_geocolour.
- Activité électrique : LI Accumulated Flash Area (AFA), couche candidate mtg_fd:li_afa.
- Service WMS : https://view.eumetsat.int/geoserver/wms

Il demande deux PNG dans la même emprise géographique (France), les superpose
et produit le fichier mtg-li-preview/satellite_foudre_test.png.
Le nom exact de la couche LI, l'accès automatique, la transparence et
l'horodatage restent à vérifier dans les journaux du test réel.

**Attention :** une détection LI est une émission optique associée à la foudre,
pas nécessairement un impact au sol. Une image WMS reçue ne prouve pas qu'elle
est récente. Le prototype ne détermine pas encore le temps d'acquisition :
ne pas l'utiliser pour une diffusion temps réel.

## Essai GitHub Actions

Ouvrir le workflow TEST Meteosat satellite + foudre EUMETView (sans production),
puis le dernier run sur la branche de test. En cas de succès, télécharger
l'artifact mtg-li-wms-preview. Un échec affichera le statut et le début de la
réponse WMS.

**Protection :** aucune modification des Workers kfs-meteo-ia et
kfs-radar-scheduler, de /foudre, des secrets et du cron de production.
Pas de publication automatique.

Sources : https://view.eumetsat.int/productviewer/productDetails/mtg_fd%3Ali_afa
et https://view.eumetsat.int/productviewer/productDetails/mtg_fd%3Argb_geocolour .
Pour toute publication régulière, vérifier les conditions de licence et
citer EUMETSAT et NASA (fond nocturne GeoColour).
