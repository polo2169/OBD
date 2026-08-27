# Domaine maintenance v1

Ce contrat sépare les faits confirmés par l’utilisateur des propositions issues
de l’OCR. Les enregistrements restent rattachés à un VIN et chaque correction
crée une révision archivée.

## Invariants

- `purchased_at` est la date d’achat ou de facture des pièces.
- `performed_at` est la date réelle de pose ou de réalisation.
- Une facture émise par un garage peut proposer sa date comme date de pose avec
  `performed_at_source=invoice_date_assumed`; cette valeur reste modifiable.
- Une facture de fournisseur de pièces ne fournit jamais automatiquement une
  date de pose. Sans date connue, l’enregistrement reste `draft`.
- `parts` décrit les éléments montés, consommés, utilisés comme outils, non
  utilisés ou retournés. `cost_lines` conserve toutes les lignes financières,
  notamment main-d’œuvre, port et remises négatives.
- `performer_provider_id`, `seller_provider_id` et
  `invoice_issuer_provider_id` sont trois rôles indépendants.
- `import_snapshot` conserve le texte, les valeurs brutes, les preuves et la
  confiance de l’import. Une correction modifie les champs canoniques, pas cette
  preuve d’origine.
- `source_import_key` rend une migration relançable sans créer de doublon.

## Recommandations et rappels

Une recommandation possède un statut (`open`, `monitoring`, `completed` ou
`dismissed`) et peut définir :

- une date d’échéance ;
- un kilométrage d’échéance ;
- un kilométrage du constat et un contrôle après une distance donnée, par
  exemple `105000 km + 500 km`.

L’interface compare ces seuils au dernier kilométrage disponible, CAN en
priorité puis historique, et affiche les échéances atteintes.

## Professionnels

Les garages, concessions, centres de contrôle et fournisseurs sont normalisés
dans un annuaire global. Les coordonnées, identifiants SIREN/SIRET/TVA, alias et
révisions sont réutilisables entre véhicules et documents.

## API

- `GET/POST /api/maintenance/providers`
- `PUT /api/maintenance/providers/{provider_id}`
- `GET/POST /api/maintenance/records`
- `PUT /api/maintenance/records/{record_id}`
- `POST /api/maintenance/records/{record_id}/documents`
- `POST /api/maintenance/invoice-draft`
- `GET /api/maintenance/mileage-estimate`

L’OCR du brouillon utilise uniquement des bibliothèques locales Python :
PyMuPDF pour les PDF, OpenCV pour les images et RapidOCR/ONNX Runtime pour la
reconnaissance. Aucun document n’est envoyé à une API externe payante.
