#!/usr/bin/env python3
"""Construit le lot Fiat relu visuellement à partir de l'audit OCR local."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import shutil


def line(
    designation: str,
    *,
    kind: str = "service",
    reference: str | None = None,
    quantity: float | None = 1,
    unit_ht: float | None = None,
    unit_ttc: float | None = None,
    amount_ht: float | None = None,
    amount_ttc: float | None = None,
    hours: float | None = None,
    page: int = 1,
) -> dict:
    return {
        "type_ligne": kind,
        "designation": designation,
        "reference": reference,
        "code_tarif": None,
        "quantite": quantity,
        "temps_heures": hours,
        "prix_unitaire_ht_eur": unit_ht,
        "prix_unitaire_ttc_eur": unit_ttc,
        "remise_pct": None,
        "prix_unitaire_net_ht_eur": unit_ht,
        "montant_ht_eur": amount_ht,
        "montant_ttc_eur": amount_ttc,
        "numero_page": page,
        "confiance": "haute",
        "texte_source": [designation],
    }


def recommendation(
    title: str,
    *,
    mileage: int | None,
    status: str = "open",
    due_date: str | None = None,
    due_mileage: int | None = None,
    completed_at: str | None = None,
    reason: str | None = None,
    details: str | None = None,
) -> dict:
    return {
        "title": title,
        "details": details,
        "status": status,
        "source": "document",
        "recommended_at_km": mileage,
        "due_date": due_date,
        "due_mileage_km": due_mileage,
        "follow_up_after_km": None,
        "confidence": "high",
        "auto_managed": False,
        "completed_by_record_id": None,
        "completed_at": completed_at,
        "completion_reason": reason,
    }


def event(
    key: str,
    sources: list[str],
    title: str,
    *,
    date: str | None,
    mileage: int | None,
    provider: str,
    vin: str,
    registration: str,
    invoice_number: str | None = None,
    client: str,
    subtotal: float | None = None,
    tax: float | None = None,
    total: float | None = None,
    lines: list[dict] | None = None,
    recommendations: list[dict] | None = None,
    notes: str | None = None,
    event_type: str = "maintenance",
    document_type: str = "facture",
    category: str = "Entretien",
    status: str | None = None,
    warnings: list[str] | None = None,
) -> dict:
    page_count = len(sources)
    return {
        "identifiant_document": f"fiat:{key}",
        "fichiers_sources": sources,
        "type_document": document_type,
        "numero_document": invoice_number,
        "identifiant_dossier": None,
        "client_nom": client,
        "date": date,
        "kilometrage": mileage,
        "enseigne_ou_garage": provider,
        "immatriculation": registration,
        "vin": vin,
        "pages_trouvees": list(range(1, page_count + 1)),
        "nombre_pages": page_count,
        "pagination_statut": "complete",
        "lignes_facture": lines or [],
        "notes_manuscrites": [],
        "pieces_changees": [],
        "conseils_maintenance": [],
        "anomalies_ou_points_attention": [],
        "prochaine_echeance_date": None,
        "prochaine_echeance_km": None,
        "montant_ht_eur": subtotal,
        "montant_tva_eur": tax,
        "montant_total_eur": total,
        "somme_lignes_ht_eur": None,
        "somme_lignes_ttc_eur": None,
        "ecart_controle_eur": None,
        "controle_montants": "non_calculable",
        "nature_evenement": None,
        "realise_par": "garage",
        "commentaire_utilisateur": None,
        "confiance": "haute",
        "champs_a_verifier": warnings or [],
        "objet": title,
        "event_type_obd": event_type,
        "category_obd": category,
        "record_status_obd": status,
        "document_kind_obd": "recommendation" if document_type == "fiche_controle" else "invoice",
        "recommendations_obd": recommendations or [],
        "notes": notes,
    }


def curated_events(
    *,
    vin: str,
    registration: str,
    default_client: str,
    owner_client: str,
) -> list[dict]:
    def vehicle_event(*args, **kwargs) -> dict:
        kwargs.setdefault("client", default_client)
        return event(
            *args,
            vin=vin,
            registration=registration,
            **kwargs,
        )

    return [
        vehicle_event(
            "2016-01-13-purchase-7670", ["IMG_0596.jpg"], "Achat du véhicule d’occasion",
            date="2016-01-13", mileage=35_000, provider="S.A.S. Littoral Automobile",
            invoice_number="7670", total=7_700.00, event_type="other", category="Achat du véhicule",
            lines=[
                line("FIAT 500 1.2 POP d’occasion", kind="other", amount_ttc=7_500.00),
                line("Frais d’immatriculation", kind="service", amount_ttc=200.00),
            ],
            notes="Véhicule garanti 6 mois OPTEVEN Medium. Première mise en circulation : 31/12/2010.",
        ),
        vehicle_event(
            "2017-01-28-tires-alignment-247708", ["IMG_0613.jpg", "IMG_0611.jpg", "IMG_0612.jpg"],
            "Remplacement de deux pneus et réglage de la géométrie",
            date="2017-01-28", mileage=40_932, provider="Norauto Coudekerque",
            invoice_number="0148/247708", subtotal=150.68, tax=30.12, total=180.80,
            event_type="repair", category="Pneumatiques et géométrie",
            lines=[
                line("Pneu 175/65R14 82T PREVENSYS 3", kind="piece", reference="2068635", quantity=2, unit_ht=34.96, unit_ttc=41.95, amount_ht=69.92, amount_ttc=83.90),
                line("Montage, équilibrage et valves", amount_ht=25.00, amount_ttc=30.00),
                line("Contrôle trains avant/arrière et parallélisme avant", reference="9040", amount_ht=55.75, amount_ttc=66.90),
            ],
            recommendations=[
                recommendation("Remplacer le liquide de refroidissement", mileage=40_932, status="completed", completed_at="2019-02-13", reason="Remplacement documenté par la facture Norauto 0148/287766."),
                recommendation("Vidanger et purger le circuit de frein", mileage=40_932, status="completed", completed_at="2019-02-13", reason="Remplacement du liquide de frein documenté par la facture Norauto 0148/287766."),
            ],
            notes="Le devis 0148/178662 joint à cette visite a été refusé ; ses deux recommandations ont été réalisées en 2019.",
        ),
        vehicle_event(
            "2017-05-06-service-252445", ["IMG_0607.jpg", "IMG_0608.jpg", "IMG_0609.jpg", "IMG_0610.jpg"],
            "Révision moteur, filtres et bougies",
            date="2017-05-06", mileage=42_324, provider="Norauto Coudekerque",
            invoice_number="0148/252445", subtotal=162.50, tax=32.50, total=195.00,
            lines=[
                line("Révision des 30 000 km ou des 2 ans", amount_ht=162.50, amount_ttc=195.00),
                line("Huile moteur 5W40 5L", kind="produit", reference="2006926", amount_ht=0.00, amount_ttc=0.00),
                line("Filtre à huile Norauto", kind="piece", reference="288477", amount_ht=0.00, amount_ttc=0.00),
                line("Filtre d’habitacle", kind="piece", amount_ht=0.00, amount_ttc=0.00),
                line("Bougies d’allumage", kind="piece", quantity=4, amount_ht=0.00, amount_ttc=0.00),
            ],
            recommendations=[
                recommendation("Prochain entretien à 60 000 km ou avant mai 2019", mileage=42_324, status="completed", completed_at="2019-02-13", reason="Révision suivante documentée à 57 755 km."),
            ],
        ),
        vehicle_event(
            "2018-02-26-technical-inspection-18123711", ["IMG_0616.jpg"], "Contrôle technique périodique",
            date="2018-02-26", mileage=47_716, provider="Les Contrôles du Dunkerquois",
            invoice_number="18123711", subtotal=60.00, tax=12.00, total=72.00,
            event_type="technical_inspection", document_type="fiche_controle", category="Contrôle technique",
            lines=[line("Visite technique périodique", amount_ht=59.72, amount_ttc=71.66), line("Redevance OTC", amount_ht=0.28, amount_ttc=0.34)],
        ),
        vehicle_event(
            "2018-12-bulb-285012", ["IMG_0599.jpg"], "Remplacement d’une ampoule avant H7",
            date=None, mileage=56_036, provider="Norauto Coudekerque", invoice_number="0148/285012",
            subtotal=19.16, tax=3.83, total=22.99, event_type="repair", category="Éclairage", status="draft",
            lines=[
                line("Remplacement d’une ampoule avant", reference="2196539", amount_ht=12.50, amount_ttc=15.00),
                line("Ampoule Norauto H7", kind="piece", reference="224218", unit_ht=6.66, unit_ttc=7.99, amount_ht=6.66, amount_ttc=7.99),
            ],
            notes="Le jour exact est masqué sur la photo ; seul le mois de décembre 2018 est lisible.",
            warnings=["Jour exact de la facture masqué sur la photo ; événement conservé en brouillon."],
        ),
        vehicle_event(
            "2019-02-13-front-brakes-287769", ["IMG_0600.jpg", "IMG_0601.jpg"],
            "Remplacement des disques et plaquettes avant, réparation d’un pneu",
            date="2019-02-13", mileage=57_755, provider="Norauto Coudekerque", invoice_number="0148/287769",
            subtotal=155.83, tax=31.17, total=187.00, event_type="repair", category="Freinage et pneumatiques",
            lines=[
                line("Montage plaquettes et disques de frein avant Norauto", amount_ht=132.50, amount_ttc=159.00),
                line("Plaquettes avant NRP1944", kind="piece", reference="924216", amount_ht=0.00, amount_ttc=0.00),
                line("Deux disques avant ND3465", kind="piece", reference="443102", quantity=2, amount_ht=0.00, amount_ttc=0.00),
                line("Réparation d’une crevaison avec équilibrage", amount_ht=23.33, amount_ttc=28.00),
            ],
            recommendations=[
                recommendation("Respecter un rodage des freins pendant 500 km", mileage=57_755, status="dismissed", reason="Consigne temporaire échue depuis longtemps."),
            ],
        ),
        vehicle_event(
            "2019-02-13-service-fluids-287766", ["IMG_0602.jpg", "IMG_0603.jpg", "IMG_0604.jpg"],
            "Vidange, filtres, liquide de frein et liquide de refroidissement",
            date="2019-02-13", mileage=57_755, provider="Norauto Coudekerque", invoice_number="0148/287766",
            subtotal=189.97, tax=37.98, total=227.95, category="Entretien moteur et fluides",
            lines=[
                line("Vidange 5W40 avec filtres à huile et à air", reference="2157064", amount_ht=81.67, amount_ttc=98.00),
                line("Filtre à huile Norauto", kind="piece", reference="288477", unit_ht=24.17, unit_ttc=29.00, amount_ht=0.00, amount_ttc=0.00),
                line("Filtre à air MANN-FILTER C2859", kind="piece", reference="470652", amount_ht=0.00, amount_ttc=0.00),
                line("Vidange et remplacement du liquide de frein", reference="9354", amount_ht=49.17, amount_ttc=59.00),
                line("Remplacement du liquide de refroidissement", reference="9511", amount_ht=49.17, amount_ttc=59.00),
                line("Liquide de refroidissement -35 °C 5L", kind="produit", reference="91638", unit_ht=9.96, unit_ttc=11.95, amount_ht=9.96, amount_ttc=11.95),
            ],
            recommendations=[
                recommendation("Plaquettes avant à prévoir (3 à 5 mm)", mileage=57_755, status="completed", completed_at="2019-02-13", reason="Plaquettes remplacées le même jour sur la facture 0148/287769."),
                recommendation("Disques avant à remplacer", mileage=57_755, status="completed", completed_at="2019-02-13", reason="Disques remplacés le même jour sur la facture 0148/287769."),
            ],
            notes="Le devis complémentaire mentionné sur le compte rendu a été refusé ; les freins avant ont néanmoins été facturés séparément le même jour.",
        ),
        vehicle_event(
            "2019-03-11-heater-thermostat-FIA1168070", ["IMG_0614.jpg"],
            "Remplacement du ventilateur de chauffage et du thermostat",
            date="2019-03-11", mileage=58_510, provider="S.A.S. Littoral Automobile", invoice_number="FIA1168070",
            subtotal=519.53, tax=103.91, total=623.44, event_type="repair", category="Chauffage et refroidissement",
            lines=[
                line("Contrôle faisceaux et remplacement du moteur de chauffage", kind="main_oeuvre", hours=2.5, unit_ht=55.00, amount_ht=137.50),
                line("Moteur électrique de chauffage", kind="piece", reference="0000077365525", unit_ht=172.31, amount_ht=172.31),
                line("Résistance de chauffage", kind="piece", reference="0000046723713", unit_ht=26.73, amount_ht=26.73),
                line("Remplacement du thermostat et purge", kind="main_oeuvre", hours=2.0, unit_ht=55.00, amount_ht=110.00),
                line("Antigel", kind="produit", quantity=6, unit_ht=4.90, amount_ht=29.40),
                line("Thermostat", kind="piece", reference="0000055202371", unit_ht=39.57, amount_ht=39.57),
                line("Recyclage des déchets", amount_ht=4.02),
            ],
            notes="La date de facture est le 11/03/2019 ; l’ordre de réparation est daté du 01/03/2019.",
        ),
        vehicle_event(
            "2020-02-20-front-strut-mounts-74493", ["IMG_0606.jpg"],
            "Remplacement des semelles de suspension avant et géométrie",
            date="2020-02-20", mileage=68_037, provider="Speedy Dunkerque – FPA SAS", invoice_number="0776/74493",
            subtotal=139.23, tax=27.86, total=167.09, event_type="repair", category="Suspension et géométrie",
            lines=[
                line("Semelles de suspension avant Monroe", kind="piece", reference="03MK095", quantity=2, unit_ht=19.43, unit_ttc=23.32, amount_ht=38.86, amount_ttc=46.64),
                line("Montage ressorts ou semelles avant", reference="99MO0205", amount_ht=48.33, amount_ttc=58.00),
                line("Contrôle et réglage géométrie avant", reference="99C2", amount_ht=48.59, amount_ttc=58.31),
                line("Traitement des déchets", reference="99DECHET02", amount_ht=3.45, amount_ttc=4.14),
            ],
        ),
        vehicle_event(
            "2020-03-05-technical-inspection-20133947", ["IMG_0617.jpg"], "Contrôle technique périodique",
            date="2020-03-05", mileage=68_703, provider="Les Contrôles du Dunkerquois", invoice_number="20133947",
            subtotal=60.00, tax=12.00, total=72.00, event_type="technical_inspection", document_type="fiche_controle", category="Contrôle technique",
            lines=[line("Visite technique périodique", amount_ht=59.72, amount_ttc=71.66), line("Redevance OTC", amount_ht=0.28, amount_ttc=0.34)],
        ),
        vehicle_event(
            "2020-03-05-rear-brakes-74757", ["IMG_0605.jpg"],
            "Remplacement du kit de frein arrière et du liquide de frein",
            date="2020-03-05", mileage=68_706, provider="Speedy Dunkerque – FPA SAS", invoice_number="0776/74757",
            subtotal=247.26, tax=49.44, total=296.70, event_type="repair", category="Freinage",
            lines=[
                line("Kit de frein arrière préassemblé Delphi", kind="piece", reference="D7KP1091", unit_ht=119.00, unit_ttc=142.80, amount_ht=119.00, amount_ttc=142.80),
                line("Montage mâchoires et cylindre", reference="99MO0404", amount_ht=74.17, amount_ttc=89.00),
                line("Remplacement du liquide de frein", reference="11CIRFREIN", amount_ht=49.17, amount_ttc=59.00),
                line("Traitement des déchets", reference="99DECHET03", amount_ht=4.92, amount_ttc=5.90),
            ],
        ),
        vehicle_event(
            "2020-05-26-starter-310496", ["IMG_0597.jpg"], "Remplacement du démarreur",
            date="2020-05-26", mileage=64_850, provider="Norauto Coudekerque", invoice_number="0148/310496",
            subtotal=217.46, tax=43.49, total=260.95, event_type="repair", category="Démarrage",
            lines=[
                line("Remplacement du démarreur", reference="9143", amount_ht=52.50, amount_ttc=63.00),
                line("Démarreur échange standard 3170", kind="piece", reference="780620", unit_ht=164.96, unit_ttc=197.95, amount_ht=164.96, amount_ttc=197.95),
            ],
            recommendations=[recommendation("Batterie à remplacer", mileage=64_850, status="completed", completed_at="2020-05-26", reason="Batterie Varta D52 facturée lors de la même visite.")],
            warnings=["Le kilométrage imprimé (64 850 km) est inférieur aux 68 706 km relevés en mars 2020 ; valeur conservée telle qu’elle apparaît sur la facture."],
        ),
        vehicle_event(
            "2020-05-26-battery-310498", ["IMG_0598.jpg"], "Remplacement de la batterie",
            date="2020-05-26", mileage=64_850, provider="Norauto Coudekerque", invoice_number="0148/310498",
            subtotal=141.63, tax=28.33, total=169.95, event_type="repair", category="Démarrage",
            lines=[
                line("Montage batterie", reference="9150", amount_ht=0.00, amount_ttc=0.00),
                line("Batterie Varta D52", kind="piece", reference="877832", unit_ht=141.63, unit_ttc=169.95, amount_ht=141.63, amount_ttc=169.95),
            ],
            notes="La date et le kilométrage sont repris de la facture démarreur 0148/310496, émise deux numéros plus tôt lors de la même visite.",
            warnings=["Date et kilométrage masqués sur cette page, rapprochés de la facture 0148/310496 de la même visite."],
        ),
        vehicle_event(
            "2020-07-01-technical-reinspection-035824", ["IMG_0618.jpg"], "Contre-visite de contrôle technique",
            date="2020-07-01", mileage=71_370, provider="Contrôle Automobile Soubise", invoice_number="035824",
            subtotal=25.00, tax=5.00, total=30.00, event_type="technical_inspection", document_type="fiche_controle", category="Contrôle technique",
            lines=[line("Contre-visite visuelle extérieure", amount_ht=25.00, amount_ttc=30.00)],
        ),
        vehicle_event(
            "2021-05-07-bodywork-26631", ["IMG_0615.jpg"], "Réparation carrosserie et rétroviseur gauche",
            date="2021-05-07", mileage=None, provider="Carrosserie Lison", invoice_number="26631",
            subtotal=1_429.27, tax=285.85, total=1_715.12, event_type="repair", category="Carrosserie",
            lines=[
                line("Carter de rétroviseur extérieur gauche", kind="piece", unit_ht=28.34, amount_ht=28.34),
                line("Écran inférieur de rétroviseur gauche", kind="piece", unit_ht=19.26, amount_ht=19.26),
                line("Forfait sanitaire véhicule COVID-19", amount_ht=30.00),
                line("Agrafes", kind="piece", amount_ht=10.00),
                line("Produits", kind="produit", amount_ht=10.00),
                line("ERD", amount_ht=5.00),
                line("Main-d’œuvre tôlerie T1", kind="main_oeuvre", hours=2.5, unit_ht=60.00, amount_ht=150.00),
                line("Main-d’œuvre tôlerie T2", kind="main_oeuvre", hours=7.0, unit_ht=61.57, amount_ht=430.99),
                line("Main-d’œuvre peinture T2", kind="main_oeuvre", hours=8.0, unit_ht=61.57, amount_ht=492.56),
                line("Ingrédients peinture", kind="produit", quantity=8, unit_ht=31.64, amount_ht=253.12),
            ],
            notes="Montant total des travaux : 1 715,12 €. Franchise à la charge du client : 230,00 € ; part assurance : 1 485,12 €.",
        ),
        vehicle_event(
            "2021-05-20-timing-belt-495421", ["IMG_0623.jpg", "IMG_0624.jpg"],
            "Remplacement du kit de distribution, pompe à eau et courroie accessoires",
            date="2021-05-20", mileage=82_587, provider="Norauto Limonest", invoice_number="021/495421",
            subtotal=396.50, tax=79.30, total=475.80, event_type="repair", category="Distribution",
            lines=[
                line("Forfait kit distribution, pompe à eau et courroies accessoires", amount_ht=394.08, amount_ttc=472.90),
                line("Kit courroie Gates K055PK1148", kind="piece", reference="2292017", amount_ht=0.00, amount_ttc=0.00),
                line("Courroie Gates 4PK668", kind="piece", reference="225134", amount_ht=0.00, amount_ttc=0.00),
                line("Kit distribution et pompe Gates KP15627XS", kind="piece", reference="699740", amount_ht=0.00, amount_ttc=0.00),
                line("Forfait sécurité sanitaire", reference="2220843", amount_ht=2.42, amount_ttc=2.90),
            ],
        ),
        vehicle_event(
            "2022-02-18-tire-wipers-alignment-869624", ["IMG_0625.jpg", "IMG_0626.jpg"],
            "Remplacement d’un pneu, des essuie-glaces et réglage de la géométrie",
            date="2022-02-18", mileage=89_922, provider="Norauto Saint-Priest", invoice_number="0062/869624",
            subtotal=139.79, tax=27.96, total=167.75, event_type="repair", category="Pneumatiques et géométrie",
            lines=[
                line("Montage, équilibrage et valve d’un pneumatique", amount_ht=13.29, amount_ttc=15.95),
                line("Pneu 175/65R14 82T PREVENSYS 4", kind="piece", reference="2238349", unit_ht=39.08, unit_ttc=46.90, amount_ht=39.08, amount_ttc=46.90),
                line("Paire d’essuie-glaces Bosch 424V", kind="piece", reference="2153649", unit_ht=29.13, unit_ttc=34.95, amount_ht=29.13, amount_ttc=34.95),
                line("Réglage parallélisme avant et contrôle géométrie", reference="2209514", amount_ht=58.29, amount_ttc=69.95),
            ],
        ),
        vehicle_event(
            "2022-03-04-service-accessory-belt-870692", ["IMG_0619.jpg", "IMG_0620.jpg", "IMG_0621.jpg", "IMG_0622.jpg"],
            "Révision moteur, bougies et courroie d’accessoires",
            date="2022-03-04", mileage=90_791, provider="Norauto Saint-Priest", invoice_number="0062/870692",
            subtotal=195.13, tax=39.02, total=234.15, category="Entretien moteur",
            lines=[
                line("Révision des 11 ans avec vidange", amount_ht=171.67, amount_ttc=206.00),
                line("Huile moteur 5W40", kind="produit", reference="2123481", amount_ht=0.00, amount_ttc=0.00),
                line("Quatre bougies Bosch", kind="piece", reference="2239492", quantity=4, amount_ht=0.00, amount_ttc=0.00),
                line("Filtre à huile Norauto", kind="piece", reference="288477", amount_ht=0.00, amount_ttc=0.00),
                line("Filtre d’habitacle Norauto", kind="piece", reference="355467", amount_ht=0.00, amount_ttc=0.00),
                line("Courroie d’accessoires Gates 5PK1148", kind="piece", reference="224979", unit_ht=21.00, unit_ttc=25.20, amount_ht=21.00, amount_ttc=25.20),
                line("Participation protection COVID-19", reference="2220843", amount_ht=2.46, amount_ttc=2.95),
            ],
            recommendations=[
                recommendation("Plaquettes de frein avant à prévoir (3 à 5 mm)", mileage=90_791, status="completed", completed_at="2022-04-28", reason="Plaquettes avant remplacées par Norauto le 28/04/2022."),
            ],
        ),
        vehicle_event(
            "2022-04-28-front-pads-874767", ["IMG_0627.jpg"], "Remplacement des plaquettes de frein avant",
            date="2022-04-28", mileage=91_286, provider="Norauto Saint-Priest", invoice_number="0062/874767",
            subtotal=49.96, tax=9.99, total=59.95, event_type="repair", category="Freinage",
            lines=[
                line("Montage plaquettes de frein avant Norauto", reference="2011128", amount_ht=49.96, amount_ttc=59.95),
                line("Plaquettes Norauto NRP1944", kind="piece", reference="924216", amount_ht=0.00, amount_ttc=0.00),
            ],
            recommendations=[
                recommendation("Faire vérifier ou remplacer le liquide de frein", mileage=91_286, due_date="2022-03-05", details="La facture rappelle une vérification tous les 2 ans ; le dernier remplacement documenté date du 05/03/2020."),
                recommendation("Rodage des freins pendant 500 km", mileage=91_286, status="dismissed", reason="Consigne temporaire échue depuis longtemps."),
            ],
        ),
        vehicle_event(
            "2022-05-09-headlight-bulbs-926637", ["IMG_0628.jpg"], "Remplacement de deux ampoules avant H7",
            date="2022-05-09", mileage=91_752, provider="Feu Vert Lyon Saint-Genis", invoice_number="926637",
            subtotal=34.82, tax=6.96, total=41.78, event_type="repair", category="Éclairage",
            lines=[
                line("Ampoule Feu Vert H7", kind="piece", reference="686210", quantity=2, unit_ttc=7.99, amount_ttc=15.98),
                line("Montage d’une ampoule standard", reference="143643", quantity=2, unit_ttc=12.90, amount_ttc=25.80),
            ],
        ),
        vehicle_event(
            "2024-09-23-electronic-diagnosis-10006551", ["IMG_0595.jpg"],
            "Diagnostic de panne de démarrage et de courroie d’accessoires",
            date="2024-09-23", mileage=110_216, provider="Le Garage Toulousain", invoice_number="10006551",
            subtotal=50.00, tax=10.00, total=60.00, event_type="diagnostic", category="Diagnostic",
            lines=[line("Recherche de panne électronique", amount_ht=50.00, amount_ttc=60.00)],
            recommendations=[
                recommendation("Confirmer la réparation de la courroie d’accessoires et de la poulie Damper", mileage=110_216, due_mileage=110_216, details="La facture indique : véhicule ne démarre plus, courroie accessoires cassée et problème de poulie Damper. Aucune facture de réparation correspondante n’est présente dans le lot."),
            ],
            notes="Mentions du garage : « Ne démarre plus », « Courroie ACC morte », « Moteur HS », « Problème avec poulie Damper ». La voiture a ensuite roulé ; la facture de réparation manque dans le lot.",
        ),
        vehicle_event(
            "2025-03-06-technical-inspection-25082204", ["IMG_0593.jpg", "IMG_0594.jpg"],
            "Contrôle technique défavorable – 2 défaillances majeures et 3 mineures",
            date="2025-03-06", mileage=113_187, provider="CTA Francazal", invoice_number="25082204 / facture 25083592",
            subtotal=65.83, tax=13.17, total=79.00, event_type="technical_inspection", document_type="fiche_controle", category="Contrôle technique",
            lines=[line("Forfait contrôle technique véhicule particulier essence", amount_ht=65.41, amount_ttc=78.49), line("Redevance OTC", amount_ht=0.42, amount_ttc=0.51)],
            recommendations=[
                recommendation("Amortisseur avant gauche endommagé ou présentant une fuite", mileage=113_187, status="completed", completed_at="2025-04-11", reason="Les deux amortisseurs avant ont été remplacés par Speedy le 11/04/2025."),
                recommendation("Fuite excessive de liquide à l’avant du véhicule", mileage=113_187, status="completed", completed_at="2025-04-25", reason="La contre-visite du 25/04/2025 est favorable."),
                recommendation("Contrôler le déséquilibre du frein de service arrière", mileage=113_187, due_mileage=113_187),
                recommendation("Silentblocs ou articulations des bras de suspension avant détériorés (AVD et AVG)", mileage=113_187, due_mileage=113_187),
                recommendation("Tuyau d’échappement ou silencieux endommagé sans fuite", mileage=113_187, due_mileage=113_187),
            ],
            notes="PV 25082204 et facture de contrôle 25083592 regroupés dans la même intervention.",
        ),
        vehicle_event(
            "2025-04-11-front-shocks-service-5457", ["IMG_0591.jpg", "IMG_0592.jpg"],
            "Remplacement des amortisseurs avant et entretien moteur",
            date="2025-04-11", mileage=113_825, provider="Speedy Toulouse – Dallard Automobiles 31", invoice_number="0534/5457",
            client=owner_client, subtotal=474.76, tax=94.94, total=569.70, event_type="repair", category="Suspension et entretien moteur",
            lines=[
                line("Amortisseur avant droit Monroe", kind="piece", reference="3KG7305", unit_ht=106.25, unit_ttc=127.50, amount_ht=106.25, amount_ttc=127.50),
                line("Montage des amortisseurs avant", reference="99MO0202", amount_ht=112.50, amount_ttc=135.00),
                line("Contrôle de géométrie", reference="99C1", amount_ht=44.17, amount_ttc=53.00),
                line("Amortisseur avant gauche Monroe", kind="piece", reference="3KG7306", unit_ht=106.25, unit_ttc=127.50, amount_ht=106.25, amount_ttc=127.50),
                line("Forfait entretien Basic 5W40", reference="99BA540D", amount_ht=94.00, amount_ttc=112.80),
                line("Huile Evolution Full Tech LSX 5W40", kind="produit", reference="ELV15D", amount_ht=0.00, amount_ttc=0.00),
                line("Joint de bouchon de vidange", kind="piece", reference="99RMPJTBOU", amount_ht=0.00, amount_ttc=0.00),
                line("Filtre à huile", kind="piece", reference="MFELH4393", amount_ht=0.00, amount_ttc=0.00),
                line("Participation énergie", reference="99PROTECTC", amount_ht=6.67, amount_ttc=8.00),
                line("Traitement des déchets", reference="99DECHET03", amount_ht=4.92, amount_ttc=5.90),
            ],
            notes="La facture est acquittée par carte bancaire et confirme la pose des pièces le 11/04/2025.",
        ),
        vehicle_event(
            "2025-04-25-technical-reinspection-25082847", ["IMG_0590.jpg"],
            "Contre-visite de contrôle technique favorable",
            date="2025-04-25", mileage=113_922, provider="CTA Francazal", invoice_number="25082847",
            event_type="technical_inspection", document_type="fiche_controle", category="Contrôle technique",
            notes="Contre-visite favorable faisant suite au PV défavorable 25082204 du 06/03/2025. Validité du contrôle : 05/03/2027.",
        ),
    ]


def prepare(
    input_dir: Path,
    output_dir: Path,
    *,
    vin: str,
    registration: str,
    default_client: str,
    owner_client: str,
) -> dict[str, int]:
    log_path = input_dir / "maintenance_log.json"
    records = json.loads(log_path.read_text(encoding="utf-8"))
    raw_sources = {str(record["fichier_source"]) for record in records}
    events = curated_events(
        vin=vin,
        registration=registration,
        default_client=default_client,
        owner_client=owner_client,
    )
    curated_sources = [source for item in events for source in item["fichiers_sources"]]
    duplicates = sorted({source for source in curated_sources if curated_sources.count(source) > 1})
    missing = sorted(raw_sources.difference(curated_sources))
    unknown = sorted(set(curated_sources).difference(raw_sources))
    if duplicates or missing or unknown:
        raise ValueError(f"Périmètre invalide — doublons={duplicates}, absents={missing}, inconnus={unknown}")
    output_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy2(log_path, output_dir / "maintenance_log.json")
    (output_dir / "maintenance_events.json").write_text(
        json.dumps(events, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    summary = {
        "source_pages": len(raw_sources),
        "curated_events": len(events),
        "confirmed_events": sum(item.get("record_status_obd") != "draft" for item in events),
        "draft_events": sum(item.get("record_status_obd") == "draft" for item in events),
    }
    (output_dir / "curation_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--vin", required=True)
    parser.add_argument("--registration", required=True)
    parser.add_argument("--default-client", required=True)
    parser.add_argument("--owner-client", required=True)
    arguments = parser.parse_args()
    print(json.dumps(prepare(
        arguments.input_dir.resolve(),
        arguments.output_dir.resolve(),
        vin=arguments.vin,
        registration=arguments.registration,
        default_client=arguments.default_client,
        owner_client=arguments.owner_client,
    ), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
