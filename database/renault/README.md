# Renault — sources et liens utiles

Ce dossier suit le même schéma que `database/psa/` et `database/fiat/` :
`vehicles/*.yaml` contient les profils publiés (chargés automatiquement par
`KnowledgeBase`), un dossier `drafts/` pourrait accueillir des variantes non
publiées si besoin plus tard.

Le profil actuel (`vehicles/renault_trafic_x82.yaml`, Renault Trafic III /
plateforme X82) est un catalogue de diagnostic UDS/OBD standard, sans
décodeur CAN passif constructeur — voir `docs/ECU_CATALOG_RENAULT_TRAFIC.md`
à la racine du dépôt pour le détail. Les liens ci-dessous sont ceux utilisés
ou évalués pendant la recherche qui a précédé ce profil.

## Source principale — adressage UDS

- [cedricp/ddt4all](https://github.com/cedricp/ddt4all) (GPL-3.0) — outil de
  diagnostic communautaire Renault/Dacia, équivalent fonctionnel de
  `arduino-psa-diag` côté PSA. Le fichier
  [`src/ddt4all/resources/projects.json`](https://github.com/cedricp/ddt4all/blob/master/src/ddt4all/resources/projects.json)
  contient les paires CAN requête/réponse par calculateur pour de nombreux
  véhicules Renault, dont des entrées explicitement labellisées
  `[X82] - Renault Trafic III` (Ph1/Ph2/Ph3) — c'est la source des adresses
  ECU du profil.
  ⚠️ Le catalogue de paramètres/DID détaillé par calculateur (`ecu.zip`)
  n'est **pas** versionné dans ce dépôt Git ; seul le mapping d'adressage
  CAN dans `projects.json` l'est. Une exploration plus poussée nécessiterait
  de récupérer ce fichier séparément et d'en vérifier la licence/l'usage.
- [`src/ddt4all/plugins/rsat4_reset.py`](https://github.com/cedricp/ddt4all/blob/master/src/ddt4all/plugins/rsat4_reset.py) —
  seule mention littérale « TRAFIC III » du code source ddt4all ; le
  calculateur airbag y est partagé avec Twingo III/Zoe/Dokker/Duster
  ph2/Captur/Lodgy ph1-2.

## Norme OBD-II générique

- [OBDb/SAEJ1979](https://github.com/OBDb/SAEJ1979) (CC-BY-SA-4.0) — PIDs
  Mode 01 normalisés, déjà utilisés par les profils Peugeot et Fiat.

## Pistes évaluées mais écartées (aucune donnée exploitable pour le X82)

Recherche dédiée effectuée avant la création du profil ; aucune de ces
pistes ne fournit d'identifiants CAN concrets pour le Trafic III / X82,
Opel Vivaro B ou Nissan NV300 :

- [commaai/opendbc](https://github.com/commaai/opendbc) — aucun fichier DBC
  Renault (Renault n'est pas une marque supportée par openpilot).
- [x0r.fr/blog/39](https://x0r.fr/blog/39) — reverse engineering CAN d'une
  Renault Clio III (2006), utile seulement comme référence des conventions
  générales Renault (algorithme de checksum, style d'échelle des signaux),
  pas du tout la même génération/architecture que le X82.
- [cpocol/canDrive](https://github.com/cpocol/canDrive) — Dacia Sandero II,
  IDs régime/température moteur revendiqués généralisables au groupe
  Renault, mais plateforme différente du X82.
- [krsche/renault-megane-3-rs-can-dbc](https://github.com/krsche/renault-megane-3-rs-can-dbc) —
  dépôt peu avancé (liste d'IDs à ignorer, pas de signaux décodés).
- [dirksan28/Scenic2DashCanEmu](https://github.com/dirksan28/Scenic2DashCanEmu) —
  Renault Scenic 2, périmètre limité (émulation tableau de bord).

## Prochaine étape naturelle

Construire un vrai catalogue `broadcast_can` pour le X82 nécessite une
capture réelle sur un Trafic III via le module Learn de ce dépôt (écoute
passive déjà brand-agnostic côté firmware ESP32), suivie d'un recoupement
signal par signal comme cela a été fait pour le profil Fiat 500
(`database/fiat/vehicles/fiat_500_generic.yaml`).
