# Peugeot 308 T9 : code partageable et dataset

Cette page décrit l'état courant à partager. Les rapports datés précédents
restent utiles pour comprendre les essais, mais peuvent décrire une ancienne
valeur de seuil ou une fonction qui n'était pas encore installée.

## Version courante

L'overlay se trouve dans [`../port/t9_lateral`](../port/t9_lateral). Il cible
la base openpilot `6c928b70b499fae53c3791384e44886f4c352842`. Les 73 chemins remplacés
sont listés avec l'empreinte attendue de leur version d'origine dans
`base-sha256.json`. Le manifeste de la version installée sur le comma porte
l'empreinte SHA-256
`822e3ccf66069f184604e8d67ff70ab92d45cbe68230f47a33e5dcc0bc5e1edf`.

Le profil courant sépare le latéral et le RVV :

- seuil conducteur ±15 inclus ; la pause commence au-delà, à ±16 en unités
  entières observées ;
- pause latérale immédiate avec un clignotant ou les warnings ;
- reprise après extinction du clignotant ou retour de l'effort dans ±15, puis
  0,5 seconde de modèles successifs avec deux lignes fiables et plausibles ;
- reprise à couple nul suivie de la rampe existante ;
- RVV disponible à partir de 40 km/h, latéral à partir de 67,1 km/h et plafond
  à 140 km/h ;
- anticipation de quatre secondes de la distance de rapprochement, baisse de
  consigne bornée à 1 km/h par 100 ms, sans exigence d'atteindre la cible en
  deux secondes et sans commande des freins ;
- cycle EPS inspiré de cristianku, optionnel et OFF par défaut. En ON, il peut
  demander une brève désactivation/réactivation après au moins 12 secondes,
  seulement avec retour EPS frais, activité conducteur reconnue, lignes
  fiables et trajectoire droite actuelle et prévue.

La pause clignotant/effort ne dépend pas du bouton du cycle EPS. Une perte
réelle d'autorisation EPS, un défaut ou une interruption de la session reste
un arrêt mémorisé qui demande un OFF/ON physique du RVV.

## Validation connue

La copie exacte installée a passé 383 tests : 377 réussis et 6 ignorés, plus
deux bancs C++. Le programme natif, le firmware Panda H7 signé, son bootstub
et le module des paramètres ont été compilés sur le comma. Trois démarrages
USB successifs ont validé OFF → ON → OFF, avec 30 contrôles à chaque fois.
Le réglage final laissé sur l'appareil est OFF.

Ces contrôles valident les sources, les artefacts, le chargement des profils,
l'interface, le collecteur et les protections logicielles, avec le harnais
débranché et Panda en `noOutput`. Ils ne valident pas le cycle EPS ni la reprise
latérale en conduite. Les trajets utilisés pour étudier le camion et le RVV
précèdent cette version finale.

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
deux reprises après validation des lignes. Un second fichier,
[`truck_approach.sample.csv`](../examples/t9_dataset/truck_approach.sample.csv),
contient huit lignes réelles décodées de l'approche camion, sans GPS, VIN,
image, identifiant d'appareil, trame CAN brute ou identifiant de route. Il
compare l'ancien et le nouveau calcul hors ligne sur les mêmes perceptions ;
ce n'est pas un second trajet commandé par la nouvelle version.

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
