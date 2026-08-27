import math

from tools.identify_t9_factory_lka import (
    IdentificationConfig,
    build_identifiability_assessment,
    effective_factory_torque_raw,
    scan_static_alignment,
    split_active_bursts,
)
from tools.simulate_t9_torque import ReplaySample


def sample(index: int, *, session_id: str = "test", elapsed_offset_s: float = 0.0,
           torque: float = 10.0, factor: int = 100,
           lateral_accel: float = 0.4) -> ReplaySample:
    return ReplaySample(
        session_id=session_id,
        timestamp_us=1_000_000 + index * 50_000,
        elapsed_s=elapsed_offset_s + index * 0.05,
        dt_s=0.05,
        speed_kph=90.0,
        desired_curvature_raw_1pm=0.002,
        desired_curvature_1pm=0.002,
        desired_lateral_accel_ms2=lateral_accel,
        measured_lateral_accel_yaw_ms2=lateral_accel,
        measured_lateral_accel_sensor_ms2=lateral_accel,
        steering_angle_deg=1.0,
        steering_rate_deg_s=0.0,
        driver_torque_raw=0.0,
        observed_lka_torque_raw=torque,
        observed_lka_state_raw=4,
        observed_lka_torque_factor_raw=factor,
        observed_lka_unknown_byte2_raw=0x10,
        observed_column_angle_setpoint_deg=0.0,
        eps_torque_candidate_nm=0.0,
        eps_state_lka_raw=3,
        steering_wheel_held_by_driver=False,
        eps_status_age_s=0.01,
        path_fit_rmse_m=0.01,
        can_age_s=0.01,
        brake_active=False,
        reverse=False,
        parking_brake=False,
        driver_door_open=False,
        driver_seatbelt_state=2,
        current_gear=4,
        counterfactual_eligible=True,
        safety_reasons=[],
    )


def test_effective_factory_torque_applies_ramped_factor() -> None:
    assert effective_factory_torque_raw(sample(0, torque=20.0, factor=50)) == 10.0


def test_active_bursts_require_sustained_factor_and_split_timing_gaps() -> None:
    config = IdentificationConfig(
        minimum_burst_samples=2,
        minimum_burst_duration_s=0.0,
    )
    samples = [
        sample(0),
        sample(1),
        sample(2, factor=50),
        sample(0, elapsed_offset_s=2.0),
        sample(1, elapsed_offset_s=2.0),
    ]

    bursts = split_active_bursts(samples, config)

    assert [len(burst) for burst in bursts] == [2, 2]


def test_static_alignment_recovers_synthetic_two_step_response() -> None:
    bursts = []
    for burst_index in range(3):
        commands = [
            12.0 * math.sin(0.31 * index + burst_index)
            + 4.0 * math.sin(1.17 * index)
            for index in range(90)
        ]
        burst = []
        for index, command in enumerate(commands):
            delayed = commands[index - 2] if index >= 2 else 0.0
            burst.append(sample(
                index,
                session_id=f"session-{burst_index}",
                torque=command,
                lateral_accel=0.04 * delayed,
            ))
        bursts.append(burst)

    scan = scan_static_alignment(bursts, maximum_lag_steps=5, sample_period_s=0.05)
    best = max(scan, key=lambda item: abs(item["command_response_correlation"]))

    assert best["lag_steps"] == 2
    assert math.isclose(
        best["apparent_gain_ms2_per_effective_raw"], 0.04, rel_tol=1e-6
    )


def test_identifiability_rejects_a_single_active_session() -> None:
    sessions = [
        {"active_samples": 1200},
        {"active_samples": 0},
    ]
    bursts = [
        {
            "session_id": "one-session",
            "apparent_gain_ms2_per_effective_raw": 0.038 + index * 0.0005,
        }
        for index in range(6)
    ]
    static = {"apparent_gain_ms2_per_effective_raw": 0.04, "lag_ms": 300.0}
    dynamic = {
        "dc_gain_median_ms2_per_effective_raw": 0.04,
        "delay_ms": 0.0,
        "improvement_over_persistence_fraction": 0.10,
    }

    assessment = build_identifiability_assessment(sessions, bursts, static, dynamic)

    assert assessment["gates"]["active_lka_in_at_least_2_sessions"] is False
    assert assessment["gates"]["static_and_dynamic_delay_within_100_ms"] is False
    assert assessment["vehicle_calibration_ready"] is False
