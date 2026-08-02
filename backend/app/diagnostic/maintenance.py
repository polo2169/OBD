from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from app.config import settings
from app.database import KnowledgeBase


def _catalog_path() -> Path:
    return settings.database_dir / "maintenance" / "services.yaml"


def _service_definitions() -> list[dict[str, Any]]:
    payload = yaml.safe_load(_catalog_path().read_text(encoding="utf-8")) or {}
    services = payload.get("services", [])
    if not isinstance(services, list):
        raise ValueError("Le catalogue des services de maintenance est invalide.")
    return [dict(item) for item in services if isinstance(item, dict) and item.get("key")]


def maintenance_catalog(vehicle_profile: str | None = None) -> dict[str, Any]:
    """Build a truthful capability matrix without inventing active commands."""
    profile_key = vehicle_profile or settings.vehicle_profile
    vehicle = KnowledgeBase().vehicle(profile_key)
    maintenance = vehicle.get("maintenance", {})
    applicable = set(maintenance.get("applicable", []))
    conditional = set(maintenance.get("conditional", []))
    not_applicable = set(maintenance.get("not_applicable", []))
    validated = set(maintenance.get("vehicle_validated", []))

    services: list[dict[str, Any]] = []
    for definition in _service_definitions():
        key = str(definition["key"])
        if key in not_applicable:
            applicability = "not_applicable"
            implementation_status = "not_applicable"
            reason = "Fonction absente ou incompatible avec ce profil véhicule."
        elif key in conditional:
            applicability = "if_equipped"
            implementation_status = "equipment_confirmation_required"
            reason = "La présence du calculateur ou de l'équipement doit d'abord être confirmée."
        elif key in applicable:
            applicability = "applicable"
            implementation_status = (
                "vehicle_validated" if key in validated else "procedure_required"
            )
            reason = (
                "Procédure et résultat validés sur ce profil."
                if key in validated
                else "Applicable, mais aucune séquence constructeur validée sur ce véhicule n'est encore autorisée."
            )
        else:
            applicability = "unknown"
            implementation_status = "research_required"
            reason = "Applicabilité non documentée pour ce profil."

        execution_enabled = key in validated and implementation_status == "vehicle_validated"
        services.append({
            **definition,
            "applicability": applicability,
            "implementation_status": implementation_status,
            "execution_enabled": execution_enabled,
            "reason": reason,
        })

    counts: dict[str, int] = {}
    for service in services:
        status = service["implementation_status"]
        counts[status] = counts.get(status, 0) + 1

    return {
        "vehicle_profile": profile_key,
        "manufacturer": vehicle.get("manufacturer", "Inconnu"),
        "model": vehicle.get("model", "Inconnu"),
        "policy": maintenance.get("policy", "catalog_only_until_vehicle_validated"),
        "execution_enabled": any(service["execution_enabled"] for service in services),
        "service_count": len(services),
        "counts": counts,
        "services": services,
        "notes": list(maintenance.get("notes", [])),
        "protocol_coverage": [
            {
                "key": "iso15765_can",
                "name": "ISO 15765-4 · CAN classique",
                "supported": True,
                "detail": "CAN 11/29 bits et ISO-TP disponibles sur la passerelle actuelle.",
            },
            {
                "key": "uds",
                "name": "ISO 14229 · UDS",
                "supported": True,
                "detail": "Lecture disponible; les écritures restent soumises aux profils et allowlists.",
            },
            {
                "key": "iso9141_kwp",
                "name": "ISO 9141-2 / KWP2000 K-Line",
                "supported": False,
                "detail": "Transceiver K-Line absent du matériel actuel.",
            },
            {
                "key": "j1850",
                "name": "SAE J1850 VPW/PWM",
                "supported": False,
                "detail": "Couche physique J1850 absente du matériel actuel.",
            },
            {
                "key": "can_fd",
                "name": "CAN-FD",
                "supported": False,
                "detail": "TWAI et MCP2515 actuels limités au CAN classique.",
            },
        ],
    }


def require_vehicle_validated_service(vehicle_profile: str, service_key: str) -> dict[str, Any]:
    """Central guard for future executors; currently every catalog action is locked."""
    catalog = maintenance_catalog(vehicle_profile)
    service = next((item for item in catalog["services"] if item["key"] == service_key), None)
    if service is None:
        raise KeyError(f"Service de maintenance inconnu : {service_key}.")
    if not service["execution_enabled"]:
        raise PermissionError(service["reason"])
    return service
