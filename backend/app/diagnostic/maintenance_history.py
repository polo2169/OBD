from __future__ import annotations

from datetime import date, datetime, timezone
from hashlib import sha256
from pathlib import Path
from typing import Literal
import json
import os
import re
import threading
import unicodedata
import uuid

from fastapi import UploadFile
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.config import settings
from app.diagnostic.history import active_vehicle, vehicle_storage_dir
from app.maintenance.models import DocumentImportSnapshot
from app.maintenance.document_normalizer import normalize_sources_to_pdf
from app.maintenance.providers import get_service_provider


_LOCK = threading.RLock()
_RECORD_ID = re.compile(r"^maintenance-[0-9TZ]+-[a-f0-9]{8}$")
_DOCUMENT_ID = re.compile(r"^document-[a-f0-9]{12}$")
_MAX_DOCUMENT_BYTES = 20 * 1024 * 1024
_MAX_DOCUMENTS_PER_RECORD = 20
_CHUNK_SIZE = 1024 * 1024


class MaintenancePart(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    name: str = Field(min_length=1, max_length=160)
    manufacturer: str | None = Field(default=None, max_length=120)
    part_number: str | None = Field(default=None, max_length=120)
    serial_number: str | None = Field(default=None, max_length=180)
    removed_part_number: str | None = Field(default=None, max_length=120)
    removed_serial_number: str | None = Field(default=None, max_length=180)
    quantity: float = Field(default=1, gt=0, le=10_000)
    unit_price: float | None = Field(default=None, ge=0, le=10_000_000)
    warranty_until: date | None = None
    note: str | None = Field(default=None, max_length=500)
    usage: Literal[
        "installed", "consumed", "tool", "shipping", "discount", "not_used", "returned"
    ] = "installed"
    system_code: str | None = Field(default=None, pattern=r"^[a-z0-9_.-]{2,80}$")
    component_code: str | None = Field(default=None, pattern=r"^[a-z0-9_.-]{2,120}$")
    position: Literal[
        "front", "rear", "front_left", "front_right", "rear_left", "rear_right", "engine", "cabin", "other"
    ] | None = None
    invoice_line_id: str | None = Field(default=None, max_length=120)


class MaintenanceCostLine(BaseModel):
    """Ligne financière fidèle au document, distincte des pièces réellement montées."""

    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    line_type: Literal["part", "product", "service", "labor", "shipping", "discount", "other"] = "other"
    description: str = Field(min_length=1, max_length=500)
    reference: str | None = Field(default=None, max_length=160)
    tariff_code: str | None = Field(default=None, max_length=120)
    quantity: float | None = Field(default=None, gt=0, le=100_000)
    labor_hours: float | None = Field(default=None, ge=0, le=10_000)
    unit_price_excl_tax: float | None = Field(default=None, le=100_000_000)
    unit_price_incl_tax: float | None = Field(default=None, le=100_000_000)
    discount_percent: float | None = Field(default=None, ge=0, le=100)
    net_unit_price_excl_tax: float | None = Field(default=None, le=100_000_000)
    amount_excl_tax: float | None = Field(default=None, ge=-100_000_000, le=100_000_000)
    amount_incl_tax: float | None = Field(default=None, ge=-100_000_000, le=100_000_000)
    page_number: int | None = Field(default=None, ge=1, le=10_000)
    confidence: Literal["high", "medium", "low", "unknown"] = "unknown"
    source_text: list[str] = Field(default_factory=list, max_length=30)


class MaintenanceRecommendation(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    title: str = Field(min_length=1, max_length=300)
    details: str | None = Field(default=None, max_length=2_000)
    status: Literal["open", "monitoring", "completed", "dismissed"] = "open"
    source: Literal["manual", "document", "handwritten_note", "diagnostic"] = "manual"
    recommended_at_km: int | None = Field(default=None, ge=0, le=9_999_999)
    due_date: date | None = None
    due_mileage_km: int | None = Field(default=None, ge=0, le=9_999_999)
    follow_up_after_km: int | None = Field(default=None, ge=1, le=1_000_000)
    confidence: Literal["high", "medium", "low", "unknown"] = "unknown"
    auto_managed: bool = False
    completed_by_record_id: str | None = Field(default=None, pattern=r"^maintenance-[0-9TZ]+-[a-f0-9]{8}$")
    completed_at: date | None = None
    completion_reason: str | None = Field(default=None, max_length=500)


class MaintenanceRecommendationStatusUpdate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    status: Literal["open", "monitoring", "completed", "dismissed"]
    note: str | None = Field(default=None, max_length=500)


class MaintenanceRecordInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    vin: str = Field(min_length=17, max_length=17, pattern=r"^[A-HJ-NPR-Z0-9]{17}$")
    vehicle_profile: str | None = Field(default=None, min_length=1, max_length=100)
    schema_version: Literal[1] = 1
    record_status: Literal["draft", "confirmed"] = "confirmed"
    source_system: str | None = Field(default=None, max_length=100)
    source_import_key: str | None = Field(default=None, min_length=1, max_length=240)
    event_type: Literal[
        "maintenance", "repair", "diagnostic", "inspection", "technical_inspection", "upgrade", "other"
    ] = "maintenance"
    purchased_at: date | None = None
    performed_at: date | None = None
    performed_at_source: Literal[
        "manual", "document_explicit", "vehicle_return", "invoice_date_assumed", "estimated"
    ] = "manual"
    mileage_km: int | None = Field(default=None, ge=0, le=9_999_999)
    mileage_source: Literal["manual", "can_signal", "invoice", "history_estimate"] = "manual"
    mileage_note: str | None = Field(default=None, max_length=500)
    title: str = Field(min_length=1, max_length=180)
    category: str = Field(default="Entretien", min_length=1, max_length=80)
    workshop: str | None = Field(default=None, max_length=180)
    performed_by: Literal["owner", "service_provider", "unknown"] = "unknown"
    performer_provider_id: str | None = Field(default=None, pattern=r"^provider-[a-f0-9]{12}$")
    seller_provider_id: str | None = Field(default=None, pattern=r"^provider-[a-f0-9]{12}$")
    invoice_issuer_provider_id: str | None = Field(default=None, pattern=r"^provider-[a-f0-9]{12}$")
    invoice_number: str | None = Field(default=None, max_length=120)
    document_client_name: str | None = Field(default=None, max_length=180)
    document_vehicle_vin: str | None = Field(
        default=None, min_length=17, max_length=17, pattern=r"^[A-HJ-NPR-Z0-9]{17}$"
    )
    document_registration: str | None = Field(default=None, max_length=30)
    document_page_count: int | None = Field(default=None, ge=1, le=10_000)
    document_pagination_status: Literal["complete", "partial", "inferred", "unknown"] = "unknown"
    document_dossier_id: str | None = Field(default=None, max_length=160)
    invoice_subtotal: float | None = Field(default=None, ge=0, le=100_000_000)
    invoice_tax: float | None = Field(default=None, ge=0, le=100_000_000)
    invoice_total: float | None = Field(default=None, ge=0, le=100_000_000)
    currency: str = Field(default="EUR", min_length=3, max_length=3)
    labor_hours: float | None = Field(default=None, ge=0, le=10_000)
    notes: str | None = Field(default=None, max_length=5_000)
    parts: list[MaintenancePart] = Field(default_factory=list, max_length=100)
    cost_lines: list[MaintenanceCostLine] = Field(default_factory=list, max_length=500)
    recommendations: list[MaintenanceRecommendation] = Field(default_factory=list, max_length=200)
    import_snapshot: DocumentImportSnapshot | None = None

    @field_validator("currency")
    @classmethod
    def normalize_currency(cls, value: str) -> str:
        normalized = value.upper()
        if not re.fullmatch(r"[A-Z]{3}", normalized):
            raise ValueError("La devise doit être un code ISO sur trois lettres.")
        return normalized

    @model_validator(mode="after")
    def validate_performer(self) -> "MaintenanceRecordInput":
        if self.record_status == "confirmed" and self.performed_at is None:
            raise ValueError("Une intervention confirmée doit avoir une date de réalisation.")
        if self.performed_at is None and self.performed_at_source != "manual":
            raise ValueError("La provenance de la date ne peut être définie sans date de réalisation.")
        if self.performed_by == "service_provider" and not self.performer_provider_id:
            raise ValueError("Sélectionne le professionnel qui a réalisé l'intervention.")
        if self.performed_by == "owner" and self.performer_provider_id:
            raise ValueError("Une intervention propriétaire ne doit pas référencer un garage.")
        return self


class MaintenanceDocument(BaseModel):
    id: str
    kind: Literal[
        "invoice", "receipt", "photo", "warranty", "diagnostic_report", "work_order", "recommendation", "other"
    ]
    original_name: str
    media_type: str
    size_bytes: int
    sha256: str
    uploaded_at: datetime
    download_url: str
    page_count: int = Field(default=1, ge=1, le=10_000)
    source_names: list[str] = Field(default_factory=list, max_length=20)
    normalized: bool = False


class MaintenanceRecord(MaintenanceRecordInput):
    id: str
    created_at: datetime
    updated_at: datetime
    revision: int = Field(ge=1)
    documents: list[MaintenanceDocument] = Field(default_factory=list)


class AttachmentTooLargeError(ValueError):
    pass


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _record_root(vin: str) -> Path:
    return vehicle_storage_dir(vin) / "maintenance"


def _record_path(vin: str, record_id: str) -> Path:
    if not _RECORD_ID.fullmatch(record_id):
        raise KeyError("Intervention d’entretien introuvable.")
    return _record_root(vin) / "records" / f"{record_id}.json"


def _read_json(path: Path) -> dict:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise KeyError("Intervention d’entretien introuvable.") from exc
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        raise ValueError(f"Le dossier d’entretien est illisible : {path.name}.") from exc
    if not isinstance(payload, dict):
        raise ValueError(f"Le dossier d’entretien est invalide : {path.name}.")
    return payload


def _atomic_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def _archive_revision(vin: str, payload: dict) -> None:
    record_id = str(payload.get("id") or "")
    revision = int(payload.get("revision") or 1)
    path = _record_root(vin) / "revisions" / record_id / f"revision-{revision:04d}.json"
    if not path.exists():
        _atomic_json(path, payload)


def _public_document(record_id: str, payload: dict) -> MaintenanceDocument:
    return MaintenanceDocument(
        id=str(payload["id"]),
        kind=str(payload.get("kind") or "other"),
        original_name=str(payload["original_name"]),
        media_type=str(payload["media_type"]),
        size_bytes=int(payload["size_bytes"]),
        sha256=str(payload["sha256"]),
        uploaded_at=payload["uploaded_at"],
        download_url=f"/api/maintenance/records/{record_id}/documents/{payload['id']}",
        page_count=int(payload.get("page_count") or 1),
        source_names=[str(value) for value in payload.get("source_names") or []],
        normalized=payload.get("role") == "normalized",
    )


def _public_record(payload: dict) -> MaintenanceRecord:
    public_payload = {
        key: value
        for key, value in payload.items()
        if key != "documents"
    }
    documents = [item for item in payload.get("documents", []) if isinstance(item, dict)]
    normalized_documents = [item for item in documents if item.get("role") == "normalized"]
    visible_documents = normalized_documents or [
        item for item in documents if item.get("role") != "source"
    ]
    public_payload["documents"] = [
        _public_document(str(payload["id"]), document)
        for document in visible_documents
    ]
    return MaintenanceRecord.model_validate(public_payload)


def _resolve_vin(vin: str | None) -> str:
    selected = vin or str((active_vehicle() or {}).get("vin") or "")
    if not selected:
        raise ValueError("Aucun véhicule actif : sélectionne d’abord un VIN dans le Garage.")
    vehicle_storage_dir(selected)
    return selected


def _validate_provider_links(entry: MaintenanceRecordInput) -> None:
    for provider_id in {
        entry.performer_provider_id,
        entry.seller_provider_id,
        entry.invoice_issuer_provider_id,
    }:
        if provider_id:
            get_service_provider(provider_id)


def _plain(value: str | None) -> str:
    return " ".join(
        "".join(
            character
            for character in unicodedata.normalize("NFKD", value or "")
            if not unicodedata.combining(character)
        ).casefold().replace("/", " ").replace("-", " ").split()
    )


def _component_signatures(value: str | None) -> set[str]:
    text = _plain(value)
    signatures: set[str] = set()
    rear = bool(re.search(r"\b(?:ar|arr|arriere|ard|arg)\b", text))
    front = bool(re.search(r"\b(?:av|avant|avd|avg)\b", text))
    if "plaquette" in text:
        signatures.add("brakes.pads.rear" if rear else "brakes.pads.front" if front else "brakes.pads")
    if "disque" in text and any(value in text for value in ("frein", "brakes", "plaquette")):
        signatures.add("brakes.discs.rear" if rear else "brakes.discs.front" if front else "brakes.discs")
    if "rotule" in text:
        signatures.add("suspension.tie_rod")
    if "bras inferieur" in text or "silentbloc" in text or "silent bloc" in text:
        signatures.add("suspension.control_arm")
    if "pneu" in text or "pneumatique" in text:
        signatures.add("tires.rear" if rear else "tires.front" if front else "tires")
    if "camera" in text:
        signatures.add("adas.camera")
    if "bougie" in text:
        signatures.add("engine.spark_plugs")
    if "bobine" in text and "allumage" in text:
        signatures.add("engine.ignition_coils")
    if "courroie" in text and ("distribution" in text or "kit" in text):
        signatures.add("engine.timing_belt")
    if "vidange" in text or "huile moteur" in text:
        signatures.add("engine.oil_service")
    if "campagne" in text and "mva" in text:
        signatures.add("vehicle.campaign.mva")
    return signatures


def _completed_component_evidence(record: dict) -> dict[str, str]:
    evidence: dict[str, str] = {}
    for part in record.get("parts") or []:
        if not isinstance(part, dict) or part.get("usage") not in {"installed", "consumed"}:
            continue
        label = str(part.get("name") or "pièce montée")
        for signature in _component_signatures(
            " ".join(str(part.get(key) or "") for key in ("name", "system_code", "component_code", "position"))
        ):
            evidence.setdefault(signature, label)
    action_words = (
        "remplac", "montage", "monte", "pose", "change", "neuf", "revision",
        "vidange", "mise a jour",
    )
    action_texts = [str(record.get("title") or "")]
    action_texts.extend(
        str(line.get("description") or "")
        for line in record.get("cost_lines") or []
        if isinstance(line, dict) and line.get("line_type") in {"part", "service", "labor"}
    )
    for text in action_texts:
        if not any(word in _plain(text) for word in action_words):
            continue
        for signature in _component_signatures(text):
            evidence.setdefault(signature, text)
    return evidence


def _is_later_intervention(source: dict, candidate: dict, recommendation: dict) -> bool:
    source_date = source.get("performed_at") or source.get("purchased_at")
    candidate_date = candidate.get("performed_at")
    source_mileage = recommendation.get("recommended_at_km") or source.get("mileage_km")
    candidate_mileage = candidate.get("mileage_km")
    if source_date and candidate_date and str(candidate_date) < str(source_date):
        return False
    if source_mileage is not None and candidate_mileage is not None and int(candidate_mileage) < int(source_mileage):
        return False
    return bool(
        (source_date and candidate_date and str(candidate_date) >= str(source_date))
        or (source_mileage is not None and candidate_mileage is not None and int(candidate_mileage) >= int(source_mileage))
    )


def reconcile_maintenance_recommendations(vin: str) -> int:
    """Clôture uniquement les recommandations ayant une preuve mécanique ultérieure."""

    selected_vin = _resolve_vin(vin)
    directory = _record_root(selected_vin) / "records"
    with _LOCK:
        payloads = [
            _read_json(path)
            for path in directory.glob("maintenance-*.json") if directory.exists()
        ]
        candidates = [
            (payload, _completed_component_evidence(payload))
            for payload in payloads
            if payload.get("record_status") == "confirmed"
            and payload.get("event_type") in {"maintenance", "repair"}
            and payload.get("performed_at")
        ]
        mileage_evidence = max(
            (
                payload
                for payload in payloads
                if payload.get("record_status") == "confirmed"
                and payload.get("mileage_km") is not None
            ),
            key=lambda payload: int(payload.get("mileage_km") or 0),
            default=None,
        )
        changed_records = 0
        for source in payloads:
            changed = False
            for recommendation in source.get("recommendations") or []:
                if not isinstance(recommendation, dict):
                    continue
                if recommendation.get("status") in {"completed", "dismissed"} and not recommendation.get("auto_managed"):
                    continue
                required = _component_signatures(str(recommendation.get("title") or ""))
                match: tuple[dict, str, str] | None = None
                if required:
                    ordered_candidates = sorted(
                        candidates,
                        key=lambda item: (str(item[0].get("performed_at") or ""), int(item[0].get("mileage_km") or 0)),
                    )
                    for candidate, evidence in ordered_candidates:
                        if candidate.get("id") == source.get("id") or not _is_later_intervention(source, candidate, recommendation):
                            continue
                        matched_signature = next(
                            (
                                signature
                                for signature in required
                                if signature in evidence
                                or any(value.startswith(f"{signature}.") for value in evidence)
                            ),
                            None,
                        )
                        if matched_signature:
                            evidence_key = matched_signature if matched_signature in evidence else next(
                                value for value in evidence if value.startswith(f"{matched_signature}.")
                            )
                            match = (candidate, evidence_key, evidence[evidence_key])
                            break
                due_mileage = recommendation.get("due_mileage_km")
                if due_mileage is None and recommendation.get("recommended_at_km") is not None and recommendation.get("follow_up_after_km") is not None:
                    due_mileage = int(recommendation["recommended_at_km"]) + int(recommendation["follow_up_after_km"])
                elapsed_rodage = bool(
                    mileage_evidence
                    and due_mileage is not None
                    and int(mileage_evidence.get("mileage_km") or 0) >= int(due_mileage)
                    and "rodage" in _plain(str(recommendation.get("title") or ""))
                )
                if match:
                    candidate, _, evidence = match
                    completion_date = candidate.get("performed_at")
                    replacement = {
                        **recommendation,
                        "status": "completed",
                        "auto_managed": True,
                        "completed_by_record_id": candidate.get("id"),
                        "completed_at": completion_date,
                        "completion_reason": f"Clôturée automatiquement par « {candidate.get('title')} » ({completion_date}) : {evidence[:180]}",
                    }
                elif elapsed_rodage:
                    observed_mileage = int(mileage_evidence.get("mileage_km") or 0)
                    completion_date = mileage_evidence.get("performed_at") or mileage_evidence.get("purchased_at")
                    due_label = f"{int(due_mileage):,}".replace(",", " ")
                    observed_label = f"{observed_mileage:,}".replace(",", " ")
                    replacement = {
                        **recommendation,
                        "status": "completed",
                        "auto_managed": True,
                        "completed_by_record_id": mileage_evidence.get("id"),
                        "completed_at": completion_date,
                        "completion_reason": (
                            f"Période de rodage terminée : seuil de {due_label} km "
                            f"dépassé, kilométrage confirmé à {observed_label} km."
                        ),
                    }
                elif recommendation.get("auto_managed"):
                    replacement = {
                        **recommendation,
                        "status": "open",
                        "auto_managed": False,
                        "completed_by_record_id": None,
                        "completed_at": None,
                        "completion_reason": None,
                    }
                else:
                    continue
                if replacement != recommendation:
                    recommendation.clear()
                    recommendation.update(replacement)
                    changed = True
            if changed:
                _archive_revision(selected_vin, source)
                source["updated_at"] = _utc_now().isoformat(timespec="seconds")
                source["revision"] = int(source.get("revision") or 1) + 1
                _atomic_json(_record_path(selected_vin, str(source["id"])), source)
                changed_records += 1
        return changed_records


def set_maintenance_recommendation_status(
    vin: str,
    record_id: str,
    recommendation_index: int,
    update: MaintenanceRecommendationStatusUpdate,
) -> MaintenanceRecord:
    """Valide, classe ou rouvre une recommandation sans réécrire toute la fiche."""

    selected_vin = _resolve_vin(vin)
    path = _record_path(selected_vin, record_id)
    with _LOCK:
        current = _read_json(path)
        recommendations = current.get("recommendations") or []
        if not 0 <= recommendation_index < len(recommendations):
            raise KeyError("Recommandation introuvable.")
        recommendation = recommendations[recommendation_index]
        if not isinstance(recommendation, dict):
            raise ValueError("Recommandation invalide.")
        now = _utc_now()
        reason = update.note
        if not reason and update.status == "completed":
            reason = f"Validée manuellement le {now.date().isoformat()}."
        elif not reason and update.status == "dismissed":
            reason = f"Classée manuellement le {now.date().isoformat()}."
        _archive_revision(selected_vin, current)
        recommendation.update({
            "status": update.status,
            "auto_managed": False,
            "completed_by_record_id": None,
            "completed_at": now.date().isoformat() if update.status == "completed" else None,
            "completion_reason": reason if update.status in {"completed", "dismissed"} else None,
        })
        current["updated_at"] = now.isoformat(timespec="seconds")
        current["revision"] = int(current.get("revision") or 1) + 1
        _atomic_json(path, current)
        return _public_record(current)


def list_maintenance_records(vin: str | None = None) -> list[MaintenanceRecord]:
    selected_vin = _resolve_vin(vin)
    with _LOCK:
        results: list[MaintenanceRecord] = []
        directory = _record_root(selected_vin) / "records"
        for path in directory.glob("maintenance-*.json") if directory.exists() else []:
            try:
                results.append(_public_record(_read_json(path)))
            except (KeyError, ValueError):
                continue
    results.sort(
        key=lambda item: (
            item.performed_at or item.purchased_at or date.min,
            item.updated_at,
        ),
        reverse=True,
    )
    return results


def get_maintenance_record(vin: str, record_id: str) -> MaintenanceRecord:
    selected_vin = _resolve_vin(vin)
    with _LOCK:
        return _public_record(_read_json(_record_path(selected_vin, record_id)))


def create_maintenance_record(entry: MaintenanceRecordInput) -> MaintenanceRecord:
    selected_vin = _resolve_vin(entry.vin)
    _validate_provider_links(entry)
    now = _utc_now()
    record_id = f"maintenance-{now.strftime('%Y%m%dT%H%M%SZ')}-{uuid.uuid4().hex[:8]}"
    payload = {
        **entry.model_dump(mode="json"),
        "vin": selected_vin,
        "id": record_id,
        "created_at": now.isoformat(timespec="seconds"),
        "updated_at": now.isoformat(timespec="seconds"),
        "revision": 1,
        "documents": [],
    }
    with _LOCK:
        if entry.source_import_key:
            directory = _record_root(selected_vin) / "records"
            for existing_path in directory.glob("maintenance-*.json") if directory.exists() else []:
                existing = _read_json(existing_path)
                if existing.get("source_import_key") == entry.source_import_key:
                    return _public_record(existing)
        _atomic_json(_record_path(selected_vin, record_id), payload)
    reconcile_maintenance_recommendations(selected_vin)
    return get_maintenance_record(selected_vin, record_id)


def update_maintenance_record(record_id: str, entry: MaintenanceRecordInput) -> MaintenanceRecord:
    selected_vin = _resolve_vin(entry.vin)
    _validate_provider_links(entry)
    path = _record_path(selected_vin, record_id)
    with _LOCK:
        current = _read_json(path)
        if current.get("vin") != selected_vin:
            raise ValueError("Une intervention ne peut pas être déplacée vers un autre VIN.")
        _archive_revision(selected_vin, current)
        payload = {
            **entry.model_dump(mode="json"),
            "vin": selected_vin,
            "id": record_id,
            "created_at": current["created_at"],
            "updated_at": _utc_now().isoformat(timespec="seconds"),
            "revision": int(current.get("revision") or 1) + 1,
            "documents": list(current.get("documents") or []),
        }
        _atomic_json(path, payload)
    reconcile_maintenance_recommendations(selected_vin)
    return get_maintenance_record(selected_vin, record_id)


def reconcile_duplicate_maintenance_record(
    vin: str,
    duplicate_record_id: str,
    canonical_record_id: str,
) -> None:
    """Retire un doublon de la liste active en le conservant dans une archive récupérable."""

    selected_vin = _resolve_vin(vin)
    if duplicate_record_id == canonical_record_id:
        return
    with _LOCK:
        duplicate_path = _record_path(selected_vin, duplicate_record_id)
        duplicate = _read_json(duplicate_path)
        _read_json(_record_path(selected_vin, canonical_record_id))
        duplicate["reconciled_into_record_id"] = canonical_record_id
        duplicate["reconciled_at"] = _utc_now().isoformat(timespec="seconds")
        archive = _record_root(selected_vin) / "reconciled" / f"{duplicate_record_id}.json"
        _atomic_json(archive, duplicate)
        duplicate_path.unlink()
        document_dir = _record_root(selected_vin) / "documents" / duplicate_record_id
        if document_dir.exists():
            archive_dir = _record_root(selected_vin) / "reconciled" / "documents" / duplicate_record_id
            archive_dir.parent.mkdir(parents=True, exist_ok=True)
            if archive_dir.exists():
                raise ValueError("Une archive de rapprochement existe déjà pour ce doublon.")
            document_dir.replace(archive_dir)


def _detected_document_type(header: bytes) -> tuple[str, str] | None:
    if header.startswith(b"%PDF-"):
        return "application/pdf", ".pdf"
    if header.startswith(b"\xFF\xD8\xFF"):
        return "image/jpeg", ".jpg"
    if header.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png", ".png"
    if len(header) >= 12 and header.startswith(b"RIFF") and header[8:12] == b"WEBP":
        return "image/webp", ".webp"
    return None


def _file_sha256(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(_CHUNK_SIZE):
            digest.update(chunk)
    return digest.hexdigest()


def normalize_maintenance_documents(
    vin: str,
    record_id: str,
    *,
    rotations_by_original_name: dict[str, int] | None = None,
    record_new_revision: bool = True,
) -> MaintenanceRecord:
    """Construit le PDF principal sans supprimer les photos sources d'audit."""

    selected_vin = _resolve_vin(vin)
    path = _record_path(selected_vin, record_id)
    with _LOCK:
        current = _read_json(path)
        documents = [item for item in current.get("documents", []) if isinstance(item, dict)]
        sources = [item for item in documents if item.get("role") != "normalized"]
        if not sources:
            return _public_record(current)
        document_dir = _record_root(selected_vin) / "documents" / record_id
        source_paths: list[Path] = []
        rotations_by_stored_name: dict[str, int] = {}
        for source in sources:
            stored_name = str(source.get("stored_name") or "")
            if Path(stored_name).name != stored_name:
                raise ValueError("Chemin de document d’entretien invalide.")
            source_path = document_dir / stored_name
            if not source_path.is_file():
                raise KeyError(f"Fichier source introuvable : {stored_name}.")
            source_paths.append(source_path)
            original_name = str(source.get("original_name") or "")
            if rotations_by_original_name and original_name in rotations_by_original_name:
                rotations_by_stored_name[stored_name] = rotations_by_original_name[original_name]

    destination = document_dir / "document-normalized.pdf"
    result = normalize_sources_to_pdf(
        source_paths,
        destination,
        rotations_by_name=rotations_by_stored_name,
    )
    existing_normalized = next(
        (item for item in documents if item.get("role") == "normalized"),
        None,
    )
    normalized_id = str((existing_normalized or {}).get("id") or f"document-{uuid.uuid4().hex[:12]}")
    kinds = [str(source.get("kind") or "other") for source in sources]
    normalized_kind = "invoice" if "invoice" in kinds else kinds[0]
    normalized = {
        "id": normalized_id,
        "kind": normalized_kind,
        "role": "normalized",
        "original_name": str(sources[0].get("original_name")) if len(sources) == 1 and source_paths[0].suffix.casefold() == ".pdf" else f"Justificatifs – {str(current.get('title') or 'intervention')[:190]}.pdf",
        "stored_name": destination.name,
        "media_type": "application/pdf",
        "size_bytes": destination.stat().st_size,
        "sha256": _file_sha256(destination),
        "uploaded_at": (existing_normalized or {}).get("uploaded_at") or _utc_now().isoformat(timespec="seconds"),
        "page_count": result.page_count,
        "source_names": [str(source.get("original_name") or "document") for source in sources],
        "crop_methods": result.crop_methods,
        "rotations": result.rotations,
    }
    normalized_sources = [{**source, "role": "source"} for source in sources]
    with _LOCK:
        latest = _read_json(path)
        if record_new_revision:
            _archive_revision(selected_vin, latest)
        latest["documents"] = [*normalized_sources, normalized]
        snapshot = latest.get("import_snapshot")
        if isinstance(snapshot, dict):
            snapshot["document_id"] = normalized_id
        latest["updated_at"] = _utc_now().isoformat(timespec="seconds")
        if record_new_revision:
            latest["revision"] = int(latest.get("revision") or 1) + 1
        _atomic_json(path, latest)
        return _public_record(latest)


async def add_maintenance_document(
    vin: str,
    record_id: str,
    upload: UploadFile,
    kind: Literal[
        "invoice", "receipt", "photo", "warranty", "diagnostic_report", "work_order", "recommendation", "other"
    ] = "invoice",
) -> MaintenanceRecord:
    selected_vin = _resolve_vin(vin)
    path = _record_path(selected_vin, record_id)
    with _LOCK:
        current = _read_json(path)
        source_count = sum(
            1 for item in current.get("documents") or []
            if isinstance(item, dict) and item.get("role") != "normalized"
        )
        if source_count >= _MAX_DOCUMENTS_PER_RECORD:
            raise ValueError(f"Une intervention est limitée à {_MAX_DOCUMENTS_PER_RECORD} documents.")

    original_name = Path(upload.filename or "document").name[:240]
    document_id = f"document-{uuid.uuid4().hex[:12]}"
    document_dir = _record_root(selected_vin) / "documents" / record_id
    document_dir.mkdir(parents=True, exist_ok=True)
    temporary = document_dir / f".{document_id}.upload"
    size = 0
    digest = sha256()
    header = b""
    try:
        with temporary.open("wb") as stream:
            while chunk := await upload.read(_CHUNK_SIZE):
                size += len(chunk)
                if size > _MAX_DOCUMENT_BYTES:
                    raise AttachmentTooLargeError("Le document dépasse la limite de 20 Mo.")
                if len(header) < 16:
                    header += chunk[: 16 - len(header)]
                digest.update(chunk)
                stream.write(chunk)
            stream.flush()
            os.fsync(stream.fileno())
        detected = _detected_document_type(header)
        if detected is None:
            raise ValueError("Formats acceptés : PDF, JPEG, PNG ou WebP.")
        if size == 0:
            raise ValueError("Le document envoyé est vide.")
        media_type, extension = detected
        stored_name = f"{document_id}{extension}"
        destination = document_dir / stored_name
        temporary.replace(destination)

        document = {
            "id": document_id,
            "kind": kind,
            "original_name": original_name,
            "stored_name": stored_name,
            "media_type": media_type,
            "size_bytes": size,
            "sha256": digest.hexdigest(),
            "uploaded_at": _utc_now().isoformat(timespec="seconds"),
            "role": "source",
        }
        with _LOCK:
            current = _read_json(path)
            _archive_revision(selected_vin, current)
            current.setdefault("documents", []).append(document)
            snapshot = current.get("import_snapshot")
            current["updated_at"] = _utc_now().isoformat(timespec="seconds")
            current["revision"] = int(current.get("revision") or 1) + 1
            _atomic_json(path, current)
        return normalize_maintenance_documents(selected_vin, record_id, record_new_revision=False)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise
    finally:
        await upload.close()


def maintenance_document_file(
    vin: str,
    record_id: str,
    document_id: str,
) -> tuple[Path, MaintenanceDocument]:
    selected_vin = _resolve_vin(vin)
    if not _DOCUMENT_ID.fullmatch(document_id):
        raise KeyError("Document d’entretien introuvable.")
    with _LOCK:
        payload = _read_json(_record_path(selected_vin, record_id))
        document = next(
            (item for item in payload.get("documents", []) if item.get("id") == document_id),
            None,
        )
        if not isinstance(document, dict):
            raise KeyError("Document d’entretien introuvable.")
        stored_name = str(document.get("stored_name") or "")
        if Path(stored_name).name != stored_name:
            raise ValueError("Chemin de document d’entretien invalide.")
        path = _record_root(selected_vin) / "documents" / record_id / stored_name
        if not path.is_file():
            raise KeyError("Fichier de facture introuvable.")
        return path, _public_document(record_id, document)
