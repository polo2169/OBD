# Diagbox++ / OpenDiag PSA + Fiat

Socle open source pour construire un outil de diagnostic PSA/Stellantis avancé sans
réimplémenter les couches standard déjà disponibles.

Références principales :

- [arduino-psa-diag](https://github.com/ludwig-v/arduino-psa-diag) pour la recherche PSA UDS/KWP et les familles de calculateurs ;
- [PSA-RE](https://github.com/prototux/PSA-RE) pour les architectures AEE2004/AEE2010 et les descriptions DBMUXE ;
- [python-can](https://github.com/hardbyte/python-can) pour l'accès CAN ;
- [python-can-isotp](https://github.com/pylessard/python-can-isotp) pour ISO-TP ;
- [udsoncan](https://github.com/pylessard/python-udsoncan) pour UDS ISO 14229 ;
- [VanBus](https://github.com/0xCAFEDECAF/VanBus) pour les architectures PSA VAN ;
- [OBD-LCD-display-for-PSA](https://github.com/nico1080/OBD-LCD-display-for-PSA) et [AutoWP](https://autowp.github.io) comme sources complémentaires.
Starter kit open source pour construire un outil de diagnostic automobile modulaire :

- **ESP32 / ESP32-S3** : passerelle CAN/TWAI vers USB série ou Wi-Fi privé ;
- **RDK X5 ou PC Linux** : moteur de diagnostic, stockage, API et IA ;
- **React** : interface utilisateur ;
- **Base YAML PSA** : véhicules, calculateurs, DIDs et DTC documentés ;
- **Simulateur** : développement sans voiture.

lien interressant : https://driver.top/exp/695220
https://driver.top/exp/700838/
https://github.com/Barracuda09/PyPSADiag

https://driver.top/exp/253246/

## État de cette version

Fonctions disponibles :

- écoute CAN passive sur l'ESP32 ;
Code : B1238- protocole USB/TCP v6 : contrôle JSON Lines et trames CAN compactes sans filtrage ;
- lecture et journalisation de trames ;
- transport virtuel pour les tests ;
- lecture OBD-II générique simulée ;
- pile ISO-TP complète via `python-can-isotp` (trames simples et segmentées) ;
- client UDS via `udsoncan` avec gestion des NRC et temporisations P2/P2* ;
- scanner UDS configurable avec session réutilisée par calculateur ;
- lecture et décodage des DIDs d'identification ISO 14229 ;
- lecture DID ciblée par API ;
- profil T9 enrichi avec 11 familles ECU sourcées et présence optionnelle explicite ;
- lecture UDS `0x19/0x02`, décodage des états et descriptions DTC PSA ;
- catalogue communautaire normalisé : 355 variantes et 40 840 définitions sourcées ;
- mode « capteurs uniquement » avec découverte des PID OBD-II Mode 01 supportés ;
- direct hybride Fiat/Peugeot : CAN constructeur passif prioritaire et complément
  OBD Mode 01 borné par profil (régime, vitesse, températures, admission et
  tension calculateur/batterie) ;
- arbitrage transactionnel du transport partagé : une capture peut rester active
  pendant le polling OBD sans mélanger les réponses ISO-TP avec un scan ECU ;
- catalogue multimarque de 29 services de maintenance, avec applicabilité par
  profil, équipement conditionnel, niveau de risque et verrouillage systématique
  des procédures non validées sur véhicule ;
- sessions JSONL détaillées : CAN, passerelle, ISO-TP, UDS/OBD, NRC et durées ;
- API FastAPI ;
- interface React ;
- navigation stabilisée autour de six modules : Garage, Diagnostic, Atelier,
  Learn, Database et Security & Workflow ;
- sélecteur de mode global Lecture seule / Maintenance contrôlée, avec
  préconditions, confirmation, retour immédiat au mode sûr et audit par VIN ;
- Live Data transversal avec ajout, modification et archivage de capteurs locaux
  au VIN, sans modifier la capture CAN d'origine ;
- garage multi-véhicules avec sélection persistante du VIN actif et chronologie
  consolidée des diagnostics, trajets et identifications ;
- replay temporel des captures CAN avec Peugeot vue du dessus, instruments, commandes et états ADAS ;
- reconstruction locale du mouvement par vitesse et angle du volant, avec cache de post-traitement sur le PC ;
- base PSA extensible avec niveaux de confiance ;
- séparation entre autorisation matérielle TX et filtrage applicatif lecture seule.
- mode « Diagnostic PSA avancé » : lecture de zones brutes, calcul seed/key hors
  ligne, clés candidates par ECU et actionneurs NAC strictement nommés ;
- profil firmware `esp32-tja1050-serial-psa-lab` à allowlist doublement vérifiée
  par le PC et l'ESP32, distinct du firmware de lecture seule.
- page « VIN & véhicule » : lecture UDS `22 F1 90` sur Peugeot, lecture OBD-II
  Mode 09 PID 02 sur Fiat, validation WMI et journalisation JSONL locale ;
- profil initial Fiat 500 en identification seule, avec les candidats Body Computer
  `7B0→7C0` et combiné `7B0→7C3` clairement marqués expérimentaux.


## Architecture

Le contrat fonctionnel et les règles de sécurité sont décrits dans
[docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

```text
OBD-II
  │
Transceiver CAN automobile
  │
ESP32-S3
  │ Wi-Fi privé / TCP ou USB série (protocole v6)
  │
RDK X5 ou PC
  ├── FastAPI
  ├── udsoncan
  ├── python-can-isotp
  ├── Transports CAN / série / virtuel
  ├── Base PSA YAML
  ├── Historique
  ├── Analyse acoustique
  └── React
```

## Lancer toute l'application

### Première installation

Depuis la racine du dépôt, préparer une fois les dépendances du backend et du
frontend :

```bash
cd backend
python3 -m venv .venv
./.venv/bin/pip install -r requirements.txt
test -f .env || cp .env.example .env

cd ../frontend
npm install
cd ..
```

Le fichier `backend/.env` choisit le matériel utilisé. Pour travailler sans
voiture, conserver `TRANSPORT=virtual`. Pour la passerelle USB, utiliser
`TRANSPORT=esp32_serial` et renseigner son `SERIAL_PORT`.

Les réglages et observations propres à la machine sont écrits dans
`data/runtime/`, qui n'est pas versionné. Les fichiers `data/*.example.json`
documentent les formats attendus sans publier de port série, VIN ou défaut
observé.

### Vérification avant commit

Depuis la racine du dépôt :

```bash
./scripts/check_project.sh
```

Cette commande exécute les tests backend, le contrôle TypeScript strict et le
build frontend dans un répertoire temporaire. Si PlatformIO est installé, elle
compile aussi le profil firmware passif par défaut. La CI reprend ces contrôles
et compile en plus les profils firmware actifs filtrés de référence.

### Frontend et backend en une commande

Toujours depuis la racine du dépôt :

```bash
./scripts/start_app.sh
```

Le script lance simultanément :

- l'interface React sur <http://127.0.0.1:5173> ;
- l'API FastAPI sur <http://127.0.0.1:8000> ;
- la documentation de l'API sur <http://127.0.0.1:8000/docs>.

Les journaux des deux services restent visibles dans le même terminal. Utiliser
`Ctrl+C` pour arrêter proprement le frontend et le backend ensemble.

Pour forcer le simulateur sans modifier `backend/.env` :

```bash
TRANSPORT=virtual ./scripts/start_app.sh
```

Les ports peuvent également être changés ponctuellement ; le lanceur transmet
automatiquement le nouveau port du backend au frontend :

```bash
BACKEND_PORT=8002 FRONTEND_PORT=5174 ./scripts/start_app.sh
```

### Démarrage manuel, service par service

#### Backend

```bash
cd backend
python -m venv .venv
source .venv/bin/activate
# Windows : .venv\Scripts\Activate.ps1
pip install -r requirements.txt
cp .env.example .env
uvicorn app.main:app --reload
```

Documentation :

```text
http://127.0.0.1:8000/docs
```

#### Frontend

```bash
cd frontend
npm install
npm run dev
```

Interface :

```text
http://localhost:5173
```

### Replay véhicule et trajectoire

Ouvrir **Replay véhicule** dans la barre latérale, puis choisir une session. Le
backend parcourt le JSONL en flux, échantillonne les signaux à 10 Hz et conserve
le résultat dans `data/sessions/<session>.replay.json`. La capture originale n'est
jamais modifiée.

Le replay anime la vitesse, le régime moteur, le volant, les pédales, les
clignotants, les feux et les signaux ADAS disponibles. L'option **Enregistrer le
trajet GPS**, active par défaut, utilise la géolocalisation du navigateur et écrit
chaque position dans le JSONL avec l'heure, la précision, l'altitude, le cap et la
vitesse disponibles. Le navigateur doit être ouvert sur `localhost` ou via HTTPS.
Un refus de permission n'interrompt jamais la capture CAN.

Avec au moins deux positions exploitables, le replay synchronise la trace GPS aux
échantillons CAN. Une position unique sert seulement d'ancrage à la reconstruction
vitesse/volant. Sans GPS, l'origine et l'orientation restent arbitraires et la
trajectoire ne doit pas être superposée à une route réelle. La trace brute est
exportable en GeoJSON depuis le replay.

API correspondante :

```text
GET /api/learn/replay/{session_id}
GET /api/learn/replay/{session_id}?force=true
GET /api/learn/replay/{session_id}/route.geojson
```

#### Vidéo caméra + CAN synchronisée

Les sessions produites par l'enregistreur caméra/CAN d'openpilot peuvent être
rendues hors ligne avec le DBC spécifique à la 308 T9 :

```bash
cd backend
.venv/bin/python tools/render_camera_can_replay.py \
  /chemin/vers/record-YYYYMMDDTHHMMSSZ
```

Le rendu utilise `frames.jsonl` comme horloge caméra et l'ancre ESP32 de
`meta.json` pour sélectionner l'état CAN de chaque image. Il ne suppose donc pas
que les images ont réellement été capturées au débit nominal inscrit dans le
MP4. Les sorties (vidéo H.264, télémétrie JSONL, rapport et sous-titres) sont
écrites dans `data/runtime/camera_can_replays/`, hors Git. L'opération est
strictement hors ligne : aucun port série n'est ouvert et aucune trame CAN n'est
émise.

Le décodage nécessite l'environnement Python du backend (`cantools`). Le dessin
des images nécessite un Python contenant OpenCV ; l'environnement openpilot
frère est détecté automatiquement, ou peut être indiqué avec
`--renderer-python /chemin/vers/python`.

#### Perception openpilot sur une vidéo enregistrée

Le vrai modèle `driving_supercombo` installé dans le dépôt openpilot frère peut
être exécuté hors ligne sur la vidéo. Le résultat superpose le chemin prédit, les
quatre lignes de voie avec leur confiance, les deux bords de route et le meilleur
véhicule précédent possible :

```bash
cd backend
env -u DEBUG ../../openpilot/.venv/bin/python \
  tools/run_openpilot_perception.py \
  /chemin/vers/record-YYYYMMDDTHHMMSSZ
```

Pour valider rapidement le cadrage avant de traiter toute la capture :

```bash
env -u DEBUG ../../openpilot/.venv/bin/python \
  tools/run_openpilot_perception.py \
  /chemin/vers/record-YYYYMMDDTHHMMSSZ \
  --start-frame 7350 --max-frames 600
```

L'outil reproduit le redressement optique et le recadrage décrits dans
`camera_intrinsics.json`, respecte les horodatages réels de `frames.jsonl`, puis
alimente le modèle à 20 Hz. Si la télémétrie du replay caméra/CAN existe, la
vitesse décodée sert aussi au calibrateur openpilot. Les prédictions JSONL, le
rapport et la vidéo H.264 sont écrits dans
`data/runtime/openpilot_perception/<session>/`, hors Git.

Cette commande ne démarre ni `manager`, ni `camerad`, ni `controlsd`, n'ouvre
aucun adaptateur et n'émet aucune trame CAN. Le modèle openpilot ne fournit pas
des boîtes pour tous les objets visibles : ses trois sorties `lead` représentent
les horizons de probabilité à 0, 2 et 4 secondes, et non trois voitures. Le
losange orange utilise toujours l'horizon courant `t=0`. Sa distance suit le
calcul officiel de `radard.py`, soit la coordonnée longitudinale du modèle moins
`RADAR_TO_CAMERA = 1,52 m`. Il matérialise une estimation, pas une mesure radar
ni une détection certifiée de chaque voiture.

#### Caméra + openpilot + CAN en direct sur le Mac

Le même modèle peut fonctionner en direct dans une fenêtre OpenCV, avec le CAN
308 T9 décodé en parallèle. Le processus modèle ne conserve que la dernière
image caméra : si l'inférence est plus lente que la caméra, les anciennes images
sont abandonnées au lieu de former une file et d'augmenter continuellement la
latence.

Lister les caméras disponibles :

```bash
cd backend
env -u DEBUG ../../openpilot/.venv/bin/python \
  tools/run_openpilot_live.py --list-cameras
```

Lancer la caméra et l'ESP32 connecté sur le port validé :

```bash
env -u DEBUG ../../openpilot/.venv/bin/python \
  tools/run_openpilot_live.py \
  --camera 0 \
  --rotate-180 \
  --port /dev/cu.usbserial-0001
```

Le redressement optique, la rotation de la caméra et le cadrage sont repris de
`camera_intrinsics.json`. Sur le Mac de test, AVFoundation associe l'index `0` à
la Lenovo FHD montée à l'envers et l'index `1` à la caméra FaceTime. La rotation
180° est donc activée par défaut pour la caméra route et peut être rendue
explicite avec `--rotate-180`. Pour tester la caméra du Mac, utiliser
`--camera 1 --no-rotate-180`. Cette option est ignorée avec `--video`, car les
captures enregistrées sont déjà orientées. Le lecteur CAN utilise le DBC 308 T9 du dépôt et
affiche notamment vitesse, rapport/cible EAT6, frein, accélérateur, volant, RVV,
clignotants gauche/droite/warning, portes, ceinture et frein de parking. Les
flèches du HUD reproduisent le clignotement du combiné à partir de l'état `0x452`.
Au-dessus de 20 mph (environ 32 km/h), un clignotant unique suivi d'un effort
conducteur validé (`DriverTorqueRaw > +5` à gauche ou `< -5` à droite) injecte
une impulsion `laneChangeLeft` ou `laneChangeRight` dans le modèle. Le HUD passe
de **ATTENTE EFFORT** à **MODELE GAUCHE/DROITE**. La voiture ne possédant pas de
détection d'angle mort, aucun état de ce type n'est inventé. Cette fonction ne
change que le chemin prédit et peut être désactivée avec `--no-blinker-desire` ;
elle ne produit toujours aucune commande véhicule.
`q` ou Échap ferme la fenêtre ; `s`
enregistre une capture d'écran.

Une session brute synchronisée peut aussi être enregistrée :

```bash
env -u DEBUG ../../openpilot/.venv/bin/python \
  tools/run_openpilot_live.py \
  --camera 0 \
  --port /dev/cu.usbserial-0001 \
  --record
```

`--record` conserve `road.mp4`, `frames.jsonl`, le CAN brut, les prédictions et
les métadonnées dans `data/runtime/openpilot_live/`. `--record-overlay` ajoute
la vidéo de l'interface et sa propre chronologie, avec un coût CPU supérieur.
À la fermeture propre, les horodatages des deux MP4 sont automatiquement remis
à la cadence réellement mesurée, sans réencoder les images. Les sessions créées
avant ce correctif peuvent être réparées sans écraser les originaux avec :

```bash
cd backend
.venv/bin/python tools/retime_openpilot_live.py \
  data/runtime/openpilot_live/live-YYYYMMDDTHHMMSSZ
```

Cette commande crée `road-realtime.mp4` et `overlay-realtime.mp4`.
Une vidéo existante peut simuler la caméra pour valider le montage sans voiture :

```bash
env -u DEBUG ../../openpilot/.venv/bin/python \
  tools/run_openpilot_live.py \
  --video /chemin/vers/road.mp4 \
  --video-start-frame 7350 \
  --no-can
```

Le lecteur série est un processus isolé exécuté avec l'environnement backend.
Il effectue uniquement des lectures série par blocs et ne contient aucune
écriture série, aucune publication `sendcan` et aucune commande véhicule. Les
trames brutes sont toutes conservées, tandis que seul le dernier exemplaire de
chaque identifiant est décodé à 20 Hz pour empêcher le flux T9 d'environ
1 570 trames/s de prendre du retard. Le HUD distingue désormais `OK`, `RETARD`
et `PERDU`; le débit, le retard maximal, les pertes firmware et le backlog final
sont aussi enregistrés dans `meta.json`. Un seul programme peut ouvrir
la caméra et le port ESP32 : arrêter l'enregistreur, le backend direct ou un
scanner UDS avant de lancer le live. Ne pas effectuer de diagnostic actif en
parallèle.

Sur le Mac utilisé pour les essais, la caméra traitée atteint environ 25 Hz sans
enregistrement, le modèle 6,5 Hz et la latence observée 160–220 ms. Ce mode est
adapté à l'observation et au développement, pas à une boucle de contrôle de la
direction ou du freinage.

#### Simulateur latéral T9 hors ligne

Les sessions `--record` peuvent alimenter un simulateur de couple strictement
hors ligne. Il synchronise le chemin prédit avec la vitesse, le lacet, le couple
conducteur, le frein et les interverrouillages CAN, puis compare plusieurs
hypothèses de réponse de la direction :

```bash
cd backend
.venv/bin/python tools/simulate_t9_torque.py \
  ../data/runtime/openpilot_live/live-20260812T084624Z \
  ../data/runtime/openpilot_live/live-20260812T085627Z
```

Le dossier `data/runtime/t9_torque_simulator/sim-*/` contient un rapport HTML,
le rapport JSON complet et les traces JSONL/CSV. Le calcul distingue la consigne
fantôme sans conducteur de la consigne qui aurait été neutralisée par un effort
au volant supérieur à `DriverTorqueRaw = 5`. Il applique aussi une limite brute
de ±10, des rampes, la vitesse minimale, le frein, la marche avant EAT6
confirmée, la porte, la ceinture, le frein de parking et la fraîcheur du CAN.

Le simulateur exploite aussi, uniquement comme référence de recherche, la
branche `cristianku/openpilot:psa-torque-sunny` et son openDBC associé. Il
décodera `EPS_STATE_LKA`, le couple EPS candidat et l'état « volant tenu » dans
`0x495`, puis simulera le réarmement périodique de 8 s du fork avec plusieurs
latences hypothétiques (`0,1`, `0,3`, `0,7` et `1,0 s`). Le rapport indique la
fraction d'indisponibilité et les coupures qui tomberaient pendant une courbe.
Il compare également ces hypothèses à la capture usine T9 contenant 536
commandes `0x3F2` non nulles.

Ce profil R3 reste séparé : ses limites ±150/±200, son facteur 25–100, son octet
`0x18` et son interprétation `EPS_STATE_LKA=3` ne sont pas appliqués à la T9
R2/EVO. Les injections utilisées par le fork pour simuler les mains sur le
volant ou un couple conducteur ne sont ni reproduites ni encodées.

La corrélation entre l'effort conducteur et le lacet sert uniquement à centrer
l'analyse de sensibilité. Elle ne mesure pas le transfert réel de la commande
EPS `0x3F2`. Les gains produits optimisent donc un modèle numérique simplifié et
ne sont pas des paramètres prêts pour un essai routier. Le programme n'importe
aucun pilote série, n'accepte aucun port, n'encode aucune trame et n'émet aucune
commande véhicule.

### Garage, véhicule actif et historique

Ouvrir **Garage & historique** avant de travailler sur une voiture. Le véhicule
chargé est mémorisé côté PC par son VIN et devient le contexte commun du direct,
des diagnostics, des DTC et des replays. Le sélecteur présent dans l'en-tête
permet ensuite de changer rapidement de dossier.

Chaque nouvelle capture CAN reçoit automatiquement le VIN actif. Les anciennes
captures restent volontairement « sans VIN » jusqu'à leur classement depuis le
Garage : leur association utilise un petit fichier annexe
`data/sessions/<session>.vehicle.json` et ne réécrit jamais le JSONL brut.

La chronologie d'un véhicule regroupe :

- ses lectures d'identité ;
- ses diagnostics ECU/DTC et leurs comparaisons avant/après ;
- ses captures CAN et trajets GPS, ouvrables directement dans le replay.

Le changement de véhicule est bloqué pendant une capture afin d'éviter qu'une
session soit enregistrée sous le mauvais VIN.

### Simulation

Le backend utilise `TRANSPORT=virtual` par défaut.

```bash
curl http://127.0.0.1:8000/api/system/status
curl -X POST http://127.0.0.1:8000/api/diagnostic/scan
curl -X POST http://127.0.0.1:8000/api/sensors/snapshot
curl -X POST http://127.0.0.1:8000/api/diagnostic/ecus/engine/dids/0xF190
curl http://127.0.0.1:8000/api/database/vehicles
curl -X POST http://127.0.0.1:8000/api/diagnostic/identity \
  -H 'Content-Type: application/json' \
  -d '{"vehicle_profile":"fiat_500_generic"}'
curl http://127.0.0.1:8000/api/database/dids
curl http://127.0.0.1:8000/api/diagnostic/live
```

## Firmware ESP32 / ESP32-S3

Le firmware utilise PlatformIO et le pilote TWAI Arduino.

Pour l'ESP32 classique associé au transceiver Waveshare SN65HVD230, le profil
passif Wi-Fi est désormais le profil par défaut :

```bash
cd firmware/esp32-gateway
pio run -e esp32-waveshare-wifi-readonly
pio run -e esp32-waveshare-wifi-readonly -t upload
```

Il crée le point d'accès `OpenDiag-ESP32` et écoute en TCP sur
`192.168.4.1:35000`. Le mot de passe de développement est `opendiag-safe`.
Avant un usage régulier, copier `include/secrets.example.hpp` vers
`include/secrets.hpp` et remplacer ce mot de passe. Le fichier secret n'est pas
versionné.

```bash
cd firmware/esp32-gateway
# ESP32 classique : firmware passif par défaut
pio run -e esp32-readonly
pio run -e esp32-readonly -t upload
pio device monitor -b 921600
```

Le firmware actif doit être demandé explicitement. Il est nécessaire même pour une
lecture UDS/OBD, car une lecture implique d'émettre une requête CAN :

```bash
pio run -e esp32-active
pio run -e esp32-active -t upload
```

Pour le TJA1050 sur GPIO 5/4 et la liaison USB série, préférer le profil verrouillé
qui n'autorise dans le firmware que les lectures OBD/UDS documentées :

```bash
pio run -e esp32-tja1050-serial-diagnostic -t upload
```

Pour une carte ESP32-S3, utiliser respectivement `esp32-s3-readonly` et
`esp32-s3-active`. Vérifier le modèle avant le flash : un pont USB CP2102 ne suffit
pas à distinguer la famille de la puce.

Pour un diagnostic actif réel, il faut à la fois le firmware `active` et
`CAN_TX_ENABLED=true` dans le backend. `READ_ONLY=true` doit rester activé pour
bloquer les services UDS d'écriture, programmation, effacement et sécurité.

Voir [docs/ESP32_TEST.md](docs/ESP32_TEST.md) pour le premier essai sur véhicule.

### VIN et profil Fiat 500

La page **VIN & véhicule** propose la Peugeot 308 T9 et un premier profil Fiat
500. Pour la Peugeot, elle tente le DID UDS standard `F190` sur le BSI puis le
calculateur moteur avant le repli OBD-II. Pour la Fiat, elle commence par la
commande normalisée `09 02` sur `7E0→7E8`, puis seulement en cas d'échec tente
les paires communautaires Fiat en lecture `22 F1 90`.

Le résultat contient le VIN, le WMI, le constructeur détecté, la méthode qui a
répondu et les champs d'identité disponibles. Toute l'opération est enregistrée
dans `data/sessions/*.jsonl`. Le profil Fiat est limité à l'identification tant
que l'année, la motorisation et la génération exacte ne sont pas confirmées.
Voir [docs/VEHICLE_IDENTITY.md](docs/VEHICLE_IDENTITY.md).

### Diagnostic PSA avancé

La page **Diagnostic PSA avancé** permet de lire n'importe quel DID `0x22` sur
une paire ECU documentée et de calculer une réponse seed/key hors ligne. Ces
fonctions n'exposent aucun champ d'émission CAN arbitraire.

Les tests NAC documentés (écran et caméra) utilisent un profil dédié :

```bash
cd firmware/esp32-gateway
pio run -e esp32-tja1050-serial-psa-lab
pio run -e esp32-tja1050-serial-psa-lab -t upload
```

Ils restent verrouillés tant que `READ_ONLY=false`, `CAN_TX_ENABLED=true` et
`PSA_ACTUATOR_ENABLED=true` ne sont pas explicitement réunis. Le déverrouillage
de configuration possède son propre verrou `PSA_SECURITY_ACCESS_ENABLED=true`.
Chaque opération exige en plus les confirmations atelier dans l'interface.

Chaque page calculateur PSA contient également un atelier de télécodage issu du
catalogue PyPSADiag. Il impose une variante ECU exacte et le parcours
`lecture → sauvegarde VIN → diff → relecture anti-concurrence → écriture unique
→ contrôle`. Les écritures restent désactivées tant que
`PSA_TELECODING_WRITE_ENABLED=true` et `PSA_SECURITY_ACCESS_ENABLED=true` ne
sont pas réunis avec le mode Maintenance contrôlée et le firmware
`psa_lab_bounded_writes`. Les sauvegardes et rapports restent locaux dans
`data/runtime/telecoding/`.

Les commandes BSI de clignotants ne sont pas connues : elles apparaissent dans
le catalogue mais restent non exécutables. Voir [docs/PSA_ADVANCED.md](docs/PSA_ADVANCED.md).

### Câblage prototype

Ne connecte jamais directement les GPIO de l'ESP32 à CAN-H/CAN-L.

```text
ESP32 GPIO TX/RX
       │
Transceiver CAN 3,3 V
       │
CAN-H / CAN-L
       │
OBD-II broches 6 et 14
```

Pour les premiers essais :

- alimentation ESP32 par batterie USB, câble du PC physiquement débranché ;
- masse commune ;
- véhicule immobile ;
- firmware en mode passif ;
- aucune résistance de terminaison supplémentaire sur une voiture déjà terminée.

### Waveshare SN65HVD230 3,3 V — montage retenu

L'ESP32 possède déjà le contrôleur TWAI : le MCP2515 n'est pas utilisé dans ce
montage. Le module Waveshare n'est pas isolé galvaniquement. Sa protection ESD ne
doit pas être confondue avec une isolation du PC.

| Waveshare | ESP32 / OBD | Remarque |
|---|---:|---|
| 3.3V | ESP32 3V3 | jamais OBD 16 |
| GND | ESP32 GND et OBD 5 | masse commune nécessaire |
| CAN_TX / D | GPIO 17 | de préférence via cavalier amovible |
| CAN_RX / R | GPIO 16 | logique 3,3 V |
| CANH | OBD 6 | câble court |
| CANL | OBD 14 | câble court |

Le schéma de cette carte contient une résistance `R2` de 120 ohms entre CAN-H et
CAN-L. Elle doit être dessoudée pour une connexion en dérivation sur la prise OBD,
le réseau du véhicule étant déjà terminé. Le premier essai se fait avec le profil
`esp32-waveshare-wifi-readonly`, la liaison TX idéalement ouverte, une batterie USB
et aucun câble entre l'ESP32 et le PC.

Le PC se connecte ensuite au réseau Wi-Fi de l'ESP32 et enregistre directement les
captures dans `data/sessions`. La file RAM du firmware absorbe les variations
courtes ; les compteurs `wifi_dropped_messages` et les numéros `seq` rendent toute
perte visible. Sans carte SD, une coupure Wi-Fi prolongée ne peut pas être récupérée.

Le module TJA1050 câblé selon le tutoriel ESP32 (`TX=GPIO5`, `RX=GPIO4`) dispose
des profils Wi-Fi équivalents `esp32-tja1050-wifi-readonly` et
`esp32-tja1050-wifi-active`. Utiliser le premier pour toute validation initiale.

### Module MCP2515 + TJA1050

Le MCP2515 est pris en charge avec la bibliothèque maintenue
[`autowp-mcp2515`](https://github.com/autowp/arduino-mcp2515), épinglée en version
1.3.1. Les profils disponibles sont :

```text
esp32-mcp2515-8mhz-readonly
esp32-mcp2515-8mhz-active
esp32-mcp2515-16mhz-readonly
esp32-mcp2515-16mhz-active
esp32-dual-can-16mhz-serial-diagnostic
esp32-dual-can-16mhz-serial-psa-lab
```

Choisir la fréquence inscrite sur le quartz métallique du module (`8.000` ou
`16.000`). Le profil `readonly` place matériellement le MCP2515 en mode
`listen-only`.

Le TJA1050 est un composant 5 V. Un module MCP2515/TJA1050 alimenté en 5 V ne doit
pas être relié directement aux GPIO 3,3 V de l'ESP32 : utiliser un traducteur de
niveaux logique adapté au SPI. Le câblage logique prévu, de part et d'autre de ce
traducteur, est :

| MCP2515 | ESP32 | Direction |
|---|---:|---|
| SCK | GPIO 18 | ESP32 vers MCP2515 |
| SO / MISO | GPIO 19 | MCP2515 vers ESP32 |
| SI / MOSI | GPIO 23 | ESP32 vers MCP2515 |
| CS | GPIO 5 en MCP seul, GPIO 27 en double CAN | ESP32 vers MCP2515 |
| INT | non connecté en MCP seul, GPIO 26 en double CAN | MCP2515 vers ESP32 |
| GND | GND | masse commune |

Alimenter le module en 5 V régulé depuis l'USB, jamais directement depuis le 12 V
de la broche 16 OBD. Vérifier hors tension la résistance entre CAN-H et CAN-L : si
le module présente environ 120 ohms, retirer/désactiver sa terminaison avant de le
brancher au véhicule, déjà terminé. CAN-H va sur OBD 6, CAN-L sur OBD 14 et la masse
commune sur OBD 4 ou 5.

Dans le montage double CAN de la Peugeot 308 T9, le tableau se lit avec
`CS=GPIO27` et `INT=GPIO26`. Le TJA/TWAI actuel reste sur OBD `6/14` ; le MCP2515
quartz `16.000` est relié à CAN-H OBD `3` et CAN-L OBD `8`. Le profil
`esp32-dual-can-16mhz-serial-diagnostic` lit les deux réseaux en même temps. Sur
`6/14`, il n'autorise que les requêtes OBD-II normalisées `01` et `09` adressées à
`0x7E0`, ainsi que le contrôle de flux ISO-TP nécessaire aux réponses. Sur `3/8`,
il conserve l'allowlist diagnostic en lecture seule. Le backend applique la même
séparation et la même double validation avant l'envoi, puis inscrit l'origine
`live`/`diagnostic` dans chaque capture.

Références électriques : [MCP2515 Microchip](https://www.microchip.com/content/dam/mchp/documents/APID/ProductDocuments/DataSheets/MCP2515-Family-Data-Sheet-DS20001801K.pdf),
[TJA1050 NXP](https://www.nxp.com/docs/en/data-sheet/TJA1050.pdf).

### Double CAN recommandé : deux ESP32 par UART

Le montage courant n'utilise plus le MCP2515. Une ESP32 principale écoute OBD
`6/14` avec TWAI et reste connectée au PC ; une seconde ESP32 utilise son TWAI sur
OBD `3/8`. Elles échangent les trames diagnostic à 2 Mbit/s :

| Principale | Satellite |
|---|---|
| GPIO17 TX | GPIO16 RX |
| GPIO16 RX | GPIO17 TX |
| GND | GND |

Flasher respectivement `esp32-dual-uart-main-diagnostic` et
`esp32-dual-uart-satellite-diagnostic`. Le backend continue à voir une seule
passerelle `dual_can` et sépare les trames `live` et `diagnostic`. La carte
principale n'accepte sur `6/14` que les lectures OBD-II `01`/`09` à destination de
`0x7E0` et leur contrôle de flux ISO-TP. Les requêtes UDS restent relayées
exclusivement vers le satellite `3/8`. Avec ce profil normal, effacement DTC,
écriture, routine et commande d'actionneur restent bloqués sur les deux réseaux.
Le profil séparé `esp32-dual-uart-satellite-psa-lab` est requis pour une séance de
maintenance ; même dans ce mode, seul `14 FFFFFF` et les rares actions PSA nommées
de l'allowlist firmware peuvent franchir la satellite.

### Transceiver TJA1050 seul

Un module portant des broches telles que `VCC`, `GND`, `CTX/TXD`, `CRX/RXD`,
`CANH` et `CANL` est un transceiver seul. C'est le montage le plus simple avec
l'ESP32, car il utilise directement le pilote TWAI et les profils `esp32-readonly`
ou `esp32-active` :

| TJA1050 | ESP32 / OBD | Remarque |
|---|---|---|
| VCC | 5 V USB régulé | jamais OBD 16 (12 V) |
| GND | GND ESP32 et OBD 4/5 | masse commune |
| CTX / TXD | GPIO 5 | liaison directe admise, VIH minimal TJA1050 = 2 V |
| CRX / RXD | GPIO 4 | adaptation 5 V vers 3,3 V obligatoire |
| CANH | OBD 6 | bus CAN High |
| CANL | OBD 14 | bus CAN Low |

Pour CRX/RXD, utiliser de préférence un traducteur de niveau rapide. À défaut, un
pont résistif 10 kohms entre RXD et GPIO 4, puis 18 kohms entre GPIO 4 et GND,
abaisse 5 V à environ 3,2 V. Vérifier au multimètre avant de raccorder GPIO 4.
Comme pour le MCP2515, retirer ou désactiver toute terminaison 120 ohms présente
sur le module avant raccordement au véhicule.

## Protocole passerelle

Les messages de contrôle restent en JSON Lines. Depuis le protocole 6, les trames
CAN utilisent sur le fil une ligne hexadécimale compacte afin de rester sous la
limite du pont CP2102 à 921 600 bauds, même sur un bus chargé :

```text
{"type":"hello","protocol":6,"device":"opendiag-esp32","firmware":"0.7.2-framed-diagnostic-lock","diagnostic_read_only":true,"bitrate":500000}
F,1E240,2A,7E8,20,0362F19000000000
{"type":"stats","rx":1200,"tx":0,"dropped":0,"bus_off":0,"rx_error_counter":0,"tx_error_counter":0}
```

Le backend développe immédiatement chaque ligne `F` et écrit toujours un JSONL
complet dans `data/sessions`, avec horodatages ESP/PC, identifiant, données et
événements de perte. Le fichier est vidé périodiquement puis synchronisé sur disque
à l'arrêt de la capture avant de lancer le post-traitement.

Commandes autorisées par défaut :

```json
{"type":"set_filter","ids":[2015,2024]}
{"type":"clear_filter"}
{"type":"ping"}
{"type":"get_status"}
```

La commande `can_tx` n'est disponible que dans un firmware actif ou dans le profil
`esp32-tja1050-serial-diagnostic`. Ce dernier verrouille aussi côté ESP les
identifiants et services autorisés en lecture. Le format étendu et les huit octets
maximum sont validés avant émission.

## Base PSA

Les fichiers de `database/psa` contiennent uniquement des éléments standards ou des exemples
marqués comme expérimentaux. Une donnée PSA ne doit être ajoutée qu'avec :

- une source ;
- un véhicule ou une architecture ;
- un niveau de confiance ;
- un niveau d'accès.

Le profil 308 T9 2018 contient maintenant moteur, boîte, ABS/ESP, BSI, airbag,
direction assistée, combiné, climatisation, caméra multifonction, aide au
stationnement et télématique. Les adresses proviennent d'un catalogue de familles :
les équipements optionnels ne sont considérés présents qu'après une réponse UDS.

Le catalogue DTC importé conserve sa provenance GPL-3.0 et la révision exacte. Une
description reste communautaire jusqu'à identification de la variante ECU ; le code
brut et l'octet d'état sont toujours conservés dans le rapport.

## Effacement des défauts

Le service UDS `0x14` est implémenté mais verrouillé par défaut. Il ne devient
accessible qu'avec `DTC_CLEAR_ENABLED=true`, `READ_ONLY=false`, `CAN_TX_ENABLED=true`,
une confirmation spécifique à l'ECU et quatre préconditions. ABS, airbag, BSI,
caméra et direction assistée demandent en plus `SAFETY_ECU_CLEAR_ENABLED=true`.
Le firmware doit annoncer `psa_lab=true`. Le workflow lit la mémoire du seul ECU
avant l'effacement, exige la réponse exacte `0x54`, puis relit immédiatement la
même mémoire et conserve les preuves avant/après dans la trace de session.

Effacer un DTC ne répare pas la panne et ne garantit pas la disparition d'un message
au tableau de bord : tout défaut encore présent sera recréé. Toujours sauvegarder le
rapport avant effacement puis relire immédiatement les DTC.

Les exports texte, CSV, candump ou JSONL de Diagbox peuvent être chargés depuis la
page **Diagnostic véhicule**. L'importeur reconstitue ISO-TP et classe les lectures
et services actifs hors véhicule ; une commande observée reste toujours marquée
non exécutable jusqu'à validation explicite.

Voir [docs/ECU_CATALOG.md](docs/ECU_CATALOG.md) pour les paires d'adresses, les sources
figées et la stratégie de détection.

## Tests

```bash
./scripts/check_project.sh
```

Pour ne lancer que le backend :

```bash
cd backend
./.venv/bin/pytest -p no:cacheprovider -q
```

La fixture globale force un transport virtuel et redirige toutes les données
d'exécution vers un répertoire temporaire. Les tests restent donc isolés du
fichier `.env`, du véhicule et des données locales.

## Important

Ce dépôt est un socle technique, pas un clone complet de l'outil constructeur.
Les adresses, DIDs et procédures spécifiques PSA doivent être acquises légalement,
documentées et testées sur banc avant utilisation.

La stratégie de réutilisation des projets existants et la feuille de route sont
décrites dans [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

---

# V0.4 — pile de diagnostic standard

- remplacement du parseur ISO-TP minimal par `python-can-isotp` ;
- utilisation de `udsoncan` pour les requêtes, NRC et délais UDS ;
- réassemblage réel des réponses multi-trames ;
- inventaire des DIDs d'identification par ECU ;
- endpoint de lecture DID unitaire avec journalisation ;
- simulateur ECU ISO-TP multi-trame ;
- passerelle ESP32 active optionnelle et firmware passif par défaut ;
- garde-fous distincts `CAN_TX_ENABLED` et `READ_ONLY`.


---

# V0.5 — OpenDiag Learn : découverte comportementale

Le laboratoire peut maintenant chercher des correspondances sans connaître à
l'avance les identifiants PSA : il enregistre le bus en lecture seule, place des
marqueurs au moment d'une action, puis compare hors ligne les fenêtres avant et
après chaque marqueur répété.

## Enrichissement opendbc PSA

Le post-traitement charge également la base MIT
[`commaai/opendbc`](https://github.com/commaai/opendbc) :

- DBC `psa_aee2010_r3` figé à la révision
  `a0febba355168a5cb6168b535144c8c41a5ce323` ;
- 107 messages et 432 signaux disponibles ;
- décodage avec `cantools`, sans importer le code d'actionnement openpilot ;
- rapprochement automatique entre marqueurs et signaux DBC décodés ;
- inventaire CAN enrichi avec le nom du message et ses signaux connus ;
- provenance, licence et révision exposées dans l'interface et l'API.

Le port PSA amont documente la Peugeot 208 2019–2025, pas la 308 T9 2018.
Les noms opendbc restent donc marqués comme externes et non validés tant qu'une
capture répétée sur la 308 ne confirme pas leur comportement.
Le nom `r3` désigne ici la provenance du catalogue externe, pas l'architecture
attribuée à la voiture : les captures locales de `0x3F2` sont compatibles avec
la variante AEE2010 R2/EVO à commande de couple et CVM G2.

La copie amont et son attribution se trouvent dans
`database/psa/dbc/opendbc/`. Elle est utilisée uniquement sur les trames reçues :
activer `OPENDBC_ENABLED=true` ne permet aucune émission CAN.

Pour chaque identifiant CAN, le rapport calcule la fréquence, les DLC observés,
les octets variables, leur entropie et leurs basculements. Les candidats de type
fréquence, octet et bit sont classés avec un score, une confiance et une
justification. Le résultat est sauvegardé à côté de la capture :

```text
data/sessions/learn-<date>-<id>.jsonl
data/sessions/learn-<date>-<id>.correlations.json
```

## Workflow comportemental conseillé

1. Stabiliser le véhicule cinq secondes sans action.
2. Cliquer sur le marqueur `frein_appuye`.
3. Appuyer immédiatement sur le frein et maintenir l'action deux secondes.
4. Relâcher, stabiliser, puis répéter trois fois avec le même marqueur.
5. Arrêter et sauvegarder la capture.
6. Lancer l'analyse hors ligne depuis l'historique.
7. Refaire une seconde session pour confirmer les meilleurs candidats.

Un score élevé indique une corrélation temporelle, pas la signification certaine
du signal. Les feux stop, par exemple, peuvent faire varier simultanément la pédale,
le BSI et la consommation électrique.

## API de corrélation

```text
POST /api/learn/correlate/{session_id}
GET  /api/learn/correlations/{session_id}
GET  /api/learn/opendbc/catalog
```

Le corps facultatif du `POST` accepte `before_ms`, `after_ms`, `min_samples` et
`max_candidates_per_marker`.

---

# V0.3 — OpenDiag Learn

Cette version ajoute une chaîne de reverse engineering assisté, conçue pour analyser
des captures CAN obtenues légalement sur son propre véhicule ou sur un banc.

## Fonctions

- capture passive JSONL depuis ESP32, SocketCAN ou fichiers ;
- marqueurs utilisateur avant/après une opération ;
- import de captures ;
- regroupement des trames par identifiant ;
- détection heuristique de couples requête/réponse ;
- reconnaissance des services UDS courants ;
- calcul des différences entre deux fenêtres temporelles ;
- génération de propositions YAML ;
- validation humaine obligatoire ;
- aucune transmission CAN pendant l'analyse.

## Workflow

```text
1. Démarrer une capture passive.
2. Ajouter le marqueur "avant_lecture_abs".
3. Effectuer une lecture dans un outil autorisé.
4. Ajouter le marqueur "apres_lecture_abs".
5. Arrêter la capture.
6. Lancer l'analyse de la session.
7. Examiner les candidats.
8. Exporter une proposition YAML.
9. Valider manuellement avant ajout à la base.
```

## API Learn

```text
POST /api/learn/capture/start
POST /api/learn/capture/marker
POST /api/learn/capture/gps
POST /api/learn/capture/stop
GET  /api/learn/capture/status
GET  /api/learn/sessions
POST /api/learn/analyze/{session_id}
GET  /api/learn/proposals/{session_id}
POST /api/learn/export/{session_id}
POST /api/learn/correlate/{session_id}
GET  /api/learn/correlations/{session_id}
```

## Limites

L'analyse est heuristique. Une trame détectée comme UDS n'est pas nécessairement une
commande de diagnostic. Toute proposition reste marquée `experimental` jusqu'à
validation sur plusieurs véhicules ou sources fiables.


peux tu : séparer les historiques Peugeot/Fiat par VIN ;
générer et exporter un rapport diagnostic complet ;
ajouter les tests actionneurs confirmés ;
enrichir le catalogue de DIDs et DTC constructeur ;
éventuellement implémenter une passerelle compatible Diagbox — notre ESP32 n’est pas encore un émulateur de VCI Diagbox.
