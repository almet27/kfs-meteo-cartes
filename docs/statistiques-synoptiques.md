# KFS MÉTÉO – Statistiques synoptiques mensuelles

## Commande Discord

`/statistiques modeles` propose :
- Température à 2 m : MAE en °C
- Pression au niveau de la mer : MAE en hPa
- Blocage nord-atlantique (proxy de pression de surface)
- Anticyclone scandinave (proxy de pression de surface)
- Circulation zonale Europe (proxy de pression de surface)

Sélection du mois `AAAA-MM`, comparaison des quatre modèles de base ECMWF IFS, ECMWF AIFS **Single**, NOAA AIGFS, NOAA GFS, **plus AIFS ENS Control (membre 0)** lorsqu'une archive vérifiée existe, échéances J+1 à J+15.

## Source et vérification

Les prévisions sont tirées des **runs individuels archivés**, et non des cartes actuelles ou des prévisions recomposées. Elles sont mises en correspondance avec la pression ERA5 (réanalyse ECMWF) au même lieu et à la même échéance UTC via Open-Meteo. Les quatre modèles de base doivent disposer d'une valeur valide pour qu'un échantillon commun soit inclus. **AIFS ENS Control est calculé sur les mêmes dates/points disponibles, mais avec ses propres effectifs (`n_by_model`) : son absence ne supprime jamais les séries des quatre modèles de base.** Six à huit runs 00 UTC sont prévus par mois (jours 1/5/9/13/17/21/25/29 selon maturité des observations). Chaque J+ est vérifié, dans la limite de la disponibilité native, à 00/06/12/18 UTC. **Ces heures issues d'un même run sont corrélées** : ne pas les interpréter comme autant de runs indépendants.

## Définitions provisoires (indicateurs au sol)

Les seuils sont des **indicateurs heuristiques définis par KFS**, pas des critères scientifiques homologués.

| Rubrique | Mesure continue en hPa | Détection indicative |
| --- | --- | --- |
| Blocage nord-atlantique | Pression Groenland − Açores | Groenland >= 1017 hPa; écart Groenland-Açores >= −5 hPa; Groenland >= Atlantique central |
| Anticyclone scandinave | Scandinavie − Royaume-Uni | Scandinavie >= 1022 hPa; écart Royaume-Uni >= 5 hPa; écart Russie NW >= 3 hPa |
| Circulation zonale | Ibérie − Islande | Gradient >= 18 hPa |

**Important** : le véritable blocage anticyclonique est généralement diagnostiqué au géopotentiel **500 hPa**, en recherchant l'inversion des gradients méridiens et la persistance sur plusieurs jours. Le jet est étudié à **300 ou 250 hPa** et n'est pas directement mesuré par le gradient de pression au sol. Les présentes courbes **ne mesurent pas** directement ces structures d'altitude ; elles décrivent des **configurations barométriques compatibles avec certains régimes**. Aucun indice ou score de blocage formel n'est annoncé.

## Deux graphiques complémentaires

1. **Score de détection** : balanced accuracy, `100 × (sensibilité + spécificité) / 2`, entre 0 et 100. Calcul **uniquement** si, pour cette échéance, au moins 10 échantillons communs incluent au moins 4 événements, au moins 4 non-événements, et chaque classe est observée sur au moins 2 dates de runs distinctes. Sinon : absence de score (`null`).
2. **Erreur d'indice (hPa)** : MAE du gradient de pression continu, affichable y compris lorsque les configurations événementielles sont trop rares. Plus bas = meilleur.

La balanced accuracy à 50 % correspond à **aucune discrimination** (dans le sens de la moyenne des deux taux de reconnaissance), et non à une probabilité de prévision juste à 50 %. Ne pas déduire un classement robuste d'un seul mois ou d'un faible échantillon.

## AIFS ENS Control : disponibilité et méthode

- **AIFS Single** et **AIFS ENS Control** sont deux prévisions distinctes. Le contrôle est le **membre 0** de l'ensemble AIFS ; ce n'est pas la moyenne de l'ensemble.
- Archive utilisée : [Dynamical.org AIFS ENS](https://dynamical.org/catalog/ecmwf-aifs-ens-forecast/), produit `ecmwf-aifs-ens-forecast`, disponible à partir de juillet 2025. Les données sont validées par l'heure d'initialisation exacte et par la présence du membre 0 avant calcul.
- Pas de chiffres pour les mois antérieurs à juillet 2025. Si l'accès aux archives, un lieu ou une échéance manque, **pas d'interpolation ni de score inventé**.
- Pour la comparabilité, les quatre modèles de base restent évalués sur leur ancien échantillon commun. Les scores d'AIFS Control utilisent leur propre effectif ; en particulier, une courbe AIFS Control avec moins de cas n'a pas strictement la même population statistique qu'une autre.
- La vérification des régimes synoptiques exige également pour AIFS Control les nombres minimaux d'événements, de non-événements et de dates indépendantes avant de publier une balanced accuracy.

## Automatisation

Workflow GitHub Actions : `.github/workflows/kfs-model-skill.yml`.
- Lancement hebdomadaire, ou manuel avec option `month`.
- Pipeline température/pression : `scripts/build_model_skill.py` → `data/model-skill/YYYY-MM.json`.
- Pipeline synoptique : `scripts/build_model_regimes.py` → `data/model-skill/YYYY-MM-regimes.json`.
- Si la vérification ne réussit pas, les chiffres ne sont pas publiés.

Fonctions Discord : `cloudflare/kfs-model-skill-module.js`, montées dans le Worker `kfs-meteo-ia`.

## Prochaine étape de rigueur scientifique

Lorsque l'accès à des archives fiables **Z500** et **vents zonaux U300** comparables aux quatre modèles sera disponible, ajouter des indices de blocage de Tibaldi–Molteni/Scherrer avec critère de persistance et une mesure directe du courant-jet, en conservant les proxies SLP sous une étiquette distincte.
