"""Keep passive RVV research from turning output correlations into button claims."""
import importlib.util
import json
from pathlib import Path
import sys

import numpy as np
import pytest


def load(name):
    spec = importlib.util.spec_from_file_location(name, Path(__file__).parents[1] / 'tools' / f'{name}.py')
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


audit = load('audit_t9_rvv_button_candidates')
summary = load('summarize_t9_rvv_button_search')


@pytest.mark.parametrize(('speed', 'expected'), [(0x57, 1), (0x58, 1), (0x59, 0), (0x60, 0),
                                               (0x61, 1), (0x80, 2), (0x81, 3), (0xff, 0)])
def test_parity_matches_recorded_and_independent_vectors(speed, expected):
    assert audit.parity(speed) == expected


def raw(hexdata):
    return int.from_bytes(bytes.fromhex(hexdata), 'little')


def test_recorded_increase_and_decrease_are_setpoint_effects():
    # Original ESP32 session regu, 2026-08-05, not synthetic button messages.
    _, stats = audit.setpoint_changes([0, 100_000_000], [raw('121a0014474257af'), raw('121a0014474258a1')])
    assert stats == {'frames': 2, 'parity_ok': 2}
    changes, _ = audit.setpoint_changes([0, 100_000_000], [raw('12130014324261a5'), raw('02130014324260a7')])
    assert changes[0]['from_kph'] == 97 and changes[0]['to_kph'] == 96
    assert changes[0]['delta_kph'] == -1


@pytest.mark.parametrize('obstacle', ['gap', 'duplicate_time', 'bad_parity', 'counter_repeated', 'inactive', 'limiter'])
def test_unreliable_or_non_cruise_transitions_are_not_events(obstacle):
    before, after = raw('121a0014474257af'), raw('121a0014474258a1')
    times = [0, 100_000_000]
    if obstacle == 'gap':
        times[1] = 250_000_001
    elif obstacle == 'duplicate_time':
        times[1] = 0
    elif obstacle == 'bad_parity':
        before ^= 1 << 4
    elif obstacle == 'counter_repeated':
        after = (after & ~(15 << 56)) | (15 << 56)
    elif obstacle == 'inactive':
        after &= ~(1 << 63)
    elif obstacle == 'limiter':
        before = (before & ~(3 << 61)) | (2 << 61)
        after = (after & ~(3 << 61)) | (2 << 61)
    assert audit.setpoint_changes(times, [before, after])[0] == []


def test_corrupt_middle_frame_breaks_continuity():
    before, after = raw('121a0014474257af'), raw('121a0014474258a1')
    assert audit.setpoint_changes([0, 100_000_000, 200_000_000], [before, before ^ 16, after])[0] == []


def test_future_and_stale_edges_never_confirm_a_change():
    hits, ages = audit.hit_latencies(np.array([100, 300], dtype=np.uint64),
                                     np.array([90, 100, 200, 250, 305], dtype=np.uint64), 100)
    assert hits.tolist() == [False, True, True, False, True]
    assert ages.tolist() == [-1, 0, 100, 150, 5]


def test_held_change_grouping_keeps_direction_and_pauses():
    changes = [{'ns': t, 'delta_kph': end - start, 'from_kph': start, 'to_kph': end}
               for t, start, end in [(1, 80, 81), (500_000_000, 81, 83), (600_000_000, 83, 82),
                                    (1_700_000_001, 82, 81)]]
    groups = audit.change_groups(changes)
    assert [(g['sign'], g['changes']) for g in groups] == [(1, 2), (-1, 1), (-1, 1)]
    assert groups[0]['from_kph'] == 80 and groups[0]['to_kph'] == 83


def test_affine_recovery_reports_ambiguity_with_insufficient_variation():
    models = summary.affine_models([0, 1], [0, 1])
    assert len(models) == 128  # Seven input bits have never varied.
    assert summary.affine_models([1, 1], [0, 1]) == []
    assert summary.affine_models([], []) == []


def test_affine_recovery_finds_xor_using_independent_training_basis():
    # All-zero plus each input bit in isolation is a full affine basis.
    values = [0, 1, 2, 4, 8, 16, 32, 64, 128]
    assert summary.affine_models(values, [0, 1, 1, 1, 1, 0, 0, 0, 0]) == [{'mask': 15, 'bias': 0}]
    assert summary.affine_models(values, [0, 0, 0, 0, 0, 1, 1, 1, 1]) == [{'mask': 240, 'bias': 0}]


def test_gaps_do_not_invent_edge_timing():
    times = np.array([0, 100_000_000, 500_000_000, 600_000_000], dtype=np.uint64)
    values = np.array([0, 1, 0, 1], dtype=np.uint64)
    assert summary.edges_for_bit(times, values, 0, 'fall').tolist() == []
    assert summary.edges_for_bit(times, values, 0, 'rise').tolist() == [100_000_000, 600_000_000]


def test_jsonl_filters_tx_and_unknown_bus_and_keeps_bus_clocks_separate(tmp_path):
    frame = {'type': 'can_frame', 'timestamp_us': 100, 'source_timestamp_us': 999999,
             'arbitration_id': 0x50e, 'data_hex': '121a0014474257af', 'direction': 'rx', 'extended': False, 'bus': 'live'}
    rows = [frame, {**frame, 'direction': 'tx'}, {**frame, 'extended': True}, {**frame, 'bus': None},
            {**frame, 'bus': 'diagnostic', 'source_timestamp_us': 1},
            {'type': 'marker', 'timestamp_us': 100, 'name': 'test', 'note': 'annotation'}]
    path = tmp_path / 'session.jsonl'
    path.write_text('\n'.join(map(json.dumps, rows)) + '\n')
    streams, sources, tails, counts, metadata = audit.collect_jsonl(path)
    assert counts == {'physical_rx_frames': 2, 'excluded_not_standard_rx': 2, 'excluded_unknown_bus': 1}
    assert streams[(0x50e, 0, 8)][0].tolist() == [100_000]
    assert streams[(0x50e, 1, 8)][0].tolist() == [100_000]
    assert len(sources[0]['sha256']) == 64 and tails == []
    assert metadata['jsonl_bus_labels'] == {'live': 0, 'diagnostic': 1}


def test_cross_route_evaluation_counts_zero_hits_in_second_route():
    times = np.arange(0, 20_100_000_000, 100_000_000, dtype=np.uint64)
    signal = np.zeros(len(times), dtype=np.uint64)
    signal[(times >= 9_900_000_000) & (times <= 10_000_000_000)] = 1
    candidate = {'address': '0x123', 'bus': 0, 'dlc': 1, 'bit_lsb': 0, 'polarity': 'rise', 'direction': 'plus'}
    base = {'reference_setpoint_bus': 0, 'change_groups': [{'ns': 10_000_000_000, 'sign': 1}],
            'ranked_bit_correlations': [candidate]}
    good = ({**base, 'route': 'good'}, {'123_0_1_ns': times, '123_0_1_data': signal})
    bad = ({**base, 'route': 'bad', 'ranked_bit_correlations': []},
           {'123_0_1_ns': times, '123_0_1_data': np.zeros_like(signal)})
    [row] = summary.cross_route_candidates([good, bad])
    assert row['events'] == 2 and row['hits'] == 1 and row['hit_rate'] == .5
    assert row['per_route'][1]['hits'] == 0
    assert row['validated_button'] is False


def test_message_bus_is_chosen_by_coverage_not_bsi_bus_or_correlation():
    cache = {'208_0_8_ns': np.arange(100), '208_2_8_ns': np.arange(2),
             '50e_0_8_ns': np.arange(2), '50e_2_8_ns': np.arange(100),
             '30d_0_8_ns': np.arange(100), '30d_1_8_ns': np.arange(100)}
    assert summary.buses_by_coverage(cache, preferred=2) == {(0x208, 8): 0, (0x50e, 8): 2, (0x30d, 8): 0}
