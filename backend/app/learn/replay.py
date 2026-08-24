from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from statistics import median
from typing import Any, Literal
from bisect import bisect_right
import json
import math
import threading

from app.config import settings
from app.learn.models import ReplayData, ReplayEvent, ReplayGpsPoint, ReplaySample
from app.learn.opendbc import get_opendbc_decoder
from app.learn.session_vehicle import load_session_vehicle, session_vehicle_mtime_ns


CACHE_VERSION = 38
SAMPLE_PERIOD_US = 100_000
WHEELBASE_M = 2.62
STEERING_RATIO = 15.3

# Consommation dérivée du compteur de volume carburant 0x488 (Dat_CMM,
# P021_Com_volFlCons) et de la vitesse 0x38D. Le calculateur ne transmet pas
# de L/100km : voir database/psa/dbc/peugeot_308_t9_2018_checksums.yaml pour
# la validation sur capture véhicule (589,24 s, compteur observé 0..254 avec
# rebouclage confirmé, 0xFF jamais observé) et le détail du raisonnement.
# facteur DBC officiel : 1 tick (octet brut) = 80 mm³.
FUEL_TICK_MODULUS_MM3 = 255 * 80
FUEL_RATE_WINDOW_MS = 1500
# Au-delà, on considère la synchronisation perdue (perte de trames, coupure
# contact) plutôt que de calculer un delta aberrant sur un grand intervalle.
FUEL_MAX_GAP_MS = 5000
# Écarte un intervalle dont le débit instantané impliqué dépasse largement ce
# qu'un moteur de cette gamme peut consommer, révélateur d'une resynchronisation
# du compteur (redémarrage ECU) plutôt que d'une consommation réelle.
FUEL_IMPLAUSIBLE_RATE_LPH = 80.0
FUEL_MIN_SPEED_FOR_L100KM_KPH = 5.0

# Non documenté dans opendbc ; extrait en octets bruts, hors du pipeline de
# décodage par message nommé. Candidat radar de stationnement avant, non validé.
FRONT_SENSOR_CANDIDATE_ID = 0x489

# Non documenté. Octets 2/4/5 quasi identiques entre eux, dérive lente et
# plage plausible (8.9-22.1°C sur un essai) : candidat température intérieure
# ou ambiante, non validé. Octet 0 et octet 3 sont en fait deux copies
# redondantes de régime moteur et pédale accélérateur (formule exacte
# retrouvée par corrélation, cf accelerator_pct_3b8_candidate /
# engine_rpm_3b8_candidate) : ce n'est donc pas de la climatisation.
CLIMATE_CANDIDATE_ID = 0x3B8

# Non documenté. Octet 1 = copie de la pédale accélérateur (formule exacte
# byte ≈ pct × 2, confirmée par corrélation). Octet 3 corrèle avec la vitesse
# et le rapport engagé mais avec seulement 4-5 valeurs distinctes : hypothèse
# d'une table de limite couple/vitesse par rapport, non confirmée.
ENGINE_ACCEL_SHADOW_CANDIDATE_ID = 0x2E8

# Non documenté. Octet 5 anti-corrélé au régime moteur (r≈-0.79) mais avec
# seulement 5-7 valeurs distinctes sur un essai : hypothèse d'un état moteur
# discret (ralenti, Start&Stop, verrouillage convertisseur), non confirmée.
ENGINE_STATE_CANDIDATE_ID = 0x57C

# Non documenté. Octet 0 corrèle modérément avec la vitesse (r≈0.5) : piste
# faible, non confirmée.
SPEED_CANDIDATE_ID = 0x389

# Non documenté. Octet 7 bascule 0/1 de façon identique dans deux essais
# dédiés portière arrière gauche et portière arrière droite : hypothèse d'un
# indicateur générique "au moins une porte arrière ouverte", non confirmée
# individuellement (contrairement à 0x412 octet 6 bits 0x20/0x40, validés).
REAR_DOOR_AJAR_CANDIDATE_ID = 0x78D

TARGET_IDS = {
    0x208,  # moteur
    0x228,  # accélérateur
    0x2F5,  # couple volant
    0x305,  # angle volant
    0x30D,  # vitesses de roues
    0x329,  # défaut boîte de vitesses
    0x348,  # états ESP / voyant moteur
    0x349,  # rapport cible / changement de vitesse
    0x34D,  # intervention ESP
    0x38D,  # vitesse véhicule
    0x3AD,  # frein de stationnement / EasyMove ESP
    0x3CD,  # freinage
    0x3F2,  # maintien dans la voie
    0x412,  # BSI
    0x452,  # commandes conducteur
    0x488,  # températures moteur / huile / admission
    0x50D,  # intervention ABS
    0x50E,  # régulateur - consigne de vitesse (Dat_CLIM)
    0x552,  # kilométrage absolu (BSI)
    0x56E,  # pédale accélérateur
    0x572,  # retenue
    0x588,  # état pression d'huile / pression atmosphérique
    0x592,  # batterie
    0x5B2,  # température extérieure
    0x612,  # éclairage
}

STATE_FIELDS = tuple(
    field
    for field in ReplaySample.model_fields
    if field not in {
        "t_ms",
        "latitude",
        "longitude",
        "gps_accuracy_m",
        "gps_altitude_m",
        "gps_heading_deg",
        "gps_speed_kph",
        "x_m",
        "y_m",
        "heading_deg",
        "distance_m",
        "cruise_probable",
        "cruise_confidence",
        "cruise_detection_state",
        "cruise_detection_reason",
        "cruise_switch_candidate",
        "cruise_active_candidate",
        "cruise_button_event",
        "cruise_button_event_source",
        "cruise_setpoint_direction",
        "cruise_setpoint_step_kph",
    }
)

FIELD_QUALITY = {
    "odometer_km": "validated_on_vehicle",
    "steering_angle_deg": "validated_on_vehicle",
    "steering_rate_deg_s": "validated_on_vehicle",
    "driver_torque": "validated_on_vehicle",
    "speed_kph": "opendbc_candidate",
    "engine_rpm": "opendbc_candidate",
    "accelerator_pct": "opendbc_candidate",
    "accelerator_secondary_pct": "cross_check_only",
    "engine_torque_nm": "opendbc_candidate",
    "idle_setpoint_rpm": "opendbc_candidate",
    "climate_pressure_kpa": "opendbc_candidate",
    "fuel_consumption_candidate_mm3": "rejected_on_vehicle",
    "virtual_fuel_consumption_candidate_mm3": "rejected_on_vehicle",
    "can_fuel_rate_lph": "derived_from_0x488_0x38d_vehicle_validated_counter",
    "can_instant_consumption_l_100km": "derived_from_0x488_0x38d_vehicle_validated_counter",
    "can_trip_fuel_l": "derived_from_0x488_0x38d_vehicle_validated_counter",
    "current_gear": "vehicle_validated_0x348_byte0_high_nibble_with_legacy_fallback",
    "target_gear": "opendbc_candidate",
    "gear_shift_active": "opendbc_candidate",
    "drivetrain_engaged_state": "opendbc_candidate_raw_state",
    "longitudinal_accel_ms2": "opendbc_candidate",
    "lateral_accel_ms2": "validated_on_vehicle",
    "yaw_rate_deg_s": "validated_on_vehicle",
    "brake_active": "opendbc_candidate",
    "brake_system_state": "opendbc_candidate",
    "brake_pressure_raw": "opendbc_candidate_unscaled",
    "turn_signal": "opendbc_candidate",
    "low_beam": "opendbc_candidate",
    "high_beam": "opendbc_candidate",
    "reverse": "opendbc_candidate",
    "parking_brake": "vehicle_validated_0x3ad_state_1_applied",
    "parking_brake_state": "vehicle_validated_0x3ad_four_state",
    "driver_door": "validated_on_vehicle_0x412_byte6_0x08",
    "passenger_door": "opendbc_candidate",
    "rear_left_door": "validated_dedicated_test_0x412_byte6_0x20",
    "rear_right_door": "validated_dedicated_test_0x412_byte6_0x40",
    "rear_door_ajar_candidate": "experimental_unvalidated_candidate",
    "front_wiper_status": "opendbc_candidate",
    "fuel_liters_raw": "vehicle_signal_slosh_affected",
    "fuel_liters": "filtered_vehicle_signal",
    "oil_temperature_c": "opendbc_candidate",
    "coolant_temperature_c": "opendbc_candidate",
    "intake_air_temperature_c": "opendbc_candidate",
    "oil_pressure_switch": "validated_on_vehicle_state_only",
    "battery_voltage_v": "opendbc_candidate",
    "battery_temperature_c": "opendbc_candidate",
    "battery_charge_pct": "opendbc_candidate",
    "ambient_temperature_c": "opendbc_candidate",
    "atmospheric_pressure_hpa": "opendbc_candidate",
    "obd_error": "opendbc_candidate",
    "mil_on": "opendbc_candidate",
    "mil_blinking": "opendbc_candidate",
    "esp_acknowledged": "source_confirmed_constant_on_vehicle",
    "esp_fault_state": "source_confirmed_no_fault_transition_observed",
    "esp_intervention_state": "vehicle_observed_raw_state_semantics_unknown",
    "esp_intervention": "source_confirmed_active_state_not_observed",
    "tcs_intervention": "source_confirmed_active_state_not_observed",
    "esp_exclusive_intervention": "source_confirmed_active_state_not_observed",
    "abs_intervention": "source_confirmed_active_state_not_observed",
    "gearbox_fault": "opendbc_candidate",
    "generic_warning_requested": "opendbc_candidate",
    "brake_fault": "opendbc_candidate",
    "low_fuel_warning": "opendbc_candidate",
    "fuel_level_fault_state": "opendbc_candidate",
    "headlamp_fault": "opendbc_candidate",
    "driver_seatbelt_state": "validated_dedicated_test_0x572_byte0_bits7_6",
    "passenger_seatbelt_state": "opendbc_candidate_raw_state",
    "lane_assist_status": "opendbc_candidate",
    "lane_departure": "opendbc_candidate",
    "lka_mode": "opendbc_candidate",
    "lka_active": "derived_from_lane_assist_status_4",
    "lka_torque_command_raw": "vehicle_observed_candidate",
    "lka_angle_setpoint_deg": "opendbc_candidate_inactive_on_local_vehicle",
    "lka_torque_factor_raw": "opendbc_candidate_scale_not_vehicle_validated",
    "acc_mode": "opendbc_candidate",
    "acc_requested": "opendbc_candidate",
    "lvv_requested": "opendbc_candidate",
    "speed_setpoint_kph": "opendbc_candidate",
    "cruise_xvv_state": "vehicle_observed_candidate",
    "cruise_mode_raw": "validated_on_vehicle_0x50e_byte7_bits5_6",
    "cruise_on": "derived_from_validated_cruise_mode_raw_1",
    "cruise_activation_request": "validated_on_vehicle_0x50e_byte7_bit7",
    "cruise_setpoint_kph": "vehicle_observed_candidate",
    "climate_ac_active": "opendbc_candidate",
    "climate_ac_power_kw": "opendbc_candidate",
    "interior_temp_candidate_c": "experimental_unvalidated_candidate",
    "front_sensor_b0_raw": "experimental_unvalidated_candidate",
    "front_sensor_b2_raw": "experimental_unvalidated_candidate",
    "front_sensor_b4_raw": "experimental_unvalidated_candidate",
    "engine_rpm_3b8_candidate": "validated_exact_formula_0x3b8_byte0",
    "accelerator_pct_3b8_candidate": "validated_exact_formula_0x3b8_byte3",
    "accelerator_pct_2e8_candidate": "validated_exact_formula_0x2e8_byte1",
    "engine_state_57c_candidate_raw": "experimental_unvalidated_candidate",
    "gear_torque_table_2e8_candidate_raw": "experimental_unvalidated_candidate",
    "speed_389_candidate_raw": "experimental_unvalidated_candidate",
    "fiat_clock_hour_candidate": "fiat_500_vehicle_observed_candidate",
    "fiat_clock_minute_candidate": "fiat_500_vehicle_observed_candidate",
    "fiat_clock_day_candidate": "fiat_500_vehicle_observed_candidate",
    "fiat_clock_month_candidate": "fiat_500_vehicle_observed_candidate",
    "fiat_clock_year_candidate": "fiat_500_vehicle_observed_candidate",
    "fiat_start_stop_state_raw": "experimental_unvalidated_candidate",
    "fiat_start_stop_active_candidate": "fiat_500_community_candidate",
    "fiat_start_stop_available_candidate": "fiat_500_community_candidate",
    "fiat_start_stop_door_or_seatbelt_ok_candidate": "fiat_500_community_candidate",
    "fiat_clutch_pedal_candidate": "experimental_unvalidated_candidate",
    "fiat_accelerator_request_candidate": "fiat_500_community_candidate",
    "fiat_clutch_accelerator_state_raw": "fiat_500_community_candidate",
    "fiat_battery_voltage_candidate_v": "fiat_500_vehicle_observed_candidate",
    "fiat_contact_on_candidate": "fiat_500_community_candidate",
    "fiat_ignition_active_candidate": "fiat_500_community_candidate",
    "fiat_city_mode_candidate": "fiat_500_community_candidate",
    "fiat_rear_window_heater_candidate": "fiat_500_community_candidate",
    "fiat_engine_running_candidate": "fiat_500_community_candidate",
    "fiat_speed_related_raw_candidate": "fiat_500_community_candidate_raw",
    "fiat_speed_0a18a006_candidate_kph": "fiat_500_community_candidate",
    "fiat_speed_0a28a000_candidate_kph": "fiat_500_community_candidate",
    "fiat_speed_0a28a006_candidate_kph": "fiat_500_community_candidate",
    "fiat_wheel_activity_counter_raw": "fiat_500_community_candidate_raw",
    "fiat_electrical_load_candidate_raw": "fiat_500_community_candidate_raw",
    "fiat_a1_fast_nibble_candidate": "experimental_unvalidated_candidate",
    "fiat_mode_flag_candidate": "experimental_unvalidated_candidate",
    "fiat_mode_analog_candidate_raw": "experimental_unvalidated_candidate",
    "wheel_front_left_kph": "opendbc_candidate",
    "wheel_front_right_kph": "opendbc_candidate",
    "wheel_rear_left_kph": "opendbc_candidate",
    "wheel_rear_right_kph": "opendbc_candidate",
    "latitude": "browser_gps",
    "longitude": "browser_gps",
    "gps_accuracy_m": "browser_gps_reported_accuracy",
    "gps_altitude_m": "browser_gps",
    "gps_heading_deg": "browser_gps",
    "gps_speed_kph": "browser_gps",
    "x_m": "estimated_dead_reckoning",
    "y_m": "estimated_dead_reckoning",
    "heading_deg": "estimated_dead_reckoning",
    "distance_m": "estimated_from_speed",
}

_PREPARE_LOCK = threading.Lock()


def _session_path(session_id: str) -> Path:
    if Path(session_id).name != session_id or not session_id.startswith("learn-"):
        raise FileNotFoundError(f"Identifiant de session invalide : {session_id}")
    path = settings.session_dir / f"{session_id}.jsonl"
    if not path.exists():
        raise FileNotFoundError(f"Session introuvable : {session_id}")
    return path


def _route_override_path(session_path: Path) -> Path:
    return session_path.with_suffix(".route.json")


def _load_route_override(session_path: Path) -> tuple[list[tuple[float, float]], dict[str, Any]] | None:
    path = _route_override_path(session_path)
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        raw_coordinates = payload["geometry"]["coordinates"]
    except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError):
        return None
    coordinates: list[tuple[float, float]] = []
    for coordinate in raw_coordinates:
        if not isinstance(coordinate, list) or len(coordinate) < 2:
            return None
        longitude = _optional_finite(coordinate[0])
        latitude = _optional_finite(coordinate[1])
        if longitude is None or latitude is None or not -180 <= longitude <= 180 or not -90 <= latitude <= 90:
            return None
        coordinates.append((longitude, latitude))
    if len(coordinates) < 2:
        return None
    return coordinates, payload


from .cruise_detector import CruiseDetector

def _number(values: dict[str, dict[str, Any]], name: str) -> float | None:
    item = values.get(name)
    value = item.get("value") if item else None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    number = float(value)
    return number if math.isfinite(number) else None


def _boolean(values: dict[str, dict[str, Any]], name: str) -> bool | None:
    value = _number(values, name)
    return bool(value) if value is not None else None


def _rounded(value: Any, digits: int = 3) -> Any:
    if isinstance(value, float):
        return round(value, digits)
    return value


def _snapshot(state: dict[str, Any], t_ms: int) -> ReplaySample:
    # Les champs cruise_* sont calculés après la création des échantillons.
    # Ils ne doivent pas être injectés depuis l'état CAN avec une valeur None,
    # car cela écraserait les valeurs par défaut du modèle ReplaySample.
    derived_fields = {
        "cruise_probable",
        "cruise_confidence",
        "cruise_detection_state",
        "cruise_detection_reason",
    }

    return ReplaySample(
        t_ms=max(0, t_ms),
        **{
            key: _rounded(state.get(key))
            for key in STATE_FIELDS
            if key not in derived_fields
        },
    )


def _update_state(message: str, values: dict[str, dict[str, Any]], state: dict[str, Any], data: bytes | None = None) -> None:
    if message == "Dyn_CMM":
        state["engine_rpm"] = _number(values, "P000_Com_nEng")
        state["accelerator_pct"] = _number(values, "P002_Com_rAPP")
        state["engine_torque_nm"] = _number(values, "P003_Com_trqActOut")
        xvv_state = _number(values, "P037_VehV_stXVV")
        state["cruise_xvv_state"] = int(xvv_state) if xvv_state is not None else None
    elif message == "Dyn2_CMM":
        current_gear = _number(values, "P152_Gearbx_stGear")
        if data is not None and len(data) >= 1 and (data[0] >> 4) == 0:
            # Compatibility with an early low-nibble fixture/capture. Current
            # T9 road recordings and the PSA source DBC place P152 in the high
            # nibble; only fall back when that authoritative nibble is zero.
            current_gear = data[0] & 0x0F
        state["current_gear"] = int(current_gear) if current_gear is not None and 0 <= current_gear <= 9 else None
        esp_fault = _number(values, "P025_Com_stESPErr")
        state["esp_fault_state"] = int(esp_fault) if esp_fault is not None else None
        state["esp_acknowledged"] = _boolean(values, "P026_Com_bESPAck")
        state["obd_error"] = _boolean(values, "P343_Com_bOBDErr")
        state["mil_on"] = _boolean(values, "P344_Com_bMILOn")
        state["mil_blinking"] = _boolean(values, "P345_Com_bMILBln")
    elif message == "Dyn_V2_BVMP":
        target_gear = _number(values, "P283_Com_stGearTrgtPos")
        state["target_gear"] = int(target_gear) if target_gear is not None and 0 <= target_gear <= 9 else None
        state["gear_shift_active"] = _boolean(values, "P009_Com_bGearShftActv")
        drivetrain_state = _number(values, "P030_Gbx_stDrvTrnEgd")
        state["drivetrain_engaged_state"] = int(drivetrain_state) if drivetrain_state is not None else None
    elif message == "Dyn_CDS":
        esp_state = _number(values, "P047_Com_stESPIntv")
        state["esp_intervention_state"] = int(esp_state) if esp_state is not None else None
        state["esp_intervention"] = _boolean(values, "P147_Com_bESPIntvActv")
        state["tcs_intervention"] = _boolean(values, "P352_StbIntv_bTCSIntvActv")
        state["esp_exclusive_intervention"] = _boolean(
            values,
            "P353_StbIntv_bESPExclvIntvActv",
        )
    elif message == "Dyn_STT_BV":
        state["gearbox_fault"] = _boolean(values, "P444_Com_bGbxSysFaultRaw")
    elif message == "Dyn5_CMM":
        secondary_accelerator = _number(values, "P334_ACCPed_Position")
        state["accelerator_secondary_pct"] = secondary_accelerator
        if state.get("accelerator_pct") is None:
            state["accelerator_pct"] = secondary_accelerator
    elif message == "Dat_CLIM":
        setpoint = _number(values, "P219_Com_xPrpReqRaw")
        mode = _number(values, "P221_Speed_setPoint_Typ")
        state["cruise_setpoint_kph"] = setpoint if setpoint is not None and setpoint < 255 else None
        state["cruise_mode_raw"] = int(mode) if mode is not None else None
        state["cruise_on"] = int(mode) == 1 if mode is not None else None
        # La définition PSA source place DDE_ACTIVATION_RVV_ACC sur le bit 7
        # du dernier octet de 0x50E. Le signal est absent du DBC OpenDBC
        # nettoyé, donc on le conserve explicitement depuis la trame brute.
        state["cruise_activation_request"] = bool(data[7] & 0x80) if data is not None and len(data) == 8 else None
        state["climate_ac_active"] = _boolean(values, "P050_Com_stAC")
        power_watts = _number(values, "P210_Com_pwrACDem")
        state["climate_ac_power_kw"] = round(power_watts / 1000, 3) if power_watts is not None else None
    elif message == "STEERING":
        state["driver_torque"] = _number(values, "DRIVER_TORQUE")
    elif message == "STEERING_ALT":
        angle = _number(values, "ANGLE")
        if angle is not None and abs(angle) <= 1080:
            state["steering_angle_deg"] = angle
        rate = _number(values, "RATE")
        sign = _number(values, "RATE_SIGN")
        state["steering_rate_deg_s"] = -rate if rate is not None and sign else rate
    elif message == "Dyn4_FRE":
        state["wheel_front_left_kph"] = _number(values, "P263_VehV_VPsvValWhlFrtL")
        state["wheel_front_right_kph"] = _number(values, "P264_VehV_VPsvValWhlFrtR")
        state["wheel_rear_left_kph"] = _number(values, "P265_VehV_VPsvValWhlBckL")
        state["wheel_rear_right_kph"] = _number(values, "P266_VehV_VPsvValWhlBckR")
    elif message == "HS2_DYN_ABR_38D":
        speed = _number(values, "VITESSE_VEHICULE_ROUES")
        state["speed_kph"] = speed if speed is not None and speed < 300 else None
        state["longitudinal_accel_ms2"] = _number(values, "ACCEL_LONGI_ROUES")
        state["generic_warning_requested"] = _boolean(values, "REQ_LAMPE_WARNING")
    elif message == "Dyn_EasyMove":
        parking_state = _number(values, "P337_Com_stPrkBrk")
        if parking_state is not None:
            state["parking_brake_state"] = int(parking_state)
            state["parking_brake"] = int(parking_state) == 1
            # Keep the validated 0x3AD source authoritative when the older
            # 0x412 candidate is also present in the same replay.
            state["_parking_brake_from_3ad"] = True
    elif message == "Dyn2_FRE":
        brake_state = _number(values, "P226_Com_stBrkActv")
        state["brake_system_state"] = int(brake_state) if brake_state is not None else None
        state["brake_pressure_raw"] = _number(values, "BRAKE_PRESSURE")
        state["lateral_accel_ms2"] = _number(values, "LATERAL_ACCELERATION")
        state["yaw_rate_deg_s"] = _number(values, "YAW_RATE")
    elif message == "DAT4_BSI_AEE2010":
        # Kilométrage absolu, octets 5-7 (24 bits big-endian). Validé sur véhicule :
        # confirmé par la documentation constructeur PSA du champ 552 et recoupé
        # par 29 captures matérielles indépendantes du 2026-08-01 au 2026-08-13
        # (progression strictement monotone 104473 -> 104975 km, cohérente avec
        # la conduite quotidienne réelle du véhicule).
        state["odometer_km"] = _number(values, "P015_Com_lTotDst")
    elif message == "Dat_BSI":
        state["reverse"] = _boolean(values, "P103_Com_bRevGear")
        if not state.get("_parking_brake_from_3ad"):
            state["parking_brake"] = _boolean(values, "PARKING_BRAKE")
        state["brake_active"] = _boolean(values, "P013_MainBrake")
        state["driver_door"] = _boolean(values, "DRIVER_DOOR")
        state["passenger_door"] = _boolean(values, "PASSENGER_DOOR")
        state["brake_fault"] = _boolean(values, "P040_MainBrakeFault")
        state["low_fuel_warning"] = _boolean(values, "P012_Com_bFlMin")
        fuel_level_fault = _number(values, "P086_Com_stFlLvlDia")
        state["fuel_level_fault_state"] = int(fuel_level_fault) if fuel_level_fault is not None else None
        if data is not None and len(data) >= 7:
            # Bits non documentés dans le DBC (seuls DRIVER_DOOR/PASSENGER_DOOR y sont
            # définis) ; confirmés par deux essais dédiés porte arrière gauche/droite.
            state["rear_left_door"] = bool(data[6] & 0x20)
            state["rear_right_door"] = bool(data[6] & 0x40)
    elif message == "HS2_DAT_MDD_CMD_452":
        signal = _number(values, "TURN_SIGNAL_STATUS")
        if signal is not None:
            state["turn_signal"] = {0: "off", 1: "right", 2: "left", 3: "hazard"}.get(int(signal), "off")
        state["front_wiper_status"] = int(_number(values, "FRONT_WIPER_STATUS") or 0)
        state["speed_setpoint_kph"] = _number(values, "SPEED_SETPOINT")
        state["acc_mode"] = int(_number(values, "LONGITUDINAL_REGULATION_TYPE") or 0)
        state["acc_requested"] = _boolean(values, "RVV_ACC_ACTIVATION_REQ")
        state["lvv_requested"] = _boolean(values, "LVV_ACTIVATION_REQ")
    elif message == "HS2_DAT7_BSI_612":
        state["low_beam"] = _boolean(values, "ETAT_FEUX_CROIST")
        state["high_beam"] = _boolean(values, "ETAT_FEUX_ROUTE")
        state["fuel_liters_raw"] = _number(values, "INFO_NIV_CARB")
        headlamp_faults = [
            _boolean(values, "DEF_FEU_CROISMNT_D"),
            _boolean(values, "DEF_FEU_CROISMNT_G"),
            _boolean(values, "DEF_FEU_ROUTE_D"),
            _boolean(values, "DEF_FEU_ROUTE_G"),
        ]
        state["headlamp_fault"] = any(headlamp_faults) if any(value is not None for value in headlamp_faults) else None
    elif message == "Dat_ABR":
        state["abs_intervention"] = _boolean(values, "P351_Com_bABSIntvActv")
    elif message == "RESTRAINTS":
        driver_seatbelt = _number(values, "DRIVER_SEATBELT")
        passenger_seatbelt = _number(values, "PASSENGER_SEATBELT")
        state["driver_seatbelt_state"] = int(driver_seatbelt) if driver_seatbelt is not None else None
        state["passenger_seatbelt_state"] = int(passenger_seatbelt) if passenger_seatbelt is not None else None
    elif message == "Dat_CMM":
        state["coolant_temperature_c"] = _number(values, "P005_CEngDst_tSens")
        state["oil_temperature_c"] = _number(values, "P011_Oil_tSwmp")
        state["intake_air_temperature_c"] = _number(values, "P158_Air_tAFS")
        state["idle_setpoint_rpm"] = _number(values, "P022_Com_nSetPLo")
        state["fuel_consumption_candidate_mm3"] = _number(values, "P021_Com_volFlCons")
        state["climate_pressure_kpa"] = _number(values, "P056_ACCD_p")
    elif message == "Dat2_CMM":
        pressure_switch = _number(values, "P278_Oil_stPSwmp")
        state["oil_pressure_switch"] = bool(pressure_switch) if pressure_switch is not None else None
        state["atmospheric_pressure_hpa"] = _number(values, "P338_EnvP_p")
        state["virtual_fuel_consumption_candidate_mm3"] = _number(values, "P316_FlSys_volFlConsVirt")
    elif message == "Dat6_BSI":
        battery_charge = _number(values, "P272_Com_rBattCh")
        battery_temperature = _number(values, "P273_Com_tBatt")
        battery_voltage = _number(values, "P418_Com_uBattRaw")
        # 0xFE/0xFF et leurs valeurs composées sont diffusés pendant
        # l'initialisation du BSI : ce sont des sentinelles, pas des mesures.
        state["battery_charge_pct"] = battery_charge if battery_charge is not None and 0 <= battery_charge <= 100 else None
        state["battery_temperature_c"] = battery_temperature if battery_temperature is not None and -40 <= battery_temperature <= 90 else None
        state["battery_voltage_v"] = battery_voltage if battery_voltage is not None and 8 <= battery_voltage <= 16.5 else None
    elif message == "Contexte1_5B2":
        state["ambient_temperature_c"] = _number(values, "P146_Com_tEnvT")
    elif message == "LANE_KEEP_ASSIST":
        status = _number(values, "STATUS")
        departure = _number(values, "LANE_DEPARTURE")
        mode = _number(values, "LXA_ACTIVATION")
        state["lane_assist_status"] = int(status) if status is not None else None
        state["lane_departure"] = int(departure) if departure is not None else None
        # LXA_ACTIVATION sélectionne la fonction LKA (0) ou LPA (1) ; il ne
        # signifie pas que l'assistance braque. L'état actif est STATUS == 4.
        state["lka_mode"] = int(mode) if mode is not None else None
        state["lka_active"] = int(status) == 4 if status is not None else None
        torque = _number(values, "TORQUE")
        state["lka_torque_command_raw"] = int(torque) if torque is not None else None
        state["lka_angle_setpoint_deg"] = _number(values, "SET_ANGLE")
        state["lka_torque_factor_raw"] = _number(values, "TORQUE_FACTOR")
    elif message == "DRIVER" and state.get("accelerator_pct") is None:
        state["accelerator_pct"] = _number(values, "GAS_PEDAL")


OBD_REPLAY_FIELDS: dict[str, tuple[str, float]] = {
    "engine_rpm": ("engine_rpm", 1.0),
    "vehicle_speed": ("speed_kph", 1.0),
    "engine_load": ("engine_load_pct", 1.0),
    "absolute_engine_load": ("absolute_engine_load_pct", 1.0),
    "fuel_pressure": ("fuel_pressure_kpa", 1.0),
    "intake_manifold_pressure": ("manifold_pressure_kpa", 1.0),
    "maf": ("mass_air_flow_g_s", 1.0),
    "throttle_position": ("throttle_position_pct", 1.0),
    "relative_throttle_position": ("relative_throttle_position_pct", 1.0),
    "absolute_throttle_position_b": ("throttle_position_b_pct", 1.0),
    "absolute_throttle_position_c": ("throttle_position_c_pct", 1.0),
    "commanded_throttle_actuator": ("commanded_throttle_actuator_pct", 1.0),
    "timing_advance": ("ignition_advance_deg", 1.0),
    "fuel_injection_timing": ("fuel_injection_timing_deg", 1.0),
    "short_fuel_trim_bank_1": ("short_fuel_trim_pct", 1.0),
    "long_fuel_trim_bank_1": ("long_fuel_trim_pct", 1.0),
    "oxygen_sensor_b1s1_voltage": ("oxygen_sensor_b1s1_v", 1.0),
    "oxygen_sensor_b1s2_voltage": ("oxygen_sensor_b1s2_v", 1.0),
    "commanded_equivalence_ratio": ("commanded_equivalence_ratio", 1.0),
    "commanded_evap_purge": ("evap_purge_pct", 1.0),
    "engine_runtime": ("engine_runtime_s", 1.0),
    "fuel_level": ("fuel_level_pct", 1.0),
    "fuel_rate": ("fuel_rate_lph", 1.0),
    "fuel_system_status": ("fuel_system_status_raw", 1.0),
    "secondary_air_status": ("secondary_air_status_raw", 1.0),
    "oxygen_sensors_present": ("oxygen_sensors_present_raw", 1.0),
    "obd_standard": ("obd_standard_raw", 1.0),
    "catalyst_temperature_b1s1": ("catalyst_temperature_b1s1_c", 1.0),
    "monitor_status_current_cycle": ("monitor_status_current_cycle_raw", 1.0),
    "coolant_temperature": ("coolant_temperature_c", 1.0),
    "intake_air_temperature": ("intake_air_temperature_c", 1.0),
    "engine_oil_temperature": ("oil_temperature_c", 1.0),
    "control_module_voltage": ("battery_voltage_v", 1.0),
    "ambient_temperature": ("ambient_temperature_c", 1.0),
    "accelerator_pedal_d": ("accelerator_pct", 1.0),
    "accelerator_pedal_e": ("accelerator_secondary_pct", 1.0),
    "accelerator_pedal_f": ("accelerator_tertiary_pct", 1.0),
    "relative_accelerator_position": ("relative_accelerator_position_pct", 1.0),
    "barometric_pressure": ("atmospheric_pressure_hpa", 10.0),
    "maximum_maf": ("maximum_maf_g_s", 1.0),
    "ethanol_fuel_percent": ("ethanol_fuel_pct", 1.0),
    "absolute_evap_vapor_pressure": ("absolute_evap_vapor_pressure_kpa", 1.0),
    "evap_vapor_pressure_alt": ("evap_vapor_pressure_alt_pa", 1.0),
    "emission_requirements": ("emission_requirements_raw", 1.0),
    "driver_demand_torque": ("driver_demand_torque_pct", 1.0),
    "actual_engine_torque": ("actual_engine_torque_pct", 1.0),
    "engine_reference_torque": ("engine_reference_torque_nm", 1.0),
}

FIAT_500_REPLAY_IDS = {
    0x0210A006,
    0x0218A006,
    0x0618A001,
    0x0810A000,
    0x0A18A000,
    0x0C28A000,
    0x0C1CA000,
    0x0628A001,
    0x0A18A001,
    0x0A18A006,
    0x0A28A000,
    0x0A28A006,
}


def _update_obd_state(values: list[dict[str, Any]], state: dict[str, Any]) -> set[str]:
    updated: set[str] = set()
    for item in values:
        mapping = OBD_REPLAY_FIELDS.get(str(item.get("key") or ""))
        value = item.get("value")
        if mapping is None or isinstance(value, bool) or not isinstance(value, (int, float)):
            continue
        number = float(value)
        if not math.isfinite(number):
            continue
        field, factor = mapping
        state[field] = number * factor
        updated.add(field)
    return updated


def _fiat_wheel_speed(raw: int) -> float:
    return 0.0 if raw <= 0x002C else round(raw / 16.0, 2)


def _fiat_bcd_byte(value: int) -> int | None:
    high, low = value >> 4, value & 0x0F
    return high * 10 + low if high <= 9 and low <= 9 else None


def _update_fiat_500_state(
    arbitration_id: int,
    data: bytes,
    state: dict[str, Any],
) -> set[str]:
    """Apply only Fiat fields observed on this VIN and documented independently."""

    updated: set[str] = set()
    if arbitration_id == 0x0210A006 and len(data) >= 6:
        state["fiat_speed_related_raw_candidate"] = int.from_bytes(data[4:6], "big")
        updated.add("fiat_speed_related_raw_candidate")
    elif arbitration_id == 0x0618A001 and len(data) >= 4:
        rpm = int.from_bytes(data[2:4], "big")
        if 0 <= rpm <= 8_000:
            state["engine_rpm"] = rpm
            updated.add("engine_rpm")
        if len(data) >= 8:
            state["fiat_throttle_candidate_pct"] = round(data[7] * 100 / 255, 2)
            state["fiat_air_load_candidate_raw"] = data[4]
            updated.update({
                "fiat_throttle_candidate_pct",
                "fiat_air_load_candidate_raw",
            })
    elif arbitration_id == 0x0218A006 and len(data) >= 8:
        fields = (
            "wheel_front_left_kph",
            "wheel_front_right_kph",
            "wheel_rear_left_kph",
            "wheel_rear_right_kph",
        )
        values = [
            _fiat_wheel_speed(int.from_bytes(data[index:index + 2], "big"))
            for index in range(0, 8, 2)
        ]
        for field, value in zip(fields, values, strict=True):
            state[field] = value
            updated.add(field)
        state["speed_kph"] = round(sum(values) / len(values), 2)
        updated.add("speed_kph")
    elif arbitration_id == 0x0810A000 and len(data) >= 3:
        brake_state = data[2] & 0xF0
        state["brake_active"] = brake_state >= 0x30
        state["brake_pressure_raw"] = brake_state
        updated.update({"brake_active", "brake_pressure_raw"})
    elif arbitration_id == 0x0A18A000 and len(data) >= 3:
        state["parking_brake"] = bool(data[0] & 0x20)
        state["driver_door"] = bool(data[2] & 0x08)
        state["fiat_contact_on_candidate"] = bool(data[2] & 0x40)
        state["fiat_ignition_active_candidate"] = bool(data[2] & 0x80)
        updated.update({
            "parking_brake",
            "driver_door",
            "fiat_contact_on_candidate",
            "fiat_ignition_active_candidate",
        })
        if len(data) >= 7:
            state["fiat_city_mode_candidate"] = bool(data[4] & 0x08)
            state["fiat_rear_window_heater_candidate"] = bool(data[6] & 0x10)
            updated.update({
                "fiat_city_mode_candidate",
                "fiat_rear_window_heater_candidate",
            })
        if len(data) >= 8:
            state["fiat_wheel_activity_counter_raw"] = data[7]
            updated.add("fiat_wheel_activity_counter_raw")
    elif arbitration_id == 0x0C28A000 and len(data) >= 2:
        # Horloge véhicule : octet 0 = heure BCD, octet 1 = minute BCD.
        # Auto-validé par l'incrément d'exactement +1 minute toutes les 60 s réelles.
        hour = _fiat_bcd_byte(data[0])
        minute = _fiat_bcd_byte(data[1])
        if hour is not None and 0 <= hour <= 23:
            state["fiat_clock_hour_candidate"] = hour
            updated.add("fiat_clock_hour_candidate")
        if minute is not None and 0 <= minute <= 59:
            state["fiat_clock_minute_candidate"] = minute
            updated.add("fiat_clock_minute_candidate")
        if len(data) >= 6:
            day = _fiat_bcd_byte(data[2])
            month = _fiat_bcd_byte(data[3])
            year_high = _fiat_bcd_byte(data[4])
            year_low = _fiat_bcd_byte(data[5])
            if day is not None and 1 <= day <= 31:
                state["fiat_clock_day_candidate"] = day
                updated.add("fiat_clock_day_candidate")
            if month is not None and 1 <= month <= 12:
                state["fiat_clock_month_candidate"] = month
                updated.add("fiat_clock_month_candidate")
            if year_high is not None and year_low is not None:
                state["fiat_clock_year_candidate"] = year_high * 100 + year_low
                updated.add("fiat_clock_year_candidate")
    elif arbitration_id == 0x0C1CA000 and len(data) >= 3:
        start_stop_state = data[2]
        state["fiat_start_stop_state_raw"] = start_stop_state
        state["fiat_start_stop_active_candidate"] = bool(start_stop_state & 0x20)
        state["fiat_start_stop_available_candidate"] = (start_stop_state & 0xC0) == 0xC0
        state["fiat_start_stop_door_or_seatbelt_ok_candidate"] = bool(start_stop_state & 0x04)
        updated.update({
            "fiat_start_stop_state_raw",
            "fiat_start_stop_active_candidate",
            "fiat_start_stop_available_candidate",
            "fiat_start_stop_door_or_seatbelt_ok_candidate",
        })
    elif arbitration_id == 0x0628A001 and len(data) >= 6:
        pedal_state = data[5] & 0x30
        state["fiat_clutch_pedal_candidate"] = bool(pedal_state & 0x20)
        state["fiat_accelerator_request_candidate"] = bool(pedal_state & 0x10)
        state["fiat_clutch_accelerator_state_raw"] = pedal_state
        state["fiat_battery_voltage_candidate_v"] = round(data[3] * 0.1, 1)
        updated.update({
            "fiat_clutch_pedal_candidate",
            "fiat_accelerator_request_candidate",
            "fiat_clutch_accelerator_state_raw",
            "fiat_battery_voltage_candidate_v",
        })
    elif arbitration_id == 0x0A18A001 and len(data) >= 7:
        # Nibble bas de l'octet 3 : change toutes les 100-300 ms, bien trop vite
        # pour un rapport de boîte. Signification réelle non identifiée.
        state["fiat_a1_fast_nibble_candidate"] = data[3] & 0x0F
        state["fiat_mode_flag_candidate"] = bool(data[4])
        state["fiat_mode_analog_candidate_raw"] = data[5]
        state["fiat_electrical_load_candidate_raw"] = int.from_bytes(data[4:6], "big")
        updated.update({
            "fiat_a1_fast_nibble_candidate",
            "fiat_mode_flag_candidate",
            "fiat_mode_analog_candidate_raw",
            "fiat_electrical_load_candidate_raw",
        })
    elif arbitration_id == 0x0A18A006 and len(data) >= 4:
        state["fiat_engine_running_candidate"] = data[0] == 1
        state["fiat_speed_0a18a006_candidate_kph"] = round(
            int.from_bytes(data[2:4], "big") / 16.0,
            2,
        )
        updated.update({
            "fiat_engine_running_candidate",
            "fiat_speed_0a18a006_candidate_kph",
        })
    elif arbitration_id == 0x0A28A000 and len(data) >= 2:
        state["fiat_speed_0a28a000_candidate_kph"] = round(
            int.from_bytes(data[0:2], "big") / 16.0,
            2,
        )
        updated.add("fiat_speed_0a28a000_candidate_kph")
        if len(data) >= 4:
            state["fiat_wheel_activity_counter_raw"] = data[3]
            updated.add("fiat_wheel_activity_counter_raw")
    elif arbitration_id == 0x0A28A006 and len(data) >= 4:
        state["fiat_speed_0a28a006_candidate_kph"] = round(
            int.from_bytes(data[2:4], "big") / 16.0,
            2,
        )
        updated.add("fiat_speed_0a28a006_candidate_kph")
    return updated


def _reconstruct_route(points: list[ReplaySample]) -> tuple[float, float, dict[str, float]]:
    center_candidates = [
        point.steering_angle_deg
        for point in points
        if point.steering_angle_deg is not None
        and point.speed_kph is not None
        and point.speed_kph >= 50
        and abs(point.steering_angle_deg) <= 25
    ]
    steering_zero = float(median(center_candidates)) if center_candidates else 0.0

    x_m = 0.0
    y_m = 0.0
    heading_rad = 0.0
    distance_m = 0.0
    filtered_road_angle = 0.0
    previous_t_ms = points[0].t_ms if points else 0

    for point in points:
        dt = max(0.0, min(0.5, (point.t_ms - previous_t_ms) / 1000))
        speed_ms = (point.speed_kph or 0.0) / 3.6
        if point.reverse:
            speed_ms *= -1
        steering_angle = point.steering_angle_deg if point.steering_angle_deg is not None else steering_zero
        # Sur cette 308, le signe DBC observé est opposé au sens visuel du volant.
        road_angle = max(-35.0, min(35.0, -(steering_angle - steering_zero) / STEERING_RATIO))
        filtered_road_angle += 0.24 * (road_angle - filtered_road_angle)
        if point.yaw_rate_deg_s is not None and abs(speed_ms) >= 0.3:
            # Le lacet positif de l'ESP correspond à un virage à gauche, alors
            # que notre cap cartographique croît dans le sens horaire.
            yaw_rate = -math.radians(point.yaw_rate_deg_s)
        else:
            yaw_rate = speed_ms / WHEELBASE_M * math.tan(math.radians(filtered_road_angle))
        heading_rad += yaw_rate * dt
        x_m += speed_ms * math.sin(heading_rad) * dt
        y_m += speed_ms * math.cos(heading_rad) * dt
        distance_m += abs(speed_ms) * dt
        point.x_m = round(x_m, 2)
        point.y_m = round(y_m, 2)
        point.heading_deg = round(math.degrees(heading_rad) % 360, 2)
        point.distance_m = round(distance_m, 1)
        previous_t_ms = point.t_ms

    xs = [point.x_m for point in points] or [0.0]
    ys = [point.y_m for point in points] or [0.0]
    bounds = {
        "min_x": round(min(xs), 2),
        "max_x": round(max(xs), 2),
        "min_y": round(min(ys), 2),
        "max_y": round(max(ys), 2),
    }
    return steering_zero, distance_m, bounds


def _optional_finite(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    number = float(value)
    return number if math.isfinite(number) else None


def _parse_gps_points(
    events: list[dict[str, Any]],
    first_frame_us: int,
    duration_ms: int,
) -> list[ReplayGpsPoint]:
    points: list[ReplayGpsPoint] = []
    for event in events:
        latitude = _optional_finite(event.get("latitude"))
        longitude = _optional_finite(event.get("longitude"))
        accuracy = _optional_finite(event.get("accuracy_m"))
        try:
            timestamp_us = int(event["timestamp_us"])
        except (KeyError, TypeError, ValueError):
            continue
        if (
            latitude is None
            or longitude is None
            or accuracy is None
            or not -90 <= latitude <= 90
            or not -180 <= longitude <= 180
            or accuracy < 0
        ):
            continue
        heading = _optional_finite(event.get("heading_deg"))
        if heading is not None:
            heading %= 360
        speed_m_s = _optional_finite(event.get("speed_m_s"))
        points.append(ReplayGpsPoint(
            t_ms=max(0, min(duration_ms, (timestamp_us - first_frame_us) // 1000)),
            timestamp_us=timestamp_us,
            latitude=latitude,
            longitude=longitude,
            accuracy_m=accuracy,
            altitude_m=_optional_finite(event.get("altitude_m")),
            altitude_accuracy_m=_optional_finite(event.get("altitude_accuracy_m")),
            heading_deg=heading,
            speed_kph=speed_m_s * 3.6 if speed_m_s is not None and speed_m_s >= 0 else None,
        ))
    points.sort(key=lambda point: point.timestamp_us)
    deduplicated: list[ReplayGpsPoint] = []
    for point in points:
        if deduplicated and point.timestamp_us == deduplicated[-1].timestamp_us:
            deduplicated[-1] = point
        else:
            deduplicated.append(point)
    return deduplicated


def _route_bounds(points: list[ReplaySample]) -> dict[str, float]:
    xs = [point.x_m for point in points] or [0.0]
    ys = [point.y_m for point in points] or [0.0]
    return {
        "min_x": round(min(xs), 2),
        "max_x": round(max(xs), 2),
        "min_y": round(min(ys), 2),
        "max_y": round(max(ys), 2),
    }


def _interpolate_optional(first: float | None, second: float | None, ratio: float) -> float | None:
    if first is None:
        return second
    if second is None:
        return first
    return first + (second - first) * ratio


def _interpolate_heading(first: float | None, second: float | None, ratio: float) -> float | None:
    if first is None or second is None:
        return first if first is not None else second
    delta = (second - first + 180) % 360 - 180
    return (first + delta * ratio) % 360


def _interpolate_route_position(points: list[ReplaySample], times: list[int], t_ms: int) -> tuple[float, float]:
    """Return the dead-reckoned position at an arbitrary GPS timestamp."""
    upper_index = bisect_right(times, t_ms)
    if upper_index <= 0:
        return points[0].x_m, points[0].y_m
    if upper_index >= len(points):
        return points[-1].x_m, points[-1].y_m
    first = points[upper_index - 1]
    second = points[upper_index]
    elapsed = max(1, second.t_ms - first.t_ms)
    ratio = max(0.0, min(1.0, (t_ms - first.t_ms) / elapsed))
    return (
        first.x_m + (second.x_m - first.x_m) * ratio,
        first.y_m + (second.y_m - first.y_m) * ratio,
    )


def _segment_similarity_transform(
    raw_start: tuple[float, float],
    raw_end: tuple[float, float],
    gps_start: tuple[float, float],
    gps_end: tuple[float, float],
) -> tuple[float, float, float, bool]:
    """Build a similarity transform which makes a CAN segment hit both GPS fixes."""
    raw_dx = raw_end[0] - raw_start[0]
    raw_dy = raw_end[1] - raw_start[1]
    gps_dx = gps_end[0] - gps_start[0]
    gps_dy = gps_end[1] - gps_start[1]
    raw_length = math.hypot(raw_dx, raw_dy)
    gps_length = math.hypot(gps_dx, gps_dy)
    if raw_length < 1.0 or gps_length < 1.0:
        return 1.0, 1.0, 0.0, False
    scale = gps_length / raw_length
    cosine = (raw_dx * gps_dx + raw_dy * gps_dy) / (raw_length * gps_length)
    sine = (raw_dx * gps_dy - raw_dy * gps_dx) / (raw_length * gps_length)
    return scale, cosine, sine, True


def _apply_similarity(
    position: tuple[float, float],
    raw_origin: tuple[float, float],
    gps_origin: tuple[float, float],
    transform: tuple[float, float, float, bool],
) -> tuple[float, float]:
    scale, cosine, sine, usable = transform
    if not usable:
        return gps_origin
    raw_x = position[0] - raw_origin[0]
    raw_y = position[1] - raw_origin[1]
    return (
        gps_origin[0] + scale * (cosine * raw_x - sine * raw_y),
        gps_origin[1] + scale * (sine * raw_x + cosine * raw_y),
    )


def _apply_gps_route(
    points: list[ReplaySample],
    gps_points: list[ReplayGpsPoint],
    dead_reckoning_method: str = "dead_reckoning_speed_steering",
) -> tuple[str, float, dict[str, float], int]:
    # Very coarse network fixes remain in the raw export but must not replace the
    # speed/steering reconstruction shown in the replay.
    fixes = [point for point in gps_points if point.accuracy_m <= 1_000]
    if not fixes:
        distance_m = points[-1].distance_m if points else 0.0
        return dead_reckoning_method, distance_m, _route_bounds(points), 0

    origin = fixes[0]
    latitude_scale = 111_132.0
    longitude_scale = max(1.0, 111_320.0 * math.cos(math.radians(origin.latitude)))

    if len(fixes) == 1:
        # One fix is still useful as an absolute anchor; motion remains estimated.
        for point in points:
            point.latitude = round(origin.latitude + point.y_m / latitude_scale, 7)
            point.longitude = round(origin.longitude + point.x_m / longitude_scale, 7)
            point.gps_accuracy_m = round(origin.accuracy_m, 1)
            point.gps_altitude_m = origin.altitude_m
            point.gps_heading_deg = origin.heading_deg
            point.gps_speed_kph = origin.speed_kph
        distance_m = points[-1].distance_m if points else 0.0
        return "dead_reckoning_gps_anchor", distance_m, _route_bounds(points), 1

    times = [point.t_ms for point in fixes]
    replay_times = [point.t_ms for point in points]
    raw_fix_positions = [
        _interpolate_route_position(points, replay_times, fix.t_ms)
        for fix in fixes
    ]
    gps_fix_positions = [
        (
            (fix.longitude - origin.longitude) * longitude_scale,
            (fix.latitude - origin.latitude) * latitude_scale,
        )
        for fix in fixes
    ]
    transforms = [
        _segment_similarity_transform(
            raw_fix_positions[index],
            raw_fix_positions[index + 1],
            gps_fix_positions[index],
            gps_fix_positions[index + 1],
        )
        for index in range(len(fixes) - 1)
    ]
    can_fusion_used = any(transform[3] for transform in transforms)
    previous_x: float | None = None
    previous_y: float | None = None
    derived_heading = 0.0
    distance_m = 0.0
    for point in points:
        upper_index = bisect_right(times, point.t_ms)
        if upper_index <= 0:
            first = second = fixes[0]
            ratio = 0.0
        elif upper_index >= len(fixes):
            first = second = fixes[-1]
            ratio = 0.0
        else:
            first = fixes[upper_index - 1]
            second = fixes[upper_index]
            elapsed = max(1, second.t_ms - first.t_ms)
            ratio = max(0.0, min(1.0, (point.t_ms - first.t_ms) / elapsed))

        if can_fusion_used:
            if upper_index <= 0:
                segment_index = 0
                raw_origin = raw_fix_positions[0]
                gps_origin = gps_fix_positions[0]
            elif upper_index >= len(fixes):
                segment_index = len(transforms) - 1
                raw_origin = raw_fix_positions[-1]
                gps_origin = gps_fix_positions[-1]
            else:
                segment_index = upper_index - 1
                raw_origin = raw_fix_positions[segment_index]
                gps_origin = gps_fix_positions[segment_index]
            transformed = _apply_similarity(
                (point.x_m, point.y_m),
                raw_origin,
                gps_origin,
                transforms[segment_index],
            )
            if transforms[segment_index][3]:
                x_m, y_m = transformed
            else:
                x_m = gps_fix_positions[max(0, upper_index - 1)][0] + (
                    gps_fix_positions[min(len(fixes) - 1, upper_index)][0]
                    - gps_fix_positions[max(0, upper_index - 1)][0]
                ) * ratio
                y_m = gps_fix_positions[max(0, upper_index - 1)][1] + (
                    gps_fix_positions[min(len(fixes) - 1, upper_index)][1]
                    - gps_fix_positions[max(0, upper_index - 1)][1]
                ) * ratio
        else:
            x_m = gps_fix_positions[max(0, upper_index - 1)][0] + (
                gps_fix_positions[min(len(fixes) - 1, upper_index)][0]
                - gps_fix_positions[max(0, upper_index - 1)][0]
            ) * ratio
            y_m = gps_fix_positions[max(0, upper_index - 1)][1] + (
                gps_fix_positions[min(len(fixes) - 1, upper_index)][1]
                - gps_fix_positions[max(0, upper_index - 1)][1]
            ) * ratio
        latitude = origin.latitude + y_m / latitude_scale
        longitude = origin.longitude + x_m / longitude_scale
        if previous_x is not None and previous_y is not None:
            dx = x_m - previous_x
            dy = y_m - previous_y
            segment = math.hypot(dx, dy)
            distance_m += segment
            if segment >= 0.05:
                derived_heading = math.degrees(math.atan2(dx, dy)) % 360
        previous_x, previous_y = x_m, y_m

        gps_heading = _interpolate_heading(first.heading_deg, second.heading_deg, ratio)
        point.latitude = round(latitude, 7)
        point.longitude = round(longitude, 7)
        point.gps_accuracy_m = round(
            first.accuracy_m + (second.accuracy_m - first.accuracy_m) * ratio,
            1,
        )
        point.gps_altitude_m = _rounded(
            _interpolate_optional(first.altitude_m, second.altitude_m, ratio),
            1,
        )
        point.gps_heading_deg = _rounded(gps_heading, 1)
        point.gps_speed_kph = _rounded(
            _interpolate_optional(first.speed_kph, second.speed_kph, ratio),
            1,
        )
        point.x_m = round(x_m, 2)
        point.y_m = round(y_m, 2)
        point.heading_deg = round(gps_heading if gps_heading is not None else derived_heading, 2)
        point.distance_m = round(distance_m, 1)

    return (
        "gps_can_fusion" if can_fusion_used else "browser_gps",
        distance_m,
        _route_bounds(points),
        len(fixes),
    )


def _apply_confirmed_road_route(
    points: list[ReplaySample],
    coordinates: list[tuple[float, float]],
    raw_distances: list[float],
) -> tuple[float, dict[str, float]]:
    """Place replay samples on a driver-confirmed road geometry.

    CAN speed controls progress and timing; the external road geometry controls
    only the displayed latitude/longitude and heading.
    """
    origin_longitude, origin_latitude = coordinates[0]
    latitude_scale = 111_132.0
    longitude_scale = max(1.0, 111_320.0 * math.cos(math.radians(origin_latitude)))
    projected = [
        (
            (longitude - origin_longitude) * longitude_scale,
            (latitude - origin_latitude) * latitude_scale,
        )
        for longitude, latitude in coordinates
    ]
    cumulative = [0.0]
    for index in range(1, len(projected)):
        cumulative.append(cumulative[-1] + math.hypot(
            projected[index][0] - projected[index - 1][0],
            projected[index][1] - projected[index - 1][1],
        ))
    route_distance = cumulative[-1]
    if route_distance < 1:
        return 0.0, _route_bounds(points)
    raw_total = max(raw_distances, default=0.0)
    duration_ms = max(1, points[-1].t_ms if points else 1)
    for index, point in enumerate(points):
        ratio = (
            raw_distances[index] / raw_total
            if raw_total > 1 and index < len(raw_distances)
            else point.t_ms / duration_ms
        )
        target_distance = route_distance * max(0.0, min(1.0, ratio))
        upper_index = bisect_right(cumulative, target_distance)
        if upper_index <= 0:
            first_index = second_index = 0
            segment_ratio = 0.0
        elif upper_index >= len(cumulative):
            first_index = second_index = len(cumulative) - 1
            segment_ratio = 0.0
        else:
            first_index = upper_index - 1
            second_index = upper_index
            segment_length = max(0.001, cumulative[second_index] - cumulative[first_index])
            segment_ratio = (target_distance - cumulative[first_index]) / segment_length
        first_x, first_y = projected[first_index]
        second_x, second_y = projected[second_index]
        x_m = first_x + (second_x - first_x) * segment_ratio
        y_m = first_y + (second_y - first_y) * segment_ratio
        first_longitude, first_latitude = coordinates[first_index]
        second_longitude, second_latitude = coordinates[second_index]
        point.longitude = round(first_longitude + (second_longitude - first_longitude) * segment_ratio, 7)
        point.latitude = round(first_latitude + (second_latitude - first_latitude) * segment_ratio, 7)
        point.x_m = round(x_m, 2)
        point.y_m = round(y_m, 2)
        if second_index != first_index:
            point.heading_deg = round(math.degrees(math.atan2(
                second_x - first_x,
                second_y - first_y,
            )) % 360, 2)
        point.distance_m = round(target_distance, 1)
    return route_distance, _route_bounds(points)



def _detect_probable_cruise(points: list[ReplaySample]) -> bool:
    """
    Ajoute une estimation comportementale de l'état du régulateur.

    Cette estimation ne remplace pas le décodage direct d'un signal CAN.
    Elle sert à identifier les fenêtres susceptibles de contenir une
    régulation de vitesse active.
    """
    detector = CruiseDetector(
        sample_period_ms=SAMPLE_PERIOD_US // 1000,
    )

    populated = False

    for point in points:
        detection = detector.update(
            speed_kph=point.speed_kph,
            accelerator_d_pct=point.accelerator_pct,
            accelerator_e_pct=point.accelerator_secondary_pct,
            engine_load_pct=point.engine_load_pct,
            throttle_pct=point.throttle_position_pct,
            brake_active=point.brake_active,
        )

        point.cruise_probable = detection.probable
        point.cruise_confidence = detection.confidence
        point.cruise_detection_state = detection.state
        point.cruise_detection_reason = detection.reason
        point.cruise_switch_candidate = (
            point.acc_mode != 0
            if point.acc_mode is not None
            else None
        )
        point.cruise_active_candidate = (
            point.cruise_xvv_state == 2
            if point.cruise_xvv_state is not None
            else None
        )

        if detection.state != "unavailable":
            populated = True

    return populated


def _detect_cruise_controls(points: list[ReplaySample]) -> bool:
    """Reconstruit les commandes visibles du commodo régulateur.

    ON vient directement du mode 0x50E (1 = RVV). SET+ et SET- sont déduits
    du signe des sauts de consigne. CANCEL est une désactivation RVV sans
    freinage et sans sortie du mode RVV. RESUME est un réengagement après une
    désactivation dans la même session; c'est donc une déduction d'effet et
    non la lecture d'un contact électrique dédié.
    """
    populated = False
    previous_engaged: bool | None = None
    previous_setpoint: float | None = None
    saved_setpoint: float | None = None
    resume_armed = False
    active_event: Literal["set_plus", "set_minus", "resume", "cancel"] | None = None
    active_source: Literal["setpoint_delta", "state_transition"] | None = None
    active_step: float | None = None
    event_until_ms = -1

    for point in points:
        on = point.cruise_on
        engaged = point.cruise_activation_request
        setpoint = point.cruise_setpoint_kph
        event: Literal["set_plus", "set_minus", "resume", "cancel"] | None = None
        source: Literal["setpoint_delta", "state_transition"] | None = None
        step: float | None = None

        if on is False:
            resume_armed = False
            saved_setpoint = None

        if previous_engaged is True and engaged is False:
            if previous_setpoint is not None:
                saved_setpoint = previous_setpoint
            if on is True and point.brake_active is False and point.cruise_xvv_state != 3:
                event = "cancel"
                source = "state_transition"
                resume_armed = saved_setpoint is not None
            else:
                resume_armed = False

        elif previous_engaged is False and engaged is True:
            if resume_armed and on is True and saved_setpoint is not None:
                event = "resume"
                source = "state_transition"
            resume_armed = False

        elif (
            engaged is True
            and setpoint is not None
            and previous_setpoint is not None
            and setpoint != previous_setpoint
        ):
            delta = setpoint - previous_setpoint
            event = "set_plus" if delta > 0 else "set_minus"
            source = "setpoint_delta"
            step = round(delta, 1)

        if event is not None:
            active_event = event
            active_source = source
            active_step = step
            event_until_ms = point.t_ms + 800
            populated = True
        elif point.t_ms > event_until_ms:
            active_event = None
            active_source = None
            active_step = None

        point.cruise_button_event = active_event
        point.cruise_button_event_source = active_source
        point.cruise_setpoint_direction = (
            "up" if active_event == "set_plus" else "down" if active_event == "set_minus" else None
        )
        point.cruise_setpoint_step_kph = active_step

        previous_engaged = engaged if engaged is not None else previous_engaged
        previous_setpoint = setpoint

    return populated


def _events(points: list[ReplaySample]) -> list[ReplayEvent]:
    events: list[ReplayEvent] = []
    previous: ReplaySample | None = None
    hard_braking = False
    for point in points:
        if previous is not None:
            if point.turn_signal != previous.turn_signal and point.turn_signal not in {None, "off"}:
                labels = {"left": "Clignotant gauche", "right": "Clignotant droit", "hazard": "Feux de détresse"}
                events.append(ReplayEvent(t_ms=point.t_ms, kind="turn_signal", label=labels[point.turn_signal], value=point.turn_signal))
            if point.low_beam != previous.low_beam and point.low_beam is not None:
                events.append(ReplayEvent(t_ms=point.t_ms, kind="lights", label="Feux de croisement allumés" if point.low_beam else "Feux de croisement éteints", value=point.low_beam))
            if point.high_beam != previous.high_beam and point.high_beam is not None:
                events.append(ReplayEvent(t_ms=point.t_ms, kind="lights", label="Feux de route allumés" if point.high_beam else "Feux de route éteints", value=point.high_beam))
            if point.brake_active and not previous.brake_active:
                events.append(ReplayEvent(t_ms=point.t_ms, kind="brake", label="Frein conducteur", value=True))
            if (
                point.fiat_clutch_pedal_candidate is not None
                and point.fiat_clutch_pedal_candidate != previous.fiat_clutch_pedal_candidate
            ):
                events.append(ReplayEvent(
                    t_ms=point.t_ms,
                    kind="clutch",
                    label=(
                        "Embrayage enfoncé"
                        if point.fiat_clutch_pedal_candidate
                        else "Embrayage relâché"
                    ),
                    value=point.fiat_clutch_pedal_candidate,
                ))
            if (
                point.fiat_start_stop_available_candidate is not None
                and point.fiat_start_stop_available_candidate
                != previous.fiat_start_stop_available_candidate
            ):
                events.append(ReplayEvent(
                    t_ms=point.t_ms,
                    kind="start_stop",
                    label=(
                        "Start&Stop disponible"
                        if point.fiat_start_stop_available_candidate
                        else "Start&Stop indisponible"
                    ),
                    value=point.fiat_start_stop_available_candidate,
                ))
            if (
                point.fiat_start_stop_active_candidate is not None
                and point.fiat_start_stop_active_candidate
                != previous.fiat_start_stop_active_candidate
            ):
                events.append(ReplayEvent(
                    t_ms=point.t_ms,
                    kind="start_stop",
                    label=(
                        "Start&Stop activé"
                        if point.fiat_start_stop_active_candidate
                        else "Start&Stop désactivé"
                    ),
                    value=point.fiat_start_stop_active_candidate,
                ))
            if (
                point.fiat_engine_running_candidate is not None
                and point.fiat_engine_running_candidate != previous.fiat_engine_running_candidate
            ):
                events.append(ReplayEvent(
                    t_ms=point.t_ms,
                    kind="engine",
                    label=(
                        "Moteur en fonctionnement"
                        if point.fiat_engine_running_candidate
                        else "Moteur arrêté"
                    ),
                    value=point.fiat_engine_running_candidate,
                ))
            if point.cruise_probable != previous.cruise_probable:
                events.append(
                    ReplayEvent(
                        t_ms=point.t_ms,
                        kind="cruise",
                        label=(
                            "Régulateur probable actif"
                            if point.cruise_probable
                            else "Régulateur probable inactif"
                        ),
                        value=point.cruise_probable,
                    )
                )
            if point.cruise_on is not None and point.cruise_on != previous.cruise_on:
                events.append(ReplayEvent(
                    t_ms=point.t_ms,
                    kind="cruise",
                    label="Régulateur ON" if point.cruise_on else "Régulateur OFF",
                    value=point.cruise_on,
                ))
            if point.cruise_button_event is not None and point.cruise_button_event != previous.cruise_button_event:
                labels = {
                    "set_plus": "Commodo SET+",
                    "set_minus": "Commodo SET−",
                    "resume": "Commodo RESUME (déduit)",
                    "cancel": "Commodo CANCEL",
                }
                events.append(ReplayEvent(
                    t_ms=point.t_ms,
                    kind="cruise",
                    label=labels[point.cruise_button_event],
                    value=point.cruise_button_event,
                ))
            if point.current_gear is not None and point.current_gear != previous.current_gear:
                events.append(ReplayEvent(t_ms=point.t_ms, kind="gear", label=f"Rapport {point.current_gear}", value=point.current_gear))
            if point.lane_departure and not previous.lane_departure:
                side = "droite" if point.lane_departure == 1 else "gauche" if point.lane_departure == 2 else "indéterminée"
                events.append(ReplayEvent(t_ms=point.t_ms, kind="adas", label=f"Franchissement de ligne {side}", value=point.lane_departure))
        now_hard_braking = (point.longitudinal_accel_ms2 or 0) <= -2.0
        if now_hard_braking and not hard_braking:
            events.append(ReplayEvent(t_ms=point.t_ms, kind="deceleration", label="Forte décélération", value=point.longitudinal_accel_ms2))
        hard_braking = now_hard_braking
        previous = point
    return events


def _filter_fuel_level(points: list[ReplaySample], time_constant_s: float = 120.0) -> bool:
    """Create a causal tank-level estimate while retaining the slosh-affected float."""
    filtered: float | None = None
    previous_t_ms: int | None = None
    populated = False
    for point in points:
        raw = point.fuel_liters_raw
        if raw is None or not math.isfinite(raw):
            continue
        if filtered is None or previous_t_ms is None:
            filtered = raw
        else:
            elapsed_s = max(0.0, min(5.0, (point.t_ms - previous_t_ms) / 1000))
            alpha = 1 - math.exp(-elapsed_s / time_constant_s)
            filtered += alpha * (raw - filtered)
        point.fuel_liters = round(filtered, 2)
        previous_t_ms = point.t_ms
        populated = True
    return populated


def _estimate_fuel_consumption(
    points: list[ReplaySample],
    distance_m: float,
) -> tuple[float | None, str | None]:
    """Trip-average consumption estimated from the filtered tank float level.

    This is deliberately coarse: a float sender is not a flow meter, so the
    estimate is only attempted over several kilometres without a refuel
    during the capture, using the median of the first/last readings rather
    than single endpoints to dampen sender noise.
    """
    distance_km = distance_m / 1000
    if distance_km < 3.0:
        return None, "Trajet trop court (moins de 3 km) pour une estimation fiable."

    readings = [point.fuel_liters for point in points if point.fuel_liters is not None]
    if len(readings) < 20:
        return None, "Pas assez de mesures de niveau carburant sur cette capture."

    sample = max(5, len(readings) // 20)
    baseline = median(readings[:sample])
    final = median(readings[-sample:])
    consumed = baseline - final
    if consumed <= 0:
        return None, "Le niveau du réservoir n'a pas baissé pendant cette capture (plein ou remplissage possible)."

    consumption = consumed / distance_km * 100
    if not 1.0 <= consumption <= 30.0:
        return None, (
            f"Estimation hors plage plausible ({consumption:.1f} L/100km) : le flotteur n'est pas assez "
            "précis sur ce trajet pour ce calcul."
        )

    return round(consumption, 1), (
        f"Estimation basée sur le niveau filtré du flotteur : {baseline:.1f} L → {final:.1f} L sur "
        f"{distance_km:.1f} km. Ce n'est pas un débitmètre instantané ; fiable uniquement sur plusieurs "
        "kilomètres sans plein pendant l'essai."
    )


def _compute_can_fuel_consumption(points: list[ReplaySample]) -> bool:
    """Débit et consommation dérivés du compteur de volume carburant 0x488.

    P021_Com_volFlCons n'est pas une mesure instantanée : c'est un compteur de
    volume cumulé qui reboucle modulo 255 (comportement confirmé sur capture
    véhicule, cf. database/psa/dbc/peugeot_308_t9_2018_checksums.yaml). La
    valeur brute prise seule reste donc à juste titre marquée "rejetée" dans
    FIELD_QUALITY/sensor_metadata — ce sont ses *incréments* qui portent
    l'information : reconstruits ici entre échantillons consécutifs, lissés
    sur une fenêtre glissante pour amortir la quantification (un tick vaut
    80 mm³ = 0,00008 L), puis rapportés à la vitesse (0x38D) pour obtenir un
    L/100km.
    """
    # Chaque entrée de fenêtre est (début d'intervalle, fin d'intervalle,
    # volume consommé pendant cet intervalle) ; le début est nécessaire pour
    # que la durée couverte par la fenêtre inclue le tout premier intervalle
    # (sinon le débit calculé serait systématiquement surestimé).
    window: list[tuple[int, int, float]] = []
    trip_total_l = 0.0
    previous_raw: float | None = None
    previous_t_ms: int | None = None
    populated = False

    for point in points:
        raw = point.fuel_consumption_candidate_mm3
        if raw is not None and previous_raw is not None and previous_t_ms is not None:
            gap_ms = point.t_ms - previous_t_ms
            if 0 < gap_ms <= FUEL_MAX_GAP_MS:
                delta_mm3 = (raw - previous_raw) % FUEL_TICK_MODULUS_MM3
                delta_l = delta_mm3 / 1_000_000
                implied_rate_lph = delta_l * 3_600_000 / gap_ms
                if implied_rate_lph <= FUEL_IMPLAUSIBLE_RATE_LPH:
                    trip_total_l += delta_l
                    window.append((previous_t_ms, point.t_ms, delta_l))
        if raw is not None:
            previous_raw = raw
            previous_t_ms = point.t_ms
            point.can_trip_fuel_l = round(trip_total_l, 4)
            populated = True

        window[:] = [
            (start_ms, end_ms, delta_l) for start_ms, end_ms, delta_l in window
            if point.t_ms - end_ms <= FUEL_RATE_WINDOW_MS
        ]
        if window:
            window_span_ms = window[-1][1] - window[0][0]
            if window_span_ms > 0:
                rate_lph = sum(delta_l for _, _, delta_l in window) * 3_600_000 / window_span_ms
                point.can_fuel_rate_lph = round(rate_lph, 3)
                if point.speed_kph is not None and point.speed_kph >= FUEL_MIN_SPEED_FOR_L100KM_KPH:
                    point.can_instant_consumption_l_100km = round(rate_lph / point.speed_kph * 100, 2)

    return populated


def _summarize_can_fuel_consumption(
    points: list[ReplaySample],
    distance_m: float,
    available: bool,
) -> tuple[float | None, float | None, str | None]:
    if not available:
        return None, None, None
    trip_total_l = next(
        (point.can_trip_fuel_l for point in reversed(points) if point.can_trip_fuel_l is not None),
        None,
    )
    if trip_total_l is None:
        return None, None, "Aucun incrément exploitable du compteur 0x488 sur cette capture."

    distance_km = distance_m / 1000
    if distance_km < 0.3:
        return trip_total_l, None, "Trajet trop court pour une moyenne L/100km fiable."

    average = trip_total_l / distance_km * 100
    note = (
        f"Calculée à partir du compteur de volume carburant 0x488 (incréments modulo, "
        f"lissés sur {FUEL_RATE_WINDOW_MS} ms) rapportée à la distance reconstruite "
        f"({distance_km:.2f} km). Contrairement à l'estimation par flotteur ci-dessus, c'est "
        "un débitmètre reconstruit, exploitable dès quelques centaines de mètres."
    )
    if not 0 <= average <= 40:
        return trip_total_l, None, (
            f"{note} Moyenne hors plage plausible ({average:.1f} L/100km) : probablement une "
            "resynchronisation du compteur pendant la capture."
        )
    return trip_total_l, round(average, 2), note


def _build_replay(path: Path, session_id: str) -> ReplayData:
    decoder = get_opendbc_decoder()
    state = {field: None for field in STATE_FIELDS}
    points: list[ReplaySample] = []
    available_fields: set[str] = set()
    first_frame_us: int | None = None
    last_frame_us: int | None = None
    next_sample_us: int | None = None
    frame_count = 0
    decoded_frame_count = 0
    obd_standardized_fields: set[str] = set()
    fiat_observed_fields: set[str] = set()
    gps_events: list[dict[str, Any]] = []
    source = ""
    name = session_id
    vin: str | None = None
    vehicle_profile: str | None = None
    vehicle_label: str | None = None

    with path.open(encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            try:
                event = json.loads(line)
            except (TypeError, ValueError, json.JSONDecodeError):
                continue
            if event.get("type") == "gps_position":
                gps_events.append(event)
                continue
            if event.get("type") == "meta":
                source = str(event.get("source") or source)
                name = str(event.get("name") or name)
                vin = str(event.get("vin") or vin or "") or None
                vehicle_profile = str(event.get("vehicle_profile") or vehicle_profile or "") or None
                vehicle_label = str(event.get("vehicle_label") or vehicle_label or "") or None
                continue
            if event.get("type") == "obd_sensor_snapshot":
                try:
                    timestamp_us = int(event["timestamp_us"])
                except (KeyError, TypeError, ValueError):
                    continue
                if first_frame_us is None:
                    first_frame_us = timestamp_us
                    next_sample_us = timestamp_us + SAMPLE_PERIOD_US
                last_frame_us = timestamp_us
                while next_sample_us is not None and timestamp_us >= next_sample_us:
                    points.append(_snapshot(state, (next_sample_us - first_frame_us) // 1000))
                    next_sample_us += SAMPLE_PERIOD_US
                values = event.get("values")
                if isinstance(values, list):
                    updated = _update_obd_state(values, state)
                    if updated:
                        decoded_frame_count += 1
                        obd_standardized_fields.update(updated)
                        available_fields.update(updated)
                continue
            if event.get("type") != "can_frame":
                continue
            if event.get("bus") == "diagnostic":
                continue
            try:
                timestamp_us = int(event["timestamp_us"])
                arbitration_id = int(event["arbitration_id"])
            except (KeyError, TypeError, ValueError):
                continue
            frame_count += 1
            if first_frame_us is None:
                first_frame_us = timestamp_us
                next_sample_us = timestamp_us + SAMPLE_PERIOD_US
            last_frame_us = timestamp_us

            while next_sample_us is not None and timestamp_us >= next_sample_us:
                points.append(_snapshot(state, (next_sample_us - first_frame_us) // 1000))
                next_sample_us += SAMPLE_PERIOD_US

            if (
                vehicle_profile == "fiat_500_generic"
                and bool(event.get("extended", arbitration_id > 0x7FF))
                and arbitration_id in FIAT_500_REPLAY_IDS
            ):
                try:
                    data = bytes.fromhex(str(event.get("data_hex") or ""))
                except ValueError:
                    data = b""
                updated = _update_fiat_500_state(arbitration_id, data, state)
                if updated:
                    available_fields.update(updated)
                    fiat_observed_fields.update(updated)
                    decoded_frame_count += 1
                continue

            if arbitration_id == CLIMATE_CANDIDATE_ID:
                try:
                    data = bytes.fromhex(str(event.get("data_hex") or ""))
                except ValueError:
                    data = b""
                if len(data) >= 6:
                    state["interior_temp_candidate_c"] = round(data[2] * 0.1, 1)
                    state["engine_rpm_3b8_candidate"] = round((255 - data[0]) * 32)
                    state["accelerator_pct_3b8_candidate"] = round((255 - data[3]) / 2, 1)
                    available_fields.update({
                        "interior_temp_candidate_c",
                        "engine_rpm_3b8_candidate",
                        "accelerator_pct_3b8_candidate",
                    })
                    decoded_frame_count += 1
                continue

            if arbitration_id == ENGINE_ACCEL_SHADOW_CANDIDATE_ID:
                try:
                    data = bytes.fromhex(str(event.get("data_hex") or ""))
                except ValueError:
                    data = b""
                if len(data) >= 4:
                    state["accelerator_pct_2e8_candidate"] = round(data[1] / 2, 1)
                    state["gear_torque_table_2e8_candidate_raw"] = data[3]
                    available_fields.update({
                        "accelerator_pct_2e8_candidate",
                        "gear_torque_table_2e8_candidate_raw",
                    })
                    decoded_frame_count += 1
                continue

            if arbitration_id == ENGINE_STATE_CANDIDATE_ID:
                try:
                    data = bytes.fromhex(str(event.get("data_hex") or ""))
                except ValueError:
                    data = b""
                if len(data) >= 6:
                    state["engine_state_57c_candidate_raw"] = data[5]
                    available_fields.add("engine_state_57c_candidate_raw")
                    decoded_frame_count += 1
                continue

            if arbitration_id == SPEED_CANDIDATE_ID:
                try:
                    data = bytes.fromhex(str(event.get("data_hex") or ""))
                except ValueError:
                    data = b""
                if len(data) >= 1:
                    state["speed_389_candidate_raw"] = data[0]
                    available_fields.add("speed_389_candidate_raw")
                    decoded_frame_count += 1
                continue

            if arbitration_id == REAR_DOOR_AJAR_CANDIDATE_ID:
                try:
                    data = bytes.fromhex(str(event.get("data_hex") or ""))
                except ValueError:
                    data = b""
                if len(data) >= 8:
                    state["rear_door_ajar_candidate"] = bool(data[7])
                    available_fields.add("rear_door_ajar_candidate")
                    decoded_frame_count += 1
                continue

            if arbitration_id == FRONT_SENSOR_CANDIDATE_ID:
                try:
                    data = bytes.fromhex(str(event.get("data_hex") or ""))
                except ValueError:
                    data = b""
                if len(data) >= 5:
                    state["front_sensor_b0_raw"] = data[0]
                    state["front_sensor_b2_raw"] = data[2]
                    state["front_sensor_b4_raw"] = data[4]
                    available_fields.update({
                        "front_sensor_b0_raw",
                        "front_sensor_b2_raw",
                        "front_sensor_b4_raw",
                    })
                    decoded_frame_count += 1
                continue

            if arbitration_id not in TARGET_IDS:
                continue
            try:
                data = bytes.fromhex(str(event.get("data_hex") or ""))
            except ValueError:
                continue
            message, values, error = decoder.decode_frame(
                arbitration_id,
                bool(event.get("extended", arbitration_id > 0x7FF)),
                data,
            )
            if message is None or values is None or error is not None:
                continue
            decoded_frame_count += 1
            _update_state(message.name, values, state, data)
            available_fields.update(key for key in STATE_FIELDS if state.get(key) is not None)

    if first_frame_us is None or last_frame_us is None:
        raise ValueError(f"La session {session_id} ne contient aucune donnée directe lisible.")
    duration_ms = max(0, (last_frame_us - first_frame_us) // 1000)
    if not points:
        points.append(_snapshot(state, 0))
    elif points[0].t_ms > 0:
        points.insert(0, points[0].model_copy(update={"t_ms": 0}))
    if points[-1].t_ms < duration_ms:
        points.append(_snapshot(state, duration_ms))
    if _filter_fuel_level(points):
        available_fields.add("fuel_liters")

    cruise_detection_available = _detect_probable_cruise(points)
    if cruise_detection_available:
        available_fields.update({
            "cruise_probable",
            "cruise_confidence",
            "cruise_detection_state",
            "cruise_detection_reason",
            "cruise_switch_candidate",
            "cruise_active_candidate",
        })

    cruise_controls_available = _detect_cruise_controls(points)
    if cruise_controls_available:
        available_fields.update({
            "cruise_button_event",
            "cruise_button_event_source",
            "cruise_setpoint_direction",
            "cruise_setpoint_step_kph",
        })

    can_fuel_available = _compute_can_fuel_consumption(points)
    if can_fuel_available:
        available_fields.update({
            "can_fuel_rate_lph",
            "can_instant_consumption_l_100km",
            "can_trip_fuel_l",
        })

    steering_zero, distance_m, route_bounds = _reconstruct_route(points)
    raw_distances = [point.distance_m for point in points]
    gps_points = _parse_gps_points(gps_events, first_frame_us, duration_ms)
    dead_reckoning_method = (
        "dead_reckoning_speed_yaw"
        if any(point.yaw_rate_deg_s is not None for point in points)
        else "dead_reckoning_speed_steering"
    )
    route_method, distance_m, route_bounds, used_gps_point_count = _apply_gps_route(
        points,
        gps_points,
        dead_reckoning_method,
    )
    route_override = _load_route_override(path)
    route_override_metadata: dict[str, Any] | None = None
    if route_override is not None:
        route_coordinates, route_override_metadata = route_override
        distance_m, route_bounds = _apply_confirmed_road_route(
            points,
            route_coordinates,
            raw_distances,
        )
        route_method = "driver_confirmed_osrm"
    estimated_fuel_consumption_l_100km, fuel_consumption_note = _estimate_fuel_consumption(points, distance_m)
    can_trip_fuel_total_l, can_average_fuel_consumption_l_100km, can_fuel_consumption_note = (
        _summarize_can_fuel_consumption(points, distance_m, can_fuel_available)
    )
    if used_gps_point_count:
        available_fields.update({"latitude", "longitude", "gps_accuracy_m"})
        if any(point.altitude_m is not None for point in gps_points):
            available_fields.add("gps_altitude_m")
        if any(point.heading_deg is not None for point in gps_points):
            available_fields.add("gps_heading_deg")
        if any(point.speed_kph is not None for point in gps_points):
            available_fields.add("gps_speed_kph")
    moving_speeds = [point.speed_kph for point in points if point.speed_kph is not None and point.speed_kph > 1]
    max_speed = max((point.speed_kph or 0 for point in points), default=0)
    stat = path.stat()
    warnings = [f"Replay préparé le {datetime.now(timezone.utc).isoformat(timespec='seconds')}."]
    if vehicle_profile == "fiat_500_generic":
        warnings[:0] = [
            "Le régime CAN Fiat est validé sur cette 500; les autres mesures moteur marquées OBD sont normalisées Mode 01.",
            "Les vitesses de roue, le frein et les états Body Fiat observés restent des candidats à confirmer par captures annotées.",
            "Les identifiants CAN Fiat non cartographiés restent exclus du replay plutôt que d'être interprétés comme des signaux Peugeot.",
        ]
    else:
        warnings[:0] = [
            "Le DBC AEE2010 R3 est conservé comme catalogue externe de comparaison ; les captures 0x3F2 de cette 308 indiquent une variante R2/EVO à commande de couple.",
            "Le couple signé 0x3F2 est observé sur le véhicule ; les autres libellés OpenDBC restent des candidats à confirmer sur Peugeot 308 T9.",
            "La pression d'huile disponible est un contacteur logique, pas une mesure en bar.",
        ]
    if route_method == "driver_confirmed_osrm":
        roads = ", ".join(route_override_metadata.get("road_refs", [])) if route_override_metadata else ""
        warnings[:0] = [
            "Tracé routier OSRM confirmé par le conducteur; la vitesse CAN synchronise la progression de la voiture.",
            f"Axes confirmés : {roads}." if roads else "Le tracé routier remplace la dérive de navigation à l'estime.",
            "Les positions GPS brutes restent conservées séparément avec leur précision déclarée.",
        ]
    elif route_method == "gps_can_fusion":
        warnings[:0] = [
            "Trajectoire détaillée reconstruite par vitesse/lacet entre les positions GPS, puis recalée sur chaque point GPS.",
            "Les virages entre deux positions sont estimés par le CAN; la précision absolue reste limitée par accuracy_m du navigateur.",
        ]
    elif route_method == "browser_gps":
        warnings.insert(0, "Trajectoire issue de la géolocalisation du navigateur; sa précision dépend du récepteur utilisé et de la valeur accuracy_m enregistrée.")
    elif route_method == "dead_reckoning_gps_anchor":
        warnings[:0] = [
            "Une seule position GPS exploitable a été reçue : elle sert d'ancrage, mais le déplacement reste reconstruit par les capteurs CAN.",
            "La trajectoire dérive progressivement et ne doit pas être considérée comme une trace GPS mesurée.",
        ]
    elif route_method == "dead_reckoning_speed_yaw":
        warnings[:0] = [
            "Aucune coordonnée GPS exploitable n'est présente : la trajectoire utilise la vitesse et le lacet ESP validé sur cette Peugeot.",
            "Le lacet réduit fortement la dérive du volant, mais une navigation à l'estime reste relative et doit être recalée périodiquement.",
        ]
        if gps_points:
            warnings.insert(0, "Des positions GPS ont été enregistrées, mais leur précision déclarée dépasse 1 000 m; elles restent disponibles dans l'export brut.")
    else:
        warnings[:0] = [
            "Aucune coordonnée GPS exploitable n'est présente : la position absolue en France ne peut pas être retrouvée avec cette capture seule.",
            "La trajectoire est une reconstruction locale par vitesse et angle du volant; elle dérive progressivement et ne doit pas être superposée à une route réelle.",
        ]
        if gps_points:
            warnings.insert(0, "Des positions GPS ont été enregistrées, mais leur précision déclarée dépasse 1 000 m; elles restent disponibles dans l'export brut.")

    if cruise_detection_available:
        warnings.append(
            "L’état cruise_probable est une détection comportementale "
            "expérimentale fondée sur la pédale, la stabilité de la vitesse "
            "et la charge moteur. Il ne constitue pas encore un décodage "
            "direct du commodo ou du calculateur moteur."
        )
    if "cruise_xvv_state" in available_fields:
        warnings.append(
            "cruise_xvv_state (0x208 Dyn_CMM.P037_VehV_stXVV) est un candidat fort pour "
            "le régulateur (0 = inactif, 2 = actif, 3 = transitoire), confirmé par "
            "corrélation sur plusieurs essais, mais la définition opendbc reste non "
            "validée officiellement pour cette Peugeot 308 T9 2018."
        )
    if "cruise_setpoint_kph" in available_fields:
        warnings.append(
            "cruise_setpoint_kph (0x50E Dat_CLIM.P219_Com_xPrpReqRaw) est un candidat fort "
            "pour la consigne du régulateur (255 = inactif), confirmé sur 5 engagements "
            "répartis sur 4 essais indépendants, mais non validé officiellement pour cette "
            "Peugeot 308 T9 2018."
        )
    if cruise_controls_available:
        warnings.append(
            "Les commandes du régulateur sont reconstruites depuis 0x50E : ON vient du mode "
            "RVV, SET+/SET- des sauts de consigne et CANCEL d'une désactivation sans frein. "
            "RESUME reste une déduction de réengagement, aucun contact dédié n'étant visible."
        )
    if "front_sensor_b4_raw" in available_fields:
        warnings.append(
            "front_sensor_b0/b2/b4_raw (0x489, non documenté) sont des candidats précoces pour "
            "le radar de stationnement avant : une activité par à-coups a été observée sur deux "
            "essais dédiés, avec une cadence qui semble suivre la proximité. Non validé, "
            "affiché pour permettre une vérification en direct."
        )
    if "rear_left_door" in available_fields or "rear_right_door" in available_fields:
        warnings.append(
            "rear_left_door/rear_right_door (0x412 Dat_BSI, octet 6, bits 0x20/0x40, non "
            "documentés dans opendbc) sont validés par deux essais dédiés porte arrière "
            "gauche/droite (fermé-ouvert-fermé répété, avec DRIVER_DOOR/PASSENGER_DOOR/"
            "PARKING_BRAKE constants pendant les tests)."
        )
    if "rear_door_ajar_candidate" in available_fields:
        warnings.append(
            "rear_door_ajar_candidate (0x78D, non documenté, octet 7) bascule à l'identique "
            "sur les essais porte arrière gauche et droite : hypothèse d'un indicateur "
            "générique « au moins une porte arrière ouverte », non confirmée individuellement."
        )
    if "engine_rpm_3b8_candidate" in available_fields:
        warnings.append(
            "engine_rpm_3b8_candidate (0x3B8, non documenté, octet 0) suit une formule exacte "
            "rpm ≈ (255 − octet) × 32 par rapport au régime moteur validé, sur l'ensemble de "
            "la plage observée (0-2450 tr/min) : copie redondante probable pour un autre ECU."
        )
    if "accelerator_pct_3b8_candidate" in available_fields:
        warnings.append(
            "accelerator_pct_3b8_candidate (0x3B8, non documenté, octet 3) suit une formule "
            "exacte pct ≈ (255 − octet) / 2 par rapport à la pédale accélérateur validée. "
            "Corrige l'hypothèse précédente « climatisation air soufflé » pour cet octet."
        )
    if "accelerator_pct_2e8_candidate" in available_fields:
        warnings.append(
            "accelerator_pct_2e8_candidate (0x2E8, non documenté, octet 1) suit une formule "
            "exacte octet ≈ pct × 2 par rapport à la pédale accélérateur validée : deuxième "
            "copie redondante trouvée sur un identifiant CAN distinct."
        )
    if "engine_state_57c_candidate_raw" in available_fields:
        warnings.append(
            "engine_state_57c_candidate_raw (0x57C, non documenté, octet 5) est anti-corrélé "
            "au régime moteur (r≈-0.79) mais ne prend que 5-7 valeurs distinctes : hypothèse "
            "d'un état moteur discret (ralenti, Start&Stop…), non confirmée."
        )
    if "gear_torque_table_2e8_candidate_raw" in available_fields:
        warnings.append(
            "gear_torque_table_2e8_candidate_raw (0x2E8, non documenté, octet 3) corrèle "
            "modérément avec la vitesse et le rapport engagé (r≈0.66-0.68) mais avec "
            "seulement 4-5 valeurs distinctes : hypothèse d'une table liée au rapport, "
            "non confirmée."
        )
    if "speed_389_candidate_raw" in available_fields:
        warnings.append(
            "speed_389_candidate_raw (0x389, non documenté, octet 0) corrèle modérément avec "
            "la vitesse (r≈0.5) : piste faible, non confirmée."
        )

    field_quality = {
        key: value
        for key, value in FIELD_QUALITY.items()
        if key in available_fields or key in {"x_m", "y_m", "heading_deg", "distance_m"}
    }
    if cruise_detection_available:
        field_quality.update({
            "cruise_probable": "experimental_behavioral_detection",
            "cruise_confidence": "experimental_behavioral_detection",
            "cruise_detection_state": "experimental_behavioral_detection",
            "cruise_detection_reason": "experimental_behavioral_detection",
            "cruise_switch_candidate": "opendbc_candidate",
            "cruise_active_candidate": "opendbc_candidate",
        })
    if cruise_controls_available:
        field_quality.update({
            "cruise_button_event": "vehicle_observed_effect_candidate",
            "cruise_button_event_source": "vehicle_observed_effect_candidate",
            "cruise_setpoint_direction": "vehicle_observed_candidate",
            "cruise_setpoint_step_kph": "vehicle_observed_candidate",
        })

    for field in obd_standardized_fields:
        field_quality[field] = "standardized_obd_mode_01"
    fiat_validated_fields = {"engine_rpm", "brake_active", "driver_door"}
    for field in fiat_observed_fields - fiat_validated_fields:
        field_quality[field] = "fiat_500_vehicle_observed_candidate"
    for field in fiat_observed_fields & fiat_validated_fields:
        field_quality[field] = "validated_on_fiat_500_vin"
    if route_method == "driver_confirmed_osrm":
        field_quality.update({
            "latitude": "driver_confirmed_osrm_route",
            "longitude": "driver_confirmed_osrm_route",
            "x_m": "driver_confirmed_osrm_route",
            "y_m": "driver_confirmed_osrm_route",
            "heading_deg": "driver_confirmed_osrm_route",
            "distance_m": "driver_confirmed_osrm_route_can_timing",
        })
    elif route_method == "gps_can_fusion":
        field_quality.update({
            "latitude": "gps_can_fusion",
            "longitude": "gps_can_fusion",
            "x_m": "gps_can_fusion",
            "y_m": "gps_can_fusion",
            "heading_deg": "gps_can_fusion",
            "distance_m": "gps_can_fusion",
        })
    elif route_method == "browser_gps":
        field_quality.update({
            "x_m": "browser_gps",
            "y_m": "browser_gps",
            "heading_deg": "browser_gps_or_track_bearing",
            "distance_m": "browser_gps_track",
        })
    elif route_method == "dead_reckoning_gps_anchor":
        field_quality.update({
            "latitude": "gps_anchor_plus_dead_reckoning",
            "longitude": "gps_anchor_plus_dead_reckoning",
        })

    assignment = load_session_vehicle(session_id)
    vin = str(assignment.get("vin") or vin or "") or None
    vehicle_profile = str(assignment.get("vehicle_profile") or vehicle_profile or "") or None
    vehicle_label = str(assignment.get("vehicle_label") or vehicle_label or "") or None
    replay = ReplayData(
        version=CACHE_VERSION,
        session_id=session_id,
        name=name,
        vehicle=vehicle_label or vehicle_profile or "Véhicule non attribué",
        vin=vin,
        vehicle_profile=vehicle_profile,
        source=source,
        source_size_bytes=stat.st_size,
        source_mtime_ns=stat.st_mtime_ns,
        route_override_mtime_ns=(
            _route_override_path(path).stat().st_mtime_ns
            if _route_override_path(path).exists()
            else None
        ),
        vehicle_assignment_mtime_ns=session_vehicle_mtime_ns(session_id),
        start_timestamp_us=first_frame_us,
        duration_ms=duration_ms,
        sample_period_ms=SAMPLE_PERIOD_US // 1000,
        frame_count=frame_count,
        decoded_frame_count=decoded_frame_count,
        max_speed_kph=round(max_speed, 1),
        average_moving_speed_kph=round(sum(moving_speeds) / len(moving_speeds), 1) if moving_speeds else 0,
        distance_km=round(distance_m / 1000, 3),
        estimated_fuel_consumption_l_100km=estimated_fuel_consumption_l_100km,
        fuel_consumption_note=fuel_consumption_note,
        can_average_fuel_consumption_l_100km=can_average_fuel_consumption_l_100km,
        can_trip_fuel_total_l=can_trip_fuel_total_l,
        can_fuel_consumption_note=can_fuel_consumption_note,
        gps_available=bool(gps_points),
        gps_point_count=len(gps_points),
        route_method=route_method,
        steering_zero_offset_deg=round(steering_zero, 2),
        route_bounds=route_bounds,
        available_fields=sorted(available_fields),
        field_quality=field_quality,
        warnings=warnings,
        events=_events(points),
        gps_points=gps_points,
        points=points,
    )
    return replay


def prepare_replay(session_id: str, force: bool = False) -> ReplayData:
    path = _session_path(session_id)
    cache_path = path.with_suffix(".replay.json")
    stat = path.stat()
    route_path = _route_override_path(path)
    route_override_mtime_ns = route_path.stat().st_mtime_ns if route_path.exists() else None
    vehicle_assignment_mtime = session_vehicle_mtime_ns(session_id)
    if not force and cache_path.exists():
        try:
            cached = ReplayData.model_validate_json(cache_path.read_text(encoding="utf-8"))
            if (
                cached.version == CACHE_VERSION
                and cached.source_size_bytes == stat.st_size
                and cached.source_mtime_ns == stat.st_mtime_ns
                and cached.route_override_mtime_ns == route_override_mtime_ns
                and cached.vehicle_assignment_mtime_ns == vehicle_assignment_mtime
            ):
                return cached
        except (OSError, ValueError, json.JSONDecodeError):
            pass

    with _PREPARE_LOCK:
        if not force and cache_path.exists():
            try:
                cached = ReplayData.model_validate_json(cache_path.read_text(encoding="utf-8"))
                if (
                    cached.version == CACHE_VERSION
                    and cached.source_size_bytes == stat.st_size
                    and cached.source_mtime_ns == stat.st_mtime_ns
                    and cached.route_override_mtime_ns == route_override_mtime_ns
                    and cached.vehicle_assignment_mtime_ns == vehicle_assignment_mtime
                ):
                    return cached
            except (OSError, ValueError, json.JSONDecodeError):
                pass
        replay = _build_replay(path, session_id)
        temporary = cache_path.with_suffix(cache_path.suffix + ".tmp")
        temporary.write_text(replay.model_dump_json(), encoding="utf-8")
        temporary.replace(cache_path)
        return replay


def replay_geojson(session_id: str) -> dict[str, Any]:
    replay = prepare_replay(session_id)
    if not replay.gps_points:
        raise ValueError(f"La session {session_id} ne contient aucune coordonnée GPS.")

    # The replay points contain the dense GPS/CAN fusion used by the vehicle
    # animation. Sample it at 1 Hz for a compact but turn-preserving export.
    dense_coordinates = [
        [point.longitude, point.latitude]
        for index, point in enumerate(replay.points)
        if point.longitude is not None
        and point.latitude is not None
        and (index % 10 == 0 or index == len(replay.points) - 1)
    ]
    coordinates = dense_coordinates or [
        [point.longitude, point.latitude]
        for point in replay.gps_points
    ]
    geometry: dict[str, Any]
    if len(coordinates) == 1:
        geometry = {"type": "Point", "coordinates": coordinates[0]}
    else:
        geometry = {"type": "LineString", "coordinates": coordinates}
    longitudes = [coordinate[0] for coordinate in coordinates]
    latitudes = [coordinate[1] for coordinate in coordinates]
    bbox = [min(longitudes), min(latitudes), max(longitudes), max(latitudes)]
    return {
        "type": "FeatureCollection",
        "bbox": bbox,
        "features": [{
            "type": "Feature",
            "id": replay.session_id,
            "bbox": bbox,
            "geometry": geometry,
            "properties": {
                "session_id": replay.session_id,
                "name": replay.name,
                "vehicle": replay.vehicle,
                "start_timestamp_us": replay.start_timestamp_us,
                "duration_ms": replay.duration_ms,
                "point_count": replay.gps_point_count,
                "route_point_count": len(coordinates),
                "route_method": replay.route_method,
                "timestamps_us": [point.timestamp_us for point in replay.gps_points],
                "accuracy_m": [point.accuracy_m for point in replay.gps_points],
                "altitude_m": [point.altitude_m for point in replay.gps_points],
                "heading_deg": [point.heading_deg for point in replay.gps_points],
                "speed_kph": [point.speed_kph for point in replay.gps_points],
            },
        }],
    }
