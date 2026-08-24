from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from app.config import settings
from app.database import KnowledgeBase
from app.diagnostic.isotp import UdsSession
from app.models import DebugSummary, SensorSnapshot, SensorValue
from app.session import SessionWriter
from app.transports.factory import build_transport


@dataclass(frozen=True)
class PidDefinition:
    key: str
    pid: int
    name: str
    unit: str
    length: int
    decoder: Callable[[bytes], float | int]
    group: str = "Moteur"
    description: str = "Paramètre OBD-II normalisé lu en mode 01."


def _percent(data: bytes) -> float:
    return round(data[0] * 100 / 255, 2)


def _temperature(data: bytes) -> int:
    return data[0] - 40


def _word(data: bytes) -> int:
    return int.from_bytes(data[:2], "big")


def _signed_percent(data: bytes) -> float:
    return round(data[0] * 100 / 128 - 100, 2)


def _oxygen_voltage(data: bytes) -> float:
    return round(data[0] / 200, 3)


def _absolute_load(data: bytes) -> float:
    return round(_word(data) * 100 / 255, 2)


def _fuel_injection_timing(data: bytes) -> float:
    return round(_word(data) / 128 - 210, 2)


def _wideband_lambda(data: bytes) -> float:
    return round(_word(data) * 2 / 65536, 4)


def _catalyst_temperature(data: bytes) -> float:
    return round(_word(data) / 10 - 40, 1)


def _torque_percent(data: bytes) -> int:
    return data[0] - 125


PID_DEFINITIONS = (
    PidDefinition("fuel_system_status", 0x03, "État des boucles carburant", "code", 2, _word, "Carburant", "États normalisés des circuits carburant 1 et 2; utile pour distinguer boucle ouverte et boucle fermée."),
    PidDefinition("engine_load", 0x04, "Charge moteur calculée", "%", 1, _percent, "Combustion", "Charge moteur normalisée calculée par l'ECU."),
    PidDefinition("coolant_temperature", 0x05, "Température liquide de refroidissement", "°C", 1, _temperature, "Températures", "Température moteur utilisée par la stratégie d'injection."),
    PidDefinition("short_fuel_trim_bank_1", 0x06, "Correction carburant court terme B1", "%", 1, _signed_percent, "Carburant", "Correction de richesse OBD court terme; souvent non prise en charge sur diesel."),
    PidDefinition("long_fuel_trim_bank_1", 0x07, "Correction carburant long terme B1", "%", 1, _signed_percent, "Carburant", "Adaptation de richesse OBD long terme; souvent non prise en charge sur diesel."),
    PidDefinition("short_fuel_trim_bank_2", 0x08, "Correction carburant court terme B2", "%", 1, _signed_percent, "Carburant", "Correction de richesse de la banque 2 quand elle existe."),
    PidDefinition("long_fuel_trim_bank_2", 0x09, "Correction carburant long terme B2", "%", 1, _signed_percent, "Carburant", "Adaptation de richesse de la banque 2 quand elle existe."),
    PidDefinition("fuel_pressure", 0x0A, "Pression carburant basse pression", "kPa", 1, lambda data: data[0] * 3, "Carburant", "Pression carburant relative normalisée; ce n'est pas la pression de rampe haute pression."),
    PidDefinition("intake_manifold_pressure", 0x0B, "Pression collecteur d'admission", "kPa abs", 1, lambda data: data[0], "Air", "Pression absolue dans le collecteur, incluant la suralimentation."),
    PidDefinition("engine_rpm", 0x0C, "Régime moteur", "tr/min", 2, lambda data: round(_word(data) / 4, 2), "Combustion", "Vitesse de rotation moteur diffusée par l'ECU."),
    PidDefinition("vehicle_speed", 0x0D, "Vitesse véhicule", "km/h", 1, lambda data: data[0], "Contexte", "Vitesse véhicule associée au relevé injection."),
    PidDefinition("timing_advance", 0x0E, "Avance à l'allumage", "°", 1, lambda data: round(data[0] / 2 - 64, 2), "Combustion", "Avance normalisée; surtout pertinente pour un moteur essence."),
    PidDefinition("intake_air_temperature", 0x0F, "Température d'air d'admission", "°C", 1, _temperature, "Air", "Température d'air prise en compte pour la masse injectée."),
    PidDefinition("maf", 0x10, "Débit d'air massique", "g/s", 2, lambda data: round(_word(data) / 100, 2), "Air", "Masse d'air mesurée par le débitmètre."),
    PidDefinition("throttle_position", 0x11, "Position papillon", "%", 1, _percent, "Air", "Position absolue du papillon ou doseur d'air."),
    PidDefinition("secondary_air_status", 0x12, "État injection d'air secondaire", "code", 1, lambda data: data[0], "Dépollution", "État normalisé du système d'injection d'air secondaire lorsqu'il est présent."),
    PidDefinition("oxygen_sensors_present", 0x13, "Sondes lambda présentes", "bitmap", 1, lambda data: data[0], "Dépollution", "Bitmap indiquant les emplacements de sondes à oxygène annoncés par l'ECU."),
    PidDefinition("oxygen_sensor_b1s1_voltage", 0x14, "Sonde lambda amont B1S1", "V", 2, _oxygen_voltage, "Dépollution", "Tension normalisée de la sonde à oxygène amont; le second octet de correction n'est pas affiché ici."),
    PidDefinition("oxygen_sensor_b1s2_voltage", 0x15, "Sonde lambda aval B1S2", "V", 2, _oxygen_voltage, "Dépollution", "Tension normalisée de la sonde à oxygène aval; le second octet de correction n'est pas affiché ici."),
    PidDefinition("obd_standard", 0x1C, "Norme OBD déclarée", "code", 1, lambda data: data[0], "Contexte", "Code de conformité OBD déclaré par le calculateur."),
    PidDefinition("oxygen_sensors_present_4_bank", 0x1D, "Sondes lambda présentes · 4 banques", "bitmap", 1, lambda data: data[0], "Dépollution", "Bitmap étendu des sondes à oxygène présentes."),
    PidDefinition("auxiliary_input_status", 0x1E, "État entrée auxiliaire / PTO", "bitmap", 1, lambda data: data[0], "Contexte", "État normalisé de l'entrée auxiliaire ou prise de force lorsqu'elle existe."),
    PidDefinition("engine_runtime", 0x1F, "Temps depuis démarrage moteur", "s", 2, _word, "Contexte", "Durée de fonctionnement depuis le dernier démarrage."),
    PidDefinition("distance_with_mil", 0x21, "Distance avec voyant moteur allumé", "km", 2, _word, "Contexte", "Distance parcourue depuis l'allumage du voyant moteur."),
    PidDefinition("fuel_rail_relative_pressure", 0x22, "Pression relative de rampe", "kPa", 2, lambda data: round(_word(data) * 0.079, 3), "Carburant", "Pression relative de rampe normalisée pour certains systèmes d'injection."),
    PidDefinition("fuel_rail_gauge_pressure", 0x23, "Pression de rampe carburant", "kPa", 2, lambda data: _word(data) * 10, "Carburant", "Pression de rampe relative normalisée, typique de l'injection directe/diesel."),
    PidDefinition("wideband_o2_b1s1_lambda", 0x24, "Lambda large bande B1S1", "λ", 4, _wideband_lambda, "Dépollution", "Rapport lambda de la sonde large bande; la tension associée reste dans les octets bruts."),
    PidDefinition("wideband_o2_b1s2_lambda", 0x25, "Lambda large bande B1S2", "λ", 4, _wideband_lambda, "Dépollution", "Rapport lambda de la sonde large bande B1S2."),
    PidDefinition("wideband_o2_b1s3_lambda", 0x26, "Lambda large bande B1S3", "λ", 4, _wideband_lambda, "Dépollution", "Rapport lambda de la sonde large bande B1S3."),
    PidDefinition("wideband_o2_b1s4_lambda", 0x27, "Lambda large bande B1S4", "λ", 4, _wideband_lambda, "Dépollution", "Rapport lambda de la sonde large bande B1S4."),
    PidDefinition("wideband_o2_b2s1_lambda", 0x28, "Lambda large bande B2S1", "λ", 4, _wideband_lambda, "Dépollution", "Rapport lambda de la sonde large bande B2S1."),
    PidDefinition("wideband_o2_b2s2_lambda", 0x29, "Lambda large bande B2S2", "λ", 4, _wideband_lambda, "Dépollution", "Rapport lambda de la sonde large bande B2S2."),
    PidDefinition("wideband_o2_b2s3_lambda", 0x2A, "Lambda large bande B2S3", "λ", 4, _wideband_lambda, "Dépollution", "Rapport lambda de la sonde large bande B2S3."),
    PidDefinition("wideband_o2_b2s4_lambda", 0x2B, "Lambda large bande B2S4", "λ", 4, _wideband_lambda, "Dépollution", "Rapport lambda de la sonde large bande B2S4."),
    PidDefinition("commanded_egr", 0x2C, "Commande EGR", "%", 1, _percent, "Dépollution", "Consigne d'ouverture EGR demandée par le calculateur."),
    PidDefinition("egr_error", 0x2D, "Écart EGR", "%", 1, _signed_percent, "Dépollution", "Écart entre la consigne et le retour EGR."),
    PidDefinition("commanded_evap_purge", 0x2E, "Commande purge canister", "%", 1, _percent, "Dépollution", "Commande normalisée de purge des vapeurs de carburant."),
    PidDefinition("fuel_level", 0x2F, "Niveau carburant", "%", 1, _percent, "Carburant", "Niveau de carburant déclaré au diagnostic OBD."),
    PidDefinition("warmups_since_clear", 0x30, "Cycles de chauffe depuis effacement DTC", "cycles", 1, lambda data: data[0], "Contexte", "Nombre de cycles de chauffe moteur depuis le dernier effacement des défauts."),
    PidDefinition("distance_since_clear", 0x31, "Distance depuis effacement DTC", "km", 2, _word, "Contexte", "Distance parcourue depuis le dernier effacement des défauts."),
    PidDefinition("evap_vapor_pressure", 0x32, "Pression vapeurs canister", "Pa", 2, lambda data: round(_word(data) / 4 - 8192, 2), "Dépollution", "Pression différentielle des vapeurs du système EVAP."),
    PidDefinition("barometric_pressure", 0x33, "Pression barométrique", "kPa abs", 1, lambda data: data[0], "Air", "Pression atmosphérique de référence utilisée par le calculateur."),
    PidDefinition("catalyst_temperature_b1s1", 0x3C, "Température catalyseur B1S1", "°C", 2, _catalyst_temperature, "Dépollution", "Température normalisée du catalyseur banque 1 capteur 1."),
    PidDefinition("catalyst_temperature_b2s1", 0x3D, "Température catalyseur B2S1", "°C", 2, _catalyst_temperature, "Dépollution", "Température normalisée du catalyseur banque 2 capteur 1."),
    PidDefinition("catalyst_temperature_b1s2", 0x3E, "Température catalyseur B1S2", "°C", 2, _catalyst_temperature, "Dépollution", "Température normalisée du catalyseur banque 1 capteur 2."),
    PidDefinition("catalyst_temperature_b2s2", 0x3F, "Température catalyseur B2S2", "°C", 2, _catalyst_temperature, "Dépollution", "Température normalisée du catalyseur banque 2 capteur 2."),
    PidDefinition("monitor_status_current_cycle", 0x41, "Moniteurs OBD du cycle courant", "bitmap", 4, lambda data: int.from_bytes(data, "big"), "Dépollution", "Disponibilité et résultat des moniteurs OBD pendant le cycle de conduite courant."),
    PidDefinition("control_module_voltage", 0x42, "Tension calculateur", "V", 2, lambda data: round(_word(data) / 1000, 3), "Électrique", "Tension d'alimentation du calculateur d'injection."),
    PidDefinition("absolute_engine_load", 0x43, "Charge moteur absolue", "%", 2, _absolute_load, "Combustion", "Charge absolue normalisée, complémentaire à la charge calculée PID 04."),
    PidDefinition("commanded_equivalence_ratio", 0x44, "Richesse commandée (lambda)", "λ", 2, lambda data: round(_word(data) * 2 / 65536, 4), "Combustion", "Rapport d'équivalence commandé; 1 correspond au mélange stœchiométrique."),
    PidDefinition("relative_throttle_position", 0x45, "Position relative papillon", "%", 1, _percent, "Air", "Position relative normalisée du papillon motorisé."),
    PidDefinition("ambient_temperature", 0x46, "Température ambiante", "°C", 1, _temperature, "Températures", "Température extérieure utilisée comme contexte moteur."),
    PidDefinition("absolute_throttle_position_b", 0x47, "Position papillon voie B", "%", 1, _percent, "Air", "Seconde voie normalisée de position du papillon motorisé."),
    PidDefinition("absolute_throttle_position_c", 0x48, "Position papillon voie C", "%", 1, _percent, "Air", "Troisième voie normalisée de position du papillon lorsqu'elle existe."),
    PidDefinition("accelerator_pedal_d", 0x49, "Position pédale accélérateur D", "%", 1, _percent, "Commande conducteur", "Position normalisée de la voie D de la pédale d'accélérateur."),
    PidDefinition("accelerator_pedal_e", 0x4A, "Position pédale accélérateur E", "%", 1, _percent, "Commande conducteur", "Position normalisée de la voie E de la pédale d'accélérateur."),
    PidDefinition("accelerator_pedal_f", 0x4B, "Position pédale accélérateur F", "%", 1, _percent, "Commande conducteur", "Troisième voie normalisée de la pédale d'accélérateur lorsqu'elle existe."),
    PidDefinition("commanded_throttle_actuator", 0x4C, "Commande actionneur papillon", "%", 1, _percent, "Air", "Commande normalisée envoyée à l'actionneur du papillon."),
    PidDefinition("time_with_mil", 0x4D, "Temps avec voyant moteur allumé", "min", 2, _word, "Contexte", "Durée cumulée de fonctionnement avec le voyant moteur allumé."),
    PidDefinition("time_since_clear", 0x4E, "Temps depuis effacement DTC", "min", 2, _word, "Contexte", "Temps écoulé depuis le dernier effacement des défauts."),
    PidDefinition("maximum_maf", 0x50, "Débit d'air massique maximal", "g/s", 4, lambda data: data[0] * 10, "Air", "Valeur maximale déclarée du débitmètre; les autres octets codent des maxima secondaires."),
    PidDefinition("fuel_type", 0x51, "Type de carburant OBD", "code", 1, lambda data: data[0], "Carburant", "Code normalisé du type de carburant déclaré par le calculateur."),
    PidDefinition("ethanol_fuel_percent", 0x52, "Teneur en éthanol", "%", 1, _percent, "Carburant", "Pourcentage d'éthanol déclaré par le système carburant."),
    PidDefinition("absolute_evap_vapor_pressure", 0x53, "Pression absolue vapeurs canister", "kPa", 2, lambda data: round(_word(data) / 200, 3), "Dépollution", "Pression absolue normalisée du circuit EVAP."),
    PidDefinition("evap_vapor_pressure_alt", 0x54, "Pression vapeurs canister alternative", "Pa", 2, lambda data: _word(data) - 32767, "Dépollution", "Seconde représentation normalisée de la pression différentielle EVAP."),
    PidDefinition("absolute_fuel_rail_pressure", 0x59, "Pression absolue de rampe", "kPa", 2, lambda data: _word(data) * 10, "Carburant", "Pression absolue de rampe carburant lorsqu'elle est exposée par l'ECU."),
    PidDefinition("relative_accelerator_position", 0x5A, "Position relative accélérateur", "%", 1, _percent, "Commande conducteur", "Demande relative normalisée de la pédale d'accélérateur."),
    PidDefinition("engine_oil_temperature", 0x5C, "Température huile moteur", "°C", 1, _temperature, "Températures", "Température d'huile utilisée pour la protection moteur."),
    PidDefinition("fuel_injection_timing", 0x5D, "Avance d'injection", "°", 2, _fuel_injection_timing, "Combustion", "Calage normalisé de l'injection par rapport au point mort haut."),
    PidDefinition("fuel_rate", 0x5E, "Débit carburant", "L/h", 2, lambda data: round(_word(data) / 20, 2), "Carburant", "Débit total de carburant consommé par le moteur."),
    PidDefinition("emission_requirements", 0x5F, "Exigences d'émissions", "code", 1, lambda data: data[0], "Dépollution", "Code de réglementation d'émissions auquel le véhicule déclare répondre."),
    PidDefinition("driver_demand_torque", 0x61, "Demande de couple conducteur", "%", 1, _torque_percent, "Combustion", "Demande de couple moteur normalisée du conducteur."),
    PidDefinition("actual_engine_torque", 0x62, "Couple moteur réel", "%", 1, _torque_percent, "Combustion", "Couple réel exprimé en pourcentage du couple de référence."),
    PidDefinition("engine_reference_torque", 0x63, "Couple moteur de référence", "N·m", 2, _word, "Combustion", "Couple de référence utilisé pour convertir les pourcentages de couple."),
    PidDefinition("egr_temperature_sensor_1", 0x6B, "Température EGR capteur 1", "°C", 3, lambda data: data[1] - 40, "Dépollution", "Première température EGR lorsque ce groupe de capteurs est pris en charge."),
)

PID_BY_ID = {definition.pid: definition for definition in PID_DEFINITIONS}


def sensor_catalog() -> list[dict]:
    return [
        {
            "key": definition.key,
            "pid": definition.pid,
            "name": definition.name,
            "unit": definition.unit,
            "group": definition.group,
            "description": definition.description,
            "source": "SAE J1979 / ISO 15031-5",
            "confidence": "standardized",
            "access": "read_only",
            "request_hex": f"01{definition.pid:02X}",
        }
        for definition in PID_DEFINITIONS
    ]


def supported_pids(session: UdsSession) -> list[int]:
    supported: set[int] = set()
    base = 0x00
    while base <= 0xE0:
        response = session.request_obd(bytes([0x01, base]))
        expected = bytes([0x41, base])
        if not response.startswith(expected) or len(response) < 6:
            raise ValueError(
                f"Réponse support PID inattendue pour 0x{base:02X}: {response.hex().upper()}"
            )
        bitmap = int.from_bytes(response[2:6], "big")
        for offset in range(1, 33):
            if bitmap & (1 << (32 - offset)):
                supported.add(base + offset)
        next_base = base + 0x20
        if next_base not in supported:
            break
        base = next_base
    return sorted(supported)


def read_pid(session: UdsSession, definition: PidDefinition) -> SensorValue:
    """Read and decode one standardized Mode 01 PID."""
    response = session.request_obd(bytes([0x01, definition.pid]))
    expected = bytes([0x41, definition.pid])
    if not response.startswith(expected):
        raise ValueError(f"Réponse inattendue : {response.hex().upper()}")
    data = response[2:]
    if len(data) < definition.length:
        raise ValueError(
            f"PID 0x{definition.pid:02X} tronqué : "
            f"{len(data)} octets, {definition.length} attendus."
        )
    return SensorValue(
        key=definition.key,
        pid=definition.pid,
        name=definition.name,
        value=definition.decoder(data[:definition.length]),
        unit=definition.unit,
        group=definition.group,
        description=definition.description,
        source="SAE J1979 / ISO 15031-5",
        confidence="standardized",
        raw_hex=data.hex().upper(),
    )


def live_pid_definitions(profile_key: str) -> tuple[PidDefinition, ...]:
    """Return the allowlisted live PIDs configured for a vehicle profile."""
    diagnostic = KnowledgeBase().vehicle(profile_key).get("diagnostic", {})
    live = diagnostic.get("live_obd", {})
    configured = live.get("pids", []) if isinstance(live, dict) else []
    definitions: list[PidDefinition] = []
    for value in configured:
        pid = int(str(value), 0)
        definition = PID_BY_ID.get(pid)
        if definition is not None and definition not in definitions:
            definitions.append(definition)
    return tuple(definitions)


def snapshot_sensors(profile_key: str | None = None) -> SensorSnapshot:
    if settings.transport != "virtual" and not settings.can_tx_enabled:
        raise PermissionError(
            "Le mode capteurs envoie uniquement des lectures OBD, mais nécessite CAN_TX_ENABLED=true."
        )

    selected_profile = profile_key or settings.vehicle_profile
    diagnostic = KnowledgeBase().vehicle(selected_profile).get("diagnostic", {})
    request_id = int(str(diagnostic.get("obd_request_id", 0x7E0)), 0)
    response_id = int(str(diagnostic.get("obd_response_id", 0x7E8)), 0)
    flow_control_id = (
        int(str(diagnostic["obd_flow_control_id"]), 0)
        if diagnostic.get("obd_flow_control_id") is not None
        else None
    )
    flow_control_blocksize = int(diagnostic.get("obd_flow_control_blocksize", 8))
    trace = SessionWriter()

    def sink(event: dict) -> None:
        if event.get("type") == "can_frame" and not settings.trace_can_frames:
            return
        trace.write(event)

    transport = build_transport(
        sink,
        receive_buses=("default", "live"),
        require_diagnostic_can=False,
        vehicle_profile=selected_profile,
    )
    snapshot = SensorSnapshot(
        transport=transport.name,
        vehicle_profile=selected_profile,
        request_id=request_id,
        response_id=response_id,
    )
    trace.write({
        "type": "sensor_snapshot_start",
        "request_id": request_id,
        "response_id": response_id,
        "pid_catalog": [definition.pid for definition in PID_DEFINITIONS],
    })
    opened = False
    try:
        transport.open()
        opened = True
        with UdsSession(
            transport,
            request_id,
            response_id,
            timeout=settings.diagnostic_timeout,
            read_only=True,
            tx_bus="live",
            flow_control_id=flow_control_id,
            flow_control_blocksize=flow_control_blocksize,
        ) as session:
            snapshot.supported_pids = supported_pids(session)
            supported = set(snapshot.supported_pids)
            if 0x01 in supported:
                response = session.request_obd(bytes.fromhex("0101"))
                if not response.startswith(bytes.fromhex("4101")) or len(response) < 6:
                    raise ValueError(f"Statut OBD PID 01 inattendu : {response.hex().upper()}")
                status = response[2]
                snapshot.mil_on = bool(status & 0x80)
                snapshot.emissions_dtc_count = status & 0x7F
                snapshot.readiness_raw_hex = response[2:6].hex().upper()
            for definition in PID_DEFINITIONS:
                if definition.pid not in supported:
                    continue
                try:
                    snapshot.values.append(read_pid(session, definition))
                except Exception as exc:
                    snapshot.values.append(SensorValue(
                        key=definition.key,
                        pid=definition.pid,
                        name=definition.name,
                        unit=definition.unit,
                        group=definition.group,
                        description=definition.description,
                        source="SAE J1979 / ISO 15031-5",
                        confidence="standardized",
                        error=str(exc),
                    ))
        trace.write({"type": "sensor_snapshot", "payload": snapshot.model_dump()})
    except Exception as exc:
        trace.write({
            "type": "sensor_snapshot_error",
            "error_type": type(exc).__name__,
            "error": str(exc),
        })
        raise
    finally:
        if opened:
            transport.close()
        snapshot.debug = DebugSummary(**trace.finish())
    return snapshot
