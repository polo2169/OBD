from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import json
import re
import uuid

from app.config import settings
from app.database import KnowledgeBase
from app.models import DiagnosticTraceImportRequest


_HEX = re.compile(r"^[0-9A-Fa-f]+$")
_HASH_FRAME = re.compile(
    r"(?:(?P<direction>TX|RX)\s+)?(?:0x)?(?P<id>[0-9A-Fa-f]{3,8})#(?P<data>[0-9A-Fa-f]+)",
    re.IGNORECASE,
)
_TEXT_FRAME = re.compile(
    r"(?P<direction>TX|RX)\s*[:;, ]+\s*(?:ID\s*[:=]\s*)?(?:0x)?"
    r"(?P<id>[0-9A-Fa-f]{3,8}).*?(?:DATA\s*[:=]\s*)?"
    r"(?P<data>(?:[0-9A-Fa-f]{2}[\s:,-]*){2,64})\s*$",
    re.IGNORECASE,
)
_REQUEST_SERVICES = {0x10, 0x11, 0x14, 0x19, 0x22, 0x27, 0x28, 0x2E, 0x2F, 0x31, 0x3E, 0x85}
_ACTIVE_SERVICES = {0x11, 0x14, 0x27, 0x28, 0x2E, 0x2F, 0x31, 0x85}
_SERVICE_NAMES = {
    0x10: "DiagnosticSessionControl",
    0x11: "ECUReset",
    0x14: "ClearDiagnosticInformation",
    0x19: "ReadDTCInformation",
    0x22: "ReadDataByIdentifier",
    0x27: "SecurityAccess",
    0x28: "CommunicationControl",
    0x2E: "WriteDataByIdentifier",
    0x2F: "InputOutputControlByIdentifier",
    0x31: "RoutineControl",
    0x3E: "TesterPresent",
    0x85: "ControlDTCSetting",
}


def _root() -> Path:
    path = settings.diagnostic_trace_import_dir
    if not path.is_absolute():
        path = (Path(__file__).resolve().parents[2] / path).resolve()
    path.mkdir(parents=True, exist_ok=True)
    return path


def _compact_hex(value: str) -> str | None:
    compact = re.sub(r"[^0-9A-Fa-f]", "", value)
    if not compact or len(compact) % 2 or not _HEX.fullmatch(compact):
        return None
    return compact.upper()


def _direction(value: object) -> str | None:
    normalized = str(value or "").strip().lower()
    if normalized in {"tx", "transmit", "sent", "request"}:
        return "tx"
    if normalized in {"rx", "receive", "received", "response"}:
        return "rx"
    return None


def _parse_json_frame(line: str, line_number: int) -> dict | None:
    try:
        payload = json.loads(line)
    except json.JSONDecodeError:
        return None
    if not isinstance(payload, dict):
        return None
    candidate = payload.get("payload") if isinstance(payload.get("payload"), dict) else payload
    arbitration_id = candidate.get("arbitration_id", candidate.get("can_id", candidate.get("id")))
    data = candidate.get("data_hex", candidate.get("data"))
    if arbitration_id is None or data is None:
        return None
    try:
        can_id = int(str(arbitration_id), 0) if not isinstance(arbitration_id, int) else arbitration_id
    except ValueError:
        try:
            can_id = int(str(arbitration_id), 16)
        except ValueError:
            return None
    data_hex = _compact_hex(str(data))
    if data_hex is None:
        return None
    return {
        "line": line_number,
        "arbitration_id": can_id,
        "direction": _direction(candidate.get("direction")),
        "data_hex": data_hex,
    }


def _parse_text_frame(line: str, line_number: int) -> dict | None:
    match = _HASH_FRAME.search(line) or _TEXT_FRAME.search(line)
    if match is None:
        return None
    data_hex = _compact_hex(match.group("data"))
    if data_hex is None:
        return None
    return {
        "line": line_number,
        "arbitration_id": int(match.group("id"), 16),
        "direction": _direction(match.groupdict().get("direction")),
        "data_hex": data_hex,
    }


def _frames(content: str, ecu_by_can_id: dict[int, tuple[str, str]]) -> tuple[list[dict], list[int]]:
    frames: list[dict] = []
    unparsed: list[int] = []
    for line_number, raw_line in enumerate(content.splitlines(), start=1):
        line = raw_line.strip()
        if not line or line.startswith(("#", "//")):
            continue
        frame = _parse_json_frame(line, line_number) or _parse_text_frame(line, line_number)
        if frame is None:
            unparsed.append(line_number)
            continue
        if frame["direction"] is None and frame["arbitration_id"] in ecu_by_can_id:
            frame["direction"] = ecu_by_can_id[frame["arbitration_id"]][1]
        frames.append(frame)
    return frames, unparsed


def _isotp_payloads(frames: list[dict]) -> tuple[list[dict], list[str]]:
    payloads: list[dict] = []
    assembling: dict[tuple[int, str | None], dict] = {}
    warnings: list[str] = []
    for frame in frames:
        data = bytes.fromhex(frame["data_hex"])
        if not data:
            continue
        key = (frame["arbitration_id"], frame["direction"])
        pci = data[0] >> 4
        if pci == 0:
            length = data[0] & 0x0F
            offset = 1
            if length == 0 and len(data) >= 2:
                length = data[1]
                offset = 2
            if not length or offset + length > len(data):
                warnings.append(f"Ligne {frame['line']}: Single Frame ISO-TP invalide.")
                continue
            payloads.append({**frame, "payload_hex": data[offset:offset + length].hex().upper()})
        elif pci == 1 and len(data) >= 2:
            total = ((data[0] & 0x0F) << 8) | data[1]
            assembling[key] = {
                **frame,
                "total": total,
                "next_sequence": 1,
                "buffer": bytearray(data[2:]),
            }
        elif pci == 2 and key in assembling:
            state = assembling[key]
            sequence = data[0] & 0x0F
            if sequence != state["next_sequence"]:
                warnings.append(
                    f"Ligne {frame['line']}: séquence ISO-TP {sequence}, "
                    f"attendu {state['next_sequence']} sur 0x{frame['arbitration_id']:X}."
                )
                del assembling[key]
                continue
            state["next_sequence"] = (sequence + 1) & 0x0F
            state["buffer"].extend(data[1:])
            if len(state["buffer"]) >= state["total"]:
                payloads.append({
                    "line": state["line"],
                    "end_line": frame["line"],
                    "arbitration_id": state["arbitration_id"],
                    "direction": state["direction"],
                    "data_hex": state["data_hex"],
                    "payload_hex": bytes(state["buffer"][:state["total"]]).hex().upper(),
                })
                del assembling[key]
        elif pci == 3:
            continue
        elif data[0] in _REQUEST_SERVICES or data[0] == 0x7F or data[0] - 0x40 in _REQUEST_SERVICES:
            # Certains exports Diagbox contiennent le payload UDS sans en-tête ISO-TP.
            payloads.append({**frame, "payload_hex": data.hex().upper()})
        else:
            warnings.append(f"Ligne {frame['line']}: trame non reconnue sur 0x{frame['arbitration_id']:X}.")
    for state in assembling.values():
        warnings.append(
            f"Ligne {state['line']}: réponse ISO-TP incomplète sur 0x{state['arbitration_id']:X}."
        )
    return payloads, warnings


def _response_service(payload: bytes) -> int | None:
    if len(payload) >= 3 and payload[0] == 0x7F:
        return payload[1]
    candidate = payload[0] - 0x40 if payload and payload[0] >= 0x40 else -1
    return candidate if candidate in _REQUEST_SERVICES else None


def _pair_exchanges(payloads: list[dict], ecu_by_can_id: dict[int, tuple[str, str]]) -> list[dict]:
    pending: list[dict] = []
    exchanges: list[dict] = []
    for record in payloads:
        payload = bytes.fromhex(record["payload_hex"])
        if not payload:
            continue
        can_role = ecu_by_can_id.get(record["arbitration_id"])
        direction = record["direction"] or (can_role[1] if can_role else None)
        is_request = payload[0] in _REQUEST_SERVICES and direction != "rx"
        if is_request:
            pending.append({**record, "direction": "tx" if direction is None else direction})
            continue
        service = _response_service(payload)
        if service is None:
            continue
        ecu_key = can_role[0] if can_role else None
        selected_index = None
        for index in range(len(pending) - 1, -1, -1):
            request = bytes.fromhex(pending[index]["payload_hex"])
            request_role = ecu_by_can_id.get(pending[index]["arbitration_id"])
            if request[0] == service and (ecu_key is None or request_role is None or request_role[0] == ecu_key):
                selected_index = index
                break
        if selected_index is None:
            continue
        request = pending.pop(selected_index)
        request_payload = bytes.fromhex(request["payload_hex"])
        negative = payload[0] == 0x7F
        exchange = {
            "ecu_key": ecu_key or (ecu_by_can_id.get(request["arbitration_id"]) or (None,))[0],
            "tx_id": request["arbitration_id"],
            "rx_id": record["arbitration_id"],
            "request_hex": request["payload_hex"],
            "response_hex": record["payload_hex"],
            "request_line": request["line"],
            "response_line": record["line"],
            "service": service,
            "service_name": _SERVICE_NAMES.get(service, f"Service 0x{service:02X}"),
            "status": "negative_response" if negative else "positive",
            "nrc": payload[2] if negative and len(payload) >= 3 else None,
        }
        if service in {0x22, 0x2E, 0x2F} and len(request_payload) >= 3:
            exchange["identifier"] = int.from_bytes(request_payload[1:3], "big")
        if service == 0x31 and len(request_payload) >= 4:
            exchange["routine_control_type"] = request_payload[1]
            exchange["identifier"] = int.from_bytes(request_payload[2:4], "big")
        exchanges.append(exchange)

    for request in pending:
        payload = bytes.fromhex(request["payload_hex"])
        can_role = ecu_by_can_id.get(request["arbitration_id"])
        exchange = {
            "ecu_key": can_role[0] if can_role else None,
            "tx_id": request["arbitration_id"],
            "rx_id": None,
            "request_hex": request["payload_hex"],
            "response_hex": None,
            "request_line": request["line"],
            "response_line": None,
            "service": payload[0],
            "service_name": _SERVICE_NAMES.get(payload[0], f"Service 0x{payload[0]:02X}"),
            "status": "unanswered",
            "nrc": None,
        }
        if payload[0] in {0x22, 0x2E, 0x2F} and len(payload) >= 3:
            exchange["identifier"] = int.from_bytes(payload[1:3], "big")
        exchanges.append(exchange)
    return sorted(exchanges, key=lambda item: item["request_line"])


def _observations(exchanges: list[dict]) -> tuple[list[dict], list[dict]]:
    dids: list[dict] = []
    actions: list[dict] = []
    for exchange in exchanges:
        service = exchange["service"]
        if service == 0x22 and exchange["status"] == "positive" and exchange.get("identifier") is not None:
            response = bytes.fromhex(exchange["response_hex"])
            dids.append({
                "ecu_key": exchange.get("ecu_key"),
                "did": exchange["identifier"],
                "value_hex": response[3:].hex().upper() if len(response) >= 3 else "",
                "request_line": exchange["request_line"],
                "response_line": exchange["response_line"],
                "confidence": "observed_trace",
            })
        if service in _ACTIVE_SERVICES:
            actions.append({
                "ecu_key": exchange.get("ecu_key"),
                "service": service,
                "service_name": exchange["service_name"],
                "identifier": exchange.get("identifier"),
                "request_hex": exchange["request_hex"],
                "response_hex": exchange["response_hex"],
                "status": exchange["status"],
                "review_required": True,
                "executable": False,
            })
    return dids, actions


def import_diagnostic_trace(request: DiagnosticTraceImportRequest) -> dict:
    knowledge = KnowledgeBase()
    ecus = knowledge.ecus(request.vehicle_profile)
    ecu_by_can_id: dict[int, tuple[str, str]] = {}
    for ecu in ecus:
        if ecu.request_id is not None:
            ecu_by_can_id[ecu.request_id] = (ecu.key, "tx")
        if ecu.response_id is not None:
            ecu_by_can_id[ecu.response_id] = (ecu.key, "rx")

    frames, unparsed_lines = _frames(request.content, ecu_by_can_id)
    if not frames:
        raise ValueError("Aucune trame CAN exploitable trouvée dans cette trace.")
    payloads, warnings = _isotp_payloads(frames)
    exchanges = _pair_exchanges(payloads, ecu_by_can_id)
    dids, actions = _observations(exchanges)
    if unparsed_lines:
        preview = ", ".join(str(item) for item in unparsed_lines[:10])
        warnings.append(
            f"{len(unparsed_lines)} ligne(s) non interprétée(s) (premières : {preview})."
        )
    if actions:
        warnings.append(
            "Les services actifs observés sont archivés pour analyse uniquement ; aucun n'est exécutable."
        )

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    import_id = f"diagbox-{stamp}-{uuid.uuid4().hex[:8]}"
    safe_name = re.sub(r"[^A-Za-z0-9._-]+", "-", request.name).strip("-.") or "trace"
    result = {
        "import_id": import_id,
        "name": safe_name,
        "vehicle_profile": request.vehicle_profile,
        "source_format": request.source_format,
        "imported_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "frame_count": len(frames),
        "payload_count": len(payloads),
        "exchange_count": len(exchanges),
        "unparsed_line_count": len(unparsed_lines),
        "exchanges": exchanges,
        "observed_dids": dids,
        "observed_actions": actions,
        "warnings": warnings,
    }
    destination = _root() / f"{import_id}-{safe_name}.json"
    destination.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    result["saved_file"] = str(destination.resolve())
    return result
