#!/usr/bin/env python3
"""Offline PSA T9 RVV/ACC shadow replay with an engine-brake-only actuator.

The tool consumes recorded GoPro/OpenPilot perception and passive CAN data.  It
has no serial or CAN transmission dependency and cannot command the vehicle.
The longitudinal policy is an explicit analytical surrogate of openpilot's
distance policy; it is not the acados MPC and it does not claim vehicle-ready
longitudinal calibration.
"""

from __future__ import annotations

import argparse
import csv
from collections import Counter
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import html
import json
import math
from pathlib import Path
import statistics
from typing import Any, Iterable, Iterator, Sequence

import cantools

try:
    from tools.render_camera_can_replay import (
        DecodeCounters,
        decode_can_frame,
        iter_can_frames,
    )
except ModuleNotFoundError:  # Direct execution from openpilot/tools.
    from render_camera_can_replay import DecodeCounters, decode_can_frame, iter_can_frames


OPENPILOT_LAB_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = OPENPILOT_LAB_ROOT.parent
DEFAULT_DBC = REPO_ROOT / "database/psa/dbc/peugeot_308_t9_2018.dbc"
DEFAULT_OUTPUT_ROOT = REPO_ROOT / "data/runtime/t9_rvv_shadow"

# Pinned from the local commaai/openpilot checkout used for the capture.
OPENPILOT_LONGITUDINAL_REVISION = "b973dc8ac7e5f38309ef3763d126b39b24f53a39"
OPENPILOT_T_FOLLOW_STANDARD_S = 1.45
OPENPILOT_COMFORT_BRAKE_MS2 = 2.5
OPENPILOT_STOP_DISTANCE_M = 6.0
OPENPILOT_LEAD_DANGER_FACTOR = 0.75
OPENPILOT_ACCEL_MIN_MS2 = -1.2
OPENPILOT_ACCEL_MAX_BP_MS = (0.0, 10.0, 25.0, 40.0)
OPENPILOT_ACCEL_MAX_VALUES_MS2 = (1.6, 1.2, 0.8, 0.6)


@dataclass(frozen=True)
class RvvShadowConfig:
    min_speed_kph: float = 40.0
    min_setpoint_kph: int = 40
    max_setpoint_kph: int = 130
    lead_min_probability: float = 0.50
    t_follow_s: float = OPENPILOT_T_FOLLOW_STANDARD_S
    comfort_brake_ms2: float = OPENPILOT_COMFORT_BRAKE_MS2
    stop_distance_m: float = OPENPILOT_STOP_DISTANCE_M
    danger_factor: float = OPENPILOT_LEAD_DANGER_FACTOR
    minimum_accel_ms2: float = OPENPILOT_ACCEL_MIN_MS2
    gap_response_s: float = 3.0
    speed_response_s: float = 2.0
    accel_lookahead_weight: float = 0.35
    jerk_limit_ms3: float = 0.8
    # Conservative initial prior from the weakest sustained deceleration
    # sequences observed on the 2026-08-27 road capture.
    engine_brake_decel_ms2: float = 0.30
    setpoint_step_kph: int = 1
    setpoint_step_interval_s: float = 0.50
    max_can_age_s: float = 0.25


@dataclass(frozen=True)
class LeadObservation:
    probability: float
    distance_m: float
    speed_ms: float
    relative_speed_ms: float
    acceleration_ms2: float


@dataclass(frozen=True)
class PolicyDecision:
    safe_gap_m: float | None
    danger_gap_m: float | None
    obstacle_margin_m: float | None
    requested_accel_ms2: float
    engine_brake_limited_accel_ms2: float
    service_brake_required: bool
    target_setpoint_kph: float
    action: str
    source: str


@dataclass
class ShadowRow:
    session_id: str
    timestamp_us: int
    elapsed_s: float
    dt_s: float
    speed_kph: float | None
    actual_accel_ms2: float | None
    engine_torque_nm: float | None
    stock_setpoint_kph: float | None
    applied_shadow_setpoint_kph: float | None
    target_shadow_setpoint_kph: float | None
    cruise_mode_raw: int | None
    cruise_activation_request: bool | None
    cruise_engine_state_raw: int | None
    calibration_status: str | None
    lead_probability: float | None
    lead_distance_m: float | None
    lead_speed_kph: float | None
    relative_speed_kph: float | None
    safe_gap_m: float | None
    danger_gap_m: float | None
    obstacle_margin_m: float | None
    requested_accel_ms2: float | None
    engine_brake_limited_accel_ms2: float | None
    service_brake_required: bool
    shadow_action: str
    policy_source: str
    actual_action: str
    decision_agreement: bool | None
    eligible: bool
    safety_reasons: list[str]
    can_age_s: float


def _finite(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    number = float(value)
    return number if math.isfinite(number) else None


def _interpolate(value: float, x: Sequence[float], y: Sequence[float]) -> float:
    if value <= x[0]:
        return float(y[0])
    if value >= x[-1]:
        return float(y[-1])
    for left in range(len(x) - 1):
        if x[left] <= value <= x[left + 1]:
            fraction = (value - x[left]) / (x[left + 1] - x[left])
            return float(y[left] + fraction * (y[left + 1] - y[left]))
    return float(y[-1])


def openpilot_max_accel(speed_ms: float) -> float:
    return _interpolate(
        speed_ms,
        OPENPILOT_ACCEL_MAX_BP_MS,
        OPENPILOT_ACCEL_MAX_VALUES_MS2,
    )


def stopped_equivalence_distance(speed_ms: float, comfort_brake_ms2: float) -> float:
    return max(0.0, speed_ms) ** 2 / (2.0 * comfort_brake_ms2)


def safe_obstacle_distance(speed_ms: float, config: RvvShadowConfig) -> float:
    return (
        stopped_equivalence_distance(speed_ms, config.comfort_brake_ms2)
        + config.t_follow_s * max(0.0, speed_ms)
        + config.stop_distance_m
    )


def lead_observation(record: dict[str, Any], ego_speed_ms: float) -> LeadObservation | None:
    leads = record.get("leads")
    if not isinstance(leads, list) or not leads or not isinstance(leads[0], dict):
        return None
    lead = leads[0]  # probTime=0; the other entries are 2 s/4 s horizons.
    probability = _finite(lead.get("prob"))
    distance = _finite(lead.get("distance_openpilot_m"))
    velocities = lead.get("v")
    accelerations = lead.get("a")
    pose = record.get("pose")
    model_speed_ms = (
        _finite(pose[0])
        if isinstance(pose, list) and pose
        else _finite(record.get("speed_ms"))
    )
    vision_lead_speed = (
        _finite(velocities[0])
        if isinstance(velocities, list) and velocities
        else None
    )
    acceleration = (
        _finite(accelerations[0])
        if isinstance(accelerations, list) and accelerations
        else 0.0
    )
    if None in (probability, distance, model_speed_ms, vision_lead_speed):
        return None
    relative_speed_ms = float(vision_lead_speed) - float(model_speed_ms)
    corrected_speed_ms = max(0.0, ego_speed_ms + relative_speed_ms)
    return LeadObservation(
        probability=float(probability),
        distance_m=max(0.0, float(distance)),
        speed_ms=corrected_speed_ms,
        relative_speed_ms=relative_speed_ms,
        acceleration_ms2=float(acceleration or 0.0),
    )


def longitudinal_policy(
    ego_speed_ms: float,
    stock_setpoint_kph: float,
    lead: LeadObservation | None,
    config: RvvShadowConfig,
) -> PolicyDecision:
    """Analytical openpilot-distance surrogate constrained to PSA RVV setpoints."""
    cruise_speed_ms = stock_setpoint_kph / 3.6
    maximum_accel = openpilot_max_accel(ego_speed_ms)
    cruise_accel = max(
        config.minimum_accel_ms2,
        min(maximum_accel, cruise_speed_ms - ego_speed_ms),
    )
    safe_gap: float | None = None
    danger_gap: float | None = None
    margin: float | None = None
    requested_accel = cruise_accel
    source = "cruise"

    if lead is not None and lead.probability >= config.lead_min_probability:
        safe_obstacle = safe_obstacle_distance(ego_speed_ms, config)
        lead_stopped_equivalence = stopped_equivalence_distance(
            lead.speed_ms, config.comfort_brake_ms2
        )
        safe_gap = max(config.stop_distance_m, safe_obstacle - lead_stopped_equivalence)
        danger_gap = max(
            config.stop_distance_m,
            config.danger_factor * safe_obstacle - lead_stopped_equivalence,
        )
        margin = lead.distance_m + lead_stopped_equivalence - safe_obstacle
        gap_speed_correction = max(-10.0, min(10.0, margin / config.gap_response_s))
        follow_speed_ms = max(0.0, lead.speed_ms + gap_speed_correction)
        lead_accel = (
            (follow_speed_ms - ego_speed_ms) / config.speed_response_s
            + config.accel_lookahead_weight * lead.acceleration_ms2
        )
        lead_accel = max(config.minimum_accel_ms2, min(maximum_accel, lead_accel))

        closing_speed_ms = max(0.0, ego_speed_ms - lead.speed_ms)
        if closing_speed_ms > 0.0:
            remaining = lead.distance_m - danger_gap
            collision_avoidance_accel = (
                config.minimum_accel_ms2
                if remaining <= 0.5
                else -(closing_speed_ms * closing_speed_ms) / (2.0 * remaining)
            )
            lead_accel = min(lead_accel, collision_avoidance_accel)
        if lead_accel < cruise_accel:
            requested_accel = lead_accel
            source = "lead0"

    requested_accel = max(config.minimum_accel_ms2, min(maximum_accel, requested_accel))
    service_brake_required = requested_accel < -config.engine_brake_decel_ms2
    limited_accel = max(requested_accel, -config.engine_brake_decel_ms2)
    if service_brake_required:
        action = "service_brake_required"
    elif limited_accel < -0.15:
        action = "engine_brake"
    elif limited_accel > 0.15:
        action = "accelerate"
    else:
        action = "hold"

    if limited_accel < -0.05:
        target_setpoint = min(
            stock_setpoint_kph,
            (ego_speed_ms + limited_accel * config.speed_response_s) * 3.6,
        )
    else:
        target_setpoint = stock_setpoint_kph
    target_setpoint = max(
        float(config.min_setpoint_kph),
        min(float(config.max_setpoint_kph), target_setpoint),
    )
    return PolicyDecision(
        safe_gap_m=safe_gap,
        danger_gap_m=danger_gap,
        obstacle_margin_m=margin,
        requested_accel_ms2=requested_accel,
        engine_brake_limited_accel_ms2=limited_accel,
        service_brake_required=service_brake_required,
        target_setpoint_kph=target_setpoint,
        action=action,
        source=source,
    )


def apply_accel_jerk_limit(
    requested_ms2: float,
    previous_ms2: float,
    dt_s: float,
    config: RvvShadowConfig,
) -> float:
    delta = config.jerk_limit_ms3 * max(0.0, min(0.5, dt_s))
    return max(previous_ms2 - delta, min(previous_ms2 + delta, requested_ms2))


def step_rvv_setpoint(
    current_kph: float,
    target_kph: float,
    elapsed_s: float,
    last_step_s: float,
    config: RvvShadowConfig,
) -> tuple[float, float]:
    elapsed_since_step = elapsed_s - last_step_s
    if elapsed_since_step + 1e-9 < config.setpoint_step_interval_s:
        return current_kph, last_step_s
    steps = max(1, int(elapsed_since_step / config.setpoint_step_interval_s))
    maximum_change = steps * config.setpoint_step_kph
    if current_kph < target_kph:
        current_kph = min(target_kph, current_kph + maximum_change)
    elif current_kph > target_kph:
        current_kph = max(target_kph, current_kph - maximum_change)
    return current_kph, last_step_s + steps * config.setpoint_step_interval_s


def actual_vehicle_action(
    acceleration_ms2: float | None,
    engine_torque_nm: float | None,
    brake_active: bool | None,
) -> str:
    if brake_active is True:
        return "service_brake"
    if acceleration_ms2 is None:
        return "unknown"
    if acceleration_ms2 <= -0.15 and (engine_torque_nm is None or engine_torque_nm <= 0.0):
        return "engine_brake"
    if acceleration_ms2 >= 0.15 and (engine_torque_nm is None or engine_torque_nm > 0.0):
        return "accelerate"
    return "hold"


def longitudinal_safety_reasons(
    state: dict[str, Any],
    calibration_status: str | None,
    can_age_s: float,
    config: RvvShadowConfig,
) -> list[str]:
    reasons: list[str] = []
    speed = _finite(state.get("speed_kph"))
    setpoint = _finite(state.get("cruise_setpoint_kph"))
    if calibration_status != "2":
        reasons.append("camera_not_calibrated")
    if state.get("cruise_mode") != 1:
        reasons.append("rvv_mode_not_selected")
    if state.get("cruise_activation_request") is not True or state.get("cruise_active") is not True:
        reasons.append("rvv_not_active")
    if setpoint is None or not config.min_setpoint_kph <= setpoint <= config.max_setpoint_kph:
        reasons.append("rvv_setpoint_out_of_range")
    if speed is None or speed < config.min_speed_kph:
        reasons.append("speed_below_rvv_shadow_threshold")
    if state.get("brake_active") is True:
        reasons.append("brake_active")
    if state.get("reverse") is True:
        reasons.append("reverse")
    if state.get("parking_brake") is True:
        reasons.append("parking_brake")
    if state.get("driver_door") is True:
        reasons.append("driver_door_open")
    if state.get("driver_seatbelt_state") != 2:
        reasons.append("driver_seatbelt_not_latched")
    gear = state.get("current_gear")
    if not isinstance(gear, (int, float)) or not 1 <= int(gear) <= 6:
        reasons.append("drive_gear_not_confirmed")
    if not math.isfinite(can_age_s) or can_age_s > config.max_can_age_s:
        reasons.append("can_stale")
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


def replay_session(
    session_dir: Path,
    dbc_path: Path,
    config: RvvShadowConfig,
) -> tuple[list[ShadowRow], dict[str, Any]]:
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
    rows: list[ShadowRow] = []
    first_timestamp_us: int | None = None
    previous_timestamp_us: int | None = None
    previous_accel_request = 0.0
    applied_setpoint: float | None = None
    last_setpoint_step_s = 0.0

    for perception in _load_perception(perception_path):
        timestamp_us = int(perception["timestamp_us"])
        while next_frame is not None and next_frame.wall_timestamp_us <= timestamp_us:
            decode_can_frame(next_frame, messages, state, counters)
            if next_frame.address in {0x208, 0x38D, 0x50E, 0x412, 0x572}:
                last_core_us[next_frame.address] = next_frame.wall_timestamp_us
            next_frame = next(frames, None)
        if first_timestamp_us is None:
            first_timestamp_us = timestamp_us
        elapsed_s = (timestamp_us - first_timestamp_us) / 1_000_000.0
        dt_s = (
            (timestamp_us - previous_timestamp_us) / 1_000_000.0
            if previous_timestamp_us is not None else 0.05
        )
        previous_timestamp_us = timestamp_us
        if dt_s <= 0.0 or dt_s > 0.75:
            dt_s = 0.05
            previous_accel_request = 0.0

        required_core = (0x208, 0x38D, 0x50E, 0x412, 0x572)
        ages = [
            (timestamp_us - last_core_us[address]) / 1_000_000.0
            for address in required_core if address in last_core_us
        ]
        can_age_s = max(ages) if len(ages) == len(required_core) else math.inf
        calibration = perception.get("calibration")
        calibration_status = (
            str(calibration.get("status")) if isinstance(calibration, dict) else None
        )
        reasons = longitudinal_safety_reasons(
            state, calibration_status, can_age_s, config
        )
        eligible = not reasons
        speed_kph = _finite(state.get("speed_kph"))
        speed_ms = speed_kph / 3.6 if speed_kph is not None else None
        stock_setpoint = _finite(state.get("cruise_setpoint_kph"))
        lead = lead_observation(perception, speed_ms) if speed_ms is not None else None
        decision: PolicyDecision | None = None
        if eligible and speed_ms is not None and stock_setpoint is not None:
            decision = longitudinal_policy(speed_ms, stock_setpoint, lead, config)
            limited = apply_accel_jerk_limit(
                decision.engine_brake_limited_accel_ms2,
                previous_accel_request,
                dt_s,
                config,
            )
            previous_accel_request = limited
            target = decision.target_setpoint_kph
            if limited >= -0.05:
                target = stock_setpoint
            else:
                target = max(
                    config.min_setpoint_kph,
                    min(stock_setpoint, (speed_ms + limited * config.speed_response_s) * 3.6),
                )
            # The bridge and 0x50E field both use integer km/h setpoints.  A
            # braking request rounds downward so the offline quantization is
            # conservative and bit-compatible with the firmware command.
            target = float(math.floor(target + 1e-9))
            if applied_setpoint is None:
                applied_setpoint = stock_setpoint
                last_setpoint_step_s = elapsed_s
            applied_setpoint, last_setpoint_step_s = step_rvv_setpoint(
                applied_setpoint,
                target,
                elapsed_s,
                last_setpoint_step_s,
                config,
            )
            applied_setpoint = max(
                config.min_setpoint_kph,
                min(config.max_setpoint_kph, applied_setpoint),
            )
            target_setpoint = target
        else:
            previous_accel_request = 0.0
            applied_setpoint = stock_setpoint
            target_setpoint = stock_setpoint
            last_setpoint_step_s = elapsed_s

        actual_accel = _finite(state.get("longitudinal_accel_ms2"))
        engine_torque = _finite(state.get("engine_torque_nm"))
        actual_action = actual_vehicle_action(
            actual_accel,
            engine_torque,
            state.get("brake_active"),
        )
        shadow_action = decision.action if decision is not None else "inactive"
        comparable_actual = "hold" if actual_action == "unknown" else actual_action
        agreement = (
            comparable_actual == shadow_action
            if eligible and shadow_action in {"hold", "accelerate", "engine_brake"}
            else None
        )
        usable_lead = (
            lead
            if lead is not None and lead.probability >= config.lead_min_probability
            else None
        )
        rows.append(ShadowRow(
            session_id=session_dir.name,
            timestamp_us=timestamp_us,
            elapsed_s=elapsed_s,
            dt_s=dt_s,
            speed_kph=speed_kph,
            actual_accel_ms2=actual_accel,
            engine_torque_nm=engine_torque,
            stock_setpoint_kph=stock_setpoint,
            applied_shadow_setpoint_kph=applied_setpoint,
            target_shadow_setpoint_kph=target_setpoint,
            cruise_mode_raw=(int(state["cruise_mode"]) if state.get("cruise_mode") is not None else None),
            cruise_activation_request=state.get("cruise_activation_request"),
            cruise_engine_state_raw=(
                int(state["cruise_xvv_state"])
                if state.get("cruise_xvv_state") is not None else None
            ),
            calibration_status=calibration_status,
            lead_probability=lead.probability if lead is not None else None,
            lead_distance_m=usable_lead.distance_m if usable_lead is not None else None,
            lead_speed_kph=usable_lead.speed_ms * 3.6 if usable_lead is not None else None,
            relative_speed_kph=(
                usable_lead.relative_speed_ms * 3.6 if usable_lead is not None else None
            ),
            safe_gap_m=decision.safe_gap_m if decision is not None else None,
            danger_gap_m=decision.danger_gap_m if decision is not None else None,
            obstacle_margin_m=decision.obstacle_margin_m if decision is not None else None,
            requested_accel_ms2=decision.requested_accel_ms2 if decision is not None else None,
            engine_brake_limited_accel_ms2=(
                previous_accel_request if decision is not None else None
            ),
            service_brake_required=(decision.service_brake_required if decision else False),
            shadow_action=shadow_action,
            policy_source=(decision.source if decision is not None else "inactive"),
            actual_action=actual_action,
            decision_agreement=agreement,
            eligible=eligible,
            safety_reasons=reasons,
            can_age_s=can_age_s,
        ))

    summary = {
        "session_id": session_dir.name,
        "source": str(session_dir),
        "samples": len(rows),
        "duration_s": round(rows[-1].elapsed_s, 6) if rows else 0.0,
        "can": {
            "raw_lines": counters.raw_lines,
            "can_frames": counters.can_frames,
            "known_frames": counters.known_frames,
            "decoded_frames": counters.decoded_frames,
            "decode_errors": counters.decode_errors,
        },
    }
    return rows, summary


def _percentile(values: Sequence[float], fraction: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = fraction * (len(ordered) - 1)
    low = int(math.floor(index))
    high = int(math.ceil(index))
    if low == high:
        return ordered[low]
    weight = index - low
    return ordered[low] * (1.0 - weight) + ordered[high] * weight


def _event_rows(
    rows: Sequence[ShadowRow],
    predicate: Any,
    minimum_duration_s: float,
    maximum_gap_s: float = 0.25,
) -> list[list[ShadowRow]]:
    events: list[list[ShadowRow]] = []
    current: list[ShadowRow] = []
    for row in rows:
        if predicate(row):
            if current and (
                row.session_id != current[-1].session_id
                or row.elapsed_s - current[-1].elapsed_s > maximum_gap_s
            ):
                if current[-1].elapsed_s - current[0].elapsed_s >= minimum_duration_s:
                    events.append(current)
                current = []
            current.append(row)
        else:
            if current and (
                row.session_id != current[-1].session_id
                or row.elapsed_s - current[-1].elapsed_s > maximum_gap_s
            ):
                if current[-1].elapsed_s - current[0].elapsed_s >= minimum_duration_s:
                    events.append(current)
                current = []
    if current and current[-1].elapsed_s - current[0].elapsed_s >= minimum_duration_s:
        events.append(current)
    return events


def summarize_event(event: Sequence[ShadowRow], event_id: str, kind: str) -> dict[str, Any]:
    def values(name: str) -> list[float]:
        return [
            float(value) for row in event
            if (value := getattr(row, name)) is not None and math.isfinite(float(value))
        ]
    accelerations = values("actual_accel_ms2")
    requested = values("requested_accel_ms2")
    distances = values("lead_distance_m")
    margins = values("obstacle_margin_m")
    torques = values("engine_torque_nm")
    return {
        "event_id": event_id,
        "kind": kind,
        "session_id": event[0].session_id,
        "start_s": round(event[0].elapsed_s, 6),
        "end_s": round(event[-1].elapsed_s, 6),
        "duration_s": round(event[-1].elapsed_s - event[0].elapsed_s, 6),
        "speed_start_kph": event[0].speed_kph,
        "speed_end_kph": event[-1].speed_kph,
        "stock_setpoint_start_kph": event[0].stock_setpoint_kph,
        "shadow_setpoint_min_kph": min(values("applied_shadow_setpoint_kph"), default=None),
        "minimum_lead_distance_m": min(distances, default=None),
        "minimum_obstacle_margin_m": min(margins, default=None),
        "minimum_requested_accel_ms2": min(requested, default=None),
        "mean_actual_accel_ms2": statistics.fmean(accelerations) if accelerations else None,
        "mean_engine_torque_nm": statistics.fmean(torques) if torques else None,
        "service_brake_required": any(row.service_brake_required for row in event),
    }


def build_report(
    rows_by_session: Sequence[Sequence[ShadowRow]],
    inputs: Sequence[dict[str, Any]],
    config: RvvShadowConfig,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    rows = [row for session_rows in rows_by_session for row in session_rows]
    eligible = [row for row in rows if row.eligible]
    lead_rows = [row for row in eligible if row.lead_distance_m is not None]
    lead_control_rows = [row for row in lead_rows if row.policy_source == "lead0"]
    agreements = [row.decision_agreement for row in eligible if row.decision_agreement is not None]
    blockers = Counter(reason for row in rows for reason in row.safety_reasons)
    actual_events_raw = _event_rows(
        rows,
        lambda row: (
            row.cruise_mode_raw == 1
            and row.cruise_activation_request is True
            and row.actual_action == "engine_brake"
        ),
        1.0,
        maximum_gap_s=0.60,
    )
    shadow_events_raw = _event_rows(
        rows,
        lambda row: (
            row.eligible
            and row.policy_source == "lead0"
            and row.shadow_action in {"engine_brake", "service_brake_required"}
        ),
        0.75,
    )
    actual_events = [
        summarize_event(event, f"actual-{index:02d}", "observed_engine_brake")
        for index, event in enumerate(actual_events_raw, 1)
    ]
    shadow_events = [
        summarize_event(event, f"shadow-{index:02d}", "adaptive_shadow")
        for index, event in enumerate(shadow_events_raw, 1)
    ]
    actual_event_means = [
        -float(event["mean_actual_accel_ms2"])
        for event in actual_events
        if _finite(event.get("mean_actual_accel_ms2")) is not None
        and float(event["mean_actual_accel_ms2"]) < 0.0
    ]
    deltas = [
        float(row.stock_setpoint_kph - row.applied_shadow_setpoint_kph)
        for row in eligible
        if row.stock_setpoint_kph is not None and row.applied_shadow_setpoint_kph is not None
    ]
    stock_setpoint_steps: list[float] = []
    for session_rows in rows_by_session:
        previous_stock: float | None = None
        for row in session_rows:
            if not row.eligible or row.stock_setpoint_kph is None:
                previous_stock = None
                continue
            if previous_stock is not None and row.stock_setpoint_kph != previous_stock:
                stock_setpoint_steps.append(row.stock_setpoint_kph - previous_stock)
            previous_stock = row.stock_setpoint_kph
    lead_agreements = [
        row.decision_agreement
        for row in lead_control_rows
        if row.decision_agreement is not None
    ]
    engine_brake_sensitivity = {
        f"{decel:.2f}": {
            "all_eligible_samples": sum(
                row.requested_accel_ms2 is not None
                and row.requested_accel_ms2 < -decel
                for row in eligible
            ),
            "lead_eligible_samples": sum(
                row.requested_accel_ms2 is not None
                and row.requested_accel_ms2 < -decel
                for row in lead_control_rows
            ),
        }
        for decel in (0.25, 0.30, 0.40, 0.50, 0.65)
    }
    report = {
        "schema_version": 1,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "mode": "offline_shadow_readonly",
        "vehicle_control_supported": False,
        "vehicle_ready_profile": None,
        "inputs": list(inputs),
        "config": asdict(config),
        "openpilot_reference": {
            "revision": OPENPILOT_LONGITUDINAL_REVISION,
            "structure": "analytical_distance_policy_surrogate_not_acados_mpc",
            "t_follow_standard_s": OPENPILOT_T_FOLLOW_STANDARD_S,
            "comfort_brake_ms2": OPENPILOT_COMFORT_BRAKE_MS2,
            "stop_distance_m": OPENPILOT_STOP_DISTANCE_M,
            "lead_danger_factor": OPENPILOT_LEAD_DANGER_FACTOR,
            "minimum_accel_ms2": OPENPILOT_ACCEL_MIN_MS2,
        },
        "data_quality": {
            "samples": len(rows),
            "eligible_samples": len(eligible),
            "lead_confident_eligible_samples": len(lead_rows),
            "lead_confident_fraction": len(lead_rows) / len(eligible) if eligible else 0.0,
            "lead_binding_samples": len(lead_control_rows),
            "blocker_counts": dict(blockers),
        },
        "shadow_policy": {
            "action_counts": dict(Counter(row.shadow_action for row in eligible)),
            "lead_action_counts": dict(Counter(row.shadow_action for row in lead_control_rows)),
            "actual_action_counts": dict(Counter(row.actual_action for row in eligible)),
            "exact_decision_agreement_fraction": (
                sum(value is True for value in agreements) / len(agreements)
                if agreements else None
            ),
            "lead_exact_decision_agreement_fraction": (
                sum(value is True for value in lead_agreements) / len(lead_agreements)
                if lead_agreements else None
            ),
            "lower_setpoint_samples": sum(delta > 0.05 for delta in deltas),
            "setpoint_reduction_kph_p50": _percentile(deltas, 0.50),
            "setpoint_reduction_kph_p95": _percentile(deltas, 0.95),
            "service_brake_required_samples": sum(
                row.service_brake_required for row in eligible
            ),
            "lead_service_brake_required_samples": sum(
                row.service_brake_required for row in lead_control_rows
            ),
            "engine_brake_sensitivity": engine_brake_sensitivity,
            "minimum_obstacle_margin_m": min(
                (float(row.obstacle_margin_m) for row in lead_rows if row.obstacle_margin_m is not None),
                default=None,
            ),
            "bridge_setpoint_bounds_respected": all(
                row.applied_shadow_setpoint_kph is None
                or config.min_setpoint_kph <= row.applied_shadow_setpoint_kph <= config.max_setpoint_kph
                for row in eligible
            ),
            "bridge_integer_setpoints_respected": all(
                row.applied_shadow_setpoint_kph is None
                or float(row.applied_shadow_setpoint_kph).is_integer()
                for row in eligible
            ),
            "bridge_rate_policy": (
                f"{config.setpoint_step_kph} km/h par "
                f"{config.setpoint_step_interval_s:.2f} s"
            ),
            "observed_stock_setpoint_transitions": len(stock_setpoint_steps),
            "maximum_observed_stock_setpoint_step_kph": max(
                (abs(value) for value in stock_setpoint_steps), default=0.0
            ),
        },
        "observed_engine_brake_prior": {
            "events": len(actual_events),
            "event_mean_decel_ms2_median": (
                statistics.median(actual_event_means) if actual_event_means else None
            ),
            "event_mean_decel_ms2_p05": _percentile(actual_event_means, 0.05),
            "event_mean_decel_ms2_p95": _percentile(actual_event_means, 0.95),
            "configured_conservative_decel_ms2": config.engine_brake_decel_ms2,
            "interpretation": (
                "Prior observé en boucle fermée avec route et boîte inconnues; "
                "ce n'est pas une garantie de décélération disponible."
            ),
        },
        "events": {
            "observed_engine_brake": actual_events,
            "adaptive_shadow": shadow_events,
        },
        "limitations": [
            "Le surrogate reprend les distances et bornes openpilot, pas le solveur acados exact.",
            "La caméra GoPro n'est ni un radar homologué ni une mesure redondante de distance.",
            "Le RVV PSA ne commande pas les freins et ne peut garantir une distance de sécurité.",
            "Une demande sous la capacité supposée du frein moteur est classée service_brake_required et reste non exécutable.",
            "Le couple moteur, la pente, le rapport engagé et la traînée ne sont pas causalement identifiés.",
            "La comparaison d'actions décrit le trajet humain/PSA enregistré; elle ne mesure pas la réponse à la consigne shadow.",
            "Les variations de 0x50E observées ne distinguent pas encore avec certitude une action conducteur d'une rampe interne PSA; cette priorité doit être définie avant toute intégration hôte.",
            "Aucun résultat ne doit activer automatiquement un profil véhicule ou une émission CAN.",
        ],
    }
    return report, actual_events + shadow_events


def write_trace(path: Path, rows: Iterable[ShadowRow]) -> None:
    fieldnames = list(ShadowRow.__dataclass_fields__)
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            payload = asdict(row)
            payload["safety_reasons"] = "|".join(row.safety_reasons)
            writer.writerow(payload)


def write_events(path: Path, events: Sequence[dict[str, Any]]) -> None:
    fieldnames = list(events[0]) if events else ["event_id", "kind", "session_id"]
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(events)


def _svg_chart(
    rows: Sequence[ShadowRow],
    series: Sequence[tuple[str, str, str]],
    title: str,
    unit: str,
) -> str:
    width, height = 1080, 245
    left, right, top, bottom = 58, 18, 32, 34
    usable_width = width - left - right
    usable_height = height - top - bottom
    finite_values: list[float] = []
    for row in rows:
        for attribute, _, _ in series:
            value = getattr(row, attribute)
            if value is not None and math.isfinite(float(value)):
                finite_values.append(float(value))
    if not rows or not finite_values:
        return f"<h3>{html.escape(title)}</h3><p>Données indisponibles.</p>"
    y_min, y_max = min(finite_values), max(finite_values)
    padding = max(0.5, (y_max - y_min) * 0.08)
    y_min -= padding
    y_max += padding
    x_min, x_max = rows[0].elapsed_s, max(rows[-1].elapsed_s, rows[0].elapsed_s + 1.0)
    stride = max(1, math.ceil(len(rows) / 1800))

    def point(row: ShadowRow, value: float) -> tuple[float, float]:
        x = left + (row.elapsed_s - x_min) / (x_max - x_min) * usable_width
        y = top + (y_max - value) / (y_max - y_min) * usable_height
        return x, y

    paths: list[str] = []
    legends: list[str] = []
    for attribute, label, color in series:
        segments: list[list[tuple[float, float]]] = []
        current: list[tuple[float, float]] = []
        for row in rows[::stride]:
            value = getattr(row, attribute)
            if value is None or not math.isfinite(float(value)):
                if current:
                    segments.append(current)
                    current = []
                continue
            current.append(point(row, float(value)))
        if current:
            segments.append(current)
        for segment in segments:
            coordinates = " ".join(
                ("M" if index == 0 else "L") + f"{x:.1f},{y:.1f}"
                for index, (x, y) in enumerate(segment)
            )
            paths.append(
                f'<path d="{coordinates}" fill="none" stroke="{color}" '
                'stroke-width="1.7" vector-effect="non-scaling-stroke"/>'
            )
        legends.append(
            f'<span><i style="background:{color}"></i>{html.escape(label)}</span>'
        )
    grid = "".join(
        f'<line x1="{left}" y1="{top + usable_height * index / 4:.1f}" '
        f'x2="{width-right}" y2="{top + usable_height * index / 4:.1f}"/>'
        for index in range(5)
    )
    return (
        f'<section class="chart"><h3>{html.escape(title)}</h3>'
        f'<div class="legend">{"".join(legends)}</div>'
        f'<svg viewBox="0 0 {width} {height}" role="img">'
        f'<g class="grid">{grid}</g>{"".join(paths)}'
        f'<text x="8" y="{top + 5}">{y_max:.1f}</text>'
        f'<text x="8" y="{top + usable_height}">{y_min:.1f}</text>'
        f'<text x="{left}" y="{height-8}">{x_min:.0f}s</text>'
        f'<text x="{width-right-48}" y="{height-8}">{x_max:.0f}s</text>'
        f'<text x="{width-55}" y="18">{html.escape(unit)}</text>'
        '</svg></section>'
    )


def write_html(
    path: Path,
    report: dict[str, Any],
    rows_by_session: Sequence[Sequence[ShadowRow]],
) -> None:
    config = report["config"]
    quality = report["data_quality"]
    policy = report["shadow_policy"]
    prior = report["observed_engine_brake_prior"]
    event_rows = []
    for group in report["events"].values():
        for event in group:
            event_rows.append(
                "<tr>"
                f"<td>{html.escape(event['event_id'])}</td>"
                f"<td>{html.escape(event['kind'])}</td>"
                f"<td>{event['start_s']:.1f}</td>"
                f"<td>{event['duration_s']:.1f}</td>"
                f"<td>{event.get('speed_start_kph') or 0:.1f} → {event.get('speed_end_kph') or 0:.1f}</td>"
                f"<td>{event.get('minimum_lead_distance_m') if event.get('minimum_lead_distance_m') is not None else '—'}</td>"
                f"<td>{'oui' if event.get('service_brake_required') else 'non'}</td>"
                "</tr>"
            )
    charts: list[str] = []
    for rows in rows_by_session:
        if not rows:
            continue
        charts.append(f"<h2>{html.escape(rows[0].session_id)}</h2>")
        charts.append(_svg_chart(rows, (
            ("speed_kph", "Véhicule", "#73d6ff"),
            ("stock_setpoint_kph", "RVV PSA", "#f2c94c"),
            ("applied_shadow_setpoint_kph", "Cible shadow appliquée", "#7ee787"),
            ("lead_speed_kph", "Véhicule précédent", "#e879f9"),
        ), "Vitesses et consignes", "km/h"))
        charts.append(_svg_chart(rows, (
            ("lead_distance_m", "Distance lead", "#73d6ff"),
            ("safe_gap_m", "Distance souhaitée", "#7ee787"),
            ("danger_gap_m", "Zone danger", "#ff7b72"),
        ), "Distance adaptative", "m"))
        charts.append(_svg_chart(rows, (
            ("actual_accel_ms2", "Accélération réelle", "#f2c94c"),
            ("requested_accel_ms2", "Décision shadow", "#ff7b72"),
            ("engine_brake_limited_accel_ms2", "Limite frein moteur", "#73d6ff"),
        ), "Accélération longitudinale", "m/s²"))
    agreement = policy["lead_exact_decision_agreement_fraction"]
    document = f"""<!doctype html>
<html lang="fr"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width">
<title>Shadow RVV T9</title><style>
body{{font:15px system-ui;background:#0d1117;color:#e6edf3;margin:0;padding:28px}}
main{{max-width:1180px;margin:auto}}h1,h2,h3{{margin:0.7em 0}}.warning{{background:#3b2611;border:1px solid #9e6a03;padding:14px;border-radius:8px}}
.cards{{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:12px;margin:18px 0}}.card,.chart{{background:#161b22;border:1px solid #30363d;border-radius:8px;padding:14px}}
.card b{{display:block;font-size:25px;color:#7ee787}}svg{{width:100%;height:auto}}.grid line{{stroke:#30363d;stroke-width:1}}svg text{{fill:#8b949e;font-size:12px}}.legend{{display:flex;gap:18px;flex-wrap:wrap;color:#b1bac4;margin-bottom:6px}}.legend i{{display:inline-block;width:14px;height:3px;margin:0 6px 3px 0}}
table{{width:100%;border-collapse:collapse;background:#161b22}}th,td{{padding:8px;border:1px solid #30363d;text-align:left}}code{{color:#73d6ff}}a{{color:#73d6ff}}
</style></head><body><main>
<h1>Shadow longitudinal Peugeot 308 T9</h1>
<p class="warning"><b>Lecture seule.</b> Aucun port série, aucune émission CAN et aucune commande véhicule. Le calcul est un surrogate analytique, pas le MPC acados exact d'openpilot.</p>
<div class="cards">
<div class="card"><b>{quality['samples']}</b>points synchronisés</div>
<div class="card"><b>{quality['eligible_samples']}</b>points RVV éligibles</div>
<div class="card"><b>{quality['lead_confident_eligible_samples']}</b>leads confiants</div>
<div class="card"><b>{policy['service_brake_required_samples']}</b>points hors frein moteur</div>
<div class="card"><b>{'—' if agreement is None else f'{agreement:.1%}'}</b>accord exact avec lead</div>
<div class="card"><b>{prior['events']}</b>séquences frein moteur observées</div>
</div>
<p>Référence openpilot <code>{OPENPILOT_LONGITUDINAL_REVISION}</code> : suivi standard {config['t_follow_s']:.2f} s, distance d'arrêt {config['stop_distance_m']:.1f} m. La consigne PSA simulée reste bornée à {config['min_setpoint_kph']}–{config['max_setpoint_kph']} km/h et évolue de {config['setpoint_step_kph']} km/h toutes les {config['setpoint_step_interval_s']:.2f} s.</p>
{''.join(charts)}
<h2>Événements</h2><table><thead><tr><th>ID</th><th>Type</th><th>Début (s)</th><th>Durée</th><th>Vitesse (km/h)</th><th>Distance min (m)</th><th>Frein requis</th></tr></thead><tbody>{''.join(event_rows) or '<tr><td colspan="7">Aucun événement qualifié</td></tr>'}</tbody></table>
<h2>Limites</h2><ul>{''.join(f'<li>{html.escape(item)}</li>' for item in report['limitations'])}</ul>
</main></body></html>"""
    path.write_text(document, encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("sessions", nargs="+", type=Path)
    parser.add_argument("--dbc", type=Path, default=DEFAULT_DBC)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--lead-min-probability", type=float, default=0.50)
    parser.add_argument("--time-gap-s", type=float, default=OPENPILOT_T_FOLLOW_STANDARD_S)
    parser.add_argument("--engine-brake-decel-ms2", type=float, default=0.30)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if not 0.0 <= args.lead_min_probability <= 1.0:
        raise ValueError("--lead-min-probability doit être compris entre 0 et 1")
    if args.time_gap_s <= 0.0 or args.engine_brake_decel_ms2 <= 0.0:
        raise ValueError("Le temps de suivi et le frein moteur doivent être positifs")
    config = RvvShadowConfig(
        lead_min_probability=args.lead_min_probability,
        t_follow_s=args.time_gap_s,
        engine_brake_decel_ms2=args.engine_brake_decel_ms2,
    )
    output = (
        args.output.resolve()
        if args.output
        else DEFAULT_OUTPUT_ROOT / datetime.now(timezone.utc).strftime("rvv-shadow-%Y%m%dT%H%M%SZ")
    )
    output.mkdir(parents=True, exist_ok=True)
    print("SHADOW LONGITUDINAL RVV T9 — HORS LIGNE", flush=True)
    print("Aucun port série, aucune émission CAN, aucune commande véhicule.", flush=True)
    rows_by_session: list[list[ShadowRow]] = []
    inputs: list[dict[str, Any]] = []
    for session in args.sessions:
        rows, summary = replay_session(session, args.dbc.resolve(), config)
        rows_by_session.append(rows)
        inputs.append(summary)
        print(
            f"[rejeu] {summary['session_id']}: {summary['samples']} points, "
            f"{summary['duration_s']:.1f} s",
            flush=True,
        )
    report, events = build_report(rows_by_session, inputs, config)
    report.update({
        "artifacts": {
            "report_html": str((output / "report.html").resolve()),
            "trace_csv": str((output / "trace.csv").resolve()),
            "events_csv": str((output / "events.csv").resolve()),
        }
    })
    (output / "report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    write_trace(output / "trace.csv", (row for rows in rows_by_session for row in rows))
    write_events(output / "events.csv", events)
    write_html(output / "report.html", report, rows_by_session)
    print(
        f"[qualification] éligibles={report['data_quality']['eligible_samples']}, "
        f"lead={report['data_quality']['lead_confident_eligible_samples']}, "
        f"frein requis={report['shadow_policy']['service_brake_required_samples']}",
        flush=True,
    )
    print(f"[rapport] {(output / 'report.html').resolve()}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
