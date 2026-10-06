#!/usr/bin/env python3
"""Measure recorded driver effort around T9 lateral cuts, without vehicle access.

Only physical CAN0 input is used. EPS activity is a candidate indicator, not
proof of hands presence or a label of driver intent. No threshold is selected.
"""
from __future__ import annotations

import argparse
from bisect import bisect_right
from collections import Counter
import csv
import hashlib
import json
from pathlib import Path
import sys


DRIVER_MAX_AGE_NS = 30_000_000
EPS_MAX_AGE_NS = 150_000_000
WINDOW_NS = 500_000_000
CURRENT_LIMIT_RAW = 5  # Legacy capture default; --observed-limit selects a later recorded version.


def driver_value(data: bytes) -> int | None:
    if len(data) != 7 or sum((b >> 4) + (b & 15) for b in data) % 16 != 11:
        return None
    return int.from_bytes(data[1:2], 'big', signed=True)


def recent(rows: list[dict], timestamps: list[int], now: int, maximum_age: int) -> dict | None:
    index = bisect_right(timestamps, now) - 1
    if index < 0 or now - timestamps[index] > maximum_age or not rows[index]['valid']:
        return None
    return rows[index]


def excursions(rows: list[dict], observed_limit_raw: int = CURRENT_LIMIT_RAW) -> list[dict]:
    """Bracket threshold excursions with observed release samples, not guesses.

    Missing samples, bad checksums, counter discontinuities and segment edges
    leave the duration upper bound unknown. The lower bound spans only a
    contiguous observed run; it cannot establish what happened between frames.
    """
    if type(observed_limit_raw) is not int or not 1 <= observed_limit_raw <= 127:
        raise ValueError('Recorded limit must be an integer in 1..127 raw')
    result, run, previous = [], None, None
    for row in rows:
        contiguous = (previous is not None and row['valid'] and previous['valid']
                      and 0 < row['ns'] - previous['ns'] <= DRIVER_MAX_AGE_NS
                      and (row['counter'] - previous['counter']) % 16 == 1)
        if not contiguous:
            run = None
        above = row['valid'] and abs(row['driver_raw']) > observed_limit_raw
        if above:
            if run is None:
                run = {'first_ns': row['ns'], 'last_ns': row['ns'], 'samples': 0,
                       'before_ns': previous['ns'] if contiguous else None,
                       'after_ns': None, 'peak_abs_raw': 0}
                result.append(run)
            run['last_ns'] = row['ns']
            run['samples'] += 1
            run['peak_abs_raw'] = max(run['peak_abs_raw'], abs(row['driver_raw']))
        elif run is not None:
            run['after_ns'] = row['ns']
            run = None
        previous = row
    for run in result:
        run['observed_span_ms'] = (run['last_ns'] - run['first_ns']) / 1e6
        run['duration_upper_bound_ms'] = ((run['after_ns'] - run['before_ns']) / 1e6
                                        if run['before_ns'] is not None and run['after_ns'] is not None else None)
    return result


def compare_limits(rows: list[dict], now: int, limits: tuple[int, ...]) -> dict:
    """Compare numeric threshold crossings only; never predict engagement.

    Continuing assistance would change the recorded vehicle trajectory. In
    particular, absence of a crossing is not permission to maintain torque.
    Stop extending an observation through missing/invalid CAN samples.
    """
    timestamps = [r['ns'] for r in rows]
    index = bisect_right(timestamps, now) - 1
    result = {str(limit): {'first_over_ns': None, 'delay_from_recorded_cut_ms': None}
              for limit in limits}
    initial = recent(rows, timestamps, now, DRIVER_MAX_AGE_NS)
    if initial is None:
        return {'window_complete': False, 'last_observed_ns': None, 'limits': result}
    previous = None
    last_observed, complete = None, False
    for row in rows[index:]:
        if not row['valid']:
            break
        if previous is not None and not (
            0 < row['ns'] - previous['ns'] <= DRIVER_MAX_AGE_NS
            and (row['counter'] - previous['counter']) % 16 == 1
        ):
            break
        if row['ns'] > now + WINDOW_NS:
            complete = True
            break
        last_observed = row['ns']
        for limit in limits:
            entry = result[str(limit)]
            if abs(row['driver_raw']) > limit and entry['first_over_ns'] is None:
                entry['first_over_ns'] = row['ns']
                entry['delay_from_recorded_cut_ms'] = max(0, row['ns'] - now) / 1e6
        previous = row
        complete = row['ns'] == now + WINDOW_NS
    return {'window_complete': complete, 'last_observed_ns': last_observed, 'limits': result}


def analyze(records: list[tuple[int, str, dict]], comparison_limits: tuple[int, ...] = (5, 10),
            observed_limit_raw: int = CURRENT_LIMIT_RAW) -> tuple[dict, list[dict]]:
    if not comparison_limits or any(type(x) is not int or not 1 <= x <= 127 for x in comparison_limits):
        raise ValueError('Comparison limits must be integers in 1..127 raw')
    if type(observed_limit_raw) is not int or not 1 <= observed_limit_raw <= 127:
        raise ValueError('Recorded limit must be an integer in 1..127 raw')
    records.sort(key=lambda r: r[0])
    counts = Counter()
    drivers, eps_rows, cuts = [], [], []
    last_reason, last_phase = None, None
    for now, kind, data in records:
        if now <= 0:
            counts['invalid_timestamp'] += 1
            continue
        if kind == 'driver':
            drivers.append({'ns': now, **data})
            counts['driver_valid' if data['valid'] else 'driver_invalid'] += 1
        elif kind == 'eps':
            eps_rows.append({'ns': now, **data})
            counts['eps_valid' if data['valid'] else 'eps_invalid'] += 1
        elif kind == 'lateral':
            if data.get('reason') == 'driver_override' and last_reason != 'driver_override':
                cuts.append({'ns': now, 'previous_phase': last_phase, 'snapshot': data})
            last_reason, last_phase = data.get('reason'), data.get('phase')

    driver_ns = [r['ns'] for r in drivers]
    eps_ns = [r['ns'] for r in eps_rows]
    for eps in eps_rows:
        if not eps['valid']:
            continue
        driver = recent(drivers, driver_ns, eps['ns'], DRIVER_MAX_AGE_NS)
        if driver is None:
            counts['eps_without_recent_driver'] += 1
        else:
            label = f"activity_{str(eps['activity_candidate']).lower()}"
            counts[label + '_paired'] += 1
            if abs(driver['driver_raw']) > observed_limit_raw:
                counts[label + '_over_current_limit'] += 1

    runs = excursions(drivers, observed_limit_raw)
    for cut in cuts:
        now = cut['ns']
        driver = recent(drivers, driver_ns, now, DRIVER_MAX_AGE_NS)
        eps = recent(eps_rows, eps_ns, now, EPS_MAX_AGE_NS)
        cut['physical_driver_at_or_before_cut'] = driver
        cut['physical_eps_at_or_before_cut'] = eps
        # A snapshot can lag the physical sample slightly; preserve both.
        cut['excursion_at_or_before_cut'] = next((r for r in runs if driver is not None
                                                and r['first_ns'] <= driver['ns'] <= r['last_ns']), None)
        window = [r for r in drivers if now - WINDOW_NS <= r['ns'] <= now + WINDOW_NS]
        cut['window_driver_samples'] = window
        cut['window_eps_samples'] = [r for r in eps_rows if now - WINDOW_NS <= r['ns'] <= now + WINDOW_NS]
        cut['driver_intent'] = 'unlabelled'
        cut['threshold_comparison'] = compare_limits(drivers, now, comparison_limits)

    csv_rows = []
    for driver in drivers:
        eps = recent(eps_rows, eps_ns, driver['ns'], EPS_MAX_AGE_NS)
        csv_rows.append({**driver, 'eps_state': eps['state'] if eps else None,
                         'eps_activity_candidate': eps['activity_candidate'] if eps else None,
                         'eps_age_ms': (driver['ns'] - eps['ns']) / 1e6 if eps else None})
    return {'counts': dict(counts), 'driver_cuts': cuts, 'comparison_limits_raw': list(comparison_limits),
            'observed_limit_raw': observed_limit_raw}, csv_rows


def read_log(path: Path, schema: Path) -> tuple[list, dict]:
    import capnp
    import zstandard
    sys.path.insert(0, str(schema.resolve()))
    from cereal import log

    records, errors, boots = [], [], set()
    with path.open('rb') as stream:
        raw = zstandard.ZstdDecompressor().stream_reader(stream).read()
    try:
        for event in log.Event.read_multiple_bytes(raw):
            now, kind = int(event.logMonoTime), event.which()
            if kind == 'initData':
                boots.add(str(event.initData.bootlogId))
            elif kind == 'can':
                for frame in event.can:
                    if frame.src != 0 or frame.address not in (0x2F5, 0x495):
                        continue
                    data = bytes(frame.dat)
                    if frame.address == 0x2F5:
                        value = driver_value(data) if event.valid else None
                        records.append((now, 'driver', {'valid': value is not None,
                            'driver_raw': value, 'counter': data[0] & 15 if data else None}))
                    else:
                        valid = bool(event.valid and len(data) == 4)
                        records.append((now, 'eps', {'valid': valid,
                            'state': (data[2] >> 2) & 7 if valid else None,
                            'activity_candidate': bool(data[2] & 2) if valid else None}))
            elif kind == 'logMessage':
                try:
                    outer = json.loads(str(event.logMessage))
                    message = outer.get('msg', outer.get('msg$s', ''))
                    if not isinstance(message, str) or not message.startswith('psa_t9_lateral '):
                        continue
                    snapshot = json.loads(message.removeprefix('psa_t9_lateral '))
                    timestamp = snapshot.get('mono_ns')
                    # Use decision time, not delayed log publication time.
                    if type(timestamp) is not int or not 0 < timestamp <= now or now - timestamp > 1_000_000_000:
                        errors.append('Lateral snapshot without a usable decision timestamp')
                        continue
                    records.append((timestamp, 'lateral', snapshot))
                except (ValueError, TypeError, AttributeError):
                    continue
    except capnp.KjException as exc:
        errors.append(str(exc).splitlines()[0])
    if len(boots) > 1:
        raise ValueError('A segment cannot combine different boot clocks')
    return records, {'source': str(path), 'sha256': hashlib.sha256(path.read_bytes()).hexdigest(),
                     'boot_ids': sorted(boots), 'parse_complete': not errors, 'errors': errors}


def write_markdown(report: dict, path: Path) -> None:
    limit = report['driver_limit_raw_observed_in_current_port']
    lines = ['# Effort conducteur autour des coupures T9', '',
             'Analyse hors ligne. Les valeurs restent en unités brutes ; intention du conducteur inconnue.', '',
             f'| Segment | Temps de décision (s) | Effort journalisé | Échantillons consécutifs au-dessus de ±{limit} | Étendue observée (ms) | Borne supérieure (ms) |',
             '|---|---:|---:|---:|---:|---:|']
    for segment in report['segments']:
        for cut in segment['driver_cuts']:
            run = cut['excursion_at_or_before_cut'] or {}
            span = run.get('observed_span_ms')
            upper = run.get('duration_upper_bound_ms')
            lines.append(f"| {Path(segment['source']).parent.name} | {cut['ns'] / 1e9:.6f} | "
                         f"{cut['snapshot'].get('driver_torque_raw')} | {run.get('samples', 'inconnu')} | "
                         f"{span if span is not None else 'inconnue'} | {upper if upper is not None else 'inconnue'} |")
    lines += ['', 'Une étendue nulle signifie un seul échantillon observé, pas une durée physique nulle.',
              'La borne supérieure utilise les deux observations sous le seuil qui encadrent la séquence.',
              'Un pic court ne prouve pas un parasite ; aucune nouvelle valeur de coupure n’est proposée.', '',
              'Les empreintes des rlogs, limites de fraîcheur, signaux EPS et fenêtres brutes sont dans `report.json`.',
              'Les CSV contiennent les valeurs physiques CAN0. Les segments sont analysés séparément.']
    lines += ['', '## Comparaison des seuils sur les 500 ms suivant la coupure', '',
              'Les autres causes de coupure ne sont pas rejouées ici. La trajectoire enregistrée reste fixe.', '',
              '| Segment | Coupure (s) | Seuil comparé | Premier dépassement après la coupure (ms) | Fenêtre continue complète |',
              '|---|---:|---:|---:|---|']
    for segment in report['segments']:
        for cut in segment['driver_cuts']:
            comparison = cut['threshold_comparison']
            for limit, entry in comparison['limits'].items():
                delay = entry['delay_from_recorded_cut_ms']
                label = f'{delay:.2f}' if delay is not None else 'non observé'
                complete = 'oui' if comparison['window_complete'] else 'non'
                lines.append(f"| {Path(segment['source']).parent.name} | {cut['ns'] / 1e9:.6f} | ±{limit} | {label} | {complete} |")
    lines += ['', 'Cette comparaison ne calibre pas le couple physique ni la capacité de reprise du conducteur.',
              'Elle ne modifie aucun paramètre, firmware ou autorisation de commande.']
    path.write_text('\n'.join(lines) + '\n')


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--schema', type=Path, required=True, help='Local openpilot checkout containing cereal')
    parser.add_argument('--logs', nargs='+', type=Path, required=True)
    parser.add_argument('--output-dir', type=Path, required=True)
    parser.add_argument('--compare-limits', type=int, nargs='+', default=[5, 10],
                        help='Offline numeric comparisons only, in raw units (default: 5 10)')
    parser.add_argument('--observed-limit', type=int, default=CURRENT_LIMIT_RAW,
                        help='Threshold of the version that recorded these logs; legacy default 5. No vehicle setting is changed.')
    args = parser.parse_args()
    if any(not 1 <= limit <= 127 for limit in args.compare_limits):
        parser.error('Comparison limits must be in 1..127 raw')
    if not 1 <= args.observed_limit <= 127:
        parser.error('Recorded limit must be in 1..127 raw')
    args.output_dir.mkdir(parents=True, exist_ok=True)
    reports = []
    for path in args.logs:
        if path.name != 'rlog.zst' or not path.is_file():
            parser.error('Existing full rlog.zst files are required')
        records, source = read_log(path, args.schema)
        result, rows = analyze(records, tuple(dict.fromkeys(args.compare_limits)), args.observed_limit)
        reports.append(source | result)
        with (args.output_dir / (path.parent.name + '.csv')).open('w') as target:
            writer = csv.DictWriter(target, fieldnames=['ns', 'valid', 'driver_raw', 'counter',
                'eps_state', 'eps_activity_candidate', 'eps_age_ms'])
            writer.writeheader()
            writer.writerows(rows)
        print(path.parent.name, result['counts'], 'cuts', len(result['driver_cuts']))
    report = {'mode': 'offline_observation_only', 'can_frames_emitted': 0,
        'comparison_limits_raw': list(dict.fromkeys(args.compare_limits)),
        'comparison_window_ms': WINDOW_NS / 1e6,
        'driver_limit_raw_observed_in_current_port': args.observed_limit,
        'observed_limit_source': 'Explicit CLI value or legacy default; verify against the recorded release manifest.',
        'driver_max_age_ms': DRIVER_MAX_AGE_NS / 1e6, 'eps_max_age_ms': EPS_MAX_AGE_NS / 1e6,
        'limitations': ['No hands-presence ground truth, driver-intent labels or Nm calibration.',
                       'EPS activity is a candidate signal; no EPS checksum is validated here.',
                       'Each segment is independent; timing uses logger reception, not an ECU clock.',
                       'A short excursion is not proof of noise; no new actuation threshold is inferred.'],
        'segments': reports}
    (args.output_dir / 'report.json').write_text(json.dumps(report, indent=2, allow_nan=False) + '\n')
    write_markdown(report, args.output_dir / 'report.md')


if __name__ == '__main__':
    main()
