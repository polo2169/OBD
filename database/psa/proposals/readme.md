> Implémenté dans `backend/app/learn/replay.py`
> (`_compute_can_fuel_consumption` / `_summarize_can_fuel_consumption`),
> exposé sur `ReplaySample.can_fuel_rate_lph` /
> `can_instant_consumption_l_100km` / `can_trip_fuel_l` et
> `ReplayData.can_average_fuel_consumption_l_100km` /
> `can_trip_fuel_total_l`, affiché dans l'onglet Replay à côté de
> l'estimation par flotteur existante. Testé par
> `test_can_derived_fuel_consumption_handles_wraparound_and_smoothing`
> (backend/tests/test_learn.py), qui rejoue les exemples chiffrés
> ci-dessous.

Comment fonctionne la consommation sur la 308

La Peugeot ne transmet pas directement une valeur du type « 6,4 L/100 km ». Le calculateur moteur transmet un compteur de volume de carburant consommé.

La trame importante est :

CAN ID : 0x488
Nom DBC : Dat_CMM
Période : 100 ms

Dans OpenDBC, le deuxième octet correspond à :

P021_Com_volFlCons
facteur = 80 mm³ / unité

Donc avec :

488  77 19 6A 84 1E 7C FF 51
        ^^

0x19 n'est pas 25 L/100 km.

C'est un compteur :

raw = 0x19 = 25

1 tick = 80 mm³
       = 0,00008 L

Dans tes captures, on voit bien ce compteur avancer puis reboucler, par exemple FD → 00.

Sur ta voiture, les valeurs observées vont de :

0 ... 254

puis :

254 → 0

Donc on utilise un modulo 255.

1. Calculer combien de carburant a été consommé

Par exemple :

ancien compteur = 100
nouveau compteur = 103

Alors :

delta = 3 ticks

3 × 0,00008 L
= 0,00024 L

soit 0,24 mL consommé pendant l'intervalle.

Avec rebouclage :

ancien = 254
nouveau = 1

on fait :

delta = (1 - 254 + 255) % 255
      = 2 ticks

La formule intégrée au YAML est donc :

delta_ticks =
(current_raw - previous_raw + 255) % 255
2. Transformer ça en L/h

Il faut ensuite tenir compte du temps.

Si pendant 1 seconde le compteur avance de 20 ticks :

20 × 0,00008
= 0,0016 L

Donc :

0,0016 × 3600
= 5,76 L/h

La formule est :

fuel_rate =
delta_liters × 3600 / delta_time_seconds

C'est le débit carburant réel calculé.

3. Passer de L/h à L/100 km

On récupère simultanément la vitesse sur :

CAN 0x38D
VITESSE_VEHICULE_ROUES

Les deux premiers octets donnent :

vitesse = uint16_be(bytes 0-1) × 0,01 km/h

C'est également la définition du DBC PSA.

Supposons :

Débit carburant = 5,76 L/h
Vitesse         = 80 km/h

Alors :

Conso = 5,76 / 80 × 100

      = 7,2 L/100 km

Donc :

L/100 km =
(L/h / km/h) × 100
4. Pourquoi il faut lisser

0x488 arrive environ toutes les 100 ms, mais un tick représente déjà :

80 µL

Si on calculait la consommation sur seulement 100 ms :

0 tick → 0 L/h
1 tick → 2,88 L/h
2 ticks → 5,76 L/h
3 ticks → 8,64 L/h

L'affichage sauterait donc constamment.

J'ai configuré dans le YAML une fenêtre glissante recommandée de :

1500 ms

avec une plage raisonnable :

1000–2000 ms

Ça donnera un affichage beaucoup plus proche de ce qu'on attend d'un ordinateur de bord.

5. Cas intéressant : pied levé

Si tu lèves complètement le pied et que l'ECU coupe l'injection :

0x488 compteur avant : 42
0x488 compteur après : 42

Alors :

delta = 0
fuel = 0
débit = 0 L/h
conso = 0 L/100 km

C'est justement pour ça que dans ta première petite capture 0x488 semblait « bloqué » : tu étais en décélération.

6. À l'arrêt

À :

vitesse = 0 km/h

on ne peut évidemment pas faire :

L/h / 0 × 100

Donc j'ai prévu :

>= 5 km/h → L/100 km
< 5 km/h  → L/h

Par exemple au ralenti :

0,7 L/h

plutôt qu'une valeur absurde en L/100 km.

7. Consommation moyenne

J'ai aussi ajouté dans le YAML le compteur de distance de 0x38D :

DISTANCE_ROUES
bytes 2-3
facteur = 0,1 m

Cela permet de garder :

carburant trajet = somme des incréments 0x488
distance trajet  = incréments du compteur 0x38D

puis :

Conso moyenne =
litres consommés
---------------- × 100
distance en km
Les trois trames à retenir
0x208  Dyn_CMM
 ├─ régime moteur
 └─ position accélérateur

0x38D  dynamique ABS
 ├─ vitesse véhicule
 └─ distance roues

0x488  Dat_CMM
 └─ compteur volume carburant

0x208 n'est d'ailleurs pas indispensable au calcul de consommation : régime et pédale servent surtout à comprendre et valider le comportement. Le calcul lui-même repose essentiellement sur 0x488 + 0x38D + temps.




----------------Km actuel voiture-----------------
CAN ID : 0x552
octets : 5 à 7
format : entier non signé 24 bits, big-endian
unité  : 1 km

La documentation PSA décrit précisément ce champ de IS_DAT4_BSI_552 comme le « kilométrage absolu », sur 24 bits, positions 5 à 7.

Dans ta capture, au début :

552  0A 7E A3 37 01 9A 0F FE
                  └───────┘
                   01 9A 0F

0x019A0F = 104 975 km.

a ajouter !