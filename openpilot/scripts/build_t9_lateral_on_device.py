#!/usr/bin/env python3
"""Build/test an isolated comma source copy; never touches the live Panda."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

root = Path(sys.argv[1]).resolve()
if root == Path('/data/openpilot') or not root.name.startswith('t9-lateral-build-'):
  raise SystemExit('Requires a dedicated /data/t9-lateral-build-* copy')
manifest = json.loads((root / 'manifest.json').read_text())
(root / 'build-result.json').unlink(missing_ok=True)
for relative, hashes in manifest.items():
  if hashlib.sha256((root / relative).read_bytes()).hexdigest() != hashes['after']:
    raise SystemExit('Source mismatch: ' + relative)

# The installed release has compiled models, not the training ONNX inputs.
# Exclude their unrelated build graph in this staging tree only.
sc = root / 'SConstruct'
original = sc.read_text()
original_path = root / 'SConstruct.before-lateral-build'
if not original_path.exists(): original_path.write_text(original)
sc.write_text(original.replace("  'selfdrive/modeld/SConscript',\n", ''))
env = os.environ | {'PATH': '/usr/local/venv/bin:' + os.environ['PATH'], 'PYTHONPATH': str(root)}
env.pop('PSA_T9_LATERAL_TEST', None)
env.pop('PSA_DASHCAM_ONLY', None)
env.pop('PSA_T9_RVV_TEST', None)
env.pop('PSA_T9_SPLIT_AXES_TEST', None)
env.pop('PSA_T9_EPS_CYCLE_TEST', None)
commands = [
  ['/usr/local/venv/bin/scons', '-j4', 'selfdrive/pandad/pandad',
   'panda/board/obj/panda_h7.bin.signed', 'panda/board/obj/bootstub.panda_h7.bin'] +
   (['common/params_pyx.so'] if 'common/params_keys.h' in manifest else []),
  ['c++', '-std=c++17', '-Wall', '-Wextra', '-Werror', '-I.', 'selfdrive/pandad/tests/test_psa_t9_guard.cc', '-o', 'test_psa_t9_guard'],
  ['./test_psa_t9_guard'],
  ['c++', '-std=c++17', '-Wall', '-Wextra', '-Werror', '-I.', 'selfdrive/pandad/tests/test_psa_t9_rvv_wire.cc', '-o', 'test_psa_t9_rvv_wire'],
  ['./test_psa_t9_rvv_wire'],
  ['/usr/local/venv/bin/python', '-m', 'unittest', 'opendbc.safety.tests.test_psa_t9', 'opendbc.safety.tests.test_psa_t9_rvv', 'opendbc.safety.tests.test_psa_t9_combined', 'opendbc.safety.tests.test_psa_t9_split', 'opendbc.safety.tests.test_psa', '-q'],
  ['/usr/local/venv/bin/python', '-m', 'unittest', 'discover', '-s', 'opendbc_repo/opendbc/car/psa/tests', '-q'],
  ['/usr/local/venv/bin/python', '-m', 'unittest', 'selfdrive.controls.tests.test_psa_t9_torque', 'selfdrive.controls.tests.test_psa_t9_rvv_transport', 'selfdrive.controls.tests.test_psa_t9_split_transport', '-q'],
  ['/usr/local/venv/bin/python', '-m', 'unittest', 'selfdrive.car.tests.test_psa_t9_events', 'selfdrive.car.tests.test_psa_t9_rvv_events', 'selfdrive.car.tests.test_psa_t9_split_events', 'selfdrive.car.tests.test_psa_t9_split_integration', '-q'],
  ['/usr/local/venv/bin/python', '-m', 'unittest', 'system.tests.test_psa_recorder', '-q'],
  ['/usr/local/venv/bin/python', '-m', 'unittest', 'selfdrive.ui.mici.tests.test_lane_confidence',
   'selfdrive.ui.mici.tests.test_lead_indicator', 'selfdrive.ui.mici.tests.test_eps_cycle_toggle', '-q'],
]
for command in commands:
  print('RUN', ' '.join(command), flush=True)
  subprocess.run(command, cwd=root, env=env, check=True)
artifacts = ['selfdrive/pandad/pandad', 'panda/board/obj/panda_h7.bin.signed', 'panda/board/obj/bootstub.panda_h7.bin']
if 'common/params_keys.h' in manifest:
  artifacts.append('common/params_pyx.so')
report = {'source_root': str(root), 'tests_passed': True, 'installed': False,
          'artifacts': {name: hashlib.sha256((root/name).read_bytes()).hexdigest() for name in artifacts},
          'source_manifest_sha256': hashlib.sha256((root/'manifest.json').read_bytes()).hexdigest()}
(root/'build-result.json').write_text(json.dumps(report, indent=2)+'\n')
print(json.dumps(report, indent=2))
