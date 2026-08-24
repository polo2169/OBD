from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import json
import threading
import uuid

from app.config import settings
from app.diagnostic.history import active_identity
from app.models import OilLogEntryInput, OilLogEntryResult


_LOCK = threading.Lock()


def _path() -> Path:
    path = settings.oil_log_file
    if path.is_absolute():
        return path
    backend_root = Path(__file__).resolve().parents[2]
    return (backend_root / path).resolve()


def _load_raw() -> list[dict]:
    path = _path()
    with _LOCK:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError, json.JSONDecodeError):
            return []
    return payload if isinstance(payload, list) else []


def _write_raw(payload: list[dict]) -> None:
    path = _path()
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    with _LOCK:
        temporary.write_text(
            json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        temporary.replace(path)


def _parse(item: dict) -> OilLogEntryResult | None:
    try:
        return OilLogEntryResult.model_validate(item)
    except ValueError:
        return None


def list_oil_log(
    vin: str | None = None,
    vehicle_profile: str | None = None,
) -> list[OilLogEntryResult]:
    results = [entry for item in _load_raw() if (entry := _parse(item)) is not None]
    if vin is not None:
        results = [result for result in results if result.vin == vin]
    if vehicle_profile is not None:
        results = [result for result in results if result.vehicle_profile == vehicle_profile]
    # Chronologique croissant : c'est un carnet, pas un flux "plus récent d'abord".
    results.sort(key=lambda result: result.recorded_at)
    return results


def save_oil_log_entry(entry: OilLogEntryInput) -> OilLogEntryResult:
    entry.vehicle_profile = entry.vehicle_profile or settings.vehicle_profile
    identity = active_identity(entry.vehicle_profile)
    entry.vin = entry.vin or (identity or {}).get("vin")

    now = datetime.now(timezone.utc)
    record = {
        **entry.model_dump(exclude_none=True),
        "id": f"oil-{now.strftime('%Y%m%dT%H%M%S%fZ')}-{uuid.uuid4().hex[:8]}",
        "recorded_at": now.isoformat(timespec="seconds"),
    }
    # Chaque relevé est un point distinct du carnet : contrairement aux DTC
    # observés, on n'écrase jamais un relevé précédent (pas de déduplication).
    payload = _load_raw()
    payload.append(record)
    _write_raw(payload)

    result = _parse(record)
    if result is None:
        raise ValueError("Relevé de carnet d'entretien invalide.")
    return result
