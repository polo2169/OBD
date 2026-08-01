import json

from app.config import settings
from app.learn.analyzer import analyze_behavior, list_sessions
from app.learn.capture import capture_manager
from app.learn.isotp import parse_isotp_frame, uds_service
from app.learn.models import CaptureStatus, CorrelationOptions, PassiveSensorOverride
from app.learn.opendbc import get_opendbc_decoder
from app.learn.passive_sensors import passive_sensor_snapshot
from app.learn.replay import prepare_replay
from app.learn.sensor_metadata import save_override
from app.safety import authorize_uds


def test_single_frame_parse():
    parsed = parse_isotp_frame(bytes.fromhex("0322F19000000000"))
    assert parsed is not None
    assert parsed.complete
    assert parsed.payload == bytes.fromhex("22F190")
    assert uds_service(parsed.payload) == 0x22


def test_sensitive_service_stays_blocked():
    assert not authorize_uds(bytes.fromhex("2701"), True).allowed


def test_opendbc_psa_catalog_is_loaded_and_decodes_engine_speed():
    decoder = get_opendbc_decoder()
    source = decoder.source_info()
    assert source.loaded
    assert source.database == "psa_aee2010_r3"
    assert source.message_count == 107
    assert source.signal_count == 430

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

    path = tmp_path / f"{session_id}.jsonl"
    path.write_text("\n".join(json.dumps(frame) for frame in frames) + "\n", encoding="utf-8")

    replay = prepare_replay(session_id)

    assert replay.name == "Replay de test"
    assert replay.duration_ms == 400
    assert replay.frame_count == 80
    assert replay.max_speed_kph == 36
    assert replay.distance_km > 0
    assert not replay.gps_available
    assert replay.route_method == "dead_reckoning_speed_steering"
    # Sur la 308, un angle DBC positif correspond au virage visuel gauche :
    # la reconstruction doit donc partir vers les x négatifs.
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
    assert any(event.kind == "turn_signal" for event in replay.events)
    assert any(event.kind == "brake" for event in replay.events)
    assert any(event.kind == "gear" for event in replay.events)
    assert (tmp_path / f"{session_id}.replay.json").exists()
    assert prepare_replay(session_id).points == replay.points


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
    assert sessions[0].frame_count == 32
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
