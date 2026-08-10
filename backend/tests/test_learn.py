import json
import time

from app.config import settings
from app.learn.analyzer import analyze_behavior, list_sessions
from app.learn.capture import PassiveCaptureManager, capture_manager
from app.learn.isotp import parse_isotp_frame, uds_service
from app.learn.models import CaptureGpsPosition, CaptureStatus, CorrelationOptions, PassiveSensorOverride, ReplayGpsPoint, ReplaySample, SessionVehicleAssignment
from app.learn.opendbc import get_opendbc_decoder
from app.learn.passive_sensors import passive_sensor_snapshot
from app.learn.replay import _apply_confirmed_road_route, _apply_gps_route, _filter_fuel_level, prepare_replay, replay_geojson
from app.learn.sensor_metadata import save_override
from app.learn.session_vehicle import assign_session_vehicle
from app.learn.validation import validate_replay
from app.safety import authorize_uds


def test_single_frame_parse():
    parsed = parse_isotp_frame(bytes.fromhex("0322F19000000000"))
    assert parsed is not None
    assert parsed.complete
    assert parsed.payload == bytes.fromhex("22F190")
    assert uds_service(parsed.payload) == 0x22


def test_session_can_be_attached_to_a_vehicle_without_rewriting_raw_capture(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "session_dir", tmp_path)
    session_id = "learn-20260802T120000Z-garage"
    raw_path = tmp_path / f"{session_id}.jsonl"
    raw_payload = json.dumps({
        "type": "meta",
        "timestamp_us": 1_800_000_000_000_000,
        "session_id": session_id,
        "name": "Ancien trajet",
        "source": "fixture",
    }) + "\n"
    raw_path.write_text(raw_payload, encoding="utf-8")

    assign_session_vehicle(session_id, SessionVehicleAssignment(
        vin="VF3LJHNYWJS123456",
        vehicle_profile="peugeot_308_t9_2018",
        vehicle_label="Peugeot 308 II",
    ))

    summary = list_sessions()[0]
    assert raw_path.read_text(encoding="utf-8") == raw_payload
    assert summary.vin == "VF3LJHNYWJS123456"
    assert summary.vehicle_profile == "peugeot_308_t9_2018"
    assert summary.vehicle_label == "Peugeot 308 II"


def test_sensitive_service_stays_blocked():
    assert not authorize_uds(bytes.fromhex("2701"), True).allowed


def test_fuel_filter_preserves_raw_float_and_damps_tank_slosh():
    points = [
        ReplaySample(t_ms=0, fuel_liters_raw=30),
        ReplaySample(t_ms=1_000, fuel_liters_raw=40),
        ReplaySample(t_ms=2_000, fuel_liters_raw=20),
    ]

    assert _filter_fuel_level(points, time_constant_s=1)
    assert [point.fuel_liters_raw for point in points] == [30, 40, 20]
    assert points[0].fuel_liters == 30
    assert points[1].fuel_liters == 36.32
    assert 25 < (points[2].fuel_liters or 0) < 36.32


def test_opendbc_psa_catalog_is_loaded_and_decodes_engine_speed():
    decoder = get_opendbc_decoder()
    source = decoder.source_info()
    assert source.loaded
    assert source.database == "psa_aee2010_r3"
    assert source.message_count == 107
    assert source.signal_count == 432

    message, values, error = decoder.decode_frame(
        0x208,
        False,
        bytes.fromhex("1F40000000000000"),
    )
    assert error is None
    assert message is not None
    assert message.name == "Dyn_CMM"
    assert values is not None
    assert values["P000_Com_nEng"]["value"] == 1000.0
    assert values["P000_Com_nEng"]["unit"] == "1/min"


def test_replay_streams_session_and_reconstructs_local_route(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "session_dir", tmp_path)
    monkeypatch.setattr(settings, "manual_signal_validations_file", tmp_path / "manual_signal_validations.json")
    session_id = "learn-20260731T150000Z-replay"
    decoder = get_opendbc_decoder()

    def payload(arbitration_id: int, **updates: float) -> str:
        message = decoder.message_for_frame(arbitration_id, False)
        assert message is not None
        values = {
            signal.name: signal.minimum if signal.minimum is not None and signal.minimum > 0 else 0
            for signal in message.signals
        }
        values.update(updates)
        return message.encode(values, strict=False).hex().upper()

    frames: list[dict] = [{
        "type": "meta",
        "timestamp_us": 1_000_000,
        "session_id": session_id,
        "name": "Replay de test",
        "source": "fixture",
    }]
    for index in range(5):
        timestamp_us = 1_000_000 + index * 100_000
        turn_signal = 1 if index >= 2 else 0
        brake = 1 if index == 3 else 0
        messages = [
            (0x38D, payload(0x38D, VITESSE_VEHICULE_ROUES=36, ACCEL_LONGI_ROUES=0, REQ_LAMPE_WARNING=1 if index >= 3 else 0)),
            (0x305, payload(0x305, ANGLE=45 if index >= 2 else 0, RATE=5)),
            (0x329, payload(0x329, P444_Com_bGbxSysFaultRaw=0)),
            (0x348, payload(0x348, P152_Gearbx_stGear=index + 1, P025_Com_stESPErr=0, P343_Com_bOBDErr=0, P344_Com_bMILOn=-1 if index >= 3 else 0, P345_Com_bMILBln=0)),
            (0x349, payload(0x349, P030_Gbx_stDrvTrnEgd=2, P009_Com_bGearShftActv=1 if index >= 3 else 0, P283_Com_stGearTrgtPos=min(6, index + 2))),
            (0x34D, payload(0x34D, P147_Com_bESPIntvActv=1 if index >= 3 else 0)),
            (0x3CD, payload(0x3CD, LATERAL_ACCELERATION=1.25, YAW_RATE=2.3)),
            (0x452, payload(0x452, TURN_SIGNAL_STATUS=turn_signal)),
            (0x612, payload(0x612, ETAT_FEUX_CROIST=1, DEF_FEU_CROISMNT_D=0, DEF_FEU_CROISMNT_G=0, DEF_FEU_ROUTE_D=0, DEF_FEU_ROUTE_G=0)),
            (0x412, payload(0x412, P013_MainBrake=brake, P040_MainBrakeFault=0, P012_Com_bFlMin=1 if index >= 3 else 0, P086_Com_stFlLvlDia=0)),
            (0x3F2, payload(0x3F2, STATUS=2)),
            (0x488, payload(0x488, P005_CEngDst_tSens=88, P011_Oil_tSwmp=90, P158_Air_tAFS=32)),
            (0x50D, payload(0x50D, P351_Com_bABSIntvActv=1 if index == 3 else 0)),
            (0x572, payload(0x572, DRIVER_SEATBELT=2, PASSENGER_SEATBELT=1)),
            (0x588, payload(0x588, P278_Oil_stPSwmp=-1, P338_EnvP_p=1000)),
            (0x592, payload(0x592, P272_Com_rBattCh=86, P273_Com_tBatt=51, P418_Com_uBattRaw=13.8)),
            (0x5B2, payload(0x5B2, P146_Com_tEnvT=21.5)),
        ]
        for arbitration_id, data_hex in messages:
            frames.append({
                "type": "can_frame",
                "timestamp_us": timestamp_us,
                "arbitration_id": arbitration_id,
                "extended": False,
                "data_hex": data_hex,
                "direction": "rx",
            })

    frames.append({
        "type": "can_frame",
        "timestamp_us": 1_500_000,
        "arbitration_id": 0x652,
        "extended": False,
        "data_hex": "0762F19056463300",
        "direction": "rx",
        "bus": "diagnostic",
    })
    path = tmp_path / f"{session_id}.jsonl"
    path.write_text("\n".join(json.dumps(frame) for frame in frames) + "\n", encoding="utf-8")

    replay = prepare_replay(session_id)

    assert replay.name == "Replay de test"
    assert replay.duration_ms == 400
    assert replay.frame_count == 85
    assert replay.max_speed_kph == 36
    assert replay.distance_km > 0
    assert not replay.gps_available
    assert replay.route_method == "dead_reckoning_speed_yaw"
    # Le lacet ESP positif correspond à un virage à gauche : le cap de carte
    # décroît et la reconstruction doit partir vers les x négatifs.
    assert replay.points[-1].x_m < 0
    assert replay.points[-1].low_beam is True
    assert replay.points[-1].turn_signal == "right"
    assert replay.points[-1].oil_temperature_c == 90
    assert replay.points[-1].coolant_temperature_c == 88
    assert replay.points[-1].oil_pressure_switch is True
    assert replay.points[-1].battery_voltage_v == 13.8
    assert replay.points[-1].ambient_temperature_c == 21.5
    assert replay.points[-1].mil_on is True
    assert replay.points[-1].esp_intervention is True
    assert replay.points[-1].generic_warning_requested is True
    assert replay.points[-1].low_fuel_warning is True
    assert replay.points[-1].driver_seatbelt_state == 2
    assert replay.points[-1].current_gear == 4
    assert replay.points[-1].target_gear == 5
    assert replay.points[-1].gear_shift_active is True
    assert replay.points[-1].lateral_accel_ms2 == 1.25
    assert replay.points[-1].yaw_rate_deg_s == 2.3
    assert any(event.kind == "turn_signal" for event in replay.events)
    assert any(event.kind == "brake" for event in replay.events)
    assert any(event.kind == "gear" for event in replay.events)
    assert (tmp_path / f"{session_id}.replay.json").exists()
    assert prepare_replay(session_id).points == replay.points
    validation = validate_replay(session_id)
    validations = {item.key: item for item in validation.signals}
    assert validations["steering_angle_deg"].status == "validated"
    assert validations["lateral_accel_ms2"].status == "validated"
    assert validations["yaw_rate_deg_s"].status == "validated"
    assert validations["oil_temperature_c"].status == "plausible"
    assert validations["oil_pressure_switch"].status == "validated"
    assert validations["oil_pressure_bar"].status == "unavailable"
    assert (tmp_path / f"{session_id}.validation.json").exists()


def test_gps_positions_are_saved_and_drive_replay_route(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "session_dir", tmp_path)
    session_id = "learn-20260801T160000Z-gps"
    manager = PassiveCaptureManager()
    manager._active = True
    manager._session_id = session_id
    manager._path = tmp_path / f"{session_id}.jsonl"
    manager._started_at_us = time.time_ns() // 1000
    manager._open_writer()
    manager._write({
        "type": "meta",
        "timestamp_us": manager._started_at_us,
        "session_id": session_id,
        "name": "Trajet GPS test",
        "source": "fixture",
    })

    start_us = manager._started_at_us
    coordinates = [
        (48.856600, 2.352200),
        (48.856750, 2.352450),
        (48.856950, 2.352800),
    ]
    for index, (latitude, longitude) in enumerate(coordinates):
        manager.gps_position(CaptureGpsPosition(
            session_id=session_id,
            latitude=latitude,
            longitude=longitude,
            accuracy_m=4.5,
            altitude_m=38.0 + index,
            heading_deg=45.0,
            speed_m_s=8.0,
            source_timestamp_us=start_us + index * 1_000_000,
        ))
        manager._write({
            "type": "can_frame",
            "timestamp_us": start_us + index * 1_000_000,
            "arbitration_id": 0x123,
            "extended": False,
            "data_hex": "0000000000000000",
            "direction": "rx",
            "bus": "live",
        })
    manager._close_writer()

    replay = prepare_replay(session_id)
    assert replay.gps_available
    assert replay.gps_point_count == 3
    assert replay.route_method == "browser_gps"
    assert replay.distance_km > 0
    assert replay.points[0].latitude == coordinates[0][0]
    assert replay.points[-1].longitude == coordinates[-1][1]
    assert replay.points[-1].gps_accuracy_m == 4.5
    assert replay.points[-1].gps_speed_kph == 28.8
    assert replay.points[-1].x_m > 0
    assert replay.points[-1].y_m > 0

    geojson = replay_geojson(session_id)
    feature = geojson["features"][0]
    assert feature["geometry"]["type"] == "LineString"
    assert feature["geometry"]["coordinates"][0] == [2.3522, 48.8566]
    assert feature["properties"]["accuracy_m"] == [4.5, 4.5, 4.5]


def test_fiat_replay_keeps_extended_obd_fields_for_live_display(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "session_dir", tmp_path)
    session_id = "learn-20260802T210000Z-fiat-obd"
    path = tmp_path / f"{session_id}.jsonl"
    events = [
        {
            "type": "meta",
            "timestamp_us": 1_000_000,
            "session_id": session_id,
            "name": "Fiat EOBD",
            "source": "fixture",
            "vehicle_profile": "fiat_500_generic",
            "vehicle_label": "Fiat 500 1.2 8V",
        },
        {
            "type": "obd_sensor_snapshot",
            "timestamp_us": 1_000_000,
            "values": [
                {"key": "vehicle_speed", "value": 24},
                {"key": "engine_rpm", "value": 1850},
                {"key": "engine_load", "value": 37.5},
                {"key": "fuel_pressure", "value": 330},
                {"key": "intake_manifold_pressure", "value": 54},
                {"key": "maf", "value": 4.25},
                {"key": "throttle_position", "value": 11.2},
                {"key": "relative_throttle_position", "value": 8.4},
                {"key": "absolute_throttle_position_b", "value": 12.1},
                {"key": "absolute_throttle_position_c", "value": 12.5},
                {"key": "commanded_throttle_actuator", "value": 10.8},
                {"key": "short_fuel_trim_bank_1", "value": -1.56},
                {"key": "oxygen_sensor_b1s1_voltage", "value": 0.72},
                {"key": "control_module_voltage", "value": 13.94},
                {"key": "fuel_level", "value": 62.4},
                {"key": "accelerator_pedal_d", "value": 9.1},
                {"key": "accelerator_pedal_e", "value": 9.4},
                {"key": "relative_accelerator_position", "value": 7.8},
                {"key": "fuel_injection_timing", "value": 2.5},
            ],
        },
        {
            "type": "obd_sensor_snapshot",
            "timestamp_us": 1_301_000,
            "values": [
                {"key": "vehicle_speed", "value": 26},
                {"key": "engine_rpm", "value": 1920},
                {"key": "engine_load", "value": 41.2},
                {"key": "fuel_pressure", "value": 336},
                {"key": "intake_manifold_pressure", "value": 58},
                {"key": "maf", "value": 5.18},
                {"key": "throttle_position", "value": 14.6},
                {"key": "relative_throttle_position", "value": 11.7},
                {"key": "absolute_throttle_position_b", "value": 15.1},
                {"key": "absolute_throttle_position_c", "value": 15.5},
                {"key": "commanded_throttle_actuator", "value": 14.2},
                {"key": "short_fuel_trim_bank_1", "value": 0.78},
                {"key": "oxygen_sensor_b1s1_voltage", "value": 0.18},
                {"key": "control_module_voltage", "value": 14.01},
                {"key": "fuel_level", "value": 62.4},
                {"key": "accelerator_pedal_d", "value": 13.4},
                {"key": "accelerator_pedal_e", "value": 13.7},
                {"key": "relative_accelerator_position", "value": 12.9},
                {"key": "fuel_injection_timing", "value": 4.5},
            ],
        },
    ]
    path.write_text("\n".join(json.dumps(event) for event in events) + "\n", encoding="utf-8")

    replay = prepare_replay(session_id)

    assert replay.vehicle_profile == "fiat_500_generic"
    assert {
        "engine_load_pct", "fuel_pressure_kpa", "manifold_pressure_kpa",
        "mass_air_flow_g_s", "throttle_position_pct", "relative_throttle_position_pct",
        "throttle_position_b_pct", "throttle_position_c_pct",
        "commanded_throttle_actuator_pct", "accelerator_pct",
        "accelerator_secondary_pct", "relative_accelerator_position_pct",
        "fuel_injection_timing_deg", "oxygen_sensor_b1s1_v", "fuel_level_pct",
    } <= set(replay.available_fields)
    assert replay.points[-1].engine_rpm == 1920
    assert replay.points[-1].engine_load_pct == 41.2
    assert replay.points[-1].manifold_pressure_kpa == 58
    assert replay.points[-1].mass_air_flow_g_s == 5.18
    assert replay.points[-1].throttle_position_pct == 14.6
    assert replay.points[-1].throttle_position_b_pct == 15.1
    assert replay.points[-1].commanded_throttle_actuator_pct == 14.2
    assert replay.points[-1].accelerator_pct == 13.4
    assert replay.points[-1].accelerator_secondary_pct == 13.7
    assert replay.points[-1].relative_accelerator_position_pct == 12.9
    assert replay.points[-1].fuel_injection_timing_deg == 4.5
    assert replay.points[-1].oxygen_sensor_b1s1_v == 0.18
    assert replay.points[-1].battery_voltage_v == 14.01
    assert replay.points[-1].fuel_level_pct == 62.4


def test_fiat_replay_decodes_observed_wheels_brake_and_body_without_psa(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "session_dir", tmp_path)
    session_id = "learn-20260802T213000Z-fiat-can"
    path = tmp_path / f"{session_id}.jsonl"
    events = [{
        "type": "meta",
        "timestamp_us": 1_000_000,
        "session_id": session_id,
        "name": "Fiat CAN observé",
        "source": "fixture",
        "vehicle_profile": "fiat_500_generic",
        "vehicle_label": "Fiat 500 1.2 8V",
    }]
    for timestamp_us, arbitration_id, data_hex in (
        (1_000_000, 0x0618A001, "001702BA161B7D00"),
        (1_010_000, 0x0218A006, "0160016001600160"),
        (1_020_000, 0x0810A000, "00007000"),
        (1_030_000, 0x0A18A000, "2009480008002000"),
        (1_301_000, 0x0618A001, "00170320161B7D00"),
    ):
        events.append({
            "type": "can_frame",
            "timestamp_us": timestamp_us,
            "arbitration_id": arbitration_id,
            "extended": True,
            "data_hex": data_hex,
            "direction": "rx",
            "bus": "live",
        })
    path.write_text("\n".join(json.dumps(event) for event in events) + "\n", encoding="utf-8")

    replay = prepare_replay(session_id)

    assert replay.points[-1].engine_rpm == 800
    assert replay.points[-1].fiat_throttle_candidate_pct == 0
    assert replay.points[-1].fiat_air_load_candidate_raw == 0x16
    assert replay.points[-1].speed_kph == 22
    assert replay.points[-1].wheel_front_left_kph == 22
    assert replay.points[-1].wheel_rear_right_kph == 22
    assert replay.points[-1].brake_active is True
    assert replay.points[-1].brake_pressure_raw == 0x70
    assert replay.points[-1].parking_brake is True
    assert replay.points[-1].driver_door is True
    assert replay.field_quality["engine_rpm"] == "validated_on_fiat_500_vin"
    assert replay.field_quality["fiat_throttle_candidate_pct"] == "fiat_500_vehicle_observed_candidate"
    assert replay.field_quality["wheel_front_left_kph"] == "fiat_500_vehicle_observed_candidate"
    assert replay.field_quality["brake_active"] == "validated_on_fiat_500_vin"
    assert replay.field_quality["driver_door"] == "validated_on_fiat_500_vin"
    assert replay.field_quality["brake_pressure_raw"] == "fiat_500_vehicle_observed_candidate"


def test_sparse_gps_is_fused_with_can_route_to_preserve_turns():
    points = [
        ReplaySample(t_ms=0, x_m=0, y_m=0),
        ReplaySample(t_ms=500, x_m=5, y_m=5),
        ReplaySample(t_ms=1000, x_m=10, y_m=0),
    ]
    fixes = [
        ReplayGpsPoint(
            t_ms=0,
            timestamp_us=1_000_000,
            latitude=48.8566,
            longitude=2.3522,
            accuracy_m=5,
        ),
        ReplayGpsPoint(
            t_ms=1000,
            timestamp_us=2_000_000,
            latitude=48.8566,
            longitude=2.352337,
            accuracy_m=5,
        ),
    ]

    method, distance_m, _, used_fix_count = _apply_gps_route(points, fixes)

    assert method == "gps_can_fusion"
    assert used_fix_count == 2
    assert distance_m > 10
    assert points[0].latitude == fixes[0].latitude
    assert abs(points[-1].longitude - fixes[-1].longitude) < 0.000001
    # The middle CAN point bends north instead of becoming a straight GPS chord.
    assert points[1].latitude > fixes[0].latitude


def test_driver_confirmed_road_uses_can_distance_for_timing():
    points = [
        ReplaySample(t_ms=0, distance_m=0),
        ReplaySample(t_ms=500, distance_m=50),
        ReplaySample(t_ms=1000, distance_m=100),
    ]
    road = [
        (1.4000, 43.5000),
        (1.4005, 43.5000),
        (1.4005, 43.5005),
    ]

    distance_m, bounds = _apply_confirmed_road_route(points, road, [0, 50, 100])

    assert distance_m > 70
    assert points[0].longitude == road[0][0]
    assert points[-1].latitude == road[-1][1]
    assert points[1].distance_m == round(distance_m / 2, 1)
    assert points[1].longitude == road[1][0]
    assert bounds["max_x"] > 0


def test_passive_sensor_snapshot_prefers_valid_steering_angle(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "sensor_overrides_file", tmp_path / "sensor_overrides.json")
    monkeypatch.setattr(capture_manager, "status", lambda: CaptureStatus(
        session_id="learn-test",
        active=True,
        source="fixture",
        frame_count=3,
        marker_count=0,
        path="fixture.jsonl",
        strict_passive=True,
    ))
    monkeypatch.setattr(capture_manager, "latest_frames", lambda: [
        {
            "timestamp_us": 1_000_000,
            "arbitration_id": 0x2F5,
            "extended": False,
            "data": bytes.fromhex("0501007FFF0001"),
            "raw_hex": "0501007FFF0001",
        },
        {
            "timestamp_us": 1_000_100,
            "arbitration_id": 0x305,
            "extended": False,
            "data": bytes.fromhex("005F0007D00020"),
            "raw_hex": "005F0007D00020",
        },
        {
            "timestamp_us": 1_000_200,
            "arbitration_id": 0x7FF,
            "extended": False,
            "data": bytes.fromhex("0000000000000000"),
            "raw_hex": "0000000000000000",
        },
    ])

    snapshot = passive_sensor_snapshot()

    assert snapshot.strict_passive is True
    assert snapshot.steering.detected
    assert snapshot.steering.angle_degrees == 9.5
    assert snapshot.steering.driver_torque == 1
    assert snapshot.steering.angle_source == "0x305 STEERING_ALT.ANGLE"
    assert snapshot.observed_can_id_count == 3
    assert snapshot.observed_message_count == 2
    assert snapshot.unknown_can_id_count == 1
    assert snapshot.unknown_can_ids == [0x7FF]
    assert snapshot.cursor_us == 1_000_200
    assert any(
        signal.key == "STEERING_ALT.ANGLE"
        and signal.display_name == "Angle du volant"
        and signal.essential
        and signal.confidence == "validated"
        for signal in snapshot.signals
    )
    assert not any(signal.key == "STEERING.ANGLE" for signal in snapshot.signals)

    delta = passive_sensor_snapshot(since_us=1_000_050)
    assert delta.cursor_us == 1_000_200
    assert {signal.message for signal in delta.signals} == {"STEERING_ALT"}
    assert delta.decoded_signal_count == snapshot.decoded_signal_count

    save_override(PassiveSensorOverride(
        key="STEERING_ALT.ANGLE",
        label="Angle corrigé",
        description="Correction de test",
        unit="tour",
        factor=2,
        offset=1,
    ))
    corrected = passive_sensor_snapshot()
    angle = next(signal for signal in corrected.signals if signal.key == "STEERING_ALT.ANGLE")
    assert angle.display_name == "Angle corrigé"
    assert angle.description == "Correction de test"
    assert angle.value == 20
    assert angle.raw_value == 9.5
    assert angle.unit == "tour"
    assert angle.customized


def test_passive_sensor_snapshot_uses_fiat_profile_without_psa_decoding(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "sensor_overrides_file", tmp_path / "sensor_overrides.json")
    monkeypatch.setattr(capture_manager, "status", lambda: CaptureStatus(
        session_id="learn-fiat",
        active=True,
        source="fixture",
        frame_count=2,
        marker_count=0,
        path="fixture.jsonl",
        strict_passive=True,
        vehicle_profile="fiat_500_generic",
        vehicle_label="Fiat 500",
    ))
    monkeypatch.setattr(capture_manager, "latest_frames", lambda: [
        {
            "timestamp_us": 2_000_000,
            "arbitration_id": 0x0618A001,
            "extended": True,
            "data": bytes.fromhex("002002B71F1E8400"),
            "raw_hex": "002002B71F1E8400",
        },
        {
            "timestamp_us": 2_000_100,
            "arbitration_id": 0x0210A006,
            "extended": True,
            "data": bytes.fromhex("0000000000000000"),
            "raw_hex": "0000000000000000",
        },
    ])

    snapshot = passive_sensor_snapshot()
    by_key = {signal.key: signal for signal in snapshot.signals}

    assert snapshot.observed_message_count == 1
    assert snapshot.decoded_signal_count == 3
    assert snapshot.unknown_can_ids == [0x0210A006]
    assert by_key["FIAT_ENGINE.ENGINE_RPM"].value == 695
    assert by_key["FIAT_ENGINE.ENGINE_RPM"].confidence == "validated"
    assert by_key["FIAT_ENGINE.THROTTLE_POSITION_CANDIDATE"].value == 0
    assert by_key["FIAT_ENGINE.THROTTLE_POSITION_CANDIDATE"].confidence == "vehicle_observed_candidate"
    assert by_key["FIAT_ENGINE.AIR_LOAD_CANDIDATE_RAW"].value == 0x1F
    assert any("aucun décodeur Peugeot" in warning for warning in snapshot.warnings)


def test_fiat_passive_snapshot_distinguishes_validated_and_candidate_fields(monkeypatch):
    monkeypatch.setattr(capture_manager, "status", lambda: CaptureStatus(
        session_id="learn-fiat-candidates",
        active=True,
        source="fixture",
        frame_count=6,
        marker_count=0,
        path="fixture.jsonl",
        strict_passive=True,
        vehicle_profile="fiat_500_generic",
        vehicle_label="Fiat 500",
    ))
    monkeypatch.setattr(capture_manager, "latest_obd_values", lambda: [])
    monkeypatch.setattr(capture_manager, "latest_frames", lambda: [
        {
            "timestamp_us": 2_000_000,
            "arbitration_id": 0x0218A006,
            "extended": True,
            "data": bytes.fromhex("016701680169016A"),
            "raw_hex": "016701680169016A",
        },
        {
            "timestamp_us": 2_000_100,
            "arbitration_id": 0x0628A001,
            "extended": True,
            "data": bytes.fromhex("0000000000200000"),
            "raw_hex": "0000000000200000",
        },
        {
            "timestamp_us": 2_000_200,
            "arbitration_id": 0x0810A000,
            "extended": True,
            "data": bytes.fromhex("00007000"),
            "raw_hex": "00007000",
        },
        {
            "timestamp_us": 2_000_300,
            "arbitration_id": 0x0A18A000,
            "extended": True,
            "data": bytes.fromhex("2009480008003000"),
            "raw_hex": "2009480008003000",
        },
        {
            "timestamp_us": 2_000_400,
            "arbitration_id": 0x0C1CA000,
            "extended": True,
            "data": bytes.fromhex("0000E00000000000"),
            "raw_hex": "0000E00000000000",
        },
        {
            "timestamp_us": 2_000_500,
            "arbitration_id": 0x0C28A000,
            "extended": True,
            "data": bytes.fromhex("182602082026"),
            "raw_hex": "182602082026",
        },
    ])

    snapshot = passive_sensor_snapshot()
    by_key = {signal.key: signal for signal in snapshot.signals}

    assert snapshot.observed_message_count == 6
    assert snapshot.unknown_can_ids == []
    assert by_key["FIAT_ABS.WHEEL_FRONT_LEFT_SPEED"].value == 22.44
    assert by_key["FIAT_DRIVER.CLUTCH_PEDAL_PRESSED"].value is True
    assert by_key["FIAT_ABS.BRAKE_PEDAL_ACTIVE"].value is True
    assert by_key["FIAT_ABS.BRAKE_PEDAL_ACTIVE"].confidence == "validated"
    assert by_key["FIAT_BODY.PARKING_BRAKE"].value is True
    assert by_key["FIAT_BODY.DRIVER_DOOR_OPEN"].value is True
    assert by_key["FIAT_BODY.DRIVER_DOOR_OPEN"].confidence == "validated"
    assert by_key["FIAT_BODY.CITY_MODE"].value is True
    assert by_key["FIAT_BODY.REAR_WINDOW_HEATER"].value is True
    assert by_key["FIAT_BODY.START_STOP_AVAILABLE"].value is True
    assert by_key["FIAT_CLOCK.DATE_TIME"].value == "2026-08-02 18:26"
    assert by_key["FIAT_ABS.BRAKE_PEDAL_STATE_RAW"].confidence == "vehicle_observed_candidate"
    assert by_key["FIAT_BODY.PARKING_BRAKE"].confidence == "vehicle_observed_candidate"
    assert snapshot.source_url and "talking-with-cars" in snapshot.source_url


def test_hybrid_obd_values_complete_fiat_passive_sensors(monkeypatch):
    monkeypatch.setattr(capture_manager, "status", lambda: CaptureStatus(
        session_id="learn-fiat-hybrid",
        active=True,
        source="fixture",
        frame_count=0,
        marker_count=0,
        path="fixture.jsonl",
        strict_passive=False,
        hybrid_obd_enabled=True,
        hybrid_obd_ready=True,
        obd_sample_count=3,
        obd_supported_pids=[0x0C, 0x42],
        vehicle_profile="fiat_500_generic",
        vehicle_label="Fiat 500",
    ))
    monkeypatch.setattr(capture_manager, "latest_frames", lambda: [])
    monkeypatch.setattr(capture_manager, "latest_obd_values", lambda: [
        {
            "key": "engine_rpm",
            "pid": 0x0C,
            "name": "Régime moteur",
            "value": 702,
            "unit": "tr/min",
            "raw_hex": "0AF8",
            "updated_at_us": 3_000_000,
            "request_id": 0x18DB33F1,
            "response_id": 0x18DAF110,
        },
        {
            "key": "control_module_voltage",
            "pid": 0x42,
            "name": "Tension calculateur",
            "value": 13.82,
            "unit": "V",
            "raw_hex": "35FC",
            "updated_at_us": 3_000_100,
            "request_id": 0x18DB33F1,
            "response_id": 0x18DAF110,
        },
    ])

    snapshot = passive_sensor_snapshot()
    by_key = {signal.key: signal for signal in snapshot.signals}

    assert snapshot.hybrid_obd_ready
    assert snapshot.obd_sample_count == 3
    assert snapshot.decoded_signal_count == 2
    assert by_key["OBD01.engine_rpm"].value == 702
    assert by_key["OBD01.control_module_voltage"].value == 13.82
    assert by_key["OBD01.control_module_voltage"].source == "obd"
    assert by_key["OBD01.control_module_voltage"].confidence == "standardized"
    assert snapshot.cursor_us == 3_000_100


def test_post_processing_finds_repeated_bit_correlation(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "session_dir", tmp_path)
    session_id = "learn-20260731T120000Z-test"
    events = [
        {
            "type": "meta",
            "timestamp_us": 1_000_000,
            "session_id": session_id,
            "name": "Essai frein",
            "source": "fixture",
        }
    ]

    def frame(timestamp_us: int, arbitration_id: int, first_byte: int) -> dict:
        return {
            "type": "can_frame",
            "timestamp_us": timestamp_us,
            "arbitration_id": arbitration_id,
            "extended": False,
            "data_hex": bytes([first_byte, 0, 0, 0, 0, 0, 0, 0]).hex().upper(),
            "direction": "rx",
        }

    for marker_time in (2_000_000, 6_000_000):
        for offset in (-900_000, -650_000, -400_000, -150_000):
            events.append(frame(marker_time + offset, 0x123, 0x00))
            events.append(frame(marker_time + offset, 0x456, 0x55))
        events.append({
            "type": "marker",
            "timestamp_us": marker_time,
            "name": "frein_appuye",
            "note": "Pédale maintenue",
        })
        for offset in (150_000, 400_000, 650_000, 900_000):
            events.append(frame(marker_time + offset, 0x123, 0x04))
            events.append(frame(marker_time + offset, 0x456, 0x55))

    diagnostic_event = frame(7_500_000, 0x652, 0x62)
    diagnostic_event["bus"] = "diagnostic"
    events.append(diagnostic_event)

    path = tmp_path / f"{session_id}.jsonl"
    path.write_text(
        "\n".join(json.dumps(event) for event in sorted(events, key=lambda e: e["timestamp_us"])) + "\n",
        encoding="utf-8",
    )

    report = analyze_behavior(
        session_id,
        CorrelationOptions(before_ms=1000, after_ms=1000, min_samples=3),
    )
    assert report.total_frames == 32
    assert report.unique_ids == 2
    assert report.correlations[0].marker == "frein_appuye"
    assert report.correlations[0].occurrences == 2

    bit_candidates = [
        candidate
        for candidate in report.correlations[0].candidates
        if candidate.kind == "bit"
    ]
    assert any(
        candidate.arbitration_id == 0x123
        and candidate.byte_index == 0
        and candidate.bit_index == 2
        and candidate.confidence == "forte"
        for candidate in bit_candidates
    )
    assert not any(candidate.arbitration_id == 0x456 for candidate in bit_candidates)

    sessions = list_sessions()
    assert sessions[0].name == "Essai frein"
    assert sessions[0].frame_count == 33
    assert sessions[0].live_frame_count == 32
    assert sessions[0].diagnostic_frame_count == 1
    assert sessions[0].marker_count == 2


def test_post_processing_enriches_candidates_with_opendbc(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "session_dir", tmp_path)
    session_id = "learn-20260731T140000Z-opendbc"
    events = [{
        "type": "meta",
        "timestamp_us": 1_000_000,
        "session_id": session_id,
        "name": "Essai accélérateur",
        "source": "fixture",
    }]

    def frame(timestamp_us: int, data_hex: str) -> dict:
        return {
            "type": "can_frame",
            "timestamp_us": timestamp_us,
            "arbitration_id": 0x208,
            "extended": False,
            "data_hex": data_hex,
            "direction": "rx",
        }

    for marker_time in (2_000_000, 6_000_000):
        for offset in (-900_000, -650_000, -400_000, -150_000):
            events.append(frame(marker_time + offset, "1F40000000000000"))
        events.append({
            "type": "marker",
            "timestamp_us": marker_time,
            "name": "accelerateur_appuye",
        })
        for offset in (150_000, 400_000, 650_000, 900_000):
            events.append(frame(marker_time + offset, "1F40002800000000"))

    (tmp_path / f"{session_id}.jsonl").write_text(
        "\n".join(json.dumps(event) for event in sorted(events, key=lambda e: e["timestamp_us"])) + "\n",
        encoding="utf-8",
    )

    report = analyze_behavior(
        session_id,
        CorrelationOptions(before_ms=1000, after_ms=1000, min_samples=3),
    )
    assert report.opendbc is not None
    assert report.opendbc.loaded
    assert report.opendbc.observed_messages == ["Dyn_CMM"]
    assert report.inventory[0].opendbc_message == "Dyn_CMM"
    assert "P002_Com_rAPP" in report.inventory[0].opendbc_signals
    assert any(
        candidate.kind == "dbc_signal"
        and candidate.source == "opendbc"
        and candidate.dbc_message == "Dyn_CMM"
        and candidate.dbc_signal == "P002_Com_rAPP"
        for candidate in report.correlations[0].candidates
    )
