1. Les projets / sources importantes
Projet	Véhicule	Modification	Résultat
Driver.top – ACC caméra	Peugeot 2008 II Active 2021	Ajout caméra + câblage BSI + télécodage	✅ ACC caméra, freinage/accélération, distances, LKA, panneaux
Driver.top – CVM3 retrofit	Peugeot Rifter 2019	Ajout CVM3 provenant d'un autre véhicule + flash + télécodage	✅ LKA, TSR, HBA ; ❌ ACC au départ
Driver.top – suite Rifter	Peugeot Rifter	Remplacement ESP incompatible	✅ ACC fonctionnel après changement ESP
Forum Peugeot – CVM2 → CVM3	PSA avec radar G3 + ACC + CVM2	Remplacement CVM2 par CVM3 pour LPA	Projet explicitement en cours en mai 2026
Forum Peugeot – télécodage CVM	Plusieurs PSA	Reverse engineering CVM2/CVM3	Adresse CAN, zones 2100/2101, configurations
PyPSADiag	PSA/Stellantis	Diagnostic/télécodage CAN open-source	Lecture/écriture zones, CAL/ULP
arduino-psa-diag	PSA/Stellantis	Diagnostic UDS/KWP	Base technique utilisée par la communauté
2. Le projet Peugeot 2008 II : preuve qu'un ACC caméra existe

C'est ton lien :

Peugeot 2008 II – retrofit ACC par caméra

La voiture est une 2008 II Active achetée neuve en 2021, sans caméra avant. Le propriétaire explique qu'il avait simplement l'emplacement prévu dans le pare-brise. Il ajoute la caméra, tire son câble jusqu'au connecteur du BSI puis fait télécoder les calculateurs à distance.

Le résultat annoncé est très clair :

Caméra ajoutée
     │
     ├── ACC
     │    ├ maintien distance
     │    ├ freinage
     │    ├ accélération
     │    └ 3 distances
     │
     ├── LKA / "Ping-Pong"
     ├── lecture panneaux
     └── HBA possible

L'auteur décrit explicitement le véhicule qui freine lorsqu'il se rapproche de la voiture précédente et réaccélère lorsque celle-ci accélère.

C'est donc une preuve communautaire particulièrement intéressante d'un ACC PSA utilisant la caméra sans installation de radar dans ce retrofit.

Ce projet n'est toutefois pas un G2 → G3, puisque la voiture n'avait pas de caméra au départ.

3. Le projet Rifter : probablement le plus instructif

Premier article :

Peugeot Rifter – ajout d'une CVM3

L'auteur dit explicitement :

installation d'une caméra CVM3 et télécodage à distance.

Il part d'un Rifter qui ne possède pas ces équipements.

Il achète une CVM3, le faisceau et une commande de régulateur adaptée. Très intéressant : il explique avoir acheté une caméra qui n'était pas prévue pour son modèle de voiture et avoir dû la reprogrammer/flasher, puis configurer caméra, BSI, NAC, combiné et d'autres calculateurs.

Après cette première phase :

CVM3 retrofit
     │
     ├── ✅ HBA
     ├── ✅ LKA
     ├── ✅ panneaux
     ├── ✅ détection voitures
     ├── ✅ affichage distance
     │
     ├── ❌ ACC réel
     └── ❌ freinage automatique

La caméra voyait pourtant les véhicules et le combiné affichait les informations de distance.

Et ensuite ils ont découvert la cause.

4. Le Rifter : l'ESP était le verrou

Suite du projet :

Rifter – ACC fonctionnel après remplacement ESP

Après neuf mois de recherche, ils découvrent que le bloc ESP monté d'origine ne permet pas le freinage autonome nécessaire. Ils trouvent donc un autre bloc ESP compatible, le montent, puis terminent la configuration du BSI.

Résultat :

CVM3
  +
BSI configuré
  +
ESP compatible ACC
  ↓
✅ ACC
✅ maintien distance
✅ accélération
✅ freinage

L'auteur dit très clairement que le plus gros problème était :

le bloc ESP qui ne supportait pas le freinage sans intervention du conducteur.

C'est extrêmement important pour notre projet : la caméra seule ne garantit pas que l'ACC fonctionnera.

5. Et quelqu'un tente précisément CVM2 → CVM3

Voilà probablement le message le plus proche de ce qu'on cherche :

Forum Peugeot – projet CVM2 → CVM3, mai 2026

Le 21 mai 2026, ezejp explique :

“My factory config has radar g3, ACC, cvm2 and hoping to update to cvm3 to test LPA”

Autrement dit :

Configuration usine

Radar G3
+
ACC
+
CVM2
   │
   ▼
objectif
CVM3
   │
   ▼
LPA

Donc oui, le remplacement CVM2 → CVM3 est actuellement expérimenté par la communauté PSA.

Par contre, le membre n'a pas encore publié de compte rendu définitif disant que tout fonctionne.

6. CVM2 et CVM3 utilisent une architecture diagnostic très proche

C'est l'une de nos découvertes les plus intéressantes.

Sur le forum Peugeot, l'adresse diagnostic utilisée pour les CVM est :

TX : 0x74A
RX : 0x64A

La grosse différence est la zone de configuration principale.

CVM2
>74A:64A
1003
222100

soit :

zone 2100
CVM3
>74A:64A
1003
222101

soit :

zone 2101

Un membre explique explicitement :

“2101 zone for CVM3 type camera. 2100 zone for CVM2 type camera.”

C'est une excellente nouvelle : la G3 reste dans le même écosystème diagnostic PSA, ce n'est pas un calculateur totalement étranger à la génération précédente.

7. CVM3 et câblage : probablement 6 fils / deux CAN

Sur cette même discussion, ezejp confirme :

“I do have a CVM3 with 6 wires”

et un autre membre indique que les caméras disposant du jeu complet de fonctions peuvent utiliser deux CAN, ce qui explique la présence de plus de quatre fils.

On arrive donc vraisemblablement à quelque chose de ce genre :

CVM G2                     CVM G3
────────                   ────────

+12 V                      +12 V
GND                        GND

CAN 1 H                    CAN 1 H
CAN 1 L                    CAN 1 L

                           CAN 2 H
                           CAN 2 L

~4 fils                    ~6 fils

Mais nous n'avons pas encore suffisamment de documentation fiable pour attribuer les numéros exacts des pins. C'est une des choses qu'il reste absolument à déterminer avant de brancher une G3.

8. Référence G3 particulièrement intéressante : 9842997780

Cette référence revient plusieurs fois dans les discussions.

Un propriétaire indique explicitement avoir :

9842997780

et confirme ensuite qu'il possède bien une CVM3. Il explique également que Diagbox lui affiche une autre référence, 9842725080, ce qui montre que la référence physique et la référence software/calibration peuvent être différentes.

Cette caméra est donc une cible intéressante pour nos recherches :

9842997780
     │
     └── CVM3

Mais attention : ça ne signifie pas qu'une 9842997780 récupérée au hasard sera immédiatement compatible avec une 308 T9.

Le projet Rifter démontre justement que le firmware/calibration associé au véhicule donneur compte énormément.

9. HBA et zone 2101

On a même un exemple concret de configuration CVM3.

Un membre indique :

2101 = 04 B8 FD

avec HBA actif.

ezejp confirme ensuite avoir appliqué cette configuration et avoir testé le HBA avec succès : extinction des pleins phares à l'approche d'un autre véhicule, retour automatique, etc.

Donc le 2101 n'est pas seulement théorique : la communauté sait déjà modifier certains paramètres CVM3.

10. ACC sans radar : nuance importante

Le forum Peugeot contient des témoignages un peu contradictoires.

Sur une discussion de décembre 2023, certains membres pensent initialement qu'un radar est obligatoire. D'autres indiquent qu'une CVM3 peut assurer certaines fonctions seule. Le cas 9842997780 y est également discuté.

Le projet Driver.top 2008 de 2025 est beaucoup plus intéressant parce que l'auteur décrit concrètement son retrofit « adaptive cruise control by camera » et son comportement de freinage/accélération, sans décrire l'ajout d'un radar.

Donc notre état actuel est :

                 CVM3
                   │
           ┌───────┴────────┐
           │                │
       radar + CVM       caméra seule
           │                │
          ACC             ACC possible
                         sur certaines
                         configurations

Il faudra néanmoins comprendre quelle version logicielle de CVM3 et quelle architecture ESP/BSI permettent cette variante caméra seule.

11. Ta 308 T9 : le scénario envisagé

L'idée n'est donc plus irréaliste :

308 T9
│
├── CVM G2 actuelle
│
│        ↓
│
├── remplacement
│
│        ↓
│
├── CVM G3
│
├── télécodage 2101
│
├── configuration BSI
│
├── configuration combiné/NAC
│
├── éventuellement second CAN
│
└── vérification ESP
         │
         ▼
     compatible ACC ?

Le gros point d'interrogation est maintenant l'ESP.

Le projet Rifter montre précisément qu'on peut avoir :

CVM3 fonctionnelle
+ voitures détectées
+ LKA fonctionnel
+ affichage ACC fonctionnel

MAIS

ESP incompatible
      ↓
ACC impossible

12. Comment vérifier ton ESP

C'est pourquoi on était arrivé à l'idée de lire ton ESP avant d'acheter quoi que ce soit.

On veut récupérer au minimum :

F080 = identification / référence
F0FE = logiciel / calibration
2100/2101 = configuration

puis chercher une 308 T9 équipée d'ACC usine possédant le même hardware.

L'objectif est de déterminer si :

TON ESP                     308 T9 ACC usine
────────                    ────────────────

Hardware A         =        Hardware A
Software famille A =        Software famille A

             ↓

probablement télécodable

ou si on obtient :

Hardware A                  Hardware B
    ↓                           ↓
ESP standard                ESP ACC

             ↓

remplacement probablement nécessaire
13. Les outils open-source que nous avons retrouvés

PyPSADiag est probablement le projet logiciel le plus intéressant pour continuer. Il est spécifiquement destiné à envoyer des trames de diagnostic sur les véhicules PSA/Stellantis. Il sait notamment lire des zones, sauvegarder les zones en CSV, écrire des zones modifiées et même flasher des fichiers CAL/ULP.

GitHub – PyPSADiag

Et il repose en partie sur le travail de arduino-psa-diag, qui est la grosse base communautaire PSA pour envoyer des diagnostics UDS/KWP sur CAN.

GitHub – arduino-psa-diag

Ces deux projets sont directement utiles pour notre objectif puisque PyPSADiag connaît déjà les concepts de zones ECU, configurations et fichiers CAL.

Où on en est

Je résumerais notre niveau de certitude comme ça :

Élément	État
CVM2 et CVM3 peuvent être diagnostiquées sur PSA	✅ confirmé
CVM2 utilise principalement 2100	✅ confirmé
CVM3 utilise principalement 2101	✅ confirmé
CVM3 6 fils existe	✅ confirmé
9842997780 est utilisée comme CVM3	✅ confirmé communauté
CVM3 peut être rétrofitée sur une PSA qui n'en avait pas	✅ confirmé
Caméra venant d'un autre modèle peut nécessiter un flash	✅ confirmé
LKA/HBA/TSR fonctionnent après retrofit CVM3	✅ confirmé
ACC caméra sans radar existe sur certaines PSA	✅ retour concret 2008
ESP compatible est indispensable pour l'ACC	✅ confirmé par Rifter
Quelqu'un expérimente explicitement CVM2 → CVM3	✅ confirmé, mai 2026
CVM3 plug-and-play sur 308 T9	❌ pas démontré
Pinout G2 ↔ G3 identique	❓ à trouver
Ton ESP est compatible ACC	❓ à vérifier
Firmware G3 approprié à la 308 T9	❓ à identifier
Valeurs exactes BSI/ESP/CVM pour retrofit T9	❓ à reconstruire
Les trois prochaines étapes les plus logiques

1. Identifier ton ESP en récupérant F080, F0FE et ses zones de configuration.

2. Retrouver le pinout exact CVM G2 de 308 T9 et CVM G3 9842997780, pour savoir si le connecteur peut être adapté et où va éventuellement le deuxième CAN.

3. Trouver un dump complet d'une PSA avec CVM3 + ACC caméra sans radar — idéalement la 2008 II du projet Driver.top — et comparer CVM 2101 + BSI + ESP avec ta configuration.

À mon sens, le projet Rifter + le projet 2008 + le message CVM2→CVM3 de mai 2026 sont les trois sources les plus importantes que nous ayons trouvées. Ensemble, elles montrent que l'idée est techniquement crédible, tout en identifiant précisément les trois obstacles : firmware CVM3, câblage et ESP.