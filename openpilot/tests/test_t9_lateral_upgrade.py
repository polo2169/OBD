"""An upgrade must match the reviewed installed overlay, including old files."""
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

SCRIPT = Path(__file__).resolve().parents[1] / 'scripts/install_t9_lateral_on_device.py'
spec = importlib.util.spec_from_file_location('t9_installer', SCRIPT)
installer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(installer)


class TestReviewedUpgrade(unittest.TestCase):
  def test_initial_install_uses_original_base(self):
    manifest = {'existing.py': {'before': 'base', 'after': 'new'},
                'added.py': {'before': None, 'after': 'new'}}
    self.assertEqual(installer.installed_source_hashes(Path('/unused'), manifest),
                     {'existing.py': {'base'}, 'added.py': {None}})

  def test_upgrade_requires_exact_manifest_and_keeps_all_previous_paths(self):
    with tempfile.TemporaryDirectory() as directory:
      live = Path(directory)
      old = {'existing.py': {'before': 'base', 'after': 'installed'}}
      (live/'manifest.json').write_text(json.dumps(old))
      digest = installer.sha(live/'manifest.json')
      new = {'existing.py': {'before': 'base', 'after': 'new'},
             'added.py': {'before': None, 'after': 'new'}}
      self.assertEqual(installer.installed_source_hashes(live, new, digest),
                       {'existing.py': {'installed', 'new'}, 'added.py': {None, 'new'}})
      with self.assertRaisesRegex(RuntimeError, 'manifest changed'):
        installer.installed_source_hashes(live, new, 'different digest')
      with self.assertRaisesRegex(RuntimeError, 'cannot drop'):
        installer.installed_source_hashes(live, {'added.py': new['added.py']}, digest)


if __name__ == '__main__':
  unittest.main()
