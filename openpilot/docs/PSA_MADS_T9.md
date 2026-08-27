# MADS-T9 : engagement latéral indépendant du RVV

## Objectif et statut

`MADS-T9` est une adaptation locale des principes du Modular Assistive Driving
System de sunnypilot. Elle sépare l'état de l'assistance latérale de celui du
RVV, sans importer sunnypilot ni modifier le contrôleur torque T9.

Cette première version est volontairement conservatrice :

- aucune activation unifiée avec le RVV (`UEM` désactivé) ;
- frein = désengagement, sans reprise automatique ;
- activation latérale à partir de 40 km/h ;
- accélérateur et RVV inactif sans effet sur l'état latéral ;
- reprise après effort conducteur seulement après 300 ms de relâchement stable ;
- commande hôte, heartbeat et autorisation physique nécessaires ensemble ;
- longitudinal toujours facultatif et indépendant.

Le couple non nul reste verrouillé dans les profils `PSA_BENCH_ONLY`. MADS-T9
ne transforme donc pas le firmware actuel en logiciel routier et ne valide ni
le transfert réel de l'EPS, ni le couple T9, ni le freinage longitudinal.

## États

| État | Couple latéral | Signification |
|---|---:|---|
| `disabled` | Non | Non demandé ou désengagement verrouillé |
| `paused` | Non | Demandé, mais préconditions ou interrupteur physique absents |
| `enabled` | Oui, selon le profil compilé | Toutes les barrières sont valides |
| `overriding` | Non | Le conducteur applique un effort au volant |
| `fault` | Non | Faute latched, redémarrage et diagnostic requis |

Le passage `overriding → enabled` attend 300 ms sous le seuil d'effort. Le frein,
une donnée de sécurité périmée, une perte de heartbeat ou une sortie de
l'enveloppe de vitesse provoquent `disabled` avec `rearm_required=true`. Répéter
`enabled=true` ne suffit pas : l'hôte doit envoyer `false`, puis `true`.

## Séparation latéral / longitudinal

```text
psa_mads=true ──► centrage latéral possible ───────────────┐
                                                          │ indépendants
psa_longitudinal=true ──► remplacement de consigne RVV ───┘
```

Un RVV inactif ou une pression sur l'accélérateur bloque seulement le
longitudinal. Si une commande RVV expire ou devient incohérente, `0x50E` repasse
en transmission stock et l'événement `RVV_DISABLED_LATERAL_REMAINS` est émis.
La direction reste engagée si toutes ses propres barrières sont valides.

Le frein reste commun aux deux domaines : il restaure le bypass et verrouille
MADS jusqu'au prochain cycle explicite `false → true`.

## Autorisation physique

Utiliser un interrupteur à verrouillage **DPST** :

1. premier pôle en série entre `GPIO32` et l'entrée `ON` du TPS22919-Q1 ; ouvert,
   le pull-down 100 kΩ force matériellement `SBU1=0` et le bypass stock ;
2. second pôle entre `GPIO33` et la masse ; fermé, il fournit l'autorisation
   MADS active-bas ;
3. ajouter un pull-up externe 10 kΩ entre `GPIO33` et 3,3 V, même si le firmware
   active aussi `INPUT_PULLUP`.

L'ouverture du premier pôle ne dépend pas du logiciel. Le GPIO33 apporte en plus
l'état visible par le firmware, avec 50 ms de stabilité exigés avant activation
et une désactivation immédiate à l'ouverture.

## Protocole hôte

Séquence latérale, RVV non requis :

1. fermer l'interrupteur physique ;
2. envoyer le heartbeat au moins toutes les 100 ms ;
3. demander MADS ;
4. envoyer une consigne torque fraîche au moins toutes les 100 ms, y compris
   `raw=0` dans le profil de validation ;
5. vérifier `mads_state=enabled` dans `stats` ;
6. demander la prise de contrôle du pont.

```json
{"type":"psa_heartbeat","engaged":true}
{"type":"psa_mads","enabled":true}
{"type":"psa_torque","raw":0}
{"type":"psa_takeover","enabled":true}
```

Le RVV de banc peut être activé ou arrêté ensuite sans désengager MADS :

```json
{"type":"psa_longitudinal","enabled":true,"target_kph":70}
{"type":"psa_longitudinal","enabled":false}
```

Après un frein ou un autre désengagement verrouillé :

```json
{"type":"psa_mads","enabled":false}
{"type":"psa_mads","enabled":true}
{"type":"psa_takeover","enabled":true}
```

`stats` publie `mads_state`, `mads_requested`, `mads_engaged`,
`mads_rearm_required`, `mads_physical_enable`, `mads_reason` et
`torque_command_age_ms`. Une consigne torque âgée de plus de 150 ms restaure le
bypass, même si le heartbeat général reste valide.

## Validation

Les tests hôte couvrent la machine à états et son intégration à la barrière LKA :

```bash
cd openpilot/firmware/psa-obdc-bridge

MADS_TEST_BIN=$(mktemp /tmp/mads-state-test.XXXXXX)
c++ -std=c++17 -Wall -Wextra -Werror -Iinclude \
  test/mads_state_test.cpp -o "$MADS_TEST_BIN"
"$MADS_TEST_BIN"

LKA_TEST_BIN=$(mktemp /tmp/lka-mads-test.XXXXXX)
c++ -std=c++17 -Wall -Wextra -Werror -Itest/stubs -Iinclude \
  test/lka_mads_safety_test.cpp -o "$LKA_TEST_BIN"
"$LKA_TEST_BIN"
```

Avant tout essai physique, vérifier séparément que l'ouverture du commutateur
DPST remet bien `SBU1` à 0 V même si `GPIO32` reste commandé à l'état haut.
