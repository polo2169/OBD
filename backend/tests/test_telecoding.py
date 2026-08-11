from fastapi.testclient import TestClient

from app.config import settings
from app.diagnostic import telecoding
from app.main import app
from app.transports.virtual import VirtualVehicleTransport


client = TestClient(app)


def test_catalog_keeps_variants_separate_and_normalizes_structured_fields():
    bsi = client.get("/api/diagnostic/psa/ecus/bsi/telecoding/catalog")
    assert bsi.status_code == 200
    variants = bsi.json()["variants"]
    assert [variant["id"] for variant in variants] == ["BSI2010"]
    assert variants[0]["zone_count"] == 516
    zone = next(item for item in variants[0]["zones"] if item["did_hex"] == "2200")
    assert zone["writable"] is True
    assert zone["fields"][0]["key"] == "CFG_APQ_BSI_TABLEJAUGE_000"
    assert zone["fields"][0]["options"][1]["encoded_hex"] == "01"

    telematics = client.get("/api/diagnostic/psa/ecus/telematics/telecoding/catalog")
    assert telematics.status_code == 200
    assert {variant["id"] for variant in telematics.json()["variants"]} == {"IVI", "NAC", "RCC"}

    esp = client.get("/api/diagnostic/psa/ecus/abs_esp/telecoding/catalog")
    assert esp.status_code == 200
    esp_variants = esp.json()["variants"]
    assert [variant["id"] for variant in esp_variants] == ["ESP90"]
    assert esp_variants[0]["write_supported"] is False
    assert esp_variants[0]["security_keys"] == []
    assert "écriture verrouillée" in esp.json()["warning"]


def test_esp_profile_rejects_an_incompatible_mk100_schema():
    response = client.post(
        "/api/diagnostic/psa/ecus/abs_esp/telecoding/snapshots",
        json={"variant_id": "ESPMK100_UDS", "did": 0x2101},
    )
    assert response.status_code == 422
    assert "ESP90" in response.json()["detail"]


def test_snapshot_preview_execute_and_backup_are_one_verified_workflow(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "session_dir", tmp_path / "sessions")
    monkeypatch.setattr(settings, "telecoding_backup_dir", tmp_path / "telecoding")
    monkeypatch.setattr(settings, "psa_telecoding_write_enabled", True)
    monkeypatch.setattr(settings, "psa_security_access_enabled", True)
    monkeypatch.setattr(settings, "read_only", False)
    monkeypatch.setattr(settings, "can_tx_enabled", True)
    monkeypatch.setattr(telecoding, "active_vehicle", lambda: {"vin": "VF3LJHNYWJS123456"})

    snapshot_response = client.post(
        "/api/diagnostic/psa/ecus/bsi/telecoding/snapshots",
        json={"variant_id": "BSI2010", "did": 0x2200},
    )
    assert snapshot_response.status_code == 200
    snapshot = snapshot_response.json()
    assert snapshot["raw_hex"] == "00"
    assert snapshot["vin"] == "VF3LJHNYWJS123456"
    assert snapshot["fields"][0]["value"] == "Type 0"

    changes = [{
        "field_key": "CFG_APQ_BSI_TABLEJAUGE_000",
        "option_key": "option-1",
    }]
    preview_response = client.post(
        "/api/diagnostic/psa/telecoding/preview",
        json={"snapshot_id": snapshot["snapshot_id"], "changes": changes},
    )
    assert preview_response.status_code == 200
    preview = preview_response.json()
    assert preview["executable"] is True
    assert preview["raw_before_hex"] == "00"
    assert preview["raw_after_hex"] == "01"
    assert preview["changed_byte_indexes"] == [0]

    execute_response = client.post(
        "/api/diagnostic/psa/telecoding/execute",
        json={
            "snapshot_id": snapshot["snapshot_id"],
            "changes": changes,
            "plan_hash": preview["plan_hash"],
            "application_key_hex": "E4D8",
            "confirmation": "TELECODER BSI 2200",
            "vehicle_stationary": True,
            "ignition_on_engine_off": True,
            "stable_battery_voltage": True,
            "workshop_or_private_site": True,
        },
    )
    assert execute_response.status_code == 200
    result = execute_response.json()
    assert result["verified"] is True
    assert result["raw_before_hex"] == "00"
    assert result["raw_after_hex"] == "01"
    assert (tmp_path / "telecoding" / "executions" / "VF3LJHNYWJS123456").is_dir()
    assert '"outcome": "verified"' in (tmp_path / "security_audit.jsonl").read_text()

    backups = client.get("/api/diagnostic/psa/telecoding/backups?ecu_key=bsi")
    assert backups.status_code == 200
    assert backups.json()[0]["snapshot_id"] == snapshot["snapshot_id"]


def test_execute_aborts_before_write_when_snapshot_is_stale(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "session_dir", tmp_path / "sessions")
    monkeypatch.setattr(settings, "telecoding_backup_dir", tmp_path / "telecoding")
    monkeypatch.setattr(settings, "psa_telecoding_write_enabled", True)
    monkeypatch.setattr(settings, "psa_security_access_enabled", True)
    monkeypatch.setattr(settings, "read_only", False)
    monkeypatch.setattr(settings, "can_tx_enabled", True)
    monkeypatch.setattr(telecoding, "active_vehicle", lambda: {"vin": "VF3LJHNYWJS123456"})

    snapshot = client.post(
        "/api/diagnostic/psa/ecus/bsi/telecoding/snapshots",
        json={"variant_id": "BSI2010", "did": 0x2200},
    ).json()
    changes = [{
        "field_key": "CFG_APQ_BSI_TABLEJAUGE_000",
        "option_key": "option-1",
    }]
    preview = client.post(
        "/api/diagnostic/psa/telecoding/preview",
        json={"snapshot_id": snapshot["snapshot_id"], "changes": changes},
    ).json()
    VirtualVehicleTransport._telecoding_values[(0x752, 0x2200)] = bytes.fromhex("02")

    response = client.post(
        "/api/diagnostic/psa/telecoding/execute",
        json={
            "snapshot_id": snapshot["snapshot_id"],
            "changes": changes,
            "plan_hash": preview["plan_hash"],
            "application_key_hex": "E4D8",
            "confirmation": "TELECODER BSI 2200",
            "vehicle_stationary": True,
            "ignition_on_engine_off": True,
            "stable_battery_voltage": True,
            "workshop_or_private_site": True,
        },
    )
    assert response.status_code == 409
    assert "Aucune écriture" in response.json()["detail"]
    assert VirtualVehicleTransport._telecoding_values[(0x752, 0x2200)] == bytes.fromhex("02")
