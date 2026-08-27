# Passerelle PSA OBD-C à deux ESP32

Le guide complet d'architecture, de protocole et de validation se trouve dans
[`docs/PSA_RVV_ESP32_BRIDGE.md`](../../docs/PSA_RVV_ESP32_BRIDGE.md).
La couche d'engagement latéral indépendante est détaillée dans
[`docs/PSA_MADS_T9.md`](../../docs/PSA_MADS_T9.md).

Cette passerelle correspond au harnais présent dans
[`hardware/PSA-Harness`](../../hardware/PSA-Harness/) :

```text
BSI / voiture ── CAN2 ── ESP32 satellite ══ UART CRC ══ ESP32 maître ── CAN0 ── EPS/CMM
                       \____________ SBU1 = 0 : liaison matérielle stock __________/
                                      SBU1 = 1 : deux bus isolés et terminés
```

Le maître est la seule carte autorisée à commander `SBU1` et à émettre la
commande de direction `0x3F2`. Une compilation de banc séparée peut aussi
remplacer la consigne RVV de `0x50E` uniquement vers CAN0/calculateur moteur.
Le satellite refuse explicitement tout retour de `0x3F2` ou `0x50E` vers le BSI.
Il n'existe aucun chemin d'émission CAN arbitraire depuis l'USB.

## État actuel

- bypass matériel au démarrage et après toute faute ;
- échange inter-cartes binaire à 2 Mbit/s, CRC-16, compteur de séquence et
  heartbeat ;
- pont CAN bidirectionnel uniquement pendant l'isolation ;
- surveillance frein, accélérateur, couple conducteur, angle, vitesse, régulateur
  et fraîcheur des trames ;
- machine à états MADS-T9 séparant le latéral du RVV : frein en mode
  désengagement, reprise après effort conducteur et réarmement explicite ;
- autorisation physique active-bas sur GPIO 33, doublée par un pôle matériel en
  série dans la commande `SBU1` ;
- première validation véhicule verrouillée à une copie bit-à-bit d'une trame
  stock `0x3F2` à couple nul, 20 Hz, pendant 400 ms maximum ;
- profil couple non nul compilable seulement avec `PSA_BENCH_ONLY=1` ;
- contrôleur RVV `0x50E` disponible uniquement dans le profil de banc : mode
  RVV déjà actif, consigne 40..130 km/h, variation maximale de 1 km/h toutes les
  500 ms et timeout hôte de 300 ms ;
- checksum de consigne `0x50E` validé sans erreur sur 104 190 trames locales ;
  compteur, activation, mode et tous les autres champs restent copiés du BSI ;
- LVV et `0x452` ne sont jamais modifiés ; aucune commande de frein n'existe.

Ce n'est donc pas encore un calculateur de conduite autonome. openpilot reste sur
le PC/Mac et devra produire les consignes de couple et de vitesse ; les ESP32
assurent le transport CAN et la barrière de sécurité.

## Brochage confirmé du harnais

Les noms `A…/B…` sont ceux du réceptacle OBD-C `J7` dans le schéma fourni.

| Fonction | Broche OBD-C | Destination |
|---|---:|---|
| CAN0_H | A2 | CANH transceiver du maître, côté EPS |
| CAN0_L | A3 | CANL transceiver du maître, côté EPS |
| CAN2_H | B2 | CANH transceiver du satellite, côté voiture/BSI |
| CAN2_L | B3 | CANL transceiver du satellite, côté voiture/BSI |
| SBU1 | A8 | sortie 5 V de l'étage TPS22919-Q1, jamais le GPIO directement |
| +12 V brut | A4, A9, B4, B9 | fusible puis convertisseur 12 V vers 5 V |
| Masse | A1, A12, B1, B12 | masse puissance, CAN, ESP32 et UART commune |
| CAN1_H/L | A11/A10 | passage direct dans le harnais, inutilisé ici |
| SBU2 / CAN3 | B8 / B11-B10 | non câblés dans ce harnais |

Attention : `+12 V brut` est placé sur les contacts normalement appelés VBUS.
Le connecteur est mécaniquement USB-C mais électriquement ce n'est pas de l'USB.
Ne jamais le brancher à un ordinateur, un téléphone ou un hub USB.

## Câblage des deux ESP32

### Maître, CAN0 / EPS

| ESP32 maître | Connexion |
|---|---|
| GPIO 5 | TXD du transceiver CAN0 |
| GPIO 4 | RXD du transceiver CAN0 |
| GPIO 17 | RX GPIO 16 du satellite |
| GPIO 16 | TX GPIO 17 du satellite |
| GPIO 32 | entrée `ON` du TPS22919-Q1 ; pull-down 100 kΩ séparé vers GND |
| GPIO 33 | second pôle de l'interrupteur MADS vers GND ; pull-up 10 kΩ vers 3,3 V |
| 5V / GND | alimentation régulée / masse commune |

Pour `SBU1`, alimenter `IN` du TPS22919-Q1 en 5 V, relier `VOUT` à OBD-C A8,
relier `ON` au GPIO 32 à travers le premier pôle d'un interrupteur DPST, ajouter
100 kΩ de `ON` à GND et 100 nF près de `IN`. Le second pôle relie GPIO 33 à la
masse lorsque MADS est physiquement autorisé ; ajouter 10 kΩ de GPIO 33 à 3,3 V.
`QOD` peut
rester ouvert ici : les deux résistances de 120 Ω du harnais tirent déjà `SBU1`
vers la masse, soit 240 Ω. À 5 V, l'étage fournit environ 20,8 mA. Le GPIO ne doit
pas fournir ce courant lui-même.

### Satellite, CAN2 / voiture

| ESP32 satellite | Connexion |
|---|---|
| GPIO 5 | TXD du transceiver CAN2 |
| GPIO 4 | RXD du transceiver CAN2 |
| GPIO 17 | RX GPIO 16 du maître |
| GPIO 16 | TX GPIO 17 du maître |
| 5V / GND | alimentation régulée / masse commune |

Les transceivers ne doivent pas ajouter de résistance 120 Ω. Le harnais établit
ses propres terminaisons lorsque `SBU1=1`; en bypass, les terminaisons d'origine
du véhicule restent utilisées. Sur un module SN65HVD230 de prototypage, retirer
la résistance embarquée ou ouvrir son cavalier.

## Matériel

La liste détaillée et les variantes prototype/finale sont dans
[`hardware_bom.csv`](hardware_bom.csv). Le minimum pratique est :

- 2 × ESP32-DevKitC V4 / ESP32-WROOM-32E ;
- 2 × interfaces CAN 3,3 V sans terminaison ; TCAN3403-Q1 conseillé pour la
  carte finale, SN65HVD230 seulement pour le banc ;
- 1 × câble OBD-C comma 3/3X, ou câble USB-C 3.1/3.2 Gen 2 réellement
  full-featured ;
- 1 × PCB adaptateur OBD-C sur mesure avec réceptacle GCT USB4115-03-C ; un
  breakout USB-C USB2 classique ne sort ni les paires CAN0/CAN2 ni `SBU1` ;
- 1 × convertisseur 12 V vers 5 V protégé, 1 × fusible temporisé 1 A et son
  porte-fusible ;
- 1 × TPS22919-Q1, 1 × 100 kΩ, 1 × 100 nF pour `SBU1` ;
- 1 × interrupteur DPST à verrouillage et 1 × 10 kΩ pour l'autorisation MADS ;
- fils torsadés CAN, connecteurs verrouillables, boîtier et masse UART commune.

Un Pololu D36V28F5 (5 V / 3,2 A, entrée jusqu'à 50 V) convient à la maquette.
Pour un boîtier destiné à rester dans la voiture, utiliser une alimentation
qualifiée et testée aux transitoires automobiles, par exemple une conception
autour de LM5164-Q1, et des TCAN3403-Q1. Ne pas rouler avec une breadboard ou des
fils Dupont.

## RVV et LVV

`RVV` est le régulateur volontaire de vitesse : le calculateur moteur cherche à
maintenir la consigne. `LVV` est le limiteur volontaire de vitesse : il limite
l'accélération du conducteur mais ne constitue pas un régulateur adaptatif. Le
contrôleur refuse donc tout mode autre que `CruiseMode=1` (RVV) et exige que le
RVV stock soit déjà actif avant l'isolation.

Sur la 308 T9 observée, `0x50E` arrive à environ 10 Hz depuis le BSI. Le firmware
intercepte chaque trame au lieu de créer son propre compteur : seuls l'octet 6
(`CruiseSetpointKph`) et les bits 4..5 de l'octet 0 (`XVVChecksum`) peuvent
changer. La consigne appliquée rejoint la cible par pas de 1 km/h toutes les
500 ms. Frein, accélérateur, désactivation du RVV, mode LVV, trame périmée ou
commande hôte périmée provoquent l'abandon de la prise de contrôle.

### Verrou de sécurité actuel

Le profil RVV est volontairement marqué `PSA_BENCH_ONLY=1`. Une perte logicielle
détectée rétablit immédiatement le bypass, mais une perte électrique totale des
deux ESP32 reconnecterait directement la consigne RVV stock. Comme ce RVV ne
connaît pas le véhicule précédent, une version routière exige d'abord une ligne
d'annulation physique indépendante et fail-safe. Ce profil ne doit être utilisé
que sur un simulateur CAN ou un banc isolé, jamais sur route.

## Compilation

```bash
cd openpilot/firmware/psa-obdc-bridge
platformio run
```

Flasher le maître puis le satellite :

```bash
platformio run -e psa-obdc-master-zero-torque -t upload --upload-port /dev/cu.usbserial-MASTER
platformio run -e psa-obdc-satellite -t upload --upload-port /dev/cu.usbserial-SATELLITE
```

Ne pas flasher `psa-obdc-master-bench-torque` sur une carte reliée au véhicule.
Le même interdit s'applique à `psa-obdc-master-bench-rvv`.

Compilation du contrôleur RVV de banc :

```bash
platformio run -e psa-obdc-master-bench-rvv
```

## Protocole hôte du maître

Le maître restitue les trames du côté voiture avec le format compact existant
`F,timestamp,sequence,id,flags,data`. Les seules commandes JSON acceptées sont :

```json
{"type":"get_status"}
{"type":"psa_heartbeat","engaged":true}
{"type":"psa_mads","enabled":true}
{"type":"psa_torque","raw":0}
{"type":"psa_longitudinal","enabled":true,"target_kph":70}
{"type":"psa_longitudinal","enabled":false}
{"type":"psa_takeover","enabled":true}
{"type":"psa_takeover","enabled":false}
```

`psa_mads` est indépendant de `psa_longitudinal`. Couper le RVV modifié laisse
donc le latéral engagé et transmet à nouveau `0x50E` sans modification. Après un
frein ou une perte de heartbeat, envoyer `psa_mads=false`, puis `true` avant une
nouvelle demande de takeover.

Le heartbeat doit être renouvelé en moins de 300 ms. Pour armer, il faut d'abord
fermer l'interrupteur physique, envoyer les heartbeats, demander MADS puis rester
entre 40 et 90 km/h dans les profils latéraux. Le RVV n'est pas requis.
Une commande `psa_torque`, y compris `raw=0`, doit être rafraîchie en moins de
150 ms avant et pendant la prise de contrôle.
Frein, trame périmée, CRC UART, bus-off ou fin de fenêtre remettent immédiatement
`SBU1` à 0. L'accélérateur et un RVV inactif ne coupent que le longitudinal ; un
effort conducteur met temporairement le couple MADS à zéro.

Dans le profil RVV de banc, envoyer également `psa_longitudinal` au moins toutes
les 300 ms. La première commande `enabled=true` doit précéder `psa_takeover` ;
les commandes suivantes peuvent mettre à jour `target_kph`. Ce profil utilise
une enveloppe simulée de 40..130 km/h et une fenêtre maximale de 30 secondes.

## Ordre de validation

1. Contrôler au multimètre, harnais débranché du véhicule : `SBU1=0` relie CAN0
   à CAN2 et `SBU1=5 V` les sépare.
2. Vérifier environ 60 Ω entre H/L du réseau complet en bypass, puis 120 Ω sur
   chaque segment isolé, alimentations coupées.
3. Alimenter sur table avec une source 12 V limitée à 0,5 A et deux réseaux CAN
   simulés ; tester reset, perte UART et perte d'alimentation.
4. Sur véhicule immobile : bypass uniquement et acquisition passive.
5. Ensuite seulement : fenêtre couple nul de 400 ms. Le couple non nul et le
   longitudinal routier restent bloqués tant que cette étape n'est pas mesurée.
6. Rejouer `0x50E` sur deux réseaux CAN de banc et vérifier à l'analyseur que
   seuls l'octet 6 et les bits de checksum autorisés changent.
7. Ajouter et tester une annulation RVV matérielle indépendante avant de créer
   un quelconque profil longitudinal destiné au véhicule.
