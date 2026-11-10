# /climato — Orages et neige (11 novembre 2026)

Deux rubriques nouvelles ont été ajoutées à la commande Discord existante :
- `rubrique: Orages (jours observés)` (`orages`) : nombre de jours avec orage observé par mois/année, dates si un mois est ciblé et détail des 12 mois.
- `rubrique: Neige (chutes et au sol)` (`neige`) : jours avec chute de neige ; si disponibles, jours de sol enneigé, épaisseur maximale au sol et neige fraîche maximale sur 24 h.

**Source** : Météo-France, archives quotidiennes `Q_<département>_<période>_autres-parametres.csv.gz`, colonnes `ORAG`, `NEIG`, `SOLNEIGE`, `NEIGETOTX`, `NEIGETOT06`, `HNEIGEF` et indicateurs de qualité. La couverture réelle des observations et la station sélectionnée sont indiquées. Les valeurs manquantes ne sont **jamais** comptées comme zéro. Le modèle des journées avec orage indique une occurrence observée : pas un nombre d'impacts de foudre ni un nombre de cellules orageuses.

Le module autonome se trouve dans [kfs-climato-phenomenes.js](./kfs-climato-phenomenes.js). Son code est inséré avant `kfsClimatoHandleV2` dans le Worker Cloudflare `kfs-meteo-ia` ; `kfsClimatoHandleV2` route ces deux rubriques vers `kfsPReport`, et `kfsClimatoRegisterV2` enregistre leurs choix Discord. Conserver les autres branches du handler, notamment anomalies et records, lors des redéploiements.

**Déploiement** : API Cloudflare `PUT /workers/scripts/kfs-meteo-ia/content` réussie ; nouvelle version relue et vérifiée. Le workflow GitHub `kfs-climato-sync.yml` a accédé au Worker avec HTTP 200 après déploiement. L'enregistrement effectif de l'option dans l'interface Discord et les valeurs d'une consultation réelle restent à valider avec une commande Discord.

Exemples :
- `/climato ville: Évreux annee: 2025 rubrique: Orages (jours observés)`
- `/climato ville: Bourth annee: 2024 rubrique: Neige (chutes et au sol)`
- `/climato ville: Rouen annee: 2025 mois: janvier rubrique: Neige (chutes et au sol)`

---

# /climato — option « record » (novembre 2026)

La commande Discord `/climato` dispose maintenant d'un champ optionnel **record**. Les choix sont :
- Rafale maximale (`rafale_max`)
- Température maximale absolue (`chaleur_max`)
- Température minimale absolue (`froid_min`)
- Pluie maximale en 24 h (`pluie_max`)

**Exemple** : `/climato ville: Lesquin mois: novembre rubrique: Vent et rafales record: Rafale maximale`

Lorsque `record` est renseigné, le bot recherche un **record historique toutes années confondues**, et non le maximum de la dernière année disponible. Le résultat donne la valeur, la date, la station Météo-France retenue et un lien vers la fiche officielle. Si le champ `annee` est renseigné également, il est ignoré dans ce mode, avec un avertissement. Sans `record`, les bilans annuels et mensuels précédents restent inchangés.

Cas test vérifié avec les valeurs de la fiche officielle Météo-France Lille–Lesquin (n° 59343001) : **novembre = rafale maximale 34 m/s, soit 122,4 km/h, le 27 novembre 1983**. Les calculs du module ont été testés sur une fiche représentative de cette structure. Cette validation ne remplace pas un essai en conditions réelles dans Discord.

**Dépendance Discord** : le Worker KFS doit actualiser sa commande auprès de l'API Discord après déploiement. L'actualisation automatique existante se produit lors d'une requête HTTP. Il reste à confirmer la mise à jour de l'interface sur le serveur Discord.

---

# /climato — version 2 déployée (9 novembre 2026)

Le Worker Cloudflare `kfs-meteo-ia` a été mis à jour, avec conservation des bindings. La **disponibilité effective dans le menu Discord reste à confirmer** ; le Worker enregistre la commande lors d'une requête entrante. Une GitHub Action `.github/workflows/kfs-climato-sync.yml` déclenche une requête publique après son ajout au dépôt.

## Exemples
- `/climato ville: Évreux` : bilan observé de la dernière année complète (2025).
- `/climato ville: Évreux annee: 2024` : températures, date la plus chaude/la plus froide, gel/chaleur, pluie, rafales et dates.
- `/climato ville: Rouen annee: 2022 mois: juillet rubrique: complet` : bilan de juillet 2022.
- `/climato ville: Paris annee: 2025 rubrique: mensuel` : tableau des 12 mois.
- `/climato ville: Bourth rubrique: normales` : normales et climatologie de référence.
- `/climato ville: Évreux rubrique: records` : records historiques disponibles.

## Signification des indicateurs
Les jours `Tmax≥30°C`, `≥35°C`, `≥40°C`, `Tmin≤−5°C`, `≤−10°C` et les nuits tropicales `Tmin≥20°C` sont calculés à partir des relevés quotidiens effectivement disponibles. Les **séquences chaudes** sont un indicateur *non officiel* : au moins 3 jours consécutifs avec Tmax ≥ 30 °C et Tmin ≥ 20 °C ; elles ne constituent pas un décompte officiel des jours de vigilance canicule, qui dépend de seuils locaux.

Les rafales sont converties des m/s en km/h. Les précipitations sont en mm. L'heure éventuelle de rafale est indiquée en UTC. Les jours sans donnée ne comptent pas comme zéro ; les effectifs valides sont affichés.

## Sources
- Données quotidiennes, métropole et outre-mer : https://www.data.gouv.fr/datasets/donnees-climatologiques-de-base-quotidiennes
- Fiches climatologiques : https://www.data.gouv.fr/datasets/fiches-climatologiques
- Module additionnel : [kfs-climato-observations.js](./kfs-climato-observations.js)

## Limitations
- Les fichiers `1950–2024` par département sont volumineux : la première consultation d'une année ancienne peut être plus lente. Cache des relevés par station/année.
- Les dates de début/fin de séries et les paramètres disponibles varient d'une station à l'autre. Aucun chiffre n'est extrapolé.
- Une commune sans station de mesures sera rattachée à une station proche, explicitement nommée.
- Les fichiers quotidiens et les rubriques ne sont pas encore tous validés de bout en bout dans Discord.
- La période actuelle de distribution des archives est 2025–2026 ; sa dénomination devra être ajustée lors du changement d'année.
- Le jeu `RR-T-Vent` ne couvre pas tous les paramètres optionnels (neige, humidité, ensoleillement) ; ceux-ci ne sont pas présentés comme observés s'ils ne sont pas présents.

---

## Documentation précédente / instructions manuelles

# KFS MÉTÉO — Installation de la commande `/climato`

## État
Le module `cloudflare/kfs-climato-module.js` est prêt dans ce dépôt. **Il n'est pas déployé sur le Worker Cloudflare ni enregistré auprès de Discord.** La connexion Cloudflare utilisée pour le préparer a refusé une opération d'écriture (HTTP 403). Ne pas considérer `/climato` comme disponible tant que les étapes suivantes ne sont pas terminées.

## Fonctionnement
`/climato ville: Rouen rubrique: complet mois: annee`

- recherche une commune française (référentiel `geo.api.gouv.fr`, repli Open-Meteo) ;
- récupère le catalogue officiel des stations Météo-France disposant d'une fiche climatologique, puis choisit la station exploitable la plus proche ;
- lit directement sa fiche `FICHECLIM_<numéro>.data` et affiche les normales, les seuils et les records **effectivement publiés** ;
- affichage annuel ou par mois, rubrique bilan/températures/pluie/vent/soleil/phénomènes/records/toutes statistiques/tableau des 12 mois ;
- indique nom de station, identifiant, distance, lien vers la fiche officielle et périodes de calcul propres aux blocs ;
- données absentes = pas de valeur inventée ; poste éloigné = avertissement ;
- cache Cloudflare `cf.cacheTtl: 86400` ; aucune clé API ajoutée, aucune modification o2switch.

**Attention** : la couverture des variables dépend des stations. Une fiche ne contient pas systématiquement neige, orages, vent, ensoleillement, etc. Le code n'extrapole pas ces statistiques à chaque commune.

## À intégrer dans le script existant `kfs-meteo-ia`
Faire d'abord une sauvegarde de `worker.js` dans Cloudflare, puis ouvrir l'éditeur du Worker.

1. Copier l'intégralité du fichier [kfs-climato-module.js](./kfs-climato-module.js) **avant** la ligne `export default {` du Worker. Ne pas remplacer les commandes ou handlers existants.
2. Juste avant `export default {` (après les fonctions du module), déclarer une seule fois :

```js
let KFS_CLIMATO_LAST_SYNC = 0;
```

3. Dans le handler `fetch`, immédiatement après `if (interaction.type===1) return json({type:1});`, ajouter ce bloc :

```js
if(interaction.type===2 && Date.now()-KFS_CLIMATO_LAST_SYNC>21600000){
  KFS_CLIMATO_LAST_SYNC=Date.now();
  ctx.waitUntil(
    kfsClimatoRegister(env.DISCORD_BOT_TOKEN,APPLICATION_ID,KFS_TENDANCE_GUILD)
      .catch(e=>console.error("KFS /climato registration failed",String(e)))
  );
}
if(interaction.type===2 && interaction.data?.name==="climato"){
  const ville=String(interaction.data.options?.find(o=>o.name==="ville")?.value||"");
  if(ville.length<2||ville.length>80){
    return json({type:4,data:{content:"Indique une ville de 2 à 80 caractères."}});
  }
  ctx.waitUntil(kfsClimatoHandle(interaction,APPLICATION_ID));
  return json({type:5}); // Réponse différée publique
}
```

4. Déployer **après** la vérification de la syntaxe du Worker entier. Les bindings `DISCORD_BOT_TOKEN`, `SETUP_KEY` et les autres secrets doivent rester sur le Worker existant : ne jamais les inscrire dans GitHub.
5. Sur le serveur Discord KFS, lancer une commande existante (par exemple `/meteo`) pour déclencher l'enregistrement de la nouvelle commande `/climato`. Elle est déclarée sur la guilde déjà configurée par le Worker (`KFS_TENDANCE_GUILD`).
6. Tester `/climato ville: Évreux rubrique: bilan`, puis `/climato ville: Rouen rubrique: complet` et `/climato ville: Bourth rubrique: mensuel`. Vérifier les chiffres dans les fiches officielles. Un appel Discord réel n'a pas encore pu être testé dans cette session.

## Données
- [Fiches climatologiques Météo-France](https://www.data.gouv.fr/datasets/fiches-climatologiques)
- [Catalogue des stations](https://meteofrance.s3.sbg.io.cloud.ovh.net/data/synchro_ftp/REF_STATION/liste_fiches_clim.geojson)
- Modèle de fiche : `https://meteofrance.s3.sbg.io.cloud.ovh.net/data/synchro_ftp/REF_STATION/FICHECLIM_<NUM>.data`

Le format `.data` est un texte à séparateur point-virgule (12 mois + année) avec des blocs qui peuvent avoir des périodes différentes. Un point isolé dans une cellule numérique signifie zéro ; un tiret signifie absence de mesure. Les dates de records sont distinctes des normales.

## Diagnostic
- « Ville introuvable » : préciser orthographe et code postal ;
- « Aucune fiche exploitable » : aucune des stations proches vérifiées ne dispose à la fois d'une normale annuelle de température et de précipitations ;
- erreur réseau : vérifier les accès HTTP des origines `geo.api.gouv.fr` et `meteofrance.s3.sbg.io.cloud.ovh.net` depuis le Worker ;
- si une rubrique est absente, ne pas afficher une statistique synthétique non documentée par Météo-France.
