#!/usr/bin/env python3
"""Search recorded CAN for signals preceding stock RVV setpoint changes.

This is correlation, not button ground truth or an encoder. Reads local rlogs
only. No network, serial, Panda or CAN transmission API is used.
Bit numbers are little-endian (byte*8 + bit), independent of DBC numbering.
"""
import argparse
from array import array
from collections import Counter, defaultdict
import hashlib
import json
from pathlib import Path
import sys

import numpy as np


def parity(value):
    return (((value >> 4).bit_count() & 1) << 1) | ((value & 15).bit_count() & 1)


def setpoint_changes(times, payloads):
    changes, stats = [], Counter()
    previous = None
    for ns, raw in zip(times, payloads):
        ns, raw = int(ns), int(raw)
        data = raw.to_bytes(8, 'little')
        valid = ((data[0] >> 4) & 3) == parity(data[6])
        stats['frames'] += 1
        stats['parity_ok' if valid else 'parity_bad'] += 1
        current = {'ns': ns, 'setpoint': data[6], 'active': bool(data[7] & 128),
                   'mode': (data[7] >> 5) & 3, 'counter': data[7] & 15, 'hex': data.hex()}
        if valid and previous is not None and 0 < ns - previous['ns'] <= 250_000_000:
            if (current['active'] and previous['active'] and current['mode'] == previous['mode'] == 1
                    and 40 <= current['setpoint'] <= 200 and 40 <= previous['setpoint'] <= 200
                    and current['counter'] != previous['counter'] and current['setpoint'] != previous['setpoint']):
                changes.append({'ns': ns, 'from_kph': previous['setpoint'], 'to_kph': current['setpoint'],
                                'delta_kph': current['setpoint'] - previous['setpoint'],
                                'before_hex': previous['hex'], 'after_hex': current['hex']})
        previous = current if valid else None
    return changes, dict(stats)


def change_groups(changes):
    """Avoid counting repeated changes of a held input as independent presses.

    These are same-direction change groups, NOT identified physical presses.
    """
    groups = []
    for row in changes:
        sign = 1 if row['delta_kph'] > 0 else -1
        if groups and groups[-1]['sign'] == sign and 0 < row['ns'] - groups[-1]['last_ns'] <= 1_000_000_000:
            groups[-1]['last_ns'] = row['ns']
            groups[-1]['changes'] += 1
            groups[-1]['to_kph'] = row['to_kph']
        else:
            groups.append({'ns': row['ns'], 'last_ns': row['ns'], 'sign': sign, 'changes': 1,
                           'from_kph': row['from_kph'], 'to_kph': row['to_kph']})
    return groups


def hit_latencies(edges, events, window_ns=250_000_000):
    """Latest preceding edge, excluding future observations."""
    indices = np.searchsorted(edges, events, side='right') - 1
    ages = np.full(len(events), -1, dtype=np.int64)
    present = indices >= 0
    ages[present] = events[present].astype(np.int64) - edges[indices[present]].astype(np.int64)
    matched = (ages >= 0) & (ages <= window_ns)
    return matched, ages


def rank_bits(streams, groups):
    if not groups:
        return []
    events = np.array([g['ns'] for g in groups], dtype=np.uint64)
    signs = np.array([g['sign'] for g in groups])
    ranking = []
    for (address, bus, dlc), (times, values) in sorted(streams.items()):
        if len(times) < 2:
            continue
        # Gaps do not establish the moment of a bit transition.
        continuous = (times[1:] > times[:-1]) & (times[1:] - times[:-1] <= 250_000_000)
        duration = (int(times[-1]) - int(times[0])) / 1e9
        eligible = (events >= times[0] + 5_250_000_000) & (events <= times[-1])
        selected, directions = events[eligible], signs[eligible]
        if len(selected) < 3:
            continue
        changed = values[1:] ^ values[:-1]
        for bit in range(dlc * 8):
            mask = np.uint64(1 << bit)
            any_change = ((changed & mask) != 0) & continuous
            if not np.any(any_change):
                continue
            for polarity in ('rise', 'fall'):
                selected_edges = any_change & (((values[1:] & mask) != 0) if polarity == 'rise' else ((values[1:] & mask) == 0))
                edges = times[1:][selected_edges]
                rate = len(edges) / max(duration, 1e-9)
                if not len(edges) or rate > 5:
                    continue  # Fast clocks/counters are not useful button candidates.
                hits, ages = hit_latencies(edges, selected)
                # Nearby negative control, not a p-value or independent trial.
                null_hits, _ = hit_latencies(edges, selected - 5_000_000_000)
                for direction in (1, -1):
                    wanted = directions == direction
                    other = directions == -direction
                    count = int(wanted.sum())
                    support = int((hits & wanted).sum())
                    if count < 2 or support < 2:
                        continue
                    hit_rate = support / count
                    null_rate = float(null_hits[wanted].mean())
                    other_rate = float(hits[other].mean()) if other.any() else None
                    score = hit_rate - max(null_rate, other_rate or 0.)
                    ranking.append({'address': f'0x{address:X}', 'bus': bus, 'dlc': dlc, 'bit_lsb': bit,
                                    'polarity': polarity, 'direction': 'plus' if direction == 1 else 'minus',
                                    'events': count, 'hits': support, 'hit_rate': hit_rate,
                                    'null_hit_rate_5s_earlier': null_rate, 'opposite_direction_hit_rate': other_rate,
                                    'edge_rate_hz': rate, 'score': score,
                                    'median_precedence_ms': float(np.median(ages[hits & wanted]) / 1e6),
                                    'matched_event_ns': [int(t) for t in selected[hits & wanted]],
                                    'known_setpoint_output': address in (0x50E, 0x452), 'validated_button': False})
    return sorted(ranking, key=lambda r: (-r['score'], -r['hits'], r['address'], r['bit_lsb']))


def collect(paths, log):
    import capnp
    import zstandard
    streams = defaultdict(lambda: (array('Q'), array('Q')))
    sources, tails = [], []
    counts = Counter()
    for path in paths:
        compressed = path.read_bytes()
        sources.append({'path': str(path), 'sha256': hashlib.sha256(compressed).hexdigest()})
        with zstandard.ZstdDecompressor().stream_reader(compressed) as reader:
            raw = reader.read()
        try:
            for event in log.Event.read_multiple_bytes(raw):
                if event.which() != 'can':
                    continue
                if not event.valid:
                    counts['invalid_can_envelopes'] += 1
                    continue
                ns = int(event.logMonoTime)
                for frame in event.can:
                    bus, address, data = int(frame.src), int(frame.address), bytes(frame.dat)
                    if bus not in (0, 1, 2) or not 1 <= len(data) <= 8:
                        counts['excluded_echo_error_or_nonclassic_frame'] += 1
                        continue
                    times, values = streams[(address, bus, len(data))]
                    times.append(ns)
                    values.append(int.from_bytes(data, 'little'))
                    counts['physical_rx_frames'] += 1
        except capnp.KjException as exc:
            tails.append({'path': str(path), 'error': str(exc).splitlines()[0]})
        print(path.parent.name, flush=True)
    return sorted_streams(streams), sources, tails, dict(counts)


def sorted_streams(streams):
    result = {}
    for key, (times, values) in streams.items():
        times, values = np.asarray(times, dtype=np.uint64), np.asarray(values, dtype=np.uint64)
        order = np.argsort(times, kind='stable')
        result[key] = times[order], values[order]
    return result


def collect_jsonl(path):
    """Read original ESP32 RX records, not inferred replay button labels.

    Use the common host timestamp: the two ESP32 source clocks need not agree.
    Bus numbers in this adapter are local labels, not comma bus assignments.
    """
    streams = defaultdict(lambda: (array('Q'), array('Q')))
    counts, buses, markers = Counter(), {}, []
    digest = hashlib.sha256()
    with path.open('rb') as source:
        for line_number, line in enumerate(source, 1):
            digest.update(line)
            if not line.strip():
                continue
            row = json.loads(line)
            if row.get('type') == 'marker':
                markers.append({k: row.get(k) for k in ('timestamp_us', 'name', 'note')})
            if row.get('type') != 'can_frame':
                continue
            if row.get('direction') != 'rx' or row.get('extended') is not False:
                counts['excluded_not_standard_rx'] += 1
                continue
            data = bytes.fromhex(row['data_hex'])
            address, ns = int(row['arbitration_id']), int(row['timestamp_us']) * 1000
            if not 1 <= len(data) <= 8 or not 0 <= address <= 0x7ff or ns < 0:
                raise ValueError(f'{path}:{line_number}: invalid classic CAN record')
            label = row.get('bus')
            if not label:
                counts['excluded_unknown_bus'] += 1
                continue
            bus = buses.setdefault(str(label), len(buses))
            times, values = streams[(address, bus, len(data))]
            times.append(ns)
            values.append(int.from_bytes(data, 'little'))
            counts['physical_rx_frames'] += 1
    sources = [{'path': str(path), 'sha256': digest.hexdigest()}]
    metadata = {'jsonl_bus_labels': buses, 'timestamp_basis': 'host_timestamp_us', 'markers': markers}
    return sorted_streams(streams), sources, [], dict(counts), metadata


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--schema', type=Path, help='Cereal schema checkout; required for rlogs')
    inputs = parser.add_mutually_exclusive_group(required=True)
    inputs.add_argument('--logs', type=Path, nargs='+', help='Full rlogs from ONE route')
    inputs.add_argument('--jsonl', type=Path, help='ONE original ESP32 learning session')
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    metadata = {'timestamp_basis': 'logMonoTime'}
    if args.jsonl:
        route = args.jsonl.stem
        streams, sources, tails, counts, metadata = collect_jsonl(args.jsonl)
    else:
        if args.schema is None:
            parser.error('--schema is required for rlogs')
        routes = {p.parent.name.rsplit('--', 1)[0] for p in args.logs}
        if len(routes) != 1 or len(set(args.logs)) != len(args.logs):
            parser.error('Use unique full rlogs from one route, without mixing monotonic clocks')
        if any(p.name != 'rlog.zst' or not p.is_file() for p in args.logs):
            parser.error('Expected existing full rlog.zst files')
        paths = sorted(args.logs, key=lambda p: int(p.parent.name.rsplit('--', 1)[1]))
        route = next(iter(routes))
        sys.path.insert(0, str(args.schema.resolve()))
        from cereal import log
        streams, sources, tails, counts = collect(paths, log)
    args.output.mkdir(parents=True, exist_ok=True)
    # Compact local cache for independently examining correlations/checksums.
    cache = {f'{a:x}_{b}_{dlc}_{kind}': rows[i] for (a, b, dlc), rows in streams.items()
             for i, kind in enumerate(('ns', 'data'))}
    np.savez_compressed(args.output / 'physical-can.npz', **cache)
    changes, checksums = {}, {}
    for (address, bus, dlc), rows in streams.items():
        if address == 0x50E and dlc == 8:
            changes[str(bus)], checksums[str(bus)] = setpoint_changes(*rows)
    source_bus = '2' if not args.jsonl and '2' in changes else max(checksums, key=lambda b: checksums[b]['frames'], default='0')
    groups = change_groups(changes.get(source_bus, []))
    ranking = rank_bits(streams, groups)
    inventory = [{'address': f'0x{a:X}', 'bus': b, 'dlc': dlc, 'frames': len(rows[0])}
                 for (a, b, dlc), rows in sorted(streams.items())]
    report = {'route': route, 'source_logs': sources, 'partial_tails': tails, **metadata,
              'counts': counts, 'inventory': inventory, 'stock_parity': checksums,
              'setpoint_events_by_bus': changes, 'reference_setpoint_bus': int(source_bus),
              'change_groups': groups, 'ranked_bit_correlations': ranking,
              'method': 'preceding_bit_edges_250ms_vs_same_events_shifted_5s_earlier',
              'ground_truth_button_labels': False, 'can_frames_emitted': 0}
    (args.output / 'report.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps({'counts': counts, 'stock_parity': checksums, 'change_groups': groups,
                      'top_correlations': ranking[:8]}, indent=2))


if __name__ == '__main__':
    main()
