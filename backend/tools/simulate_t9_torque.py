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
import csv
import html
import json
import math
import statistics
from collections import Counter
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Iterator, Sequence

import cantools

try:
    from tools.render_camera_can_replay import DecodeCounters, decode_can_frame, iter_can_frames
except ModuleNotFoundError:  # Direct execution from backend/tools.
    from render_camera_can_replay import DecodeCounters, decode_can_frame, iter_can_frames


BACKEND_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = BACKEND_ROOT.parent
DEFAULT_DBC = REPO_ROOT / "database/psa/dbc/peugeot_308_t9_2018.dbc"
DEFAULT_OUTPUT_ROOT = REPO_ROOT / "data/runtime/t9_torque_simulator"
DEFAULT_FACTORY_EVIDENCE = (
    REPO_ROOT / "data/sessions/learn-20260805T081220Z-a182e602.jsonl"
)

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
        "r3_active_state_3_near_nonzero_samples": eps_states[3],
        "interpretation": (
            "Les états 0x495 restent bruts. L'état R3=3 ne doit pas être requis "
            "pour la T9 sans validation active dédiée."
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

    for perception in _load_perception(perception_path):
        timestamp_us = int(perception["timestamp_us"])
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
        ))

    if not samples:
        raise ValueError(f"Aucun échantillon caméra/CAN exploitable dans {session_dir}")
    return samples, {
        "session_id": str(meta.get("session_id") or session_dir.name),
        "source": str(session_dir),
        "samples": len(samples),
        "duration_s": round(samples[-1].elapsed_s, 3),
        "can": asdict(counters),
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
    rearm_rows = "".join(
        "<tr>"
        f"<td>{item['aggregate']['assumed_downtime_s']:.2f} s</td>"
        f"<td>{item['aggregate']['rearm_events']}</td>"
        f"<td>{100*item['aggregate']['unavailable_fraction']:.2f}%</td>"
        f"<td>{item['aggregate']['curve_exposure_samples']}</td>"
        f"<td>{item['aggregate']['rmse_ms2']:.3f}</td>"
        f"<td>{item['aggregate']['rmse_delta_ms2']:+.3f}</td>"
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
        f"<td>{item['aggregate']['rmse_ms2']:.3f}</td>"
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
<section><h2>Réarmement EPS — inspiration R3, hypothèses T9</h2><p>La période de 8 s provient de <code>psa-torque-sunny</code>. Les durées de coupure ne sont pas connues sur la T9 et sont donc balayées. La trace violette utilise {report['eps_rearm_sensitivity']['trace_reference_downtime_s']:.2f} s.</p><table><thead><tr><th>Coupure supposée</th><th>Cycles</th><th>Indisponible</th><th>Points en courbe</th><th>RMS</th><th>Δ RMS</th></tr></thead><tbody>{rearm_rows}</tbody></table><h3>Placement du réarmement à 0,7 s</h3><p>La stratégie différée attend une cible latérale inférieure à 0,35 m/s², sans dépasser son délai maximal. Cela ne prouve pas que l'EPS autorise ce délai.</p><table><thead><tr><th>Politique</th><th>Délai max</th><th>Cycles</th><th>Départs en courbe</th><th>Points coupés en courbe</th><th>RMS</th></tr></thead><tbody>{strategy_rows}</tbody></table></section>
<section><h2>Comparaison Cristian R3 / 308 T9</h2><p>{factory_text}</p><table><thead><tr><th>Aspect</th><th>Fork R3</th><th>T9 observée</th><th>Conclusion</th></tr></thead><tbody>{compatibility_rows}</tbody></table><p><strong>Les faux messages mains au volant et couple conducteur du fork ne sont pas reproduits.</strong></p></section>
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
        "warning": (
            "Les positions de bits 0x495 viennent du DBC R3; les valeurs sont "
            "conservées brutes sur la T9 jusqu'à validation de leur sémantique R2."
        ),
    }


def build_r3_reference_assessment(factory: dict[str, Any] | None) -> dict[str, Any]:
    t9_states = (
        sorted(int(key) for key in factory["nearest_0x495_eps_state_counts"])
        if factory else T9_FACTORY_EVIDENCE["eps_states_seen_near_nonzero_lka"]
    )
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
            "Aucune hypothèse que EPS_STATE_LKA=3 signifie actif sur la T9.",
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
                "t9": "0x12 pendant les commandes usine non nulles",
                "verdict": "different",
            },
            {
                "aspect": "Facteur de couple 0x3F2",
                "r3": "25..100",
                "t9": "0 observé pendant les commandes usine",
                "verdict": "different",
            },
            {
                "aspect": "État EPS 0x495 près d'un couple usine",
                "r3": "3 requis comme actif",
                "t9": f"états bruts {t9_states}",
                "verdict": "state_semantics_different",
            },
            {
                "aspect": "Enveloppe de couple",
                "r3": "logiciel ±150, safety ±200 raw",
                "t9": "usine -7..60 raw; simulateur conservateur ±10",
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
        key=lambda index: abs(plant_gains[index] - abs(proxy.apparent_gain_ms2_per_driver_raw)),
    )
    selected_parameters, selected_metrics, _ = optimized[center_index]
    selected_rows: list[list[SimulationRow]] = []
    for samples in all_sessions:
        rows, _ = simulate(samples, selected_parameters, config)
        selected_rows.append(rows)

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
            aggregate["rmse_ms2"] = math.sqrt(sum(
                int(item["scored_samples"]) / total_scored * float(item["rmse_ms2"]) ** 2
                for item in session_metrics
            ))
            aggregate["base_rmse_ms2"] = math.sqrt(sum(
                int(item["scored_samples"]) / total_scored
                * float(item["base_rmse_ms2"]) ** 2
                for item in session_metrics
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
            aggregate["rmse_ms2"] = math.sqrt(sum(
                int(item["scored_samples"]) / total_scored * float(item["rmse_ms2"]) ** 2
                for item in session_metrics
            ))
            aggregate["base_rmse_ms2"] = math.sqrt(sum(
                int(item["scored_samples"]) / total_scored
                * float(item["base_rmse_ms2"]) ** 2
                for item in session_metrics
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
    data_quality = {
        "synchronized_samples": len(combined),
        "counterfactual_eligible_samples": len(quality_samples),
        "path_fit_rejected_samples": sum(
            1 for sample in combined if "path_fit_invalid" in sample.safety_reasons
        ),
        "raw_path_lateral_accel_clipped_samples": len(raw_clipped),
        "raw_path_lateral_accel_clipped_fraction": len(raw_clipped) / len(combined),
        "yaw_vs_lateral_sensor_correlation": _correlation(sensor_pairs),
        "desired_vs_measured_lateral_correlation": _correlation(desired_pairs),
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
    r3_assessment = build_r3_reference_assessment(factory_evidence)

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    output_dir = (args.output or DEFAULT_OUTPUT_ROOT / f"sim-{timestamp}").resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    report: dict[str, Any] = {
        "schema_version": 2,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "mode": "offline_shadow_readonly",
        "vehicle": "Peugeot 308 T9 2018 AEE2010 R2",
        "vehicle_control_supported": False,
        "dbc": str(dbc_path),
        "inputs": inputs,
        "config": asdict(config),
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
        "safety_audit": safety_audit,
        "limitations": [
            "DriverTorqueRaw mesure l'effort conducteur, pas la réponse à une commande EPS.",
            "Le transfert réel de 0x3F2 vers l'accélération latérale n'est pas validé.",
            "Le modèle plante est un premier ordre simplifié, sans dynamique pneu/route complète.",
            "La période de 8 s vient du fork R3; les latences de réactivation sont balayées, pas mesurées sur la T9.",
            "La sémantique des états 0x495 R2 n'est pas assimilée à celle du R3.",
            "Les gains optimisés sont valables uniquement dans ce simulateur hors ligne.",
            "Aucun test routier actif ne doit être déduit automatiquement de ce rapport.",
        ],
        "artifacts": {
            "trace_jsonl": "trace.jsonl",
            "trace_csv": "trace.csv",
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
