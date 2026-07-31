# OpenDiag Learn — conception

## Principe de sécurité

Le module Learn ne transmet aucune trame. Il ne fait que :

- capturer ;
- indexer ;
- corréler ;
- proposer ;
- exporter.

La validation d'une proposition ne doit jamais activer automatiquement son rejeu.

## Heuristiques V0.3

Une requête candidate est retenue lorsqu'une trame :

1. ressemble à une trame ISO-TP Single Frame ou First Frame ;
2. contient un octet de service compatible UDS ;
3. est suivie sous 500 ms d'une réponse positive `service + 0x40`
   ou d'une réponse négative `0x7F service NRC`.

Le score augmente si :

- la réponse existe ;
- l'adresse de réponse vaut `request_id + 8` ;
- le service est un service de lecture connu ;
- le motif apparaît plusieurs fois.

## Améliorations prévues

- réassemblage ISO-TP multiframe complet ;
- fenêtres délimitées précisément par marqueurs ;
- distinction trafic périodique / diagnostic ;
- DBC et ODX publics ;
- clustering par ECU ;
- comparaison multi-session ;
- validation communautaire signée ;
- détection des requêtes fonctionnelles `0x7DF` ;
- prise en charge des adresses étendues.
1. Analyse classique du signal

À partir du fichier audio provenant micro + acceleromètre

spectre FFT ;
spectrogramme ;
MFCC ;
énergie RMS ;
centroid spectral ;
pics fréquentiels ;
régularité des impulsions moteur.

librosa fournit déjà la plupart de ces fonctions.