#!/usr/bin/env python3
"""Test/install the logging-only update, preserving the compiled Panda policy."""
import datetime
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

from install_t9_lateral_on_device import preflight


def sha(path):
  return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
  stage = Path(sys.argv[1]).resolve()
  live = Path('/data/openpilot')
  if stage.parent != Path('/data') or not stage.name.startswith('t9-debug-build-'):
    raise RuntimeError('An isolated /data/t9-debug-build-* tree is required')
  allowed = {'opendbc_repo/opendbc/car/psa/lateral_test.py',
             'opendbc_repo/opendbc/car/psa/tests/test_lateral_test.py',
             'system/manager/process_config.py', 'system/psa_recorder.py', 'system/tests/test_psa_recorder.py'}
  patch = json.loads((stage/'patch-manifest.json').read_text())
  manifest = json.loads((stage/'manifest.json').read_text())
  previous = json.loads((live/'manifest.json').read_text())
  if set(patch) != allowed or set(manifest) != set(previous) | allowed:
    raise RuntimeError('Unexpected update scope')
  for name, entry in manifest.items():
    if sha(stage/name) != entry['after']:
      raise RuntimeError('Staged file mismatch: '+name)
    expected = patch[name]['before'] if name in patch else previous[name]['after']
    if sha(live/name) != expected:
      raise RuntimeError('Installed file changed: '+name)
  build = json.loads((live/'build-result.json').read_text())
  for name, checksum in build['artifacts'].items():
    if sha(stage/name) != checksum or sha(live/name) != checksum:
      raise RuntimeError('Logging update must not change compiled firmware/runtime')
  if sha(stage/'SConstruct') != sha(live/'SConstruct') or not (stage/'prebuilt').exists():
    raise RuntimeError('Build graph/runtime must stay intact')

  env = os.environ | {'PYTHONPATH': str(stage)}
  env.pop('PSA_T9_LATERAL_TEST', None)
  env.pop('PSA_DASHCAM_ONLY', None)
  tests = [
    [sys.executable, '-m', 'unittest', 'discover', '-s', 'opendbc_repo/opendbc/car/psa/tests', '-q'],
    [sys.executable, '-m', 'unittest', 'selfdrive.controls.tests.test_psa_t9_torque', 'system.tests.test_psa_recorder', '-q'],
  ]
  with (stage/'logging-tests.log').open('w') as output:
    for command in tests:
      subprocess.run(command, cwd=stage, env=env, stdout=output, stderr=subprocess.STDOUT, check=True)
  subprocess.run([sys.executable, '-c',
    'from openpilot.system.manager.process_config import managed_processes; '
    'assert managed_processes["psa_recorder"].enabled; '
    'assert not managed_processes["psa_shadow"].enabled'],
    cwd=stage, env=env | {'PSA_T9_LATERAL_TEST': '1', 'PSA_DASHCAM_ONLY': '0'}, check=True)

  params, observed = preflight()
  stamp = datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%SZ')
  backup = Path('/data') / ('openpilot-before-t9-lateral-logging-'+stamp)
  receipt = {'phase': 'tested', 'backup': str(backup), 'preflight': observed,
             'files': patch, 'tests_passed': True, 'compiled_artifacts_unchanged': build['artifacts']}
  build['logging_update'] = {'previous_source_manifest_sha256': build['source_manifest_sha256'],
                             'tests_passed': True, 'tests_log_sha256': sha(stage/'logging-tests.log')}
  build['source_manifest_sha256'] = sha(stage/'manifest.json')
  (stage/'build-result.json').write_text(json.dumps(build, indent=2)+'\n')
  receipt_path = Path('/data') / ('t9-logging-installation-'+stamp+'.json')
  receipt_path.write_text(json.dumps(receipt, indent=2)+'\n')
  os.sync()
  os.rename(live, backup)
  try:
    os.rename(stage, live)
  except BaseException:
    os.rename(backup, live)
    raise
  receipt['phase'] = 'installed_reboot_pending'
  receipt_path.write_text(json.dumps(receipt, indent=2)+'\n')
  os.sync()
  print(json.dumps({'phase': receipt['phase'], 'receipt': str(receipt_path), 'backup': str(backup)}), flush=True)
  params.put_bool('DoReboot', True)


if __name__ == '__main__':
  main()
