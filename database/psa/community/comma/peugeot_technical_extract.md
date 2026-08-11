# Extraction technique PSA AEE2010 R3 — communauté comma.ai

Date d'extraction : 2026-08-10  
Véhicule local : Peugeot 308 II T9 2018 — VIN `VF3LPHNYWJS141966`  
Source : export Discord `peugeot.json`, 943 messages du 2022-02-15 au 2026-08-03

## Objet et limites

Ce document transforme la discussion communautaire en données utilisables pour le diagnostic : identifiant CAN, bus, émetteur, destinataire, signaux, fonction, confiance et source. Il croise les 943 messages avec le DBC AEE2010 R3, l'implémentation OpenDBC et les captures locales de la 308.

Il s'agit d'une documentation **de réception et de diagnostic**. Elle ne valide ni l'injection CAN, ni les checksums de sécurité, ni le télécodage d'un organe de direction ou de freinage. Les faits observés sur la 308 sont séparés des résultats obtenus sur d'autres PSA et des hypothèses communautaires.

## Échelle de confiance

| Niveau | Signification |
|---|---|
| `vehicle_confirmed` | Mesuré ou reproduit sur la 308 locale dans plusieurs captures/tests. |
| `vehicle_diagnostic` | Observé sur la 308, utile au diagnostic, sans validation dynamique complète. |
| `upstream_confirmed` | Présent dans OpenDBC ou une implémentation primaire fusionnée, mais pas forcément activé sur cette 308. |
| `community_confirmed` | Plusieurs essais communautaires concordants ou résultat fonctionnel documenté. |
| `community_report` | Information technique attribuable à un message, non reproduite localement. |
| `hypothesis` | Supposition explicite ou interprétation à tester. |
| `not_observed` | Trame recherchée mais absente du périmètre de capture local actuel. |

## Résultat immédiat pour la 308

1. `0x3F2` est bien présente : 128 357 trames dans 43 sessions, DLC 8, période médiane 50,007 ms (~20 Hz).
2. Le champ `STATUS` n'atteint jamais `4 = Active`. Répartition locale : `2=Selected` 108 045, `5=Defect` 7 609, `0=Unavailable` 5 749, `1=Unselected` 5 719, `3=Authorized` 1 235, `4=Active` 0.
3. `SET_ANGLE` reste à 0 et `TORQUE_FACTOR` reste à 0. Ce résultat est cohérent avec l'absence d'état actif et **ne permet pas** de conclure à une commande par couple.
4. Les DTC caméra `B1004` et `B117F` sont devenus actifs (`0x89`) dans le scan du 2026-08-07 à 10:29, après avoir été historiques (`0x08`) à 10:03. Le BSI reflète les mêmes défauts (`0x09`).
5. `0x305` est abondante et cohérente avec l'angle volant réel : 612 725 trames, 40 sessions, période médiane 9,989 ms (~100 Hz), angle observé -536,9° à +541,1°.
6. `0x452` est présente à ~20 Hz, mais les champs de régulation longitudinale, consigne et activation ACC restent inactifs dans les captures étudiées.
7. `0x50E` est présente à ~10 Hz. Le sélecteur `OFF / RVV / LVV`, la demande d'activation RVV et la consigne ont été corrélés sur les essais dédiés. La valeur de consigne 255 correspond à l'état inactif/indisponible observé.
8. `0x2B6` et `0x2F6` n'ont jamais été observées dans les 337 sessions rattachées au VIN inspectées. Cela signifie « absentes du bus capturé », pas « absentes du véhicule ».
9. `0x412` contient `DriverDoorOpen` sur l'octet 6 masque `0x08`; les deux états ont été observés. `ParkingBrakeActive` est défini sur l'octet 0 masque `0x08`, mais aucune activation locale n'a encore été capturée.
10. `0x572` contient `DriverSeatbeltState` sur les bits 7–6 du premier octet. Sept sessions montrent des transitions; l'essai le plus propre valide `1 = débouclée` et `2 = bouclée`.

### Conclusion diagnostic CVM

La chaîne la plus probable est : la CVM fournit le modèle de voie au BSI, le BSI produit la commande `0x3F2` vers l'EPS, mais la fonction n'atteint jamais l'état actif et signale régulièrement `Defect`. Avec `B1004` et `B117F` actifs côté caméra et reflétés par le BSI, la panne caméra est une explication forte du comportement observé. L'identification exacte `CVM2` ou `CVM3` n'est toutefois pas prouvée par l'adresse UDS ou les DTC actuels.

## Architecture reconstruite

```text
CVM / calculateur 7573
  CAN HS1 + CAN ADAS + CAN HS2
       │ modèle véhicule, lacet, courbure/voies
       ▼
BSI / passerelle maître
  filtre, transforme et distribue les messages
       │ 0x3F2 commande LKA + état
       │ 0x305 information direction (rôle rapporté)
       ▼
EPS / calculateur 7126 — CAN HS1

ARTIV / radar
       │ 0x2B6 dynamique longitudinale
       │ 0x2F6 cible, alertes et AEB
       ▼
BSI + calculateur moteur + calculateur de freinage
```

La formulation initiale « `0x3F2` serait BSI → EPS » était une hypothèse d'incognitojam. Elle est ensuite renforcée par elkoled : `0x3F2 = control`, `0x305 = information` parmi les messages BSI → EPS. L'architecture OpenDBC fusionnée décrit elle aussi la passerelle comme l'émetteur des messages EPS. Le sens fonctionnel est donc de confiance élevée, même si l'émetteur du vieux DBC était parfois laissé à `XXX`.

### Répartition des bus du harness communautaire

| Bus panda | Réseau annoncé | Éléments utiles |
|---|---|---|
| CAN0 | BSI1 / passerelle | Point d'interception côté gateway. |
| CAN1 | CAN HS2 | Régulation/ADAS selon équipement. |
| CAN2 | CAN HS1 | EPS et trames dynamiques; `0x348` et `0x3CD` n'étaient vus que sur CAN2 lors du test cité. |

Le connecteur décrit est le connecteur BSI `EP` 60 voies. Une mesure d'environ 60 Ω entre les lignes CAN est rapportée sur CAN2, broches 13 et 15, après correction du câblage/terminaison. Ces numéros proviennent du harness communautaire et doivent être contrôlés sur le schéma correspondant exactement au VIN avant toute connexion.

## Carte CAN synthétique

| CAN ID | Bus / chemin probable | Émetteur | Destinataire(s) | Fonction | État local | Confiance |
|---|---|---|---|---|---|---|
| `0x305` | HS1 / chaîne EPS | EPS ou distribution BSI selon variante | BSI / consommateurs direction | Angle volant réel, vitesse de rotation, compteur, checksum | 612 725 trames; angle et sens validés | `vehicle_confirmed` pour les signaux; sens exact à préciser |
| `0x3F2` | HS1, BSI → EPS | BSI/gateway | EPS 7126 | Commande de maintien de voie, état LKA/LPA, consigne de colonne | 128 357 trames; jamais Active; Defect présent | `vehicle_diagnostic` + `upstream_confirmed` |
| `0x452` | HS2/ADAS, diffusé par BSI | BSI | ARTIV, moteur, freinage, autres | Type régulation, consigne, demandes RVV/ACC, temps inter-véhicule | 128 273 trames; fonctions ACC inactives | `upstream_confirmed`, présence locale confirmée |
| `0x50E` | BSI → ECU moteur | BSI | ECU moteur | Ordres régulateur classique; mode, activation et consigne | 64 285 trames; mode/activation/consigne validés | `vehicle_confirmed` |
| `0x412` | Données carrosserie BSI | BSI | Combiné et consommateurs habitacle | Porte conducteur, frein de stationnement, portes et frein principal | 170 566 trames; porte validée, frein de stationnement actif non observé | `vehicle_confirmed` porte; `upstream_confirmed` frein stationnement |
| `0x572` | Données de retenue/habitacle | BSI | Combiné et consommateurs retenue | États des ceintures conducteur/passager | 86 396 trames; conducteur 1/2 validé, passager constant | `vehicle_confirmed` conducteur |
| `0x2B6` | HS2/ADAS | ARTIV/radar | moteur, freinage, BSI, CMF | Demande de décélération et couple longitudinal ACC | Non observée sur le bus local | `upstream_confirmed` + `not_observed` |
| `0x2F6` | HS2/ADAS | ARTIV/radar | BSI, moteur, freinage, CMF | Cible, distance, alertes collision, AEB, état ACC | Non observée sur le bus local | `upstream_confirmed` + `not_observed` |

## Détail `0x3F2` — `LANE_KEEP_ASSIST`

Longueur 8 octets, périodicité locale ~50 ms. Le DBC communautaire/OpenDBC contient les champs suivants :

| Signal | Position DBC | Unité / enum | Interprétation | Validation 308 |
|---|---:|---|---|---|
| `DRIVE` | `6|1@0+` | booléen | Requête liée à la disponibilité/charge de la commande | Toujours 0 localement; rôle non validé |
| `COUNTER` | `11|4@0+` | 0..15 | Compteur de trame | Toujours 0 dans le périmètre local |
| `CHECKSUM` | `15|4@0+` | brut | Checksum 4 bits; algorithme communautaire apparenté Honda avec init dépendant de l'index | Toujours 0 localement; émission non validée |
| `unknown2` | `23|8@0+` | brut | Champ non nommé | 0..100 observé |
| `TORQUE` | `31|11@0-` | brut signé | Champ historique nommé couple; rôle/échelle à revalider | -7..60 observé, majoritairement 0; **ne pas interpréter en N·m** |
| `LANE_DEPARTURE` | `33|2@0+` | 0 aucun, 1 droite, 2 gauche | Alerte de franchissement | Décodé dans le replay |
| `STATUS` | `36|3@0+` | 0..7 | 0 indisponible, 1 non sélectionné, 2 sélectionné, 3 autorisé, 4 actif, 5 défaut, 6 collision, 7 réservé | Très utile : état 4 absent, état 5 présent |
| `LXA_ACTIVATION` | `40|1@0+` | 0 LKA, 1 LPA | Sélecteur de fonction, **pas** indicateur d'activité | Sémantique corrigée dans le projet |
| `TORQUE_FACTOR` | `47|7@0+` | brut 0..127 | Facteur de limitation; une ancienne définition utilisait un facteur 0,01 | 0 localement; échelle physique non validée |
| `SET_ANGLE` | `55|14@0-` | 0,1° | Consigne d'angle de colonne | 0 localement car aucun état Active observé |
| `unknown4` | `57|1@0+` | booléen | Inconnu | Non utilisé |

OpenDBC construit actuellement une commande d'angle avec une séquence d'états `2 → 3 → 4`, puis envoie `SET_ANGLE` et un facteur de couple. Cette implémentation confirme le format angle de la variante supportée par l'amont, mais ne prouve pas que toutes les 308/CVM utilisent cette variante.

## Détail `0x305` — information direction

| Signal | Position DBC | Échelle | Résultat local |
|---|---:|---:|---|
| `ANGLE` | `7|16@0-` signé | 0,1° | -536,9° à +541,1°, validé |
| `RATE` | `23|8@0+` | 1°/s | 0..196, magnitude validée |
| `RATE_SIGN` | `31|1@0+` | 0 positif, 1 négatif local | Sens validé |
| `COUNTER` | `35|4@0+` | 0..15 | Toute la plage observée |
| `CHECKSUM` | `39|4@0+` | 0..15 | Toute la plage observée |
| `RATE_ALT` | `47|8@0+` | brut | Copie/variante à préciser |

`0x305` doit servir de mesure réelle pour comparer `SET_ANGLE` de `0x3F2` lors d'un futur essai avec une caméra saine. Il ne faut pas confondre angle réel et consigne.

## Détail `0x452` — commandes conducteur et ACC

Émetteur DBC : BSI. Récepteurs : CMF, ARTIV, calculateur moteur et calculateur de freinage.

| Signal | Position | Fonction |
|---|---:|---|
| `LONGITUDINAL_REGULATION_TYPE` | `1|2@0+` | 0 désactivé, puis LVV, RVV ou ACC selon enum à confirmer |
| `TURN_SIGNAL_STATUS` | `5|2@0+` | 0 arrêt, 1 droite, 2 gauche, 3 détresse |
| `FRONT_WIPER_STATUS` | `7|2@0+` | Arrêt, balayage unique, lent, rapide |
| `SPEED_SETPOINT` | `15|8@0+` | Consigne limiteur/régulateur en km/h |
| `CHECKSUM_CONS_RVV_LVV2` | `17|2@0+` | Checksum de la consigne |
| `BRAKE_ONLY_CMD_BSI` | `18|1@0+` | Demande de freinage BSI |
| `LVV_ACTIVATION_REQ` | `22|1@0+` | Demande d'activation limiteur |
| `RVV_ACC_ACTIVATION_REQ` | `23|1@0+` | Demande d'activation régulateur/ACC |
| `ARC_HABIT_SENSITIVITY` | `26|3@0+` | Sensibilité habituelle d'alerte collision |
| `ARC_HABIT_ACTIVATION_REQ` | `27|1@0+` | Activation habituelle ARC |
| `COUNTER` | `31|4@0+` | Compteur BSI |
| `FRONT_WASH_STATUS` | `32|1@0+` | Lavage/balayage avant; nuance non confirmée |
| `FORCE_ACTIVATION_HAB_CMD` | `33|1@0+` | Activation forcée freinage auto/habituel |
| `INTER_VEHICLE_TIME_SETPOINT` | `39|6@0+`, 0,1 s | Temps inter-véhicule demandé |
| `CHECKSUM` | `43|4@0+` | Checksum de trame |
| `COCKPIT_GO_ACC_REQUEST` | `45|1@0+` | Inconnu; possiblement Stop & Go, non confirmé |
| `ACC_PROGRAM_MODE` | `47|2@0+` | Programme ACC confort/sport/éco selon source |

Sur la 308 locale, les champs utiles à l'ACC sont restés à zéro dans les captures agrégées. Les clignotants évoluent 0..3 et `ARC_HABIT_SENSITIVITY` vaut 3. L'absence d'activité est compatible avec une voiture sans chaîne ARTIV/ACC active sur le bus observé.

## Détail `0x50E` — régulateur classique

Le message `Dat_CLIM`, malgré son nom historique, est émis par le BSI et contient aussi les ordres de régulateur classique vers l'ECU.

| Signal utile | Position | Fonction / observation |
|---|---:|---|
| `P219_Com_xPrpReqRaw` | `48|8@1+` | Consigne observée en km/h; 255 inactif/indisponible |
| `P231_Com_ctBSIFrm` | `56|4@1+` | Compteur BSI |
| `P222_Typ_PrpCtl_Req` | `60|1@1+` | Type de requête; enum à confirmer |
| `P221_Speed_setPoint_Typ` / `TYPE_REGUL_LONGI` | `61|2@1+` | 0 OFF, 1 RVV/régulateur, 2 LVV/limiteur, 3 réservé/ACC selon variante |
| `DDE_ACTIVATION_RVV_ACC` | bit 7 du dernier octet (`63|1`) | Demande d'activation RVV; 1 pendant la régulation active |
| `P232_Com_stXVVChkSum` | `4|2@1+` | Checksum XVV |

Statistiques locales : 64 285 trames dans 42 sessions, DLC 8, période médiane 100,001 ms. `P219` prend 49 valeurs distinctes de 37 à 255; 255 domine hors régulation. La consigne a été confirmée sur cinq engagements dans quatre essais. Dans les 337 sessions rattachées au VIN, les valeurs du dernier octet confirment notamment les familles `0x00` (OFF), `0x20` (RVV sélectionné), `0x40` (LVV sélectionné) et `0xA0` (RVV actif).

### Commandes du commodo visibles dans le replay

| Commande affichée | Méthode | Validation locale |
|---|---|---|
| `ON` | Lecture directe du mode `TYPE_REGUL_LONGI = 1` | Bascule `ON → OFF → LVV → OFF → ON` observée dans l'essai `learn-20260805T065418Z-fca10a57` |
| `SET+` | Effet déduit d'une hausse de la consigne pendant l'activation RVV | +1 km/h à 77,9 s dans `learn-20260805T155300Z-757befbc`; reproduit dans deux autres essais |
| `SET−` | Effet déduit d'une baisse de la consigne pendant l'activation RVV | −1 km/h à 87,1 s dans la même session; reproduit dans un autre essai |
| `CANCEL` | Front actif → inactif, mode RVV conservé, sans frein et sans état XVV de coupure par frein | 44,1 s dans la session principale; autre occurrence à 35,3 s |
| `RESUME` | Réengagement après un `CANCEL` dans la même session | Candidat cohérent à 68,7 s; aucun bit de contact électrique dédié n'a été isolé |

`ON` et `DDE_ACTIVATION_RVV_ACC` sont des lectures directes de la trame. `SET+`, `SET−`, `CANCEL` et surtout `RESUME` sont des événements reconstruits à partir de leurs effets véhicule. Ils sont destinés au diagnostic passif et ne constituent pas une définition de trame d'injection.

## Compléments habitacle `0x412` et `0x572`

Le fork [`cristianku/openpilot`](https://github.com/cristianku/openpilot) ne contient aucun commit propre par rapport à son amont et référence `commaai/opendbc` comme sous-module au commit `58b89559ede390a9a4b389f2276ab3863a3ecc52`. Cette révision confirme les positions ci-dessous. Au 2026-08-10, le fork était 245 commits derrière `commaai/openpilot`; il sert donc ici de confirmation historique, pas de source plus récente.

| CAN ID | Signal DBC T9 | Position | Résultat local |
|---|---|---:|---|
| `0x412` | `DriverDoorOpen` | `51|1@0+`, octet 6 masque `0x08` | 168 223 trames fermées, 2 343 ouvertes; transitions dans 5 sessions |
| `0x412` | `ParkingBrakeActive` | `3|1@0+`, octet 0 masque `0x08` | Position source-confirmée, mais 0 état actif sur 170 566 trames de 50 sessions; activation véhicule non validée |
| `0x572` | `DriverSeatbeltState` | `7|2@0+`, octet 0 bits 7–6 | 12 172 états `1`, 74 224 états `2`; transitions dans 7 sessions |

L'essai le plus propre pour la ceinture est `learn-20260805T154951Z-57acfc99` : véhicule à 0 km/h, porte conducteur fermée et bit de frein de stationnement constant, la séquence est `2 → 1 → 2 → 1 → 2`. Les autres captures routières montrent généralement `1 → 2` avant le départ et `2 → 1` après l'arrêt. L'enum retenu est donc `1 = débouclée`, `2 = bouclée`; `0` et `3` restent réservés/inconnus. Le champ passager est resté à `1` dans les 86 396 trames inspectées et n'est pas déclaré validé dynamiquement.

## Détail `0x2B6` — dynamique longitudinale ARTIV

Nom DBC : `HS2_DYN1_MDD_ETAT_2B6`, émetteur ARTIV. Cette trame n'est pas présente dans les captures locales étudiées.

| Signal | Position | Échelle / fonction |
|---|---:|---|
| `MDD_DESIRED_DECELERATION` | `7|8@0+` | 0,05 m/s², offset -10,65 |
| `MIN_TIME_FOR_DESIRED_GEAR` | `15|6@0+` | 0,1 s |
| `POTENTIAL_WHEEL_TORQUE_REQUEST` | `9|2@0+` | Type de requête de couple potentiel |
| `GMP_POTENTIAL_WHEEL_TORQUE` | `23|12@0+` | facteur 4, offset -4000 N·m |
| `ACC_STATUS` | `27|4@0+` | État ACC |
| `GMP_WHEEL_TORQUE` | `39|14@0+` | offset -4000 N·m |
| `WHEEL_TORQUE_REQUEST` | `41|2@0+` | Type de demande couple roue |
| `AUTO_BRAKING_STATUS` | `50|3@0+` | État freinage automatique |
| `MDD_DECEL_TYPE` | `52|2@0+` | Type de décélération |
| `MDD_DECEL_CONTROL_REQ` | `53|1@0+` | Demande de contrôle décélération |
| `GEAR_TYPE` | `54|1@0+` | Type de rapport |
| `PREFILL_REQUEST` | `55|1@0+` | Préremplissage freinage |
| `DYN_ACC_CHECKSUM` | `59|4@0+` | Checksum 4 bits |
| `DYN_ACC_PROCESS_COUNTER` | `63|4@0+` | Compteur 4 bits |

## Détail `0x2F6` — cible, ARC et AEB

Nom DBC : `HS2_DYN_MDD_ETAT_2F6`, émetteur ARTIV. Cette trame n'est pas présente dans les captures locales étudiées.

| Signal | Position | Échelle / fonction |
|---|---:|---|
| `TARGET_DETECTED` | `0|1@0+` | Cible détectée |
| `REQUEST_TAKEOVER` | `2|2@0+` | Reprise en main demandée |
| `BLIND_SENSOR` | `4|1@0+` | Capteur aveuglé |
| `REQ_*_COLL_ALERT_ARC` | bits 5, 6, 7 | Alertes collision visuelle, sonore, haptique |
| `INTER_VEHICLE_DISTANCE` | `15|10@0+` | 0,25 m |
| `ARC_STATUS` | `19|4@0+` | État alerte risque collision |
| `AUTO_BRAKING_IN_PROGRESS` | `20|1@0+` | Freinage auto en cours |
| `AEB_ENABLED` | `21|1@0+` | AEB activé |
| `DRIVE_AWAY_REQUEST` | `33|1@0+` | Demande de redémarrage |
| `DISPLAY_INTERVEHICLE_TIME` | `39|6@0+` | 0,1 s |
| `MDD_DECEL_CONTROL_REQ` | `42|1@0+` | Demande de décélération |
| `AUTO_BRAKING_STATUS` | `47|3@0+` | État freinage auto |
| `CHECKSUM_TRANSM_DYN_ACC2` | `51|4@0+` | Checksum 4 bits |
| `PROCESS_COUNTER_4B_ACC2` | `55|4@0+` | Compteur 4 bits |
| `TARGET_POSITION` | `63|3@0+` | Position de la cible |

## UDS et identification des calculateurs

### CVM locale

Le scan local identifie une famille `CVM` sur requête `0x74A`, réponse `0x64A`, session active 3. Les alias CVM2/CVM3 partagent des adresses dans la base actuelle : cette paire d'adresses ne permet donc pas de trancher la génération.

DTC actifs au 2026-08-07 10:29 :

| ECU | DTC | Statut | Interprétation base locale |
|---|---|---:|---|
| Caméra multifonction | `B1004` / brut `900496` | `0x89` actif | Défaut caméra vidéo multifonction |
| Caméra multifonction | `B117F` / brut `917F00` | `0x89` actif | Défaut capteur d'image |
| BSI (reflet) | mêmes codes | `0x09` | Défaut présent/reçu dans la chaîne véhicule |

Un balayage DID du 2026-08-06 n'a répondu qu'à `0x2100` avec `A840`. Cette valeur seule n'est pas suffisante pour identifier matériel, logiciel ou génération de CVM.

### Adresses rapportées par la communauté

| Adresse requête | Réponse / offset | DID testés | Remarque |
|---|---|---|---|
| `0x6B5` | `rxoffset -0x20` | `F180`, `F186`, `F18B`, `F18C` | Réponses version/date/série rapportées |
| `0x6A6` | `rxoffset -0x20` | mêmes DID | Réponses rapportées |
| `0x6B4` | `rxoffset -0x20` | précédents + `F193`, `F195` | Versions fournisseur matériel/logiciel rapportées |
| Radar, attribution incertaine | `0x6B6 ↔ 0x696` | présence UDS | Le sens requête/réponse a été corrigé puis rediscuté; à vérifier par capture |

Ces adresses proviennent d'autres véhicules et ne doivent pas être interrogées à l'aveugle sur la 308. Pour l'identification locale, privilégier les services de lecture autorisés et les adresses déjà découvertes passivement.

## Matériel 308 étudié par la communauté

Un membre a démonté un module ADAS de Peugeot 308 et publié des photographies. Il identifie :

- processeur vision Mobileye EyeQ3;
- microcontrôleur NXP MPC5643L;
- possibilité de lecture flash via adaptateur, sans résultat firmware exploitable publié dans les messages retenus.

Cela établit qu'un matériel 308 a bien été étudié, mais ne prouve pas que la référence photographiée est identique au calculateur monté sur `VF3LPHNYWJS141966`.

## Longitudinal : résultat communautaire et portée

Elkoled rapporte un contrôle longitudinal fonctionnel sur son véhicule : radar maintenu en session Programming par `Tester Present`, service UDS `0x28 Communication Control` non supporté, puis reproduction des messages CAN radar. Ce résultat confirme l'importance de `0x2B6`/`0x2F6` et de la chaîne ARTIV.

Ce résultat n'est pas transférable directement à la 308 locale : les deux trames radar n'y ont pas été vues, le radar/ACC n'est pas identifié, les checksums et compteurs ne sont pas validés, et la neutralisation d'un radar touche aux fonctions de freinage. Le projet conserve donc cette information comme architecture de référence, sans implémenter l'émission.

## CVM2, CVM3, VSI et commande couple/angle

| Affirmation | Niveau | Décision |
|---|---|---|
| Les branches `psa-torque` ciblent des PSA plus anciennes à commande couple | `community_report` | Confirmé uniquement pour les fingerprints 3008 et C4 SpaceTourer cités |
| CVM2 impliquerait couple, CVM3 angle | `hypothesis` | Message unique « as I know »; ne pas en faire une règle PSA |
| La variante OpenDBC actuelle utilise `SET_ANGLE` sur `0x3F2` | `upstream_confirmed` | Vrai pour les voitures supportées par cette implémentation |
| La 308 locale est CVM3 et commande angle | non prouvé | Le scan dit seulement famille `CVM`; l'angle est nul faute d'état Active |
| Le champ historique `TORQUE` prouve une commande couple | faux à ce stade | Nom et valeurs brutes insuffisants; échelle/fonction non validées |

## AEE2010 R3 et portabilité

La communauté explique que les réseaux PSA se regroupent par génération d'architecture électronique AEE, pas uniquement par plateforme châssis. Le DBC et le harness AEE2010 R3 ont ensuite été intégrés à OpenDBC pour plus de vingt modèles avec passerelle commune.

Cela augmente fortement la réutilisabilité des trames, mais ne garantit pas l'identité de chaque signal entre millésimes, options, calculateurs ou versions de caméra. Les checksums, compteurs, sens des bus et fingerprints restent à confirmer par véhicule.

## Plan d'essais recommandé — diagnostic passif

1. **Identifier exactement la CVM** : lire références matériel/logiciel, date et numéro de série via les DID de lecture déjà découverts, sans écriture ni changement de session inutile.
2. **Capturer une transition de panne** : démarrage à froid, apparition du défaut, extinction/redémarrage, avec marqueurs. Comparer `STATUS`, `unknown2`, les DTC et la tension batterie.
3. **Comparer panne et caméra saine** : après réparation/remplacement/calibration, vérifier si `STATUS` atteint 3 puis 4, si `SET_ANGLE` évolue et s'il suit `0x305` avec un retard cohérent.
4. **Capturer les trois branches du harness** : inventorier `0x2B6`, `0x2F6`, `0x3F2`, `0x305`, `0x452`, `0x50E` séparément sur CAN0/CAN1/CAN2. Ne pas déduire un bus physique d'une capture OBD gateway filtrée.
5. **Tester le commodo avec marqueurs** : OFF/ON, limiteur, régulateur, SET+/SET−, RES, frein, embrayage. Cibler `0x452` et `0x50E`, puis corréler les états moteur `0x208`.
6. **Établir une preuve angle/couple** : uniquement avec assistance réellement active, comparer consigne `0x3F2`, angle réel `0x305` et effort conducteur. L'absence de mouvement en défaut ne tranche rien.
7. **Garder l'émission bloquée** tant que le calcul du checksum, la séquence de compteur, les timeouts EPS, la terminaison CAN et le comportement de repli ne sont pas prouvés sur banc.

## Modifications intégrées au projet

- Le replay backend dérive désormais `lka_active` de `STATUS == 4`.
- `LXA_ACTIVATION` est exposé comme `lka_mode` (`0=LKA`, `1=LPA`).
- `SET_ANGLE` et `TORQUE_FACTOR` sont exposés séparément dans le backend et le front.
- L'écran ADAS affiche état, activité réelle, mode, consigne d'angle et facteur brut.
- Le DBC local contient désormais `0x3F2` et la définition complète de `0x452`, avec commentaires de confiance et limitations.

## Sources Discord principales

Les liens ouvrent le message original dans le canal exporté.

| Sujet | Auteur/date | Message |
|---|---|---|
| Module 308 avec EyeQ3 | platix., 2024-01-30 | [1201692191710249061](https://discord.com/channels/469524606043160576/943275077137498112/1201692191710249061) |
| MPC5643L | platix., 2024-01-30 | [1201703896360439909](https://discord.com/channels/469524606043160576/943275077137498112/1201703896360439909) |
| Régulateur classique dans `0x50E` | kurkpitaine, 2024-03-10 | [1216469720828608594](https://discord.com/channels/469524606043160576/943275077137498112/1216469720828608594) |
| Radar/ACC `0x2B6`, `0x2F6` | kurkpitaine, 2024-03-10 | [1216470323575128105](https://discord.com/channels/469524606043160576/943275077137498112/1216470323575128105) |
| Ordres BSI → ECU sur `0x50E` | kurkpitaine, 2024-03-10 | [1216471510835789845](https://discord.com/channels/469524606043160576/943275077137498112/1216471510835789845) |
| Ajout HS2 et découverte état/consigne | incognitojam, 2024-03-15 | [1218283515053871124](https://discord.com/channels/469524606043160576/943275077137498112/1218283515053871124) |
| Liste complète des signaux `0x452` | kurkpitaine, 2024-03-16 | [1218511775968792678](https://discord.com/channels/469524606043160576/943275077137498112/1218511775968792678) |
| Portée AEE2010 R3 | kurkpitaine, 2024-03-16 | [1218521057913340047](https://discord.com/channels/469524606043160576/943275077137498112/1218521057913340047) |
| Définition communautaire `0x3F2` | incognitojam, 2024-03-16 | [1218583557488902174](https://discord.com/channels/469524606043160576/943275077137498112/1218583557488902174) |
| Checksum LKA trouvé | incognitojam, 2024-03-17 | [1218727188556288091](https://discord.com/channels/469524606043160576/943275077137498112/1218727188556288091) |
| Caméra 7573 → BSI → EPS 7126 | incognitojam, 2024-03-19 | [1219464745997041764](https://discord.com/channels/469524606043160576/943275077137498112/1219464745997041764) |
| Hypothèse initiale BSI → EPS `0x3F2` | incognitojam, 2024-03-19 | [1219465389705007124](https://discord.com/channels/469524606043160576/943275077137498112/1219465389705007124) |
| Confirmation que le BSI, pas la caméra, actionne l'EPS | incognitojam, 2024-04-08 | [1226686403534917694](https://discord.com/channels/469524606043160576/943275077137498112/1226686403534917694) |
| BSI passerelle filtrante/transformatrice | kurkpitaine, 2024-04-13 | [1228589414704480276](https://discord.com/channels/469524606043160576/943275077137498112/1228589414704480276) |
| Implantation calculateurs 7126/7500/7573 | incognitojam, 2024-06-13 | [1250816519194021909](https://discord.com/channels/469524606043160576/943275077137498112/1250816519194021909) |
| `0x3F2` contrôle, `0x305` information | elkoled, 2024-12-11 | [1316377761165607004](https://discord.com/channels/469524606043160576/943275077137498112/1316377761165607004) |
| Mapping CAN0/CAN1/CAN2 du harness | elkoled, 2024-12-11 | [1316533980429815892](https://discord.com/channels/469524606043160576/943275077137498112/1316533980429815892) |
| Exemples de lecture firmware UDS | elkoled, 2025-02-22 | [1342919257062768844](https://discord.com/channels/469524606043160576/943275077137498112/1342919257062768844) |
| Longitudinal fonctionnel | elkoled, 2025-03-19 | [1352016966730252329](https://discord.com/channels/469524606043160576/943275077137498112/1352016966730252329) |
| PyPSADiag/VLUDS ne remplace pas le sniff CAN | sascha_t, 2026-05-25 | [1508447258872381520](https://discord.com/channels/469524606043160576/943275077137498112/1508447258872381520) |
| Branches torque et véhicules explicitement supportés | cristianku, 2026-07-10 | [1525153395328155769](https://discord.com/channels/469524606043160576/943275077137498112/1525153395328155769) |
| Hypothèse CVM2 couple / CVM3 angle | semitop7, 2026-07-15 | [1526836366795604138](https://discord.com/channels/469524606043160576/943275077137498112/1526836366795604138) |

## Sources primaires de code

- [OpenDBC — DBC PSA AEE2010 R3](https://github.com/commaai/opendbc/blob/master/opendbc/dbc/psa_aee2010_r3.dbc)
- [OpenDBC — création des messages PSA](https://github.com/commaai/opendbc/blob/master/opendbc/car/psa/psacan.py)
- [OpenDBC — contrôleur PSA](https://github.com/commaai/opendbc/blob/master/opendbc/car/psa/carcontroller.py)
- [OpenDBC — état véhicule et répartition des bus](https://github.com/commaai/opendbc/blob/master/opendbc/car/psa/carstate.py)
- [PR OpenDBC #2379 — support PSA AEE2010 R3 et harness gateway](https://github.com/commaai/opendbc/pull/2379)
- [PSA Harness — schémas matériels communautaires](https://github.com/lukasloetkolben/OpenpilotHardware/tree/main/PSA-Harness)

## Traçabilité locale

- Export source : `database/psa/community/comma/peugeot.json`
- DBC OpenDBC figé utilisé par le projet : `database/psa/dbc/opendbc/psa_aee2010_r3.dbc`
- DBC spécifique véhicule : `database/psa/dbc/peugeot_308_t9_2018.dbc`
- Scan CVM actif : `data/diagnostics/peugeot/VF3LPHNYWJS141966/scans/scan-20260807T102946956596Z-21700cb0.json`
- Extraction machine : `database/psa/community/comma/peugeot_technical_extract.json`
