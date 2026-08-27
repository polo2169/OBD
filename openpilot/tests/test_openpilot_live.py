from pathlib import Path

from tools.run_openpilot_live import (
    DESIRE_LANE_CHANGE_LEFT,
    DESIRE_LANE_CHANGE_RIGHT,
    DESIRE_NONE,
    PassiveLaneChangeDesire,
    SerialLineBuffer,
    can_status_is_fresh,
    can_status_label,
    executable_path,
    measured_frame_rate,
    parse_compact_can_line,
    transmission_text,
    turn_signal_sides,
    turn_signal_text,
)


def test_parse_compact_can_line_accepts_real_gateway_format() -> None:
    frame = parse_compact_can_line("F,1E240,2A,38D,20,00000000AF017600")

    assert frame is not None
    assert frame.timestamp_us == 0x1E240
    assert frame.sequence == 0x2A
    assert frame.address == 0x38D
    assert frame.flags == 0x20
    assert frame.bus == "live"
    assert frame.data.hex() == "00000000af017600"


def test_parse_compact_can_line_rejects_control_and_malformed_lines() -> None:
    assert parse_compact_can_line('{"type":"hello"}') is None
    assert parse_compact_can_line("F,invalid") is None
    assert parse_compact_can_line("F,1,2,38D,0,not-hex") is None
    assert parse_compact_can_line("F,1,2,38D,20,0011") is None


def test_serial_line_buffer_handles_chunks_and_corrupt_fragments() -> None:
    buffer = SerialLineBuffer(max_line_bytes=16)

    assert buffer.feed(b"F,1,2") == []
    assert buffer.feed(b",3\nhello\r\n") == [b"F,1,2,3", b"hello"]
    assert buffer.feed(b"x" * 17) == []
    assert buffer.discarded_lines == 1
    assert buffer.feed(b"valid\n") == [b"valid"]


def test_can_status_rejects_stale_or_backlogged_data() -> None:
    assert can_status_is_fresh({"age_s": 0.02, "transport_lag_s": 0.03})
    assert can_status_label({"age_s": 0.02, "transport_lag_s": 0.03}) == "OK"
    assert not can_status_is_fresh({"age_s": 0.7, "transport_lag_s": 0.03})
    assert can_status_label({"age_s": 0.7, "transport_lag_s": 0.03}) == "PERDU"
    assert not can_status_is_fresh({"age_s": 0.02, "transport_lag_s": 1.2})
    assert can_status_label({"age_s": 0.02, "transport_lag_s": 1.2}) == "RETARD 1.2s"
    assert can_status_label({
        "age_s": 0.02,
        "transport_lag_s": 0.02,
        "gateway_dropped": 7,
    }) == "OK pertes=7"
    assert can_status_label({"type": "disabled"}) == "OFF"


def test_transmission_never_presents_target_as_engaged_gear() -> None:
    assert transmission_text({"speed_kph": 30, "current_gear": 4, "target_gear": 5}) == "D4"
    assert transmission_text({"speed_kph": 30, "current_gear": 0, "target_gear": 5}) == "cible 5"
    assert transmission_text({"reverse": True, "target_gear": 5}) == "R"


def test_backend_python_path_keeps_virtualenv_symlink(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    venv_python = Path("backend/.venv/bin/python")

    assert executable_path(venv_python) == tmp_path / venv_python
    assert executable_path(tmp_path / venv_python) == tmp_path / venv_python


def test_measured_frame_rate_uses_capture_timestamps() -> None:
    assert measured_frame_rate(121, 1_000_000, 11_000_000) == 12.0


def test_turn_signal_mapping_matches_validated_0x452_values() -> None:
    assert turn_signal_sides(0) == (False, False)
    assert turn_signal_sides(1) == (False, True)
    assert turn_signal_sides(2) == (True, False)
    assert turn_signal_sides(3) == (True, True)
    assert turn_signal_text(1) == "DROITE"
    assert turn_signal_text(2) == "GAUCHE"
    assert turn_signal_text(3) == "WARNING"


def test_passive_lane_change_requires_speed_and_driver_torque() -> None:
    helper = PassiveLaneChangeDesire()

    assert helper.update({"turn_signal": 2, "speed_kph": 20, "driver_torque_raw": 20}) == DESIRE_NONE
    # Release and re-apply above the official 20 mph threshold.
    assert helper.update({"turn_signal": 0, "speed_kph": 40, "driver_torque_raw": 0}) == DESIRE_NONE
    assert helper.update({"turn_signal": 2, "speed_kph": 40, "driver_torque_raw": 0}) == DESIRE_NONE
    assert helper.phase == "waiting_torque"
    assert helper.update({"turn_signal": 2, "speed_kph": 40, "driver_torque_raw": 6}) == DESIRE_LANE_CHANGE_LEFT
    assert helper.phase == "active"
    # Once triggered, neutral torque does not create another rising edge.
    assert helper.update({"turn_signal": 2, "speed_kph": 40, "driver_torque_raw": 0}) == DESIRE_LANE_CHANGE_LEFT
    assert helper.update({"turn_signal": 0, "speed_kph": 40, "driver_torque_raw": 0}) == DESIRE_NONE


def test_passive_lane_change_right_and_hazard_mapping() -> None:
    helper = PassiveLaneChangeDesire()

    assert helper.update({"turn_signal": 1, "speed_kph": 80, "driver_torque_raw": 0}) == DESIRE_NONE
    assert helper.update({"turn_signal": 1, "speed_kph": 80, "driver_torque_raw": -6}) == DESIRE_LANE_CHANGE_RIGHT
    assert helper.update({"turn_signal": 3, "speed_kph": 80, "driver_torque_raw": -20}) == DESIRE_NONE
    assert helper.snapshot(DESIRE_NONE)["blindspot_available"] is False


def test_passive_lane_change_can_be_disabled() -> None:
    helper = PassiveLaneChangeDesire(enabled=False)

    assert helper.update({"turn_signal": 2, "speed_kph": 90, "driver_torque_raw": 30}) == DESIRE_NONE
    assert helper.phase == "off"
