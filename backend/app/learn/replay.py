from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from statistics import median
from typing import Any
import json
import math
import threading

from app.config import settings
from app.learn.models import ReplayData, ReplayEvent, ReplaySample
from app.learn.opendbc import get_opendbc_decoder


CACHE_VERSION = 4
SAMPLE_PERIOD_US = 100_000
WHEELBASE_M = 2.62
STEERING_RATIO = 15.3

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
    0x3CD,  # freinage
    0x3F2,  # maintien dans la voie
    0x412,  # BSI
    0x452,  # commandes conducteur
    0x488,  # températures moteur / huile / admission
    0x50D,  # intervention ABS
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
    if field not in {"t_ms", "x_m", "y_m", "heading_deg", "distance_m"}
)

FIELD_QUALITY = {
    "steering_angle_deg": "validated_on_vehicle",
    "steering_rate_deg_s": "validated_on_vehicle",
    "driver_torque": "validated_on_vehicle",
    "speed_kph": "opendbc_candidate",
    "engine_rpm": "opendbc_candidate",
    "accelerator_pct": "opendbc_candidate",
    "engine_torque_nm": "opendbc_candidate",
    "current_gear": "opendbc_candidate",
    "target_gear": "opendbc_candidate",
    "gear_shift_active": "opendbc_candidate",
    "drivetrain_engaged_state": "opendbc_candidate_raw_state",
    "longitudinal_accel_ms2": "opendbc_candidate",
    "brake_active": "opendbc_candidate",
    "brake_system_state": "opendbc_candidate",
    "brake_pressure_raw": "opendbc_candidate_unscaled",
    "turn_signal": "opendbc_candidate",
    "low_beam": "opendbc_candidate",
    "high_beam": "opendbc_candidate",
    "reverse": "opendbc_candidate",
    "parking_brake": "opendbc_candidate",
    "driver_door": "opendbc_candidate",
    "passenger_door": "opendbc_candidate",
    "front_wiper_status": "opendbc_candidate",
    "fuel_liters": "opendbc_candidate",
    "oil_temperature_c": "opendbc_candidate",
    "coolant_temperature_c": "opendbc_candidate",
    "intake_air_temperature_c": "opendbc_candidate",
    "oil_pressure_switch": "opendbc_candidate_state_only",
    "battery_voltage_v": "opendbc_candidate",
    "battery_temperature_c": "opendbc_candidate",
    "battery_charge_pct": "opendbc_candidate",
    "ambient_temperature_c": "opendbc_candidate",
    "atmospheric_pressure_hpa": "opendbc_candidate",
    "obd_error": "opendbc_candidate",
    "mil_on": "opendbc_candidate",
    "mil_blinking": "opendbc_candidate",
    "esp_fault_state": "opendbc_candidate",
    "esp_intervention": "opendbc_candidate",
    "abs_intervention": "opendbc_candidate",
    "gearbox_fault": "opendbc_candidate",
    "generic_warning_requested": "opendbc_candidate",
    "brake_fault": "opendbc_candidate",
    "low_fuel_warning": "opendbc_candidate",
    "fuel_level_fault_state": "opendbc_candidate",
    "headlamp_fault": "opendbc_candidate",
    "driver_seatbelt_state": "opendbc_candidate_raw_state",
    "passenger_seatbelt_state": "opendbc_candidate_raw_state",
    "lane_assist_status": "opendbc_candidate",
    "lane_departure": "opendbc_candidate",
    "lka_active": "opendbc_candidate",
    "acc_mode": "opendbc_candidate",
    "acc_requested": "opendbc_candidate",
    "speed_setpoint_kph": "opendbc_candidate",
    "wheel_front_left_kph": "opendbc_candidate",
    "wheel_front_right_kph": "opendbc_candidate",
    "wheel_rear_left_kph": "opendbc_candidate",
    "wheel_rear_right_kph": "opendbc_candidate",
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
    return ReplaySample(
        t_ms=max(0, t_ms),
        **{key: _rounded(state.get(key)) for key in STATE_FIELDS},
    )


def _update_state(message: str, values: dict[str, dict[str, Any]], state: dict[str, Any]) -> None:
    if message == "Dyn_CMM":
        state["engine_rpm"] = _number(values, "P000_Com_nEng")
        state["accelerator_pct"] = _number(values, "P002_Com_rAPP")
        state["engine_torque_nm"] = _number(values, "P003_Com_trqActOut")
    elif message == "Dyn2_CMM":
        current_gear = _number(values, "P152_Gearbx_stGear")
        state["current_gear"] = int(current_gear) if current_gear is not None and 0 <= current_gear <= 9 else None
        esp_fault = _number(values, "P025_Com_stESPErr")
        state["esp_fault_state"] = int(esp_fault) if esp_fault is not None else None
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
        state["esp_intervention"] = _boolean(values, "P147_Com_bESPIntvActv")
    elif message == "Dyn_STT_BV":
        state["gearbox_fault"] = _boolean(values, "P444_Com_bGbxSysFaultRaw")
    elif message == "Dyn5_CMM" and state.get("accelerator_pct") is None:
        state["accelerator_pct"] = _number(values, "P334_ACCPed_Position")
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
    elif message == "Dyn2_FRE":
        brake_state = _number(values, "P226_Com_stBrkActv")
        state["brake_system_state"] = int(brake_state) if brake_state is not None else None
        state["brake_pressure_raw"] = _number(values, "BRAKE_PRESSURE")
    elif message == "Dat_BSI":
        state["reverse"] = _boolean(values, "P103_Com_bRevGear")
        state["parking_brake"] = _boolean(values, "PARKING_BRAKE")
        state["brake_active"] = _boolean(values, "P013_MainBrake")
        state["driver_door"] = _boolean(values, "DRIVER_DOOR")
        state["passenger_door"] = _boolean(values, "PASSENGER_DOOR")
        state["brake_fault"] = _boolean(values, "P040_MainBrakeFault")
        state["low_fuel_warning"] = _boolean(values, "P012_Com_bFlMin")
        fuel_level_fault = _number(values, "P086_Com_stFlLvlDia")
        state["fuel_level_fault_state"] = int(fuel_level_fault) if fuel_level_fault is not None else None
    elif message == "HS2_DAT_MDD_CMD_452":
        signal = _number(values, "TURN_SIGNAL_STATUS")
        if signal is not None:
            state["turn_signal"] = {0: "off", 1: "right", 2: "left", 3: "hazard"}.get(int(signal), "off")
        state["front_wiper_status"] = int(_number(values, "FRONT_WIPER_STATUS") or 0)
        state["speed_setpoint_kph"] = _number(values, "SPEED_SETPOINT")
        state["acc_mode"] = int(_number(values, "LONGITUDINAL_REGULATION_TYPE") or 0)
        state["acc_requested"] = _boolean(values, "RVV_ACC_ACTIVATION_REQ")
    elif message == "HS2_DAT7_BSI_612":
        state["low_beam"] = _boolean(values, "ETAT_FEUX_CROIST")
        state["high_beam"] = _boolean(values, "ETAT_FEUX_ROUTE")
        state["fuel_liters"] = _number(values, "INFO_NIV_CARB")
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
    elif message == "Dat2_CMM":
        pressure_switch = _number(values, "P278_Oil_stPSwmp")
        state["oil_pressure_switch"] = bool(pressure_switch) if pressure_switch is not None else None
        state["atmospheric_pressure_hpa"] = _number(values, "P338_EnvP_p")
    elif message == "Dat6_BSI":
        state["battery_charge_pct"] = _number(values, "P272_Com_rBattCh")
        state["battery_temperature_c"] = _number(values, "P273_Com_tBatt")
        state["battery_voltage_v"] = _number(values, "P418_Com_uBattRaw")
    elif message == "Contexte1_5B2":
        state["ambient_temperature_c"] = _number(values, "P146_Com_tEnvT")
    elif message == "LANE_KEEP_ASSIST":
        status = _number(values, "STATUS")
        departure = _number(values, "LANE_DEPARTURE")
        state["lane_assist_status"] = int(status) if status is not None else None
        state["lane_departure"] = int(departure) if departure is not None else None
        state["lka_active"] = _boolean(values, "LXA_ACTIVATION")
    elif message == "DRIVER" and state.get("accelerator_pct") is None:
        state["accelerator_pct"] = _number(values, "GAS_PEDAL")


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
    source = ""
    name = session_id

    with path.open(encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            try:
                event = json.loads(line)
            except (TypeError, ValueError, json.JSONDecodeError):
                continue
            if event.get("type") == "meta":
                source = str(event.get("source") or source)
                name = str(event.get("name") or name)
                continue
            if event.get("type") != "can_frame":
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
            _update_state(message.name, values, state)
            available_fields.update(key for key in STATE_FIELDS if state.get(key) is not None)

    if first_frame_us is None or last_frame_us is None:
        raise ValueError(f"La session {session_id} ne contient aucune trame CAN lisible.")
    duration_ms = max(0, (last_frame_us - first_frame_us) // 1000)
    if not points:
        points.append(_snapshot(state, 0))
    elif points[0].t_ms > 0:
        points.insert(0, points[0].model_copy(update={"t_ms": 0}))
    if points[-1].t_ms < duration_ms:
        points.append(_snapshot(state, duration_ms))

    steering_zero, distance_m, route_bounds = _reconstruct_route(points)
    moving_speeds = [point.speed_kph for point in points if point.speed_kph is not None and point.speed_kph > 1]
    max_speed = max((point.speed_kph or 0 for point in points), default=0)
    stat = path.stat()
    replay = ReplayData(
        version=CACHE_VERSION,
        session_id=session_id,
        name=name,
        vehicle="Peugeot 308 T9 · 2018",
        source=source,
        source_size_bytes=stat.st_size,
        source_mtime_ns=stat.st_mtime_ns,
        start_timestamp_us=first_frame_us,
        duration_ms=duration_ms,
        sample_period_ms=SAMPLE_PERIOD_US // 1000,
        frame_count=frame_count,
        decoded_frame_count=decoded_frame_count,
        max_speed_kph=round(max_speed, 1),
        average_moving_speed_kph=round(sum(moving_speeds) / len(moving_speeds), 1) if moving_speeds else 0,
        distance_km=round(distance_m / 1000, 3),
        route_method="dead_reckoning_speed_steering",
        steering_zero_offset_deg=round(steering_zero, 2),
        route_bounds=route_bounds,
        available_fields=sorted(available_fields),
        field_quality={key: value for key, value in FIELD_QUALITY.items() if key in available_fields or key in {"x_m", "y_m", "heading_deg", "distance_m"}},
        warnings=[
            "Aucune coordonnée GPS n'est présente : la position absolue en France ne peut pas être retrouvée avec cette capture seule.",
            "La trajectoire est une reconstruction locale par vitesse et angle du volant; elle dérive progressivement et ne doit pas être superposée à une route réelle.",
            "À l'exception de la direction validée sur ce véhicule, les libellés OpenDBC restent des candidats à confirmer sur Peugeot 308 T9.",
            "La pression d'huile disponible est un contacteur logique, pas une mesure en bar.",
            f"Replay préparé le {datetime.now(timezone.utc).isoformat(timespec='seconds')}.",
        ],
        events=_events(points),
        points=points,
    )
    return replay


def prepare_replay(session_id: str, force: bool = False) -> ReplayData:
    path = _session_path(session_id)
    cache_path = path.with_suffix(".replay.json")
    stat = path.stat()
    if not force and cache_path.exists():
        try:
            cached = ReplayData.model_validate_json(cache_path.read_text(encoding="utf-8"))
            if (
                cached.version == CACHE_VERSION
                and cached.source_size_bytes == stat.st_size
                and cached.source_mtime_ns == stat.st_mtime_ns
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
                ):
                    return cached
            except (OSError, ValueError, json.JSONDecodeError):
                pass
        replay = _build_replay(path, session_id)
        temporary = cache_path.with_suffix(cache_path.suffix + ".tmp")
        temporary.write_text(replay.model_dump_json(), encoding="utf-8")
        temporary.replace(cache_path)
        return replay
