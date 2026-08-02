# Architecture cible — OpenDiag

## Principe

OpenDiag doit devenir une station de diagnostic modulaire, pas une copie monolithique
de Diagbox. Les protocoles standard sont confiés à des bibliothèques maintenues ; le
code du projet se concentre sur la connaissance véhicule, la sécurité, les workflows,
la traçabilité et l'interface.

## Contrat produit : six modules, pas davantage

| Module | Responsabilité exclusive | Ne fait jamais |
|---|---|---|
| **Garage** | Dossier VIN, véhicules, scans, captures, rapports, réparations, entretien et chronologie | Communiquer directement avec un ECU |
| **Diagnostic** | État des calculateurs, Live Data, défauts, identification, mesures, historique et documentation | Écrire, effacer ou lancer une routine arbitraire |
| **Atelier** | Fonctions organisées par métier et procédures guidées | Exposer un payload CAN/UDS libre |
| **Learn** | Capturer passivement, importer, corréler, découvrir et produire des preuves | Émettre une trame ou publier automatiquement une commande |
| **Database** | ECU, DID, capteurs, routines, DTC, sources, confiance et maturité | Interroger le véhicule |
| **Security & Workflow** | Préconditions, autorisation, exécution bornée, contrôle, rapport et fermeture | Contourner une allowlist ou exécuter une routine inconnue |

`Live Data` est une capacité transversale de Diagnostic et Atelier, pas un septième
module. Sa vue conserve l'ajout, la modification et la suppression logique des
capteurs. Une définition créée depuis l'interface est locale au VIN actif par
défaut. Sa suppression l'archive pour préserver les anciens rapports et replays.

## Parcours utilisateur

Le mode normal ne montre pas les payloads CAN/UDS, ne propose pas de champ de DID
libre et n'exécute aucune routine inconnue. L'utilisateur choisit une fonction métier.
Security & Workflow applique ensuite cette chaîne :

```text
Demande → Préconditions → Autorisation → Exécution bornée
        → Relecture/contrôle → Rapport VIN → Fermeture
```

Les preuves protocolaires restent disponibles dans un mode laboratoire explicite
(`?lab=1`) afin de développer et valider les profils sans mélanger ces outils avec
le diagnostic quotidien.

### Changement de mode à l’exécution

L’interface propose deux modes globaux :

- `Lecture seule`, disponible à tout moment ;
- `Maintenance contrôlée`, armée temporairement après validation de la passerelle,
  sélection du VIN, confirmation exacte et contrôle des quatre préconditions.

Le changement est journalisé dans `data/security_audit.jsonl` et n'est pas conservé
au redémarrage : `READ_ONLY` reste la valeur de démarrage. Le sélecteur nécessite
`RUNTIME_MODE_SWITCH_ENABLED=true`. Le mode maintenance ne débloque aucune fonction
à lui seul : effacement DTC, ECU de sécurité, SecurityAccess et actionneurs gardent
leurs options et allowlists indépendantes.

## Cycle de connaissance

```text
Découvert → Observé → Validé → Documenté → Publié
```

Une corrélation Learn, un import de trace ou une hypothèse de DID ne devient jamais
automatiquement un capteur officiel ou une commande exécutable. La publication
exige une source, un véhicule, une preuve reproductible et une validation humaine.

## Ce qui est réutilisé

| Besoin | Projet | Usage dans OpenDiag |
|---|---|---|
| Accès CAN multi-plateforme | [python-can](https://github.com/hardbyte/python-can) | Transport SocketCAN actuel, autres interfaces ensuite |
| Segmentation ISO 15765-2 | [python-can-isotp](https://github.com/pylessard/python-can-isotp) | Couche commune aux transports série, SocketCAN et virtuel |
| Services ISO 14229 | [udsoncan](https://github.com/pylessard/python-udsoncan) | Requêtes, validation, NRC, P2/P2* et futurs services DTC |
| Topologies PSA et signaux | [PSA-RE](https://github.com/prototux/PSA-RE) | Futur import DBMUXE/DBC avec provenance et licence |
| Recherche diagnostic PSA | [arduino-psa-diag](https://github.com/ludwig-v/arduino-psa-diag) | Référence pour familles ECU, adressage UDS/KWP et bancs de test |
| Réseaux VAN AEE2001 | [VanBus](https://github.com/0xCAFEDECAF/VanBus) | Futur transport/décodeur VAN séparé du cœur UDS |

Les données externes ne sont pas copiées sans provenance. Un importeur devra conserver
la source, la révision, la licence, l'architecture véhicule, le niveau de confiance et
la validation locale.

## Couches techniques

```text
Interface React — Garage | Diagnostic | Atelier | Learn | Database | Security
      │
API FastAPI ─── journal d'audit / rapports
      │
Workflows diagnostic (inventaire, DTC, mesures, maintenance)
      │
Garde-fou UDS ─── base PSA versionnée
      │
udsoncan
      │
python-can-isotp
      │
Transport virtuel | SocketCAN | ESP32 série/TCP Wi-Fi | futur J2534/DoIP
```

En capture embarquée sans carte SD, l'ESP32 crée un point d'accès privé et pousse
les trames JSONL par TCP. Une tâche réseau et une file RAM sont séparées de la
réception TWAI. Le backend écrit les événements sur le disque du PC, détecte les
trous de séquence et tente de se reconnecter. La file RAM amortit uniquement les
ralentissements courts : elle ne remplace pas un stockage local lors d'une coupure
Wi-Fi prolongée.

## Niveaux de sécurité

1. `passive` : aucune émission, capture et analyse seulement.
2. `active_read` : émission matérielle autorisée, services UDS limités à la lecture.
3. `maintenance` : opérations écrites individuellement approuvées, préconditions et journal complet.
4. `programming` : flash/télécodage isolé, alimentation stabilisée, sauvegarde, reprise et validation spécifiques.

La V0.5 implémente les deux premiers niveaux et un effacement DTC unitaire de niveau 3
désactivé par défaut, avec lecture avant/après, confirmation explicite et protections
renforcées pour les ECU de sécurité. Le reste des niveaux 3 et 4 ne doit jamais être
activé par une simple option globale.

## Palier Peugeot actuel

Le profil de référence Peugeot 308 T9 2018 conserve exactement huit calculateurs
réellement détectés lors de la capture de référence : moteur, boîte de vitesses,
ABS/ESP, BSI, combiné, climatisation, caméra et télématique. Cette base sert de test
de non-régression. Les prochaines informations (versions, numéros de série, mesures
et tests fonctionnels comme le plafonnier) sont ajoutées ECU par ECU et ne sont
publiées qu'après observation puis validation sur le véhicule.

## Feuille de route

### V0.5 — diagnostic atelier en lecture (implémenté)

- lecture DTC UDS `0x19/0x02`, code brut, états et dictionnaire PSA ;
- effacement volontaire séparé et désactivé par défaut ;
- capteurs OBD-II Mode 01 avec découverte des PID supportés ;
- traces détaillées CAN/ISO-TP/UDS/OBD et télémétrie de passerelle ;
- mesures live configurées par profil avec unités, échelles et fréquence ;
- identification automatique du véhicule et de l'architecture ;
- rapport JSONL ; PDF et comparaison avant/après restent à faire ;
- import DBC/DBMUXE public avec provenance.

### V0.6 — couverture PSA

- catalogue ECU versionné par architecture AEE2004/AEE2010 ;
- KWP2000 sur CAN et réseaux basse vitesse ;
- adressage fonctionnel et étendu ;
- détection de topologie et routage via BSI ;
- comparaison multi-session dans OpenDiag Learn.

### V0.7 — fonctions atelier contrôlées

- tests actionneurs avec temporisation, arrêt d'urgence et préconditions ;
- procédures de maintenance guidées ;
- télécodage avec lecture/sauvegarde/diff/validation avant écriture ;
- profils matériels J2534 et DoIP ;
- signatures des définitions et journal d'audit infalsifiable.

## Règles de contribution des données

Chaque adresse, DID, signal, DTC ou procédure PSA doit déclarer :

- la source et sa licence ;
- le véhicule, l'année, l'architecture et le calculateur ;
- le type d'accès et les préconditions ;
- le niveau de confiance ;
- les captures ou tests de banc permettant la reproduction ;
- la date et la personne ayant validé la donnée.
