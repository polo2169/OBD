# Collecte et dataset — Peugeot 308 T9

Le [port courant](ETAT_308_T9.md) et le [README de l’overlay](../port/t9_lateral/README.md)
décrivent la version du code à joindre. Les captures restent locales jusqu’à
un export explicitement choisi.

## Enregistrement

`system/psa_recorder.py` écrit des segments locaux de 16 Mio sous
`/data/psa-diagnostics`, avec un maximum de 32 segments et une réserve de
1 Gio. Le collecteur lit les services déjà publiés ; il n'ouvre pas directement
Panda et ne déclenche pas d'envoi CAN. Les segments sont des suites non
compressées de messages `cereal.Event`.

Depuis la racine du dépôt, la récupération conserve les originaux sur le
comma :

```sh
./openpilot/scripts/fetch_comma_308_diagnostics.sh ADRESSE_DU_COMMA
```

L'archive brute est placée dans `data/diagnostics/comma/`, dossier ignoré par
Git. Elle peut contenir jusqu'à 512 Mio et n'est pas destinée à être publiée
telle quelle.

## Préparer un dataset avec le code

L'exporteur choisit par défaut la session la plus récente, conserve ses quatre
derniers segments complets et ajoute le code de l'overlay ainsi que les outils
de construction et de vérification :

```sh
python3 openpilot/tools/export_t9_dataset.py \
  data/diagnostics/comma/308-AAAAmmjjTHHMMSSZ-PID.tar.gz \
  --segments 4 \
  --label essai-308-t9 \
  --output data/diagnostics/comma/t9-dataset-a-partager.tar.gz
```

Le fichier produit contient :

- `dataset/` : les paires `.rlog`/`.json` sélectionnées et, si elle correspond
  à la session, une copie de `status.json` ;
- `code/` : l'overlay T9 et les scripts nécessaires à sa construction ;
- `manifest.json` : taille et SHA-256 de chaque élément, numéros des segments,
  services enregistrés, commit Git vu au moment de l'export et indication d'un
  éventuel espace de travail non propre ;
- `README.md` : format de lecture et limites de confidentialité.

L'identifiant UUID de la session est remplacé dans les JSON par les 16 premiers
caractères de son SHA-256. Le flux `cereal.Event` reste inchangé octet pour
octet afin de rester rejouable. Le collecteur n'enregistre ni caméra ni service
GPS, mais le CAN brut, `carParams` ou les messages système peuvent encore
contenir des identifiants du véhicule ou de l'appareil. L'archive indique donc
explicitement `event_stream_anonymized=false` et doit être contrôlée avant une
publication publique.

Un exemple synthétique lisible, sans donnée véhicule, est fourni dans
[`../examples/t9_dataset/timeline.example.csv`](../examples/t9_dataset/timeline.example.csv).
Il illustre une pause au clignotant, une pause à 16, le maintien à 15 et les
deux reprises après validation des lignes. Les exemples publiés sont
synthétiques ; les extraits de captures restent locaux.

## Lecture

Avec l'environnement openpilot correspondant :

```python
from pathlib import Path
from openpilot.tools.lib.logreader import LogReader

raw = Path("dataset/capture-00000001.rlog").read_bytes()
for event in LogReader.from_bytes(raw):
  print(event.logMonoTime, event.which())
```

Les empreintes du manifeste permettent de vérifier que le dataset reçu et le
code analysé n'ont pas changé pendant le transfert.
