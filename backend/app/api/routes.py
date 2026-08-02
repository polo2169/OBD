from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import FileResponse, HTMLResponse
from udsoncan.exceptions import NegativeResponseException, TimeoutException

from app.config import settings
from app.database import KnowledgeBase
from app.diagnostic.obd import sensor_catalog, snapshot_sensors
from app.diagnostic.identity import read_vehicle_identity
from app.diagnostic.history import (
    active_vehicle,
    active_identity,
    find_report,
    latest_report,
    list_reports,
    list_vehicles,
    report_html,
    select_vehicle,
)
from app.diagnostic.maintenance import maintenance_catalog
from app.diagnostic.observed_dtcs import list_observed_dtcs, save_observed_dtc
from app.diagnostic.psa_advanced import (
    advanced_catalog,
    calculate_seed_key,
    execute_named_action,
    read_raw_did,
    unlock_configuration,
)
from app.diagnostic.regression import compare_with_baseline
from app.diagnostic.scanner import clear_ecu_dtcs, read_ecu_did, scan_vehicle
from app.diagnostic.trace_import import import_diagnostic_trace
from app.learn.capture import capture_manager
from app.models import (
    ClearDtcRequest,
    ClearDtcResult,
    DiagnosticTraceImportRequest,
    DidReadResult,
    ObservedDtcInput,
    ObservedDtcResult,
    PsaActionRequest,
    PsaActionResult,
    PsaSeedKeyRequest,
    PsaSeedKeyResult,
    PsaUnlockRequest,
    PsaUnlockResult,
    ScanReport,
    ScanRequest,
    SensorSnapshot,
    TransportConnectRequest,
    VehicleIdentityRequest,
    VehicleIdentityResult,
    VehicleSelectionRequest,
)
from app.transports.selection import (
    available_transport_options,
    connection_probe_status,
    probe_and_select_transport,
)

router = APIRouter(prefix="/api")


@router.get("/system/status")
def status() -> dict:
    gateway_endpoint = None
    if settings.transport == "esp32_wifi":
        gateway_endpoint = f"{settings.esp32_wifi_host}:{settings.esp32_wifi_port}"
    elif settings.transport == "esp32_serial":
        gateway_endpoint = settings.serial_port
    connection = connection_probe_status()
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
        "psa_advanced_enabled": settings.psa_advanced_enabled,
        "psa_security_access_enabled": settings.psa_security_access_enabled,
        "psa_actuator_enabled": settings.psa_actuator_enabled,
        "vehicle_profile": settings.vehicle_profile,
        "gateway_endpoint": gateway_endpoint,
        "gateway_verified": connection["verified"],
        "gateway_hello": connection["hello"],
        "gateway_error": connection["error"],
    }


@router.get("/system/transports")
def system_transports() -> dict:
    endpoint = (
        f"{settings.esp32_wifi_host}:{settings.esp32_wifi_port}"
        if settings.transport == "esp32_wifi"
        else settings.serial_port if settings.transport == "esp32_serial" else None
    )
    current_id = (
        f"serial:{endpoint}" if settings.transport == "esp32_serial" and endpoint
        else f"wifi:{endpoint}" if settings.transport == "esp32_wifi" and endpoint
        else None
    )
    return {
        "options": available_transport_options(),
        "current_id": current_id,
        "capture_active": capture_manager.status().active,
        "connection": connection_probe_status(),
    }


@router.post("/system/transport/connect")
def system_transport_connect(request: TransportConnectRequest) -> dict:
    if capture_manager.status().active:
        raise HTTPException(
            status_code=409,
            detail="Arrête et sauvegarde la capture avant de changer de connexion ESP32.",
        )
    try:
        return probe_and_select_transport(request.transport, request.endpoint, request.baud)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=503,
            detail=f"Connexion ESP32 impossible : {exc}",
        ) from exc


@router.get("/database/vehicle")
def vehicle_profile() -> dict:
    return KnowledgeBase().vehicle()


@router.get("/database/vehicles")
def vehicle_profiles() -> list[dict]:
    return KnowledgeBase().vehicle_profiles()


@router.get("/maintenance/catalog")
def vehicle_maintenance_catalog(
    vehicle_profile: str | None = Query(default=None),
) -> dict:
    try:
        return maintenance_catalog(vehicle_profile)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


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
def observed_dtcs(
    vin: str | None = Query(default=None),
    vehicle_profile: str | None = Query(default=None),
) -> list[ObservedDtcResult]:
    return list_observed_dtcs(vin=vin, vehicle_profile=vehicle_profile)


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
def diagnostic_sensor_snapshot(
    vehicle_profile: str | None = Query(default=None),
) -> SensorSnapshot:
    if settings.transport != "virtual" and not settings.can_tx_enabled:
        raise HTTPException(
            status_code=403,
            detail="PID OBD actifs indisponibles : l'ESP32 est en écoute passive stricte.",
        )
    try:
        return snapshot_sensors(vehicle_profile)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except TimeoutException as exc:
        raise HTTPException(status_code=504, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/diagnostic/scan", response_model=ScanReport)
def diagnostic_scan(request: ScanRequest | None = None) -> ScanReport:
    if settings.transport != "virtual" and not settings.can_tx_enabled:
        raise HTTPException(
            status_code=403,
            detail=(
                "Inventaire ECU/DTC actif indisponible : le firmware ESP32 est en "
                "listen-only. Aucun message n'a été émis."
            ),
        )
    try:
        return scan_vehicle(
            request.vehicle_profile if request else None,
            request.vin if request else None,
        )
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/diagnostic/traces/import")
def diagnostic_trace_import(request: DiagnosticTraceImportRequest) -> dict:
    """Normalize an exported diagnostic trace without transmitting to the vehicle."""

    try:
        return import_diagnostic_trace(request)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/diagnostic/vehicles")
def diagnostic_vehicles() -> list[dict]:
    return list_vehicles()


@router.get("/diagnostic/vehicles/active")
def diagnostic_active_vehicle() -> dict:
    vehicle = active_vehicle()
    if vehicle is None:
        raise HTTPException(status_code=404, detail="Aucun véhicule enregistré.")
    return vehicle


@router.post("/diagnostic/vehicles/active")
def diagnostic_select_vehicle(request: VehicleSelectionRequest) -> dict:
    try:
        return select_vehicle(request.vin)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=exc.args[0]) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/diagnostic/identity/latest")
def diagnostic_latest_identity(vehicle_profile: str = Query(default="peugeot_308_t9_2018")) -> dict:
    identity = active_identity(vehicle_profile)
    if identity is None:
        raise HTTPException(status_code=404, detail="Aucune identité enregistrée pour ce profil.")
    return identity


@router.get("/diagnostic/reports")
def diagnostic_reports(
    vehicle_profile: str | None = Query(default=None),
    vin: str | None = Query(default=None),
) -> list[dict]:
    return list_reports(vehicle_profile=vehicle_profile, vin=vin)


@router.get("/diagnostic/reports/latest", response_model=ScanReport)
def diagnostic_latest_report(
    vehicle_profile: str | None = Query(default=None),
    vin: str | None = Query(default=None),
) -> ScanReport:
    report = latest_report(vehicle_profile=vehicle_profile, vin=vin)
    if report is None:
        raise HTTPException(status_code=404, detail="Aucun rapport diagnostic enregistré.")
    return report


@router.get("/diagnostic/reports/{scan_id}", response_model=ScanReport)
def diagnostic_report(scan_id: str) -> ScanReport:
    found = find_report(scan_id)
    if found is None:
        raise HTTPException(status_code=404, detail="Rapport diagnostic introuvable.")
    return found[0]


@router.get("/diagnostic/reports/{scan_id}/regression")
def diagnostic_report_regression(scan_id: str) -> dict:
    found = find_report(scan_id)
    if found is None:
        raise HTTPException(status_code=404, detail="Rapport diagnostic introuvable.")
    try:
        return compare_with_baseline(found[0])
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/diagnostic/reports/{scan_id}/export")
def diagnostic_report_export(scan_id: str, format: str = Query(default="html")):
    found = find_report(scan_id)
    if found is None:
        raise HTTPException(status_code=404, detail="Rapport diagnostic introuvable.")
    report, path = found
    safe_vin = report.vin or "sans-vin"
    if format == "json":
        return FileResponse(
            path,
            media_type="application/json",
            filename=f"opendiag-{safe_vin}-{scan_id}.json",
        )
    if format != "html":
        raise HTTPException(status_code=422, detail="Formats disponibles : html, json.")
    return HTMLResponse(
        report_html(report),
        headers={"Content-Disposition": f'attachment; filename="opendiag-{safe_vin}-{scan_id}.html"'},
    )


@router.post("/diagnostic/identity", response_model=VehicleIdentityResult)
def diagnostic_vehicle_identity(request: VehicleIdentityRequest) -> VehicleIdentityResult:
    try:
        return read_vehicle_identity(request.vehicle_profile)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=exc.args[0]) from exc
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


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


@router.get("/diagnostic/psa/catalog")
def diagnostic_psa_catalog() -> dict:
    return advanced_catalog()


@router.post("/diagnostic/psa/seed-key", response_model=PsaSeedKeyResult)
def diagnostic_psa_seed_key(request: PsaSeedKeyRequest) -> PsaSeedKeyResult:
    try:
        return calculate_seed_key(request.seed_hex, request.application_key_hex)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/diagnostic/psa/ecus/{ecu_key}/dids/{did}", response_model=DidReadResult)
def diagnostic_psa_read_raw_did(ecu_key: str, did: str) -> DidReadResult:
    try:
        normalized = did.strip().lower()
        base = 16 if normalized.startswith("0x") or any(c in "abcdef" for c in normalized) else 10
        return read_raw_did(ecu_key, int(normalized, base))
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
            detail=f"Lecture refusée par l'ECU : NRC 0x{exc.response.code:02X} {exc.response.code_name}",
        ) from exc


@router.post("/diagnostic/psa/ecus/{ecu_key}/unlock", response_model=PsaUnlockResult)
def diagnostic_psa_unlock(ecu_key: str, request: PsaUnlockRequest) -> PsaUnlockResult:
    try:
        return unlock_configuration(ecu_key, request)
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
            detail=f"Accès sécurité refusé par l'ECU : NRC 0x{exc.response.code:02X} {exc.response.code_name}",
        ) from exc


@router.post("/diagnostic/psa/actions/{action_key}", response_model=PsaActionResult)
def diagnostic_psa_action(action_key: str, request: PsaActionRequest) -> PsaActionResult:
    try:
        return execute_named_action(action_key, request)
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
            detail=f"Action refusée par l'ECU : NRC 0x{exc.response.code:02X} {exc.response.code_name}",
        ) from exc


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
