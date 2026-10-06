"""Protect the audit against future data, stale joins and invented EPS runs."""
import importlib.util
from pathlib import Path

import pytest


def load(name):
    spec = importlib.util.spec_from_file_location(name, Path(__file__).parents[1] / 'tools' / f'{name}.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


audit = load('audit_t9_trip_events')
summary = load('summarize_t9_trip_events')


def test_only_fresh_past_valid_observations_are_joined():
    rows = [{'ns': 10, 'valid': True}, {'ns': 20, 'valid': False}, {'ns': 30, 'valid': True}]
    timestamps = [r['ns'] for r in rows]
    assert audit.past(rows, timestamps, 9, 10) is None
    assert audit.past(rows, timestamps, 19, 10) == rows[0]
    assert audit.past(rows, timestamps, 21, 10) is None  # Never fall back past malformed RX.
    assert audit.past(rows, timestamps, 40, 10) == rows[2]
    assert audit.past(rows, timestamps, 41, 10) is None


@pytest.mark.parametrize('raw', [-1024, -10, -1, 0, 1, 10, 1023])
def test_signed_torque_does_not_include_state_bits(raw):
    data = bytearray(8)
    data[3] = (raw & 2047) >> 3
    data[4] = ((raw & 7) << 5) | (4 << 2)
    data[5] = 100 << 1
    assert audit.steering(data) == {'state': 4, 'factor': 100, 'torque_raw': raw, 'hex': data.hex()}
    assert audit.steering(data[:7]) is None


def eps(ns, state, valid=True, activity=False):
    return {'ns': ns, 'state': state, 'valid': valid, 'activity_candidate': activity}


def test_eps_transition_uses_sample_time_and_never_a_future_decision_as_prior():
    samples = [eps(100_000_000, 1), eps(200_000_000, 3), eps(300_000_000, 3), eps(400_000_000, 0)]
    decisions = [{'mono_ns': 250_000_000, 'reason': 'active'}, {'mono_ns': 410_000_000, 'reason': 'eps_not_authorized'}]
    [exit_event] = summary.eps_exits(samples, decisions)
    assert exit_event['observed_active_duration_s'] == .2
    assert exit_event['observed_activity_false_before_s'] == .1
    assert exit_event['decision_before']['reason'] == 'active'
    assert exit_event['decision_after']['reason'] == 'eps_not_authorized'


def test_first_active_sample_is_left_censored():
    [event] = summary.eps_exits([eps(100_000_000, 3), eps(200_000_000, 0)], [])
    assert event['observed_active_duration_s'] is None


def test_gaps_and_invalid_eps_do_not_create_withdrawals():
    assert summary.eps_exits([eps(1, 3), eps(300_000_000, 0)], []) == []
    assert summary.eps_exits([eps(1, 3), eps(100_000_000, 0, valid=False)], []) == []
    assert summary.eps_exits([eps(1, 3, valid=False), eps(100_000_000, 0)], []) == []


def test_gapped_active_run_has_unknown_start_and_activity_restarts():
    samples = [eps(1, 1), eps(100_000_000, 3), eps(900_000_000, 3),
               eps(1_000_000_000, 3, activity=True), eps(1_100_000_000, 3), eps(1_200_000_000, 0)]
    [event] = summary.eps_exits(samples, [])
    assert event['observed_active_duration_s'] is None
    assert event['observed_activity_false_before_s'] == 0


def test_duplicate_segments_and_different_boots_cannot_be_aggregated():
    one = {'source': '/logs/00000021--route--0/rlog.zst', 'boot_ids': ['boot-a']}
    with pytest.raises(ValueError, match='Duplicate segment'):
        summary.summarize([one, one])
    two = {'source': '/logs/00000021--route--1/rlog.zst', 'boot_ids': ['boot-b']}
    with pytest.raises(ValueError, match='Multiple boots'):
        summary.summarize([one, two])
