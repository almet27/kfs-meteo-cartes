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
