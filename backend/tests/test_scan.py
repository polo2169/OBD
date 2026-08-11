from contextlib import contextmanager

from app.config import settings
from app.diagnostic.scanner import clear_ecu_dtcs, read_ecu_did, scan_vehicle
from app.database import KnowledgeBase
from app.diagnostic.obd import PID_BY_ID, live_pid_definitions, snapshot_sensors
from app.diagnostic.isotp import UdsSession
from app.diagnostic.uds import decode_dtc_status, format_sae_dtc
from app.models import ClearDtcRequest
from app.diagnostic.uds import request
from app.transports.virtual import VirtualVehicleTransport


class TransactionRecordingVirtualTransport(VirtualVehicleTransport):
    def __init__(self) -> None:
        super().__init__()
        self.live_mute_requests: list[bool] = []
        self.sent_frames = []

    def send(self, frame):
        self.sent_frames.append(frame)
        super().send(frame)

    @contextmanager
    def diagnostic_transaction(self, *, mute_live: bool = False):
        self.live_mute_requests.append(mute_live)
        yield


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
    assert abs_ecu.dtcs[0].title == "Capteur de vitesse de roue avant gauche"
    assert abs_ecu.dtcs[0].state == "active"
    assert report.dtc_summary.active >= 1
    assert report.scan_id
    assert "confirmed" in abs_ecu.dtcs[0].status_labels
    esp_zones = {item.did: item for item in abs_ecu.identification if 0x2100 <= item.did <= 0x2103}
    assert set(esp_zones) == {0x2100, 0x2101, 0x2102, 0x2103}
    assert esp_zones[0x2102].raw_hex == "06000000A400"
    assert esp_zones[0x2103].raw_hex == "06FFFDFFFF"
    assert esp_zones[0x2101].telecoding is not None
    gearbox = next(ecu for ecu in report.ecus if ecu.key == "gearbox")
    gearbox_zones = {item.did: item for item in gearbox.identification}
    assert gearbox_zones[0x2100].raw_hex == "00FEFFFCFF003801"
    assert gearbox_zones[0x2101].raw_hex == "00FEFFFEFFBFBE"
    assert gearbox_zones[0x2101].telecoding is not None
    assert report.debug.session_id
    assert report.debug.event_types["uds_request"] > 0
    assert engine.active_session == 1
    assert engine.active_session_source == "did_f186"
    assert engine.probe_attempts == [{
        "request_hex": "1001",
        "response_hex": "5001003201F4",
        "outcome": "positive",
    }]


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
        if key == "abs_esp":
            assert ecus[key].confidence == "vehicle_identified"
        else:
            assert ecus[key].confidence == "community_family_catalog"

    assert ecus["front_camera"].optional is True
    assert ecus["abs_esp"].optional is False

    profile_abs = next(item for item in KnowledgeBase().ecus() if item.key == "abs_esp")
    assert profile_abs.name == "ABS / ESP90 Bosch 9.0"
    assert profile_abs.telecoding_variant == "ESP90"
    assert profile_abs.telecoding_write_allowed is False
    assert profile_abs.identification_dids == [0x2100, 0x2101, 0x2102, 0x2103]
    assert profile_abs.dtc_catalogs == ["ESP90", "ABRASR"]
    assert profile_abs.dtc_status_masks == [0x09, 0xFF]

    profile_gearbox = next(item for item in KnowledgeBase().ecus() if item.key == "gearbox")
    assert profile_gearbox.name == "Aisin TF-71SC / AT6 III (EAT6)"
    assert profile_gearbox.confidence == "vehicle_identified"
    assert profile_gearbox.flow_control_blocksize == 0
    assert profile_gearbox.isotp_tx_padding is None
    assert profile_gearbox.identification_dids == [0x2100, 0x2101]
    assert profile_gearbox.telecoding_variant == "BVA_AM6_AT6_UDS"
    assert profile_gearbox.telecoding_write_allowed is False


def test_dtc_decoder_keeps_failure_type_separate():
    assert format_sae_dtc(0x40, 0x31) == "C0031"
    assert decode_dtc_status(0x2F) == [
        "test_failed",
        "test_failed_this_operation_cycle",
        "pending",
        "confirmed",
        "test_failed_since_last_clear",
    ]


def test_dtc_status_classification_does_not_turn_unfinished_tests_into_faults():
    from app.diagnostic.dtc_status import classify_dtc_status

    assert classify_dtc_status(0x2F)["state"] == "active"
    assert classify_dtc_status(0x20)["state"] == "historical"
    assert classify_dtc_status(0x40)["state"] == "not_tested"
    assert classify_dtc_status(0x50)["state"] == "not_tested"


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


def test_fiat_live_profile_exposes_extended_gasoline_obd_sensors():
    definitions = {item.pid: item for item in live_pid_definitions("fiat_500_generic")}

    assert {
        0x06, 0x07, 0x0A, 0x0B, 0x0E, 0x0F, 0x10, 0x11, 0x14, 0x15,
        0x2E, 0x42, 0x44, 0x45, 0x47, 0x48, 0x49, 0x4A, 0x4C, 0x5A, 0x5D,
    } <= definitions.keys()
    assert PID_BY_ID[0x14].decoder(bytes.fromhex("80FF")) == 0.64
    assert PID_BY_ID[0x10].decoder(bytes.fromhex("0208")) == 5.2
    assert PID_BY_ID[0x47].decoder(bytes.fromhex("80")) == 50.2
    assert PID_BY_ID[0x43].decoder(bytes.fromhex("00FF")) == 100
    assert PID_BY_ID[0x5D].decoder(bytes.fromhex("6900")) == 0


def test_obd_session_routes_requests_to_live_bus():
    events: list[dict] = []
    transport = TransactionRecordingVirtualTransport()
    transport.set_debug_sink(events.append)
    transport.open()
    try:
        with UdsSession(transport, 0x7E0, 0x7E8, tx_bus="live") as session:
            assert session.request_obd(bytes.fromhex("010C")) == bytes.fromhex("410C0C30")
    finally:
        transport.close()

    assert any(
        event.get("type") == "can_frame"
        and event.get("direction") == "tx"
        and event.get("bus") == "live"
        for event in events
    )
    assert transport.live_mute_requests == [False]


def test_diagnostic_session_requests_live_bus_mute():
    transport = TransactionRecordingVirtualTransport()
    transport.open()
    try:
        with UdsSession(transport, 0x7E0, 0x7E8) as session:
            assert session.request(bytes.fromhex("22F190")).startswith(bytes.fromhex("62F190"))
    finally:
        transport.close()

    assert transport.live_mute_requests == [True]


def test_unpadded_isotp_session_sends_three_byte_flow_control():
    transport = TransactionRecordingVirtualTransport()
    transport.response_ids[0x6A9] = 0x689
    transport.open()
    try:
        with UdsSession(
            transport,
            0x6A9,
            0x689,
            tx_padding=None,
            flow_control_blocksize=0,
        ) as session:
            assert session.request(bytes.fromhex("222100")) == bytes.fromhex(
                "62210000FEFFFCFF003801"
            )
    finally:
        transport.close()

    flow_controls = [
        frame for frame in transport.sent_frames
        if frame.data and frame.data[0] >> 4 == 0x3
    ]
    assert [frame.data for frame in flow_controls] == [bytes.fromhex("300000")]


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
    assert result.request_hex == "14FFFFFF"
    assert result.before_dtcs == []
    assert result.after_dtcs == []
    assert result.verified is True
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
