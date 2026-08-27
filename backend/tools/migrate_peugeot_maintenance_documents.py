#!/usr/bin/env python3
"""Normalise les justificatifs et corrige les libellés connus de la Peugeot.

Les photos originales restent dans le dossier d'audit. L'application ne publie
ensuite qu'un PDF recadré par intervention. Le script est idempotent par défaut :
un PDF déjà normalisé n'est pas régénéré sans ``--force-documents``.
"""

from __future__ import annotations

import argparse
from datetime import date
import json
from pathlib import Path
import sys


BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.diagnostic.maintenance_history import (
    MaintenanceRecommendation,
    MaintenanceRecord,
    MaintenanceRecordInput,
    list_maintenance_records,
    normalize_maintenance_documents,
    reconcile_maintenance_recommendations,
    update_maintenance_record,
)


DEFAULT_VIN = "VF3LPHNYWJS141966"
DEFAULT_ROTATION_LOG = Path.home() / "Downloads/voiture/data/maintenance_log.json"


SOURCE_CORRECTIONS: dict[str, dict] = {
    "WhatsApp Image 2026-08-25 at 11.46.19.jpeg": {
        "title": "Pneus arrière à remplacer",
        "performed_at": date(2026, 8, 21),
        "performed_at_source": "document_explicit",
    },
    "WhatsApp Image 2026-08-25 at 11.46.20.jpeg": {
        "title": "Contrôle des pneus et campagne MVA",
        "performed_at": date(2026, 2, 17),
        "performed_at_source": "document_explicit",
    },
    "WhatsApp Image 2026-08-25 at 11.46.19 (1).jpeg": {
        "title": "Diagnostic du voyant d’huile",
        "event_type": "diagnostic",
        "category": "Diagnostic",
    },
    "WhatsApp Image 2026-08-25 at 11.46.21.jpeg": {
        "title": "Mise à jour du logiciel moteur – campagne MVA",
        "event_type": "repair",
        "category": "Campagne constructeur",
    },
    "WhatsApp Image 2026-08-25 at 11.46.23 (1).jpeg": {
        "title": "Révision Peugeot à l’huile de synthèse",
    },
    "WhatsApp Image 2026-08-25 at 11.46.23 (2).jpeg": {
        "title": "Entretien Peugeot – vidange et filtre à huile",
    },
    "WhatsApp Image 2026-08-25 at 11.46.23.jpeg": {
        "title": "Mise à jour du logiciel moteur – campagne MVA (facture)",
        "event_type": "repair",
        "category": "Campagne constructeur",
    },
    "WhatsApp Image 2026-08-25 at 11.46.24.jpeg": {
        "title": "Montage et équilibrage des pneumatiques",
    },
    "WhatsApp Image 2026-08-25 at 11.46.24 (4).jpeg": {
        "title": "Révision et remplacement des plaquettes arrière",
    },
    "WhatsApp Image 2026-08-25 at 11.46.24 (7).jpeg": {
        "title": "Plan d’entretien constructeur Peugeot",
        "category": "Plan d’entretien",
    },
    "WhatsApp Image 2026-08-25 at 11.46.24 (8).jpeg": {
        "title": "Plan d’entretien Peugeot – édition 2023",
        "category": "Plan d’entretien",
    },
    "WhatsApp Image 2026-08-25 at 11.46.24 (9).jpeg": {
        "title": "Remplacement du kit de distribution et révision moteur",
    },
    "WhatsApp Image 2026-08-25 at 11.46.25.jpeg": {
        "title": "Révision complète, plaquettes avant et pneumatiques",
    },
    "WhatsApp Image 2026-08-25 at 11.46.25 (1).jpeg": {
        "title": "Campagne MVA à réaliser – logiciel moteur",
        "event_type": "diagnostic",
        "category": "Campagne constructeur",
        "performed_at": date(2025, 12, 11),
        "performed_at_source": "document_explicit",
    },
    "WhatsApp Image 2026-08-25 at 11.46.25 (3).jpeg": {
        "title": "Contrôle technique périodique – facture",
        "category": "Contrôle technique",
    },
    "WhatsApp Image 2026-08-25 at 11.46.25 (4).jpeg": {
        "title": "Contrôle technique favorable – 4 défaillances mineures",
        "event_type": "technical_inspection",
        "category": "Contrôle technique",
    },
    "WhatsApp Image 2026-08-25 at 11.46.25 (6).jpeg": {
        "title": "Vidange, bobine et bougies d’allumage",
    },
    "WhatsApp Image 2026-08-25 at 11.46.25 (7).jpeg": {
        "title": "Contrôle qualité Peugeot – 100 points",
        "performed_at": date(2018, 8, 22),
        "performed_at_source": "document_explicit",
    },
    "WhatsApp Image 2026-08-25 at 11.46.25 (8).jpeg": {
        "title": "Contrôle technique favorable – antibrouillards à régler",
        "event_type": "technical_inspection",
        "category": "Contrôle technique",
        "performed_at": date(2022, 5, 9),
        "performed_at_source": "document_explicit",
    },
    "WhatsApp Image 2026-08-25 at 11.46.15.jpeg": {
        "title": "Achat d’huile moteur Total Quartz Ineo RCP 5W-30",
        "category": "Pièces et consommables",
    },
    "280736037-T250353834-A122887755-VFT0060166688.pdf": {
        "title": "Remplacement des disques et plaquettes avant",
        "event_type": "repair",
        "category": "Freinage",
    },
}


def _source_names(record: MaintenanceRecord) -> set[str]:
    names: set[str] = set()
    for document in record.documents:
        names.update(document.source_names)
        if not document.normalized:
            names.add(document.original_name)
    return names


def _rotation_map(path: Path) -> dict[str, int]:
    if not path.is_file():
        return {}
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, list):
        raise ValueError("Le journal OCR de rotation doit être une liste.")
    rotations: dict[str, int] = {}
    for item in payload:
        if not isinstance(item, dict):
            continue
        name = item.get("fichier_source")
        degrees = (item.get("ocr") or {}).get("rotation_appliquee_degres")
        if isinstance(name, str) and degrees in {0, 90, 180, 270}:
            rotations[name] = int(degrees)
    return rotations


def _input_from_record(record: MaintenanceRecord, corrections: dict) -> MaintenanceRecordInput:
    payload = record.model_dump(
        mode="python",
        exclude={"id", "created_at", "updated_at", "revision", "documents"},
    )
    payload.update(corrections)
    recommendations = [dict(value) for value in payload.get("recommendations") or []]
    source_names = _source_names(record)

    def close(item: dict, status: str, reason: str, completed_at: date | None = None) -> None:
        item.update({
            "status": status,
            "auto_managed": False,
            "completed_by_record_id": None,
            "completed_at": completed_at if status == "completed" else None,
            "completion_reason": reason,
        })

    if "WhatsApp Image 2026-08-25 at 11.46.24 (4).jpeg" in source_names:
        for recommendation in recommendations:
            title = str(recommendation.get("title") or "")
            plain_title = title.casefold()
            if "prochain entretien" in plain_title:
                close(
                    recommendation, "dismissed",
                    "Ancienne échéance remplacée par les entretiens enregistrés depuis.",
                )
            elif "2 à 4mm" in title or "2 à 4 mm" in title:
                close(
                    recommendation, "completed",
                    "Mesure effectuée avant le remplacement des plaquettes arrière réalisé sur cette même intervention.",
                    date(2025, 2, 28),
                )
            elif title.startswith("GAUCHE A REMPLACER") or title.startswith("DROIT A REMPLACER"):
                close(
                    recommendation, "completed",
                    "Pneumatiques avant remplacés lors de l’intervention du 07/07/2025.",
                    date(2025, 7, 7),
                )
            elif title == "A REMPLACER":
                close(
                    recommendation, "completed",
                    "Balai d’essuie-glace arrière remplacé sur cette même intervention.",
                    date(2025, 2, 28),
                )
            elif "USE 75%" in title:
                close(
                    recommendation, "dismissed",
                    "Constat remplacé par la recommandation plus récente de remplacement des pneus arrière.",
                )

    if "WhatsApp Image 2026-08-25 at 11.46.24.jpeg" in source_names:
        for recommendation in recommendations:
            title = str(recommendation.get("title") or "")
            if "3 à 5mm" in title or "3 à 5 mm" in title:
                close(
                    recommendation, "completed",
                    "Plaquettes avant remplacées le 22/08/2026.",
                    date(2026, 8, 22),
                )
            elif title.startswith("GAUCHE A REMPLACER") or title.startswith("DROIT A REMPLACER"):
                close(
                    recommendation, "completed",
                    "Disques avant remplacés le 22/08/2026.",
                    date(2026, 8, 22),
                )
            elif "rotules axiale" in title.casefold():
                recommendation["title"] = "Rotules axiales à remplacer"

    if "WhatsApp Image 2026-08-25 at 11.46.19.jpeg" in source_names:
        for recommendation in recommendations:
            if "pneu" in str(recommendation.get("title") or "").casefold():
                recommendation.update({
                    "title": "Remplacer les deux pneus arrière",
                    "details": "Deux pneus arrière signalés en sous-pression ; remplacement demandé par l’utilisateur.",
                    "recommended_at_km": 105_221,
                    "due_mileage_km": 105_221,
                    "confidence": "high",
                })

    if "WhatsApp Image 2026-08-25 at 11.46.20.jpeg" in source_names:
        for recommendation in recommendations:
            if "pression" in str(recommendation.get("title") or "").casefold():
                close(
                    recommendation, "dismissed",
                    "Ancien contrôle de pression remplacé par le constat plus récent du 21/08/2026.",
                )

    if "WhatsApp Image 2026-08-25 at 11.46.23 (2).jpeg" in source_names:
        for recommendation in recommendations:
            if str(recommendation.get("title") or "").startswith("Prochaine échéance"):
                close(
                    recommendation, "dismissed",
                    "Échéance 2024 remplacée par les entretiens réalisés depuis.",
                )

    if "WhatsApp Image 2026-08-25 at 11.46.25 (8).jpeg" in source_names:
        for recommendation in recommendations:
            if "BROUILLARD" in str(recommendation.get("title") or ""):
                close(
                    recommendation, "dismissed",
                    "Constat 2022 remplacé par le contrôle technique plus récent du 09/06/2026.",
                )

    if "WhatsApp Image 2026-08-25 at 11.46.25 (4).jpeg" in source_names:
        for recommendation in recommendations:
            if "PNEUMATIQUES" in str(recommendation.get("title") or ""):
                close(
                    recommendation, "dismissed",
                    "Constat regroupé dans la recommandation actuelle de remplacement des deux pneus arrière.",
                )
            elif "SUSPENSION" in str(recommendation.get("title") or ""):
                close(
                    recommendation, "dismissed",
                    "Confirmation 2026 regroupée dans la recommandation ouverte depuis 2024 sur les bras inférieurs et silentblocs.",
                )

    if "WhatsApp Image 2026-08-25 at 11.46.24 (9).jpeg" in source_names:
        merged: list[dict] = []
        for recommendation in recommendations:
            if str(recommendation.get("title") or "").startswith("blocs fortement"):
                continue
            if str(recommendation.get("title") or "").startswith("Bras inferieur"):
                recommendation["title"] = (
                    "Bras inférieurs avant gauche et droit à remplacer "
                    "(silentblocs fortement détériorés)"
                )
                recommendation["details"] = (
                    "Signalé dès le 15/02/2024 ; le contrôle technique 2026 "
                    "confirme encore un silentbloc avant droit détérioré."
                )
            merged.append(recommendation)
        recommendations = merged

    if "WhatsApp Image 2026-08-25 at 11.46.25 (4).jpeg" in source_names:
        for recommendation in recommendations:
            if str(recommendation.get("title") or "").startswith("légèrement usé"):
                recommendation["title"] = (
                    "Disques de frein avant légèrement usés : AVD, AVG"
                )

    if "WhatsApp Image 2026-08-25 at 11.46.25 (1).jpeg" in source_names:
        if not any(
            "campagne mva" in str(value.get("title") or "").casefold()
            for value in recommendations
        ):
            recommendations.append(MaintenanceRecommendation(
                title="Campagne MVA – mettre à jour le logiciel du calculateur moteur",
                status="open",
                source="document",
                confidence="high",
            ).model_dump(mode="python"))

    payload["recommendations"] = recommendations
    return MaintenanceRecordInput.model_validate(payload)


def migrate(
    vin: str,
    rotation_log: Path,
    *,
    apply: bool,
    force_documents: bool,
) -> dict[str, int]:
    rotations = _rotation_map(rotation_log)
    records = list_maintenance_records(vin)
    corrected = normalized = skipped_documents = 0
    for original_record in records:
        source_names = _source_names(original_record)
        corrections: dict = {}
        for source_name in source_names:
            corrections.update(SOURCE_CORRECTIONS.get(source_name, {}))

        expected = _input_from_record(original_record, corrections)
        current_payload = original_record.model_dump(
            mode="python",
            exclude={"id", "created_at", "updated_at", "revision", "documents"},
        )
        changed = expected.model_dump(mode="python") != current_payload
        print(
            f"{'CORRIGER' if changed else 'CONSERVER'} {original_record.id} — "
            f"{expected.title}"
        )
        record = original_record
        if changed:
            corrected += 1
            if apply:
                record = update_maintenance_record(original_record.id, expected)

        already_normalized = bool(record.documents and record.documents[0].normalized)
        if already_normalized and not force_documents:
            skipped_documents += 1
            continue
        if apply:
            normalize_maintenance_documents(
                vin,
                record.id,
                rotations_by_original_name=rotations,
            )
        normalized += 1

    reconciled = reconcile_maintenance_recommendations(vin) if apply else 0
    return {
        "records_total": len(records),
        "records_corrected": corrected,
        "pdf_normalized": normalized,
        "pdf_already_normalized": skipped_documents,
        "records_reconciled": reconciled,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--vin", default=DEFAULT_VIN)
    parser.add_argument("--rotation-log", type=Path, default=DEFAULT_ROTATION_LOG)
    parser.add_argument("--apply", action="store_true", help="Écrit les corrections et les PDF.")
    parser.add_argument("--force-documents", action="store_true")
    arguments = parser.parse_args()
    summary = migrate(
        arguments.vin,
        arguments.rotation_log.expanduser().resolve(),
        apply=arguments.apply,
        force_documents=arguments.force_documents,
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    if not arguments.apply:
        print("Simulation uniquement : relancer avec --apply pour écrire les changements.")


if __name__ == "__main__":
    main()
