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


VALIDATED_SIGNALS = {
    ("STEERING_ALT", "ANGLE"),
    ("STEERING_ALT", "RATE"),
    ("STEERING", "DRIVER_TORQUE"),
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


def passive_sensor_snapshot(since_us: int | None = None) -> PassiveSensorSnapshot:
    status = capture_manager.status()
    frames = capture_manager.latest_frames()
    profile_key = status.vehicle_profile or settings.vehicle_profile
    is_psa_profile = profile_key.startswith(("peugeot_", "psa_"))

    if not is_psa_profile:
        signals: list[PassiveCanSignal] = []
        unknown_can_ids: list[int] = []
        selected_timestamps: list[int] = []
        fiat_rpm_observed = False
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
            if not is_validated_fiat_rpm:
                unknown_can_ids.append(arbitration_id)
                continue

            rpm = int.from_bytes(bytes(frame["data"])[2:4], "big")
            if not 0 <= rpm <= 8_000:
                unknown_can_ids.append(arbitration_id)
                continue
            fiat_rpm_observed = True
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

        obd_signals, obd_signal_count, obd_timestamps = _hybrid_obd_signals(since_us)
        signals.extend(obd_signals)
        selected_timestamps.extend(obd_timestamps)

        warnings = []
        if not status.active:
            warnings.append("Démarre une capture passive pour actualiser les capteurs.")
        if profile_key == "fiat_500_generic":
            warnings.append(
                "Profil Fiat actif : le régime CAN 0x0618A001 est validé et les PIDs "
                "OBD normalisés complètent le direct; aucun décodeur Peugeot n'est appliqué."
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
            observed_message_count=1 if fiat_rpm_observed else 0,
            unknown_can_id_count=len(set(unknown_can_ids)),
            unknown_can_ids=sorted(set(unknown_can_ids)),
            decoded_signal_count=(1 if fiat_rpm_observed else 0) + obd_signal_count,
            generated_at_us=time.time_ns() // 1000,
            cursor_us=max(selected_timestamps, default=since_us or 0),
            steering=PassiveSteeringSnapshot(),
            signals=signals,
            warnings=warnings,
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
        decoded_signal_count=total_signal_count + obd_signal_count,
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
