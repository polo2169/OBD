# Collecte du comma avant détection du contact

Version installée et vérifiée après redémarrage le 16 septembre 2026 :
`6c928b70b` sur `peugeot-308-t9-dashcam-mici`. Le collecteur reste actif hors
contact. La détection T15 dans `pandad` a passé les replays, puis deux routes
réelles enregistrées le 17 septembre. Les rapports détaillés d'installation,
les sauvegardes et les routes restent dans les données locales du projet.

Le premier relevé du 15 septembre ne contenait aucun CAN. Les essais suivants,
le 16 septembre, contiennent 3,89 millions de trames avec le harnais reconnu.

## Pourquoi cette collecte

Les journaux du garage du 15 septembre montrent des trames CAN reçues, mais
`ignitionLine=false`, `ignitionCan=false` et `started=false`. Dans cet état,
`loggerd` ne produit pas de route normale. La collecte ajoutée à la branche
`peugeot-308-t9-dashcam-mici` démarre avec le gestionnaire, avant le contact,
et fonctionne sans Internet, même si l'écran indique « Start the car ».

Le processus `psa_recorder` s'abonne aux messages CAN et aux états déjà publiés
utiles à l'analyse : Panda, appareil, périphériques, commandes, sorties,
contrôles, événements, paramètres véhicule et messages T9 réservés. `carState`
reste enregistré par `loggerd` afin de ne pas consommer le dernier lecteur de
ce service. Le collecteur ne modifie ni le contact ni les paramètres, n'ouvre
pas directement le Panda, n'active pas les caméras et n'émet aucune requête
diagnostic. Les acquittements/erreurs électriques du Panda restent distincts
de cette absence d'émission applicative.

## Relevé à l'arrêt

Après validation du raccordement, voiture immobile :

1. Alimenter le comma et attendre le démarrage de l'interface.
2. Garder le contact coupé environ 30 secondes.
3. Mettre le contact, moteur arrêté, pendant environ 60 secondes.
4. Couper le contact et attendre encore 60 secondes avant de débrancher.
5. Revenir avec le comma sur le réseau accessible en SSH.

Il n'y a aucun script à lancer au garage. Noter l'ordre réel des manipulations
et tout message du tableau de bord. Si les alertes du premier incident
reviennent, interrompre l'essai et rétablir le montage d'origine contact coupé.
Ce relevé ne valide pas le montage pour rouler ni une commande de conduite.

## Récupération au retour

Depuis la racine du dépôt OBD sur le Mac :

```sh
./openpilot/scripts/fetch_comma_308_diagnostics.sh 172.19.159.205
```

Adapter l'adresse si elle a changé. La connexion utilise la clé SSH et la clé
d'hôte déjà validées. L'archive `.tar.gz` est créée sous `data/diagnostics/comma/`.
La récupération ne supprime pas les originaux et peut fonctionner pendant la
collecte. Aucun de ces fichiers n'est envoyé automatiquement à comma.

Pour envoyer une sélection bornée accompagnée du code exact, utiliser ensuite
[`export_t9_dataset.py`](../tools/export_t9_dataset.py) :

```sh
python3 openpilot/tools/export_t9_dataset.py \
  data/diagnostics/comma/308-AAAAmmjjTHHMMSSZ-PID.tar.gz \
  --segments 4 \
  --output data/diagnostics/comma/t9-dataset-a-partager.tar.gz
```

Le [guide de version et de dataset](COMMA_308_T9_RELEASE_2026-09-21.md) décrit
le manifeste, les empreintes du code et la vérification de confidentialité à
effectuer avant diffusion. Les captures et exports restent hors Git.

## Stockage et limites

- Dossier appareil : `/data/psa-diagnostics`, séparé des routes de l'uploader.
- Segments de 16 Mio, au maximum 32 : 512 Mio de données, plus quelques
  fichiers JSON. Les segments les plus anciens sont remplacés.
- Numérotation persistante indépendante de l'heure : la date peut repartir
  en mars lors d'un démarrage sans réseau. Un identifiant de session dans le
  JSON distingue les redémarrages du collecteur.
- Écritures synchronisées environ chaque seconde. Une coupure brutale peut
  perdre les dernières données ou tronquer le dernier événement ; les
  événements complets précédents restent lisibles.
- La collecte suspend les écritures quand l'espace libre passe sous la réserve
  de 1 Gio plus un segment. `status.json` indique les messages perdus pour cette
  raison. Un problème d'accès au stockage entraîne une nouvelle tentative
  après 30 secondes.
- `messages_received.can` compte les lots de messages, y compris les lots
  vides : ce n'est pas un compteur de trames. La complétude se vérifie avec le
  contenu enregistré et les compteurs RX/débordements Panda.
- Hors contact, le firmware coupe deux transceivers et leurs interruptions
  pour économiser l'énergie. Le collecteur enregistre ce qui est publié ; il
  ne réveille pas ces interfaces. Les trois bus ne sont donc pas garantis.
- Ce sont des événements Cap'n Proto bruts, sans vidéo, GPS ou `initData` de
  route. Ils ne remplacent pas une route comma pour la contribution upstream.

Lecture avec l'environnement openpilot de cette version :

```python
from pathlib import Path
from openpilot.tools.lib.logreader import LogReader

for event in LogReader.from_bytes(Path("capture-00000001.rlog").read_bytes()):
    if event.which() == "can":
        for frame in event.can:
            print(event.logMonoTime, frame.src, hex(frame.address), frame.dat.hex())
```

Utiliser `from_bytes` : cette version de `LogReader` refuse l'extension `.rlog`
dans son constructeur de chemin. Une alerte « Corrupted events detected » en
fin de dernier segment peut correspondre à une coupure d'alimentation.

## Correction associée du mode passif

### Piste de détection du contact par CAN

La comparaison des démarrages et du Stop & Start dans quatre captures ESP32
identifie désormais **`P372_T15_st` sur 0x348** comme candidat prioritaire.
Il reste à 1 pendant neuf arrêts moteur intermédiaires, alors qu'une séquence
montre son activation avant démarrage et son extinction avant l'arrêt final.
Les mesures locales distinguent ce signal du Stop & Start ; elles ne sont pas
incluses dans le petit dataset partageable.

La collecte comma du 16 septembre confirme la réception de ce signal sur le
bus logique 0, trois démarrages après cycles
de contact et son maintien à 1 pendant vingt cycles compatibles avec le Stop & Start.
Depuis la mise à jour du 16 septembre, le processus natif `pandad` utilise
ce bit pour publier `ignitionCan`. Le firmware Panda lui-même reste identique.

Le DBC générique [PSA AEE2010 d'opendbc](https://github.com/commaai/opendbc/blob/master/opendbc/dbc/psa_aee2010_r3.dbc)
nomme `IGNITION` le bit `32|1@0+` de la trame `0x572` (octet d'indice 4,
masque `0x01`) et indique une extinction retardée. Cette dénomination n'est
pas une validation sur la 308 T9.

Vérification locale du 15 septembre sur le roulage ESP32
`data/runtime/t9_drive_audit/drive-20260910T172156Z/can.jsonl` : **1 792 trames
0x572**, couvrant **179,094 secondes**, ont toutes l'octet 4 égal à `0x80`.
Le bit candidat vaut donc toujours zéro pendant ce roulage. Cela contredit une
interprétation directe « 1 = contact mis » sur cette capture ; une polarité
inverse ou une autre signification ne peut pas être validée sans états de
référence contact coupé/accessoires/contact mis et transitions répétées.

Le signal 0x572 n'est pas utilisé. La détection T15 s'effectue côté hôte dans
`pandad` ; la ligne physique de contact SBU2 du harnais n'est pas câblée.
La présence de trafic CAN ou la seule tension d'alimentation ne remplacent
pas la lecture de T15.

### Initialisation de la sécurité passive

Après écriture synchrone des `CarParams` passifs avec sécurité `noOutput`,
`card` signale désormais `ControlsReady`. Il le fait sans appeler `CI.init`
ou le contrôleur. Cela permet à `pandad` de quitter le mode de préparation
ELM327 une fois l'identification terminée. Les voitures actives conservent leur
attente d'initialisation du contrôleur.

Depuis la mise à jour T15, le mode dédié PSA reste `noOutput` même pendant
l'identification, sans passage par ELM327. `SKIP_FW_QUERY=1` évite toujours
les requêtes ECU. Le binaire `pandad` est modifié ; le firmware Panda reste
identique. Le fonctionnement réel après détection du contact reste à vérifier
sur des mesures ; les tests logiciels ne le remplacent pas.

## Caméras

Une capture manuelle des deux caméras route a réussi au retour à la maison.
Le grand-angle montre le bureau à l'envers ; la caméra étroite regarde une
surface très proche. Ce constat ne valide pas l'orientation du support dans
la voiture. Aucune image du pare-brise ni calibration en roulage n'est disponible.
Les photos restent dans `data/runtime/harness_audit/camera-view-20260915/`.
