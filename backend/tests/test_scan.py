from app.config import settings
from app.diagnostic.scanner import clear_ecu_dtcs, read_ecu_did, scan_vehicle
from app.diagnostic.obd import snapshot_sensors
from app.diagnostic.uds import decode_dtc_status, format_sae_dtc
from app.models import ClearDtcRequest
from app.diagnostic.uds import request
from app.transports.virtual import VirtualVehicleTransport


def test_virtual_scan():
    report = scan_vehicle()
    assert report.transport == "virtual"
    assert report.readonly is True
    assert any(ecu.detected for ecu in report.ecus)
    engine = next(ecu for ecu in report.ecus if ecu.key == "engine")
    assert engine.vin == "VF3LJHNYWJS123456"
    assert {item.did for item in engine.identification} >= {0xF180, 0xF190}
    abs_ecu = next(ecu for ecu in report.ecus if ecu.key == "abs_esp")
    assert abs_ecu.dtcs[0].code == "C0031"
    assert abs_ecu.dtcs[0].title == "Front left wheel speed sensor"
    assert "confirmed" in abs_ecu.dtcs[0].status_labels
    assert report.debug.session_id
    assert report.debug.event_types["uds_request"] > 0


def test_multiframe_vin_response_is_reassembled():
    transport = VirtualVehicleTransport()
    transport.open()
    try:
        response = request(transport, 0x7E0, 0x7E8, bytes.fromhex("22F190"))
    finally:
        transport.close()

    assert response == bytes.fromhex("62F190") + b"VF3LJHNYWJS123456"


def test_targeted_did_read_uses_catalog_codec():
    result = read_ecu_did("engine", 0xF190)
    assert result.value == "VF3LJHNYWJS123456"
    assert result.codec == "ascii"


def test_t9_profile_contains_sourced_psa_ecus():
    report = scan_vehicle()
    ecus = {ecu.key: ecu for ecu in report.ecus}

    expected_addresses = {
        "engine": (0x6A8, 0x688),
        "abs_esp": (0x6AD, 0x68D),
        "bsi": (0x752, 0x652),
        "front_camera": (0x74A, 0x64A),
        "airbag": (0x744, 0x644),
    }
    for key, (request_id, response_id) in expected_addresses.items():
        assert ecus[key].request_id == request_id
        assert ecus[key].response_id == response_id
        assert ecus[key].source
        assert ecus[key].confidence == "community_family_catalog"

    assert ecus["front_camera"].optional is True
    assert ecus["abs_esp"].optional is False


def test_dtc_decoder_keeps_failure_type_separate():
    assert format_sae_dtc(0x40, 0x31) == "C0031"
    assert decode_dtc_status(0x2F) == [
        "test_failed",
        "test_failed_this_operation_cycle",
        "pending",
        "confirmed",
        "test_failed_since_last_clear",
    ]


def test_virtual_sensor_only_snapshot():
    snapshot = snapshot_sensors()
    values = {item.key: item.value for item in snapshot.values}
    assert values["engine_rpm"] == 780
    assert values["coolant_temperature"] == 88
    assert values["control_module_voltage"] == 12.636
    assert values["intake_manifold_pressure"] == 100
    assert values["fuel_rail_gauge_pressure"] == 40_000
    assert values["commanded_equivalence_ratio"] == 1
    assert values["fuel_rate"] == 2.5
    assert 0x0C in snapshot.supported_pids
    assert 0x23 in snapshot.supported_pids
    assert snapshot.debug.event_types["obd_request"] > 0


def test_explicit_virtual_dtc_clear_workflow(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "session_dir", tmp_path)
    monkeypatch.setattr(settings, "dtc_clear_enabled", True)
    monkeypatch.setattr(settings, "read_only", False)
    monkeypatch.setattr(settings, "can_tx_enabled", True)
    result = clear_ecu_dtcs("engine", ClearDtcRequest(
        confirmation="EFFACER ENGINE",
        vehicle_stationary=True,
        ignition_on_engine_off=True,
        stable_battery_voltage=True,
        report_saved=True,
    ))
    assert result.cleared
    assert result.response_hex == "54"
    assert result.session_id


def test_safety_ecu_clear_has_an_additional_lock(monkeypatch):
    monkeypatch.setattr(settings, "dtc_clear_enabled", True)
    monkeypatch.setattr(settings, "read_only", False)
    monkeypatch.setattr(settings, "can_tx_enabled", True)
    monkeypatch.setattr(settings, "safety_ecu_clear_enabled", False)
    try:
        clear_ecu_dtcs("abs_esp", ClearDtcRequest(
            confirmation="EFFACER ABS_ESP",
            vehicle_stationary=True,
            ignition_on_engine_off=True,
            stable_battery_voltage=True,
            report_saved=True,
        ))
    except PermissionError as exc:
        assert "SAFETY_ECU_CLEAR_ENABLED=false" in str(exc)
    else:
        raise AssertionError("L'effacement ABS aurait dû rester verrouillé.")
