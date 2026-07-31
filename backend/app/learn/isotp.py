from dataclasses import dataclass


@dataclass
class IsoTpPayload:
    kind: str
    payload: bytes
    complete: bool
    total_length: int | None = None


def parse_isotp_frame(data: bytes) -> IsoTpPayload | None:
    if not data:
        return None

    pci = data[0] >> 4

    if pci == 0x0:
        length = data[0] & 0x0F
        if length == 0 or length > 7:
            return None
        return IsoTpPayload("single", data[1:1 + length], True, length)

    if pci == 0x1 and len(data) >= 2:
        total = ((data[0] & 0x0F) << 8) | data[1]
        return IsoTpPayload("first", data[2:], False, total)

    if pci == 0x2:
        return IsoTpPayload("consecutive", data[1:], False, None)

    if pci == 0x3:
        return IsoTpPayload("flow_control", data[1:], True, None)

    return None


def uds_service(payload: bytes) -> int | None:
    if not payload:
        return None
    service = payload[0]
    # Services UDS et réponses positives/négatives usuelles
    if service == 0x7F or 0x10 <= service <= 0x3E or 0x50 <= service <= 0x7E:
        return service
    return None


def is_positive_response(request_service: int, response_payload: bytes) -> bool:
    return bool(response_payload) and response_payload[0] == ((request_service + 0x40) & 0xFF)


def is_negative_response(request_service: int, response_payload: bytes) -> bool:
    return (
        len(response_payload) >= 3
        and response_payload[0] == 0x7F
        and response_payload[1] == request_service
    )
