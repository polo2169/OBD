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
- import des 50 variantes et 1 022 zones de la révision PyPSADiag référencée ;
- télécodage UDS structuré avec variante explicite, sauvegarde VIN, modification
  multi-paramètres, aperçu binaire, contrôle de concurrence et relecture ;
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

Son `hello` annonce `psa_lab=true`, `telecoding_bounded=true` et
`tx_policy=psa_lab_bounded_writes`. Le
backend refuse toute action si cette capacité n'est pas annoncée.

Les requêtes `0x2E` longues utilisent ISO-TP. Le firmware ne laisse passer un
premier fragment que si le service, le DID constructeur, l'adresse ECU et la
taille maximale sont valides. Il mémorise ensuite l'identifiant, le numéro de
séquence et une échéance de 1,5 s ; un fragment isolé ou hors séquence est
refusé. Le backend applique en plus le catalogue exact et le plan validé.

## Verrous backend

Configuration sûre par défaut :

```dotenv
PSA_ADVANCED_ENABLED=true
PSA_SECURITY_ACCESS_ENABLED=false
PSA_ACTUATOR_ENABLED=false
PSA_ACTUATOR_MAX_DURATION_MS=3000
PSA_ECU_RESET_ENABLED=false
PSA_TELECODING_WRITE_ENABLED=false
READ_ONLY=true
```

Pour un essai actionneur volontaire en atelier, les trois autorisations
suivantes sont nécessaires :

```dotenv
CAN_TX_ENABLED=true
READ_ONLY=false
PSA_ACTUATOR_ENABLED=true
```

`PSA_SECURITY_ACCESS_ENABLED=true` est indépendant. Une écriture de télécodage
exige en plus `PSA_TELECODING_WRITE_ENABLED=true`. Le firmware bloque toujours
`0x31`, `0x34`, `0x36`, `0x37` et toute commande non listée. `0x2E` n'est admis
que pour le workflow borné décrit ci-dessous.

## Workflow de télécodage

L'atelier est visible dans la page de chaque calculateur PSA :

1. choisir explicitement la variante PyPSADiag correspondant à l'identification
   et à l'adressage du calculateur ;
2. lire une zone `0x22` ; OpenDiag crée immédiatement une sauvegarde JSON liée
   au VIN, avec la valeur brute, les champs décodés et une empreinte SHA-256 ;
3. modifier une ou plusieurs options énumérées. Les chaînes brutes, DIDs Fxxx,
   champs inconnus et zones de mauvaise longueur restent en lecture seule ;
4. générer un diff. Le backend recalcule tous les masques, détecte les champs
   qui se chevauchent et produit une empreinte immuable du plan ;
5. confirmer les préconditions, la clé de la variante et la phrase exacte
   `TELECODER <ECU> <DID>` ;
6. dans une seule session, le backend ouvre la session étendue, effectue
   `SecurityAccess`, relit la zone et compare chaque octet à la sauvegarde. Au
   moindre écart, aucune écriture n'est envoyée ;
7. si la zone est inchangée, une unique requête `0x2E` est envoyée, puis `0x22`
   contrôle la valeur complète. Un rapport d'exécution et la trace protocolaire
   sont enregistrés localement.

Les sauvegardes sont stockées sous `TELECODING_BACKUP_DIR` (par défaut
`data/runtime/telecoding`). Elles peuvent être rouvertes depuis l'interface,
mais une ancienne sauvegarde ne contourne jamais le contrôle de concurrence.

API correspondante :

```text
GET  /api/diagnostic/psa/ecus/{ecu}/telecoding/catalog
POST /api/diagnostic/psa/ecus/{ecu}/telecoding/snapshots
GET  /api/diagnostic/psa/telecoding/backups
GET  /api/diagnostic/psa/telecoding/backups/{snapshot_id}
POST /api/diagnostic/psa/telecoding/preview
POST /api/diagnostic/psa/telecoding/execute
```

Les variantes `kwp_hab` et `kwp_is` sont cataloguées pour consultation, mais
restent non exécutables : le transport actif OpenDiag est actuellement UDS sur
ISO-TP. Aucune compatibilité KWP n'est simulée ou revendiquée.

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
https://github.com/lukasloetkolben/OpenpilotHardware/tree/main/PSA-Harness
