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

Le profil T9 actuel utilise l'OBD `6/14` pour le réseau CAN observé. La
documentation NAC/RCC citée indique le CAN diagnostic PSA sur `3/8`. Il faut
identifier le réseau réellement accessible sur la voiture avant de déplacer un
fil ou d'ajouter un second transceiver.

- ne jamais relier `6/14` et `3/8` entre eux ;
- ne pas ajouter de résistance 120 Ω sur un véhicule déjà terminé ;
- utiliser un transceiver CAN automobile et une masse commune ;
- véhicule immobilisé, moteur arrêté, batterie stabilisée ;
- arrêter et sauvegarder toute capture avant une session diagnostic active.

## Clignotants BSI

La trame `0x452` et son champ `TURN_SIGNAL_STATUS` décrivent un état diffusé par
le BSI ; ce n'est pas une commande d'actionneur. Les actions clignotant gauche,
droit et warning sont donc visibles dans le catalogue mais marquées
« commande à identifier ». Elles resteront bloquées jusqu'à obtention d'une
séquence UDS BSI confirmée par une source ou une capture contrôlée.
