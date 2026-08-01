from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import json
import threading

from app.config import settings
from app.database import KnowledgeBase
from app.diagnostic.history import active_identity
from app.models import ObservedDtcInput, ObservedDtcResult


_LOCK = threading.Lock()


def _path() -> Path:
    path = settings.observed_dtcs_file
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


def _enrich(item: dict, kb: KnowledgeBase) -> ObservedDtcResult | None:
    try:
        entry = ObservedDtcInput.model_validate(item)
    except ValueError:
        return None
    entry.code = entry.code.upper()
    profile = entry.vehicle_profile or settings.vehicle_profile
    try:
        ecus = kb.ecus(profile)
    except FileNotFoundError:
        ecus = []
    ecu = next((candidate for candidate in ecus if candidate.key == entry.ecu_key), None)
    definition = kb.lookup_dtc(entry.code, ecu.dtc_catalogs if ecu else None)
    return ObservedDtcResult(
        **entry.model_dump(),
        ecu_name=ecu.name if ecu else "Calculateur à confirmer",
        title=entry.label or definition.get("title"),
        catalogs=definition.get("catalogs", []),
        catalog_source=definition.get("source"),
        confidence="user_reported_catalog_match" if definition else "user_reported_raw",
        recorded_at=str(item.get("recorded_at") or ""),
    )


def list_observed_dtcs(
    vin: str | None = None,
    vehicle_profile: str | None = None,
) -> list[ObservedDtcResult]:
    kb = KnowledgeBase()
    results = [result for item in _load_raw() if (result := _enrich(item, kb)) is not None]
    if vin is not None:
        results = [result for result in results if result.vin == vin]
    if vehicle_profile is not None:
        results = [result for result in results if result.vehicle_profile == vehicle_profile]
    return results


def save_observed_dtc(entry: ObservedDtcInput) -> ObservedDtcResult:
    entry.code = entry.code.upper()
    entry.vehicle_profile = entry.vehicle_profile or settings.vehicle_profile
    identity = active_identity(entry.vehicle_profile)
    entry.vin = entry.vin or (identity or {}).get("vin")
    payload = _load_raw()
    record = {
        **entry.model_dump(exclude_none=True),
        "recorded_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    key = (entry.vin, entry.vehicle_profile, entry.code, entry.ecu_key)
    payload = [
        item for item in payload
        if (
            item.get("vin"),
            item.get("vehicle_profile"),
            str(item.get("code") or "").upper(),
            item.get("ecu_key"),
        ) != key
    ]
    payload.append(record)
    _write_raw(payload)
    result = _enrich(record, KnowledgeBase())
    if result is None:
        raise ValueError(f"Code DTC invalide : {entry.code}")
    return result
