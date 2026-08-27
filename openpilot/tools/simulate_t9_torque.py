#!/usr/bin/env python3
"""Offline Peugeot 308 T9 lateral torque shadow simulator.

This tool deliberately has no serial, CAN transmission, panda, cereal or
vehicle-control dependency.  It only consumes recordings made by
``run_openpilot_live.py`` and writes numerical shadow-command reports.

The actuator transfer function of the T9 steering ECU has not been validated.
Consequently the simulator evaluates several explicit plant-gain hypotheses;
it must not be treated as a source of vehicle-ready controller parameters.
"""

from __future__ import annotations

import argparse
from bisect import bisect_left
import csv
import html
import json
import math
import statistics
from collections import Counter, deque
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Iterator, Sequence

import cantools

try:
    from tools.render_camera_can_replay import DecodeCounters, decode_can_frame, iter_can_frames
except ModuleNotFoundError:  # Direct execution from openpilot/tools.
    from render_camera_can_replay import DecodeCounters, decode_can_frame, iter_can_frames


OPENPILOT_LAB_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = OPENPILOT_LAB_ROOT.parent
DEFAULT_DBC = REPO_ROOT / "database/psa/dbc/peugeot_308_t9_2018.dbc"
DEFAULT_OUTPUT_ROOT = REPO_ROOT / "data/runtime/t9_torque_simulator"
DEFAULT_FACTORY_EVIDENCE = (
    REPO_ROOT / "data/sessions/learn-20260805T081220Z-a182e602.jsonl"
)

GRAVITY_MS2 = 9.81
T9_WHEELBASE_M = 2.62
T9_STEERING_RATIO = 15.3
T9_STEERING_ZERO_DEG = 1.5

# Pinned behavior of commaai/openpilot's LatControlTorque at revision
# 4a13639cfd122ccb9113a4d6ce225dcbd8e61914 (2026-08-26).  The controller
# remains reimplemented locally so this strictly offline tool has no openpilot
# runtime dependency.
OPENPILOT_TORQUE_REVISION = "4a13639cfd122ccb9113a4d6ce225dcbd8e61914"
OPENPILOT_TORQUE_KP = 0.8
OPENPILOT_TORQUE_KI = 0.15
OPENPILOT_TORQUE_KP_SPEEDS_MS = (1.0, 1.5, 2.0, 3.0, 5.0, 7.5, 10.0, 15.0, 30.0)
OPENPILOT_TORQUE_KP_VALUES = (250.0, 120.0, 65.0, 30.0, 11.5, 5.5, 3.5, 2.0, 0.8)
SUNNYPILOT_TORQUE_REVISION = "2d6cc4c065c4d1833dc267fff60ebae48b444817"
SUNNYPILOT_TORQUE_V0_KP = 1.0
SUNNYPILOT_TORQUE_V0_KI = 0.3

# Read-only reference pinned by cristianku/openpilot's psa-torque-sunny branch
# on 2026-08-04.  These values describe a 3008/C4 SpaceTourer AEE2010 R3
# experiment.  They are never used as T9 transmission limits or CAN payloads.
CRISTIANKU_OPENPILOT_REVISION = "1f033bc05b78db6d29489f704b8b6965a550a9fe"
CRISTIANKU_OPENDBC_REVISION = "6dddbdb2d534bf51b178df23d71691ee1d606f45"
CRISTIANKU_R3_REFERENCE = {
    "architecture": "AEE2010 R3",
    "vehicles": ["Peugeot 3008 II", "Citroen C4 SpaceTourer"],
    "steer_step_hz": 20.0,
    "software_steer_max_raw": 150,
    "software_safety_max_raw": 200,
    "torque_factor_min_raw": 25,
    "torque_factor_max_raw": 100,
    "lka_unknown_byte2_raw": 0x18,
    "eps_active_state_raw": 3,
    "eps_rearm_period_s": 8.0,
    "spoofs_steering_wheel_hold": True,
    "spoofs_driver_torque": True,
    "torque_violation_blocks_tx": False,
}

T9_FACTORY_EVIDENCE = {
    "architecture": "AEE2010 R2/EVO",
    "lka_unknown_byte2_raw": 0x12,
    "lka_torque_factor_raw": 0,
    "column_angle_setpoint_deg": 0.0,
    "observed_nonzero_torque_min_raw": -7,
    "observed_nonzero_torque_max_raw": 60,
    "eps_states_seen_near_nonzero_lka": [1, 2],
    "nonzero_lka_samples": 536,
}


@dataclass(frozen=True)
class SimulatorConfig:
    min_speed_kph: float = 32.2
    max_lateral_accel_ms2: float = 1.5
    max_torque_raw: float = 10.0
    torque_rate_up_raw_s: float = 20.0
    torque_rate_down_raw_s: float = 60.0
    driver_override_raw: float = 5.0
    max_can_age_s: float = 0.25
    path_filter_tau_s: float = 0.35
    path_fit_max_rmse_m: float = 0.35
    plant_time_constant_s: float = 0.30


@dataclass(frozen=True)
class ControllerParameters:
    plant_gain_ms2_per_raw: float
    feedforward_raw_per_ms2: float
    kp_raw_per_ms2: float
    ki_raw_per_ms2_s: float


@dataclass(frozen=True)
class OpenpilotTorqueParameters:
    """Offline equivalent of openpilot's lateral-acceleration torque loop.

    ``friction`` uses openpilot/opendbc's normalized-torque convention.  The
    0.08 value is only a conservative PSA R3-derived shadow prior; unlike the
    controller structure, it is not claimed to be identified for the T9.
    """

    plant_gain_ms2_per_raw: float
    kp_high_speed: float = OPENPILOT_TORQUE_KP
    ki: float = OPENPILOT_TORQUE_KI
    feedforward_scale: float = 1.0
    kp_schedule_scale: float = 1.0
    ki_scale: float = 1.0
    friction: float = 0.08
    lat_accel_offset_ms2: float = 0.0
    lateral_delay_s: float = 0.15
    request_buffer_s: float = 1.0
    jerk_lookahead_s: float = 0.19
    jerk_lookahead_max_s: float | None = None
    future_jerk_lookahead: bool = False
    jerk_gain: float = 0.3
    friction_error_scale: float = 1.0
    jerk_filter_cutoff_hz: float = 1.2
    friction_threshold_ms2: float = 0.2
    steering_angle_deadzone_deg: float = 0.0


@dataclass(frozen=True)
class EpsStatus495:
    eps_torque_candidate_nm: float
    steering_wheel_held_by_driver: bool
    eps_state_lka_raw: int
    dynamic_steering_state_raw: int


@dataclass
class ReplaySample:
    session_id: str
    timestamp_us: int
    elapsed_s: float
    dt_s: float
    speed_kph: float
    desired_curvature_raw_1pm: float
    desired_curvature_1pm: float
    desired_lateral_accel_ms2: float
    measured_lateral_accel_yaw_ms2: float
    measured_lateral_accel_sensor_ms2: float | None
    steering_angle_deg: float | None
    steering_rate_deg_s: float | None
    driver_torque_raw: float
    observed_lka_torque_raw: float | None
    observed_lka_state_raw: int | None
    observed_lka_torque_factor_raw: int | None
    observed_lka_unknown_byte2_raw: int | None
    observed_column_angle_setpoint_deg: float | None
    eps_torque_candidate_nm: float | None
    eps_state_lka_raw: int | None
    steering_wheel_held_by_driver: bool | None
    eps_status_age_s: float
    path_fit_rmse_m: float
    can_age_s: float
    brake_active: bool
    reverse: bool
    parking_brake: bool
    driver_door_open: bool
    driver_seatbelt_state: int | None
    current_gear: int | None
    counterfactual_eligible: bool
    safety_reasons: list[str]
    matek_lateral_accel_right_ms2: float | None = None
    matek_yaw_rate_right_deg_s: float | None = None
    matek_sensor_age_s: float = math.inf
    matek_gps_speed_mps: float | None = None
    matek_gps_latitude_deg: float | None = None
    matek_gps_longitude_deg: float | None = None
    matek_gps_age_s: float = math.inf
    road_roll_rad: float | None = None


@dataclass
class SimulationRow:
    sample: ReplaySample
    simulated_lateral_accel_ms2: float
    lateral_accel_error_ms2: float
    unrestricted_torque_raw: float
    safety_applied_torque_raw: float
    saturated: bool
    eps_rearm_active: bool = False
    rearm_limited_torque_raw: float = 0.0
    rearm_simulated_lateral_accel_ms2: float = 0.0
    rearm_lateral_accel_error_ms2: float = 0.0
    controller_setpoint_ms2: float | None = None
    controller_measurement_ms2: float | None = None
    controller_error_ms2: float | None = None
    feedforward_ms2: float | None = None
    proportional_ms2: float | None = None
    integral_ms2: float | None = None
    friction_compensation_ms2: float | None = None
    roll_compensation_ms2: float | None = None
    desired_lateral_jerk_ms3: float | None = None
    integrator_frozen: bool = False


@dataclass(frozen=True)
class DriverProxyFit:
    sample_count: int
    apparent_gain_ms2_per_driver_raw: float
    intercept_ms2: float
    correlation: float
    rmse_ms2: float
    r_squared: float


def _finite_number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    number = float(value)
    return number if math.isfinite(number) else None


def decode_eps_status_495(data: bytes) -> EpsStatus495:
    """Decode the useful read-only fields of PSA ``IS_DAT_DIRA`` (0x495).

    The bit positions come from the R3 reference DBC.  State meanings are kept
    raw because the T9 R2 traces demonstrably do not use the R3 ``3=active``
    convention during their factory 0x3F2 torque bursts.
    """
    if len(data) != 4:
        raise ValueError(f"0x495 doit contenir 4 octets, reçu {len(data)}")
    torque_raw = data[0] - 256 if data[0] & 0x80 else data[0]
    return EpsStatus495(
        eps_torque_candidate_nm=torque_raw * 0.25,
        # Motorola DBC positions 17|1 and 20|3 map to byte-2 bits 1 and 4..2.
        steering_wheel_held_by_driver=bool(data[2] & 0x02),
        eps_state_lka_raw=(data[2] >> 2) & 0x07,
        dynamic_steering_state_raw=(data[1] >> 4) & 0x03,
    )


def _solve_3x3(matrix: list[list[float]], vector: list[float]) -> tuple[float, float, float] | None:
    augmented = [row[:] + [value] for row, value in zip(matrix, vector, strict=True)]
    for column in range(3):
        pivot = max(range(column, 3), key=lambda row: abs(augmented[row][column]))
        if abs(augmented[pivot][column]) < 1e-12:
            return None
        augmented[column], augmented[pivot] = augmented[pivot], augmented[column]
        divisor = augmented[column][column]
        augmented[column] = [value / divisor for value in augmented[column]]
        for row in range(3):
            if row == column:
                continue
            factor = augmented[row][column]
            augmented[row] = [
                current - factor * reference
                for current, reference in zip(augmented[row], augmented[column], strict=True)
            ]
    return augmented[0][3], augmented[1][3], augmented[2][3]


def _quadratic_fit(points: Sequence[tuple[float, float]]) -> tuple[float, float, float] | None:
    if len(points) < 5:
        return None
    sx = sum(x for x, _ in points)
    sx2 = sum(x * x for x, _ in points)
    sx3 = sum(x * x * x for x, _ in points)
    sx4 = sum(x * x * x * x for x, _ in points)
    sy = sum(y for _, y in points)
    sxy = sum(x * y for x, y in points)
    sx2y = sum(x * x * y for x, y in points)
    return _solve_3x3(
        [[sx4, sx3, sx2], [sx3, sx2, sx], [sx2, sx, float(len(points))]],
        [sx2y, sxy, sy],
    )


def estimate_path_curvature(
    path: Any,
    speed_ms: float,
) -> tuple[float, float] | None:
    """Estimate vehicle-frame curvature from openpilot's camera-frame path.

    The model uses positive lateral ``y`` in the opposite direction to the
    validated PSA yaw/steering signs, hence the explicit minus sign below.
    """
    if not isinstance(path, list) or not math.isfinite(speed_ms):
        return None
    horizon_m = min(30.0, max(12.0, speed_ms * 1.25))
    points: list[tuple[float, float]] = []
    for point in path:
        if not isinstance(point, (list, tuple)) or len(point) < 2:
            continue
        x = _finite_number(point[0])
        y = _finite_number(point[1])
        if x is not None and y is not None and 2.0 <= x <= horizon_m:
            points.append((x, y))
    fit = _quadratic_fit(points)
    if fit is None:
        return None

    # A single bad far-path point can otherwise dominate a short-horizon fit.
    residuals = [y - (fit[0] * x * x + fit[1] * x + fit[2]) for x, y in points]
    median = statistics.median(residuals)
    mad = statistics.median(abs(value - median) for value in residuals)
    threshold = max(0.08, 3.5 * 1.4826 * mad)
    inliers = [
        point for point, residual in zip(points, residuals, strict=True)
        if abs(residual - median) <= threshold
    ]
    if len(inliers) >= 5:
        fit = _quadratic_fit(inliers) or fit
        points = inliers

    a, b, c = fit
    lookahead_m = min(7.0, max(3.0, speed_ms * 0.30))
    slope = 2.0 * a * lookahead_m + b
    curvature_camera = 2.0 * a / ((1.0 + slope * slope) ** 1.5)
    residual_rms = math.sqrt(
        sum((y - (a * x * x + b * x + c)) ** 2 for x, y in points) / len(points)
    )
    return -curvature_camera, residual_rms


def apply_torque_limits(
    requested: float,
    previous: float,
    dt_s: float,
    config: SimulatorConfig,
) -> float:
    """Apply the conservative, pre-existing T9 shadow torque envelope."""
    requested = max(-config.max_torque_raw, min(config.max_torque_raw, requested))
    dt_s = max(0.0, min(0.5, dt_s))
    up = config.torque_rate_up_raw_s * dt_s
    down = config.torque_rate_down_raw_s * dt_s
    if previous > 0.0:
        lower = max(previous - down, -up)
        upper = previous + up
    else:
        lower = previous - up
        upper = min(previous + down, up)
    return max(lower, min(upper, requested))


def safety_reasons(state: dict[str, Any], config: SimulatorConfig, can_age_s: float) -> list[str]:
    reasons: list[str] = []
    speed = _finite_number(state.get("speed_kph"))
    if speed is None or speed < config.min_speed_kph:
        reasons.append("speed_below_threshold")
    if bool(state.get("brake_active")):
        reasons.append("brake_active")
    if bool(state.get("reverse")):
        reasons.append("reverse")
    if bool(state.get("parking_brake")):
        reasons.append("parking_brake")
    if bool(state.get("driver_door")):
        reasons.append("driver_door_open")
    seatbelt = state.get("driver_seatbelt_state")
    if seatbelt != 2:
        reasons.append("driver_seatbelt_not_latched")
    current_gear = state.get("current_gear")
    if not isinstance(current_gear, (int, float)) or not 1 <= int(current_gear) <= 6:
        reasons.append("drive_gear_not_confirmed")
    if not math.isfinite(can_age_s) or can_age_s > config.max_can_age_s:
        reasons.append("can_stale")
    eps_status_age_s = _finite_number(state.get("_eps_status_age_s"))
    if eps_status_age_s is None or eps_status_age_s > config.max_can_age_s:
        reasons.append("eps_status_stale")
    driver_torque = _finite_number(state.get("driver_torque_raw"))
    if driver_torque is None:
        reasons.append("driver_torque_missing")
    elif abs(driver_torque) > config.driver_override_raw:
        reasons.append("driver_override")
    return reasons


def _load_perception(path: Path) -> Iterator[dict[str, Any]]:
    with path.open(encoding="utf-8") as stream:
        for line_number, line in enumerate(stream, 1):
            if not line.strip():
                continue
            try:
                record = json.loads(line)
                int(record["timestamp_us"])
            except (json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
                raise ValueError(f"{path}:{line_number}: perception invalide") from exc
            yield record


def _perception_road_roll_rad(record: dict[str, Any]) -> float | None:
    """Read a localization road-roll signal when a future recorder provides it.

    Camera calibration roll is intentionally excluded: it describes camera
    mounting, whereas LatControlTorque expects the vehicle/road roll estimated
    by localization.
    """
    direct = _finite_number(record.get("road_roll_rad"))
    if direct is not None:
        return direct
    for container_name in ("localization", "live_pose", "live_parameters"):
        container = record.get(container_name)
        if isinstance(container, dict):
            nested = _finite_number(container.get("road_roll_rad"))
            if nested is None:
                nested = _finite_number(container.get("roll_rad"))
            if nested is not None:
                return nested
    return None


@dataclass(frozen=True)
class AuxiliarySensorTimeline:
    imu: list[dict[str, Any]]
    gps: list[dict[str, Any]]
    summary: dict[str, Any]


def _sensor_timestamp(record: dict[str, Any]) -> int | None:
    value = record.get("received_timestamp_us")
    try:
        timestamp = int(value)
    except (TypeError, ValueError):
        return None
    return timestamp if timestamp > 0 else None


def _stream_timing_summary(records: Sequence[dict[str, Any]]) -> dict[str, Any]:
    timestamps = [
        timestamp for record in records
        if (timestamp := _sensor_timestamp(record)) is not None
    ]
    gaps = [
        (second - first) / 1_000_000.0
        for first, second in zip(timestamps, timestamps[1:])
        if second > first
    ]
    return {
        "samples": len(timestamps),
        "duration_s": (
            round((timestamps[-1] - timestamps[0]) / 1_000_000.0, 3)
            if len(timestamps) >= 2 else 0.0
        ),
        "mean_hz": (
            (len(timestamps) - 1) * 1_000_000.0 / (timestamps[-1] - timestamps[0])
            if len(timestamps) >= 2 and timestamps[-1] > timestamps[0] else 0.0
        ),
        "maximum_gap_s": max(gaps, default=0.0),
    }


def _gps_track_distance_m(records: Sequence[dict[str, Any]]) -> float:
    distance_m = 0.0
    previous: tuple[float, float] | None = None
    for record in records:
        latitude = _finite_number(record.get("latitude_deg"))
        longitude = _finite_number(record.get("longitude_deg"))
        if latitude is None or longitude is None:
            continue
        current = math.radians(latitude), math.radians(longitude)
        if previous is not None:
            delta_latitude = current[0] - previous[0]
            delta_longitude = current[1] - previous[1]
            haversine = (
                math.sin(delta_latitude / 2.0) ** 2
                + math.cos(previous[0]) * math.cos(current[0])
                * math.sin(delta_longitude / 2.0) ** 2
            )
            distance_m += 2.0 * 6_371_000.0 * math.asin(min(1.0, math.sqrt(haversine)))
        previous = current
    return distance_m


def load_auxiliary_sensor_timeline(path: Path) -> AuxiliarySensorTimeline:
    if not path.is_file():
        return AuxiliarySensorTimeline([], [], {"available": False, "source": None})

    imu: list[dict[str, Any]] = []
    gps: list[dict[str, Any]] = []
    device: dict[str, Any] | None = None
    malformed_lines = 0
    with path.open(encoding="utf-8") as stream:
        for line in stream:
            if not line.strip():
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                malformed_lines += 1
                continue
            if not isinstance(record, dict) or _sensor_timestamp(record) is None:
                malformed_lines += 1
                continue
            if record.get("type") == "device" and record.get("source") == "matek_f722_se_msp":
                device = record
            elif record.get("type") == "imu" and record.get("source") == "matek_f722_se_msp":
                if (
                    _finite_number(record.get("acceleration_right_ms2")) is not None
                    and _finite_number(record.get("yaw_rate_right_deg_s")) is not None
                ):
                    imu.append(record)
            elif record.get("type") == "gps" and record.get("source") == "matek_f722_se_msp":
                gps.append(record)

    imu.sort(key=lambda record: int(record["received_timestamp_us"]))
    gps.sort(key=lambda record: int(record["received_timestamp_us"]))
    valid_gps = [
        record for record in gps
        if bool(record.get("fix_valid"))
        and _finite_number(record.get("latitude_deg")) is not None
        and _finite_number(record.get("longitude_deg")) is not None
    ]
    summary = {
        "available": bool(imu or gps),
        "source": "matek_f722_se_msp" if imu or gps else None,
        "path": str(path),
        "device": {
            key: device.get(key)
            for key in (
                "fc_variant", "fc_version", "board_identifier", "msp_api_version",
                "mounting_yaw_deg", "accel_lsb_per_g",
            )
        } if device else None,
        "imu": _stream_timing_summary(imu),
        "gps": {
            **_stream_timing_summary(gps),
            "valid_fix_samples": len(valid_gps),
            "track_distance_m": _gps_track_distance_m(valid_gps),
            "first_fix": (
                {
                    "latitude_deg": valid_gps[0].get("latitude_deg"),
                    "longitude_deg": valid_gps[0].get("longitude_deg"),
                }
                if valid_gps else None
            ),
            "last_fix": (
                {
                    "latitude_deg": valid_gps[-1].get("latitude_deg"),
                    "longitude_deg": valid_gps[-1].get("longitude_deg"),
                }
                if valid_gps else None
            ),
        },
        "malformed_lines": malformed_lines,
    }
    return AuxiliarySensorTimeline(imu, gps, summary)


def analyze_factory_evidence(path: Path, dbc_path: Path) -> dict[str, Any]:
    """Summarize the known T9 factory LKA burst without interpreting R3 states."""
    database = cantools.database.load_file(str(dbc_path))
    lka_message = database.get_message_by_frame_id(0x3F2)
    latest_eps: EpsStatus495 | None = None
    latest_eps_timestamp_us: int | None = None
    total_lka = 0
    nonzero: list[tuple[int, dict[str, Any], EpsStatus495 | None]] = []
    with path.open(encoding="utf-8") as stream:
        for line_number, line in enumerate(stream, 1):
            if not line.strip():
                continue
            try:
                payload = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"{path}:{line_number}: JSON invalide") from exc
            if payload.get("type") != "can_frame" or payload.get("direction") != "rx":
                continue
            address = payload.get("arbitration_id")
            try:
                timestamp_us = int(payload["timestamp_us"])
                data = bytes.fromhex(payload["data_hex"])
            except (KeyError, TypeError, ValueError) as exc:
                raise ValueError(f"{path}:{line_number}: trame CAN invalide") from exc
            if address == 0x495:
                latest_eps = decode_eps_status_495(data)
                latest_eps_timestamp_us = timestamp_us
            elif address == 0x3F2:
                total_lka += 1
                decoded = lka_message.decode(data, decode_choices=False)
                torque = _finite_number(decoded.get("LKATorqueCommandRaw")) or 0.0
                eps = latest_eps
                if latest_eps_timestamp_us is None or timestamp_us - latest_eps_timestamp_us > 150_000:
                    eps = None
                if torque != 0.0:
                    nonzero.append((timestamp_us, decoded, eps))

    burst_threshold_us = 90_000
    bursts: list[list[tuple[int, dict[str, Any], EpsStatus495 | None]]] = []
    for item in nonzero:
        if bursts and item[0] - bursts[-1][-1][0] <= burst_threshold_us:
            bursts[-1].append(item)
        else:
            bursts.append([item])
    torque_values = [float(item[1]["LKATorqueCommandRaw"]) for item in nonzero]
    eps_states = Counter(
        item[2].eps_state_lka_raw for item in nonzero if item[2] is not None
    )
    hold_values = Counter(
        item[2].steering_wheel_held_by_driver for item in nonzero if item[2] is not None
    )
    factor_active = [
        item for item in nonzero
        if int(item[1]["LKAState"]) == 4 and int(item[1]["LKATorqueFactorRaw"]) > 0
    ]
    sustained_active = [
        item for item in factor_active if int(item[1]["LKATorqueFactorRaw"]) >= 90
    ]
    sustained_eps_states = Counter(
        item[2].eps_state_lka_raw for item in sustained_active if item[2] is not None
    )
    return {
        "source": str(path.resolve()),
        "total_0x3f2_samples": total_lka,
        "nonzero_0x3f2_samples": len(nonzero),
        "nonzero_bursts": len(bursts),
        "burst_durations_s": [
            round((burst[-1][0] - burst[0][0]) / 1_000_000.0, 6) for burst in bursts
        ],
        "torque_min_raw": min(torque_values) if torque_values else None,
        "torque_max_raw": max(torque_values) if torque_values else None,
        "lka_state_counts": dict(Counter(int(item[1]["LKAState"]) for item in nonzero)),
        "lka_unknown_byte2_counts": dict(Counter(
            int(item[1]["LKAUnknownByte2Raw"]) for item in nonzero
        )),
        "lka_torque_factor_counts": dict(Counter(
            int(item[1]["LKATorqueFactorRaw"]) for item in nonzero
        )),
        "column_angle_setpoint_counts": dict(Counter(
            float(item[1]["ColumnAngleSetpointDeg"]) for item in nonzero
        )),
        "nearest_0x495_eps_state_counts": dict(eps_states),
        "nearest_0x495_steering_hold_counts": {
            str(key).lower(): value for key, value in hold_values.items()
        },
        "factor_active_samples": len(factor_active),
        "sustained_factor_active_samples": len(sustained_active),
        "sustained_factor_active_0x495_eps_state_counts": dict(sustained_eps_states),
        "r3_active_state_3_near_nonzero_samples": eps_states[3],
        "interpretation": (
            "Une commande brute non nulle avec facteur 0 ne prouve pas une action EPS. "
            "La comparaison d'état doit privilégier LKAState=4 avec un facteur proche "
            "de 100. Les états 0x495 restent passivement observés et n'autorisent pas "
            "une commande véhicule."
        ),
    }


def load_session_samples(
    session_dir: Path,
    dbc_path: Path,
    config: SimulatorConfig,
) -> tuple[list[ReplaySample], dict[str, Any]]:
    session_dir = session_dir.resolve()
    meta_path = session_dir / "meta.json"
    can_path = session_dir / "can.jsonl"
    perception_path = session_dir / "perception.jsonl"
    sensors_path = session_dir / "sensors.jsonl"
    for required in (meta_path, can_path, perception_path):
        if not required.is_file():
            raise ValueError(f"Fichier de session manquant : {required}")

    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    anchor = meta.get("sync_anchor") or {}
    try:
        first_can_timestamp_us = int(anchor["can_first_frame_ts_us"])
        first_can_wall_epoch = float(anchor["can_first_frame_wall_epoch"])
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError(f"Ancre CAN/caméra absente ou invalide : {meta_path}") from exc

    database = cantools.database.load_file(str(dbc_path))
    messages = {message.frame_id: message for message in database.messages}
    counters = DecodeCounters()
    frames = iter(iter_can_frames(
        can_path,
        first_can_timestamp_us,
        first_can_wall_epoch,
        counters,
    ))
    next_frame = next(frames, None)
    state: dict[str, Any] = {}
    last_core_us: dict[int, int] = {}
    last_eps_status_us: int | None = None
    samples: list[ReplaySample] = []
    first_timestamp_us: int | None = None
    previous_timestamp_us: int | None = None
    filtered_curvature: float | None = None
    auxiliary = load_auxiliary_sensor_timeline(sensors_path)
    imu_index = 0
    gps_index = 0
    latest_imu: dict[str, Any] | None = None
    latest_gps: dict[str, Any] | None = None

    for perception in _load_perception(perception_path):
        timestamp_us = int(perception["timestamp_us"])
        while (
            imu_index < len(auxiliary.imu)
            and int(auxiliary.imu[imu_index]["received_timestamp_us"]) <= timestamp_us
        ):
            latest_imu = auxiliary.imu[imu_index]
            imu_index += 1
        while (
            gps_index < len(auxiliary.gps)
            and int(auxiliary.gps[gps_index]["received_timestamp_us"]) <= timestamp_us
        ):
            latest_gps = auxiliary.gps[gps_index]
            gps_index += 1
        while next_frame is not None and next_frame.wall_timestamp_us <= timestamp_us:
            decode_can_frame(next_frame, messages, state, counters)
            if next_frame.address in {0x2F5, 0x38D, 0x3CD}:
                last_core_us[next_frame.address] = next_frame.wall_timestamp_us
            if next_frame.address == 0x495:
                eps_status = decode_eps_status_495(next_frame.data)
                state.update({
                    "eps_torque_candidate_nm": eps_status.eps_torque_candidate_nm,
                    "eps_state_lka_raw": eps_status.eps_state_lka_raw,
                    "steering_wheel_held_by_driver": eps_status.steering_wheel_held_by_driver,
                    "dynamic_steering_state_raw": eps_status.dynamic_steering_state_raw,
                })
                last_eps_status_us = next_frame.wall_timestamp_us
            next_frame = next(frames, None)

        speed_kph = _finite_number(state.get("speed_kph"))
        yaw_rate_deg_s = _finite_number(state.get("yaw_rate_deg_s"))
        driver_torque_raw = _finite_number(state.get("driver_torque_raw"))
        if speed_kph is None or yaw_rate_deg_s is None or driver_torque_raw is None:
            continue
        speed_ms = speed_kph / 3.6
        estimate = estimate_path_curvature(perception.get("path"), speed_ms)
        if estimate is None:
            continue
        raw_curvature, fit_rmse = estimate

        if first_timestamp_us is None:
            first_timestamp_us = timestamp_us
        dt_s = (
            (timestamp_us - previous_timestamp_us) / 1_000_000.0
            if previous_timestamp_us is not None else 0.05
        )
        previous_timestamp_us = timestamp_us
        if dt_s <= 0.0 or dt_s > 0.75:
            filtered_curvature = None
            dt_s = 0.05

        max_curvature = config.max_lateral_accel_ms2 / max(speed_ms * speed_ms, 1.0)
        clipped_curvature = max(-max_curvature, min(max_curvature, raw_curvature))
        model_valid = fit_rmse <= config.path_fit_max_rmse_m
        alpha = dt_s / (config.path_filter_tau_s + dt_s)
        if filtered_curvature is None:
            filtered_curvature = clipped_curvature if model_valid else 0.0
        elif model_valid:
            filtered_curvature += alpha * (clipped_curvature - filtered_curvature)
        desired_lateral_accel = max(
            -config.max_lateral_accel_ms2,
            min(config.max_lateral_accel_ms2, filtered_curvature * speed_ms * speed_ms),
        )
        filtered_curvature = desired_lateral_accel / max(speed_ms * speed_ms, 1.0)
        measured_lateral_accel = math.radians(yaw_rate_deg_s) * speed_ms

        core_timestamps = [last_core_us.get(address) for address in (0x2F5, 0x38D, 0x3CD)]
        if any(value is None for value in core_timestamps):
            can_age_s = math.inf
        else:
            can_age_s = max((timestamp_us - int(value)) / 1_000_000.0 for value in core_timestamps)
        eps_status_age_s = (
            (timestamp_us - last_eps_status_us) / 1_000_000.0
            if last_eps_status_us is not None else math.inf
        )
        state["_eps_status_age_s"] = eps_status_age_s
        reasons = safety_reasons(state, config, can_age_s)
        if not model_valid:
            reasons.append("path_fit_invalid")
        # Recorded human drives naturally contain steering effort, and these two
        # legacy captures expose CurrentGear=0 while the independently decoded
        # speed proves forward motion.  Both conditions remain hard blockers for
        # the safety-applied trace, but not for the numerical counterfactual.
        counterfactual_nonblocking = {"driver_override", "drive_gear_not_confirmed"}
        counterfactual_reasons = [
            reason for reason in reasons if reason not in counterfactual_nonblocking
        ]

        imu_timestamp_us = _sensor_timestamp(latest_imu) if latest_imu else None
        matek_sensor_age_s = (
            (timestamp_us - imu_timestamp_us) / 1_000_000.0
            if imu_timestamp_us is not None else math.inf
        )
        current_imu = latest_imu if 0.0 <= matek_sensor_age_s <= 0.25 else None
        gps_timestamp_us = _sensor_timestamp(latest_gps) if latest_gps else None
        matek_gps_age_s = (
            (timestamp_us - gps_timestamp_us) / 1_000_000.0
            if gps_timestamp_us is not None else math.inf
        )
        current_gps = (
            latest_gps
            if 0.0 <= matek_gps_age_s <= 1.0 and bool(latest_gps.get("fix_valid"))
            else None
        )

        samples.append(ReplaySample(
            session_id=str(meta.get("session_id") or session_dir.name),
            timestamp_us=timestamp_us,
            elapsed_s=(timestamp_us - first_timestamp_us) / 1_000_000.0,
            dt_s=dt_s,
            speed_kph=speed_kph,
            desired_curvature_raw_1pm=raw_curvature,
            desired_curvature_1pm=filtered_curvature,
            desired_lateral_accel_ms2=desired_lateral_accel,
            measured_lateral_accel_yaw_ms2=measured_lateral_accel,
            measured_lateral_accel_sensor_ms2=_finite_number(state.get("lateral_accel_ms2")),
            steering_angle_deg=_finite_number(state.get("steering_angle_deg")),
            steering_rate_deg_s=_finite_number(state.get("steering_rate_deg_s")),
            driver_torque_raw=driver_torque_raw,
            observed_lka_torque_raw=_finite_number(state.get("lka_torque_command_raw")),
            observed_lka_state_raw=(
                int(state["lka_state"])
                if isinstance(state.get("lka_state"), (int, float)) else None
            ),
            observed_lka_torque_factor_raw=(
                int(state["lka_torque_factor_raw"])
                if isinstance(state.get("lka_torque_factor_raw"), (int, float)) else None
            ),
            observed_lka_unknown_byte2_raw=(
                int(state["lka_unknown_byte2_raw"])
                if isinstance(state.get("lka_unknown_byte2_raw"), (int, float)) else None
            ),
            observed_column_angle_setpoint_deg=_finite_number(
                state.get("column_angle_setpoint_deg")
            ),
            eps_torque_candidate_nm=_finite_number(state.get("eps_torque_candidate_nm")),
            eps_state_lka_raw=(
                int(state["eps_state_lka_raw"])
                if isinstance(state.get("eps_state_lka_raw"), (int, float)) else None
            ),
            steering_wheel_held_by_driver=(
                bool(state["steering_wheel_held_by_driver"])
                if isinstance(state.get("steering_wheel_held_by_driver"), bool) else None
            ),
            eps_status_age_s=eps_status_age_s,
            path_fit_rmse_m=fit_rmse,
            can_age_s=can_age_s,
            brake_active=bool(state.get("brake_active")),
            reverse=bool(state.get("reverse")),
            parking_brake=bool(state.get("parking_brake")),
            driver_door_open=bool(state.get("driver_door")),
            driver_seatbelt_state=(
                int(state["driver_seatbelt_state"])
                if isinstance(state.get("driver_seatbelt_state"), (int, float)) else None
            ),
            current_gear=(
                int(state["current_gear"])
                if isinstance(state.get("current_gear"), (int, float)) else None
            ),
            counterfactual_eligible=model_valid and not counterfactual_reasons,
            safety_reasons=reasons,
            matek_lateral_accel_right_ms2=(
                _finite_number(current_imu.get("acceleration_right_ms2"))
                if current_imu else None
            ),
            matek_yaw_rate_right_deg_s=(
                _finite_number(current_imu.get("yaw_rate_right_deg_s"))
                if current_imu else None
            ),
            matek_sensor_age_s=matek_sensor_age_s,
            matek_gps_speed_mps=(
                _finite_number(current_gps.get("speed_mps")) if current_gps else None
            ),
            matek_gps_latitude_deg=(
                _finite_number(current_gps.get("latitude_deg")) if current_gps else None
            ),
            matek_gps_longitude_deg=(
                _finite_number(current_gps.get("longitude_deg")) if current_gps else None
            ),
            matek_gps_age_s=matek_gps_age_s,
            road_roll_rad=_perception_road_roll_rad(perception),
        ))

    if not samples:
        raise ValueError(f"Aucun échantillon caméra/CAN exploitable dans {session_dir}")
    return samples, {
        "session_id": str(meta.get("session_id") or session_dir.name),
        "source": str(session_dir),
        "samples": len(samples),
        "duration_s": round(samples[-1].elapsed_s, 3),
        "can": asdict(counters),
        "auxiliary_sensors": auxiliary.summary,
        "road_roll": {
            "source": "localization" if any(
                sample.road_roll_rad is not None for sample in samples
            ) else "unavailable_zero_compensation",
            "available_samples": sum(
                1 for sample in samples if sample.road_roll_rad is not None
            ),
        },
    }


def fit_driver_proxy(samples: Sequence[ReplaySample], config: SimulatorConfig) -> DriverProxyFit:
    usable = [
        sample for sample in samples
        if sample.speed_kph >= config.min_speed_kph
        and abs(sample.driver_torque_raw) <= 60.0
        and abs(sample.measured_lateral_accel_yaw_ms2) <= 4.0
        and sample.can_age_s <= config.max_can_age_s
    ]
    if len(usable) < 3:
        return DriverProxyFit(len(usable), 0.10, 0.0, 0.0, math.nan, 0.0)
    xs = [sample.driver_torque_raw for sample in usable]
    ys = [sample.measured_lateral_accel_yaw_ms2 for sample in usable]
    mean_x = statistics.fmean(xs)
    mean_y = statistics.fmean(ys)
    variance_x = sum((value - mean_x) ** 2 for value in xs)
    variance_y = sum((value - mean_y) ** 2 for value in ys)
    covariance = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, ys, strict=True))
    gain = covariance / variance_x if variance_x > 1e-12 else 0.10
    intercept = mean_y - gain * mean_x
    residuals = [y - (gain * x + intercept) for x, y in zip(xs, ys, strict=True)]
    rmse = math.sqrt(statistics.fmean(value * value for value in residuals))
    correlation = covariance / math.sqrt(variance_x * variance_y) if variance_x and variance_y else 0.0
    r_squared = max(0.0, 1.0 - sum(value * value for value in residuals) / variance_y) if variance_y else 0.0
    return DriverProxyFit(
        sample_count=len(usable),
        apparent_gain_ms2_per_driver_raw=gain,
        intercept_ms2=intercept,
        correlation=correlation,
        rmse_ms2=rmse,
        r_squared=r_squared,
    )


def simulate(
    samples: Sequence[ReplaySample],
    parameters: ControllerParameters,
    config: SimulatorConfig,
) -> tuple[list[SimulationRow], dict[str, float]]:
    rows: list[SimulationRow] = []
    simulated_lateral_accel = 0.0
    unrestricted_torque = 0.0
    safety_torque = 0.0
    integral = 0.0
    active_time = 0.0
    scored_errors: list[float] = []
    scored_torques: list[float] = []
    scored_saturated: list[bool] = []
    baseline_errors: list[float] = []

    for sample in samples:
        dt_s = max(0.01, min(0.5, sample.dt_s))
        if not sample.counterfactual_eligible:
            unrestricted_torque = apply_torque_limits(0.0, unrestricted_torque, dt_s, config)
            safety_torque = apply_torque_limits(0.0, safety_torque, dt_s, config)
            simulated_lateral_accel = sample.measured_lateral_accel_yaw_ms2
            integral = 0.0
            active_time = 0.0
            error = sample.desired_lateral_accel_ms2 - simulated_lateral_accel
            rows.append(SimulationRow(sample, simulated_lateral_accel, error, unrestricted_torque, safety_torque, False))
            continue

        if active_time == 0.0:
            simulated_lateral_accel = sample.measured_lateral_accel_yaw_ms2
        active_time += dt_s
        error = sample.desired_lateral_accel_ms2 - simulated_lateral_accel
        integral_limit = config.max_torque_raw / max(parameters.ki_raw_per_ms2_s, 1e-6)
        integral = max(-integral_limit, min(integral_limit, integral + error * dt_s))
        requested = (
            parameters.feedforward_raw_per_ms2 * sample.desired_lateral_accel_ms2
            + parameters.kp_raw_per_ms2 * error
            + parameters.ki_raw_per_ms2_s * integral
        )
        saturated = abs(requested) > config.max_torque_raw
        unrestricted_torque = apply_torque_limits(requested, unrestricted_torque, dt_s, config)
        plant_alpha = 1.0 - math.exp(-dt_s / config.plant_time_constant_s)
        plant_target = parameters.plant_gain_ms2_per_raw * unrestricted_torque
        simulated_lateral_accel += plant_alpha * (plant_target - simulated_lateral_accel)
        error = sample.desired_lateral_accel_ms2 - simulated_lateral_accel

        safety_target = unrestricted_torque if not sample.safety_reasons else 0.0
        safety_torque = apply_torque_limits(safety_target, safety_torque, dt_s, config)
        rows.append(SimulationRow(
            sample,
            simulated_lateral_accel,
            error,
            unrestricted_torque,
            safety_torque,
            saturated,
        ))
        if active_time >= 0.5:
            scored_errors.append(error)
            scored_torques.append(unrestricted_torque)
            scored_saturated.append(saturated)
            baseline_errors.append(
                sample.desired_lateral_accel_ms2 - sample.measured_lateral_accel_yaw_ms2
            )

    if not scored_errors:
        metrics = {
            "scored_samples": 0,
            "rmse_ms2": math.inf,
            "p95_abs_error_ms2": math.inf,
            "mean_abs_error_ms2": math.inf,
            "baseline_measured_rmse_ms2": math.inf,
            "rms_torque_raw": 0.0,
            "saturation_fraction": 0.0,
            "objective": math.inf,
        }
        return rows, metrics
    absolute_errors = sorted(abs(value) for value in scored_errors)
    p95 = absolute_errors[min(len(absolute_errors) - 1, int(0.95 * len(absolute_errors)))]
    rmse = math.sqrt(statistics.fmean(value * value for value in scored_errors))
    rms_torque = math.sqrt(statistics.fmean(value * value for value in scored_torques))
    saturation_fraction = statistics.fmean(1.0 if value else 0.0 for value in scored_saturated)
    baseline_rmse = math.sqrt(statistics.fmean(value * value for value in baseline_errors))
    objective = rmse + 0.03 * p95 + 0.015 * rms_torque + 0.25 * saturation_fraction
    return rows, {
        "scored_samples": len(scored_errors),
        "rmse_ms2": rmse,
        "p95_abs_error_ms2": p95,
        "mean_abs_error_ms2": statistics.fmean(absolute_errors),
        "baseline_measured_rmse_ms2": baseline_rmse,
        "rms_torque_raw": rms_torque,
        "saturation_fraction": saturation_fraction,
        "objective": objective,
    }


def _interpolate(value: float, breakpoints: Sequence[float], values: Sequence[float]) -> float:
    if len(breakpoints) != len(values) or not breakpoints:
        raise ValueError("Les points d'interpolation doivent avoir la même taille")
    if value <= breakpoints[0]:
        return float(values[0])
    if value >= breakpoints[-1]:
        return float(values[-1])
    for index in range(1, len(breakpoints)):
        if value <= breakpoints[index]:
            lower_x = float(breakpoints[index - 1])
            upper_x = float(breakpoints[index])
            fraction = (value - lower_x) / (upper_x - lower_x)
            return float(values[index - 1]) * (1.0 - fraction) + float(values[index]) * fraction
    return float(values[-1])


def openpilot_torque_kp(speed_ms: float, parameters: OpenpilotTorqueParameters) -> float:
    values = (*OPENPILOT_TORQUE_KP_VALUES[:-1], parameters.kp_high_speed)
    return parameters.kp_schedule_scale * _interpolate(
        speed_ms, OPENPILOT_TORQUE_KP_SPEEDS_MS, values,
    )


def lateral_accel_from_steering_angle(
    steering_angle_deg: float,
    speed_ms: float,
    *,
    steering_zero_deg: float = T9_STEERING_ZERO_DEG,
    steering_ratio: float = T9_STEERING_RATIO,
    wheelbase_m: float = T9_WHEELBASE_M,
) -> float:
    """T9 bicycle-model equivalent of openpilot's angle measurement path."""
    road_wheel_angle_deg = -(steering_angle_deg - steering_zero_deg) / steering_ratio
    curvature = math.tan(math.radians(road_wheel_angle_deg)) / wheelbase_m
    return curvature * speed_ms * speed_ms


def _history_value(history: Sequence[tuple[float, float]], target_s: float) -> float:
    if not history:
        return 0.0
    if target_s <= history[0][0]:
        return history[0][1]
    for index in range(1, len(history)):
        upper_t, upper_value = history[index]
        if target_s <= upper_t:
            lower_t, lower_value = history[index - 1]
            if upper_t <= lower_t:
                return upper_value
            fraction = (target_s - lower_t) / (upper_t - lower_t)
            return lower_value * (1.0 - fraction) + upper_value * fraction
    return history[-1][1]


def _history_slope(
    history: Sequence[tuple[float, float]],
    target_s: float,
    timestamps: Sequence[float] | None = None,
) -> float:
    if len(history) < 2:
        return 0.0
    if timestamps is not None:
        upper_index = min(len(history) - 1, bisect_left(timestamps, target_s, lo=1))
    else:
        upper_index = len(history) - 1
        for index in range(1, len(history)):
            if target_s <= history[index][0]:
                upper_index = index
                break
    lower_index = max(0, upper_index - 1)
    upper_index = min(len(history) - 1, upper_index + 1)
    lower_t, lower_value = history[lower_index]
    upper_t, upper_value = history[upper_index]
    return (upper_value - lower_value) / (upper_t - lower_t) if upper_t > lower_t else 0.0


def _friction_compensation_ms2(
    friction_input_ms2: float,
    lateral_accel_deadzone_ms2: float,
    lat_accel_factor_ms2: float,
    parameters: OpenpilotTorqueParameters,
) -> float:
    if -lateral_accel_deadzone_ms2 < friction_input_ms2 < lateral_accel_deadzone_ms2:
        friction_input_ms2 = 0.0
    threshold = max(parameters.friction_threshold_ms2, 1e-6)
    normalized = max(-1.0, min(1.0, friction_input_ms2 / threshold))
    return normalized * parameters.friction * lat_accel_factor_ms2


def _metrics_from_scored_values(
    scored_errors: Sequence[float],
    scored_torques: Sequence[float],
    scored_saturated: Sequence[bool],
    baseline_errors: Sequence[float],
) -> dict[str, float]:
    if not scored_errors:
        return {
            "scored_samples": 0,
            "rmse_ms2": math.inf,
            "p95_abs_error_ms2": math.inf,
            "mean_abs_error_ms2": math.inf,
            "baseline_measured_rmse_ms2": math.inf,
            "rms_torque_raw": 0.0,
            "saturation_fraction": 0.0,
            "objective": math.inf,
        }
    absolute_errors = sorted(abs(value) for value in scored_errors)
    p95 = absolute_errors[min(len(absolute_errors) - 1, int(0.95 * len(absolute_errors)))]
    rmse = math.sqrt(statistics.fmean(value * value for value in scored_errors))
    rms_torque = math.sqrt(statistics.fmean(value * value for value in scored_torques))
    saturation_fraction = statistics.fmean(1.0 if value else 0.0 for value in scored_saturated)
    baseline_rmse = math.sqrt(statistics.fmean(value * value for value in baseline_errors))
    objective = rmse + 0.03 * p95 + 0.015 * rms_torque + 0.25 * saturation_fraction
    return {
        "scored_samples": len(scored_errors),
        "rmse_ms2": rmse,
        "p95_abs_error_ms2": p95,
        "mean_abs_error_ms2": statistics.fmean(absolute_errors),
        "baseline_measured_rmse_ms2": baseline_rmse,
        "rms_torque_raw": rms_torque,
        "saturation_fraction": saturation_fraction,
        "objective": objective,
    }


def simulate_openpilot_torque(
    samples: Sequence[ReplaySample],
    parameters: OpenpilotTorqueParameters,
    config: SimulatorConfig,
) -> tuple[list[SimulationRow], dict[str, float]]:
    """Run the current openpilot torque-loop structure on the offline plant.

    The counterfactual plant has no separately identified steering-angle state,
    so its lateral-acceleration state is used as the vehicle-model-equivalent
    feedback.  Recorded steering angle is deliberately not fed back because it
    belongs to the human-driven trajectory, not to the simulated torque command.
    """
    rows: list[SimulationRow] = []
    desired_history: deque[tuple[float, float]] = deque()
    desired_plan = [
        (sample.elapsed_s, sample.desired_lateral_accel_ms2) for sample in samples
    ]
    desired_plan_times = [point[0] for point in desired_plan]
    simulated_lateral_accel = 0.0
    unrestricted_torque = 0.0
    safety_torque = 0.0
    integral_ms2 = 0.0
    filtered_jerk_ms3 = 0.0
    active_time = 0.0
    limited_previous = False
    scored_errors: list[float] = []
    scored_torques: list[float] = []
    scored_saturated: list[bool] = []
    baseline_errors: list[float] = []
    lat_accel_factor_ms2 = parameters.plant_gain_ms2_per_raw * config.max_torque_raw
    jerk_rc_s = 1.0 / (2.0 * math.pi * parameters.jerk_filter_cutoff_hz)

    for sample in samples:
        dt_s = max(0.01, min(0.5, sample.dt_s))
        if sample.dt_s > 0.25:
            desired_history.clear()
            filtered_jerk_ms3 = 0.0
        desired_history.append((sample.elapsed_s, sample.desired_lateral_accel_ms2))
        history_floor_s = sample.elapsed_s - parameters.request_buffer_s - 0.5
        while len(desired_history) > 2 and desired_history[1][0] < history_floor_s:
            desired_history.popleft()

        setpoint_ms2 = _history_value(
            desired_history,
            sample.elapsed_s - parameters.lateral_delay_s,
        )
        if not sample.counterfactual_eligible:
            unrestricted_torque = apply_torque_limits(0.0, unrestricted_torque, dt_s, config)
            safety_torque = apply_torque_limits(0.0, safety_torque, dt_s, config)
            simulated_lateral_accel = sample.measured_lateral_accel_yaw_ms2
            integral_ms2 = 0.0
            active_time = 0.0
            limited_previous = False
            error = sample.desired_lateral_accel_ms2 - simulated_lateral_accel
            rows.append(SimulationRow(
                sample,
                simulated_lateral_accel,
                error,
                unrestricted_torque,
                safety_torque,
                False,
                controller_setpoint_ms2=setpoint_ms2,
                controller_measurement_ms2=simulated_lateral_accel,
                controller_error_ms2=setpoint_ms2 - simulated_lateral_accel,
                integral_ms2=integral_ms2,
                integrator_frozen=True,
            ))
            continue

        if active_time == 0.0:
            simulated_lateral_accel = sample.measured_lateral_accel_yaw_ms2
        active_time += dt_s
        measurement_ms2 = simulated_lateral_accel
        controller_error_ms2 = setpoint_ms2 - measurement_ms2
        speed_ms = sample.speed_kph / 3.6
        jerk_lookahead_s = parameters.jerk_lookahead_s
        if parameters.jerk_lookahead_max_s is not None:
            jerk_lookahead_s = _interpolate(
                speed_ms,
                (9.0, 30.0),
                (parameters.jerk_lookahead_s, parameters.jerk_lookahead_max_s),
            )
        jerk_history: Sequence[tuple[float, float]] = (
            desired_plan if parameters.future_jerk_lookahead else desired_history
        )
        jerk_target_s = (
            sample.elapsed_s + jerk_lookahead_s
            if parameters.future_jerk_lookahead
            else sample.elapsed_s - parameters.lateral_delay_s + jerk_lookahead_s
        )
        raw_jerk_ms3 = _history_slope(
            jerk_history,
            jerk_target_s,
            desired_plan_times if parameters.future_jerk_lookahead else None,
        )
        jerk_alpha = dt_s / (jerk_rc_s + dt_s)
        filtered_jerk_ms3 += jerk_alpha * (raw_jerk_ms3 - filtered_jerk_ms3)

        deadzone_curvature = math.tan(math.radians(
            parameters.steering_angle_deadzone_deg / T9_STEERING_RATIO
        )) / T9_WHEELBASE_M
        lateral_accel_deadzone_ms2 = abs(deadzone_curvature) * speed_ms * speed_ms
        friction_ms2 = _friction_compensation_ms2(
            parameters.friction_error_scale * controller_error_ms2
            + parameters.jerk_gain * filtered_jerk_ms3,
            lateral_accel_deadzone_ms2,
            lat_accel_factor_ms2,
            parameters,
        )
        roll_compensation_ms2 = (sample.road_roll_rad or 0.0) * GRAVITY_MS2
        feedforward_ms2 = (
            parameters.feedforward_scale * (
                sample.desired_lateral_accel_ms2
                - roll_compensation_ms2
                - parameters.lat_accel_offset_ms2
            )
            + friction_ms2
        )
        proportional_ms2 = openpilot_torque_kp(speed_ms, parameters) * controller_error_ms2
        freeze_integrator = (
            limited_previous
            or "driver_override" in sample.safety_reasons
            or speed_ms < 5.0
        )
        if not freeze_integrator:
            candidate_integral = (
                integral_ms2
                + parameters.ki * parameters.ki_scale * dt_s * controller_error_ms2
            )
            candidate_control = feedforward_ms2 + proportional_ms2 + candidate_integral
            if -lat_accel_factor_ms2 <= candidate_control <= lat_accel_factor_ms2:
                integral_ms2 = candidate_integral

        unrestricted_lat_accel = feedforward_ms2 + proportional_ms2 + integral_ms2
        saturated = abs(unrestricted_lat_accel) > lat_accel_factor_ms2
        output_lat_accel = max(
            -lat_accel_factor_ms2,
            min(lat_accel_factor_ms2, unrestricted_lat_accel),
        )
        requested_torque = output_lat_accel / parameters.plant_gain_ms2_per_raw
        unrestricted_torque = apply_torque_limits(
            requested_torque, unrestricted_torque, dt_s, config,
        )
        limited_previous = abs(unrestricted_torque - requested_torque) > 1e-9

        plant_alpha = 1.0 - math.exp(-dt_s / config.plant_time_constant_s)
        plant_target = parameters.plant_gain_ms2_per_raw * unrestricted_torque
        simulated_lateral_accel += plant_alpha * (plant_target - simulated_lateral_accel)
        tracking_error_ms2 = sample.desired_lateral_accel_ms2 - simulated_lateral_accel

        safety_target = unrestricted_torque if not sample.safety_reasons else 0.0
        safety_torque = apply_torque_limits(safety_target, safety_torque, dt_s, config)
        rows.append(SimulationRow(
            sample,
            simulated_lateral_accel,
            tracking_error_ms2,
            unrestricted_torque,
            safety_torque,
            saturated,
            controller_setpoint_ms2=setpoint_ms2,
            controller_measurement_ms2=measurement_ms2,
            controller_error_ms2=controller_error_ms2,
            feedforward_ms2=feedforward_ms2,
            proportional_ms2=proportional_ms2,
            integral_ms2=integral_ms2,
            friction_compensation_ms2=friction_ms2,
            roll_compensation_ms2=roll_compensation_ms2,
            desired_lateral_jerk_ms3=filtered_jerk_ms3,
            integrator_frozen=freeze_integrator,
        ))
        if active_time >= 0.5:
            scored_errors.append(tracking_error_ms2)
            scored_torques.append(unrestricted_torque)
            scored_saturated.append(saturated)
            baseline_errors.append(
                sample.desired_lateral_accel_ms2 - sample.measured_lateral_accel_yaw_ms2
            )

    return rows, _metrics_from_scored_values(
        scored_errors,
        scored_torques,
        scored_saturated,
        baseline_errors,
    )


def _percentile(values: Sequence[float], quantile: float) -> float:
    if not values:
        return math.nan
    ordered = sorted(values)
    position = max(0.0, min(1.0, quantile)) * (len(ordered) - 1)
    lower = int(math.floor(position))
    upper = int(math.ceil(position))
    if lower == upper:
        return ordered[lower]
    fraction = position - lower
    return ordered[lower] * (1.0 - fraction) + ordered[upper] * fraction


def summarize_command_dynamics(rows: Sequence[SimulationRow]) -> dict[str, float | int]:
    """Measure command activity without claiming that it is physical EPS motion.

    The trace is reset across safety-ineligible samples, session changes and
    timing gaps.  A small low-pass residual and slope reversals flag windows to
    review; they are deliberately called *candidates*, because a real road can
    legitimately contain the same high-frequency changes.
    """
    rates: list[float] = []
    high_frequency: list[float] = []
    eligible_duration_s = 0.0
    total_variation_raw = 0.0
    slope_reversals = 0
    error_crossings = 0
    direction_mismatches = 0
    direction_samples = 0
    previous_torque: float | None = None
    previous_rate_sign = 0
    previous_error_sign = 0
    previous_session: str | None = None
    low_pass_torque: float | None = None

    for row in rows:
        sample = row.sample
        dt_s = max(0.01, min(0.5, sample.dt_s))
        continuous = (
            sample.counterfactual_eligible
            and previous_torque is not None
            and previous_session == sample.session_id
            and sample.dt_s <= 0.25
        )
        if not sample.counterfactual_eligible:
            previous_torque = None
            previous_rate_sign = 0
            previous_error_sign = 0
            previous_session = sample.session_id
            low_pass_torque = None
            continue

        eligible_duration_s += dt_s
        torque = row.unrestricted_torque_raw
        if not continuous:
            low_pass_torque = torque
            previous_rate_sign = 0
            previous_error_sign = 0
        else:
            delta = torque - previous_torque
            rate = delta / dt_s
            rates.append(abs(rate))
            total_variation_raw += abs(delta)
            # Ignore tiny derivative sign changes caused by float noise.
            rate_sign = 1 if rate >= 1.0 else -1 if rate <= -1.0 else 0
            if rate_sign and previous_rate_sign and rate_sign != previous_rate_sign:
                slope_reversals += 1
            if rate_sign:
                previous_rate_sign = rate_sign

            assert low_pass_torque is not None
            alpha = dt_s / (0.50 + dt_s)
            low_pass_torque += alpha * (torque - low_pass_torque)
            high_frequency.append(torque - low_pass_torque)

        error_sign = (
            1 if row.lateral_accel_error_ms2 >= 0.05
            else -1 if row.lateral_accel_error_ms2 <= -0.05
            else 0
        )
        if error_sign and previous_error_sign and error_sign != previous_error_sign:
            error_crossings += 1
        if error_sign:
            previous_error_sign = error_sign

        desired = sample.desired_lateral_accel_ms2
        if abs(desired) >= 0.35 and abs(torque) >= 0.5:
            direction_samples += 1
            if desired * torque < 0.0:
                direction_mismatches += 1

        previous_torque = torque
        previous_session = sample.session_id

    minutes = eligible_duration_s / 60.0
    rms_rate = math.sqrt(statistics.fmean(value * value for value in rates)) if rates else 0.0
    hf_rms = (
        math.sqrt(statistics.fmean(value * value for value in high_frequency))
        if high_frequency else 0.0
    )
    return {
        "eligible_duration_s": eligible_duration_s,
        "torque_total_variation_raw_per_s": (
            total_variation_raw / eligible_duration_s if eligible_duration_s else 0.0
        ),
        "torque_rate_rms_raw_s": rms_rate,
        "torque_rate_p95_raw_s": _percentile(rates, 0.95) if rates else 0.0,
        "command_high_frequency_rms_raw": hf_rms,
        "torque_slope_reversals": slope_reversals,
        "torque_slope_reversals_per_min": slope_reversals / minutes if minutes else 0.0,
        "tracking_error_crossings_per_min": error_crossings / minutes if minutes else 0.0,
        "opposite_direction_samples": direction_mismatches,
        "opposite_direction_fraction": (
            direction_mismatches / direction_samples if direction_samples else 0.0
        ),
    }


def aggregate_simulation_metrics(metrics: Sequence[dict[str, float]]) -> dict[str, float]:
    finite = [item for item in metrics if math.isfinite(item["objective"])]
    if not finite:
        return {
            "scored_samples": 0,
            "rmse_ms2": math.inf,
            "p95_abs_error_ms2": math.inf,
            "mean_abs_error_ms2": math.inf,
            "baseline_measured_rmse_ms2": math.inf,
            "rms_torque_raw": 0.0,
            "saturation_fraction": 0.0,
            "objective": math.inf,
        }
    total_samples = sum(int(item["scored_samples"]) for item in finite)
    weights = [int(item["scored_samples"]) / total_samples for item in finite]
    aggregate = {
        "scored_samples": float(total_samples),
        "rmse_ms2": math.sqrt(sum(
            weight * item["rmse_ms2"] ** 2
            for weight, item in zip(weights, finite, strict=True)
        )),
        "p95_abs_error_ms2": sum(
            weight * item["p95_abs_error_ms2"]
            for weight, item in zip(weights, finite, strict=True)
        ),
        "mean_abs_error_ms2": sum(
            weight * item["mean_abs_error_ms2"]
            for weight, item in zip(weights, finite, strict=True)
        ),
        "baseline_measured_rmse_ms2": math.sqrt(sum(
            weight * item["baseline_measured_rmse_ms2"] ** 2
            for weight, item in zip(weights, finite, strict=True)
        )),
        "rms_torque_raw": math.sqrt(sum(
            weight * item["rms_torque_raw"] ** 2
            for weight, item in zip(weights, finite, strict=True)
        )),
        "saturation_fraction": sum(
            weight * item["saturation_fraction"]
            for weight, item in zip(weights, finite, strict=True)
        ),
    }
    aggregate["objective"] = (
        aggregate["rmse_ms2"]
        + 0.03 * aggregate["p95_abs_error_ms2"]
        + 0.015 * aggregate["rms_torque_raw"]
        + 0.25 * aggregate["saturation_fraction"]
    )
    return aggregate


def compare_controller_profiles(
    sessions: Sequence[Sequence[ReplaySample]],
    selected: ControllerParameters,
    config: SimulatorConfig,
) -> tuple[dict[str, Any], dict[str, list[list[SimulationRow]]]]:
    gain = selected.plant_gain_ms2_per_raw
    definitions = [
        ("ff_only", "Feed-forward seul", "legacy_raw_pid", ControllerParameters(
            gain, selected.feedforward_raw_per_ms2, 0.0, 0.0,
        )),
        ("current_smooth", "Réglage souple actuel", "legacy_raw_pid", selected),
        (
            "openpilot_torque_v1",
            "openpilot LatControlTorque v1",
            "openpilot_lataccel_torque",
            OpenpilotTorqueParameters(gain),
        ),
        (
            "openpilot_torque_t9_shadow_v1",
            "openpilot T9 shadow conservateur",
            "openpilot_lataccel_torque_t9_shadow",
            OpenpilotTorqueParameters(
                gain,
                feedforward_scale=0.55,
                kp_schedule_scale=0.015,
                ki_scale=0.0,
                friction=0.0,
            ),
        ),
        (
            "sunnypilot_torque_v0",
            "sunnypilot LatControlTorque v0",
            "sunnypilot_lataccel_torque_v0",
            OpenpilotTorqueParameters(
                gain,
                kp_high_speed=SUNNYPILOT_TORQUE_V0_KP,
                ki=SUNNYPILOT_TORQUE_V0_KI,
                jerk_gain=0.0,
            ),
        ),
        (
            "sunnypilot_torque_v0_jerk_shadow",
            "sunnypilot v0 jerk-aware (shadow)",
            "sunnypilot_lataccel_torque_v0_jerk_shadow",
            OpenpilotTorqueParameters(
                gain,
                kp_high_speed=SUNNYPILOT_TORQUE_V0_KP,
                ki=SUNNYPILOT_TORQUE_V0_KI,
                jerk_lookahead_s=1.4,
                jerk_lookahead_max_s=2.0,
                future_jerk_lookahead=True,
                jerk_gain=0.4,
                friction_error_scale=0.7,
            ),
        ),
        ("balanced", "Équilibré", "legacy_raw_pid", ControllerParameters(
            gain, 0.90 / gain, 0.35 / gain, 0.04 / gain,
        )),
        ("responsive", "Réactif", "legacy_raw_pid", ControllerParameters(
            gain, 1.10 / gain, 0.60 / gain, 0.10 / gain,
        )),
    ]
    profiles: list[dict[str, Any]] = []
    profile_rows: dict[str, list[list[SimulationRow]]] = {}
    for profile_id, label, controller_family, parameters in definitions:
        rows_by_session: list[list[SimulationRow]] = []
        session_metrics: list[dict[str, float]] = []
        for samples in sessions:
            if isinstance(parameters, OpenpilotTorqueParameters):
                rows, metrics = simulate_openpilot_torque(samples, parameters, config)
            else:
                rows, metrics = simulate(samples, parameters, config)
            rows_by_session.append(rows)
            session_metrics.append(metrics)
        aggregate = aggregate_simulation_metrics(session_metrics)
        dynamics = summarize_command_dynamics([
            row for rows in rows_by_session for row in rows
        ])
        gates = {
            "tracking_not_worse_than_measured": (
                aggregate["rmse_ms2"] <= aggregate["baseline_measured_rmse_ms2"]
            ),
            "saturation_below_5_percent": aggregate["saturation_fraction"] <= 0.05,
            "p95_torque_rate_below_12_raw_s": (
                float(dynamics["torque_rate_p95_raw_s"]) <= 12.0
            ),
            "opposite_direction_below_1_percent": (
                float(dynamics["opposite_direction_fraction"]) <= 0.01
            ),
        }
        profiles.append({
            "profile_id": profile_id,
            "label": label,
            "controller_family": controller_family,
            "parameters": {
                **asdict(parameters),
                **({
                    "lat_accel_factor_ms2": (
                        parameters.plant_gain_ms2_per_raw * config.max_torque_raw
                    ),
                    "feedforward_raw_per_ms2": (
                        parameters.feedforward_scale / parameters.plant_gain_ms2_per_raw
                    ),
                    "kp_raw_per_ms2_at_30ms": (
                        parameters.kp_high_speed
                        * parameters.kp_schedule_scale
                        / parameters.plant_gain_ms2_per_raw
                    ),
                    "ki_raw_per_ms2_s": (
                        parameters.ki
                        * parameters.ki_scale
                        / parameters.plant_gain_ms2_per_raw
                    ),
                    "road_roll_source": (
                        "localization_when_recorded_otherwise_zero"
                    ),
                    "measurement_source": (
                        "counterfactual_plant_vehicle_model_equivalent"
                    ),
                    "structure_revision": OPENPILOT_TORQUE_REVISION,
                    "sunnypilot_structure_revision": (
                        SUNNYPILOT_TORQUE_REVISION
                        if controller_family.startswith("sunnypilot_") else None
                    ),
                    "friction_prior_status": "unvalidated_t9_shadow_only",
                    "lateral_delay_status": "unvalidated_t9_shadow_prior",
                    "future_plan_status": (
                        "recorded_path_time_series_surrogate_not_model_plan"
                        if parameters.future_jerk_lookahead else "not_used"
                    ),
                } if isinstance(parameters, OpenpilotTorqueParameters) else {}),
            },
            "aggregate_metrics": aggregate,
            "session_metrics": session_metrics,
            "command_dynamics": dynamics,
            "numerical_gates": gates,
            "passes_all_numerical_gates": all(gates.values()),
            **({
                "shadow_tuning_basis": {
                    "date": "2026-08-27",
                    "method": "coarse_grid_on_all_recorded_trips",
                    "selection": "minimum_existing_objective_with_torque_rate_gate",
                    "holdout_validation": False,
                    "vehicle_calibration": False,
                },
            } if profile_id == "openpilot_torque_t9_shadow_v1" else {}),
        })
        profile_rows[profile_id] = rows_by_session

    shadow_preferred = min(
        profiles,
        key=lambda profile: float(profile["aggregate_metrics"]["objective"]),
    )
    numerically_qualified = [
        profile["profile_id"] for profile in profiles
        if profile["passes_all_numerical_gates"]
    ]
    return {
        "central_plant_gain_ms2_per_raw": gain,
        "profiles": profiles,
        "shadow_preferred_profile": shadow_preferred["profile_id"],
        "numerically_qualified_profiles": numerically_qualified,
        "vehicle_ready_profile": None,
        "openpilot_torque_v1": {
            "structure_revision": OPENPILOT_TORQUE_REVISION,
            "features": [
                "lateral_acceleration_space_pid",
                "speed_scheduled_proportional_gain",
                "delay_aligned_setpoint_buffer",
                "jerk_aware_friction",
                "road_roll_compensation_when_available",
                "anti_windup_and_integrator_freeze",
                "final_torque_conversion_and_existing_raw_safety_limits",
            ],
            "known_offline_gaps": [
                "road_roll_absent_from_current_recordings",
                "counterfactual_steering_angle_state_not_identified",
                "eps_gain_friction_and_delay_not_actively_identified",
            ],
        },
        "qualification_note": (
            "Les seuils numériques trient les rejeux, mais aucun profil ne devient "
            "prêt véhicule tant que le transfert réel 0x3F2/EPS n'est pas identifié."
        ),
    }, profile_rows


def _window_metrics(rows: Sequence[SimulationRow]) -> dict[str, Any]:
    eligible = [row for row in rows if row.sample.counterfactual_eligible]
    if not eligible:
        return {
            "samples": 0,
            "rmse_ms2": math.nan,
            "peak_abs_error_ms2": math.nan,
            "peak_abs_torque_raw": 0.0,
            "saturation_fraction": 0.0,
            "command_dynamics": summarize_command_dynamics([]),
        }
    errors = [row.lateral_accel_error_ms2 for row in eligible]
    return {
        "samples": len(eligible),
        "rmse_ms2": math.sqrt(statistics.fmean(value * value for value in errors)),
        "peak_abs_error_ms2": max(abs(value) for value in errors),
        "peak_abs_torque_raw": max(abs(row.unrestricted_torque_raw) for row in eligible),
        "saturation_fraction": statistics.fmean(
            1.0 if row.saturated else 0.0 for row in eligible
        ),
        "command_dynamics": summarize_command_dynamics(eligible),
    }


def detect_curve_events(
    rows: Sequence[SimulationRow],
    *,
    threshold_ms2: float = 0.35,
    merge_gap_s: float = 0.75,
    min_duration_s: float = 0.60,
) -> list[dict[str, Any]]:
    active_indices = [
        index for index, row in enumerate(rows)
        if row.sample.counterfactual_eligible
        and abs(row.sample.desired_lateral_accel_ms2) >= threshold_ms2
    ]
    groups: list[list[int]] = []
    for index in active_indices:
        if not groups:
            groups.append([index])
            continue
        previous = groups[-1][-1]
        same_session = rows[previous].sample.session_id == rows[index].sample.session_id
        gap_s = rows[index].sample.elapsed_s - rows[previous].sample.elapsed_s
        if not same_session or gap_s > merge_gap_s:
            groups.append([index])
        else:
            groups[-1].append(index)

    events: list[dict[str, Any]] = []
    for group in groups:
        start_index, end_index = group[0], group[-1]
        start = rows[start_index].sample
        end = rows[end_index].sample
        duration_s = end.elapsed_s - start.elapsed_s
        if duration_s < min_duration_s:
            continue
        event_rows = rows[start_index:end_index + 1]
        peak_row = max(
            event_rows,
            key=lambda row: abs(row.sample.desired_lateral_accel_ms2),
        )
        desired_peak = peak_row.sample.desired_lateral_accel_ms2
        eligible = [row for row in event_rows if row.sample.counterfactual_eligible]
        selected_metrics = _window_metrics(event_rows)
        dynamics = selected_metrics["command_dynamics"]
        events.append({
            "session_id": start.session_id,
            "start_index": start_index,
            "end_index": end_index,
            "start_s": start.elapsed_s,
            "end_s": end.elapsed_s,
            "review_start_s": max(0.0, start.elapsed_s - 3.0),
            "review_end_s": end.elapsed_s + 3.0,
            "duration_s": duration_s,
            "direction": "gauche" if desired_peak > 0.0 else "droite",
            "peak_elapsed_s": peak_row.sample.elapsed_s,
            "peak_desired_lateral_accel_ms2": abs(desired_peak),
            "mean_speed_kph": statistics.fmean(
                row.sample.speed_kph for row in eligible
            ),
            "selected_profile_metrics": selected_metrics,
            "review_score": (
                abs(desired_peak)
                + float(selected_metrics["saturation_fraction"])
                + 0.03 * float(dynamics["torque_rate_p95_raw_s"])
            ),
        })
    return events


def detect_oscillation_review_windows(
    rows: Sequence[SimulationRow],
    *,
    window_s: float = 4.0,
    step_s: float = 2.0,
    limit: int = 8,
) -> list[dict[str, Any]]:
    segments: list[list[int]] = []
    for index, row in enumerate(rows):
        if not row.sample.counterfactual_eligible:
            continue
        if not segments:
            segments.append([index])
            continue
        previous = segments[-1][-1]
        continuous = (
            rows[previous].sample.session_id == row.sample.session_id
            and row.sample.elapsed_s - rows[previous].sample.elapsed_s <= 0.25
        )
        if continuous:
            segments[-1].append(index)
        else:
            segments.append([index])

    candidates: list[dict[str, Any]] = []
    for segment in segments:
        cursor = 0
        while cursor < len(segment):
            start_index = segment[cursor]
            start_s = rows[start_index].sample.elapsed_s
            end_cursor = cursor
            while (
                end_cursor + 1 < len(segment)
                and rows[segment[end_cursor]].sample.elapsed_s - start_s < window_s
            ):
                end_cursor += 1
            end_index = segment[end_cursor]
            end_s = rows[end_index].sample.elapsed_s
            if end_s - start_s >= min(2.0, window_s * 0.75):
                window_rows = rows[start_index:end_index + 1]
                metrics = _window_metrics(window_rows)
                dynamics = metrics["command_dynamics"]
                hf_rms = float(dynamics["command_high_frequency_rms_raw"])
                p95_rate = float(dynamics["torque_rate_p95_raw_s"])
                reversals = float(dynamics["torque_slope_reversals_per_min"])
                candidates.append({
                    "session_id": rows[start_index].sample.session_id,
                    "start_index": start_index,
                    "end_index": end_index,
                    "start_s": start_s,
                    "end_s": end_s,
                    "review_start_s": max(0.0, start_s - 2.0),
                    "review_end_s": end_s + 2.0,
                    "mean_speed_kph": statistics.fmean(
                        row.sample.speed_kph for row in window_rows
                        if row.sample.counterfactual_eligible
                    ),
                    "peak_desired_lateral_accel_ms2": max(
                        abs(row.sample.desired_lateral_accel_ms2) for row in window_rows
                    ),
                    "selected_profile_metrics": metrics,
                    "review_score": p95_rate + 4.0 * hf_rms + 0.02 * reversals,
                    "interpretation": (
                        "Fenêtre de forte activité de consigne; une courbe ou une "
                        "transition de voie peut produire le même signal qu'une oscillation."
                    ),
                })
            target_s = start_s + step_s
            cursor += 1
            while cursor < len(segment) and rows[segment[cursor]].sample.elapsed_s < target_s:
                cursor += 1

    selected: list[dict[str, Any]] = []
    for candidate in sorted(candidates, key=lambda item: item["review_score"], reverse=True):
        overlaps = any(
            candidate["session_id"] == existing["session_id"]
            and candidate["start_s"] < existing["end_s"]
            and candidate["end_s"] > existing["start_s"]
            for existing in selected
        )
        if not overlaps:
            selected.append(candidate)
        if len(selected) >= limit:
            break
    return selected


def simulate_eps_rearm_effect(
    rows: Sequence[SimulationRow],
    parameters: ControllerParameters,
    config: SimulatorConfig,
    period_s: float,
    downtime_s: float,
    *,
    annotate: bool = False,
    curve_aware: bool = False,
    curve_threshold_ms2: float = 0.35,
    max_deferral_s: float = 0.0,
) -> dict[str, Any]:
    """Apply periodic torque dropouts to an already simulated shadow trace.

    Cristian's R3 branch explicitly rearms every eight seconds, but does not
    establish a deterministic downtime for the T9.  Sweeping ``downtime_s`` is
    therefore more honest than assuming one exact activation latency.
    """
    if period_s <= 0.0 or downtime_s < 0.0 or max_deferral_s < 0.0:
        raise ValueError("Les périodes de réarmement doivent être positives")
    active_elapsed_s = 0.0
    rearm_remaining_s = 0.0
    rearm_torque = 0.0
    rearm_lateral_accel = 0.0
    segment_active_s = 0.0
    events = 0
    deferral_elapsed_s = 0.0
    deferred_samples = 0
    rearm_starts_in_curve = 0
    rearm_samples = 0
    eligible_samples = 0
    curve_exposure_samples = 0
    errors: list[float] = []
    base_errors: list[float] = []

    for row in rows:
        sample = row.sample
        dt_s = max(0.01, min(0.5, sample.dt_s))
        if not sample.counterfactual_eligible:
            active_elapsed_s = 0.0
            rearm_remaining_s = 0.0
            deferral_elapsed_s = 0.0
            rearm_torque = 0.0
            rearm_lateral_accel = sample.measured_lateral_accel_yaw_ms2
            segment_active_s = 0.0
            if annotate:
                row.eps_rearm_active = False
                row.rearm_limited_torque_raw = 0.0
                row.rearm_simulated_lateral_accel_ms2 = rearm_lateral_accel
                row.rearm_lateral_accel_error_ms2 = (
                    sample.desired_lateral_accel_ms2 - rearm_lateral_accel
                )
            continue

        if segment_active_s == 0.0:
            rearm_lateral_accel = sample.measured_lateral_accel_yaw_ms2
        segment_active_s += dt_s
        eligible_samples += 1
        if rearm_remaining_s <= 0.0 and active_elapsed_s >= period_s:
            demanding_curve = abs(sample.desired_lateral_accel_ms2) >= curve_threshold_ms2
            can_defer = (
                curve_aware and demanding_curve
                and deferral_elapsed_s + dt_s <= max_deferral_s
            )
            if can_defer:
                deferral_elapsed_s += dt_s
                deferred_samples += 1
            else:
                rearm_remaining_s = downtime_s
                active_elapsed_s = 0.0
                deferral_elapsed_s = 0.0
                events += 1
                if demanding_curve:
                    rearm_starts_in_curve += 1
        rearm_active = rearm_remaining_s > 0.0
        target_torque = 0.0 if rearm_active else row.unrestricted_torque_raw
        rearm_torque = apply_torque_limits(target_torque, rearm_torque, dt_s, config)
        plant_alpha = 1.0 - math.exp(-dt_s / config.plant_time_constant_s)
        plant_target = parameters.plant_gain_ms2_per_raw * rearm_torque
        rearm_lateral_accel += plant_alpha * (plant_target - rearm_lateral_accel)
        error = sample.desired_lateral_accel_ms2 - rearm_lateral_accel
        if rearm_active:
            rearm_samples += 1
            rearm_remaining_s = max(0.0, rearm_remaining_s - dt_s)
            if abs(sample.desired_lateral_accel_ms2) >= 0.5:
                curve_exposure_samples += 1
        else:
            active_elapsed_s += dt_s
        if segment_active_s >= 0.5:
            errors.append(error)
            base_errors.append(row.lateral_accel_error_ms2)
        if annotate:
            row.eps_rearm_active = rearm_active
            row.rearm_limited_torque_raw = rearm_torque
            row.rearm_simulated_lateral_accel_ms2 = rearm_lateral_accel
            row.rearm_lateral_accel_error_ms2 = error

    rmse = math.sqrt(statistics.fmean(value * value for value in errors)) if errors else math.inf
    base_rmse = (
        math.sqrt(statistics.fmean(value * value for value in base_errors))
        if base_errors else math.inf
    )
    return {
        "period_s": period_s,
        "assumed_downtime_s": downtime_s,
        "policy": "defer_low_curvature" if curve_aware else "fixed_period",
        "curve_threshold_ms2": curve_threshold_ms2,
        "max_deferral_s": max_deferral_s,
        "rearm_events": events,
        "deferred_samples": deferred_samples,
        "rearm_starts_in_curve": rearm_starts_in_curve,
        "eligible_samples": eligible_samples,
        "scored_samples": len(errors),
        "rearm_samples": rearm_samples,
        "unavailable_fraction": rearm_samples / eligible_samples if eligible_samples else 0.0,
        "curve_exposure_samples": curve_exposure_samples,
        "rmse_ms2": rmse,
        "base_rmse_ms2": base_rmse,
        "rmse_delta_ms2": rmse - base_rmse,
    }


def optimize_controller(
    sessions: Sequence[Sequence[ReplaySample]],
    plant_gain: float,
    config: SimulatorConfig,
) -> tuple[ControllerParameters, dict[str, float], list[dict[str, float]]]:
    candidates: list[tuple[float, ControllerParameters, dict[str, float], list[dict[str, float]]]] = []
    for feedforward_scale in (0.70, 0.90, 1.10):
        for kp_scale in (0.15, 0.35, 0.60):
            for ki_scale in (0.0, 0.04, 0.10):
                parameters = ControllerParameters(
                    plant_gain_ms2_per_raw=plant_gain,
                    feedforward_raw_per_ms2=feedforward_scale / plant_gain,
                    kp_raw_per_ms2=kp_scale / plant_gain,
                    ki_raw_per_ms2_s=ki_scale / plant_gain,
                )
                per_session: list[dict[str, float]] = []
                for samples in sessions:
                    _, metrics = simulate(samples, parameters, config)
                    per_session.append(metrics)
                finite = [item for item in per_session if math.isfinite(item["objective"])]
                if not finite:
                    continue
                total_samples = sum(item["scored_samples"] for item in finite)
                weights = [item["scored_samples"] / total_samples for item in finite]
                aggregate = {
                    "scored_samples": total_samples,
                    "rmse_ms2": math.sqrt(sum(
                        weight * item["rmse_ms2"] ** 2
                        for weight, item in zip(weights, finite, strict=True)
                    )),
                    "p95_abs_error_ms2": sum(
                        weight * item["p95_abs_error_ms2"]
                        for weight, item in zip(weights, finite, strict=True)
                    ),
                    "mean_abs_error_ms2": sum(
                        weight * item["mean_abs_error_ms2"]
                        for weight, item in zip(weights, finite, strict=True)
                    ),
                    "baseline_measured_rmse_ms2": math.sqrt(sum(
                        weight * item["baseline_measured_rmse_ms2"] ** 2
                        for weight, item in zip(weights, finite, strict=True)
                    )),
                    "rms_torque_raw": math.sqrt(sum(
                        weight * item["rms_torque_raw"] ** 2
                        for weight, item in zip(weights, finite, strict=True)
                    )),
                    "saturation_fraction": sum(
                        weight * item["saturation_fraction"]
                        for weight, item in zip(weights, finite, strict=True)
                    ),
                }
                aggregate["objective"] = (
                    aggregate["rmse_ms2"]
                    + 0.03 * aggregate["p95_abs_error_ms2"]
                    + 0.015 * aggregate["rms_torque_raw"]
                    + 0.25 * aggregate["saturation_fraction"]
                )
                candidates.append((aggregate["objective"], parameters, aggregate, per_session))
    if not candidates:
        raise ValueError("Aucune plage roulante éligible pour optimiser le simulateur")
    _, parameters, aggregate, per_session = min(candidates, key=lambda candidate: candidate[0])
    return parameters, aggregate, per_session


def _round_floats(value: Any) -> Any:
    if isinstance(value, float):
        return None if not math.isfinite(value) else round(value, 6)
    if isinstance(value, dict):
        return {key: _round_floats(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_round_floats(item) for item in value]
    return value


def _write_trace(path: Path, session_rows: Sequence[Sequence[SimulationRow]]) -> int:
    count = 0
    with path.open("w", encoding="utf-8") as stream:
        for rows in session_rows:
            for row in rows:
                payload = asdict(row.sample)
                payload.update({
                    "simulated_lateral_accel_ms2": row.simulated_lateral_accel_ms2,
                    "lateral_accel_error_ms2": row.lateral_accel_error_ms2,
                    "unrestricted_torque_raw": row.unrestricted_torque_raw,
                    "safety_applied_torque_raw": row.safety_applied_torque_raw,
                    "saturated": row.saturated,
                    "eps_rearm_active": row.eps_rearm_active,
                    "rearm_limited_torque_raw": row.rearm_limited_torque_raw,
                    "rearm_simulated_lateral_accel_ms2": row.rearm_simulated_lateral_accel_ms2,
                    "rearm_lateral_accel_error_ms2": row.rearm_lateral_accel_error_ms2,
                })
                stream.write(json.dumps(_round_floats(payload), ensure_ascii=False) + "\n")
                count += 1
    return count


def _write_csv(path: Path, session_rows: Sequence[Sequence[SimulationRow]]) -> None:
    fieldnames = [
        "session_id", "elapsed_s", "speed_kph", "desired_lateral_accel_ms2",
        "measured_lateral_accel_yaw_ms2", "simulated_lateral_accel_ms2",
        "matek_lateral_accel_right_ms2", "matek_yaw_rate_right_deg_s",
        "matek_sensor_age_s", "matek_gps_speed_mps", "matek_gps_age_s",
        "driver_torque_raw", "unrestricted_torque_raw", "safety_applied_torque_raw",
        "eps_state_lka_raw", "steering_wheel_held_by_driver", "eps_rearm_active",
        "rearm_limited_torque_raw", "rearm_simulated_lateral_accel_ms2",
        "counterfactual_eligible", "safety_reasons",
    ]
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fieldnames)
        writer.writeheader()
        for rows in session_rows:
            for row in rows:
                sample = row.sample
                writer.writerow({
                    "session_id": sample.session_id,
                    "elapsed_s": round(sample.elapsed_s, 4),
                    "speed_kph": round(sample.speed_kph, 4),
                    "desired_lateral_accel_ms2": round(sample.desired_lateral_accel_ms2, 6),
                    "measured_lateral_accel_yaw_ms2": round(sample.measured_lateral_accel_yaw_ms2, 6),
                    "simulated_lateral_accel_ms2": round(row.simulated_lateral_accel_ms2, 6),
                    "matek_lateral_accel_right_ms2": sample.matek_lateral_accel_right_ms2,
                    "matek_yaw_rate_right_deg_s": sample.matek_yaw_rate_right_deg_s,
                    "matek_sensor_age_s": (
                        round(sample.matek_sensor_age_s, 6)
                        if math.isfinite(sample.matek_sensor_age_s) else None
                    ),
                    "matek_gps_speed_mps": sample.matek_gps_speed_mps,
                    "matek_gps_age_s": (
                        round(sample.matek_gps_age_s, 6)
                        if math.isfinite(sample.matek_gps_age_s) else None
                    ),
                    "driver_torque_raw": round(sample.driver_torque_raw, 3),
                    "unrestricted_torque_raw": round(row.unrestricted_torque_raw, 6),
                    "safety_applied_torque_raw": round(row.safety_applied_torque_raw, 6),
                    "eps_state_lka_raw": sample.eps_state_lka_raw,
                    "steering_wheel_held_by_driver": sample.steering_wheel_held_by_driver,
                    "eps_rearm_active": row.eps_rearm_active,
                    "rearm_limited_torque_raw": round(row.rearm_limited_torque_raw, 6),
                    "rearm_simulated_lateral_accel_ms2": round(
                        row.rearm_simulated_lateral_accel_ms2, 6
                    ),
                    "counterfactual_eligible": sample.counterfactual_eligible,
                    "safety_reasons": "|".join(sample.safety_reasons),
                })


def _write_profile_trace_csv(
    path: Path,
    profile_rows: dict[str, list[list[SimulationRow]]],
) -> None:
    profile_ids = list(profile_rows)
    if not profile_ids:
        return
    fieldnames = ["session_id", "elapsed_s", "desired_lateral_accel_ms2"]
    for profile_id in profile_ids:
        fieldnames.extend([
            f"{profile_id}_torque_raw",
            f"{profile_id}_error_ms2",
            f"{profile_id}_saturated",
            f"{profile_id}_controller_setpoint_ms2",
            f"{profile_id}_controller_error_ms2",
            f"{profile_id}_friction_ms2",
            f"{profile_id}_jerk_ms3",
            f"{profile_id}_integrator_frozen",
        ])
    reference = profile_rows[profile_ids[0]]
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fieldnames)
        writer.writeheader()
        for session_index, reference_rows in enumerate(reference):
            for row_index, reference_row in enumerate(reference_rows):
                payload: dict[str, Any] = {
                    "session_id": reference_row.sample.session_id,
                    "elapsed_s": round(reference_row.sample.elapsed_s, 4),
                    "desired_lateral_accel_ms2": round(
                        reference_row.sample.desired_lateral_accel_ms2, 6
                    ),
                }
                for profile_id in profile_ids:
                    row = profile_rows[profile_id][session_index][row_index]
                    payload[f"{profile_id}_torque_raw"] = round(
                        row.unrestricted_torque_raw, 6
                    )
                    payload[f"{profile_id}_error_ms2"] = round(
                        row.lateral_accel_error_ms2, 6
                    )
                    payload[f"{profile_id}_saturated"] = row.saturated
                    payload[f"{profile_id}_controller_setpoint_ms2"] = (
                        round(row.controller_setpoint_ms2, 6)
                        if row.controller_setpoint_ms2 is not None else None
                    )
                    payload[f"{profile_id}_controller_error_ms2"] = (
                        round(row.controller_error_ms2, 6)
                        if row.controller_error_ms2 is not None else None
                    )
                    payload[f"{profile_id}_friction_ms2"] = (
                        round(row.friction_compensation_ms2, 6)
                        if row.friction_compensation_ms2 is not None else None
                    )
                    payload[f"{profile_id}_jerk_ms3"] = (
                        round(row.desired_lateral_jerk_ms3, 6)
                        if row.desired_lateral_jerk_ms3 is not None else None
                    )
                    payload[f"{profile_id}_integrator_frozen"] = row.integrator_frozen
                writer.writerow(payload)


def _write_events_csv(path: Path, events: Sequence[dict[str, Any]]) -> None:
    fieldnames = [
        "event_id", "session_id", "start_s", "end_s", "review_start_s",
        "review_end_s", "direction", "mean_speed_kph",
        "peak_desired_lateral_accel_ms2", "selected_rmse_ms2",
        "selected_peak_abs_torque_raw", "selected_saturation_fraction",
        "selected_torque_rate_p95_raw_s", "review_score",
    ]
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fieldnames)
        writer.writeheader()
        for event in events:
            selected = event["selected_profile_metrics"]
            dynamics = selected["command_dynamics"]
            writer.writerow({
                "event_id": event["event_id"],
                "session_id": event["session_id"],
                "start_s": event["start_s"],
                "end_s": event["end_s"],
                "review_start_s": event["review_start_s"],
                "review_end_s": event["review_end_s"],
                "direction": event["direction"],
                "mean_speed_kph": event["mean_speed_kph"],
                "peak_desired_lateral_accel_ms2": (
                    event["peak_desired_lateral_accel_ms2"]
                ),
                "selected_rmse_ms2": selected["rmse_ms2"],
                "selected_peak_abs_torque_raw": selected["peak_abs_torque_raw"],
                "selected_saturation_fraction": selected["saturation_fraction"],
                "selected_torque_rate_p95_raw_s": dynamics["torque_rate_p95_raw_s"],
                "review_score": event["review_score"],
            })


def _svg_chart(rows: Sequence[SimulationRow], width: int = 1000, height: int = 260) -> str:
    if not rows:
        return ""
    step = max(1, len(rows) // 900)
    shown = list(rows[::step])
    maximum_x = max(row.sample.elapsed_s for row in shown) or 1.0
    maximum_y = max(
        0.5,
        max(abs(row.sample.desired_lateral_accel_ms2) for row in shown),
        max(abs(row.sample.measured_lateral_accel_yaw_ms2) for row in shown),
        max(abs(row.simulated_lateral_accel_ms2) for row in shown),
        max(abs(row.rearm_simulated_lateral_accel_ms2) for row in shown),
    )
    margin = 24

    def points(values: Iterable[tuple[float, float]]) -> str:
        result = []
        for x_value, y_value in values:
            x = margin + (width - 2 * margin) * x_value / maximum_x
            y = height / 2.0 - (height - 2 * margin) * y_value / (2.0 * maximum_y)
            result.append(f"{x:.1f},{y:.1f}")
        return " ".join(result)

    desired = points((row.sample.elapsed_s, row.sample.desired_lateral_accel_ms2) for row in shown)
    measured = points((row.sample.elapsed_s, row.sample.measured_lateral_accel_yaw_ms2) for row in shown)
    simulated = points((row.sample.elapsed_s, row.simulated_lateral_accel_ms2) for row in shown)
    rearmed = points((
        row.sample.elapsed_s, row.rearm_simulated_lateral_accel_ms2
    ) for row in shown)
    return (
        f'<svg viewBox="0 0 {width} {height}" role="img" '
        f'aria-label="accélération latérale"><line x1="{margin}" y1="{height/2:.1f}" '
        f'x2="{width-margin}" y2="{height/2:.1f}" class="axis"/>'
        f'<polyline points="{desired}" class="desired"/>'
        f'<polyline points="{measured}" class="measured"/>'
        f'<polyline points="{simulated}" class="simulated"/>'
        f'<polyline points="{rearmed}" class="rearmed"/></svg>'
    )


def _write_html(
    path: Path,
    report: dict[str, Any],
    session_rows: Sequence[Sequence[SimulationRow]],
) -> None:
    sensitivity_rows = "".join(
        "<tr>"
        f"<td>{item['plant_gain_ms2_per_raw']:.4f}</td>"
        f"<td>{item['parameters']['feedforward_raw_per_ms2']:.3f}</td>"
        f"<td>{item['parameters']['kp_raw_per_ms2']:.3f}</td>"
        f"<td>{item['parameters']['ki_raw_per_ms2_s']:.3f}</td>"
        f"<td>{item['aggregate_metrics']['rmse_ms2']:.3f}</td>"
        f"<td>{100*item['aggregate_metrics']['saturation_fraction']:.1f}%</td>"
        "</tr>"
        for item in report["plant_sensitivity"]
    )
    def profile_parameter(item: dict[str, Any], primary: str, fallback: str | None = None) -> float:
        value = item["parameters"].get(primary)
        if value is None and fallback is not None:
            value = item["parameters"].get(fallback)
        return float(value or 0.0)

    profile_rows = "".join(
        "<tr>"
        f"<td>{html.escape(item['label'])}</td>"
        f"<td>{html.escape(item['controller_family'])}</td>"
        f"<td>{profile_parameter(item, 'feedforward_raw_per_ms2'):.2f}</td>"
        f"<td>{profile_parameter(item, 'kp_raw_per_ms2', 'kp_raw_per_ms2_at_30ms'):.2f}</td>"
        f"<td>{profile_parameter(item, 'ki_raw_per_ms2_s'):.2f}</td>"
        f"<td>{profile_parameter(item, 'friction'):.3f}</td>"
        f"<td>{profile_parameter(item, 'lateral_delay_s'):.2f}</td>"
        f"<td>{item['aggregate_metrics']['rmse_ms2']:.3f}</td>"
        f"<td>{100*item['aggregate_metrics']['saturation_fraction']:.1f}%</td>"
        f"<td>{item['command_dynamics']['torque_rate_p95_raw_s']:.1f}</td>"
        f"<td>{item['command_dynamics']['command_high_frequency_rms_raw']:.3f}</td>"
        f"<td>{'oui' if item['passes_all_numerical_gates'] else 'non'}</td>"
        "</tr>"
        for item in report["controller_comparison"]["profiles"]
    )

    def format_time(value: float) -> str:
        minutes, seconds = divmod(float(value), 60.0)
        return f"{int(minutes):02d}:{seconds:04.1f}"

    def overlay_link(item: dict[str, Any]) -> str:
        source = Path(item["source_overlay"])
        if not source.is_file():
            return "absent"
        target = (
            f"{source.as_uri()}#t={item['review_start_s']:.2f},"
            f"{item['review_end_s']:.2f}"
        )
        return f'<a href="{html.escape(target)}">voir</a>'

    critical_events = report["curve_event_detection"]["events"][:12]
    event_rows = "".join(
        "<tr>"
        f"<td>{html.escape(item['event_id'])}</td>"
        f"<td>{html.escape(item['session_id'])}</td>"
        f"<td>{format_time(item['start_s'])}–{format_time(item['end_s'])}</td>"
        f"<td>{html.escape(item['direction'])}</td>"
        f"<td>{item['mean_speed_kph']:.1f}</td>"
        f"<td>{item['peak_desired_lateral_accel_ms2']:.3f}</td>"
        f"<td>{item['selected_profile_metrics']['peak_abs_torque_raw']:.2f}</td>"
        f"<td>{100*item['selected_profile_metrics']['saturation_fraction']:.1f}%</td>"
        f"<td>{item['selected_profile_metrics']['rmse_ms2']:.3f}</td>"
        f"<td>{overlay_link(item)}</td>"
        "</tr>"
        for item in critical_events
    )
    oscillation_rows = "".join(
        "<tr>"
        f"<td>{html.escape(item['window_id'])}</td>"
        f"<td>{html.escape(item['session_id'])}</td>"
        f"<td>{format_time(item['start_s'])}–{format_time(item['end_s'])}</td>"
        f"<td>{item['mean_speed_kph']:.1f}</td>"
        f"<td>{item['selected_profile_metrics']['command_dynamics']['torque_rate_p95_raw_s']:.1f}</td>"
        f"<td>{item['selected_profile_metrics']['command_dynamics']['command_high_frequency_rms_raw']:.3f}</td>"
        f"<td>{item['selected_profile_metrics']['command_dynamics']['torque_slope_reversals_per_min']:.1f}</td>"
        f"<td>{overlay_link(item)}</td>"
        "</tr>"
        for item in report["oscillation_review"]["windows"]
    )
    charts = "".join(
        f"<h3>{html.escape(rows[0].sample.session_id)}</h3>{_svg_chart(rows)}"
        for rows in session_rows if rows
    )
    selected = report["selected_hypothesis"]
    proxy = report["driver_torque_proxy"]
    safety = report["safety_audit"]
    blockers = ", ".join(
        f"{html.escape(reason)}: {count}"
        for reason, count in safety["blocker_counts"].items()
    ) or "aucun"

    def optional_number(value: Any, format_spec: str) -> str:
        return "n/a" if value is None else format(float(value), format_spec)

    rearm_rows = "".join(
        "<tr>"
        f"<td>{item['aggregate']['assumed_downtime_s']:.2f} s</td>"
        f"<td>{item['aggregate']['rearm_events']}</td>"
        f"<td>{100*item['aggregate']['unavailable_fraction']:.2f}%</td>"
        f"<td>{item['aggregate']['curve_exposure_samples']}</td>"
        f"<td>{optional_number(item['aggregate']['rmse_ms2'], '.3f')}</td>"
        f"<td>{optional_number(item['aggregate']['rmse_delta_ms2'], '+.3f')}</td>"
        "</tr>"
        for item in report["eps_rearm_sensitivity"]["results"]
    )
    strategy_rows = "".join(
        "<tr>"
        f"<td>{html.escape(item['aggregate']['policy'])}</td>"
        f"<td>{item['aggregate']['max_deferral_s']:.1f} s</td>"
        f"<td>{item['aggregate']['rearm_events']}</td>"
        f"<td>{item['aggregate']['rearm_starts_in_curve']}</td>"
        f"<td>{item['aggregate']['curve_exposure_samples']}</td>"
        f"<td>{optional_number(item['aggregate']['rmse_ms2'], '.3f')}</td>"
        "</tr>"
        for item in report["eps_rearm_sensitivity"]["strategy_results_at_reference_downtime"]
    )
    compatibility_rows = "".join(
        "<tr>"
        f"<td>{html.escape(item['aspect'])}</td>"
        f"<td>{html.escape(str(item['r3']))}</td>"
        f"<td>{html.escape(str(item['t9']))}</td>"
        f"<td>{html.escape(item['verdict'])}</td>"
        "</tr>"
        for item in report["cristianku_r3_reference"]["compatibility"]
    )
    factory = report.get("factory_t9_evidence")
    factory_text = (
        f"{factory['nonzero_0x3f2_samples']} commandes non nulles en "
        f"{factory['nonzero_bursts']} salves, plage {factory['torque_min_raw']}.."
        f"{factory['torque_max_raw']} raw; états EPS proches "
        f"{html.escape(str(factory['nearest_0x495_eps_state_counts']))}."
        if factory else "Capture usine non fournie."
    )
    matek = report["data_quality"]["matek_f722_se"]
    matek_lateral = matek["lateral_accel_fit_matek_right_vs_can_yaw"]
    matek_yaw = matek["yaw_rate_fit_matek_right_vs_can"]
    matek_gps = matek["gps_speed_fit_matek_vs_can"]

    def metric(value: Any, digits: int = 3) -> str:
        number = _finite_number(value)
        return f"{number:.{digits}f}" if number is not None else "indisponible"

    path.write_text(f"""<!doctype html>
<html lang="fr"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width">
<title>Simulation couple 308 T9</title><style>
body{{font:15px system-ui,sans-serif;margin:0;background:#10151d;color:#e9eef5}}main{{max-width:1120px;margin:auto;padding:28px}}
.warning{{background:#4b2b09;border:1px solid #d78b28;padding:16px;border-radius:10px}}.cards{{display:grid;grid-template-columns:repeat(auto-fit,minmax(190px,1fr));gap:12px;margin:18px 0}}
.card,table,section{{background:#18212c;border:1px solid #2b3949;border-radius:10px;padding:14px}}.value{{font-size:25px}}table{{width:100%;border-collapse:collapse}}th,td{{padding:8px;text-align:right;border-bottom:1px solid #2b3949}}th:first-child,td:first-child{{text-align:left}}
svg{{width:100%;background:#0c1118;border-radius:8px}}polyline{{fill:none;stroke-width:1.5}}.axis{{stroke:#536273}}.desired{{stroke:#50b7ff}}.measured{{stroke:#f5a742;opacity:.75}}.simulated{{stroke:#58d68d}}.rearmed{{stroke:#d783ff;opacity:.85}}code{{color:#8fd3ff}}
</style></head><body><main><h1>Simulateur latéral Peugeot 308 T9</h1>
<p class="warning"><strong>Hors ligne uniquement.</strong> Aucun port série, aucune émission CAN et aucune commande véhicule. Le gain de l'actionneur 0x3F2 n'est pas validé : les résultats sont des hypothèses numériques, pas des paramètres prêts à rouler.</p>
<div class="cards"><div class="card"><div>Hypothèse centrale</div><div class="value">{selected['plant_gain_ms2_per_raw']:.4f}</div><small>m/s² par point brut</small></div>
<div class="card"><div>Erreur simulée RMS</div><div class="value">{selected['aggregate_metrics']['rmse_ms2']:.3f}</div><small>m/s²</small></div>
<div class="card"><div>Corrélation effort/lacet</div><div class="value">{proxy['correlation']:.3f}</div><small>proxy conducteur</small></div>
<div class="card"><div>Neutralisation conducteur</div><div class="value">{100*safety['driver_override_fraction']:.1f}%</div><small>des points éligibles</small></div>
<div class="card"><div>Sortie sécurité max</div><div class="value">{safety['max_safety_applied_torque_raw']:.1f}</div><small>raw (reste virtuelle)</small></div></div>
<section><h2>Analyse de sensibilité</h2><table><thead><tr><th>Gain plante</th><th>FF</th><th>Kp</th><th>Ki</th><th>RMS</th><th>Saturation</th></tr></thead><tbody>{sensitivity_rows}</tbody></table></section>
<section><h2>Comparaison des réglages de couple</h2><p>Le profil <code>{html.escape(report['controller_comparison']['shadow_preferred_profile'])}</code> est le meilleur compromis dans ce modèle seulement. Le profil openpilot travaille en accélération latérale puis convertit en couple brut ; son Kp affiché est la valeur haute vitesse équivalente à 30 m/s. La colonne « portes numériques » n'est pas une autorisation véhicule.</p><table><thead><tr><th>Profil</th><th>Famille</th><th>FF</th><th>Kp</th><th>Ki</th><th>Frottement</th><th>Délai</th><th>RMS</th><th>Saturation</th><th>P95 vitesse couple</th><th>HF RMS</th><th>Portes numériques</th></tr></thead><tbody>{profile_rows}</tbody></table><p>{html.escape(report['controller_comparison']['qualification_note'])}</p></section>
<section><h2>Virages les plus exigeants</h2><p>Les liens ouvrent l'overlay trois secondes avant et après l'événement. Le signe positif correspond à gauche dans le décodage utilisé.</p><table><thead><tr><th>ID</th><th>Session</th><th>Temps</th><th>Direction</th><th>km/h</th><th>Pic cible</th><th>Pic couple</th><th>Saturation</th><th>RMS</th><th>Overlay</th></tr></thead><tbody>{event_rows}</tbody></table></section>
<section><h2>Fenêtres à examiner pour oscillation</h2><p>Ce classement détecte une consigne rapide ou riche en hautes fréquences. Il ne distingue pas à lui seul une oscillation du contrôleur d'un virage, d'un changement de voie ou d'une trajectoire modèle instable.</p><table><thead><tr><th>ID</th><th>Session</th><th>Temps</th><th>km/h</th><th>P95 vitesse couple</th><th>HF RMS</th><th>Inversions pente/min</th><th>Overlay</th></tr></thead><tbody>{oscillation_rows}</tbody></table></section>
<section><h2>Réarmement EPS — inspiration R3, hypothèses T9</h2><p>La période de 8 s provient de <code>psa-torque-sunny</code>. Les durées de coupure ne sont pas connues sur la T9 et sont donc balayées. La trace violette utilise {report['eps_rearm_sensitivity']['trace_reference_downtime_s']:.2f} s.</p><table><thead><tr><th>Coupure supposée</th><th>Cycles</th><th>Indisponible</th><th>Points en courbe</th><th>RMS</th><th>Δ RMS</th></tr></thead><tbody>{rearm_rows}</tbody></table><h3>Placement du réarmement à 0,7 s</h3><p>La stratégie différée attend une cible latérale inférieure à 0,35 m/s², sans dépasser son délai maximal. Cela ne prouve pas que l'EPS autorise ce délai.</p><table><thead><tr><th>Politique</th><th>Délai max</th><th>Cycles</th><th>Départs en courbe</th><th>Points coupés en courbe</th><th>RMS</th></tr></thead><tbody>{strategy_rows}</tbody></table></section>
<section><h2>Comparaison Cristian R3 / 308 T9</h2><p>{factory_text}</p><table><thead><tr><th>Aspect</th><th>Fork R3</th><th>T9 observée</th><th>Conclusion</th></tr></thead><tbody>{compatibility_rows}</tbody></table><p><strong>Les faux messages mains au volant et couple conducteur du fork ne sont pas reproduits.</strong></p></section>
<section><h2>Matek F722-SE / BN-880</h2><p>{matek['synchronized_imu_samples']} points IMU et {matek['synchronized_gps_samples']} points GPS ont été recalés sur la caméra/CAN. Orientation déduite : <code>{html.escape(matek['axis_sign_assessment'])}</code>. Qualification pour estimer les facteurs latéraux : <strong>{'oui' if matek['ready_for_lateral_factor_estimation'] else 'non'}</strong>.</p><table><thead><tr><th>Comparaison</th><th>Points</th><th>Pente</th><th>Biais</th><th>Corrélation</th><th>RMS</th></tr></thead><tbody><tr><td>Accélération latérale Matek / CAN lacet</td><td>{matek_lateral['sample_count']}</td><td>{metric(matek_lateral['slope'])}</td><td>{metric(matek_lateral['intercept'])}</td><td>{metric(matek_lateral['correlation'])}</td><td>{metric(matek_lateral['rmse'])}</td></tr><tr><td>Lacet Matek / CAN</td><td>{matek_yaw['sample_count']}</td><td>{metric(matek_yaw['slope'])}</td><td>{metric(matek_yaw['intercept'])}</td><td>{metric(matek_yaw['correlation'])}</td><td>{metric(matek_yaw['rmse'])}</td></tr><tr><td>Vitesse GPS / CAN</td><td>{matek_gps['sample_count']}</td><td>{metric(matek_gps['slope'])}</td><td>{metric(matek_gps['intercept'])}</td><td>{metric(matek_gps['correlation'])}</td><td>{metric(matek_gps['rmse'])}</td></tr></tbody></table><p>{html.escape(matek['interpretation'])}</p></section>
<section><h2>Audit sécurité</h2><p>{blockers}</p><p>Ces blocages sont conservés dans la trace <code>safety_applied_torque_raw</code>. Ils n'empêchent pas le calcul purement contrefactuel <code>unrestricted_torque_raw</code>.</p></section>
<section><h2>Rejeu synchronisé</h2><p><span style="color:#50b7ff">— cible modèle</span> · <span style="color:#f5a742">— lacet mesuré</span> · <span style="color:#58d68d">— réponse sans coupure</span> · <span style="color:#d783ff">— avec réarmement hypothétique</span></p>{charts}</section>
<section><h2>Interprétation</h2><p>Le couple conducteur donne une pente apparente de <code>{proxy['apparent_gain_ms2_per_driver_raw']:.4f}</code> m/s²/raw (R² {proxy['r_squared']:.3f}). Cette valeur sert seulement à choisir l'hypothèse centrale. Une vraie identification de l'EPS exigera plus tard un essai instrumenté et encadré.</p></section>
</main></body></html>""", encoding="utf-8")


def _parse_plant_gains(value: str | None, proxy_gain: float) -> list[float]:
    if value:
        gains = [float(item.strip()) for item in value.split(",") if item.strip()]
    else:
        center = max(0.03, min(0.20, abs(proxy_gain)))
        gains = [max(0.02, center * 0.6), center, min(0.25, center * 1.6)]
    gains = sorted({round(gain, 6) for gain in gains if math.isfinite(gain) and gain > 0.0})
    if not gains:
        raise ValueError("Au moins un gain plante strictement positif est requis")
    return gains


def _correlation(pairs: Sequence[tuple[float, float]]) -> float | None:
    if len(pairs) < 3:
        return None
    xs = [pair[0] for pair in pairs]
    ys = [pair[1] for pair in pairs]
    mean_x = statistics.fmean(xs)
    mean_y = statistics.fmean(ys)
    variance_x = sum((value - mean_x) ** 2 for value in xs)
    variance_y = sum((value - mean_y) ** 2 for value in ys)
    if variance_x <= 1e-12 or variance_y <= 1e-12:
        return None
    covariance = sum((x - mean_x) * (y - mean_y) for x, y in pairs)
    return covariance / math.sqrt(variance_x * variance_y)


def _linear_sensor_fit(pairs: Sequence[tuple[float, float]]) -> dict[str, Any]:
    """Fit auxiliary = slope * vehicle_reference + intercept."""
    result: dict[str, Any] = {
        "sample_count": len(pairs),
        "slope": None,
        "intercept": None,
        "correlation": _correlation(pairs),
        "rmse": None,
    }
    if len(pairs) < 3:
        return result
    mean_x = statistics.fmean(pair[0] for pair in pairs)
    mean_y = statistics.fmean(pair[1] for pair in pairs)
    variance_x = sum((pair[0] - mean_x) ** 2 for pair in pairs)
    if variance_x <= 1e-12:
        return result
    covariance = sum((x - mean_x) * (y - mean_y) for x, y in pairs)
    slope = covariance / variance_x
    intercept = mean_y - slope * mean_x
    residuals = [y - (slope * x + intercept) for x, y in pairs]
    result.update({
        "slope": slope,
        "intercept": intercept,
        "rmse": math.sqrt(statistics.fmean(value * value for value in residuals)),
    })
    return result


def summarize_matek_sensor_quality(samples: Sequence[ReplaySample]) -> dict[str, Any]:
    imu_samples = [
        sample for sample in samples
        if sample.matek_lateral_accel_right_ms2 is not None
        and sample.matek_yaw_rate_right_deg_s is not None
        and sample.matek_sensor_age_s <= 0.25
    ]
    gps_samples = [
        sample for sample in samples
        if sample.matek_gps_speed_mps is not None and sample.matek_gps_age_s <= 1.0
    ]
    lateral_pairs = [
        (sample.measured_lateral_accel_yaw_ms2, float(sample.matek_lateral_accel_right_ms2))
        for sample in imu_samples
        if abs(sample.measured_lateral_accel_yaw_ms2) <= 6.0
        and abs(float(sample.matek_lateral_accel_right_ms2)) <= 20.0
    ]
    yaw_pairs: list[tuple[float, float]] = []
    for sample in imu_samples:
        speed_ms = sample.speed_kph / 3.6
        if speed_ms < 2.0:
            continue
        can_yaw_rate_deg_s = math.degrees(sample.measured_lateral_accel_yaw_ms2 / speed_ms)
        if abs(can_yaw_rate_deg_s) <= 90.0:
            yaw_pairs.append((can_yaw_rate_deg_s, float(sample.matek_yaw_rate_right_deg_s)))
    gps_pairs = [
        (sample.speed_kph / 3.6, float(sample.matek_gps_speed_mps))
        for sample in gps_samples if sample.speed_kph >= 5.0
    ]
    lateral_fit = _linear_sensor_fit(lateral_pairs)
    yaw_fit = _linear_sensor_fit(yaw_pairs)
    gps_fit = _linear_sensor_fit(gps_pairs)
    finite_ages = [sample.matek_sensor_age_s for sample in imu_samples]
    age_p95_s = _percentile(finite_ages, 0.95) if finite_ages else None

    lateral_slope = _finite_number(lateral_fit.get("slope"))
    yaw_slope = _finite_number(yaw_fit.get("slope"))
    lateral_correlation = _finite_number(lateral_fit.get("correlation"))
    yaw_correlation = _finite_number(yaw_fit.get("correlation"))
    gps_correlation = _finite_number(gps_fit.get("correlation"))
    sign_consistent = (
        lateral_slope is not None
        and yaw_slope is not None
        and lateral_slope * yaw_slope > 0.0
    )
    gates = {
        "at_least_200_synchronized_imu_samples": len(imu_samples) >= 200,
        "imu_age_p95_below_100_ms": age_p95_s is not None and age_p95_s <= 0.1,
        "lateral_correlation_abs_at_least_0_70": (
            lateral_correlation is not None and abs(lateral_correlation) >= 0.70
        ),
        "yaw_correlation_abs_at_least_0_85": (
            yaw_correlation is not None and abs(yaw_correlation) >= 0.85
        ),
        "lateral_and_yaw_signs_consistent": sign_consistent,
        "at_least_20_synchronized_gps_samples": len(gps_samples) >= 20,
        "gps_speed_correlation_at_least_0_95": (
            gps_correlation is not None and gps_correlation >= 0.95
        ),
    }
    return {
        "available": bool(imu_samples or gps_samples),
        "synchronized_imu_samples": len(imu_samples),
        "synchronized_gps_samples": len(gps_samples),
        "imu_age_p95_s": age_p95_s,
        "lateral_accel_fit_matek_right_vs_can_yaw": lateral_fit,
        "yaw_rate_fit_matek_right_vs_can": yaw_fit,
        "gps_speed_fit_matek_vs_can": gps_fit,
        "axis_sign_assessment": (
            "matek_right_matches_can_positive"
            if sign_consistent and lateral_slope is not None and lateral_slope > 0.0
            else "matek_right_opposes_can_positive"
            if sign_consistent and lateral_slope is not None
            else "undetermined"
        ),
        "quality_gates": gates,
        "ready_for_lateral_factor_estimation": all(gates.values()),
        "interpretation": (
            "Les pentes et biais qualifient le montage et les mesures. Ils ne sont pas "
            "des gains de commande EPS et ne doivent pas être utilisés pour émettre du CAN."
        ),
    }


def summarize_live_eps(samples: Sequence[ReplaySample]) -> dict[str, Any]:
    valid = [sample for sample in samples if sample.eps_state_lka_raw is not None]
    transitions = 0
    previous_by_session: dict[str, int] = {}
    for sample in valid:
        previous = previous_by_session.get(sample.session_id)
        if previous is not None and previous != sample.eps_state_lka_raw:
            transitions += 1
        previous_by_session[sample.session_id] = int(sample.eps_state_lka_raw)
    torque_values = [
        sample.eps_torque_candidate_nm for sample in valid
        if sample.eps_torque_candidate_nm is not None
    ]
    factor_active = [
        sample for sample in samples
        if sample.observed_lka_state_raw == 4
        and (sample.observed_lka_torque_factor_raw or 0) > 0
    ]
    sustained_active = [
        sample for sample in factor_active
        if (sample.observed_lka_torque_factor_raw or 0) >= 90
    ]
    active_torques = [
        float(sample.observed_lka_torque_raw) for sample in factor_active
        if sample.observed_lka_torque_raw is not None
    ]
    active_factors = [
        int(sample.observed_lka_torque_factor_raw) for sample in factor_active
        if sample.observed_lka_torque_factor_raw is not None
    ]
    return {
        "decoded_samples": len(valid),
        "state_counts": dict(Counter(int(sample.eps_state_lka_raw) for sample in valid)),
        "state_transitions": transitions,
        "steering_wheel_hold_counts": {
            str(key).lower(): value for key, value in Counter(
                sample.steering_wheel_held_by_driver for sample in valid
            ).items()
        },
        "eps_torque_candidate_min_nm": min(torque_values) if torque_values else None,
        "eps_torque_candidate_max_nm": max(torque_values) if torque_values else None,
        "stale_samples": sum(
            1 for sample in samples if sample.eps_status_age_s > 0.25
        ),
        "factor_active_samples": len(factor_active),
        "factor_active_torque_min_raw": min(active_torques) if active_torques else None,
        "factor_active_torque_max_raw": max(active_torques) if active_torques else None,
        "factor_active_factor_min_raw": min(active_factors) if active_factors else None,
        "factor_active_factor_max_raw": max(active_factors) if active_factors else None,
        "factor_active_unknown_byte2_counts": dict(Counter(
            sample.observed_lka_unknown_byte2_raw for sample in factor_active
            if sample.observed_lka_unknown_byte2_raw is not None
        )),
        "factor_active_eps_state_counts": dict(Counter(
            sample.eps_state_lka_raw for sample in factor_active
            if sample.eps_state_lka_raw is not None
        )),
        "sustained_factor_active_samples": len(sustained_active),
        "sustained_factor_active_eps_state_counts": dict(Counter(
            sample.eps_state_lka_raw for sample in sustained_active
            if sample.eps_state_lka_raw is not None
        )),
        "warning": (
            "Les positions de bits 0x495 viennent du DBC R3; les valeurs sont "
            "conservées brutes sur la T9 jusqu'à validation de leur sémantique R2."
        ),
    }


def build_r3_reference_assessment(
    factory: dict[str, Any] | None,
    live_eps: dict[str, Any],
) -> dict[str, Any]:
    sustained_count = int(live_eps.get("sustained_factor_active_samples") or 0)
    sustained_states = live_eps.get("sustained_factor_active_eps_state_counts") or {}
    state_3_count = int(sustained_states.get(3, sustained_states.get("3", 0)) or 0)
    if sustained_count:
        t9_state_text = (
            f"état 3 sur {state_3_count}/{sustained_count} points "
            "LKAState=4/facteur>=90"
        )
        state_verdict = "passive_capture_consistent_not_tx_validated"
    else:
        t9_states = (
            sorted(int(key) for key in factory["nearest_0x495_eps_state_counts"])
            if factory else T9_FACTORY_EVIDENCE["eps_states_seen_near_nonzero_lka"]
        )
        t9_state_text = f"états bruts {t9_states}; aucun point facteur>=90"
        state_verdict = "insufficient_factor_active_evidence"

    active_unknown = sorted(
        int(key) for key in (live_eps.get("factor_active_unknown_byte2_counts") or {})
    )
    active_factor_min = live_eps.get("factor_active_factor_min_raw")
    active_factor_max = live_eps.get("factor_active_factor_max_raw")
    active_torque_min = live_eps.get("factor_active_torque_min_raw")
    active_torque_max = live_eps.get("factor_active_torque_max_raw")
    return {
        "source": {
            "repository": "https://github.com/cristianku/openpilot",
            "branch": "psa-torque-sunny",
            "openpilot_revision": CRISTIANKU_OPENPILOT_REVISION,
            "opendbc_revision": CRISTIANKU_OPENDBC_REVISION,
            "inspected_at": "2026-08-12",
        },
        "r3_profile": CRISTIANKU_R3_REFERENCE,
        "directly_transposable_to_t9": False,
        "useful_in_simulator": [
            "Cadence de commande 0x3F2 à 20 Hz.",
            "Modélisation d'une perte périodique d'autorité et du réarmement EPS.",
            "Lecture de l'état EPS brut dans 0x495.",
            "Limiteur dépendant de l'effort conducteur et relâchement rapide.",
        ],
        "not_imported": [
            "Aucune fabrication ni émission de 0x3F2, 0x495 ou 0x2F5.",
            "Aucune injection de faux état mains au volant.",
            "Aucune injection de faux couple conducteur.",
            "Aucune limite R3 ±150/±200 appliquée à la T9.",
            "Aucune émission fondée uniquement sur la corrélation passive EPS_STATE_LKA=3.",
        ],
        "compatibility": [
            {
                "aspect": "Architecture",
                "r3": "AEE2010 R3",
                "t9": "AEE2010 R2/EVO",
                "verdict": "incompatible_without_validation",
            },
            {
                "aspect": "Octet 2 de 0x3F2",
                "r3": "0x18",
                "t9": f"valeurs actives brutes {active_unknown}",
                "verdict": "different",
            },
            {
                "aspect": "Facteur de couple 0x3F2",
                "r3": "25..100",
                "t9": f"rampe {active_factor_min}..{active_factor_max}; 0 neutralise la commande",
                "verdict": "capture_consistent_ramp_differs",
            },
            {
                "aspect": "État EPS 0x495 près d'un couple usine",
                "r3": "3 requis comme actif",
                "t9": t9_state_text,
                "verdict": state_verdict,
            },
            {
                "aspect": "Enveloppe de couple",
                "r3": "logiciel ±150, safety ±200 raw",
                "t9": (
                    f"actif pondéré observé {active_torque_min}..{active_torque_max} raw; "
                    "simulateur conservateur ±10"
                ),
                "verdict": "r3_limits_rejected",
            },
            {
                "aspect": "Safety torque",
                "r3": "une violation laisse actuellement tx=true",
                "t9": "aucune TX; sortie shadow seulement",
                "verdict": "r3_safety_not_acceptable",
            },
        ],
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Rejoue caméra+CAN et simule un couple latéral T9, strictement hors ligne.",
    )
    parser.add_argument("sessions", type=Path, nargs="+", help="Dossiers live-* enregistrés")
    parser.add_argument("--dbc", type=Path, default=DEFAULT_DBC)
    parser.add_argument("--output", type=Path, help="Dossier de rapport (créé s'il manque)")
    parser.add_argument("--plant-gains", help="Hypothèses m/s²/raw séparées par des virgules")
    parser.add_argument(
        "--central-plant-gain",
        type=float,
        help=(
            "Gain central m/s²/raw à sélectionner parmi --plant-gains; "
            "par défaut, utilise le proxy d'effort conducteur"
        ),
    )
    parser.add_argument("--min-speed-kph", type=float, default=32.2)
    parser.add_argument("--max-torque-raw", type=float, default=10.0)
    parser.add_argument("--rearm-period-s", type=float, default=8.0)
    parser.add_argument(
        "--rearm-downtimes-s",
        default="0.1,0.3,0.7,1.0",
        help="Latences hypothétiques séparées par des virgules",
    )
    parser.add_argument(
        "--factory-evidence",
        type=Path,
        default=DEFAULT_FACTORY_EVIDENCE,
        help="Capture JSONL usine T9 contenant les commandes 0x3F2",
    )
    parser.add_argument("--no-factory-evidence", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.max_torque_raw <= 0.0 or args.min_speed_kph < 0.0 or args.rearm_period_s <= 0.0:
        raise SystemExit("Les limites vitesse/couple doivent être positives")
    if args.central_plant_gain is not None and (
        not math.isfinite(args.central_plant_gain) or args.central_plant_gain <= 0.0
    ):
        raise SystemExit("--central-plant-gain doit être strictement positif")
    try:
        rearm_downtimes = sorted({
            float(value.strip()) for value in args.rearm_downtimes_s.split(",")
            if value.strip()
        })
    except ValueError as exc:
        raise SystemExit("--rearm-downtimes-s doit contenir des nombres") from exc
    if not rearm_downtimes or any(value < 0.0 for value in rearm_downtimes):
        raise SystemExit("Les latences de réarmement doivent être positives")
    config = SimulatorConfig(
        min_speed_kph=args.min_speed_kph,
        max_torque_raw=args.max_torque_raw,
    )
    dbc_path = args.dbc.resolve()
    if not dbc_path.is_file():
        raise SystemExit(f"DBC introuvable : {dbc_path}")

    print("SIMULATEUR COUPLE T9 — HORS LIGNE / SHADOW MODE", flush=True)
    print("Aucun port série, aucune émission CAN, aucune commande véhicule.", flush=True)
    all_sessions: list[list[ReplaySample]] = []
    inputs: list[dict[str, Any]] = []
    for session in args.sessions:
        samples, summary = load_session_samples(session, dbc_path, config)
        all_sessions.append(samples)
        inputs.append(summary)
        print(f"[rejeu] {summary['session_id']}: {len(samples)} points synchronisés", flush=True)

    combined = [sample for samples in all_sessions for sample in samples]
    proxy = fit_driver_proxy(combined, config)
    plant_gains = _parse_plant_gains(args.plant_gains, proxy.apparent_gain_ms2_per_driver_raw)
    central_gain_target = (
        args.central_plant_gain
        if args.central_plant_gain is not None
        else abs(proxy.apparent_gain_ms2_per_driver_raw)
    )
    sensitivity: list[dict[str, Any]] = []
    optimized: list[tuple[ControllerParameters, dict[str, float], list[dict[str, float]]]] = []
    for gain in plant_gains:
        parameters, aggregate, per_session = optimize_controller(all_sessions, gain, config)
        optimized.append((parameters, aggregate, per_session))
        sensitivity.append({
            "plant_gain_ms2_per_raw": gain,
            "parameters": asdict(parameters),
            "aggregate_metrics": aggregate,
            "session_metrics": [
                {"session_id": inputs[index]["session_id"], **metrics}
                for index, metrics in enumerate(per_session)
            ],
        })

    center_index = min(
        range(len(plant_gains)),
        key=lambda index: abs(plant_gains[index] - central_gain_target),
    )
    selected_parameters, selected_metrics, _ = optimized[center_index]
    selected_rows: list[list[SimulationRow]] = []
    for samples in all_sessions:
        rows, _ = simulate(samples, selected_parameters, config)
        selected_rows.append(rows)

    controller_comparison, profile_rows = compare_controller_profiles(
        all_sessions, selected_parameters, config,
    )
    curve_events: list[dict[str, Any]] = []
    oscillation_windows: list[dict[str, Any]] = []
    for session_index, session_input in enumerate(inputs):
        current_rows = profile_rows["current_smooth"][session_index]
        session_events = detect_curve_events(current_rows)
        for event in session_events:
            start_index = int(event.pop("start_index"))
            end_index = int(event.pop("end_index"))
            event["profiles"] = {
                profile_id: _window_metrics(
                    rows_by_session[session_index][start_index:end_index + 1]
                )
                for profile_id, rows_by_session in profile_rows.items()
            }
            event["source_overlay"] = str(
                Path(session_input["source"]) / "overlay.mp4"
            )
            curve_events.append(event)

        session_windows = detect_oscillation_review_windows(current_rows)
        for window in session_windows:
            start_index = int(window.pop("start_index"))
            end_index = int(window.pop("end_index"))
            window["profiles"] = {
                profile_id: _window_metrics(
                    rows_by_session[session_index][start_index:end_index + 1]
                )
                for profile_id, rows_by_session in profile_rows.items()
            }
            window["source_overlay"] = str(
                Path(session_input["source"]) / "overlay.mp4"
            )
            oscillation_windows.append(window)

    for index, event in enumerate(
        sorted(curve_events, key=lambda item: (item["session_id"], item["start_s"])),
        start=1,
    ):
        event["event_id"] = f"curve-{index:03d}"
    for index, window in enumerate(
        sorted(
            oscillation_windows,
            key=lambda item: float(item["review_score"]),
            reverse=True,
        ),
        start=1,
    ):
        window["window_id"] = f"osc-review-{index:03d}"

    rearm_sensitivity: list[dict[str, Any]] = []
    for downtime_s in rearm_downtimes:
        session_metrics = [
            simulate_eps_rearm_effect(
                rows,
                selected_parameters,
                config,
                args.rearm_period_s,
                downtime_s,
            )
            for rows in selected_rows
        ]
        total_scored = sum(int(item["scored_samples"]) for item in session_metrics)
        total_eligible = sum(int(item["eligible_samples"]) for item in session_metrics)
        aggregate = {
            "period_s": args.rearm_period_s,
            "assumed_downtime_s": downtime_s,
            "rearm_events": sum(int(item["rearm_events"]) for item in session_metrics),
            "eligible_samples": total_eligible,
            "scored_samples": total_scored,
            "rearm_samples": sum(int(item["rearm_samples"]) for item in session_metrics),
            "curve_exposure_samples": sum(
                int(item["curve_exposure_samples"]) for item in session_metrics
            ),
        }
        aggregate["unavailable_fraction"] = (
            aggregate["rearm_samples"] / total_eligible if total_eligible else 0.0
        )
        if total_scored:
            scored_metrics = [
                item for item in session_metrics if int(item["scored_samples"]) > 0
            ]
            aggregate["rmse_ms2"] = math.sqrt(sum(
                int(item["scored_samples"]) / total_scored * float(item["rmse_ms2"]) ** 2
                for item in scored_metrics
            ))
            aggregate["base_rmse_ms2"] = math.sqrt(sum(
                int(item["scored_samples"]) / total_scored
                * float(item["base_rmse_ms2"]) ** 2
                for item in scored_metrics
            ))
            aggregate["rmse_delta_ms2"] = (
                aggregate["rmse_ms2"] - aggregate["base_rmse_ms2"]
            )
        rearm_sensitivity.append({
            "aggregate": aggregate,
            "sessions": [
                {"session_id": inputs[index]["session_id"], **metrics}
                for index, metrics in enumerate(session_metrics)
            ],
        })
    reference_downtime_s = min(rearm_downtimes, key=lambda value: abs(value - 0.7))
    rearm_strategy_sensitivity: list[dict[str, Any]] = []
    for max_deferral_s in (0.0, 1.0, 2.0, 4.0):
        curve_aware = max_deferral_s > 0.0
        session_metrics = [
            simulate_eps_rearm_effect(
                rows,
                selected_parameters,
                config,
                args.rearm_period_s,
                reference_downtime_s,
                curve_aware=curve_aware,
                max_deferral_s=max_deferral_s,
            )
            for rows in selected_rows
        ]
        total_scored = sum(int(item["scored_samples"]) for item in session_metrics)
        total_eligible = sum(int(item["eligible_samples"]) for item in session_metrics)
        total_rearm = sum(int(item["rearm_samples"]) for item in session_metrics)
        aggregate = {
            "policy": "defer_low_curvature" if curve_aware else "fixed_period",
            "max_deferral_s": max_deferral_s,
            "curve_threshold_ms2": 0.35,
            "rearm_events": sum(int(item["rearm_events"]) for item in session_metrics),
            "rearm_starts_in_curve": sum(
                int(item["rearm_starts_in_curve"]) for item in session_metrics
            ),
            "deferred_samples": sum(
                int(item["deferred_samples"]) for item in session_metrics
            ),
            "curve_exposure_samples": sum(
                int(item["curve_exposure_samples"]) for item in session_metrics
            ),
            "unavailable_fraction": total_rearm / total_eligible if total_eligible else 0.0,
        }
        if total_scored:
            scored_metrics = [
                item for item in session_metrics if int(item["scored_samples"]) > 0
            ]
            aggregate["rmse_ms2"] = math.sqrt(sum(
                int(item["scored_samples"]) / total_scored * float(item["rmse_ms2"]) ** 2
                for item in scored_metrics
            ))
            aggregate["base_rmse_ms2"] = math.sqrt(sum(
                int(item["scored_samples"]) / total_scored
                * float(item["base_rmse_ms2"]) ** 2
                for item in scored_metrics
            ))
            aggregate["rmse_delta_ms2"] = (
                aggregate["rmse_ms2"] - aggregate["base_rmse_ms2"]
            )
        rearm_strategy_sensitivity.append({
            "aggregate": aggregate,
            "sessions": [
                {"session_id": inputs[index]["session_id"], **metrics}
                for index, metrics in enumerate(session_metrics)
            ],
        })
    for rows in selected_rows:
        simulate_eps_rearm_effect(
            rows,
            selected_parameters,
            config,
            args.rearm_period_s,
            reference_downtime_s,
            annotate=True,
        )

    eligible = [row for rows in selected_rows for row in rows if row.sample.counterfactual_eligible]
    driver_overrides = [row for row in eligible if "driver_override" in row.sample.safety_reasons]
    observed_lka = [
        sample.observed_lka_torque_raw for sample in combined
        if sample.observed_lka_torque_raw is not None
    ]
    safety_audit = {
        "eligible_samples": len(eligible),
        "driver_override_samples": len(driver_overrides),
        "driver_override_fraction": len(driver_overrides) / len(eligible) if eligible else 0.0,
        "max_unrestricted_torque_raw": max((abs(row.unrestricted_torque_raw) for row in eligible), default=0.0),
        "max_safety_applied_torque_raw": max((abs(row.safety_applied_torque_raw) for row in eligible), default=0.0),
        "blocker_counts": {
            reason: sum(1 for sample in combined if reason in sample.safety_reasons)
            for reason in sorted({reason for sample in combined for reason in sample.safety_reasons})
        },
    }
    quality_samples = [sample for sample in combined if sample.counterfactual_eligible]
    raw_clipped = [
        sample for sample in combined
        if abs(sample.desired_curvature_raw_1pm * (sample.speed_kph / 3.6) ** 2)
        > config.max_lateral_accel_ms2
    ]
    sensor_pairs = [
        (sample.measured_lateral_accel_yaw_ms2, sample.measured_lateral_accel_sensor_ms2)
        for sample in quality_samples if sample.measured_lateral_accel_sensor_ms2 is not None
    ]
    desired_pairs = [
        (sample.desired_lateral_accel_ms2, sample.measured_lateral_accel_yaw_ms2)
        for sample in quality_samples
    ]
    matek_quality = summarize_matek_sensor_quality(combined)
    data_quality = {
        "synchronized_samples": len(combined),
        "counterfactual_eligible_samples": len(quality_samples),
        "road_roll_localization_samples": sum(
            1 for sample in combined if sample.road_roll_rad is not None
        ),
        "path_fit_rejected_samples": sum(
            1 for sample in combined if "path_fit_invalid" in sample.safety_reasons
        ),
        "raw_path_lateral_accel_clipped_samples": len(raw_clipped),
        "raw_path_lateral_accel_clipped_fraction": len(raw_clipped) / len(combined),
        "yaw_vs_lateral_sensor_correlation": _correlation(sensor_pairs),
        "desired_vs_measured_lateral_correlation": _correlation(desired_pairs),
        "matek_f722_se": matek_quality,
    }
    lka_observation = {
        "sample_count": len(observed_lka),
        "minimum_raw": min(observed_lka) if observed_lka else None,
        "maximum_raw": max(observed_lka) if observed_lka else None,
        "nonzero_samples": sum(1 for value in observed_lka if value != 0.0),
        "state_counts": dict(Counter(
            sample.observed_lka_state_raw for sample in combined
            if sample.observed_lka_state_raw is not None
        )),
        "torque_factor_counts": dict(Counter(
            sample.observed_lka_torque_factor_raw for sample in combined
            if sample.observed_lka_torque_factor_raw is not None
        )),
        "unknown_byte2_counts": dict(Counter(
            sample.observed_lka_unknown_byte2_raw for sample in combined
            if sample.observed_lka_unknown_byte2_raw is not None
        )),
    }
    factory_evidence: dict[str, Any] | None = None
    if not args.no_factory_evidence:
        factory_path = args.factory_evidence.resolve()
        if factory_path.is_file():
            factory_evidence = analyze_factory_evidence(factory_path, dbc_path)
        else:
            print(f"[usine] capture de référence absente : {factory_path}", flush=True)
    live_eps = summarize_live_eps(combined)
    r3_assessment = build_r3_reference_assessment(factory_evidence, live_eps)

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    output_dir = (args.output or DEFAULT_OUTPUT_ROOT / f"sim-{timestamp}").resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    report: dict[str, Any] = {
        "schema_version": 5,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "mode": "offline_shadow_readonly",
        "vehicle": "Peugeot 308 T9 2018 AEE2010 R2",
        "vehicle_control_supported": False,
        "dbc": str(dbc_path),
        "inputs": inputs,
        "config": asdict(config),
        "plant_gain_selection": {
            "hypotheses_ms2_per_raw": plant_gains,
            "central_target_ms2_per_raw": central_gain_target,
            "selected_ms2_per_raw": plant_gains[center_index],
            "source": (
                "explicit_central_plant_gain"
                if args.central_plant_gain is not None
                else "driver_torque_proxy"
            ),
        },
        "driver_torque_proxy": asdict(proxy),
        "data_quality": data_quality,
        "observed_0x3f2": lka_observation,
        "observed_0x495": live_eps,
        "factory_t9_evidence": factory_evidence,
        "cristianku_r3_reference": r3_assessment,
        "eps_rearm_sensitivity": {
            "source_period_s": CRISTIANKU_R3_REFERENCE["eps_rearm_period_s"],
            "trace_reference_downtime_s": reference_downtime_s,
            "downtime_is_hypothetical": True,
            "results": rearm_sensitivity,
            "strategy_results_at_reference_downtime": rearm_strategy_sensitivity,
            "strategy_warning": (
                "Différer un réarmement pourrait dépasser une échéance EPS réelle inconnue; "
                "cette optimisation reste strictement numérique."
            ),
        },
        "plant_sensitivity": sensitivity,
        "selected_hypothesis": {
            "plant_gain_ms2_per_raw": plant_gains[center_index],
            "parameters": asdict(selected_parameters),
            "aggregate_metrics": selected_metrics,
        },
        "controller_comparison": controller_comparison,
        "curve_event_detection": {
            "threshold_ms2": 0.35,
            "merge_gap_s": 0.75,
            "min_duration_s": 0.60,
            "event_count": len(curve_events),
            "events": sorted(
                curve_events,
                key=lambda item: float(item["review_score"]),
                reverse=True,
            ),
        },
        "oscillation_review": {
            "window_s": 4.0,
            "step_s": 2.0,
            "classification": "review_candidates_not_proven_oscillations",
            "windows": sorted(
                oscillation_windows,
                key=lambda item: float(item["review_score"]),
                reverse=True,
            ),
        },
        "safety_audit": safety_audit,
        "limitations": [
            "DriverTorqueRaw mesure l'effort conducteur, pas la réponse à une commande EPS.",
            "Le transfert réel de 0x3F2 vers l'accélération latérale n'est pas validé.",
            "Le modèle plante est un premier ordre simplifié, sans dynamique pneu/route complète.",
            "La période de 8 s vient du fork R3; les latences de réactivation sont balayées, pas mesurées sur la T9.",
            "L'état EPS 3 corrèle fortement avec LKAState=4/facteur>=90, sans valider une politique TX.",
            "Les gains optimisés sont valables uniquement dans ce simulateur hors ligne.",
            "Les facteurs Matek/CAN qualifient les axes, biais et échelles; ils ne mesurent pas le gain de l'actionneur EPS.",
            "Le profil openpilot utilise zéro pour le roulis lorsque la localisation n'en fournit pas; le roll de calibration caméra n'est pas substitué au roll routier.",
            "Dans le rejeu contrefactuel, la mesure du contrôleur openpilot vient de l'état de plante équivalent; l'angle enregistré appartient à la trajectoire humaine et ne peut pas fermer la boucle simulée.",
            "Aucun test routier actif ne doit être déduit automatiquement de ce rapport.",
        ],
        "artifacts": {
            "trace_jsonl": "trace.jsonl",
            "trace_csv": "trace.csv",
            "profile_trace_csv": "profile_trace.csv",
            "curve_events_csv": "curve_events.csv",
            "report_html": "report.html",
        },
    }
    report = _round_floats(report)
    (output_dir / "report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    _write_trace(output_dir / "trace.jsonl", selected_rows)
    _write_csv(output_dir / "trace.csv", selected_rows)
    _write_profile_trace_csv(output_dir / "profile_trace.csv", profile_rows)
    _write_events_csv(
        output_dir / "curve_events.csv",
        report["curve_event_detection"]["events"],
    )
    _write_html(output_dir / "report.html", report, selected_rows)

    print(
        f"[proxy] corrélation effort/lacet={proxy.correlation:.3f}, "
        f"pente apparente={proxy.apparent_gain_ms2_per_driver_raw:.4f} m/s²/raw",
        flush=True,
    )
    print(
        f"[hypothèse] gain={plant_gains[center_index]:.4f}, "
        f"RMS simulée={selected_metrics['rmse_ms2']:.3f} m/s²",
        flush=True,
    )
    print(
        f"[qualification] {len(curve_events)} virages, "
        f"{len(oscillation_windows)} fenêtres de nervosité à revoir, "
        f"profil shadow={controller_comparison['shadow_preferred_profile']}",
        flush=True,
    )
    for profile_id in ("openpilot_torque_v1", "openpilot_torque_t9_shadow_v1"):
        profile = next(
            item for item in controller_comparison["profiles"]
            if item["profile_id"] == profile_id
        )
        metrics = profile["aggregate_metrics"]
        dynamics = profile["command_dynamics"]
        print(
            f"[{profile_id}] RMS={metrics['rmse_ms2']:.3f} m/s², "
            f"saturation={100 * metrics['saturation_fraction']:.1f}%, "
            f"P95 couple={dynamics['torque_rate_p95_raw_s']:.1f} raw/s",
            flush=True,
        )
    if safety_audit["max_safety_applied_torque_raw"] == 0.0:
        print(
            "[sécurité] sortie appliquée neutralisée sur ces captures "
            "(voir blocker_counts dans report.json)",
            flush=True,
        )
    print(f"[rapport] {output_dir / 'report.html'}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
