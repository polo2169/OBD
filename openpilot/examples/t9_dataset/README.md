# Exemple de chronologie T9

`timeline.example.csv` est un exemple **synthétique**, sans donnée issue d'un
véhicule. Il montre les champs utiles pour expliquer une pause latérale sur
clignotant ou effort conducteur, puis la reprise après 0,5 seconde de lignes
fiables.

Les datasets réels ne sont pas versionnés dans Git. Ils sont produits sous
`data/diagnostics/`, qui est ignoré, avec `export_t9_dataset.py`. L'archive contient les
segments `cereal.Event` bruts, leur manifeste SHA-256 et le code T9 associé.
