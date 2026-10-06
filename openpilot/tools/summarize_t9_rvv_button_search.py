#!/usr/bin/env python3
"""Cross-check recorded RVV correlations and recover the setpoint parity model.

Reads caches produced by audit_t9_rvv_button_candidates.py. No vehicle I/O.
Never upgrades a correlation to a validated button or produces CAN commands.
"""
import argparse
from collections import Counter
import json
from pathlib import Path

import numpy as np

from audit_t9_rvv_button_candidates import hit_latencies


def affine_models(values, observed):
    """Find every exact XOR-of-input-bits model, including a constant term."""
    pairs = {(int(v), int(c)) for v, c in zip(values, observed)}
    if not pairs:
        return []
    return [{'mask': mask, 'bias': bias} for mask in range(256) for bias in (0, 1)
            if all((((v & mask).bit_count() & 1) ^ bias) == c for v, c in pairs)]


def edges_for_bit(times, values, bit, polarity):
    continuous = (times[1:] > times[:-1]) & (times[1:] - times[:-1] <= 250_000_000)
    mask = np.uint64(1 << bit)
    changed = ((values[1:] ^ values[:-1]) & mask) != 0
    state = (values[1:] & mask) != 0
    return times[1:][continuous & changed & (state if polarity == 'rise' else ~state)]


def buses_by_coverage(cache, preferred):
    """Choose once by sample count, never by correlation with the desired answer.

    The BSI setpoint is received on bus 2; engine/brake traffic can be on bus 0/1.
    Choosing bus 2 for every message would drop most of the road observations.
    """
    choices = {}
    for key in cache:
        if not key.endswith('_ns'):
            continue
        address, bus, dlc, _ = key.split('_')
        address, bus, dlc = int(address, 16), int(bus), int(dlc)
        score = (len(cache[key]), bus == preferred, -bus)
        if (address, dlc) not in choices or score > choices[(address, dlc)][0]:
            choices[(address, dlc)] = score, bus
    return {key: value[1] for key, value in choices.items()}


def cross_route_candidates(datasets):
    # Candidate nomination on any route; evaluation includes zero-hit routes.
    selections = [buses_by_coverage(cache, report['reference_setpoint_bus']) for report, cache in datasets]
    keys = set()
    for (report, _), buses in zip(datasets, selections):
        for row in report['ranked_bit_correlations']:
            if row['bus'] == buses[(int(row['address'], 16), row['dlc'])]:
                keys.add((int(row['address'], 16), row['dlc'], row['bit_lsb'], row['polarity'], row['direction']))
    output = []
    for address, dlc, bit, polarity, direction in sorted(keys):
        rows = []
        total = Counter()
        for (report, cache), buses in zip(datasets, selections):
            bus = buses.get((address, dlc))
            if bus is None:
                continue
            prefix = f'{address:x}_{bus}_{dlc}'
            if prefix + '_ns' not in cache:
                continue
            times, values = cache[prefix + '_ns'], cache[prefix + '_data']
            groups = report['change_groups']
            selected = [g for g in groups if int(times[0]) + 5_250_000_000 <= g['ns'] <= int(times[-1])]
            events = np.array([g['ns'] for g in selected], dtype=np.uint64)
            signs = np.array([g['sign'] for g in selected])
            wanted = signs == (1 if direction == 'plus' else -1)
            edges = edges_for_bit(times, values, bit, polarity)
            hits, _ = hit_latencies(edges, events)
            null_hits, _ = hit_latencies(edges, events - 5_000_000_000)
            row = {'route': report['route'], 'bus': bus, 'events': int(wanted.sum()),
                   'hits': int((hits & wanted).sum()), 'null_hits': int((null_hits & wanted).sum()),
                   'opposite_events': int((~wanted).sum()), 'opposite_hits': int((hits & ~wanted).sum())}
            rows.append(row)
            total.update({k: row[k] for k in ('events', 'hits', 'null_hits', 'opposite_events', 'opposite_hits')})
        if not total['events']:
            continue
        hit_rate = total['hits'] / total['events']
        null_rate = total['null_hits'] / total['events']
        opposite_rate = total['opposite_hits'] / max(1, total['opposite_events'])
        output.append({'address': f'0x{address:X}', 'dlc': dlc, 'bit_lsb': bit, 'polarity': polarity,
                       'direction': direction, **total, 'hit_rate': hit_rate, 'null_hit_rate': null_rate,
                       'opposite_hit_rate': opposite_rate, 'score': hit_rate - max(null_rate, opposite_rate),
                       'known_setpoint_output': address in (0x50e, 0x452),
                       'per_route': rows, 'validated_button': False})
    return sorted(output, key=lambda r: (-r['score'], -r['hits'], r['address'], r['bit_lsb']))


def message_profiles(datasets):
    output = []
    for report, cache in datasets:
        for (address, dlc), bus in buses_by_coverage(cache, report['reference_setpoint_bus']).items():
            if address not in (0x50e, 0x452):
                continue
            prefix = f'{address:x}_{bus}_{dlc}'
            values, times = cache[prefix + '_data'], cache[prefix + '_ns']
            byte_values = [sorted(set(map(int, (values >> (8 * i)) & 255))) for i in range(dlc)]
            row = {'route': report['route'], 'address': f'0x{address:X}', 'bus': bus, 'frames': len(values),
                   'byte_values': byte_values}
            if address == 0x50e:
                counter = values & (np.uint64(15) << np.uint64(56))
                counter = (counter >> np.uint64(56)).astype(np.int64)
                fresh = (times[1:] > times[:-1]) & (times[1:] - times[:-1] <= 250_000_000)
                steps = (counter[1:] - counter[:-1]) & 15
                row['counter_steps_on_fresh_samples'] = dict(Counter(map(int, steps[fresh])))
            output.append(row)
    return output


def summarize(datasets, training_route):
    training = next((item for item in datasets if item[0]['route'] == training_route), None)
    if training is None:
        raise ValueError('Training route absent')
    checksum = {'training_route': training_route, 'fields': [], 'per_route': []}
    report, cache = training
    values = cache[f"50e_{report['reference_setpoint_bus']}_8_data"]
    speeds = ((values >> 48) & 255).astype(np.uint8)
    for bit in (4, 5):
        candidates = affine_models(speeds, (values >> bit) & 1)
        checksum['fields'].append({'payload_bit_lsb': bit, 'exact_affine_models': candidates,
                                   'training_distinct_speed_values': len(set(map(int, speeds)))})
    for report, cache in datasets:
        values = cache[f"50e_{report['reference_setpoint_bus']}_8_data"]
        speeds = ((values >> 48) & 255).astype(np.uint8)
        row = {'route': report['route'], 'frames': len(values), 'held_out': report['route'] != training_route,
               'distinct_speed_values': len(set(map(int, speeds))), 'models': []}
        for field in checksum['fields']:
            for model in field['exact_affine_models']:
                lookup = np.array([((v & model['mask']).bit_count() & 1) ^ model['bias'] for v in range(256)])
                mismatch = int(np.count_nonzero(lookup[speeds] != ((values >> field['payload_bit_lsb']) & 1)))
                row['models'].append({'bit': field['payload_bit_lsb'], **model, 'mismatches': mismatch})
        checksum['per_route'].append(row)
    for field in checksum['fields']:
        field['models_surviving_all_routes'] = [model for model in field['exact_affine_models']
            if all(m['mismatches'] == 0 for row in checksum['per_route'] for m in row['models']
                   if m['bit'] == field['payload_bit_lsb'] and m['mask'] == model['mask'] and m['bias'] == model['bias'])]
    return {'inputs': [{'route': r['route'], 'source_logs': r['source_logs'], 'counts': r['counts'],
                       'reference_bus': r['reference_setpoint_bus'], 'parity': r['stock_parity'],
                       'change_groups': len(r['change_groups']),
                       'groups_by_direction': dict(Counter(g['sign'] for g in r['change_groups']))}
                      for r, _ in datasets],
            'parity_recovery': checksum, 'message_profiles': message_profiles(datasets),
            'cross_route_candidates': cross_route_candidates(datasets),
            'ground_truth_button_labels': False, 'can_frames_emitted': 0,
            'limitations': ['Candidates nominated and evaluated on the same recordings: exploratory, not statistical validation.',
                            'A preceding bit edge is not evidence that an ECU accepts it as a button input.',
                            'No independently labeled button press/release sequence in the input.',
                            'Each message uses its most populated physical RX bus, chosen independently of correlation.',
                            'JSONL host reception timestamps have serial/host jitter.']}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--training-route', required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    datasets = []
    for path in sorted(args.root.glob('*/report.json')):
        with np.load(path.parent / 'physical-can.npz') as archive:
            cache = {key: archive[key] for key in archive.files}
        datasets.append((json.loads(path.read_text()), cache))
    result = summarize(datasets, args.training_route)
    args.output.write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps({'parity_recovery': result['parity_recovery'],
                      'top_candidates': result['cross_route_candidates'][:8]}, indent=2))


if __name__ == '__main__':
    main()
