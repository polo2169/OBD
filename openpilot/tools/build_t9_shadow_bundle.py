#!/usr/bin/env python3
"""Package the reviewed source overlay; does not connect to a device."""

import argparse
import hashlib
import json
from pathlib import Path
import tarfile


def main():
  parser = argparse.ArgumentParser(description=__doc__)
  parser.add_argument('--output', required=True, type=Path)
  args = parser.parse_args()
  lab = Path(__file__).resolve().parents[1]
  overlay = lab / 'port/t9_shadow'
  base = json.loads((overlay / 'base-sha256.json').read_text())
  files = args.output / 'bundle/files'
  files.mkdir(parents=True, exist_ok=True)
  manifest = {'base_commit': '6c928b70b499fae53c3791384e44886f4c352842',
              'mode': 'observation_only', 'files': {}}
  for part, target in [('opendbc', 'opendbc_repo/opendbc'), ('system', 'openpilot/system')]:
    for source in sorted((overlay / part).rglob('*')):
      if not source.is_file() or source.suffix not in ('.py', '.dbc'):
        continue
      name = str(Path(target) / source.relative_to(overlay / part))
      raw = source.read_bytes()
      manifest['files'][name] = {'sha256': hashlib.sha256(raw).hexdigest(), 'old_sha256': base.get(name)}
      dest = files / name
      dest.parent.mkdir(parents=True, exist_ok=True)
      dest.write_bytes(raw)
  (args.output / 'bundle/manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
  (args.output / 'bundle/install.py').write_bytes((lab / 'scripts/install_t9_shadow_on_device.py').read_bytes())
  with tarfile.open(args.output / 'bundle.tar.gz', 'w:gz') as tar:
    for name in ('manifest.json', 'install.py'):
      tar.add(args.output / 'bundle' / name, arcname=name)
    for name in manifest['files']:
      tar.add(files / name, arcname='files/' + name)
  print(json.dumps({'files': len(manifest['files']), 'archive': str(args.output / 'bundle.tar.gz')}))


if __name__ == '__main__':
  main()
