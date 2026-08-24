from __future__ import annotations

from datetime import date, datetime, timezone
from hashlib import sha256
from pathlib import Path
from typing import Literal
import json
import os
import re
import threading
import uuid

from fastapi import UploadFile
from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.config import settings
from app.diagnostic.history import active_vehicle, vehicle_storage_dir


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


class MaintenanceRecordInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    vin: str = Field(min_length=17, max_length=17, pattern=r"^[A-HJ-NPR-Z0-9]{17}$")
    vehicle_profile: str | None = Field(default=None, min_length=1, max_length=100)
    performed_at: date
    mileage_km: int = Field(ge=0, le=9_999_999)
    mileage_source: Literal["manual", "can_signal", "invoice", "history_estimate"] = "manual"
    mileage_note: str | None = Field(default=None, max_length=500)
    title: str = Field(min_length=1, max_length=180)
    category: str = Field(default="Entretien", min_length=1, max_length=80)
    workshop: str | None = Field(default=None, max_length=180)
    invoice_number: str | None = Field(default=None, max_length=120)
    invoice_total: float | None = Field(default=None, ge=0, le=100_000_000)
    currency: str = Field(default="EUR", min_length=3, max_length=3)
    labor_hours: float | None = Field(default=None, ge=0, le=10_000)
    notes: str | None = Field(default=None, max_length=5_000)
    parts: list[MaintenancePart] = Field(default_factory=list, max_length=100)

    @field_validator("currency")
    @classmethod
    def normalize_currency(cls, value: str) -> str:
        normalized = value.upper()
        if not re.fullmatch(r"[A-Z]{3}", normalized):
            raise ValueError("La devise doit être un code ISO sur trois lettres.")
        return normalized


class MaintenanceDocument(BaseModel):
    id: str
    kind: Literal["invoice", "receipt", "photo", "warranty", "other"]
    original_name: str
    media_type: str
    size_bytes: int
    sha256: str
    uploaded_at: datetime
    download_url: str


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
    )


def _public_record(payload: dict) -> MaintenanceRecord:
    public_payload = {
        key: value
        for key, value in payload.items()
        if key != "documents"
    }
    public_payload["documents"] = [
        _public_document(str(payload["id"]), document)
        for document in payload.get("documents", [])
        if isinstance(document, dict)
    ]
    return MaintenanceRecord.model_validate(public_payload)


def _resolve_vin(vin: str | None) -> str:
    selected = vin or str((active_vehicle() or {}).get("vin") or "")
    if not selected:
        raise ValueError("Aucun véhicule actif : sélectionne d’abord un VIN dans le Garage.")
    vehicle_storage_dir(selected)
    return selected


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
    results.sort(key=lambda item: (item.performed_at, item.updated_at), reverse=True)
    return results


def get_maintenance_record(vin: str, record_id: str) -> MaintenanceRecord:
    selected_vin = _resolve_vin(vin)
    with _LOCK:
        return _public_record(_read_json(_record_path(selected_vin, record_id)))


def create_maintenance_record(entry: MaintenanceRecordInput) -> MaintenanceRecord:
    selected_vin = _resolve_vin(entry.vin)
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
        _atomic_json(_record_path(selected_vin, record_id), payload)
    return _public_record(payload)


def update_maintenance_record(record_id: str, entry: MaintenanceRecordInput) -> MaintenanceRecord:
    selected_vin = _resolve_vin(entry.vin)
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
    return _public_record(payload)


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


async def add_maintenance_document(
    vin: str,
    record_id: str,
    upload: UploadFile,
    kind: Literal["invoice", "receipt", "photo", "warranty", "other"] = "invoice",
) -> MaintenanceRecord:
    selected_vin = _resolve_vin(vin)
    path = _record_path(selected_vin, record_id)
    with _LOCK:
        current = _read_json(path)
        if len(current.get("documents") or []) >= _MAX_DOCUMENTS_PER_RECORD:
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
        }
        with _LOCK:
            current = _read_json(path)
            _archive_revision(selected_vin, current)
            current.setdefault("documents", []).append(document)
            current["updated_at"] = _utc_now().isoformat(timespec="seconds")
            current["revision"] = int(current.get("revision") or 1) + 1
            _atomic_json(path, current)
        return _public_record(current)
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
