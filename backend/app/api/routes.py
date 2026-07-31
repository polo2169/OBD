from fastapi import APIRouter, HTTPException
from udsoncan.exceptions import NegativeResponseException, TimeoutException

from app.config import settings
from app.database import KnowledgeBase
from app.diagnostic.obd import sensor_catalog, snapshot_sensors
from app.diagnostic.observed_dtcs import list_observed_dtcs, save_observed_dtc
from app.diagnostic.scanner import clear_ecu_dtcs, read_ecu_did, scan_vehicle
from app.models import (
    ClearDtcRequest,
    ClearDtcResult,
    DidReadResult,
    ObservedDtcInput,
    ObservedDtcResult,
    ScanReport,
    SensorSnapshot,
)

router = APIRouter(prefix="/api")


@router.get("/system/status")
def status() -> dict:
    gateway_endpoint = None
    if settings.transport == "esp32_wifi":
        gateway_endpoint = f"{settings.esp32_wifi_host}:{settings.esp32_wifi_port}"
    elif settings.transport == "esp32_serial":
        gateway_endpoint = settings.serial_port
    return {
        "application": settings.app_name,
        "transport": settings.transport,
        "read_only": settings.read_only,
        "can_tx_enabled": settings.can_tx_enabled,
        "read_dtcs": settings.read_dtcs,
        "debug_sessions_enabled": settings.debug_sessions_enabled,
        "trace_can_frames": settings.trace_can_frames,
        "dtc_clear_enabled": settings.dtc_clear_enabled,
        "safety_ecu_clear_enabled": settings.safety_ecu_clear_enabled,
        "vehicle_profile": settings.vehicle_profile,
        "gateway_endpoint": gateway_endpoint,
    }


@router.get("/database/vehicle")
def vehicle_profile() -> dict:
    return KnowledgeBase().vehicle()


@router.get("/database/dids")
def did_catalog() -> list[dict]:
    return [
        {"did": did, **definition}
        for did, definition in sorted(KnowledgeBase().dids().items())
    ]


@router.get("/database/dtcs/status")
def dtc_catalog_status() -> dict:
    return KnowledgeBase().dtc_metadata()


@router.get("/diagnostic/dtcs/observed", response_model=list[ObservedDtcResult])
def observed_dtcs() -> list[ObservedDtcResult]:
    return list_observed_dtcs()


@router.post("/diagnostic/dtcs/observed", response_model=ObservedDtcResult)
def record_observed_dtc(entry: ObservedDtcInput) -> ObservedDtcResult:
    try:
        return save_observed_dtc(entry)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/sensors/catalog")
def diagnostic_sensor_catalog() -> list[dict]:
    return sensor_catalog()


@router.post("/sensors/snapshot", response_model=SensorSnapshot)
def diagnostic_sensor_snapshot() -> SensorSnapshot:
    if settings.transport != "virtual" and not settings.can_tx_enabled:
        raise HTTPException(
            status_code=403,
            detail="PID OBD actifs indisponibles : l'ESP32 est en écoute passive stricte.",
        )
    try:
        return snapshot_sensors()
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except TimeoutException as exc:
        raise HTTPException(status_code=504, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/diagnostic/scan", response_model=ScanReport)
def diagnostic_scan() -> ScanReport:
    if settings.transport != "virtual" and not settings.can_tx_enabled:
        raise HTTPException(
            status_code=403,
            detail=(
                "Inventaire ECU/DTC actif indisponible : le firmware ESP32 est en "
                "listen-only. Aucun message n'a été émis."
            ),
        )
    return scan_vehicle()


@router.post("/diagnostic/ecus/{ecu_key}/dids/{did}", response_model=DidReadResult)
def diagnostic_read_did(ecu_key: str, did: str) -> DidReadResult:
    try:
        normalized = did.strip().lower()
        base = 16 if normalized.startswith("0x") or any(c in "abcdef" for c in normalized) else 10
        did_value = int(normalized, base)
        result = read_ecu_did(ecu_key, did_value)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=exc.args[0]) from exc
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except TimeoutException as exc:
        raise HTTPException(status_code=504, detail=str(exc)) from exc

    return result


@router.post("/diagnostic/ecus/{ecu_key}/dtcs/clear", response_model=ClearDtcResult)
def diagnostic_clear_dtcs(ecu_key: str, request: ClearDtcRequest) -> ClearDtcResult:
    try:
        return clear_ecu_dtcs(ecu_key, request)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=exc.args[0]) from exc
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except TimeoutException as exc:
        raise HTTPException(status_code=504, detail=str(exc)) from exc
    except NegativeResponseException as exc:
        raise HTTPException(
            status_code=409,
            detail=f"Effacement refusé par l'ECU : NRC 0x{exc.response.code:02X} {exc.response.code_name}",
        ) from exc


@router.get("/diagnostic/live")
def live_placeholder() -> dict:
    return {
        "status": "prototype",
        "signals": {
            "rpm": 780,
            "coolant_c": 88,
            "battery_v": 12.6,
            "vehicle_speed_kmh": 0,
        },
        "source": "simulation",
    }
