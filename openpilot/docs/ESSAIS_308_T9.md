# Prochains essais — direction à 50 km/h, puis clignotant

Ordre des essais : conserver la version actuelle, vérifier
le pilotage à partir de 50 km/h, puis étudier le changement de voie demandé
au clignotant. Le plancher actif de 67,1 km/h et la pause au clignotant restent
en place dans les sources publiées.

## Distinguer les deux états

| Signal | États utiles dans le décodage actuel |
|---|---|
| Demande LKA `0x3F2` | 2 : prêt/relâché ; 3 : autorisé/préparation ; 4 : demande active |
| Retour EPS `0x495` | 0 : non autorisé ; 1 : autorisé ; 2 : disponible ; 3 : actif ; 4 : défaut |

Un état 3 de la demande LKA n’équivaut pas à l’état 3 du retour EPS.
L’absence de correction Peugeot ne prouve ni l’impossibilité ni la possibilité
d’une commande Openpilot.

## 1. Pilotage sous 67,1 km/h

Préparer un profil d’essai distinct, d’abord testé hors véhicule. Il doit
conserver l’autorisation physique EPS, les limites de couple et de rampe,
les contrôles CAN, la surveillance conducteur et la reprise manuelle.
Les barrières Python, transport natif et Panda doivent utiliser le même profil.

Le premier essai physique concerne une piste fermée adaptée, autour de
55–60 km/h, avec mesure synchronisée des éléments suivants :

- vitesse CAN et état EPS avant et après la demande ;
- commande effectivement émise et éventuels rejets Panda ;
- nouvel acquittement EPS après la demande ;
- réponse de la direction, effort conducteur et trajectoire réelle ;
- relâchement et reprise manuelle, sans réactivation inattendue.

Le critère de succès est une commande acceptée et une réponse physique
cohérente, reproductible, dans les limites prévues. Un passage à l’état EPS 3
ou une commande présente dans `sendcan` ne suffit pas seul.
La proximité de 50 km/h demande ensuite une mesure des seuils et de leur
hystérésis ; le seuil de disponibilité doit être mesuré. Une vitesse falsifiée sur le CAN partagé ne fait pas
partie de ce protocole.

## 2. Direction pendant le clignotant

À une vitesse déjà validée, distinguer la baisse d’autorisation usine,
la pause volontaire du logiciel/Panda et un éventuel refus propre à l’EPS.
Mesurer l’ordre des transitions d’état et du signal de clignotant.

Le succès de l’essai basse vitesse ne valide pas ce deuxième cas. Un profil
borné dédié et ses tests doivent précéder un essai physique sur piste fermée.
Les mesures doivent établir l’acceptation pendant le clignotant, une réponse
physique limitée et le maintien de la priorité conducteur.

## 3. Changement de voie demandé après deux secondes

Le comportement souhaité est un seul changement de voie par demande :

1. Le conducteur vérifie rétroviseurs et angle mort, puis maintient un seul
   clignotant pendant deux secondes.
2. À l’échéance, le système vérifie une voie voisine du bon côté, dans le même
   sens, et une perception fraîche suffisamment fiable. Marquages, accotement,
   voie opposée et ligne continue doivent être départagés ; des lignes visibles
   ne suffisent pas à prouver la possibilité de changer de voie.
3. Une condition manquante refuse cette demande. Une voie apparaissant plus
   tard ne déclenche pas de départ retardé ; une nouvelle demande est nécessaire.
4. La trajectoire rejoint progressivement la voie voisine, puis se recentre.
   Le clignotant maintenu ne déclenche pas un deuxième changement.
5. Le rabattement exige une nouvelle demande. Le conducteur conserve la reprise
   manuelle à tout moment.

Valider d’abord cette décision sur les vidéos/replays, puis en observation
sans nouvelle commande de direction. Inclure les clignotants brefs, warnings,
annulations avant départ, données périmées, pertes de perception et voies ambiguës.
Le traitement d’une annulation ou d’une perte de perception pendant la
manœuvre doit être défini et testé avant le contrôle physique.

L’existence d’une voie ne garantit pas qu’elle est libre. La détection du trafic
latéral/arrière et les limites des éventuels capteurs doivent être connues ;
la vérification du conducteur fait partie de la demande de manœuvre.
