# Peugeot 308 T9 : optimisation latérale après analyse des routes

## Constat mesuré

L'analyse porte sur 54 segments `rlog.zst` déjà rapatriés, dont 460 secondes
de contrôle latéral actif réparties en 36 séquences d'au moins cinq secondes.
La vitesse médiane est de 130,0 km/h et le 95e centile de 132,3 km/h.

Les traces montrent deux phénomènes distincts :

- une oscillation dominante de la commande vers 0,7 Hz et de l'accélération
  latérale vers 0,6 Hz ;
- une demande supérieure à l'enveloppe validée de 0,42 m/s² pendant 12,0 %
  des points, avec une commande appliquée à ±10 raw pendant 8,0 % des points.

L'erreur de suivi RMS enregistrée est de 0,137 m/s². Sur les portions proches
de la ligne droite, la composante rapide RMS de la commande atteint 3,16 raw.
La tranche 110–130 km/h concentre le problème : 25,9 % des demandes dépassent
0,42 m/s² et 17,3 % des points atteignent la limite de couple.

Ces chiffres séparent une correction trop vive près du centre d'une demande
de courbure parfois impossible à produire avec la limite active. Augmenter la
limite au-delà de ±10 n'est pas retenu : les routes analysées valident la
réponse fermée jusqu'à cette valeur seulement. Les commandes usine plus fortes
constituent une observation passive, pas une validation d'une émission plus
forte par openpilot.

## Correctif

Le profil candidat conserve l'enveloppe ±10 raw et le gain identifié de
0,042 m/s²/raw. Il modifie uniquement le profil T9 :

- le gain proportionnel reste inchangé jusqu'à 90 km/h, puis descend de 1,2 à
  0,7 à 108 km/h, 0,6 à 119 km/h et 0,5 à partir de 130 km/h ;
- le gain intégral descend de 0,12 à 90 km/h à 0,10, 0,08 puis 0,06 aux mêmes
  points de vitesse ;
- la compensation de frottement passe de 1,4 à 0,7 raw ;
- une zone morte égale à la moitié de la résolution CAN de lacet, soit
  `0,5 × 0,1 deg/s × vitesse`, empêche le PID de poursuivre la quantification ;
- avant le limiteur standard de jerk, la courbure demandée est bornée par
  `|courbure| <= 0,42 / vitesse²`.

La dernière règle relie explicitement le rayon, le couple et la vitesse :
`rayon_min = vitesse² / 0,42`. Elle évite l'accumulation du PID sur une
trajectoire hors de l'autorité validée. Si la route demande une courbe plus
serrée, le signal `curvature_limited` reste actif afin que l'alerte de
saturation puisse demander la reprise du conducteur. Ce correctif ne prétend
pas ralentir le véhicule et ne commande toujours pas les freins.

## Rejeu hors ligne

Un rejeu contrefactuel utilise le gain 0,042 m/s²/raw, le délai 150 ms, la
constante de réponse 140 ms et la même rampe de 1 raw par trame à 20 Hz. Sur
25 726 points après retrait des transitoires, le réglage candidat donne :

| Mesure | Ancien | Candidat | Écart |
| --- | ---: | ---: | ---: |
| RMS de commande rapide | 1,885 raw | 1,586 raw | −15,9 % |
| RMS d'accélération rapide | 0,0692 m/s² | 0,0618 m/s² | −10,7 % |
| Demande à la limite | 14,7 % | 13,8 % | −0,9 point |

Le rejeu aide à comparer les réglages sur les mêmes consignes. Il ne remplace
pas un trajet avec le nouveau code : la réponse finale doit être vérifiée dans
les mêmes tranches de vitesse, puis comparée au spectre 0,6–0,7 Hz ci-dessus.

## Installation et contrôle

La version a été construite et testée dans une copie isolée sur le comma, puis
installée atomiquement. Le manifeste actif après redémarrage porte l'empreinte
SHA-256
`7282a222fb4e3898979f6a04870b7466da060920bee75063c6fbf60939257962`.
La sauvegarde précédente est conservée dans
`/data/openpilot-before-t9-lateral-20260921T184818Z`.

La validation complète compte 387 tests : 381 réussis et 6 ignorés, auxquels
s'ajoutent les deux bancs C++. Le contrôle après redémarrage a confirmé les
sources et artefacts installés, le profil latéral/RVV à axes séparés, la pause
latérale, le seuil conducteur à 15, la commande bornée à ±10 et le cycle EPS
conservé sur **ON**. Le comma était sur USB, hors route, harnais débranché et
Panda en `noOutput`, sans trame CAN transmise pendant ce contrôle.

Cette validation couvre la construction et les invariants hors route. Un
nouveau trajet reste nécessaire pour mesurer le résultat réel, surtout entre
110 et 130 km/h, et vérifier la baisse du pic à 0,6–0,7 Hz.
