import math

from tools.simulate_t9_rvv import (
    LeadObservation,
    RvvShadowConfig,
    actual_vehicle_action,
    lead_observation,
    longitudinal_policy,
    safe_obstacle_distance,
    step_rvv_setpoint,
)


def test_openpilot_safe_distance_reference_is_preserved() -> None:
    config = RvvShadowConfig()

    distance = safe_obstacle_distance(20.0, config)

    assert math.isclose(distance, 20.0**2 / 5.0 + 1.45 * 20.0 + 6.0)


def test_lead_speed_uses_model_relative_speed_and_can_ego_speed() -> None:
    record = {
        "speed_ms": 20.0,
        "pose": [18.0, 0.0, 0.0],
        "leads": [{
            "prob": 0.9,
            "distance_openpilot_m": 30.0,
            "v": [15.0],
            "a": [-0.4],
        }],
    }

    lead = lead_observation(record, ego_speed_ms=20.0)

    assert lead is not None
    assert lead.relative_speed_ms == -3.0
    assert lead.speed_ms == 17.0
    assert lead.acceleration_ms2 == -0.4


def test_close_slow_lead_requests_more_than_engine_brake_can_supply() -> None:
    config = RvvShadowConfig(engine_brake_decel_ms2=0.5)
    lead = LeadObservation(
        probability=0.95,
        distance_m=16.0,
        speed_ms=12.0,
        relative_speed_ms=-10.0,
        acceleration_ms2=-0.5,
    )

    decision = longitudinal_policy(
        ego_speed_ms=22.0,
        stock_setpoint_kph=90.0,
        lead=lead,
        config=config,
    )

    assert decision.source == "lead0"
    assert decision.requested_accel_ms2 < -config.engine_brake_decel_ms2
    assert decision.engine_brake_limited_accel_ms2 == -config.engine_brake_decel_ms2
    assert decision.service_brake_required is True
    assert decision.action == "service_brake_required"
    assert decision.target_setpoint_kph < 90.0


def test_distant_faster_lead_leaves_stock_rvv_setpoint_unchanged() -> None:
    config = RvvShadowConfig()
    lead = LeadObservation(0.9, 100.0, 28.0, 6.0, 0.0)

    decision = longitudinal_policy(22.0, 90.0, lead, config)

    assert decision.source == "cruise"
    assert decision.service_brake_required is False
    assert decision.action == "accelerate"
    assert decision.target_setpoint_kph == 90.0


def test_rvv_bridge_rate_limit_matches_one_kph_per_half_second() -> None:
    config = RvvShadowConfig()

    unchanged, last = step_rvv_setpoint(90.0, 70.0, 0.49, 0.0, config)
    first, last = step_rvv_setpoint(unchanged, 70.0, 0.50, last, config)
    two_more, last = step_rvv_setpoint(first, 70.0, 1.50, last, config)

    assert unchanged == 90.0
    assert first == 89.0
    assert two_more == 87.0
    assert last == 1.5


def test_actual_action_distinguishes_engine_brake_and_service_brake() -> None:
    assert actual_vehicle_action(-0.4, -50.0, False) == "engine_brake"
    assert actual_vehicle_action(-0.4, -50.0, True) == "service_brake"
    assert actual_vehicle_action(0.3, 80.0, False) == "accelerate"
    assert actual_vehicle_action(0.0, 20.0, False) == "hold"
