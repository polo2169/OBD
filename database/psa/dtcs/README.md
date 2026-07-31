# Catalogue DTC PSA communautaire

`psa_community.json` est généré depuis le répertoire `dtc` de
[ludwig-v/arduino-psa-diag](https://github.com/ludwig-v/arduino-psa-diag),
révision `c1409e60798f66bb63149505826170b5eb3c163f`, sous licence GPL-3.0.

Il contient des dictionnaires pour de nombreuses variantes de calculateurs PSA.
Une correspondance de code n'établit pas à elle seule que la description concerne
la variante montée sur le véhicule. OpenDiag privilégie les catalogues déclarés
dans le profil de l'ECU et marque les correspondances globales comme ambiguës.

Régénération :

```bash
cd backend
python tools/import_psa_dtc_catalog.py /chemin/arduino-psa-diag/dtc \
  ../database/psa/dtcs/psa_community.json
```
