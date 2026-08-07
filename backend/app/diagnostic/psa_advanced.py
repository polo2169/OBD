from __future__ import annotations

from dataclasses import dataclass
import time

from udsoncan.exceptions import NegativeResponseException, TimeoutException

from app.config import settings
from app.database import KnowledgeBase
from app.diagnostic.isotp import UdsSession
from app.diagnostic.uds import (
    ecu_reset,
    enter_extended_session,
    read_data_by_identifier,
    write_data_by_identifier,
)
from app.learn.capture import capture_manager
from app.models import (
    DidReadResult,
    EcuResetRequest,
    EcuResetResult,
    PsaActionRequest,
    PsaActionResult,
    PsaSeedKeyResult,
    PsaUnlockRequest,
    PsaUnlockResult,
    TelecodingParameterValue,
    TelecodingWriteRequest,
    TelecodingWriteResult,
    TelecodingZoneInfo,
)
from app.safety import authorize_psa_lab_uds
from app.session import SessionWriter
from app.transports.factory import build_transport


PSA_DIAG_SOURCE = "https://github.com/ludwig-v/arduino-psa-diag"
PSA_SEEDKEY_SOURCE = "https://github.com/ludwig-v/psa-seedkey-algorithm"
PSA_NAC_SOURCE = "https://github.com/dragouf/PSA-Arduino-NAC-RCC/blob/master/protocol.md"


SECURITY_KEY_CANDIDATES: dict[str, list[dict[str, str]]] = {
    "bsi": [
        {"variant": "BSI_2010", "key_hex": "E4D8"},
        {"variant": "BSI_2010_EV", "key_hex": "B4E0"},
    ],
    "telematics": [
        {"variant": "NAC", "key_hex": "D91C"},
        {"variant": "RCC", "key_hex": "F107"},
    ],
    "instrument_cluster": [
        {"variant": "CIROCCO", "key_hex": "FAFA"},
        {"variant": "MATT", "key_hex": "ECEC"},
    ],
    "abs_esp": [{"variant": "ESP81", "key_hex": "ABFB"}],
    "power_steering": [{"variant": "GEP", "key_hex": "4628"}],
    "gearbox": [
        {"variant": "EAT8", "key_hex": "4854"},
        {"variant": "AT6", "key_hex": "8086"},
    ],
    "parking_assistance": [{"variant": "AAS_UDS", "key_hex": "EFCA"}],
}


@dataclass(frozen=True)
class PsaActionDefinition:
    key: str
    ecu_key: str
    name: str
    description: str
    start_payload: bytes | None
    stop_payload: bytes | None = None
    timed: bool = False
    confidence: str = "documented_community"
    source: str = PSA_NAC_SOURCE
    unavailable_reason: str | None = None
    validation_status: str = "source_confirmed_not_vehicle_tested"
    requires_detected_ecu: bool = True
    vehicle_confirmed: bool = False

    def as_catalog(self) -> dict:
        return {
            "key": self.key,
            "ecu_key": self.ecu_key,
            "name": self.name,
            "description": self.description,
            "available": self.start_payload is not None,
            "timed": self.timed,
            "start_payload_hex": self.start_payload.hex().upper() if self.start_payload else None,
            "stop_payload_hex": self.stop_payload.hex().upper() if self.stop_payload else None,
            "confirmation": f"ACTIVER {self.key.upper()}" if self.start_payload else None,
            "confidence": self.confidence,
            "source": self.source,
            "unavailable_reason": self.unavailable_reason,
            "validation_status": self.validation_status,
            "requires_detected_ecu": self.requires_detected_ecu,
            "vehicle_confirmed": self.vehicle_confirmed,
        }


PSA_ACTIONS: dict[str, PsaActionDefinition] = {
    action.key: action
    for action in (
        PsaActionDefinition(
            key="nac_black_screen",
            ecu_key="telematics",
            name="Écran NAC noir",
            description="Force temporairement l'écran noir puis envoie systématiquement la restauration.",
            start_payload=bytes.fromhex("2FD6000300"),
            stop_payload=bytes.fromhex("2FD60000"),
            timed=True,
        ),
        PsaActionDefinition(
            key="nac_restore_screen",
            ecu_key="telematics",
            name="Restaurer l'écran NAC",
            description="Commande de retour immédiat à l'affichage normal.",
            start_payload=bytes.fromhex("2FD60000"),
        ),
        PsaActionDefinition(
            key="nac_camera",
            ecu_key="telematics",
            name="Afficher la caméra",
            description="Affiche temporairement la caméra puis envoie la commande d'arrêt.",
            start_payload=bytes.fromhex("2FD66003"),
            stop_payload=bytes.fromhex("2FD66000"),
            timed=True,
        ),
        PsaActionDefinition(
            key="nac_camera_standard",
            ecu_key="telematics",
            name="Caméra 180° · vue standard",
            description="Sélectionne temporairement la vue standard de la caméra 180°.",
            start_payload=bytes.fromhex("2FD6700330"),
            stop_payload=bytes.fromhex("2FD66000"),
            timed=True,
        ),
        PsaActionDefinition(
            key="nac_camera_zoom",
            ecu_key="telematics",
            name="Caméra 180° · zoom",
            description="Sélectionne temporairement la vue zoom de la caméra 180°.",
            start_payload=bytes.fromhex("2FD6700340"),
            stop_payload=bytes.fromhex("2FD66000"),
            timed=True,
        ),
        PsaActionDefinition(
            key="nac_camera_lateral",
            ecu_key="telematics",
            name="Caméra 180° · vue latérale",
            description="Sélectionne temporairement la vue latérale de la caméra 180°.",
            start_payload=bytes.fromhex("2FD6700350"),
            stop_payload=bytes.fromhex("2FD66000"),
            timed=True,
        ),
        PsaActionDefinition(
            key="bsi_turn_left",
            ecu_key="bsi",
            name="Clignotant gauche",
            description="Emplacement réservé au test actionneur BSI.",
            start_payload=None,
            confidence="unknown_command",
            unavailable_reason="DID et paramètres BSI non confirmés ; aucune trame ne sera inventée.",
            validation_status="not_documented",
        ),
        PsaActionDefinition(
            key="bsi_turn_right",
            ecu_key="bsi",
            name="Clignotant droit",
            description="Emplacement réservé au test actionneur BSI.",
            start_payload=None,
            confidence="unknown_command",
            unavailable_reason="DID et paramètres BSI non confirmés ; aucune trame ne sera inventée.",
            validation_status="not_documented",
        ),
        PsaActionDefinition(
            key="bsi_hazard",
            ecu_key="bsi",
            name="Feux de détresse",
            description="Emplacement réservé au test actionneur BSI.",
            start_payload=None,
            confidence="unknown_command",
            unavailable_reason="DID et paramètres BSI non confirmés ; aucune trame ne sera inventée.",
            validation_status="not_documented",
        ),
    )
}


def _trace_sink(session: SessionWriter):
    def sink(event: dict) -> None:
        if event.get("type") == "can_frame" and not settings.trace_can_frames:
            return
        session.write(event)

    return sink


def _require_advanced_read() -> None:
    if not settings.psa_advanced_enabled:
        raise PermissionError("Diagnostic PSA avancé verrouillé : PSA_ADVANCED_ENABLED=false.")
    if settings.transport != "virtual" and not settings.can_tx_enabled:
        raise PermissionError("Lecture PSA active impossible tant que CAN_TX_ENABLED=false.")


def _find_ecu(ecu_key: str):
    ecu = next((item for item in KnowledgeBase().ecus() if item.key == ecu_key), None)
    if ecu is None:
        raise KeyError(f"Calculateur inconnu : {ecu_key}.")
    if ecu.request_id is None or ecu.response_id is None:
        raise ValueError(f"Adresses non documentées pour {ecu.name}.")
    return ecu


def _require_lab_preconditions(
    ecu_key: str,
    confirmation: str,
    expected_confirmation: str,
    *,
    vehicle_stationary: bool,
    ignition_on_engine_off: bool,
    stable_battery_voltage: bool,
    workshop_or_private_site: bool,
) -> None:
    _require_advanced_read()
    if settings.read_only:
        raise PermissionError("Mode PSA lab impossible tant que READ_ONLY=true.")
    if confirmation.strip() != expected_confirmation:
        raise PermissionError(f"Confirmation exacte requise : {expected_confirmation}")
    missing = [
        label
        for checked, label in (
            (vehicle_stationary, "véhicule immobilisé"),
            (ignition_on_engine_off, "contact mis et moteur arrêté"),
            (stable_battery_voltage, "tension batterie stable"),
            (workshop_or_private_site, "atelier ou site privé"),
        )
        if not checked
    ]
    if missing:
        raise PermissionError("Préconditions non confirmées : " + ", ".join(missing) + ".")
    if capture_manager.status().active:
        raise PermissionError("Arrête et sauvegarde la capture avant une commande PSA lab active.")
    _find_ecu(ecu_key)


def advanced_catalog() -> dict:
    kb = KnowledgeBase()
    ecus = []
    for ecu in kb.ecus():
        zones = kb.telecoding_zones_for_family(ecu.family)
        ecus.append({
            "key": ecu.key,
            "name": ecu.name,
            "family": ecu.family,
            "request_id": ecu.request_id,
            "response_id": ecu.response_id,
            "protocol": ecu.protocol,
            "optional": ecu.optional,
            "security_keys": SECURITY_KEY_CANDIDATES.get(ecu.key, []),
            "telecoding_zones": [
                {"did": zone_id, "name": zone.get("name", zone_id)}
                for zone_id, zone in sorted(zones.items())
            ][:12],
        })
    return {
        "enabled": settings.psa_advanced_enabled,
        "security_access_enabled": settings.psa_security_access_enabled,
        "actuator_enabled": settings.psa_actuator_enabled,
        "ecu_reset_enabled": settings.psa_ecu_reset_enabled,
        "telecoding_write_enabled": settings.psa_telecoding_write_enabled,
        "read_only": settings.read_only,
        "can_tx_enabled": settings.can_tx_enabled,
        "required_firmware_policy": "psa_lab_named_actions",
        "wiring": {
            "vehicle_can": "AEE2004/AEE2010 : CAN diagnostic sur OBD 3/8",
            "standard_obd": "OBD-II moteur normalisé généralement sur 6/14 selon l'interface et le câblage utilisé",
            "source": "https://github.com/ludwig-v/arduino-psa-diag/blob/master/README.md#pinout",
            "warning": "Ne jamais ponter 3/8 et 6/14. Utiliser un sélecteur ou un second transceiver isolé.",
        },
        "ecus": ecus,
        "actions": [action.as_catalog() for action in PSA_ACTIONS.values()],
        "sources": [PSA_DIAG_SOURCE, PSA_SEEDKEY_SOURCE, PSA_NAC_SOURCE],
    }


def _to_int16(value: int) -> int:
    value &= 0xFFFF
    return value - 0x10000 if value & 0x8000 else value


def _trunc_div(dividend: int, divisor: int) -> int:
    quotient = abs(dividend) // abs(divisor)
    return -quotient if (dividend < 0) != (divisor < 0) else quotient


def _c_mod(dividend: int, divisor: int) -> int:
    return dividend - _trunc_div(dividend, divisor) * divisor


def _seed_transform(value: int, secret: tuple[int, int, int]) -> int:
    value = _to_int16(value)
    first, second, third = secret
    result = (_c_mod(value, first) * third) - (_trunc_div(value, first) * second)
    if result < 0:
        result += (first * third) + second
    return result & 0xFFFF


def compute_psa_seed_key(seed_hex: str, application_key_hex: str) -> str:
    seed = bytes.fromhex(seed_hex.strip())
    application_key = bytes.fromhex(application_key_hex.strip())
    if len(seed) != 4:
        raise ValueError("Le seed PSA doit contenir exactement 4 octets.")
    if len(application_key) != 2:
        raise ValueError("La clé application PSA doit contenir exactement 2 octets.")
    secret_one = (0xB2, 0x3F, 0xAA)
    secret_two = (0xB1, 0x02, 0xAB)
    result_msb = _seed_transform(int.from_bytes(application_key, "big"), secret_one) | _seed_transform(
        (seed[0] << 8) | seed[3], secret_two
    )
    result_lsb = _seed_transform((seed[1] << 8) | seed[2], secret_one) | _seed_transform(
        result_msb, secret_two
    )
    return f"{((result_msb << 16) | result_lsb):08X}"


def calculate_seed_key(seed_hex: str, application_key_hex: str) -> PsaSeedKeyResult:
    normalized_seed = seed_hex.strip().upper()
    normalized_key = application_key_hex.strip().upper()
    return PsaSeedKeyResult(
        seed_hex=normalized_seed,
        application_key_hex=normalized_key,
        response_key_hex=compute_psa_seed_key(normalized_seed, normalized_key),
        source=PSA_SEEDKEY_SOURCE,
        transmitted=False,
    )


def read_raw_did(ecu_key: str, did: int) -> DidReadResult:
    _require_advanced_read()
    if not 0 <= did <= 0xFFFF:
        raise ValueError("Le DID doit tenir sur deux octets.")
    ecu = _find_ecu(ecu_key)
    kb = KnowledgeBase()
    trace = SessionWriter() if settings.debug_sessions_enabled else None
    transport = build_transport(_trace_sink(trace) if trace else None)
    opened = False
    try:
        transport.open()
        opened = True
        with UdsSession(
            transport,
            ecu.request_id,
            ecu.response_id,
            timeout=settings.diagnostic_timeout,
            read_only=True,
        ) as session:
            enter_extended_session(session)
            response, value = read_data_by_identifier(session, did)
        printable = value.decode("ascii", errors="replace").strip("\x00 ")
        mostly_printable = bool(printable) and sum(character.isprintable() for character in printable) / len(printable) > 0.85
        telecoding = None
        zone = kb.describe_telecoding_zone(ecu.family, did)
        if zone is not None:
            parameters = kb.decode_telecoding_parameters(zone, value)
            telecoding = TelecodingZoneInfo(
                did=did,
                name=zone.get("name", f"Zone 0x{did:04X}"),
                family=ecu.family or "",
                parameters=[TelecodingParameterValue(**item) for item in parameters],
                source=kb.pypsadiag_source(),
            )
        return DidReadResult(
            did=did,
            name=f"Zone PSA / DID 0x{did:04X}",
            codec="ascii" if mostly_printable else "bytes",
            value=printable if mostly_printable else value.hex().upper(),
            raw_hex=value.hex().upper(),
            source=PSA_DIAG_SOURCE,
            confidence="raw_vehicle_response",
            telecoding=telecoding,
        )
    finally:
        if opened:
            transport.close()
        if trace:
            trace.finish()


def _unlock_security(session: UdsSession, application_key_hex: str) -> tuple[str, str, bytes]:
    """Seed/key handshake shared by unlock_configuration and write_telecoding_parameter.

    Leaves the security level unlocked on the already-open session — the caller
    decides what to do next (close, or immediately read/write while unlocked).
    """
    seed_response = session.request(bytes.fromhex("2703"))
    if len(seed_response) != 6 or seed_response[:2] != bytes.fromhex("6703"):
        raise ValueError("Réponse seed PSA inattendue.")
    seed_hex = seed_response[2:].hex().upper()
    response_key = compute_psa_seed_key(seed_hex, application_key_hex)
    unlock_response = session.request(bytes.fromhex("2704") + bytes.fromhex(response_key))
    if unlock_response[:2] != bytes.fromhex("6704"):
        raise ValueError("Réponse de déverrouillage PSA inattendue.")
    return seed_hex, response_key, unlock_response


def unlock_configuration(ecu_key: str, request: PsaUnlockRequest) -> PsaUnlockResult:
    if not settings.psa_security_access_enabled:
        raise PermissionError("Accès sécurité PSA verrouillé : PSA_SECURITY_ACCESS_ENABLED=false.")
    expected_confirmation = f"DEVERROUILLER {ecu_key.upper()}"
    _require_lab_preconditions(
        ecu_key,
        request.confirmation,
        expected_confirmation,
        vehicle_stationary=request.vehicle_stationary,
        ignition_on_engine_off=request.ignition_on_engine_off,
        stable_battery_voltage=request.stable_battery_voltage,
        workshop_or_private_site=request.workshop_or_private_site,
    )
    ecu = _find_ecu(ecu_key)
    if ecu.request_id not in {0x752, 0x764}:
        raise PermissionError("Accès sécurité transmis limité au BSI et au calculateur télématique.")

    trace = SessionWriter()
    transport = build_transport(_trace_sink(trace), safety_profile="psa_lab")
    opened = False
    try:
        transport.open()
        opened = True
        policy = lambda payload: authorize_psa_lab_uds(ecu.request_id, payload)
        with UdsSession(
            transport,
            ecu.request_id,
            ecu.response_id,
            timeout=settings.diagnostic_timeout,
            read_only=False,
            safety_policy=policy,
        ) as session:
            session.request(bytes.fromhex("1003"))
            seed_hex, response_key, unlock_response = _unlock_security(session, request.application_key_hex)
        result = PsaUnlockResult(
            ecu_key=ecu_key,
            unlocked=True,
            seed_hex=seed_hex,
            response_key_hex=response_key,
            response_hex=unlock_response.hex().upper(),
            message="Session de configuration déverrouillée puis refermée sans écriture.",
            session_id=trace.id,
        )
        trace.write({"type": "psa_unlock_result", "payload": result.model_dump()})
        return result
    finally:
        if opened:
            transport.close()
        trace.finish()


def execute_named_action(action_key: str, request: PsaActionRequest) -> PsaActionResult:
    if not settings.psa_actuator_enabled:
        raise PermissionError("Actionneurs PSA verrouillés : PSA_ACTUATOR_ENABLED=false.")
    action = PSA_ACTIONS.get(action_key)
    if action is None:
        raise KeyError(f"Action PSA inconnue : {action_key}.")
    if action.start_payload is None:
        raise PermissionError(action.unavailable_reason or "Commande PSA non documentée.")
    expected_confirmation = f"ACTIVER {action.key.upper()}"
    _require_lab_preconditions(
        action.ecu_key,
        request.confirmation,
        expected_confirmation,
        vehicle_stationary=request.vehicle_stationary,
        ignition_on_engine_off=request.ignition_on_engine_off,
        stable_battery_voltage=request.stable_battery_voltage,
        workshop_or_private_site=request.workshop_or_private_site,
    )
    if request.duration_ms > settings.psa_actuator_max_duration_ms:
        raise PermissionError(
            f"Durée supérieure au plafond PSA_ACTUATOR_MAX_DURATION_MS={settings.psa_actuator_max_duration_ms}."
        )

    ecu = _find_ecu(action.ecu_key)
    trace = SessionWriter()
    transport = build_transport(_trace_sink(trace), safety_profile="psa_lab")
    opened = False
    started_response: bytes | None = None
    stopped_response: bytes | None = None
    try:
        transport.open()
        opened = True
        policy = lambda payload: authorize_psa_lab_uds(ecu.request_id, payload)
        with UdsSession(
            transport,
            ecu.request_id,
            ecu.response_id,
            timeout=settings.diagnostic_timeout,
            read_only=False,
            safety_policy=policy,
        ) as session:
            session.request(bytes.fromhex("1003"))
            try:
                started_response = session.request(action.start_payload)
                if action.timed:
                    time.sleep(request.duration_ms / 1_000)
            finally:
                if action.stop_payload is not None:
                    stopped_response = session.request(action.stop_payload)
        result = PsaActionResult(
            action_key=action.key,
            executed=True,
            started_response_hex=started_response.hex().upper() if started_response else None,
            stopped_response_hex=stopped_response.hex().upper() if stopped_response else None,
            duration_ms=request.duration_ms if action.timed else 0,
            message=(
                "Action terminée et commande d'arrêt envoyée."
                if action.stop_payload is not None
                else "Commande de restauration envoyée."
            ),
            session_id=trace.id,
        )
        trace.write({"type": "psa_action_result", "payload": result.model_dump()})
        return result
    except NegativeResponseException:
        raise
    finally:
        if opened:
            transport.close()
        trace.finish()


def reset_ecu(ecu_key: str, request: EcuResetRequest) -> EcuResetResult:
    """ECUReset (hardReset 0x11/0x01) — available on all 15 catalog ECUs, unlike
    telecoding write which needs a security-access unlock only wired for BSI/télématique."""
    if not settings.psa_ecu_reset_enabled:
        raise PermissionError("Redémarrage ECU verrouillé : PSA_ECU_RESET_ENABLED=false.")
    expected_confirmation = f"REDEMARRER {ecu_key.upper()}"
    _require_lab_preconditions(
        ecu_key,
        request.confirmation,
        expected_confirmation,
        vehicle_stationary=request.vehicle_stationary,
        ignition_on_engine_off=request.ignition_on_engine_off,
        stable_battery_voltage=request.stable_battery_voltage,
        workshop_or_private_site=request.workshop_or_private_site,
    )
    ecu = _find_ecu(ecu_key)

    trace = SessionWriter()
    transport = build_transport(_trace_sink(trace), safety_profile="psa_lab")
    opened = False
    response_hex: str | None = None
    message = "Commande de redémarrage envoyée."
    try:
        transport.open()
        opened = True
        policy = lambda payload: authorize_psa_lab_uds(ecu.request_id, payload)
        with UdsSession(
            transport,
            ecu.request_id,
            ecu.response_id,
            timeout=settings.diagnostic_timeout,
            read_only=False,
            safety_policy=policy,
        ) as session:
            enter_extended_session(session)
            try:
                response = ecu_reset(session)
                response_hex = response.original_payload.hex().upper()
                message = "Redémarrage confirmé par le calculateur (réponse 0x51/0x01)."
            except (TimeoutException, TimeoutError):
                message = (
                    "Commande envoyée mais le calculateur est resté silencieux — normal si le "
                    "redémarrage l'a coupé avant qu'il ait pu répondre."
                )
        result = EcuResetResult(
            ecu_key=ecu_key,
            reset=True,
            response_hex=response_hex,
            message=message,
            session_id=trace.id,
        )
        trace.write({"type": "ecu_reset_result", "payload": result.model_dump()})
        return result
    finally:
        if opened:
            transport.close()
        trace.finish()


def write_telecoding_parameter(ecu_key: str, request: TelecodingWriteRequest) -> TelecodingWriteResult:
    """Read-modify-write-verify a single documented telecoding option.

    Experimental: never confirmed on a real vehicle. Only reachable for BSI and
    télématique — the only ECUs with a wired security-access unlock today. The
    client can only choose from options already enumerated in the PyPSADiag
    catalog (by name); it never gets to send an arbitrary byte.
    """
    if not settings.psa_telecoding_write_enabled:
        raise PermissionError("Écriture télécodage verrouillée : PSA_TELECODING_WRITE_ENABLED=false.")
    if not settings.psa_security_access_enabled:
        raise PermissionError("Écriture télécodage impossible : PSA_SECURITY_ACCESS_ENABLED=false.")
    expected_confirmation = f"TELECODER {ecu_key.upper()}"
    _require_lab_preconditions(
        ecu_key,
        request.confirmation,
        expected_confirmation,
        vehicle_stationary=request.vehicle_stationary,
        ignition_on_engine_off=request.ignition_on_engine_off,
        stable_battery_voltage=request.stable_battery_voltage,
        workshop_or_private_site=request.workshop_or_private_site,
    )
    ecu = _find_ecu(ecu_key)
    if ecu.request_id not in {0x752, 0x764}:
        raise PermissionError("Écriture télécodage limitée au BSI et au calculateur télématique.")

    kb = KnowledgeBase()
    zone = kb.describe_telecoding_zone(ecu.family, request.did)
    if zone is None:
        raise KeyError(f"Zone de télécodage 0x{request.did:04X} non documentée pour {ecu.family}.")
    parameter = zone.get("parameters", {}).get(request.parameter_key)
    if parameter is None:
        raise KeyError(f"Paramètre inconnu : {request.parameter_key}.")
    byte_offset = parameter.get("byte", 0)
    field_mask_str = parameter.get("mask")
    if not isinstance(field_mask_str, str):
        raise ValueError("Paramètre sans masque documenté : écriture impossible.")
    field_mask = int(field_mask_str, 2)
    option = next(
        (item for item in parameter.get("params", []) if item.get("name") == request.option_name),
        None,
    )
    if option is None or option.get("mask") is None:
        raise KeyError(f"Option inconnue pour {request.parameter_key} : {request.option_name}.")
    option_mask = int(option["mask"], 2)

    trace = SessionWriter()
    transport = build_transport(_trace_sink(trace), safety_profile="psa_lab")
    opened = False
    try:
        transport.open()
        opened = True
        policy = lambda payload: authorize_psa_lab_uds(ecu.request_id, payload)
        with UdsSession(
            transport,
            ecu.request_id,
            ecu.response_id,
            timeout=settings.diagnostic_timeout,
            read_only=False,
            safety_policy=policy,
        ) as session:
            session.request(bytes.fromhex("1003"))
            _unlock_security(session, request.application_key_hex)

            _, before_bytes = read_data_by_identifier(session, request.did)
            if byte_offset >= len(before_bytes):
                raise ValueError(
                    "Décalage d'octet du paramètre hors de la zone lue — catalogue incohérent "
                    "avec la réponse du véhicule, écriture annulée."
                )
            before_decoded = kb.decode_telecoding_parameters(zone, before_bytes)
            previous_value = next(
                (item["value"] for item in before_decoded if item["key"] == request.parameter_key),
                None,
            )

            patched = bytearray(before_bytes)
            patched[byte_offset] = (patched[byte_offset] & ~field_mask) | option_mask
            write_data_by_identifier(session, request.did, bytes(patched))

            _, after_bytes = read_data_by_identifier(session, request.did)
            after_decoded = kb.decode_telecoding_parameters(zone, after_bytes)
            new_value = next(
                (item["value"] for item in after_decoded if item["key"] == request.parameter_key),
                None,
            )

        verified = new_value == request.option_name
        result = TelecodingWriteResult(
            ecu_key=ecu_key,
            did=request.did,
            parameter_key=request.parameter_key,
            requested_option=request.option_name,
            previous_value=previous_value,
            new_value=new_value,
            verified=verified,
            raw_before_hex=before_bytes.hex().upper(),
            raw_after_hex=after_bytes.hex().upper(),
            message=(
                "Écriture confirmée par relecture."
                if verified
                else "Écriture envoyée mais la relecture ne correspond pas à la valeur demandée — à vérifier manuellement."
            ),
            session_id=trace.id,
        )
        trace.write({"type": "telecoding_write_result", "payload": result.model_dump()})
        return result
    finally:
        if opened:
            transport.close()
        trace.finish()
