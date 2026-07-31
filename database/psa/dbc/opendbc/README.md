# Source opendbc PSA

`psa_aee2010_r3.dbc` provient du projet MIT
[`commaai/opendbc`](https://github.com/commaai/opendbc), figé à la révision
`a0febba355168a5cb6168b535144c8c41a5ce323`.

Le port PSA amont documente actuellement la Peugeot 208 2019–2025. Les noms et
facteurs de signaux sont donc des informations externes utiles, mais ne sont pas
considérés comme validés pour la Peugeot 308 T9 2018. Chaque correspondance doit
être confirmée par les captures annotées du mode Découverte.

Le DBC est utilisé uniquement pour décoder des trames reçues. Son intégration
n'active aucune émission CAN et n'importe aucun code de commande d'openpilot.
