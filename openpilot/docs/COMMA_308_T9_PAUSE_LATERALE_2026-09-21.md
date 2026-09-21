# Pause latérale sur clignotant et intervention conducteur

> Rapport historique de la première version à seuil ±10. La version courante
> utilise ±15 et ajoute le cycle EPS optionnel ; voir
> [l'état partageable](COMMA_308_T9_RELEASE_2026-09-21.md).

État : **version installée et vérifiée après redémarrage sur USB**.
La compilation complète et les tests sur le comma ont réussi. L'installation
a confirmé l'alimentation USB, le harnais débranché et l'assistance arrêtée.
La version précédente est conservée dans
`/data/openpilot-before-t9-lateral-20260920T221133Z`.
Le paquet est dans `data/runtime/t9_lateral_pause_20260920/` ; la date du dossier
correspond au début de la préparation, poursuivie après minuit.

## Fonctionnement installé

Dans le profil séparé `0x1314`, une assistance latérale déjà autorisée passe
à couple nul si un clignotant ou les warnings sont actifs, ou si l'effort
conducteur dépasse ±10 unités brutes. **−10 et +10 restent inclus** ; la pause
commence à −11 ou +11, conformément à la précision de l'utilisateur.

La reprise exige un effort revenu dans ±10, les clignotants éteints et
0,5 seconde de données successives satisfaisant ces critères :

- Deux limites de voie avec une probabilité modèle d'au moins 0,75 chacune.
- Véhicule entre les deux limites, largeur estimée de 2,4 à 4,5 m et décentrage
  estimé inférieur ou égal à 0,75 m.
- Modèle valide, récent d'au plus 0,5 seconde, avec de nouveaux échantillons.
- État de changement de voie du modèle revenu à `off`.

Ces valeurs définissent un réglage de développement, pas une calibration de
sécurité des probabilités du modèle ni une validation sur la 308. Un modèle
figé, une baisse de confiance, une nouvelle intervention ou une discontinuité
de calcul remet l'attente à zéro.

La pause conserve la session EPS existante en état 4 avec un couple nul.
Elle ne désactive pas puis ne réactive pas l'EPS. Le contrôleur attend une
autorisation explicite de reprise issue de la validation des lignes ; une
baisse du couple conducteur seule ne suffit pas. Cette autorisation utilise
des champs dédiés dans `CarControl`, avec un état de pause dans `CarState`,
pour ne pas perdre une intervention brève entre deux cycles.

Le contrôleur repart de zéro et conserve la rampe de couple existante. Panda
vérifie indépendamment le clignotant physique dans `0x452` et l'effort brut
dans `0x2F5`, et refuse les commandes non nulles pendant ces interventions.
L'interface affiche « Steering Assist Paused » pendant l'attente. La pause
latérale seule ne coupe pas le suivi RVV.

Une autorisation EPS retirée, un défaut, une perte de données, un rejet de
commande Panda, le frein ou l'accélérateur restent des arrêts mémorisés avec
réarmement physique. En particulier, si l'EPS se retire pendant une pause,
le retour des lignes ou de l'effort sous le seuil ne le réactive pas. Une
admission initiale refusée ne devient pas une pause permettant de s'engager
plus tard toute seule.

## Vérification de cristianku

La branche publique `psa-torque-sunny-testing` a été vérifiée à nouveau :
opendbc reste au commit `d79cb27c85fb9f447cb0276858a6a51376a09198`.
Les fichiers et leurs empreintes sont archivés dans
`data/diagnostics/comma/cristianku-lateral-pause-20260920/`.

Son [contrôleur](https://github.com/cristianku/opendbc/blob/d79cb27c85fb9f447cb0276858a6a51376a09198/opendbc/car/psa/carcontroller.py)
met le couple et le facteur à zéro lors de l'intervention conducteur dans la
branche de commande en couple. Séparément, `_deactivate_eps()` demande
l'état 2 et remet le facteur à zéro. Lorsque l'EPS n'est plus actif,
`_activate_eps()` fait évoluer les états 2/3/4 et augmente le facteur.
La réactivation peut demander une reprise conducteur en courbe. Sa durée
dépend du retour EPS ; ce n'est pas une pause de durée fixe garantie.

Le [réglage du cycle](https://github.com/cristianku/opendbc/blob/d79cb27c85fb9f447cb0276858a6a51376a09198/opendbc/car/psa/values.py)
est de 12 secondes, avec possibilité d'anticipation selon la courbure prévue.
Une [fonction distincte](https://github.com/cristianku/opendbc/blob/d79cb27c85fb9f447cb0276858a6a51376a09198/opendbc/car/psa/psacan.py)
force aussi une indication de tenue du volant dans certaines trames.

Le cycle périodique EPS et cette indication forcée ne sont pas repris ici.
Les captures T9 ont montré un retrait d'autorisation après environ 13 secondes
sans activité conducteur reconnue ; leur analyse n'établit pas qu'une
réinitialisation périodique soit un fonctionnement compatible et validé de
cet EPS. La fonction installée couvre donc la suspension temporaire du couple
avec autorisation EPS continue. Elle ne résout pas ce retrait de l'EPS.

## Paquet et vérifications

Le manifeste du paquet est
`51974ed47ea05be5e9d5865ccfdb8212a9a140762e0ec091353eb09a3606bb91`.
Il conserve les sources de la version précédente, dont le seuil ±10, le RVV
sans exigence d'atteindre la cible en deux secondes et le plafond 140 km/h.
Il contient 66 chemins, dont 19 modifiés ou ajoutés. `review.diff` compare
le paquet à la version effectivement installée.

Les tests couvrent le seuil dans les deux sens, chaque clignotant et les
warnings, le filtrage de reprise, les champs réellement sérialisés, les
commandes CAN confrontées au Panda compilé, les défauts pendant la pause et
la conservation du RVV. Les 355 tests tournent avec succès en local et sur le
comma : 349 réussis et 6 ignorés. Les deux bancs C++ de commande et transport
passent également. Le firmware Panda H7 a été compilé et signé dans un
conteneur local sans réseau, puis compilé avec le programme `pandad` sur le
comma. Les sources et les trois binaires correspondent au manifeste vérifié
par l'installateur. Les résultats détaillés et empreintes sont conservés dans
`validation.json` du paquet.

Les 23 contrôles après redémarrage passent : les 20 vérifications des
sources, binaires, paramètres, services et de l'enregistrement, puis les
3 vérifications du démarrage natif et des capacités du firmware. Le journal
du démarrage actuel annonce une signature Panda `0bc3a73e3dd4cf81`, identique
à la signature attendue, puis confirme les capacités `split_axes=1`.
Le contrôle de firmware n'est pas contourné. Sur USB, Panda reste en
`noOutput`, sans émission CAN.

Le bilan final et les empreintes des preuves sont dans
`data/runtime/t9_lateral_pause_20260920/installation-status.json`.
La vérification réseau après redémarrage a abouti en IPv4, avec la clé hôte
épinglée d'origine, après expiration des premières tentatives. Le
fonctionnement réel de la pause et de la reprise sur la 308 reste à valider
sur terrain fermé ; les tests logiciels et USB ne constituent pas cet essai.
