# Diagnostic PSA avancé

Ce mode reprend les éléments utiles publiquement documentés par les projets
[arduino-psa-diag](https://github.com/ludwig-v/arduino-psa-diag),
[PSA seed/key algorithm](https://github.com/ludwig-v/psa-seedkey-algorithm) et
[PSA-Arduino-NAC-RCC](https://github.com/dragouf/PSA-Arduino-NAC-RCC), tout en
conservant la pile ISO-TP et le protocole ESP32 natifs d'OpenDiag.

## Fonctions

- sélection des ECU du profil Peugeot 308 T9 ;
- lecture brute de n'importe quel DID via le service UDS `0x22` ;
- calcul seed/key local, sans émission CAN ;
- accès sécurité de configuration `0x27/03-04`, désactivé par défaut ;
- tests NAC connus : écran noir/restauration et affichage caméra ;
- arrêt automatique des commandes temporaires en trois secondes maximum ;
- deadman ESP32 autonome à 3,5 s, avec nouvelles tentatives d'arrêt si le PC
  disparaît ou si la première émission échoue ;
- trace JSONL complète de chaque échange.

Il n'existe aucun formulaire permettant d'envoyer une trame ou un payload UDS
libre. Les payloads NAC sont comparés à une allowlist exacte dans le backend,
le transport et le firmware.

## Profils firmware

Le profil de lecture habituel reste recommandé pour les scans ECU/DTC et DID :

```bash
pio run -e esp32-tja1050-serial-diagnostic -t upload
```

Le profil expérimental est séparé :

```bash
pio run -e esp32-tja1050-serial-psa-lab -t upload
```

Son `hello` annonce `psa_lab=true` et `tx_policy=psa_lab_named_actions`. Le
backend refuse toute action si cette capacité n'est pas annoncée.

## Verrous backend

Configuration sûre par défaut :

```dotenv
PSA_ADVANCED_ENABLED=true
PSA_SECURITY_ACCESS_ENABLED=false
PSA_ACTUATOR_ENABLED=false
PSA_ACTUATOR_MAX_DURATION_MS=3000
READ_ONLY=true
```

Pour un essai actionneur volontaire en atelier, les trois autorisations
suivantes sont nécessaires :

```dotenv
CAN_TX_ENABLED=true
READ_ONLY=false
PSA_ACTUATOR_ENABLED=true
```

`PSA_SECURITY_ACCESS_ENABLED=true` est indépendant et n'est nécessaire que pour
l'échange seed/key réel. Le firmware bloque toujours `0x2E`, `0x31`, `0x34`,
`0x36`, `0x37`, l'effacement DTC et toute autre commande non listée.

## Câblage

La documentation d'`arduino-psa-diag` place le CAN diagnostic des architectures
AEE2004/AEE2010 sur l'OBD `3/8`. Le CAN OBD-II normalisé peut être présenté sur
`6/14` selon l'interface et le câblage. Le profil T9 conserve donc les deux
notions séparées : diagnostic constructeur sur `3/8`, OBD-II moteur sur `6/14`.

- ne jamais relier `6/14` et `3/8` entre eux ;
- ne pas ajouter de résistance 120 Ω sur un véhicule déjà terminé ;
- utiliser un transceiver CAN automobile et une masse commune ;
- véhicule immobilisé, moteur arrêté, batterie stabilisée ;
- arrêter et sauvegarder toute capture avant une session diagnostic active.

Deux montages sont possibles :

1. Un seul contrôleur CAN : un commutateur bipolaire sélectionne ensemble
   `CAN-H 6 ↔ 3` et `CAN-L 14 ↔ 8`. Il ne doit exister aucune position qui
   ponte les deux réseaux. C'est le montage le plus simple pour alterner entre
   capture roulante/OBD-II et diagnostic constructeur.
2. Deux réseaux simultanés : le contrôleur TWAI interne de l'ESP32 pilote un
   transceiver et un second contrôleur CAN externe (par exemple SPI) pilote le
   second transceiver. Deux TJA branchés en parallèle sur les mêmes lignes
   TX/RX de l'ESP32 ne constituent pas deux interfaces CAN indépendantes.

Le montage implémenté utilise précisément la seconde solution : TWAI/TJA sur
OBD `6/14` en écoute seule, et MCP2515 quartz 16 MHz sur OBD `3/8` pour les
requêtes diagnostic. SPI utilise `18/19/23`, CS `27`; INT `26` est optionnel. Le firmware
`esp32-dual-can-16mhz-serial-diagnostic` donne toujours la priorité de vidage à
TWAI, puis traite le MCP2515. Le backend mutualise la connexion USB : le direct
et l'enregistrement continuent pendant un inventaire ECU ou une lecture DTC.

Dans les deux cas, `3` est le CAN-H diagnostic PSA et `8` son CAN-L. Les
broches `5/4` mentionnées par le firmware sont les GPIO TX/RX entre l'ESP32 et
le transceiver ; elles ne correspondent pas aux numéros de la prise OBD.

## Clignotants BSI

La trame `0x452` et son champ `TURN_SIGNAL_STATUS` décrivent un état diffusé par
le BSI ; ce n'est pas une commande d'actionneur. Les actions clignotant gauche,
droit et warning sont donc visibles dans le catalogue mais marquées
« commande à identifier ». Elles resteront bloquées jusqu'à obtention d'une
séquence UDS BSI confirmée par une source ou une capture contrôlée.
