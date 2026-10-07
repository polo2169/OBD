# Préparation des profils latéraux 308 T9

La configuration de lancement normale impose `PSA_T9_LATERAL_EXPERIMENT=off`
et `PSA_T9_LANE_CHANGE_MODE=off`. Son seuil de direction reste 67,1 km/h et
le clignotant suspend toujours la direction. La pédale conserve son comportement
actuel : elle permet l'utilisation du RVV Peugeot seul, sans réadmission
automatique de l'assistance à son relâchement.

## Observation passive sur la configuration actuelle

Le processus indépendant `psa_t9_observer` observe les trois profils, même
quand la direction actuelle est inactive. Il reçoit les CAN existants, le modèle,
les états Panda et les commandes du contrôleur actuel. Il ne publie aucune
commande, ne lit pas `carState` et ne modifie aucun réglage du RVV ou de la pédale.

Les observations contiennent la vitesse, les états usine LKA/EPS, le côté du
clignotant, la fraîcheur des entrées et les motifs de refus de chaque hypothèse.
À deux secondes de signal continu, un échantillon conserve la présence d'une
voie candidate et les états physiques. Le contexte routier et le trafic arrière
restent inconnus : cette observation n'autorise aucun changement de voie.
Une disponibilité EPS observée ne prouve pas l'acceptation d'une commande
à basse vitesse ou pendant le clignotant. `physical_acceptance_validated` reste
toujours `false`.

Cette installation passive ajoute seulement le module d'observation et ses
trois modules auxiliaires (`lateral_profiles.py`, `lane_change.py`,
`t9_lane_change.py`), puis son enregistrement dans `process_config.py`.
Elle conserve les contrôleurs, `modeld`, le lancement, l'interface, les binaires
et les paramètres actuels. Elle ne nécessite pas le nouveau firmware ni
l'installation d'un profil expérimental. Le gestionnaire démarre l'observation
automatiquement avec les modes T9/RVV ; `PSA_T9_OBSERVE=0` la désactive.

Les données restent dans `/data/psa-observation/` : `status.json` permet de
vérifier la réception et les fichiers `observation-*.jsonl` conservent les
décisions. La rétention est limitée à huit fichiers de 16 Mio et laisse 1 Gio
libre. Les mêmes décisions sont envoyées dans les journaux existants avec le
préfixe `psa_t9_observation`. Aucun texte supplémentaire n'est affiché sur
l'écran. Les captures récupérées et les comptes rendus restent sous
`data/runtime/`, hors Git.

## Profils isolés

| Sélecteur | Paramètre actif / observation Panda | Plancher direction | Clignotant |
|---|---|---|---|
| `off` | Profil existant | 67,1 km/h | Pause existante |
| `low_speed` | `0x1318` / `0x1319` | 50 km/h | Pause existante |
| `blinker` | `0x131A` / `0x131B` | 67,1 km/h | Assistance avec un seul signal |
| `low_speed_blinker` | `0x131C` / `0x131D` | 50 km/h | Assistance avec un seul signal |

Les trois expériences nécessitent le profil RVV/direction indépendant, le
réglage du cycle EPS et la capacité firmware 10. `pandad` interroge cette capacité
avant de choisir un paramètre, même d'observation ; un ancien firmware refuse
ainsi l'essai. Les anciens profils gardent leurs restrictions.

Le RVV reste à 40 km/h minimum. Les limites existantes de couple, de rampe,
de fraîcheur CAN, d'effort conducteur et d'accélération latérale sont conservées.
Le nouvel acquittement physique EPS reste obligatoire avant tout couple.
Un état EPS 0, un défaut ou un retrait d'autorisation pendant le pilotage arrête
la direction ; une récupération EPS ne la réarme pas.

L'état usine LKA 2 est admis uniquement dans le domaine de l'expérience :
sous 67,1 km/h pour `low_speed`, ou avec un clignotant physique unique pour
`blinker`. Au-dessus de 67,1 km/h, une chute LKA précédant le clignotant admet
au plus 150 ms à **couple nul** ; un signal tardif ne réautorise pas la session.
Les warnings arrêtent la direction dans le profil clignotant.

## Demande de changement de voie à deux secondes

Le superviseur et le simulateur de trajectoire sont préparés pour un seul
changement de voie par demande physique. À deux secondes, ils vérifient la
voie du bon côté, des données récentes et une géométrie stable. Le modèle doit
montrer des limites de voie plausibles à plusieurs distances ; un bord de route
ne remplace pas une limite de voie.

Le sens de circulation, l'autorisation de franchissement et le trafic arrière
sont des entrées indépendantes, datées. Le modèle actuel ne fournit pas ces
preuves : elles restent **inconnues** dans l'intégration native. Une absence
d'information refuse le départ à l'échéance ; une récupération ultérieure ne
déclenche pas de départ retardé. Les capteurs d'angle mort à `false` ne sont
pas assimilés à une preuve de voie libre.

`PSA_T9_LANE_CHANGE_MODE=observe` ajoute uniquement une observation dans
`modeld`. Elle ne modifie ni le désir du modèle, ni `carControl`, ni les commandes
CAN. Le mode de pilotage automatique n'est pas exposé au lancement. Il exige
d'abord la validation de ces entrées et du traitement d'une interruption.

Dans le simulateur, une intervention, une annulation, des données périmées ou
un délai dépassé supprime le désir de changement de voie et consomme la demande.
La fin nécessite un recentrage et une confirmation d'arrivée dans la voie cible.
Un clignotant maintenu ne provoque pas une deuxième manœuvre. Ces séquences
servent à la validation et ne prouvent pas une réponse physique de la direction.

## Produire les archives sans installation

Depuis ce dépôt, utiliser une copie connue des sources natives :

```sh
python3 openpilot/tools/prepare_t9_lateral_experiment.py \
  --source-tree /chemin/vers/les/sources/natives \
  --output data/runtime/t9-experiments/low_speed \
  --profile low_speed
```

Chaque archive contient un manifeste des empreintes avant/après et un profil
explicite. Répéter avec `blinker`, puis `low_speed_blinker` pour les essais
successifs. Un répertoire de sortie existant est refusé. L'outil ne copie rien
dans l'installation et ne démarre aucun processus.

Pour rejouer une route fermée à travers le superviseur en observation :

```sh
python3 openpilot/tools/replay_t9_lane_change.py \
  --schema /chemin/vers/les/sources/natives/preparees \
  --log-dir data/runtime/realdata --route IDENTIFIANT_ROUTE \
  --output data/runtime/t9-experiments/lane-replay.json
```

Ce replay conserve l'activation latérale effectivement enregistrée et laisse
le contexte routier/arrière inconnu. Il ne transforme pas un trajet manuel en
preuve d'un pilotage accepté par l'EPS.

La compilation native utilise exclusivement une copie `/data/t9-lateral-build-*`
et `scripts/build_t9_lateral_on_device.py`. Elle construit et teste le firmware
et `pandad` sans flasher le Panda. Les tests incluent le décodage CAN, le
contrôleur Python, les permissions du firmware C, les refus, la priorité
conducteur et la conservation du RVV physique.

Les archives, données brutes, diagnostics et résultats restent dans
`data/runtime/`, ignoré par Git. Seuls les sources, tests et ce guide générique
font partie de la publication.

L'ordre de validation physique reste celui de [ESSAIS_308_T9.md](ESSAIS_308_T9.md) :
basse vitesse, puis clignotant à une vitesse validée, puis observation du
changement de voie avant toute activation de sa trajectoire.
