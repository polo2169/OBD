# Matek F722-SE + BN-880 pour les captures OpenPilot

La Matek est utilisée ici comme centrale inertielle et GNSS auxiliaire. Le PC
interroge en lecture seule le firmware Betaflight ou iNav par MSP sur l’USB :
aucune configuration n’est écrite, aucun moteur n’est commandé et aucune trame
CAN véhicule n’est émise.

La F722-SE possède deux IMU intégrées (MPU6000 et ICM20602). MSP expose la mesure
IMU active et alignée par le firmware, pas deux flux bruts indépendants. Voir le
[manuel officiel Matek F722-SE](https://www.mateksys.com/downloads/F722-SE_Manual.pdf)
et la [référence officielle MSP Betaflight](https://betaflight.com/docs/development/MSP-Protocol-Reference-Dev).

## Préparer la carte

1. Conserver Betaflight ou iNav sur la F722-SE. Il n’est pas nécessaire de
   remplacer le firmware par un programme spécifique au projet.
2. Dans l’onglet **Ports**, activer `GPS` sur l’UART où le BN-880 est branché.
   Ne pas attribuer `MSP` et `GPS` au même UART. L’USB/VCP reste le port MSP du PC.
3. Sélectionner le protocole GNSS `UBLOX`, puis vérifier dans l’onglet GPS que la
   position, le nombre de satellites et la vitesse évoluent.
4. Calibrer l’accéléromètre carte parfaitement immobile et horizontale. Vérifier
   aussi l’alignement de carte dans Betaflight/iNav.
5. Fixer rigidement la carte au véhicule, à plat. Éviter une mousse très souple,
   qui introduit du retard et des oscillations propres dans les mesures.

Le câblage UART du GPS est croisé : `TX` du BN-880 vers `RX` de l’UART Matek,
`RX` vers `TX`, avec une masse commune et une alimentation conforme au module.
Le compas du BN-880 utilise un bus I²C séparé : le seul câblage UART suffit au
GPS demandé ici, mais pas au magnétomètre.

## Déclarer l’orientation

`--sensor-mount-yaw` décrit la direction de la flèche de la Matek, vue du dessus,
par rapport à l’avant du véhicule :

| Valeur | Direction de la flèche FC |
|---:|---|
| `0` | avant |
| `90` | droite |
| `180` | arrière |
| `270` | gauche |

La transformation suppose la carte à plat. Les fichiers gardent à la fois les
axes FC et les axes véhicule `forward/right`; une erreur de montage sera visible
dans la comparaison de signe avec le lacet CAN.

## Essai autonome

Fermer Betaflight/iNav Configurator, qui ne peut pas partager le port série,
puis trouver le port :

```bash
find /dev -maxdepth 1 \( -name 'cu.usbmodem*' -o -name 'cu.usbserial*' \) -print | sort
```

Lancer un enregistrement et l’arrêter avec `Ctrl+C` :

```bash
backend/.venv/bin/python openpilot/tools/record_matek_sensors.py \
  --port /dev/cu.usbmodemXXXX \
  --baud 115200 \
  --mount-yaw-deg 0 \
  --output /tmp/matek-sensors.jsonl
```

Le premier événement `device` doit indiquer `BTFL` ou `INAV`. Les événements
`status` doivent annoncer l’accéléromètre et le GPS présents. Un fix GNSS valide
apparaît avec `"type":"gps"`, `"fix_valid":true` et plusieurs satellites.

## Capture caméra + CAN + Matek

Avec la webcam :

```bash
./openpilot/scripts/record_peugeot_lka.sh \
  --camera 0 \
  --port "$LKA_CAN_PORT" \
  --sensor-port /dev/cu.usbmodemXXXX \
  --sensor-protocol matek-msp \
  --sensor-mount-yaw 0 \
  --until-stop \
  --overlay
```

Avec la GoPro, ajouter les mêmes trois options capteur :

```bash
./openpilot/scripts/run_openpilot_gopro.sh \
  --with-can --port "$LKA_CAN_PORT" \
  --sensor-port /dev/cu.usbmodemXXXX \
  --sensor-protocol matek-msp \
  --sensor-mount-yaw 0 \
  --record --overlay
```

La session contient alors `sensors.jsonl`, synchronisé par l’horloge monotone et
l’horloge murale du Mac avec `frames.jsonl`, `perception.jsonl` et `can.jsonl`.

## Déduire les facteurs de mesure latérale

Après plusieurs trajets comportant lignes droites, virages à gauche/droite et
variations progressives de vitesse :

```bash
backend/.venv/bin/python openpilot/tools/simulate_t9_torque.py \
  data/runtime/openpilot_live/live-YYYYMMDDTHHMMSSZ
```

Le rapport `report.json` et sa page HTML exposent :

- la pente, le biais, la corrélation et l’erreur RMS de l’accélération latérale
  Matek par rapport à `vitesse × lacet CAN` ;
- les mêmes facteurs pour le gyroscope Matek par rapport au lacet CAN ;
- la pente, le biais et la corrélation de la vitesse BN-880 par rapport au CAN ;
- l’âge P95 des mesures et des portes de qualité minimales ;
- le signe d’axe déduit, afin de détecter une orientation inversée.

Ces facteurs servent à calibrer et qualifier la chaîne de mesure. Ils ne sont
pas le gain couple→accélération de l’EPS. Une conduite humaine passive ne permet
pas, à elle seule, d’identifier ce gain d’actionneur ni d’autoriser une commande
de direction.
