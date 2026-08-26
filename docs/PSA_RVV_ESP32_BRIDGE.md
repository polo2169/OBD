# Passerelle PSA RVV avec deux ESP32

## Objet du document

Ce document décrit la passerelle expérimentale construite pour une Peugeot 308 II
T9 équipée du régulateur classique PSA. Elle relie le harnais gateway OBD-C à deux
ESP32 afin de séparer les deux segments CAN, conserver le trafic d'origine et,
sur banc uniquement, remplacer la consigne du RVV dans `0x50E`.

Le projet firmware se trouve dans
[`firmware/esp32-psa-obdc-bridge`](../firmware/esp32-psa-obdc-bridge/README.md).
L'analyse électrique détaillée du PCB est disponible dans
[`PSA_HARNESS_OBDC_AUDIT.md`](PSA_HARNESS_OBDC_AUDIT.md).

## Statut

| Fonction | Statut | Usage autorisé |
|---|---|---|
| Bypass matériel au démarrage | Implémenté | Véhicule après contrôles électriques |
| Pont CAN0 ↔ CAN2 par deux ESP32 | Implémenté | Banc, puis validation progressive |
| Copie `0x3F2` à couple nul | Fenêtre de 400 ms | Validation véhicule encadrée |
| Couple de direction non nul | Compilé séparément | Banc isolé uniquement |
| Remplacement RVV `0x50E` | Compilé séparément | Simulateur CAN ou banc isolé uniquement |
| Commande de frein | Absente | Non disponible |
| ACC / Stop & Go | Absent | Non disponible |
| Intégration `CarController` openpilot | À réaliser | Le protocole JSON est défini |

Le profil RVV n'est pas un firmware routier. Une coupure électrique totale des
ESP32 remet le harnais en bypass et restitue la consigne RVV d'origine. Il faut une
annulation physique indépendante et fail-safe avant d'envisager une activation
longitudinale dans le véhicule.

## RVV et LVV

- `RVV` signifie **Régulation Volontaire de Vitesse**. Le calculateur moteur
  maintient une consigne sans action continue sur l'accélérateur.
- `LVV` signifie **Limitation Volontaire de Vitesse**. Le calculateur limite la
  vitesse demandée par le conducteur ; ce n'est pas un régulateur adaptatif.

Le firmware n'agit que lorsque `CruiseMode=1`, c'est-à-dire en RVV. Le mode LVV
(`CruiseMode=2`) est transmis sans modification et empêche l'armement du contrôle
longitudinal.

## Architecture matérielle

```text
                         UART 2 Mbit/s, CRC-16
BSI / CAN2 ── ESP32 satellite ═════════════════ ESP32 maître ── CAN0 / EPS + CMM
      │                                                               │
      └──────────── liaison matérielle stock commandée par SBU1 ──────┘

SBU1 = 0 V : CAN0 et CAN2 reliés, fonctionnement PSA d'origine
SBU1 = 5 V : segments séparés et terminés, pont logiciel actif
```

Le CMM est le calculateur moteur. Les directions validées sont :

| Trame | Producteur stock | Récepteur | Traitement expérimental |
|---|---|---|---|
| `0x3F2` | BSI / CAN2 | EPS / CAN0 | Remplacement direction uniquement sur CAN0 |
| `0x50E` | BSI / CAN2 | CMM / CAN0 | Remplacement RVV uniquement sur CAN0 |

Le satellite refuse tout retour de `0x3F2` ou `0x50E` vers le BSI. Le maître ne
propose aucune commande CAN arbitraire au PC.

## Raccordement OBD-C

Le connecteur utilise la mécanique USB-C, mais il ne transporte pas de l'USB.
Le `+12 V` véhicule est présent sur les contacts normalement appelés VBUS : ce
câble ne doit jamais être branché à un ordinateur, un téléphone ou un hub USB.

| Fonction | Contact OBD-C | Carte |
|---|---:|---|
| CAN0_H / CAN0_L | A2 / A3 | ESP32 maître |
| CAN2_H / CAN2_L | B2 / B3 | ESP32 satellite |
| SBU1 | A8 | Sortie 5 V de l'étage fail-low, commandée par le maître |
| Alimentation brute | A4, A9, B4, B9 | Fusible puis convertisseur automobile 12 V → 5 V |
| Masse | A1, A12, B1, B12 | Masse commune |

Chaque ESP32 utilise `GPIO5` pour TWAI TX, `GPIO4` pour TWAI RX, `GPIO17` pour
l'UART TX et `GPIO16` pour l'UART RX. Le maître utilise en plus `GPIO32` pour
l'entrée de commande de l'étage SBU1. Le GPIO ne doit jamais alimenter directement
SBU1.

## Trame RVV `0x50E`

La trame stock est reçue à environ 10 Hz. Le firmware ne crée ni cadence ni
compteur : il transforme chaque trame BSI reçue et la transmet immédiatement au
CMM.

| Champ | Position | Politique |
|---|---:|---|
| `XVVChecksum` | octet 0, masque `0x30` | Recalcul autorisé |
| `CruiseSetpointKph` | octet 6 | Modification autorisée entre 40 et 130 km/h |
| `BSIFrameCounter` | octet 7, bits 0..3 | Copie stricte du BSI |
| Type de requête | octet 7, bit 4 | Copie stricte du BSI |
| `CruiseMode` | octet 7, bits 5..6 | Copie stricte ; doit valoir 1 |
| Activation RVV | octet 7, bit 7 | Copie stricte ; doit être active |
| Tous les autres bits | — | Copie stricte du BSI |

Le checksum protège uniquement l'octet de consigne :

```text
XVVChecksum.bit1 = parité binaire du demi-octet haut de la consigne
XVVChecksum.bit0 = parité binaire du demi-octet bas de la consigne
```

La parité vaut le nombre de bits à 1 modulo 2. Cette formule reproduit les
104 190 trames `0x50E` observées dans 55 sessions locales, sans aucun écart. Le
compteur progresse normalement de deux entre deux émissions à 10 Hz et reste
toujours fourni par le BSI.

## Limites de commande

Le profil `psa-obdc-master-bench-rvv` applique les limites suivantes :

| Limite | Valeur |
|---|---:|
| Consigne minimale | 40 km/h |
| Consigne maximale | 130 km/h |
| Variation maximale | 1 km/h toutes les 500 ms |
| Timeout de la commande RVV | 300 ms |
| Timeout du heartbeat général | 300 ms |
| Timeout de la trame stock `0x50E` | 250 ms |
| Durée maximale d'une prise de contrôle de banc | 30 s |

Le RVV doit être sélectionné et déjà actif avant l'isolation. Le frein,
l'accélérateur, la disparition du RVV, le passage en LVV, une donnée de sécurité
périmée, une erreur UART, un bus-off ou un timeout provoquent l'abandon de la
prise de contrôle.

La voiture n'étant pas équipée d'un ACC utilisable par cette passerelle, la
décélération repose sur la réduction de couple et le frein moteur. Le système ne
peut garantir ni la distance de sécurité, ni un freinage d'urgence, ni un arrêt
complet.

## Profils de compilation

| Environnement PlatformIO | Rôle | Couple non nul | RVV modifié | Fenêtre |
|---|---|---:|---:|---:|
| `psa-obdc-master-zero-torque` | Maître véhicule de validation | Non | Non | 400 ms |
| `psa-obdc-satellite` | Satellite CAN2 | Non applicable | Refuse le retour `0x50E` | Pilotée par le maître |
| `psa-obdc-master-bench-torque` | Direction sur banc | Oui, borné | Non | 400 ms |
| `psa-obdc-master-bench-rvv` | RVV sur banc | Non | Oui | 30 s |

Compilation complète :

```bash
cd firmware/esp32-psa-obdc-bridge
platformio run \
  -e psa-obdc-master-zero-torque \
  -e psa-obdc-satellite \
  -e psa-obdc-master-bench-torque \
  -e psa-obdc-master-bench-rvv
```

Test unitaire du contrôleur RVV :

```bash
cd firmware/esp32-psa-obdc-bridge
RVV_TEST_BIN=$(mktemp /tmp/rvv-safety-test.XXXXXX)
c++ -std=c++17 -Wall -Wextra -Werror -Iinclude \
  test/rvv_safety_test.cpp -o "$RVV_TEST_BIN"
"$RVV_TEST_BIN"
```

## Protocole hôte

Le port série du maître fonctionne à 921 600 bit/s. Les commandes sont des objets
JSON terminés par un retour à la ligne.

Séquence d'armement du profil RVV de banc :

1. Envoyer un heartbeat `engaged=true` au moins toutes les 100 ms.
2. Activer le RVV stock sur le banc simulé.
3. Envoyer la cible RVV au moins toutes les 100 ms.
4. Demander la prise de contrôle.
5. Continuer les deux flux périodiques pendant toute la prise de contrôle.
6. Envoyer `enabled=false` ou `psa_takeover=false` pour revenir au bypass.

```json
{"type":"psa_heartbeat","engaged":true}
{"type":"psa_longitudinal","enabled":true,"target_kph":70}
{"type":"psa_takeover","enabled":true}
```

Mise à jour de la cible :

```json
{"type":"psa_longitudinal","enabled":true,"target_kph":65}
```

Arrêt volontaire :

```json
{"type":"psa_longitudinal","enabled":false}
```

Le retour `stats` expose notamment `rvv_stock_mode`, `rvv_stock_active`,
`rvv_stock_setpoint_kph`, `rvv_target_kph`, `rvv_applied_kph`,
`rvv_checksum_failures` et `rvv_controlled_frames`.

## Validation avant toute évolution routière

1. Vérifier les continuités du harnais et l'absence de court-circuit.
2. Mesurer environ 60 Ω sur le réseau complet en bypass.
3. Alimentations coupées, isoler les segments et vérifier environ 120 Ω sur
   chacun d'eux.
4. Utiliser deux réseaux CAN simulés pour tester la perte UART, le reset de chaque
   ESP32, le bus-off et la coupure d'alimentation.
5. Rejouer des trames `0x50E` réelles et vérifier que seuls l'octet 6 et le masque
   `0x30` de l'octet 0 peuvent changer.
6. Valider le pont bit-identique avant toute modification de consigne.
7. Ajouter une entrée matérielle indépendante capable d'annuler le RVV lors d'une
   perte totale de la passerelle.
8. Faire valider cette annulation sur banc, puis sur zone fermée, avant de créer
   un profil autre que `PSA_BENCH_ONLY`.

## Fichiers de référence

- [Firmware et câblage détaillé](../firmware/esp32-psa-obdc-bridge/README.md)
- [Audit du harnais PSA OBD-C](PSA_HARNESS_OBDC_AUDIT.md)
- [DBC Peugeot 308 T9](../database/psa/dbc/peugeot_308_t9_2018.dbc)
- [Extrait technique PSA](../database/psa/community/comma/peugeot_technical_extract.md)
