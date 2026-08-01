from fastapi.testclient import TestClient

from app.config import settings
from app.diagnostic import psa_advanced
from app.diagnostic.psa_advanced import (
    advanced_catalog,
    compute_psa_seed_key,
    execute_named_action,
    unlock_configuration,
)
from app.main import app
from app.models import PsaActionRequest, PsaUnlockRequest
from app.safety import authorize_diagnostic_can_frame, authorize_psa_lab_can_frame


client = TestClient(app)


def test_seed_key_matches_public_psa_algorithm_vectors():
    assert compute_psa_seed_key("11111111", "D91C") == "55E33B97"
    assert compute_psa_seed_key("12345678", "E4D8") == "53F73F6B"


def test_catalog_separates_documented_nac_actions_from_unknown_bsi_commands():
    actions = {item["key"]: item for item in advanced_catalog()["actions"]}
    assert actions["nac_black_screen"]["available"] is True
    assert actions["nac_black_screen"]["stop_payload_hex"] == "2FD60000"
    assert actions["nac_black_screen"]["validation_status"] == "source_confirmed_not_vehicle_tested"
    assert actions["nac_black_screen"]["vehicle_confirmed"] is False
    assert actions["bsi_turn_left"]["available"] is False
    assert actions["bsi_turn_left"]["validation_status"] == "not_documented"
    assert "aucune trame" in actions["bsi_turn_left"]["unavailable_reason"]


def test_psa_lab_can_allowlist_is_stricter_than_raw_active_can():
    named_nac_frame = bytes.fromhex("052FD60003000000")
    arbitrary_io_control = bytes.fromhex("042F123403000000")

    assert authorize_diagnostic_can_frame(0x764, False, named_nac_frame).allowed is False
    assert authorize_psa_lab_can_frame(0x764, False, named_nac_frame).allowed is True
    assert authorize_psa_lab_can_frame(0x764, False, arbitrary_io_control).allowed is False
    assert authorize_psa_lab_can_frame(0x752, False, named_nac_frame).allowed is False
    assert authorize_psa_lab_can_frame(0x7B0, False, bytes.fromhex("0322F19000000000")).allowed is True
    assert authorize_psa_lab_can_frame(0x7B0, False, bytes.fromhex("042E123400000000")).allowed is False


def test_psa_seed_key_and_raw_did_api(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "session_dir", tmp_path)

    seed = client.post("/api/diagnostic/psa/seed-key", json={
        "seed_hex": "12345678",
        "application_key_hex": "D91C",
    })
    assert seed.status_code == 200
    assert seed.json()["response_key_hex"] == "57F61D6F"
    assert seed.json()["transmitted"] is False

    did = client.post("/api/diagnostic/psa/ecus/bsi/dids/0xF190")
    assert did.status_code == 200
    assert did.json()["value"] == "VF3LJHNYWJS123456"


def test_psa_actions_are_locked_by_default():
    response = client.post("/api/diagnostic/psa/actions/nac_black_screen", json={
        "confirmation": "ACTIVER NAC_BLACK_SCREEN",
        "vehicle_stationary": True,
        "ignition_on_engine_off": True,
        "stable_battery_voltage": True,
        "workshop_or_private_site": True,
        "duration_ms": 250,
    })
    assert response.status_code == 403
    assert "PSA_ACTUATOR_ENABLED=false" in response.json()["detail"]


def test_virtual_named_action_always_sends_stop(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "session_dir", tmp_path)
    monkeypatch.setattr(settings, "psa_actuator_enabled", True)
    monkeypatch.setattr(settings, "read_only", False)
    monkeypatch.setattr(settings, "can_tx_enabled", True)
    monkeypatch.setattr(psa_advanced.time, "sleep", lambda _seconds: None)

    result = execute_named_action("nac_black_screen", PsaActionRequest(
        confirmation="ACTIVER NAC_BLACK_SCREEN",
        vehicle_stationary=True,
        ignition_on_engine_off=True,
        stable_battery_voltage=True,
        workshop_or_private_site=True,
        duration_ms=250,
    ))

    assert result.executed is True
    assert result.started_response_hex == "6FD6000300"
    assert result.stopped_response_hex == "6FD60000"
    assert result.session_id


def test_virtual_security_access_computes_and_transmits_derived_key(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "session_dir", tmp_path)
    monkeypatch.setattr(settings, "psa_security_access_enabled", True)
    monkeypatch.setattr(settings, "read_only", False)
    monkeypatch.setattr(settings, "can_tx_enabled", True)

    result = unlock_configuration("telematics", PsaUnlockRequest(
        application_key_hex="D91C",
        confirmation="DEVERROUILLER TELEMATICS",
        vehicle_stationary=True,
        ignition_on_engine_off=True,
        stable_battery_voltage=True,
        workshop_or_private_site=True,
    ))

    assert result.unlocked is True
    assert result.seed_hex == "12345678"
    assert result.response_key_hex == "57F61D6F"
    assert result.response_hex == "6704"
