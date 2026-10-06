import pytest

from tools.audit_t9_driver_effort import analyze, compare_limits, driver_value, excursions, recent, write_markdown


def row(ms, raw, counter, valid=True):
    return {'ns': 1_000_000_000 + ms * 1_000_000, 'driver_raw': raw, 'counter': counter, 'valid': valid}


def test_signed_raw_and_corrupt_checksum():
    assert driver_value(bytes.fromhex('2afaffffffffff')) == -6
    assert driver_value(bytes.fromhex('6afaffffffffff')) is None
    assert driver_value(bytes(6)) is None


def test_one_sample_excursion_has_observed_zero_span_and_bounded_duration():
    rows = [row(0, 5, 0), row(10, -6, 1), row(20, 4, 2)]
    result = excursions(rows)
    assert len(result) == 1
    assert result[0]['samples'] == 1
    assert result[0]['observed_span_ms'] == 0
    assert result[0]['duration_upper_bound_ms'] == 20


def test_gaps_and_counter_discontinuities_leave_duration_unknown():
    for boundary in (row(50, 0, 2), row(20, 0, 4), row(20, None, 2, valid=False)):
        result = excursions([row(0, 0, 0), row(10, 6, 1), boundary])
        assert result[0]['after_ns'] is None
        assert result[0]['duration_upper_bound_ms'] is None


def test_counter_wrap_and_segment_start():
    result = excursions([row(0, 8, 15), row(10, 7, 0), row(20, 0, 1)])
    assert result[0]['samples'] == 2
    assert result[0]['observed_span_ms'] == 10
    assert result[0]['duration_upper_bound_ms'] is None


def test_no_future_stale_or_invalid_value_substituted():
    rows = [row(0, 0, 0), row(10, None, 1, valid=False), row(20, 9, 2)]
    timestamps = [r['ns'] for r in rows]
    assert recent(rows, timestamps, row(-1, 0, 0)['ns'], 30_000_000) is None
    assert recent(rows, timestamps, row(5, 0, 0)['ns'], 30_000_000)['driver_raw'] == 0
    assert recent(rows, timestamps, row(15, 0, 0)['ns'], 30_000_000) is None
    assert recent(rows, timestamps, row(51, 0, 0)['ns'], 30_000_000) is None


def test_sorted_decisions_count_cut_once_and_pair_only_past_physical_data():
    ns = lambda ms: 1_000_000_000 + ms * 1_000_000
    records = [(ns(0), 'lateral', {'phase': 'active', 'reason': 'eps_active'})]
    records += [(ns(ms), 'driver', row(ms, value, counter)) for ms, value, counter in (
        (0, 5, 0), (10, -6, 1), (20, 0, 2))]
    records += [(ns(11), 'lateral', {'phase': 'blocked', 'reason': 'driver_override'}),
                (ns(12), 'eps', {'valid': True, 'state': 3, 'activity_candidate': True}),
                (ns(15), 'lateral', {'phase': 'blocked', 'reason': 'driver_override'})]
    result, _ = analyze(list(reversed(records)))
    assert result['counts']['activity_true_over_current_limit'] == 1
    assert len(result['driver_cuts']) == 1
    cut = result['driver_cuts'][0]
    assert cut['physical_driver_at_or_before_cut']['driver_raw'] == -6
    assert cut['physical_eps_at_or_before_cut'] is None
    assert cut['excursion_at_or_before_cut']['duration_upper_bound_ms'] == 20
    assert cut['driver_intent'] == 'unlabelled'


def test_comparison_respects_signed_threshold_boundary_and_measures_delay():
    rows = [row(ms, -6 if ms < 30 else -10 if ms < 70 else -11, (ms // 10) % 16)
            for ms in range(0, 531, 10)]
    result = compare_limits(rows, row(1, 0, 0)['ns'], (5, 10))
    assert result['window_complete']
    assert result['limits']['5']['delay_from_recorded_cut_ms'] == 0
    assert result['limits']['10']['delay_from_recorded_cut_ms'] == 69


def test_comparison_missing_signal_does_not_mean_threshold_was_not_exceeded():
    rows = [row(0, 6, 0), row(10, 6, 1), row(60, 11, 6)]
    result = compare_limits(rows, row(1, 0, 0)['ns'], (10,))
    assert not result['window_complete']
    assert result['last_observed_ns'] == row(10, 0, 0)['ns']
    assert result['limits']['10']['first_over_ns'] is None


def test_comparison_cannot_use_future_sample_as_initial_state():
    result = compare_limits([row(10, 20, 1)], row(0, 0, 0)['ns'], (10,))
    assert not result['window_complete']
    assert result['last_observed_ns'] is None
    assert result['limits']['10']['first_over_ns'] is None


@pytest.mark.parametrize('limits', [(), (0,), (128,), (True,), (5.0,)])
def test_invalid_comparison_limits(limits):
    with pytest.raises(ValueError):
        analyze([], limits)


def test_recorded_eight_threshold_is_used_for_counts_and_excursions(tmp_path):
    rows = [row(ms, raw, index) for index, (ms, raw) in enumerate([(0, 6), (10, 8), (20, -9), (30, 8)])]
    records = [(r['ns'], 'driver', r) for r in rows]
    records += [(r['ns'] + 1, 'eps', {'valid': True, 'state': 3, 'activity_candidate': True}) for r in rows]
    records += [(row(0, 0, 0)['ns'], 'lateral', {'phase': 'active', 'reason': 'eps_active'}),
                (row(21, 0, 0)['ns'], 'lateral', {'phase': 'blocked', 'reason': 'driver_override'})]
    result, _ = analyze(records, (8, 10), observed_limit_raw=8)
    assert result['observed_limit_raw'] == 8
    assert result['counts']['activity_true_over_current_limit'] == 1
    cut = result['driver_cuts'][0]
    assert cut['excursion_at_or_before_cut']['samples'] == 1
    assert cut['threshold_comparison']['limits']['8']['delay_from_recorded_cut_ms'] == 0
    assert cut['threshold_comparison']['limits']['10']['first_over_ns'] is None
    assert not cut['threshold_comparison']['window_complete']
    report = {'driver_limit_raw_observed_in_current_port': 8, 'segments': [dict(result, source='route--0/rlog.zst')]}
    path = tmp_path / 'report.md'
    write_markdown(report, path)
    assert 'au-dessus de ±8' in path.read_text()
    assert 'au-dessus de ±5' not in path.read_text()


@pytest.mark.parametrize('limit', [0, 128, True, 8.0])
def test_invalid_recorded_limit(limit):
    with pytest.raises(ValueError):
        analyze([], observed_limit_raw=limit)
    with pytest.raises(ValueError):
        excursions([], observed_limit_raw=limit)
