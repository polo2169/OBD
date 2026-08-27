# Données véhicule partagées

`database/` est le seul domaine métier partagé par les deux sous-projets :

- l'application OBD lit les profils, calculateurs, DIDs, DTC et procédures ;
- le laboratoire `openpilot/` lit les DBC et les paramètres véhicule nécessaires
  aux replays et simulations.

Les captures et résultats calculés ne doivent pas être ajoutés ici. Ils vont
respectivement dans `data/sessions/` et `data/runtime/`. Une donnée ajoutée à la
base doit rester déclarative, sourcée et indépendante d'un port série ou d'une
machine locale.
