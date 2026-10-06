#!/usr/bin/env python3
"""Install the hashed T9 observation overlay on the stationary comma.

Run with the comma's /usr/local/venv/bin/python, passing an extracted bundle.
The bundle must match the known T15 checkout. No Panda firmware/safety changes.
"""

import datetime
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time


def sha(path):
  return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
  bundle = Path(sys.argv[1]).resolve()
  root = Path('/data/openpilot')
  sys.path.insert(0, str(root))
  import cereal.messaging as messaging
  from openpilot.common.params import Params

  manifest = json.loads((bundle / 'manifest.json').read_text())
  head = subprocess.check_output(['git', '-C', str(root), 'rev-parse', 'HEAD'], text=True).strip()
  assert head == manifest['base_commit'], 'Different installed revision; review first'
  params = Params()
  sm = messaging.SubMaster(['deviceState', 'pandaStates'])
  deadline = time.monotonic() + 5
  while time.monotonic() < deadline:
    sm.update(500)
  assert sm.all_checks(), 'Fresh device and Panda state required'
  assert not sm['deviceState'].started and not params.get_bool('IsOnroad') and not params.get_bool('IsEngaged')
  assert len(sm['pandaStates']) > 0
  for panda in sm['pandaStates']:
    assert not panda.ignitionLine and not panda.ignitionCan and not panda.controlsAllowed
    assert str(panda.safetyModel) == 'noOutput'

  for name, entry in manifest['files'].items():
    assert not Path(name).is_absolute() and '..' not in Path(name).parts
    assert sha(bundle / 'files' / name) == entry['sha256'], name
    target = root / name
    if entry['old_sha256'] is None:
      assert not target.exists(), f'New path already exists: {name}'
    else:
      assert sha(target) == entry['old_sha256'], f'Changed installed file: {name}'

  stamp = datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%SZ')
  backup = Path('/data') / f'psa-t9-shadow-backup-{stamp}'
  backup.mkdir()
  state = {'base_commit': head, 'backup': str(backup), 'phase': 'prepared', 'mode': 'observation_only',
           'manifest': manifest, 'offroad_preflight': True,
           'disable_updates_before': params.get_bool('DisableUpdates'), 'updates_paused': False}
  journal = bundle / 'installation.json'
  journal.write_text(json.dumps(state, indent=2) + '\n')
  changed = []
  overlay_init = root / '.overlay_init'
  try:
    # A finalized background update can overwrite uncommitted source edits at
    # boot, even when the upstream commit is unchanged. Use the supported
    # development switch and preserve the launcher marker in our backup.
    import psutil
    params.put_bool('DisableUpdates', True)
    for process in psutil.process_iter(['cmdline']):
      try:
        if process.info['cmdline'] == ['system.updated.updated']:
          process.terminate()
          process.wait(timeout=10)
      except psutil.NoSuchProcess:
        pass
    if overlay_init.exists():
      shutil.move(overlay_init, backup / '.overlay_init')
    state['updates_paused'] = True
    journal.write_text(json.dumps(state, indent=2) + '\n')
    # Manager registration goes last; running processes remain offroad.
    names = sorted(manifest['files'], key=lambda name: name.endswith('manager/process_config.py'))
    for name in names:
      assert not params.get_bool('IsOnroad') and not params.get_bool('IsEngaged')
      target = root / name
      if target.exists():
        saved = backup / name
        saved.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(target, saved)
      target.parent.mkdir(parents=True, exist_ok=True)
      temp = target.with_name(target.name + '.t9-install')
      shutil.copy2(bundle / 'files' / name, temp)
      os.replace(temp, target)
      changed.append(name)
    env = os.environ | {'PYTHONPATH': str(root), 'PSA_DASHCAM_ONLY': '1'}
    result = subprocess.run([sys.executable, '-m', 'unittest', 'discover', '-s', 'opendbc/car/psa/tests', '-q'],
                            cwd=root, env=env, capture_output=True, text=True, timeout=60)
    (bundle / 'tests.log').write_text(result.stdout + result.stderr)
    assert result.returncode == 0, 'Native tests failed; see tests.log'
    smoke = subprocess.run([sys.executable, '-c',
      'from openpilot.system.psa_shadow import main; '
      'from openpilot.system.manager.process_config import managed_processes; '
      'assert "psa_shadow" in managed_processes; print("observer_import_ok")'],
      cwd=root, env=env, capture_output=True, text=True, timeout=30)
    (bundle / 'smoke.log').write_text(smoke.stdout + smoke.stderr)
    assert smoke.returncode == 0, 'Observer/manager import failed'
    for name, entry in manifest['files'].items():
      assert sha(root / name) == entry['sha256'], name
    assert not params.get_bool('IsOnroad') and not params.get_bool('IsEngaged')
    state['phase'] = 'installed_verified_reboot_pending'
  except BaseException:
    for name in reversed(changed):
      saved = backup / name
      if saved.exists():
        shutil.copy2(saved, root / name)
      else:
        (root / name).unlink()
    params.put_bool('DisableUpdates', state['disable_updates_before'])
    if (backup / '.overlay_init').exists():
      shutil.move(backup / '.overlay_init', overlay_init)
    state['phase'] = 'rolled_back'
    journal.write_text(json.dumps(state, indent=2) + '\n')
    raise
  journal.write_text(json.dumps(state, indent=2) + '\n')
  os.sync()
  print(json.dumps({'phase': state['phase'], 'backup': str(backup), 'files': len(changed)}))


if __name__ == '__main__':
  main()
