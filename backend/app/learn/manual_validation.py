from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import json
import threading

from app.config import settings
from app.learn.models import ManualSignalValidation


_LOCK = threading.Lock()


def _path() -> Path:
    path = settings.manual_signal_validations_file
    if path.is_absolute():
        return path
    backend_root = Path(__file__).resolve().parents[2]
    return (backend_root / path).resolve()


def load_manual_validations() -> dict[str, ManualSignalValidation]:
    path = _path()
    with _LOCK:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError, json.JSONDecodeError):
            return {}
    if not isinstance(payload, dict):
        return {}
    result: dict[str, ManualSignalValidation] = {}
    for key, value in payload.items():
        try:
            result[key] = ManualSignalValidation.model_validate({"key": key, **value})
        except (TypeError, ValueError):
            continue
    return result


def set_manual_validation(
    key: str,
    validated: bool,
    note: str | None,
    session_id: str | None,
) -> ManualSignalValidation:
    entries = load_manual_validations()
    entry = ManualSignalValidation(
        key=key,
        validated=validated,
        note=note,
        session_id=session_id,
        validated_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
    )
    entries[key] = entry
    _write(entries)
    return entry


def clear_manual_validation(key: str) -> bool:
    entries = load_manual_validations()
    existed = entries.pop(key, None) is not None
    if existed:
        _write(entries)
    return existed


def _write(entries: dict[str, ManualSignalValidation]) -> None:
    path = _path()
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        key: value.model_dump(exclude={"key"})
        for key, value in sorted(entries.items())
    }
    temporary = path.with_suffix(path.suffix + ".tmp")
    with _LOCK:
        temporary.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        temporary.replace(path)
