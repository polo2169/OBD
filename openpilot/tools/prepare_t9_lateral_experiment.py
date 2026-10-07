#!/usr/bin/env python3
"""Create hashed, reversible experiment archives; never install or start them."""
import argparse
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import sys
import tarfile

OVERLAY = Path(__file__).resolve().parents[1] / 'port/t9_lateral'
spec = importlib.util.spec_from_file_location('t9_preparation_profiles',
  OVERLAY / 'opendbc_repo/opendbc/car/psa/lateral_profiles.py')
profiles = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = profiles
spec.loader.exec_module(profiles)
EXPERIMENTS, selected = profiles.EXPERIMENTS, profiles.selected


def prepare(source, output, name):
  source, output = source.resolve(), output.resolve()
  if not source.is_dir() or output.is_relative_to(source):
    raise ValueError('Output must be outside the source tree')
  if output.exists():
    raise ValueError('Use a new output directory to preserve previous artifacts')
  profile = selected(name)
  pins = json.loads((OVERLAY / 'base-sha256.json').read_text())
  content, manifest = {}, {}
  for relative in sorted(pins):
    path = Path(relative)
    if path.is_absolute() or '..' in path.parts:
      raise ValueError('Invalid overlay path')
    original = source / path
    if original.is_symlink():
      raise ValueError('Refusing source symlink: ' + relative)
    before = hashlib.sha256(original.read_bytes()).hexdigest() if original.is_file() else None
    data = (OVERLAY / path).read_bytes()
    if relative == 'selfdrive/modeld/modeld.py' and before not in (pins[relative], hashlib.sha256(data).hexdigest()):
      raise ValueError('Unreviewed modeld base')
    if relative == 'launch_env.sh' and name != 'off':
      text = data.decode().replace('export PSA_T9_LATERAL_EXPERIMENT=off',
        'export PSA_T9_LATERAL_EXPERIMENT=' + name)
      if profile.blinker_assist:
        text = text.replace('export PSA_T9_LANE_CHANGE_MODE=off', 'export PSA_T9_LANE_CHANGE_MODE=observe')
      data = text.encode()
    content[relative] = data
    manifest[relative] = {'before': before, 'after': hashlib.sha256(data).hexdigest()}
  output.mkdir(parents=True)
  with tarfile.open(output / 'overlay.tar.gz', 'w:gz') as archive:
    for relative, data in content.items():
      info = tarfile.TarInfo(relative)
      info.size, info.mode = len(data), (OVERLAY / relative).stat().st_mode & 0o777
      archive.addfile(info, io.BytesIO(data))
  (output / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
  metadata = {'profile': name, 'safety_param': profile.safety_param or None,
    'min_lateral_speed_kph': profile.min_speed_kph, 'blinker_assist': profile.blinker_assist,
    'lane_change': 'observation_only' if profile.blinker_assist else 'off',
    'eps_cycle_setting_required': name != 'off', 'firmware_capability_required': 10 if name != 'off' else None,
    'installed': False, 'physically_validated': False,
    'manifest_sha256': hashlib.sha256((output / 'manifest.json').read_bytes()).hexdigest()}
  (output / 'experiment.json').write_text(json.dumps(metadata, indent=2) + '\n')
  return metadata


def main():
  parser = argparse.ArgumentParser(description=__doc__)
  parser.add_argument('--source-tree', type=Path, required=True, help='Read-only installed/base source tree')
  parser.add_argument('--output', type=Path, required=True, help='New private archive directory')
  parser.add_argument('--profile', choices=('off', *EXPERIMENTS), default='off')
  args = parser.parse_args()
  print(json.dumps(prepare(args.source_tree, args.output, args.profile), indent=2))


if __name__ == '__main__':
  main()
