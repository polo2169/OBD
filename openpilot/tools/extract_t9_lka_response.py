#!/usr/bin/env python3
"""Extract the factory's real LKA commands and responses from archived comma logs.

Input is the complete neutral CAN export plus original rlogs. No device I/O.
0x3F2 remains the factory command, never an openpilot/carOutput command.
"""

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import sys

import numpy as np
import zstandard

from compare_cristianku_308 import packets


LENGTHS = {0x2F5: 7, 0x305: 7, 0x30D: 8, 0x3CD: 8, 0x3F2: 8, 0x495: 4, 0x412: 8}
FIELDS = ['torque_raw', 'factor', 'lka_state', 'angle_command_deg', 'lxa', 'eps_state', 'eps_torque_raw',
          'driver_raw', 'angle_deg', 'rate_deg_s', 'speed_ms', 'yaw_can_rad_s', 'accel_can_ms2',
          'brake', 'command_age_s', 'eps_age_s', 'motion_age_s', 'driver_age_s']


def signed(value, bits):
  return value - (1 << bits) if value & (1 << (bits - 1)) else value


def checksum_ok(address, data):
  if address in (0x2F5, 0x3CD):
    return sum((b >> 4) + (b & 15) for b in data) % 16 == (11 if address == 0x2F5 else 3)
  if address == 0x305:
    value = 0
    for b in data[:5]:
      value ^= (b >> 4) ^ (b & 15)
    return value == 0
  return True


def decode(state, ns):
  def get(a): return state[a][1]
  d = get(0x3F2)
  steer = get(0x305)
  eps = get(0x495)
  motion = get(0x3CD)
  wheels = get(0x30D)
  return [signed((d[3] << 3) | (d[4] >> 5), 11), d[5] >> 1, (d[4] >> 2) & 7,
          signed((d[6] << 6) | (d[7] >> 2), 14) * .1, d[5] & 1,
          (eps[2] >> 2) & 7, signed(eps[0], 8), signed(get(0x2F5)[1], 8),
          signed(int.from_bytes(steer[:2], 'big'), 16) * .1,
          steer[2] * (-1 if steer[3] & 128 else 1),
          sum(int.from_bytes(wheels[i:i+2], 'big') for i in range(0, 8, 2)) * .01 / 4 / 3.6,
          np.radians(signed(int.from_bytes(motion[2:4], 'big'), 16) * .1),
          signed(motion[1], 8) * .05, bool(get(0x412)[0] & 32),
          (ns - state[0x3F2][0]) / 1e9, (ns - state[0x495][0]) / 1e9,
          max((ns - state[a][0]) / 1e9 for a in (0x305, 0x30D, 0x3CD)), (ns - state[0x2F5][0]) / 1e9]


def extract_can(path, output):
  times = []; values = []; state = {}; counters = {}; errors = Counter(); frames = Counter()
  for ns, batch in packets(path):
    for address, data, bus in batch:
      if bus != 0 or address not in LENGTHS:
        continue
      frames[hex(address)] += 1
      if len(data) != LENGTHS[address] or not checksum_ok(address, data):
        errors['invalid_' + hex(address)] += 1
        state.pop(address, None)
        continue
      position = {0x2F5: 0, 0x305: 4, 0x3CD: -1}.get(address)
      counter = data[position] & 15 if position is not None else None
      if counter is not None and address in counters and counter != (counters[address] + 1) % 16:
        errors['counter_gap_' + hex(address)] += 1
        # Do not bridge a detected gap into a calibration sample.
        counters[address] = counter
        state.pop(address, None)
        continue
      if counter is not None:
        counters[address] = counter
      state[address] = (ns, data)
    if all(a in state for a in LENGTHS):
      times.append(ns); values.append(decode(state, ns))
  np.savez_compressed(output / 'can.npz', ns=np.asarray(times, dtype=np.int64), values=np.asarray(values), fields=FIELDS)
  return {'frames_bus0': frames, 'rejections': errors, 'samples': len(times), 'source': str(path),
          'source_sha256': hashlib.sha256(path.read_bytes()).hexdigest()}


def extract_pose(source, paths, output):
  sys.path.insert(0, str(source.resolve()))
  from cereal import log
  from openpilot.selfdrive.locationd.helpers import Pose, PoseCalibrator
  calibrator = PoseCalibrator()
  fields = ['roll_device_rad', 'roll_calibrated_rad', 'yaw_calibrated_rad_s', 'accel_y_calibrated_ms2',
            'valid', 'calibrated', 'log_delay_s', 'roll_std_rad', 'yaw_std_rad_s']
  times = []; values = []; car = []; counts = Counter(); latest_calib_ns = 0
  for path in paths:
    with path.open('rb') as f:
      raw = zstandard.ZstdDecompressor().stream_reader(f).read()
    for event in log.Event.read_multiple_bytes(raw):
      k = event.which()
      if k == 'liveCalibration':
        if event.valid:
          calibrator.feed_live_calib(event.liveCalibration)
          latest_calib_ns = event.logMonoTime
      elif k == 'carState':
        s = event.carState
        car.append([event.logMonoTime, event.valid and s.canValid and not s.canTimeout,
                    s.steeringPressed, s.brakePressed])
      elif k == 'livePose':
        p = event.livePose; counts['pose_samples'] += 1
        pose = Pose.from_live_pose(p)
        calibrated = calibrator.build_calibrated_pose(pose)
        valid = bool(event.valid and p.angularVelocityDevice.valid and p.orientationNED.valid
                     and p.inputsOK and p.sensorsOK and p.posenetOK)
        calib = bool(calibrator.calib_valid and 0 <= event.logMonoTime - latest_calib_ns < 2_000_000_000)
        counts['valid'] += valid; counts['calibrated'] += calib
        times.append(p.timestamp)
        values.append([pose.orientation.roll, calibrated.orientation.roll,
                       calibrated.angular_velocity.yaw, calibrated.acceleration.y,
                       valid, calib, (event.logMonoTime - p.timestamp) / 1e9,
                       pose.orientation.roll_std, calibrated.angular_velocity.yaw_std])
    print('pose', path.parent.name, flush=True)
  np.savez_compressed(output / 'pose.npz', ns=np.asarray(times, dtype=np.int64), values=np.asarray(values), fields=fields,
                      car=np.asarray(car))
  return {'counts': counts, 'source_files': [str(p) for p in paths], 'time_base': 'livePose.timestamp'}


def main():
  p = argparse.ArgumentParser(description=__doc__)
  p.add_argument('--source', type=Path, required=True)
  p.add_argument('--archive', type=Path, required=True)
  p.add_argument('--route', required=True)
  p.add_argument('--output', type=Path, required=True)
  a = p.parse_args(); a.output.mkdir(parents=True, exist_ok=True)
  can = a.archive / 'comparaison-cristianku' / a.route / 'long.can.gz'
  paths = sorted((a.archive / 'realdata').glob(a.route + '--*/rlog.zst'), key=lambda p: int(p.parent.name.rsplit('--', 1)[1]))
  assert paths and can.exists()
  result = {'route': a.route, 'can': extract_can(can, a.output), 'pose': extract_pose(a.source, paths, a.output),
            'actuation_source': 'recorded_factory_0x3F2', 'device_modified': False}
  (a.output / 'extraction.json').write_text(json.dumps(result, indent=2) + '\n')


if __name__ == '__main__':
  main()
