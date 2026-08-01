from __future__ import annotations

from udsoncan.exceptions import NegativeResponseException, TimeoutException

from app.config import settings
from app.database import KnowledgeBase
from app.diagnostic.isotp import UdsSession
from app.diagnostic.dtc_status import apply_dtc_classification, summarize_dtcs
from app.diagnostic.history import finalize_scan
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
    return [apply_dtc_classification(item) for item in decoded]


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


def _integer(value: int | str) -> int:
    return int(str(value), 0)


def _probe_payloads(diagnostic_config: dict) -> list[bytes]:
    configured = diagnostic_config.get(
        "probe_payloads",
        ["1001", "1003", "3E00", "22F186", "22F190"],
    )
    payloads: list[bytes] = []
    for value in configured:
        payload = bytes.fromhex(str(value).replace("0x", ""))
        if payload and payload not in payloads:
            payloads.append(payload)
    return payloads


def _probe_session(session: UdsSession, payloads: list[bytes]) -> tuple[bool, str | None, str | None]:
    for payload in payloads:
        label = payload.hex().upper()
        try:
            response = session.request(payload)
            return True, label, response.hex().upper()
        except NegativeResponseException as exc:
            return True, label, exc.response.original_payload.hex().upper()
        except (TimeoutException, TimeoutError):
            continue
    return False, None, None


def _address_options(ecu: EcuDefinition) -> list[dict]:
    options = [{
        "request_id": ecu.request_id,
        "response_id": ecu.response_id,
        "label": "adresse principale",
        "source": ecu.source,
        "confidence": ecu.confidence,
    }]
    options.extend(ecu.address_candidates)
    unique: list[dict] = []
    seen: set[tuple[int | None, int | None]] = set()
    for option in options:
        request_id = option.get("request_id")
        response_id = option.get("response_id")
        normalized_request = _integer(request_id) if request_id is not None else None
        normalized_response = _integer(response_id) if response_id is not None else None
        pair = (normalized_request, normalized_response)
        if pair in seen:
            continue
        seen.add(pair)
        unique.append({**option, "request_id": normalized_request, "response_id": normalized_response})
    return unique


def scan_vehicle(vehicle_profile: str | None = None, vin: str | None = None) -> ScanReport:
    kb = KnowledgeBase()
    profile_key = vehicle_profile or settings.vehicle_profile
    vehicle = kb.vehicle(profile_key)
    diagnostic_config = vehicle.get("diagnostic", {})
    if diagnostic_config.get("identity_scope") == "identity_only":
        raise ValueError(
            f"Le profil {profile_key} est limité à l'identification ; aucun scan ECU constructeur ne sera improvisé."
        )

    trace = SessionWriter() if settings.debug_sessions_enabled else None
    transport = build_transport(_trace_sink(trace) if trace else None)
    results: list[EcuScanResult] = []
    warnings: list[str] = []
    ecus = kb.ecus(profile_key)
    did_definitions = kb.dids()
    identification_dids = kb.identification_dids(profile_key)
    did_order = {did: index for index, did in enumerate(identification_dids)}
    probe_payloads = _probe_payloads(diagnostic_config)
    read_dtcs = settings.read_dtcs and bool(diagnostic_config.get("read_dtcs", True))
    default_dtc_masks = [
        _integer(value)
        for value in diagnostic_config.get(
            "dtc_status_masks",
            [diagnostic_config.get("dtc_status_mask", 0xFF), 0x09],
        )
    ]

    if trace:
        trace.write({
            "type": "scan_start",
            "vehicle_profile": profile_key,
            "vin": vin,
            "transport": transport.name,
            "read_only": settings.read_only,
            "can_tx_enabled": settings.can_tx_enabled,
            "read_dtcs": read_dtcs,
            "probe_payloads": [payload.hex().upper() for payload in probe_payloads],
            "dtc_status_masks": default_dtc_masks,
        })

    opened = False
    try:
        transport.open()
        opened = True
        for ecu in ecus:
            addresses = _address_options(ecu)
            if trace:
                trace.write({
                    "type": "ecu_scan_start",
                    "ecu": ecu.key,
                    "name": ecu.name,
                    "family": ecu.family,
                    "address_options": addresses,
                    "aliases": ecu.aliases,
                })

            detected = False
            selected_request_id = ecu.request_id
            selected_response_id = ecu.response_id
            probe_method: str | None = None
            probe_response_hex: str | None = None
            vin_value: str | None = None
            identification: list[DidReadResult] = []
            dtcs: list[DtcReadResult] = []
            dtc_availability_mask: int | None = None
            dtc_status_mask_used: int | None = None
            dtc_error: str | None = None
            raw_responses: list[str] = []
            transport_errors: list[str] = []

            for address in addresses:
                request_id = address.get("request_id")
                response_id = address.get("response_id")
                if request_id is None or response_id is None:
                    continue
                candidate_identification: list[DidReadResult] = []
                candidate_raw: list[str] = []
                try:
                    with UdsSession(
                        transport,
                        request_id,
                        response_id,
                        timeout=settings.diagnostic_timeout,
                        read_only=settings.read_only,
                    ) as session:
                        present, method, probe_raw = _probe_session(session, probe_payloads)
                        if not present:
                            continue
                        detected = True
                        selected_request_id = request_id
                        selected_response_id = response_id
                        probe_method = method
                        probe_response_hex = probe_raw
                        if probe_raw:
                            candidate_raw.append(probe_raw)

                        for did in identification_dids:
                            definition = did_definitions.get(did, {})
                            value_payload: bytes | None = None
                            try:
                                response, value_payload = read_data_by_identifier(session, did)
                                candidate_raw.append(response.original_payload.hex().upper())
                                value = decode_did_value(value_payload, definition.get("codec", "bytes"))
                                candidate_identification.append(DidReadResult(
                                    did=did,
                                    name=definition.get("name", f"DID 0x{did:04X}"),
                                    codec=definition.get("codec", "bytes"),
                                    value=value,
                                    raw_hex=value_payload.hex().upper(),
                                    source=definition.get("source"),
                                    confidence=definition.get("confidence", "experimental"),
                                ))
                                if did == 0xF190 and isinstance(value, str):
                                    vin_value = value
                            except NegativeResponseException as exc:
                                raw = exc.response.original_payload
                                candidate_raw.append(raw.hex().upper())
                                candidate_identification.append(_did_error(
                                    did,
                                    definition,
                                    f"NRC 0x{exc.response.code:02X} {exc.response.code_name}",
                                    raw,
                                ))
                            except (TimeoutException, TimeoutError) as exc:
                                candidate_identification.append(_did_error(did, definition, str(exc)))
                            except ValueError as exc:
                                candidate_identification.append(_did_error(
                                    did,
                                    definition,
                                    str(exc),
                                    value_payload,
                                ))

                        if read_dtcs:
                            masks = ecu.dtc_status_masks or default_dtc_masks
                            mask_errors: list[str] = []
                            for mask in dict.fromkeys(masks):
                                try:
                                    response, dtc_availability_mask, raw_dtcs = read_dtcs_by_status_mask(
                                        session,
                                        mask,
                                    )
                                    candidate_raw.append(response.original_payload.hex().upper())
                                    dtcs = _decode_dtcs(kb, ecu, raw_dtcs)
                                    dtc_status_mask_used = mask
                                    mask_errors = []
                                    break
                                except NegativeResponseException as exc:
                                    raw = exc.response.original_payload
                                    candidate_raw.append(raw.hex().upper())
                                    mask_errors.append(
                                        f"masque 0x{mask:02X}: NRC 0x{exc.response.code:02X} {exc.response.code_name}"
                                    )
                                except (TimeoutException, TimeoutError, ValueError) as exc:
                                    mask_errors.append(f"masque 0x{mask:02X}: {exc}")
                            if mask_errors:
                                dtc_error = "; ".join(mask_errors)
                        identification = candidate_identification
                        raw_responses = candidate_raw
                        break
                except Exception as exc:
                    transport_errors.append(
                        f"0x{request_id:X}/0x{response_id:X}: {exc}"
                    )

            identification.sort(key=lambda item: did_order.get(item.did, len(did_order)))
            result = EcuScanResult(
                key=ecu.key,
                name=ecu.name,
                detected=detected,
                request_id=selected_request_id,
                response_id=selected_response_id,
                family=ecu.family,
                network=ecu.network,
                confidence=ecu.confidence,
                optional=ecu.optional,
                source=ecu.source,
                vin=vin_value,
                identification=identification,
                aliases=ecu.aliases,
                dtcs=dtcs,
                dtc_status_availability_mask=dtc_availability_mask,
                dtc_status_mask_used=dtc_status_mask_used,
                dtc_error=dtc_error,
                probe_method=probe_method,
                probe_response_hex=probe_response_hex,
                raw_responses=raw_responses,
                error="; ".join(transport_errors) or (
                    "Aucune adresse candidate documentée n'a répondu."
                    if not detected and addresses else None
                ),
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

    if not settings.read_only:
        warnings.append("Le filtre applicatif UDS lecture seule est désactivé.")
    if any(ecu.confidence == "community_family_catalog" for ecu in ecus):
        warnings.append(
            "Les adresses constructeur sont communautaires ; seule une réponse UDS confirme un calculateur."
        )
    if read_dtcs:
        warnings.append(
            "Les entrées classées « test non exécuté » ne sont pas comptées comme des pannes. "
            "Le code brut, le sous-type et le statut UDS restent la référence."
        )
    if any(ecu.aliases for ecu in ecus):
        warnings.append(
            "Certaines paires d'adresses sont partagées entre variantes ; les DIDs d'identification "
            "doivent confirmer le calculateur réel."
        )

    report = ScanReport(
        vehicle_profile=profile_key,
        manufacturer=vehicle.get("manufacturer"),
        model=vehicle.get("model"),
        transport=transport.name,
        readonly=settings.read_only,
        ecus=results,
        dtc_summary=summarize_dtcs(results),
        warnings=warnings,
    )
    if trace:
        trace.write({"type": "scan_report", "payload": report.model_dump()})
        report.debug = DebugSummary(**trace.finish())
    return finalize_scan(report, vin)


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
