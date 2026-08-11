# Source opendbc PSA

`psa_aee2010_r3.dbc` provient du projet MIT
[`commaai/opendbc`](https://github.com/commaai/opendbc), figé à la révision
`a0febba355168a5cb6168b535144c8c41a5ce323`.

Le port PSA amont documente actuellement la Peugeot 208 2019–2025. Les noms et
facteurs de signaux sont donc des informations externes utiles, mais ne sont pas
considérés comme validés pour la Peugeot 308 T9 2018. Chaque correspondance doit
être confirmée par les captures annotées du mode Découverte.

Le nom du fichier ne classe pas la 308 T9 en R3. Sur ce véhicule, 191 254 trames
`0x3F2` montrent une commande de couple signée dynamique tandis que la consigne
d'angle reste nulle : le résultat local est compatible AEE2010 R2/EVO + CVM G2.
Le fichier R3 reste chargé comme catalogue passif étendu pour les trames communes.

Le calculateur de freinage a été identifié séparément par UDS comme un Bosch
ESP 9.0 / ESP90 (`0x6AD → 0x68D`, références PSA `9826694380` et
`9812786180`). Les trames communes `0x34D` (ESP/TCS), `0x38D`, `0x3CD` et
`0x50D` (ABS) sont bien présentes. Les bits d'intervention sont affichés, mais
restent candidats tant qu'un déclenchement réel n'a pas été capturé.

Le DBC est utilisé uniquement pour décoder des trames reçues. Son intégration
n'active aucune émission CAN et n'importe aucun code de commande d'openpilot.
