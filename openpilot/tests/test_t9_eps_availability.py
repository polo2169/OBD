import pytest
from tools.audit_t9_eps_availability import (
    AvailabilityAudit,
    Frame,
    audit_capture,
    parse_compact,
    speed_checksum_valid,
)


def speed_frame(ts=100_000, kph=51):
    data = bytearray.fromhex("0000000000000000")
    data[:2] = round(kph * 100).to_bytes(2, "big")
    data[5] = (7 - sum((byte >> 4) + (byte & 15) for byte in data)) & 15
    return Frame(ts, 0x38D, 0x20, bytes(data))


def eps_frame(ts, state, flags=0x10):
    return Frame(ts, 0x495, flags, bytes([0, 0, state << 2, 0]))


@pytest.mark.parametrize("line", [b"F,10,0,495,20,00000000", b"F,10,0,495,10,0000000Z", b"F,-1,0,495,10,00000000", b"F,10,0,8495,10,00000000", b"F,10,0,495,110,00000000", b"F,10,0,495,10,0000\xff0000"])
def test_corrupted_records_are_rejected(line):
    with pytest.raises(ValueError):
        parse_compact(line)


def test_known_speed_checksum_vector_and_corruption():
    # Firmware test vector padded with two zero bytes to the real capture DLC.
    assert speed_checksum_valid(bytes.fromhex("1388000000030000"))
    assert not speed_checksum_valid(bytes.fromhex("1389000000030000"))


def test_context_preserves_signed_driver_angle_and_brake():
    audit = AvailabilityAudit()
    audit.observe(speed_frame())
    audit.observe(Frame(100_000, 0x2F5, 0x1C, bytes.fromhex("00F90000000000")))
    audit.observe(Frame(100_000, 0x305, 0x1C, bytes.fromhex("FF9C0580000000")))
    audit.observe(Frame(100_000, 0x412, 0x20, bytes.fromhex("2000000000000000")))
    audit.observe(eps_frame(110_000, 2))
    audit.observe(eps_frame(210_000, 0))
    row = audit.transitions[0]
    assert row["driver_torque_raw"] == -7
    assert row["angle_deg"] == -10
    assert row["steering_rate_deg_s"] == -5
    assert row["brake_pressed"] is True
    assert row["speed_kph"] == 51


@pytest.mark.parametrize("flags", [0x50, 0x11, 0x12])
def test_diagnostic_extended_and_remote_frames_do_not_change_live_state(flags):
    audit = AvailabilityAudit()
    audit.observe(speed_frame())
    audit.observe(eps_frame(110_000, 2))
    audit.observe(eps_frame(120_000, 0, flags))
    audit.observe(eps_frame(130_000, 2))
    assert audit.transitions == []


def test_stale_speed_does_not_create_a_false_transition():
    audit = AvailabilityAudit()
    audit.observe(speed_frame())
    audit.observe(eps_frame(110_000, 2))
    audit.observe(eps_frame(400_000, 0))
    audit.observe(speed_frame(410_000))
    audit.observe(eps_frame(420_000, 0))
    assert audit.transitions == []
    assert audit.counters["eps_without_fresh_speed"] == 1


def test_corrupt_speed_invalidates_the_previously_valid_sample():
    audit = AvailabilityAudit()
    audit.observe(speed_frame())
    audit.observe(eps_frame(110_000, 2))
    bad = bytearray(speed_frame().data)
    bad[5] ^= 1
    audit.observe(Frame(120_000, 0x38D, 0x20, bytes(bad)))
    audit.observe(eps_frame(130_000, 0))
    assert audit.transitions == []
    assert audit.counters["invalid_speed"] == 1


def test_timestamp_reset_clears_all_context():
    audit = AvailabilityAudit()
    audit.observe(speed_frame())
    audit.observe(eps_frame(110_000, 2))
    audit.observe(eps_frame(100, 0))
    assert audit.context(100)["speed_kph"] is None
    assert audit.transitions == []


def test_missing_context_is_unknown_rather_than_zero_or_released():
    audit = AvailabilityAudit()
    audit.observe(speed_frame())
    audit.observe(eps_frame(110_000, 2))
    audit.observe(eps_frame(210_000, 0))
    row = audit.transitions[0]
    assert row["angle_deg"] is None
    assert row["driver_torque_raw"] is None
    assert row["brake_pressed"] is None


def test_wrong_dlc_invalidates_cached_speed():
    audit = AvailabilityAudit()
    audit.observe(speed_frame())
    audit.observe(Frame(110_000, 0x38D, 0x1C, bytes(7)))
    audit.observe(eps_frame(120_000, 0))
    assert audit.counters["eps_without_fresh_speed"] == 1


def test_stationary_requires_fresh_zero_speed_at_each_wheel():
    audit = AvailabilityAudit()
    audit.observe(speed_frame(kph=0))
    audit.observe(eps_frame(110_000, 0))
    assert audit.counters["eps_stationary_confirmed_by_four_wheels"] == 0
    audit.observe(Frame(120_000, 0x30D, 0x20, bytes(8)))
    audit.observe(eps_frame(130_000, 0))
    assert audit.counters["eps_stationary_confirmed_by_four_wheels"] == 1
    audit.observe(Frame(140_000, 0x30D, 0x20, bytes.fromhex("0000000000000064")))
    audit.observe(eps_frame(150_000, 0))
    assert audit.counters["eps_stationary_confirmed_by_four_wheels"] == 1


def test_file_audit_clears_corrupt_lines_and_keeps_content_hash(tmp_path):
    path = tmp_path / "can.jsonl"
    speed = speed_frame().data.hex()
    path.write_bytes(f"F,186A0,0,38D,20,{speed}\nF,1ADB0,1,495,10,00000800\n".encode() +
                     b"F,broken\nF,1D4C0,2,495,10,00000000\n")
    report = audit_capture(path)
    assert len(report["sha256"]) == 64
    assert report["counters"]["malformed_compact_lines"] == 1
    assert report["transitions"] == []
