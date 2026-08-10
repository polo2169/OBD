from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
import threading

from app.config import settings
from app.diagnostic.history import active_vehicle
from app.learn.capture import capture_manager
from app.models import OperatingModeRequest
from app.transports.selection import connection_probe_status


_LOCK = threading.RLock()


def _audit_path() -> Path:
    path = settings.security_audit_file
    if path.is_absolute():
        return path
    return (Path(__file__).resolve().parents[1] / path).resolve()


def operating_mode_state() -> dict:
    connection = connection_probe_status()
    gateway_ready = settings.transport == "virtual" or bool(connection.get("verified"))
    capture = capture_manager.status()
    maintenance_available = bool(
        settings.runtime_mode_switch_enabled
        and settings.can_tx_enabled
        and gateway_ready
        and not capture.active
    )
    blockers: list[str] = []
    if not settings.runtime_mode_switch_enabled:
        blockers.append("RUNTIME_MODE_SWITCH_ENABLED=false")
    if not settings.can_tx_enabled:
        blockers.append("Émission CAN désactivée")
    if not gateway_ready:
        blockers.append("Passerelle diagnostic non validée")
    if capture.active:
        blockers.append("Capture Live Data ou Learn active")
    return {
        "mode": "read_only" if settings.read_only else "maintenance",
        "read_only": settings.read_only,
        "maintenance_available": maintenance_available,
        "runtime_switch_enabled": settings.runtime_mode_switch_enabled,
        "can_tx_enabled": settings.can_tx_enabled,
        "gateway_ready": gateway_ready,
        "capture_active": capture.active,
        "blockers": blockers,
        "capabilities": {
            "diagnostic_reads": settings.can_tx_enabled and gateway_ready,
            "dtc_clear": not settings.read_only and settings.dtc_clear_enabled,
            "safety_ecu_clear": not settings.read_only and settings.safety_ecu_clear_enabled,
            "psa_actions": not settings.read_only and settings.psa_actuator_enabled,
            "security_access": not settings.read_only and settings.psa_security_access_enabled,
            "ecu_reset": not settings.read_only and settings.psa_ecu_reset_enabled,
            "telecoding": bool(
                not settings.read_only
                and settings.psa_security_access_enabled
                and settings.psa_telecoding_write_enabled
            ),
        },
    }


def _write_audit(previous: str, requested: str, vin: str | None) -> None:
    path = _audit_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    event = {
        "timestamp": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "type": "operating_mode_changed",
        "previous_mode": previous,
        "mode": requested,
        "vin": vin,
        "transport": settings.transport,
    }
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(event, ensure_ascii=False) + "\n")


def change_operating_mode(request: OperatingModeRequest) -> dict:
    with _LOCK:
        previous = "read_only" if settings.read_only else "maintenance"
        if request.mode == "read_only":
            settings.read_only = True
            if previous != "read_only":
                _write_audit(previous, "read_only", request.vin)
            return operating_mode_state()

        state = operating_mode_state()
        if not state["maintenance_available"]:
            detail = ", ".join(state["blockers"]) or "mode indisponible"
            raise PermissionError(f"Mode maintenance verrouillé : {detail}.")
        if request.confirmation.strip() != "ACTIVER MAINTENANCE":
            raise PermissionError("Confirmation exacte requise : ACTIVER MAINTENANCE")
        missing = [
            label
            for checked, label in (
                (request.vehicle_stationary, "véhicule immobilisé"),
                (request.ignition_on_engine_off, "contact mis et moteur arrêté"),
                (request.stable_battery_voltage, "tension batterie stable"),
                (request.workshop_or_private_site, "atelier ou site privé"),
            )
            if not checked
        ]
        if missing:
            raise PermissionError("Préconditions non confirmées : " + ", ".join(missing) + ".")
        vehicle = active_vehicle()
        active_vin = vehicle.get("vin") if vehicle else None
        if not request.vin or request.vin != active_vin:
            raise PermissionError("Le VIN confirmé doit correspondre au véhicule actif du Garage.")

        settings.read_only = False
        _write_audit(previous, "maintenance", request.vin)
        return operating_mode_state()
