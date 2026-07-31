from app.safety import authorize_diagnostic_can_frame, authorize_obd, authorize_uds


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


def test_read_memory_services_are_blocked_even_though_they_do_not_write():
    assert not authorize_uds(b"\x23\x00", True).allowed
    assert not authorize_uds(b"\x24\x00", True).allowed


def test_dtc_clear_requires_explicit_maintenance_mode():
    assert not authorize_uds(bytes.fromhex("14FFFFFF"), False).allowed
    assert authorize_uds(bytes.fromhex("14FFFFFF"), False, maintenance=True).allowed
    assert not authorize_uds(bytes.fromhex("14FFFF"), False, maintenance=True).allowed


def test_sensor_mode_only_allows_reading_obd_pids():
    assert authorize_obd(bytes.fromhex("010C")).allowed
    assert not authorize_obd(bytes.fromhex("0400")).allowed


def test_can_policy_allows_read_did_and_flow_control():
    assert authorize_diagnostic_can_frame(0x74A, False, bytes.fromhex("0322F19000000000")).allowed
    assert authorize_diagnostic_can_frame(0x74A, False, bytes.fromhex("3008000000000000")).allowed


def test_can_policy_blocks_write_clear_security_and_unknown_ids():
    for data in ("042E123400000000", "0414FFFFFF000000", "0227010000000000"):
        assert not authorize_diagnostic_can_frame(0x752, False, bytes.fromhex(data)).allowed
    assert not authorize_diagnostic_can_frame(0x123, False, bytes.fromhex("0322F19000000000")).allowed


def test_can_policy_blocks_fragmented_requests_and_obd_clear():
    assert not authorize_diagnostic_can_frame(0x752, False, bytes.fromhex("10092E123456789A")).allowed
    assert not authorize_diagnostic_can_frame(0x7E0, False, bytes.fromhex("0104000000000000")).allowed
