import numpy as np
import pytest

from tools.analyze_t9_lka_response import aligned_rows, arx_scan, ols, runs, torque_tls


def synthetic_route(seed, n=1800):
    rng = np.random.default_rng(seed)
    torque = np.repeat(rng.uniform(-15, 15, n // 10), 10)
    y = np.zeros(n)
    for i in range(3, n - 1):
        y[i + 1] = y[i] + .05 / .2 * (.04 * torque[i - 3] - y[i])
    return {'t': np.arange(n) * .05, 'torque': torque, 'driver': np.zeros(n),
            'can_lat': y, 'episode': np.ones(n), 'selected': np.arange(n) > 40,
            'active': np.ones(n, dtype=bool), 'factor': np.full(n, 100.), 'rate': np.zeros(n)}


def test_tls_recovers_gain_offset_and_distinguishes_normalization_from_limit():
    u = np.linspace(-25, 25, 1000)
    for norm in (10, 150):
        fit = torque_tls(u, .04 * u + .12, norm)
        assert fit['lat_accel_factor'] == pytest.approx(.04 * norm)
        assert fit['gain_ms2_per_raw'] == pytest.approx(.04)
        assert fit['offset_ms2'] == pytest.approx(.12)
        assert fit['friction_equivalent_raw'] == pytest.approx(0, abs=1e-10)


def test_signed_rate_fit_recovers_known_hysteresis_without_absorbing_driver():
    rng = np.random.default_rng(308)
    u, driver = rng.normal(size=(2, 1000))
    rate = rng.choice([-1, 0, 1], 1000)
    x = np.c_[np.ones(1000), u, driver, rate]
    fit = ols(x, .04*u + .03*driver - .06*rate + .1)
    assert fit['coefficients'] == pytest.approx([.1, .04, .03, -.06])
    assert -fit['coefficients'][3]/fit['coefficients'][1] == pytest.approx(1.5)


def test_alignment_never_crosses_inactive_episode_or_variable_factor():
    d = synthetic_route(1)
    d['active'][300:310] = False
    d['selected'][300:310] = False
    d['episode'][310:] = 2
    d['factor'][450:460] = 40
    _, _, _, _, i, j = aligned_rows(d, .15)
    assert np.all(i-j == 3)
    assert not np.any((j >= 300) & (j < 310))
    assert not np.any((j >= 450) & (j < 460))
    assert np.all(d['episode'][i] == d['episode'][j])


def test_arx_distinguishes_actuator_delay_from_first_order_response_time():
    best = min(arx_scan([synthetic_route(1), synthetic_route(2)], 'can_lat'),
               key=lambda x: x['mean_holdout_rmse_ms2'])
    assert best['delay_s'] == pytest.approx(.15)
    for route in best['routes']:
        assert route['dc_gain_ms2_per_raw'] == pytest.approx(.04)
        assert route['time_constant_s'] == pytest.approx(.2)
    assert best['mean_holdout_rmse_ms2'] < 1e-12


def test_run_boundaries_include_last_active_sample():
    assert runs(np.array([True, True, False, True])) == [(0, 2), (3, 4)]
