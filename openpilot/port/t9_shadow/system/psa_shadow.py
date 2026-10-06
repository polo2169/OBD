"""Receive-only T9 controller observer. No PubMaster, Panda or serial output.

The passive card does not call CarInterface.apply; this separate observer
evaluates the same native interface without touching the live card instance.
Real carControl requests are logged as received, never fabricated from vision
or stock LKA activity. Model actions are context, not actuator commands.
"""

import json
import math
from pathlib import Path
import time

import cereal.messaging as messaging
from opendbc.car import structs
from opendbc.car.psa.interface import CarInterface
from opendbc.car.psa.values import CAR


def json_safe(value):
  if isinstance(value, float) and not math.isfinite(value):
    return None
  if isinstance(value, dict):
    return {key: json_safe(item) for key, item in value.items()}
  return value


def main():
  root = Path('/data/psa-shadow')
  root.mkdir(exist_ok=True)
  stamp = time.strftime('%Y%m%dT%H%M%SZ', time.gmtime())
  cp = CarInterface.get_non_essential_params(CAR.PSA_PEUGEOT_308_T9)
  assert cp.dashcamOnly and not cp.openpilotLongitudinalControl
  assert all(s.safetyModel == structs.CarParams.SafetyModel.noOutput for s in cp.safetyConfigs)
  ci = CarInterface(cp)
  can_sock = messaging.sub_sock('can', timeout=100)
  sm = messaging.SubMaster(['carControl', 'modelV2', 'carParams'])
  last_write = 0
  part = 0
  output = None
  try:
    while True:
      events = messaging.drain_sock(can_sock, wait_for_one=True)
      now = time.monotonic_ns()
      sm.update(0)
      if sm.seen['carParams'] and sm['carParams'].carFingerprint != CAR.PSA_PEUGEOT_308_T9:
        time.sleep(0.05)
        continue
      packets = [(event.logMonoTime, [(frame.address, frame.dat, frame.src) for frame in event.can]) for event in events]
      state = ci.update(packets or [(now, [])])
      control = sm['carControl'] if sm.all_checks(['carControl']) else structs.CarControl().as_reader()
      applied, can_sends = ci.apply(control, now)
      assert not can_sends and applied.torque == 0 and applied.accel == 0
      if now - last_write < 500_000_000:
        continue
      last_write = now
      model = sm['modelV2']
      status = ci.CC.t9_shadow.status | {
        'logMonoTime': now, 'canValid': bool(state.canValid),
        'carControl_fresh': sm.all_checks(['carControl']),
        'model_fresh': sm.all_checks(['modelV2']),
        'model_desired_curvature': float(model.action.desiredCurvature),
        'model_desired_acceleration': float(model.action.desiredAcceleration),
        'model_should_stop': bool(model.action.shouldStop),
      }
      if output is None or output.tell() >= 8_000_000:
        if output is not None:
          output.close()
        output = (root / f'{stamp}-{part:03}.jsonl').open('a')
        part += 1
      output.write(json.dumps(json_safe(status), allow_nan=False) + '\n')
      output.flush()
  finally:
    if output is not None:
      output.close()


if __name__ == '__main__':
  main()
