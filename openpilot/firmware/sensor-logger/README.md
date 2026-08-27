# ESP32 GPS + ADXL345 pour OpenPilot

Ce firmware passif enregistre les trames NMEA du GPS et les accélérations
brutes de l’ADXL345. Il ne contient aucun pilote CAN et ne peut envoyer aucune
commande au véhicule.

## Branchement

| ESP32 | GPS BN-880 / ADXL345 |
|---|---|
| GPIO16 (RX2) | GPS TX |
| GPIO17 (TX2) | GPS RX |
| GPIO21 (SDA) | ADXL345 SDA |
| GPIO22 (SCL) | ADXL345 SCL |
| 3V3 | ADXL345 VCC et CS |
| GND | Masse commune |

`SDO` à GND sélectionne l’adresse ADXL345 `0x53`; `SDO` au 3,3 V sélectionne
`0x1D`. Le firmware teste automatiquement les deux adresses. Vérifier la
tension acceptée par le module GPS avant son alimentation.

Le GPS est recherché automatiquement à 9600, 115200, 38400, 57600 et 230400
bauds. La sortie USB fonctionne à **921600 bauds**.

## Compilation et téléversement

```bash
pio run -d openpilot/firmware/sensor-logger
pio run -d openpilot/firmware/sensor-logger \
  -t upload --upload-port /dev/cu.usbserial-110
```

## Enregistrement

Test autonome :

```bash
backend/.venv/bin/python openpilot/tools/record_esp32_sensors.py \
  --port /dev/cu.wchusbserial110 --output /tmp/sensors.jsonl
```

Capture synchronisée avec OpenPilot et la GoPro :

```bash
./openpilot/scripts/run_openpilot_gopro.sh --record --overlay \
  --sensor-port /dev/cu.wchusbserial110
```
