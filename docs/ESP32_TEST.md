# Premier essai ESP32 — Peugeot 308 T9

## 1. Avant de brancher

- véhicule immobilisé dans un endroit ventilé ;
- ESP32 alimenté par une batterie USB, pas par le PC ;
- transceiver CAN automobile compatible 3,3 V entre l'ESP32 et la prise OBD ;
- masse commune, CAN-H sur OBD 6 et CAN-L sur OBD 14 ;
- aucune connexion directe des GPIO à CAN-H/CAN-L ;
- aucune résistance de terminaison supplémentaire sur le véhicule.

### Montage retenu : ESP32 classique + Waveshare SN65HVD230

1. Dessouder `R2` (120 ohms) du Waveshare avant toute connexion OBD.
2. Relier `3.3V`, `GND`, `CAN_TX/D` et `CAN_RX/R` respectivement à `3V3`, `GND`,
   `GPIO17` et `GPIO16` de l'ESP32.
3. Relier CAN-H à OBD 6, CAN-L à OBD 14 et GND à OBD 5.
4. Ne rien relier à OBD 16.
5. Mettre si possible un cavalier amovible entre GPIO17 et TX/D ; le laisser ouvert
   pendant les premiers essais passifs.
6. Débrancher le câble USB du PC, puis alimenter l'ESP32 avec la batterie USB.

Le Waveshare n'est pas isolé galvaniquement. Le PC communique donc uniquement par
Wi-Fi pendant que l'OBD est connecté.

Avec un module MCP2515/TJA1050, ne pas continuer avant d'avoir :

- identifié le quartz `8.000` ou `16.000` ;
- placé un traducteur de niveaux logique adapté entre le SPI 3,3 V et le module 5 V ;
- vérifié que la terminaison 120 ohms du module est retirée ou désactivée ;
- confirmé que VCC reçoit 5 V régulé, jamais le 12 V de la prise OBD.

### Montage double CAN retenu — deux ESP32 reliées par UART

Le MCP2515 est abandonné. Chaque ESP32 utilise son contrôleur TWAI natif et son
propre transceiver CAN. Une seule ESP32 reste reliée au PC :

| Rôle | CAN | Firmware |
|---|---|---|
| ESP32 principale | OBD 6/14, écoute seule | `esp32-dual-uart-main-diagnostic` |
| ESP32 satellite | OBD 3/8, diagnostic filtré | `esp32-dual-uart-satellite-diagnostic` |

Relier les deux ESP32 en logique 3,3 V, sans convertisseur :

| ESP32 principale | ESP32 satellite |
|---|---|
| GPIO 17 TX | GPIO 16 RX |
| GPIO 16 RX | GPIO 17 TX |
| GND | GND |

Les deux cartes peuvent rester alimentées chacune par leur USB pendant les essais,
mais ne pas relier leurs broches `5V/VIN` entre elles. La liaison UART fonctionne à
2 Mbit/s. Le transceiver de chaque carte utilise `TXD=GPIO5` et `RXD=GPIO4` ; un
TJA1050 5 V exige toujours une adaptation sur RXD vers GPIO4. Un TJA1051 avec VIO
3,3 V ou un transceiver CAN entièrement 3,3 V est préférable. Retirer toute
terminaison 120 ohms ajoutée par les modules.

Ne jamais relier OBD `3/8` à OBD `6/14`. Le firmware de la carte principale place
matériellement son TWAI en écoute seule et ne relaie vers le satellite que les
requêtes diagnostic autorisées.

### Ancien montage double CAN — MCP2515 quartz 16.000

Le transceiver déjà relié au contrôleur TWAI reste sur le CAN véhicule OBD
`6/14`. Il fonctionne en écoute seule et conserve le débit du dashboard. Le
MCP2515 est un second contrôleur indépendant exclusivement relié au CAN
diagnostic PSA OBD `3/8` :

| Signal MCP2515 | Connexion |
|---|---|
| SCK | ESP32 GPIO 18 |
| MISO | ESP32 GPIO 19 via adaptation 5 V → 3,3 V |
| MOSI | ESP32 GPIO 23 via adaptation 3,3 V → 5 V |
| CS | ESP32 GPIO 27 via adaptation 3,3 V → 5 V |
| INT | ESP32 GPIO 26 via adaptation 5 V → 3,3 V |
| CAN-H | OBD 3 |
| CAN-L | OBD 8 |
| GND | masse ESP32 et OBD 5 |
| VCC | 5 V USB régulé |

Le GPIO 5 reste réservé au TX du transceiver TWAI actuel : il ne doit plus être
utilisé comme CS du MCP2515 dans ce montage. Retirer la terminaison 120 ohms du
module et ne jamais ponter OBD `3/8` avec `6/14`.

Avec un transceiver TJA1050 seul, utiliser le firmware TWAI `esp32-readonly` déjà
prévu : GPIO 5 vers TXD, et RXD vers GPIO 4 uniquement au travers d'une adaptation
5 V vers 3,3 V. Alimenter le TJA1050 en 5 V USB régulé, relier les masses, CAN-H à
OBD 6 et CAN-L à OBD 14. Retirer toute terminaison 120 ohms du module.

Pour conserver ce même brochage avec la liaison Wi-Fi, utiliser
`esp32-tja1050-wifi-readonly`. Le profil actif correspondant reste volontairement
séparé : `esp32-tja1050-wifi-active`.

## 2. Choisir le firmware

Pour le montage Waveshare Wi-Fi retenu :

```bash
cd firmware/esp32-gateway
/Users/paul/.platformio/penv/bin/pio run -e esp32-waveshare-wifi-readonly -t upload
```

Après le flash, le moniteur série doit annoncer `firmware=0.7.2-framed-diagnostic-lock`,
`protocol=6`,
`readonly=true`, `tx_pin=17`, `rx_pin=16`, le réseau `OpenDiag-ESP32` et le port
TCP `35000`. L'USB sert ici uniquement à flasher sur l'établi, avant la connexion
au véhicule.

`esp32-readonly` est une écoute passive stricte : capture seulement, aucun scan.
Pour une carte ESP32-S3, le profil équivalent est `esp32-s3-readonly`.

Avec un MCP2515, choisir selon le quartz :

```bash
# Exemple pour un quartz marqué 8.000
/Users/paul/.platformio/penv/bin/pio run -e esp32-mcp2515-8mhz-readonly -t upload
```

Pour le montage recommandé à deux ESP32, flasher chaque carte séparément :

```bash
cd firmware/esp32-gateway
# Carte principale, reliée ensuite au PC
/Users/paul/.platformio/penv/bin/pio run \
  -e esp32-dual-uart-main-diagnostic -t upload

# Seconde carte, satellite OBD 3/8
/Users/paul/.platformio/penv/bin/pio run \
  -e esp32-dual-uart-satellite-diagnostic -t upload
```

Le `hello` de la carte principale doit annoncer `protocol=7`,
`driver=twai+uart-twai`, `dual_can=true`, `live_listen_only=true`,
`live_can_ready=true`, `diagnostic_can_ready=true` et
`satellite_connected=true`. Le PC ne sélectionne que le port USB de la carte
principale.

Pour l'ancien montage double CAN MCP2515 avec le quartz `16.000`, le profil reste
disponible :

```bash
cd firmware/esp32-gateway
/Users/paul/.platformio/penv/bin/pio run \
  -e esp32-dual-can-16mhz-serial-diagnostic -t upload
```

Le `hello` attendu annonce `protocol=7`, `driver=twai+mcp2515`,
`dual_can=true`, `live_can_ready=true`, `diagnostic_can_ready=true`,
`live_listen_only=true`, `oscillator_mhz=16`, `spi_cs_pin=27` et
`spi_hz=8000000`. Ne pas flasher le profil `psa-lab` pour une lecture normale :
il reste réservé aux actions nommées déjà validées et explicitement armées.

Chaque ligne compacte conserve le format `F,...`; le bit `0x40` du champ flags
identifie désormais une trame `diagnostic`. Le backend enregistre `bus: live` ou
`bus: diagnostic`, utilise uniquement `live` pour le dashboard/replay et route
les requêtes UDS uniquement vers le MCP2515.

Les boutons **Capteurs uniquement** et **Scanner le véhicule** doivent envoyer des
requêtes de lecture. Il faut donc flasher `esp32-s3-active`, tout en gardant le backend
en filtre applicatif lecture seule :

```bash
cd firmware/esp32-gateway
/Users/paul/.platformio/penv/bin/pio run -e esp32-active -t upload
```

Pour le montage TJA1050 série sur GPIO 5/4, utiliser de préférence le profil
verrouillé testé sur l'ESP32 classique :

```bash
/Users/paul/.platformio/penv/bin/pio run -e esp32-tja1050-serial-diagnostic -t upload
```

Le `hello` doit alors annoncer `diagnostic_read_only=true`,
`write_services_locked=true` et `tx_policy=read_only_diagnostics`.

Avec le montage Waveshare Wi-Fi, l'équivalent est
`esp32-waveshare-wifi-active`. Ne l'utiliser qu'après validation complète de la
capture passive et remise volontaire du cavalier TX.

Pour une carte ESP32-S3, remplacer l'environnement par `esp32-s3-active`.
Pour un MCP2515, utiliser le profil `esp32-mcp2515-8mhz-active` ou
`esp32-mcp2515-16mhz-active` correspondant au quartz.

## 3. Configurer le backend

Pour une capture passive par Wi-Fi sans carte SD, se connecter au réseau
`OpenDiag-ESP32`, puis régler :

```dotenv
TRANSPORT=esp32_wifi
ESP32_WIFI_HOST=192.168.4.1
ESP32_WIFI_PORT=35000
ESP32_WIFI_RECONNECT_INTERVAL=0.5
CAN_TX_ENABLED=false
READ_ONLY=true
```

Le mot de passe Wi-Fi de développement est `opendiag-safe`. Pour le modifier,
copier `firmware/esp32-gateway/include/secrets.example.hpp` vers `secrets.hpp`,
changer le mot de passe puis reflasher.

Le bloc série suivant ne concerne que les essais USB sur établi :

Copier `.env.example` vers `.env`, trouver le port avec PlatformIO, puis régler :

```dotenv
TRANSPORT=esp32_serial
SERIAL_PORT=/dev/cu.usbserial-0001
SERIAL_BAUD=921600
CAN_TX_ENABLED=true
READ_ONLY=true
READ_DTCS=true
DEBUG_SESSIONS_ENABLED=true
TRACE_CAN_FRAMES=true
ESP32_HANDSHAKE_TIMEOUT=8.0
DTC_CLEAR_ENABLED=false
SAFETY_ECU_CLEAR_ENABLED=false
SESSION_DIR=../data/sessions
SENSOR_OVERRIDES_FILE=../data/sensor_overrides.json
```

Sur Linux, le port ressemble généralement à `/dev/ttyUSB0` ou `/dev/ttyACM0`.
Sur macOS, préférer `/dev/cu.usbserial-…`, `/dev/cu.SLAB_USBtoUART` ou
`/dev/cu.usbmodem…` selon le convertisseur présent.

## 4. Ordre du premier test

1. Contact mis, moteur arrêté.
2. Alimenter l'ESP32 avec la batterie USB, sans câble vers le PC.
3. Connecter le PC au Wi-Fi `OpenDiag-ESP32`.
4. Démarrer le backend et l'interface.
5. Vérifier que l'écran indique `esp32_wifi · 192.168.4.1:35000`, `Lecture seule`
   et `Effacement DTC : Verrouillé`.
6. Ouvrir **Découverte**, démarrer une capture immobile de 30 secondes, puis
   l'arrêter et vérifier que le nombre de trames augmente sans erreur.
7. Vérifier dans la capture l'absence de `gateway_sequence_gap`, de bus-off et de
   `wifi_dropped_messages` non nul.

En USB série, vérifier également les événements `gateway_stats` : `dropped`,
`bus_off`, `rx_error_counter` et `bus_error_count` doivent rester à zéro. L'arrêt
de la capture synchronise le JSONL sur le disque du PC avant l'analyse.

Le profil passif ne permet pas **Capteurs uniquement** ni **Scanner le véhicule** :
ces fonctions émettent nécessairement des requêtes CAN. Elles seront testées plus
tard, avec le cavalier TX remis et une procédure active séparée.

Pour observer régime et débit d'air, le moteur peut ensuite être démarré, véhicule
immobile et dans un endroit ventilé. Ne pas conduire en manipulant l'interface.

## 5. Récupérer le diagnostic de débogage

Chaque opération affiche un identifiant de trace et écrit :

```text
data/sessions/<session_id>.jsonl
```

Le fichier contient les messages `hello`, statistiques TWAI, trames CAN, sessions
ISO-TP, requêtes/réponses UDS ou OBD, NRC, timeouts, durées et rapport décodé. Ne pas
publier une trace brute sans anonymiser le VIN.

## 6. Tester le mode Découverte

Le profil `esp32-waveshare-wifi-readonly` convient au nouveau montage sans carte
SD. Dans l'interface, ouvrir **Découverte** :

1. nommer l'expérience et démarrer la capture ;
2. laisser le bus se stabiliser cinq secondes ;
3. cliquer sur le marqueur, puis faire immédiatement une seule action et la
   maintenir environ deux secondes ;
4. répéter la même action au moins trois fois avec exactement le même nom ;
5. arrêter la capture, puis cliquer sur **Analyser** dans l'historique.

La capture brute reste en JSONL et le post-traitement produit un fichier
`.correlations.json`. Le temps ESP32 original est conservé pour le débogage, mais
les trames et les marqueurs sont alignés avec l'horloge de la machine afin que les
fenêtres avant/après soient comparables.

Lorsque le DBC PSA opendbc reconnaît un identifiant, l'inventaire affiche aussi le
nom du message et l'analyse peut proposer directement un signal nommé. La mention
`opendbc` indique une définition externe à confirmer sur la 308 ; les propositions
octet/bit brutes restent affichées pour permettre la comparaison.

Le mode Découverte n'envoie aucune commande de diagnostic lorsque le firmware
passif strict est utilisé. Une corrélation doit être reproduite sur plusieurs
sessions avant d'être ajoutée comme signal connu.

## 7. À propos de l'effacement

Ne rien effacer pendant ce premier test. L'effacement ne sera envisagé qu'après :

- sauvegarde du rapport initial ;
- identification du calculateur et du défaut ;
- réparation ou vérification de la cause ;
- tension batterie stable ;
- nouvelle lecture immédiatement après l'effacement.
