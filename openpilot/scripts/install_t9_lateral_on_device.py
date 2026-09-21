#!/usr/bin/env python3
"""Install or roll back the tested T9 lateral tree on a USB-powered comma.

No CAN/safety-mode calls: normal pandad startup installs the signed firmware.
The complete previous tree (including its Panda firmware) is retained.
"""
import argparse
import datetime
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time

LIVE = Path('/data/openpilot')
BASE_COMMIT = '6c928b70b499fae53c3791384e44886f4c352842'


def sha(path):
  return hashlib.sha256(path.read_bytes()).hexdigest()


def installed_source_hashes(live, manifest, previous_manifest_sha256=None):
  if previous_manifest_sha256 is None:
    return {name: entry['before'] for name, entry in manifest.items()}
  # An upgrade must name the exact previously reviewed installed overlay.
  # The new manifest still preserves the original base hashes for provenance.
  if sha(live/'manifest.json') != previous_manifest_sha256:
    raise RuntimeError('Installed overlay manifest changed')
  previous = json.loads((live/'manifest.json').read_text())
  if not set(previous) <= set(manifest):
    raise RuntimeError('Upgrade cannot drop previously overlaid sources')
  return {name: previous[name]['after'] if name in previous else entry['before']
          for name, entry in manifest.items()}


def preflight():
  sys.path.insert(0, str(LIVE))
  import cereal.messaging as messaging
  from openpilot.common.params import Params
  params = Params()
  sm = messaging.SubMaster(['deviceState', 'pandaStates'])
  deadline = time.monotonic() + 10
  while time.monotonic() < deadline:
    sm.update(500)
  if not sm.all_checks():
    raise RuntimeError('Fresh deviceState and pandaStates required')
  if sm['deviceState'].started or params.get_bool('IsOnroad') or params.get_bool('IsEngaged'):
    raise RuntimeError('Device must be offroad and disengaged')
  pandas = sm['pandaStates']
  if len(pandas) != 1:
    raise RuntimeError('Exactly one Panda required')
  for p in pandas:
    if (p.ignitionLine or p.ignitionCan or p.controlsAllowed or str(p.safetyModel) != 'noOutput'
        or str(p.harnessStatus) != 'notConnected' or not 4000 < p.voltage < 9000):
      raise RuntimeError('Requires USB power, car harness disconnected, ignition off and noOutput')
  return params, {'started': False, 'panda': [p.to_dict() for p in pandas]}


def main():
  parser = argparse.ArgumentParser(description=__doc__)
  parser.add_argument('tree', type=Path)
  parser.add_argument('--rollback', action='store_true')
  parser.add_argument('--check-only', action='store_true')
  parser.add_argument('--previous-manifest-sha256', help='Exact installed overlay digest, required for an upgrade')
  args = parser.parse_args()
  if args.rollback and args.previous_manifest_sha256:
    raise RuntimeError('Upgrade digest does not apply to rollback')
  tree = args.tree.resolve()
  prefix = 'openpilot-before-t9-lateral-' if args.rollback else 't9-lateral-build-'
  if tree.parent != Path('/data') or not tree.name.startswith(prefix) or tree == LIVE.resolve():
    raise RuntimeError('Unexpected staging/backup directory')
  params, observed = preflight()
  if not args.rollback:
    head = subprocess.check_output(['git', '-C', str(LIVE), 'rev-parse', 'HEAD'], text=True).strip()
    if head != BASE_COMMIT:
      raise RuntimeError('Installed revision changed')
    manifest = json.loads((tree/'manifest.json').read_text())
    expected_installed = installed_source_hashes(LIVE, manifest, args.previous_manifest_sha256)
    result = json.loads((tree/'build-result.json').read_text())
    required = {'selfdrive/pandad/pandad', 'panda/board/obj/panda_h7.bin.signed', 'panda/board/obj/bootstub.panda_h7.bin'}
    if 'common/params_keys.h' in manifest:
      required.add('common/params_pyx.so')
    if set(result['artifacts']) != required:
      raise RuntimeError('Build must include the matching development bootstub')
    if not result['tests_passed'] or result['source_manifest_sha256'] != sha(tree/'manifest.json'):
      raise RuntimeError('No successful build/tests matching these sources')
    for name, entry in manifest.items():
      if Path(name).is_absolute() or '..' in Path(name).parts:
        raise RuntimeError('Unsafe manifest path')
      if sha(tree/name) != entry['after']:
        raise RuntimeError('Staged source changed: '+name)
      target = LIVE/name
      before = sha(target) if target.exists() else None
      if before != expected_installed[name]:
        raise RuntimeError('Installed source changed: '+name)
    for name, checksum in result['artifacts'].items():
      if sha(tree/name) != checksum:
        raise RuntimeError('Compiled artifact changed: '+name)
    if sha(tree/'SConstruct.before-lateral-build') != sha(LIVE/'SConstruct'):
      raise RuntimeError('Original build graph mismatch')
    if not (tree/'prebuilt').is_file():
      raise RuntimeError('Prebuilt model/runtime marker missing')
    if not params.get_bool('OpenpilotEnabledToggle'):
      raise RuntimeError('Enable openpilot in the device settings before installing')
  else:
    if not (tree/'prebuilt').is_file() or not (tree/'panda/board/obj/panda_h7.bin.signed').is_file():
      raise RuntimeError('Incomplete rollback tree')
  if args.check_only:
    print(json.dumps({'preflight': observed, 'checked_tree': str(tree), 'installable': True}))
    return

  stamp = datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%SZ')
  backup = Path('/data') / (('openpilot-lateral-retired-' if args.rollback else 'openpilot-before-t9-lateral-')+stamp)
  journal = Path('/data') / ('t9-lateral-installation-'+stamp+'.json')
  state = {'phase': 'prepared', 'tree': str(tree), 'backup': str(backup), 'rollback': args.rollback,
           'previous_manifest_sha256': args.previous_manifest_sha256,
           'preflight': observed, 'updates_paused_before': params.get_bool('DisableUpdates')}
  def record(phase):
    state['phase'] = phase
    journal.write_text(json.dumps(state, indent=2)+'\n')
    os.sync()
  record('prepared')
  # Already authorized for this development version. Preserve the value on rollback.
  params.put_bool('DisableUpdates', True)
  if not args.rollback:
    shutil.copy2(tree/'SConstruct.before-lateral-build', tree/'SConstruct')
    (tree/'.overlay_init').unlink(missing_ok=True)
  # Recheck immediately before the two directory renames.
  preflight()
  os.rename(LIVE, backup)
  try:
    os.rename(tree, LIVE)
  except BaseException:
    os.rename(backup, LIVE)
    record('swap_failed_restored')
    raise
  record('installed_reboot_pending')
  print(json.dumps({'phase': state['phase'], 'backup': str(backup), 'journal': str(journal)}), flush=True)
  params.put_bool('DoReboot', True)


if __name__ == '__main__':
  main()
