# Shadow longitudinal RVV / frein moteur — Peugeot 308 T9

## Objectif

`tools/simulate_t9_rvv.py` rejoue hors ligne une capture GoPro + CAN et compare :

- la vitesse, l'accélération et la consigne RVV PSA réellement observées ;
- le véhicule précédent estimé par `driving_supercombo` ;
- une décision longitudinale adaptative inspirée des distances openpilot ;
- la consigne entière `0x50E` qu'aurait acceptée la passerelle RVV ;
- la capacité observée du frein moteur et les situations qui exigeraient un
  véritable freinage de service.

L'outil n'ouvre aucun port série et ne contient aucun chemin d'émission CAN. Il
ne modifie pas le firmware des ESP32 et ne rend aucun profil prêt véhicule.

## Modèle longitudinal

Le replay reprend les constantes du checkout openpilot de référence, révision `b973dc8ac7e5f38309ef3763d126b39b24f53a39` :

| Paramètre | Valeur initiale |
|---|---:|
| Temps de suivi standard | 1,45 s |
| Distance d'arrêt | 6 m |
| Décélération confortable openpilot | 2,5 m/s² |
| Facteur de zone dangereuse | 0,75 |
| Décélération maximale demandée par le planner | −1,2 m/s² |

Le solveur acados exact n'est pas exécuté : la capture ne contient ni radar, ni
état `radarState`, ni boucle actionneur longitudinale. Le script utilise un
surrogate analytique déterministe qui conserve les distances d'obstacle et les
bornes openpilot. Sa sortie doit être considérée comme une hypothèse de décision,
pas comme une reproduction bit à bit du planner.

La capacité initiale de frein moteur est limitée à `0,30 m/s²`. Cette
valeur est une hypothèse de simulation : pente, vent, rapport de boîte et charge du
véhicule peuvent réduire ou augmenter la décélération réelle.

## Compatibilité passerelle RVV

Le shadow transforme uniquement une demande de ralentissement en consigne RVV :

- consigne entière entre 40 et 130 km/h ;
- variation maximale de 1 km/h toutes les 500 ms ;
- retour progressif à la consigne PSA lorsque la contrainte disparaît ;
- aucune représentation d'une commande de frein.

Une intégration hôte doit distinguer l’origine des variations de la consigne
stock `0x50E` et donner priorité à une baisse de consigne ou une annulation
du conducteur, quitte à quitter immédiatement le remplacement et repasser la
trame stock.

Si la décision demande une décélération supérieure au prior de frein moteur,
l'échantillon est classé `service_brake_required`. Cette décision est
explicitement **non exécutable** par la passerelle actuelle.

## Lancer un rejeu

Depuis la racine du dépôt :

```bash
SESSION=data/runtime/openpilot_live/live-YYYYMMDDTHHMMSSZ

backend/.venv/bin/python openpilot/tools/simulate_t9_rvv.py \
  "$SESSION" \
  --output "data/runtime/t9_rvv_shadow/$(basename "$SESSION")"
```

Pour tester une autre hypothèse, sans modifier le firmware :

```bash
backend/.venv/bin/python openpilot/tools/simulate_t9_rvv.py \
  "$SESSION" \
  --time-gap-s 1.75 \
  --engine-brake-decel-ms2 0.25
```

## Fichiers produits

- `report.html` : graphes vitesse, consignes, distance et accélération ;
- `report.json` : métriques, portes de qualité, hypothèses et limites ;
- `trace.csv` : décision détaillée pour chaque inférence caméra ;
- `events.csv` : séquences de frein moteur et événements adaptatifs.

La colonne `policy_source` distingue la contrainte réellement dominante :

- `cruise` : consigne RVV PSA/du conducteur plus restrictive ;
- `lead0` : distance au véhicule précédent plus restrictive ;
- `inactive` : portes de sécurité non satisfaites.

## Lecture du rapport

Une corrélation ou un accord de décision élevé ne valide pas un actionneur. Le
RVV d'origine, le conducteur, la pente et le trafic évoluent simultanément. Les
points réellement utiles sont :

1. les événements `lead0` assez longs pour éviter les faux positifs caméra ;
2. la marge d'obstacle minimale et la stabilité de la vitesse du lead ;
3. la part des décisions réalisables au frein moteur ;
4. les cas `service_brake_required`, qui définissent le domaine interdit ;
5. la répétabilité sur plusieurs trajets et rapports de boîte.

Une activation routière demanderait au minimum une mesure de distance redondante,
une annulation matérielle indépendante, une caractérisation par rapport de boîte
et pente, puis des essais sur banc et zone fermée. Le RVV seul ne peut pas fournir
un ACC de sécurité ni un freinage d'urgence.
