# KFS MÉTÉO – Statistiques synoptiques mensuelles

## Commande Discord

`/statistiques modeles` propose :
- Température à 2 m : MAE en °C
- Pression au niveau de la mer : MAE en hPa
- Blocage nord-atlantique (proxy de pression de surface)
- Anticyclone scandinave (proxy de pression de surface)
- Circulation zonale Europe (proxy de pression de surface)

Sélection du mois `AAAA-MM`, comparaison des quatre modèles ECMWF IFS, ECMWF AIFS, NOAA AIGFS, NOAA GFS, échéances J+1 à J+15.

## Source et vérification

Les prévisions sont tirées des **runs individuels archivés**, et non des cartes actuelles ou des prévisions recomposées. Elles sont mises en correspondance avec la pression ERA5 (réanalyse ECMWF) au même lieu et à la même échéance UTC via Open-Meteo. Les quatre modèles doivent disposer d'une valeur valide pour qu'un échantillon soit inclus. Six à huit runs 00 UTC sont prévus par mois (jours 1/5/9/13/17/21/25/29 selon maturité des observations). Chaque J+ est vérifié, dans la limite de la disponibilité native, à 00/06/12/18 UTC. **Ces heures issues d'un même run sont corrélées** : ne pas les interpréter comme autant de runs indépendants.

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

## Automatisation

Workflow GitHub Actions : `.github/workflows/kfs-model-skill.yml`.
- Lancement hebdomadaire, ou manuel avec option `month`.
- Pipeline température/pression : `scripts/build_model_skill.py` → `data/model-skill/YYYY-MM.json`.
- Pipeline synoptique : `scripts/build_model_regimes.py` → `data/model-skill/YYYY-MM-regimes.json`.
- Si la vérification ne réussit pas, les chiffres ne sont pas publiés.

Fonctions Discord : `cloudflare/kfs-model-skill-module.js`, montées dans le Worker `kfs-meteo-ia`.

## Prochaine étape de rigueur scientifique

Lorsque l'accès à des archives fiables **Z500** et **vents zonaux U300** comparables aux quatre modèles sera disponible, ajouter des indices de blocage de Tibaldi–Molteni/Scherrer avec critère de persistance et une mesure directe du courant-jet, en conservant les proxies SLP sous une étiquette distincte.
