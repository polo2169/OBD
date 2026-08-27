from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import json
import re
import threading
import unicodedata
import uuid

from app.config import settings
from app.maintenance.models import ServiceProvider, ServiceProviderInput


_LOCK = threading.RLock()
_PROVIDER_ID = re.compile(r"^provider-[a-f0-9]{12}$")


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _diagnostic_root() -> Path:
    path = settings.diagnostic_history_dir
    if not path.is_absolute():
        backend_root = Path(__file__).resolve().parents[2]
        path = (backend_root / path).resolve()
    path.mkdir(parents=True, exist_ok=True)
    return path


def _root() -> Path:
    return _diagnostic_root() / "service_providers"


def _path(provider_id: str) -> Path:
    if not _PROVIDER_ID.fullmatch(provider_id):
        raise KeyError("Professionnel introuvable.")
    return _root() / "records" / f"{provider_id}.json"


def _read(path: Path) -> dict:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise KeyError("Professionnel introuvable.") from exc
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        raise ValueError(f"La fiche professionnel est illisible : {path.name}.") from exc
    if not isinstance(payload, dict):
        raise ValueError(f"La fiche professionnel est invalide : {path.name}.")
    return payload


def _atomic(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    temporary.replace(path)


def _plain(value: str) -> str:
    return " ".join(
        "".join(
            character
            for character in unicodedata.normalize("NFKD", value)
            if not unicodedata.combining(character)
        )
        .casefold()
        .split()
    )


def list_service_providers() -> list[ServiceProvider]:
    with _LOCK:
        providers = [
            ServiceProvider.model_validate(_read(path))
            for path in sorted((_root() / "records").glob("provider-*.json"))
        ] if (_root() / "records").exists() else []
    return sorted(providers, key=lambda item: (item.display_name or item.legal_name).casefold())


def get_service_provider(provider_id: str) -> ServiceProvider:
    with _LOCK:
        return ServiceProvider.model_validate(_read(_path(provider_id)))


def _duplicate(entry: ServiceProviderInput, *, excluding: str | None = None) -> ServiceProvider | None:
    for provider in list_service_providers():
        if provider.id == excluding:
            continue
        same_identifier = (
            (entry.siret and provider.siret == entry.siret)
            or (entry.vat_number and provider.vat_number == entry.vat_number)
        )
        same_name_and_city = (
            _plain(provider.legal_name) == _plain(entry.legal_name)
            and _plain(provider.city or "") == _plain(entry.city or "")
        )
        if same_identifier or same_name_and_city:
            return provider
    return None


def create_service_provider(entry: ServiceProviderInput) -> ServiceProvider:
    if duplicate := _duplicate(entry):
        raise ValueError(f"Ce professionnel existe déjà : {duplicate.id}.")
    now = _utc_now()
    provider_id = f"provider-{uuid.uuid4().hex[:12]}"
    payload = {
        **entry.model_dump(mode="json"),
        "id": provider_id,
        "created_at": now.isoformat(timespec="seconds"),
        "updated_at": now.isoformat(timespec="seconds"),
        "revision": 1,
    }
    with _LOCK:
        _atomic(_path(provider_id), payload)
    return ServiceProvider.model_validate(payload)


def update_service_provider(provider_id: str, entry: ServiceProviderInput) -> ServiceProvider:
    if duplicate := _duplicate(entry, excluding=provider_id):
        raise ValueError(f"Ces coordonnées appartiennent déjà à {duplicate.id}.")
    with _LOCK:
        current = _read(_path(provider_id))
        revision = int(current.get("revision") or 1)
        archive = _root() / "revisions" / provider_id / f"revision-{revision:04d}.json"
        if not archive.exists():
            _atomic(archive, current)
        payload = {
            **entry.model_dump(mode="json"),
            "id": provider_id,
            "created_at": current["created_at"],
            "updated_at": _utc_now().isoformat(timespec="seconds"),
            "revision": revision + 1,
        }
        _atomic(_path(provider_id), payload)
    return ServiceProvider.model_validate(payload)


def match_service_provider(candidate: ServiceProviderInput | None) -> ServiceProvider | None:
    return _duplicate(candidate) if candidate is not None else None
