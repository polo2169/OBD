# Brochage du harnais PSA OBD-C

## Correspondance des 60 contacts PSA

Les désignations suivantes sont celles du projet KiCad. Elles ne doivent pas
être transposées à une numérotation automobile 1–60 sans vérifier le repérage
physique du connecteur. Les 58 contacts directs conservent leur numéro local.
Les deux lignes CAN J1.3/J4.3 et J1.5/J4.5 passent par les commutateurs.

| Broche locale | J1 ↔ J4 | J2 ↔ J5 | J3 ↔ J6 |
| --- | --- | --- | --- |
| 1 | Direct | Direct | Direct |
| 2 | Direct | Direct | Direct |
| 3 | U1 : 1–2 (NC) ; CAN0_L ↔ CAN2_L | Direct | Direct |
| 4 | Direct | Direct ; GND | Direct ; CAN1_L |
| 5 | U2 : 2–1 (NC) ; CAN0_H ↔ CAN2_H | Direct | Direct |
| 6 | Direct | Direct | Direct ; CAN1_H |
| 7 | Direct | Direct | Direct |
| 8 | Direct | Direct | Direct |
| 9 | Direct | Direct | Direct |
| 10 | Direct | Direct | Direct |
| 11 | Direct | Direct | Direct |
| 12 | Direct | Direct ; +12V | Direct |
| 13 | Direct | Direct | Direct |
| 14 | Direct | Direct | Direct |
| 15 | Direct | Direct | Direct |
| 16 | Direct | Direct | Direct |
| 17 | Direct | Direct | Direct |
| 18 | Direct | Direct | Direct |
| 19 | Direct | Direct | Direct |
| 20 | Direct | Direct | Direct |

La [fiche de mesure des 60 contacts](PSA_HARNESS_CONTROLE_60_BROCHES.csv)
contient chaque paire, son net et la broche de liaison entre cartes. Les colonnes
mesure et observation sont vides dans ce modèle. Une mesure de résistance s'effectue uniquement sur le harnais déposé et
sans alimentation ; les voies électroniques NC demandent un contrôle distinct
sur banc alimenté et ne doivent pas être déclarées coupées sur un simple test
au bip hors tension.

## Liaisons entre cartes

J8 doit correspondre à J10, et J9 à J11, broche pour broche selon la géométrie
du dessin. Le tableau liste les noms de nets du projet.

| Broche | J8 ↔ J10 | J9 ↔ J11 |
| --- | --- | --- |
| 1 | GND | 28 |
| 2 | 12 | 45 |
| 3 | +12V | 29 |
| 4 | 13 | 47 |
| 5 | CAN1_L | 30 |
| 6 | 14 | 48 |
| 7 | CAN1_H | 31 |
| 8 | 15 | 49 |
| 9 | CAN2_L | 33 |
| 10 | 16 | 50 |
| 11 | CAN2_H | 34 |
| 12 | 17 | 51 |
| 13 | 1 | 35 |
| 14 | 18 | 52 |
| 15 | 2 | 36 |
| 16 | 19 | 53 |
| 17 | 4 | 37 |
| 18 | 20 | 54 |
| 19 | 6 | 38 |
| 20 | 21 | 55 |
| 21 | 7 | 39 |
| 22 | 22 | 56 |
| 23 | 8 | 40 |
| 24 | 23 | 57 |
| 25 | 9 | 41 |
| 26 | 25 | 58 |
| 27 | 10 | 42 |
| 28 | 26 | 59 |
| 29 | 11 | 43 |
| 30 | 27 | 60 |

## J7 : affectations OBD-C dans ce harnais

| Contacts J7 | Connexion prévue |
| --- | --- |
| A1, A12, B1, B12, S1 | GND ; J2.4 ↔ J5.4 |
| A4, A9, B4, B9 | +12 V ; J2.12 ↔ J5.12 |
| A2 / A3 | CAN0_H / CAN0_L ; J1.5 / J1.3 |
| B2 / B3 | CAN2_H / CAN2_L ; J4.5 / J4.3 |
| A11 / A10 | CAN1_H / CAN1_L ; J3.6 / J3.4 ↔ J6.6 / J6.4 |
| A8 | SBU1, commande commune U1.6/U2.6, rappel à la masse de 240 Ω |
| B8 | SBU2 non connecté |
| B10, B11 | Non connectés (paire CAN3 absente dans ce dessin) |
| A5, B5, A6, B6, A7, B7 | Non connectés |

Cette prise transporte du +12 V sur les contacts VBUS ; elle ne doit pas être
assimilée à une prise USB de périphérique ordinaire.
