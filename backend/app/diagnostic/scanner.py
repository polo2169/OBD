from __future__ import annotations

from udsoncan.exceptions import NegativeResponseException, TimeoutException

from app.config import settings
from app.database import KnowledgeBase
from app.diagnostic.isotp import UdsSession
from app.diagnostic.uds import (
    clear_diagnostic_information,
    read_data_by_identifier,
    read_dtcs_by_status_mask,
)
from app.models import (
    ClearDtcRequest,
    ClearDtcResult,
    DebugSummary,
    DidReadResult,
    DtcReadResult,
    EcuDefinition,
    EcuScanResult,
    ScanReport,
)
from app.session import SessionWriter
from app.transports.factory import build_transport


SAFETY_CRITICAL_ECUS = {
    "abs_esp",
    "airbag",
    "bsi",
    "front_camera",
    "power_steering",
}


def decode_vin(response: bytes) -> str | None:
    if not response.startswith(b"\x62\xF1\x90"):
        return None
    return response[3:].decode("ascii", errors="replace").strip("\x00 ")


def decode_did_value(payload: bytes, codec: str) -> str | int:
    if codec == "ascii":
        return payload.decode("ascii", errors="replace").strip("\x00 ")
    if codec == "uint8":
        if len(payload) != 1:
            raise ValueError(f"uint8 attend 1 octet, reçu {len(payload)}.")
        return payload[0]
    return payload.hex().upper()


def _did_error(did: int, definition: dict, message: str, raw: bytes | None = None) -> DidReadResult:
    return DidReadResult(
        did=did,
        name=definition.get("name", f"DID 0x{did:04X}"),
        codec=definition.get("codec", "bytes"),
        raw_hex=raw.hex().upper() if raw else None,
        source=definition.get("source"),
        confidence=definition.get("confidence", "experimental"),
        error=message,
    )


def _trace_sink(session: SessionWriter):
    def sink(event: dict) -> None:
        if event.get("type") == "can_frame" and not settings.trace_can_frames:
            return
        session.write(event)
    return sink


def _decode_dtcs(
    kb: KnowledgeBase,
    ecu: EcuDefinition,
    raw_dtcs,
) -> list[DtcReadResult]:
    decoded: list[DtcReadResult] = []
    for item in raw_dtcs:
        definition = kb.lookup_dtc(item.code, ecu.dtc_catalogs)
        decoded.append(DtcReadResult(
            code=item.code,
            raw_hex=item.raw_hex,
            failure_type=item.failure_type,
            status=item.status,
            status_hex=f"{item.status:02X}",
            status_labels=item.status_labels,
            title=definition.get("title"),
            catalogs=definition.get("catalogs", []),
            source=definition.get("source"),
            confidence=definition.get("confidence", "raw_only"),
        ))
    return decoded


def read_ecu_did(ecu_key: str, did: int) -> DidReadResult:
    kb = KnowledgeBase()
    definition = kb.dids().get(did)
    if definition is None:
        raise KeyError(f"DID 0x{did:04X} non documenté.")
    if definition.get("access", "read_only") != "read_only":
        raise PermissionError(f"DID 0x{did:04X} non classé en lecture seule.")

    ecu = next((item for item in kb.ecus() if item.key == ecu_key), None)
    if ecu is None:
        raise KeyError(f"Calculateur inconnu : {ecu_key}.")
    if ecu.request_id is None or ecu.response_id is None:
        raise ValueError(f"Adresses non documentées pour {ecu.name}.")

    trace = SessionWriter() if settings.debug_sessions_enabled else None
    transport = build_transport(_trace_sink(trace) if trace else None)
    if trace:
        trace.write({"type": "did_read_start", "ecu": ecu_key, "did": did})
    opened = False
    try:
        transport.open()
        opened = True
        with UdsSession(
            transport,
            ecu.request_id,
            ecu.response_id,
            timeout=settings.diagnostic_timeout,
            read_only=settings.read_only,
        ) as session:
            try:
                response, value_payload = read_data_by_identifier(session, did)
            except NegativeResponseException as exc:
                result = _did_error(
                    did,
                    definition,
                    f"NRC 0x{exc.response.code:02X} {exc.response.code_name}",
                    exc.response.original_payload,
                )
            else:
                result = DidReadResult(
                    did=did,
                    name=definition.get("name", f"DID 0x{did:04X}"),
                    codec=definition.get("codec", "bytes"),
                    value=decode_did_value(value_payload, definition.get("codec", "bytes")),
                    raw_hex=value_payload.hex().upper(),
                    source=definition.get("source"),
                    confidence=definition.get("confidence", "experimental"),
                )
            if trace:
                trace.write({
                    "type": "did_read_result",
                    "ecu": ecu_key,
                    "payload": result.model_dump(),
                })
            return result
    finally:
        if opened:
            transport.close()
        if trace:
            trace.finish()


def scan_vehicle() -> ScanReport:
    kb = KnowledgeBase()
    trace = SessionWriter() if settings.debug_sessions_enabled else None
    transport = build_transport(_trace_sink(trace) if trace else None)
    results: list[EcuScanResult] = []
    warnings: list[str] = []
    did_definitions = kb.dids()
    identification_dids = kb.identification_dids()
    probe_did = kb.probe_did()
    scan_dids = [probe_did, *[did for did in identification_dids if did != probe_did]]
    did_order = {did: index for index, did in enumerate(identification_dids)}
    diagnostic_config = kb.vehicle().get("diagnostic", {})
    read_dtcs = settings.read_dtcs and bool(diagnostic_config.get("read_dtcs", True))
    dtc_status_mask = int(str(diagnostic_config.get("dtc_status_mask", 0xFF)), 0)

    if trace:
        trace.write({
            "type": "scan_start",
            "vehicle_profile": settings.vehicle_profile,
            "transport": transport.name,
            "read_only": settings.read_only,
            "can_tx_enabled": settings.can_tx_enabled,
            "read_dtcs": read_dtcs,
            "dtc_status_mask": dtc_status_mask,
        })

    opened = False
    try:
        transport.open()
        opened = True
        for ecu in kb.ecus():
            if trace:
                trace.write({
                    "type": "ecu_scan_start",
                    "ecu": ecu.key,
                    "name": ecu.name,
                    "family": ecu.family,
                    "request_id": ecu.request_id,
                    "response_id": ecu.response_id,
                    "aliases": ecu.aliases,
                })
            if ecu.request_id is None or ecu.response_id is None:
                result = EcuScanResult(
                    key=ecu.key,
                    name=ecu.name,
                    detected=False,
                    request_id=ecu.request_id,
                    response_id=ecu.response_id,
                    family=ecu.family,
                    network=ecu.network,
                    confidence=ecu.confidence,
                    optional=ecu.optional,
                    source=ecu.source,
                    aliases=ecu.aliases,
                    error="Adresses non documentées.",
                )
                results.append(result)
                if trace:
                    trace.write({"type": "ecu_scan_result", "payload": result.model_dump()})
                continue

            detected = False
            vin: str | None = None
            identification: list[DidReadResult] = []
            dtcs: list[DtcReadResult] = []
            dtc_availability_mask: int | None = None
            dtc_error: str | None = None
            raw_responses: list[str] = []
            transport_errors: list[str] = []

            try:
                with UdsSession(
                    transport,
                    ecu.request_id,
                    ecu.response_id,
                    timeout=settings.diagnostic_timeout,
                    read_only=settings.read_only,
                ) as session:
                    for did in scan_dids:
                        definition = did_definitions.get(did, {})
                        value_payload: bytes | None = None
                        try:
                            response, value_payload = read_data_by_identifier(session, did)
                            detected = True
                            raw_responses.append(response.original_payload.hex().upper())
                            value = decode_did_value(
                                value_payload,
                                definition.get("codec", "bytes"),
                            )
                            identification.append(DidReadResult(
                                did=did,
                                name=definition.get("name", f"DID 0x{did:04X}"),
                                codec=definition.get("codec", "bytes"),
                                value=value,
                                raw_hex=value_payload.hex().upper(),
                                source=definition.get("source"),
                                confidence=definition.get("confidence", "experimental"),
                            ))
                            if did == 0xF190 and isinstance(value, str):
                                vin = value
                        except NegativeResponseException as exc:
                            detected = True
                            raw = exc.response.original_payload
                            raw_responses.append(raw.hex().upper())
                            identification.append(_did_error(
                                did,
                                definition,
                                f"NRC 0x{exc.response.code:02X} {exc.response.code_name}",
                                raw,
                            ))
                        except TimeoutException as exc:
                            identification.append(_did_error(did, definition, str(exc)))
                            if did == probe_did and not detected:
                                break
                        except ValueError as exc:
                            if value_payload is not None:
                                detected = True
                            identification.append(_did_error(
                                did,
                                definition,
                                str(exc),
                                value_payload,
                            ))

                    if detected and read_dtcs:
                        try:
                            response, dtc_availability_mask, raw_dtcs = read_dtcs_by_status_mask(
                                session,
                                dtc_status_mask,
                            )
                            raw_responses.append(response.original_payload.hex().upper())
                            dtcs = _decode_dtcs(kb, ecu, raw_dtcs)
                        except NegativeResponseException as exc:
                            raw = exc.response.original_payload
                            raw_responses.append(raw.hex().upper())
                            dtc_error = f"NRC 0x{exc.response.code:02X} {exc.response.code_name}"
                        except TimeoutException as exc:
                            dtc_error = str(exc)
                        except ValueError as exc:
                            dtc_error = str(exc)
            except Exception as exc:
                transport_errors.append(str(exc))

            identification.sort(key=lambda item: did_order.get(item.did, len(did_order)))

            result = EcuScanResult(
                key=ecu.key,
                name=ecu.name,
                detected=detected,
                request_id=ecu.request_id,
                response_id=ecu.response_id,
                family=ecu.family,
                network=ecu.network,
                confidence=ecu.confidence,
                optional=ecu.optional,
                source=ecu.source,
                vin=vin,
                identification=identification,
                aliases=ecu.aliases,
                dtcs=dtcs,
                dtc_status_availability_mask=dtc_availability_mask,
                dtc_error=dtc_error,
                raw_responses=raw_responses,
                error="; ".join(transport_errors) or None,
            )
            results.append(result)
            if trace:
                trace.write({"type": "ecu_scan_result", "payload": result.model_dump()})
    except Exception as exc:
        if trace:
            trace.write({
                "type": "scan_error",
                "error_type": type(exc).__name__,
                "error": str(exc),
            })
            trace.finish()
        raise
    finally:
        if opened:
            transport.close()

    if settings.transport != "virtual" and not settings.can_tx_enabled:
        warnings.append(
            "Émission CAN désactivée : activez CAN_TX_ENABLED uniquement pour lancer un diagnostic actif."
        )
    if not settings.read_only:
        warnings.append("Le filtre applicatif UDS lecture seule est désactivé.")
    if any(ecu.confidence == "community_family_catalog" for ecu in kb.ecus()):
        warnings.append(
            "Les adresses PSA proviennent d'un catalogue de familles communautaire ; "
            "la réponse du véhicule confirme la présence réelle de chaque calculateur."
        )
    if read_dtcs:
        warnings.append(
            "Les descriptions DTC PSA sont communautaires : le code brut et son état font foi ; "
            "la description dépend de la variante ECU identifiée."
        )
    if any(ecu.aliases for ecu in kb.ecus()):
        warnings.append(
            "Certaines paires d'adresses sont partagées entre variantes (notamment CVM/CPL) ; "
            "les DIDs d'identification doivent confirmer le calculateur réel."
        )

    report = ScanReport(
        vehicle_profile=settings.vehicle_profile,
        transport=transport.name,
        readonly=settings.read_only,
        ecus=results,
        warnings=warnings,
    )
    if trace:
        trace.write({"type": "scan_report", "payload": report.model_dump()})
        report.debug = DebugSummary(**trace.finish())
    return report


def clear_ecu_dtcs(ecu_key: str, request: ClearDtcRequest) -> ClearDtcResult:
    if not settings.dtc_clear_enabled:
        raise PermissionError("Effacement DTC verrouillé : DTC_CLEAR_ENABLED=false.")
    if settings.read_only:
        raise PermissionError("Effacement DTC impossible tant que READ_ONLY=true.")
    if not settings.can_tx_enabled:
        raise PermissionError("Effacement DTC impossible tant que CAN_TX_ENABLED=false.")
    if ecu_key in SAFETY_CRITICAL_ECUS and not settings.safety_ecu_clear_enabled:
        raise PermissionError(
            "Effacement d'un ECU de sécurité verrouillé : SAFETY_ECU_CLEAR_ENABLED=false."
        )

    required_confirmation = f"EFFACER {ecu_key.upper()}"
    if request.confirmation.strip() != required_confirmation:
        raise PermissionError(f"Confirmation exacte requise : {required_confirmation}")
    missing = [
        label
        for field, label in (
            (request.vehicle_stationary, "véhicule immobilisé"),
            (request.ignition_on_engine_off, "contact mis et moteur arrêté"),
            (request.stable_battery_voltage, "tension batterie stable"),
            (request.report_saved, "rapport avant effacement sauvegardé"),
        )
        if not field
    ]
    if missing:
        raise PermissionError("Préconditions non confirmées : " + ", ".join(missing) + ".")

    kb = KnowledgeBase()
    ecu = next((item for item in kb.ecus() if item.key == ecu_key), None)
    if ecu is None:
        raise KeyError(f"Calculateur inconnu : {ecu_key}.")
    if ecu.request_id is None or ecu.response_id is None:
        raise ValueError(f"Adresses non documentées pour {ecu.name}.")

    trace = SessionWriter()
    transport = build_transport(_trace_sink(trace))
    trace.write({
        "type": "dtc_clear_start",
        "ecu": ecu_key,
        "request_id": ecu.request_id,
        "response_id": ecu.response_id,
        "preconditions": request.model_dump(exclude={"confirmation"}),
    })
    opened = False
    try:
        transport.open()
        opened = True
        with UdsSession(
            transport,
            ecu.request_id,
            ecu.response_id,
            timeout=settings.diagnostic_timeout,
            read_only=False,
            maintenance=True,
        ) as uds_session:
            response = clear_diagnostic_information(uds_session)
        result = ClearDtcResult(
            ecu_key=ecu_key,
            cleared=True,
            response_hex=response.original_payload.hex().upper(),
            message="Mémoire DTC effacée ; relire immédiatement les défauts pour vérifier ceux qui reviennent.",
            session_id=trace.id,
        )
        trace.write({"type": "dtc_clear_result", "payload": result.model_dump()})
        return result
    except Exception as exc:
        trace.write({
            "type": "dtc_clear_error",
            "ecu": ecu_key,
            "error_type": type(exc).__name__,
            "error": str(exc),
        })
        raise
    finally:
        if opened:
            transport.close()
        trace.finish()
