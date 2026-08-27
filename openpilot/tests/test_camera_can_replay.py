from pathlib import Path

from tools.render_camera_can_replay import (
    DecodeCounters,
    ass_timestamp,
    iter_can_frames,
    load_camera_frames,
    transmission_text,
    turn_signal_text,
    update_state,
)


def test_iter_can_frames_ignores_noise_and_aligns_wall_clock(tmp_path: Path) -> None:
    capture = tmp_path / "can.jsonl"
    capture.write_bytes(
        b"\x00startup noise\n"
        b'{"type":"hello"}\n'
        b"F,120,0,38D,20,00000000AF017600\n"
        b"invalid\n"
    )
    counters = DecodeCounters()

    frames = list(iter_can_frames(capture, 0x100, 10.0, counters))

    assert len(frames) == 1
    assert frames[0].timestamp_us == 0x120
    assert frames[0].wall_timestamp_us == 10_000_032
    assert frames[0].address == 0x38D
    assert frames[0].data.hex() == "00000000af017600"
    assert counters.raw_lines == 4
    assert counters.can_frames == 1


def test_load_camera_frames_requires_contiguous_monotonic_timestamps(tmp_path: Path) -> None:
    capture = tmp_path / "frames.jsonl"
    capture.write_text(
        '{"frame_index":0,"timestamp_us":100}\n'
        '{"frame_index":1,"timestamp_us":133}\n',
        encoding="utf-8",
    )

    frames = load_camera_frames(capture)

    assert [(frame.index, frame.timestamp_us) for frame in frames] == [(0, 100), (1, 133)]


def test_update_state_maps_vehicle_validated_t9_fields() -> None:
    state = {}
    update_state(
        0x208,
        {
            "EngineRPM": 1640.5,
            "EngineTorqueNm": 72,
            "AcceleratorPositionPct": 18.5,
            "CruiseStateCandidate": 2,
        },
        state,
    )
    update_state(
        0x412,
        {
            "ReverseGearActive": 0,
            "ParkingBrakeActive": 1,
            "BrakePedalActive": 1,
            "DriverDoorOpen": 0,
            "PassengerDoorOpen": 0,
            "RearLeftDoorOpen": 1,
            "RearRightDoorOpen": 0,
        },
        state,
    )
    update_state(
        0x572,
        {"DriverSeatbeltState": 2, "PassengerSeatbeltState": 1},
        state,
    )

    assert state["engine_rpm"] == 1640.5
    assert state["accelerator_pct"] == 18.5
    assert state["cruise_active"] is True
    assert state["brake_active"] is True
    assert state["parking_brake"] is True
    assert state["rear_left_door"] is True
    assert state["driver_seatbelt_state"] == 2


def test_transmission_display_does_not_claim_target_is_engaged_gear() -> None:
    assert transmission_text({"speed_kph": 20, "current_gear": 0, "target_gear": 3}) == "cible 3"
    assert transmission_text({"speed_kph": 20, "current_gear": 4, "target_gear": 3}) == "D4"
    assert transmission_text({"speed_kph": 0, "current_gear": 0, "target_gear": 1}) == "N"
    assert transmission_text({"reverse": True, "current_gear": 0, "target_gear": 9}) == "R"


def test_ass_timestamp() -> None:
    assert ass_timestamp(0) == "0:00:00.00"
    assert ass_timestamp(6_123) == "0:01:01.23"


def test_turn_signal_text_uses_psa_0x452_encoding() -> None:
    assert turn_signal_text(0) == "OFF"
    assert turn_signal_text(1) == "DROITE"
    assert turn_signal_text(2) == "GAUCHE"
    assert turn_signal_text(3) == "WARNING"
