import pytest

from app.config import settings


@pytest.fixture(autouse=True)
def isolate_diagnostic_history(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "diagnostic_history_dir", tmp_path / "diagnostics")
    monkeypatch.setattr(settings, "live_sensor_registry_file", tmp_path / "live_sensor_registry.json")
    monkeypatch.setattr(settings, "security_audit_file", tmp_path / "security_audit.jsonl")
