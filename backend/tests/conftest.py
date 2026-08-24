import pytest

from app.config import settings
from app.transports.virtual import VirtualVehicleTransport


@pytest.fixture(autouse=True)
def isolate_runtime_settings(tmp_path, monkeypatch):
    """Keep tests deterministic and independent from the developer's .env.

    The application intentionally persists its selected hardware transport and
    runtime safety mode. Tests must never inherit either of those choices or
    write diagnostic artefacts into the real data directory.
    """
    monkeypatch.setattr(settings, "transport", "virtual")
    monkeypatch.setattr(settings, "can_tx_enabled", False)
    monkeypatch.setattr(settings, "read_only", True)
    monkeypatch.setattr(settings, "runtime_mode_switch_enabled", False)
    monkeypatch.setattr(settings, "dtc_clear_enabled", False)
    monkeypatch.setattr(settings, "safety_ecu_clear_enabled", False)
    monkeypatch.setattr(settings, "psa_security_access_enabled", False)
    monkeypatch.setattr(settings, "psa_actuator_enabled", False)
    monkeypatch.setattr(settings, "psa_ecu_reset_enabled", False)
    monkeypatch.setattr(settings, "psa_telecoding_write_enabled", False)

    monkeypatch.setattr(settings, "session_dir", tmp_path / "sessions")
    monkeypatch.setattr(settings, "diagnostic_history_dir", tmp_path / "diagnostics")
    monkeypatch.setattr(settings, "diagnostic_trace_import_dir", tmp_path / "diagbox_imports")
    monkeypatch.setattr(settings, "sensor_overrides_file", tmp_path / "sensor_overrides.json")
    monkeypatch.setattr(
        settings,
        "manual_signal_validations_file",
        tmp_path / "manual_signal_validations.json",
    )
    monkeypatch.setattr(settings, "live_sensor_registry_file", tmp_path / "live_sensor_registry.json")
    monkeypatch.setattr(settings, "observed_dtcs_file", tmp_path / "observed_dtcs.json")
    monkeypatch.setattr(settings, "oil_log_file", tmp_path / "oil_log.json")
    monkeypatch.setattr(settings, "transport_selection_file", tmp_path / "transport_selection.json")
    monkeypatch.setattr(settings, "security_audit_file", tmp_path / "security_audit.jsonl")
    monkeypatch.setattr(settings, "telecoding_backup_dir", tmp_path / "telecoding")
    VirtualVehicleTransport.reset_simulation()
