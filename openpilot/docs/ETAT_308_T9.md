# Port Peugeot 308 II T9 — comportement des sources

## Comportement du code

| Fonction | Comportement |
|---|---|
| Direction | Disponible dans l’enveloppe de 67,1 à 140 km/h, avec autorisation EPS et conditions véhicule valides |
| RVV | Disponible dès 40 km/h ; agit sur la consigne Peugeot, sans commande du frein de service |
| Intervention au volant | Pause au-delà de ±15 raw ; ±15 reste accepté |
| Clignotant ou warnings | Relâchement latéral, couple commandé nul ; accepte les deux ordres CAN |
| Reprise après pause | 300 ms de modèles successifs frais et lignes plausibles, puis séquence EPS et rampe |
| Commande latérale | Limites expérimentales ±20 raw et 0,82 m/s² ; rampe et fraîcheur contrôlées indépendamment |
| Distance RVV locale | 2,0 s plus 5 m fixes |
| Anticipation RVV | De 4 s jusqu’à 80 km/h à 6 s à 130 km/h ; sans exigence d’atteindre la cible en deux secondes |
| Cycle EPS optionnel | Échéance à 12 s d’activation confirmée ; anticipation dès 3 s selon la courbure actuelle et prévue |
| Upload maison optionnel | Inactif sans configuration privée ; fichiers terminés, Wi-Fi, appareil hors conduite |

Le cycle EPS exige la séquence `3 → 2 → 0 → 1/2 → 3`, un couple
nul pendant la transition, un délai borné et un nouvel acquittement avant
la reprise. Il ne démontre pas la suppression du rappel Peugeot « mains sur
le volant ». Un défaut ou un arrêt mémorisé conserve le réarmement manuel
prévu par le port.

## Ce qui reste à démontrer

- L’acceptation et la réponse réelle de la direction sous 67,1 km/h.
- L’acceptation des commandes pendant le clignotant.
- La fiabilité de la détection d’une voie voisine autorisée pour la manœuvre.
- Le changement de voie temporisé de deux secondes, demandé et surveillé par
  le conducteur : cette fonction n’est pas implémentée dans le contrôle actif.
- Le comportement physique du calendrier EPS et du réglage RVV.

Le [protocole d’essais](ESSAIS_308_T9.md) commence par la plage 50–67 km/h,
puis le clignotant à une vitesse déjà validée. Les sources ne permettent pas
de déduire quelle version est installée sur un appareil.
