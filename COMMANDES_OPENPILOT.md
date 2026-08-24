# Commandes d'enregistrement openpilot

Toutes les commandes de ce fichier sont strictement passives : elles
n'envoient aucune trame CAN et aucune consigne de direction. Dans les quatre
cas, la vidéo brute, l'overlay openpilot et les prédictions sont enregistrés
sur le Mac dans
`/Users/paul/Documents/DevRuder/OBD/data/runtime/openpilot_live`. Avec la
GoPro, ces commandes n'utilisent pas sa carte SD : elles enregistrent sur le
Mac le flux reçu en USB.

## Préparation commune

Ouvrir un Terminal et se placer dans le projet :

```bash
cd /Users/paul/Documents/DevRuder/OBD
```

Lister les caméras disponibles :

```bash
./scripts/record_peugeot_lka.sh --list-cameras
```

La webcam actuellement détectée est l'index `0` en 1920 x 1080. Si cela
change, remplacer `--camera 0` dans les commandes ci-dessous.

Lister les ports série avant un test avec CAN :

```bash
find /dev -maxdepth 1 -name 'cu.*' -print | sort
```

Définir le port de l'ESP32 côté véhicule, après avoir vérifié son nom :

```bash
export LKA_CAN_PORT=/dev/cu.SLAB_USBtoUART
```

Le port ne doit pas déjà être ouvert par l'application OBD, un autre lecteur
série ou le HIL. Sur le banc utilisé jusqu'ici,
`/dev/cu.SLAB_USBtoUART10` correspond au contrôleur et
`/dev/cu.SLAB_USBtoUART` au côté véhicule. Toujours revérifier après un
rebranchement USB.

Les commandes utilisent le petit modèle officiel `driving_supercombo.onnx`
avec ONNX Runtime CPU à `--model-hz 20`. Sur ce Mac M1 Pro, le replay routier
mesuré tient environ 19,5–19,6 Hz avec une latence typique de 27–36 ms. Le
pickle tinygrad natif reste disponible avec `--model-backend native`, mais il
ne tenait qu'environ 6 Hz. Appuyer sur `Q` ou Échap pour terminer proprement
l'enregistrement et finaliser les fichiers.

## 1. Webcam, sans CAN, avec enregistrement PC

Cette commande enregistre la webcam, l'overlay, les lignes, la trajectoire et
le véhicule précédent estimé par openpilot. Sans CAN, les vitesses de l'ego et
du véhicule précédent reposent uniquement sur l'estimation visuelle du modèle.

```bash
../openpilot/.venv/bin/python backend/tools/run_openpilot_live.py \
  --openpilot-root ../openpilot \
  --calibration ../openpilot/camera_intrinsics.json \
  --camera 0 \
  --rotate-180 \
  --no-can \
  --model-backend onnx-cpu \
  --model-hz 20 \
  --record \
  --record-overlay \
  --output-dir /Users/paul/Documents/DevRuder/OBD/data/runtime/openpilot_live
```

Si la webcam est à l'endroit, remplacer `--rotate-180` par
`--no-rotate-180`.

## 2. Webcam, CAN passif et vitesses, avec enregistrement PC

Cette commande est celle à privilégier pour une capture routière. Elle ajoute
la vitesse réelle de la Peugeot, le CAN brut synchronisé et une estimation
corrigée de la vitesse du véhicule précédent.

```bash
./scripts/record_peugeot_lka.sh \
  --camera 0 \
  --port "$LKA_CAN_PORT" \
  --until-stop \
  --overlay \
  --output-dir /Users/paul/Documents/DevRuder/OBD/data/runtime/openpilot_live
```

Si la webcam est à l'endroit, ajouter `--no-rotate-180`.

Pour un enregistrement limité à 15 minutes :

```bash
./scripts/record_peugeot_lka.sh \
  --camera 0 \
  --port "$LKA_CAN_PORT" \
  --duration 900 \
  --overlay \
  --output-dir /Users/paul/Documents/DevRuder/OBD/data/runtime/openpilot_live
```

## 3. GoPro, sans CAN, avec enregistrement PC

Brancher la GoPro en USB et sélectionner `USB Connection > GoPro Connect`.
La commande démarre le flux 1080p30, l'affichage openpilot et l'enregistrement
local. Les vitesses affichées sont ici uniquement des estimations visuelles.

```bash
./scripts/run_openpilot_gopro.sh \
  --model-hz 20 \
  --record \
  --overlay \
  --output-dir /Users/paul/Documents/DevRuder/OBD/data/runtime/openpilot_live
```

La GoPro est considérée montée à l'envers par défaut. Ajouter
`--no-rotate-180` si elle est à l'endroit.

## 4. GoPro, CAN passif et vitesses, avec enregistrement PC

Cette commande enregistre simultanément le flux GoPro, l'overlay, les
prédictions et le CAN Peugeot. La vitesse de la Peugeot provient du CAN et
sert à corriger la vitesse absolue estimée du véhicule précédent.

```bash
./scripts/run_openpilot_gopro.sh \
  --with-can \
  --port "$LKA_CAN_PORT" \
  --model-hz 20 \
  --record \
  --overlay \
  --output-dir /Users/paul/Documents/DevRuder/OBD/data/runtime/openpilot_live
```

Pour limiter la capture à 15 minutes, ajouter `--duration 900`.

## Retrouver et ouvrir le dernier enregistrement

Après l'arrêt propre, retrouver la session la plus récente :

```bash
cd /Users/paul/Documents/DevRuder/OBD
SESSION="$(find data/runtime/openpilot_live -maxdepth 1 -type d -name 'live-*' -print | sort | tail -1)"
printf '%s\n' "$SESSION"
ls -lh "$SESSION"
```

Ouvrir la vidéo brute puis la vidéo annotée :

```bash
open "$SESSION/road.mp4"
open "$SESSION/overlay.mp4"
```

## Fichiers produits

- `road.mp4` : vidéo brute enregistrée sur le Mac.
- `overlay.mp4` : vidéo annotée avec trajectoire, lignes, vitesse Peugeot,
  véhicule précédent, distance, vitesse estimée et vitesse relative `dV`.
- `frames.jsonl` : horodatage de chaque image vidéo.
- `perception.jsonl` : sorties openpilot, probabilités, trajectoire et données
  du véhicule précédent.
- `can.jsonl` : trames CAN brutes synchronisées, uniquement dans les cas 2 et
  4.
- `meta.json` : paramètres, résumé, pertes éventuelles et ancre de
  synchronisation caméra/CAN.

## Signification des vitesses affichées

L'overlay affiche :

- la vitesse de la Peugeot en haut à droite ;
- `VITESSE ~... km/h` pour le véhicule précédent retenu par openpilot ;
- `dV` pour sa vitesse relative par rapport à la Peugeot ;
- la distance et la probabilité du véhicule précédent.

Openpilot ne fournit pas ici la vitesse de toutes les voitures visibles. Son
signal `lead` représente le véhicule précédent le plus probable, avec des
horizons de probabilité à 0, 2 et 4 secondes. Les valeurs restent des
estimations de vision et ne remplacent pas une mesure radar homologuée.
