# Seuil conducteur ±15, RVV dès 40 km/h et anticipation du rapprochement

> Rapport historique de la version immédiatement antérieure au cycle EPS.
> Le seuil, les pauses et le RVV décrits ici sont conservés ; le cycle EPS est
> maintenant disponible en option. Voir
> [l'état partageable](COMMA_308_T9_RELEASE_2026-09-21.md).

État : **version installée et vérifiée après redémarrage sur USB**.
La version précédente est conservée dans
`/data/openpilot-before-t9-lateral-20260920T231926Z`.
Les éléments de preuve sont dans `data/runtime/t9_driver15_rvv40_20260921/`.

## Fonctionnement

Le seuil d'intervention conducteur passe à **±15 inclus** : la pause latérale
commence à ±16 unités brutes. Les clignotants et warnings conservent leur
fonction de pause. La reprise conserve la validation des deux lignes pendant
0,5 seconde et exige une autorisation EPS restée continue, comme décrit dans
le [rapport de pause latérale](COMMA_308_T9_PAUSE_LATERALE_2026-09-21.md).
Le couple maximal commandé reste à 10 unités brutes.

Dans le profil à axes séparés `0x1314`, le **RVV est disponible dès 40 km/h**.
Le plancher latéral reste à 67,1 km/h. Une admission sous ce plancher permet
donc le RVV seul, y compris en attente d'une cible ; cette attente ne demande
aucune modification de consigne. Accélérer au-delà de 67,1 ne réarme pas à
lui seul le latéral : il faut un OFF/ON physique du RVV. Le passage sous
40 km/h coupe les deux axes. Le plafond reste à 140 km/h.

La baisse de consigne est bornée à **1 km/h par 100 ms**, contre 500 ms
auparavant. La hausse conserve 1 km/h par 500 ms. Panda applique ces bornes
sur les trames réellement reçues, sans rattrapage des pas manqués ; la cadence
CAN peut donc ralentir ces rampes. Le chemin historique de proposition
d'accélération hors ligne conserve sa cadence de 500 ms.

La distance souhaitée normale reste `5 + 2 × vitesse_ego` en mètres, avec
la vitesse en m/s. Pour une cible dont on se rapproche, le calcul de consigne
utilise aussi la distance qui serait parcourue en **4 secondes de vitesse
relative actuelle** : `distance_anticipée = distance_normale + 4 × rapprochement`.
Cela rend la réduction plus précoce lorsque la perception fournit déjà une
cible fiable. Ce n'est ni une extension de la portée du modèle, ni une
exigence d'atteindre une vitesse en quatre secondes. L'ancienne exigence
d'atteindre la cible en deux secondes reste supprimée.

Une entrée nouvellement rendue possible par cette anticipation exige au
moins 200 ms de données satisfaisantes et trois nouveaux horodatages modèle.
Une détection isolée ne suffit pas. Après une réduction, une remontée de
consigne attend une seconde continue avec un rapprochement inférieur ou égal
à 0,5 m/s et une distance au moins égale à la distance normale. Une baisse
du plafond par le conducteur reste prioritaire et immédiate.

Les contrôles de fraîcheur, de confiance, de calibration, de pédales, de
plafond conducteur, de parité CAN et les arrêts mémorisés sont conservés.
Une situation critique ou une cible demandant une vitesse inférieure à
l'enveloppe du RVV interrompt toujours le suivi. Ce système ajuste un RVV
déjà engagé ; il ne commande pas les freins.

## Essais avec un camion

Les sept derniers trajets ont fourni 54 segments fermés, soit 547 440 320
octets de journaux dont les empreintes ont été vérifiées. Deux segments de
fin de trajet contiennent un dernier message tronqué (`32--26` et `37--13`) ;
ils sont exclus des statistiques sur les segments complets. L'analyse et
les originaux sont dans `data/diagnostics/comma/truck-rvv-20260921/`.

La vidéo du trajet `00000037--abdee54f52`, segment 7, montre un camion sur
l'approche étudiée. Le log donne environ 132 km/h pour la voiture et une
consigne conducteur de 133 km/h. La première détection atteignant 0,75 de
confiance apparaît vers 512,874 s à 101,6 m, puis devient intermittente.
Le suivi commence réellement vers 516,015 s. La vitesse cible estimée
fluctue ; elle ne permet pas de confirmer indépendamment les 90 km/h
annoncés par l'utilisateur. La comparaison exacte avec son ralentissement
manuel de 130 à 90 n'est donc pas établie.

Les échos CAN montrent une consigne descendant seulement de 133 à 124 km/h
entre 516,708 et 521,211 s, puis remontant à 125 pendant le rapprochement.
À 522,068 s, la confiance cible passe sous le seuil et arrête le suivi.
À 522,111 s, la consigne Peugeot de 133 km/h réapparaît. La vitesse réelle
ne baisse qu'à environ 127 km/h sur cette fenêtre. Cette restitution de
consigne est une cause distincte de reprise de vitesse.

Le rejeu applique les anciens et nouveaux observateurs aux mêmes détections,
états d'engagement enregistrés et trames physiques `0x50E`. La première
prise en charge reste identique à 516,108 s dans ce rejeu : les détections
initiales ne sont pas assez continues pour être utilisables. La consigne
recalculée passe sous 125 km/h à 517,409 s, contre 521,111 s avec l'ancienne
version, soit **3,70 secondes plus tôt**. Son minimum avant la perte de
cible est de 97 km/h, contre 124. Il s'agit de consignes, pas d'une vitesse
réelle prédite.

![Comparaison des consignes et de la confiance cible](../../data/diagnostics/comma/truck-rvv-20260921/truck-command-comparison.png)

Le rejeu conserve la trajectoire et la perception enregistrées ; il ne
simule pas leur modification sous l'effet d'une autre commande. Il modélise
la rampe aux arrivées CAN physiques et ne reproduit pas exactement les
arrivées SPI. Les bornes de rampe sont vérifiées séparément contre le Panda
compilé. Le maximum de distance observé avec confiance suffisante dans les
segments complets est d'environ 112 m ; cela ne définit pas une portée
garantie ou une limite matérielle.

**Limite restante : la perte de cible après prise en charge rend toujours
la consigne Peugeot initiale, et peut provoquer une reprise d'accélération.**
La nouvelle rampe ne change pas ce comportement de restitution. L'annulation
physique du RVV sur cette perte n'est pas validée par ces captures. La
version améliore l'anticipation et la baisse tant que la cible reste valide ;
elle ne garantit pas un ralentissement de 130 à 90 sans freinage, ni un
suivi fiable à plus longue distance.

## Cycle EPS de cristianku

**Le cycle périodique de désactivation/réactivation EPS n'est pas installé.**
La comparaison de son cycle et de ses états 2/3/4 est consignée dans le
[rapport précédent](COMMA_308_T9_PAUSE_LATERALE_2026-09-21.md#vérification-de-cristianku).
La pause installée garde l'autorisation EPS existante avec un couple nul.
Un retrait réel de l'EPS reste un arrêt latéral mémorisé, avec réarmement
physique OFF/ON du RVV. Aucune indication de tenue du volant n'est forcée.

## Provenance et vérifications

Le manifeste comporte 66 chemins, dont 24 modifiés par rapport à la version
installée précédente. Son empreinte est
`f96167ab0a50fcff63d7b65cfd0c7b76a810aa155601561ab79ebee823887025`.
Le manifeste précédent est
`51974ed47ea05be5e9d5865ccfdb8212a9a140762e0ec091353eb09a3606bb91`.
L'archive transférable a pour empreinte
`0587cee40dc095bd7761cda82ab1377c201d1257c8dc8fce062f17bb288c9f8c`.

Le fichier Panda présent initialement dans l'espace de travail contenait
à la fois un seuil conducteur 15 et un maximum de commande 15. Il est
archivé intégralement dans `preexisting-psa_t9.h`. Le paquet ajuste le seuil
conducteur demandé et conserve le maximum de commande 10, cohérent avec le
contrôleur hôte et la version précédemment installée. Les autres modifications
préexistantes du dépôt ne sont pas embarquées par cette mise à jour.

Les 365 tests locaux ont terminé : **359 réussis et 6 ignorés**. Les 66
empreintes de sources gelées correspondent à la copie testée. Ruff F/E9
passe sur les fichiers concernés. Les tests couvrent notamment ±15/±16,
les bornes 39,99/40 et 67,09/67,1 km/h, le maintien du RVV seul en attente,
les interruptions latérales, les nouvelles rampes, le filtrage d'acquisition,
la stabilité de remontée et les commandes confrontées au Panda compilé.

La compilation sur le comma a produit le programme natif `pandad`, le firmware
Panda H7 signé et son bootstub. Les six suites exécutées sur l'appareil comptent
121, 165, 17, 44, 6 et 12 tests : **359 réussis, 6 ignorés** au total. Les deux
bancs C++ de commande et de transport passent également. L'installateur a
vérifié les sources et binaires, puis a confirmé l'alimentation USB, le
harnais débranché et le mode `noOutput` avant la permutation des dossiers.

Les **27 contrôles après redémarrage passent** : 24 contrôles des sources,
binaires, paramètres, services et de l'enregistrement, plus 3 contrôles du
démarrage natif et des capacités du firmware. Le nouveau démarrage porte
l'identifiant `2b5e460c-2356-4818-875d-4f0f6491ab08`. Le journal montre l'ancienne
signature, la signature attendue `313ebd352086be57`, puis `Done flashing` et
la confirmation `split_axes=1`. Le programme de démarrage lit et vérifie la
signature après le flash avant de lancer le service natif. Son empreinte et
la relation parent/enfant des processus ont été vérifiées. L'audit ne relit
pas lui-même la signature via l'API Panda et n'émet aucune trame CAN.

Les résultats et empreintes des preuves sont enregistrés dans `validation.json`
et `installation-status.json`. Après une résolution mDNS indisponible pendant
le redémarrage, la vérification a abouti sur le réseau local avec la même clé
hôte épinglée. Les tests logiciels et USB ne valident pas le
comportement réel sur route. Les derniers trajets disponibles précèdent
également l'installation de la pause latérale précédente ; ils n'établissent
pas qu'elle a déjà été essayée sur la voiture.
