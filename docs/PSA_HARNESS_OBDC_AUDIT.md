# Audit du dossier PSA-Harness

Voir aussi le guide d'intégration
[`PSA_RVV_ESP32_BRIDGE.md`](PSA_RVV_ESP32_BRIDGE.md) pour le firmware, le
protocole RVV et l'ordre de validation.

## Conclusion

Le harnais est utilisable comme gateway inline sur le connecteur noir EP 60
broches du BSI. Contrairement à un simple branchement OBD en parallèle, il peut
isoler le producteur stock de `0x3F2` et `0x50E`, terminer les deux segments et
revenir passivement au câblage d'origine.

Le ZIP `production/PSA-Harness-panel-JLCPCB.zip` ne contient que les Gerbers et
perçages du panneau. Le schéma, le routage logique et les références sont dans le
reste du dossier KiCad ; aucune instruction contenue dans ces fichiers n'a été
traitée comme une demande utilisateur.

## Chemin CAN confirmé

- `J1 to_EPS_1`, broches 5/3 : `CAN0_H/CAN0_L` ;
- `J4 to_car_1`, broches 5/3 : `CAN2_H/CAN2_L` ;
- OBD-C `J7` : CAN0 sur A2/A3, CAN2 sur B2/B3 ;
- CAN1 sur A11/A10 est un autre bus passé directement via J3/J6 ;
- CAN3 et SBU2 ne sont pas connectés dans cette révision.

Les DG419 U1/U2 sont commandés ensemble par `SBU1` :

- `SBU1=0` : les contacts NC relient CAN0 à CAN2, donc fonctionnement stock ;
- `SBU1=1` : les contacts NO séparent les bus et placent R1/R2 de 120 Ω sur
  CAN2 et CAN0 ;
- R3+R4, 120 Ω + 120 Ω en série, tirent `SBU1` à la masse. À 5 V, la commande
  doit fournir environ 20,8 mA.

Le harnais ne contient ni ESP32, ni transceiver CAN, ni convertisseur 12 V vers
5 V. `+12 V` arrive directement sur les quatre contacts VBUS du réceptacle USB-C.

## Protection observée

- D3 `SMF16A` sur l'alimentation 12 V ;
- D1/D2, réseaux Schottky sur les lignes CAN autour des DG419 ;
- R1/R2, terminaisons 120 Ω commutées ;
- R3/R4, pull-down SBU1 total 240 Ω.

Ces éléments ne remplacent pas le fusible d'entrée, le convertisseur automobile,
la protection locale des transceivers ni un étage 5 V pour `SBU1`.

## Points de fabrication à corriger ou vérifier

1. Le BOM exporté nomme U1/U2 `DG419LEUA`, alors que les propriétés du schéma
   nomment `DG419LEDQ-T1-GE3`. Il faut figer la référence et vérifier le brochage
   du boîtier MSOP-8 avant assemblage.
2. Le BOM nomme D1/D2 `BAS40TW-AU`, tandis que les valeurs placées du schéma
   apparaissent aussi comme `BAS40SDW`. Vérifier boîtier, réseau interne et
   brochage ; ces variantes ne doivent pas être substituées sans contrôle.
3. `DRC PCB1.rpt` contient trois erreurs `starved_thermal` sur la masse. Le
   rapport PCB1 indique zéro pad non connecté, mais ces thermiques doivent être
   corrigés puis le DRC relancé avant une nouvelle commande.
4. `DRC PCB2.rpt` n'a pas de pad non connecté et ne signale que des avertissements
   de bibliothèque/empreinte.
5. Les 211 pads non connectés du rapport combiné `DRC PCB ALL.rpt` proviennent en
   grande partie de la combinaison des deux cartes empilées ; utiliser les DRC
   individuels comme référence, sans ignorer les trois erreurs PCB1.
6. Les champs LCSC du BOM sont vides : le ZIP JLCPCB suffit pour fabriquer les
   cartes nues, pas pour garantir un PCBA correctement approvisionné.

## Vérifications avant véhicule

- test de continuité complet connecteurs PSA ↔ OBD-C ;
- vérification de la polarité +12/GND et de l'orientation du câble OBD-C ;
- mesure hors tension de 60 Ω sur le réseau complet en bypass et 120 Ω sur chaque
  segment isolé ;
- confirmation à l'oscilloscope que la résistance série des deux DG419 ne dégrade
  pas les fronts CAN à 500 kbit/s ;
- test de retour bypass sur reset de chaque ESP32, perte UART, bus-off et coupure
  d'alimentation ;
- première isolation uniquement avec une trame `0x3F2` stock à couple nul.
