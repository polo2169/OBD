#!/usr/bin/env python3
"""Replay closed route logs through the observation-only T9 lane supervisor."""
import argparse
from collections import Counter
import json
from pathlib import Path
import sys


def main():
  parser = argparse.ArgumentParser(description=__doc__)
  parser.add_argument('--schema', type=Path, required=True, help='Prepared native source tree')
  parser.add_argument('--log-dir', type=Path, required=True)
  parser.add_argument('--route', required=True)
  parser.add_argument('--output', type=Path, required=True, help='Private JSON report, outside published sources')
  parser.add_argument('--min-speed', type=float, choices=(50., 67.1), default=50.)
  args = parser.parse_args()
  sys.path.insert(0, str(args.schema.resolve()))
  from cereal import log
  import capnp
  import zstandard
  from openpilot.selfdrive.controls.lib.t9_lane_change import T9LaneChangePreview

  files = sorted(args.log_dir.glob(args.route + '--*/rlog.zst'),
                 key=lambda p: int(p.parent.name.rsplit('--', 1)[1]))
  if not files:
    raise SystemExit('No closed rlogs found')
  preview = T9LaneChangePreview(args.min_speed)
  latest = {}
  transitions, errors, reasons = [], [], Counter()
  previous = None
  starts = models = lane_candidates = lateral_samples = 0
  for path in files:
    with zstandard.ZstdDecompressor().stream_reader(path.read_bytes()) as stream:
      raw = stream.read()
    try:
      for event in log.Event.read_multiple_bytes(raw):
        kind, now = event.which(), int(event.logMonoTime)
        if kind in ('carState', 'carControl'):
          latest[kind] = (now, bool(event.valid), getattr(event, kind).as_builder())
        elif kind == 'modelV2' and 'carState' in latest and 'carControl' in latest:
          car_ns, car_valid, car = latest['carState']
          control_ns, control_valid, control = latest['carControl']
          active = bool(control.latActive and control_valid and 0 <= now - control_ns <= 150_000_000)
          valid = bool(event.valid and car_valid and car.canValid and not car.canTimeout
                       and 0 <= now - car_ns <= 150_000_000)
          model = event.modelV2
          probabilities = model.meta.desireState
          probability = (float(probabilities[log.Desire.laneChangeLeft]) +
                         float(probabilities[log.Desire.laneChangeRight])) if len(probabilities) >= 5 else float('nan')
          model_ns = int(model.timestampEof)
          row = preview.update(now, car, active, model, model_ns, valid, probability)
          models += 1
          lane_candidates += row['adjacent_lane_candidate']
          lateral_samples += active
          starts += row['start']
          reasons[row['reason']] += 1
          state = (row['phase'], row['direction'], row['reason'])
          if state != previous:
            transitions.append(row)
            previous = state
    except capnp.KjException as error:
      errors.append({'segment': path.parent.name, 'error': str(error).splitlines()[0]})
  report = {'route': args.route, 'segments': len(files), 'model_samples': models,
    'lateral_active_samples': lateral_samples, 'adjacent_lane_candidate_samples': lane_candidates,
    'start_candidates': starts, 'road_and_rear_context': 'unknown', 'observation_only': True,
    'physical_acceptance_validated': False, 'reasons': dict(reasons), 'transitions': transitions,
    'parse_errors': errors}
  args.output.parent.mkdir(parents=True, exist_ok=True)
  args.output.write_text(json.dumps(report, indent=2) + '\n')
  print(json.dumps({key: report[key] for key in ('segments', 'model_samples', 'lateral_active_samples',
    'start_candidates', 'observation_only', 'physical_acceptance_validated')}, indent=2))


if __name__ == '__main__':
  main()
