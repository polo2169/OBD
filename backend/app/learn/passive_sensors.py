from __future__ import annotations

import math
import time
from typing import Any

from app.config import settings
from app.diagnostic.obd import PID_BY_ID
from app.learn.capture import capture_manager
from app.learn.models import (
    PassiveCanSignal,
    PassiveSensorSnapshot,
    PassiveSteeringSnapshot,
)
from app.learn.opendbc import get_opendbc_decoder
from app.learn.sensor_metadata import load_overrides, metadata_for
from app.live_data.registry import list_definitions


VALIDATED_SIGNALS = {
    ("STEERING_ALT", "ANGLE"),
    ("STEERING_ALT", "RATE"),
    ("STEERING", "DRIVER_TORQUE"),
}

FIAT_500_CAN_NOTES_URL = (
    "https://github.com/P1kachu/talking-with-cars/blob/master/notes/fiat-500.txt"
)
FIAT_ENGINE_CAN_NOTES_URL = "https://fiatpunto.com.pl/topic59422-50.html"
FRONT_SENSOR_CANDIDATE_ID = 0x489  # non documenté ; candidat radar de stationnement avant

FIAT_500_CANDIDATE_IDS = {
    0x0218A006,  # quatre vitesses de roue
    0x0628A001,  # états combinés accélérateur / embrayage
    0x0810A000,  # pédale de frein
    0x0A18A000,  # frein à main, porte conducteur, City, dégivrage
    0x0C1CA000,  # Start&Stop
    0x0C28A000,  # horloge véhicule
}


def _category(message: str) -> str:
    upper = message.upper()
    if upper in {"STEERING", "STEERING_ALT", "IS_DAT_DIRA"}:
        return "Direction"
    if upper in {"LANE_KEEP_ASSIST", "DRIVER", "NEW_MSG_42D"}:
        return "ADAS / caméra"
    if any(token in upper for token in ("FRE", "ABR", "VROUES")):
        return "Freinage / ABS"
    if any(token in upper for token in ("CMM", "EOBD")):
        return "Moteur"
    if "BSI" in upper or "MDD" in upper:
        return "Habitacle / BSI"
    if any(token in upper for token in ("_BV", "BVMP", "EASYMOVE")):
        return "Transmission"
    if "CLIM" in upper:
        return "Climatisation"
    if "RESTRAINT" in upper:
        return "Airbag / retenue"
    return "Autres"


def _ecu_family(message: str) -> str | None:
    """Best-effort mapping from a decoded CAN message name to the vehicle.yaml
    ``family`` it was broadcast by, so the ECU page can show it its own signals.
    Only covers message-name patterns actually observed in the PSA DBC; unknown
    or ambiguous messages (STEERING, ESP, NEW_MSG_*, DRIVER...) stay unattributed
    rather than guessed.
    """
    upper = message.upper()
    if any(token in upper for token in ("CMM", "EOBD", "OBD01")):
        return "INJ"
    if any(token in upper for token in ("_BV", "BVMP", "EASYMOVE")):
        return "BOITEVIT"
    if any(token in upper for token in ("FRE", "ABR", "VROUES", "CDS")):
        return "ABRASR"
    if "BSI" in upper or "MDD" in upper:
        return "BMF_UDS_PSA"
    if "CLIM" in upper:
        return "CLIM"
    if "DIRA" in upper:
        return "DIRECTN"
    if "ARTIV" in upper:
        return "ARTIV"
    if "RESTRAINT" in upper:
        return "AIRBAG"
    return None


def _is_metadata_signal(name: str) -> bool:
    upper = name.upper()
    return (
        "CHECKSUM" in upper
        or "COUNTER" in upper
        or upper.startswith("UNKNOWN")
        or upper.startswith("NEW_SIGNAL")
    )


def _number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    result = float(value)
    return result if math.isfinite(result) else None


def _steering_from_messages(decoded: dict[str, dict[str, dict[str, Any]]]) -> PassiveSteeringSnapshot:
    primary = decoded.get("STEERING_ALT", {})
    fallback = decoded.get("STEERING", {})

    angle = _number(primary.get("ANGLE", {}).get("value"))
    angle_source = "0x305 STEERING_ALT.ANGLE" if angle is not None else None
    if angle is None or abs(angle) > 1080:
        candidate = _number(fallback.get("ANGLE", {}).get("value"))
        if candidate is not None and abs(candidate) <= 1080:
            angle = candidate
            angle_source = "0x2F5 STEERING.ANGLE"
        else:
            angle = None

    rate = _number(primary.get("RATE", {}).get("value"))
    rate_sign = _number(primary.get("RATE_SIGN", {}).get("value"))
    if rate is not None and rate_sign:
        rate = -rate

    torque = _number(fallback.get("DRIVER_TORQUE", {}).get("value"))
    detected = angle is not None or rate is not None or torque is not None
    warning = None
    fallback_angle = _number(fallback.get("ANGLE", {}).get("value"))
    if fallback_angle is not None and abs(fallback_angle) > 1080:
        warning = "L'angle 0x2F5 est une sentinelle invalide; 0x305 est utilisé."

    return PassiveSteeringSnapshot(
        detected=detected,
        angle_degrees=angle,
        rate_degrees_s=rate,
        driver_torque=torque,
        angle_source=angle_source,
        torque_source="0x2F5 STEERING.DRIVER_TORQUE" if torque is not None else None,
        warning=warning,
    )


def _display_value(value: Any, factor: float, offset: float) -> Any:
    number = _number(value)
    if number is None:
        return value
    converted = number * factor + offset
    if abs(converted - round(converted)) < 1e-9:
        return int(round(converted))
    return round(converted, 6)


def _fiat_wheel_speed(raw: int) -> float:
    # La Fiat diffuse 0x002C à l'arrêt et sous environ 4 km/h.
    return 0.0 if raw <= 0x002C else round(raw / 16.0, 2)


def _bcd_byte(value: int) -> int | None:
    high, low = value >> 4, value & 0x0F
    return high * 10 + low if high <= 9 and low <= 9 else None


def _fiat_500_candidate_signals(frame: dict[str, Any]) -> list[PassiveCanSignal]:
    """Decode only Fiat 500 fields both documented publicly and seen on this VIN.

    These remain candidates until an annotated action or an independent sensor
    confirms their physical meaning. Keeping that confidence separate prevents
    a community map from being presented as vehicle-validated data.
    """

    arbitration_id = int(frame["arbitration_id"])
    data = bytes(frame["data"])
    updated_at_us = int(frame["timestamp_us"])
    raw_hex = str(frame["raw_hex"])
    signals: list[PassiveCanSignal] = []

    def add(
        key: str,
        message: str,
        signal: str,
        label: str,
        description: str,
        category: str,
        value: str | int | float | bool,
        unit: str | None = None,
        essential: bool = False,
        confidence: str = "vehicle_observed_candidate",
    ) -> None:
        validation_note = (
            "Fonction confirmée physiquement par le conducteur sur le VIN courant."
            if confidence == "validated"
            else "Décodage à confirmer par capture annotée."
        )
        signals.append(PassiveCanSignal(
            key=key,
            arbitration_id=arbitration_id,
            message=message,
            signal=signal,
            display_name=label,
            description=(
                f"{description} Trame observée sur le VIN courant. {validation_note} "
                f"Source ouverte : {FIAT_500_CAN_NOTES_URL}"
            ),
            category=category,
            value=value,
            raw_value=value,
            unit=unit,
            source_unit=unit,
            essential=essential,
            updated_at_us=updated_at_us,
            raw_hex=raw_hex,
            confidence=confidence,
        ))

    if arbitration_id == 0x0218A006 and len(data) >= 8:
        names = (
            ("FRONT_LEFT", "Roue avant gauche"),
            ("FRONT_RIGHT", "Roue avant droite"),
            ("REAR_LEFT", "Roue arrière gauche"),
            ("REAR_RIGHT", "Roue arrière droite"),
        )
        for index, (signal, label) in enumerate(names):
            raw = int.from_bytes(data[index * 2:index * 2 + 2], "big")
            add(
                f"FIAT_ABS.WHEEL_{signal}_SPEED",
                "FIAT_ABS",
                f"WHEEL_{signal}_SPEED",
                f"Vitesse {label.lower()}",
                "Vitesse individuelle ABS candidate, résolution 1/16 km/h.",
                "Freinage / ABS",
                _fiat_wheel_speed(raw),
                "km/h",
                True,
            )
    elif arbitration_id == 0x0628A001 and len(data) >= 6:
        add(
            "FIAT_DRIVER.CLUTCH_PEDAL_PRESSED",
            "FIAT_DRIVER",
            "CLUTCH_PEDAL_PRESSED",
            "Pédale d'embrayage enfoncée",
            "Bit candidat de l'état combiné embrayage/accélération (octet 5, bit 5).",
            "Commandes conducteur",
            bool(data[5] & 0x20),
        )
    elif arbitration_id == 0x0810A000 and len(data) >= 3:
        brake_state = data[2] & 0xF0
        add(
            "FIAT_ABS.BRAKE_PEDAL_ACTIVE",
            "FIAT_ABS",
            "BRAKE_PEDAL_ACTIVE",
            "Pédale de frein active",
            "Le nibble 0x1 indique le repos; 0x3 et au-delà indiquent un appui.",
            "Freinage / ABS",
            brake_state >= 0x30,
            essential=True,
            confidence="validated",
        )
        add(
            "FIAT_ABS.BRAKE_PEDAL_STATE_RAW",
            "FIAT_ABS",
            "BRAKE_PEDAL_STATE_RAW",
            "Niveau brut de freinage",
            "État non étalonné de la pédale; il ne s'agit pas encore d'une pression en bar.",
            "Freinage / ABS",
            brake_state,
        )
    elif arbitration_id == 0x0A18A000 and len(data) >= 7:
        body_values = (
            ("PARKING_BRAKE", "Frein de stationnement", bool(data[0] & 0x20), "vehicle_observed_candidate"),
            ("DRIVER_DOOR_OPEN", "Porte conducteur ouverte", bool(data[2] & 0x08), "validated"),
            ("KEY_CONTACT_ON", "Contact établi", bool(data[2] & 0x40), "vehicle_observed_candidate"),
            ("IGNITION_ACTIVE", "Phase démarrage active", bool(data[2] & 0x80), "vehicle_observed_candidate"),
            ("CITY_MODE", "Mode City", bool(data[4] & 0x08), "vehicle_observed_candidate"),
            ("REAR_WINDOW_HEATER", "Dégivrage arrière", bool(data[6] & 0x10), "vehicle_observed_candidate"),
        )
        for signal, label, value, confidence in body_values:
            add(
                f"FIAT_BODY.{signal}",
                "FIAT_BODY",
                signal,
                label,
                "État logique candidat diffusé par le Body Computer.",
                "Habitacle / Body Computer",
                value,
                confidence=confidence,
            )
    elif arbitration_id == 0x0C1CA000 and len(data) >= 3:
        add(
            "FIAT_BODY.START_STOP_ACTIVE",
            "FIAT_BODY",
            "START_STOP_ACTIVE",
            "Start&Stop activé",
            "Bit candidat d'activation du Start&Stop.",
            "Habitacle / Body Computer",
            bool(data[2] & 0x20),
        )
        add(
            "FIAT_BODY.START_STOP_AVAILABLE",
            "FIAT_BODY",
            "START_STOP_AVAILABLE",
            "Start&Stop disponible",
            "Paire de bits candidate indiquant la disponibilité du Start&Stop.",
            "Habitacle / Body Computer",
            (data[2] & 0xC0) == 0xC0,
        )
    elif arbitration_id == 0x0C28A000 and len(data) >= 6:
        parts = [_bcd_byte(value) for value in data[:6]]
        hour, minute, day, month, year_high, year_low = parts
        if (
            all(value is not None for value in parts)
            and hour is not None and 0 <= hour <= 23
            and minute is not None and 0 <= minute <= 59
            and day is not None and 1 <= day <= 31
            and month is not None and 1 <= month <= 12
            and year_high is not None and year_low is not None
        ):
            add(
                "FIAT_CLOCK.DATE_TIME",
                "FIAT_CLOCK",
                "DATE_TIME",
                "Date et heure véhicule",
                "Horloge BCD candidate diffusée sur le réseau Fiat.",
                "Combiné d'instruments",
                f"{year_high:02d}{year_low:02d}-{month:02d}-{day:02d} {hour:02d}:{minute:02d}",
            )

    return signals


def _hybrid_obd_signals(
    since_us: int | None,
) -> tuple[list[PassiveCanSignal], int, list[int]]:
    records = capture_manager.latest_obd_values()
    signals: list[PassiveCanSignal] = []
    selected_timestamps: list[int] = []
    for record in records:
        try:
            pid = int(record["pid"])
            updated_at_us = int(record["updated_at_us"])
            response_id = int(record["response_id"])
        except (KeyError, TypeError, ValueError):
            continue
        definition = PID_BY_ID.get(pid)
        if definition is None:
            continue
        if since_us is not None and updated_at_us <= since_us:
            continue
        selected_timestamps.append(updated_at_us)
        signals.append(PassiveCanSignal(
            key=f"OBD01.{definition.key}",
            arbitration_id=response_id,
            message="OBD01",
            signal=definition.key,
            display_name=definition.name,
            description=definition.description,
            category=definition.group,
            ecu_family="INJ",
            value=record.get("value"),
            raw_value=record.get("value"),
            unit=record.get("unit") or definition.unit,
            source_unit=record.get("unit") or definition.unit,
            essential=definition.key in {
                "control_module_voltage",
                "coolant_temperature",
                "engine_rpm",
                "vehicle_speed",
            },
            updated_at_us=updated_at_us,
            raw_hex=str(record.get("raw_hex") or ""),
            source="obd",
            pid=pid,
            confidence="standardized",
        ))
    return signals, len(records), selected_timestamps


def _append_hybrid_warning(status, warnings: list[str], obd_signal_count: int) -> None:
    if not status.hybrid_obd_enabled:
        return
    if status.hybrid_obd_ready:
        warnings.append(
            f"Direct hybride actif : {obd_signal_count} PID OBD normalisé(s) complètent le CAN passif."
        )
    elif status.obd_error:
        warnings.append(f"Complément OBD direct indisponible : {status.obd_error}")


def _custom_signals(signals: list[PassiveCanSignal], vin: str | None) -> list[PassiveCanSignal]:
    """Materialize VIN-scoped aliases without changing their physical source."""

    sources = {signal.key: signal for signal in signals if not signal.user_defined}
    custom: list[PassiveCanSignal] = []
    for definition in list_definitions(vin=vin):
        source = sources.get(definition.source_key)
        if source is None:
            continue
        custom.append(PassiveCanSignal(
            key=definition.key,
            arbitration_id=source.arbitration_id,
            message="CUSTOM",
            signal=definition.key.split(".", 1)[-1],
            display_name=definition.label,
            description=definition.description or f"Capteur local dérivé de {definition.source_key}.",
            category=definition.category,
            ecu_family=source.ecu_family,
            value=_display_value(source.raw_value, definition.factor, definition.offset),
            raw_value=source.raw_value,
            unit=definition.unit if definition.unit is not None else source.unit,
            source_unit=source.source_unit,
            factor=definition.factor,
            offset=definition.offset,
            customized=True,
            essential=False,
            updated_at_us=source.updated_at_us,
            raw_hex=source.raw_hex,
            source=source.source,
            pid=source.pid,
            confidence=source.confidence,
            user_defined=True,
            definition_key=definition.key,
            derived_from=definition.source_key,
        ))
    return custom


def passive_sensor_snapshot(
    since_us: int | None = None,
    vin: str | None = None,
) -> PassiveSensorSnapshot:
    status = capture_manager.status()
    frames = capture_manager.latest_frames()
    profile_key = status.vehicle_profile or settings.vehicle_profile
    is_psa_profile = profile_key.startswith(("peugeot_", "psa_"))

    if not is_psa_profile:
        signals: list[PassiveCanSignal] = []
        unknown_can_ids: list[int] = []
        selected_timestamps: list[int] = []
        observed_fiat_messages: set[int] = set()
        for frame in frames:
            arbitration_id = int(frame["arbitration_id"])
            frame_timestamp = int(frame["timestamp_us"])
            is_selected = since_us is None or frame_timestamp > since_us
            if is_selected:
                selected_timestamps.append(frame_timestamp)
            is_validated_fiat_rpm = (
                profile_key == "fiat_500_generic"
                and bool(frame["extended"])
                and arbitration_id == 0x0618A001
                and len(frame["data"]) >= 4
            )
            is_fiat_candidate = (
                profile_key == "fiat_500_generic"
                and bool(frame["extended"])
                and arbitration_id in FIAT_500_CANDIDATE_IDS
            )
            if not is_validated_fiat_rpm and not is_fiat_candidate:
                unknown_can_ids.append(arbitration_id)
                continue

            if is_fiat_candidate:
                candidate_signals = _fiat_500_candidate_signals(frame)
                if candidate_signals:
                    observed_fiat_messages.add(arbitration_id)
                    if is_selected:
                        signals.extend(candidate_signals)
                else:
                    unknown_can_ids.append(arbitration_id)
                continue

            rpm = int.from_bytes(bytes(frame["data"])[2:4], "big")
            if not 0 <= rpm <= 8_000:
                unknown_can_ids.append(arbitration_id)
                continue
            observed_fiat_messages.add(arbitration_id)
            if not is_selected:
                continue
            signals.append(PassiveCanSignal(
                key="FIAT_ENGINE.ENGINE_RPM",
                arbitration_id=arbitration_id,
                message="FIAT_ENGINE",
                signal="ENGINE_RPM",
                display_name="Régime moteur",
                description=(
                    "Régime moteur Fiat CAN 29 bits validé par comparaison avec "
                    "le PID EOBD 01/0C sur la 500 2010 1.2."
                ),
                category="Moteur",
                value=rpm,
                raw_value=rpm,
                unit="tr/min",
                source_unit="tr/min",
                essential=True,
                updated_at_us=frame_timestamp,
                raw_hex=str(frame["raw_hex"]),
                confidence="validated",
            ))
            data = bytes(frame["data"])
            if len(data) >= 8:
                throttle_pct = round(data[7] * 100 / 255, 2)
                signals.append(PassiveCanSignal(
                    key="FIAT_ENGINE.THROTTLE_POSITION_CANDIDATE",
                    arbitration_id=arbitration_id,
                    message="FIAT_ENGINE",
                    signal="THROTTLE_POSITION_CANDIDATE",
                    display_name="Position papillon candidate",
                    description=(
                        "Octet 7 identifié comme papillon sur une implémentation ouverte "
                        "Fiat et corrélé aux accélérations de cette 500. À comparer au PID "
                        f"EOBD 01/11 avant validation. Source : {FIAT_ENGINE_CAN_NOTES_URL}"
                    ),
                    category="Moteur",
                    value=throttle_pct,
                    raw_value=data[7],
                    unit="%",
                    source_unit="octet brut",
                    factor=round(100 / 255, 8),
                    essential=False,
                    updated_at_us=frame_timestamp,
                    raw_hex=str(frame["raw_hex"]),
                    confidence="vehicle_observed_candidate",
                ))
                signals.append(PassiveCanSignal(
                    key="FIAT_ENGINE.AIR_LOAD_CANDIDATE_RAW",
                    arbitration_id=arbitration_id,
                    message="FIAT_ENGINE",
                    signal="AIR_LOAD_CANDIDATE_RAW",
                    display_name="Charge / pression d'air candidate",
                    description=(
                        "Octet 4 réactif à l'accélération. Une source Fiat proche le nomme "
                        "boost, mais aucune unité MAP n'est retenue sur ce moteur atmosphérique "
                        "avant comparaison au PID EOBD 01/0B."
                    ),
                    category="Moteur",
                    value=data[4],
                    raw_value=data[4],
                    unit="brut",
                    source_unit="octet brut",
                    essential=False,
                    updated_at_us=frame_timestamp,
                    raw_hex=str(frame["raw_hex"]),
                    confidence="vehicle_observed_candidate",
                ))

        obd_signals, obd_signal_count, obd_timestamps = _hybrid_obd_signals(since_us)
        signals.extend(obd_signals)
        custom_signals = _custom_signals(signals, vin or status.vin)
        signals.extend(custom_signals)
        selected_timestamps.extend(obd_timestamps)

        warnings = []
        if not status.active:
            warnings.append("Démarre une capture passive pour actualiser les capteurs.")
        if profile_key == "fiat_500_generic":
            warnings.append(
                "Profil Fiat actif : le régime CAN 0x0618A001 est validé, les PIDs "
                "OBD normalisés complètent le direct; le papillon et la charge d'air de "
                "0x0618A001 ainsi que les autres trames Fiat affichées "
                "restent marquées candidates; aucun décodeur Peugeot n'est appliqué."
            )
        else:
            warnings.append(
                f"Aucun décodeur direct validé pour {profile_key}; les trames restent brutes."
            )
        _append_hybrid_warning(status, warnings, obd_signal_count)
        signals.sort(key=lambda item: (item.category, item.message, item.signal))
        return PassiveSensorSnapshot(
            session_id=status.session_id,
            active=status.active,
            strict_passive=status.strict_passive,
            frame_count=status.frame_count,
            observed_can_id_count=len(frames),
            observed_message_count=len(observed_fiat_messages),
            unknown_can_id_count=len(set(unknown_can_ids)),
            unknown_can_ids=sorted(set(unknown_can_ids)),
            decoded_signal_count=len(signals),
            generated_at_us=time.time_ns() // 1000,
            cursor_us=max(selected_timestamps, default=since_us or 0),
            steering=PassiveSteeringSnapshot(),
            signals=signals,
            warnings=warnings,
            source_url=FIAT_500_CAN_NOTES_URL if profile_key == "fiat_500_generic" else None,
            hybrid_obd_enabled=status.hybrid_obd_enabled,
            hybrid_obd_ready=status.hybrid_obd_ready,
            obd_sample_count=status.obd_sample_count,
            obd_error=status.obd_error,
        )

    decoder = get_opendbc_decoder()
    overrides = load_overrides()
    signals: list[PassiveCanSignal] = []
    decoded_by_message: dict[str, dict[str, dict[str, Any]]] = {}
    observed_messages: set[str] = set()
    warnings: list[str] = []

    unknown_can_ids: list[int] = []
    total_signal_count = 0
    selected_timestamps: list[int] = []
    for frame in frames:
        arbitration_id = int(frame["arbitration_id"])
        frame_timestamp = int(frame["timestamp_us"])
        is_selected = since_us is None or frame_timestamp > since_us
        if is_selected:
            selected_timestamps.append(frame_timestamp)
        if arbitration_id == FRONT_SENSOR_CANDIDATE_ID:
            data = bytes(frame["data"])
            if is_selected and len(data) >= 5:
                for byte_index in (0, 2, 4):
                    signals.append(PassiveCanSignal(
                        key=f"FRONT_SENSOR_CANDIDATE.BYTE{byte_index}_RAW",
                        arbitration_id=arbitration_id,
                        message="FRONT_SENSOR_CANDIDATE",
                        signal=f"BYTE{byte_index}_RAW",
                        display_name=f"Radar avant · octet {byte_index} (brut)",
                        description=(
                            "Octet non documenté de 0x489, actif par à-coups pendant deux "
                            "essais dédiés au radar de stationnement avant ; la cadence de "
                            "bascule semble suivre la proximité perçue. Candidat non validé."
                        ),
                        category="ADAS / caméra",
                        value=data[byte_index],
                        raw_value=data[byte_index],
                        unit="brut",
                        source_unit="octet brut",
                        essential=False,
                        updated_at_us=frame_timestamp,
                        raw_hex=str(frame["raw_hex"]),
                        confidence="vehicle_observed_candidate",
                    ))
            continue
        message = decoder.message_for_frame(arbitration_id, bool(frame["extended"]))
        if message is None:
            unknown_can_ids.append(arbitration_id)
            continue
        observed_messages.add(message.name)
        total_signal_count += sum(
            not _is_metadata_signal(signal.name)
            and not (message.name == "STEERING" and signal.name == "ANGLE")
            for signal in message.signals
        )

        is_steering = message.name in {"STEERING", "STEERING_ALT"}
        if not is_selected and not is_steering:
            continue
        _, values, error = decoder.decode_frame(
            arbitration_id,
            bool(frame["extended"]),
            bytes(frame["data"]),
        )
        if values is None or error is not None:
            continue
        if is_steering:
            decoded_by_message[message.name] = values
        if not is_selected:
            continue
        for name, decoded in values.items():
            if _is_metadata_signal(name):
                continue
            if (
                message.name == "STEERING"
                and name == "ANGLE"
                and (_number(decoded.get("value")) or 0) > 1080
            ):
                # 0x7FFF / 3276.7° is the unavailable sentinel observed on this car.
                continue
            key = f"{message.name}.{name}"
            default_label, default_description, essential = metadata_for(
                key, message.name, name
            )
            override = overrides.get(key)
            factor = override.factor if override else 1.0
            offset = override.offset if override else 0.0
            raw_value = decoded.get("value")
            signals.append(PassiveCanSignal(
                key=key,
                arbitration_id=arbitration_id,
                message=message.name,
                signal=name,
                display_name=(override.label if override and override.label else default_label),
                description=(
                    override.description
                    if override and override.description
                    else default_description
                ),
                category=_category(message.name),
                ecu_family=_ecu_family(message.name),
                value=_display_value(raw_value, factor, offset),
                raw_value=raw_value,
                unit=(override.unit if override and override.unit is not None else decoded.get("unit")),
                source_unit=decoded.get("unit"),
                factor=factor,
                offset=offset,
                customized=override is not None,
                essential=essential,
                updated_at_us=int(frame["timestamp_us"]),
                raw_hex=str(frame["raw_hex"]),
                confidence=(
                    "validated"
                    if (message.name, name) in VALIDATED_SIGNALS
                    else "dbc_candidate"
                ),
            ))

    if not status.active:
        warnings.append("Démarre une capture passive pour actualiser les capteurs.")
    if not decoder.loaded:
        warnings.append(decoder.error or "Base OpenDBC indisponible.")
    if decoder.loaded:
        warnings.append(
            "Les signaux OpenDBC restent à confirmer sur Peugeot 308 T9 2018; "
            "les valeurs de direction marquées validées ont été vérifiées sur cette voiture."
        )

    obd_signals, obd_signal_count, obd_timestamps = _hybrid_obd_signals(since_us)
    signals.extend(obd_signals)
    custom_signals = _custom_signals(signals, vin or status.vin)
    signals.extend(custom_signals)
    selected_timestamps.extend(obd_timestamps)
    _append_hybrid_warning(status, warnings, obd_signal_count)

    signals.sort(key=lambda item: (item.category, item.message, item.signal))
    return PassiveSensorSnapshot(
        session_id=status.session_id,
        active=status.active,
        strict_passive=status.strict_passive,
        frame_count=status.frame_count,
        observed_can_id_count=len(frames),
        observed_message_count=len(observed_messages),
        unknown_can_id_count=len(unknown_can_ids),
        unknown_can_ids=sorted(unknown_can_ids),
        decoded_signal_count=total_signal_count + obd_signal_count + len(custom_signals),
        generated_at_us=time.time_ns() // 1000,
        cursor_us=max(selected_timestamps, default=since_us or 0),
        steering=_steering_from_messages(decoded_by_message),
        signals=signals,
        warnings=warnings,
        source_url=decoder.source_url if decoder.loaded else None,
        hybrid_obd_enabled=status.hybrid_obd_enabled,
        hybrid_obd_ready=status.hybrid_obd_ready,
        obd_sample_count=status.obd_sample_count,
        obd_error=status.obd_error,
    )
