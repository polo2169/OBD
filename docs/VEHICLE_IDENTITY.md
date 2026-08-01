# VIN et identité multi-marque

## Fonctions disponibles

La route `POST /api/diagnostic/identity` accepte un profil publié par
`GET /api/database/vehicles`. Elle effectue uniquement des lectures :

- UDS `ReadDataByIdentifier (0x22)` avec le DID VIN standard `F190` ;
- OBD-II Mode 09 PID 02 pour le VIN ;
- OBD-II Mode 09 PID 04, 06 et 0A pour la calibration, le CVN et le nom ECU ;
- DIDs d'identification `F180`, `F181`, `F187`, `F189` et `F18C` sur le profil
  Peugeot lorsque le calculateur les expose.

Un VIN n'est accepté que s'il contient exactement 17 caractères autorisés. Le
préfixe WMI permet ensuite d'afficher le constructeur connu et de détecter une
erreur de sélection de profil.

Chaque requête, réponse, NRC, erreur ISO-TP et résultat décodé est écrit dans une
session JSONL sous `data/sessions`. La lecture est refusée pendant une capture
CAN pour éviter deux propriétaires concurrents du même port ESP32.

## Peugeot 308 T9

Ordre de lecture VIN :

1. BSI `752→652`, commande `22 F1 90` ;
2. injection `6A8→688`, commande `22 F1 90` ;
3. OBD-II moteur `7E0→7E8`, commande `09 02`.

Les couples d'identifiants viennent du catalogue communautaire
`arduino-psa-diag`; une réponse réelle reste la preuve de présence de l'ECU.

## Fiat 500 — portée actuelle

Le profil `fiat_500_generic` commence toujours par OBD-II Mode 09, qui est la
méthode la moins dépendante de la génération. Le catalogue communautaire joint
au projet documente aussi :

- `BMF_CAN_FIAT` / Body Computer : `7B0→7C0` ;
- `COMBINE_CAN_FIAT` / combiné : `7B0→7C3`.

Ces deux paires sont des replis expérimentaux pour `22 F1 90` : la source donne
les adresses, pas la garantie que ce DID UDS soit accepté sur chaque Fiat 500.
Elles restent limitées aux services de lecture par l'allowlist du PC et du
firmware.

Ce profil ne doit pas encore être utilisé pour promettre un inventaire complet
des ECU ou un décodage DTC Fiat. Il faut d'abord connaître au minimum :

- année ;
- motorisation et carburant ;
- marché/pays ;
- génération exacte (500 type 312, 500X ou 500e).

## Firmware

Le firmware diagnostic `0.9.0-multibrand-readonly` autorise `7B0` uniquement
avec les mêmes services UDS de lecture déjà permis sur les adresses PSA. Les
écritures, effacements, SecurityAccess et requêtes multi-trames émises par le PC
restent bloqués. OBD `09 02/04/06/0A` utilise l'adresse standard `7E0` déjà
allowlistée.

## Sources

- <https://github.com/ludwig-v/arduino-psa-diag>
- <https://github.com/ludwig-v/arduino-psa-diag/blob/master/ECU_LIST.md>
- <https://github.com/OBDb/SAEJ1979>
