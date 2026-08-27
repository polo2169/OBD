from tools.record_esp32_sensors import parse_line


def test_parse_rmc_speed_and_position() -> None:
    record = parse_line(
        "GPS,123456,9600,$GNRMC,123519,A,4807.038,N,01131.000,E,10.0,84.4,230394,,,A*00",
        1_000_000,
        2_000_000,
    )
    assert record["sentence_type"] == "RMC"
    assert record["fix_valid"] is True
    assert record["latitude_deg"] == 48.1173
    assert record["longitude_deg"] == 11.516666666666667
    assert record["speed_mps"] == 5.1444
    assert record["course_deg"] == 84.4


def test_parse_status_without_fix_or_adxl() -> None:
    record = parse_line("STAT,1000,9600,8,0,725,0,1", 1, 2)
    assert record["valid_nmea"] == 8
    assert record["gps_age_ms"] == 725
    assert record["adxl345_present"] is False
    assert record["magnetometer_present"] is True


def test_parse_imu_preserves_signed_raw_axes() -> None:
    record = parse_line("IMU,999,-12,34,256", 1, 2)
    assert (record["raw_x"], record["raw_y"], record["raw_z"]) == (-12, 34, 256)
    assert record["scale_g_per_lsb"] == 0.0039
