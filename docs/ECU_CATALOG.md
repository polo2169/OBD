# Catalogue ECU — Peugeot 308 II T9 (2018)

## Portée

La plateforme T9 est associée à l'architecture `AEE2010.full` par
[PSA-RE](https://github.com/prototux/PSA-RE/blob/74294e99bd8f4decbfcdceabb11c7413dd977f4d/cars/T9.yml).
Les paires requête/réponse viennent du catalogue de familles
[arduino-psa-diag](https://github.com/ludwig-v/arduino-psa-diag/blob/c1409e60798f66bb63149505826170b5eb3c163f/ECU_LIST.md).

Ces sources ne décrivent pas la liste exacte des équipements montés sur un VIN donné.
Une adresse indique donc un calculateur candidat ; seule une réponse UDS valide, positive
ou négative, confirme sa présence sur le véhicule.

## Calculateurs configurés

| Clé | Calculateur | Famille | Requête | Réponse | Présence attendue |
|---|---|---:|---:|---:|---|
| `engine` | Moteur / injection | INJ | `0x6A8` | `0x688` | Oui |
| `gearbox` | Boîte pilotée/automatique | BOITEVIT | `0x6A9` | `0x689` | Selon transmission |
| `abs_esp` | ABS / ESP | ABRASR | `0x6AD` | `0x68D` | Oui |
| `bsi` | Boîtier de servitude intelligent | BMF_UDS_PSA | `0x752` | `0x652` | Oui |
| `airbag` | Airbags / prétensionneurs | AIRBAG | `0x744` | `0x644` | Oui |
| `power_steering` | Direction assistée | DIRECTN | `0x6B5` | `0x695` | Oui |
| `instrument_cluster` | Combiné | COMBINE | `0x75F` | `0x65F` | Oui |
| `climate_control` | Climatisation | CLIM | `0x76D` | `0x66D` | Selon version |
| `front_camera` | Caméra vidéo multifonction | CVM | `0x74A` | `0x64A` | Selon aides à la conduite |
| `parking_assistance` | Aide au stationnement | AAS | `0x75D` | `0x65D` | Selon équipement |
| `telematics` | SMEG, NAC, RCC ou télématique | TELEMAT | `0x764` | `0x664` | Selon équipement |

## Stratégie de détection

Le scanner commence par le DID VIN `0xF190` :

- réponse positive : calculateur détecté, puis lecture des autres DIDs ;
- réponse négative UDS (NRC) : calculateur détecté, puis lecture des autres DIDs ;
- silence jusqu'au timeout : calculateur non détecté et arrêt des lectures pour cette adresse.

Cette stratégie réduit fortement le trafic et évite sept timeouts successifs pour chaque
équipement absent. Les adresses sont utilisées uniquement avec les services autorisés par
le garde-fou `READ_ONLY`.

La paire `0x74A/0x64A` est partagée dans le catalogue communautaire par les familles
`CVM` et `CPL` (capteur pluie/luminosité). Le scanner expose donc les variantes possibles
et conserve les références d'identification au lieu de conclure sur la seule adresse.

Après l'identification, le scanner envoie `19 02 FF` aux calculateurs détectés. Chaque
entrée conserve le code 24 bits, le type de panne, l'état UDS et une description issue
des catalogues candidats déclarés dans le profil.

## Validation sur véhicule

Après un premier scan réel, les résultats doivent être reportés dans le profil avec :

- VIN anonymisé ou empreinte du véhicule ;
- motorisation et type de boîte ;
- présence/absence de chaque ECU ;
- réponse brute au probe ;
- version logicielle si disponible ;
- date, firmware de passerelle et version du profil.

Une adresse `community_family_catalog` ne doit devenir `vehicle_confirmed` qu'après une
validation reproductible sur la T9 concernée.
