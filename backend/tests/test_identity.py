from fastapi.testclient import TestClient

from app.config import settings
from app.diagnostic.identity import (
    decode_obd_vin,
    manufacturer_from_vin,
    validate_vin,
)
from app.main import app


client = TestClient(app)


def test_vin_decoder_accepts_standard_mode09_response_and_rejects_bad_charset():
    response = bytes.fromhex("490201") + b"ZFA31200001234567"
    assert decode_obd_vin(response) == "ZFA31200001234567"
    assert validate_vin("ZFA31200001234567") is True
    assert validate_vin("ZFA312000I1234567") is False
    assert manufacturer_from_vin("ZFA31200001234567") == "Fiat"


def test_vehicle_catalog_includes_peugeot_and_fiat():
    response = client.get("/api/database/vehicles")
    assert response.status_code == 200
    profiles = {item["key"]: item for item in response.json()}
    assert profiles["peugeot_308_t9_2018"]["manufacturer"] == "Peugeot"
    assert profiles["fiat_500_generic"]["manufacturer"] == "Fiat"
    assert profiles["fiat_500_generic"]["identity_scope"] == "identity_only"


def test_trafic_phase1_catalog_requires_manual_identity_and_keeps_passive_can():
    response = client.get("/api/database/vehicles")
    profiles = {item["key"]: item for item in response.json()}

    phase1 = profiles["renault_trafic_x83_ph1"]
    assert phase1["year"] == "2001-2005"
    assert phase1["identity_scope"] == "manual_only"
    assert phase1["vin_methods"] == []
    assert phase1["identity_protocols"] == []
    assert phase1["can_bitrate"] == 250000


def test_manual_vehicle_creation_is_saved_without_vehicle_io(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "session_dir", tmp_path / "sessions")
    monkeypatch.setattr(settings, "diagnostic_history_dir", tmp_path / "diagnostics")

    response = client.post("/api/diagnostic/vehicles", json={
        "vehicle_profile": "renault_trafic_x83_ph1",
        "vin": "vf1flaha6by123456",
    })

    assert response.status_code == 200
    payload = response.json()
    assert payload["vin"] == "VF1FLAHA6BY123456"
    assert payload["transport"] == "manual:no-vehicle-io"
    assert payload["found"] is True
    assert payload["profile_match"] is True
    assert payload["attempts"] == []
    assert payload["debug"]["event_types"]["vehicle_identity_manual"] == 1

    vehicles = client.get("/api/diagnostic/vehicles").json()
    saved = next(vehicle for vehicle in vehicles if vehicle["vin"] == payload["vin"])
    assert saved["vehicle_profile"] == "renault_trafic_x83_ph1"
    assert saved["is_active"] is True


def test_manual_vehicle_creation_rejects_invalid_vin():
    response = client.post("/api/diagnostic/vehicles", json={
        "vehicle_profile": "renault_trafic_x83_ph1",
        "vin": "VF1INVALIDVIN00000",
    })

    assert response.status_code == 422


def test_peugeot_identity_uses_uds_f190_and_is_saved(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "session_dir", tmp_path)
    response = client.post("/api/diagnostic/identity", json={
        "vehicle_profile": "peugeot_308_t9_2018",
    })
    assert response.status_code == 200
    payload = response.json()
    assert payload["vin"] == "VF3LJHNYWJS123456"
    assert payload["detected_manufacturer"] == "Peugeot"
    assert payload["profile_match"] is True
    assert payload["attempts"][0]["protocol"] == "uds"
    assert payload["attempts"][0]["command_hex"] == "22F190"
    assert payload["debug"]["trace_file"]
    assert list(tmp_path.glob("*.jsonl"))


def test_fiat_identity_prefers_standard_obd_mode09(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "session_dir", tmp_path)
    response = client.post("/api/diagnostic/identity", json={
        "vehicle_profile": "fiat_500_generic",
    })
    assert response.status_code == 200
    payload = response.json()
    assert payload["vin"] == "ZFA31200001234567"
    assert payload["wmi"] == "ZFA"
    assert payload["detected_manufacturer"] == "Fiat"
    assert payload["attempts"][0]["command_hex"] == "0902"
    assert payload["fields"][0]["value"] == "SIM-CAL-2026"
    assert any("limité à l'identification" in warning for warning in payload["warnings"])


def test_renault_trafic_x83_identity_is_saved_as_a_new_garage_vehicle(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "session_dir", tmp_path / "sessions")
    monkeypatch.setattr(settings, "diagnostic_history_dir", tmp_path / "diagnostics")

    response = client.post("/api/diagnostic/identity", json={
        "vehicle_profile": "renault_trafic_x83",
    })

    assert response.status_code == 200
    payload = response.json()
    assert payload["vin"] == "VF1FLAHA6BY123456"
    assert payload["detected_manufacturer"] == "Renault"
    assert payload["profile_match"] is True
    assert payload["attempts"][0]["protocol"] == "obd"
    assert payload["attempts"][0]["command_hex"] == "0902"

    vehicles = client.get("/api/diagnostic/vehicles").json()
    saved = next(vehicle for vehicle in vehicles if vehicle["vin"] == payload["vin"])
    assert saved["vehicle_profile"] == "renault_trafic_x83"
    assert saved["manufacturer"] == "Renault"
    assert saved["is_active"] is True


def test_unknown_vehicle_profile_is_rejected_without_transport_access():
    response = client.post("/api/diagnostic/identity", json={
        "vehicle_profile": "../../inconnu",
    })
    assert response.status_code == 404
