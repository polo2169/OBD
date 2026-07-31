from dataclasses import dataclass

from udsoncan import Request, Response
from udsoncan.services import ReadDataByIdentifier

from app.diagnostic.isotp import UdsSession
from app.transports.base import Transport


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
