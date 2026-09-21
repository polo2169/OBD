#!/usr/bin/env python3
"""Package the lateral overlay against its reviewed pre-install source hashes."""
import argparse
import hashlib
import json
from pathlib import Path
import tarfile


def main():
  parser = argparse.ArgumentParser(description=__doc__)
  parser.add_argument('--base', type=Path, required=True, help='Original openpilot tree including the T9 shadow overlay')
  parser.add_argument('--output', type=Path, required=True)
  args = parser.parse_args()
  root = Path(__file__).resolve().parents[1] / 'port/t9_lateral'
  expected = json.loads((root/'base-sha256.json').read_text())
  manifest = {}
  for name, before in expected.items():
    old = args.base/name
    actual = hashlib.sha256(old.read_bytes()).hexdigest() if old.is_file() else None
    if actual != before:
      raise SystemExit('Unexpected base file: '+name)
    manifest[name] = {'before': before, 'after': hashlib.sha256((root/name).read_bytes()).hexdigest()}
  args.output.mkdir(parents=True, exist_ok=True)
  with tarfile.open(args.output/'overlay.tar.gz', 'w:gz') as archive:
    for name in sorted(manifest):
      archive.add(root/name, arcname=name)
  (args.output/'manifest.json').write_text(json.dumps(dict(sorted(manifest.items())), indent=2)+'\n')
  print(f'{len(manifest)} files packaged in {args.output}')


if __name__ == '__main__':
  main()
