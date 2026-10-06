#!/usr/bin/env python3
"""Read-only post-boot checks; does not open Panda or send CAN frames."""
import hashlib
import json
import os
from pathlib import Path
import sys
import time

ROOT = Path('/data/openpilot')
sys.path.insert(0, str(ROOT))
import cereal.messaging as messaging
import psutil
from openpilot.common.params import Params
from openpilot.selfdrive.pandad.pandad import get_expected_signature
from opendbc.car.psa.interface import CarInterface
from opendbc.car.psa.values import CAR


def main():
  params = Params()
  sm = messaging.SubMaster(['deviceState', 'pandaStates', 'managerState'])
  end = time.monotonic()+8
  while time.monotonic() < end:
    sm.update(500)
  manifest = json.loads((ROOT/'manifest.json').read_text())
  build = json.loads((ROOT/'build-result.json').read_text())
  checks = {
    'fresh_telemetry': sm.all_checks(),
    'sources_match': all(hashlib.sha256((ROOT/name).read_bytes()).hexdigest() == e['after'] for name, e in manifest.items()),
    'artifacts_match': all(hashlib.sha256((ROOT/name).read_bytes()).hexdigest() == h for name, h in build['artifacts'].items()),
    'offroad': not sm['deviceState'].started and not params.get_bool('IsOnroad') and not params.get_bool('IsEngaged'),
    'updates_paused': params.get_bool('DisableUpdates'),
    'openpilot_enabled': params.get_bool('OpenpilotEnabledToggle'),
  }
  panda = [p.to_dict() for p in sm['pandaStates']]
  checks['home_no_output'] = len(panda) == 1 and all(
    p['safetyModel'] == 'noOutput' and not p['controlsAllowed'] and not p['ignitionLine'] and not p['ignitionCan']
    and p['harnessStatus'] == 'notConnected' and not p['faults']
    and all(p['canState'+str(i)]['totalTxCnt'] == 0 for i in range(3)) for p in panda)
  runtime = []
  for proc in psutil.process_iter(['pid', 'cmdline', 'name']):
    try:
      if proc.info['name'] == 'pandad' and proc.exe() == str(ROOT/'selfdrive/pandad/pandad'):
        env = proc.environ()
        runtime.append({'pid': proc.pid, 't9_mode': env.get('PSA_T9_LATERAL_TEST'),
                        'dashcam': env.get('PSA_DASHCAM_ONLY'), 'skip_fw_check': env.get('BOARDD_SKIP_FW_CHECK')})
    except (psutil.NoSuchProcess, psutil.AccessDenied):
      pass
  checks['native_pandad_running_with_firmware_check'] = len(runtime) == 1 and all(
    p['t9_mode'] == '1' and p['dashcam'] == '0' and p['skip_fw_check'] is None for p in runtime)
  os.environ['PSA_T9_LATERAL_TEST'] = '1'
  cp = CarInterface.get_non_essential_params(CAR.PSA_PEUGEOT_308_T9)
  checks['lateral_only_profile'] = (not cp.dashcamOnly and not cp.openpilotLongitudinalControl
                                   and str(cp.safetyConfigs[0].safetyModel) == 'psa' and cp.safetyConfigs[0].safetyParam == 0x1308)
  report = {'checks': checks, 'passed': all(checks.values()), 'panda': panda, 'native_pandad': runtime,
            'expected_firmware_signature_prefix': get_expected_signature().hex()[:16],
            'boot_id': Path('/proc/sys/kernel/random/boot_id').read_text().strip(),
            'source_manifest_sha256': hashlib.sha256((ROOT/'manifest.json').read_bytes()).hexdigest()}
  (ROOT/'post-boot-verification.json').write_text(json.dumps(report, indent=2)+'\n')
  print(json.dumps(report, indent=2))
  return 0 if report['passed'] else 1


if __name__ == '__main__':
  sys.exit(main())
