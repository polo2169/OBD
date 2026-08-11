from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from statistics import median, pstdev
from typing import Any
import json
import math

from app.config import settings
from app.learn.manual_validation import load_manual_validations
from app.learn.models import ReplayData, ReplayValidation, SignalValidation
from app.learn.replay import prepare_replay


VALIDATION_VERSION = 7

LABELS = {
    "speed_kph": "Vitesse véhicule",
    "engine_rpm": "Régime moteur",
    "engine_load_pct": "Charge moteur calculée",
    "absolute_engine_load_pct": "Charge moteur absolue",
    "fuel_pressure_kpa": "Pression carburant basse pression",
    "manifold_pressure_kpa": "Pression du collecteur d’admission",
    "mass_air_flow_g_s": "Débit d’air massique",
    "throttle_position_pct": "Position du papillon",
    "relative_throttle_position_pct": "Position relative du papillon",
    "throttle_position_b_pct": "Position du papillon voie B",
    "throttle_position_c_pct": "Position du papillon voie C",
    "commanded_throttle_actuator_pct": "Commande de l’actionneur de papillon",
    "fiat_throttle_candidate_pct": "Position papillon CAN Fiat candidate",
    "fiat_air_load_candidate_raw": "Charge d’air CAN Fiat candidate",
    "ignition_advance_deg": "Avance à l’allumage",
    "fuel_injection_timing_deg": "Calage d’injection",
    "short_fuel_trim_pct": "Correction richesse court terme",
    "long_fuel_trim_pct": "Correction richesse long terme",
    "oxygen_sensor_b1s1_v": "Sonde lambda amont B1S1",
    "oxygen_sensor_b1s2_v": "Sonde lambda aval B1S2",
    "commanded_equivalence_ratio": "Richesse commandée",
    "evap_purge_pct": "Commande purge canister",
    "engine_runtime_s": "Temps de fonctionnement moteur",
    "fuel_level_pct": "Niveau de carburant OBD",
    "fuel_rate_lph": "Débit de carburant",
    "steering_angle_deg": "Angle du volant",
    "steering_rate_deg_s": "Vitesse du volant",
    "driver_torque": "Effort conducteur",
    "accelerator_pct": "Pédale d’accélérateur",
    "accelerator_secondary_pct": "Pédale d’accélérateur (voie redondante)",
    "relative_accelerator_position_pct": "Position relative de l’accélérateur",
    "engine_torque_nm": "Couple moteur",
    "idle_setpoint_rpm": "Consigne de ralenti",
    "cruise_xvv_state": "Régulateur · état brut (0x208)",
    "cruise_active_candidate": "Régulateur actif",
    "cruise_mode_raw": "Régulateur · position du sélecteur",
    "cruise_on": "Régulateur · ON",
    "cruise_activation_request": "Régulateur · demande active",
    "cruise_button_event": "Régulateur · dernière commande",
    "cruise_button_event_source": "Régulateur · source de la commande",
    "cruise_setpoint_kph": "Régulateur · consigne de vitesse",
    "fuel_consumption_candidate_mm3": "Consommation carburant passive candidate",
    "virtual_fuel_consumption_candidate_mm3": "Consommation carburant virtuelle candidate",
    "current_gear": "Rapport engagé",
    "target_gear": "Rapport cible",
    "gear_shift_active": "Changement de rapport",
    "longitudinal_accel_ms2": "Accélération longitudinale",
    "lateral_accel_ms2": "Accélération latérale",
    "yaw_rate_deg_s": "Vitesse de lacet",
    "brake_active": "Pédale de frein",
    "brake_pressure_raw": "Pression de freinage relative",
    "brake_system_state": "État du système de freinage",
    "turn_signal": "Clignotants",
    "low_beam": "Feux de croisement",
    "high_beam": "Feux de route",
    "reverse": "Marche arrière",
    "parking_brake": "Frein de stationnement",
    "driver_door": "Porte conducteur",
    "passenger_door": "Porte passager",
    "driver_seatbelt_state": "Ceinture conducteur",
    "passenger_seatbelt_state": "Ceinture passager",
    "oil_temperature_c": "Température d’huile",
    "coolant_temperature_c": "Température liquide de refroidissement",
    "intake_air_temperature_c": "Température d’air admission",
    "oil_pressure_switch": "Contacteur de pression d’huile",
    "battery_voltage_v": "Tension batterie",
    "battery_temperature_c": "Température batterie",
    "battery_charge_pct": "Charge batterie",
    "ambient_temperature_c": "Température extérieure",
    "atmospheric_pressure_hpa": "Pression atmosphérique",
    "fuel_liters_raw": "Niveau de carburant brut",
    "fuel_liters": "Niveau de carburant filtré",
    "wheel_front_left_kph": "Vitesse roue avant gauche",
    "wheel_front_right_kph": "Vitesse roue avant droite",
    "wheel_rear_left_kph": "Vitesse roue arrière gauche",
    "wheel_rear_right_kph": "Vitesse roue arrière droite",
    "latitude": "Latitude GPS",
    "longitude": "Longitude GPS",
    "gps_accuracy_m": "Précision GPS déclarée",
    "gps_altitude_m": "Altitude GPS",
    "gps_heading_deg": "Cap GPS",
    "gps_speed_kph": "Vitesse GPS",
}

PLAUSIBLE_RANGES: dict[str, tuple[float, float]] = {
    "speed_kph": (0, 260),
    "engine_rpm": (0, 8_000),
    "engine_load_pct": (0, 100),
    "absolute_engine_load_pct": (0, 300),
    "fuel_pressure_kpa": (0, 765),
    "manifold_pressure_kpa": (10, 255),
    "mass_air_flow_g_s": (0, 655.35),
    "throttle_position_pct": (0, 100),
    "relative_throttle_position_pct": (0, 100),
    "throttle_position_b_pct": (0, 100),
    "throttle_position_c_pct": (0, 100),
    "commanded_throttle_actuator_pct": (0, 100),
    "fiat_throttle_candidate_pct": (0, 100),
    "fiat_air_load_candidate_raw": (0, 255),
    "ignition_advance_deg": (-64, 63.5),
    "fuel_injection_timing_deg": (-210, 301.992),
    "short_fuel_trim_pct": (-100, 99.22),
    "long_fuel_trim_pct": (-100, 99.22),
    "oxygen_sensor_b1s1_v": (0, 1.275),
    "oxygen_sensor_b1s2_v": (0, 1.275),
    "commanded_equivalence_ratio": (0, 2),
    "evap_purge_pct": (0, 100),
    "engine_runtime_s": (0, 65_535),
    "fuel_level_pct": (0, 100),
    "fuel_rate_lph": (0, 3_276.75),
    "steering_angle_deg": (-1_080, 1_080),
    "steering_rate_deg_s": (-2_000, 2_000),
    "accelerator_pct": (0, 100),
    "accelerator_secondary_pct": (0, 100),
    "relative_accelerator_position_pct": (0, 100),
    "engine_torque_nm": (-600, 800),
    "idle_setpoint_rpm": (600, 1_200),
    "cruise_xvv_state": (0, 3),
    "cruise_mode_raw": (0, 3),
    "cruise_setpoint_kph": (0, 250),
    "driver_seatbelt_state": (0, 3),
    "passenger_seatbelt_state": (0, 3),
    "longitudinal_accel_ms2": (-15, 15),
    "lateral_accel_ms2": (-15, 15),
    "yaw_rate_deg_s": (-100, 100),
    "fuel_liters_raw": (0, 75),
    "fuel_liters": (0, 75),
    "oil_temperature_c": (-40, 180),
    "coolant_temperature_c": (-40, 140),
    "intake_air_temperature_c": (-50, 120),
    "battery_voltage_v": (8, 16.5),
    "battery_temperature_c": (-40, 100),
    "battery_charge_pct": (0, 100),
    "ambient_temperature_c": (-50, 70),
    "atmospheric_pressure_hpa": (750, 1_200),
    "speed_setpoint_kph": (0, 250),
    "wheel_front_left_kph": (0, 260),
    "wheel_front_right_kph": (0, 260),
    "wheel_rear_left_kph": (0, 260),
    "wheel_rear_right_kph": (0, 260),
    "latitude": (-90, 90),
    "longitude": (-180, 180),
    "gps_accuracy_m": (0, 100_000),
    "gps_altitude_m": (-500, 9_000),
    "gps_heading_deg": (0, 360),
    "gps_speed_kph": (0, 260),
}

EXPECTED_UNAVAILABLE = {
    "instant_fuel_consumption_lph": (
        "Consommation instantanée",
        "Aucun débit carburant passif fiable : les deux candidats PSA sont rejetés sur cette capture. Lire le PID OBD 01-5E ou un DID moteur confirmé.",
    ),
    "average_fuel_consumption_l_100km": (
        "Consommation moyenne",
        "Impossible à calculer sans débit carburant ou quantité injectée validée.",
    ),
    "oil_pressure_bar": (
        "Pression d’huile en bar",
        "Non disponible sur le CAN passif observé : seul le contacteur d’alerte logique est présent.",
    ),
    "fuel_rail_pressure_kpa": (
        "Pression de rampe d’injection",
        "Non diffusée dans les trames passives décodées ; lecture OBD/DID moteur nécessaire.",
    ),
    "manifold_pressure_kpa": (
        "Pression admission / suralimentation",
        "Non diffusée dans les trames passives décodées ; lecture OBD/DID moteur nécessaire.",
    ),
    "mass_air_flow_g_s": (
        "Débit d’air MAF",
        "Non diffusé dans les trames passives décodées ; lecture OBD moteur nécessaire.",
    ),
    "injector_correction": (
        "Corrections injecteurs",
        "Aucun DID constructeur confirmé pour cette capture.",
    ),
}

WHEEL_KEYS = (
    "wheel_front_left_kph",
    "wheel_front_right_kph",
    "wheel_rear_left_kph",
    "wheel_rear_right_kph",
)


def _source_path(session_id: str) -> Path:
    if Path(session_id).name != session_id or not session_id.startswith("learn-"):
        raise FileNotFoundError(f"Identifiant de session invalide : {session_id}")
    path = settings.session_dir / f"{session_id}.jsonl"
    if not path.exists():
        raise FileNotFoundError(f"Session introuvable : {session_id}")
    return path


def _is_number(value: Any) -> bool:
    return not isinstance(value, bool) and isinstance(value, (int, float)) and math.isfinite(float(value))


def _values(replay: ReplayData, key: str) -> list[Any]:
    return [value for point in replay.points if (value := getattr(point, key, None)) is not None]


def _transitions(values: list[Any]) -> int:
    return sum(current != previous for previous, current in zip(values, values[1:]))


def _correlation(pairs: list[tuple[float, float]]) -> float | None:
    if len(pairs) < 30:
        return None
    mean_x = sum(x for x, _ in pairs) / len(pairs)
    mean_y = sum(y for _, y in pairs) / len(pairs)
    xx = sum((x - mean_x) ** 2 for x, _ in pairs)
    yy = sum((y - mean_y) ** 2 for _, y in pairs)
    if xx <= 1e-12 or yy <= 1e-12:
        return None
    return sum((x - mean_x) * (y - mean_y) for x, y in pairs) / math.sqrt(xx * yy)


def _percentile(values: list[float], ratio: float) -> float:
    ordered = sorted(values)
    if not ordered:
        return 0.0
    return ordered[round((len(ordered) - 1) * ratio)]


def _validated(
    by_key: dict[str, SignalValidation],
    keys: tuple[str, ...],
    evidence: str,
) -> None:
    for key in keys:
        result = by_key.get(key)
        if result is None:
            continue
        result.evidence.append(evidence)
        if result.status != "suspicious":
            result.status = "validated"


def _base_validation(replay: ReplayData, key: str) -> SignalValidation:
    values = _values(replay, key)
    numeric = [float(value) for value in values if _is_number(value)]
    result = SignalValidation(
        key=key,
        label=LABELS.get(key, key.replace("_", " ").capitalize()),
        status="candidate" if values else "unavailable",
        sample_count=len(values),
        minimum=round(min(numeric), 3) if numeric else None,
        maximum=round(max(numeric), 3) if numeric else None,
        transitions=_transitions(values),
    )
    if not values:
        result.evidence.append("Aucune valeur décodée dans cette capture.")
        return result

    quality = replay.field_quality.get(key, "candidate")
    rejected = quality == "rejected_on_vehicle"
    if quality == "validated_on_fiat_500_vin":
        result.status = "validated"
        result.evidence.append("Fonction et sens confirmés physiquement par le conducteur sur cette Fiat.")
    elif quality in {"validated_on_vehicle", "validated_on_vehicle_state_only"}:
        result.status = "validated"
        result.evidence.append("Décodage et sens validés directement sur cette Peugeot.")
    elif rejected:
        result.status = "suspicious"
        result.evidence.append("Décodage rejeté sur cette Peugeot : la dynamique observée ne correspond pas à la grandeur annoncée.")

    expected = PLAUSIBLE_RANGES.get(key)
    if expected and numeric:
        low, high = expected
        outside = [value for value in numeric if value < low or value > high]
        if outside:
            result.status = "suspicious"
            result.evidence.append(
                f"{len(outside)} échantillon(s) hors plage plausible {low:g}…{high:g}."
            )
        elif result.status not in {"validated", "suspicious"}:
            result.status = "plausible"
            result.evidence.append(f"Toutes les valeurs restent dans la plage plausible {low:g}…{high:g}.")

    if key == "oil_pressure_switch":
        result.evidence.append("Signal logique seulement : aucune pression en bar ne peut être déduite.")
    elif result.transitions:
        result.evidence.append(f"{result.transitions} transition(s) observée(s) pendant l’essai.")
    else:
        result.evidence.append("Signal stable pendant cette capture ; sa réaction reste à provoquer et confirmer.")
    return result


def _apply_powertrain_checks(replay: ReplayData, by_key: dict[str, SignalValidation]) -> None:
    fiat_throttle_pairs = [
        (float(point.fiat_throttle_candidate_pct), float(point.throttle_position_pct))
        for point in replay.points
        if _is_number(point.fiat_throttle_candidate_pct)
        and _is_number(point.throttle_position_pct)
    ]
    fiat_throttle_correlation = _correlation(fiat_throttle_pairs)
    if fiat_throttle_correlation is not None:
        candidate_span = max(left for left, _ in fiat_throttle_pairs) - min(left for left, _ in fiat_throttle_pairs)
        obd_span = max(right for _, right in fiat_throttle_pairs) - min(right for _, right in fiat_throttle_pairs)
        evidence = (
            f"Papillon CAN Fiat comparé au PID EOBD 01/11 sur {len(fiat_throttle_pairs)} points : "
            f"corrélation {fiat_throttle_correlation:.3f}, amplitudes {candidate_span:.1f}/{obd_span:.1f} %."
        )
        result = by_key.get("fiat_throttle_candidate_pct")
        if result:
            result.evidence.append(evidence)
            if result.status != "suspicious" and fiat_throttle_correlation >= 0.9 and min(candidate_span, obd_span) >= 5:
                result.status = "validated"

    fiat_air_pairs = [
        (float(point.fiat_air_load_candidate_raw), float(point.manifold_pressure_kpa))
        for point in replay.points
        if _is_number(point.fiat_air_load_candidate_raw)
        and _is_number(point.manifold_pressure_kpa)
    ]
    fiat_air_correlation = _correlation(fiat_air_pairs)
    if fiat_air_correlation is not None:
        evidence = (
            f"Octet d'air Fiat comparé au MAP EOBD 01/0B sur {len(fiat_air_pairs)} points : "
            f"corrélation {fiat_air_correlation:.3f}."
        )
        result = by_key.get("fiat_air_load_candidate_raw")
        if result:
            result.evidence.append(evidence)
            if result.status != "suspicious" and abs(fiat_air_correlation) >= 0.85:
                result.status = "plausible"

    idle_pairs = [
        (float(point.engine_rpm), float(point.idle_setpoint_rpm))
        for point in replay.points
        if _is_number(point.engine_rpm)
        and _is_number(point.idle_setpoint_rpm)
        and 500 < float(point.engine_rpm) < 1_100
        and (point.speed_kph or 0) < 1
        and (point.accelerator_pct or 0) < 1
    ]
    if len(idle_pairs) >= 30:
        idle_error = sum(abs(actual - target) for actual, target in idle_pairs) / len(idle_pairs)
        evidence = (
            f"Régime réel comparé à la consigne sur {len(idle_pairs)} points de ralenti : "
            f"écart moyen {idle_error:.1f} tr/min (médianes {median(x for x, _ in idle_pairs):.0f}/{median(y for _, y in idle_pairs):.0f})."
        )
        if idle_error <= 60:
            _validated(by_key, ("engine_rpm", "idle_setpoint_rpm"), evidence)

    accelerator_pairs = [
        (float(point.accelerator_pct), float(point.accelerator_secondary_pct))
        for point in replay.points
        if _is_number(point.accelerator_pct) and _is_number(point.accelerator_secondary_pct)
    ]
    accelerator_correlation = _correlation(accelerator_pairs)
    if accelerator_correlation is not None:
        accelerator_mae = sum(abs(left - right) for left, right in accelerator_pairs) / len(accelerator_pairs)
        evidence = (
            f"Deux trames moteur indépendantes comparées sur {len(accelerator_pairs)} points : "
            f"corrélation {accelerator_correlation:.3f}, écart moyen {accelerator_mae:.2f} %."
        )
        if accelerator_correlation >= 0.94 and accelerator_mae <= 3:
            _validated(by_key, ("accelerator_pct", "accelerator_secondary_pct"), evidence)

    torque_pairs = [
        (float(point.accelerator_pct), float(point.engine_torque_nm))
        for point in replay.points
        if (point.engine_rpm or 0) > 500
        and _is_number(point.accelerator_pct)
        and _is_number(point.engine_torque_nm)
    ]
    torque_correlation = _correlation(torque_pairs)
    if torque_correlation is not None:
        evidence = f"Couple moteur cohérent avec la pédale sur {len(torque_pairs)} points : corrélation {torque_correlation:.3f}."
        result = by_key.get("engine_torque_nm")
        if result:
            result.evidence.append(evidence)
            if result.status != "suspicious" and torque_correlation >= 0.85:
                result.status = "validated"

    acceleration_pairs: list[tuple[float, float]] = []
    for previous, point in zip(replay.points, replay.points[1:]):
        elapsed_s = (point.t_ms - previous.t_ms) / 1000
        if elapsed_s <= 0 or not _is_number(point.longitudinal_accel_ms2):
            continue
        speed_before = float(previous.speed_kph or 0) / 3.6
        speed_after = float(point.speed_kph or 0) / 3.6
        acceleration_pairs.append((float(point.longitudinal_accel_ms2), (speed_after - speed_before) / elapsed_s))
    acceleration_correlation = _correlation(acceleration_pairs)
    if acceleration_correlation is not None:
        evidence = f"Comparaison avec la dérivée de vitesse sur {len(acceleration_pairs)} points : corrélation {acceleration_correlation:.3f}."
        if acceleration_correlation >= 0.85:
            _validated(by_key, ("longitudinal_accel_ms2",), evidence)

    running_voltage = [
        float(point.battery_voltage_v)
        for point in replay.points
        if _is_number(point.battery_voltage_v) and (point.engine_rpm or 0) > 500
    ]
    stopped_voltage = [
        float(point.battery_voltage_v)
        for point in replay.points
        if _is_number(point.battery_voltage_v) and (point.engine_rpm or 0) < 100
    ]
    if running_voltage and stopped_voltage:
        running_median = median(running_voltage)
        stopped_median = median(stopped_voltage)
        evidence = f"Tension médiane {running_median:.2f} V moteur tournant contre {stopped_median:.2f} V moteur arrêté."
        if 13 <= running_median <= 15 and running_median - stopped_median >= 0.5:
            _validated(by_key, ("battery_voltage_v",), evidence)

    oil_pairs = [
        ((point.engine_rpm or 0) < 500, bool(point.oil_pressure_switch))
        for point in replay.points
        if point.oil_pressure_switch is not None
    ]
    if oil_pairs:
        agreement = sum(engine_stopped == switch_active for engine_stopped, switch_active in oil_pairs) / len(oil_pairs)
        evidence = (
            f"Contacteur actif moteur arrêté et inactif moteur tournant sur "
            f"{agreement * 100:.2f}% de {len(oil_pairs)} points."
        )
        if agreement >= 0.95:
            _validated(by_key, ("oil_pressure_switch",), evidence)


def _apply_brake_checks(replay: ReplayData, by_key: dict[str, SignalValidation]) -> None:
    pairs = [
        (bool(point.brake_active), float(point.brake_pressure_raw))
        for point in replay.points
        if point.brake_active is not None and _is_number(point.brake_pressure_raw)
    ]
    active = [pressure for brake, pressure in pairs if brake]
    inactive = [pressure for brake, pressure in pairs if not brake]
    if not active or not inactive:
        return
    active_mean = sum(active) / len(active)
    inactive_mean = sum(inactive) / len(inactive)
    evidence = (
        f"Pression brute moyenne {active_mean:.1f} frein actif contre {inactive_mean:.1f} au repos; "
        "la valeur est relative et ne doit pas être affichée en bar."
    )
    if active_mean - inactive_mean >= 30:
        _validated(by_key, ("brake_active", "brake_pressure_raw"), evidence)


def _apply_fuel_checks(replay: ReplayData, by_key: dict[str, SignalValidation]) -> None:
    raw_points = [
        (float(point.fuel_liters_raw), float(point.longitudinal_accel_ms2))
        for point in replay.points
        if _is_number(point.fuel_liters_raw) and _is_number(point.longitudinal_accel_ms2)
    ]
    raw = by_key.get("fuel_liters_raw")
    filtered = by_key.get("fuel_liters")
    if raw and len(raw_points) >= 30:
        fuel_values = [fuel for fuel, _ in raw_points]
        acceleration_values = [acceleration for _, acceleration in raw_points]
        window_size = max(3, round(30_000 / replay.sample_period_ms))
        rolling_sum = 0.0
        rolling: list[float] = []
        high_pass: list[float] = []
        for value in fuel_values:
            rolling.append(value)
            rolling_sum += value
            if len(rolling) > window_size:
                rolling_sum -= rolling.pop(0)
            high_pass.append(value - rolling_sum / len(rolling))
        best_correlation: float | None = None
        best_lag = 0
        for lag in range(-10, 11):
            if lag < 0:
                pairs = list(zip(high_pass[-lag:], acceleration_values[:lag]))
            elif lag > 0:
                pairs = list(zip(high_pass[:-lag], acceleration_values[lag:]))
            else:
                pairs = list(zip(high_pass, acceleration_values))
            correlation = _correlation(pairs)
            if correlation is not None and (best_correlation is None or abs(correlation) > abs(best_correlation)):
                best_correlation = correlation
                best_lag = lag
        largest_step = max(abs(current - previous) for previous, current in zip(fuel_values, fuel_values[1:]))
        if best_correlation is not None:
            raw.evidence.append(
                f"Le signal brut suit l’accélération longitudinale (corrélation maximale {abs(best_correlation):.3f}, décalage ~{abs(best_lag) * replay.sample_period_ms / 1000:.1f} s) : comportement compatible avec le ballottement du carburant."
            )
        raw.evidence.append(
            f"Variation brute maximale {largest_step:.1f} L en {replay.sample_period_ms} ms : ne pas utiliser directement comme quantité de carburant."
        )
        if raw.status != "suspicious":
            raw.status = "plausible"

    if filtered:
        filtered.evidence.append(
            "Filtre exponentiel causal de 120 s appliqué au flotteur pour amortir les accélérations et les virages."
        )
        if filtered.status != "suspicious":
            filtered.status = "plausible"

    consumption = by_key.get("fuel_consumption_candidate_mm3")
    consumption_values = [
        float(value)
        for value in _values(replay, "fuel_consumption_candidate_mm3")
        if _is_number(value)
    ]
    if consumption and consumption_values:
        consumption.status = "suspicious"
        consumption.evidence.append(
            f"Le champ parcourt {len(set(consumption_values))} valeurs et ne suit ni le régime, ni la pédale, ni le couple : ce n'est pas une consommation exploitable sur cette 308."
        )

    virtual = by_key.get("virtual_fuel_consumption_candidate_mm3")
    virtual_values = [
        float(value)
        for value in _values(replay, "virtual_fuel_consumption_candidate_mm3")
        if _is_number(value)
    ]
    if virtual and virtual_values and len(set(virtual_values)) == 1:
        virtual.status = "unavailable"
        virtual.evidence.append("Champ constamment nul pendant tout l’essai : aucune information de consommation disponible.")


def _apply_wheel_checks(replay: ReplayData, by_key: dict[str, SignalValidation]) -> None:
    moving = []
    complete = []
    for point in replay.points:
        wheels = [getattr(point, key) for key in WHEEL_KEYS]
        vehicle_speed = point.speed_kph
        if (vehicle_speed or 0) > 3 or any(_is_number(value) and float(value) > 3 for value in wheels):
            moving.append(point)
        if all(_is_number(value) for value in wheels):
            complete.append((point, [float(value) for value in wheels]))
    if not complete:
        return

    spreads = [max(values) - min(values) for _, values in complete]
    max_spread = max(spreads)
    mean_spread = sum(spreads) / len(spreads)
    dropout_count = sum(
        1 for point in moving
        if not all(_is_number(getattr(point, key)) for key in WHEEL_KEYS)
    )
    straight_spreads = [
        max(values) - min(values)
        for point, values in complete
        if (point.speed_kph or 0) > 10 and abs(point.steering_angle_deg or 0) < 5
    ]
    percentile_95_straight = _percentile(straight_spreads, 0.95) if straight_spreads else max_spread
    speed_diffs = [
        abs(sum(values) / 4 - float(point.speed_kph))
        for point, values in complete
        if _is_number(point.speed_kph) and float(point.speed_kph) > 3
    ]
    mean_speed_diff = sum(speed_diffs) / len(speed_diffs) if speed_diffs else None
    coherent = percentile_95_straight <= 2.5 and (mean_speed_diff is None or mean_speed_diff <= 1) and dropout_count == 0
    evidence = (
        f"4 roues comparées sur {len(complete)} échantillons : écart moyen {mean_spread:.2f} km/h, "
        f"95e percentile en ligne droite {percentile_95_straight:.2f} km/h "
        f"({max_spread:.2f} km/h tous virages compris), {dropout_count} perte(s) en roulage."
    )
    for key in WHEEL_KEYS:
        result = by_key.get(key)
        if result is None:
            continue
        result.evidence.append(evidence)
        if result.status != "suspicious":
            result.status = "validated" if coherent else "plausible"
    speed = by_key.get("speed_kph")
    if speed and mean_speed_diff is not None:
        speed.evidence.append(f"Écart moyen avec la moyenne des quatre roues : {mean_speed_diff:.2f} km/h.")
        if speed.status != "suspicious":
            speed.status = "validated" if coherent else "plausible"


def _apply_gear_checks(replay: ReplayData, by_key: dict[str, SignalValidation]) -> None:
    gears = [point.current_gear for point in replay.points if point.current_gear is not None]
    target_gears = [point.target_gear for point in replay.points if point.target_gear is not None]
    valid_codes = set(range(0, 7)) | {9}
    invalid = sorted({value for value in gears + target_gears if value not in valid_codes})
    for key, values in (("current_gear", gears), ("target_gear", target_gears)):
        result = by_key.get(key)
        if not result or not values:
            continue
        result.evidence.append(f"Codes observés : {', '.join('R' if value == 9 else str(value) for value in sorted(set(values)))}.")
        if invalid:
            result.status = "suspicious"
            result.evidence.append(f"Codes inattendus : {invalid}.")
        elif result.status != "suspicious":
            result.status = "plausible"

    comparable = [
        (point.current_gear == 9, bool(point.reverse))
        for point in replay.points
        if point.current_gear is not None and point.reverse is not None
    ]
    reverse_samples = sum(gear_is_reverse for gear_is_reverse, _ in comparable)
    if not comparable or reverse_samples == 0:
        return
    agreement = sum(gear_is_reverse == reverse for gear_is_reverse, reverse in comparable) / len(comparable)
    evidence = f"Le code rapport 9 et le bit marche arrière concordent sur {agreement * 100:.1f}% de {len(comparable)} échantillons."
    for key in ("current_gear", "reverse"):
        result = by_key.get(key)
        if result:
            result.evidence.append(evidence)
            if result.status != "suspicious":
                result.status = "validated" if agreement >= 0.9 else "plausible"


def _haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    earth_radius_m = 6_371_000.0
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    d_phi = math.radians(lat2 - lat1)
    d_lambda = math.radians(lon2 - lon1)
    a = math.sin(d_phi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(d_lambda / 2) ** 2
    return 2 * earth_radius_m * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def _apply_gps_checks(replay: ReplayData, by_key: dict[str, SignalValidation]) -> None:
    """Cross-check the GPS track and speed against the independent CAN reconstruction.

    The point isn't to validate GPS as a technology, but to confirm that *this*
    capture's position fusion (browser GPS, dead reckoning, or a blend of both)
    agrees with the wheel/yaw-based distance and speed already used elsewhere.
    """
    fixes = [
        point for point in replay.points
        if _is_number(point.latitude) and _is_number(point.longitude)
    ]
    if len(fixes) >= 5:
        track_m = sum(
            _haversine_m(a.latitude, a.longitude, b.latitude, b.longitude)
            for a, b in zip(fixes, fixes[1:])
        )
        can_distance_m = replay.distance_km * 1000
        evidence = (
            f"Trace GPS ({len(fixes)} points) : {track_m / 1000:.2f} km contre "
            f"{replay.distance_km:.2f} km reconstruits par le CAN (roues/lacet)."
        )
        coherent: bool | None = None
        if can_distance_m > 200:
            relative_error = abs(track_m - can_distance_m) / can_distance_m
            evidence += f" Écart relatif {relative_error * 100:.0f}%."
            coherent = relative_error <= 0.20

        accuracies = [point.gps_accuracy_m for point in replay.points if point.gps_accuracy_m is not None]
        median_accuracy = median(accuracies) if accuracies else None
        if median_accuracy is not None:
            evidence += f" Précision déclarée médiane {median_accuracy:.0f} m."

        for key in ("latitude", "longitude"):
            result = by_key.get(key)
            if result is None:
                continue
            result.evidence.append(evidence)
            if result.status == "suspicious":
                continue
            if coherent is False or (median_accuracy is not None and median_accuracy > 100):
                result.status = "suspicious"
            elif coherent is True and (median_accuracy is None or median_accuracy <= 50):
                result.status = "validated"
            else:
                result.status = "plausible"

    speed_pairs = [
        (float(point.gps_speed_kph), float(point.speed_kph))
        for point in replay.points
        if _is_number(point.gps_speed_kph) and _is_number(point.speed_kph)
    ]
    speed_correlation = _correlation(speed_pairs)
    if speed_correlation is not None:
        result = by_key.get("gps_speed_kph")
        if result:
            result.evidence.append(
                f"Vitesse GPS comparée à la vitesse CAN sur {len(speed_pairs)} points : "
                f"corrélation {speed_correlation:.3f}."
            )
            if result.status != "suspicious":
                result.status = "validated" if speed_correlation >= 0.9 else "plausible"


def _apply_cruise_checks(replay: ReplayData, by_key: dict[str, SignalValidation]) -> None:
    result = by_key.get("cruise_xvv_state")
    if result is None:
        return

    active_pedal = [
        float(point.accelerator_pct)
        for point in replay.points
        if point.cruise_xvv_state == 2 and _is_number(point.accelerator_pct)
    ]
    baseline_pedal = [
        float(point.accelerator_pct)
        for point in replay.points
        if point.cruise_xvv_state == 0
        and not point.brake_active
        and (point.speed_kph or 0) > 30
        and _is_number(point.accelerator_pct)
    ]
    active_speed = [
        float(point.speed_kph)
        for point in replay.points
        if point.cruise_xvv_state == 2 and _is_number(point.speed_kph)
    ]
    baseline_speed = [
        float(point.speed_kph)
        for point in replay.points
        if point.cruise_xvv_state == 0
        and not point.brake_active
        and (point.speed_kph or 0) > 30
        and _is_number(point.speed_kph)
    ]

    if len(active_pedal) < 20 or len(baseline_pedal) < 20:
        result.evidence.append(
            f"Échantillon insuffisant pour comparer état actif ({len(active_pedal)} points) et "
            f"conduite normale ({len(baseline_pedal)} points) ; corrélation à confirmer sur une capture plus longue."
        )
        return

    active_pedal_median = median(active_pedal)
    baseline_pedal_median = median(baseline_pedal)
    active_speed_std = pstdev(active_speed) if len(active_speed) > 1 else 0.0
    baseline_speed_std = pstdev(baseline_speed) if len(baseline_speed) > 1 else 0.0

    evidence = (
        f"Pédale médiane {active_pedal_median:.1f}% pendant l'état actif contre {baseline_pedal_median:.1f}% "
        f"en conduite normale à vitesse comparable ({len(active_pedal)}/{len(baseline_pedal)} points) ; "
        f"écart-type de vitesse {active_speed_std:.2f}/{baseline_speed_std:.2f} km/h."
    )
    pedal_released = active_pedal_median <= baseline_pedal_median - 10
    speed_held = active_speed_std <= baseline_speed_std + 1.5

    for key in ("cruise_xvv_state", "cruise_active_candidate"):
        target = by_key.get(key)
        if target is None:
            continue
        target.evidence.append(evidence)
        if target.status != "suspicious":
            target.status = "plausible" if pedal_released and speed_held else "candidate"


def _apply_cruise_setpoint_check(replay: ReplayData, by_key: dict[str, SignalValidation]) -> None:
    result = by_key.get("cruise_setpoint_kph")
    if result is None:
        return

    engage_errors: list[float] = []
    previous_state: int | None = None
    for point in replay.points:
        state = point.cruise_xvv_state
        if (
            state == 2
            and previous_state != 2
            and _is_number(point.speed_kph)
            and _is_number(point.cruise_setpoint_kph)
        ):
            engage_errors.append(abs(float(point.cruise_setpoint_kph) - float(point.speed_kph)))
        previous_state = state

    if not engage_errors:
        result.evidence.append(
            "Aucun engagement complet observé dans cette capture pour comparer la consigne "
            "à la vitesse réelle au moment de l'activation."
        )
        return

    mean_error = sum(engage_errors) / len(engage_errors)
    evidence = (
        f"Écart moyen entre consigne et vitesse réelle à l'instant de l'engagement : "
        f"{mean_error:.1f} km/h sur {len(engage_errors)} engagement(s)."
    )
    result.evidence.append(evidence)
    if result.status != "suspicious":
        result.status = "plausible" if mean_error <= 8 else "candidate"


def _apply_manual_overrides(result: ReplayValidation) -> ReplayValidation:
    """Overlay human-confirmed/rejected signals on top of the cached, automated report.

    Manual records live in their own small store (see manual_validation.py) so a
    confirmation made from the UI takes effect immediately without invalidating
    or recomputing the versioned, cached statistical report.
    """
    manual = load_manual_validations()
    if not manual:
        return result

    signals = [signal.model_copy(deep=True) for signal in result.signals]
    changed = False
    for signal in signals:
        record = manual.get(signal.key)
        if record is None:
            continue
        changed = True
        signal.manual_validation = record.validated
        note_suffix = f" « {record.note} »" if record.note else ""
        if record.validated:
            signal.status = "validated"
            signal.evidence.append(f"Confirmé manuellement le {record.validated_at}{note_suffix}.")
        else:
            signal.status = "suspicious"
            signal.evidence.append(f"Marqué invalide manuellement le {record.validated_at}{note_suffix}.")

    if not changed:
        return result

    order = {"suspicious": 0, "candidate": 1, "plausible": 2, "validated": 3, "unavailable": 4}
    signals.sort(key=lambda item: (order[item.status], item.label.casefold()))
    return result.model_copy(update={
        "signals": signals,
        "validated_count": sum(signal.status == "validated" for signal in signals),
        "plausible_count": sum(signal.status == "plausible" for signal in signals),
        "suspicious_count": sum(signal.status == "suspicious" for signal in signals),
    })


def validate_replay(session_id: str, force: bool = False) -> ReplayValidation:
    source = _source_path(session_id)
    output = source.with_suffix(".validation.json")
    if not force and output.exists() and output.stat().st_mtime_ns >= source.stat().st_mtime_ns:
        try:
            cached = ReplayValidation.model_validate_json(output.read_text(encoding="utf-8"))
            if cached.version == VALIDATION_VERSION:
                return _apply_manual_overrides(cached)
        except (OSError, ValueError, json.JSONDecodeError):
            pass

    replay = prepare_replay(session_id, force=force)
    keys = sorted(set(replay.available_fields) - {
        "x_m", "y_m", "heading_deg", "distance_m",
    })
    signals = [_base_validation(replay, key) for key in keys]
    existing_keys = {signal.key for signal in signals}
    for key, (label, evidence) in EXPECTED_UNAVAILABLE.items():
        if key in existing_keys:
            continue
        signals.append(SignalValidation(
            key=key,
            label=label,
            status="unavailable",
            evidence=[evidence],
        ))
    by_key = {signal.key: signal for signal in signals}
    _apply_powertrain_checks(replay, by_key)
    _apply_brake_checks(replay, by_key)
    _apply_fuel_checks(replay, by_key)
    _apply_wheel_checks(replay, by_key)
    _apply_gear_checks(replay, by_key)
    _apply_gps_checks(replay, by_key)
    _apply_cruise_checks(replay, by_key)
    _apply_cruise_setpoint_check(replay, by_key)
    order = {"suspicious": 0, "candidate": 1, "plausible": 2, "validated": 3, "unavailable": 4}
    signals.sort(key=lambda item: (order[item.status], item.label.casefold()))
    result = ReplayValidation(
        version=VALIDATION_VERSION,
        session_id=session_id,
        generated_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        signal_count=len(signals),
        validated_count=sum(signal.status == "validated" for signal in signals),
        plausible_count=sum(signal.status == "plausible" for signal in signals),
        suspicious_count=sum(signal.status == "suspicious" for signal in signals),
        signals=signals,
        warnings=[
            "Validé signifie cohérent avec une seconde information indépendante dans cette capture, ou déjà confirmé physiquement sur le véhicule.",
            "Plausible ne remplace pas une mesure étalon ni la documentation constructeur.",
            "Le contacteur d’huile est validé comme alerte logique, mais ne fournit aucune pression en bar.",
            "Le niveau carburant 0x612 est affiché après filtrage du ballottement ; les champs de consommation passive restent rejetés.",
        ],
    )
    temporary = output.with_suffix(output.suffix + ".tmp")
    temporary.write_text(result.model_dump_json(indent=2), encoding="utf-8")
    temporary.replace(output)
    return _apply_manual_overrides(result)
