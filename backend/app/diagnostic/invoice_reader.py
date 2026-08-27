from __future__ import annotations

from datetime import date, datetime, timezone
from functools import lru_cache
from pathlib import Path
from typing import Literal
import logging
import re
import tempfile
import unicodedata

from fastapi import UploadFile
from pydantic import BaseModel, Field

from app.diagnostic.maintenance_history import AttachmentTooLargeError, MaintenancePart
from app.maintenance.models import (
    DocumentImportSnapshot,
    ImportedField,
    ServiceProviderInput,
)


_MAX_DOCUMENT_BYTES = 20 * 1024 * 1024
_MAX_TEXT_CHARS = 50_000
_CHUNK_SIZE = 1024 * 1024


class InvoiceAnalysis(BaseModel):
    purchased_at: date | None = None
    performed_at: date | None = None
    performed_at_source: Literal[
        "document_explicit", "vehicle_return", "invoice_date_assumed"
    ] | None = None
    mileage_km: int | None = Field(default=None, ge=0, le=9_999_999)
    title: str | None = None
    category: str = "Réparation"
    workshop: str | None = None
    invoice_number: str | None = None
    invoice_total: float | None = Field(default=None, ge=0)
    currency: str = "EUR"
    parts: list[MaintenancePart] = Field(default_factory=list)
    provider_candidate: ServiceProviderInput | None = None
    matched_provider_id: str | None = None
    confidence: float = Field(ge=0, le=1)
    ocr_used: bool
    extracted_text_excerpt: str
    warnings: list[str] = Field(default_factory=list)
    import_snapshot: DocumentImportSnapshot


def _plain(value: str) -> str:
    return "".join(
        character for character in unicodedata.normalize("NFKD", value)
        if not unicodedata.combining(character)
    ).casefold()


def _document_type(header: bytes) -> tuple[str, str] | None:
    if header.startswith(b"%PDF-"):
        return "application/pdf", ".pdf"
    if header.startswith(b"\xFF\xD8\xFF"):
        return "image/jpeg", ".jpg"
    if header.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png", ".png"
    if len(header) >= 12 and header.startswith(b"RIFF") and header[8:12] == b"WEBP":
        return "image/webp", ".webp"
    return None


@lru_cache(maxsize=1)
def _rapid_ocr():
    logging.getLogger("RapidOCR").setLevel(logging.WARNING)
    try:
        from rapidocr import ModelType, OCRVersion, RapidOCR
    except ImportError as exc:
        raise ValueError(
            "OCR local indisponible : installe les dépendances Python RapidOCR."
        ) from exc
    return RapidOCR(
        params={
            "Det.model_type": ModelType.SMALL,
            "Det.ocr_version": OCRVersion.PPOCRV6,
            "Rec.model_type": ModelType.SMALL,
            "Rec.ocr_version": OCRVersion.PPOCRV6,
            "Global.text_score": 0.45,
        }
    )


def _result_text(result) -> str:
    texts = getattr(result, "txts", None)
    scores = getattr(result, "scores", None)
    if texts is None:
        return ""
    if scores is None:
        return "\n".join(str(value).strip() for value in texts if str(value).strip())
    return "\n".join(
        str(value).strip()
        for value, score in zip(texts, scores)
        if str(value).strip() and float(score) >= 0.40
    )


def _ocr_array(image) -> str:
    try:
        import cv2
    except ImportError as exc:
        raise ValueError(
            "Décodage d’image indisponible : installe opencv-python-headless."
        ) from exc
    if image is None or not getattr(image, "size", 0):
        raise ValueError("L’image de la facture est illisible.")
    longest = max(image.shape[:2])
    scale = min(3.0, max(0.5, 2200 / longest))
    if abs(scale - 1.0) > 0.05:
        interpolation = cv2.INTER_CUBIC if scale > 1 else cv2.INTER_AREA
        image = cv2.resize(image, None, fx=scale, fy=scale, interpolation=interpolation)
    candidates: list[tuple[int, str]] = []
    for rotation in (
        None,
        cv2.ROTATE_90_CLOCKWISE,
        cv2.ROTATE_180,
        cv2.ROTATE_90_COUNTERCLOCKWISE,
    ):
        oriented = image if rotation is None else cv2.rotate(image, rotation)
        text = _result_text(_rapid_ocr()(oriented))
        candidates.append((sum(character.isalnum() for character in text), text))
    return max(candidates, key=lambda item: item[0])[1]


def _ocr_image(path: Path) -> str:
    try:
        import cv2
        import numpy as np
    except ImportError as exc:
        raise ValueError(
            "Décodage d’image indisponible : installe les dépendances Python OCR."
        ) from exc
    encoded = np.fromfile(path, dtype=np.uint8)
    return _ocr_array(cv2.imdecode(encoded, cv2.IMREAD_COLOR))


def _pdf_page_image(page):
    try:
        import cv2
        import numpy as np
    except ImportError as exc:
        raise ValueError(
            "Décodage PDF indisponible : installe les dépendances Python OCR."
        ) from exc
    pixmap = page.get_pixmap(dpi=200, alpha=False)
    rgb = np.frombuffer(pixmap.samples, dtype=np.uint8).reshape(
        pixmap.height, pixmap.width, pixmap.n
    )
    conversion = cv2.COLOR_RGBA2BGR if pixmap.n == 4 else cv2.COLOR_RGB2BGR
    return cv2.cvtColor(rgb, conversion)


def _extract_text(path: Path, media_type: str) -> tuple[str, bool]:
    if media_type.startswith("image/"):
        return _ocr_image(path), True

    try:
        import pymupdf
    except ImportError as exc:
        raise ValueError(
            "Lecture PDF indisponible : installe la dépendance Python PyMuPDF."
        ) from exc
    try:
        with pymupdf.open(path) as document:
            if document.page_count > 50:
                raise ValueError("Le document dépasse la limite de 50 pages.")
            native_text = "\n\n".join(
                document.load_page(index).get_text("text", sort=True)
                for index in range(document.page_count)
            )
            if len(native_text.strip()) >= 30:
                return native_text, False
            ocr_text = "\n\n".join(
                _ocr_array(_pdf_page_image(document.load_page(index)))
                for index in range(document.page_count)
            )
            return ocr_text, True
    except ValueError:
        raise
    except Exception as exc:
        raise ValueError("Le PDF est illisible ou endommagé.") from exc


def _parse_date(value: str) -> date | None:
    cleaned = value.strip().replace(".", "/").replace("-", "/")
    for pattern in ("%d/%m/%Y", "%Y/%m/%d", "%d/%m/%y"):
        try:
            return datetime.strptime(cleaned, pattern).date()
        except ValueError:
            continue
    return None


def _amount(value: str) -> float | None:
    cleaned = value.replace("\u00a0", "").replace(" ", "").replace("€", "")
    if "," in cleaned and "." in cleaned:
        if cleaned.rfind(",") > cleaned.rfind("."):
            cleaned = cleaned.replace(".", "").replace(",", ".")
        else:
            cleaned = cleaned.replace(",", "")
    else:
        cleaned = cleaned.replace(",", ".")
    try:
        return float(cleaned)
    except ValueError:
        return None


def _first_match(lines: list[str], pattern: re.Pattern[str]) -> re.Match[str] | None:
    for line in lines:
        if match := pattern.search(line):
            return match
    return None


def _provider_name(lines: list[str]) -> str | None:
    for index, line in enumerate(lines[:-1]):
        plain = _plain(line).strip(" :/")
        if plain in {"seller / vendeur", "vendeur", "seller"}:
            candidate = lines[index + 1]
            if 2 < len(candidate) <= 180:
                return candidate
    business_markers = (
        "garage", "automobiles", "auto service", "norauto", "oscaro", "ovoko",
        "controle technique", "contrôle technique", "carrosserie", "pneus", "peugeot",
    )
    for line in lines[:20]:
        plain = _plain(line)
        if "adresse de facturation" in plain:
            candidate = re.split(r"adresse de facturation", line, flags=re.I)[0].strip()
            if candidate and any(marker in _plain(candidate) for marker in business_markers):
                return candidate
        if any(marker in plain for marker in business_markers) and not any(
            excluded in plain for excluded in ("facture", "adresse de facturation", "total", "promotion")
        ):
            return line
    excluded = (
        "facture", "invoice", "date", "siret", "siren", "tva", "telephone",
        "tel ", "client", "adresse", "france", "vendeur", "seller", "acheteur", "buyer",
    )
    return next(
        (
            line for line in lines[:15]
            if 3 <= len(line) <= 120
            and any(character.isalpha() for character in line)
            and not any(word in _plain(line) for word in excluded)
        ),
        None,
    )


def _provider_candidate(lines: list[str], name: str | None, title: str | None) -> ServiceProviderInput | None:
    if not name:
        return None
    context = _plain(" ".join(lines[:40]))
    plain_name = _plain(name)
    if any(marker in plain_name for marker in ("oscaro", "ovoko", "autodoc", "mister auto")):
        kind = "parts_supplier"
    elif "controle technique" in context or "contrôle technique" in context:
        kind = "inspection_center"
    elif "carrosserie" in plain_name:
        kind = "body_shop"
    elif any(marker in plain_name for marker in ("pneu", "pneumatique", "norauto")):
        kind = "tire_shop"
    elif any(marker in plain_name for marker in ("peugeot", "citroen", "citroën", "renault", "fiat")):
        kind = "dealership"
    elif "garage" in plain_name or title:
        kind = "garage"
    else:
        kind = "other"

    joined = "\n".join(lines)
    siret_match = re.search(r"\bSIRET\s*[:#]?\s*([\d ]{14,20})", joined, re.I)
    siren_match = re.search(r"\bSIREN\s*[:#]?\s*([\d ]{9,14})", joined, re.I)
    vat_match = re.search(r"(?:TVA|VAT)(?:\s+intracommunautaire|\s+No[.]?)?\s*[:#]?\s*([A-Z]{2}\s*[A-Z0-9 ]{8,16})", joined, re.I)
    phone_match = re.search(r"(?:T[ée]l(?:[ée]phone)?|Phone)\s*[:#]?\s*([+\d][\d .-]{7,})", joined, re.I)
    email_match = re.search(r"[\w.+-]+@[\w.-]+\.[A-Z]{2,}", joined, re.I)
    return ServiceProviderInput(
        kind=kind,
        legal_name=name,
        siret=siret_match.group(1) if siret_match else None,
        siren=siren_match.group(1) if siren_match else None,
        vat_number=vat_match.group(1) if vat_match else None,
        phone=phone_match.group(1).strip() if phone_match else None,
        email=email_match.group(0) if email_match else None,
        aliases=[name],
        verified_by_user=False,
    )


def parse_invoice_text(text: str, *, ocr_used: bool = False) -> InvoiceAnalysis:
    text = text[:_MAX_TEXT_CHARS]
    lines = [re.sub(r"\s+", " ", line).strip() for line in text.splitlines()]
    lines = [line for line in lines if line]
    if not lines:
        raise ValueError("Aucun texte lisible n’a été détecté dans la facture.")

    date_pattern = re.compile(r"(?:date(?:\s+de\s+facture)?\s*[:#-]?\s*)?(\d{1,2}[./-]\d{1,2}[./-]\d{2,4}|\d{4}-\d{1,2}-\d{1,2})", re.I)
    labelled_date = next((date_pattern.search(line) for line in lines if "date" in _plain(line)), None)
    date_match = labelled_date or _first_match(lines, date_pattern)
    invoice_date = _parse_date(date_match.group(1)) if date_match else None

    invoice_pattern = re.compile(r"(?:facture|invoice)\s*(?:n(?:o|°|º)?|num(?:e|é)ro|#)?\s*[:#-]?\s*([A-Z0-9][A-Z0-9./_-]{2,})", re.I)
    invoice_match = _first_match(lines, invoice_pattern)
    invoice_number = invoice_match.group(1).strip("-_.") if invoice_match else None

    mileage_pattern = re.compile(r"(?:kilom(?:e|é)trage|compteur|mileage)[^0-9]{0,20}(\d[\d .]{2,})\s*km", re.I)
    mileage_match = _first_match(lines, mileage_pattern)
    if not mileage_match:
        mileage_match = _first_match(lines, re.compile(r"\b(\d{2,7})\s*km\b", re.I))
    mileage = int(re.sub(r"\D", "", mileage_match.group(1))) if mileage_match else None
    if mileage is not None and mileage > 9_999_999:
        mileage = None

    total = None
    total_line_pattern = re.compile(r"(?:net\s+[àa]\s+payer|total\s*ttc|montant\s*ttc|total\s+facture)", re.I)
    money_pattern = re.compile(r"(?<!\d)(\d{1,3}(?:[ .]\d{3})*(?:[,.]\d{2})|\d+[,.]\d{2})\s*(?:€|eur)?", re.I)
    for index in range(len(lines) - 1, -1, -1):
        line = lines[index]
        if total_line_pattern.search(line):
            amounts = money_pattern.findall(line)
            if amounts:
                total = _amount(amounts[-1])
                break
            for neighbor in (index - 1, index + 1):
                if 0 <= neighbor < len(lines):
                    nearby = money_pattern.findall(lines[neighbor])
                    if nearby:
                        total = _amount(nearby[-1])
                        break
            if total is not None:
                break

    workshop = _provider_name(lines)

    reference_pattern = re.compile(r"(?:r[ée]f(?:[ée]rence)?|reference|article|oem)\s*\.?(?:\s*n(?:o|°|º)?\s*)?[:#-]?\s*([A-Z0-9][A-Z0-9./_-]{3,})", re.I)
    serial_pattern = re.compile(r"(?:n(?:o|°|º)?\s*(?:de\s*)?s[ée]rie|serial(?:\s+number)?)\s*\.?\s*[:#-]?\s*([A-Z0-9][A-Z0-9./_-]{3,})", re.I)
    parts: list[MaintenancePart] = []
    seen_parts: set[tuple[str | None, str | None, str | None, str | None]] = set()
    for index, line in enumerate(lines):
        reference = reference_pattern.search(line)
        serial = serial_pattern.search(line)
        if not reference and not serial:
            continue
        plain = _plain(line)
        removed = any(word in plain for word in ("ancien", "ancienne", "depose", "retire", "remplacee"))
        first_label = min(match.start() for match in (reference, serial) if match)
        name = re.sub(r"^[\d.,]+\s*(?:x|×)?\s*", "", line[:first_label]).strip(" :-")
        if not name and index > 0 and len(lines[index - 1]) <= 120:
            name = lines[index - 1]
        name = name[:160] or "Pièce facturée"
        ref_value = reference.group(1).strip("-_.") if reference else None
        serial_value = serial.group(1).strip("-_.") if serial else None
        key = (
            None if removed else ref_value,
            None if removed else serial_value,
            ref_value if removed else None,
            serial_value if removed else None,
        )
        if key in seen_parts:
            continue
        seen_parts.add(key)
        amounts = money_pattern.findall(line)
        parts.append(MaintenancePart(
            name=name,
            part_number=None if removed else ref_value,
            serial_number=None if removed else serial_value,
            removed_part_number=ref_value if removed else None,
            removed_serial_number=serial_value if removed else None,
            quantity=1,
            unit_price=_amount(amounts[-1]) if amounts else None,
        ))

    service_words = ("remplacement", "revision", "révision", "vidange", "entretien", "réparation", "reparation", "controle", "contrôle")
    title = next((line[:180] for line in lines if any(word in line.casefold() for word in service_words) and len(line) <= 180), None)
    if not title and parts:
        title = f"Remplacement {parts[0].name}"[:180]

    provider_candidate = _provider_candidate(lines, workshop, title)
    explicit_intervention_match = next(
        (
            date_pattern.search(line)
            for line in lines
            if any(
                marker in _plain(line)
                for marker in ("date intervention", "date des travaux", "date restitution")
            )
            and date_pattern.search(line)
        ),
        None,
    )
    if explicit_intervention_match:
        performed_at = _parse_date(explicit_intervention_match.group(1))
        performed_at_source = "document_explicit"
    elif provider_candidate and provider_candidate.kind in {
        "garage", "dealership", "inspection_center", "body_shop", "tire_shop"
    }:
        performed_at = invoice_date
        performed_at_source = "invoice_date_assumed" if invoice_date else None
    else:
        performed_at = None
        performed_at_source = None

    detected_fields = sum(value is not None for value in (
        invoice_date, mileage, title, workshop, invoice_number, total,
    )) + min(2, len(parts))
    confidence = min(0.98, 0.25 + detected_fields * 0.09)
    warnings: list[str] = []
    if invoice_date is None:
        warnings.append("Date non détectée : vérifie-la avant l’enregistrement.")
    if performed_at is None:
        warnings.append("Renseigne la date de pose : une facture de pièces ne prouve pas le montage.")
    elif performed_at_source == "invoice_date_assumed":
        warnings.append("Date de pose proposée d’après la date de facture du garage : à confirmer.")
    if mileage is None:
        warnings.append("Kilométrage absent de la facture : une estimation datée peut être proposée.")
    if not parts:
        warnings.append("Aucune référence de pièce clairement libellée n’a été détectée.")
    if not any(part.serial_number or part.removed_serial_number for part in parts):
        warnings.append("Aucun numéro de série clairement libellé n’a été détecté.")
    warnings.append("Contrôle obligatoire : corrige les champs préremplis avant de sauvegarder.")

    snapshot = DocumentImportSnapshot(
        engine="rapidocr" if ocr_used else "pymupdf_native_text",
        analyzed_at=datetime.now(timezone.utc),
        fields={
            "purchased_at": ImportedField(
                raw_value=date_match.group(1) if date_match else None,
                normalized_value=invoice_date.isoformat() if invoice_date else None,
                confidence=0.9 if date_match else None,
                evidence=date_match.group(0) if date_match else None,
            ),
            "performed_at": ImportedField(
                raw_value=explicit_intervention_match.group(1) if explicit_intervention_match else None,
                normalized_value=performed_at.isoformat() if performed_at else None,
                confidence=0.95 if explicit_intervention_match else 0.55 if performed_at else None,
                evidence=(
                    explicit_intervention_match.group(0)
                    if explicit_intervention_match
                    else "Date de facture utilisée comme proposition" if performed_at else None
                ),
            ),
            "mileage_km": ImportedField(
                raw_value=mileage_match.group(0) if mileage_match else None,
                normalized_value=mileage,
                confidence=0.9 if mileage_match else None,
                evidence=mileage_match.group(0) if mileage_match else None,
            ),
            "invoice_number": ImportedField(
                raw_value=invoice_match.group(0) if invoice_match else None,
                normalized_value=invoice_number,
                confidence=0.9 if invoice_match else None,
                evidence=invoice_match.group(0) if invoice_match else None,
            ),
            "invoice_total": ImportedField(
                raw_value=total,
                normalized_value=total,
                confidence=0.9 if total is not None else None,
            ),
            "provider": ImportedField(
                raw_value=workshop,
                normalized_value=provider_candidate.legal_name if provider_candidate else None,
                confidence=0.7 if provider_candidate else None,
                evidence=workshop,
            ),
        },
        raw_payload={
            "parts": [part.model_dump(mode="json") for part in parts],
            "provider_candidate": (
                provider_candidate.model_dump(mode="json") if provider_candidate else None
            ),
        },
        text_excerpt="\n".join(lines)[:6_000],
        warnings=warnings,
    )
    return InvoiceAnalysis(
        purchased_at=invoice_date,
        performed_at=performed_at,
        performed_at_source=performed_at_source,
        mileage_km=mileage,
        title=title,
        workshop=workshop,
        invoice_number=invoice_number,
        invoice_total=total,
        currency="EUR" if "€" in text or "eur" in text.casefold() else "EUR",
        parts=parts,
        provider_candidate=provider_candidate,
        confidence=round(confidence, 2),
        ocr_used=ocr_used,
        extracted_text_excerpt="\n".join(lines)[:6_000],
        warnings=warnings,
        import_snapshot=snapshot,
    )


async def analyze_invoice_upload(upload: UploadFile) -> InvoiceAnalysis:
    size = 0
    header = b""
    with tempfile.TemporaryDirectory(prefix="opendiag-invoice-") as temporary_directory:
        temporary_root = Path(temporary_directory)
        raw_path = temporary_root / "invoice.upload"
        try:
            with raw_path.open("wb") as stream:
                while chunk := await upload.read(_CHUNK_SIZE):
                    size += len(chunk)
                    if size > _MAX_DOCUMENT_BYTES:
                        raise AttachmentTooLargeError("La facture dépasse la limite de 20 Mo.")
                    if len(header) < 16:
                        header += chunk[: 16 - len(header)]
                    stream.write(chunk)
            detected = _document_type(header)
            if detected is None:
                raise ValueError("Formats acceptés pour la lecture : PDF, JPEG, PNG ou WebP.")
            if size == 0:
                raise ValueError("La facture envoyée est vide.")
            media_type, extension = detected
            path = raw_path.with_suffix(extension)
            raw_path.replace(path)
            text, ocr_used = _extract_text(path, media_type)
            return parse_invoice_text(text, ocr_used=ocr_used)
        finally:
            await upload.close()
