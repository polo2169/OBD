# Laboratoire OpenPilot PSA T9

Ce dossier regroupe tout ce qui concerne l'observation openpilot, les capteurs
auxiliaires, la simulation de couple latéral et la passerelle expérimentale PSA.
Il est volontairement séparé de l'application de diagnostic OBD située à la
racine du dépôt.

## Périmètre

```text
openpilot/
├── tools/       acquisition, synchronisation, vidéo et simulation hors ligne
├── tests/       tests Python propres au laboratoire
├── scripts/     lanceurs caméra, GoPro, CAN passif et capteurs
├── docs/        protocoles Matek, MADS, RVV et résultats T9
├── firmware/    passerelle PSA à deux ESP32 et enregistreur GPS/IMU
└── hardware/    sources et production du harnais PSA OBD-C
```

L'application OBD et ce laboratoire partagent uniquement les interfaces
documentées suivantes :

- `database/` pour les profils véhicule, DBC et connaissances vérifiées ;
- `data/sessions/` pour les captures brutes ;
- `data/runtime/` pour les sorties locales non versionnées ;
- `backend/.venv/` comme environnement Python local lorsque les scripts le
  demandent explicitement.

Le dépôt comma/openpilot utilisé pour exécuter `driving_supercombo` reste un
dépôt frère, par défaut `../openpilot`. Ce dossier-ci n'en est pas une copie.

## Installation et tests

Depuis la racine du dépôt :

```bash
backend/.venv/bin/pip install -r openpilot/requirements.txt
cd openpilot
../backend/.venv/bin/pytest -p no:cacheprovider -q
```

La vérification globale reste disponible avec :

```bash
./scripts/check_project.sh
```

## Points d'entrée

- [Commandes caméra, GoPro et CAN passif](COMMANDES.md)
- [Capteur Matek F722-SE et GPS BN-880](docs/MATEK_F722_SE_SENSORS.md)
- [Analyse couple openpilot/sunnypilot](docs/T9_OPENPILOT_TORQUE_SHADOW.md)
- [Engagement latéral MADS-T9](docs/PSA_MADS_T9.md)
- [Passerelle RVV à deux ESP32](docs/PSA_RVV_ESP32_BRIDGE.md)
- [Audit du harnais OBD-C](docs/PSA_HARNESS_OBDC_AUDIT.md)

## Limite de sécurité

Les outils d'acquisition et de simulation restent passifs ou hors ligne. Les
profils de couple non nul et de RVV modifié sont réservés au banc isolé tant que
la réponse réelle de l'EPS, les mécanismes de repli et la sécurité longitudinale
n'ont pas été validés sur matériel instrumenté.
