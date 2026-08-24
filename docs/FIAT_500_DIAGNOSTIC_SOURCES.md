# Fiat 500 type 312 — diagnostic, capteurs et sources ouvertes

Ce document distingue les données réellement observées sur la Fiat 500 de
référence des pistes communautaires. Il ne décrit aucune écriture calculateur :
les lectures constructeur non validées restent désactivées dans le profil.

## Ce que le projet sait lire

### EOBD normalisé, en lecture active bornée

Le profil interroge d'abord la table de PID supportés annoncée par le
calculateur, puis seulement les PID autorisés par
`database/fiat/vehicles/fiat_500_generic.yaml`. Le catalogue comprend notamment :

- régime, charge, température d'eau et d'air, MAP, débit d'air, papillon,
  avance et temps depuis démarrage ;
- corrections de richesse, sondes lambda, purge canister, pression carburant,
  richesse commandée et température catalyseur ;
- tension calculateur, positions redondantes de pédale/papillon, température
  d'huile, débit carburant et couple moteur si l'ECU les annonce ;
- état des moniteurs OBD, norme OBD, exigences d'émissions et type de carburant.

Un PID présent dans le catalogue n'est pas nécessairement disponible sur la
voiture. L'application conserve cette différence et ne fabrique pas de valeur
quand l'ECU ne déclare pas le PID.

### CAN Fiat passif, observé sur la voiture

La capture de référence contient les identifiants étendus 29 bits ci-dessous.
Les fonctions marquées « validées » ont été confirmées par une action
conducteur ; les autres restent candidates même lorsqu'une source ouverte
propose le même décodage.

| Identifiant | Données exposées | Niveau actuel |
| --- | --- | --- |
| `0x0618A001` | régime moteur, charge d'air brute, papillon candidat | régime validé ; autres candidats |
| `0x0218A006` | quatre vitesses de roue | candidat recoupé |
| `0x0810A000` | frein actif et niveau brut | frein actif validé |
| `0x0628A001` | embrayage, demande accélérateur, état combiné | candidat recoupé |
| `0x0A18A000` | porte conducteur, frein à main, contact, démarrage, City, dégivrage | porte validée ; autres candidats |
| `0x0A18A001` | charge électrique brute | candidat, unité inconnue |
| `0x0A18A006` | moteur en marche et vitesse redondante | candidat recoupé |
| `0x0A28A000/006` | vitesses et compteur d'activité redondants | candidats recoupés |
| `0x0C1CA000` | état brut, actif/disponible et condition porte/ceinture du Start&Stop | candidat recoupé |
| `0x0C28A000` | date et heure BCD | candidat auto-cohérent |

Deux corrections importantes ont été tirées de la capture : l'état Start&Stop
vient de l'octet 2 de `0x0C1CA000`, et l'embrayage enfoncé est le bit `0x20` de
l'octet 5 de `0x0628A001`. Le bit `0x10` correspond à la demande accélérateur et
ne doit pas être présenté comme l'embrayage.

## Décodage des défauts

Les catalogues générés et utilisables hors ligne sont :

- 9 533 définitions OBD-II issues d'[OBDex](https://github.com/foerbsnavi/obdex),
  révision `318d156892ac4b00063a95e7d1a38ecaa0b59e36`, licence CC0-1.0 ;
- 100 libellés constructeur Fiat de
  [kierandrewett/obd](https://github.com/kierandrewett/obd/blob/b56a07a2ffc0d574e68e6426ff55418ee4173b7a/dtc_codes/fiat.json),
  licence MIT, initialement collectés depuis dot.report.

Les définitions Fiat sont communautaires, parfois en italien ou en anglais, et
ne sont pas filtrées par modèle, année ou calculateur. Elles sont donc affichées
avec une confiance faible. Un DTC constructeur n'est confirmé qu'après
identification exacte de l'ECU qui l'a émis. Les catalogues PSA/PyPSADiag ne
sont jamais utilisés comme repli sur une Fiat.

L'import est reproductible avec `backend/tools/import_open_dtc_catalogs.py` à
partir de clones locaux placés sur les révisions indiquées.

## Protocole conseillé pour les deux symptômes

### Ralenti irrégulier

1. Lire les DTC enregistrés et en attente avant tout effacement.
2. Faire une capture de trois à cinq minutes à froid, puis moteur chaud, avec
   régime, température d'eau, MAP, charge, corrections court/long terme,
   avance, papillon, lambda et tension calculateur.
3. Poser des marqueurs lors de l'activation de la climatisation, du dégivrage,
   des phares, de la direction assistée et de l'embrayage. Ces charges peuvent
   provoquer une correction normale du ralenti ; leur absence de compensation
   est au contraire un indice utile.
4. Contrôler mécaniquement et électriquement l'admission, le boîtier papillon,
   les durites de dépression, l'allumage et les masses avant d'envisager une
   adaptation.

Le régime cible est géré dynamiquement par l'ECU selon la température et les
charges. Le profil ne contient donc pas de « télécodage pour monter le ralenti » :
modifier une calibration pour masquer une prise d'air, un raté d'allumage ou
une tension instable rendrait le diagnostic moins fiable. Une procédure
d'apprentissage papillon/ralenti ne pourra être ajoutée qu'avec l'identité
exacte du calculateur et une séquence Fiat documentée pour cette variante.

### Démarreur ou Start&Stop intermittent

1. Contrôler la batterie compatible Start&Stop, ses cosses, la masse
   moteur/caisse et la chute de tension pendant une tentative de démarrage.
2. Capturer une tentative réussie puis une tentative refusée sans couper
   l'enregistrement. Marquer : clé tournée, bruit de relais, démarreur qui
   tourne ou non, voyant antidémarrage et état de l'embrayage.
3. Comparer dans le replay la tension OBD, l'embrayage, le frein, le contact, la
   phase démarrage, le moteur en marche et l'octet brut Start&Stop.
4. Lire les DTC moteur et en attente. Les calculateurs Body Computer et combiné
   ne doivent être interrogés activement qu'après validation de leurs adresses
   sur cette voiture.

Le fait qu'un nouveau cycle de clé débloque parfois la situation peut venir de
la batterie, du démarreur/relais, d'une masse, du contacteur d'embrayage, de
l'antidémarrage ou d'une condition Start&Stop non satisfaite. La capture doit
permettre de séparer ces hypothèses ; elle ne suffit pas encore à autoriser une
écriture ou un reset Start&Stop.

## Sources et projets intéressants

| Projet / document | Utilité pour la Fiat | Précaution |
| --- | --- | --- |
| [Notes CAN Fiat 500C 1.2 2010](https://github.com/P1kachu/talking-with-cars/blob/master/notes/fiat-500.txt) | Carte la plus proche du véhicule : CAN 29 bits, destinations ECU, trames et quelques DID | source communautaire sans garantie de compatibilité ECU |
| [Manuel officiel Fiat 500 2010](https://aftersales.fiat.com/eLumData/EN/00/150_500/00_150_500_603.81.684_EN_01_02.10_L_LG/00_150_500_603.81.684_EN_01_02.10_L_LG.pdf) | Conditions et témoins Start&Stop, contrôles conducteur | manuel utilisateur, pas une table de diagnostic |
| [Cartographie CAN Fiat/SCS](https://fruba.pl/canbus/can-messages/) | Éclairage, portes, niveau de carburant et états moteur sur familles Fiat | B-CAN familial, non observé sur le bus rapide de la capture |
| [PyPSADiag](https://github.com/Barracuda09/PyPSADiag) | Bonne structure de fichiers ECU, zones et interface | vise PSA/Stellantis ; aucune adresse PSA ne doit être copiée sur la Fiat |
| [abarth-dashboard](https://github.com/EmilxGames/abarth-dashboard/blob/main/src/obd/pids.cpp) | Exemples de PID Mode 22 Abarth, dont température d'huile | pistes désactivées : une Abarth récente n'est pas une 500 1.2 IAW5SF 2010 |
| [CANBUS_RevEng](https://github.com/jeby/CANBUS_RevEng) | Méthode de captures une action à la fois avec SocketCAN | rester en écoute seule sur la voiture |
| [CAN Commander](https://github.com/MatthewKuKanich/CAN_Commander) | Découverte OBD, capture et visualisation DBC | ne pas utiliser les commandes actives sans vérification |
| [BACCAble](https://github.com/gaucho1978/BACCAble) | Recherche Abarth sur plusieurs bus, notamment Start&Stop | projet actif/injecteur : utile comme lecture, pas comme séquence à rejouer |

La recherche d'un projet nommé exactement « PyDiagBox » n'a pas trouvé de base
Fiat exploitable. Le projet proche est PyPSADiag, qui annonce explicitement une
cible PSA/Stellantis. Ici, seule son organisation générale a servi de modèle.

## Lectures constructeur laissées désactivées

La source Fiat 500 communautaire décrit les destinations moteur `0x10`, ABS
`0x28`, direction `0x30` et Body Computer `0x40`, ainsi que les DID direction
`0x0948` et ABS `0x0885/0x0889`. Ils sont consignés dans le profil comme pistes
en lecture seule, mais aucune requête automatique n'est émise tant que
l'identité du calculateur, le routage ISO-TP et la réponse positive n'ont pas été
validés sur le véhicule.
