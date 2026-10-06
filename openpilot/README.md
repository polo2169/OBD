# Openpilot — Peugeot 308 T9

Ce laboratoire contient le port expérimental de la Peugeot 308 II T9,
les outils d’acquisition et de rejeu, les tests et les sources du harnais PSA.
Il partage la base véhicule `database/` avec l’application de diagnostic OBD.

## Commencer ici

- [Comportement du code et limites](docs/ETAT_308_T9.md)
- [Protocole : direction dès 50 km/h, puis clignotant](docs/ESSAIS_308_T9.md)
- [Sources de l’overlay actif et construction](port/t9_lateral/README.md)
- [Collecte des journaux et export d’un dataset](docs/DATASET_308_T9.md)
- [Commandes caméra, GoPro, CAN passif et capteurs](COMMANDES.md)
- [Index technique](docs/README.md)

Le code conserve le plancher latéral de **67,1 km/h**, le RVV dès **40 km/h**
et la pause de direction au clignotant. Le pilotage dès 50 km/h et le changement
de voie après deux secondes restent des fonctions à étudier.

## Organisation

```text
openpilot/
├── port/t9_lateral/   overlay actif 308, tests et politique Panda
├── port/t9_shadow/    intégration en observation
├── tools/            acquisition, analyse, simulation et packaging
├── scripts/          collecte, construction, installation et vérification
├── tests/            tests du laboratoire hors véhicule
├── docs/             guides techniques et protocoles
├── parameters/       paramètres de simulation
├── examples/         exemples synthétiques
├── firmware/         passerelle PSA ESP32 et enregistreur GPS/IMU
└── hardware/         sources et production du harnais PSA OBD-C
```

Les comptes rendus, diagnostics, captures, vidéos, paquets compilés,
sauvegardes et sorties d’analyse restent locaux et sont exclus de Git.
Les sorties des outils utilisent `data/runtime/` ou `data/diagnostics/`.

Le dépôt comma/openpilot servant aux modèles et à la compilation est un dépôt
distinct, généralement `../openpilot`. Ce laboratoire distribue un overlay
contre une base précise.

## Vérifier le laboratoire

Depuis la racine OBD, avec l’environnement Python existant :

```sh
backend/.venv/bin/pip install -r openpilot/requirements.txt
cd openpilot
../backend/.venv/bin/pytest -p no:cacheprovider -q
```

La construction de l’overlay exige la base et les empreintes documentées dans
[son README](port/t9_lateral/README.md). La validation native sur cette base
est distincte des tests du laboratoire.

Le port actif reste expérimental. Les contrôles logiciels et USB ne constituent
pas une validation en conduite ; les essais physiques demandent un terrain fermé.
Le RVV agit sur la consigne Peugeot sans commande du frein de service.
