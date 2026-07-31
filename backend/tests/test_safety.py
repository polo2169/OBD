from app.safety import authorize_obd, authorize_uds


def test_read_did_allowed():
    assert authorize_uds(b"\x22\xF1\x90", True).allowed


def test_security_access_blocked():
    result = authorize_uds(b"\x27\x01", True)
    assert not result.allowed


def test_write_did_blocked():
    result = authorize_uds(b"\x2E\xF1\x90", True)
    assert not result.allowed


def test_programming_session_blocked_in_read_only_mode():
    result = authorize_uds(b"\x10\x02", True)
    assert not result.allowed


def test_extended_diagnostic_session_allowed_in_read_only_mode():
    assert authorize_uds(b"\x10\x03", True).allowed


def test_dtc_clear_requires_explicit_maintenance_mode():
    assert not authorize_uds(bytes.fromhex("14FFFFFF"), False).allowed
    assert authorize_uds(bytes.fromhex("14FFFFFF"), False, maintenance=True).allowed
    assert not authorize_uds(bytes.fromhex("14FFFF"), False, maintenance=True).allowed


def test_sensor_mode_only_allows_reading_obd_pids():
    assert authorize_obd(bytes.fromhex("010C")).allowed
    assert not authorize_obd(bytes.fromhex("0400")).allowed
