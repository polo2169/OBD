# Cycle EPS d'essai avec interrupteur ON/OFF

État : **version installée et vérifiée sur USB, modes OFF → ON → OFF ;
réglage final OFF. Aucun essai dynamique validé**.
Le paquet et les preuves sont dans `data/runtime/t9_eps_cycle_20260921/`.
La version précédente est sauvegardée dans
`/data/openpilot-before-t9-lateral-20260921T170732Z`.

## Utilisation

Dans l'interface du comma : **Settings → toggles → cycle EPS (essai)**.
Le sous-titre indique « redémarre le comma ». Chaque changement enregistre
le choix puis redémarre l'appareil. Le bouton est utilisable véhicule éteint,
assistance arrêtée ; ces conditions sont vérifiées de nouveau au clic.

Le mode est **OFF par défaut**. OFF conserve le profil `0x1314` et son
réarmement physique après arrêt latéral. ON choisit le profil d'essai `0x1316`
(sonde sans commande `0x1317`). Le choix est lu une seule fois au démarrage
du gestionnaire, avant de lancer ses processus : le contrôleur et Panda ne
peuvent pas charger deux choix différents après un simple changement du
paramètre. Le réglage persistant s'appelle `PsaT9EpsCycleTest`.

## Cycle implémenté

La séquence reprend le principe du cycle périodique de
[cristianku](https://github.com/cristianku/opendbc/blob/d79cb27c85fb9f447cb0276858a6a51376a09198/opendbc/car/psa/carcontroller.py),
adapté au protocole et aux protections du port T9. Les sources de référence
et leurs empreintes sont archivées dans
`data/diagnostics/comma/cristianku-lateral-pause-20260920/`.
Ce n'est pas une copie à l'identique de son contrôleur.

Après au moins **12 secondes depuis la confirmation d'activation EPS**, le
contrôleur peut proposer un cycle si le véhicule roule sur une portion droite
et si l'EPS signale une activité conducteur récente. L'autorisation EPS doit
encore être présente. Une pause au clignotant, une intervention au-delà de
±15 ou un arrêt déjà mémorisé ne peuvent pas déclencher ce cycle.

La validation de la portion droite exige 0,5 seconde de données successives,
un modèle récent d'au plus 150 ms, deux lignes fiables et une accélération
latérale actuelle et prévue inférieure ou égale à 0,10 m/s² sur les deux
secondes à venir. La prédiction doit couvrir cette fenêtre sans trous de
plus de 0,5 seconde. Une donnée figée, une courbe prévue, une perte de lignes
ou une intervention remet l'attente à zéro. Si ces conditions ne sont pas
réunies à 12 secondes, le cycle attend ; il n'est pas forcé à l'échéance.

La séquence est la suivante :

1. Le contrôleur émet un marqueur explicite en état 4, facteur et couple nuls.
   Seul le nouveau profil Panda peut reconnaître ce marqueur comme un cycle.
2. Il demande l'état 2, toujours à couple nul, et attend un retour EPS
   physique récent dans l'état 1 ou 2. La trame d'origine reste interceptée
   pendant cette attente bornée pour éviter deux demandes concurrentes.
3. Après ce retour, il prépare l'état 3 pendant 100 ms, puis demande l'état 4
   avec le facteur progressif existant. Il attend une **nouvelle** réponse
   EPS active avant toute restitution du couple.
4. Après confirmation, le contrôleur reprend depuis zéro avec sa rampe
   existante. Une tolérance de 150 ms permet le retour du message entre
   `card` et `controlsd` ; elle exige toujours la validation explicite du
   cycle et ne permet pas de réarmer un arrêt mémorisé.

Le cycle complet a une limite de deux secondes. L'attente de libération EPS
est limitée à 1,5 seconde et celle de nouvelle activation à 0,5 seconde.
Le couple reste nul pendant la transition et le régulateur latéral est
réinitialisé pour éviter l'accumulation de sa correction. L'écran affiche
**« EPS Test Cycle — Steer manually during reactivation »**.
Le suivi RVV conserve son autorisation pendant une transition saine.

Panda contrôle indépendamment le profil, les 12 secondes minimales,
l'activité EPS physique récente, les étapes de la séquence, les délais,
les entrées véhicule et l'absence de couple avant confirmation. Un arrêt
normal sans marqueur reste un arrêt définitif de l'épisode. Une séquence
invalide, une autorisation EPS retirée, un défaut, une interruption conducteur
ou un dépassement de délai impose un réarmement manuel OFF/ON du RVV.
Les défauts communs gardent leur effet sur les deux axes.

Le signal d'activité EPS est une indication liée à l'effort, **pas une preuve
de contact des mains**. Il est utilisé comme condition supplémentaire du
cycle, jamais pour fabriquer une activité ni pour réactiver une autorisation
retirée. Si l'EPS ne reconnaît pas l'activité conducteur, ON n'impose pas de
cycle et ne supprime pas le rappel Peugeot. Aucun bit de présence des mains
n'est forcé.

Les réglages précédents restent : seuil conducteur ±15 inclus, pause sur
clignotant, RVV dès 40 km/h, latéral à partir de 67,1 km/h, plafond 140 km/h,
anticipation RVV et absence d'exigence d'atteindre la cible en deux secondes.
Le couple maximal de commande reste à 10 unités brutes.

## Validation et déploiement

Le manifeste comporte **73 chemins**, dont 28 modifiés ou ajoutés par rapport
à la version précédente. Son SHA-256 est
`822e3ccf66069f184604e8d67ff70ab92d45cbe68230f47a33e5dcc0bc5e1edf`.
La version précédente est identifiée par
`f96167ab0a50fcff63d7b65cfd0c7b76a810aa155601561ab79ebee823887025`.

Les tests locaux comptent **383 tests : 377 réussis et 6 ignorés**. Les deux
bancs C++ passent. Les tests confrontent notamment un cycle complet issu du
contrôleur au Panda compilé, avec maintien du RVV ; ils couvrent les défauts,
les réponses manquantes, les étapes sautées, les données figées, le mode OFF,
la séparation des profils, le retour différé de `controlsd`, l'affichage
natif et l'ordre enregistrement du réglage/redémarrage. Les empreintes des
sources gelées correspondent à celles de la copie utilisée pour les tests.
Ruff F/E9 passe sur les fichiers concernés.

Un premier import de l'interface graphique dans le processus de tests local
a bloqué dans les services graphiques macOS. Ce processus a été arrêté.
La logique de changement de mode a été isolée du rendu graphique et testée
sans ouvrir de fenêtre ; le programme de l'interface a également été contrôlé
en fonctionnement après installation. Aucun essai dynamique de cette séquence EPS sur la 308
n'est établi par les tests logiciels ou la vérification sur USB.

La compilation cible inclut `pandad`, le firmware H7 signé, son bootstub et
`common/params_pyx.so`, qui enregistre le nouveau paramètre. L'installateur
vérifie leurs empreintes et les sources, impose l'alimentation USB avec
harnais débranché et garde une sauvegarde complète de la version précédente.
L'hôte exige la capacité firmware dédiée avant de sélectionner le nouveau
profil ; un ancien firmware ne peut pas être pris pour un firmware compatible.

La compilation et les six suites sur le comma ont terminé avec succès :
121, 179, 17, 45, 6 et 15 tests, soit 383 tests au total, dont 6 ignorés.
Les deux bancs C++ passent également sur l'appareil. Les quatre binaires
compilés et leurs empreintes sont enregistrés dans `build-result.json`.

Après déverrouillage de la clé SSH par l'utilisateur, le contrôle préalable
a confirmé l'alimentation USB, le harnais débranché, l'assistance arrêtée et
les empreintes attendues. L'installation a conservé la sauvegarde complète
`/data/openpilot-before-t9-lateral-20260921T170732Z`, remplacé le dossier actif
et demandé le redémarrage. Son journal est
`/data/t9-lateral-installation-20260921T170732Z.json`.

Les résultats sont enregistrés dans `validation.json` et
`installation-status.json`. Les trois démarrages passent chacun les
30 contrôles de sources, binaires, interface, réglage, processus et télémétrie :

| Démarrage | Réglage | Profil demandé | Contrôles de démarrage firmware | Identifiant de démarrage |
| --- | --- | --- | --- | --- |
| Après installation | OFF | `0x1314` | 3/3 | `ad48d0ef-4d6c-4197-a737-014dbd56501c` |
| Essai du changement | ON | `0x1316` | 4/4 | `b37969da-30b4-42d5-b558-85b5daaa164b` |
| État final | OFF | `0x1314` | 3/3 | `12bb8da0-bf72-441f-9452-06cba65f0845` |

Les changements utilisent la même fonction que le bouton de l'interface,
avec un contrôle USB préalable ; aucun clic tactile n'a été simulé. Les
trois contrôles observent Panda en `noOutput`, harnais débranché, sans trame
CAN émise. Le profil indiqué est celui dérivé du réglage au démarrage : il
n'a pas été activé sur le bus véhicule pendant ces vérifications.

Les journaux ON confirment la capacité EPS dédiée du firmware. Les journaux
ON et OFF final donnent une signature correspondant au binaire attendu
(`74b09c57c99e1654`). Le processus natif final descend du lanceur standard,
dont l'empreinte est vérifiée et dont le journal porte cette même signature.
Ces preuves viennent du démarrage normal ; les outils de vérification
n'ouvrent pas directement Panda et n'émettent pas de commandes CAN.
