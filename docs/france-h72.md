# KFS MÉTÉO — Cartes France 0–72 h (prototype)

## Ce qui fonctionne

Le moteur `scripts/generate_france_forecasts.py` produit des cartes centrées sur la France, avec un horaire de validité et le run source dans chaque image. Les cartes proviennent des champs GRIB des modèles, pas d'images extrapolées.

| Modèle | Pas de temps natif | Échéances |
| --- | --- | --- |
| ECMWF IFS | 3 heures | +3, +6, …, +72 h |
| NOAA GFS | 3 heures | +3, +6, …, +72 h |
| ECMWF AIFS | 6 heures | +6, +12, …, +72 h |
| NOAA AIGFS | 6 heures | +6, +12, …, +72 h |

Les paramètres pris en charge sont : température à 2 m, température à 850 hPa, vent à 10 m, pression réduite au niveau de la mer, précipitations totales, pluie et neige lorsqu'une séparation est étayée.

**Neige** : pour ECMWF, il s'agit d'un équivalent-eau, pas de centimètres au sol. Pour GFS, le découpage pluie / précipitations gelées utilise la fraction instantanée CPOFP si cette fraction est valide et indique explicitement une estimation. Pour AIGFS, la phase n'est pas déduite arbitrairement : la carte de précipitations **totales** reste disponible même sans séparation pluie/neige.

## Tester maintenant

Dans GitHub Actions, ouvrir [KFS France - cartes haute fréquence 0-72 h](../actions/workflows/france-h72.yml), choisir **Run workflow**, le modèle et un horizon 12, 24 ou 72 heures. Les cartes et `metadata.json` sont disponibles via l'artefact ZIP de l'exécution pendant trois jours.

Sur chaque `push` de modification du moteur, le workflow lance un test réduit sur les quatre modèles, pas la génération complète, pour ne pas mobiliser inutilement les serveurs météorologiques.

## Détection des nouveaux runs

Le workflow [KFS France - détection des nouveaux cycles](../actions/workflows/watch-france-cycles.yml) contrôle ECMWF / NOAA toutes les 20 minutes. Les cartes Europe peuvent être regénérées plus tôt lorsqu'un nouveau run est détecté. Les mises à jour France automatiques restent suspendues tant que la publication du site complet et le bot Discord ne sont pas validés.

## Diffusion indépendante des cartes Europe : GitHub Releases

Aucun abonnement R2 ni ressource o2switch n'est nécessaire. Les cartes Europe
et leurs chemins `forecast-maps/europe` ne sont pas modifiés.

Le workflow [KFS France : publication des cartes](../actions/workflows/publier-france-releases.yml)
récupère les archives réelles du générateur France, vérifie **toutes les échéances natives
jusqu'à +72 h**, convertit les PNG en WebP et publie une release distincte par modèle :

- [IFS](../releases/tag/france-ifs) : +3 à +72 h, pas de 3 h ;
- [GFS](../releases/tag/france-gfs) : +3 à +72 h, pas de 3 h ;
- [AIFS](../releases/tag/france-aifs-single) : +6 à +72 h, pas de 6 h ;
- [AIGFS](../releases/tag/france-aigfs) : +6 à +72 h quand tous les champs requis sont disponibles.

Les noms des fichiers et les liens restent stables. Les actifs anciens portant
le même nom sont remplacés lors d'un nouveau run, sans enregistrer des PNG dans
l'historique Git. Les données manquantes ne sont jamais inventées.

La surveillance vérifie les nouvelles sorties toutes les 20 minutes
et peut déclencher une génération France +72 h quand le dernier run est annoncé complet.
L'exécution de GitHub Actions et la publication des sources peuvent subir des retards.

## Discord : nouvelle commande indépendante `/france`

Le Worker Cloudflare de KFS propose la commande `/france` en plus de `/modele`.
La commande `/modele` continue de fonctionner pour l'Europe, sans modification
de ses choix ni de ses fichiers.

Pour enregistrer automatiquement `/france` auprès de Discord, appeler
une fois la commande actuelle `/modele` après le déploiement du Worker. Elle
déclenche l'enregistrement de `/france`, sans modifier sa propre réponse.

`/france` offre les paramètres température 2 m, température 850 hPa
(avec isothermes -5 et -10 degrés), vent 10 m, pression, précipitations totales
et pluie/neige uniquement si les modèles fournissent des champs suffisants.
Les paramètres et échéances non publiés renvoient un message explicite.

**AIGFS :** les cartes France de température, vent, pression et
précipitations totales jusqu'à +72 h sont publiées lorsque les champs
indispensables passent les contrôles de qualité. La séparation pluie/neige
n'est pas proposée sans catégories NOAA fiables.

Le workflow [GitHub Pages expérimental](../actions/workflows/pages-france-snapshot.yml)
est conservé uniquement pour des essais ; `publish=false` et aucune migration
Pages n'a été faite. Les releases sont le moyen de diffusion retenu.

## Evolution du 9 novembre : cartes chiffrees et diffusion progressive

Les cartes France `t2m` et `t850` affichent maintenant les valeurs en degrés Celsius
à des points repères de la France, calculées depuis les vraies mailles natives GRIB,
ainsi que des isothermes étiquetées. Les lignes **-5 °C et -10 °C à 850 hPa**
sont renforcées lorsqu'elles sont présentes.

Sur GFS, la séparation `rain`/`snow` repose dorénavant sur les quatre indicateurs
NOAA instantanés CRAIN/CSNOW/CFRZR/CICEP : seuls les secteurs clairement
identifiés comme pluie ou neige reçoivent un cumul ESTIMÉ sur l'intervalle.
Les mailles humides à phase mixte, verglaçante, grésil ou inconnue sont
**grisées**, sans attribution artificielle à la neige.
Pour IFS/AIFS, les cartes de pluie et de neige utilisent les champs ECMWF
et la neige est donnée en **mm équivalent-eau** (pas en cm au sol).
Pour AIGFS, seule la précipitation totale est publiée si le type est absent.

Le moniteur source `watch-france-cycles.yml` fonctionne nominalement toutes
les **10 minutes** (sous réserve du retard possible des tâches planifiées GitHub).
Il distingue : l'arrivée des champs disponibles jusqu'à **+12 h**, qui déclenche
la publication rapide dans les releases `france-{modele}-early`, et la sortie
jusqu'à **+72 h**, qui déclenche l'édition complète dans
`france-{modele}`. Une release plus ancienne ne peut écraser un run plus récent.

La commande Discord indépendante `/france` compare les horodatages des releases
rapides et complètes pour les échéances jusqu'à +12 h et affiche le run le plus
récent réellement disponible. Elle garde l'édition complète pour les échéances
supérieures à +12 h. Si un champ de pluie/neige n'est pas vérifiable, son
absence est expliquée au lieu de fournir une carte erronée.

**Important :** une échéance publiée par la source pour la seule température
ne garantit pas encore la disponibilité de toutes les variables ; le générateur
vérifie individuellement les données avant publication. La détection toutes les
10 minutes ne garantit pas une livraison immédiate (retards NOAA/ECMWF,
GitHub Actions, conversions et mise en ligne).

**Périmètre :** aucune modification des cartes Europe ni de leurs workflows
n'est requise.
