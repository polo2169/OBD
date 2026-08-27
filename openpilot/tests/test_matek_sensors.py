import math
import struct

from tools.record_matek_sensors import (
    MspV1Parser,
    decode_attitude,
    decode_raw_gps,
    decode_raw_imu,
    encode_msp_v1_request,
)


def response(command: int, payload: bytes) -> bytes:
    checksum = len(payload) ^ command
    for value in payload:
        checksum ^= value
    return b"$M>" + bytes((len(payload), command)) + payload + bytes((checksum,))


def test_msp_request_and_fragmented_response_checksum() -> None:
    assert encode_msp_v1_request(102) == b"$M<\x00ff"
    parser = MspV1Parser()
    encoded = response(108, struct.pack("<hhh", -125, 33, 271))

    assert parser.feed(b"garbage" + encoded[:4]) == []
    frames = parser.feed(encoded[4:])

    assert len(frames) == 1
    assert frames[0].command == 108
    assert frames[0].payload == struct.pack("<hhh", -125, 33, 271)


def test_decode_betaflight_imu_and_flat_mount_rotation() -> None:
    payload = struct.pack("<9h", 2048, -1024, 2048, 10, -20, 30, 1, 2, 3)

    record = decode_raw_imu(
        payload,
        fc_variant="BTFL",
        mounting_yaw_deg=90,
    )

    assert math.isclose(record["acceleration_x_ms2"], 9.80665)
    assert math.isclose(record["acceleration_y_ms2"], -4.903325)
    assert math.isclose(record["acceleration_forward_ms2"], 4.903325)
    assert math.isclose(record["acceleration_right_ms2"], 9.80665)
    assert record["roll_rate_deg_s"] == 20.0
    assert record["pitch_rate_deg_s"] == 10.0
    assert record["yaw_rate_right_deg_s"] == 30.0


def test_decode_inav_imu_uses_normalized_acceleration_scale() -> None:
    payload = struct.pack("<9h", 0, 0, 512, 0, 0, -15, 0, 0, 0)

    record = decode_raw_imu(payload, fc_variant="INAV", mounting_yaw_deg=0)

    assert math.isclose(record["acceleration_z_ms2"], 9.80665)
    assert record["accel_lsb_per_g"] == 512.0
    assert record["yaw_rate_right_deg_s"] == -15.0


def test_decode_gps_preserves_signed_coordinates_and_physical_units() -> None:
    payload = struct.pack(
        "<BBiiHHHH",
        2,
        14,
        488566000,
        23522000,
        132,
        1543,
        847,
        125,
    )

    record = decode_raw_gps(payload)

    assert record["fix_valid"] is True
    assert record["satellites"] == 14
    assert record["latitude_deg"] == 48.8566
    assert record["longitude_deg"] == 2.3522
    assert record["speed_mps"] == 15.43
    assert record["course_deg"] == 84.7
    assert record["pdop"] == 1.25


def test_decode_attitude_applies_mount_yaw_to_roll_and_pitch() -> None:
    record = decode_attitude(struct.pack("<hhh", 100, -50, -10), 180)

    assert record["roll_deg"] == -10.0
    assert record["pitch_deg"] == 5.0
    assert record["heading_deg"] == 350.0
