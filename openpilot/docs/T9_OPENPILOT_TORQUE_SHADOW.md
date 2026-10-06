# Simulation latérale torque T9

`tools/simulate_t9_torque.py` compare hors ligne des contrôleurs inspirés
d’openpilot et de sunnypilot. Aucun profil n’émet de CAN ;
`vehicle_ready_profile` reste nul.

## Profils

- `openpilot_torque_v1` : structure et gains de la révision openpilot
  `4a13639cfd122ccb9113a4d6ce225dcbd8e61914` ;
- `openpilot_torque_t9_shadow_v1` : gains réduits pour la simulation T9 ;
- `sunnypilot_torque_v0` : gains principaux v0 (`Kp=1`, `Ki=0,3`) ;
- `sunnypilot_torque_v0_jerk_shadow` : pondération accélération/jerk `0,7/0,4`
  et horizon de 1,4 à 2,0 s.

La révision sunnypilot de référence est
`2d6cc4c065c4d1833dc267fff60ebae48b444817`. Le profil jerk utilise les chemins
futurs enregistrés comme substitut hors ligne au plan d’accélération futur.
Il permet une comparaison de sensibilité, sans reproduire une commande en temps réel.

## Modèle

Le simulateur travaille dans l’espace accélération latérale, puis convertit
la sortie en couple brut. Il comprend le délai de consigne, le jerk filtré,
la compensation de frottement, le gel de l’intégrateur, l’anti-windup et les
limites de magnitude et de variation.

Le profil shadow utilise une échelle feed-forward de 0,55, une échelle Kp
de 0,015, Ki nul, frottement nul et délai supposé de 0,15 s. Ces paramètres
sont des hypothèses de simulation ; ils ne constituent pas un profil véhicule validé.

## Utilisation

Depuis la racine du dépôt :

```sh
backend/.venv/bin/python openpilot/tools/simulate_t9_torque.py --help
```

`--factory-response-profile` accepte un JSON de schéma `t9_factory_response_v1`
pour définir gain, délai, constante de réponse et sensibilité au frottement.
Le fichier `parameters/t9_factory_response_2026-09-17.json` contient uniquement
ces paramètres, sans captures, identifiants de trajets ni résultats d’essais.

Les sorties, dont `profile_trace.csv`, restent dans `data/runtime/`.
La trace expose couple, erreur, consigne retardée, jerk, frottement et gel
de l’intégrateur pour chaque profil.

## Limites

Une mesure de roulis de localisation est nécessaire pour sa compensation ;
le roulis de calibration caméra ne la remplace pas. La trajectoire réellement
conduite ne peut pas fermer la boucle d’une commande contrefactuelle : le
simulateur utilise sa propre plante latérale.

Les résultats doivent être confrontés à des mesures instrumentées de la
commande acceptée, de la direction, du lacet, de la vitesse et de l’effort
conducteur avant toute modification du contrôle physique.
