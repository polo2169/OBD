import json
import math

from tools.simulate_t9_torque import (
    ControllerParameters,
    OpenpilotTorqueParameters,
    ReplaySample,
    SimulationRow,
    SimulatorConfig,
    apply_torque_limits,
    build_r3_reference_assessment,
    compare_controller_profiles,
    decode_eps_status_495,
    detect_curve_events,
    detect_oscillation_review_windows,
    estimate_path_curvature,
    fit_driver_proxy,
    lateral_accel_from_steering_angle,
    load_auxiliary_sensor_timeline,
    openpilot_torque_kp,
    safety_reasons,
    simulate,
    simulate_openpilot_torque,
    simulate_eps_rearm_effect,
    summarize_command_dynamics,
    summarize_live_eps,
    summarize_matek_sensor_quality,
)


def sample(**overrides: object) -> ReplaySample:
    values = {
        "session_id": "test",
        "timestamp_us": 1_000_000,
        "elapsed_s": 0.0,
        "dt_s": 0.05,
        "speed_kph": 72.0,
        "desired_curvature_raw_1pm": 0.002,
        "desired_curvature_1pm": 0.002,
        "desired_lateral_accel_ms2": 0.8,
        "measured_lateral_accel_yaw_ms2": 0.0,
        "measured_lateral_accel_sensor_ms2": 0.0,
        "steering_angle_deg": 0.0,
        "steering_rate_deg_s": 0.0,
        "driver_torque_raw": 0.0,
        "observed_lka_torque_raw": 0.0,
        "observed_lka_state_raw": 2,
        "observed_lka_torque_factor_raw": 0,
        "observed_lka_unknown_byte2_raw": 0x12,
        "observed_column_angle_setpoint_deg": 0.0,
        "eps_torque_candidate_nm": 0.0,
        "eps_state_lka_raw": 2,
        "steering_wheel_held_by_driver": True,
        "eps_status_age_s": 0.01,
        "path_fit_rmse_m": 0.01,
        "can_age_s": 0.01,
        "brake_active": False,
        "reverse": False,
        "parking_brake": False,
        "driver_door_open": False,
        "driver_seatbelt_state": 2,
        "current_gear": 4,
        "counterfactual_eligible": True,
        "safety_reasons": [],
    }
    values.update(overrides)
    return ReplaySample(**values)  # type: ignore[arg-type]


def test_path_curvature_converts_openpilot_lateral_sign() -> None:
    expected_curvature = 0.004
    path = [[float(x), -0.5 * expected_curvature * x * x, 0.0] for x in range(33)]

    estimate = estimate_path_curvature(path, speed_ms=15.0)

    assert estimate is not None
    curvature, rms = estimate
    assert math.isclose(curvature, expected_curvature, rel_tol=0.02)
    assert rms < 1e-8


def test_torque_limiter_applies_magnitude_and_asymmetric_rates() -> None:
    config = SimulatorConfig()

    first = apply_torque_limits(100.0, 0.0, 0.05, config)
    released = apply_torque_limits(0.0, first, 0.05, config)

    assert first == 1.0
    assert released == 0.0
    assert abs(apply_torque_limits(-100.0, 0.0, 1.0, config)) <= config.max_torque_raw


def test_decode_eps_status_495_keeps_t9_state_raw() -> None:
    status = decode_eps_status_495(bytes.fromhex("04308200"))
    available = decode_eps_status_495(bytes.fromhex("00302800"))

    assert status.eps_torque_candidate_nm == 1.0
    assert status.steering_wheel_held_by_driver is True
    assert status.eps_state_lka_raw == 0
    assert status.dynamic_steering_state_raw == 3
    assert available.eps_state_lka_raw == 2
    assert available.steering_wheel_held_by_driver is False


def test_safety_reasons_detect_driver_override_and_vehicle_interlocks() -> None:
    reasons = safety_reasons(
        {
            "speed_kph": 80.0,
            "driver_torque_raw": 6,
            "brake_active": True,
            "reverse": False,
            "parking_brake": False,
            "driver_door": True,
            "driver_seatbelt_state": 2,
            "current_gear": 4,
        },
        SimulatorConfig(),
        can_age_s=0.01,
    )

    assert "driver_override" in reasons
    assert "brake_active" in reasons
    assert "driver_door_open" in reasons


def test_driver_proxy_recovers_linear_apparent_gain() -> None:
    samples = [
        sample(
            timestamp_us=1_000_000 + index * 50_000,
            elapsed_s=index * 0.05,
            driver_torque_raw=float(torque),
            measured_lateral_accel_yaw_ms2=0.09 * torque + 0.02,
        )
        for index, torque in enumerate(range(-20, 21))
    ]

    fit = fit_driver_proxy(samples, SimulatorConfig())

    assert math.isclose(fit.apparent_gain_ms2_per_driver_raw, 0.09, rel_tol=1e-9)
    assert math.isclose(fit.intercept_ms2, 0.02, abs_tol=1e-9)
    assert math.isclose(fit.correlation, 1.0, abs_tol=1e-9)


def test_shadow_simulation_never_exceeds_envelope_and_honors_override() -> None:
    config = SimulatorConfig()
    samples = [
        sample(
            timestamp_us=1_000_000 + index * 50_000,
            elapsed_s=index * 0.05,
            driver_torque_raw=6.0 if index >= 15 else 0.0,
            safety_reasons=["driver_override"] if index >= 15 else [],
        )
        for index in range(30)
    ]
    parameters = ControllerParameters(
        plant_gain_ms2_per_raw=0.1,
        feedforward_raw_per_ms2=10.0,
        kp_raw_per_ms2=4.0,
        ki_raw_per_ms2_s=0.0,
    )

    rows, metrics = simulate(samples, parameters, config)

    assert metrics["scored_samples"] > 0
    assert max(abs(row.unrestricted_torque_raw) for row in rows) <= config.max_torque_raw
    assert rows[-1].safety_applied_torque_raw == 0.0
    assert rows[-1].unrestricted_torque_raw > 0.0


def test_openpilot_torque_uses_current_speed_scheduled_kp() -> None:
    parameters = OpenpilotTorqueParameters(plant_gain_ms2_per_raw=0.1)

    assert openpilot_torque_kp(15.0, parameters) == 2.0
    assert math.isclose(openpilot_torque_kp(20.0, parameters), 1.6)
    assert openpilot_torque_kp(30.0, parameters) == 0.8


def test_t9_vehicle_model_keeps_validated_steering_sign_and_zero() -> None:
    assert lateral_accel_from_steering_angle(1.5, 20.0) == 0.0
    assert lateral_accel_from_steering_angle(10.0, 20.0) < 0.0
    assert lateral_accel_from_steering_angle(-10.0, 20.0) > 0.0


def test_openpilot_torque_delay_buffer_and_roll_compensation() -> None:
    samples = [
        sample(
            timestamp_us=1_000_000 + index * 50_000,
            elapsed_s=index * 0.05,
            desired_lateral_accel_ms2=0.2 if index >= 10 else 0.0,
            road_roll_rad=0.01,
        )
        for index in range(30)
    ]
    parameters = OpenpilotTorqueParameters(
        plant_gain_ms2_per_raw=0.1,
        friction=0.0,
        lateral_delay_s=0.15,
    )

    rows, _ = simulate_openpilot_torque(samples, parameters, SimulatorConfig())

    assert math.isclose(rows[12].controller_setpoint_ms2 or 0.0, 0.0, abs_tol=1e-9)
    assert math.isclose(rows[13].controller_setpoint_ms2 or 0.0, 0.2, abs_tol=1e-9)
    assert math.isclose(rows[-1].roll_compensation_ms2 or 0.0, 0.0981, rel_tol=1e-9)
    assert math.isclose(rows[-1].feedforward_ms2 or 0.0, 0.1019, rel_tol=1e-9)


def test_openpilot_torque_anti_windup_keeps_existing_raw_envelope() -> None:
    samples = [
        sample(
            timestamp_us=1_000_000 + index * 50_000,
            elapsed_s=index * 0.05,
            desired_lateral_accel_ms2=1.5,
        )
        for index in range(60)
    ]
    parameters = OpenpilotTorqueParameters(
        plant_gain_ms2_per_raw=0.03841,
        friction=0.08,
    )

    rows, metrics = simulate_openpilot_torque(samples, parameters, SimulatorConfig())

    assert max(abs(row.unrestricted_torque_raw) for row in rows) <= 10.0
    assert metrics["saturation_fraction"] > 0.9
    assert math.isclose(rows[-1].integral_ms2 or 0.0, 0.0, abs_tol=1e-12)
    assert (rows[-1].friction_compensation_ms2 or 0.0) > 0.0


def test_controller_comparison_exports_exact_and_t9_shadow_openpilot_profiles() -> None:
    samples = [
        sample(
            timestamp_us=1_000_000 + index * 50_000,
            elapsed_s=index * 0.05,
            desired_lateral_accel_ms2=0.2,
        )
        for index in range(40)
    ]
    selected = ControllerParameters(0.1, 7.0, 1.5, 0.0)

    comparison, profile_rows = compare_controller_profiles(
        [samples], selected, SimulatorConfig(),
    )
    profiles = {
        item["profile_id"]: item for item in comparison["profiles"]
    }

    assert "openpilot_torque_v1" in profile_rows
    assert "openpilot_torque_t9_shadow_v1" in profile_rows
    assert "sunnypilot_torque_v0" in profile_rows
    assert "sunnypilot_torque_v0_jerk_shadow" in profile_rows
    assert profiles["openpilot_torque_v1"]["parameters"]["structure_revision"]
    assert profiles["openpilot_torque_t9_shadow_v1"]["parameters"]["feedforward_scale"] == 0.55
    assert profiles["openpilot_torque_t9_shadow_v1"]["parameters"]["friction"] == 0.0
    assert profiles["openpilot_torque_t9_shadow_v1"]["shadow_tuning_basis"]["vehicle_calibration"] is False
    assert profiles["sunnypilot_torque_v0"]["parameters"]["kp_high_speed"] == 1.0
    assert profiles["sunnypilot_torque_v0"]["parameters"]["ki"] == 0.3
    assert profiles["sunnypilot_torque_v0_jerk_shadow"]["parameters"]["future_plan_status"] == (
        "recorded_path_time_series_surrogate_not_model_plan"
    )


def test_sunnypilot_jerk_shadow_uses_future_path_surrogate() -> None:
    samples = [
        sample(
            timestamp_us=1_000_000 + index * 50_000,
            elapsed_s=index * 0.05,
            desired_lateral_accel_ms2=0.7 * math.sin(index * 0.16),
        )
        for index in range(120)
    ]
    base = OpenpilotTorqueParameters(
        plant_gain_ms2_per_raw=0.1,
        kp_high_speed=1.0,
        ki=0.3,
        jerk_gain=0.0,
    )
    jerk = OpenpilotTorqueParameters(
        plant_gain_ms2_per_raw=0.1,
        kp_high_speed=1.0,
        ki=0.3,
        jerk_lookahead_s=1.4,
        jerk_lookahead_max_s=2.0,
        future_jerk_lookahead=True,
        jerk_gain=0.4,
        friction_error_scale=0.7,
    )

    base_rows, _ = simulate_openpilot_torque(samples, base, SimulatorConfig())
    jerk_rows, _ = simulate_openpilot_torque(samples, jerk, SimulatorConfig())

    assert any(abs(row.desired_lateral_jerk_ms3 or 0.0) > 0.01 for row in jerk_rows)
    assert any(
        abs(first.unrestricted_torque_raw - second.unrestricted_torque_raw) > 1e-6
        for first, second in zip(base_rows, jerk_rows, strict=True)
    )


def test_rearm_sensitivity_forces_periodic_shadow_torque_dropout() -> None:
    config = SimulatorConfig()
    samples = [
        sample(timestamp_us=1_000_000 + index * 50_000, elapsed_s=index * 0.05)
        for index in range(100)
    ]
    parameters = ControllerParameters(
        plant_gain_ms2_per_raw=0.1,
        feedforward_raw_per_ms2=10.0,
        kp_raw_per_ms2=4.0,
        ki_raw_per_ms2_s=0.0,
    )
    rows, _ = simulate(samples, parameters, config)

    metrics = simulate_eps_rearm_effect(
        rows, parameters, config, period_s=1.0, downtime_s=0.3, annotate=True
    )

    assert metrics["rearm_events"] >= 3
    assert metrics["rearm_samples"] > 0
    assert any(row.eps_rearm_active for row in rows)
    assert min(row.rearm_limited_torque_raw for row in rows[25:]) < max(
        row.unrestricted_torque_raw for row in rows[25:]
    )


def test_curve_aware_rearm_can_defer_dropout_to_lower_lateral_demand() -> None:
    config = SimulatorConfig()
    samples = [
        sample(
            timestamp_us=1_000_000 + index * 50_000,
            elapsed_s=index * 0.05,
            desired_lateral_accel_ms2=0.8 if 20 <= index < 28 else 0.1,
        )
        for index in range(50)
    ]
    parameters = ControllerParameters(0.1, 10.0, 4.0, 0.0)
    rows, _ = simulate(samples, parameters, config)

    fixed = simulate_eps_rearm_effect(rows, parameters, config, 1.0, 0.3)
    deferred = simulate_eps_rearm_effect(
        rows,
        parameters,
        config,
        1.0,
        0.3,
        curve_aware=True,
        max_deferral_s=0.5,
    )

    assert deferred["deferred_samples"] > 0
    assert deferred["rearm_starts_in_curve"] < fixed["rearm_starts_in_curve"]


def test_r3_assessment_uses_factor_active_eps_evidence() -> None:
    samples = [
        sample(
            observed_lka_torque_raw=12.0,
            observed_lka_state_raw=4,
            observed_lka_torque_factor_raw=100,
            observed_lka_unknown_byte2_raw=0x0D,
            eps_state_lka_raw=3,
        )
        for _ in range(5)
    ]

    live_eps = summarize_live_eps(samples)
    assessment = build_r3_reference_assessment(None, live_eps)
    eps_row = next(
        item for item in assessment["compatibility"]
        if item["aspect"] == "État EPS 0x495 près d'un couple usine"
    )

    assert live_eps["sustained_factor_active_eps_state_counts"] == {3: 5}
    assert "5/5" in eps_row["t9"]
    assert eps_row["verdict"] == "passive_capture_consistent_not_tx_validated"


def simulation_row(index: int, torque: float, desired: float = 0.8) -> SimulationRow:
    replay = sample(
        timestamp_us=1_000_000 + index * 50_000,
        elapsed_s=index * 0.05,
        desired_lateral_accel_ms2=desired,
    )
    return SimulationRow(
        sample=replay,
        simulated_lateral_accel_ms2=desired - 0.1,
        lateral_accel_error_ms2=0.1,
        unrestricted_torque_raw=torque,
        safety_applied_torque_raw=torque,
        saturated=abs(torque) >= 10.0,
    )


def test_command_dynamics_flags_alternating_torque_as_more_nervous() -> None:
    smooth = [simulation_row(index, index * 0.02) for index in range(100)]
    alternating = [
        simulation_row(index, 2.0 if index % 2 else -2.0)
        for index in range(100)
    ]

    smooth_metrics = summarize_command_dynamics(smooth)
    alternating_metrics = summarize_command_dynamics(alternating)

    assert alternating_metrics["torque_rate_p95_raw_s"] > smooth_metrics["torque_rate_p95_raw_s"]
    assert alternating_metrics["command_high_frequency_rms_raw"] > smooth_metrics["command_high_frequency_rms_raw"]
    assert alternating_metrics["torque_slope_reversals"] > 80


def test_curve_event_detection_merges_short_gaps_and_keeps_review_padding() -> None:
    rows = [
        simulation_row(
            index,
            torque=min(10.0, index * 0.1),
            desired=0.8 if 20 <= index < 45 and index != 32 else 0.1,
        )
        for index in range(80)
    ]

    events = detect_curve_events(rows)

    assert len(events) == 1
    assert events[0]["start_s"] == 1.0
    assert events[0]["end_s"] == 2.2
    assert events[0]["review_start_s"] == 0.0
    assert events[0]["review_end_s"] == 5.2


def test_oscillation_review_windows_return_non_overlapping_candidates() -> None:
    rows = [
        simulation_row(index, 3.0 if (index // 3) % 2 else -3.0)
        for index in range(240)
    ]

    windows = detect_oscillation_review_windows(rows, limit=3)

    assert len(windows) == 3
    for first, second in zip(windows, windows[1:]):
        assert first["end_s"] <= second["start_s"] or second["end_s"] <= first["start_s"]


def test_matek_timeline_keeps_only_physical_msp_records(tmp_path) -> None:
    path = tmp_path / "sensors.jsonl"
    records = [
        {"type": "device", "source": "matek_f722_se_msp", "received_timestamp_us": 1,
         "fc_variant": "INAV", "mounting_yaw_deg": 0},
        {"type": "imu", "source": "matek_f722_se_msp", "received_timestamp_us": 10,
         "acceleration_right_ms2": 0.2, "yaw_rate_right_deg_s": 1.0},
        {"type": "imu", "source": "esp32", "received_timestamp_us": 11,
         "raw_x": 1, "raw_y": 2, "raw_z": 3},
        {"type": "gps", "source": "matek_f722_se_msp", "received_timestamp_us": 20,
         "fix_valid": True, "latitude_deg": 48.0, "longitude_deg": 2.0,
         "speed_mps": 10.0},
        {"type": "gps", "source": "matek_f722_se_msp", "received_timestamp_us": 30,
         "fix_valid": True, "latitude_deg": 48.0001, "longitude_deg": 2.0,
         "speed_mps": 10.0},
    ]
    path.write_text("\n".join(json.dumps(item) for item in records) + "\n")

    timeline = load_auxiliary_sensor_timeline(path)

    assert len(timeline.imu) == 1
    assert len(timeline.gps) == 2
    assert timeline.summary["device"]["fc_variant"] == "INAV"
    assert 10.0 < timeline.summary["gps"]["track_distance_m"] < 12.0


def test_matek_quality_recovers_mount_sign_bias_and_gps_scale() -> None:
    samples = []
    for index in range(240):
        speed_kph = 40.0 + index * 0.15
        speed_ms = speed_kph / 3.6
        lateral = 1.2 * math.sin(index * 0.09)
        can_yaw_deg_s = math.degrees(lateral / speed_ms)
        samples.append(sample(
            timestamp_us=1_000_000 + index * 50_000,
            elapsed_s=index * 0.05,
            speed_kph=speed_kph,
            measured_lateral_accel_yaw_ms2=lateral,
            matek_lateral_accel_right_ms2=-1.1 * lateral + 0.18,
            matek_yaw_rate_right_deg_s=-0.9 * can_yaw_deg_s + 0.12,
            matek_sensor_age_s=0.02,
            matek_gps_speed_mps=1.02 * speed_ms + 0.05,
            matek_gps_age_s=0.10,
        ))

    quality = summarize_matek_sensor_quality(samples)

    assert quality["axis_sign_assessment"] == "matek_right_opposes_can_positive"
    assert math.isclose(
        quality["lateral_accel_fit_matek_right_vs_can_yaw"]["slope"],
        -1.1,
        rel_tol=1e-9,
    )
    assert math.isclose(quality["gps_speed_fit_matek_vs_can"]["slope"], 1.02, rel_tol=1e-9)
    assert quality["ready_for_lateral_factor_estimation"] is True
