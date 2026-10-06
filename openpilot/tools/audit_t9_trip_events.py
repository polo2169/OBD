#!/usr/bin/env python3
"""Export recorded T9 transitions and EPS context; never connects to CAN.

Run against closed rlogs. Timestamps are monotonic, not file modification
times. Exported host commands are requests, not proof of applied EPS torque.
"""
import argparse
from bisect import bisect_right
from collections import Counter
import gzip
import hashlib
import json
from pathlib import Path
import sys


def past(rows, timestamps, now, max_age):
    i = bisect_right(timestamps, now) - 1
    if i < 0 or now - rows[i]['ns'] > max_age:
        return None
    return rows[i] if rows[i].get('valid', True) else None


def steering(data):
    if len(data) != 8:
        return None
    raw = (data[3] << 3) | (data[4] >> 5)
    return {'state': (data[4] >> 2) & 7, 'factor': data[5] >> 1,
            'torque_raw': raw - 2048 if raw & 1024 else raw, 'hex': data.hex()}


def audit(path, log):
    import capnp
    import zstandard
    compressed = path.read_bytes()
    with zstandard.ZstdDecompressor().stream_reader(compressed) as stream:
        raw = stream.read()
    counts, alerts, tx, params, following, rvv, lateral = (Counter() for _ in range(7))
    drivers, eps, commands, car, decisions, following_changes, panda = ([] for _ in range(7))
    speeds, boot_ids, errors, host_rejects = [], set(), [], []
    first = last = None
    try:
        for e in log.Event.read_multiple_bytes(raw):
            now, kind = int(e.logMonoTime), e.which()
            counts[kind] += 1
            if kind == 'initData':
                boot_ids.add(str(e.initData.bootlogId))
            elif kind == 'carParams':
                p = e.carParams
                params[str((p.carFingerprint, p.dashcamOnly, p.openpilotLongitudinalControl))] += 1
            elif kind == 'can':
                for frame in e.can:
                    address, bus, data = int(frame.address), int(frame.src), bytes(frame.dat)
                    if address == 0x2F5 and bus == 0:
                        valid = bool(e.valid and len(data) == 7 and sum((b >> 4) + (b & 15) for b in data) % 16 == 11)
                        drivers.append({'ns': now, 'valid': valid,
                                        'raw': int.from_bytes(data[1:2], 'big', signed=True) if valid else None})
                    elif address == 0x495 and bus == 0:
                        valid = bool(e.valid and len(data) == 4)
                        eps.append({'ns': now, 'valid': valid, 'state': (data[2] >> 2) & 7 if valid else None,
                                    'activity_candidate': bool(data[2] & 2) if valid else None, 'hex': data.hex()})
                    elif address == 0x3F2 and bus == 192:
                        host_rejects.append({'ns': now, 'frame': steering(data)})
            elif kind == 'sendcan':
                for frame in e.sendcan:
                    tx[f'{frame.address:#x}/bus{frame.src}'] += 1
                    if frame.address == 0x3F2 and frame.src == 0:
                        decoded = steering(bytes(frame.dat))
                        if decoded is not None:
                            commands.append({'ns': now, 'valid': bool(e.valid), **decoded})
            elif kind == 'carControl':
                counts['valid_lat_active'] += bool(e.valid and e.carControl.latActive)
                counts['valid_long_active'] += bool(e.valid and e.carControl.longActive)
            elif kind == 'carState':
                s = e.carState
                first = now if first is None else min(first, now)
                last = now if last is None else max(last, now)
                speeds.append(float(s.vEgoRaw) * 3.6)
                car.append({'ns': now, 'valid': bool(e.valid and s.canValid and not s.canTimeout),
                            'speed_kph': speeds[-1], 'rvv_active': bool(s.cruiseState.enabled),
                            'setpoint_kph': float(s.cruiseState.speed) * 3.6,
                            'brake': bool(s.brakePressed), 'gas': bool(s.gasPressed)})
                counts['stock_rvv_active'] += bool(s.cruiseState.enabled)
                counts['stock_rvv_active_40_to_67kph'] += bool(s.cruiseState.enabled and 40 <= speeds[-1] < 67.1)
            elif kind == 'pandaStates':
                for p in e.pandaStates:
                    panda.append({'ns': now, 'tx_blocked': int(p.safetyTxBlocked), 'spi_errors': int(p.spiErrorCount),
                                  'controls_allowed': bool(p.controlsAllowed), 'model': str(p.safetyModel),
                                  'param': int(p.safetyParam)})
            elif kind == 'radarState':
                lead = e.radarState.leadOne
                counts['lead_present'] += bool(e.valid and lead.status)
                counts['lead_confident'] += bool(e.valid and lead.status and lead.modelProb >= .75)
            elif kind == 'selfdriveState':
                s = e.selfdriveState
                if s.alertType:
                    alerts[str((s.alertType, s.alertText1, s.alertText2))] += 1
            elif kind == 'logMessage':
                try:
                    outer = json.loads(str(e.logMessage))
                    message = outer.get('msg', outer.get('msg$s', ''))
                    if not isinstance(message, str):
                        continue
                    for prefix, bucket in (('psa_t9_lateral ', lateral), ('psa_t9_rvv_following ', following), ('psa_t9_rvv ', rvv)):
                        if not message.startswith(prefix):
                            continue
                        d = json.loads(message[len(prefix):])
                        bucket[d.get('reason', 'unknown')] += 1
                        if prefix == 'psa_t9_lateral ':
                            ns = d.get('mono_ns')
                            if type(ns) is int and 0 < ns <= now and now - ns <= 1_000_000_000:
                                decisions.append(d)
                            else:
                                counts['invalid_decision_timestamp'] += 1
                        elif prefix == 'psa_t9_rvv_following ':
                            following_changes.append(d)
                except (ValueError, TypeError, AttributeError):
                    counts['unparsed_log_message'] += 1
    except capnp.KjException as exc:
        errors.append(str(exc).splitlines()[0])
    for rows in (drivers, eps, commands, car, panda):
        rows.sort(key=lambda r: r['ns'])
    decisions.sort(key=lambda r: r['mono_ns'])
    # Pair only observations at/before EPS RX, within explicit age bounds.
    contexts = [(label, rows, [r['ns'] for r in rows], age)
                for label, rows, age in (('driver', drivers, 30_000_000), ('car', car, 150_000_000),
                                        ('host_command', commands, 150_000_000))]
    for row in eps:
        for label, rows, timestamps, max_age in contexts:
            row[label] = past(rows, timestamps, row['ns'], max_age)
    return {'source': str(path), 'compressed_sha256': hashlib.sha256(compressed).hexdigest(),
            'bytes': len(compressed), 'parse_complete': not errors, 'errors': errors, 'boot_ids': sorted(boot_ids),
            'first_car_ns': first, 'last_car_ns': last, 'counts': counts,
            'speed_range_kph': [min(speeds), max(speeds)] if speeds else None,
            'car_params': params, 'host_sendcan': tx, 'alerts': alerts,
            'lateral_reasons': lateral, 'following_reasons': following, 'rvv_reasons': rvv,
            'lateral_decisions': decisions, 'following_decisions': following_changes,
            'eps_samples': eps, 'panda_samples': panda, 'host_tx_rejects': host_rejects}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--schema', type=Path, required=True)
    parser.add_argument('--log-root', type=Path, required=True)
    parser.add_argument('--minimum-route-hex', default='1d')
    args = parser.parse_args()
    sys.path.insert(0, str(args.schema.resolve()))
    from cereal import log
    minimum = int(args.minimum_route_hex, 16)
    paths = []
    for path in args.log_root.glob('*/rlog.zst'):
        try:
            route, _, segment = path.parent.name.split('--')
            number, segment = int(route, 16), int(segment)
        except ValueError:
            continue
        if number >= minimum:
            paths.append((number, segment, path))
    # Streaming gzip JSONL avoids retaining a whole day's decoded logs in RAM.
    with gzip.GzipFile(fileobj=sys.stdout.buffer, mode='wb') as output:
        for _, _, path in sorted(paths):
            result = audit(path, log)
            output.write((json.dumps(result, separators=(',', ':')) + '\n').encode())
            print(f'{path.parent.name}: {len(result["lateral_decisions"])} decisions, '
                  f'{len(result["eps_samples"])} EPS samples, complete={result["parse_complete"]}', file=sys.stderr, flush=True)


if __name__ == '__main__':
    main()
