from __future__ import annotations

from datetime import date, datetime
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import unicodedata

from fastapi import UploadFile
from pydantic import BaseModel, Field

from app.diagnostic.maintenance_history import AttachmentTooLargeError, MaintenancePart


_MAX_DOCUMENT_BYTES = 20 * 1024 * 1024
_MAX_TEXT_CHARS = 50_000
_CHUNK_SIZE = 1024 * 1024


class InvoiceAnalysis(BaseModel):
    performed_at: date | None = None
    mileage_km: int | None = Field(default=None, ge=0, le=9_999_999)
    title: str | None = None
    category: str = "Réparation"
    workshop: str | None = None
    invoice_number: str | None = None
    invoice_total: float | None = Field(default=None, ge=0)
    currency: str = "EUR"
    parts: list[MaintenancePart] = Field(default_factory=list)
    confidence: float = Field(ge=0, le=1)
    ocr_used: bool
    extracted_text_excerpt: str
    warnings: list[str] = Field(default_factory=list)


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


def _run_text(command: list[str], timeout: int = 30) -> str:
    try:
        completed = subprocess.run(
            command,
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise ValueError("La lecture automatique de la facture a expiré ou n’est pas disponible.") from exc
    return completed.stdout if completed.returncode == 0 else ""


def _ocr_image(path: Path) -> str:
    executable = shutil.which("tesseract")
    if not executable:
        raise ValueError("OCR indisponible : installe Tesseract pour lire les factures photographiées.")
    text = _run_text([executable, str(path), "stdout", "-l", "fra+eng", "--psm", "6"], timeout=45)
    if not text:
        text = _run_text([executable, str(path), "stdout", "--psm", "6"], timeout=45)
    return text


def _extract_text(path: Path, media_type: str) -> tuple[str, bool]:
    if media_type.startswith("image/"):
        return _ocr_image(path), True

    text = ""
    pdftotext = shutil.which("pdftotext")
    if pdftotext:
        text = _run_text([pdftotext, "-layout", str(path), "-"], timeout=30)
    if len(text.strip()) >= 30:
        return text, False

    pdftoppm = shutil.which("pdftoppm")
    if not pdftoppm:
        if pdftotext:
            return text, False
        raise ValueError("Lecture PDF indisponible : installe Poppler (pdftotext/pdftoppm).")
    prefix = path.parent / "invoice-page"
    try:
        subprocess.run(
            [pdftoppm, "-f", "1", "-l", "3", "-r", "200", "-png", str(path), str(prefix)],
            check=False,
            capture_output=True,
            timeout=45,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise ValueError("La conversion OCR du PDF a échoué.") from exc
    pages = sorted(path.parent.glob("invoice-page-*.png"))
    return "\n".join(_ocr_image(page) for page in pages), True


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


def parse_invoice_text(text: str, *, ocr_used: bool = False) -> InvoiceAnalysis:
    text = text[:_MAX_TEXT_CHARS]
    lines = [re.sub(r"\s+", " ", line).strip() for line in text.splitlines()]
    lines = [line for line in lines if line]
    if not lines:
        raise ValueError("Aucun texte lisible n’a été détecté dans la facture.")

    date_pattern = re.compile(r"(?:date(?:\s+de\s+facture)?\s*[:#-]?\s*)?(\d{1,2}[./-]\d{1,2}[./-]\d{2,4}|\d{4}-\d{1,2}-\d{1,2})", re.I)
    labelled_date = next((date_pattern.search(line) for line in lines if "date" in _plain(line)), None)
    date_match = labelled_date or _first_match(lines, date_pattern)
    performed_at = _parse_date(date_match.group(1)) if date_match else None

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
    for line in reversed(lines):
        if total_line_pattern.search(line):
            amounts = money_pattern.findall(line)
            if amounts:
                total = _amount(amounts[-1])
                break

    workshop = None
    excluded_workshop = ("facture", "invoice", "date", "siret", "siren", "tva", "telephone", "tel ", "client")
    for line in lines[:12]:
        plain = _plain(line)
        if 3 <= len(line) <= 120 and any(char.isalpha() for char in line) and not any(word in plain for word in excluded_workshop):
            workshop = line
            break

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

    detected_fields = sum(value is not None for value in (
        performed_at, mileage, title, workshop, invoice_number, total,
    )) + min(2, len(parts))
    confidence = min(0.98, 0.25 + detected_fields * 0.09)
    warnings: list[str] = []
    if performed_at is None:
        warnings.append("Date non détectée : vérifie-la avant l’enregistrement.")
    if mileage is None:
        warnings.append("Kilométrage absent de la facture : une estimation datée peut être proposée.")
    if not parts:
        warnings.append("Aucune référence de pièce clairement libellée n’a été détectée.")
    if not any(part.serial_number or part.removed_serial_number for part in parts):
        warnings.append("Aucun numéro de série clairement libellé n’a été détecté.")
    warnings.append("Contrôle obligatoire : corrige les champs préremplis avant de sauvegarder.")

    return InvoiceAnalysis(
        performed_at=performed_at,
        mileage_km=mileage,
        title=title,
        workshop=workshop,
        invoice_number=invoice_number,
        invoice_total=total,
        currency="EUR" if "€" in text or "eur" in text.casefold() else "EUR",
        parts=parts,
        confidence=round(confidence, 2),
        ocr_used=ocr_used,
        extracted_text_excerpt="\n".join(lines)[:6_000],
        warnings=warnings,
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
