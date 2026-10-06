#!/usr/bin/env python3
"""Fit the *recorded factory LKA* response; never opens a device or emits CAN.

Requires extract_t9_lka_response.py outputs. Fits use independent 20 Hz samples,
fixed factor 100, acknowledged EPS, and a two-second engagement warm-up.
"""
import argparse
import csv
import json
from pathlib import Path

import numpy as np

DT = .05
FIELDS = ['t', 'episode', 'torque', 'driver', 'rate', 'can_lat', 'pose_lat', 'roll_lat',
          'roll', 'speed', 'selected', 'active', 'factor', 'eps', 'angle', 'eps_torque']


def runs(mask):
  edges = np.diff(np.r_[False, mask, False].astype(int))
  return list(zip(np.flatnonzero(edges == 1), np.flatnonzero(edges == -1)))


def ols(x, y):
  coef = np.linalg.lstsq(x, y, rcond=None)[0]
  residual = y - x @ coef
  variance = np.sum((y - y.mean()) ** 2)
  return {'coefficients': coef.tolist(), 'rmse': float(np.sqrt(np.mean(residual ** 2))),
          'r_squared': float(1 - np.sum(residual ** 2) / variance) if variance else None}


def torque_tls(torque_raw, lateral_accel, normalization_raw=150.):
  """Exact SVD/spread math of pinned torqued.py, using factory command input.

  Normalization is a coordinate convention, NOT an allowed steering limit.
  This spread-based estimate includes unexplained dynamics, not just friction.
  """
  x = torque_raw / normalization_raw
  points = np.c_[x, np.ones(len(x)), lateral_accel]
  _, _, vh = np.linalg.svd(points, full_matrices=False)
  slope, offset = -vh[-1, :2] / vh[-1, 2]
  if slope <= 0:
    raise ValueError('Expected matching positive command/response conventions')
  spread = (lateral_accel - slope * x) / np.sqrt(1 + slope ** 2)
  friction = float(np.std(spread) * 1.5)
  return {'lat_accel_factor': float(slope), 'offset_ms2': float(offset),
          'normalization_raw': normalization_raw, 'gain_ms2_per_raw': float(slope / normalization_raw),
          'friction_normalized': friction, 'friction_equivalent_raw': friction * normalization_raw}


def load_route(path):
  c = np.load(path / 'can.npz'); p = np.load(path / 'pose.npz')
  cf = {str(k): i for i, k in enumerate(c['fields'])}
  cv = c['values']; pv = p['values']; origin = int(c['ns'][0])
  ct = (c['ns'] - origin) / 1e9
  pt = (p['ns'] - origin) / 1e9
  valid_pose = (pv[:, 4] == 1) & (pv[:, 5] == 1) & (pv[:, 6] >= 0) & (pv[:, 6] < .2)
  pt = pt[valid_pose]; pv = pv[valid_pose]
  order = np.argsort(pt, kind='stable'); pt = pt[order]; pv = pv[order]
  unique = np.r_[np.diff(pt) > 0, True]; pt = pt[unique]; pv = pv[unique]
  t = np.arange(ct[0] + DT, ct[-1] - DT, DT)
  index = np.searchsorted(ct, t, side='right') - 1
  z = cv[index]
  get = lambda field: z[:, cf[field]]
  fresh = (t - ct[index] < .10) & (z[:, cf['command_age_s']:].max(axis=1) < .15)
  active = (get('lka_state') == 4) & (get('eps_state') == 3) & fresh
  episode = np.zeros(len(t), dtype=int); warmup = np.zeros(len(t))
  for number, (a, b) in enumerate(runs(active), 1):
    episode[a:b] = number; warmup[a:b] = t[a:b] - t[a]
  j = np.clip(np.searchsorted(pt, t), 1, len(pt) - 1)
  pose_ok = (t >= pt[0]) & (t <= pt[-1]) & (pt[j] - pt[j-1] < .15)
  speed = get('speed_ms'); driver = get('driver_raw')
  selected = active & (warmup >= 2.) & (get('factor') == 100) & (speed > 15.) & (np.abs(driver) <= 5.) & pose_ok
  yaw_pose = np.interp(t, pt, pv[:, 2]); roll = np.interp(t, pt, pv[:, 0])
  # Empirically opposite coordinate conventions: CAN yaw and calibrated pose.
  can_lat = speed * get('yaw_can_rad_s')
  pose_lat = -speed * yaw_pose
  roll_lat = pose_lat + np.sin(roll) * 9.81
  yaw_mask = pose_ok & fresh & (speed > 15.)
  result = dict(zip(FIELDS, [t, episode, get('torque_raw'), driver, get('rate_deg_s'),
    can_lat, pose_lat, roll_lat, roll, speed, selected, active, get('factor'), get('eps_state'),
    get('angle_deg'), get('eps_torque_raw')]))
  # Lifecycle timing uses the original 100 Hz log clock, not the fit resampling.
  raw_active = (cv[:, cf['lka_state']] == 4) & (cv[:, cf['command_age_s']] < .15)
  episodes = []
  for number, (a, b) in enumerate(runs(raw_active), 1):
    eps_ack = np.flatnonzero(cv[a:b, cf['eps_state']] == 3)
    in_episode = selected & (t >= ct[a]) & (t < (ct[b] if b < len(ct) else ct[-1]))
    episodes.append({'number': number, 'start_s': float(ct[a]),
      'duration_s': float((ct[b] if b < len(ct) else ct[-1]) - ct[a]),
      'eps_ack_delay_s': float(ct[a + eps_ack[0]] - ct[a]) if len(eps_ack) else None,
      'torque_min_raw': float(cv[a:b, cf['torque_raw']].min()),
      'torque_max_raw': float(cv[a:b, cf['torque_raw']].max()),
      'retained_20hz_samples': int(in_episode.sum())})
  meta = {'route': path.name, 'origin_mono_ns': origin, 'duration_s': float(ct[-1]),
          'episodes': episodes, 'factory_active_s': float(sum(e['duration_s'] for e in episodes)),
          'selected_samples_20hz': int(selected.sum()), 'selected_duration_s': float(selected.sum() * DT),
          'can_pose_yaw_correlation': float(np.corrcoef(get('yaw_can_rad_s')[yaw_mask], yaw_pose[yaw_mask])[0, 1]),
          'roll_deg_quantiles_selected': np.degrees(np.quantile(roll[selected], [.05, .5, .95])).tolist(),
          'extraction': json.loads((path / 'extraction.json').read_text())}
  return result, meta


def aligned_rows(data, delay_s, target='can_lat', driver_limit=5.):
  k = int(round(delay_s / DT))
  i = np.arange(k, len(data['t']))
  j = i - k
  keep = (data['selected'][i] & data['active'][j] & (data['factor'][j] == 100)
          & (data['episode'][i] == data['episode'][j]) & (np.abs(data['driver'][j]) <= driver_limit)
          & (np.abs(data['driver'][i]) <= driver_limit))
  i = i[keep]; j = j[keep]
  x = np.c_[np.ones(len(i)), data['torque'][j], data['driver'][j]]
  # The signed-rate coefficient is a *candidate* hysteresis term. Delay and
  # plant dynamics can confound it; publish its lag sensitivity and holdout.
  xh = np.c_[x, np.clip(data['rate'][i], -1., 1.)]
  return x, xh, data[target][i], data['episode'][i], i, j


def route_fits(data, target, delay_s):
  x, xh, y, ep, _, _ = aligned_rows(data, delay_s, target)
  linear = ols(x, y); hysteresis = ols(xh, y)
  tls = torque_tls(x[:, 1], y)
  friction_accel = -hysteresis['coefficients'][3]
  return {'samples': len(y), 'episodes': len(np.unique(ep)), 'delay_s': delay_s,
          'negative_samples': int(np.sum(x[:, 1] < 0)), 'positive_samples': int(np.sum(x[:, 1] > 0)),
          'linear': linear, 'tls': tls, 'signed_rate_model': hysteresis,
          'signed_rate_friction_raw': friction_accel / hysteresis['coefficients'][1]}


def transfer(datasets, target, delay_s):
  records = []
  for train_id, test_id in ((0, 1), (1, 0)):
    x, xh, y, _, _, _ = aligned_rows(datasets[train_id], delay_s, target)
    tx, txh, ty, _, _, _ = aligned_rows(datasets[test_id], delay_s, target)
    record = {'train_route_index': train_id, 'test_route_index': test_id}
    for name, xx, tt in [('linear', x, tx), ('signed_rate', xh, txh)]:
      coefficients = np.asarray(ols(xx, y)['coefficients'])
      residual = ty - tt @ coefficients
      record[name + '_rmse_ms2'] = float(np.sqrt(np.mean(residual ** 2)))
      record[name + '_bias_ms2'] = float(residual.mean())
    records.append(record)
  return records


def episode_bootstrap(datasets, target, delay_s, repeats=1000):
  """Resample whole LKA episodes, separately within each route, not adjacent points."""
  groups = []
  for data in datasets:
    x, xh, y, ep, _, _ = aligned_rows(data, delay_s, target)
    groups.append([(x[ep == e], xh[ep == e], y[ep == e]) for e in np.unique(ep)])
  rng = np.random.default_rng(308)
  gains = []; friction = []
  for _ in range(repeats):
    sample = [g[i] for g in groups for i in rng.integers(0, len(g), len(g))]
    x = np.concatenate([s[0] for s in sample]); xh = np.concatenate([s[1] for s in sample]); y = np.concatenate([s[2] for s in sample])
    gains.append(ols(x, y)['coefficients'][1])
    co = ols(xh, y)['coefficients']
    friction.append(-co[3] / co[1])
  return {'method': '1000 whole-episode bootstrap draws stratified by route; conditional on these two routes',
          'gain_ms2_per_raw_p025_p50_p975': np.quantile(gains, [.025, .5, .975]).tolist(),
          'signed_rate_friction_raw_p025_p50_p975': np.quantile(friction, [.025, .5, .975]).tolist()}


def arx_scan(datasets, target):
  """First-order dynamics with route-level holdout; delay is not static peak lag."""
  results = []
  for delay in np.arange(0, .501, DT):
    routes = []
    for data in datasets:
      x, _, y, _, i, _ = aligned_rows(data, delay, target)
      keep = (i + 1 < len(data['t']))
      x = x[keep]; y = y[keep]; i = i[keep]
      keep = data['selected'][i+1] & (data['episode'][i] == data['episode'][i+1])
      x = x[keep]; y = y[keep]; i = i[keep]
      next_y = data[target][i + 1]
      features = np.c_[np.ones(len(y)), y, x[:, 1], x[:, 2]]
      routes.append((features, (next_y-y)/DT, y, next_y))
    item = {'delay_s': float(delay), 'routes': [], 'holdout': []}
    for x, dy, _, _ in routes:
      fit = ols(x, dy); co = fit['coefficients']
      item['routes'].append({'coefficients': co, 'dc_gain_ms2_per_raw': -co[2]/co[1] if co[1] < 0 else None,
                             'time_constant_s': -1/co[1] if co[1] < 0 else None})
    for train, test in ((0, 1), (1, 0)):
      tx, _, last_y, next_y = routes[test]
      prediction = last_y + DT * (tx @ np.asarray(item['routes'][train]['coefficients']))
      item['holdout'].append({'test_route_index': test,
        'prediction_rmse_ms2': float(np.sqrt(np.mean((prediction-next_y)**2))),
        'persistence_rmse_ms2': float(np.sqrt(np.mean((last_y-next_y)**2)))})
    item['mean_holdout_rmse_ms2'] = float(np.mean([r['prediction_rmse_ms2'] for r in item['holdout']]))
    results.append(item)
  return results


def main():
  parser = argparse.ArgumentParser(description=__doc__)
  parser.add_argument('--input', type=Path, required=True)
  parser.add_argument('--output', type=Path, required=True)
  args = parser.parse_args(); args.output.mkdir(parents=True, exist_ok=True)
  paths = sorted(args.input.glob('000*'))
  if len(paths) != 2:
    raise SystemExit('Exactly two archived routes are required for this comparison')
  loaded = [load_route(p) for p in paths]; datasets = [d for d, _ in loaded]
  result = {'actuation_source': 'real factory 0x3F2 with EPS 0x495 acknowledgement',
    'scope': 'observed closed-loop response and offline calibration candidates',
    'sample_period_s': DT, 'filters': {'factor_raw': 100, 'eps_state': 3, 'lka_state': 4,
      'minimum_speed_ms': 15, 'maximum_driver_raw': 5, 'engagement_warmup_s': 2,
      'maximum_signal_age_s': .15, 'maximum_pose_bracket_s': .15, 'maximum_pose_log_delay_s': .2},
    'normalization_note': '150 raw is a reference coordinate, never a vehicle transmission limit',
    'routes': [m for _, m in loaded], 'fits': {}, 'delay_scan': {}}
  for target in ('can_lat', 'pose_lat', 'roll_lat'):
    result['fits'][target] = {'routes': [route_fits(d, target, .15) for d in datasets],
      'holdout': transfer(datasets, target, .15), 'bootstrap': episode_bootstrap(datasets, target, .15),
      'sensitivity': [{'delay_s': float(delay), 'routes': [route_fits(d, target, delay) for d in datasets],
                       'holdout': transfer(datasets, target, delay)} for delay in np.arange(0, .501, DT)],
      'driver_sensitivity': []}
    for limit in (0., 2., 5.):
      result['fits'][target]['driver_sensitivity'].append({'max_driver_raw': limit, 'routes': [
        ols(x, y) | {'samples': len(y)} for d in datasets
        for x, _, y, _, _, _ in [aligned_rows(d, .15, target, limit)]]})
    result['delay_scan'][target] = arx_scan(datasets, target)
  (args.output / 'report.json').write_text(json.dumps(result, indent=2, allow_nan=False) + '\n')
  for path, data in zip(paths, datasets):
    with (args.output / (path.name + '.csv')).open('w') as f:
      writer = csv.writer(f); writer.writerow(FIELDS)
      writer.writerows(zip(*(data[k] for k in FIELDS)))
  print(json.dumps({'routes': [{k: m[k] for k in ('route', 'factory_active_s', 'selected_samples_20hz')}
                               for m in result['routes']],
                    'can_fits': result['fits']['can_lat']['routes'],
                    'can_bootstrap': result['fits']['can_lat']['bootstrap'],
                    'can_holdout': result['fits']['can_lat']['holdout'],
                    'best_arx': {k: min(v, key=lambda x: x['mean_holdout_rmse_ms2']) for k, v in result['delay_scan'].items()}}, indent=2))


if __name__ == '__main__':
  main()
