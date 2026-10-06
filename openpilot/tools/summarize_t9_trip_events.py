#!/usr/bin/env python3
"""Summarize read-only T9 rlog exports without treating correlation as causation.

EPS RX is sampled at about 10 Hz. Durations are between recorded observations,
not exact internal ECU transition times. Host sendcan is a request, not a
measurement of applied torque. The activity bit is not a hands sensor.
"""
import argparse
from bisect import bisect_left, bisect_right
from collections import Counter, defaultdict
import gzip
import json
from pathlib import Path


def eps_exits(samples, decisions):
    samples = sorted(samples, key=lambda row: row['ns'])
    decisions = sorted(decisions, key=lambda row: row['mono_ns'])
    times = [row['mono_ns'] for row in decisions]
    exits, previous, start, quiet_start = [], None, None, None
    for row in samples:
        contiguous = (previous is not None and row['valid'] and previous['valid']
                      and 0 < row['ns'] - previous['ns'] <= 250_000_000)
        if not contiguous:
            start = quiet_start = None
        if row['valid'] and row['state'] == 3:
            # A run already active at the first sample is left-censored.
            if contiguous and previous['state'] != 3:
                start = row['ns']
            if row['activity_candidate'] is False:
                if quiet_start is None:
                    quiet_start = row['ns']
            else:
                quiet_start = None
        elif contiguous and previous['state'] == 3:
            i = bisect_right(times, row['ns']) - 1
            before = decisions[i] if i >= 0 and row['ns'] - times[i] <= 1_250_000_000 else None
            j = bisect_left(times, row['ns'])
            after = decisions[j] if j < len(times) and times[j] - row['ns'] <= 150_000_000 else None
            exits.append({'ns': row['ns'], 'to_state': row['state'],
                          'observed_active_duration_s': None if start is None else (row['ns'] - start) / 1e9,
                          'observed_activity_false_before_s': None if quiet_start is None else (previous['ns'] - quiet_start) / 1e9,
                          'eps': row, 'previous_eps': previous, 'decision_before': before, 'decision_after': after})
            start = quiet_start = None
        else:
            start = quiet_start = None
        previous = row
    return exits


def summarize(rows):
    groups = defaultdict(list)
    for row in rows:
        name = Path(row['source']).parent.name
        route, segment = name.rsplit('--', 1)
        groups[route].append((int(segment), row))
    reports = []
    for route, segments in sorted(groups.items()):
        segments.sort(key=lambda item: item[0])
        if len({index for index, _ in segments}) != len(segments):
            raise ValueError(f'Duplicate segment in {route}')
        boots = {boot for _, row in segments for boot in row['boot_ids'] if boot}
        if len(boots) > 1:
            raise ValueError(f'Multiple boots in {route}; monotonic clocks cannot be joined')
        decisions = sorted((d for _, r in segments for d in r['lateral_decisions']), key=lambda d: d['mono_ns'])
        samples = [s for _, r in segments for s in r['eps_samples']]
        counters = {}
        for field in ('counts', 'alerts', 'host_sendcan', 'lateral_reasons', 'following_reasons', 'rvv_reasons'):
            value = Counter()
            for _, r in segments:
                value.update(r[field])
            counters[field] = dict(value)
        stops = []
        for previous, current in zip(decisions, decisions[1:]):
            if previous['phase'] == 'active' and current['phase'] != 'active':
                stops.append({'decision': current,
                              'continuous_log': 0 < current['mono_ns'] - previous['mono_ns'] <= 1_250_000_000,
                              'previous_decision': previous})
        panda = sorted((p for _, r in segments for p in r['panda_samples']), key=lambda p: p['ns'])
        spans = [r['speed_range_kph'] for _, r in segments if r['speed_range_kph'] is not None]
        firsts = [r['first_car_ns'] for _, r in segments if r['first_car_ns'] is not None]
        lasts = [r['last_car_ns'] for _, r in segments if r['last_car_ns'] is not None]
        reports.append({'route': route, 'segments': [i for i, _ in segments], 'boot_ids': sorted(boots),
                        'parse_complete': all(r['parse_complete'] for _, r in segments),
                        'duration_s': (max(lasts) - min(firsts)) / 1e9 if firsts else None,
                        'speed_range_kph': [min(s[0] for s in spans), max(s[1] for s in spans)] if spans else None,
                        **counters, 'active_stops': stops, 'eps_exits': eps_exits(samples, decisions),
                        'panda_first': panda[0] if panda else None, 'panda_last': panda[-1] if panda else None,
                        'host_tx_reject_count': sum(len(r['host_tx_rejects']) for _, r in segments),
                        'physical_rearm_count_max': max((d.get('physical_rearm_count', 0) for d in decisions), default=0),
                        'sources': [{'path': r['source'], 'sha256': r['compressed_sha256']} for _, r in segments]})
    return reports


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('export', type=Path, help='Completed gzip JSONL from audit_t9_trip_events.py')
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    with gzip.open(args.export, 'rt') as stream:
        rows = [json.loads(line) for line in stream]
    reports = summarize(rows)
    args.output.write_text(json.dumps(reports, indent=2) + '\n')
    for r in reports:
        reasons = Counter(s['decision']['reason'] for s in r['active_stops'] if s['continuous_log'])
        print(r['route'], f'{r["duration_s"]:.1f}s', f'{len(r["segments"])} segments', dict(reasons))


if __name__ == '__main__':
    main()
