from __future__ import annotations

from udsoncan.exceptions import NegativeResponseException, TimeoutException

from app.config import settings
from app.database import KnowledgeBase
from app.diagnostic.isotp import UdsSession
from app.diagnostic.dtc_status import apply_dtc_classification, summarize_dtcs
from app.diagnostic.history import finalize_scan
from app.diagnostic.uds import (
    clear_diagnostic_information,
    decode_dtc_status,
    enter_extended_session,
    format_sae_dtc,
    read_data_by_identifier,
    read_dtc_snapshot,
    read_dtcs_by_status_mask,
    read_obd_dtcs,
)
from app.models import (
    ClearDtcRequest,
    ClearDtcResult,
    DebugSummary,
    DidReadResult,
    DidSweepHit,
    DidSweepResult,
    DtcReadResult,
    DtcSnapshotResult,
    EcuDefinition,
    EcuScanResult,
    ScanReport,
    TelecodingParameterValue,
    TelecodingZoneInfo,
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
        try:
            return payload.decode("ascii", errors="strict").strip("\x00 ")
        except UnicodeDecodeError as exc:
            raise ValueError(
                "Valeur non ASCII : interprétation refusée, utiliser les octets bruts."
            ) from exc
    if codec == "uint8":
        if len(payload) != 1:
            raise ValueError(f"uint8 attend 1 octet, reçu {len(payload)}.")
        return payload[0]
    return payload.hex().upper()


def _did_error(
    did: int,
    definition: dict,
    message: str,
    raw: bytes | None = None,
    *,
    response_raw: bytes | None = None,
    nrc: int | None = None,
    nrc_name: str | None = None,
) -> DidReadResult:
    return DidReadResult(
        did=did,
        name=definition.get("name", f"DID 0x{did:04X}"),
        codec=definition.get("codec", "bytes"),
        raw_hex=raw.hex().upper() if raw else None,
        source=definition.get("source"),
        confidence=definition.get("confidence", "experimental"),
        request_hex=f"22{did:04X}",
        response_hex=(response_raw or raw).hex().upper() if (response_raw or raw) else None,
        nrc=nrc,
        nrc_name=nrc_name,
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
            failure_type_label=kb.failure_type_label(item.failure_type),
            status=item.status,
            status_hex=f"{item.status:02X}",
            status_labels=item.status_labels,
            title=definition.get("title"),
            catalogs=definition.get("catalogs", []),
            source=definition.get("source"),
            confidence=definition.get("confidence", "raw_only"),
        ))
    return [apply_dtc_classification(item) for item in decoded]


def _read_dtc_snapshot(
    session: UdsSession,
    kb: KnowledgeBase,
    ecu: EcuDefinition,
    masks: list[int],
) -> tuple[list[DtcReadResult], int, int, str]:
    """Read one ECU DTC memory and keep the exact successful exchange metadata."""

    errors: list[str] = []
    for mask in dict.fromkeys(masks):
        try:
            response, availability_mask, raw_dtcs = read_dtcs_by_status_mask(session, mask)
            return (
                _decode_dtcs(kb, ecu, raw_dtcs),
                availability_mask,
                mask,
                response.original_payload.hex().upper(),
            )
        except NegativeResponseException as exc:
            errors.append(
                f"masque 0x{mask:02X}: NRC 0x{exc.response.code:02X} {exc.response.code_name}"
            )
        except (TimeoutException, TimeoutError, ValueError) as exc:
            errors.append(f"masque 0x{mask:02X}: {exc}")
    raise ValueError("Lecture DTC impossible : " + "; ".join(errors))


def _describe_telecoding(
    kb: KnowledgeBase,
    ecu: EcuDefinition,
    did: int,
    value_payload: bytes,
) -> TelecodingZoneInfo | None:
    zone = kb.describe_telecoding_zone(ecu.family, did)
    if zone is None:
        return None
    parameters = kb.decode_telecoding_parameters(zone, value_payload)
    return TelecodingZoneInfo(
        did=did,
        name=zone.get("name", f"Zone 0x{did:04X}"),
        family=ecu.family or "",
        parameters=[TelecodingParameterValue(**item) for item in parameters],
        source=kb.pypsadiag_source(),
    )


def read_ecu_did(ecu_key: str, did: int, vehicle_profile: str | None = None) -> DidReadResult:
    kb = KnowledgeBase()
    definition = kb.dids().get(did)
    if definition is None:
        raise KeyError(f"DID 0x{did:04X} non documenté.")
    if definition.get("access", "read_only") != "read_only":
        raise PermissionError(f"DID 0x{did:04X} non classé en lecture seule.")

    ecu = next((item for item in kb.ecus(vehicle_profile) if item.key == ecu_key), None)
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
            enter_extended_session(session)
            try:
                response, value_payload = read_data_by_identifier(session, did)
            except NegativeResponseException as exc:
                result = _did_error(
                    did,
                    definition,
                    f"NRC 0x{exc.response.code:02X} {exc.response.code_name}",
                    exc.response.original_payload,
                    nrc=exc.response.code,
                    nrc_name=exc.response.code_name,
                )
            else:
                try:
                    value = decode_did_value(value_payload, definition.get("codec", "bytes"))
                except ValueError as exc:
                    result = _did_error(
                        did,
                        definition,
                        str(exc),
                        value_payload,
                        response_raw=response.original_payload,
                    )
                else:
                    result = DidReadResult(
                        did=did,
                        name=definition.get("name", f"DID 0x{did:04X}"),
                        codec=definition.get("codec", "bytes"),
                        value=value,
                        raw_hex=value_payload.hex().upper(),
                        source=definition.get("source"),
                        confidence=definition.get("confidence", "experimental"),
                        request_hex=f"22{did:04X}",
                        response_hex=response.original_payload.hex().upper(),
                        telecoding=_describe_telecoding(kb, ecu, did, value_payload),
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


def read_ecu_dtc_snapshot(
    ecu_key: str,
    dtc_raw_hex: str,
    record_number: int = 0xFF,
    vehicle_profile: str | None = None,
) -> DtcSnapshotResult:
    kb = KnowledgeBase()
    ecu = next((item for item in kb.ecus(vehicle_profile) if item.key == ecu_key), None)
    if ecu is None:
        raise KeyError(f"Calculateur inconnu : {ecu_key}.")
    if ecu.request_id is None or ecu.response_id is None:
        raise ValueError(f"Adresses non documentées pour {ecu.name}.")

    dtc_bytes = bytes.fromhex(dtc_raw_hex)
    code = format_sae_dtc(dtc_bytes[0], dtc_bytes[1]) if len(dtc_bytes) >= 2 else dtc_raw_hex
    request_hex = f"1904{dtc_raw_hex.upper()}{record_number:02X}"

    trace = SessionWriter() if settings.debug_sessions_enabled else None
    transport = build_transport(_trace_sink(trace) if trace else None)
    if trace:
        trace.write({
            "type": "dtc_snapshot_start",
            "ecu": ecu_key,
            "dtc_raw_hex": dtc_raw_hex,
            "record_number": record_number,
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
            read_only=settings.read_only,
        ) as session:
            try:
                (
                    response,
                    status,
                    snapshot_record_number,
                    identifier_count,
                    raw_data,
                ) = read_dtc_snapshot(session, dtc_raw_hex, record_number)
            except NegativeResponseException as exc:
                result = DtcSnapshotResult(
                    ecu_key=ecu_key,
                    code=code,
                    dtc_raw_hex=dtc_raw_hex.upper(),
                    record_number_requested=record_number,
                    request_hex=request_hex,
                    response_hex=exc.response.original_payload.hex().upper(),
                    nrc=exc.response.code,
                    nrc_name=exc.response.code_name,
                    error=f"NRC 0x{exc.response.code:02X} {exc.response.code_name}",
                )
            else:
                result = DtcSnapshotResult(
                    ecu_key=ecu_key,
                    code=code,
                    dtc_raw_hex=dtc_raw_hex.upper(),
                    record_number_requested=record_number,
                    status=status,
                    status_hex=f"{status:02X}" if status is not None else None,
                    status_labels=decode_dtc_status(status) if status is not None else [],
                    snapshot_record_number=snapshot_record_number,
                    identifier_count=identifier_count,
                    raw_data_hex=raw_data.hex().upper() if raw_data else None,
                    request_hex=request_hex,
                    response_hex=response.original_payload.hex().upper(),
                )
            if trace:
                trace.write({
                    "type": "dtc_snapshot_result",
                    "ecu": ecu_key,
                    "payload": result.model_dump(),
                })
            return result
    finally:
        if opened:
            transport.close()
        if trace:
            trace.finish()


MAX_DID_SWEEP_SPAN = 0x200


def sweep_ecu_dids(
    ecu_key: str,
    did_start: int,
    did_end: int,
    vehicle_profile: str | None = None,
) -> DidSweepResult:
    if not 0 <= did_start <= 0xFFFF or not 0 <= did_end <= 0xFFFF:
        raise ValueError("Les DID doivent tenir sur deux octets (0x0000-0xFFFF).")
    if did_end < did_start:
        raise ValueError("did_end doit être supérieur ou égal à did_start.")
    span = did_end - did_start + 1
    if span > MAX_DID_SWEEP_SPAN:
        raise ValueError(
            f"Plage trop large ({span} identifiants) ; {MAX_DID_SWEEP_SPAN} au maximum par "
            "appel pour rester dans un temps raisonnable. Balayer par tranches."
        )

    kb = KnowledgeBase()
    ecu = next((item for item in kb.ecus(vehicle_profile) if item.key == ecu_key), None)
    if ecu is None:
        raise KeyError(f"Calculateur inconnu : {ecu_key}.")
    if ecu.request_id is None or ecu.response_id is None:
        raise ValueError(f"Adresses non documentées pour {ecu.name}.")

    trace = SessionWriter() if settings.debug_sessions_enabled else None
    transport = build_transport(_trace_sink(trace) if trace else None)
    if trace:
        trace.write({
            "type": "did_sweep_start",
            "ecu": ecu_key,
            "did_start": did_start,
            "did_end": did_end,
        })

    hits: list[DidSweepHit] = []
    unsupported_count = 0
    timeout_count = 0
    scanned_count = 0
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
            enter_extended_session(session)
            for did in range(did_start, did_end + 1):
                scanned_count += 1
                try:
                    response, value_payload = read_data_by_identifier(session, did)
                    hits.append(DidSweepHit(
                        did=did,
                        outcome="positive",
                        raw_hex=value_payload.hex().upper(),
                        response_hex=response.original_payload.hex().upper(),
                        telecoding=_describe_telecoding(kb, ecu, did, value_payload),
                    ))
                except NegativeResponseException as exc:
                    code = exc.response.code
                    # 0x31 requestOutOfRange : réponse attendue pour un DID non supporté,
                    # ce n'est pas une découverte intéressante.
                    if code == 0x31:
                        unsupported_count += 1
                        continue
                    hits.append(DidSweepHit(
                        did=did,
                        outcome="negative_response",
                        nrc=code,
                        nrc_name=exc.response.code_name,
                        response_hex=exc.response.original_payload.hex().upper(),
                    ))
                except (TimeoutException, TimeoutError):
                    timeout_count += 1
    finally:
        if opened:
            transport.close()
        if trace:
            trace.write({
                "type": "did_sweep_result",
                "ecu": ecu_key,
                "scanned_count": scanned_count,
                "hit_count": len(hits),
                "unsupported_count": unsupported_count,
                "timeout_count": timeout_count,
            })
            trace.finish()

    return DidSweepResult(
        ecu_key=ecu_key,
        did_start=did_start,
        did_end=did_end,
        scanned_count=scanned_count,
        hits=hits,
        unsupported_count=unsupported_count,
        timeout_count=timeout_count,
    )


_OBD_DTC_MODE_LABELS = {
    0x03: ("active", "Actif", "Code mémorisé (Mode OBD 03)."),
    0x07: ("not_tested", "En attente", "Code en attente, moniteur pas encore confirmé (Mode OBD 07)."),
}


def read_engine_obd_dtcs(ecu_key: str = "engine", vehicle_profile: str | None = None) -> EcuScanResult:
    """Generic EOBD Mode 03/07 DTC read, independent of the PSA-style UDS 0x19 scan.

    Deliberately bypasses the `identity_scope: identity_only` gate on
    `scan_vehicle`: it only ever talks to the one ECU the caller names, using
    plain standardized OBD services, not the unconfirmed UDS/KWP addresses
    some vehicle profiles still carry for body/cluster calculators.
    """
    kb = KnowledgeBase()
    profile_key = vehicle_profile or settings.vehicle_profile
    ecu = next((item for item in kb.ecus(profile_key) if item.key == ecu_key), None)
    if ecu is None:
        raise KeyError(f"Calculateur inconnu : {ecu_key}.")
    if ecu.request_id is None or ecu.response_id is None:
        raise ValueError(f"Adresses non documentées pour {ecu.name}.")

    trace = SessionWriter() if settings.debug_sessions_enabled else None
    transport = build_transport(_trace_sink(trace) if trace else None)
    if trace:
        trace.write({"type": "obd_dtc_read_start", "ecu": ecu_key})

    dtcs: list[DtcReadResult] = []
    errors: list[str] = []
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
            for mode, (state, state_label, state_detail) in _OBD_DTC_MODE_LABELS.items():
                try:
                    raw_dtcs = read_obd_dtcs(session, mode)
                except NegativeResponseException as exc:
                    errors.append(f"mode 0x{mode:02X}: NRC 0x{exc.response.code:02X} {exc.response.code_name}")
                    continue
                except (TimeoutException, TimeoutError, ValueError, PermissionError) as exc:
                    errors.append(f"mode 0x{mode:02X}: {exc}")
                    continue
                for item in raw_dtcs:
                    definition = kb.lookup_dtc(item.code, ecu.dtc_catalogs)
                    dtcs.append(DtcReadResult(
                        code=item.code,
                        raw_hex=item.raw_hex,
                        failure_type=0,
                        status=0,
                        status_hex="00",
                        status_labels=[],
                        title=definition.get("title"),
                        catalogs=definition.get("catalogs", []),
                        source=definition.get("source"),
                        confidence=definition.get("confidence", "raw_only"),
                        state=state,
                        state_label=state_label,
                        state_detail=state_detail,
                        actionable=state == "active",
                    ))
    finally:
        if opened:
            transport.close()
        if trace:
            trace.write({
                "type": "obd_dtc_read_result",
                "ecu": ecu_key,
                "dtc_count": len(dtcs),
                "errors": errors,
            })
            trace.finish()

    return EcuScanResult(
        key=ecu.key,
        name=ecu.name,
        detected=True,
        request_id=ecu.request_id,
        response_id=ecu.response_id,
        family=ecu.family,
        network=ecu.network,
        confidence=ecu.confidence,
        optional=ecu.optional,
        source=ecu.source,
        dtcs=dtcs,
        dtc_request_hex="03 / 07",
        dtc_error="; ".join(errors) or None,
    )


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


def _probe_session(
    session: UdsSession,
    payloads: list[bytes],
) -> tuple[bool, str | None, str | None, list[dict]]:
    attempts: list[dict] = []
    for payload in payloads:
        label = payload.hex().upper()
        try:
            response = session.request(payload)
            response_hex = response.hex().upper()
            attempts.append({
                "request_hex": label,
                "response_hex": response_hex,
                "outcome": "positive",
            })
            return True, label, response_hex, attempts
        except NegativeResponseException as exc:
            response_hex = exc.response.original_payload.hex().upper()
            attempts.append({
                "request_hex": label,
                "response_hex": response_hex,
                "outcome": "negative_response",
                "nrc": exc.response.code,
                "nrc_name": exc.response.code_name,
            })
            return True, label, response_hex, attempts
        except (TimeoutException, TimeoutError) as exc:
            attempts.append({
                "request_hex": label,
                "response_hex": None,
                "outcome": "timeout",
                "error": str(exc),
            })
            continue
    return False, None, None, attempts


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


EXTENDED_PROBE_TARGETS: dict[str, tuple[int, int]] = {
    "engine": (0x0000, 0x01FF),
    "telematics": (0x0000, 0x01FF),
    # Telecoding zone range (Configuration_Group_Data_List / Gauging_Group_Data_Values):
    # surfaces PyPSADiag CFG_* decode automatically for ECU families it documents.
    "front_camera": (0x2100, 0x21FF),
    "front_radar": (0x2100, 0x21FF),
}


def scan_vehicle(
    vehicle_profile: str | None = None,
    vin: str | None = None,
    extended_probe: bool = False,
) -> ScanReport:
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
            result = _scan_single_ecu(
                transport,
                kb,
                ecu,
                did_definitions,
                identification_dids,
                did_order,
                probe_payloads,
                read_dtcs,
                default_dtc_masks,
                trace,
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

    if extended_probe:
        by_key = {result.key: result for result in results}
        for ecu_key, (did_start, did_end) in EXTENDED_PROBE_TARGETS.items():
            ecu_result = by_key.get(ecu_key)
            if ecu_result is None or not ecu_result.detected:
                continue
            try:
                sweep = sweep_ecu_dids(ecu_key, did_start, did_end)
            except (KeyError, ValueError) as exc:
                ecu_result.did_sweep_error = str(exc)
                continue
            except (NegativeResponseException, TimeoutException) as exc:
                ecu_result.did_sweep_error = f"Balayage interrompu : {exc}"
                continue
            ecu_result.did_sweep_hits = sweep.hits
            ecu_result.did_sweep_range = f"0x{did_start:04X}-0x{did_end:04X}"
        warnings.append(
            "Recherche approfondie activée : balayage DID 0x0000-0x01FF sur les calculateurs "
            "moteur et télématique pour découvrir des identifiants non documentés (injection, "
            "GPS) ainsi que sur la caméra/CVM et le radar avant (0x2100-0x21FF, zones de "
            "télécodage)."
        )

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


def read_ecu_report(ecu_key: str, vehicle_profile: str | None = None) -> EcuScanResult:
    """Identification + DTC read for a single already-known ECU, without scanning the rest."""
    kb = KnowledgeBase()
    profile_key = vehicle_profile or settings.vehicle_profile
    vehicle = kb.vehicle(profile_key)
    diagnostic_config = vehicle.get("diagnostic", {})
    if diagnostic_config.get("identity_scope") == "identity_only":
        raise ValueError(
            f"Le profil {profile_key} est limité à l'identification ; aucune lecture ECU "
            "constructeur ne sera improvisée."
        )
    ecu = next((item for item in kb.ecus(profile_key) if item.key == ecu_key), None)
    if ecu is None:
        raise KeyError(f"Calculateur inconnu : {ecu_key}.")

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

    trace = SessionWriter() if settings.debug_sessions_enabled else None
    transport = build_transport(_trace_sink(trace) if trace else None)
    opened = False
    try:
        transport.open()
        opened = True
        result = _scan_single_ecu(
            transport,
            kb,
            ecu,
            did_definitions,
            identification_dids,
            did_order,
            probe_payloads,
            read_dtcs,
            default_dtc_masks,
            trace,
        )
    finally:
        if opened:
            transport.close()
        if trace:
            trace.finish()
    return result


def _scan_single_ecu(
    transport,
    kb: KnowledgeBase,
    ecu: EcuDefinition,
    did_definitions: dict,
    identification_dids: list[int],
    did_order: dict[int, int],
    probe_payloads: list[bytes],
    read_dtcs: bool,
    default_dtc_masks: list[int],
    trace: SessionWriter | None = None,
) -> EcuScanResult:
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
    probe_attempts: list[dict] = []
    active_session: int | None = None
    active_session_source: str | None = None
    vin_value: str | None = None
    identification: list[DidReadResult] = []
    dtcs: list[DtcReadResult] = []
    dtc_availability_mask: int | None = None
    dtc_status_mask_used: int | None = None
    dtc_error: str | None = None
    dtc_request_hex: str | None = None
    dtc_response_hex: str | None = None
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
                present, method, probe_raw, candidate_probe_attempts = _probe_session(
                    session,
                    probe_payloads,
                )
                probe_attempts.extend(candidate_probe_attempts)
                if not present:
                    continue
                detected = True
                selected_request_id = request_id
                selected_response_id = response_id
                probe_method = method
                probe_response_hex = probe_raw
                if probe_raw:
                    candidate_raw.append(probe_raw)
                if method and method.startswith("10") and probe_raw and probe_raw.startswith("50"):
                    active_session = int(probe_raw[2:4], 16)
                    active_session_source = "diagnostic_session_control"

                # The probe stops at the first payload that gets any response, and
                # "1001" (default session) is tried before "1003" — so it never
                # actually reaches extended session. Many PSA ECUs gate manufacturer
                # identification DIDs behind it even for reads, so ask explicitly here.
                enter_extended_session(session)

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
                            request_hex=f"22{did:04X}",
                            response_hex=response.original_payload.hex().upper(),
                        ))
                        if did == 0xF190 and isinstance(value, str):
                            vin_value = value
                        if did == 0xF186 and isinstance(value, int):
                            active_session = value
                            active_session_source = "did_f186"
                    except NegativeResponseException as exc:
                        raw = exc.response.original_payload
                        candidate_raw.append(raw.hex().upper())
                        candidate_identification.append(_did_error(
                            did,
                            definition,
                            f"NRC 0x{exc.response.code:02X} {exc.response.code_name}",
                            raw,
                            nrc=exc.response.code,
                            nrc_name=exc.response.code_name,
                        ))
                    except (TimeoutException, TimeoutError) as exc:
                        candidate_identification.append(_did_error(did, definition, str(exc)))
                    except ValueError as exc:
                        candidate_identification.append(_did_error(
                            did,
                            definition,
                            str(exc),
                            value_payload,
                            response_raw=response.original_payload,
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
                            dtc_request_hex = f"1902{mask:02X}"
                            dtc_response_hex = response.original_payload.hex().upper()
                            dtcs = _decode_dtcs(kb, ecu, raw_dtcs)
                            dtc_status_mask_used = mask
                            mask_errors = []
                            break
                        except NegativeResponseException as exc:
                            raw = exc.response.original_payload
                            candidate_raw.append(raw.hex().upper())
                            dtc_request_hex = f"1902{mask:02X}"
                            dtc_response_hex = raw.hex().upper()
                            mask_errors.append(
                                f"masque 0x{mask:02X}: NRC 0x{exc.response.code:02X} {exc.response.code_name}"
                            )
                        except (TimeoutException, TimeoutError, ValueError) as exc:
                            dtc_request_hex = f"1902{mask:02X}"
                            dtc_response_hex = None
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
        dtc_request_hex=dtc_request_hex,
        dtc_response_hex=dtc_response_hex,
        dtc_error=dtc_error,
        active_session=active_session,
        active_session_source=active_session_source,
        probe_method=probe_method,
        probe_response_hex=probe_response_hex,
        probe_attempts=probe_attempts,
        raw_responses=raw_responses,
        error="; ".join(transport_errors) or (
            "Aucune adresse candidate documentée n'a répondu."
            if not detected and addresses else None
        ),
    )
    return result


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
    transport = build_transport(_trace_sink(trace), safety_profile="psa_lab")
    trace.write({
        "type": "dtc_clear_start",
        "ecu": ecu_key,
        "request_id": ecu.request_id,
        "response_id": ecu.response_id,
        "preconditions": request.model_dump(exclude={"confirmation"}),
        "request_hex": "14FFFFFF",
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
            masks = ecu.dtc_status_masks or [0xFF, 0x09]
            before_dtcs, before_availability, before_mask, before_response = _read_dtc_snapshot(
                uds_session,
                kb,
                ecu,
                masks,
            )
            trace.write({
                "type": "dtc_clear_before",
                "ecu": ecu_key,
                "request_hex": f"1902{before_mask:02X}",
                "response_hex": before_response,
                "availability_mask": before_availability,
                "dtcs": [item.model_dump() for item in before_dtcs],
            })
            response = clear_diagnostic_information(uds_session)
            response_hex = response.original_payload.hex().upper()
            trace.write({
                "type": "dtc_clear_acknowledged",
                "ecu": ecu_key,
                "request_hex": "14FFFFFF",
                "response_hex": response_hex,
            })

            after_dtcs: list[DtcReadResult] = []
            verification_error: str | None = None
            try:
                after_dtcs, after_availability, after_mask, after_response = _read_dtc_snapshot(
                    uds_session,
                    kb,
                    ecu,
                    masks,
                )
                trace.write({
                    "type": "dtc_clear_after",
                    "ecu": ecu_key,
                    "request_hex": f"1902{after_mask:02X}",
                    "response_hex": after_response,
                    "availability_mask": after_availability,
                    "dtcs": [item.model_dump() for item in after_dtcs],
                })
            except ValueError as exc:
                verification_error = str(exc)
                trace.write({
                    "type": "dtc_clear_verification_error",
                    "ecu": ecu_key,
                    "error": verification_error,
                })

        before_keys = {(item.raw_hex, item.code) for item in before_dtcs}
        persistent_dtcs = [
            item for item in after_dtcs
            if (item.raw_hex, item.code) in before_keys and item.state in {"active", "historical"}
        ]
        verified = verification_error is None and not persistent_dtcs
        if verification_error:
            message = "Effacement accepté par l'ECU, mais la relecture de contrôle a échoué."
        elif persistent_dtcs:
            message = (
                "Effacement accepté, mais certains défauts actifs ou historiques sont revenus "
                "immédiatement."
            )
        else:
            message = "Effacement accepté et contrôlé par une relecture DTC du même calculateur."
        result = ClearDtcResult(
            ecu_key=ecu_key,
            cleared=True,
            response_hex=response_hex,
            before_dtcs=before_dtcs,
            after_dtcs=after_dtcs,
            persistent_dtcs=persistent_dtcs,
            verified=verified,
            verification_error=verification_error,
            message=message,
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
