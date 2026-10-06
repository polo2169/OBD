import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from openpilot.system.home_uploader import HomeUploadConfig, UploadState, completed_files


class TestHomeUploader(unittest.TestCase):
  def test_config_is_optional_and_validated(self):
    with tempfile.TemporaryDirectory() as directory:
      path = Path(directory) / "upload.json"
      self.assertIsNone(HomeUploadConfig.load(path))
      path.write_text(json.dumps({"server_url": "http://server:8060", "token": "secret", "chunk_bytes": 1}))
      config = HomeUploadConfig.load(path)
      self.assertIsNotNone(config)
      self.assertEqual(config.chunk_bytes, 256 * 1024)

  def test_completed_files_skip_locked_segments_and_remember_upload(self):
    with tempfile.TemporaryDirectory() as directory:
      temporary = Path(directory)
      root = temporary / "realdata"
      done = root / "2026-09-24--08-00-00--0"
      active = root / "2026-09-24--08-00-00--1"
      done.mkdir(parents=True)
      active.mkdir()
      log = done / "rlog.zst"
      log.write_bytes(b"data")
      (active / "rlog.zst").write_bytes(b"active")
      (active / "rlog.lock").touch()
      config = HomeUploadConfig("http://server", "token")
      state = UploadState(temporary / "state.json")
      with patch("openpilot.system.home_uploader.time.time", return_value=log.stat().st_mtime + 200):
        self.assertEqual(completed_files(root, config, state), [log])
        state.mark(log)
        self.assertEqual(completed_files(root, config, state), [])

  def test_completed_files_honors_video_allowlist(self):
    with tempfile.TemporaryDirectory() as directory:
      temporary = Path(directory)
      root = temporary / "realdata"
      segment = root / "2026-09-24--08-00-00--0"
      segment.mkdir(parents=True)
      front = segment / "fcamera.hevc"
      driver = segment / "dcamera.hevc"
      front.write_bytes(b"front")
      driver.write_bytes(b"driver")
      config = HomeUploadConfig("https://server", "token", video_files=frozenset({"fcamera.hevc"}))
      with patch("openpilot.system.home_uploader.time.time", return_value=front.stat().st_mtime + 200):
        self.assertEqual(completed_files(root, config, UploadState(temporary / "state.json")), [front])


if __name__ == "__main__":
  unittest.main()
