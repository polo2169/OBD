#!/usr/bin/env python3
"""Offline distance analysis, not an RVV controller or a vehicle calibration.

Assumes a lead at constant speed and a specified constant ego deceleration
after a specified delay. Reads local audit JSON only; no CAN/device imports,
wire messages, engagement decisions or deployable control policy.
"""
from __future__ import annotations

import argparse
from collections import Counter
import csv
import json
import math
from pathlib import Path


def closing_margin(*, distance_m, ego_kph, lead_kph, deceleration_ms2, delay_s, buffer_m=10.):
    values = (distance_m, ego_kph, lead_kph, deceleration_ms2, delay_s, buffer_m)
    if not all(isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v) for v in values):
        raise ValueError('Inputs must be finite numbers')
    if distance_m <= 0 or min(ego_kph, lead_kph, deceleration_ms2, delay_s, buffer_m) < 0:
        raise ValueError('Positive distance and nonnegative speeds, deceleration, delay and buffer required')
    closing = max(0., (ego_kph - lead_kph) / 3.6)
    delay_loss = closing * delay_s
    available_after_delay = distance_m - buffer_m - delay_loss
    # None means no finite solution under the stated model, not zero demand.
    needed_decel = (0. if closing == 0 else
                    closing ** 2 / (2. * available_after_delay) if available_after_delay > 0 else None)
    match_loss = (0. if closing == 0 else
                  delay_loss + closing ** 2 / (2. * deceleration_ms2) if deceleration_ms2 > 0 else None)
    match_time = (0. if closing == 0 else
                  delay_s + closing / deceleration_ms2 if deceleration_ms2 > 0 else None)
    required_distance = None if match_loss is None else buffer_m + match_loss
    return {
        'distance_m': distance_m, 'ego_kph': ego_kph, 'lead_kph': lead_kph,
        'closing_kph': closing * 3.6, 'assumed_deceleration_ms2': deceleration_ms2,
        'assumed_delay_s': delay_s, 'requested_buffer_m': buffer_m,
        'headway_s': distance_m / (ego_kph / 3.6) if ego_kph > 0 else None,
        'constant_speed_ttc_s': distance_m / closing if closing > 0 else None,
        'distance_consumed_until_speed_match_m': match_loss,
        'time_until_speed_match_s': match_time,
        'required_start_distance_m': required_distance,
        'margin_to_requested_buffer_m': None if required_distance is None else distance_m - required_distance,
        'required_constant_deceleration_ms2': needed_decel,
    }


def recorded_observations(folder, *, deceleration_ms2, delay_s):
    rows, files = [], []
    counts = Counter()
    for path in sorted(folder.glob('*.json')):
        data = json.loads(path.read_text())
        if 'following' not in data:
            continue
        if not data.get('parse_complete') or data.get('errors'):
            raise ValueError(f'Incomplete audit: {path}')
        files.append({'audit': str(path), 'rlog_sha256': data['sha256']})
        for sample in data['following']:
            lead = sample['lead']
            if not sample['stock_rvv_active'] or not lead['present'] or not lead['valid']:
                continue
            counts['active_cruise_with_present_lead_log_samples'] += 1
            if not math.isfinite(lead['probability']) or not .75 <= lead['probability'] <= 1:
                continue
            try:
                margin = closing_margin(distance_m=lead['distance_m'], ego_kph=sample['speed_kph'],
                                        lead_kph=lead['speed_ms'] * 3.6,
                                        deceleration_ms2=deceleration_ms2, delay_s=delay_s)
            except ValueError:
                counts['invalid_geometry_samples'] += 1
                continue
            counts['confident_present_lead_log_samples'] += 1
            if lead['distance_m'] <= 50:
                counts['confident_lead_within_50m_log_samples'] += 1
                if 0 < margin['closing_kph'] <= 5:
                    counts['within_50m_closing_up_to_5kph_log_samples'] += 1
            rows.append({'audit': str(path), 'rlog_sha256': data['sha256'],
                         'log_ns': sample['log_ns'], 'recorded_reason': sample['reason'],
                         'recorded_proposed_target_kph': sample['target_kph'],
                         'recorded_stock_setpoint_kph': sample['stock_setpoint_kph'], **margin})
    # Monotonic timestamps reset at reboot; never merge different routes
    # into a single apparent timeline by sorting timestamps alone.
    rows.sort(key=lambda row: (row['audit'], row['log_ns']))
    return {'source_files': files, 'log_sample_counts': dict(counts), 'observations': rows}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--audit-directory', type=Path)
    parser.add_argument('--assumed-deceleration', type=float, default=.30)
    parser.add_argument('--assumed-delay', type=float, default=1.)
    args = parser.parse_args()
    scenarios = [closing_margin(distance_m=distance, ego_kph=130., lead_kph=130. - difference,
                                deceleration_ms2=args.assumed_deceleration, delay_s=args.assumed_delay)
                 for distance in (50., 10.) for difference in (0., 5., 10., 20., 40.)]
    report = {
        'purpose': 'Offline sensitivity analysis; no vehicle output or control authorization',
        'assumptions': ['Lead speed stays constant; sudden braking and cut-ins are excluded.',
                        'Ego deceleration begins after the specified delay and remains constant.',
                        '0.30 m/s^2 is the current unvalidated code prior, not a measured braking guarantee.',
                        'The chosen delay is hypothetical; perception, setpoint ramp and engine delays are not measured.',
                        'A positive calculated margin does not establish real-world safety.',
                        'Recorded trajectories are observations, not counterfactual closed-loop replay.',
                        'Logged sample counts are not episode counts or durations.'],
        'scenarios': scenarios,
    }
    if args.audit_directory:
        report['recorded'] = recorded_observations(args.audit_directory,
                                                   deceleration_ms2=args.assumed_deceleration,
                                                   delay_s=args.assumed_delay)
    args.output.mkdir(parents=True, exist_ok=True)
    (args.output / 'following-margin.json').write_text(json.dumps(report, indent=2, allow_nan=False) + '\n')
    with (args.output / 'scenarios.csv').open('w', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=list(scenarios[0]))
        writer.writeheader()
        writer.writerows(scenarios)
    print('Offline results:', args.output)
    for row in scenarios:
        print(f"distance={row['distance_m']:g}m, closing={row['closing_kph']:g}km/h, "
              f"required distance={row['required_start_distance_m']!r}m")


if __name__ == '__main__':
    main()
