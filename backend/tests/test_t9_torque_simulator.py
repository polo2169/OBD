import math

from tools.simulate_t9_torque import (
    ControllerParameters,
    ReplaySample,
    SimulatorConfig,
    apply_torque_limits,
    decode_eps_status_495,
    estimate_path_curvature,
    fit_driver_proxy,
    safety_reasons,
    simulate,
    simulate_eps_rearm_effect,
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
