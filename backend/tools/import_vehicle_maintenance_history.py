#!/usr/bin/env python3
"""Importe les sorties JSON de vehicle_document_ocr dans le dossier OBD d'un VIN.

L'import est volontairement idempotent et conserve le résultat OCR brut à côté
des valeurs normalisées. Une facture de fournisseur de pièces sans date de pose
devient un brouillon : sa date d'achat n'est jamais transformée silencieusement
en date d'intervention.
"""

from __future__ import annotations

import argparse
import asyncio
from datetime import date, datetime, timezone
import json
from pathlib import Path
import re
import sys
import unicodedata

from fastapi import UploadFile

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.diagnostic.maintenance_history import (
    MaintenanceCostLine,
    MaintenancePart,
    MaintenanceRecommendation,
    MaintenanceRecordInput,
    add_maintenance_document,
    create_maintenance_record,
    list_maintenance_records,
    normalize_maintenance_documents,
    reconcile_duplicate_maintenance_record,
    update_maintenance_record,
)
from app.maintenance.models import (
    DocumentImportSnapshot,
    ImportedField,
    ServiceProvider,
    ServiceProviderInput,
)
from app.maintenance.providers import (
    create_service_provider,
    match_service_provider,
)


DEFAULT_VIN = "VF3LPHNYWJS141966"
DEFAULT_PROFILE = "peugeot_308_t9_2018"
CONFIDENCE = {"haute": "high", "moyenne": "medium", "basse": "low"}


def _plain(value: str | None) -> str:
    return "".join(
        character
        for character in unicodedata.normalize("NFKD", value or "")
        if not unicodedata.combining(character)
    ).casefold()


def _read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def _date(value: str | None) -> date | None:
    try:
        return date.fromisoformat(value) if value else None
    except ValueError:
        return None


def _provider_kind(name: str) -> str:
    plain = _plain(name)
    if any(value in plain for value in ("oscaro", "ovoko", "autodoc", "mister auto")):
        return "parts_supplier"
    if any(value in plain for value in ("controle technique", "controle automobile", "controles du", "norisko", "cta francazal")):
        return "inspection_center"
    if "carrosserie" in plain:
        return "body_shop"
    if any(value in plain for value in ("pneu", "norauto", "feu vert")):
        return "tire_shop"
    if any(value in plain for value in ("peugeot", "stellantis", "fiat", "automobiles", "sonoma")):
        return "dealership"
    if any(value in plain for value in ("garage", "auto service", "speedy")):
        return "garage"
    return "other"


def _strict_identifier(text: str, label: str, length: int) -> str | None:
    match = re.search(rf"\b{label}\s*[:#]?\s*([\d ]{{{length},{length + 6}}})", text, re.I)
    if not match:
        return None
    value = re.sub(r"\D", "", match.group(1))
    return value if len(value) == length else None


def _provider_input(name: str, text: str) -> ServiceProviderInput:
    vat_match = re.search(r"\b(?:TVA|VAT)[^A-Z0-9]{0,25}([A-Z]{2}\s*[A-Z0-9 ]{8,16})", text, re.I)
    vat = re.sub(r"\s", "", vat_match.group(1)).upper() if vat_match else None
    if vat and not 10 <= len(vat) <= 24:
        vat = None
    phone_match = re.search(r"(?:T[ée]l(?:[ée]phone)?|Phone)\s*[:#]?\s*([+\d][\d .-]{7,})", text, re.I)
    email_match = re.search(r"[\w.+-]+@[\w.-]+\.[A-Z]{2,}", text, re.I)
    city_match = re.search(r"(?m)^\s*(\d{5})\s+([A-ZÀ-ÖØ-Ý][A-ZÀ-ÖØ-Ý '’-]{2,})\s*$", text)
    return ServiceProviderInput(
        kind=_provider_kind(name),
        legal_name=name,
        siren=_strict_identifier(text, "SIREN", 9),
        siret=_strict_identifier(text, "SIRET", 14),
        vat_number=vat,
        postal_code=city_match.group(1) if city_match else None,
        city=city_match.group(2).strip().title() if city_match else None,
        phone=phone_match.group(1).strip() if phone_match else None,
        email=email_match.group(0) if email_match else None,
        aliases=[name],
        verified_by_user=False,
    )


def _ensure_provider(name: str | None, text: str) -> ServiceProvider | None:
    if not name:
        return None
    candidate = _provider_input(name, text)
    if matched := match_service_provider(candidate):
        return matched
    return create_service_provider(candidate)


def _line_type(line: dict) -> str:
    plain = _plain(line.get("designation"))
    if any(value in plain for value in ("promotion", "remise", "discount")) or (line.get("montant_ht_eur") or 0) < 0:
        return "discount"
    if any(value in plain for value in ("frais de port", "expedition", "shipping", "livraison")):
        return "shipping"
    if "main d'oeuvre" in plain or "taux mo" in plain or line.get("temps_heures") is not None:
        return "labor"
    return {"piece": "part", "produit": "product", "service": "service"}.get(line.get("type_ligne"), "other")


def _cost_line(line: dict) -> MaintenanceCostLine:
    return MaintenanceCostLine(
        line_type=_line_type(line),
        description=str(line.get("designation") or "Ligne non libellée"),
        reference=line.get("reference"),
        tariff_code=line.get("code_tarif"),
        quantity=line.get("quantite"),
        labor_hours=line.get("temps_heures"),
        unit_price_excl_tax=line.get("prix_unitaire_ht_eur"),
        unit_price_incl_tax=line.get("prix_unitaire_ttc_eur"),
        discount_percent=line.get("remise_pct"),
        net_unit_price_excl_tax=line.get("prix_unitaire_net_ht_eur"),
        amount_excl_tax=line.get("montant_ht_eur"),
        amount_incl_tax=line.get("montant_ttc_eur"),
        page_number=line.get("numero_page"),
        confidence=CONFIDENCE.get(line.get("confiance"), "unknown"),
        source_text=[str(value) for value in (line.get("texte_source") or [])[:30]],
    )


def _part_usage(description: str, line_type: str) -> str | None:
    plain = _plain(description)
    if line_type not in {"part", "product", "other"}:
        return None
    if any(value in plain for value in ("brosse", "outil", "douille", "cle ")):
        return "tool"
    if any(value in plain for value in ("huile", "lubrifiant", "liquide", "pate a joint", "lave vitre")):
        return "consumed"
    if line_type == "part" or any(value in plain for value in ("filtre", "bougie", "camera", "pneu", "plaquette", "disque", "joint")):
        return "installed"
    return None


def _system_code(description: str) -> str | None:
    plain = _plain(description)
    if any(value in plain for value in ("frein", "plaquette", "disque")):
        return "brakes"
    if any(value in plain for value in ("rotule", "bras inferieur", "silentbloc", "suspension")):
        return "suspension"
    if "camera" in plain:
        return "adas.camera"
    if any(value in plain for value in ("huile", "vidange", "filtre a huile")):
        return "engine.lubrication"
    if any(value in plain for value in ("pneu", "225/")):
        return "tires"
    if any(value in plain for value in ("bougie", "bobine")):
        return "engine.ignition"
    return None


def _manufacturer(description: str) -> str | None:
    brands = ("BOSCH", "FERODO", "GOODYEAR", "TOTAL", "QUARTZ", "KS TOOLS", "PEUGEOT")
    upper = description.upper()
    return next((brand.title() for brand in brands if brand in upper), None)


def _parts(event: dict) -> list[MaintenancePart]:
    result: list[MaintenancePart] = []
    for index, line in enumerate(event.get("lignes_facture") or []):
        description = str(line.get("designation") or "")
        line_type = _line_type(line)
        usage = _part_usage(description, line_type)
        if not usage:
            continue
        result.append(MaintenancePart(
            name=description[:160],
            manufacturer=_manufacturer(description),
            part_number=line.get("reference"),
            quantity=line.get("quantite") or 1,
            unit_price=line.get("prix_unitaire_ttc_eur") or line.get("prix_unitaire_ht_eur"),
            note="Prix HT" if line.get("prix_unitaire_ttc_eur") is None and line.get("prix_unitaire_ht_eur") is not None else None,
            usage=usage,
            system_code=_system_code(description),
            invoice_line_id=f"{event['identifiant_document']}:{index + 1}",
        ))
    return result


def _recommendations(event: dict) -> list[MaintenanceRecommendation]:
    if event.get("recommendations_obd") is not None:
        return [
            MaintenanceRecommendation.model_validate(value)
            for value in event.get("recommendations_obd") or []
        ]
    result: list[MaintenanceRecommendation] = []
    seen: set[str] = set()
    mileage = event.get("kilometrage")
    event_date = _date(event.get("date"))

    def add(title: str, *, source: str, confidence: str, status: str = "open", details: str | None = None) -> None:
        normalized = " ".join(title.split()).strip(" -")
        key = _plain(normalized)
        if not normalized or key in seen:
            return
        seen.add(key)
        follow_up = 500 if "rodage" in key and "500" in key else None
        due_km = None
        relative = re.search(r"(?:dans|pendant)\s+(\d[\d ]{2,})\s*km", key)
        if relative and mileage:
            due_km = int(re.sub(r"\D", "", relative.group(1))) + int(mileage)
        result.append(MaintenanceRecommendation(
            title=normalized[:300], details=details, status=status, source=source,
            recommended_at_km=mileage, due_mileage_km=due_km,
            follow_up_after_km=follow_up, confidence=confidence,
        ))

    for value in event.get("conseils_maintenance") or []:
        add(str(value), source="document", confidence=CONFIDENCE.get(event.get("confiance"), "unknown"))
    for value in event.get("anomalies_ou_points_attention") or []:
        add(str(value), source="document", confidence=CONFIDENCE.get(event.get("confiance"), "unknown"))
    for note in event.get("notes_manuscrites") or []:
        text = str(note.get("transcription") or "")
        status = "completed" if any(value in _plain(text) for value in ("faite ce jour", "fait ce jour")) else "open"
        add(
            text, source="handwritten_note", confidence=CONFIDENCE.get(note.get("confiance"), "unknown"),
            status=status, details=f"Transcription brute : {note.get('transcription_brute_ocr')}" if note.get("transcription_brute_ocr") else None,
        )
    due_date = _date(event.get("prochaine_echeance_date"))
    due_mileage = event.get("prochaine_echeance_km")
    if (due_date and (not event_date or due_date > event_date)) or (due_mileage and (not mileage or due_mileage > mileage)):
        result.append(MaintenanceRecommendation(
            title="Prochaine échéance indiquée sur le document", status="open", source="document",
            recommended_at_km=mileage, due_date=due_date if not event_date or due_date > event_date else None,
            due_mileage_km=due_mileage if not mileage or due_mileage > mileage else None, confidence="medium",
        ))
    return result


def _title(event: dict, text: str = "") -> str:
    """Décrit le travail ou le constat, plutôt que le contenant du document."""

    if event.get("objet"):
        return str(event["objet"])[:180]

    provider = event.get("enseigne_ou_garage")
    lines = event.get("lignes_facture") or []
    descriptions = [str(line.get("designation") or "") for line in lines]
    recommendations = [str(value) for value in event.get("conseils_maintenance") or []]
    recommendations.extend(str(value) for value in event.get("anomalies_ou_points_attention") or [])
    recommendations.extend(
        str(note.get("transcription") or "")
        for note in event.get("notes_manuscrites") or []
        if isinstance(note, dict)
    )
    joined = _plain(" ".join([*descriptions, *recommendations, text]))
    if event.get("nature_evenement") == "achat_pieces":
        if "camera" in joined:
            return f"Caméra pare-brise – pièces {provider or 'achetées'}"
        if any(value in joined for value in ("frein", "plaquette", "disque")):
            return f"Freinage – pièces {provider or 'achetées'}"
        return f"Pièces posées – {provider or 'achat fournisseur'}"
    if event.get("type_document") == "fiche_controle":
        if "proces verbal" in joined and "controle technique" in joined:
            anomalies = event.get("anomalies_ou_points_attention") or []
            if "feux de brouillard" in joined and len(anomalies) == 1:
                return "Contrôle technique favorable – antibrouillards à régler"
            if anomalies:
                return f"Contrôle technique favorable – {len(anomalies)} défaillance{'s' if len(anomalies) > 1 else ''} mineure{'s' if len(anomalies) > 1 else ''}"
            return "Contrôle technique favorable"
        if "100 points de controle" in joined or "certificat de qualite" in joined:
            return "Contrôle qualité Peugeot – 100 points"
        if "voyant huile" in joined:
            return "Diagnostic du voyant d’huile"
        if "pression" in joined and "pneu" in joined and "campagne mva" in joined:
            return "Contrôle des pneus et campagne MVA"
        if "pression" in joined and "pneu" in joined:
            position = " arrière" if "arriere" in joined else ""
            return f"Contrôle de la pression des pneus{position}"
        if "vidange huile moteur" in joined or "filtre a huile" in joined:
            return "Entretien Peugeot – vidange et filtre à huile"
        return "Contrôle du véhicule"
    if event.get("type_document") == "rapport_entretien":
        if "campagne" in joined:
            return f"Campagne après-vente{f' – {provider}' if provider else ''}"
        return f"Compte rendu d’entretien{f' – {provider}' if provider else ''}"
    rear_pads = "plaquette" in joined and any(value in joined for value in (" ar ", "arriere"))
    front_pads = "plaquette" in joined and any(value in joined for value in (" av ", "avant"))
    if rear_pads and any(value in joined for value in ("revision", "entretien")):
        return "Révision et remplacement des plaquettes arrière"
    if "kit" in joined and "courroie" in joined and any(value in joined for value in ("revision", "entretien")):
        return "Remplacement du kit de distribution et révision moteur"
    if front_pads and "pneumatique" in joined:
        return "Révision, plaquettes avant et pneumatique"
    if "bobine d'allumage" in joined and "bougie d'allumage" in joined:
        return "Vidange, bobine et bougies d’allumage"
    if "montage pneu" in joined:
        return "Montage et équilibrage des pneumatiques"
    if "vidange" in joined or "revision" in joined or "entretien" in joined:
        return f"Révision / entretien{f' – {provider}' if provider else ''}"
    if descriptions:
        return descriptions[0][:180]
    if event.get("numero_document"):
        return f"Facture {event['numero_document']}{f' – {provider}' if provider else ''}"
    return f"Document d’entretien{f' – {provider}' if provider else ''}"


def _event_type(event: dict) -> str:
    if event.get("event_type_obd"):
        return str(event["event_type_obd"])
    kind = event.get("type_document")
    text = _plain(" ".join(str(line.get("designation") or "") for line in event.get("lignes_facture") or []))
    if kind == "fiche_controle":
        return "inspection"
    if kind == "rapport_entretien":
        return "maintenance"
    if any(value in text for value in ("remplacement", "remplacer", "bobine", "joint", "camera")):
        return "repair"
    return "maintenance" if kind == "facture" else "other"


def _document_kind(event: dict) -> str:
    if event.get("document_kind_obd"):
        return str(event["document_kind_obd"])
    return {
        "facture": "invoice",
        "fiche_controle": "recommendation",
        "rapport_entretien": "work_order",
    }.get(event.get("type_document"), "other")


def _page_text(source_names: list[str], page_records: dict[str, dict]) -> str:
    return "\n\n".join(
        str((page_records.get(name, {}).get("ocr") or {}).get("texte_integral") or "")
        for name in source_names
    ).strip()


def _snapshot(event: dict, source_names: list[str], page_records: dict[str, dict], vehicle_vin: str) -> DocumentImportSnapshot:
    text = _page_text(source_names, page_records)
    proofs: dict[str, dict] = {}
    engines: list[str] = []
    for name in source_names:
        record = page_records.get(name, {})
        for key, value in (record.get("preuves_champs") or {}).items():
            proofs.setdefault(key, value)
        engine = (record.get("ocr") or {}).get("moteur")
        if engine and engine not in engines:
            engines.append(engine)
    normalized = {
        "date": event.get("date"), "mileage_km": event.get("kilometrage"),
        "provider": event.get("enseigne_ou_garage"), "invoice_number": event.get("numero_document"),
        "client_name": event.get("client_nom"), "vin": event.get("vin"),
        "registration": event.get("immatriculation"), "invoice_total": event.get("montant_total_eur"),
    }
    fields: dict[str, ImportedField] = {}
    for key, value in normalized.items():
        proof = proofs.get(key) or proofs.get({"mileage_km": "kilometrage", "provider": "enseigne_ou_garage", "invoice_number": "numero_document", "client_name": "client_nom", "invoice_total": "montant_total_eur"}.get(key, "")) or {}
        fields[key] = ImportedField(
            raw_value=proof.get("texte_source") if proof else value,
            normalized_value=value,
            confidence=proof.get("confiance_ocr") if isinstance(proof.get("confiance_ocr"), (float, int)) else None,
            evidence=proof.get("texte_source"),
        )
    warnings = [str(value) for value in event.get("champs_a_verifier") or []]
    if event.get("vin") and event.get("vin") != vehicle_vin:
        warnings.append(
            f"VIN OCR discordant ({event['vin']}) : non retenu face au VIN confirmé {vehicle_vin}."
        )
    return DocumentImportSnapshot(
        engine=" + ".join(engines) or "vehicle_document_ocr",
        analyzed_at=datetime.now(timezone.utc),
        fields=fields,
        raw_payload={"maintenance_event": event},
        text_excerpt=text[:20_000],
        warnings=warnings,
    )


def _notes(event: dict) -> str | None:
    lines: list[str] = []
    if event.get("commentaire_utilisateur"):
        lines.append(str(event["commentaire_utilisateur"]))
    if event.get("notes"):
        lines.append(str(event["notes"]))
    for note in event.get("notes_manuscrites") or []:
        label = "Note manuscrite validée" if note.get("statut") == "validee_visuellement" else "Note manuscrite à vérifier"
        lines.append(f"{label} : {note.get('transcription')}")
    if event.get("champs_a_verifier"):
        lines.append("Champs à vérifier : " + "; ".join(str(value) for value in event["champs_a_verifier"]))
    return "\n".join(lines)[:5_000] or None


def _record_input(event: dict, vin: str, profile: str, page_records: dict[str, dict]) -> MaintenanceRecordInput:
    source_names = [str(value) for value in event.get("fichiers_sources") or []]
    text = _page_text(source_names, page_records)
    provider = _ensure_provider(event.get("enseigne_ou_garage"), text)
    provider_kind = provider.kind if provider else None
    purchase_date = _date(event.get("date")) if event.get("type_document") == "facture" else None
    parts_purchase = event.get("nature_evenement") == "achat_pieces" or provider_kind == "parts_supplier"
    status_override = event.get("record_status_obd")
    performed_at = None if parts_purchase or event.get("type_document") == "devis" or status_override == "draft" else _date(event.get("date"))
    performed_by = "owner" if event.get("realise_par") == "proprietaire" else "service_provider" if provider and performed_at else "unknown"
    pagination = {"complete": "complete", "inferee": "inferred", "non_indiquee": "unknown"}.get(event.get("pagination_statut"), "unknown")
    event_vin = event.get("vin") if event.get("vin") == vin else None
    cost_lines = [_cost_line(line) for line in event.get("lignes_facture") or []]
    labor_hours = sum(line.labor_hours or 0 for line in cost_lines) or None
    return MaintenanceRecordInput(
        vin=vin, vehicle_profile=profile, schema_version=1,
        record_status=status_override or ("draft" if performed_at is None else "confirmed"),
        source_system="vehicle_document_ocr",
        source_import_key=f"vehicle_document_ocr:{event['identifiant_document']}",
        event_type=_event_type(event), purchased_at=purchase_date, performed_at=performed_at,
        performed_at_source="invoice_date_assumed" if performed_at and event.get("type_document") == "facture" else "document_explicit" if performed_at else "manual",
        mileage_km=event.get("kilometrage"), mileage_source="invoice" if event.get("kilometrage") is not None else "manual",
        mileage_note="Kilométrage extrait du document source." if event.get("kilometrage") is not None else None,
        title=_title(event, text), category=event.get("category_obd") or {"facture": "Facture", "fiche_controle": "Contrôle", "rapport_entretien": "Rapport d’entretien"}.get(event.get("type_document"), "Document"),
        workshop=event.get("enseigne_ou_garage"), performed_by=performed_by,
        performer_provider_id=provider.id if performed_by == "service_provider" else None,
        seller_provider_id=provider.id if provider and provider.kind == "parts_supplier" else None,
        invoice_issuer_provider_id=provider.id if provider and event.get("type_document") == "facture" else None,
        invoice_number=event.get("numero_document"), document_client_name=event.get("client_nom"),
        document_vehicle_vin=event_vin, document_registration=event.get("immatriculation"),
        document_page_count=event.get("nombre_pages") or len(source_names) or None,
        document_pagination_status=pagination, document_dossier_id=event.get("identifiant_dossier"),
        invoice_subtotal=event.get("montant_ht_eur"), invoice_tax=event.get("montant_tva_eur"),
        invoice_total=event.get("montant_total_eur"), currency="EUR", labor_hours=labor_hours,
        notes=_notes(event), parts=_parts(event), cost_lines=cost_lines,
        recommendations=_recommendations(event), import_snapshot=_snapshot(event, source_names, page_records, vin),
    )


async def _attach_sources(record, event: dict, document_dir: Path) -> int:
    attached = 0
    existing = {document.original_name for document in record.documents}
    for document in record.documents:
        existing.update(document.source_names)
    for name in event.get("fichiers_sources") or []:
        path = document_dir / str(name)
        if path.name in existing:
            continue
        if not path.is_file():
            print(f"AVERTISSEMENT document absent : {path}")
            continue
        upload = UploadFile(filename=path.name, file=path.open("rb"))
        record = await add_maintenance_document(record.vin, record.id, upload, _document_kind(event))
        existing.add(path.name)
        attached += 1
    return attached


def _same_source(record, event: dict) -> bool:
    names = {str(value) for value in event.get("fichiers_sources") or []}
    record_source_names = {
        source_name
        for document in record.documents
        for source_name in document.source_names
    }
    return bool(
        names.intersection(record_source_names)
        or names.intersection(document.original_name for document in record.documents)
        or (
            event.get("numero_document")
            and record.invoice_number == event.get("numero_document")
        )
    )


def _merge_with_confirmed_record(record, imported: MaintenanceRecordInput):
    notes = [value for value in (record.notes, imported.notes) if value]
    merged_notes = "\n\n".join(dict.fromkeys(notes)) or None
    if record.invoice_total is not None and imported.invoice_total is not None and record.invoice_total != imported.invoice_total:
        merged_notes = (merged_notes + "\n\n" if merged_notes else "") + (
            f"Ancien total saisi avant lecture détaillée : {record.invoice_total:.2f} EUR. "
            f"Total du document importé : {imported.invoice_total:.2f} EUR."
        )
    parts = list(record.parts)
    known = {re.sub(r"\W", "", part.part_number or "").casefold() for part in parts if part.part_number}
    for part in imported.parts:
        reference = re.sub(r"\W", "", part.part_number or "").casefold()
        if part.usage not in {"tool", "consumed"} or (reference and reference in known):
            continue
        parts.append(part)
        if reference:
            known.add(reference)
    recommendations = list(record.recommendations)
    recommendation_keys = {_plain(item.title) for item in recommendations}
    recommendations.extend(item for item in imported.recommendations if _plain(item.title) not in recommendation_keys)
    payload = MaintenanceRecordInput(
        **{
            **imported.model_dump(),
            "record_status": "confirmed",
            "performed_at": record.performed_at,
            "performed_at_source": record.performed_at_source,
            "mileage_km": record.mileage_km,
            "mileage_source": record.mileage_source,
            "mileage_note": record.mileage_note,
            "title": record.title,
            "category": record.category,
            "workshop": record.workshop,
            "performed_by": "owner",
            "performer_provider_id": None,
            "labor_hours": record.labor_hours,
            "notes": merged_notes,
            "parts": [part.model_dump() for part in parts],
            "recommendations": [item.model_dump() for item in recommendations],
        }
    )
    return update_maintenance_record(record.id, payload)


async def run_import(data_dir: Path, document_dir: Path, vin: str, profile: str) -> dict[str, int]:
    events = _read_json(data_dir / "maintenance_events.json")
    log = _read_json(data_dir / "maintenance_log.json")
    page_records = {str(record["fichier_source"]): record for record in log}
    records = list_maintenance_records(vin)
    existing_keys = {record.source_import_key for record in records if record.source_import_key}
    created = existing = documents = reconciled = 0
    for event in events:
        entry = _record_input(event, vin, profile, page_records)
        manual_record = next(
            (
                record for record in records
                if not record.source_import_key and _same_source(record, event)
            ),
            None,
        )
        imported_record = next(
            (record for record in records if record.source_import_key == entry.source_import_key),
            None,
        )
        if manual_record:
            record = _merge_with_confirmed_record(manual_record, entry)
            if imported_record and imported_record.id != record.id:
                reconcile_duplicate_maintenance_record(vin, imported_record.id, record.id)
                records.remove(imported_record)
                reconciled += 1
            records = [record if value.id == record.id else value for value in records]
            existing += 1
        else:
            was_existing = entry.source_import_key in existing_keys
            record = create_maintenance_record(entry)
            if was_existing and not record.documents:
                # Une interruption peut survenir après la sauvegarde d'une
                # source, mais avant la création du PDF public. Régénérer
                # d'abord ce PDF rend la reprise réellement idempotente.
                record = normalize_maintenance_documents(
                    vin,
                    record.id,
                    record_new_revision=False,
                )
            if was_existing:
                existing += 1
            else:
                created += 1
                records.append(record)
                existing_keys.add(entry.source_import_key)
        documents += await _attach_sources(record, event, document_dir)
    return {
        "events_created": created,
        "events_existing": existing,
        "duplicates_reconciled": reconciled,
        "documents_attached": documents,
        "events_total": len(events),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, required=True)
    parser.add_argument("--document-dir", type=Path, required=True)
    parser.add_argument("--vin", default=DEFAULT_VIN)
    parser.add_argument("--vehicle-profile", default=DEFAULT_PROFILE)
    arguments = parser.parse_args()
    summary = asyncio.run(run_import(arguments.data_dir.resolve(), arguments.document_dir.resolve(), arguments.vin, arguments.vehicle_profile))
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
