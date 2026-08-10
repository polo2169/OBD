import json

from fastapi.testclient import TestClient

from app.config import settings
from app.main import app
from app.api import learn_routes, routes
from app import operating_mode
from app.learn.models import CaptureStart
from app.transports import selection


client = TestClient(app)


def test_system_status_exposes_wifi_gateway(monkeypatch):
    monkeypatch.setattr(settings, "transport", "esp32_wifi")
    monkeypatch.setattr(settings, "esp32_wifi_host", "192.168.4.1")
    monkeypatch.setattr(settings, "esp32_wifi_port", 35000)
    response = client.get("/api/system/status")
    assert response.status_code == 200
    assert response.json()["gateway_endpoint"] == "192.168.4.1:35000"


def test_operating_mode_switch_requires_checks_and_audits_vin(tmp_path, monkeypatch):
    vin = "VF3LJHNYWJS123456"

    class IdleCapture:
        @staticmethod
        def status():
            return type("Status", (), {"active": False})()

    monkeypatch.setattr(settings, "transport", "virtual")
    monkeypatch.setattr(settings, "can_tx_enabled", True)
    monkeypatch.setattr(settings, "read_only", True)
    monkeypatch.setattr(settings, "runtime_mode_switch_enabled", True)
    monkeypatch.setattr(settings, "security_audit_file", tmp_path / "security-audit.jsonl")
    monkeypatch.setattr(operating_mode, "capture_manager", IdleCapture())
    monkeypatch.setattr(operating_mode, "active_vehicle", lambda: {"vin": vin})

    refused = client.post("/api/system/operating-mode", json={
        "mode": "maintenance",
        "confirmation": "ACTIVER MAINTENANCE",
        "vin": vin,
    })
    assert refused.status_code == 403
    assert settings.read_only is True

    armed = client.post("/api/system/operating-mode", json={
        "mode": "maintenance",
        "confirmation": "ACTIVER MAINTENANCE",
        "vin": vin,
        "vehicle_stationary": True,
        "ignition_on_engine_off": True,
        "stable_battery_voltage": True,
        "workshop_or_private_site": True,
    })
    assert armed.status_code == 200
    assert armed.json()["mode"] == "maintenance"
    assert settings.read_only is False
    assert vin in (tmp_path / "security-audit.jsonl").read_text(encoding="utf-8")

    safe = client.post("/api/system/operating-mode", json={"mode": "read_only", "vin": vin})
    assert safe.status_code == 200
    assert safe.json()["mode"] == "read_only"
    assert settings.read_only is True


def test_system_transports_lists_esp32_choices():
    response = client.get("/api/system/transports")
    assert response.status_code == 200
    payload = response.json()
    assert any(option["transport"] == "esp32_wifi" for option in payload["options"])
    assert any(option["transport"] == "esp32_serial" for option in payload["options"])


def test_system_transport_connect_probes_and_persists(tmp_path, monkeypatch):
    class FakeEsp32Transport:
        hello = {"type": "hello", "protocol": 3, "readonly": True, "can_ready": True}

        def open(self):
            return None

        def close(self):
            return None

    preference_path = tmp_path / "transport_selection.json"
    monkeypatch.setattr(settings, "transport", "esp32_serial")
    monkeypatch.setattr(settings, "serial_port", "/dev/cu.test-esp32")
    monkeypatch.setattr(settings, "transport_selection_file", preference_path)
    monkeypatch.setattr(selection, "build_transport", lambda: FakeEsp32Transport())

    response = client.post("/api/system/transport/connect", json={
        "transport": "esp32_serial",
        "endpoint": "/dev/cu.test-esp32",
        "baud": 921600,
    })

    assert response.status_code == 200
    assert response.json()["verified"] is True
    assert response.json()["hello"]["protocol"] == 3
    assert json.loads(preference_path.read_text())["endpoint"] == "/dev/cu.test-esp32"


def test_targeted_did_endpoint(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "session_dir", tmp_path)
    response = client.post("/api/diagnostic/ecus/engine/dids/0xF190")
    assert response.status_code == 200
    assert response.json()["value"] == "VF3LJHNYWJS123456"


def test_unknown_did_is_not_probed():
    response = client.post("/api/diagnostic/ecus/engine/dids/0x1234")
    assert response.status_code == 404


def test_sensor_snapshot_endpoint():
    response = client.post("/api/sensors/snapshot")
    assert response.status_code == 200
    payload = response.json()
    assert any(item["key"] == "engine_rpm" for item in payload["values"])
    assert payload["debug"]["session_id"]


def test_live_sensor_registry_crud_is_vin_scoped_and_archived():
    vin = "VF3LJHNYWJS123456"
    created = client.post("/api/live-data/sensors", json={
        "source_key": "OBD01.engine_rpm",
        "vin": vin,
        "label": "Régime atelier",
        "description": "Vue locale du régime.",
        "category": "Injection",
        "unit": "tr/min",
        "factor": 1,
        "offset": 0,
    })
    assert created.status_code == 200
    key = created.json()["key"]
    assert key.startswith("CUSTOM.REGIME_ATELIER_")

    listed = client.get(f"/api/live-data/sensors?vin={vin}")
    assert [item["key"] for item in listed.json()] == [key]
    assert client.get("/api/live-data/sensors?vin=ZFA31200001234567").json() == []

    updated = client.put(f"/api/live-data/sensors/{key}", json={
        "label": "Régime corrigé",
        "description": "Capteur local modifié.",
        "category": "Moteur",
        "unit": "tr/min",
        "factor": 0.5,
        "offset": 10,
        "archived": False,
    })
    assert updated.status_code == 200
    assert updated.json()["factor"] == 0.5

    archived = client.delete(f"/api/live-data/sensors/{key}")
    assert archived.status_code == 200
    assert archived.json()["archived"] is True
    assert client.get(f"/api/live-data/sensors?vin={vin}").json() == []
    assert len(client.get(f"/api/live-data/sensors?vin={vin}&include_archived=true").json()) == 1


def test_learn_capture_is_passive_and_live_data_reads_are_explicit(monkeypatch):
    class FakeCaptureManager:
        def __init__(self):
            self.active = False
            self.starts = []
            self.mode = None

        def status(self):
            return type("Status", (), {"active": self.active, "vin": None, "mode": self.mode})()

        def start(self, *args):
            self.starts.append(args)
            self.active = True
            self.mode = "live_data" if args[-1] is True else "learn_passive"

        def reset_latest_frames(self):
            return None

    learn_manager = FakeCaptureManager()
    live_manager = FakeCaptureManager()
    monkeypatch.setattr(learn_routes, "capture_manager", learn_manager)
    monkeypatch.setattr(routes, "capture_manager", live_manager)
    monkeypatch.setattr(learn_routes, "passive_sensor_snapshot", lambda **kwargs: kwargs)
    monkeypatch.setattr(routes, "passive_sensor_snapshot", lambda **kwargs: kwargs)

    learn_routes.detect_passive_sensors(vin=None)
    routes.live_data_detect(vin=None)

    assert learn_manager.starts[0][-1] is False
    assert live_manager.starts[0][-1] is True


def test_capture_start_routes_keep_learn_and_live_data_modes_separate(monkeypatch):
    class FakeCaptureManager:
        def __init__(self):
            self.starts = []

        def status(self):
            return type("Status", (), {"active": False, "vin": None, "mode": None})()

        def start(self, *args):
            self.starts.append(args)
            return type("Started", (), {})()

    learn_manager = FakeCaptureManager()
    live_manager = FakeCaptureManager()
    monkeypatch.setattr(learn_routes, "capture_manager", learn_manager)
    monkeypatch.setattr(routes, "capture_manager", live_manager)

    learn_routes.start_capture(CaptureStart(name="Corrélation passive"))
    routes.live_data_start(CaptureStart(name="Direct atelier"))

    assert learn_manager.starts[0][-1] is False
    assert live_manager.starts[0][-1] is True


def test_opendbc_catalog_endpoint():
    response = client.get("/api/learn/opendbc/catalog")
    assert response.status_code == 200
    payload = response.json()
    assert payload["source"]["loaded"] is True
    assert payload["source"]["message_count"] == 107
    assert any(
        message["name"] == "Dyn_CMM" and message["arbitration_id"] == 0x208
        for message in payload["messages"]
    )


def test_dtc_clear_is_locked_by_default():
    response = client.post("/api/diagnostic/ecus/engine/dtcs/clear", json={
        "confirmation": "EFFACER ENGINE",
        "vehicle_stationary": True,
        "ignition_on_engine_off": True,
        "stable_battery_voltage": True,
        "report_saved": True,
    })
    assert response.status_code == 403
    assert "DTC_CLEAR_ENABLED=false" in response.json()["detail"]


def test_trace_import_endpoint_never_transmits(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "diagnostic_trace_import_dir", tmp_path)
    response = client.post("/api/diagnostic/traces/import", json={
        "name": "lecture-vin.log",
        "vehicle_profile": "peugeot_308_t9_2018",
        "source_format": "text",
        "content": "TX 752#0322F18600000000\nRX 652#0462F18601000000\n",
    })
    assert response.status_code == 200
    payload = response.json()
    assert payload["exchange_count"] == 1
    assert payload["observed_dids"][0]["did"] == 0xF186
    assert payload["observed_actions"] == []


def test_observed_dtcs_are_persisted_and_enriched(tmp_path, monkeypatch):
    path = tmp_path / "observed_dtcs.json"
    monkeypatch.setattr(settings, "observed_dtcs_file", path)

    recorded = client.post("/api/diagnostic/dtcs/observed", json={
        "code": "c0031",
        "ecu_key": "abs_esp",
        "source": "user_reported",
        "note": "Relevé de test",
    })

    assert recorded.status_code == 200
    assert recorded.json()["code"] == "C0031"
    assert recorded.json()["ecu_name"] == "ABS / ESP"
    assert recorded.json()["title"] == "Capteur de vitesse de roue avant gauche"
    assert path.exists()

    reopened = client.get("/api/diagnostic/dtcs/observed")
    assert reopened.status_code == 200
    assert [item["code"] for item in reopened.json()] == ["C0031"]


def test_behavioral_analysis_is_saved_and_can_be_reopened(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "session_dir", tmp_path)
    session_id = "learn-20260731T130000Z-api"
    events = [
        {
            "type": "meta",
            "timestamp_us": 1_000_000,
            "session_id": session_id,
            "name": "Test API",
            "source": "fixture",
        },
        {
            "type": "marker",
            "timestamp_us": 2_000_000,
            "name": "frein_appuye",
            "note": "essai",
        },
    ]
    (tmp_path / f"{session_id}.jsonl").write_text(
        "\n".join(json.dumps(event) for event in events) + "\n",
        encoding="utf-8",
    )

    response = client.post(
        f"/api/learn/correlate/{session_id}",
        json={"before_ms": 1000, "after_ms": 1000, "min_samples": 3},
    )
    assert response.status_code == 200
    assert response.json()["session_id"] == session_id
    assert (tmp_path / f"{session_id}.correlations.json").exists()

    reopened = client.get(f"/api/learn/correlations/{session_id}")
    assert reopened.status_code == 200
    assert reopened.json()["correlations"][0]["marker"] == "frein_appuye"
