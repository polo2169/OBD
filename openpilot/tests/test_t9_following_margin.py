import json
import math
import pytest

from tools.analyze_t9_following_margin import closing_margin, recorded_observations


def case(**changes):
    return closing_margin(**(dict(distance_m=50., ego_kph=100., lead_kph=95.,
                                  deceleration_ms2=.3, delay_s=1., buffer_m=10.) | changes))


def test_five_kph_closing_under_explicit_ideal_assumptions():
    result = case()
    assert result['distance_consumed_until_speed_match_m'] == pytest.approx(4.603909465020576)
    assert result['required_start_distance_m'] == pytest.approx(14.603909465020577)
    assert result['time_until_speed_match_s'] == pytest.approx(5.62962962962963)
    assert result['margin_to_requested_buffer_m'] > 0


def test_twenty_kph_closing_already_needs_more_than_fifty_meters():
    result = case(lead_kph=80.)
    assert result['required_start_distance_m'] == pytest.approx(66.99588477366255)
    assert result['margin_to_requested_buffer_m'] < 0
    assert case(distance_m=10., lead_kph=80.)['constant_speed_ttc_s'] == pytest.approx(1.8)


def test_no_deceleration_has_no_finite_speed_match():
    result = case(deceleration_ms2=0.)
    assert result['required_start_distance_m'] is None
    assert result['time_until_speed_match_s'] is None
    assert result['margin_to_requested_buffer_m'] is None


def test_same_or_faster_lead_has_no_closing_loss():
    for speed in (100., 105.):
        result = case(lead_kph=speed, deceleration_ms2=0.)
        assert result['constant_speed_ttc_s'] is None
        assert result['distance_consumed_until_speed_match_m'] == 0
        assert result['required_start_distance_m'] == 10.


def test_headway_and_collision_time_are_distinct():
    result = case(distance_m=10., ego_kph=130., lead_kph=125.)
    assert result['headway_s'] == pytest.approx(.27692307692307694)
    assert result['constant_speed_ttc_s'] == pytest.approx(7.2)
    assert result['required_constant_deceleration_ms2'] is None


def test_delay_can_exhaust_available_gap_before_deceleration():
    result = case(distance_m=12., delay_s=2.)
    assert result['required_constant_deceleration_ms2'] is None
    assert result['margin_to_requested_buffer_m'] < 0


@pytest.mark.parametrize('changes', [dict(distance_m=0.), dict(ego_kph=-1.), dict(lead_kph=math.nan),
                                     dict(deceleration_ms2=-.3), dict(delay_s=math.inf), dict(buffer_m=True)])
def test_invalid_inputs_never_produce_a_favorable_result(changes):
    with pytest.raises(ValueError):
        case(**changes)


def test_logged_observations_preserve_source_across_clock_resets(tmp_path):
    sample = dict(stock_rvv_active=True, speed_kph=100., stock_setpoint_kph=100.,
                  target_kph=None, reason='observation_only',
                  lead=dict(present=True, valid=True, probability=.95,
                            distance_m=50., speed_ms=95. / 3.6))
    for name, clock, digest in [('route-a.json', 1000, 'a' * 64), ('route-b.json', 100, 'b' * 64)]:
        (tmp_path / name).write_text(json.dumps(dict(parse_complete=True, sha256=digest,
                                                    following=[dict(sample, log_ns=clock)])))
    result = recorded_observations(tmp_path, deceleration_ms2=.3, delay_s=1.)
    assert [r['rlog_sha256'] for r in result['observations']] == ['a' * 64, 'b' * 64]
    assert [r['log_ns'] for r in result['observations']] == [1000, 100]
    assert result['observations'][1]['audit'].endswith('route-b.json')
    assert result['log_sample_counts']['within_50m_closing_up_to_5kph_log_samples'] == 2


def test_incomplete_log_audit_cannot_be_used(tmp_path):
    (tmp_path / 'partial.json').write_text(json.dumps(dict(parse_complete=False, following=[])))
    with pytest.raises(ValueError, match='Incomplete audit'):
        recorded_observations(tmp_path, deceleration_ms2=.3, delay_s=1.)
