# Contrôle latéral torque T9 — profil openpilot shadow

## État

Le simulateur hors ligne contient désormais quatre contrôleurs inspirés de
`LatControlTorque` :

- `openpilot_torque_v1` reproduit la structure et les gains de la révision
  openpilot `4a13639cfd122ccb9113a4d6ce225dcbd8e61914` ;
- `openpilot_torque_t9_shadow_v1` conserve cette structure avec une calibration
  réduite, destinée uniquement aux rejeux contrefactuels de la 308 T9 ;
- `sunnypilot_torque_v0` reproduit les gains principaux v0 (`Kp=1`, `Ki=0,3`)
  à paramètres EPS T9 encore hypothétiques ;
- `sunnypilot_torque_v0_jerk_shadow` ajoute la pondération sunnypilot
  accélération/jerk `0,7/0,4` et un horizon variant de 1,4 à 2,0 s.

Aucun de ces profils n'émet de CAN. `vehicle_ready_profile` reste nul.

Le profil jerk-aware ne dispose pas du vrai plan d'accélération future de
sunnypilot dans les anciens enregistrements. Il utilise donc explicitement la
série temporelle future des chemins enregistrés comme substitut hors ligne. Ce
résultat permet une comparaison de sensibilité, pas une reproduction exacte en
temps réel. La révision sunnypilot de référence est
`2d6cc4c065c4d1833dc267fff60ebae48b444817`.

## Structure intégrée

Le profil travaille dans l'espace accélération latérale avant de convertir le
résultat en couple brut. Il comprend :

- le gain proportionnel dépendant de la vitesse d'openpilot ;
- un tampon de consigne aligné sur le délai latéral ;
- le calcul et le filtrage du jerk latéral ;
- la compensation de frottement au format opendbc ;
- la compensation du roulis lorsqu'une vraie mesure de localisation existe ;
- le gel de l'intégrateur lors d'une intervention conducteur ou d'une limite ;
- l'anti-windup avant conversion finale en couple brut ;
- les limites de magnitude et de variation déjà utilisées par le simulateur.

La conversion utilise encore l'hypothèse de gain `0,038410 m/s²/raw`. Avec la
limite actuelle de ±10 raw, le facteur d'accélération pleine échelle n'est donc
que `0,3841 m/s²`. Cette valeur n'est pas une mesure active de l'EPS.

## Calibration shadow retenue

Le profil conservateur utilise :

| Paramètre | Valeur |
|---|---:|
| échelle feed-forward | 0,55 |
| échelle du Kp openpilot | 0,015 |
| échelle du Ki | 0 |
| frottement normalisé | 0 |
| délai supposé | 0,15 s |
| limite brute | ±10 raw |

Le frottement reste désactivé dans ce profil tant que l'hystérésis de l'EPS T9
n'est pas mesurée. Le jerk est calculé et exporté dans la trace, mais ne crée
donc pas encore de compensation de frottement.

Cette calibration vient d'un balayage grossier effectué sur tous les trajets
enregistrés le 27 août 2026. Il ne s'agit pas d'une validation holdout ni d'une
calibration véhicule.

## Résultat sur les 14 trajets

| Profil | RMS m/s² | Saturation | P95 couple raw/s | HF RMS | Inversions/min |
|---|---:|---:|---:|---:|---:|
| réglage souple actuel | 0,341 | 23,5 % | 9,1 | 1,434 | 78,9 |
| openpilot standard | 0,338 | 34,5 % | 20,0 | 1,731 | 335,6 |
| openpilot T9 shadow | 0,351 | 17,1 % | 7,4 | 1,245 | 49,7 |
| sunnypilot torque v0 | 0,339 | 34,6 % | 20,0 | 1,731 | 335,2 |
| sunnypilot v0 jerk-aware shadow | 0,339 | 34,4 % | 20,0 | 1,725 | 330,3 |

Le profil openpilot standard suit légèrement mieux, mais il est trop agressif
avec l'autorité supposée. Le profil T9 shadow est retenu par l'objectif du
simulateur parce qu'il réduit la saturation et l'activité de commande. Aucun
profil ne respecte le seuil de saturation inférieur à 5 %.

Le rejeu confirme que sunnypilot v0 brut n'améliore pas notre cas : il atteint
pratiquement la même erreur que le contrôleur openpilot standard, mais conserve
environ 34,6 % de saturation et la limite de variation à 20 raw/s. Le substitut
jerk-aware réduit très légèrement l'activité haute fréquence, sans résoudre la
saturation. Il ne doit donc pas remplacer le profil T9 shadow conservateur.

Rapport final :
`data/runtime/t9_torque_simulator/all-trips-openpilot-torque-v1-final-20260827/`.
Rejeu sunnypilot/MADS :
`data/runtime/t9_torque_simulator/all-trips-sunnypilot-mads-20260827/`.
`profile_trace.csv` contient, pour chaque profil, le couple, l'erreur, la
consigne retardée, l'erreur interne, le jerk, le frottement et l'état de gel de
l'intégrateur.

## Données manquantes

- Les captures actuelles ne contiennent aucun roulis routier issu de la
  localisation. La compensation utilisée vaut donc explicitement zéro. Le roll
  de calibration de la caméra n'est pas utilisé à sa place.
- L'angle de volant enregistré appartient à la trajectoire conduite par
  l'humain. Il ne peut pas fermer honnêtement la boucle d'une commande
  contrefactuelle ; le simulateur utilise l'état latéral équivalent de sa plante.
- Le gain, le délai, la zone morte, le frottement et les asymétries de l'EPS ne
  sont pas identifiés par les trajets passifs.

## Étape de validation suivante

Conserver le facteur EPS fixe à 100 et les limites ESP32 actuelles. La prochaine
étape est une identification instrumentée avec de petites commandes symétriques,
sur banc ou zone fermée, avec opérateur et coupure indépendante. Il faut mesurer
la commande réellement acceptée, l'angle et la vitesse de volant, le lacet, la
vitesse, les états EPS, le couple conducteur et le frein avant de modifier ±10
ou d'activer un frottement appris.
