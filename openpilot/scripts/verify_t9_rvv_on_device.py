#!/usr/bin/env python3
"""Read-only post-boot checks; does not open Panda or send CAN frames."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import sys
import time

ROOT = Path('/data/openpilot')
sys.path.insert(0, str(ROOT))
import cereal.messaging as messaging
import psutil
from cereal import log
from openpilot.common.params import Params
from openpilot.selfdrive.pandad.pandad import get_expected_signature
from opendbc.car.psa.interface import CarInterface
from opendbc.car.psa.values import CAR, CarControllerParams
from opendbc.car.psa.lka import DRIVER_TORQUE_LIMIT, MAX_SPEED_KPH
from opendbc.car.psa.rvv import ENGINE_BRAKE_PRIOR_MS2
from opendbc.car.psa.rvv_following import RvvLead, T9RvvFollowing
from opendbc.car.psa.rvv_wire import enabled as rvv_enabled
from opendbc.car.psa.lateral_test import enabled as lateral_enabled


def main():
  parser = argparse.ArgumentParser(description=__doc__)
  parser.add_argument('--combined', action='store_true', help='Verify the explicit combined lateral/RVV profile')
  parser.add_argument('--split-axes', action='store_true', help='Verify the independent-axis profile; requires --combined')
  parser.add_argument('--lateral-pause', action='store_true', help='Verify temporary lateral suspension; requires --split-axes')
  parser.add_argument('--eps-cycle', action='store_true', help='Verify the EPS test mode ON; requires --split-axes')
  args = parser.parse_args()
  if args.eps_cycle and not args.split_axes:
    parser.error('--eps-cycle requires --split-axes')
  if args.split_axes and not args.combined:
    parser.error('--split-axes requires --combined')
  if args.lateral_pause and not args.split_axes:
    parser.error('--lateral-pause requires --split-axes')
  lateral_mode = '1' if args.combined else '0'
  expected_param = 0x1316 if args.eps_cycle else 0x1314 if args.split_axes else 0x1312 if args.combined else 0x1310
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
    and p['harnessStatus'] == 'notConnected' and 4000 < p['voltage'] < 9000 and not p['faults']
    and all(p['canState'+str(i)]['totalTxCnt'] == 0 for i in range(3)) for p in panda)
  runtime = []
  for proc in psutil.process_iter(['pid', 'cmdline', 'name']):
    try:
      if proc.info['name'] == 'pandad' and proc.exe() == str(ROOT/'selfdrive/pandad/pandad'):
        env = proc.environ()
        runtime.append({'pid': proc.pid, 't9_mode': env.get('PSA_T9_LATERAL_TEST'), 'rvv_mode': env.get('PSA_T9_RVV_TEST'),
                        'split_axes_mode': env.get('PSA_T9_SPLIT_AXES_TEST'),
                        'eps_cycle_mode': env.get('PSA_T9_EPS_CYCLE_TEST'),
                        'dashcam': env.get('PSA_DASHCAM_ONLY'), 'skip_fw_check': env.get('BOARDD_SKIP_FW_CHECK')})
    except (psutil.NoSuchProcess, psutil.AccessDenied):
      pass
  checks['native_pandad_running_with_firmware_check'] = len(runtime) == 1 and all(
    p['t9_mode'] == lateral_mode and p['rvv_mode'] == '1' and p['dashcam'] == '0' and p['skip_fw_check'] is None
    and p['eps_cycle_mode'] == ('1' if args.eps_cycle else '0')
    and (p['split_axes_mode'] == '1' if args.split_axes else p['split_axes_mode'] in (None, '0')) for p in runtime)
  # Set only this verifier's environment. Derive the requested CarParams
  # independently of the SSH shell; no running process or parameter is changed.
  os.environ.update({'PSA_T9_LATERAL_TEST': lateral_mode, 'PSA_T9_RVV_TEST': '1',
                     'PSA_T9_SPLIT_AXES_TEST': '1' if args.split_axes else '0', 'PSA_DASHCAM_ONLY': '0',
                     'PSA_T9_EPS_CYCLE_TEST': '1' if args.eps_cycle else '0'})
  cp = CarInterface.get_non_essential_params(CAR.PSA_PEUGEOT_308_T9)
  checks['requested_profile'] = (rvv_enabled(cp) and lateral_enabled(cp) == args.combined
    and cp.safetyConfigs[0].safetyParam == expected_param
    and abs(cp.minEnableSpeed * 3.6 - (67.1 if args.combined and not args.split_axes else 40.)) < 0.01)
  checks['limits_preserved'] = (DRIVER_TORQUE_LIMIT == 15 and CarControllerParams.T9_STEER_DRIVER_THRESHOLD_RAW == 15
                                and MAX_SPEED_KPH == 140. and ENGINE_BRAKE_PRIOR_MS2 == .30)
  checks['panda_driver_threshold_15'] = bool(re.search(r'^#define T9_DRIVER_OVERRIDE_LIMIT 15$',
    (ROOT/'opendbc_repo/opendbc/safety/modes/psa_t9.h').read_text(), re.MULTILINE))
  checks['panda_command_torque_limit_15'] = bool(re.search(r'^#define T9_MAX_TORQUE 15$',
    (ROOT/'opendbc_repo/opendbc/safety/modes/psa_t9.h').read_text(), re.MULTILINE))
  # Evaluate the recorded refusal in memory only, without a wire publication.
  now = 2404232601773
  lead = RvvLead(True, 62.40969467163086, 26.299819946289062, -1.0491962432861328,
                .9936181902885437, 2404223442883, 2404211746675, True, False)
  following = T9RvvFollowing().update(now, active=True, car_valid=True, car_ns=now,
    speed_kph=98.49, stock_setpoint_kph=99., calibrated=True, calibration_ns=now, lead=lead)
  checks['recorded_target_without_two_second_deadline'] = (
    following.reason == 'vision_following_candidate' and following.target_kph == 93
    and following.requested_accel_ms2 is None and not following.rearm_required)
  if args.split_axes:
    from opendbc.car.psa.rvv import DOWN_STEP_NS, STEP_NS
    from opendbc.car.psa.rvv_following import ANTICIPATION_SECONDS, RECOVERY_STABLE_NS, ANTICIPATION_ACQUIRE_NS
    checks['rvv_40_lateral_67'] = (abs(cp.minEnableSpeed*3.6 - 40.) < .01
                                   and abs(cp.minSteerSpeed*3.6 - 67.1) < .01)
    checks['asymmetric_rvv_steps'] = (DOWN_STEP_NS == 100_000_000 and STEP_NS == 500_000_000
      and '#define RVV_DOWN_STEP_US 100000U' in (ROOT/'opendbc_repo/opendbc/safety/modes/psa_t9_rvv.h').read_text())
    checks['anticipation_and_recovery'] = (ANTICIPATION_SECONDS == 4. and RECOVERY_STABLE_NS == 1_000_000_000
                                          and ANTICIPATION_ACQUIRE_NS == 200_000_000)
    from openpilot.selfdrive.selfdrived.events import EVENTS, ET
    event_ids = {'psaLateralAxisUnavailable': 101, 'psaRvvAxisUnavailable': 102, 'psaAxesUnavailable': 103}
    checks['split_event_schema'] = all(getattr(log.OnroadEvent.EventName, name, None) == code
                                      for name, code in event_ids.items())
    checks['split_axis_alerts'] = (all(ET.WARNING in EVENTS.get(event_ids[name], {})
                                     for name in ('psaLateralAxisUnavailable', 'psaRvvAxisUnavailable'))
                                  and all(kind in EVENTS.get(event_ids['psaAxesUnavailable'], {})
                                          for kind in (ET.IMMEDIATE_DISABLE, ET.NO_ENTRY)))
  if args.lateral_pause:
    from opendbc.car import structs
    from opendbc.car.psa.lateral_pause import DRIVER_PAUSE_RAW, RESUME_STABLE_NS, LANE_PROBABILITY_MIN
    checks['pause_schema'] = ('psaLateralPaused' in structs.CarState.schema.fields
      and all(name in structs.CarControl.schema.fields for name in ('psaLateralPause', 'psaLateralResume')))
    checks['pause_alert'] = (getattr(log.OnroadEvent.EventName, 'psaLateralPaused', None) == 104
                             and set(EVENTS.get(104, {})) == {ET.WARNING})
    checks['pause_parameters'] = (DRIVER_PAUSE_RAW == 15 and RESUME_STABLE_NS == 500_000_000
                                  and LANE_PROBABILITY_MIN == .75)
  from opendbc.car import structs
  from openpilot.selfdrive.selfdrived.events import EVENTS, ET
  from opendbc.car.psa.lka import EPS_CYCLE_PERIOD_NS, EPS_CYCLE_TIMEOUT_NS
  from opendbc.car.psa.eps_cycle import MAX_LAT_ACCEL, STABLE_NS
  checks['eps_cycle_setting_matches_mode'] = params.get_bool('PsaT9EpsCycleTest') == args.eps_cycle
  checks['eps_cycle_default_off'] = params.get_default_value('PsaT9EpsCycleTest') is False
  checks['eps_cycle_schema_and_warning'] = ('psaEpsCycling' in structs.CarState.schema.fields
    and 'psaEpsCycleReady' in structs.CarControl.schema.fields
    and getattr(log.OnroadEvent.EventName, 'psaEpsCycling', None) == 105
    and set(EVENTS.get(105, {})) == {ET.WARNING})
  checks['eps_cycle_bounds'] = (EPS_CYCLE_PERIOD_NS == 12_000_000_000 and EPS_CYCLE_TIMEOUT_NS == 2_000_000_000
    and MAX_LAT_ACCEL == .10 and STABLE_NS == 500_000_000
    and '#define T9_CYCLE_PERIOD_US 12000000U' in (ROOT/'opendbc_repo/opendbc/safety/modes/psa_t9.h').read_text())
  checks['eps_cycle_ui_and_boot_snapshot'] = ('class T9EpsCycleToggle' in (ROOT/'selfdrive/ui/mici/layouts/settings/toggles.py').read_text()
    and 'configure_eps_cycle(params)' in (ROOT/'system/manager/manager.py').read_text())
  checks['ui_running'] = any(p.name == 'ui' and p.running for p in sm['managerState'].processes)
  checks['debug_recorder_running'] = any(p.name == 'psa_recorder' and p.running for p in sm['managerState'].processes)
  checks['debug_recording_enabled'] = not params.get_bool('DisableLogging')
  recorder_before = json.loads(Path('/data/psa-diagnostics/status.json').read_text())
  time.sleep(2)
  recorder_after = json.loads(Path('/data/psa-diagnostics/status.json').read_text())
  checks['debug_capture_progressing'] = (recorder_after['session'] == recorder_before['session']
    and recorder_after['bytes_written'] > recorder_before['bytes_written']
    and recorder_after['storage_drops'] == 0
    and 'customReservedRawData0' in recorder_after['messages_received'])
  report = {'checks': checks, 'passed': all(checks.values()), 'recorder': recorder_after, 'panda': panda, 'native_pandad': runtime,
            'requested_safety_param': f'0x{expected_param:04x}',
            'expected_firmware_signature_prefix': get_expected_signature().hex()[:16],
            'firmware_evidence': {'expected_signature_source': 'signed_firmware_file_on_disk',
                                  'actual_firmware_signature_checked_by_this_script': False,
                                  'split_capability_checked_by_this_script': False},
            'eps_cycle_mode': 'ON' if args.eps_cycle else 'OFF',
            'boot_id': Path('/proc/sys/kernel/random/boot_id').read_text().strip(),
            'source_manifest_sha256': hashlib.sha256((ROOT/'manifest.json').read_bytes()).hexdigest()}
  (ROOT/'post-boot-rvv-verification.json').write_text(json.dumps(report, indent=2)+'\n')
  print(json.dumps(report, indent=2))
  return 0 if report['passed'] else 1


if __name__ == '__main__':
  sys.exit(main())
