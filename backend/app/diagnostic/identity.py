from __future__ import annotations

import re

from app.config import settings
from app.database import KnowledgeBase
from app.diagnostic.isotp import UdsSession
from app.diagnostic.history import save_identity
from app.diagnostic.uds import read_data_by_identifier
from app.learn.capture import capture_manager
from app.models import (
    DebugSummary,
    VehicleIdentityAttempt,
    VehicleIdentityField,
    VehicleIdentityResult,
)
from app.session import SessionWriter
from app.transports.factory import build_transport


VIN_PATTERN = re.compile(rb"[A-HJ-NPR-Z0-9]{17}")
WMI_MANUFACTURERS = {
    "VF3": "Peugeot",
    "VR3": "Peugeot",
    "VF7": "Citroën",
    "ZFA": "Fiat",
    "ZFB": "Fiat",
    "3C3": "Fiat",
}


def _integer(value: int | str) -> int:
    return int(str(value), 0)


def validate_vin(value: str) -> bool:
    normalized = value.strip().upper()
    try:
        encoded = normalized.encode("ascii")
    except UnicodeEncodeError:
        return False
    return len(normalized) == 17 and bool(VIN_PATTERN.fullmatch(encoded))


def decode_vin_payload(payload: bytes) -> str:
    match = VIN_PATTERN.search(payload.upper())
    if match is None:
        printable = payload.decode("ascii", errors="replace").strip("\x00 ")
        raise ValueError(
            f"Aucun VIN valide de 17 caractères dans la réponse ({printable or payload.hex().upper()})."
        )
    return match.group().decode("ascii")


def decode_obd_vin(response: bytes) -> str:
    if not response.startswith(b"\x49\x02"):
        raise ValueError(f"Réponse Mode 09 PID 02 inattendue : {response.hex().upper()}")
    return decode_vin_payload(response[2:])


def manufacturer_from_vin(vin: str) -> str | None:
    return WMI_MANUFACTURERS.get(vin[:3].upper()) if validate_vin(vin) else None


def _decode_obd_field(response: bytes, pid: int, codec: str) -> str:
    expected = bytes([0x49, pid])
    if not response.startswith(expected):
        raise ValueError(
            f"Réponse Mode 09 PID 0x{pid:02X} inattendue : {response.hex().upper()}"
        )
    data = response[2:]
    if codec.startswith("indexed_") and data and data[0] <= 0x20:
        data = data[1:]
    if codec.endswith("ascii"):
        value = data.decode("ascii", errors="replace").strip("\x00 ")
        if not value:
            raise ValueError("Champ ASCII vide.")
        return value
    return data.hex().upper()


def _trace_sink(session: SessionWriter):
    def sink(event: dict) -> None:
        if event.get("type") == "can_frame" and not settings.trace_can_frames:
            return
        session.write(event)

    return sink


def _profile(profile_key: str) -> dict:
    kb = KnowledgeBase()
    available = {item["key"] for item in kb.vehicle_profiles()}
    if profile_key not in available:
        raise KeyError(f"Profil véhicule inconnu : {profile_key}.")
    return kb.vehicle(profile_key)


def _read_vin_attempt(transport, strategy: dict) -> VehicleIdentityAttempt:
    protocol = str(strategy.get("protocol", "")).lower()
    if protocol not in {"uds", "obd"}:
        raise ValueError(f"Protocole d'identification non pris en charge : {protocol}.")
    request_id = _integer(strategy["request_id"])
    response_id = _integer(strategy["response_id"])
    if not (0 <= request_id <= 0x7FF and 0 <= response_id <= 0x7FF):
        raise ValueError("Le profil VIN doit utiliser des identifiants CAN 11 bits documentés.")

    if protocol == "uds":
        did = _integer(strategy.get("did", 0xF190))
        command = b"\x22" + did.to_bytes(2, "big")
    else:
        command_value = _integer(strategy.get("command", 0x0902))
        command = command_value.to_bytes(2, "big")
        if command != b"\x09\x02":
            raise ValueError("Une stratégie VIN OBD doit être limitée au Mode 09 PID 02.")

    attempt = VehicleIdentityAttempt(
        key=str(strategy.get("key", f"{protocol}_{request_id:X}")),
        label=str(strategy.get("label", "Lecture VIN")),
        protocol=protocol,
        request_id=request_id,
        response_id=response_id,
        command_hex=command.hex().upper(),
        source=strategy.get("source"),
        confidence=str(strategy.get("confidence", "experimental")),
    )
    try:
        with UdsSession(
            transport,
            request_id,
            response_id,
            timeout=settings.diagnostic_timeout,
            read_only=True,
        ) as session:
            if protocol == "obd":
                response = session.request_obd(command)
                vin = decode_obd_vin(response)
            else:
                did = int.from_bytes(command[1:], "big")
                response_object, value_payload = read_data_by_identifier(session, did)
                response = response_object.original_payload
                vin = decode_vin_payload(value_payload)
        attempt.success = True
        attempt.vin = vin
        attempt.raw_hex = response.hex().upper()
    except Exception as exc:
        raw = getattr(getattr(exc, "response", None), "original_payload", None)
        attempt.raw_hex = raw.hex().upper() if isinstance(raw, bytes) else None
        attempt.error = str(exc)
    return attempt


def _read_identity_field(transport, definition: dict) -> VehicleIdentityField:
    protocol = str(definition.get("protocol", "")).lower()
    if protocol not in {"uds", "obd"}:
        raise ValueError(f"Protocole de champ d'identité non pris en charge : {protocol}.")
    request_id = _integer(definition["request_id"])
    response_id = _integer(definition["response_id"])
    if protocol == "uds":
        did = _integer(definition["did"])
        command = b"\x22" + did.to_bytes(2, "big")
    else:
        pid = _integer(definition["pid"])
        command = bytes([0x09, pid])

    field = VehicleIdentityField(
        key=str(definition["key"]),
        name=str(definition["name"]),
        protocol=protocol,
        command_hex=command.hex().upper(),
        source=definition.get("source"),
        confidence=str(definition.get("confidence", "experimental")),
    )
    try:
        with UdsSession(
            transport,
            request_id,
            response_id,
            timeout=settings.diagnostic_timeout,
            read_only=True,
        ) as session:
            if protocol == "obd":
                response = session.request_obd(command)
                field.value = _decode_obd_field(
                    response,
                    command[1],
                    str(definition.get("codec", "bytes")),
                )
                field.raw_hex = response.hex().upper()
            else:
                _, value_payload = read_data_by_identifier(session, int.from_bytes(command[1:], "big"))
                codec = str(definition.get("codec", "bytes"))
                field.value = (
                    value_payload.decode("ascii", errors="replace").strip("\x00 ")
                    if codec == "ascii"
                    else value_payload.hex().upper()
                )
                field.raw_hex = value_payload.hex().upper()
    except Exception as exc:
        raw = getattr(getattr(exc, "response", None), "original_payload", None)
        field.raw_hex = raw.hex().upper() if isinstance(raw, bytes) else None
        field.error = str(exc)
    return field


def read_vehicle_identity(profile_key: str) -> VehicleIdentityResult:
    if settings.transport != "virtual" and not settings.can_tx_enabled:
        raise PermissionError(
            "La lecture d'identité émet uniquement des requêtes OBD/UDS de lecture, "
            "mais nécessite CAN_TX_ENABLED=true."
        )
    if capture_manager.status().active:
        raise PermissionError("Arrête et sauvegarde la capture avant de lire l'identité du véhicule.")

    vehicle = _profile(profile_key)
    diagnostic = vehicle.get("diagnostic", {})
    strategies = diagnostic.get("vin_strategies", [])
    if not strategies:
        raise ValueError(f"Aucune stratégie VIN documentée pour {profile_key}.")

    trace = SessionWriter()
    transport = build_transport(_trace_sink(trace))
    result = VehicleIdentityResult(
        vehicle_profile=profile_key,
        manufacturer=str(vehicle.get("manufacturer", "Inconnu")),
        model=str(vehicle.get("model", "Inconnu")),
        year=vehicle.get("year"),
        transport=transport.name,
    )
    trace.write({
        "type": "vehicle_identity_start",
        "vehicle_profile": profile_key,
        "strategies": [strategy.get("key") for strategy in strategies],
    })
    opened = False
    try:
        transport.open()
        opened = True
        for strategy in strategies:
            attempt = _read_vin_attempt(transport, strategy)
            result.attempts.append(attempt)
            trace.write({"type": "vehicle_identity_attempt", "payload": attempt.model_dump()})
            if attempt.success and attempt.vin:
                result.found = True
                result.vin = attempt.vin
                break

        for definition in diagnostic.get("identity_fields", []):
            field = _read_identity_field(transport, definition)
            result.fields.append(field)
            trace.write({"type": "vehicle_identity_field", "payload": field.model_dump()})

        if result.vin:
            result.wmi = result.vin[:3]
            result.detected_manufacturer = manufacturer_from_vin(result.vin)
            if result.detected_manufacturer:
                result.profile_match = (
                    result.detected_manufacturer.casefold() == result.manufacturer.casefold()
                )
                if not result.profile_match:
                    result.warnings.append(
                        f"Le WMI {result.wmi} indique {result.detected_manufacturer}, "
                        f"mais le profil sélectionné est {result.manufacturer}."
                    )
        else:
            result.warnings.append(
                "Aucune méthode n'a retourné un VIN valide. Vérifier le contact, le réseau CAN "
                "et l'année exacte du véhicule avant d'ajouter d'autres adresses."
            )
        if diagnostic.get("identity_scope") == "identity_only":
            result.warnings.append(
                "Ce profil est limité à l'identification : le scan complet des ECU et les DTC "
                "constructeur ne sont pas encore déclarés compatibles."
            )
        trace.write({"type": "vehicle_identity_result", "payload": result.model_dump()})
    except Exception as exc:
        trace.write({
            "type": "vehicle_identity_error",
            "error_type": type(exc).__name__,
            "error": str(exc),
        })
        raise
    finally:
        if opened:
            transport.close()
        result.debug = DebugSummary(**trace.finish())
    save_identity(result)
    return result
