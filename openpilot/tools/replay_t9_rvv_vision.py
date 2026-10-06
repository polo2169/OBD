#!/usr/bin/env python3
"""Evaluate the existing RVV lead planner on actual comma vision observations.

No CAN output, hardware connection or invented traffic-sign input. The cap
is the driver's recorded RVV setpoint, not an inferred road speed limit.
"""

import argparse
from collections import Counter
import csv
import gzip
import hashlib
import importlib.util
import json
from pathlib import Path
import sys

import zstandard


def main():
  parser = argparse.ArgumentParser(description=__doc__)
  parser.add_argument('--source', type=Path, required=True, help='Installed comma source/schema checkout')
  parser.add_argument('--planner', type=Path, required=True, help='Existing HIL/sim/cruise_speed_assistant.py')
  parser.add_argument('--routes', type=Path, required=True, help='Local realdata directory')
  parser.add_argument('--route', required=True)
  parser.add_argument('--output', type=Path, required=True)
  parser.add_argument('--corrected-pedal-trace', type=Path,
                      help='Native full-CAN replay trace.csv.gz; replaces the old logged gasPressed only')
  args = parser.parse_args()
  sys.path.insert(0, str(args.source.resolve()))
  from cereal import log

  spec = importlib.util.spec_from_file_location('t9_existing_cruise_planner', args.planner)
  module = importlib.util.module_from_spec(spec)
  sys.modules[spec.name] = module
  spec.loader.exec_module(module)
  planner = module.LeadAwareTargetPlanner(min_setpoint_kph=40)
  pedal_rows = iter(())
  if args.corrected_pedal_trace:
    with gzip.open(args.corrected_pedal_trace, 'rt') as f:
      pedal_rows = iter(list(csv.DictReader(f)))
  next_pedal = next(pedal_rows, None)
  current_pedal = None
  paths = sorted(args.routes.glob(args.route + '--*/qlog.zst'), key=lambda p: int(p.parent.name.rsplit('--', 1)[1]))
  assert paths
  args.output.mkdir(parents=True, exist_ok=True)
  car = None
  car_ns = 0
  calibrated = False
  first = None
  counts = Counter()
  reasons = Counter()
  inhibitions = Counter()
  fields = ['seconds', 'speed_kph', 'stock_setpoint_kph', 'lead_present', 'lead_probability', 'lead_distance_m',
            'lead_speed_kph', 'lead_radar_confirmed', 'target_kph', 'reason', 'driver_intervention',
            'below_engine_brake_prior', 'eligible_stock_rvv', 'pedal_valid', 'pedal_pct', 'gas_pressed']
  with gzip.open(args.output / 'vision-following.csv.gz', 'wt') as stream:
    writer = csv.DictWriter(stream, fields)
    writer.writeheader()
    for path in paths:
      with path.open('rb') as f:
        raw = zstandard.ZstdDecompressor().stream_reader(f).read()
      for event in log.Event.read_multiple_bytes(raw):
        ns = int(event.logMonoTime)
        first = ns if first is None else first
        kind = event.which()
        if kind == 'carState':
          car = event.carState
          car_ns = ns if event.valid else 0
        elif kind == 'liveCalibration':
          calibrated = event.valid and str(event.liveCalibration.calStatus) == 'calibrated'
        elif kind == 'radarState':
          counts['vision_messages'] += 1
          if not event.valid or car is None or not 0 <= ns - car_ns <= 250_000_000:
            counts['invalid_or_stale_input'] += 1
            continue
          lead = event.radarState.leadOne
          pedal_valid = True
          pedal_pct = None
          gas_pressed = bool(car.gasPressed)
          if args.corrected_pedal_trace:
            while next_pedal is not None and int(next_pedal['logMonoTime']) <= ns:
              current_pedal = next_pedal
              next_pedal = next(pedal_rows, None)
            pedal_valid = bool(current_pedal and 0 <= ns - int(current_pedal['logMonoTime']) <= 250_000_000
                               and current_pedal['pedal_valid'] == 'True')
            gas_pressed = not pedal_valid or current_pedal['gas_pressed'] == 'True'
            pedal_pct = float(current_pedal['pedal_pct']) if pedal_valid else None
          counts['lead_present' if lead.status else 'no_lead'] += 1
          counts['physical_radar' if lead.radar else 'vision_source'] += 1
          cap = int(round(car.cruiseState.speed * 3.6))
          if not 40 <= cap <= 130:
            counts['stock_setpoint_unavailable'] += 1
            continue
          observation = module.LeadVehicleObservation(
            present=bool(lead.status), distance_m=float(lead.dRel), speed_ms=float(lead.vLead),
            relative_speed_ms=float(lead.vRel), probability=float(lead.modelProb), age_s=0.,
            radar_confirmed=bool(lead.radar),
          )
          decision = planner.plan(cap, float(car.vEgo), observation)
          eligible = bool(calibrated and car.canValid and not car.canTimeout and car.cruiseState.enabled
                          and car.vEgoRaw * 3.6 >= 40 and not car.brakePressed and not gas_pressed
                          and not car.doorOpen and not car.seatbeltUnlatched and not car.parkingBrake)
          if car.cruiseState.enabled:
            counts['recorded_rvv_active'] += 1
            for name, inhibited in (
              ('camera_not_calibrated', not calibrated), ('can_invalid', not car.canValid or car.canTimeout),
              ('speed_below_40', car.vEgoRaw * 3.6 < 40), ('decoded_gas_pressed', gas_pressed),
              ('pedal_input_unavailable', not pedal_valid),
              ('brake_pressed', car.brakePressed), ('door_open', car.doorOpen),
              ('seatbelt_unlatched', car.seatbeltUnlatched), ('parking_brake', car.parkingBrake),
            ):
              inhibitions[name] += bool(inhibited)
          below_prior = (decision.target_kph is not None and
                         (decision.target_kph / 3.6 - car.vEgo) / 2.0 < -0.30)
          counts['evaluated'] += 1
          reasons[decision.reason] += 1
          if eligible:
            counts['stock_rvv_eligible'] += 1
            counts['eligible_lead_used'] += decision.lead_used
            counts['eligible_driver_intervention'] += decision.driver_intervention_required
            counts['eligible_below_engine_brake_prior'] += below_prior
            counts['eligible_target_below_stock'] += decision.target_kph is not None and decision.target_kph < cap
          writer.writerow(dict(zip(fields, (
            (ns - first) / 1e9, car.vEgoRaw * 3.6, cap, bool(lead.status), lead.modelProb, lead.dRel,
            lead.vLead * 3.6, bool(lead.radar), decision.target_kph, decision.reason,
            decision.driver_intervention_required, below_prior, eligible, pedal_valid, pedal_pct, gas_pressed,
          ))))
  result = {'route': args.route, 'first_log_mono_time': first, 'source_files': len(paths), 'counts': counts, 'reasons': reasons,
            'inhibitions_with_recorded_rvv_active': inhibitions,
            'planner_source': str(args.planner), 'planner_sha256': hashlib.sha256(args.planner.read_bytes()).hexdigest(),
            'speed_cap_source': 'recorded_stock_rvv_NOT_traffic_signs', 'tx_permitted': False,
            'pedal_source': str(args.corrected_pedal_trace) if args.corrected_pedal_trace else 'original_logged_carState',
            'limitations': ['Eligibility is for this numerical replay, not permission to actuate.',
                            'The -0.30 m/s² engine-brake prior is not a measured vehicle guarantee.',
                            'qlog vision input is sampled; this is not an actuation or collision-avoidance validation.']}
  (args.output / 'vision-report.json').write_text(json.dumps(result, indent=2) + '\n')
  print(json.dumps(result, indent=2))


if __name__ == '__main__':
  main()
