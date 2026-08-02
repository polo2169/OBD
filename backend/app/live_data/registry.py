from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import json
import re
import threading
import unicodedata
import uuid

from app.config import settings
from app.live_data.models import LiveSensorCreate, LiveSensorDefinition, LiveSensorUpdate


_LOCK = threading.RLock()


def _path() -> Path:
    path = settings.live_sensor_registry_file
    if path.is_absolute():
        return path
    return (Path(__file__).resolve().parents[2] / path).resolve()


def _read() -> dict[str, LiveSensorDefinition]:
    path = _path()
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, json.JSONDecodeError):
        return {}
    if not isinstance(payload, dict):
        return {}
    definitions: dict[str, LiveSensorDefinition] = {}
    for key, value in payload.items():
        try:
            definitions[key] = LiveSensorDefinition.model_validate({"key": key, **value})
        except (TypeError, ValueError):
            continue
    return definitions


def _write(definitions: dict[str, LiveSensorDefinition]) -> None:
    path = _path()
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        key: value.model_dump(exclude={"key"}, exclude_none=True)
        for key, value in sorted(definitions.items())
    }
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def list_definitions(vin: str | None = None, *, include_archived: bool = False) -> list[LiveSensorDefinition]:
    with _LOCK:
        definitions = list(_read().values())
    result = [
        item for item in definitions
        if (item.vin is None or item.vin == vin) and (include_archived or not item.archived)
    ]
    return sorted(result, key=lambda item: (item.archived, item.category.casefold(), item.label.casefold()))


def create_definition(request: LiveSensorCreate) -> LiveSensorDefinition:
    if request.source_key.startswith("CUSTOM."):
        raise ValueError("Un capteur personnalisé doit référencer une source CAN/OBD directe.")
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    ascii_label = unicodedata.normalize("NFKD", request.label).encode("ascii", "ignore").decode("ascii")
    slug = re.sub(r"[^A-Za-z0-9_]+", "_", ascii_label).strip("_").upper()[:60] or "SENSOR"
    key = f"CUSTOM.{slug}_{uuid.uuid4().hex[:6].upper()}"
    definition = LiveSensorDefinition(
        **request.model_dump(),
        key=key,
        created_at=now,
        updated_at=now,
    )
    with _LOCK:
        definitions = _read()
        definitions[key] = definition
        _write(definitions)
    return definition


def update_definition(key: str, request: LiveSensorUpdate) -> LiveSensorDefinition:
    with _LOCK:
        definitions = _read()
        current = definitions.get(key)
        if current is None:
            raise KeyError(f"Capteur personnalisé introuvable : {key}.")
        updated = current.model_copy(update={
            **request.model_dump(),
            "updated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        })
        definitions[key] = updated
        _write(definitions)
    return updated


def archive_definition(key: str) -> LiveSensorDefinition:
    with _LOCK:
        definitions = _read()
        current = definitions.get(key)
        if current is None:
            raise KeyError(f"Capteur personnalisé introuvable : {key}.")
        archived = current.model_copy(update={
            "archived": True,
            "updated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        })
        definitions[key] = archived
        _write(definitions)
    return archived
