# KFS MÉTÉO — Conception /meteo 1mois (ECMWF EC46)

**Plan technique uniquement : pas encore de code en production ni de cartes validées.**

## Réponse Discord visée
Commande existante /meteo ville:<ville> echeance:1mois :
- Image 1 : centres d'action moyens sur Atlantique Nord et Europe. Quatre panneaux hebdomadaires S1, S2, S3, S4 ; isolignes de pression MSL (hPa), fonds anomalies MSL (hPa), vecteurs moyens de vent à 10 m.
- Image 2 : tendance thermique. Quatre panneaux S1 à S4 ; anomalies T2m (°C) et vecteurs de vent à 10 m. **Ce n'est PAS une carte T850 ni des masses d'air en altitude**.
- Bulletin : analyse Atlantique Nord, Europe et France ; section par semaine, perspectives alternatives conditionnelles, niveau de confiance et dates des runs.
- Région cartographique : longitudes -60 à +40, latitudes 30 à 75 degrés.

## Source : ECMWF EC46 via Open-Meteo

Documentation officielle : https://open-meteo.com/en/docs/seasonal-forecast-api
Schéma de l'API : https://github.com/open-meteo/open-meteo/blob/main/openapi/seasonal.yml
Endpoint : https://seasonal-api.open-meteo.com/v1/seasonal

Paramètres hebdomadaires confirmés :
- pressure_msl_mean : pression moyenne MSL
- pressure_msl_anomaly : anomalie MSL
- wind_u_component_10m_mean et wind_v_component_10m_mean : vent moyen vectoriel
- temperature_2m_anomaly et temperature_2m_mean : thermique de surface
- precipitation_anomaly : anomalie précipitations

Modèle déjà employé dans le code actuel : ecmwf_seasonal_ensemble_mean_seamless.
EC46 couvre les 46 premiers jours ; valider les dates des semaines et l'horodatage de la source avant de générer.

Exemple de requête de validation pour Paris :
https://seasonal-api.open-meteo.com/v1/seasonal?latitude=48.8&longitude=2.3&models=ecmwf_seasonal_ensemble_mean_seamless&forecast_days=45&timezone=GMT&weekly=pressure_msl_mean,pressure_msl_anomaly,wind_u_component_10m_mean,wind_v_component_10m_mean,temperature_2m_anomaly,temperature_2m_mean,precipitation_anomaly

## Règles d'interprétation

Les anomalies sont relatives à la climatologie du modèle ECMWF et non des observations.
Les centres d'action sont des structures moyennes à l'échelle de la semaine.
Les anomalies positives de pression ne suffisent pas seules à identifier un anticyclone :
croiser pression moyenne absolue, isobares et gradient de pression.
Aucune interprétation T850/Z500 à partir de simples températures T2m.
Aucun pourcentage de confiance inventé à partir d'une moyenne d'ensemble :
chiffrer seulement si une mesure vérifiable de dispersion ou de probabilités est accessible.
Aucun détail quotidien à J+30.

Le texte doit expliquer :
1. Atlantique : dorsales/thalwegs et position des noyaux de pression moyens.
2. Europe : gradient de pression, circulation dominante, régions plus douces ou froides que la climatologie de modèle.
3. France : températures/pluies relatives aux normales, contrastes régionaux si vérifiés.
4. Évolution S1 à S4 avec dates exactes et incertitudes.

## Architecture prévue

1. GitHub Actions interroge EC46 après disponibilité du run ; Open-Meteo annonce vers 20:30 UTC.
2. D'abord test sur une dizaine de zones (Açores, Islande, Atlantique, France, Royaume-Uni,
   péninsule ibérique, Scandinavie, Europe centrale), puis grille régulière testée
   autour de 4° avant éventuel affinage à 2,5°. Garder les coûts/API sous contrôle.
3. Python produit 2 PNG (1600 x 1000 par exemple), plus un manifest JSON
   contenant source_run_utc, generated_utc, dates de quatre semaines, URLs des images,
   analyse régionale, disponibilité et indicateur de vérification des ensembles.
4. Publication atomique : une version des cartes et du manifest correspond au même run.
5. Worker principal (uniquement branche /meteo 1mois) répond d'abord par ACK différé
   puis transmet cartes et texte au webhook Discord ; les autres commandes restent inchangées.
6. Si la source manque ou est incohérente : retour au texte seasonalText déjà existant.

**Risque important :** GitHub Pages RainViewer est déployé comme un site complet par
le workflow rainviewer-discord.yml. Un second workflow Pages indépendant pourrait
effacer le radar déjà publié. Prévoir une publication Pages commune ou un hébergement
séparé avant intégration.

## Liste de validation
- [ ] Tester endpoint et vrais champs hebdomadaires, unités, dates.
- [ ] Définir convention S1-S4 selon semaines source.
- [ ] Vérifier les champs et la grille géographique, sans interpolation trompeuse.
- [ ] Tester PNG de pression et d'anomalies T2m.
- [ ] Tester génération de texte sans données fictives.
- [ ] Confirmer conditions de licence et coût.
- [ ] Héberger sans perturber RainViewer.
- [ ] Tester Worker Discord sans affecter /live, /radar, /foudre.
- [ ] Déployer seulement après validation manuelle.

Open-Meteo gratuit = usage non commercial et attribution requise :
https://open-meteo.com/en/terms ; https://open-meteo.com/en/pricing .
