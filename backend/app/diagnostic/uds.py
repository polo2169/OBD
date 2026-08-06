from dataclasses import dataclass

from udsoncan import Request, Response
from udsoncan.exceptions import NegativeResponseException, TimeoutException
from udsoncan.services import ReadDataByIdentifier

from app.diagnostic.isotp import UdsSession
from app.transports.base import Transport


def enter_extended_session(session: UdsSession) -> None:
    """Best-effort DiagnosticSessionControl to the extended session (0x03).

    Many PSA ECUs hide manufacturer-specific DIDs (e.g. telecoding zones)
    behind this session even for reads. Still gated by authorize_uds, which
    only allowlists sessions 0x01/0x03 — SecurityAccess (0x27) stays blocked
    regardless of session. Failure here is non-fatal: the caller just falls
    back to whatever the default session already exposes.
    """
    try:
        session.request(bytes([0x10, 0x03]))
    except (NegativeResponseException, TimeoutException, TimeoutError, PermissionError):
        pass


DTC_STATUS_LABELS = {
    0x01: "test_failed",
    0x02: "test_failed_this_operation_cycle",
    0x04: "pending",
    0x08: "confirmed",
    0x10: "test_not_completed_since_last_clear",
    0x20: "test_failed_since_last_clear",
    0x40: "test_not_completed_this_operation_cycle",
    0x80: "warning_indicator_requested",
}


@dataclass(frozen=True)
class RawDtc:
    code: str
    raw_hex: str
    failure_type: int
    status: int
    status_labels: list[str]


def format_sae_dtc(first: int, second: int) -> str:
    domain = "PCBU"[(first >> 6) & 0x03]
    return f"{domain}{(first >> 4) & 0x03:X}{first & 0x0F:X}{second:02X}"


def decode_dtc_status(status: int) -> list[str]:
    return [label for bit, label in DTC_STATUS_LABELS.items() if status & bit]


def read_dtcs_by_status_mask(
    session: UdsSession,
    status_mask: int = 0xFF,
) -> tuple[Response, int, list[RawDtc]]:
    if not 0 <= status_mask <= 0xFF:
        raise ValueError("Le masque d'état DTC doit tenir sur un octet.")
    response = session.send_request(Request.from_payload(bytes([0x19, 0x02, status_mask])))
    payload = response.original_payload
    if len(payload) < 3 or payload[:2] != b"\x59\x02":
        raise ValueError("Réponse inattendue à ReadDTCInformation 0x19/0x02.")
    records = payload[3:]
    if len(records) % 4:
        raise ValueError(
            f"Réponse DTC tronquée : {len(records)} octets après l'en-tête, multiple de 4 attendu."
        )

    dtcs: list[RawDtc] = []
    for offset in range(0, len(records), 4):
        first, second, failure_type, status = records[offset:offset + 4]
        dtcs.append(RawDtc(
            code=format_sae_dtc(first, second),
            raw_hex=bytes([first, second, failure_type]).hex().upper(),
            failure_type=failure_type,
            status=status,
            status_labels=decode_dtc_status(status),
        ))
    return response, payload[2], dtcs


def read_dtc_snapshot(
    session: UdsSession,
    dtc_raw_hex: str,
    record_number: int = 0xFF,
) -> tuple[Response, int | None, int | None, int | None, bytes]:
    """ReadDTCInformation 0x19/0x04 (reportDTCSnapshotRecordByDTCNumber).

    The snapshot payload packs a variable number of data identifiers whose
    individual lengths aren't self-describing in the UDS spec and aren't
    documented anywhere for PSA ECUs, so the identifier count is reported
    but the data itself is returned raw rather than guessed at.
    """
    dtc_bytes = bytes.fromhex(dtc_raw_hex)
    if len(dtc_bytes) != 3:
        raise ValueError("Le DTC doit tenir sur 3 octets (raw_hex d'un DtcReadResult).")
    if not 0 <= record_number <= 0xFF:
        raise ValueError("Le numéro d'enregistrement doit tenir sur un octet.")
    response = session.send_request(
        Request.from_payload(bytes([0x19, 0x04]) + dtc_bytes + bytes([record_number]))
    )
    payload = response.original_payload
    if len(payload) < 5 or payload[:2] != b"\x59\x04":
        raise ValueError("Réponse inattendue à ReadDTCInformation 0x19/0x04.")
    if payload[2:5] != dtc_bytes:
        raise ValueError("Le DTC retourné ne correspond pas à la demande.")
    status = payload[5] if len(payload) > 5 else None
    remainder = payload[6:]
    snapshot_record_number = remainder[0] if remainder else None
    identifier_count = remainder[1] if len(remainder) > 1 else None
    raw_data = remainder[2:]
    return response, status, snapshot_record_number, identifier_count, raw_data


def read_obd_dtcs(session: UdsSession, mode: int = 0x03) -> list[RawDtc]:
    """Generic EOBD DTC read (Mode 03 stored / Mode 07 pending).

    Unlike the PSA-style UDS 0x19 read, classic OBD Modes 03/07 carry no
    per-DTC status byte or failure type: only the presence of a code. The
    two-byte SAE J2012 encoding is shared with UDS 0x19, so format_sae_dtc
    applies unchanged. Uses request_obd (raw ISO-TP), not the udsoncan
    Request/Response wrapper: that library only models ISO 14229 services,
    not legacy SAE J1979 OBD modes such as 0x03/0x07.
    """
    if mode not in (0x03, 0x07):
        raise ValueError("Le mode OBD doit être 0x03 (mémorisés) ou 0x07 (en attente).")
    payload = session.request_obd(bytes([mode]))
    expected_service = mode + 0x40
    if len(payload) < 1 or payload[0] != expected_service:
        raise ValueError(f"Réponse inattendue au mode OBD 0x{mode:02X}.")
    records = payload[1:]
    if len(records) % 2:
        raise ValueError(f"Réponse DTC OBD 0x{mode:02X} tronquée : nombre d'octets impair.")

    dtcs: list[RawDtc] = []
    for offset in range(0, len(records), 2):
        first, second = records[offset:offset + 2]
        if first == 0 and second == 0:
            continue
        dtcs.append(RawDtc(
            code=format_sae_dtc(first, second),
            raw_hex=bytes([first, second]).hex().upper(),
            failure_type=0,
            status=0,
            status_labels=[],
        ))
    return dtcs


def clear_diagnostic_information(session: UdsSession, group: int = 0xFFFFFF) -> Response:
    if not 0 <= group <= 0xFFFFFF:
        raise ValueError("Le groupe DTC doit tenir sur trois octets.")
    request = Request.from_payload(b"\x14" + group.to_bytes(3, "big"))
    response = session.send_request(request)
    if response.original_payload != b"\x54":
        raise ValueError("Réponse inattendue à ClearDiagnosticInformation 0x14.")
    return response


def read_data_by_identifier(session: UdsSession, did: int) -> tuple[Response, bytes]:
    request = ReadDataByIdentifier.make_request(did, didconfig=None)
    response = session.send_request(request)
    prefix = b"\x62" + did.to_bytes(2, "big")
    if not response.original_payload.startswith(prefix):
        raise ValueError(f"Réponse inattendue pour le DID 0x{did:04X}.")
    return response, response.original_payload[len(prefix):]


def request(
    transport: Transport,
    request_id: int,
    response_id: int,
    uds_payload: bytes,
    timeout: float = 1.0,
    read_only: bool = True,
) -> bytes:
    """Compatibility helper for one UDS request on an already opened transport."""

    with UdsSession(
        transport,
        request_id,
        response_id,
        timeout=timeout,
        read_only=read_only,
    ) as session:
        return session.request(uds_payload)
