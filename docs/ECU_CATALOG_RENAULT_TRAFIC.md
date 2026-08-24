# Catalogue ECU — Renault Trafic

## Trafic II phase 1 (X83, 2001–2005)

Le véhicule validé en août 2026 expose bien un réseau multiplexé CAN
11 bits à `250 kbit/s` sur les broches OBD 6/14. Les requêtes EOBD moteur
physiques (`0x7E0`) et fonctionnelles (`0x7DF`) ont cependant été émises
sans erreur de bus et sans aucune réponse `0x7E8`, contact mis.

Ce résultat est cohérent avec le catalogue
[RenCOM Trafic II phase 1](https://www.obdtester.com/rencom-eculist/renault/trafic_ii_ph1_%5B2000_2005%5D),
qui classe les injections Bosch EDC15C/EDC16 de cette phase sur bus `ISO`,
alors que les injections EDC16C36/EDC16CP33 de la phase 2 sont classées
`CAN`. Sur la phase 1, le CAN reste utilisable en capture passive, mais la
lecture du calculateur moteur nécessite une interface automobile K-Line
ISO 9141-2 / ISO 14230 (broche OBD 7).

Le profil `renault_trafic_x83_ph1` bloque donc les lectures VIN/DTC CAN et
autorise seulement l'ajout local au Garage par VIN manuel. La passerelle
actuelle n'a pas de transceiver K-Line : la broche OBD 7 ne doit jamais être
reliée directement à un GPIO ESP32.

Le millésime et la motorisation doivent aussi être confirmés par les champs
`D.2`, `P.1` et `P.2` de la carte grise : Renault documente en 2004 les
1.9 dCi 100 et 2.5 dCi 135, tandis que les Trafic 2.0 dCi 90/115 apparaissent
avec la phase 2 à partir de 2006.

## Trafic III (X82) — portée

Le profil `renault_trafic_x82` couvre le fourgon Renault Trafic III (2014+,
Ph1/Ph2/Ph3), plateforme interne Renault `X82`. Aucun DBC ou décodeur CAN
passif open source n'a été trouvé pour cette plateforme lors de la recherche
qui a précédé ce profil (vérifié : opendbc, dépôts DBC communautaires
GitHub, forums propriétaires Trafic/Vivaro/NV300). Les paires
requête/réponse UDS ci-dessous viennent du catalogue de projets
[ddt4all](https://github.com/cedricp/ddt4all/blob/fc2f49f/src/ddt4all/resources/projects.json)
(GPL-3.0), l'outil de diagnostic communautaire Renault — équivalent
fonctionnel de `arduino-psa-diag` déjà cité pour Peugeot dans ce dépôt. Ces
entrées y sont explicitement labellisées `[X82] - Renault Trafic III` (et
`X82PH2`/`X82PH3`).

Comme pour les autres profils, ces sources ne décrivent pas l'équipement
exact d'un VIN donné : une adresse indique un calculateur candidat, seule une
réponse UDS (positive ou négative) confirme sa présence sur le véhicule.

## Calculateurs configurés

| Clé | Calculateur | Famille ddt4all | Requête | Réponse | Présence attendue |
|---|---|---:|---:|---:|---|
| `engine` | Calculateur moteur (ECM) | ECM_29 | `0x7E0` | `0x7E8` | Oui |
| `gearbox` | Boîte pilotée/automatique | AT_29B | `0x7E1` | `0x7E9` | Selon transmission |
| `abs_esp` | ABS / VDC | ABS_VDC | `0x740` | `0x760` | Oui |
| `power_steering` | Direction assistée (EPS) | EPS | `0x742` | `0x762` | Selon équipement |
| `body_computer` | Unité centrale habitacle (UCH) | UCH | `0x745` | `0x765` | Oui |
| `airbag` | Airbags / prétensionneurs (SRS) | AIRBAG_SRS | `0x752` | `0x772` | Oui |
| `gateway` | Passerelle CAN (GW) | GW | `0x710` | `0x730` | Oui |
| `instrument_cluster` | Combiné d'instruments (TDB) | TDB | `0x743` | `0x763` | Oui |

`ddt4all` référence en parallèle des adresses étendues 29 bits
(motif `18DAxxF1`) pour l'ECM, la boîte et l'ABS/VDC. Elles sont documentées
en note dans le profil YAML mais pas utilisées par défaut, faute de
confirmation sur un Trafic III réel.

## Stratégie de détection

Identique à la stratégie Peugeot (`docs/ECU_CATALOG.md`) : le scanner
commence par le DID VIN `0xF190`, réponse positive ou NRC = calculateur
détecté, silence jusqu'au timeout = calculateur absent. Les services UDS
utilisés (session `10 01`/`10 03`, `3E 00`, lecture `22 F1 86`/`22 F1 90`)
sont des services ISO 14229 génériques — `ddt4all` confirme lui-même
l'usage de `22 F1 90` pour lire le VIN sur les véhicules Renault, ce qui
valide leur réutilisation ici.

## Ce qui manque volontairement

- **Décodage CAN passif constructeur (`broadcast_can`)** : aucune source
  fiable disponible. Le profil ne déclare donc aucune trame broadcast
  décodée ; le module Learn de ce dépôt sert justement à construire ce
  catalogue à partir de captures réelles, comme cela a été fait pour le
  profil Fiat 500.
- **Télécodage / actionneurs façon PyPSADiag** : `ddt4all` ne distribue pas
  dans son dépôt Git le catalogue de paramètres/DID par calculateur (fichier
  séparé `ecu.zip`, non versionné) ; seul le calculateur airbag a une trace
  concrète dans le code source, partagée avec d'autres modèles Renault
  (Twingo III/Zoe/Dokker/Duster ph2/Captur/Lodgy). Rien n'est donc câblé côté
  Atelier pour l'instant au-delà du scan UDS générique et de la lecture DTC.

## Validation sur véhicule

Après un premier scan réel sur un Trafic III, reporter dans le profil :

- VIN anonymisé ou empreinte du véhicule, motorisation (dCi + niveau
  d'émission), type de boîte ;
- présence/absence de chaque calculateur ci-dessus ;
- réponse brute au probe `0xF190` par calculateur ;
- toute trame broadcast identifiée pendant une capture Learn, avec son statut
  (`observed_candidate` → `validated_on_vehicle`) suivant la même politique de
  confiance que les profils Peugeot/Fiat.
