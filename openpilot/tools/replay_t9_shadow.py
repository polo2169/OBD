#!/usr/bin/env python3
"""Offline T9 port verification using the exported, original CAN packets.

Control requests below are synthetic adversarial test inputs, never recorded
driver engagement or proof that the real EPS/RVV would accept a proposal.
No messaging, Panda, CAN socket or serial transport is opened.
"""

import argparse
from collections import Counter
import csv
import gzip
import json
from pathlib import Path
import sys

from compare_cristianku_308 import packets


def main():
  parser = argparse.ArgumentParser(description=__doc__)
  parser.add_argument('--source', required=True, type=Path, help='opendbc source root')
  parser.add_argument('--input', required=True, type=Path, help='exported long.can.gz')
  parser.add_argument('--output', required=True, type=Path)
  args = parser.parse_args()
  sys.path.insert(0, str(args.source.resolve()))
  from opendbc.car import structs
  from opendbc.car.psa.interface import CarInterface
  from opendbc.car.psa.values import CAR

  cp = CarInterface.get_non_essential_params(CAR.PSA_PEUGEOT_308_T9)
  assert cp.dashcamOnly and not cp.openpilotLongitudinalControl
  assert all(s.safetyModel == structs.CarParams.SafetyModel.noOutput for s in cp.safetyConfigs)
  ci = CarInterface(cp)
  stats = {name: Counter() for name in (
    'current_gear', 'target_gear', 'target_gear_raw', 'gear_shifter', 'lateral_phase', 'lateral_reason',
    'longitudinal_phase', 'longitudinal_reason', 'can_valid', 'raw_current_gear', 'raw_target_gear', 'checksum_349',
    'pedal_valid', 'pedal_during_rvv', 'checksum_228',
  )}
  batches = 0
  first = last_write = None
  args.output.mkdir(parents=True, exist_ok=True)
  fields = ['logMonoTime', 'seconds', 'speed_kph', 'current_gear', 'target_gear', 'target_gear_raw', 'gear_shifter',
            'synthetic_request', 'lateral_phase', 'lateral_reason', 'torque_proposal_raw',
            'longitudinal_phase', 'longitudinal_reason', 'speed_proposal_kph', 'can_valid',
            'pedal_valid', 'pedal_pct', 'engine_accelerator_demand_pct', 'gas_pressed', 'rvv_active']
  with gzip.open(args.output / 'trace.csv.gz', 'wt') as stream:
    writer = csv.DictWriter(stream, fields)
    writer.writeheader()
    for ns, frames in packets(args.input):
      if first is None:
        first = ns
      for address, data, bus in frames:
        if bus != 0 or len(data) != 8:
          continue
        if address == 0x348:
          stats['raw_current_gear'][data[0] >> 4] += 1
        elif address == 0x349:
          stats['raw_target_gear'][data[3] >> 4] += 1
          stats['checksum_349'][str(sum((b >> 4) + (b & 15) for b in data) % 16 == 6)] += 1
        elif address == 0x228:
          stats['checksum_228'][str(sum((b >> 4) + (b & 15) for b in data) % 16 == 3)] += 1
      state = ci.update([(ns, frames)])
      seconds = (ns - first) / 1e9
      requested = int(seconds) % 30 >= 2
      control = structs.CarControl(enabled=requested, latActive=requested, longActive=requested)
      control.actuators.torque = 1.
      control.actuators.accel = -0.2
      applied, sends = ci.apply(control.as_reader(), ns)
      assert sends == [] and applied.torque == 0 and applied.accel == 0 and applied.steeringAngleDeg == 0
      status = ci.CC.t9_shadow.status
      assert not status['tx_allowed'] and not status['lateral']['tx_allowed'] and not status['longitudinal']['tx_allowed']
      batches += 1
      for key in ('current_gear', 'target_gear', 'target_gear_raw'):
        stats[key][str(status[key])] += 1
      stats['gear_shifter'][str(state.gearShifter)] += 1
      stats['can_valid'][str(bool(state.canValid))] += 1
      stats['pedal_valid'][str(status['pedal_valid'])] += 1
      if state.cruiseState.enabled and status['pedal_valid']:
        stats['pedal_during_rvv']['batches'] += 1
        stats['pedal_during_rvv']['driver_pedal_nonzero'] += state.gasPressed
        stats['pedal_during_rvv']['engine_demand_nonzero'] += status['engine_accelerator_demand_pct'] > 0
      for controller in ('lateral', 'longitudinal'):
        for key in ('phase', 'reason'):
          stats[f'{controller}_{key}'][status[controller][key]] += 1
      if last_write is None or ns - last_write >= 100_000_000:
        last_write = ns
        writer.writerow(dict(zip(fields, (
          ns, seconds, state.vEgoRaw * 3.6, status['current_gear'], status['target_gear'], status['target_gear_raw'],
          str(state.gearShifter), requested, status['lateral']['phase'], status['lateral']['reason'],
          status['lateral']['torque_raw'], status['longitudinal']['phase'], status['longitudinal']['reason'],
          status['longitudinal']['proposed_setpoint_kph'], bool(state.canValid),
          status['pedal_valid'], status['pedal_pct'], status['engine_accelerator_demand_pct'],
          bool(state.gasPressed), bool(state.cruiseState.enabled),
        ))))
  result = {
    'source_route': args.input.parent.name, 'input': str(args.input),
    'control_request_source': 'synthetic_periodic_test_NOT_recorded_driver_engagement',
    'batches': batches, 'can_output_frames': 0, 'nonzero_applied_actuators': 0,
    'dashcam_only': bool(cp.dashcamOnly), 'counts': stats,
  }
  (args.output / 'report.json').write_text(json.dumps(result, indent=2) + '\n')
  print(json.dumps(result, indent=2))


if __name__ == '__main__':
  main()
