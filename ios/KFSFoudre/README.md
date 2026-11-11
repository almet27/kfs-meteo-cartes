# KFS Foudre — appli iPhone personnelle

Version native iOS 17+, destinée à Alain pour une surveillance pendant ses déplacements. Source des décharges et des courants de crête : Vaisala Xweather. Le service Discord reste indépendant.

## Installer sur ton iPhone

1. Sur ton Mac, installe **Xcode** depuis le Mac App Store et ouvre-le une première fois.
2. Décompresse le dossier personnel puis ouvre **KFSFoudre.xcodeproj**. Le fichier `Verifier-et-ouvrir.command` peut lancer une vérification avant de l'ouvrir.
3. Branche l'iPhone au Mac, accepte « Faire confiance » et active le mode développeur si iOS le demande.
4. Dans Xcode, sélectionne le projet **KFSFoudre**, puis **Signing & Capabilities**. Active **Automatically manage signing** et sélectionne ton équipe Apple (Personal Team convient pour un premier essai).
5. Choisis ton iPhone comme destination puis clique sur **▶ Run**. Le projet fourni contient le code d'accès personnel dans `Configuration.plist`, qui est ensuite copié dans le trousseau de cet iPhone. Ne partage pas cette archive.
6. Dans l'app, ouvre les réglages, teste une notification, règle rayon et seuil puis démarre une chasse. Accorde la localisation **Toujours** et les notifications. Si iOS ne présente pas immédiatement l'option Toujours, ouvre **Réglages → Apps → KFS Foudre → Position → Toujours** puis reviens dans l'app.

Un compte Apple gratuit permet un essai sur un appareil personnel, mais les profils de signature expirent après **7 jours** : il faudra relancer l'installation depuis Xcode. Une distribution durable/TestFlight demande la configuration Apple appropriée ; aucune souscription ni publication App Store n'est effectuée par ce projet.

## Utilisation

- Séances explicites de **2 heures maximum**, arrêtables à tout moment. Pas de suivi automatique permanent au lancement.
- Rayons : **10, 30, 50 ou 100 km** autour de la position GPS récente.
- Seuil réglable en **kA**, appliqué à la valeur absolue (−50 et +50 kA sont tous deux de forte amplitude).
- Alertes nuage-sol seules par défaut ; option incluant les décharges intranuageuses.
- Regroupement des nouvelles décharges : le téléphone notifie la plus forte et indique le nombre d'autres décharges au-dessus du seuil. Pas de répétition de la même décharge déjà notifiée.
- La liste affiche les cinq dernières minutes fournies par la source. Les notifications ne concernent que les décharges de moins de deux minutes, pour éviter d'annoncer un événement ancien comme venant de se produire.
- Les notifications sont **locales**, émises après les consultations de l'app. Aucune clé APNs, aucun droit d'alerte critique et aucun abonnement Apple ne sont nécessaires pour ce mode.

## Écran verrouillé : comportement prévu et limite réelle

La localisation Core Location avec le mode d'arrière-plan `location` reste active pendant la séance. Une nouvelle position déclenche une consultation si la dernière tentative remonte à au moins une minute. Un minuteur assiste cette cadence tant qu'iOS exécute l'app ; ce minuteur n'est jamais présenté comme une garantie d'exécution permanente.

Le téléphone doit rester allumé, avoir du réseau et une position de moins de 45 secondes avec une précision de 500 m ou mieux. Sinon, les consultations sont suspendues. **Ne force pas l'app à quitter pendant une chasse.** Après une terminaison forcée ou un redémarrage, rouvre l'app et démarre une séance. Le projet ne promet pas de continuer après une fermeture forcée.

Le suivi GPS peut consommer de la batterie. iOS conserve le contrôle de l'exécution en arrière-plan et de l'affichage des notifications (mode Concentration, autorisations). Le suivi écran verrouillé doit être validé sur ton véritable iPhone : une compilation ou un simulateur ne prouve pas ce fonctionnement.

## Données et consommation

- Les kA sont un **courant de crête estimé par le réseau**, pas une puissance. EUMETSAT n'est pas utilisé pour inventer des kA.
- La même disponibilité Xweather que dans Discord s'applique : une absence de données n'est pas une absence d'orage.
- Consultation au mieux toutes les **60 secondes**, avec temporisation supplémentaire sur erreur ou quota.
- Plafonds **locaux** : 120 tentatives/jour et 1 000/mois, stockées sur l'iPhone. Ces plafonds peuvent être réinitialisés en supprimant les données de l'app et ne constituent pas un plafond de facturation contractuel. Le compte Xweather est partagé avec le bot Discord et possède ses propres quotas.
- Le serveur applique aussi une temporisation d'une minute par emplacement réseau Cloudflare. Il n'est pas configuré pour faire des appels météo tout seul lorsque l'app est arrêtée.

## Confidentialité de cette version

L'app ne conserve aucun trajet. Pendant une séance, les coordonnées du dernier GPS sont transmises par HTTPS au Worker personnel, puis utilisées auprès de Xweather pour la requête météo. Aucun historique des positions de l'utilisateur n'est ajouté au serveur par ce module.

Les identifiants Xweather restent dans Cloudflare. Un jeton dédié, qui ne donne accès qu'à la consultation météo personnelle, est conservé dans le trousseau. L'archive personnelle inclut ce jeton pour éviter un copier-coller ; la version publique du dépôt contient un `Configuration.plist` vide. Ne mets jamais l'archive personnelle dans un dépôt public.

## Validation à réaliser sur l'iPhone

Après installation : vérifier le test de notification, démarrer une séance, verrouiller l'écran pendant un déplacement et consulter ensuite l'heure de dernière mise à jour. Lors d'activité réelle, comparer heure, distance et kA avec la source et vérifier qu'une décharge n'est pas notifiée deux fois. Aucun faux éclair n'est injecté dans l'app pour simuler une réussite.

## Compilation et tests

```sh
swiftc KFSFoudre/Domain.swift Tests/main.swift -o /tmp/kfs-foudre-tests
/tmp/kfs-foudre-tests
xcodebuild -project KFSFoudre.xcodeproj -scheme KFSFoudre -configuration Debug \
  -sdk iphonesimulator -destination 'generic/platform=iOS Simulator' CODE_SIGNING_ALLOWED=NO build
node Backend/test-mobile-api.cjs
```

## Références Apple et fournisseur

- https://developer.apple.com/documentation/corelocation/cllocationmanager/allowsbackgroundlocationupdates
- https://developer.apple.com/documentation/corelocation/handling-location-updates-in-the-background
- https://developer.apple.com/documentation/usernotifications/scheduling-a-notification-locally-from-your-app
- https://developer.apple.com/help/account/basics/about-your-developer-account
- https://www.xweather.com/docs/weather-api/endpoints/lightning
